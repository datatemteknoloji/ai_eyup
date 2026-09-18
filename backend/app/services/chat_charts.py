"""Sohbet zaman serisi grafikleri — modül SoT → ChatChartPayload (Recharts).

Linux/Windows: Timescale `metric_data` (Prom scrape kopyası); boşsa salt okunur
Prometheus query_range. Linux: envanterde olmayan scrape hedefleri de
`up` map + instance etiketi ile çizilir (Canlı Metrikler ile aynı çözümleme).
Virt: vCenter Timescale (`query_series`) — Prometheus karışmaz.
Aynı birim = tek grafik, çok seri (çapraz overlay, en fazla 8 nesne).
Farklı birim (CPU % × bellek %) = ayrı grafikler.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.server import Server
from app.services.metric_history import (
    MAX_HOURS,
    MAX_POINTS_PER_SERIES,
    METRIC_GROUPS,
    _DURATION_RE,
    _GROUP_KEYWORDS,
    _UNIT_TO_HOURS,
    _downsample,
    _format_duration_label,
    _series_stats_text,
)

logger = logging.getLogger(__name__)

MAX_CHART_OBJECTS = 8

_EXTRA_GROUP_KEYWORDS: Dict[str, List[str]] = {
    "ready": ["cpu ready", "ready", "contention"],
    "latency": ["latency", "gecikme", "gecik"],
    "balloon": ["balloon", "balon"],
}

_VIRT_KIND_HINTS = {
    "datastore": ("datastore", "datastores", "depolama", "ds "),
    "host": ("esxi", "esx ", "esx-", "host ", "hypervisor", "hipervizör"),
    "vm": (" vm", "sanal", "virtual machine", "virtualmachine"),
}

# grup → (kind → metrik id listesi). Aynı birimdekiler tek overlay grafikte.
_VIRT_GROUP_METRICS: Dict[str, Dict[str, List[str]]] = {
    "cpu": {
        "vm": ["cpu_pct"],
        "host": ["cpu_pct"],
        "datastore": ["usage_pct"],
    },
    "memory": {
        "vm": ["mem_pct"],
        "host": ["mem_pct"],
        "datastore": ["usage_pct"],
    },
    "disk": {
        "vm": ["disk_latency_ms"],
        "host": ["disk_latency_ms"],
        "datastore": ["usage_pct"],
    },
    "network": {
        "vm": ["net_rx_kbps", "net_tx_kbps"],
        "host": ["net_rx_kbps", "net_tx_kbps"],
        "datastore": [],
    },
    "iops": {
        "vm": ["disk_read_iops", "disk_write_iops"],
        "host": ["disk_read_iops", "disk_write_iops"],
        "datastore": ["read_iops", "write_iops"],
    },
    "ready": {
        "vm": ["cpu_ready_pct"],
        "host": ["cpu_ready_pct"],
        "datastore": [],
    },
    "latency": {
        "vm": ["disk_latency_ms"],
        "host": ["disk_latency_ms"],
        "datastore": ["read_latency_ms", "write_latency_ms"],
    },
    "balloon": {
        "vm": ["balloon_mb"],
        "host": ["mem_balloon_mb"],
        "datastore": [],
    },
    "swap": {
        "vm": ["swapped_mb"],
        "host": ["mem_swap_used_mb"],
        "datastore": [],
    },
    "load": {"vm": ["cpu_pct"], "host": ["cpu_pct"], "datastore": []},
}

_VIRT_METRIC_LABEL = {
    "cpu_pct": "CPU %",
    "mem_pct": "Bellek %",
    "usage_pct": "Doluluk %",
    "disk_latency_ms": "Disk gecikme",
    "cpu_ready_pct": "CPU ready %",
    "net_rx_kbps": "Net RX",
    "net_tx_kbps": "Net TX",
    "disk_read_iops": "Okuma IOPS",
    "disk_write_iops": "Yazma IOPS",
    "read_iops": "Okuma IOPS",
    "write_iops": "Yazma IOPS",
    "balloon_mb": "Balloon",
    "mem_balloon_mb": "Balloon",
    "swapped_mb": "Swap",
    "mem_swap_used_mb": "Swap",
    "read_latency_ms": "Okuma gecikme",
    "write_latency_ms": "Yazma gecikme",
}

_OS_GROUP_TITLE = {
    "cpu": "CPU Kullanımı",
    "memory": "RAM Kullanımı",
    "disk": "Disk Kullanımı",
    "network": "Network Trafiği",
    "load": "Load Average",
    "disk_io": "Disk I/O",
    "iops": "Disk IOPS",
    "swap": "Swap Kullanımı",
}


def hours_to_range_key(hours: float) -> str:
    minutes = float(hours) * 60.0
    if minutes <= 15:
        return "15m"
    if minutes <= 30:
        return "30m"
    if minutes <= 60:
        return "1h"
    if minutes <= 120:
        return "2h"
    if minutes <= 480:
        return "8h"
    if minutes <= 1440:
        return "24h"
    if minutes <= 10080:
        return "7d"
    if minutes <= 43200:
        return "30d"
    return "60d"


def parse_chart_intent(message: str, *, explicit: bool = False) -> Optional[Dict[str, Any]]:
    """Süre + metrik grubu (veya /graph varsayılanları) → hours/groups."""
    ml = (message or "").lower()
    hours: Optional[float] = None
    dur_match = _DURATION_RE.search(ml)
    if dur_match:
        amount = float(dur_match.group(1).replace(",", "."))
        unit = dur_match.group(2).lower()
        hours = amount * _UNIT_TO_HOURS.get(unit, 1.0)
        hours = max(0.25, min(hours, MAX_HOURS))

    groups: List[str] = []
    for group, keywords in list(_GROUP_KEYWORDS.items()) + list(_EXTRA_GROUP_KEYWORDS.items()):
        if any(kw in ml for kw in keywords) and group not in groups:
            groups.append(group)
    # "I/O" / "IO" → disk_io (disk kullanım % değil; okuma/yazma)
    if re.search(r"(?<![a-z0-9])i/?o(?![a-z0-9])", ml) and "disk_io" not in groups:
        groups.append("disk_io")

    if hours is None and not groups and not explicit:
        return None
    if hours is None:
        hours = 1.0 if explicit else None
    if not groups:
        if explicit:
            groups = ["cpu", "memory"]
        else:
            return None
    if hours is None:
        return None
    return {"hours": hours, "groups": groups, "explicit": explicit}


def detect_virt_kind(message: str) -> str:
    ml = f" {(message or '').lower()} "
    for kind, hints in _VIRT_KIND_HINTS.items():
        if any(h in ml for h in hints):
            return kind
    return "vm"


def match_named_entities(message: str, inventory: Sequence[str]) -> List[str]:
    """Mesajda geçen envanter adları; uzun ada öncelik, en fazla 8.

    Eşleşen aralık boşlukla örtülür ki `web` gibi kısa ad, `web-prod-01`
    bulunduktan sonra tekrar sayılmasın; ayrı yazılmış `web` durur.
    """
    ml = (message or "").lower()
    found: List[str] = []
    seen = set()
    for name in sorted((n for n in inventory if n and len(n.strip()) >= 2), key=len, reverse=True):
        key = name.lower()
        if key in seen:
            continue
        idx = ml.find(key)
        if idx < 0:
            continue
        found.append(name)
        seen.add(key)
        ml = ml[:idx] + (" " * len(key)) + ml[idx + len(key):]
        if len(found) >= MAX_CHART_OBJECTS:
            break
    return found


def _cap_servers(servers: Sequence[Server]) -> List[Server]:
    out: List[Server] = []
    seen = set()
    for s in servers:
        if s is None or s.id in seen:
            continue
        seen.add(s.id)
        out.append(s)
        if len(out) >= MAX_CHART_OBJECTS:
            break
    return out


@dataclass
class ChartHost:
    """Linux grafik hedefi — envanter Server ve/veya Prometheus instance."""
    name: str
    instance: Optional[str] = None
    server: Optional[Server] = None

    @property
    def key(self) -> str:
        if self.server is not None and getattr(self.server, "id", None) is not None:
            return f"srv:{self.server.id}"
        return f"prom:{self.instance or self.name}"


# Timescale / METRICS_TO_SYNC adı → Canlı Metrikler preset anahtarı
_METRIC_TO_PRESET: Dict[str, str] = {
    "cpu_usage_percent": "cpu",
    "memory_usage_percent": "memory",
    "disk_root_usage_percent": "disk",
    "network_rx_bytes_per_sec": "net_rx",
    "network_tx_bytes_per_sec": "net_tx",
    "load1": "load",
    "disk_read_bytes_per_sec": "disk_read",
    "disk_write_bytes_per_sec": "disk_write",
}


def resolve_os_targets(
    message: str,
    *,
    selected: Optional[Sequence[Server]] = None,
    pool: Optional[Sequence[Server]] = None,
) -> List[Server]:
    """Seçili veya mesajda adı/IP'si geçen sunucular (filo tarama yok)."""
    if selected:
        return _cap_servers(selected)
    if not pool:
        return []
    ml = (message or "").lower()
    hits: List[Server] = []
    for s in sorted(pool, key=lambda x: len(x.name or ""), reverse=True):
        names = [s.name, s.hostname, getattr(s, "vm_name", None)]
        if any(n and len(n) >= 2 and n.lower() in ml for n in names):
            hits.append(s)
            continue
        if s.ip_address and s.ip_address in (message or ""):
            hits.append(s)
        if len(hits) >= MAX_CHART_OBJECTS:
            break
    return _cap_servers(hits)


def _display_name_for_instance(instance: str) -> str:
    host = (instance or "").rsplit(":", 1)[0]
    return host.split(".")[0] if host else instance


def _server_matches_instance(server: Server, instance: str) -> bool:
    host = (instance or "").rsplit(":", 1)[0].lower()
    short = host.split(".")[0]
    for cand in (server.name, server.hostname, getattr(server, "vm_name", None), server.ip_address):
        if not cand:
            continue
        c = str(cand).strip().lower()
        if c == host or c == short or host.startswith(c + ".") or c.split(".")[0] == short:
            return True
    return False


def resolve_linux_chart_hosts(
    message: str,
    *,
    selected: Optional[Sequence[Server]] = None,
    pool: Optional[Sequence[Server]] = None,
) -> List[ChartHost]:
    """Envanter + Prometheus scrape hedefleri (Canlı Metrikler çözümlemesi)."""
    from app.services.monitoring.prometheus_metrics import (
        get_node_exporter_up_map,
        match_prometheus_instance,
        resolve_prometheus_instances_from_message,
    )

    up_map: Dict[str, str] = {}
    try:
        up_map = get_node_exporter_up_map() or {}
    except Exception as exc:
        logger.debug("chat_charts up_map: %s", exc)

    out: List[ChartHost] = []
    seen: set = set()

    def _add(host: ChartHost) -> None:
        if host.key in seen:
            return
        seen.add(host.key)
        out.append(host)

    if selected:
        for s in _cap_servers(selected):
            inst = None
            if up_map:
                inst, _up = match_prometheus_instance(
                    up_map,
                    ip=s.ip_address,
                    hostname=s.hostname,
                    name=s.name,
                )
            if not inst and s.ip_address:
                inst = f"{s.ip_address}:9100"
            _add(ChartHost(name=s.name or s.hostname or s.ip_address or "?", instance=inst, server=s))
        return out

    pool_list = list(pool or [])
    inv = resolve_os_targets(message, pool=pool_list)
    named = resolve_prometheus_instances_from_message(message, up_map) if up_map else []

    # Prometheus instance öncelikli — envanter eşleşmesi varsa Server bağla
    for inst in named:
        matched = next((s for s in pool_list if _server_matches_instance(s, inst)), None)
        label = (matched.name if matched else None) or _display_name_for_instance(inst)
        _add(ChartHost(name=label, instance=inst, server=matched))
        if len(out) >= MAX_CHART_OBJECTS:
            return out

    for s in inv:
        if any(h.server is not None and h.server.id == s.id for h in out):
            continue
        inst = None
        if up_map:
            inst, _up = match_prometheus_instance(
                up_map, ip=s.ip_address, hostname=s.hostname, name=s.name,
            )
        if not inst and s.ip_address:
            inst = f"{s.ip_address}:9100"
        _add(ChartHost(name=s.name or "?", instance=inst, server=s))
        if len(out) >= MAX_CHART_OBJECTS:
            break
    return out


def _virt_inventory_names(db: Session, kind: str) -> List[str]:
    return [name for name, _ref in _virt_inventory_refs(db, kind)]


def _virt_inventory_refs(db: Session, kind: str) -> List[tuple]:
    """(görünen ad, hv:id:ad) — aynı ad iki vCenter'da iki ref."""
    from app.services.virt_monitoring import _KIND_TABLE
    from app.services.virt_scope import encode_ref

    table, key = _KIND_TABLE.get(kind, _KIND_TABLE["vm"])
    try:
        rows = db.execute(text(
            f"SELECT DISTINCT hypervisor_id, {key} AS name FROM {table} "
            f"WHERE {key} IS NOT NULL AND {key} <> ''"
        ))
        out = []
        seen = set()
        for hid, name in rows:
            if not name:
                continue
            ref = encode_ref(hid, str(name))
            if ref in seen:
                continue
            seen.add(ref)
            out.append((str(name), ref))
        return out
    except Exception as exc:
        logger.warning("chat_charts virt inventory: %s", exc)
        return []


def _prom_query_range_instance(
    instance: str,
    metric_name: str,
    hours: float,
    *,
    kind: str = "linux",
) -> List[Dict[str, Any]]:
    """Salt okunur query_range — scrape / prometheus.yml değişmez. Instance birebir."""
    try:
        import httpx
        from app.core.config import settings
        from app.services.monitoring.prometheus_metrics import (
            linux_live_preset_queries,
            linux_promql_selector,
        )
    except Exception:
        return []

    url = (getattr(settings, "PROMETHEUS_URL", None) or "").rstrip("/")
    if not url or not instance:
        return []
    if kind != "linux":
        return []
    preset = _METRIC_TO_PRESET.get(metric_name)
    if not preset:
        return []
    selector = linux_promql_selector([instance])
    query = linux_live_preset_queries(selector).get(preset)
    if not query:
        return []
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    step = max(15, int(hours * 3600 / MAX_POINTS_PER_SERIES))
    try:
        with httpx.Client(timeout=12.0) as client:
            resp = client.get(
                f"{url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start.timestamp(),
                    "end": end.timestamp(),
                    "step": step,
                },
            )
        if resp.status_code != 200:
            return []
        payload = resp.json()
        if payload.get("status") != "success":
            return []
        results = (payload.get("data") or {}).get("result") or []
        if not results:
            return []
        values = results[0].get("values") or []
        points = []
        for ts, val in values:
            try:
                points.append({
                    "t": datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(),
                    "v": round(float(val), 3),
                })
            except (TypeError, ValueError):
                continue
        return _downsample(points, MAX_POINTS_PER_SERIES)
    except Exception as exc:
        logger.debug("chat_charts prom instance: %s", exc)
        return []


def _resolve_server_instance(server: Server) -> Optional[str]:
    try:
        from app.services.monitoring.prometheus_metrics import (
            get_node_exporter_up_map,
            match_prometheus_instance,
        )
        from app.services.platform_scope import is_windows_server
        from app.services.monitoring.prometheus_metrics import WINDOWS_EXPORTER_PORT
    except Exception:
        return f"{server.ip_address}:9100" if server.ip_address else None
    try:
        win = is_windows_server(server)
    except Exception:
        win = False
    port = WINDOWS_EXPORTER_PORT if win else 9100
    try:
        up_map = get_node_exporter_up_map() or {}
        inst, _up = match_prometheus_instance(
            up_map, ip=server.ip_address, hostname=server.hostname, name=server.name,
        )
        if inst:
            return inst
    except Exception:
        pass
    return f"{server.ip_address}:{port}" if server.ip_address else None


def _fetch_os_points(
    db: Session,
    server: Server,
    metric_name: str,
    hours: float,
    *,
    allow_prom: bool = True,
) -> Tuple[List[Dict[str, Any]], str]:
    from app.models.metric import MetricData

    def _rows(since_hours: float):
        start_time = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        return (
            db.query(MetricData.timestamp, MetricData.value)
            .filter(
                MetricData.server_id == server.id,
                MetricData.metric_name == metric_name,
                MetricData.timestamp >= start_time,
            )
            .order_by(MetricData.timestamp)
            .all()
        )

    rows = _rows(hours)
    src = "timescale"
    if len(rows) < 2:
        widen = max(hours, 24.0)
        if widen > hours:
            wider = _rows(widen)
            if len(wider) >= 2:
                rows = wider
                src = "timescale_expanded"
    if len(rows) >= 2:
        points = [{"t": ts.isoformat(), "v": round(float(val), 3)} for ts, val in rows]
        return _downsample(points, MAX_POINTS_PER_SERIES), src
    if allow_prom:
        inst = _resolve_server_instance(server)
        if inst:
            promo = _prom_query_range_instance(inst, metric_name, max(hours, 8.0))
            if promo:
                return promo, "prometheus"
    return [], "none"


def _fetch_host_points(
    db: Session,
    host: ChartHost,
    metric_name: str,
    hours: float,
) -> Tuple[List[Dict[str, Any]], str]:
    if host.server is not None:
        return _fetch_os_points(db, host.server, metric_name, hours, allow_prom=True)
    if host.instance:
        pts = _prom_query_range_instance(host.instance, metric_name, max(hours, 8.0))
        return (pts, "prometheus") if pts else ([], "none")
    return [], "none"


def _build_os_charts(
    db: Session,
    servers: Sequence[Server],
    hours: float,
    groups: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    hosts = [
        ChartHost(
            name=s.name or "?",
            instance=_resolve_server_instance(s),
            server=s,
        )
        for s in servers
    ]
    return _build_linux_charts(db, hosts, hours, groups)


def _build_linux_charts(
    db: Session,
    hosts: Sequence[ChartHost],
    hours: float,
    groups: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    charts: List[Dict[str, Any]] = []
    sources: List[str] = []
    multi = len(hosts) > 1
    hours_label = _format_duration_label(hours)
    for group in groups:
        specs = METRIC_GROUPS.get(group)
        if not specs:
            continue
        unit = specs[0][2]
        series: List[Dict[str, Any]] = []
        for host in hosts:
            for metric_name, label, _unit in specs:
                points, src = _fetch_host_points(db, host, metric_name, hours)
                if src != "none" and src not in sources:
                    sources.append(src)
                if not points:
                    continue
                series_label = f"{host.name} — {label}" if multi else label
                series.append({
                    "metric_name": f"{host.key}:{metric_name}",
                    "label": series_label,
                    "points": points,
                })
        if not series:
            continue
        title = f"{_OS_GROUP_TITLE.get(group, group)} — Son {hours_label}"
        if multi:
            title = f"{title} ({len(hosts)} sunucu)"
        srv0 = hosts[0].server if len(hosts) == 1 else None
        charts.append({
            "type": "timeseries",
            "title": title,
            "unit": unit,
            "server_id": srv0.id if srv0 is not None else None,
            "server_name": hosts[0].name if len(hosts) == 1 else None,
            "series": series,
        })
    return charts, sources


def _build_virt_charts(
    db: Session,
    *,
    kind: str,
    names: Sequence[str],
    hours: float,
    groups: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    from app.services.virt_monitoring import query_series

    range_key = hours_to_range_key(hours)
    window_minutes = max(15, int(round(float(hours) * 60)))
    hours_label = _format_duration_label(hours)
    charts: List[Dict[str, Any]] = []
    multi = len(names) > 1
    for group in groups:
        metrics = (_VIRT_GROUP_METRICS.get(group) or {}).get(kind) or []
        if not metrics:
            continue
        # Aynı birimdeki metrikleri tek grafikte topla (RX+TX, IOPS).
        by_unit: Dict[str, List[Dict[str, Any]]] = {}
        unit_of: Dict[str, str] = {}
        for metric in metrics:
            raw = query_series(
                db, kind=kind, names=names, metric=metric,
                range_key=range_key, window_minutes=window_minutes,
            )
            if not any(len((s.get("points") or [])) >= 2 for s in (raw.get("series") or [])):
                if window_minutes < 1440:
                    raw = query_series(
                        db, kind=kind, names=names, metric=metric,
                        range_key="24h", window_minutes=1440,
                    )
            unit = raw.get("unit") or ""
            unit_of[metric] = unit
            mlabel = _VIRT_METRIC_LABEL.get(metric, metric)
            for s in raw.get("series") or []:
                pts = [
                    {"t": p["t"], "v": p["v"]}
                    for p in (s.get("points") or [])
                    if p.get("t") is not None and p.get("v") is not None
                ]
                if len(pts) < 2:
                    continue
                obj = s.get("name") or "?"
                label = f"{obj} — {mlabel}" if (multi or len(metrics) > 1) else mlabel
                by_unit.setdefault(unit, []).append({
                    "metric_name": f"{obj}:{metric}",
                    "label": label,
                    "points": pts,
                })
        for unit, series in by_unit.items():
            if not series:
                continue
            gtitle = _OS_GROUP_TITLE.get(group) or _VIRT_METRIC_LABEL.get(metrics[0], group)
            title = f"{gtitle} — Son {hours_label}"
            if multi:
                title = f"{title} ({len(names)} nesne)"
            charts.append({
                "type": "timeseries",
                "title": title,
                "unit": unit,
                "series": series,
            })
    return charts, (["vcenter"] if charts else [])


def _summary_text(
    *,
    title: str,
    hours: float,
    charts: Sequence[Dict[str, Any]],
    sources: Sequence[str],
    missing: Sequence[str],
    notes: Sequence[str],
) -> str:
    hours_label = _format_duration_label(hours)
    lines = [f"### {title} — Son {hours_label}\n"]
    if charts:
        for chart in charts:
            lines.append(f"**{chart['title'].split(' — ')[0]}**")
            for s in chart.get("series") or []:
                lines.append(_series_stats_text(s["label"], chart.get("unit") or "", s.get("points") or []))
            lines.append("")
        lines.append("_Detaylı grafik aşağıda gösteriliyor._")
    else:
        lines.append(
            "Zaman serisi bulunamadı. Linux/Windows için Prometheus scrape → Timescale "
            "(`metric_data`) gerekir; sanallaştırma için vCenter sync "
            "(`virt_vm_metrics` / host / datastore). "
            "Canlı SSH/WinRM tek örnek verir, geçmiş eğri üretmez."
        )
    if sources:
        src_map = {
            "timescale": "Timescale (Prom kopyası)",
            "timescale_expanded": "Timescale (pencere genişletildi — son örnek istenen aralığın dışında)",
            "prometheus": "Prometheus query_range",
            "vcenter": "vCenter / Timescale",
        }
        lines.append("_Kaynak: " + ", ".join(src_map.get(s, s) for s in sources) + "._")
    if missing:
        lines.append("_Serisi boş: " + ", ".join(missing) + "._")
    for n in notes:
        lines.append(n)
    return "\n".join(lines)


def try_build_chat_charts(
    db: Session,
    *,
    message: str,
    platform: str,
    servers: Optional[Sequence[Server]] = None,
    pool: Optional[Sequence[Server]] = None,
    explicit: bool = False,
) -> Optional[Dict[str, Any]]:
    """Grafik turu ise {summary_text, charts, intents}; değilse None.

    implicit (süre+metrik, hedef var) ve veri yoksa None — LLM/tool akışı devam eder.
    explicit (/graph) her zaman bir cevap döner (veri yoksa açıklama).
    """
    plat = (platform or "linux").strip().lower()
    intent = parse_chart_intent(message, explicit=explicit)
    if not intent:
        return None

    hours = float(intent["hours"])
    groups = list(intent["groups"])
    notes: List[str] = []
    charts: List[Dict[str, Any]] = []
    sources: List[str] = []
    missing: List[str] = []
    title = "Metrik"

    virt_like = plat in ("virt", "vcenter", "hypervisor")
    if plat == "unified":
        virt_like = detect_virt_kind(message) != "vm" or any(
            h in f" {(message or '').lower()} "
            for h in (" vcenter", " esxi", " datastore", " sanal makine", " vm ")
        )

    if virt_like or plat == "virt":
        kind = detect_virt_kind(message)
        inventory_refs = _virt_inventory_refs(db, kind)
        names = match_named_entities(message, [n for n, _r in inventory_refs])
        if not names and kind == "vm":
            for alt in ("host", "datastore"):
                alt_refs = _virt_inventory_refs(db, alt)
                alt_names = match_named_entities(message, [n for n, _r in alt_refs])
                if alt_names:
                    kind, names, inventory_refs = alt, alt_names, alt_refs
                    break
        refs = [ref for n, ref in inventory_refs if n in set(names)]
        names = refs or names
        if not names:
            if explicit:
                return {
                    "summary_text": (
                        "Grafik için VM / ESXi / datastore adı yazın "
                        f"(en fazla {MAX_CHART_OBJECTS}). Örnek: "
                        "`vm-a ve vm-b son 8 saat CPU ve bellek /grafik`."
                    ),
                    "charts": [],
                    "intents": ["chart", "virt"],
                }
            return None
        charts, sources = _build_virt_charts(
            db, kind=kind, names=names, hours=hours, groups=groups,
        )
        display = [n for n, ref in inventory_refs if ref in set(names)]
        titled = ", ".join(dict.fromkeys(display or names))
        title = titled
        if not charts:
            missing = list(names)
        notes.append("_Hipervizör metrikleri vCenter sync; guest OS / Prometheus karışmaz._")
    else:
        if plat in ("openshift",) and not servers and not pool:
            if explicit:
                return {
                    "summary_text": (
                        "OpenShift cluster için sohbet zaman serisi yok. "
                        "Node guest metrikleri için Linux sohbetinde sunucu adı + `/grafik` kullanın."
                    ),
                    "charts": [],
                    "intents": ["chart", "openshift"],
                }
            return None
        use_prom_hosts = plat in ("linux", "unified", "")
        if use_prom_hosts:
            hosts = resolve_linux_chart_hosts(
                message,
                selected=servers if servers else None,
                pool=pool,
            )
            if not hosts:
                if explicit:
                    return {
                        "summary_text": (
                            "Grafik için sunucu adı yazın (Linux envanteri veya "
                            "Prometheus'ta scrape edilen hostname) "
                            f"(en fazla {MAX_CHART_OBJECTS}). "
                            "Örnek: `web01 ve web02 son 1 saat CPU /grafik`."
                        ),
                        "charts": [],
                        "intents": ["chart", plat],
                    }
                return None
            charts, sources = _build_linux_charts(db, hosts, hours, groups)
            title = ", ".join(h.name for h in hosts)
            if not charts:
                missing = [h.name for h in hosts]
            if any(h.server is None and h.instance for h in hosts):
                notes.append("_Kaynak: Prometheus scrape (envanter kaydı gerekmez)._")
        else:
            targets = resolve_os_targets(message, selected=servers, pool=pool)
            if not targets:
                if explicit:
                    return {
                        "summary_text": (
                            "Grafik için sunucu adı yazın veya listeden seçin "
                            f"(en fazla {MAX_CHART_OBJECTS}). "
                            "Örnek: `web01 ve web02 son 1 saat CPU /grafik`."
                        ),
                        "charts": [],
                        "intents": ["chart", plat],
                    }
                return None
            if plat == "exadata":
                notes.append("_Exadata cell/ASM canlı metrik yok; linked compute host Timescale serisi kullanılır._")
            charts, sources = _build_os_charts(db, targets, hours, groups)
            title = ", ".join(s.name for s in targets)
            if not charts:
                missing = [s.name for s in targets]

    if not charts and not explicit:
        return None

    return {
        "summary_text": _summary_text(
            title=title or "Metrik",
            hours=hours,
            charts=charts,
            sources=sources,
            missing=missing,
            notes=notes,
        ),
        "charts": list(charts),
        "intents": ["chart", plat if plat != "hypervisor" else "virt"],
    }


def emit_chart_tokens(text: str) -> Iterable[str]:
    for i in range(0, len(text), 8):
        yield text[i:i + 8]
