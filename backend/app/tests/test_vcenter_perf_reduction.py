"""Host/datastore performans sayaçlarının instance kırılımından indirgenmesi.

İki gerçek hata bu dosyada sabitlenir:

1. Host `disk.*` sayaçları vCenter'da YALNIZCA cihaz başına (naa.../t10.NVMe...)
   yayınlanır; toplam (instance="") satırı yoktur. Sorgu instance="" ile
   yapıldığı sürece disk IOPS/gecikme kolonları sessizce NULL kalır.
2. Datastore entity sorgusu, veri olmasa bile tüm anahtarları None olan bir
   satır döner. Bu satır "dolu" sayılırsa host üzerinden yapılan fallback hiç
   çalışmaz ve datastore IOPS/gecikme kolonları da NULL kalır.

Ayrıca gecikmenin cihazlar arası TOPLANMAMASI kritik: toplama, olmayan bir
darboğaz uydurur (4 LUN × 5 ms = 20 ms).
"""
from app.services.vmware.vcenter_client import (
    VCenterClient, _ds_uuid_from_url, _reduce_instances,
)


# ── instance indirgeme ──────────────────────────────────────────────────────
def test_iops_sums_across_devices():
    per_inst = {"naa.1": [10.0], "naa.2": [28.0]}
    assert _reduce_instances(per_inst, "sum") == 38.0


def test_latency_takes_worst_device_not_sum():
    per_inst = {"naa.1": [5.0], "naa.2": [61.0], "naa.3": [3.0]}
    assert _reduce_instances(per_inst, "max") == 61.0


def test_aggregate_row_wins_over_device_rows_to_avoid_double_count():
    """instance="*" hem toplam hem cihaz satırı döndürürse iki kat saymamalı."""
    per_inst = {"": [100.0], "vmnic0": [60.0], "vmnic1": [40.0]}
    assert _reduce_instances(per_inst, "sum") == 100.0


def test_single_aggregate_row_is_used_as_is():
    assert _reduce_instances({"": [22.5]}, "sum") == 22.5


def test_scale_is_applied_for_kb_to_mb_counters():
    assert _reduce_instances({"": [31_289_242.0]}, "sum", 1.0 / 1024.0) == 30555.9


def test_no_samples_returns_none_not_zero():
    """0.0 'ölçüldü ve sıfırdı' demek; ölçülmeyen sayaç None kalmalı."""
    assert _reduce_instances({}, "sum") is None
    assert _reduce_instances({}, "max") is None


def test_multiple_samples_of_one_instance_are_summed_first():
    assert _reduce_instances({"naa.1": [2.0, 3.0], "naa.2": [1.0]}, "sum") == 6.0
    assert _reduce_instances({"naa.1": [2.0, 3.0], "naa.2": [9.0]}, "max") == 9.0


# ── slot tablosu sözleşmesi ─────────────────────────────────────────────────
def test_host_disk_slots_query_all_instances_and_latency_uses_max():
    slots = {s[1]: s for s in VCenterClient._HOST_PERF_SLOTS}
    for key in ("disk_read_iops", "disk_write_iops", "disk_latency_ms",
                "disk_device_latency_ms"):
        assert slots[key][3] == "*", f"{key} cihaz başına sorgulanmalı"
    assert slots["disk_read_iops"][4] == "sum"
    assert slots["disk_write_iops"][4] == "sum"
    assert slots["disk_latency_ms"][4] == "max"
    assert slots["disk_device_latency_ms"][4] == "max"


def test_host_net_and_mem_slots_use_aggregate_instance():
    slots = {s[1]: s for s in VCenterClient._HOST_PERF_SLOTS}
    for key in ("net_rx_kbps", "net_tx_kbps", "mem_balloon_mb", "mem_swap_used_mb",
                "cpu_ready_ms"):
        assert slots[key][3] == "", f"{key} toplam satırından okunmalı"


# ── datastore UUID eşlemesi ─────────────────────────────────────────────────
def test_ds_uuid_extracted_from_vmfs_url():
    url = "ds:///vmfs/volumes/64d4ed96-b7825a44-6818-e4115bae6666/"
    assert _ds_uuid_from_url(url) == "64d4ed96-b7825a44-6818-e4115bae6666"


def test_ds_uuid_handles_missing_url():
    assert _ds_uuid_from_url(None) is None
    assert _ds_uuid_from_url("") is None


# ── boş satır tespiti + host fallback ───────────────────────────────────────
class _StubClient:
    """Yalnız zenginleştirme akışını izole eden sahte istemci."""
    _DS_PERF_SLOTS = VCenterClient._DS_PERF_SLOTS
    _enrich_datastore_perf = VCenterClient._enrich_datastore_perf

    def __init__(self, entity_result, host_result):
        self._entity_result = entity_result
        self._host_result = host_result
        self.host_called_with = None

    def query_datastore_perf(self, refs):
        return self._entity_result

    def _datastore_perf_via_hosts(self, host_refs):
        self.host_called_with = host_refs
        return self._host_result


_ROWS = [
    {"ref": "datastore-11", "name": "datastore1",
     "ds_uuid": "64d4e59c-cbd6f198-c321-e4115bae6666"},
]
_HOST_PERF = {
    "64d4e59c-cbd6f198-c321-e4115bae6666": {
        "read_iops": 62.0, "write_iops": 85.0,
        "read_latency_ms": 11.0, "write_latency_ms": 71.0,
    },
}


def test_all_none_entity_row_triggers_host_fallback():
    blank = {"datastore-11": {"read_iops": None, "write_iops": None,
                              "read_latency_ms": None, "write_latency_ms": None}}
    rows = [dict(r) for r in _ROWS]
    c = _StubClient(blank, _HOST_PERF)
    c._enrich_datastore_perf(rows, ["host-8"])
    assert c.host_called_with == ["host-8"]
    assert rows[0]["read_iops"] == 62.0
    assert rows[0]["write_latency_ms"] == 71.0


def test_real_entity_data_is_not_overwritten_by_fallback():
    real = {"datastore-11": {"read_iops": 5.0, "write_iops": 6.0,
                             "read_latency_ms": 1.0, "write_latency_ms": 2.0}}
    rows = [dict(r) for r in _ROWS]
    c = _StubClient(real, _HOST_PERF)
    c._enrich_datastore_perf(rows, ["host-8"])
    assert c.host_called_with is None          # fallback'e hiç gerek yok
    assert rows[0]["read_iops"] == 5.0


def test_without_mount_hosts_enrichment_is_skipped_quietly():
    blank = {"datastore-11": {"read_iops": None}}
    rows = [dict(r) for r in _ROWS]
    c = _StubClient(blank, _HOST_PERF)
    c._enrich_datastore_perf(rows, [])
    assert "read_iops" not in rows[0]          # uydurma değer yazılmaz


def test_entity_query_failure_still_allows_host_fallback():
    class _Boom(_StubClient):
        def query_datastore_perf(self, refs):
            raise RuntimeError("QueryPerf HTTP 500")

    rows = [dict(r) for r in _ROWS]
    c = _Boom({}, _HOST_PERF)
    c._enrich_datastore_perf(rows, ["host-8"])
    assert rows[0]["read_iops"] == 62.0
