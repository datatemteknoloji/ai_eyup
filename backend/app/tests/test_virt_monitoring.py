"""Virt monitoring: aralık / whitelist / boş seri (DB yok)."""
import pytest

from app.services.virt_monitoring import (
    MAX_SERIES_OBJECTS,
    RANGE_SPEC,
    _build_summary,
    _hv_sql,
    _metric_column,
    bucket_for_window,
    metric_catalog,
    parse_hypervisor_ids,
    parse_names,
    parse_range,
    query_series,
)


def test_range_keys_match_ui_contract():
    assert list(RANGE_SPEC) == [
        "15m", "30m", "1h", "2h", "8h", "24h", "7d", "30d", "60d",
    ]
    assert parse_range("8h") == "8h"
    assert parse_range("nope") == "8h"
    assert parse_range(None) == "8h"


def test_bucket_for_window_does_not_round_ten_days_to_thirty():
    assert bucket_for_window(60) is None
    assert bucket_for_window(24 * 60) is None
    assert bucket_for_window(10 * 24 * 60) == "1 hour"
    assert bucket_for_window(14 * 24 * 60) == "1 hour"
    assert bucket_for_window(15 * 24 * 60) == "4 hours"
    assert bucket_for_window(90 * 24 * 60) == "12 hours"


def test_hypervisor_ids_parse_and_scope():
    assert parse_hypervisor_ids() is None
    assert parse_hypervisor_ids(hypervisor_ids="") == []
    assert parse_hypervisor_ids(hypervisor_ids="2, 2, 9") == [2, 9]
    assert parse_hypervisor_ids(3, "3,4") == [3, 4]
    clause, params = _hv_sql([4, 9])
    assert clause == "hypervisor_id IN (:hvf0, :hvf1)"
    assert params == {"hvf0": 4, "hvf1": 9}
    assert _hv_sql([]) == ("FALSE", {})
    assert _hv_sql(None) == ("TRUE", {})


def test_parse_names_caps_and_dedupes():
    names = parse_names("a,b,a,c,d,e,f,g,h,i,j")
    assert names == ["a", "b", "c", "d", "e", "f", "g", "h"]
    assert len(names) == MAX_SERIES_OBJECTS


def test_metric_whitelist_rejects_injection():
    with pytest.raises(ValueError):
        _metric_column("host", "cpu_pct; DROP TABLE hypervisor_host_metrics")
    with pytest.raises(ValueError):
        _metric_column("vm", "not_a_metric")
    with pytest.raises(ValueError):
        _metric_column("pod", "cpu_pct")
    entity, col, unit = _metric_column("host", "cpu_ready_pct")
    assert entity == "host" and col == "cpu_ready_pct" and unit == "%"


def test_catalog_covers_esxi_and_vm():
    host_ids = {m["id"] for m in metric_catalog("host")}
    vm_ids = {m["id"] for m in metric_catalog("vm")}
    assert {"cpu_pct", "mem_pct", "cpu_ready_pct", "disk_latency_ms"} <= host_ids
    assert {"cpu_pct", "cpu_ready_pct", "balloon_mb"} <= vm_ids


def test_empty_names_does_not_query(monkeypatch):
    called = []

    def boom(*_a, **_k):
        called.append(True)
        raise AssertionError("DB'ye gidilmemeli")

    monkeypatch.setattr("app.services.virt_monitoring._top_sql", boom)
    out = query_series(None, kind="host", names=[], metric="cpu_pct", range_key="8h")
    assert out["series"] == []
    assert called == []


def test_summary_mentions_vcenter_only():
    text = _build_summary(
        "Uyarı",
        {"healthy": 10, "warning": 2, "critical": 0, "unknown": 1},
        [{"severity": "warning"}],
        [{"title": "esx01: bellek %88", "affected_count": 12}],
        [{"name": "DS1", "current": 76, "days_to_80": 14, "risk": "warning"}],
    )
    assert "vCenter" in text
    assert "Prometheus" in text
    assert "esx01" in text
