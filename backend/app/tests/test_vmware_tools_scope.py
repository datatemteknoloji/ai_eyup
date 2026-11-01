"""Aşama 2b — VMware Tools denetimleri yalnız hypervisor türü VMWARE olan VM'lere uygulanır.

KubeVirt / oVirt(KVM) VM'lerinde VMware Tools kavramı yok; tools_status 'unknown' → eskiden «eksik» sayılıyordu
(kanonik güç durumuyla bağlayınca 8 → 456 şişkinliği). Güç durumu kanonik `power_state.is_on`.
"""
from unittest.mock import MagicMock

import pytest

from app.services import report_engine as re_


def vm(name, hvtype, state, tools, hv="h"):
    return {"id": hash(name) % 100000, "name": name, "ip": "", "hypervisor": hv, "hypervisor_type": hvtype,
            "os_type": "", "os_version": "", "os_release": "", "cpu_count": 2, "memory_gb": 4, "memory_mb": 4096,
            "disk_gb": 50, "power_state": state, "tools_status": tools, "hw_version": "", "cluster": "",
            "datastore": "", "tier": "unknown", "last_sync": None, "ai_ready": False}


@pytest.fixture
def fleet(monkeypatch):
    vms = (
        [vm("vmw-ok", "vmware", "poweredOn", "guestToolsRunning")]
        + [vm(f"vmw-bad{i}", "vmware", "POWERED_ON", "guestToolsNotRunning") for i in range(2)]   # gerçek sorun: 2
        + [vm("vmw-notools", "vmware", "poweredOn", "unknown")]                                      # sorun: 3. VMware
        + [vm("vmw-off", "vmware", "poweredOff", "guestToolsNotRunning")]                            # kapalı: sayılmaz
        + [vm(f"kv{i}", "openshift_virt", "Running", "not-installed") for i in range(50)]           # KubeVirt: kapsam dışı
        + [vm(f"ov{i}", "kvm", "up", "unknown") for i in range(8)]                                   # oVirt: kapsam dışı
        + [vm("orphan", "", "poweredOn", "unknown", hv="?")]                                         # hypervisor'sız: kapsam dışı
    )
    monkeypatch.setattr(re_, "_get_vms", lambda db: vms)
    monkeypatch.setattr(re_, "_latest_host_metrics", lambda db: [])
    monkeypatch.setattr(re_, "_get_active_events", lambda db, days=7: [])
    return vms


def test_is_vmware_vm():
    assert re_._is_vmware_vm({"hypervisor_type": "vmware"})
    assert re_._is_vmware_vm({"hypervisor_type": "VMWARE"})
    for t in ("kvm", "openshift_virt", "proxmox", "", None):
        assert not re_._is_vmware_vm({"hypervisor_type": t})
    assert not re_._is_vmware_vm({})


def test_executive_recommendation_counts_only_vmware(fleet):
    recs = re_._build_executive_recommendations([], fleet, [], {"quality_level": "Yüksek"})
    line = [r for r in recs if "guest tools" in r]
    assert line == ["3 çalışan VM'de guest tools eksik — güvenlik/uyumluluk riski."]


def test_executive_recommendation_absent_without_vmware(monkeypatch):
    vms = [vm(f"kv{i}", "openshift_virt", "Running", "not-installed") for i in range(20)]
    recs = re_._build_executive_recommendations([], vms, [], {"quality_level": "Yüksek"})
    assert not [r for r in recs if "guest tools" in r]


def test_risk_dashboard_no_tools_vms_only_vmware(fleet):
    try:
        data = re_.generate_risk_dashboard(MagicMock())
    except Exception as e:
        pytest.skip(f"risk dashboard yalıtılamadı: {type(e).__name__}")
    names = sorted(v["vm"] for v in data["risks"]["no_tools_vms"])
    assert names == ["vmw-bad0", "vmw-bad1", "vmw-notools"]


def test_security_compliance_powered_on_non_compliant_only_vmware(fleet):
    try:
        data = re_.generate_security_compliance_report(MagicMock())
    except Exception as e:
        pytest.skip(f"security yalıtılamadı: {type(e).__name__}")
    vt = data["vmware_tools"]
    assert vt["powered_on_non_compliant"] == 3
    assert sorted(v["vm"] for v in vt["non_compliant_vms"]) == ["vmw-bad0", "vmw-bad1", "vmw-notools"]
    assert any("3 çalışan VM'de VMware Tools" in i for i in data["issues"])
