"""OpenShift Monitoring — Timescale + metrics.k8s.io (Prometheus yok)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.openshift.ocp_monitoring import (
    _pct,
    collect_live_rows,
    is_system_namespace,
    metric_catalog,
    object_ref,
    parse_names,
    parse_object_ref,
    virt_launcher_vm_name,
)


def test_object_ref_and_parse():
    a = object_ref(1, "node", "worker-1")
    b = object_ref(2, "node", "worker-1")
    assert a != b
    assert parse_object_ref(a) == (1, "node", "worker-1", None)
    assert parse_object_ref(object_ref(3, "pod", "api", "shop")) == (3, "pod", "api", "shop")
    assert parse_object_ref(object_ref(4, "vm", "rhel9", "vmns")) == (4, "vm", "rhel9", "vmns")


def test_virt_launcher_and_system_ns():
    assert virt_launcher_vm_name("virt-launcher-x-abc", {"vm.kubevirt.io/name": "pay"}) == "pay"
    assert virt_launcher_vm_name("virt-launcher-rhel9-a1b2c") == "rhel9"
    assert is_system_namespace("openshift-monitoring") is True
    assert is_system_namespace("shop") is False


def test_metric_catalog_whitelist():
    cats = metric_catalog("node")
    ids = {c["id"] for c in cats}
    assert "cpu_pct" in ids and "memory_pct" in ids
    try:
        metric_catalog("datastore")
        assert False
    except ValueError:
        pass


def test_parse_names_cap():
    names = parse_names("a,b,c,d,e,f,g,h,i,j")
    assert len(names) == 8


def test_pct():
    assert _pct(5, 10) == 50.0
    assert _pct(None, 10) is None


def test_collect_live_rows_identity():
    cluster = SimpleNamespace(
        id=7,
        name="prod",
        api_url="https://api.example:6443",
        connection_config={},
    )
    client = MagicMock()
    client.list_nodes.return_value = [{
        "name": "worker-1",
        "role": "worker",
        "status": "Ready",
        "cpu_cores": 8,
        "memory_gb": 32,
        "cpu_allocatable": 8,
        "memory_allocatable_gb": 32,
    }]
    client.list_pods.return_value = [{
        "namespace": "shop",
        "name": "api-0",
        "status": "Running",
        "phase": "Running",
        "node_name": "worker-1",
        "restart_count": 0,
        "cpu_request": 0.5,
        "memory_request_gb": 1,
        "labels": {},
    }, {
        "namespace": "vmns",
        "name": "virt-launcher-rhel9-xyz",
        "status": "Running",
        "phase": "Running",
        "node_name": "worker-1",
        "restart_count": 0,
        "cpu_request": 2,
        "memory_request_gb": 4,
        "labels": {"vm.kubevirt.io/name": "rhel9"},
    }]
    client.logout.return_value = None

    def _get(path, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        if path.endswith("/nodes"):
            resp.json.return_value = {
                "items": [{"metadata": {"name": "worker-1"}, "usage": {"cpu": "4000m", "memory": "16Gi"}}],
            }
        else:
            resp.json.return_value = {
                "items": [
                    {
                        "metadata": {"name": "api-0", "namespace": "shop"},
                        "containers": [{"usage": {"cpu": "250m", "memory": "512Mi"}}],
                    },
                    {
                        "metadata": {"name": "virt-launcher-rhel9-xyz", "namespace": "vmns"},
                        "containers": [{"usage": {"cpu": "1", "memory": "2Gi"}}],
                    },
                ],
            }
        return resp

    client._get.side_effect = _get

    with patch(
        "app.services.openshift.ocp_monitoring.client_from_cluster",
        return_value=client,
    ):
        rows, ok = collect_live_rows(cluster)

    assert ok is True
    kinds = {r["kind"] for r in rows}
    assert kinds == {"node", "pod", "vm"}
    node = next(r for r in rows if r["kind"] == "node")
    assert node["object_key"] == "worker-1"
    assert node["cpu_pct"] == 50.0
    assert node["cluster_id"] == 7
    vm = next(r for r in rows if r["kind"] == "vm")
    assert vm["object_key"] == "vmns/rhel9"
    assert vm["name"] == "rhel9"
