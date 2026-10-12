"""Dilim E: yedeğe bağlı ek analizler (trend, RTO doğrulanmadı, 3-2-1, kanıt, korelasyon, timeline, what-if)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.backup import extras
from app.services.backup.veeam_provider import VeeamDemoProvider
from app.services.findings.registry import (
    CHECKS, RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS,
)
from app.tests.test_backup_dilim_d import _demo_vms, _make_instance, db  # noqa: F401  (fixture)

GB = 1024 ** 3


def _synced(db, monkeypatch, n=20):
    from app.services.backup import sync as bsync
    vms = _demo_vms(n)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    assert bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))["ok"]
    return row, vms


def _seed_sessions(db, job, n, *, last_gb, last_min, base_gb=10, base_min=30):
    from app.models.backup import BkSession
    db.query(BkSession).filter(BkSession.job_id == job.id).delete()
    now = datetime.now(timezone.utc)
    for k in range(n):
        last = k == n - 1
        st = now - timedelta(days=n - k)
        db.add(BkSession(job_id=job.id, started_at=st,
                         ended_at=st + timedelta(minutes=last_min if last else base_min), result="Success",
                         transferred_bytes=int((last_gb if last else base_gb) * GB)))
    db.commit()


def test_new_checks_registered_and_capability_gated():
    for cid in ("bk.job.change_rate_spike", "bk.job.window_overrun", "bk.vm.rto_unverified",
                "bk.copy.missing", "bk.provider.api_revision_deprecated"):
        assert CHECKS[cid].requires_capability == ("backup",)
        assert CHECKS[cid].platforms == ("backup",)


def test_change_rate_and_window_trends(db, monkeypatch):
    from app.models.backup import BkJob
    row, _ = _synced(db, monkeypatch)
    job = db.query(BkJob).filter(BkJob.instance_id == row.id, BkJob.job_type == "backup").first()
    _seed_sessions(db, job, 12, last_gb=35, last_min=80)           # 3.5× ve 2.7×
    fs = {(f.check_id, f.entity_name): f for f in extras.job_trend_findings(db)}
    assert fs[("bk.job.change_rate_spike", job.name)].result == RESULT_FAIL
    assert fs[("bk.job.window_overrun", job.name)].result == RESULT_FAIL
    _seed_sessions(db, job, 12, last_gb=11, last_min=31)
    fs = {(f.check_id, f.entity_name): f for f in extras.job_trend_findings(db)}
    assert fs[("bk.job.change_rate_spike", job.name)].result == RESULT_PASS
    assert fs[("bk.job.window_overrun", job.name)].result == RESULT_PASS
    _seed_sessions(db, job, 3, last_gb=50, last_min=90)             # yetersiz geçmiş → ölçülemedi
    fs = {(f.check_id, f.entity_name): f for f in extras.job_trend_findings(db)}
    assert fs[("bk.job.change_rate_spike", job.name)].result == RESULT_NOT_MEASURABLE


def test_rto_unverified_rules_and_no_estimation(db, monkeypatch):
    from app.models.backup import BkProtectedObject, BkRestoreTest, BkRpoPolicy
    row, vms = _synced(db, monkeypatch)
    # RTO hedefi yok → uygulanamaz
    fs = [f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.vm.rto_unverified"]
    assert fs and all(f.result == RESULT_NOT_APPLICABLE for f in fs)
    # hedef RTO var, test yok → fail (tahmin yok)
    db.add(BkRpoPolicy(scope_kind="all", scope_ref="", target_rto_min=60, label="_t"))
    db.commit()
    fs = [f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.vm.rto_unverified"]
    assert fs and all(f.result == RESULT_FAIL for f in fs)
    assert all("tahmin edilmez" in f.detail for f in fs)
    # bir VM için güncel test kaydı → pass
    o = (db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == row.id,
                                            BkProtectedObject.match_confidence.in_(("exact", "high")),
                                            BkProtectedObject.matched_vm_id.isnot(None)).first())
    db.add(BkRestoreTest(protected_object_id=o.id, tested_at=datetime.now(timezone.utc) - timedelta(days=5),
                         duration_sec=900, result="ok"))
    db.commit()
    by = {f.entity_name: f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.vm.rto_unverified"}
    name = next(v["name"] for v in vms if v["id"] == o.matched_vm_id)
    assert by[name].result == RESULT_PASS


def test_copy_job_and_api_revision(db, monkeypatch):
    from app.models.backup import BkJob
    row, vms = _synced(db, monkeypatch)
    fs = {f.check_id: f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.copy.missing"}
    has_copy = db.query(BkJob).filter(BkJob.instance_id == row.id, BkJob.job_type == "copy").count() > 0
    assert fs["bk.copy.missing"].result == (RESULT_PASS if has_copy else RESULT_FAIL)
    db.query(BkJob).filter(BkJob.instance_id == row.id, BkJob.job_type == "copy").update({"enabled": False})
    db.commit()
    assert [f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.copy.missing"][0].result == RESULT_FAIL
    # demo kind'da API revizyonu bulgusu üretilmez
    assert not [f for f in extras.policy_findings(db, vms=vms) if f.check_id == "bk.provider.api_revision_deprecated"]


def test_evidence_missing_restore_test_is_reported_eksik(db, monkeypatch):
    _synced(db, monkeypatch)
    ev = extras.evidence(db)
    assert ev["demo"] is True
    rt = next(i for i in ev["items"] if i["item"] == "Geri yükleme testi kaydı")
    assert rt["status"] == "eksik" and rt["value"] is None
    assert any("immutability" in x.lower() for x in ev["not_checked"])
    assert ev["jobs"]


def test_timeline_items_only_with_capability_and_match(db, monkeypatch):
    from app.models.backup import BkProtectedObject
    row, vms = _synced(db, monkeypatch)
    o = (db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == row.id,
                                            BkProtectedObject.match_confidence.in_(("exact", "high")),
                                            BkProtectedObject.job_provider_id.isnot(None)).first())
    now = datetime.now(timezone.utc)
    items = extras.timeline_items(db, now - timedelta(days=2), now, {o.matched_vm_id})
    assert items and all(i["tags"] == ["backup"] and "nedensellik" in i["note"] for i in items)
    assert extras.timeline_items(db, now - timedelta(days=2), now, set()) == []
    # capability kalkınca (instance devre dışı) boş
    row.enabled = False
    db.commit()
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    assert extras.timeline_items(db, now - timedelta(days=2), now, {o.matched_vm_id}) == []


def test_repo_whatif_linear_projection(db, monkeypatch):
    _synced(db, monkeypatch)
    a = extras.repo_whatif(db, add_vms=0)
    b = extras.repo_whatif(db, add_vms=50, avg_vm_gb=100)
    assert a["ok"] and b["ok"]
    assert b["used_pct_after"] > a["used_pct_before"] and b["assumptions"]
    assert a["used_pct_after"] == a["used_pct_before"]


def test_veeamless_extras_are_empty(db):
    assert extras.extra_findings(db) == []
    assert extras.timeline_items(db, datetime.now(timezone.utc) - timedelta(hours=1), datetime.now(timezone.utc), {1}) == []
