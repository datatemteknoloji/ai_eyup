"""G: referans paketleri — (i) metinleri, ref.feed.stale + alias/migrasyon, resmi kaynak allowlist,
sağlama toplamı + üretim tarihi, paket yokluğunda bulguların KORUNMASI."""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.infra_finding import InfraFinding
from app.services import method_registry as mr
from app.services import reference_sources as rsrc
from app.services import virt_reference_checks as vrc
from app.services.findings import store
from app.services.findings.registry import category_of
from app.services.findings.schema_ensure import migrate_check_aliases
from app.tests.isolated_db import isolated_db  # noqa: F401

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
COL = {
    "about": {"version": "8.0.2", "build": "100", "fullName": "vCenter"},
    "hosts": [{"ref": "h1", "name": "esx1", "cluster": "C1",
               "config": {"version": "8.0.2", "build": "100", "vendor": "Dell Inc.", "model": "R640"}}],
    "hcl": {},
}


def _cve(affected=">=8.0,<8.0.3", extra=None, gen_days=1, **meta):
    d = {
        "source": "test", "version": "2026.10", "generated_at": (NOW - timedelta(days=gen_days)).date().isoformat(),
        "advisories": [{
            "id": "VMSA-T-1", "cve": ["CVE-T"], "severity": "critical", "title": "t",
            "source_url": "https://www.broadcom.com/support/vmware-security-advisories",
            "products": [{"product": "esxi", "affected": [affected], "fixed": "8.0.3"}],
        }],
    }
    d.update(meta)
    if extra:
        d["advisories"][0].update(extra)
    return d


def _matrix(gen_days=1):
    return {"source": "m", "version": "m1", "generated_at": (NOW - timedelta(days=gen_days)).date().isoformat(),
            "products": {"esxi": {"target": "8.0.3", "eol": [{"version": "8.0", "eol_date": "2026-11-01"}], "paths": []}}}


@pytest.fixture()
def db(isolated_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(vrc, "_event_text", lambda *a, **k: [])
    return isolated_db


def _run(db, now=NOW):
    st = vrc.persist_reference_findings(db, platform="vmware", source_id=1, source_name="vc", col=COL, now=now)
    db.commit()
    return st


def _active(db, prefix):
    return [r for r in db.query(InfraFinding).filter(InfraFinding.active.is_(True)).all()
            if r.check_id.startswith(prefix)]


# ── G.1 (i) metinleri ────────────────────────────────────────────────────────

def test_per_pack_method_texts_registered():
    for kind in vrc.KINDS:
        m = mr.resolve(f"ref.pack.{kind}")
        assert m is not None and m.id == f"ref.pack.{kind}"
        assert m.method_tr and m.source_tr and m.limits_tr and m.method_en and m.limits_en


# ── G.2 ref.feed.stale + alias + migrasyon ───────────────────────────────────

def test_old_feed_stale_id_is_alias_not_a_registry_id():
    assert "upg:feed_stale" not in mr.ids() and "ref.feed.stale" in mr.ids()
    assert mr.resolve("upg:feed_stale").id == "ref.feed.stale"
    assert mr.catalog()["aliases"]["upg:feed_stale"] == "ref.feed.stale"
    assert category_of("ref.feed.stale") == "upgrade"
    assert category_of("ref.vuln.unassessed") == "vuln" and category_of("ref.kb.unassessed") == "known_issue"


def test_migration_renames_existing_rows_and_keeps_conflicts(db):
    def mk(check_id, ref):
        db.add(InfraFinding(platform="vmware", source_id=1, check_id=check_id, entity_ref=ref, entity_name=ref, title="t",
                            category="upgrade", entity_kind="cluster", result="fail", severity="medium", active=True))
    mk("upg:feed_stale", "feed:cve_feed")
    mk("upg:feed_stale", "feed:kb_feed")
    mk("ref.feed.stale", "feed:kb_feed")  # çakışan anahtar: eski satır dokunulmadan kalır (silme yok)
    db.commit()
    eng = db.get_bind()
    assert migrate_check_aliases(eng) == 1
    assert migrate_check_aliases(eng) == 0  # idempotent
    db.expire_all()
    ids = sorted((r.entity_ref, r.check_id) for r in db.query(InfraFinding).all())
    assert ids == [("feed:cve_feed", "ref.feed.stale"), ("feed:kb_feed", "ref.feed.stale"),
                   ("feed:kb_feed", "upg:feed_stale")]
    # eski kimlikle sorgu → yeni kimlikli satır da döner
    rows = store.query_findings(db, check_id="upg:feed_stale", result="all")
    assert {r["check_id"] for r in rows} >= {"ref.feed.stale"}


def test_feed_age_uses_generation_date_not_upload_time(db):
    # bugün yüklenen ama 45 gün önce üretilmiş paket "güncel değil"
    vrc.save_package(db, "cve_feed", _cve(gen_days=45), user="u", now=NOW)
    drafts = {d.entity_name: d for d in vrc.feed_age_findings(db, now=NOW)}
    d = drafts["cve_feed"]
    assert d.check_id == "ref.feed.stale" and d.result == "fail"
    assert d.evidence["age_basis"] == "generated_at" and 44 < d.evidence["age_days"] < 46
    # taze paket geçer; yüklü olmayanlar ölçülemedi (asla pass değil)
    vrc.save_package(db, "cve_feed", _cve(gen_days=2), user="u", now=NOW)
    drafts = {d.entity_name: d for d in vrc.feed_age_findings(db, now=NOW)}
    assert drafts["cve_feed"].result == "pass"
    assert drafts["kb_feed"].result == "not_measurable" and drafts["upgrade_matrix"].result == "not_measurable"


def test_legacy_row_without_generated_at_falls_back_to_upload_time(db):
    from app.models.infra_finding import InfraReferenceData
    db.add(InfraReferenceData(kind="kb_feed", payload={"articles": []}, item_count=0, source_label="x",
                              uploaded_by="u", uploaded_at=NOW - timedelta(days=40)))
    db.commit()
    d = {x.entity_name: x for x in vrc.feed_age_findings(db, now=NOW)}["kb_feed"]
    assert d.result == "fail" and d.evidence["age_basis"] == "uploaded_at"


# ── G.3 resmi kaynak allowlist ───────────────────────────────────────────────

def test_reference_sources_file_is_well_formed_and_only_official_domains():
    data = json.load(open(rsrc._PATH, encoding="utf-8"))
    assert set(data["allowed_domains"]) == {"broadcom.com", "vmware.com", "redhat.com", "oracle.com", "nist.gov", "cve.org"}
    shown = rsrc.verified_sources()
    assert shown and all(rsrc.check_source_url(s["url"])[0] for s in shown)
    hidden = {s["id"] for s in rsrc.unverified_sources()}
    assert {"broadcom_kb", "ocp_update_graph"} <= hidden
    assert not ({s["id"] for s in shown} & hidden)
    for s in data["sources"]:
        assert s["verified_on"], s["id"]  # her bağlantının doğrulama tarihi var


@pytest.mark.parametrize("url,ok", [
    ("https://www.broadcom.com/support/vmware-security-advisories", True),
    ("https://access.redhat.com/security/security-updates", True),
    ("https://nvd.nist.gov/vuln/detail/CVE-2024-1", True),
    ("", True), (None, True),
    ("http://www.broadcom.com/x", False),
    ("https://evil.example.com/broadcom.com", False),
    ("https://broadcom.com.evil.io/x", False),
    ("https://user:pw@www.broadcom.com/x", False),
    ("https://support.broadcom.com/...", False),
    ("ftp://broadcom.com/x", False),
])
def test_check_source_url(url, ok):
    assert rsrc.check_source_url(url)[0] is ok


def test_import_rejects_non_allowlisted_links_and_lists_offenders(db):
    p = _cve()
    p["advisories"] = [dict(p["advisories"][0], id=f"V-{i}", source_url="https://evil.example.com/x") for i in range(7)]
    with pytest.raises(ValueError) as ei:
        vrc.save_package(db, "cve_feed", p, user="u", now=NOW)
    msg = str(ei.value)
    assert "7 kayıt reddedildi" in msg and "V-0" in msg and "V-4" in msg and "V-6" not in msg  # en çok 5 örnek
    assert db.query(vrc.InfraReferenceData).count() == 0  # paket yüklenmedi
    # eski `url` alanı da aynı kurala tabi
    q = _cve(); q["advisories"][0].pop("source_url"); q["advisories"][0]["url"] = "http://x.example.org/y"
    with pytest.raises(ValueError):
        vrc.save_package(db, "cve_feed", q, user="u", now=NOW)


def test_findings_never_carry_unlisted_links(db):
    p = _cve(); p["advisories"][0].pop("source_url")
    vrc.save_package(db, "cve_feed", p, user="u", now=NOW)
    d = vrc.vuln_findings(db, "vmware", COL)[0]
    assert d.evidence["source_url"] is None  # URL uydurulmaz
    vrc.save_package(db, "cve_feed", _cve(), user="u", now=NOW)
    assert vrc.vuln_findings(db, "vmware", COL)[0].evidence["source_url"].startswith("https://www.broadcom.com/")
    # eski satırdaki izinsiz bağlantı gösterimde gizlenir
    ev = store._safe_evidence({"url": "https://support.broadcom.com/...", "x": 1})
    assert ev["url"] is None and ev["url_hidden"] is True and ev["x"] == 1


def test_samples_have_no_invented_links_and_are_importable(db):
    from app.services.virt_reference_samples import sample_with_meta
    for kind in vrc.KINDS:
        s = sample_with_meta(kind)
        assert not rsrc.offenders(vrc._records(kind, s))
        assert not any(r.get("url") or r.get("source_url") for r in vrc._records(kind, s))
        vrc.save_package(db, kind, s, user="u")
    assert all(p["integrity"] == "verified" for p in vrc.package_status(db))


# ── G.4 üretim tarihi + sağlama toplamı ─────────────────────────────────────

def test_generated_at_is_required_and_future_rejected(db):
    p = _cve(); p.pop("generated_at")
    with pytest.raises(ValueError, match="generated_at"):
        vrc.save_package(db, "cve_feed", p, user="u", now=NOW)
    with pytest.raises(ValueError, match="gelecekte"):
        vrc.save_package(db, "cve_feed", _cve(generated_at="2027-01-01"), user="u", now=NOW)
    with pytest.raises(ValueError, match="generated_at"):
        vrc.save_package(db, "cve_feed", _cve(generated_at="dün"), user="u", now=NOW)


def test_checksum_verified_mismatch_rejected_and_absent_flagged(db):
    p = _cve()
    r = vrc.save_package(db, "cve_feed", p, user="u", now=NOW)
    assert r["integrity"] == "computed_only" and len(r["sha256"]) == 64
    good = dict(p, sha256=vrc.compute_checksum(p))
    assert vrc.save_package(db, "cve_feed", good, user="u", now=NOW)["integrity"] == "verified"
    tampered = copy.deepcopy(good)
    tampered["advisories"][0]["cvss"] = 1.0
    with pytest.raises(ValueError, match="bütünlük"):
        vrc.save_package(db, "cve_feed", tampered, user="u", now=NOW)
    with pytest.raises(ValueError, match="sha256"):
        vrc.save_package(db, "cve_feed", dict(p, sha256="zz"), user="u", now=NOW)
    # sha256 alanı hesaplamaya dahil değil (kendini içeremez); anahtar sırası etkisiz
    assert vrc.compute_checksum(good) == vrc.compute_checksum(dict(reversed(list(p.items()))))


def test_package_status_reports_state_age_and_sources(db):
    vrc.save_package(db, "cve_feed", _cve(gen_days=45), user="u", now=NOW)
    vrc.save_package(db, "kb_feed", {"source": "k", "generated_at": NOW.date().isoformat(), "articles": []}, user="u", now=NOW)
    st = {p["kind"]: p for p in vrc.package_status(db, now=NOW)}
    assert st["cve_feed"]["state"] == "stale" and st["cve_feed"]["age_basis"] == "generated_at"
    assert st["kb_feed"]["state"] == "ok" and st["upgrade_matrix"]["state"] == "missing"
    assert st["cve_feed"]["sources"] and all(s["url"].startswith("https://") for s in st["cve_feed"]["sources"])


# ── G.4 paket yokluğu hiçbir bulguyu kapatmaz ────────────────────────────────

def _kb():
    return {"source": "k", "generated_at": NOW.date().isoformat(), "articles": [
        {"id": "KB-1", "title": "kb", "products": [{"product": "esxi", "affected": [">=8.0,<8.0.3"]}]}]}


def _fails(db, prefix):
    return [r for r in db.query(InfraFinding).filter(InfraFinding.active.is_(True), InfraFinding.result == "fail").all()
            if r.check_id.startswith(prefix)]


def test_package_deletion_never_drops_open_vuln_kb_and_upgrade_counts(db):
    vrc.save_package(db, "cve_feed", _cve(), user="u", now=NOW)
    vrc.save_package(db, "kb_feed", _kb(), user="u", now=NOW)
    vrc.save_package(db, "upgrade_matrix", _matrix(), user="u", now=NOW)
    _run(db)
    before = store.summarize_findings(db)["by_category"]
    assert before["vuln"]["total"] == 1 and before["known_issue"]["total"] == 1 and before["upgrade"]["total"] == 2
    assert all(not r.stale for r in _fails(db, "vuln:") + _fails(db, "kb:") + _fails(db, "upg:"))

    for kind in vrc.KINDS:
        assert vrc.delete_package(db, kind) is True
    db.commit()
    st = _run(db, now=NOW + timedelta(days=1))
    assert st["vuln_stale_marked"] == 1 and st["known_issue_stale_marked"] == 1 and st["upgrade_stale_marked"] == 2

    after = store.summarize_findings(db)
    # açık sayılar DÜŞMEZ: paket yokluğu hiçbir bulguyu kapatmadı
    for cat in ("vuln", "known_issue", "upgrade"):
        assert after["by_category"][cat]["total"] == before[cat]["total"], cat
    assert after["unverifiable"] == 4  # 1 + 1 + 2 "doğrulanamayan" olarak ayrıca sayılır
    for r in _fails(db, "vuln:") + _fails(db, "kb:") + _fails(db, "upg:eol") + _fails(db, "upg:target"):
        assert r.active and r.stale and r.resolved_at is None
        assert r.evidence["stale_kind"] == "ref_pack_missing"
        assert r.evidence["stale_note"].startswith("Son bilinen durum: paket ")
        assert r.evidence["stale_note"].endswith("şu an doğrulanamıyor")
        if r.check_id.startswith("vuln:"):  # sürümü olan paket: "paket vX (tarih)"
            assert r.evidence["stale_note"] == "Son bilinen durum: paket v2026.10 (2026-10-12) ile tespit edildi, şu an doğrulanamıyor"
    # yeni koşuda yazılan şey "ölçülemedi"dir — asla pass değil
    nm = {r.check_id: r.result for r in _active(db, "ref.")}
    assert nm["ref.vuln.unassessed"] == nm["ref.kb.unassessed"] == nm["ref.upgrade.unassessed"] == "not_measurable"
    assert not any(r.result == "pass" for r in _active(db, "ref."))
    api = [store.finding_to_dict(r) for r in _fails(db, "vuln:")][0]
    assert api["stale"] is True and api["stale_note"].startswith("Son bilinen durum")


def test_stale_findings_close_only_when_reevaluated_with_new_package_and_passing(db):
    vrc.save_package(db, "cve_feed", _cve(), user="u", now=NOW)
    _run(db)
    vrc.delete_package(db, "cve_feed"); db.commit()
    _run(db, now=NOW + timedelta(days=2))
    _run(db, now=NOW + timedelta(days=3))  # tekrar eden boş koşu da kapatmaz
    assert len(_fails(db, "vuln:")) == 1 and _fails(db, "vuln:")[0].stale
    # yeni paket, hâlâ etkileniyor → yeniden değerlendirildi: bayrak/etiket temizlenir, fail sürer
    vrc.save_package(db, "cve_feed", _cve(), user="u", now=NOW + timedelta(days=3))
    _run(db, now=NOW + timedelta(days=3))
    r = _fails(db, "vuln:")[0]
    assert not r.stale and "stale_note" not in (r.evidence or {})
    assert not _active(db, "ref.vuln.unassessed")  # paket yüklenince "ölçülemedi" kaydı kapanır
    # yeni paket: artık etkilenmiyor (düzeltilmiş sürüm aralığı) → pass; yalnız burada kapanır
    vrc.save_package(db, "cve_feed", _cve(affected=">=7.0,<8.0.0"), user="u", now=NOW + timedelta(days=4))
    _run(db, now=NOW + timedelta(days=4))
    assert not _fails(db, "vuln:")
    assert any(r.result == "pass" and r.check_id.startswith("vuln:") for r in _active(db, "vuln:"))


def test_feed_stale_row_survives_pack_deletion_as_not_measurable_not_closed(db):
    vrc.save_package(db, "cve_feed", _cve(gen_days=45), user="u", now=NOW)
    _run(db)
    assert [r.result for r in _active(db, "ref.feed.stale") if r.entity_ref == "feed:cve_feed"] == ["fail"]
    vrc.delete_package(db, "cve_feed"); db.commit()
    _run(db, now=NOW + timedelta(days=1))
    row = [r for r in _active(db, "ref.feed.stale") if r.entity_ref == "feed:cve_feed"]
    assert len(row) == 1 and row[0].result == "not_measurable"  # kapanmadı, ölçülemedi


def test_missing_pack_alone_never_writes_pass(db):
    _run(db)
    assert {r.result for r in db.query(InfraFinding).all()} == {"not_measurable"}
    assert store.summarize_findings(db)["unverifiable"] == 0
