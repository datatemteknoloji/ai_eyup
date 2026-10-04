"""Zabbix metric map + monitoring unit tests (no live API)."""
from app.services.zabbix_metric_map import (
    catalog,
    get_metric,
    match_item_to_metrics,
    pick_best_item,
    resolve_metric_id,
)


def test_catalog_has_core_os_metrics():
    ids = {m["id"] for m in catalog()}
    assert "cpu_util" in ids
    assert "mem_used_pct" in ids
    assert "fs_used_pct" in ids
    assert "agent_ping" in ids


def test_resolve_metric_aliases():
    assert resolve_metric_id("cpu_util") == "cpu_util"
    assert resolve_metric_id("CPU kullanımı") == "cpu_util"
    assert resolve_metric_id("ram") == "mem_used_pct"
    assert resolve_metric_id("disk doluluk") == "fs_used_pct"
    assert resolve_metric_id("unknown_xyz") is None


def test_match_item_keys():
    hits = match_item_to_metrics("system.cpu.util[,avg1]")
    assert any(m.id == "cpu_util" for m in hits)
    hits2 = match_item_to_metrics("vfs.fs.size[/,pused]")
    assert any(m.id == "fs_used_pct" for m in hits2)
    assert match_item_to_metrics("totally.unknown.metric") == []


def test_zabbix7_keys_and_pfree_transform():
    assert any(m.id == "swap_used_pct" for m in match_item_to_metrics("system.swap.size[,pfree]"))
    assert any(m.id == "fs_used_pct" for m in match_item_to_metrics("vfs.fs.dependent.size[/,pfree]"))
    assert any(m.id == "disk_read_rate" for m in match_item_to_metrics("vfs.dev.read.rate[sda]"))
    assert any(m.id == "disk_write_rate" for m in match_item_to_metrics("vfs.dev.write.rate[vda]"))
    m = get_metric("swap_used_pct")
    assert m is not None
    assert m.transform_value(25.0, "system.swap.size[,pfree]") == 75.0
    assert m.transform_value(40.0, "system.swap.size[,pused]") == 40.0
    fs = get_metric("fs_used_pct")
    assert fs is not None
    assert fs.transform_value(18.0, "vfs.fs.dependent.size[/,pfree]") == 82.0


def test_pick_best_item_prefers_root_fs():
    m = get_metric("fs_used_pct")
    items = [
        {"key_": "vfs.fs.size[/var,pused]", "value_type": "0", "lastvalue": "40"},
        {"key_": "vfs.fs.size[/,pused]", "value_type": "0", "lastvalue": "70"},
    ]
    best = pick_best_item(items, m)
    assert best is not None
    assert best["key_"] == "vfs.fs.size[/,pused]"


def test_run_zabbix_query_catalog_mode():
    from app.services.zabbix_monitoring import run_zabbix_query

    out = run_zabbix_query(mode="catalog")
    assert out["ok"] is True
    assert out["source_kind"] == "zabbix"
    assert len(out["catalog"]) >= 10
