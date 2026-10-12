"""F.0: DEMO yedek sağlayıcısı kapısı — varsayılan KAPALI, gerçek veriden izole, kanıt/rapor/skora girmez.

Hepsi İZOLE geçici DB'de çalışır (isolated_db.py); koşullu skip yok.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.services.backup import demo_gate, extras, rpo_engine as eng
from app.services.backup import sync as bsync
from app.services.backup.demo_gate import DEMO_CAPABILITY, DEMO_PLATFORM, ENV_FLAG
from app.services.backup.veeam_provider import VeeamDemoProvider
from app.services.capabilities import capabilities_payload, get_capabilities, invalidate_capabilities
from app.services.findings import store
from app.services.findings.registry import ISO_BACKUP, RESULT_FAIL
from app.tests.test_backup_dilim_d import _demo_vms, _make_instance, db  # noqa: F401  (fixture)


def _sync(db, monkeypatch, row, n=20):
    vms = _demo_vms(n)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    assert bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))["ok"]
    return vms


def _caps():
    invalidate_capabilities()
    return get_capabilities(force_refresh=True)


# ── bayrak KAPALI (üretim varsayılanı) ───────────────────────────────────────

def test_flag_default_is_off(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    assert demo_gate.demo_enabled() is False
    for v in ("", "0", "false", "no"):
        monkeypatch.setenv(ENV_FLAG, v)
        assert demo_gate.demo_enabled() is False
    for v in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv(ENV_FLAG, v)
        assert demo_gate.demo_enabled() is True


def test_flag_off_demo_row_is_inert(db, monkeypatch):
    # satır (dev DB'deki 169 gibi) duruyor ve "enabled" ama bayrak kapalı → etkisiz
    vms = _demo_vms(10)
    row = _make_instance(db, kind="veeam_demo")
    _sync(db, monkeypatch, row, 10)                   # bayrak açıkken veri geldi (dev geçmişi)
    monkeypatch.delenv(ENV_FLAG)
    caps = _caps()
    assert "backup" not in caps and DEMO_CAPABILITY not in caps
    p = capabilities_payload()
    assert p["has_backup"] is False and p["demo_active"] is False and p["demo_banner"] is None
    assert demo_gate.backup_mode(db) == "none"
    assert eng.backup_instances(db, include_demo=True) == []
    assert eng.vm_protection(db, vms=vms, include_demo=True) == []
    assert eng.backup_findings(db, vms=vms) == []
    assert extras.extra_findings(db) == []
    # senkron (force dahil) üretmez ve satıra dokunmaz
    before = (row.last_sync_at, row.last_status)
    r = bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))
    assert r["ok"] is False and r["skipped"] == "demo_disabled" and "BACKUP_DEMO_ENABLED" in r["error"]
    assert (row.last_sync_at, row.last_status) == before
    assert bsync.run_all_due(db, force=True) == []
    assert bsync.has_enabled_backup_instance() is False
    # bulgu üretimi: önceki demo bulguları çözülür, yenisi yazılmaz
    out = eng.persist_backup_findings(db)
    assert out["capability"] is False and out["demo"] is False
    assert store.query_findings(db, platforms=["backup", DEMO_PLATFORM], result="all", include_demo=True) == []


def test_flag_off_api_rejects_demo(db, monkeypatch):
    from app.api import backup_integrations as api
    monkeypatch.delenv(ENV_FLAG, raising=False)
    body = api.InstanceBody(kind="veeam_demo", label="x")
    with pytest.raises(HTTPException) as e:
        api.create_instance(body, db=db, _u=None)
    assert e.value.status_code == 403
    row = _make_instance(db, kind="veeam_demo")
    row.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as e:
        api.enable_instance(row.id, api.EnableBody(enabled=True), db=db, _u=None)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        api.test_connection(api.TestBody(kind="veeam_demo"), db=db, _u=None)
    lst = api.list_instances(db=db, _u=None)
    assert lst["demo_enabled"] is False and all(k["kind"] != "veeam_demo" for k in lst["kinds"])
    assert lst["instances"][0]["demo_inactive"] is True
    monkeypatch.setenv(ENV_FLAG, "true")
    assert any(k["kind"] == "veeam_demo" for k in api.list_instances(db=db, _u=None)["kinds"])


# ── bayrak AÇIK, yalnız demo ─────────────────────────────────────────────────

def test_flag_on_demo_gets_view_capability_but_not_backup(db, monkeypatch):
    row = _make_instance(db, kind="veeam_demo")
    vms = _sync(db, monkeypatch, row)
    caps = _caps()
    assert DEMO_CAPABILITY in caps and "backup" not in caps
    p = capabilities_payload()
    assert p["demo_active"] is True and p["has_backup"] is False and "DEMO VERİ" in p["demo_banner"]
    # demo modunda iki sohbet aracı AÇIK (etiketli; bkz. test_demo_tools_are_labeled_*)
    from app.services.agent.tools import tool_specs_read_only
    names = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
    assert {"virt_backup_status", "virt_rpo_compliance"} <= names
    # varsayılan (gerçek-only) görünüm boş; Yedekleme ekranı include_demo ile görür
    assert eng.vm_protection(db, vms=vms) == []
    assert eng.vm_protection(db, vms=vms, include_demo=True)
    assert eng.summary(db)["providers"] == []
    s = eng.summary(db, include_demo=True)
    assert s["demo_active"] is True and s["providers"][0]["demo"] is True
    # zaman çizelgesi ve snapshot kararı demo'dan etkilenmez
    now = datetime.now(timezone.utc)
    assert extras.timeline_items(db, now - timedelta(days=2), now, {o for o in range(1, 2000)}) == []


def test_demo_findings_go_to_demo_platform_and_are_excluded_everywhere(db, monkeypatch):
    from app.services.virt_compliance import compliance_report, compliance_rows
    row = _make_instance(db, kind="veeam_demo")
    _sync(db, monkeypatch, row)
    monkeypatch.setattr(eng, "_vms", lambda _db: _demo_vms(20))
    out = eng.persist_backup_findings(db)
    assert out["demo"] is True and out["capability"] is False and out["demo_upserted"] > 0
    assert out["upserted"] == 0
    # varsayılan sorgular/özetler demo'yu GÖRMEZ
    plats = ["backup", DEMO_PLATFORM, "vmware"]
    assert store.query_findings(db, platforms=plats, result="all") == []
    assert store.query_findings(db, result="all") == []
    sm = store.summarize_findings(db)
    assert sm["by_category"] == {} and sm["passed"] == 0 and sm["not_measurable"] == 0
    assert store.summarize_findings(db, platforms=plats)["by_category"] == {}
    # yalnız açıkça istenirse (Yedekleme ekranı) görünür
    demo_rows = store.query_findings(db, platforms=[DEMO_PLATFORM], result="all", include_demo=True)
    assert demo_rows and {f["platform"] for f in demo_rows} == {DEMO_PLATFORM}
    assert any(f["result"] == RESULT_FAIL for f in demo_rows)
    assert any(ISO_BACKUP in (f.get("refs") or []) for f in demo_rows), "demo bulgusu A.8.13'e bağlı olurdu"
    # denetim kanıtı (CSV/JSON/PDF'nin kaynağı) ve rapor: A.8.13 satırı YOK
    rep = compliance_report(db, platforms=plats)
    assert all(c["control"] != ISO_BACKUP for c in rep["controls"])
    assert not [r for r in compliance_rows(rep) if "DEMO" in str(r) or r[0] == ISO_BACKUP and r[6] != "manual"]
    # Yedekleme ekranı bulgu listesi demo modunda demo platformunu okur
    from app.api import backup_insights
    lst = backup_insights.backup_findings_list(result="all", limit=500, db=db, _u=None)
    assert lst["count"] == len(demo_rows)
    # ISO A.8.13 kanıtı demo veriden ÜRETİLMEZ
    ev = extras.evidence(db)
    assert ev["blocked"] is True and ev["items"] == [] and ev["jobs"] == [] and "DEMO VERİ" in ev["blocked_reason"]
    assert backup_insights.backup_evidence(days=30, db=db, _u=None)["blocked"] is True


def test_demo_findings_resolved_when_flag_turned_off(db, monkeypatch):
    row = _make_instance(db, kind="veeam_demo")
    _sync(db, monkeypatch, row)
    monkeypatch.setattr(eng, "_vms", lambda _db: _demo_vms(20))
    assert eng.persist_backup_findings(db)["demo_upserted"] > 0
    assert store.query_findings(db, platforms=[DEMO_PLATFORM], result="all", include_demo=True)
    monkeypatch.delenv(ENV_FLAG)
    invalidate_capabilities()
    out = eng.persist_backup_findings(db)
    assert out["demo_resolved"] > 0
    assert store.query_findings(db, platforms=[DEMO_PLATFORM], result="all", include_demo=True) == []   # aktif yok


# ── gerçek + demo karışmaz ───────────────────────────────────────────────────

def test_real_provider_present_demo_is_ignored_and_never_mixes(db, monkeypatch):
    demo = _make_instance(db, kind="veeam_demo")
    vms = _sync(db, monkeypatch, demo)                 # demo VM'leri korunmuş görünüyor
    assert any(r["state"] == "protected" for r in eng.vm_protection(db, vms=vms, include_demo=True))
    real = _make_instance(db, kind="veeam_vbr")        # şimdi gerçek (henüz boş) sağlayıcı var
    caps = _caps()
    assert DEMO_CAPABILITY not in caps                  # demo yok sayılır; gerçek henüz senkronlanmadı
    assert demo_gate.backup_mode(db) == "real"
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    assert ids == [real.id]
    rows = eng.vm_protection(db, vms=vms, include_demo=True)
    assert rows and all(r["state"] != "protected" for r in rows), "demo koruması gerçek hesaba sızmamalı"
    assert eng.summary(db, include_demo=True)["protected"] == 0
    # gerçek mod bulguları platform=backup; demo satırı hiç bulgu üretmez
    monkeypatch.setattr(eng, "_vms", lambda _db: vms)
    real.last_status, real.last_sync_at = "ok", datetime.now(timezone.utc)
    db.commit()
    _caps()
    out = eng.persist_backup_findings(db)
    assert out["capability"] is True and out["demo"] is False and out["demo_upserted"] == 0
    assert store.query_findings(db, platforms=[DEMO_PLATFORM], result="all", include_demo=True) == []


def test_snapshot_guard_ignores_leftover_demo_sessions(db, monkeypatch):
    """DB'de kalmış demo oturumları, gerçek sağlayıcı varken snapshot kararını etkilemez."""
    from app.models.backup import BkJob, BkProtectedObject, BkSession
    from app.services.backup.snapshot_guard import check_snapshot_remove
    demo = _make_instance(db, kind="veeam_demo")
    _sync(db, monkeypatch, demo, 10)
    obj = db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == demo.id,
                                             BkProtectedObject.job_provider_id.isnot(None),
                                             BkProtectedObject.matched_vm_id.isnot(None)).first()
    job = db.query(BkJob).filter(BkJob.instance_id == demo.id, BkJob.provider_job_id == obj.job_provider_id).one()
    db.add(BkSession(job_id=job.id, provider_session_id="r1", started_at=datetime.now(timezone.utc),
                     ended_at=None, result="None"))
    db.commit()
    snaps = [{"name": "manual-before-patch"}]
    # demo-only (gerçek yok): capability 'backup' yok → oturum kontrolü hiç çalışmaz
    _caps()
    assert check_snapshot_remove(db, snapshots=snaps, vm_name=obj.name, matched_vm_id=obj.matched_vm_id)["ok"] is True
    # gerçek sağlayıcı geldi: demo oturumu yine sayılmaz
    real = _make_instance(db, kind="veeam_vbr")
    real.last_status, real.last_sync_at = "ok", datetime.now(timezone.utc)
    db.commit()
    _caps()
    assert check_snapshot_remove(db, snapshots=snaps, vm_name=obj.name, matched_vm_id=obj.matched_vm_id)["ok"] is True


def test_no_demo_kind_checks_outside_gate():
    """Dağınık `endswith("_demo")` kontrolü yok: kapı dışında demo kararı verilemez."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "services" / "backup"
    offenders = [p.name for p in root.glob("*.py")
                 if p.name not in ("demo_gate.py", "veeam_provider.py") and 'endswith("_demo")' in p.read_text()]
    assert offenders == [], offenders


# ── demo modunda sohbet araçları: açık + "DEMO veri" etiketi (yalnız bayrak açıkken) ──────────

def _tool_names():
    from app.services.agent.tools import tool_specs_read_only
    return {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}


def test_demo_tools_are_labeled_in_output_and_source_line(db, monkeypatch):
    from app.services.agent.tools import TOOLS
    from app.services.chat_evidence_badge import score_evidence_badge
    row = _make_instance(db, kind="veeam_demo")
    vms = _sync(db, monkeypatch, row)
    monkeypatch.setattr(eng, "_vms", lambda _db: vms)
    _caps()
    assert {"virt_backup_status", "virt_rpo_compliance"} <= _tool_names()
    for name, args in (("virt_backup_status", {"vm_name": "demo-vm-00"}), ("virt_rpo_compliance", {"filter": "unprotected"})):
        out = TOOLS[name].direct_handler(db, args, {})
        assert out["ok"] is True and out["demo"] is True and out["data_label"] == "DEMO veri"
        assert "DEMO VERİ" in out["note"] and "gerçek Veeam değil" in out["note"]
    out = TOOLS["virt_rpo_compliance"].direct_handler(db, {"filter": "unprotected"}, {})
    assert out["count"] > 0                      # demo verisi gerçekten okunuyor
    b = score_evidence_badge(kind="live", tools_used=["virt_rpo_compliance", "virt_health_overview"], has_tool_text=True)
    src = {s["tool"]: s for s in b["sources"]}
    assert src["virt_rpo_compliance"].get("demo") is True
    assert "demo" not in src["virt_health_overview"]


def test_demo_tools_closed_when_flag_off_and_unlabeled_with_real_provider(db, monkeypatch):
    from app.services.agent.tools import TOOLS
    from app.services.chat_evidence_badge import score_evidence_badge
    row = _make_instance(db, kind="veeam_demo")
    vms = _sync(db, monkeypatch, row)
    monkeypatch.setattr(eng, "_vms", lambda _db: vms)
    # bayrak kapalı → araçlar görünmez, handler çalışmaz
    monkeypatch.delenv(ENV_FLAG)
    _caps()
    assert not ({"virt_backup_status", "virt_rpo_compliance"} & _tool_names())
    out = TOOLS["virt_rpo_compliance"].direct_handler(db, {}, {})
    assert out["ok"] is False
    # bayrak açık ama GERÇEK sağlayıcı var → demo yok sayılır; araç gerçek veriyi etiketsiz döndürür
    monkeypatch.setenv(ENV_FLAG, "true")
    real = _make_instance(db, kind="veeam_vbr")
    real.last_status, real.last_sync_at = "ok", datetime.now(timezone.utc)
    db.commit()
    _caps()
    out = TOOLS["virt_rpo_compliance"].direct_handler(db, {}, {})
    assert out["ok"] is True and out["demo"] is False and "data_label" not in out
    b = score_evidence_badge(kind="live", tools_used=["virt_rpo_compliance"], has_tool_text=True)
    assert "demo" not in b["sources"][0]


# ── bayrak kapanınca çözülen demo bulguları: neden "demo_disabled", metriklerden dışlanır ─────

def test_demo_disabled_resolution_reason_and_metrics_exclusion(db, monkeypatch):
    from app.models.infra_finding import InfraFinding
    from app.services.findings.registry import RESOLVED_DEMO_DISABLED, RESOLVED_FIXED
    row = _make_instance(db, kind="veeam_demo")
    vms = _sync(db, monkeypatch, row)
    monkeypatch.setattr(eng, "_vms", lambda _db: vms)
    assert eng.persist_backup_findings(db)["demo_upserted"] > 0
    monkeypatch.delenv(ENV_FLAG)
    invalidate_capabilities()
    out = eng.persist_backup_findings(db)
    assert out["demo_resolved"] > 0
    rows = db.query(InfraFinding).filter(InfraFinding.platform == DEMO_PLATFORM).all()
    assert rows and all(r.active is False and r.resolved_reason == RESOLVED_DEMO_DISABLED for r in rows)
    assert all(r.resolved_reason != RESOLVED_FIXED for r in rows)
    m = store.closure_metrics(db)
    assert m["closed"] == 0 and m["median_resolution_sec"] is None
    assert store.summarize_findings(db)["closure"]["closed"] == 0
    # gerçek bir düzelme sayılır; demo_disabled / provider_disabled sayılmaz
    now = datetime.now(timezone.utc)
    mk = lambda ref, reason: InfraFinding(  # noqa: E731
        platform="backup", source_id=None, check_id="bk.job.failed_recent", entity_ref=ref, category="backup",
        entity_kind="job", result="fail", severity="high", title="t", active=False,
        first_seen=now - timedelta(hours=10), resolved_at=now - timedelta(hours=4), resolved_reason=reason)
    db.add_all([mk("job:fixed", RESOLVED_FIXED), mk("job:legacy", None), mk("job:dd", RESOLVED_DEMO_DISABLED),
                mk("job:pd", "provider_disabled")])
    db.commit()
    m = store.closure_metrics(db)
    assert m["closed"] == 2 and m["median_resolution_sec"] == pytest.approx(6 * 3600)
    # demo platformu kayıtları reason'dan bağımsız hiç sayılmaz
    db.add(InfraFinding(platform=DEMO_PLATFORM, source_id=None, check_id="bk.job.failed_recent", entity_ref="job:x",
                        category="backup", entity_kind="job", result="fail", severity="high", title="t", active=False,
                        first_seen=now - timedelta(hours=3), resolved_at=now - timedelta(hours=1),
                        resolved_reason=RESOLVED_FIXED))
    db.commit()
    assert store.closure_metrics(db)["closed"] == 2
    # gerçek-sağlayıcı bulgusu düzeldiğinde reason == fixed
    real = _make_instance(db, kind="veeam_vbr")
    monkeypatch.setenv(ENV_FLAG, "true")
    vms2 = _sync(db, monkeypatch, real)
    monkeypatch.setattr(eng, "_vms", lambda _db: vms2)
    _caps()
    assert eng.persist_backup_findings(db)["upserted"] > 0
    pre = {f.id for f in db.query(InfraFinding).filter(InfraFinding.platform == "backup", InfraFinding.active.is_(True))}
    from app.models.backup import BkRepository
    db.query(BkRepository).filter(BkRepository.instance_id == real.id).delete()
    db.commit()
    eng.persist_backup_findings(db)
    gone = db.query(InfraFinding).filter(InfraFinding.id.in_(pre), InfraFinding.active.is_(False),
                                         InfraFinding.check_id == "bk.repo.capacity").all()
    assert gone and all(g.resolved_reason == RESOLVED_FIXED for g in gone)
