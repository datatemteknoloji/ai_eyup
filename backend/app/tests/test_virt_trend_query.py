"""
Trend motoru sözleşmesi: eşanlamlı giriş normalizasyonu ve SQL enjeksiyon
yüzeyinin whitelist ile kapalı olması.

`metric` / `entity_type` değerleri kolon ve tablo adı olarak SQL'e girdiği için
serbest metin ASLA doğrudan geçmemeli — model bu alanları kendi doldurur.
"""
import pytest

from app.services.virt_trend_query import (
    _ENTITIES, _canon_entity, _canon_metric, _default_metric,
)


@pytest.mark.parametrize("raw,expected", [
    ("host", "host"), ("ESXi", "host"), ("hypervisor", "host"),
    ("vm", "vm"), ("VMs", "vm"), ("sanal", "vm"),
    ("datastore", "datastore"), ("ds", "datastore"), ("depolama", "datastore"),
    (None, "host"), ("saçma_şey", "host"),
])
def test_entity_normalization(raw, expected):
    assert _canon_entity(raw) == expected


@pytest.mark.parametrize("entity,raw,expected", [
    ("host", "cpu", "cpu_pct"),
    ("host", "RAM", "mem_pct"),
    ("host", "mem_usage_pct", "mem_pct"),
    ("vm", "cpu ready", "cpu_ready_pct"),
    ("vm", "latency", "disk_latency_ms"),
    ("datastore", "doluluk", "usage_pct"),
    ("datastore", "free", "free_gb"),
])
def test_metric_aliases(entity, raw, expected):
    assert _canon_metric(entity, raw) == expected


def test_unknown_metric_falls_back_to_default_not_raw_sql():
    injected = "usage_pct; DROP TABLE virt_vm_metrics --"
    canon = _canon_metric("datastore", injected)
    assert canon in (None, *_ENTITIES["datastore"]["metrics"])
    resolved = canon or _default_metric("datastore")
    assert resolved in _ENTITIES["datastore"]["metrics"]


def test_every_metric_maps_to_declared_column():
    for entity, spec in _ENTITIES.items():
        for key, (column, unit, threshold) in spec["metrics"].items():
            assert column.replace("_", "").isalnum(), (entity, key)
            assert unit
