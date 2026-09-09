"""Darboğaz teşhis kural motoru sözleşmesi.

Kritik olan tek metrik değil, VM+host ÇİFTİNİN birlikte değerlendirilmesi:
aynı VM CPU ready değeri, host doygunluğuna göre farklı katmanı suçlar ve
farklı aksiyon üretir ("host'a taşı" ↔ "vCPU'yu azalt"). Bu ayrım bozulursa
operatöre zıt öneri gider, o yüzden matris halinde sabitlenmiştir.
"""
import pytest

from app.services.virt_diagnostics import TH, _classify_row, classify_bottleneck


def _vm(**kw):
    base = {
        "vm_name": "app01", "host_name": "esxi01", "cluster_name": "cl1",
        "datastore": "ds1", "samples": 100, "cpu_avg": 20.0, "cpu_p95": 30.0,
        "mem_p95": 40.0, "ready_p95": 0.5, "costop_p95": 0.0, "dlat_p95": 2.0,
        "balloon_max": 0.0, "swapped_max": 0.0, "dropped_max": 0.0, "num_cpu": 4,
    }
    base.update(kw)
    return base


def _host(**kw):
    base = {
        "host_name": "esxi01", "cluster_name": "cl1", "samples": 100,
        "cpu_p95": 40.0, "mem_p95": 50.0, "ds_p95": 60.0, "ready_p95": 0.4,
        "dlat_p95": 3.0, "devlat_p95": 2.0, "swap_max": 0.0, "balloon_max": 0.0,
        "dropped_max": 0.0, "vms_running": 20, "cpu_threads": 48,
    }
    base.update(kw)
    return base


def _layers(result, resource):
    return [f["layer"] for f in result["findings"] if f["resource"] == resource]


# ── CPU ayrımı: aynı ready, host doygunluğuna göre farklı suçlu ─────────────
def test_high_ready_with_saturated_host_blames_host():
    res = _classify_row(_vm(ready_p95=12.0), _host(cpu_p95=95.0))
    assert res["primary_layer"] == "host"
    cpu = next(f for f in res["findings"] if f["resource"] == "cpu")
    assert cpu["layer"] == "host"
    # Ters öneri felaket olur: host doygunken vCPU eklemek çekişmeyi artırır.
    assert "EKLEMEYİN" in cpu["action"]
    assert cpu["evidence"]["host_cpu_p95"] == 95.0


def test_high_ready_with_idle_host_blames_vm_sizing():
    res = _classify_row(_vm(ready_p95=12.0), _host(cpu_p95=30.0))
    cpu = next(f for f in res["findings"] if f["resource"] == "cpu")
    assert cpu["layer"] == "vm"
    assert "düşür" in cpu["action"].lower()


def test_high_vm_cpu_without_ready_is_guest_workload():
    res = _classify_row(_vm(cpu_p95=97.0, ready_p95=0.3), _host(cpu_p95=45.0))
    assert _layers(res, "cpu") == ["guest"]


def test_costop_alone_flags_smp_contention():
    res = _classify_row(_vm(costop_p95=TH["cpu_costop_ms"] + 50, num_cpu=16), _host())
    cpu = next(f for f in res["findings"] if f["resource"] == "cpu")
    assert cpu["layer"] == "vm"
    assert cpu["evidence"]["vcpu"] == 16


# ── Bellek / depolama / ağ ──────────────────────────────────────────────────
def test_ballooning_with_full_host_memory_blames_host():
    res = _classify_row(_vm(balloon_max=512.0), _host(mem_p95=96.0))
    assert _layers(res, "memory") == ["host"]


def test_swapping_with_free_host_memory_stays_on_vm():
    res = _classify_row(_vm(swapped_max=128.0), _host(mem_p95=55.0))
    assert _layers(res, "memory") == ["vm"]


def test_shared_storage_latency_blames_datastore():
    res = _classify_row(_vm(dlat_p95=45.0), _host(dlat_p95=38.0))
    storage = next(f for f in res["findings"] if f["resource"] == "storage")
    assert storage["layer"] == "datastore"
    assert storage["evidence"]["datastore"] == "ds1"


def test_isolated_storage_latency_stays_on_vm():
    res = _classify_row(_vm(dlat_p95=45.0), _host(dlat_p95=2.0, devlat_p95=1.0))
    assert _layers(res, "storage") == ["vm"]


def test_packet_drops_follow_host_uplink_when_host_also_drops():
    assert _layers(_classify_row(_vm(dropped_max=9.0), _host(dropped_max=7.0)), "network") == ["host"]
    assert _layers(_classify_row(_vm(dropped_max=9.0), _host(dropped_max=0.0)), "network") == ["vm"]


# ── Gürültü kontrolü: eşik altı = bulgu yok, uydurma yok ────────────────────
def test_healthy_pair_reports_no_bottleneck():
    res = _classify_row(_vm(), _host())
    assert res["primary_layer"] == "none"
    assert len(res["findings"]) == 1
    assert "yok" in res["findings"][0]["verdict"]


def test_missing_host_series_does_not_crash_and_uses_vm_evidence_only():
    res = _classify_row(_vm(dlat_p95=60.0), None)
    storage = next(f for f in res["findings"] if f["resource"] == "storage")
    assert storage["layer"] == "vm"          # host kanıtı yok → host suçlanamaz
    assert storage["evidence"]["host_disk_latency_p95_ms"] is None


def test_none_metrics_are_never_treated_as_breach():
    """NULL kolon (sayaç henüz toplanmadı) darboğaz sanılmamalı."""
    blank = {k: None for k in _vm()}
    blank["vm_name"] = "yeni-vm"
    res = _classify_row(blank, None)
    assert res["primary_layer"] == "none"


def test_severity_ordering_puts_high_first():
    res = _classify_row(_vm(ready_p95=20.0, dlat_p95=80.0), _host(cpu_p95=93.0, dlat_p95=70.0))
    assert res["findings"][0]["severity"] == "high"
    assert res["primary_layer"] in ("host", "datastore")


# ── Girdi sınırlaması (SQL parametreleri) ───────────────────────────────────
class _FakeResult(list):
    pass


class _FakeDb:
    """execute çağrısının parametrelerini yakalar; satır döndürmez."""
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append(params or {})
        return _FakeResult()


@pytest.mark.parametrize("hours,expected", [
    (None, 24.0), (0, 24.0), (-5, 0.25), (10**6, 720.0), (48, 48.0),
])
def test_window_is_clamped(hours, expected):
    db = _FakeDb()
    out = classify_bottleneck(db, vm_name="app01", hours=hours)
    assert out["window_hours"] == expected
    assert db.calls[0]["hours"] == expected


def test_limit_is_clamped_and_name_becomes_bound_parameter():
    db = _FakeDb()
    classify_bottleneck(db, vm_name="app'; DROP TABLE virt_vm_metrics --", limit=999)
    params = db.calls[0]
    assert params["limit"] == 50
    # Ad SQL'e gömülmez, ILIKE parametresi olarak taşınır.
    assert params["vm"] == "%app'; DROP TABLE virt_vm_metrics --%"


def test_empty_series_returns_explanatory_note_not_error():
    out = classify_bottleneck(_FakeDb(), vm_name="yok-boyle-vm")
    assert out["ok"] is True
    assert out["items"] == []
    assert "bulunamadı" in out["note"]
