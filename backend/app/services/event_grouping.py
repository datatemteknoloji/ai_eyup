"""
Events / incidents tekilleştirme.

Aynı sunucu + aynı sorun = tek satır. Tekrarlar last_seen ve occurrence ile
güncellenir; tarihçe detayda (event_ids) durur.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Metrik / kaynak eşiği: başlık değişse de (CPU %91 vs %95) aynı sorun.
COARSE_EVENT_TYPES = frozenset({
    "metric_anomaly",
    "cpu_high",
    "memory_high",
    "disk_full",
    "disk_high",
    "inode_high",
    "swap_high",
    "load_high",
    "service_down",
    "virt_resource",
})

SEV_RANK = {"emergency": 4, "critical": 3, "error": 2, "warning": 1, "info": 0}

_MOR_RE = re.compile(r"^(vm|host|domain|alarm|group|resgroup|datastore|folder)-\d+$", re.I)


def normalize_title(title: str) -> str:
    """Log başlığından timestamp ve syslog prefix soy."""
    t = (title or "").strip()
    t = re.sub(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}([+-]\d{2}:?\d{2}|Z)?\s+", "", t)
    t = re.sub(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+", "", t)
    t = re.sub(r"^\S+\s+\S+\[\d+\]:\s*", "", t)
    t = re.sub(r"^\S+\s+(?=\S+:)", "", t)
    return t.strip() or (title or "").strip()


def group_key_for_title(title: str) -> str:
    """Sayı / IP / UUID ayıklanmış grup anahtarı."""
    t = normalize_title(title)
    t = re.sub(r"0x[0-9a-fA-F]+", "0xN", t)
    t = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?", "IP", t)
    t = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "UUID",
        t,
    )
    t = re.sub(r"\d+", "N", t)
    return t.strip()


def event_problem_key(event: Any) -> str:
    """Aynı sorun için kararlı anahtar (severity dahil değil)."""
    raw = event.raw_data or {} if not isinstance(event, dict) else (event.get("raw_data") or {})
    et = (getattr(event, "event_type", None) or (event.get("event_type") if isinstance(event, dict) else None) or "")
    source = (getattr(event, "source", None) or (event.get("source") if isinstance(event, dict) else None) or "")
    server = getattr(event, "server_id", None)
    if server is None and isinstance(event, dict):
        server = event.get("server_id")
    server = server or 0
    title = getattr(event, "title", None) or (event.get("title") if isinstance(event, dict) else "") or ""

    if et in COARSE_EVENT_TYPES or (et == "metric_anomaly"):
        metric = raw.get("metric") or raw.get("category") or et
        host = raw.get("host_name") or ""
        return f"{server}|{et}|{metric}|{host}"

    if et == "openshift_event" or source == "openshift_collector":
        return (
            f"ocp|{raw.get('cluster_id') or 0}|{raw.get('namespace') or ''}|"
            f"{raw.get('reason') or ''}|{raw.get('source_object') or group_key_for_title(title)[:80]}"
        )

    if et.startswith("vcenter") or source.startswith("vcenter"):
        return f"{server}|{et}|{group_key_for_title(title)[:160]}"

    return f"{server}|{et}|{source}|{group_key_for_title(title)[:200]}"


def _ts(event: Any) -> datetime:
    ls = getattr(event, "last_seen", None) or getattr(event, "created_at", None)
    if ls is None and isinstance(event, dict):
        ls = event.get("last_seen") or event.get("created_at")
    return ls or datetime.min


def event_display_resource(event: Any, server_map: Optional[dict] = None) -> str:
    sid = getattr(event, "server_id", None)
    if sid and server_map and server_map.get(sid):
        name = server_map[sid]
        if isinstance(name, dict):
            return name.get("name") or "—"
        return str(name)
    raw = getattr(event, "raw_data", None) or {}
    for key in ("entity_name", "vm_name", "host_name", "cluster_name"):
        val = raw.get(key)
        if val and str(val).strip() and not _MOR_RE.match(str(val).strip()):
            return str(val).strip()
    title = getattr(event, "title", None) or ""
    m = re.search(r"Alarm\s+'[^']*'\s+on\s+(\S+)", title, re.I)
    if m:
        return m.group(1).rstrip(".,;:")
    for key in ("platform_label", "hypervisor_name"):
        val = raw.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return "—"


def group_events(
    events: Sequence[Any],
    server_map: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """Ham event listesini sorun gruplarına çevirir (en güncel temsilci)."""
    buckets: Dict[str, List[Any]] = defaultdict(list)
    for ev in events:
        buckets[event_problem_key(ev)].append(ev)

    groups: List[Dict[str, Any]] = []
    for key, rows in buckets.items():
        rows_sorted = sorted(rows, key=_ts, reverse=True)
        latest = rows_sorted[0]
        occ = 0
        for r in rows:
            occ += int(getattr(r, "occurrence_count", None) or 1)
        max_sev = max(rows, key=lambda e: SEV_RANK.get(getattr(e, "severity", None) or "info", 0))
        first_ts = min((_ts(r) for r in rows if _ts(r) != datetime.min), default=None)
        last_ts = _ts(latest)
        if last_ts == datetime.min:
            last_ts = None
        groups.append({
            "problem_key": key,
            "event_ids": [getattr(r, "id", None) for r in rows_sorted if getattr(r, "id", None) is not None],
            "event_id": getattr(latest, "id", None),
            "event_type": getattr(latest, "event_type", None),
            "severity": getattr(max_sev, "severity", None) or "info",
            "title": getattr(latest, "title", None) or "",
            "server_id": getattr(latest, "server_id", None),
            "server_name": event_display_resource(latest, server_map),
            "source": getattr(latest, "source", None),
            "resolved": bool(getattr(latest, "resolved", False)),
            "is_acknowledged": bool(getattr(latest, "is_acknowledged", False)),
            "is_known": bool(getattr(latest, "is_known", False)),
            "occurrence_count": occ,
            "first_seen": first_ts.isoformat() if first_ts else None,
            "last_seen": last_ts.isoformat() if last_ts else None,
            "latest_created_at": last_ts.isoformat() if last_ts else None,
            "representative": latest,
        })
    groups.sort(key=lambda g: g.get("last_seen") or "", reverse=True)
    groups.sort(key=lambda g: -SEV_RANK.get(g["severity"] or "info", 0))
    return groups


def unique_events(events: Sequence[Any]) -> List[Any]:
    """Her sorun için en güncel SystemEvent (sağlık skoru / kart)."""
    seen: Dict[str, Any] = {}
    for ev in sorted(events, key=_ts, reverse=True):
        k = event_problem_key(ev)
        if k not in seen:
            seen[k] = ev
    return list(seen.values())


def incident_problem_key(inc: Any) -> str:
    pk = getattr(inc, "problem_key", None)
    if pk:
        return str(pk)
    servers = tuple(sorted(getattr(inc, "affected_servers", None) or []))
    return f"{getattr(inc, 'source', None) or ''}|{servers}"


def unique_incidents(incidents: Sequence[Any]) -> List[Any]:
    """Aynı sorun için tek açık incident (en güncel)."""
    seen: Dict[str, Any] = {}
    for inc in incidents:
        k = incident_problem_key(inc)
        prev = seen.get(k)
        if prev is None:
            seen[k] = inc
            continue
        t_new = getattr(inc, "updated_at", None) or getattr(inc, "created_at", None) or datetime.min
        t_old = getattr(prev, "updated_at", None) or getattr(prev, "created_at", None) or datetime.min
        if t_new >= t_old:
            seen[k] = inc
    return list(seen.values())


def group_severity_counts(groups: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    crit = warn = 0
    for g in groups:
        sev = g.get("severity") or ""
        if sev in ("critical", "emergency"):
            crit += 1
        elif sev == "warning":
            warn += 1
    return crit, warn
