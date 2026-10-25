"""Yönetici raporu gerçekleri. Sayılar burada üretilir. Platform API'sine gidilmez.

Sentetik hypervisor, küme ve sunucu sayaç, skor, trend ve riske girmez.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.event import Incident, SystemEvent
from app.models.infrastructure_report import CostConfig, InfrastructureReport
from app.models.server import Server
from app.services.chat_quality import power_state as ps
from app.services.report_analytics import compute_trend_from_series
from app.services.synthetic_scope import (
    synthetic_cluster_ids, synthetic_hypervisor_ids, synthetic_server_ids,
)

REQUIRED_FS_METRICS = (
    "node_filesystem_size_bytes",
    "node_filesystem_avail_bytes",
    "node_filesystem_files",
    "node_filesystem_files_free",
)
_SEV = {"emergency": 25, "critical": 15, "warning": 5, "info": 1}
_MONTHLY = "executive_monthly"


def _display_int(value: int, unit: str = "adet") -> Dict[str, Any]:
    s = str(int(value))
    display = [s, f"{s} {unit}"]
    return {"value": int(value), "unit": unit, "display": display}


def _section(sid: str, title: str, method_id: str, status: str, **extra) -> Dict[str, Any]:
    base = {
        "id": sid, "title": title, "method_id": method_id, "status": status,
        "numbers": {}, "labels": {}, "rows": [], "ranges": {}, "confidence": None, "notes": [],
    }
    base.update(extra)
    return base


def _ready(sid: str, status: str, reason: str, days_available: Optional[int] = None, days_required: Optional[int] = None) -> Dict[str, Any]:
    return {
        "section_id": sid, "status": status, "reason": reason,
        "days_available": days_available, "days_required": days_required,
    }


def _percentile(values: Sequence[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return ordered[int(k)]
    return ordered[lo] * (hi - k) + ordered[hi] * (k - lo)


def _exclude_event(ev: SystemEvent, servers: set, clusters: set, hypervisors: set) -> bool:
    if ev.server_id and ev.server_id in servers:
        return True
    raw = ev.raw_data or {}
    try:
        if raw.get("cluster_id") is not None and int(raw["cluster_id"]) in clusters:
            return True
        if raw.get("hypervisor_id") is not None and int(raw["hypervisor_id"]) in hypervisors:
            return True
    except (TypeError, ValueError):
        return False
    return False


def _events(db: Session, start: datetime, end: datetime) -> List[SystemEvent]:
    servers = synthetic_server_ids(db)
    clusters = synthetic_cluster_ids(db)
    hypervisors = synthetic_hypervisor_ids(db)
    rows = (
        db.query(SystemEvent)
        .filter(SystemEvent.created_at >= start, SystemEvent.created_at < end)
        .all()
    )
    return [ev for ev in rows if not _exclude_event(ev, servers, clusters, hypervisors)]


def _mom_section(db: Session) -> Dict[str, Any]:
    rows = (
        db.query(InfrastructureReport)
        .filter(
            InfrastructureReport.report_type == _MONTHLY,
            InfrastructureReport.status == "locked",
        )
        .order_by(InfrastructureReport.generated_at.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return _section(
            "a1_mom", "Ay-ay fark", "exec.monthly.summary", "unmeasured",
            notes=["İki kilitli aylık anlık görüntü yok. Canlı olaylardan geçen ay doldurulmaz."],
        )
    def _count(row: InfrastructureReport) -> Optional[int]:
        facts = (row.data or {}).get("facts") or {}
        for section in facts.get("sections") or []:
            if section.get("id") == "a1":
                spec = (section.get("numbers") or {}).get("events") or {}
                if spec.get("value") is None:
                    return None
                return int(spec["value"])
        return None
    newer, older = _count(rows[0]), _count(rows[1])
    if newer is None or older is None:
        return _section("a1_mom", "Ay-ay fark", "exec.monthly.summary", "unmeasured",
                        notes=["Kilitli anlık görüntüde olay sayısı yok."])
    delta = newer - older
    return _section(
        "a1_mom", "Ay-ay fark", "exec.monthly.summary", "ok",
        numbers={
            "newer": _display_int(newer),
            "older": _display_int(older),
            "delta": _display_int(delta, "fark"),
        },
        notes=["Yalnız iki kilitli aylık anlık görüntü."],
    )


def _a1(db: Session, start: datetime, end: datetime) -> Dict[str, Any]:
    events = _events(db, start, end)
    by_sev: Dict[str, int] = Counter((ev.severity or "info") for ev in events)
    ranked: Dict[str, int] = defaultdict(int)
    for ev in events:
        ranked[ev.title or ev.event_type or "olay"] += _SEV.get(ev.severity or "info", 1)
    top = sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    labels = {f"risk_{i}": name for i, (name, _score) in enumerate(top, start=1)}
    numbers = {"events": _display_int(len(events))}
    for sev in ("critical", "warning", "info"):
        numbers[sev] = _display_int(by_sev.get(sev, 0))
    section = _section(
        "a1", "Aylık yönetici özeti", "exec.monthly.summary", "ok",
        numbers=numbers, labels=labels,
        notes=["Sıralama kural tabanlıdır. Sentetik kayıtlar dışarıdadır."],
    )
    mom = _mom_section(db)
    return {
        "report_type": "a1",
        "sections": [section, mom],
        "data_readiness": [
            _ready("a1", "ok", "dönem olayları sayıldı"),
            _ready("a1_mom", mom["status"], (mom["notes"] or [""])[0]),
        ],
    }


def _b1(db: Session) -> Dict[str, Any]:
    syn = list(synthetic_hypervisor_ids(db))
    filt = "AND hypervisor_id != ALL(:syn)" if syn else ""
    params: Dict[str, Any] = {"syn": syn} if syn else {}
    rows = db.execute(text(f"""
        SELECT hypervisor_id,
               COALESCE(NULLIF(cluster_name, ''), '(küme yok)') AS cluster,
               count(DISTINCT date_trunc('day', timestamp)) AS days
        FROM hypervisor_host_metrics
        WHERE timestamp >= NOW() - INTERVAL '90 days'
          {filt}
        GROUP BY 1, 2
    """), params).all()
    cluster_rows = []
    any_ok = False
    for row in rows:
        days = int(row.days or 0)
        status = "ok" if days >= 14 else "unmeasured"
        confidence = None
        if status == "ok":
            series_rows = db.execute(text("""
                SELECT date_trunc('day', timestamp) AS day, avg(mem_usage_pct) AS v
                FROM hypervisor_host_metrics
                WHERE hypervisor_id = :hv
                  AND COALESCE(NULLIF(cluster_name, ''), '(küme yok)') = :cluster
                  AND timestamp >= NOW() - INTERVAL '90 days'
                  AND mem_usage_pct IS NOT NULL
                GROUP BY 1 ORDER BY 1
            """), {"hv": row.hypervisor_id, "cluster": row.cluster}).all()
            series = [float(r.v) for r in series_rows if r.v is not None]
            trend = compute_trend_from_series(series)
            confidence = trend.confidence
            if trend.confidence in ("low", "none") or trend.sample_count < 14:
                status = "unmeasured"
        if status == "ok":
            any_ok = True
        cluster_rows.append({
            "cluster": row.cluster, "hypervisor_id": row.hypervisor_id,
            "days": days, "status": status, "confidence": confidence,
        })
    virt = _section(
        "b1_virt", "Sanal küme ve datastore tükenme", "cap.cluster.mem_runway",
        "ok" if any_ok else "unmeasured",
        rows=cluster_rows,
        numbers={"clusters": _display_int(len(cluster_rows), "küme")} if cluster_rows else {},
        notes=[] if any_ok else ["14 günlük örnek yok veya güven low/none. Havuzlama yok."],
        confidence="mixed" if any_ok else "none",
    )
    ocp = _section(
        "b1_ocp", "OpenShift node tükenme", "exec.capacity.unmeasured", "unmeasured",
        notes=["Bu fazda OpenShift node tahmini üretilmez. Günlük kova birikiyor; ham tick örnek sayılmaz."],
    )
    linux = _section(
        "b1_linux", "Linux dosya sistemi", "exec.capacity.unmeasured", "unmeasured",
        notes=[
            "Gerekli metrikler yok: " + ", ".join(REQUIRED_FS_METRICS) + ".",
            "tmpfs, overlay ve squashfs sayılmaz. ainew müşteri Prometheus yapılandırmasını değiştirmez.",
        ],
    )
    return {
        "report_type": "b1",
        "sections": [virt, ocp, linux],
        "data_readiness": [
            _ready("b1_virt", virt["status"], (virt["notes"] or ["küme serisi"])[0], days_required=14),
            _ready("b1_ocp", "unmeasured", ocp["notes"][0], days_required=14),
            _ready("b1_linux", "unmeasured", linux["notes"][0]),
        ],
    }


def _b2(db: Session) -> Dict[str, Any]:
    syn = synthetic_hypervisor_ids(db)
    try:
        from app.services.virt_capacity_planner import build_capacity
        cap = build_capacity(db, with_forecast=False)
    except Exception:
        return {
            "report_type": "b2",
            "sections": [_section("b2", "Yatırım ihtiyacı", "cap.actions", "unmeasured",
                                  notes=["Kapasite planı okunamadı."])],
            "data_readiness": [_ready("b2", "unmeasured", "Kapasite planı okunamadı.")],
        }
    rows = []
    total = 0
    for cluster in cap.get("clusters") or []:
        if cluster.get("hypervisor_id") in syn:
            continue
        needed = sum(
            int(a.get("hosts_needed") or 0)
            for a in (cluster.get("actions") or [])
            if a.get("kind") == "invest"
        )
        n1 = (cluster.get("n_plus_one") or {}).get("status")
        total += needed
        rows.append({
            "cluster": cluster.get("cluster"),
            "hypervisor": cluster.get("hypervisor"),
            "hosts_needed": needed,
            "n_plus_one": n1,
            "host_profile": cluster.get("typical_host_mem_gb") is not None,
        })
    status = "ok" if rows else "unmeasured"
    notes = ["Host profili yoksa yalnız host adedi. RAM/disk alımı ayrı formül değil."]
    if not rows:
        notes = ["Ölçülen sanal küme yok."]
    return {
        "report_type": "b2",
        "sections": [_section(
            "b2", "Yatırım ihtiyacı", "cap.actions", status,
            numbers={"hosts_needed": _display_int(total, "host")} if rows else {},
            rows=rows, notes=notes,
        )],
        "data_readiness": [_ready("b2", status, notes[0])],
    }


def _cost_defined(db: Session) -> bool:
    try:
        return db.query(CostConfig.id).limit(1).first() is not None
    except Exception:
        return False


def _a2(db: Session) -> Dict[str, Any]:
    syn = synthetic_hypervisor_ids(db)
    q = db.query(Server).filter(Server.hypervisor_id.isnot(None))
    if syn:
        q = q.filter(~Server.hypervisor_id.in_(syn))
    vms = q.all()
    off = [v for v in vms if ps.is_off(v.vm_power_state)]
    wasted_cpu = sum(int(v.vm_cpu_count or 0) for v in off)
    wasted_ram = round(sum(int(v.vm_memory_mb or 0) for v in off) / 1024.0, 1)
    wasted_disk = sum(int(v.vm_disk_gb or 0) for v in off)
    numbers = {
        "powered_off": _display_int(len(off), "VM"),
        "wasted_vcpu": _display_int(wasted_cpu, "vCPU"),
        "wasted_disk_gb": _display_int(wasted_disk, "GB"),
    }
    ram_s = f"{wasted_ram:.1f}".replace(".", ",")
    numbers["wasted_ram_gb"] = {"value": wasted_ram, "unit": "GB", "display": [ram_s, f"{ram_s} GB"]}
    notes = ["Tahsis, tüketim değil."]
    if not _cost_defined(db):
        notes.append("Maliyet parametresi yok; para gösterilmez.")
    orphan = _section(
        "a2_orphan", "Yetim disk", "reclaim.summary", "unmeasured",
        notes=["Hazır yetim disk sorgusu yok."],
    )
    main = _section(
        "a2", "Atıl kaynak", "reclaim.vm.powered_off", "ok",
        numbers=numbers, notes=notes,
    )
    return {
        "report_type": "a2",
        "sections": [main, orphan],
        "data_readiness": [
            _ready("a2", "ok", "kapalı VM tahsisi"),
            _ready("a2_orphan", "unmeasured", orphan["notes"][0]),
        ],
    }


def _a6(db: Session, start: datetime, end: datetime) -> Dict[str, Any]:
    events = _events(db, start, end)
    incidents = (
        db.query(Incident)
        .filter(
            Incident.resolved_at.isnot(None),
            Incident.created_at.isnot(None),
            Incident.resolved_at >= start,
            Incident.resolved_at < end,
        )
        .all()
    )
    by_second: Dict[datetime, List[Incident]] = defaultdict(list)
    for inc in incidents:
        by_second[inc.resolved_at.replace(microsecond=0)].append(inc)
    bulk = [inc for group in by_second.values() if len(group) > 1 for inc in group]
    kept = [inc for group in by_second.values() if len(group) == 1 for inc in group]
    hours = [
        max(0.0, (inc.resolved_at - inc.created_at).total_seconds() / 3600.0)
        for inc in kept
    ]
    numbers = {
        "events": _display_int(len(events)),
        "bulk_closed": _display_int(len(bulk), "yığın"),
    }
    notes = ["Aynı saniyede kapanan yığın p50 ve p95 dışındadır. Ortalama yazılmaz."]
    status = "ok"
    if hours:
        p50 = round(_percentile(hours, 0.50) or 0, 1)
        p95 = round(_percentile(hours, 0.95) or 0, 1)
        for key, val in (("p50_saat", p50), ("p95_saat", p95)):
            text_val = f"{val:.1f}".replace(".", ",")
            numbers[key] = {"value": val, "unit": "saat", "display": [text_val, f"{text_val} saat"]}
    else:
        status = "unmeasured"
        notes.append("Tekil kapanış yok.")
    comps: Dict[str, int] = Counter((ev.event_type or "olay") for ev in events)
    top = sorted(comps.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    labels = {f"component_{i}": name for i, (name, _n) in enumerate(top, start=1)}
    section = _section(
        "a6", "Olay ve operasyon", "exec.ops.duration", status,
        numbers=numbers, labels=labels, notes=notes,
    )
    return {
        "report_type": "a6",
        "sections": [section],
        "data_readiness": [_ready("a6", status, notes[0])],
    }


def _wrap(report_type: str, start: datetime, end: datetime, body: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "report_id": None,
        "report_type": report_type,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": datetime.utcnow().isoformat(),
        "scope": scope,
        "data_readiness": body["data_readiness"],
        "sections": body["sections"],
    }


def build_executive_facts(db: Session, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    scope = {
        "platforms": ["linux", "windows", "virtualization", "openshift"],
        "synthetic_excluded": True,
    }
    bodies = {
        "a1": _a1(db, start, end),
        "b1": _b1(db),
        "b2": _b2(db),
        "a2": _a2(db),
        "a6": _a6(db, start, end),
    }
    return [_wrap(key, start, end, bodies[key], scope) for key in ("a1", "b1", "b2", "a2", "a6")]


def save_monthly_snapshot(db: Session, facts: Dict[str, Any], summary: Optional[str]) -> InfrastructureReport:
    row = InfrastructureReport(
        report_type=_MONTHLY,
        report_title=str(facts.get("report_type") or "executive"),
        data={"locked": True, "facts": facts},
        summary=summary,
        status="locked",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
