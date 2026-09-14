"""Sanallaştırma monitoring ekranı — yalnız vCenter / Timescale SoT.

Grafik serisi seçim olmadan çekilmez. Overview envanter + alarm + son
host/datastore satırıdır; 10k VM zaman serisini taramaz.
Mevcut collect job'larına ve Prometheus'a dokunmaz.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.services.virt_scope import count_names, disambiguate, encode_ref, parse_ref
from app.services.virt_trend_query import _ENTITIES

logger = logging.getLogger(__name__)

MAX_SERIES_OBJECTS = 8
STALE_MINUTES = 45
VCENTER_SOURCES = ("vcenter_alarm", "vcenter_event", "vcenter_task")

RANGE_SPEC: Dict[str, Dict[str, Any]] = {
    "15m": {"minutes": 15, "bucket": None},
    "30m": {"minutes": 30, "bucket": None},
    "1h": {"minutes": 60, "bucket": None},
    "2h": {"minutes": 120, "bucket": None},
    "8h": {"minutes": 480, "bucket": None},
    "24h": {"minutes": 1440, "bucket": None},
    "7d": {"minutes": 10080, "bucket": "1 hour"},
    "30d": {"minutes": 43200, "bucket": "4 hours"},
    "60d": {"minutes": 86400, "bucket": "4 hours"},
}

_KIND_TO_ENTITY = {"vm": "vm", "host": "host", "datastore": "datastore"}

_KIND_TABLE = {
    "vm": ("virt_vm_metrics", "vm_name"),
    "host": ("hypervisor_host_metrics", "host_name"),
    "datastore": ("virt_datastore_metrics", "name"),
}


def parse_range(raw: Optional[str]) -> str:
    key = (raw or "8h").strip().lower()
    return key if key in RANGE_SPEC else "8h"


def bucket_for_window(minutes: int) -> Optional[str]:
    """İstenen pencereye uygun agregasyon — 10 günü 30 güne yuvarlamaz.

    <= 24s ham örnek, 1–14 gün saatlik kova, 15–60 gün 4s, daha uzun 12s.
    """
    if minutes <= 24 * 60:
        return None
    if minutes <= 14 * 24 * 60:
        return "1 hour"
    if minutes <= 60 * 24 * 60:
        return "4 hours"
    return "12 hours"


def parse_names(raw: Optional[str], extra: Optional[Sequence[str]] = None) -> List[str]:
    parts: List[str] = []
    if raw:
        parts.extend(x.strip() for x in raw.split(",") if x.strip())
    if extra:
        parts.extend(str(x).strip() for x in extra if str(x).strip())
    seen = set()
    out: List[str] = []
    for p in parts:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= MAX_SERIES_OBJECTS:
            break
    return out


def metric_catalog(kind: str) -> List[Dict[str, str]]:
    entity = _KIND_TO_ENTITY.get((kind or "host").strip().lower(), "host")
    spec = _ENTITIES[entity]
    return [
        {"id": key, "column": mdef[0], "unit": mdef[1]}
        for key, mdef in spec["metrics"].items()
    ]


def _metric_column(kind: str, metric: str) -> Tuple[str, str, str]:
    entity = _KIND_TO_ENTITY.get((kind or "").strip().lower())
    if entity is None:
        raise ValueError("kind vm|host|datastore olmalı")
    spec = _ENTITIES[entity]
    mid = (metric or "").strip()
    if mid not in spec["metrics"]:
        raise ValueError(f"bilinmeyen metrik: {metric}")
    col, unit, _thr = spec["metrics"][mid][:3]
    if not str(col).replace("_", "").isalnum():
        raise ValueError("geçersiz kolon")
    return entity, str(col), str(unit)


def _aware(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _age_minutes(ts: Optional[datetime]) -> Optional[int]:
    ts = _aware(ts)
    if ts is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds() / 60))


def _r(v: Any, d: int = 1) -> Optional[float]:
    try:
        if v is None:
            return None
        return round(float(v), d)
    except (TypeError, ValueError):
        return None


def _delta(now: Optional[float], then: Optional[float]) -> Optional[float]:
    if now is None or then is None:
        return None
    return round(now - then, 1)


def _classify_host(h: HypervisorHostMetric) -> str:
    age = _age_minutes(h.timestamp)
    if age is None or age > STALE_MINUTES:
        return "unknown"
    conn = (h.connection_state or "").lower()
    if conn and conn not in ("connected", "up"):
        return "critical"
    status = (h.overall_status or "").lower()
    if status == "red":
        return "critical"
    if status == "yellow":
        return "warning"
    cpu, mem, ds = h.cpu_usage_pct, h.mem_usage_pct, h.ds_usage_pct
    ready, lat = h.cpu_ready_pct, h.disk_latency_ms
    if (cpu is not None and cpu >= 90) or (mem is not None and mem >= 93) or (ds is not None and ds >= 90):
        return "critical"
    if (ready is not None and ready >= 10) or (lat is not None and lat >= 40):
        return "critical"
    if h.maintenance_mode:
        return "warning"
    if (cpu is not None and cpu >= 75) or (mem is not None and mem >= 82) or (ds is not None and ds >= 80):
        return "warning"
    if (ready is not None and ready >= 5) or (lat is not None and lat >= 20):
        return "warning"
    return "healthy"


def _bucket_counts(labels: Sequence[str]) -> Dict[str, int]:
    out = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
    for lab in labels:
        out[lab if lab in out else "unknown"] += 1
    return out


def _hv_scope(ids: Optional[Sequence[int]]) -> Optional[List[int]]:
    """None = tüm vCenter. Boş liste = hiçbiri."""
    if ids is None:
        return None
    out: List[int] = []
    seen = set()
    for raw in ids:
        try:
            hid = int(raw)
        except (TypeError, ValueError):
            continue
        if hid in seen:
            continue
        seen.add(hid)
        out.append(hid)
    return out


def _hv_sql(ids: Optional[Sequence[int]], column: str = "hypervisor_id") -> Tuple[str, Dict[str, Any]]:
    scoped = _hv_scope(ids)
    if scoped is None:
        return "TRUE", {}
    if not scoped:
        return "FALSE", {}
    params: Dict[str, Any] = {}
    ph = []
    for i, hid in enumerate(scoped):
        key = f"hvf{i}"
        ph.append(f":{key}")
        params[key] = hid
    return f"{column} IN ({', '.join(ph)})", params


def _latest_hosts(db: Session, hypervisor_ids: Optional[Sequence[int]] = None) -> List[HypervisorHostMetric]:
    from sqlalchemy import func as sa_func

    subq = (
        db.query(
            HypervisorHostMetric.hypervisor_id,
            HypervisorHostMetric.host_name,
            sa_func.max(HypervisorHostMetric.timestamp).label("last_ts"),
        )
        .group_by(HypervisorHostMetric.hypervisor_id, HypervisorHostMetric.host_name)
        .subquery()
    )
    q = (
        db.query(HypervisorHostMetric)
        .join(
            subq,
            (HypervisorHostMetric.hypervisor_id == subq.c.hypervisor_id)
            & (HypervisorHostMetric.host_name == subq.c.host_name)
            & (HypervisorHostMetric.timestamp == subq.c.last_ts),
        )
    )
    scoped = _hv_scope(hypervisor_ids)
    if scoped is not None:
        q = q.filter(HypervisorHostMetric.hypervisor_id.in_(scoped or [-1]))
    return q.all()


def parse_hypervisor_ids(
    hypervisor_id: Optional[int] = None,
    hypervisor_ids: Optional[str] = None,
) -> Optional[List[int]]:
    """None = tüm vCenter. Boş liste = açıkça hiçbiri."""
    if hypervisor_ids is None and hypervisor_id is None:
        return None
    raw: List[int] = []
    if hypervisor_ids is not None:
        for part in hypervisor_ids.split(","):
            part = part.strip()
            if part.isdigit():
                raw.append(int(part))
    if hypervisor_id is not None:
        raw.append(int(hypervisor_id))
    return _hv_scope(raw) or []


def _avg_host_window(
    db: Session, start: datetime, end: datetime, hypervisor_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Optional[float]]:
    clause, hv_params = _hv_sql(hypervisor_ids)
    row = db.execute(
        text(
            f"""
            SELECT avg(cpu_usage_pct) AS cpu, avg(mem_usage_pct) AS mem,
                   avg(ds_usage_pct) AS ds,
                   avg(COALESCE(net_rx_kbps,0)+COALESCE(net_tx_kbps,0)) AS net
            FROM hypervisor_host_metrics
            WHERE timestamp >= :a AND timestamp < :b
              AND {clause}
            """
        ),
        {"a": start, "b": end, **hv_params},
    ).mappings().first()
    if not row:
        return {"cpu": None, "mem": None, "ds": None, "net": None}
    return {
        "cpu": _r(row["cpu"]),
        "mem": _r(row["mem"]),
        "ds": _r(row["ds"]),
        "net": _r(row["net"]),
    }


def _entity_type_from_raw(raw: Any) -> str:
    if not isinstance(raw, dict):
        return "unknown"
    et = str(raw.get("entity_type") or raw.get("object_type") or raw.get("entity") or "").lower()
    name = str(raw.get("entity_name") or raw.get("host_name") or "")
    if "datastore" in et or et.startswith("ds"):
        return "datastore"
    if "host" in et or "esx" in et:
        return "host"
    if "cluster" in et:
        return "cluster"
    if "vm" in et or "virtual" in et:
        return "vm"
    if "datastore" in name.lower():
        return "datastore"
    return et or "unknown"


def _active_alerts(db: Session, limit: int = 80, hypervisor_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
    rows = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source.in_(("vcenter_alarm", "vcenter_event")),
            SystemEvent.resolved.is_(False),
            (SystemEvent.event_type == "vcenter_alarm") | (SystemEvent.source == "vcenter_alarm"),
        )
        .order_by(SystemEvent.last_seen.desc().nullslast())
        .limit(limit)
        .all()
    )
    out = []
    now = datetime.now(timezone.utc)
    for r in rows:
        raw = r.raw_data if isinstance(r.raw_data, dict) else {}
        started = _aware(r.created_at)
        last = _aware(r.last_seen or r.created_at)
        dur_min = None
        if started:
            dur_min = max(0, int((now - started).total_seconds() / 60))
        host_name = raw.get("host_name") or raw.get("host")
        entity = raw.get("entity_name") or host_name or r.title
        out.append({
            "id": r.id,
            "severity": (r.severity or "info").lower(),
            "object": entity,
            "object_type": _entity_type_from_raw(raw) or ("host" if host_name else "unknown"),
            "problem": r.title,
            "description": (r.description or "")[:240],
            "start_time": started.isoformat() if started else None,
            "last_seen": last.isoformat() if last else None,
            "duration_min": dur_min,
            "current_value": raw.get("value") or raw.get("current_value"),
            "threshold": raw.get("threshold"),
            "status": "acknowledged" if r.is_acknowledged else "unacknowledged",
            "acknowledged": bool(r.is_acknowledged),
            "resolved": bool(r.resolved),
            "hypervisor": raw.get("hypervisor_name"),
            "host_name": host_name,
            "source": r.source,
            "hypervisor_id": raw.get("hypervisor_id"),
        })
    scoped = _hv_scope(hypervisor_ids)
    if scoped is not None:
        wanted = set(scoped)
        out = [
            a for a in out
            if str(a.get("hypervisor_id") or "").isdigit() and int(a["hypervisor_id"]) in wanted
        ]
    return out


def _timeline(db: Session, hours: int = 24, limit: int = 40) -> List[Dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source.in_(VCENTER_SOURCES),
            SystemEvent.created_at >= since,
        )
        .order_by(SystemEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    for r in rows:
        raw = r.raw_data if isinstance(r.raw_data, dict) else {}
        ts = _aware(r.created_at)
        items.append({
            "id": r.id,
            "time": ts.isoformat() if ts else None,
            "severity": (r.severity or "info").lower(),
            "source": r.source,
            "title": r.title,
            "object": raw.get("entity_name") or raw.get("host_name"),
            "object_type": _entity_type_from_raw(raw),
        })
    return items


def _top_sql(db: Session, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return [dict(r._mapping) for r in db.execute(text(sql), params)]
    except Exception as exc:
        logger.warning("virt monitoring query: %s", exc)
        return []


def _capacity_rows(db: Session, hypervisor_ids: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
    clause, hv_params = _hv_sql(hypervisor_ids)
    sql = f"""
    WITH latest AS (
      SELECT DISTINCT ON (hypervisor_id, name)
             hypervisor_id, name, usage_pct, free_gb, used_gb, capacity_gb, timestamp
      FROM virt_datastore_metrics
      WHERE timestamp >= now() - interval '6 hours'
        AND {clause}
      ORDER BY hypervisor_id, name, timestamp DESC
    ),
    old AS (
      SELECT hypervisor_id, name, avg(usage_pct) AS usage_pct
      FROM virt_datastore_metrics
      WHERE timestamp >= now() - interval '31 days'
        AND timestamp <  now() - interval '29 days'
        AND {clause}
      GROUP BY hypervisor_id, name
    )
    SELECT l.hypervisor_id, l.name, l.usage_pct, l.free_gb, l.used_gb, l.capacity_gb,
           o.usage_pct AS usage_30d, h.name AS hypervisor_name
    FROM latest l
    LEFT JOIN old o
      ON o.name = l.name
     AND o.hypervisor_id IS NOT DISTINCT FROM l.hypervisor_id
    LEFT JOIN hypervisors h ON h.id = l.hypervisor_id
    ORDER BY l.usage_pct DESC NULLS LAST
    LIMIT 12
    """
    rows = _top_sql(db, sql, hv_params)
    counts = count_names((r.get("hypervisor_id"), str(r.get("name") or "")) for r in rows)
    hv_names = {r.get("hypervisor_id"): r.get("hypervisor_name") for r in rows if r.get("hypervisor_id") is not None}
    out = []
    for r in rows:
        cur = _r(r.get("usage_pct"))
        old = _r(r.get("usage_30d"))
        delta = _delta(cur, old)
        days = None
        if cur is not None and delta is not None and delta > 0.2:
            gap = 80.0 - cur
            if gap > 0:
                days = round(gap / (delta / 30.0), 1)
        raw_name = str(r.get("name") or "")
        out.append({
            "name": disambiguate(raw_name, r.get("hypervisor_id"), counts, hv_names),
            "hypervisor_name": r.get("hypervisor_name"),
            "kind": "datastore",
            "current": cur,
            "free_gb": _r(r.get("free_gb")),
            "used_gb": _r(r.get("used_gb")),
            "trend_30d": delta,
            "forecast": round(cur + (delta or 0), 1) if cur is not None else None,
            "headroom": round(100 - cur, 1) if cur is not None else None,
            "days_to_80": days,
            "risk": (
                "critical" if (cur is not None and cur >= 90) or (days is not None and days <= 7)
                else "warning" if (cur is not None and cur >= 80) or (days is not None and days <= 21)
                else "ok"
            ),
        })
    return out


def _build_summary(
    health_label: str,
    buckets: Dict[str, int],
    alerts: List[Dict[str, Any]],
    problems: List[Dict[str, Any]],
    capacity: List[Dict[str, Any]],
    crit: Optional[int] = None,
    warn: Optional[int] = None,
) -> str:
    if crit is None:
        crit = sum(1 for a in alerts if a.get("severity") in ("critical", "emergency"))
    if warn is None:
        warn = sum(1 for a in alerts if a.get("severity") == "warning")
    parts = [
        f"Ortam durumu: {health_label}. "
        f"ESXi sağlığı — sağlıklı {buckets.get('healthy', 0)}, "
        f"uyarı {buckets.get('warning', 0)}, kritik {buckets.get('critical', 0)}, "
        f"bilinmeyen {buckets.get('unknown', 0)}."
    ]
    if crit or warn:
        parts.append(f"Açık vCenter alarmı: {crit} kritik, {warn} uyarı.")
    else:
        parts.append("Açık kritik vCenter alarmı yok.")
    if problems:
        top = problems[0]
        aff = top.get("affected_count")
        aff_s = f", {aff} varlık etkileniyor" if aff else ""
        parts.append(f"Öne çıkan sorun: {top.get('title')}{aff_s}.")
    risk = next((c for c in capacity if c.get("risk") in ("critical", "warning")), None)
    if risk and risk.get("days_to_80") is not None:
        parts.append(
            f"{risk['name']} depolama %{risk.get('current')} — "
            f"%80 eşiğine yaklaşık {risk['days_to_80']} gün."
        )
    parts.append("Kaynak: vCenter sync (Timescale). Guest OS / Prometheus karışmaz.")
    return " ".join(parts)


def _top_problems(
    hosts: List[HypervisorHostMetric],
    alerts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    problems: List[Dict[str, Any]] = []
    for h in hosts:
        sev = _classify_host(h)
        if sev not in ("critical", "warning"):
            continue
        reasons = []
        if h.cpu_ready_pct and h.cpu_ready_pct >= 5:
            reasons.append(f"CPU ready %{_r(h.cpu_ready_pct)}")
        if h.mem_usage_pct and h.mem_usage_pct >= 82:
            reasons.append(f"bellek %{_r(h.mem_usage_pct)}")
        if h.disk_latency_ms and h.disk_latency_ms >= 20:
            reasons.append(f"disk gecikme {_r(h.disk_latency_ms)} ms")
        if h.ds_usage_pct and h.ds_usage_pct >= 80:
            reasons.append(f"datastore %{_r(h.ds_usage_pct)}")
        conn = (h.connection_state or "").lower()
        if conn and conn not in ("connected", "up"):
            reasons.append(f"bağlantı {h.connection_state}")
        if not reasons and (h.overall_status or "").lower() in ("red", "yellow"):
            reasons.append(f"overall {h.overall_status}")
        if not reasons:
            continue
        problems.append({
            "severity": sev,
            "object": h.host_name,
            "object_type": "host",
            "title": f"{h.host_name}: {', '.join(reasons)}",
            "affected_count": h.vms_running,
            "affected_label": "VM",
            "started": h.timestamp.isoformat() if h.timestamp else None,
            "current": {
                "cpu_pct": _r(h.cpu_usage_pct),
                "mem_pct": _r(h.mem_usage_pct),
                "ready_pct": _r(h.cpu_ready_pct),
                "latency_ms": _r(h.disk_latency_ms),
            },
        })
    for a in alerts:
        if a.get("severity") not in ("critical", "emergency", "warning"):
            continue
        problems.append({
            "severity": "critical" if a["severity"] in ("critical", "emergency") else "warning",
            "object": a.get("object"),
            "object_type": a.get("object_type"),
            "title": a.get("problem"),
            "affected_count": None,
            "affected_label": None,
            "started": a.get("start_time"),
            "alert_id": a.get("id"),
        })
    rank = {"critical": 0, "warning": 1}
    problems.sort(key=lambda p: (rank.get(p["severity"], 9), -(p.get("affected_count") or 0)))
    seen = set()
    uniq = []
    for p in problems:
        key = (p.get("object_type"), (p.get("object") or "").lower(), p.get("title"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
        if len(uniq) >= 8:
            break
    return uniq


def _consumer_rows(rows: List[Dict[str, Any]], hv_names: Dict[int, str], digits: int = 1) -> List[Dict[str, Any]]:
    counts = count_names((r.get("hypervisor_id"), str(r.get("vm_name") or "")) for r in rows)
    out = []
    for r in rows:
        name = str(r.get("vm_name") or "")
        hid = r.get("hypervisor_id")
        out.append({
            "name": disambiguate(name, hid, counts, hv_names),
            "host": r.get("host_name"),
            "hypervisor_name": hv_names.get(hid) if hid is not None else None,
            "value": _r(r.get("value"), digits),
        })
    return out


def _latest_vm_top(
    db: Session, column: str, extra_expr: Optional[str] = None, hypervisor_ids: Optional[Sequence[int]] = None,
) -> List[Dict[str, Any]]:
    if not column.replace("_", "").isalnum():
        return []
    expr = extra_expr or column
    clause, hv_params = _hv_sql(hypervisor_ids)
    sql = f"""
    SELECT vm_name, host_name, hypervisor_id, value, timestamp FROM (
      SELECT DISTINCT ON (hypervisor_id, vm_name)
             vm_name, host_name, hypervisor_id, {expr} AS value, timestamp
      FROM virt_vm_metrics
      WHERE timestamp >= now() - interval '2 hours'
        AND ({expr}) IS NOT NULL
        AND {clause}
      ORDER BY hypervisor_id, vm_name, timestamp DESC
    ) t
    ORDER BY value DESC NULLS LAST
    LIMIT 8
    """
    return _top_sql(db, sql, hv_params)


def build_overview(db: Session, hypervisor_ids: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    scoped = _hv_scope(hypervisor_ids)
    hvs = db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE).all()
    if scoped is not None:
        wanted = set(scoped)
        hvs = [h for h in hvs if h.id in wanted]
    hosts = _latest_hosts(db, scoped)
    host_labels = [_classify_host(h) for h in hosts]
    host_buckets = _bucket_counts(host_labels)

    vm_q = db.query(Server).filter(Server.hypervisor_id.isnot(None))
    if scoped is not None:
        vm_q = vm_q.filter(Server.hypervisor_id.in_(scoped or [-1]))
    vm_total = vm_q.count()
    vm_running = vm_q.filter(Server.vm_power_state.ilike("%on%")).count()

    ds_clause, ds_params = _hv_sql(scoped)
    ds_health = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
    ds_rows = _top_sql(
        db,
        f"""
        SELECT DISTINCT ON (hypervisor_id, name)
               hypervisor_id, name, usage_pct, read_latency_ms, write_latency_ms, timestamp
        FROM virt_datastore_metrics
        WHERE timestamp >= now() - interval '2 days'
          AND {ds_clause}
        ORDER BY hypervisor_id, name, timestamp DESC
        """,
        ds_params,
    )
    for r in ds_rows:
        age = _age_minutes(_aware(r.get("timestamp")))
        usage = _r(r.get("usage_pct"))
        lats = [x for x in (_r(r.get("read_latency_ms")), _r(r.get("write_latency_ms"))) if x is not None]
        lat = max(lats) if lats else 0
        if age is None or age > STALE_MINUTES * 2:
            ds_health["unknown"] += 1
        elif (usage is not None and usage >= 90) or lat >= 40:
            ds_health["critical"] += 1
        elif (usage is not None and usage >= 80) or lat >= 20:
            ds_health["warning"] += 1
        else:
            ds_health["healthy"] += 1

    cluster_names = {(h.hypervisor_id, h.cluster_name) for h in hosts if h.cluster_name}
    connected = sum(
        1 for h in hosts
        if (h.connection_state or "").lower() in ("connected", "up", "")
        and _classify_host(h) != "unknown"
    )
    availability = round(100.0 * connected / len(hosts), 2) if hosts else None

    last_host_ts = max((_aware(h.timestamp) for h in hosts if h.timestamp), default=None)
    last_alarm = (
        db.query(SystemEvent)
        .filter(SystemEvent.source.in_(VCENTER_SOURCES))
        .order_by(SystemEvent.last_seen.desc().nullslast())
        .first()
    )
    last_alarm_ts = _aware(last_alarm.last_seen or last_alarm.created_at) if last_alarm else None

    alerts = _active_alerts(db, hypervisor_ids=scoped)
    if scoped is not None:
        alert_total = len(alerts)
        crit_alerts = sum(1 for a in alerts if a.get("severity") in ("critical", "emergency"))
        warn_alerts = sum(1 for a in alerts if a.get("severity") == "warning")
    else:
        alarm_q = db.query(SystemEvent).filter(
            SystemEvent.source.in_(("vcenter_alarm", "vcenter_event")),
            SystemEvent.resolved.is_(False),
            (SystemEvent.event_type == "vcenter_alarm") | (SystemEvent.source == "vcenter_alarm"),
        )
        alert_total = alarm_q.count()
        crit_alerts = (
            alarm_q.filter(SystemEvent.severity.in_(("critical", "emergency"))).count()
        )
        warn_alerts = alarm_q.filter(SystemEvent.severity == "warning").count()
    problems = _top_problems(hosts, alerts)
    capacity = _capacity_rows(db, scoped)

    cur = _avg_host_window(db, now - timedelta(minutes=STALE_MINUTES), now, scoped)
    ago_1h = _avg_host_window(db, now - timedelta(hours=2), now - timedelta(hours=1), scoped)
    ago_24h = _avg_host_window(db, now - timedelta(hours=25), now - timedelta(hours=23), scoped)
    ago_7d = _avg_host_window(db, now - timedelta(days=7, hours=2), now - timedelta(days=7), scoped)
    ago_30d = _avg_host_window(db, now - timedelta(days=31), now - timedelta(days=29), scoped)

    def _cmp(key: str) -> Dict[str, Any]:
        n = cur.get(key)
        return {
            "current": n,
            "d1h": _delta(n, ago_1h.get(key)),
            "d24h": _delta(n, ago_24h.get(key)),
            "d7d": _delta(n, ago_7d.get(key)),
            "d30d": _delta(n, ago_30d.get(key)),
        }

    top_vm_cpu = _latest_vm_top(db, "cpu_usage_pct", hypervisor_ids=scoped)
    top_vm_mem = _latest_vm_top(db, "mem_usage_pct", hypervisor_ids=scoped)
    top_vm_net = _latest_vm_top(
        db, "net_tx_kbps",
        extra_expr="(COALESCE(net_rx_kbps,0)+COALESCE(net_tx_kbps,0))",
        hypervisor_ids=scoped,
    )

    hosts_by_cpu = sorted(hosts, key=lambda h: -(h.cpu_usage_pct or 0))[:5]
    hosts_by_mem = sorted(hosts, key=lambda h: -(h.mem_usage_pct or 0))[:5]

    host_age = _age_minutes(last_host_ts)
    source_state = "connected"
    if not hvs:
        source_state = "missing"
    elif host_age is None:
        source_state = "unknown"
    elif host_age > 120:
        source_state = "critical"
    elif host_age > 30:
        source_state = "warning"

    score_crit = host_buckets["critical"] + crit_alerts
    score_warn = host_buckets["warning"] + warn_alerts
    if source_state in ("missing", "unknown") and not hosts:
        health_label, health_grade = "Veri yok", "unknown"
    elif score_crit:
        health_label, health_grade = "Kritik", "critical"
    elif score_warn:
        health_label, health_grade = "Uyarı", "warning"
    else:
        health_label, health_grade = "Sağlıklı", "healthy"

    summary = _build_summary(
        health_label, host_buckets, alerts, problems, capacity,
        crit=crit_alerts, warn=warn_alerts,
    )

    esx_cards = []
    hv_names = {h.id: h.name for h in hvs}
    host_counts = count_names((h.hypervisor_id, h.host_name or "") for h in hosts)
    for h in sorted(hosts, key=lambda x: x.host_name or ""):
        esx_cards.append({
            "host_name": disambiguate(h.host_name or "", h.hypervisor_id, host_counts, hv_names),
            "hypervisor_id": h.hypervisor_id,
            "hypervisor_name": hv_names.get(h.hypervisor_id),
            "cluster_name": h.cluster_name,
            "health": _classify_host(h),
            "overall_status": h.overall_status,
            "connection_state": h.connection_state,
            "maintenance_mode": bool(h.maintenance_mode),
            "cpu_pct": _r(h.cpu_usage_pct),
            "mem_pct": _r(h.mem_usage_pct),
            "ds_pct": _r(h.ds_usage_pct),
            "cpu_ready_pct": _r(h.cpu_ready_pct),
            "disk_latency_ms": _r(h.disk_latency_ms),
            "vms_running": h.vms_running,
            "vms_total": h.vms_total,
            "as_of": h.timestamp.isoformat() if h.timestamp else None,
        })

    return {
        "ok": True,
        "source": "vcenter",
        "generated_at": now.isoformat(),
        "health": {
            "label": health_label,
            "grade": health_grade,
            "hosts": host_buckets,
            "datastores": ds_health,
            "availability_pct": availability,
            "active_alerts": alert_total,
            "critical_alerts": crit_alerts,
            "warning_alerts": warn_alerts,
        },
        "inventory": {
            "vcenters": len(hvs),
            "esxi_hosts": len(hosts),
            "vms": vm_total,
            "vms_running": vm_running,
            "clusters": len(cluster_names),
            "datastores": len(ds_rows),
        },
        "data_source": {
            "name": "vCenter",
            "state": source_state,
            "last_host_sync": last_host_ts.isoformat() if last_host_ts else None,
            "host_age_min": host_age,
            "last_alarm_sync": last_alarm_ts.isoformat() if last_alarm_ts else None,
            "alarm_age_min": _age_minutes(last_alarm_ts),
            "interval_min": 15,
            "stale": bool(host_age is None or host_age > STALE_MINUTES),
        },
        "summary": summary,
        "alerts": alerts[:60],
        "top_problems": problems,
        "capacity": capacity,
        "comparison": {
            "cpu": _cmp("cpu"),
            "memory": _cmp("mem"),
            "storage": _cmp("ds"),
            "network": _cmp("net"),
        },
        "top_consumers": {
            "vm_cpu": _consumer_rows(top_vm_cpu, hv_names),
            "vm_memory": _consumer_rows(top_vm_mem, hv_names),
            "vm_network": _consumer_rows(top_vm_net, hv_names, digits=0),
            "host_cpu": [
                {
                    "name": disambiguate(h.host_name or "", h.hypervisor_id, host_counts, hv_names),
                    "hypervisor_name": hv_names.get(h.hypervisor_id),
                    "value": _r(h.cpu_usage_pct),
                }
                for h in hosts_by_cpu
            ],
            "host_memory": [
                {
                    "name": disambiguate(h.host_name or "", h.hypervisor_id, host_counts, hv_names),
                    "hypervisor_name": hv_names.get(h.hypervisor_id),
                    "value": _r(h.mem_usage_pct),
                }
                for h in hosts_by_mem
            ],
        },
        "timeline": _timeline(db),
        "esxi": esx_cards,
        "chart_defaults": {
            "ranges": list(RANGE_SPEC.keys()),
            "max_objects": MAX_SERIES_OBJECTS,
            "native_interval_min": 15,
        },
    }


def list_objects(
    db: Session,
    *,
    kind: str,
    q: str = "",
    cluster: str = "",
    hypervisor_ids: Optional[Sequence[int]] = None,
    limit: int = 80,
) -> Dict[str, Any]:
    kind = (kind or "host").strip().lower()
    if kind not in _KIND_TABLE:
        raise ValueError("kind vm|host|datastore olmalı")
    limit = max(1, min(int(limit or 80), 200))
    needle = (q or "").strip()
    qn = f"%{needle}%" if needle else "%"
    q_empty = not needle
    cl = (cluster or "").strip()
    cl_empty = not cl
    clause, hv_params = _hv_sql(hypervisor_ids, "m.hypervisor_id")
    params_base = {
        "q": qn, "q_empty": q_empty, "lim": limit,
        **hv_params,
    }

    if kind == "host":
        sql = f"""
        SELECT DISTINCT ON (m.hypervisor_id, m.host_name)
               m.host_name AS name, m.host_ref AS ref, m.cluster_name,
               m.hypervisor_id, h.name AS hypervisor_name,
               m.connection_state, m.overall_status,
               m.cpu_usage_pct, m.mem_usage_pct, m.timestamp
        FROM hypervisor_host_metrics m
        LEFT JOIN hypervisors h ON h.id = m.hypervisor_id
        WHERE (:q_empty OR m.host_name ILIKE :q OR COALESCE(m.cluster_name,'') ILIKE :q
               OR COALESCE(h.name,'') ILIKE :q)
          AND (:cl_empty OR m.cluster_name ILIKE :cl)
          AND {clause}
        ORDER BY m.hypervisor_id, m.host_name, m.timestamp DESC
        LIMIT :lim
        """
        rows = _top_sql(db, sql, {**params_base, "cl": f"%{cl}%", "cl_empty": cl_empty})
        items = [_object_item(r, "host", f"CPU {_r(r.get('cpu_usage_pct'))}% · RAM {_r(r.get('mem_usage_pct'))}%") for r in rows]
        return {"ok": True, "kind": kind, "count": len(items), "items": items}

    if kind == "datastore":
        sql = f"""
        SELECT DISTINCT ON (m.hypervisor_id, m.name)
               m.name, m.ds_type, m.usage_pct, m.free_gb, m.hypervisor_id,
               h.name AS hypervisor_name, m.timestamp
        FROM virt_datastore_metrics m
        LEFT JOIN hypervisors h ON h.id = m.hypervisor_id
        WHERE m.timestamp >= now() - interval '2 days'
          AND (:q_empty OR m.name ILIKE :q OR COALESCE(h.name,'') ILIKE :q)
          AND {clause}
        ORDER BY m.hypervisor_id, m.name, m.timestamp DESC
        LIMIT :lim
        """
        rows = _top_sql(db, sql, params_base)
        items = [_object_item(
            r, "datastore",
            f"%{_r(r.get('usage_pct'))} · {_r(r.get('free_gb'))} GB boş",
            cluster=r.get("ds_type"),
        ) for r in rows]
        return {"ok": True, "kind": kind, "count": len(items), "items": items}

    sql = f"""
    SELECT DISTINCT ON (m.hypervisor_id, m.vm_name)
           m.vm_name AS name, m.vm_ref AS ref, m.host_name, m.cluster_name,
           m.hypervisor_id, h.name AS hypervisor_name,
           m.power_state, m.cpu_usage_pct, m.mem_usage_pct, m.timestamp
    FROM virt_vm_metrics m
    LEFT JOIN hypervisors h ON h.id = m.hypervisor_id
    WHERE m.vm_name IS NOT NULL
      AND m.timestamp >= now() - interval '2 days'
      AND (:q_empty OR m.vm_name ILIKE :q OR COALESCE(m.host_name,'') ILIKE :q
           OR COALESCE(m.cluster_name,'') ILIKE :q OR COALESCE(h.name,'') ILIKE :q)
      AND (:cl_empty OR m.cluster_name ILIKE :cl OR m.host_name ILIKE :cl)
      AND {clause}
    ORDER BY m.hypervisor_id, m.vm_name, m.timestamp DESC
    LIMIT :lim
    """
    rows = _top_sql(db, sql, {**params_base, "cl": f"%{cl}%", "cl_empty": cl_empty})
    items = []
    seen = set()
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        key = (r.get("hypervisor_id"), str(name).lower())
        if key in seen:
            continue
        seen.add(key)
        items.append(_object_item(
            r, "vm",
            f"{r.get('host_name') or '—'} · CPU {_r(r.get('cpu_usage_pct'))}%",
            host=r.get("host_name"),
        ))
    if len(items) < limit:
        q_srv = db.query(Server).filter(Server.hypervisor_id.isnot(None))
        scoped = _hv_scope(hypervisor_ids)
        if scoped is not None:
            q_srv = q_srv.filter(Server.hypervisor_id.in_(scoped or [-1]))
        if needle:
            like = f"%{needle}%"
            q_srv = q_srv.filter(
                (Server.name.ilike(like))
                | (Server.vm_name.ilike(like))
                | (Server.hostname.ilike(like))
            )
        extra = q_srv.order_by(Server.name.asc()).limit(limit).all()
        hv_ids = {s.hypervisor_id for s in extra if s.hypervisor_id}
        hv_names = {
            h.id: h.name
            for h in db.query(Hypervisor).filter(Hypervisor.id.in_(hv_ids or [-1])).all()
        } if extra else {}
        for s in extra:
            label = s.vm_name or s.name
            if not label:
                continue
            key = (s.hypervisor_id, label.lower())
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "id": encode_ref(s.hypervisor_id, label),
                "name": label,
                "kind": "vm",
                "cluster": None,
                "host": None,
                "hypervisor_id": s.hypervisor_id,
                "hypervisor_name": hv_names.get(s.hypervisor_id),
                "status": s.vm_power_state,
                "hint": "envanter — zaman serisi yok olabilir",
                "server_id": s.id,
            })
            if len(items) >= limit:
                break
    return {"ok": True, "kind": kind, "count": len(items), "items": items}


def _object_item(r: Dict[str, Any], kind: str, hint: str, cluster: Any = None, host: Any = None) -> Dict[str, Any]:
    name = r.get("name") or ""
    hid = r.get("hypervisor_id")
    return {
        "id": encode_ref(hid, str(name)),
        "name": name,
        "kind": kind,
        "cluster": cluster if cluster is not None else r.get("cluster_name"),
        "host": host,
        "hypervisor_id": hid,
        "hypervisor_name": r.get("hypervisor_name"),
        "status": r.get("connection_state") or r.get("overall_status") or r.get("power_state"),
        "hint": hint,
    }


def query_series(
    db: Session,
    *,
    kind: str,
    names: Sequence[str],
    metric: str,
    range_key: str,
    window_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    names = parse_names(None, names)
    if not names:
        return {
            "ok": True,
            "kind": kind,
            "metric": metric,
            "range": parse_range(range_key),
            "series": [],
            "note": "nesne seçilmedi — seri çekilmedi",
        }
    entity, column, unit = _metric_column(kind, metric)
    table, key_col = _KIND_TABLE[entity]
    rng = parse_range(range_key)
    spec = RANGE_SPEC[rng]
    if window_minutes and int(window_minutes) > 0:
        minutes = max(15, int(window_minutes))
        bucket = bucket_for_window(minutes)
        rng = f"{minutes}m"
    else:
        minutes = int(spec["minutes"])
        bucket = spec["bucket"]

    scoped = [parse_ref(n) for n in names]
    pair_clauses = []
    params: Dict[str, Any] = {}
    for i, (hid, nm) in enumerate(scoped):
        if hid is not None:
            pair_clauses.append(f"(hypervisor_id = :h{i} AND {key_col} = :n{i})")
            params[f"h{i}"] = hid
            params[f"n{i}"] = nm
        else:
            pair_clauses.append(f"({key_col} = :n{i})")
            params[f"n{i}"] = nm
    where_names = "(" + " OR ".join(pair_clauses) + ")"

    def _rows_for(mins: int, buck: Optional[str]) -> List[Dict[str, Any]]:
        qparams = {**params, "mins": mins}
        if buck:
            sql = f"""
            SELECT hypervisor_id, {key_col} AS name,
                   time_bucket('{buck}', timestamp) AS ts,
                   avg({column}) AS value
            FROM {table}
            WHERE timestamp >= now() - (:mins * interval '1 minute')
              AND {where_names}
            GROUP BY hypervisor_id, {key_col}, ts
            ORDER BY hypervisor_id, {key_col}, ts
            """
        else:
            sql = f"""
            SELECT hypervisor_id, {key_col} AS name, timestamp AS ts, {column} AS value
            FROM {table}
            WHERE timestamp >= now() - (:mins * interval '1 minute')
              AND {where_names}
            ORDER BY hypervisor_id, {key_col}, timestamp
            """
        return _top_sql(db, sql, qparams)

    def _to_series(rows: List[Dict[str, Any]]) -> Dict[Tuple[Optional[int], str], List[Dict[str, Any]]]:
        by_key: Dict[Tuple[Optional[int], str], List[Dict[str, Any]]] = {}
        for r in rows:
            key = (r.get("hypervisor_id"), str(r.get("name") or ""))
            ts = r.get("ts")
            by_key.setdefault(key, []).append({
                "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
                "v": _r(r.get("value"), 3),
            })
        return by_key

    by_key = _to_series(_rows_for(minutes, bucket))
    expanded = False
    # 15/30 dk pencere sync gecikince 0–1 nokta kalıyor; çizgi için en az 8 saat.
    if not by_key or any(len(pts) < 2 for pts in by_key.values()):
        widen = max(minutes, 480)
        if widen != minutes or bucket:
            wider = _to_series(_rows_for(widen, None if widen <= 1440 else "1 hour"))
            if wider:
                by_key = wider
                expanded = True
                minutes = widen

    hv_ids = {hid for hid, _ in by_key if hid is not None}
    hv_names = {
        h.id: h.name
        for h in db.query(Hypervisor).filter(Hypervisor.id.in_(hv_ids or [-1])).all()
    } if hv_ids else {}
    name_counts = count_names(by_key.keys())
    series = []
    for (hid, nm), points in by_key.items():
        series.append({
            "name": disambiguate(nm, hid, name_counts, hv_names),
            "object": nm,
            "hypervisor_id": hid,
            "hypervisor_name": hv_names.get(hid) if hid is not None else None,
            "ref": encode_ref(hid, nm),
            "points": points,
            "outside_window": expanded,
        })
    series.sort(key=lambda s: (s.get("name") or ""))
    last_ts = None
    for s in series:
        if s["points"]:
            last_ts = s["points"][-1]["t"]
    return {
        "ok": True,
        "kind": entity,
        "metric": metric,
        "column": column,
        "unit": unit,
        "range": rng,
        "expanded_minutes": minutes if expanded else None,
        "native_interval_min": 10 if entity == "vm" else 15,
        "source": "vcenter",
        "as_of": last_ts,
        "series": series,
    }
