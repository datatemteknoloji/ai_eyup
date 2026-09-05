"""report_engine.py — Kapasite Raporu datastore kapasite entegrasyonu.

Regresyon: `generate_capacity_report()` datastore bazında kırılımda yalnızca
VM'lerin `disk_gb` (provisioned/tahsis) toplamını gösteriyordu — datastore'un
GERÇEK vCenter kapasitesi (toplam/boş/doluluk %) hiç yoktu. Bu, host aggregate
doluluk düşük görünürken tek bir datastore'un aslında kritik (>=%80) dolu
olduğu durumları gizliyordu (bkz. üretim bulgusu: host disk %54.2 iken
"datastore2" tek başına %87.8 doluydu ama rapor bunu hiç söylemiyordu).

Bu testler:
  - `_datastore_capacity_index`: virt_datastores'tan isim→kapasite index'i
  - `generate_capacity_report`: ds_vm_breakdown'a capacity/free/usage_pct
    enjekte edilmesi + kritik/yüksek doluluk uyarıları
  - `format_report_as_markdown("capacity", ...)`: yeni kolonların tabloya
    yansıması
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest

from app.services import report_engine as engine


# ── _datastore_capacity_index ────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows: List[Any]):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    """SELECT sorgusuna göre farklı sahte sonuç döndüren minimal Session taklidi."""

    def __init__(self, *, datastore_rows=None, trend_rows=None, series_rows=None):
        self.datastore_rows = datastore_rows or []
        self.trend_rows = trend_rows or []
        self.series_rows = series_rows if series_rows is not None else {}

    def execute(self, clause, params=None):
        sql = str(clause).strip().lower()
        if "from virt_datastores" in sql:
            return _FakeResult(self.datastore_rows)
        if "group by host_name" in sql:
            return _FakeResult(self.trend_rows)
        if "from hypervisor_host_metrics" in sql and "order by timestamp asc" in sql:
            host = (params or {}).get("host")
            return _FakeResult(self.series_rows.get(host, []))
        return _FakeResult([])


def _ds_row(name, capacity_gb=1000.0, free_gb=500.0, used_gb=500.0, usage_pct=50.0, accessible=True):
    return SimpleNamespace(
        name=name, capacity_gb=capacity_gb, free_gb=free_gb,
        used_gb=used_gb, usage_pct=usage_pct, accessible=accessible,
    )


def test_datastore_capacity_index_basic():
    db = _FakeDB(datastore_rows=[
        _ds_row("NVME_DS", capacity_gb=2980.5, free_gb=2022.5, usage_pct=32.1),
        _ds_row("datastore2", capacity_gb=2794.2, free_gb=339.6, usage_pct=87.8),
    ])
    idx = engine._datastore_capacity_index(db)
    assert set(idx.keys()) == {"nvme_ds", "datastore2"}
    assert idx["datastore2"]["usage_pct"] == 87.8
    assert idx["datastore2"]["free_gb"] == 339.6


def test_datastore_capacity_index_handles_missing_table():
    class _BrokenDB:
        def execute(self, *a, **k):
            raise RuntimeError("relation does not exist")
    assert engine._datastore_capacity_index(_BrokenDB()) == {}


def test_datastore_capacity_index_skips_blank_names():
    db = _FakeDB(datastore_rows=[_ds_row(""), _ds_row(None), _ds_row("ok_ds")])
    idx = engine._datastore_capacity_index(db)
    assert list(idx.keys()) == ["ok_ds"]


# ── generate_capacity_report: gerçek kapasite + uyarılar ─────────────────────

def test_generate_capacity_report_merges_real_datastore_capacity(monkeypatch):
    host_metrics = [{
        "host": "esx01", "hypervisor_id": 1, "cpu_pct": 13.5, "cpu_cores": 8,
        "mem_pct": 40.0, "mem_used_gb": 40.0, "mem_total_gb": 100.0, "mem_free_gb": 60.0,
        "ds_pct": 54.2, "ds_used_gb": 500.0, "ds_total_gb": 1000.0, "ds_free_gb": 500.0,
        "vms_running": 3, "vms_total": 3,
    }]
    vms = [
        {"name": "vm1", "datastore": "datastore2", "disk_gb": 100.0,
         "power_state": "poweredOn", "cluster": "", "hypervisor": "hv1"},
        {"name": "vm2", "datastore": "datastore2", "disk_gb": 200.0,
         "power_state": "poweredOn", "cluster": "", "hypervisor": "hv1"},
        {"name": "vm3", "datastore": "NVME_DS", "disk_gb": 50.0,
         "power_state": "poweredOff", "cluster": "", "hypervisor": "hv1"},
    ]

    monkeypatch.setattr(engine, "_latest_host_metrics", lambda db: host_metrics)
    monkeypatch.setattr(engine, "_get_vms", lambda db: vms)
    monkeypatch.setattr(engine, "_datastore_capacity_index", lambda db: {
        "datastore2": {"capacity_gb": 2794.2, "free_gb": 339.6, "used_gb": 2454.6,
                       "usage_pct": 87.8, "accessible": True},
        "nvme_ds": {"capacity_gb": 2980.5, "free_gb": 2022.5, "used_gb": 958.0,
                    "usage_pct": 32.1, "accessible": True},
    })

    db = _FakeDB()
    result = engine.generate_capacity_report(db)

    ds_breakdown = result["datastore_vm_disk"]
    assert ds_breakdown["datastore2"]["usage_pct"] == 87.8
    assert ds_breakdown["datastore2"]["free_gb"] == 339.6
    assert ds_breakdown["datastore2"]["allocated_disk_gb"] == 300.0  # VM tahsisi ayrı kalır
    assert ds_breakdown["NVME_DS"]["usage_pct"] == 32.1

    # Kritik doluluk (>=80) uyarısı üretilmeli — host aggregate (%54.2) bunu
    # göstermese bile.
    assert any("datastore2" in w and "%87.8" in w for w in result["warnings"])
    # NVME_DS %32.1 uyarı eşiğinin altında — uyarı üretilmemeli.
    assert not any("NVME_DS" in w for w in result["warnings"])


def test_generate_capacity_report_without_live_datastore_data_falls_back(monkeypatch):
    """virt_datastores boşsa (sync hiç çalışmamış) eski davranış (yalnızca
    VM tahsisi) korunmalı — capacity/free/usage_pct alanları set edilmemeli,
    hata fırlatılmamalı."""
    monkeypatch.setattr(engine, "_latest_host_metrics", lambda db: [])
    monkeypatch.setattr(engine, "_get_vms", lambda db: [
        {"name": "vm1", "datastore": "ds1", "disk_gb": 10.0,
         "power_state": "poweredOn", "cluster": "", "hypervisor": "hv1"},
    ])
    monkeypatch.setattr(engine, "_datastore_capacity_index", lambda db: {})

    result = engine.generate_capacity_report(_FakeDB())
    entry = result["datastore_vm_disk"]["ds1"]
    assert entry["allocated_disk_gb"] == 10.0
    assert "usage_pct" not in entry
    assert result["warnings"] == []


# ── format_report_as_markdown("capacity") ────────────────────────────────────

def test_capacity_markdown_includes_real_capacity_columns():
    data = {
        "capacity_items": [],
        "warnings": ["Datastore 'datastore2' %87.8 dolu (KRİTİK, boş 339.6 GB) — 2 VM barındırıyor"],
        "datastore_vm_disk": {
            "datastore2": {
                "vm_count": 2, "allocated_disk_gb": 300.0,
                "capacity_gb": 2794.2, "free_gb": 339.6, "usage_pct": 87.8,
                "vms": [{"vm": "vm1", "disk_gb": 100.0, "power_state": "poweredOn"}],
            },
            "NVME_DS": {
                "vm_count": 1, "allocated_disk_gb": 50.0,
                "capacity_gb": 2980.5, "free_gb": 2022.5, "usage_pct": 32.1,
                "vms": [{"vm": "vm3", "disk_gb": 50.0, "power_state": "poweredOff"}],
            },
        },
    }
    md = engine.format_report_as_markdown("capacity", data)
    assert "Doluluk %" in md
    assert "%87.8" in md
    assert "339.6" in md
    assert "2794.2" in md
    assert "KRİTİK" in md
