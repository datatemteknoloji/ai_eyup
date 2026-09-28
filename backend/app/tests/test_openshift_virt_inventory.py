"""Tests for OpenShift cluster → openshift_virt → servers bridge."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.openshift_virt_inventory import (
    META_CLUSTER_ID,
    MANAGED_BY,
    _hv_name,
    ensure_virt_hypervisor_from_cluster,
    find_managed_virt_hypervisor,
    sync_kubevirt_vms_into_servers,
)


def _cluster(**kw):
    defaults = dict(
        id=7,
        name="lab-ocp",
        api_url="https://api.lab.example:6443",
        connection_config={"token": "plain-token", "verify_ssl": False},
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_hv_name():
    assert _hv_name(_cluster(name="oVirt")) == "oVirt (OpenShift Virt)"


def test_find_managed_by_cluster_id():
    hv = SimpleNamespace(
        hypervisor_type=SimpleNamespace(value="openshift_virt"),
        meta_data={META_CLUSTER_ID: 7},
        connection_config={},
        hostname="",
    )
    # Enum compare uses HypervisorType — patch query chain
    db = MagicMock()
    # Simulate filter().all() returning our hv with proper type enum
    from app.models.hypervisor import HypervisorType
    hv.hypervisor_type = HypervisorType.OPENSHIFT_VIRT
    db.query.return_value.filter.return_value.all.return_value = [hv]
    assert find_managed_virt_hypervisor(db, _cluster()) is hv


def test_ensure_creates_hypervisor():
    from app.models.hypervisor import HypervisorType

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.first.return_value = None

    created = []

    def _add(obj):
        created.append(obj)
        obj.id = 99

    db.add.side_effect = _add

    cluster = _cluster()
    hv = ensure_virt_hypervisor_from_cluster(db, cluster)
    assert hv is created[0]
    assert hv.hypervisor_type == HypervisorType.OPENSHIFT_VIRT
    assert hv.meta_data[META_CLUSTER_ID] == 7
    assert hv.meta_data["managed_by"] == MANAGED_BY
    assert hv.connection_config.get("api_url") == cluster.api_url
    db.flush.assert_called()


def test_sync_kubevirt_calls_inventory_sync():
    fake_hv = SimpleNamespace(id=55)
    with patch(
        "app.services.openshift_virt_inventory.ensure_virt_hypervisor_from_cluster",
        return_value=fake_hv,
    ), patch(
        "app.services.inventory_sync_service.sync_hypervisor_vms",
        return_value={"synced_count": 2, "total_vms": 3, "enriched_count": 1, "errors": []},
    ) as sync_mock, patch(
        "app.services.platform_scope.invalidate_platform_id_cache",
    ):
        out = sync_kubevirt_vms_into_servers(MagicMock(), _cluster())
    assert out["skipped"] is False
    assert out["hypervisor_id"] == 55
    assert out["total_vms"] == 3
    assert out["synced_count"] == 2
    sync_mock.assert_called_once()


def test_sync_skips_without_credentials():
    cluster = _cluster(connection_config={})
    out = sync_kubevirt_vms_into_servers(MagicMock(), cluster)
    assert out["skipped"] is True
    assert out["total_vms"] == 0
