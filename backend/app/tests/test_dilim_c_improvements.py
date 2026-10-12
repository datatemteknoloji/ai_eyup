"""Dilim C: feed yaşı, konsolidasyon, N+1 uygulanamaz, reclaim replica."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import virt_reference_checks as vrc
from app.services.findings.registry import CHECKS, RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_PASS
from app.services.virt_health_checks import _vmware
from app.services.virt_capacity_planner import capacity_findings


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *_a, **_k):
        return _Q(self.rows)


def _row(kind, days):
    return SimpleNamespace(kind=kind, uploaded_at=datetime.now(timezone.utc) - timedelta(days=days),
                           source_label="x")


def test_feed_age_stale_and_fresh():
    drafts = vrc.feed_age_findings(_DB([_row("cve_feed", 45), _row("kb_feed", 3)]))
    by = {d.entity_name: d for d in drafts}
    assert by["cve_feed"].result == RESULT_FAIL
    assert by["kb_feed"].result == RESULT_PASS
    assert by["cve_feed"].check_id == "ref.feed.stale"
    # yüklü olmayan paket → ölçülemedi (asla pass değil)
    assert by["upgrade_matrix"].result == "not_measurable"


def test_feed_age_ignores_unknown_kind_and_unknown_date_is_not_measurable():
    rows = [SimpleNamespace(kind="other", uploaded_at=datetime.now(timezone.utc), source_label=""),
            SimpleNamespace(kind="cve_feed", uploaded_at=None, source_label="")]
    drafts = vrc.feed_age_findings(_DB(rows))
    assert {d.entity_name for d in drafts} == {"cve_feed", "kb_feed", "upgrade_matrix"}
    assert all(d.result == "not_measurable" for d in drafts)


def test_consolidation_check_registered_and_emitted():
    assert "vmw.vm.consolidation_needed" in CHECKS
    col = {"clusters": [], "hosts": [], "datastores": [],
           "vms": [{"ref": "vm-1", "name": "a", "consolidation_needed": True, "snapshots": []},
                   {"ref": "vm-2", "name": "b", "consolidation_needed": False, "snapshots": []}]}
    out = [d for d in _vmware(col, None, {}) if d.check_id == "vmw.vm.consolidation_needed"]
    assert len(out) == 1 and out[0].entity_name == "a" and out[0].result == RESULT_FAIL


def test_single_host_n_plus_one_not_applicable():
    cap = {"clusters": [{
        "platform": "vmware", "hypervisor_id": 1, "cluster": "c1",
        "n_plus_one": {"status": "single_host", "evaluable": False, "hosts_usable": 1},
        "memory": {"used_pct": 10}, "cpu": {"used_pct": 10}, "forecast": {},
    }], "datastores": []}
    res = capacity_findings(cap)
    drafts = [d for ds in res.values() for d in ds if d.check_id == "cap.cluster.n_plus_one"]
    assert len(drafts) == 1 and drafts[0].result == RESULT_NOT_APPLICABLE
