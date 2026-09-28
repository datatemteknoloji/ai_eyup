"""OpenShift Virt host metrics → hypervisor_host_metrics."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.openshift_virt_host_metrics import _clamp_pct, sync_openshift_virt_host_metrics


def test_clamp_pct():
    assert _clamp_pct(115) == 100.0
    assert _clamp_pct(-5) == 0.0
    assert _clamp_pct(34.15) == 34.1
    assert _clamp_pct(None) is None


def test_sync_writes_host_metrics():
    hv = SimpleNamespace(
        id=6,
        name="oVirt (OpenShift Virt)",
        status="ONLINE",
        meta_data={"openshift_cluster_id": 2},
        connection_config={},
        hostname="",
    )
    cluster = SimpleNamespace(id=2, name="oVirt", api_url="https://api.example:6443")
    nodes = [
        SimpleNamespace(
            name="master-0",
            status="Ready",
            cpu_cores=8,
            memory_gb=64,
            cpu_usage_pct=80,
            memory_usage_pct=40,
        )
    ]

    db = MagicMock()
    # hypervisors query
    q_hv = MagicMock()
    q_hv.filter.return_value.all.return_value = [hv]
    q_cluster = MagicMock()
    q_cluster.filter.return_value.first.return_value = cluster
    q_nodes = MagicMock()
    q_nodes.filter.return_value.all.return_value = nodes
    q_vms = MagicMock()
    q_vms.filter.return_value.all.return_value = []

    def _query(model):
        name = getattr(model, "__name__", str(model))
        if "Hypervisor" in name and "Metric" not in name and "Host" not in name:
            return q_hv
        if "OpenShiftCluster" in name:
            return q_cluster
        if "OpenShiftNode" in name:
            return q_nodes
        if "Server" in name:
            return q_vms
        return MagicMock()

    db.query.side_effect = _query

    with patch(
        "app.services.openshift_virt_host_metrics._pv_disk_usage",
        return_value=(10.0, 100.0, 10.0),
    ):
        out = sync_openshift_virt_host_metrics(db)

    assert out["hosts"] == 1
    assert out["hypervisors"] == 1
    assert db.add.call_count >= 1
    db.commit.assert_called()
