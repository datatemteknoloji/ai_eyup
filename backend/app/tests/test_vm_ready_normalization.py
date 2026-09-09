"""VM `cpu_ready_pct` normalizasyonu (vCPU başına).

`cpu.ready.summation` sayacı VM'in TÜM vCPU'larının toplam bekleme süresidir.
vCPU sayısına bölünmezse 8 vCPU'lu bir VM'de %9'luk gerçek çekişme %75 gibi
görünür; darboğaz teşhisi (eşik %5) bunu "VM'e fazla vCPU verilmiş" diye
yorumlar ve yanlış aksiyon önerir. Canlı yol (`vcenter_vm_performance`) ve host
tarafı zaten vCPU/thread sayısına normalize ediyordu — zaman serisi etmiyordu.
"""
import pytest

from app.services.metric_sync import _write_vm_metric_rows


class _FakeServer:
    def __init__(self, vcpu, name="app01"):
        self.id = 1
        self.name = name
        self.vm_name = name
        self.vm_cpu_count = vcpu
        self.vm_host_name = "esxi01"
        self.vm_cluster = "cl1"
        self.vm_datastore = "ds1"
        self.vm_power_state = "poweredOn"
        self.vm_memory_mb = 8192


class _FakeDb:
    def __init__(self):
        self.rows = []

    def bulk_insert_mappings(self, model, rows):
        self.rows.extend(rows)

    def commit(self):
        pass


def _run(vcpu, ready_ms, *, stats_num_cpu=None, extra_io=None):
    db = _FakeDb()
    stats = {"cpu_usage_pct": 10.0, "mem_usage_pct": 20.0}
    if stats_num_cpu is not None:
        stats["num_cpu"] = stats_num_cpu
    io = {"cpu_ready_ms": ready_ms}
    io.update(extra_io or {})
    _write_vm_metric_rows(
        db, 2, [(_FakeServer(vcpu), stats, "vm-101")], {"vm-101": io}, "2026-09-09T00:00:00",
    )
    return db.rows[0]


@pytest.mark.parametrize("vcpu,ready_ms,expected", [
    (1, 200.0, 1.0),      # 20 sn örnekte 200 ms → %1
    (4, 200.0, 0.25),
    (8, 15046.0, 9.4),    # ham bölme %75 verirdi
])
def test_ready_pct_is_divided_by_vcpu_count(vcpu, ready_ms, expected):
    assert _run(vcpu, ready_ms)["cpu_ready_pct"] == expected


def test_raw_ready_ms_is_preserved_unnormalized():
    """Ham sayaç saklanmaya devam etmeli — normalizasyon yalnız yüzdededir."""
    row = _run(8, 15046.0)
    assert row["cpu_ready_ms"] == 15046.0


def test_missing_vcpu_falls_back_to_one_and_does_not_crash():
    row = _run(None, 400.0)
    assert row["cpu_ready_pct"] == 2.0
    assert row["num_cpu"] is None


def test_vcpu_from_live_stats_is_used_when_inventory_is_empty():
    row = _run(None, 400.0, stats_num_cpu=4)
    assert row["cpu_ready_pct"] == 0.5
    assert row["num_cpu"] == 4


def test_no_ready_counter_leaves_percentage_none():
    row = _run(4, None)
    assert row["cpu_ready_pct"] is None


# ── balloon yedek kaynağı ───────────────────────────────────────────────────
def test_balloon_falls_back_to_perf_counter_when_quickstats_missing():
    """quickStats.balloonedMemory dönmezse mem.vmmemctl (KB) kullanılır."""
    row = _run(4, 100.0, extra_io={"mem_balloon_kb": 5_294_704.0})
    assert row["balloon_mb"] == 5170.61


def test_quickstats_balloon_wins_over_perf_counter():
    db = _FakeDb()
    _write_vm_metric_rows(
        db, 2,
        [(_FakeServer(4), {"ballooned_mb": 100.0}, "vm-101")],
        {"vm-101": {"mem_balloon_kb": 5_294_704.0}},
        "2026-09-09T00:00:00",
    )
    assert db.rows[0]["balloon_mb"] == 100.0
