"""HA/DRS DB-first + failover/hiyerarşi QA_RULES yönlendirmesi."""
import re
from unittest.mock import MagicMock, patch

import pytest

from app.services.hypervisor_intelligence import (
    QA_RULES,
    _normalize_virt_question,
    h_cluster_ha_drs,
    h_inventory_hierarchy,
)


def _route(question: str):
    q = _normalize_virt_question(question)
    for pattern, handler in QA_RULES:
        if re.search(pattern, q, re.IGNORECASE):
            return getattr(handler, "__name__", "?")
    return None


@pytest.mark.parametrize("question", [
    "Prod-Cluster HA ve DRS durumu nedir?",
    "HA DRS durumu",
    "Prod-Cluster'da bir host arızalanırsa HA VM'leri kurtarır mı?",
    "bir host arızalanırsa VM'ler ayağa kalkar mı",
    "failover kapasitesi nedir",
    "admission control açık mı",
])
def test_ha_failover_routes_to_cluster_ha_drs(question):
    assert _route(question) == h_cluster_ha_drs.__name__


@pytest.mark.parametrize("question", [
    "office vCenter altındaki hiyerarşi: cluster → host → örnek VM'ler özetle",
    "vcenter hiyerarşi özeti",
    "hiyerarşi göster",
])
def test_hierarchy_routes_to_inventory_hierarchy(question):
    assert _route(question) == h_inventory_hierarchy.__name__


def test_failover_not_hijacked_by_hierarchy():
    assert _route(
        "Prod-Cluster'da bir host arızalanırsa HA VM'leri kurtarır mı?"
    ) == h_cluster_ha_drs.__name__
    assert _route("cluster host vm hiyerarşisi") == h_inventory_hierarchy.__name__


def test_ha_drs_prefers_db_over_empty_live():
    """virt_clusters doluysa canlı ClusterComputeResource boş olsa bile DB kullanılır."""
    db = MagicMock()
    db_pack = {
        "ok": True,
        "clusters": [{
            "name": "Prod-Cluster",
            "ha_enabled": True,
            "admission_control_enabled": True,
            "drs_enabled": True,
            "drs_behavior": "fullyAutomated",
            "hosts": 3,
            "host_names": ["192.168.1.101", "esx-prod-01", "esx-prod-02"],
            "cpu_cores": 96,
            "memory_gb": 768.0,
            "overall_status": "green",
            "hypervisor": "office",
            "ha_verdict": "Failover kapasitesi var — 12 boş slot (toplam 20, kullanılan 8)",
            "policy": "ClusterFailoverResourcesAdmissionControlPolicy",
            "unreserved_slots": 12,
            "total_slots": 20,
            "effective_hosts": 3,
            "host_monitoring": "enabled",
        }],
        "note": "",
    }
    with patch("app.services.virt_db_query.list_clusters_db", return_value=db_pack), \
         patch("app.services.virt_scope.resolve_scope") as rs, \
         patch("app.services.vcenter_vm_performance.fetch_cluster_status") as live:
        rs.return_value = MagicMock(filters={"cluster": "Prod-Cluster"})
        out = h_cluster_ha_drs(db, "Prod-Cluster HA ve DRS durumu nedir?")
    assert "DB" in out or "virt_clusters" in out
    assert "Prod-Cluster" in out
    assert "esx-prod-01" in out
    assert "Failover kapasitesi var" in out
    live.assert_not_called()


def test_hierarchy_does_not_invent_ips():
    db = MagicMock()
    with patch("app.services.virt_db_query.list_clusters_db", return_value={
        "clusters": [{
            "name": "Prod-Cluster",
            "host_names": ["esx-prod-01", "esx-prod-02"],
            "ha_enabled": True,
        }],
    }), patch("app.services.virt_db_query.list_esx_hosts_db", return_value={
        "hosts": [
            {"name": "esx-prod-01", "cluster": "Prod-Cluster"},
            {"name": "esx-prod-02", "cluster": "Prod-Cluster"},
        ],
    }), patch("app.services.virt_db_query.list_vms_db", return_value={
        "vms": [
            {"name": "app1", "esxi_host": "esx-prod-01", "cluster": "Prod-Cluster"},
            {"name": "app2", "esxi_host": "esx-prod-02", "cluster": "Prod-Cluster"},
        ],
    }), patch("app.services.virt_scope.resolve_scope") as rs:
        rs.return_value = MagicMock(filters={})
        out = h_inventory_hierarchy(db, "hiyerarşi özetle")
    assert "esx-prod-01" in out
    assert "192.168.1.102" not in out
    assert "app1" in out
