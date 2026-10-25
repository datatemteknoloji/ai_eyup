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
        facts = (row.data or {}).get("facts")
        sections: List[Dict[str, Any]] = []
        if isinstance(facts, dict):
            sections = list(facts.get("sections") or [])
        elif isinstance(facts, list):
            for item in facts:
                sections.extend((item or {}).get("sections") or [])
        for section in sections:
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


def _openshift_inventory(db: Session) -> tuple:
    """Gerçek OpenShift küme ve node adedi. Sentetik küme dışarıda."""
    from app.models.openshift import OpenShiftCluster, OpenShiftNode

    hidden = synthetic_cluster_ids(db)
    clusters = [c for c in db.query(OpenShiftCluster).all() if c.id not in hidden]
    nodes = 0
    if clusters:
        nodes = db.query(OpenShiftNode).filter(
            OpenShiftNode.cluster_id.in_([c.id for c in clusters])
        ).count()
    names = ", ".join(c.name for c in clusters)
    return len(clusters), nodes, names


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
    ocp_clusters, ocp_nodes, ocp_names = _openshift_inventory(db)
    ocp = _section(
        "b1_ocp", "OpenShift node tükenme", "exec.capacity.unmeasured", "unmeasured",
        numbers={
            "clusters": _display_int(ocp_clusters, "küme"),
            "nodes": _display_int(ocp_nodes, "node"),
        },
        labels={"clusters": ocp_names or "—", "kind": "OpenShift cluster"},
        notes=[
            "Küme sayısı sentetik kayıtları dışlar. Bu ad OpenShift cluster'ıdır; OLVM/oVirt Manager değildir.",
            "Bu fazda OpenShift node tahmini üretilmez. Günlük kova birikiyor; ham tick örnek sayılmaz.",
        ],
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
    main = _section(
        "a2", "Atıl kaynak", "reclaim.vm.powered_off", "ok",
        numbers=numbers, notes=notes,
    )
    extra = _reclaim_extra(db, syn)
    orphan = extra["orphan"]
    sections = [main, orphan, extra["idle"], extra["oversized"], extra["snapshots"]]
    readiness = [
        _ready("a2", "ok", "kapalı VM tahsisi"),
        _ready("a2_orphan", orphan["status"], orphan["notes"][0]),
        _ready("a2_idle", extra["idle"]["status"], extra["idle"]["notes"][0]),
        _ready("a2_oversized", extra["oversized"]["status"], extra["oversized"]["notes"][0]),
        _ready("a2_snapshots", extra["snapshots"]["status"], extra["snapshots"]["notes"][0]),
    ]
    return {"report_type": "a2", "sections": sections, "data_readiness": readiness}


def _reclaim_extra(db: Session, syn: set) -> Dict[str, Any]:
    """Idle, oversized, snapshot ve yetim disk. Sentetik hypervisor dışarıda. Ağ yok."""
    orphan = _section(
        "a2_orphan", "Yetim disk", "reclaim.summary", "unmeasured",
        notes=["Hazır yetim disk sorgusu yok."],
    )
    idle = _section("a2_idle", "Atıl VM", "reclaim.vm.idle", "unmeasured", notes=["Atıl VM sorgusu çalışmadı."])
    oversized = _section("a2_oversized", "Aşırı boyut", "reclaim.vm.oversized", "unmeasured", notes=["Aşırı boyut sorgusu çalışmadı."])
    snapshots = _section("a2_snapshots", "Snapshot", "reclaim.vm.snapshot_age", "unmeasured", notes=["Snapshot sorgusu çalışmadı."])
    try:
        from app.services.virt_reclaim import build_reclaim
        body = build_reclaim(db)
    except Exception:
        db.rollback()
        return {"orphan": orphan, "idle": idle, "oversized": oversized, "snapshots": snapshots}

    def _keep(rows: Iterable[Dict[str, Any]], key: str = "hypervisor_id") -> List[Dict[str, Any]]:
        return [row for row in rows if row.get(key) not in syn]

    file_count = 0
    try:
        from app.models.infra_finding import VirtDatastoreFile
        fq = db.query(VirtDatastoreFile.id)
        if syn:
            fq = fq.filter(~VirtDatastoreFile.source_id.in_(list(syn)))
        file_count = fq.count()
    except Exception:
        db.rollback()
        file_count = 0
    idle_rows = _keep(body.get("idle") or [])
    over_rows = _keep(body.get("oversized") or [])
    snap_rows = _keep(body.get("snapshots") or [], "source_id")
    orphan_rows = _keep(body.get("orphans") or [])
    if file_count:
        orphan = _section(
            "a2_orphan", "Yetim disk", "reclaim.summary", "ok",
            numbers={"orphans": _display_int(len(orphan_rows), "disk")},
            notes=["Sentetik hypervisor dışarıda. Tarama satırı yoksa bu bölüm ölçülemedi kalır."],
        )
    idle = _section(
        "a2_idle", "Atıl VM", "reclaim.vm.idle", "ok",
        numbers={"idle": _display_int(len(idle_rows), "VM")},
        notes=["Düşük CPU eşiği mevcut geri kazanım kuralıdır. Sentetik hypervisor dışarıda."],
    )
    oversized = _section(
        "a2_oversized", "Aşırı boyut", "reclaim.vm.oversized", "ok",
        numbers={"oversized": _display_int(len(over_rows), "VM")},
        notes=["p95 CPU sağa boyutlandırma mevcut kuraldır. Sentetik hypervisor dışarıda."],
    )
    snapshots = _section(
        "a2_snapshots", "Snapshot", "reclaim.vm.snapshot_age", "ok",
        numbers={"snapshots": _display_int(len(snap_rows), "snapshot")},
        notes=["Yaş eşiğini aşan snapshot bulgusu. Sentetik hypervisor dışarıda."],
    )
    return {"orphan": orphan, "idle": idle, "oversized": oversized, "snapshots": snapshots}


_AUTO_NOTE = "kapanış türü ayırt edilemiyor; süreler otomatik kapanışları içerebilir"


def _close_kind(inc: Incident) -> str:
    """automatic: zaman aşımı. manual/rule: gerçek kapanış. unknown: alan boş."""
    res = (inc.resolution or "").strip()
    src = (inc.source or "").strip().lower()
    if res.lower().startswith("otomatik kapatıldı") or src.startswith("auto_"):
        return "automatic"
    if not src and not res:
        return "unknown"
    if "kural" in src or src.startswith("rule"):
        return "rule"
    return "manual"


def _hour_number(value: float) -> Dict[str, Any]:
    text_val = f"{value:.1f}".replace(".", ",")
    return {"value": value, "unit": "saat", "display": [text_val, f"{text_val} saat"]}


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
    automatic = [inc for inc in incidents if _close_kind(inc) == "automatic"]
    sample = [inc for inc in incidents if _close_kind(inc) != "automatic"]
    unknown = [inc for inc in sample if _close_kind(inc) == "unknown"]
    by_second: Dict[datetime, List[Incident]] = defaultdict(list)
    for inc in sample:
        by_second[inc.resolved_at.replace(microsecond=0)].append(inc)
    bulk = [inc for group in by_second.values() if len(group) > 1 for inc in group]
    kept = [inc for group in by_second.values() if len(group) == 1 for inc in group]
    hours = [
        max(0.0, (inc.resolved_at - inc.created_at).total_seconds() / 3600.0)
        for inc in kept
    ]
    numbers = {
        "events": _display_int(len(events)),
        "auto_closed": _display_int(len(automatic), "otomatik"),
        "bulk_closed": _display_int(len(bulk), "yığın"),
    }
    notes = [
        "Süre yalnız manuel ve kural kapanışlarından hesaplanır. Otomatik zaman aşımı ayrı sayılır. Ortalama yazılmaz.",
        "Aynı saniyede kapanan yığın p50 ve p95 dışındadır.",
    ]
    if unknown:
        notes.append(_AUTO_NOTE)
    status = "ok"
    if hours:
        p50 = round(_percentile(hours, 0.50) or 0, 1)
        p95 = round(_percentile(hours, 0.95) or 0, 1)
        numbers["p50_saat"] = _hour_number(p50)
        numbers["p95_saat"] = _hour_number(p95)
        above = [value for value in hours if value > p95]
        numbers["tail_count"] = _display_int(len(above), "adet")
        if above:
            longest = round(max(above), 1)
            numbers["tail_longest_saat"] = _hour_number(longest)
            notes.append(f"p95 üstü uzun kuyruk: {len(above)} kapanış, en uzun {longest} saat.")
        else:
            notes.append("p95 üstü uzun kuyruk: 0 kapanış.")
    else:
        status = "unmeasured"
        notes.append("Manuel veya kural kapanışı yok. Süre hesaplanmadı.")
        notes.append("p95 yok; uzun kuyruk hesaplanmadı.")
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
        "data_readiness": [_ready("a6", status, notes[-1] if status != "ok" else notes[0])],
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


def _phase2(db: Session) -> Dict[str, Any]:
    """Kalan raporlar. Kaynak yoksa ölçülemedi; sayı uydurulmaz."""
    from app.models.infra_finding import InfraReferenceData
    from app.models.infrastructure_report import BusinessServiceMap
    from app.models.integration_instance import IntegrationInstance

    sections = []
    readiness = []

    def add(sid: str, title: str, note: str) -> None:
        sections.append(_section(sid, title, "exec.capacity.unmeasured", "unmeasured", notes=[note]))
        readiness.append(_ready(sid, "unmeasured", note))

    refs = db.query(InfraReferenceData.id).count()
    add("a3", "Yaşam döngüsü", "Referans paketi yok." if refs == 0 else "Referans paketi takvim üretmez; yaşam döngüsü ölçülemedi.")
    add("a4", "Güvenlik açığı", "Referans paketi ve gerçek BMC yok. Açık uydurulmaz." if refs == 0 else "Gerçek BMC yok. Açık uydurulmaz.")
    veeam = db.query(IntegrationInstance.id).filter(
        IntegrationInstance.kind.like("veeam%"),
        ~IntegrationInstance.kind.like("%demo"),
    ).count()
    add("a5", "Yedek kapsaması", "Gerçek Veeam bağlantısı yok. Demo entegrasyon sayılmaz." if veeam == 0 else "Yedek kapsaması bu üretimde ölçülemedi.")
    services = db.query(BusinessServiceMap.id).count()
    add("b3", "Büyüme ve iş servisi", "İş servisi haritası yok." if services == 0 else "İş servisi haritası var; büyüme serisi bu üretimde ölçülemedi.")
    add("b4", "Lisans", "Lisans parametre tablosu yok. Varsayılan fiyat yazılmaz.")
    try:
        span = db.execute(text(
            "SELECT EXTRACT(EPOCH FROM (max(timestamp) - min(timestamp))) / 86400 FROM hypervisor_host_metrics"
        )).scalar()
        days = int(span or 0)
    except Exception:
        db.rollback()
        days = 0
    add("b5", "Mevsimsellik", f"Seri {days} gün. 13 ay yok. statsmodels eklenmedi.")
    hw = db.query(IntegrationInstance.id).filter(
        IntegrationInstance.kind.like("hw%"),
        ~IntegrationInstance.kind.like("%demo"),
    ).count()
    add("b7", "Donanım", "Gerçek OME/OneView bağlantısı yok. Demo entegrasyon sayılmaz." if hw == 0 else "Donanım bağlantısı var; garanti ve firmware bu üretimde ölçülemedi.")
    add("b8", "Linux kök disk", "Gerekli metrikler yok: " + ", ".join(REQUIRED_FS_METRICS) + ".")
    add("b9", "Platform geçişi", "Geçiş kaydı yok.")
    add("c4", "Tahmin isabeti", "Kilitli tahmin ve gerçekleşme çifti yok.")
    add("a7", "SLA", "Kesinti kaydı yok. Açık kalma süresi SLA diye gösterilmez.")
    return {"report_type": "phase2", "sections": sections, "data_readiness": readiness}


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
        "phase2": _phase2(db),
    }
    return [_wrap(key, start, end, bodies[key], scope) for key in ("a1", "b1", "b2", "a2", "a6", "phase2")]


def save_monthly_snapshot(
    db: Session,
    facts: Any,
    summary: Optional[str],
    period: Optional[Dict[str, Any]] = None,
) -> InfrastructureReport:
    title = "Yönetici raporu"
    if isinstance(facts, dict):
        title = str(facts.get("report_type") or title)
    data: Dict[str, Any] = {"locked": True, "facts": facts}
    if period:
        data["period"] = period
    row = InfrastructureReport(
        report_type=_MONTHLY,
        report_title=title,
        data=data,
        summary=summary,
        status="locked",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
