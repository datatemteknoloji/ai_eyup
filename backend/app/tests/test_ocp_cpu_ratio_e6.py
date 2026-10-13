"""E6 — OpenShift Virtualization vmiCPUAllocationRatio: HCO'dan okunur; okunamazsa varsayılan + etiket."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.services import capacity_policy, virt_capacity_planner as vcp
from app.services.capacity import sources as cap_src
from app.services.findings import store
from app.services.findings.collectors.ocp_virt import parse_vmi_cpu_ratio

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def _hv(db, name="ocp1"):
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.OPENSHIFT_VIRT, hostname=f"{name}.x", ip_address="10.0.0.2",
                    connection_config={})
    db.add(hv)
    db.flush()
    for i in (1, 2):
        db.add(HypervisorHostMetric(timestamp=NOW, hypervisor_id=hv.id, host_name=f"w{i}", host_ref=f"w{i}", cpu_cores=32,
                                    mem_total_mb=256 * 1024, mem_used_mb=20 * 1024, cpu_usage_pct=10,
                                    connection_state="connected", maintenance_mode=0, cluster_name=name))
    db.commit()
    return hv


def _snap(db, hv, cfg):
    store.save_config_snapshot(db, platform="ocp_virt", source_id=hv.id, entity_kind="platform", entity_ref="platform",
                               entity_name=hv.name, cluster_name=hv.name, config=cfg, state={})
    db.commit()


def test_parse_ratio_accepts_positive_numbers_only():
    assert parse_vmi_cpu_ratio(10) == 10.0 and parse_vmi_cpu_ratio("4") == 4.0
    for bad in (None, 0, -1, "x", True, ""):
        assert parse_vmi_cpu_ratio(bad) is None


def test_ratio_read_from_hco(isolated_db):
    hv = _hv(isolated_db)
    _snap(isolated_db, hv, {"hco_read": True, "vmi_cpu_allocation_ratio": 4.0})
    r = cap_src.ocp_virt_cpu_ratio(isolated_db, hv.id)
    assert r["ratio"] == 4.0 and r["source"] == "hco" and "okundu" in r["label"]


def test_ratio_unset_in_hco_uses_platform_default_labelled(isolated_db):
    hv = _hv(isolated_db)
    _snap(isolated_db, hv, {"hco_read": True, "vmi_cpu_allocation_ratio": None})
    r = cap_src.ocp_virt_cpu_ratio(isolated_db, hv.id)
    assert r["ratio"] == 10.0 and r["source"] == "hco_default" and "ayarlı değil" in r["label"]


def test_ratio_hco_unreadable_or_old_snapshot_is_default_value_label(isolated_db):
    hv = _hv(isolated_db)
    # snapshot hiç yok
    r0 = cap_src.ocp_virt_cpu_ratio(isolated_db, hv.id)
    assert r0["ratio"] == 10.0 and r0["source"] == "default" and "varsayılan değer" in r0["label"] and "ölçülmedi" in r0["label"]
    # HCO okunamadı (RBAC)
    _snap(isolated_db, hv, {"hco_read": False, "vmi_cpu_allocation_ratio": None})
    assert cap_src.ocp_virt_cpu_ratio(isolated_db, hv.id)["source"] == "default"


def test_simulate_exposes_cpu_request_and_assumption(isolated_db):
    hv = _hv(isolated_db)
    _snap(isolated_db, hv, {"hco_read": True, "vmi_cpu_allocation_ratio": 5.0})
    res = vcp.simulate(isolated_db, vcpu=10, memory_gb=8, count=2)
    r = next(x for x in res["results"] if x["platform"] == "ocp_virt")
    assert r["cpu_request"]["ratio"] == 5.0 and r["cpu_request"]["source"] == "hco"
    assert r["cpu_request"]["each_cores"] == 2.0 and r["cpu_request"]["total_cores"] == 4.0
    txt = " ".join(res["assumptions"])
    assert "CPU request" in txt and "HyperConverged'dan okundu" in txt and "request tabanlı değil" in txt


def test_simulate_default_ratio_label_when_hco_unreadable(isolated_db):
    hv = _hv(isolated_db)
    _snap(isolated_db, hv, {"hco_read": False})
    res = vcp.simulate(isolated_db, vcpu=10, memory_gb=8)
    r = next(x for x in res["results"] if x["platform"] == "ocp_virt")
    assert r["cpu_request"]["ratio"] == 10.0 and r["cpu_request"]["source"] == "default"
    assert any("varsayılan değer 10" in a and "ölçülmedi" in a for a in res["assumptions"])
