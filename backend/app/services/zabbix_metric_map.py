"""Zabbix semantic metric catalog + match map.

ainew kanonik metric_id ↔ Zabbix item key kalıpları ↔ chat alias’ları.
Ham Zabbix item dump’ı yerine sözleşmeli katalog; coverage ayrı hesaplanır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ZabbixMetricDef:
    id: str
    title: str
    unit: str
    family: str  # host_cpu|host_mem|host_disk|host_net|host_system|agent|windows
    keys: Tuple[str, ...] = ()
    key_regex: str = ""
    aliases: Tuple[str, ...] = ()
    prefer_value_types: Tuple[int, ...] = (0, 3)  # float, uint
    # pfree item → used% = 100 - value (Zabbix 7 Linux template)
    from_pfree: bool = False

    def match_key(self, key: str) -> bool:
        k = (key or "").strip()
        if not k:
            return False
        if k in self.keys:
            return True
        if self.key_regex:
            try:
                return bool(re.match(self.key_regex, k))
            except re.error:
                return False
        # prefix: system.cpu.util[*] ↔ system.cpu.util
        for base in self.keys:
            if "[" in base:
                continue
            if k == base or k.startswith(base + "["):
                return True
        return False

    def transform_value(self, raw: float, item_key: str = "") -> float:
        """Ham Zabbix lastvalue/history → kanonik birim."""
        key = item_key or ""
        if self.from_pfree and "pfree" in key and "pused" not in key:
            return max(0.0, min(100.0, 100.0 - float(raw)))
        return float(raw)


# --- Canonical catalog (OS agent v1) -----------------------------------------

CATALOG: List[ZabbixMetricDef] = [
    # CPU
    ZabbixMetricDef(
        id="cpu_util",
        title="CPU utilization",
        unit="%",
        family="host_cpu",
        keys=("system.cpu.util", "system.cpu.util[,avg1]", "system.cpu.util[,,avg1]"),
        key_regex=r"^system\.cpu\.util(\[.*\])?$",
        aliases=("cpu", "cpu util", "cpu usage", "işlemci", "cpu kullanımı", "cpu yüzdesi"),
    ),
    ZabbixMetricDef(
        id="cpu_load1",
        title="Load average (1m)",
        unit="",
        family="host_cpu",
        keys=("system.cpu.load[all,avg1]", "system.cpu.load[,avg1]", "system.cpu.load[percpu,avg1]"),
        key_regex=r"^system\.cpu\.load(\[.*avg1.*\])?$",
        aliases=("load", "load1", "load average", "yük", "yük ortalaması"),
    ),
    ZabbixMetricDef(
        id="cpu_load5",
        title="Load average (5m)",
        unit="",
        family="host_cpu",
        keys=("system.cpu.load[all,avg5]", "system.cpu.load[,avg5]", "system.cpu.load[percpu,avg5]"),
        key_regex=r"^system\.cpu\.load(\[.*avg5.*\])?$",
        aliases=("load5", "5m load"),
    ),
    ZabbixMetricDef(
        id="cpu_load15",
        title="Load average (15m)",
        unit="",
        family="host_cpu",
        keys=("system.cpu.load[all,avg15]", "system.cpu.load[,avg15]", "system.cpu.load[percpu,avg15]"),
        key_regex=r"^system\.cpu\.load(\[.*avg15.*\])?$",
        aliases=("load15", "15m load"),
    ),
    ZabbixMetricDef(
        id="cpu_num",
        title="CPU count",
        unit="",
        family="host_cpu",
        keys=("system.cpu.num", "system.cpu.num[online]"),
        key_regex=r"^system\.cpu\.num(\[.*\])?$",
        aliases=("cpu count", "çekirdek", "vcpu", "cpu sayısı"),
    ),
    # Memory
    ZabbixMetricDef(
        id="mem_used_pct",
        title="Memory used %",
        unit="%",
        family="host_mem",
        keys=("vm.memory.util", "vm.memory.utilization", "vm.memory.used[pavailable]"),
        key_regex=r"^vm\.memory\.(util|utilization)(\[.*\])?$",
        aliases=("memory", "ram", "bellek", "memory usage", "ram kullanımı", "bellek yüzdesi"),
    ),
    ZabbixMetricDef(
        id="mem_available",
        title="Memory available",
        unit="B",
        family="host_mem",
        keys=("vm.memory.size[available]", "vm.memory.size[pavailable]", "vm.memory.size[free]"),
        key_regex=r"^vm\.memory\.size\[(available|pavailable|free)\]$",
        aliases=("mem available", "boş bellek", "available memory"),
    ),
    ZabbixMetricDef(
        id="mem_total",
        title="Memory total",
        unit="B",
        family="host_mem",
        keys=("vm.memory.size[total]",),
        key_regex=r"^vm\.memory\.size\[total\]$",
        aliases=("mem total", "toplam ram", "total memory"),
    ),
    ZabbixMetricDef(
        id="swap_used_pct",
        title="Swap used %",
        unit="%",
        family="host_mem",
        keys=(
            "system.swap.size[,pused]",
            "system.swap.size[all,pused]",
            "system.swap.size[,pfree]",
            "system.swap.size[all,pfree]",
        ),
        key_regex=r"^system\.swap\.size\[.*(pused|pfree).*\]$",
        aliases=("swap", "swap usage", "takas"),
        from_pfree=True,
    ),
    # Disk / FS
    ZabbixMetricDef(
        id="fs_used_pct",
        title="Filesystem used %",
        unit="%",
        family="host_disk",
        # Zabbix 7: vfs.fs.dependent.size[/,pused|pfree]; eski: vfs.fs.size[/,pused]
        keys=(
            "vfs.fs.size[/,pused]",
            "vfs.fs.dependent.size[/,pused]",
            "vfs.fs.size[/,pfree]",
            "vfs.fs.dependent.size[/,pfree]",
        ),
        key_regex=r"^vfs\.fs(\.dependent)?\.size\[.*,(pused|pfree)\]$",
        aliases=("disk", "disk usage", "filesystem", "disk doluluk", "disk yüzdesi", "fs used"),
        from_pfree=True,
    ),
    ZabbixMetricDef(
        id="fs_total",
        title="Filesystem total",
        unit="B",
        family="host_disk",
        keys=("vfs.fs.size[/,total]", "vfs.fs.dependent.size[/,total]"),
        key_regex=r"^vfs\.fs(\.dependent)?\.size\[.*,total\]$",
        aliases=("disk total", "fs total"),
    ),
    ZabbixMetricDef(
        id="fs_free",
        title="Filesystem free",
        unit="B",
        family="host_disk",
        keys=("vfs.fs.size[/,free]", "vfs.fs.dependent.size[/,free]"),
        key_regex=r"^vfs\.fs(\.dependent)?\.size\[.*,free\]$",
        aliases=("disk free", "boş disk"),
    ),
    ZabbixMetricDef(
        id="disk_read_rate",
        title="Disk read rate",
        unit="B/s",
        family="host_disk",
        # Zabbix 7 Linux: vfs.dev.read.rate[sda]; eski: vfs.dev.read[,sps]
        keys=("vfs.dev.read.rate", "vfs.dev.read[,sps]", "vfs.dev.read[*,sps]"),
        key_regex=r"^vfs\.dev\.read(\.rate)?(\[.*\])?$",
        aliases=("disk read", "disk okuma"),
    ),
    ZabbixMetricDef(
        id="disk_write_rate",
        title="Disk write rate",
        unit="B/s",
        family="host_disk",
        keys=("vfs.dev.write.rate", "vfs.dev.write[,sps]", "vfs.dev.write[*,sps]"),
        key_regex=r"^vfs\.dev\.write(\.rate)?(\[.*\])?$",
        aliases=("disk write", "disk yazma"),
    ),
    # Network
    ZabbixMetricDef(
        id="net_in",
        title="Network bits received",
        unit="b/s",
        family="host_net",
        keys=("net.if.in[", "net.if.in"),
        key_regex=r"^net\.if\.in\[.+\]$",
        aliases=("network in", "net rx", "ağ giriş", "network receive"),
    ),
    ZabbixMetricDef(
        id="net_out",
        title="Network bits sent",
        unit="b/s",
        family="host_net",
        keys=("net.if.out[", "net.if.out"),
        key_regex=r"^net\.if\.out\[.+\]$",
        aliases=("network out", "net tx", "ağ çıkış", "network transmit"),
    ),
    # System / agent
    ZabbixMetricDef(
        id="uptime",
        title="System uptime",
        unit="s",
        family="host_system",
        keys=("system.uptime",),
        key_regex=r"^system\.uptime$",
        aliases=("uptime", "çalışma süresi"),
    ),
    ZabbixMetricDef(
        id="boot_time",
        title="Boot time",
        unit="unixtime",
        family="host_system",
        keys=("system.boottime",),
        key_regex=r"^system\.boottime$",
        aliases=("boot", "boot time"),
    ),
    ZabbixMetricDef(
        id="agent_ping",
        title="Agent ping",
        unit="",
        family="agent",
        keys=("agent.ping",),
        key_regex=r"^agent\.ping$",
        aliases=("ping", "agent", "agent durumu"),
    ),
    ZabbixMetricDef(
        id="agent_version",
        title="Agent version",
        unit="",
        family="agent",
        keys=("agent.version",),
        key_regex=r"^agent\.version$",
        aliases=("agent version",),
        prefer_value_types=(1, 4),
    ),
    ZabbixMetricDef(
        id="proc_num",
        title="Number of processes",
        unit="",
        family="host_system",
        keys=("proc.num", "proc.num[]"),
        key_regex=r"^proc\.num(\[.*\])?$",
        aliases=("processes", "process count", "süreç sayısı"),
    ),
    # Windows-oriented (same catalog; keys differ by template)
    ZabbixMetricDef(
        id="win_cpu_util",
        title="Windows CPU utilization",
        unit="%",
        family="windows",
        keys=("system.cpu.util", "perf_counter_en[\"\\Processor Information(_Total)\\% Processor Utility\"]"),
        key_regex=r"^(system\.cpu\.util(\[.*\])?|perf_counter.*Processor.*)$",
        aliases=("windows cpu", "win cpu"),
    ),
    ZabbixMetricDef(
        id="win_mem_used_pct",
        title="Windows memory used %",
        unit="%",
        family="windows",
        keys=("vm.memory.util", "vm.memory.util[pused]"),
        key_regex=r"^vm\.memory\.util(\[.*\])?$",
        aliases=("windows memory", "win ram"),
    ),
]


_BY_ID: Dict[str, ZabbixMetricDef] = {m.id: m for m in CATALOG}


def catalog(family: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = []
    for m in CATALOG:
        if family and m.family != family and family not in ("all", "views"):
            # family filter: host_os = all non-windows; or exact
            if family == "host_os" and m.family.startswith("host"):
                pass
            elif family != m.family:
                continue
        rows.append({
            "id": m.id,
            "title": m.title,
            "unit": m.unit,
            "family": m.family,
            "keys": list(m.keys),
            "aliases": list(m.aliases),
        })
    return rows


def families() -> List[Dict[str, str]]:
    return [
        {"id": "overview", "title": "Overview"},
        {"id": "hosts", "title": "Hosts"},
        {"id": "host_cpu", "title": "CPU"},
        {"id": "host_mem", "title": "Memory"},
        {"id": "host_disk", "title": "Disk / FS"},
        {"id": "host_net", "title": "Network"},
        {"id": "host_system", "title": "System"},
        {"id": "problems", "title": "Problems"},
        {"id": "coverage", "title": "Match coverage"},
    ]


def get_metric(metric_id: str) -> Optional[ZabbixMetricDef]:
    return _BY_ID.get((metric_id or "").strip())


def resolve_metric_id(text: str) -> Optional[str]:
    """Alias / id / title → metric_id."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    if raw in _BY_ID:
        return raw
    # normalize
    norm = re.sub(r"[\s_\-]+", " ", raw).strip()
    for m in CATALOG:
        if m.id == norm or m.title.lower() == norm:
            return m.id
        for a in m.aliases:
            if a.lower() == norm or a.lower() in norm:
                return m.id
    return None


def match_item_to_metrics(key: str) -> List[ZabbixMetricDef]:
    hits = [m for m in CATALOG if m.match_key(key)]
    return hits


def pick_best_item(
    items: Sequence[Dict[str, Any]],
    metric: ZabbixMetricDef,
) -> Optional[Dict[str, Any]]:
    """Host item listesinden metric için en iyi item."""
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for it in items:
        key = str(it.get("key_") or "")
        if not metric.match_key(key):
            continue
        # await / time.rate gürültüsünü ele (regex bazen geniş olabilir)
        if ".await[" in key or ".time.rate[" in key:
            continue
        score = 100
        # exact key bonus
        if key in metric.keys:
            score += 50
        # shorter keys (less wild LLD noise) preferred for aggregates
        score -= min(len(key), 80)
        # prefer root FS for fs_* when multiple
        if metric.id.startswith("fs_") and "[/," in key.replace(" ", ""):
            score += 30
        # used%: pused > pfree (from_pfree transform for pfree)
        if metric.id in ("swap_used_pct", "fs_used_pct"):
            if "pused" in key:
                score += 40
            elif "pfree" in key:
                score += 10
        # disk rate: prefer sda / vda, then .rate form
        if metric.id in ("disk_read_rate", "disk_write_rate"):
            if ".rate[" in key:
                score += 25
            if "[sda]" in key or "[vda]" in key or "[nvme0n1]" in key:
                score += 20
        vt = it.get("value_type")
        try:
            vti = int(vt)
        except Exception:
            vti = -1
        if metric.prefer_value_types and vti in metric.prefer_value_types:
            score += 10
        # prefer items with lastvalue
        if it.get("lastvalue") not in (None, ""):
            score += 5
        candidates.append((score, it))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def default_chart_metrics() -> List[str]:
    return ["cpu_util", "mem_used_pct", "fs_used_pct", "cpu_load1"]
