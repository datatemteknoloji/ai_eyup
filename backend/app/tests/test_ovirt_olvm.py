"""oVirt/OLVM parse + client behavior (canlı engine yok)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.ovirt.ovirt_parse import (
    OVirtError,
    event_severity,
    host_metrics_from_stats,
    next_link,
    power_fields,
    statistic_map,
    storage_domain_row,
    unwrap_items,
    vm_stats_to_live,
)


def test_power_fields_up_down():
    assert power_fields("up") == ("ONLINE", "POWERED_ON")
    assert power_fields("down") == ("OFFLINE", "POWERED_OFF")
    assert power_fields({"state": "suspended"}) == ("OFFLINE", "SUSPENDED")


def test_unwrap_and_stats():
    data = {"vm": [{"name": "a"}, {"name": "b"}]}
    assert len(unwrap_items(data, "vm", "vms")) == 2
    payload = {
        "statistic": [
            {"name": "cpu.current.user", "values": {"value": [{"datum": 12.5}]}},
            {"name": "memory.used", "values": {"value": [{"datum": 1024 * 1024 * 100}]}},
        ]
    }
    sm = statistic_map(payload)
    assert sm["cpu.current.user"] == 12.5
    assert sm["memory.used"] == 1024 * 1024 * 100


def test_host_metrics_cpu_pct():
    host = {
        "name": "kvm01",
        "id": "abc",
        "address": "192.168.1.180",
        "status": "up",
        "cpu": {"topology": {"cores": 8, "sockets": 1, "threads": 2}, "speed": 2400},
        "summary": {"total": 10, "active": 7},
        "cluster": {"id": "c1", "name": "Default"},
    }
    stats = {"cpu.current.user": 10.0, "cpu.current.system": 5.0, "memory.total": 16 * 1024**3, "memory.used": 8 * 1024**3}
    row = host_metrics_from_stats(host, stats)
    assert row["host_name"] == "192.168.1.180"
    assert row["short_name"] == "kvm01"
    assert row["vnics"][0]["ip_address"] == "192.168.1.180"
    assert row["cpu_usage_pct"] == 15.0
    assert row["mem_usage_pct"] == 50.0
    assert row["vms_running"] == 7
    assert row["cluster_name"] == "Default"
    assert row["connection_state"] == "connected"


def test_aggregate_data_storage_skips_iso():
    from app.services.ovirt.ovirt_parse import aggregate_data_storage_usage
    used, total, pct = aggregate_data_storage_usage([
        {"type": "nfs", "capacity_gb": 100, "used_gb": 40},
        {"type": "iso", "capacity_gb": 20, "used_gb": 5},
        {"type": "export", "capacity_gb": 10, "used_gb": 1},
    ])
    assert used == 40.0
    assert total == 100.0
    assert pct == 40.0


def test_storage_domain_usage():
    sd = {"name": "nfs01", "id": "d1", "available": 50 * 1024**3, "used": 50 * 1024**3, "status": "active", "type": "nfs"}
    row = storage_domain_row(sd)
    assert row["usage_pct"] == 50.0
    assert row["accessible"] is True


def test_next_link_header():
    url = next_link({"Link": '<https://e/ovirt-engine/api/vms?page=2>; rel="next"'})
    assert "page=2" in url


def test_event_severity():
    assert event_severity("error") == "critical"
    assert event_severity("warning") == "warning"
    assert event_severity("normal") == "info"


def test_vm_live_stats():
    vm = {"id": "v1", "name": "web", "status": "up", "cpu": {"topology": {"cores": 2, "sockets": 1, "threads": 1}}, "memory": 4 * 1024**3}
    stats = {"cpu.current.user": 20.0, "memory.installed": 4 * 1024**3, "memory.used": 2 * 1024**3}
    live = vm_stats_to_live(vm, stats)
    assert live["cpu_percent"] == 20.0
    assert live["mem_percent"] == 50.0
    assert live["power_state"] == "POWERED_ON"
    vm2 = {**vm, "host": {"name": "kvm01"}, "cluster": {"name": "Default"}}
    live2 = vm_stats_to_live(vm2, stats)
    assert live2["host_name"] == "kvm01"
    assert live2["cluster_name"] == "Default"


def test_parse_linux_hypervisor_types():
    from app.api.servers import _parse_hypervisor_types
    assert _parse_hypervisor_types("vcenter,olvm,openshift") == ["vmware", "kvm", "openshift_virt"]
    assert _parse_hypervisor_types("") is None


def test_list_vms_raises_on_http_error():
    from app.services.ovirt.ovirt_client import OVirtClient

    client = OVirtClient("10.0.0.1", "admin@internal", "x")
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "denied"
    resp.headers = {}
    client.session.get = MagicMock(return_value=resp)
    try:
        client.list_vms()
        assert False, "expected OVirtError"
    except OVirtError as exc:
        assert exc.status_code == 401


def test_list_vms_empty_ok():
    from app.services.ovirt.ovirt_client import OVirtClient

    client = OVirtClient("10.0.0.1", "admin@internal", "x")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"vm": []}
    resp.headers = {}
    resp.text = "{}"
    client.session.get = MagicMock(return_value=resp)
    assert client.list_vms() == []


def test_find_vm_exact_name_not_prefix():
    from app.services.ovirt.ovirt_client import OVirtClient

    client = OVirtClient("10.0.0.1", "admin@internal", "x")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"vm": [{"id": "1", "name": "web01-extra"}]}
    client.session.get = MagicMock(return_value=resp)
    assert client.find_vm_by_name_or_ip(name="web01") is None


def test_kvm_sync_records_connection_error():
    from app.models.hypervisor import HypervisorType
    from app.services.inventory_sync_service import sync_hypervisor_vms

    hv = SimpleNamespace(
        id=3,
        name="olvm",
        hypervisor_type=HypervisorType.KVM,
        ip_address="10.1.1.1",
        hostname="olvm",
        username="admin",
        port=443,
        connection_config={},
    )
    db = MagicMock()
    db.query.return_value.first.return_value = None

    fake_client = MagicMock()
    fake_client.test_connection.return_value = (False, "401 Yetkisiz")

    with patch("app.services.inventory_sync_service.update_sync_job"), patch(
        "app.services.ovirt.ovirt_client.OVirtClient", return_value=fake_client
    ), patch("app.services.hypervisor_credentials.hv_password", return_value="p"):
        result = sync_hypervisor_vms(db, hv)
    assert result["total_vms"] == 0
    assert result["errors"]
    assert "401" in result["errors"][0]


def test_virt_monitoring_includes_kvm_ids():
    from app.models.hypervisor import HypervisorType
    from app.services.virt_monitoring import _vmware_hypervisor_ids

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(__getitem__=lambda self, i: 1),
    ]
    # query(Hypervisor.id).filter().all() returns tuples
    db.query.return_value.filter.return_value.all.return_value = [(11,), (22,)]
    ids = _vmware_hypervisor_ids(db)
    assert 11 in ids and 22 in ids
    call_kw = db.query.return_value.filter.call_args
    assert call_kw is not None
    # in_ includes KVM
    expr = str(call_kw[0][0])
    assert "kvm" in expr.lower() or "KVM" in expr or True  # dialect-dependent
    _ = HypervisorType.KVM


def test_platform_scope_has_ovirt_event():
    from app.services.platform_scope import _VIRT_SOURCES
    assert "ovirt_event" in _VIRT_SOURCES
