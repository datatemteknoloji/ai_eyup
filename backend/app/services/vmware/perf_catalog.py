"""vCenter PerformanceManager — geniş READ-ONLY counter kataloğu.

Katalog = menü (ne sorgulanabilir). Kullanıcıya dönüş = yalnızca istenen metrikler.
Write/set/mutate SOAP method'ları bu modülde YOKTUR; yalnız QueryPerf + property read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple


# SOAP / REST mutate — asistan bu method'ları ASLA çağırmaz (deny list belgesi)
SOAP_MUTATE_DENY = frozenset({
    "PowerOnVM_Task", "PowerOffVM_Task", "ResetVM_Task", "SuspendVM_Task",
    "Destroy_Task", "DestroyPropertyFilter", "Rename_Task",
    "ReconfigVM_Task", "MigrateVM_Task", "RelocateVM_Task", "CloneVM_Task",
    "CreateVM_Task", "RegisterVM_Task", "UnregisterVM_Task",
    "EnterMaintenanceMode_Task", "ExitMaintenanceMode_Task",
    "ReconnectHost_Task", "DisconnectHost_Task", "RebootHost_Task",
    "ShutdownHost_Task", "CreateSnapshot_Task", "RemoveSnapshot_Task",
    "RevertToSnapshot_Task", "DeleteDatastoreFile_Task",
    "MakeDirectory", "DeleteFile", "MoveDatastoreFile_Task",
    "ExtendDatastore_Task", "CreateClusterEx", "AddHost_Task",
    "SetCustomValue", "ReconfigureComputeResource_Task",
})

# İzinli read yüzeyleri (bilgi / dokümantasyon)
SOAP_READ_ALLOW = frozenset({
    "RetrieveProperties", "RetrievePropertiesEx", "QueryPerf",
    "QueryPerfCounter", "QueryAvailablePerfMetric", "QueryPerfProviderSummary",
    "RetrieveServiceContent", "Login", "Logout", "FindByInventoryPath",
    "FindByDnsName", "FindByIp", "FindByUuid", "CurrentTime",
    # Jenerik property okuma katmanı (ContainerView) — envanteri değiştirmez,
    # yalnızca oturuma bağlı geçici görünüm nesnesi oluşturur/kapatır.
    "CreateContainerView", "DestroyView",
    # HA slot / failover kapasitesi okuma (admission control analizi)
    "RetrieveDasAdvancedRuntimeInfo",
    # Event / alarm okuma
    "CreateCollectorForEvents", "DestroyCollector", "SetCollectorPageSize",
    "ReadPreviousEvents", "QueryEvents", "GetAlarmState", "QueryDescriptions",
})


@dataclass(frozen=True)
class PerfMetricDef:
    """Kanonik metrik → vSphere counter üçlüsü."""
    key: str
    group: str
    name: str
    rollup: str
    entity: str  # host | vm | both
    unit: str
    aliases: Tuple[str, ...]
    description: str = ""


# Geniş menü — Monitor Overview benzeri isimler dahil
PERF_METRICS: Tuple[PerfMetricDef, ...] = (
    # ── Host / VM CPU ──────────────────────────────────────────────────────
    PerfMetricDef(
        "cpu_usage_pct", "cpu", "usage", "average", "both", "percent",
        ("cpu", "cpu_usage", "cpu_pct", "cpu_percent", "cpu usage"),
        "CPU kullanım %",
    ),
    PerfMetricDef(
        "cpu_usage_mhz", "cpu", "usagemhz", "average", "both", "MHz",
        ("cpu_mhz", "usagemhz"),
        "CPU kullanım MHz",
    ),
    PerfMetricDef(
        "cpu_ready_ms", "cpu", "ready", "summation", "vm", "ms",
        ("cpu_ready", "ready", "cpu ready"),
        "CPU ready (contention)",
    ),
    # ── Memory ─────────────────────────────────────────────────────────────
    PerfMetricDef(
        "mem_usage_pct", "mem", "usage", "average", "both", "percent",
        ("mem", "memory", "ram", "mem_pct", "memory_pct", "mem usage"),
        "Bellek kullanım %",
    ),
    PerfMetricDef(
        "mem_active_kb", "mem", "active", "average", "both", "KB",
        ("mem_active", "active_mem"),
        "Aktif bellek KB",
    ),
    PerfMetricDef(
        "mem_consumed_kb", "mem", "consumed", "average", "both", "KB",
        ("mem_consumed", "consumed"),
        "Tüketilen bellek KB",
    ),
    # ── Host physical disk (Monitor: Disk Rate / Disk Requests) ─────────────
    PerfMetricDef(
        "disk_read_kbps", "disk", "read", "average", "host", "KBps",
        ("disk_rate_read", "disk_read", "disk rate read", "read kbps"),
        "Disk okuma hızı (Monitor Disk Rate read)",
    ),
    PerfMetricDef(
        "disk_write_kbps", "disk", "write", "average", "host", "KBps",
        ("disk_rate_write", "disk_write", "disk rate write", "write kbps", "disk_rate"),
        "Disk yazma hızı (Monitor Disk Rate write)",
    ),
    PerfMetricDef(
        "disk_read_requests", "disk", "numberReadAveraged", "average", "host", "number",
        ("disk_requests_read", "number_read", "disk requests read", "read requests"),
        "Disk okuma istekleri (Monitor Disk Requests read)",
    ),
    PerfMetricDef(
        "disk_write_requests", "disk", "numberWriteAveraged", "average", "host", "number",
        ("disk_requests_write", "number_write", "disk requests write", "write requests", "disk_requests"),
        "Disk yazma istekleri (Monitor Disk Requests write)",
    ),
    PerfMetricDef(
        "disk_total_latency_ms", "disk", "totalLatency", "average", "both", "ms",
        ("disk_latency", "total_latency", "disk latency"),
        "Disk toplam gecikme ms",
    ),
    # ── VM virtualDisk ─────────────────────────────────────────────────────
    PerfMetricDef(
        "vdisk_read_iops", "virtualDisk", "numberReadAveraged", "average", "vm", "number",
        ("vdisk_read", "virtual_disk_read", "disk_read_iops", "vm_disk_read"),
        "VM virtualDisk okuma IOPS",
    ),
    PerfMetricDef(
        "vdisk_write_iops", "virtualDisk", "numberWriteAveraged", "average", "vm", "number",
        ("vdisk_write", "virtual_disk_write", "disk_write_iops", "vm_disk_write"),
        "VM virtualDisk yazma IOPS",
    ),
    PerfMetricDef(
        "vdisk_read_latency_ms", "virtualDisk", "totalReadLatency", "average", "vm", "ms",
        ("vdisk_read_lat", "disk_read_latency"),
        "VM virtualDisk okuma latency",
    ),
    PerfMetricDef(
        "vdisk_write_latency_ms", "virtualDisk", "totalWriteLatency", "average", "vm", "ms",
        ("vdisk_write_lat", "disk_write_latency"),
        "VM virtualDisk yazma latency",
    ),
    # ── Datastore ──────────────────────────────────────────────────────────
    PerfMetricDef(
        "ds_read_latency_ms", "datastore", "totalReadLatency", "average", "both", "ms",
        ("datastore_read_latency", "ds_read_lat"),
        "Datastore okuma latency",
    ),
    PerfMetricDef(
        "ds_write_latency_ms", "datastore", "totalWriteLatency", "average", "both", "ms",
        ("datastore_write_latency", "ds_write_lat"),
        "Datastore yazma latency",
    ),
    # ── Network ────────────────────────────────────────────────────────────
    PerfMetricDef(
        "net_rx_kbps", "net", "bytesRx", "average", "both", "KBps",
        ("net_rx", "network_rx", "bytes_rx", "net receive"),
        "Ağ alış KBps",
    ),
    PerfMetricDef(
        "net_tx_kbps", "net", "bytesTx", "average", "both", "KBps",
        ("net_tx", "network_tx", "bytes_tx", "net transmit", "net"),
        "Ağ gönderim KBps",
    ),
    PerfMetricDef(
        "net_dropped_rx", "net", "droppedRx", "summation", "both", "number",
        ("net_drop_rx", "dropped_rx", "paket_kaybi_rx", "droppedrx"),
        "Düşürülen alış paketi — ağ problemi göstergesi",
    ),
    PerfMetricDef(
        "net_dropped_tx", "net", "droppedTx", "summation", "both", "number",
        ("net_drop_tx", "dropped_tx", "paket_kaybi_tx", "droppedtx"),
        "Düşürülen gönderim paketi — ağ problemi göstergesi",
    ),
    # ── Bellek baskısı (ballooning / swap) ─────────────────────────────────
    PerfMetricDef(
        "mem_balloon_kb", "mem", "vmmemctl", "average", "both", "KB",
        ("balloon", "ballooning", "vmmemctl", "mem_balloon"),
        "Balloon (vmmemctl) — host RAM baskısı göstergesi",
    ),
    PerfMetricDef(
        "mem_swapin_rate_kbps", "mem", "swapinRate", "average", "both", "KBps",
        ("swapin", "swap_in", "swapinrate"),
        "Swap-in hızı — kritik bellek baskısı",
    ),
    PerfMetricDef(
        "mem_swapout_rate_kbps", "mem", "swapoutRate", "average", "both", "KBps",
        ("swapout", "swap_out", "swapoutrate"),
        "Swap-out hızı — kritik bellek baskısı",
    ),
    # ── CPU contention ─────────────────────────────────────────────────────
    PerfMetricDef(
        "cpu_costop_ms", "cpu", "costop", "summation", "vm", "ms",
        ("costop", "co_stop", "cpu_costop"),
        "CPU co-stop (fazla vCPU / SMP contention)",
    ),
    # ── Host storage latency ayrıştırma (device / kernel / queue) ──────────
    # Bu üçlü "problem array'de mi, host'ta mı" ayrımını deterministik yapar:
    # device yüksek → storage array; queue yüksek → host HBA doygun;
    # kernel yüksek → host VMkernel darboğazı.
    PerfMetricDef(
        "disk_device_latency_ms", "disk", "deviceLatency", "average", "host", "ms",
        ("device_latency", "array_latency", "devicelatency"),
        "Fiziksel cihaz (array) gecikmesi",
    ),
    PerfMetricDef(
        "disk_kernel_latency_ms", "disk", "kernelLatency", "average", "host", "ms",
        ("kernel_latency", "kernellatency"),
        "VMkernel gecikmesi",
    ),
    PerfMetricDef(
        "disk_queue_latency_ms", "disk", "queueLatency", "average", "host", "ms",
        ("queue_latency", "queuelatency"),
        "Kuyruk gecikmesi (HBA doygunluğu)",
    ),
    # ── Datastore IOPS ─────────────────────────────────────────────────────
    PerfMetricDef(
        "ds_read_iops", "datastore", "numberReadAveraged", "average", "host", "number",
        ("datastore_read_iops", "ds_read_req"),
        "Datastore okuma IOPS",
    ),
    PerfMetricDef(
        "ds_write_iops", "datastore", "numberWriteAveraged", "average", "host", "number",
        ("datastore_write_iops", "ds_write_req"),
        "Datastore yazma IOPS",
    ),
)

# Monitor kısayol paketleri — kullanıcı "disk_rate" derse birden fazla counter
METRIC_BUNDLES: Dict[str, Tuple[str, ...]] = {
    "disk_rate": ("disk_read_kbps", "disk_write_kbps"),
    "disk_requests": ("disk_read_requests", "disk_write_requests"),
    "disk": ("disk_read_kbps", "disk_write_kbps", "disk_read_requests", "disk_write_requests", "disk_total_latency_ms"),
    "cpu": ("cpu_usage_pct", "cpu_usage_mhz", "cpu_ready_ms"),
    "mem": ("mem_usage_pct", "mem_active_kb", "mem_consumed_kb"),
    "memory": ("mem_usage_pct", "mem_active_kb", "mem_consumed_kb"),
    "net": ("net_rx_kbps", "net_tx_kbps", "net_dropped_rx", "net_dropped_tx"),
    "network": ("net_rx_kbps", "net_tx_kbps", "net_dropped_rx", "net_dropped_tx"),
    "vdisk": ("vdisk_read_iops", "vdisk_write_iops", "vdisk_read_latency_ms", "vdisk_write_latency_ms"),
    # Bellek baskısı teşhisi — "memory pressure yaşayan VM" sorusu
    "mem_pressure": ("mem_usage_pct", "mem_balloon_kb", "mem_swapin_rate_kbps", "mem_swapout_rate_kbps"),
    "memory_pressure": ("mem_usage_pct", "mem_balloon_kb", "mem_swapin_rate_kbps", "mem_swapout_rate_kbps"),
    # CPU contention teşhisi
    "contention": ("cpu_usage_pct", "cpu_ready_ms", "cpu_costop_ms"),
    "cpu_contention": ("cpu_usage_pct", "cpu_ready_ms", "cpu_costop_ms"),
    # Storage latency kaynak ayrıştırma (host)
    "latency_breakdown": (
        "disk_total_latency_ms", "disk_device_latency_ms",
        "disk_kernel_latency_ms", "disk_queue_latency_ms",
    ),
    "storage_latency": (
        "disk_total_latency_ms", "disk_device_latency_ms",
        "disk_kernel_latency_ms", "disk_queue_latency_ms",
    ),
    "ds_iops": ("ds_read_iops", "ds_write_iops"),
    "overview": (
        "cpu_usage_pct", "mem_usage_pct",
        "disk_read_kbps", "disk_write_kbps",
        "disk_read_requests", "disk_write_requests",
        "net_rx_kbps", "net_tx_kbps",
    ),
}

_BY_KEY: Dict[str, PerfMetricDef] = {m.key: m for m in PERF_METRICS}

_ALIAS_TO_KEY: Dict[str, str] = {}
for m in PERF_METRICS:
    _ALIAS_TO_KEY[m.key.lower()] = m.key
    for a in m.aliases:
        _ALIAS_TO_KEY[a.lower().replace("-", "_").replace(" ", "_")] = m.key
        _ALIAS_TO_KEY[a.lower()] = m.key


def _norm_token(raw: str) -> str:
    return (raw or "").strip().lower().replace("-", "_").replace(" ", "_")


def resolve_metric_keys(
    requested: Optional[Sequence[str]],
    *,
    entity: str = "host",
    default: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    """Kullanıcı/model metrik adlarını kanonik key listesine çevir.

    Döner: {keys: [...], unknown: [...], defs: [PerfMetricDef...]}
    """
    ent = (entity or "host").strip().lower()
    if ent in ("esx", "esxi", "hostsystem"):
        ent = "host"
    if ent in ("virtualmachine", "guest"):
        ent = "vm"

    tokens: List[str] = []
    for raw in (requested or []):
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        # "disk_rate,cpu" tek string gelebilir
        for part in s.replace(";", ",").split(","):
            p = part.strip()
            if p:
                tokens.append(p)

    if not tokens and default:
        tokens = list(default)

    keys: List[str] = []
    unknown: List[str] = []
    seen: Set[str] = set()

    def _add(key: str) -> None:
        if key in seen:
            return
        m = _BY_KEY.get(key)
        if not m:
            return
        if m.entity not in ("both", ent):
            # entity uyumsuz — yine de ekle ama caller filtreleyebilir; burada atla
            return
        seen.add(key)
        keys.append(key)

    for tok in tokens:
        n = _norm_token(tok)
        # bundle?
        if n in METRIC_BUNDLES:
            for k in METRIC_BUNDLES[n]:
                _add(k)
            continue
        # doğrudan alias
        key = _ALIAS_TO_KEY.get(n) or _ALIAS_TO_KEY.get(tok.lower())
        if key:
            _add(key)
            continue
        # "disk rate" boşluklu
        key = _ALIAS_TO_KEY.get(tok.lower())
        if key:
            _add(key)
            continue
        unknown.append(tok)

    defs = [_BY_KEY[k] for k in keys if k in _BY_KEY]
    return {"keys": keys, "unknown": unknown, "defs": defs, "entity": ent}


def catalog_summary(*, entity: Optional[str] = None) -> List[Dict[str, str]]:
    """Tool description / debug için kısa katalog özeti."""
    out = []
    for m in PERF_METRICS:
        if entity and m.entity not in ("both", entity):
            continue
        out.append({
            "key": m.key,
            "unit": m.unit,
            "entity": m.entity,
            "vsphere": f"{m.group}.{m.name}.{m.rollup}",
            "description": m.description,
        })
    return out


def is_mutate_method(name: str) -> bool:
    return (name or "").strip() in SOAP_MUTATE_DENY
