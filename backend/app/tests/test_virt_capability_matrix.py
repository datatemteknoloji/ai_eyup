"""Virt yetenek matrisi — konular 1–8, 11, 13 için araç/katalog varlığı.

Canlı vCenter yoksa bu testler yalnız kod yüzeyini doğrular (ortam cevabı değil).
"""
from app.services.agent.tools import TOOLS, _VC_PROPERTY_CATALOG
from app.services.virt_trend_query import _ENTITIES
from app.services.virt_scope import SCOPE_TOOL_ARGS, tool_args, Scope


# Konu → zorunlu tool veya katalog yüzeyi
_TOPIC_REQUIREMENTS = {
    "1_architecture": ["db_list_vms", "db_list_esx_hosts", "db_list_clusters", "db_list_datastores", "vcenter_property_read"],
    "2_cluster_ha_drs": ["db_list_clusters", "vcenter_property_read"],
    "3_compute": ["db_metric_trend", "vcenter_perf_query", "virt_bottleneck_diagnose"],
    "4_storage": ["db_list_datastores", "vcenter_property_read"],
    "5_networking": ["vcenter_property_read", "db_list_esx_hosts"],
    "6_vm_lifecycle": ["db_vm_detail", "vcenter_list_vm_snapshots", "vcenter_snapshot_summary"],
    "7_migration": ["vcenter_live_tasks", "db_list_critical_events"],
    "8_backup_dr": ["vcenter_list_vm_snapshots", "db_virt_alarms"],
    "11_monitoring": ["virt_health_overview", "db_virt_alarms", "vcenter_live_alarms", "vcenter_perf_query"],
    "13_troubleshooting": ["virt_bottleneck_diagnose", "db_list_clusters", "db_virt_alarms"],
}


def test_topic_tools_registered():
    for topic, names in _TOPIC_REQUIREMENTS.items():
        for n in names:
            assert n in TOOLS, f"{topic}: missing tool {n}"


def test_cluster_scope_wires_host_and_vm():
    assert SCOPE_TOOL_ARGS["host"].get("cluster") == "cluster"
    assert tool_args("host", Scope(filters={"cluster": "X"})) == {"cluster": "X"}
    assert tool_args("vm", Scope(filters={"cluster": "X"})) == {"cluster": "X"}


def test_esx_hosts_tool_declares_cluster_param():
    props = (TOOLS["db_list_esx_hosts"].parameters or {}).get("properties") or {}
    assert "cluster" in props


def test_monitoring_metric_catalogs_cover_timescale():
    assert len(_ENTITIES["vm"]["metrics"]) >= 18
    assert len(_ENTITIES["host"]["metrics"]) >= 15
    assert len(_ENTITIES["datastore"]["metrics"]) >= 8
    for key in ("cpu_pct", "cpu_ready_pct", "balloon_mb", "net_rx_kbps", "snapshot_count"):
        assert key in _ENTITIES["vm"]["metrics"]


def test_property_catalog_covers_ops_object_types():
    for ot in (
        "HostSystem",
        "ClusterComputeResource",
        "Datastore",
        "VirtualMachine",
        "Network",
        "DistributedVirtualSwitch",
        "ResourcePool",
    ):
        assert ot in _VC_PROPERTY_CATALOG
        assert len(_VC_PROPERTY_CATALOG[ot]) >= 5
