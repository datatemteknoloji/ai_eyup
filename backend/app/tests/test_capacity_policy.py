"""Dilim C: kapasite eşik politikası (capacity_policies), planlayıcıya etkisi, N+1 not_applicable."""
from __future__ import annotations

import pytest

from app.core.database import SessionLocal, engine
from app.models.capacity_policy import CapacityPolicy
from app.services import capacity_policy as cp
from app.services import virt_capacity_planner as planner
from app.services.findings.registry import RESULT_NOT_APPLICABLE


@pytest.fixture()
def db():
    CapacityPolicy.__table__.create(bind=engine, checkfirst=True)
    s = SessionLocal()
    s.query(CapacityPolicy).delete()
    s.commit()
    cp.activate(values=None)   # varsayılanlar
    try:
        yield s
    finally:
        s.query(CapacityPolicy).delete()
        s.commit()
        s.close()
        cp.activate(values=cp.defaults())


def test_defaults_match_documented_values():
    d = cp.defaults()
    assert d == {"memory": 85.0, "cpu": 80.0, "datastore": 85.0, "n1_warn": 90.0, "vcpu_ratio": 4.0, "ds_reserve": 15.0,
                 "rs_window_days": 30.0, "rs_target_pct": 70.0, "rs_min_reduction_pct": 25.0, "rs_min_vcpu": 4.0}


def test_validate_rejects_unknown_and_out_of_range():
    with pytest.raises(ValueError):
        cp.validate({"nope": 1})
    with pytest.raises(ValueError):
        cp.validate({"memory": 120})
    with pytest.raises(ValueError):
        cp.validate({"memory": "abc"})
    assert cp.validate({"memory": "70"}) == {"memory": 70.0}


def test_save_load_roundtrip_and_default_row_removed(db):
    cp.save(db, {"memory": 70, "datastore": 90}, user="t")
    cur = cp.load(db)
    assert cur["memory"] == 70.0 and cur["datastore"] == 90.0 and cur["cpu"] == 80.0
    assert db.query(CapacityPolicy).count() == 2
    p = cp.payload(db)
    assert p["spec"]["memory"]["overridden"] is True and p["spec"]["cpu"]["overridden"] is False
    # varsayılana dönünce satır silinir
    cp.save(db, {"memory": 85}, user="t")
    assert db.query(CapacityPolicy).filter(CapacityPolicy.key == "memory").count() == 0
    assert cp.load(db)["memory"] == 85.0


def test_invalid_save_changes_nothing(db):
    with pytest.raises(ValueError):
        cp.save(db, {"memory": 70, "cpu": 5})
    assert db.query(CapacityPolicy).count() == 0


def _cap(mem_runway_days=None, ds_usage=87.0, ratio=3.0):
    cluster = {
        "platform": "vmware", "hypervisor_id": 1, "cluster": "C1", "hosts_usable": 3,
        "memory": {"used_pct": 60.0}, "cpu": {"used_pct": 40.0, "vcpu_ratio": ratio, "vcpu_allocated": 30, "total_cores": 10},
        "n_plus_one": {"status": "ok"},
        "forecast": {},
    }
    ds = {"hypervisor_id": 1, "ref": "ds-1", "name": "DS1", "usage_pct": ds_usage, "free_gb": 10, "capacity_gb": 100}
    return {"clusters": [cluster], "datastores": [ds],
            "thresholds": dict(memory=85, cpu=80, datastore=85, n1_warn=90, vcpu_ratio=4, ds_reserve=15)}


def _ds_result(cap):
    drafts = planner.capacity_findings(cap)[("vmware", 1)]
    return next(d for d in drafts if d.check_id == "cap.datastore.usage")


def test_findings_use_threshold_from_cap(db):
    cap = _cap(ds_usage=87.0)
    assert _ds_result(cap).result == "fail"            # %87 ≥ 85
    cap["thresholds"]["datastore"] = 90
    assert _ds_result(cap).result == "pass"            # eşik yükselince geçer
    cap["thresholds"]["datastore"] = 80
    assert _ds_result(cap).result == "fail"


def test_vcpu_ratio_threshold(db):
    cap = _cap(ratio=3.0)
    drafts = planner.capacity_findings(cap)[("vmware", 1)]
    assert next(d for d in drafts if d.check_id == "cap.cluster.vcpu_ratio").result == "pass"
    cap["thresholds"]["vcpu_ratio"] = 2
    drafts = planner.capacity_findings(cap)[("vmware", 1)]
    assert next(d for d in drafts if d.check_id == "cap.cluster.vcpu_ratio").result == "fail"


def test_single_host_n1_is_not_applicable(db):
    cap = _cap()
    cap["clusters"][0]["n_plus_one"] = {"status": "single_host"}
    drafts = planner.capacity_findings(cap)[("vmware", 1)]
    n1 = next(d for d in drafts if d.check_id == "cap.cluster.n_plus_one")
    assert n1.result == RESULT_NOT_APPLICABLE
