"""VM name vs guest hostname — inventory upsert (VMware + OpenShift Virt)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.inventory_sync_service import _inventory_guest_hostname, _upsert_vm_record


def test_inventory_guest_hostname_prefers_explicit():
    assert _inventory_guest_hostname({"name": "vm1", "hostname": "vm1", "vm_guest_hostname": "os-host"}) == "os-host"


def test_inventory_guest_hostname_ignores_vm_name_fallback():
    assert _inventory_guest_hostname({"name": "rhel8-10tst", "hostname": "rhel8-10tst"}) == ""


def test_inventory_guest_hostname_vmware_tools_style():
    assert _inventory_guest_hostname({"name": "gorkem2", "hostname": "gorkemaslanbas"}) == "gorkemaslanbas"


def test_upsert_sets_vm_name_and_guest_hostname_on_create():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    created = []

    def _add(obj):
        created.append(obj)
        obj.id = 1

    db.add.side_effect = _add
    hv = SimpleNamespace(id=6)

    vm = {
        "name": "gorkem2",
        "hostname": "gorkemaslanbas",
        "ip_address": "192.168.1.114",
        "os_type": "linuxGuest",
        "cpu_cores": 2,
        "memory_gb": 4,
        "vm_id": "vm-1",
        "power_state": "poweredOn",
    }
    assert _upsert_vm_record(db, hv, vm, None, client=None) is True
    srv = created[0]
    assert srv.name == "gorkem2"
    assert srv.vm_name == "gorkem2"
    assert srv.hostname == "gorkemaslanbas"
    assert srv.vm_guest_hostname == "gorkemaslanbas"


def test_upsert_openshift_without_guest_keeps_vm_name_as_hostname():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.all.return_value = []
    created = []
    db.add.side_effect = lambda o: created.append(o) or setattr(o, "id", 2)
    hv = SimpleNamespace(id=6)
    vm = {
        "name": "rhel8-10tst",
        "hostname": "rhel8-10tst",  # agent yok → fallback
        "vm_guest_hostname": "",
        "ip_address": "192.168.1.130",
        "os_type": "Red Hat Enterprise Linux 8.10",
        "cpu_cores": 2,
        "memory_gb": 4,
        "vm_id": "vm-migrasyon/rhel8-10tst",
        "power_state": "poweredOn",
    }
    assert _upsert_vm_record(db, hv, vm, None, client=None) is True
    srv = created[0]
    assert srv.vm_name == "rhel8-10tst"
    assert srv.hostname == "rhel8-10tst"
    assert not srv.vm_guest_hostname


def test_upsert_upgrades_kubevirt_uid_to_namespaced_id():
    existing = SimpleNamespace(
        id=63,
        name="rhel8-10tst",
        hostname="rhel8-10tst",
        vm_name=None,
        vm_guest_hostname=None,
        hypervisor_id=6,
        hypervisor_vm_id="2058523a-e02c-4367-853b-55680e54db4b",
        server_type="VIRTUAL",
        status="ONLINE",
        ip_address="192.168.1.130",
        cpu_cores=2,
        memory_gb=4,
        os_type="rhel",
        vm_power_state=None,
        vm_disk_gb=10,
        vm_tools_status="ok",
        vm_datastore="x",
        vm_last_sync="already",
    )
    db = MagicMock()

    def _filter(*_a, **_k):
        m = MagicMock()
        # vm_id lookup miss; ip/name lists return our OCP row
        m.first.return_value = None
        m.all.return_value = [existing]
        return m

    db.query.return_value.filter.side_effect = _filter

    hv = SimpleNamespace(id=6)
    vm = {
        "name": "rhel8-10tst",
        "hostname": "rhel8-10tst",
        "vm_guest_hostname": "",
        "ip_address": "192.168.1.130",
        "vm_id": "vm-migrasyon/rhel8-10tst",
        "os_type": "rhel",
        "cpu_cores": 2,
        "memory_gb": 4,
    }
    with patch("app.services.inventory_sync_service.owned_by_other_vcenter", return_value=False):
        assert _upsert_vm_record(db, hv, vm, None, client=None) is False
    assert existing.vm_name == "rhel8-10tst"
    assert existing.hypervisor_vm_id == "vm-migrasyon/rhel8-10tst"
