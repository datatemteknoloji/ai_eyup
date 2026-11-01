"""OpenShift hazır raporlar (ekip raporları) — `/platform-reports/openshift/*`.

Veri yalnız ainew DB'sinden gelir (son tarama `infra_check_runs.stats`, `infra_findings`,
`ocp_resource_metrics`, `ocp_node_daily`, envanter tabloları, `mtv_plan_snapshots`); bu modül kümeye
CANLI çağrı yapmaz. Çıktı `generic_report` şemasındadır. Sayılar deterministiktir (LLM yok).

Veri yoksa/yetersizse bölüm «ölçülemedi» olur — sayı uydurulmaz (tahmin için en az 14 günlük seri).
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.timeutil import utc_now
from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.services import generic_report as gr
from app.services.generic_report import kpi, r1, table, tone_for_pct, unmeasured

logger = logging.getLogger(__name__)

SCOPE = "openshift"
MIN_FORECAST_DAYS = 14
FORECAST_THRESHOLD = 85.0

REPORT_TITLES: Dict[str, str] = {
    "executive_summary": "OpenShift Executive Summary",
    "capacity": "OpenShift Kapasite Raporu",
    "forecast": "OpenShift Kapasite Tahmin",
    "capacity_plan": "OpenShift Kapasite Planı (N+1)",
    "risk": "OpenShift Risk Dashboard",
    "riskiest_assets": "OpenShift En Riskli Varlıklar",
    "namespace_usage": "OpenShift Proje (Namespace) Kullanımı",
    "storage": "OpenShift Depolama (PVC)",
    "workload_health": "OpenShift Workload Sağlığı",
    "vm_health": "OpenShift Sanal Makine (KubeVirt)",
    "compliance_update": "OpenShift Uyum ve Güncelleme",
    "operations": "OpenShift Operasyon Raporu",
    "mtv_migration": "MTV Migrasyon Raporu",
    "mtv_readiness": "MTV Migrasyon Hazırlık Raporu",
}

CATALOG: List[str] = list(REPORT_TITLES.keys())


# ── Ortak veri okuyucular ────────────────────────────────────────────────────

# Yönetici paketi sentetik (ZZ-FAKE) cluster'ları görmemeli; ekip raporları görür (varsayılan).
# Üreticilerin imzası değişmesin diye bağlam değişkeniyle taşınır.
_HIDE_SYNTHETIC: ContextVar[bool] = ContextVar("ocp_report_hide_synthetic", default=False)


@contextmanager
def hide_synthetic_clusters():
    token = _HIDE_SYNTHETIC.set(True)
    try:
        yield
    finally:
        _HIDE_SYNTHETIC.reset(token)


def _clusters(db: Session) -> List[OpenShiftCluster]:
    rows = db.query(OpenShiftCluster).order_by(OpenShiftCluster.name, OpenShiftCluster.id).all()
    if _HIDE_SYNTHETIC.get():
        from app.services.synthetic_scope import cluster_is_synthetic

        rows = [c for c in rows if not cluster_is_synthetic(c)]
    return rows


def _stats(db: Session) -> Dict[int, Dict[str, Any]]:
    from app.services.ocp_insights import latest_stats

    return {s["cluster_id"]: s for s in latest_stats(db)}


def _is_worker(role: Optional[str]) -> bool:
    return "worker" in (role or "").lower()


def _latest_ticks(db: Session, kind: str, minutes: int) -> List[Any]:
    """Her nesne için son örnek (kind: node | pod | vm); `minutes` içinde görünmeyen nesne yok sayılır."""
    return db.execute(text("""
        SELECT DISTINCT ON (cluster_id, object_key)
               cluster_id, object_key, name, namespace, role, status, node_name,
               cpu_used_cores, memory_used_gb, cpu_allocatable, memory_allocatable_gb,
               cpu_pct, memory_pct, restarts, timestamp
        FROM ocp_resource_metrics
        WHERE kind = :kind AND timestamp >= NOW() - make_interval(mins => :mins)
        ORDER BY cluster_id, object_key, timestamp DESC
    """), {"kind": kind, "mins": int(minutes)}).all()


def _findings(db: Session, check_ids: Optional[List[str]] = None, *, result: Optional[str] = "fail") -> List[Any]:
    from app.models.infra_finding import InfraFinding

    q = db.query(InfraFinding).filter(InfraFinding.platform == "ocp", InfraFinding.active.is_(True))
    if result:
        q = q.filter(InfraFinding.result == result)
    if check_ids:
        q = q.filter(InfraFinding.check_id.in_(check_ids))
    return q.all()


def _cap(stats: Dict[int, Dict[str, Any]], cid: int) -> Dict[str, Any]:
    return ((stats.get(cid) or {}).get("stats") or {}).get("capacity") or {}


def _as_of(stats: Dict[int, Dict[str, Any]], cid: int) -> Optional[str]:
    return (stats.get(cid) or {}).get("as_of")


def _daily_node_series(db: Session, days: int = 90) -> Dict[Tuple[int, str], List[Tuple[Any, Optional[float], Optional[float]]]]:
    """(cluster_id, object_key) → [(gün, avg_cpu_pct, avg_memory_pct)] eskiden yeniye (günlük özet)."""
    rows = db.execute(text("""
        SELECT cluster_id, object_key, bucket, avg_cpu_pct, avg_memory_pct
        FROM ocp_node_daily
        WHERE bucket >= NOW() - make_interval(days => :d)
        ORDER BY cluster_id, object_key, bucket
    """), {"d": int(days)}).all()
    out: Dict[Tuple[int, str], List[Tuple[Any, Optional[float], Optional[float]]]] = defaultdict(list)
    for r in rows:
        out[(int(r.cluster_id), r.object_key)].append((r.bucket, r.avg_cpu_pct, r.avg_memory_pct))
    return out


def _cluster_daily(db: Session, cluster: OpenShiftCluster, nodes: List[OpenShiftNode]) -> Dict[str, List[float]]:
    """Cluster'ın worker node'larının günlük ortalaması (yoksa tüm node'lar)."""
    series = _daily_node_series(db)
    pick = [n.name for n in nodes if _is_worker(n.role)] or [n.name for n in nodes]
    by_day: Dict[Any, Dict[str, List[float]]] = defaultdict(lambda: {"cpu": [], "mem": []})
    for name in pick:
        for day, cpu, mem in series.get((cluster.id, name), []):
            if cpu is not None:
                by_day[day]["cpu"].append(float(cpu))
            if mem is not None:
                by_day[day]["mem"].append(float(mem))
    days = sorted(by_day)
    return {
        "days": len(days),
        "cpu": [sum(by_day[d]["cpu"]) / len(by_day[d]["cpu"]) for d in days if by_day[d]["cpu"]],
        "mem": [sum(by_day[d]["mem"]) / len(by_day[d]["mem"]) for d in days if by_day[d]["mem"]],
    }


# ── 1) Executive Summary ─────────────────────────────────────────────────────

def generate_executive_summary(db: Session) -> Dict[str, Any]:
    from app.services.openshift_health import build_health_board

    board = build_health_board(db)
    tot = board["totals"]
    fails = _findings(db)
    by_sev = Counter((f.severity or "medium").lower() for f in fails)
    rows = []
    for c in board["clusters"]:
        rows.append([
            c["name"], c["version"] or "—", c["health"], f"{c['nodes_ready']}/{c['node_count']}",
            c["project_count"], c["pod_count"], c["risk_pod_count"],
            c["avg_cpu_request_pct"], c["avg_memory_request_pct"],
        ])
    vm_ticks = _latest_ticks(db, "vm", 30)
    vm_running = sum(1 for v in vm_ticks if (v.status or "").lower() == "running")
    recs: List[str] = []
    if tot["nodes_not_ready"]:
        recs.append(f"{tot['nodes_not_ready']} node hazır değil — kubelet ve node durumunu inceleyin.")
    if tot["risk_pods"]:
        recs.append(f"{tot['risk_pods']} riskli pod var (CrashLoop/ImagePull/çok restart) — Workload Sağlığı raporuna bakın.")
    if by_sev.get("critical"):
        recs.append(f"{by_sev['critical']} kritik bulgu açık — Risk Dashboard'da ayrıntı var.")
    if not recs:
        recs.append("Kritik bir aksiyon gerekmiyor; kapasite ve güncelleme raporlarını düzenli gözden geçirin.")
    health_tone = {"healthy": "ok", "warning": "warn", "critical": "crit"}.get(board["overall"], "muted")
    return gr.make_report(
        SCOPE, "executive_summary", REPORT_TITLES["executive_summary"],
        kpis=[
            kpi("Genel durum", {"healthy": "Sağlıklı", "warning": "Uyarı", "critical": "Kritik", "empty": "Cluster yok"}.get(board["overall"], board["overall"]), tone=health_tone),
            kpi("Cluster", tot["clusters"]),
            kpi("Node", tot["nodes"], f"{tot['nodes_not_ready']} hazır değil", "crit" if tot["nodes_not_ready"] else "ok"),
            kpi("Proje", tot["projects"]),
            kpi("Pod", tot["pods"], f"{tot['risk_pods']} riskli", "warn" if tot["risk_pods"] else "ok"),
            kpi("KubeVirt VM", len(vm_ticks), f"{vm_running} çalışıyor"),
            kpi("Açık bulgu", len(fails), f"{by_sev.get('critical', 0)} kritik", "crit" if by_sev.get("critical") else ("warn" if fails else "ok")),
        ],
        sections=[table(
            "Cluster özeti",
            ["Cluster", "Sürüm", "Durum", "Node hazır", "Proje", "Pod", "Riskli pod", "Ort. CPU request %", "Ort. Memory request %"],
            rows,
        )] if rows else [unmeasured("Cluster özeti", "Kayıtlı OpenShift cluster yok.")],
        recommendations=recs,
        notes=["Request yüzdesi kullanım değildir; gerçek tüketim Kapasite raporundadır."],
    )


# ── 2) Kapasite ──────────────────────────────────────────────────────────────

def generate_capacity(db: Session) -> Dict[str, Any]:
    stats = _stats(db)
    ticks = _latest_ticks(db, "node", 30)
    live = {(int(t.cluster_id), t.object_key): t for t in ticks}
    sections: List[Dict[str, Any]] = []
    cluster_rows: List[List[Any]] = []
    hot_nodes = 0
    recs: List[str] = []
    for c in _clusters(db):
        cap = _cap(stats, c.id)
        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).all()
        wk = [n for n in nodes if _is_worker(n.role)] or nodes
        usage_cpu = [live[(c.id, n.name)].cpu_pct for n in wk if (c.id, n.name) in live and live[(c.id, n.name)].cpu_pct is not None]
        usage_mem = [live[(c.id, n.name)].memory_pct for n in wk if (c.id, n.name) in live and live[(c.id, n.name)].memory_pct is not None]
        avg_cpu = r1(sum(usage_cpu) / len(usage_cpu)) if usage_cpu else None
        avg_mem = r1(sum(usage_mem) / len(usage_mem)) if usage_mem else None
        alloc, req, rp = cap.get("allocatable") or {}, cap.get("requested") or {}, cap.get("request_pct") or {}
        n1 = (cap.get("n_plus_one") or {}).get("status")
        cluster_rows.append([
            c.name, f"{cap.get('workers_usable', '—')}/{cap.get('workers_total', '—')}",
            alloc.get("cpu_cores"), req.get("cpu_cores"), rp.get("cpu"), avg_cpu,
            alloc.get("memory_gb"), req.get("memory_gb"), rp.get("memory"), avg_mem, n1 or "veri yok",
        ])
        node_rows = []
        wmap = {w["name"]: w for w in (cap.get("workers") or [])}
        for n in sorted(nodes, key=lambda x: x.name):
            t = live.get((c.id, n.name))
            w = wmap.get(n.name) or {}
            cpu_u = r1(t.cpu_pct) if t else None
            mem_u = r1(t.memory_pct) if t else None
            if (mem_u or 0) >= 85 or (cpu_u or 0) >= 85:
                hot_nodes += 1
            node_rows.append([n.name, n.role, n.status, n.pod_count, w.get("cpu_pct"), cpu_u, w.get("mem_pct"), mem_u])
        sections.append(table(
            f"Node kullanımı — {c.name}",
            ["Node", "Rol", "Durum", "Pod", "CPU request %", "CPU kullanım %", "Memory request %", "Memory kullanım %"],
            node_rows,
            note=(f"Son tarama: {_as_of(stats, c.id)}" if _as_of(stats, c.id) else "Bu cluster için tamamlanmış tarama yok; request değerleri ölçülemedi."),
        ))
        if not cap:
            recs.append(f"{c.name}: tarama özeti yok — request/allocatable hesaplanamadı (Ayarlar › OpenShift taramasını çalıştırın).")
        if rp.get("memory") and rp["memory"] > 85:
            recs.append(f"{c.name}: Memory request %{rp['memory']} — worker eklemeyi veya iş yükü dengelemeyi planlayın.")
    sections.insert(0, table(
        "Cluster kapasitesi",
        ["Cluster", "Worker (kullanılabilir/toplam)", "CPU allocatable (çekirdek)", "CPU request", "CPU request %", "CPU kullanım % (ort.)",
         "Memory allocatable (GB)", "Memory request (GB)", "Memory request %", "Memory kullanım % (ort.)", "N+1"],
        cluster_rows,
    ) if cluster_rows else unmeasured("Cluster kapasitesi", "Kayıtlı OpenShift cluster yok."))
    return gr.make_report(
        SCOPE, "capacity", REPORT_TITLES["capacity"],
        kpis=[kpi("Cluster", len(cluster_rows)), kpi("Yüksek kullanımlı node (≥%85)", hot_nodes, tone="crit" if hot_nodes else "ok")],
        sections=sections, recommendations=recs,
        methodology="Request % = pod request toplamı / worker allocatable (son tarama). Kullanım % = metrics.k8s.io son örnek / allocatable (ainew DB).",
        notes=["Request kullanım değildir; ikisi ayrı sütundadır."],
    )


# ── 3) Kapasite Tahmin ───────────────────────────────────────────────────────

def _project(current: Optional[float], daily: float, days: int) -> Optional[float]:
    if current is None:
        return None
    return round(max(0.0, min(100.0, current + daily * days)), 1)


def generate_forecast(db: Session) -> Dict[str, Any]:
    from app.services import report_analytics as ra

    ticks = _latest_ticks(db, "node", 30)
    live = {(int(t.cluster_id), t.object_key): t for t in ticks}
    rows: List[List[Any]] = []
    sections: List[Dict[str, Any]] = []
    soon = 0
    for c in _clusters(db):
        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).all()
        daily = _cluster_daily(db, c, nodes)
        wk = [n for n in nodes if _is_worker(n.role)] or nodes
        for label, key, attr in (("Memory", "mem", "memory_pct"), ("CPU", "cpu", "cpu_pct")):
            cur_vals = [getattr(live[(c.id, n.name)], attr) for n in wk
                        if (c.id, n.name) in live and getattr(live[(c.id, n.name)], attr) is not None]
            current = (sum(cur_vals) / len(cur_vals)) if cur_vals else (daily[key][-1] if daily[key] else None)
            if len(daily[key]) < MIN_FORECAST_DAYS:
                rows.append([c.name, label, r1(current), f"{len(daily[key])}/{MIN_FORECAST_DAYS} gün", "ölçülemedi", None, None, None, None])
                continue
            fc = ra.build_threshold_forecast(current, daily[key], threshold=FORECAST_THRESHOLD, min_samples=MIN_FORECAST_DAYS)
            conf = fc["trend_confidence"]
            slope = fc["daily_growth_pct"]
            usable = conf in ("medium", "high")
            rng = fc.get("days_to_threshold_range") or {}
            if usable and fc.get("days_to_threshold") is not None and fc["days_to_threshold"] <= 365:
                soon += 1
            rng_txt = None
            if rng:
                rng_txt = f"{rng.get('fastest')}–{rng.get('slowest') if rng.get('slowest') is not None else '∞'} gün" if rng.get("typical") else "eşik aşıldı"
            rows.append([
                c.name, label, r1(current), f"{len(daily[key])} gün", conf,
                f"{slope:+.3f}", rng_txt if usable else None,
                _project(current, slope, 90) if usable else None,
                _project(current, slope, 365) if usable else None,
            ])
    if rows:
        sections.append(table(
            f"Eşiğe kalan süre (eşik %{int(FORECAST_THRESHOLD)})",
            ["Cluster", "Kaynak", "Şimdi %", "Seri uzunluğu", "Trend güveni", "Günlük eğim (%/gün)",
             "Eşiğe kalan (aralık)", "3 ay sonra %", "12 ay sonra %"],
            rows,
            note="Düşük güven veya 14 günden kısa seride tahmin yazılmaz. Aralık hızlı–yavaş senaryodur; tek kesin tarih değildir.",
        ))
    else:
        sections.append(unmeasured("Eşiğe kalan süre", "Kayıtlı OpenShift cluster yok."))
    return gr.make_report(
        SCOPE, "forecast", REPORT_TITLES["forecast"],
        kpis=[kpi("Cluster", len({r[0] for r in rows})),
              kpi("12 ay içinde eşiğe varan", soon, tone="warn" if soon else "ok")],
        sections=sections,
        methodology=(f"Worker node'ların günlük ortalama (ocp_node_daily, ≤400 gün) serisine Theil–Sen eğimi; en az {MIN_FORECAST_DAYS} gün. "
                     "Aralık eğimin %25–%75 bandından. Yalnız orta/yüksek güvenli trend projeksiyon üretir."),
        notes=["Geçmişteki eğimin sürdüğünü varsayar; mevsimsellik ve planlı iş yükü değişimi modellenmez."],
    )


# ── 4) Kapasite Planı (N+1) ──────────────────────────────────────────────────

def _workers_needed(workers: List[Dict[str, Any]]) -> Optional[int]:
    usable = [w for w in workers if w.get("ready") and w.get("schedulable")]
    if len(usable) < 2:
        return None
    from app.services.capacity.engine import worker_n_plus_one

    req_cpu = sum(w.get("req_cpu_m", 0.0) for w in workers)
    req_mem = sum(w.get("req_mem_gb", 0.0) for w in workers)
    avg = {"cpu_m": sum(w["cpu_m"] for w in usable) / len(usable), "mem_gb": sum(w["mem_gb"] for w in usable) / len(usable),
           "ready": True, "schedulable": True}
    for extra in range(0, 51):
        res = worker_n_plus_one(usable + [dict(avg)] * extra, req_cpu, req_mem)
        if res["status"] == "ok":
            return extra
    return None


def generate_capacity_plan(db: Session) -> Dict[str, Any]:
    stats = _stats(db)
    rows: List[List[Any]] = []
    failing = 0
    needed_total = 0
    for c in _clusters(db):
        cap = _cap(stats, c.id)
        n1 = cap.get("n_plus_one") or {}
        status = n1.get("status")
        if status == "fail":
            failing += 1
        need = _workers_needed(cap.get("workers") or []) if status in ("fail", "warn") else 0
        if need:
            needed_total += need
        label = {"ok": "Yeterli", "warn": "Sınırda", "fail": "Yetersiz", "single_worker": "Tek worker (N+1 yok)",
                 "no_data": "Veri yok"}.get(status or "", "Veri yok")
        rows.append([
            c.name, cap.get("workers_usable"), n1.get("largest_worker"), n1.get("memory_after_pct"), n1.get("cpu_after_pct"),
            label, need if status in ("fail", "warn") else ("—" if status in (None, "no_data", "single_worker") else 0),
        ])
    recs = []
    if failing:
        recs.append(f"{failing} cluster'da en büyük worker düşerse request'ler kalan worker'lara sığmıyor — worker ekleyin ya da request'leri azaltın.")
    return gr.make_report(
        SCOPE, "capacity_plan", REPORT_TITLES["capacity_plan"],
        kpis=[kpi("Cluster", len(rows)), kpi("N+1 yetersiz", failing, tone="crit" if failing else "ok"),
              kpi("Gereken ek worker (toplam)", needed_total, tone="warn" if needed_total else "ok")],
        sections=[table(
            "N+1 değerlendirmesi",
            ["Cluster", "Kullanılabilir worker", "En büyük worker", "Memory request % (N+1)", "CPU request % (N+1)", "Sonuç", "Gereken ek worker"],
            rows,
            note="Ek worker sayısı mevcut worker'ların ortalama boyutuna göre hesaplanır; scheduler kuralları (taint, affinity) modellenmez.",
        )] if rows else [unmeasured("N+1 değerlendirmesi", "Kayıtlı OpenShift cluster yok.")],
        recommendations=recs,
        methodology="En büyük worker düşünce request toplamı / kalan allocatable. Memory veya CPU > %100 yetersiz, > %90 sınırda (kapasite motoru ile aynı karar).",
    )


# ── 5) Risk Dashboard ────────────────────────────────────────────────────────

def generate_risk(db: Session) -> Dict[str, Any]:
    from app.services.openshift_health import build_health_board, list_risk_workloads

    board = build_health_board(db)
    fails = _findings(db)
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    fails.sort(key=lambda f: (sev_rank.get((f.severity or "medium").lower(), 4), f.check_id, f.entity_name or ""))
    by_check = Counter(f.check_id for f in fails)
    risk_pods = list_risk_workloads(db, limit=15)
    nodes_down = [(c["name"], n) for c in board["clusters"] for n in c["nodes_not_ready"]]
    kp = [
        kpi("Açık bulgu", len(fails), tone="crit" if any((f.severity or "") == "critical" for f in fails) else ("warn" if fails else "ok")),
        kpi("Hazır olmayan node", len(nodes_down), tone="crit" if nodes_down else "ok"),
        kpi("Riskli pod", board["totals"]["risk_pods"], tone="warn" if board["totals"]["risk_pods"] else "ok"),
        kpi("Degraded operator", by_check.get("ocp.operator.health", 0), tone="crit" if by_check.get("ocp.operator.health") else "ok"),
    ]
    secs = [
        table("Bulgu türüne göre", ["Kontrol", "Adet"], sorted(by_check.items(), key=lambda kv: -kv[1])) if by_check
        else table("Bulgu türüne göre", ["Kontrol", "Adet"], [], note="Açık bulgu yok."),
        table("Öncelikli bulgular", ["Önem", "Cluster", "Varlık", "Kontrol", "Ayrıntı"],
              [[f.severity, f.cluster_name or f.source_name, f.entity_name, f.check_id, (f.detail or "")[:140]] for f in fails[:25]]),
        table("Riskli pod'lar", ["Cluster", "Proje", "Pod", "Durum", "Restart", "Node"],
              [[next((c["name"] for c in board["clusters"] if c["id"] == w.cluster_id), w.cluster_id), w.project, w.name, w.status, w.restart_count, w.node_name]
               for w in risk_pods]),
    ]
    return gr.make_report(
        SCOPE, "risk", REPORT_TITLES["risk"], kpis=kp, sections=secs,
        recommendations=([f"{len(nodes_down)} node hazır değil: " + ", ".join(f"{c}/{n}" for c, n in nodes_down[:5])] if nodes_down else []),
        methodology="Kural tabanlı bulgular (ocp.* kontrolleri, son tarama) + pod durumu/restart eşikleri. Skor üretilmez; sayılar ve sıralama kuraldır.",
    )


# ── 6) En Riskli Varlıklar ───────────────────────────────────────────────────

def generate_riskiest_assets(db: Session) -> Dict[str, Any]:
    from app.services.ocp_capacity_sim import node_risk
    from app.services.openshift_health import list_risk_workloads

    nr = node_risk(db, days=30)
    nodes = nr.get("nodes") or []
    pods = list_risk_workloads(db, limit=20)
    names = {c.id: c.name for c in _clusters(db)}
    return gr.make_report(
        SCOPE, "riskiest_assets", REPORT_TITLES["riskiest_assets"],
        kpis=[kpi("Riskli node", len(nodes), tone="warn" if nodes else "ok"), kpi("Riskli pod", len(pods), tone="warn" if pods else "ok")],
        sections=[
            table("En riskli node'lar (son 30 gün olayları)",
                  ["Cluster", "Node", "Skor", "Seviye", "Şu an sağlıksız", "Son olay", "Olay sayıları"],
                  [[n["cluster"], n["node"], n["score"], n["level"], n["unhealthy_now"], n["last_event"],
                    ", ".join(f"{k}:{v}" for k, v in list((n.get("counts") or {}).items())[:4])] for n in nodes[:15]],
                  note=nr.get("note")),
            table("En riskli pod'lar",
                  ["Cluster", "Proje", "Pod", "Durum", "Restart", "Node"],
                  [[names.get(w.cluster_id, w.cluster_id), w.project, w.name, w.status, w.restart_count, w.node_name] for w in pods]),
        ],
        methodology="Node skoru = Σ(olay ağırlığı × sayı) + (şu an sağlıksızsa 5). Yalnız gözlenen olaylar; arıza zamanı tahmini yapılmaz.",
    )


# ── 7) Proje (Namespace) Kullanımı ───────────────────────────────────────────

def generate_namespace_usage(db: Session) -> Dict[str, Any]:
    pods = _latest_ticks(db, "pod", 30)
    agg: Dict[Tuple[int, str], Dict[str, float]] = defaultdict(lambda: {"pods": 0, "cpu": 0.0, "mem": 0.0})
    for p in pods:
        a = agg[(int(p.cluster_id), p.namespace or "—")]
        a["pods"] += 1
        a["cpu"] += float(p.cpu_used_cores or 0)
        a["mem"] += float(p.memory_used_gb or 0)
    names = {c.id: c.name for c in _clusters(db)}
    top = sorted(agg.items(), key=lambda kv: -kv[1]["mem"])[:15]
    quota = [f for f in _findings(db, ["ocp.namespace.quota"], result=None)]
    quota.sort(key=lambda f: -float((f.evidence or {}).get("pct") or 0))
    over = _findings(db, ["ocp.pod.over_request"])
    projects = db.query(OpenShiftProject).all()
    user_projects = [p for p in projects if not (p.meta_data or {}).get("is_system")]
    return gr.make_report(
        SCOPE, "namespace_usage", REPORT_TITLES["namespace_usage"],
        kpis=[kpi("Proje (kullanıcı)", len(user_projects)),
              kpi("Quota ≥ %90", sum(1 for f in quota if f.result == "fail"), tone="warn" if any(f.result == "fail" for f in quota) else "ok"),
              kpi("Over-request proje", len(over), tone="warn" if over else "ok")],
        sections=[
            table("En çok Memory kullanan projeler (anlık)", ["Cluster", "Proje", "Pod", "CPU (çekirdek)", "Memory (GB)"],
                  [[names.get(cid, cid), ns, int(v["pods"]), round(v["cpu"], 2), round(v["mem"], 2)] for (cid, ns), v in top],
                  note=None if pods else "Son 30 dakikada pod metriği yok."),
            table("Quota doluluk", ["Cluster", "Quota", "Kaynak", "Doluluk %", "Durum"],
                  [[f.cluster_name, f.entity_name, (f.evidence or {}).get("key"), (f.evidence or {}).get("pct"), "Eşik üstü" if f.result == "fail" else "Normal"] for f in quota[:20]]),
            table("Request'i kullanımdan çok yüksek projeler", ["Cluster", "Proje", "CPU request", "CPU kullanım", "Memory request (GB)", "Memory kullanım (GB)"],
                  [[f.cluster_name, f.entity_name, (f.evidence or {}).get("req_cpu_cores"), (f.evidence or {}).get("use_cpu_cores"),
                    (f.evidence or {}).get("req_mem_gb"), (f.evidence or {}).get("use_mem_gb")] for f in over[:20]],
                  note="Anlık metrics-server örneğine göre; kullanım request'in %20'sinin altındaysa listelenir."),
        ],
        methodology="Kullanım: metrics.k8s.io son örnek (ainew DB). Quota/over-request: son tarama bulguları.",
    )


# ── 8) Depolama (PVC) ────────────────────────────────────────────────────────

def generate_storage(db: Session) -> Dict[str, Any]:
    stats = _stats(db)
    unbound: List[List[Any]] = []
    unused: List[List[Any]] = []
    unused_gb = 0.0
    scanned = 0
    for c in _clusters(db):
        rec = ((stats.get(c.id) or {}).get("stats") or {}).get("reclaim") or {}
        if rec:
            scanned += 1
        for x in rec.get("unbound") or []:
            unbound.append([c.name, x.get("pvc"), x.get("phase"), x.get("size_gb"), x.get("storage_class")])
        for x in rec.get("unused") or []:
            unused.append([c.name, x.get("pvc"), x.get("size_gb"), x.get("storage_class"), x.get("created")])
            unused_gb += float(x.get("size_gb") or 0)
    unused.sort(key=lambda r: -(r[2] or 0))
    return gr.make_report(
        SCOPE, "storage", REPORT_TITLES["storage"],
        kpis=[kpi("Taranan cluster", scanned), kpi("Bağlanmamış PVC", len(unbound), tone="crit" if unbound else "ok"),
              kpi("Kullanılmayan PVC", len(unused), f"{round(unused_gb, 1)} GB", "warn" if unused else "ok")],
        sections=[
            table("Bağlanmamış PVC (Pending / Lost)", ["Cluster", "PVC", "Durum", "Boyut (GB)", "StorageClass"], unbound[:30]),
            table("Hiçbir pod'un kullanmadığı PVC", ["Cluster", "PVC", "Boyut (GB)", "StorageClass", "Oluşturulma"], unused[:30],
                  note="KubeVirt disk PVC'leri (DataVolume/VirtualMachine sahipli) bu listede değildir."),
        ] if scanned else [unmeasured("PVC durumu", "Tamamlanmış tarama yok; PVC verisi ölçülemedi.")],
        recommendations=([f"{round(unused_gb, 1)} GB kullanılmayan PVC kapasitesi geri kazanılabilir (silmeden önce sahibiyle doğrulayın)."] if unused_gb else []),
        methodology="Son tarama: Pending/Lost PVC bağlanmamış; hiçbir pod'un volume'ünde geçmeyen PVC kullanılmayan sayılır. Depolama toplam kapasitesi (StorageClass backend) ölçülmez.",
    )


# ── 9) Workload Sağlığı ──────────────────────────────────────────────────────

def generate_workload_health(db: Session) -> Dict[str, Any]:
    from app.services.openshift_health import build_health_board, list_risk_workloads

    board = build_health_board(db)
    names = {c["id"]: c["name"] for c in board["clusters"]}
    risk = list_risk_workloads(db, limit=30)
    status_cnt: Counter = Counter()
    restarts = 0
    for w in db.query(OpenShiftWorkload).filter(OpenShiftWorkload.kind == "pod").all():
        status_cnt[w.status or "unknown"] += 1
        restarts += int(w.restart_count or 0)
    return gr.make_report(
        SCOPE, "workload_health", REPORT_TITLES["workload_health"],
        kpis=[kpi("Pod", board["totals"]["pods"]), kpi("Riskli pod", board["totals"]["risk_pods"], tone="warn" if board["totals"]["risk_pods"] else "ok"),
              kpi("Deployment", board["totals"]["deployments"]), kpi("Route", board["totals"]["routes"]), kpi("Toplam restart", restarts)],
        sections=[
            table("Cluster bazında", ["Cluster", "Durum", "Pod", "Riskli pod", "Deployment", "Route"],
                  [[c["name"], c["health"], c["pod_count"], c["risk_pod_count"], c["deployment_count"], c["route_count"]] for c in board["clusters"]]),
            table("Pod durum dağılımı", ["Durum", "Adet"], status_cnt.most_common()),
            table("Riskli pod'lar", ["Cluster", "Proje", "Pod", "Durum", "Restart", "Node"],
                  [[names.get(w.cluster_id, w.cluster_id), w.project, w.name, w.status, w.restart_count, w.node_name] for w in risk]),
        ],
        methodology="Riskli pod: CrashLoopBackOff/ImagePull/OOMKilled/Error/Failed/Unknown/Pending durumu veya ≥5 restart (OpenShift Sağlık sayfasıyla aynı kural).",
    )


# ── 10) Sanal Makine (KubeVirt) ──────────────────────────────────────────────

def generate_vm_health(db: Session) -> Dict[str, Any]:
    ticks = _latest_ticks(db, "vm", 30)
    names = {c.id: c.name for c in _clusters(db)}
    status_cnt = Counter((t.status or "unknown") for t in ticks)
    avg = {}
    if ticks:
        rows = db.execute(text("""
            SELECT cluster_id, object_key, avg(cpu_pct) AS cpu, avg(memory_pct) AS mem, count(*) AS n
            FROM ocp_resource_metrics
            WHERE kind = 'vm' AND timestamp >= NOW() - INTERVAL '3 days'
            GROUP BY cluster_id, object_key
        """)).all()
        avg = {(int(r.cluster_id), r.object_key): r for r in rows}
    hot, idle = [], []
    for t in ticks:
        a = avg.get((int(t.cluster_id), t.object_key))
        running = (t.status or "").lower() == "running"
        if running and ((t.cpu_pct or 0) >= 90 or (t.memory_pct or 0) >= 90):
            hot.append(t)
        if running and a is not None and a.n >= 50 and (a.cpu or 0) < 5 and (a.mem or 0) < 20:
            idle.append((t, a))
    running_n = sum(1 for t in ticks if (t.status or "").lower() == "running")
    return gr.make_report(
        SCOPE, "vm_health", REPORT_TITLES["vm_health"],
        kpis=[kpi("KubeVirt VM", len(ticks)), kpi("Çalışan", running_n),
              kpi("Yüksek kullanım (≥%90)", len(hot), tone="warn" if hot else "ok"),
              kpi("Atıl aday (3 gün)", len(idle), tone="info")],
        sections=[
            table("Durum dağılımı", ["Durum", "VM"], status_cnt.most_common()),
            table("Yüksek kullanımlı VM'ler", ["Cluster", "Proje", "VM", "CPU %", "Memory %", "Node"],
                  [[names.get(int(t.cluster_id)), t.namespace, t.name, r1(t.cpu_pct), r1(t.memory_pct), t.node_name]
                   for t in sorted(hot, key=lambda x: -(x.memory_pct or 0))[:15]]),
            table("Atıl VM adayları", ["Cluster", "Proje", "VM", "3g ort. CPU %", "3g ort. Memory %", "Memory (GB)"],
                  [[names.get(int(t.cluster_id)), t.namespace, t.name, r1(a.cpu), r1(a.mem), r1(t.memory_allocatable_gb)]
                   for t, a in sorted(idle, key=lambda x: -(x[0].memory_allocatable_gb or 0))[:15]],
                  note="Çalışan VM'in 3 günlük ortalaması CPU < %5 ve Memory < %20 ise aday sayılır; karar sahibine aittir."),
        ] if ticks else [unmeasured("KubeVirt VM'ler", "Son 30 dakikada VM metriği yok (OpenShift Virtualization kurulu değil veya monitoring senkronu çalışmıyor).")],
        methodology="VM CPU/Memory % = metrics.k8s.io son örnek / tahsis; atıl adayı 3 günlük ortalamadan (en az 50 örnek).",
    )


# ── 11) Uyum ve Güncelleme ───────────────────────────────────────────────────

def generate_compliance_update(db: Session) -> Dict[str, Any]:
    stats = _stats(db)
    ups = {f.source_id: f for f in _findings(db, ["ocp.cluster.update_available"], result=None)}
    deg_ops = Counter(f.source_id for f in _findings(db, ["ocp.operator.health"]))
    mcp_deg = Counter(f.source_id for f in _findings(db, ["ocp.mcp.degraded"]))
    rows, comp_rows, total_fail = [], [], 0
    for c in _clusters(db):
        st = (stats.get(c.id) or {}).get("stats") or {}
        up = ups.get(c.id)
        ev = (up.evidence or {}) if up else {}
        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).all()
        kubelets = sorted({n.kubelet_version for n in nodes if n.kubelet_version})
        rows.append([
            c.name, st.get("version") or c.version or "—",
            ("Güncelleme var" if up and up.result == "fail" else ("Güncel" if up else "Bilinmiyor")),
            ", ".join(ev.get("available") or [])[:60] or "—",
            deg_ops.get(c.id, 0), mcp_deg.get(c.id, 0), len(kubelets) or "—",
        ])
        comp = st.get("compliance") or {}
        total_fail += int(comp.get("fail") or 0)
        comp_rows.append([c.name, "Kurulu" if comp.get("installed") else "Kurulu değil / veri yok", comp.get("pass"), comp.get("fail"), comp.get("manual")])
    return gr.make_report(
        SCOPE, "compliance_update", REPORT_TITLES["compliance_update"],
        kpis=[kpi("Güncelleme bekleyen cluster", sum(1 for u in ups.values() if u.result == "fail"), tone="warn" if any(u.result == "fail" for u in ups.values()) else "ok"),
              kpi("Degraded operator", sum(deg_ops.values()), tone="crit" if deg_ops else "ok"),
              kpi("Degraded MCP", sum(mcp_deg.values()), tone="crit" if mcp_deg else "ok"),
              kpi("Başarısız uyum kuralı", total_fail, tone="warn" if total_fail else "ok")],
        sections=[
            table("Sürüm ve sağlık", ["Cluster", "Sürüm", "Güncelleme", "Mevcut güncellemeler", "Degraded operator", "Degraded MCP", "Kubelet sürümü (farklı)"], rows),
            table("Compliance Operator sonuçları", ["Cluster", "Durum", "Geçen", "Başarısız", "Manuel/N/A"], comp_rows,
                  note="Sertifikasyon iddiası değildir; denetim için teknik kanıttır."),
        ],
        methodology="Son tarama (clusterversion, clusteroperator, MachineConfigPool, ComplianceCheckResult).",
    )


# ── 12) Operasyon ────────────────────────────────────────────────────────────

def generate_operations(db: Session) -> Dict[str, Any]:
    from app.models.event import Incident, SystemEvent
    from app.services.platform_scope import apply_platform_filter, incident_platform_clause

    since = utc_now() - timedelta(days=30)
    base = apply_platform_filter(db.query(SystemEvent).filter(SystemEvent.created_at >= since), "openshift", db)
    events = base.order_by(SystemEvent.created_at.desc()).limit(20000).all()
    sev = Counter((e.severity or "info") for e in events)
    types = Counter((e.event_type or "—", e.severity or "info") for e in events)
    daily: Counter = Counter(e.created_at.date().isoformat() for e in events if e.created_at)
    clause = incident_platform_clause("openshift", db)
    open_inc = db.query(Incident).filter(Incident.status.in_(("open", "investigating")))
    if clause is not None:
        open_inc = open_inc.filter(clause)
    inc = open_inc.order_by(Incident.created_at.desc()).limit(10).all()
    return gr.make_report(
        SCOPE, "operations", REPORT_TITLES["operations"],
        kpis=[kpi("Olay (30 gün)", len(events)), kpi("Kritik", sev.get("critical", 0) + sev.get("emergency", 0), tone="crit" if sev.get("critical") else "ok"),
              kpi("Uyarı", sev.get("warning", 0), tone="warn" if sev.get("warning") else "ok"), kpi("Açık incident", len(inc))],
        sections=[
            table("Olay türleri", ["Tür", "Önem", "Adet"], [[t, s, n] for (t, s), n in types.most_common(15)]),
            table("Günlük olay trendi", ["Gün", "Olay"], sorted(daily.items())[-14:]),
            table("Açık incident'lar", ["#", "Önem", "Başlık", "Durum", "Oluşturulma"],
                  [[i.id, i.severity, i.title, i.status, i.created_at.isoformat()[:16] if i.created_at else None] for i in inc]),
        ],
        methodology="Son 30 günün OpenShift olayları (en çok 20.000 kayıt örneklenir).",
    )


# ── 13) MTV Migrasyon ────────────────────────────────────────────────────────

_STATE_TR = {"succeeded": "Başarılı", "failed": "BAŞARISIZ", "running": "Çalışıyor", "ready": "Hazır",
             "validating": "Doğrulanıyor", "archived": "Arşivlendi"}


def generate_mtv_migration(db: Session) -> Dict[str, Any]:
    from app.models.mtv import MtvPlanSnapshot

    rows = db.query(MtvPlanSnapshot).order_by(MtvPlanSnapshot.last_seen.desc()).all()
    if not rows:
        return gr.make_report(
            SCOPE, "mtv_migration", REPORT_TITLES["mtv_migration"],
            sections=[unmeasured("Taşıma planları",
                                 "Kayıtlı MTV planı yok: MTV kurulu değil, plan oluşturulmamış veya ilk anlık görüntü henüz alınmadı "
                                 "(OpenShift senkronu her 10 dakikada toplar).")],
            notes=["Geçmiş yalnız ainew'un topladığı anlık görüntülerden gelir; MTV öncesi taşımalar görünmez."],
        )
    st_cnt = Counter(r.state for r in rows)
    vm_total = sum(r.vm_total or 0 for r in rows)
    vm_ok = sum(r.vm_succeeded or 0 for r in rows)
    vm_bad = sum(r.vm_failed or 0 for r in rows)
    durations = [(r.completed_at - r.started_at).total_seconds() / 60.0 for r in rows
                 if r.state == "succeeded" and r.started_at and r.completed_at and r.completed_at > r.started_at]
    avg_min = round(sum(durations) / len(durations), 1) if durations else None
    cutoff = utc_now() - timedelta(days=30)
    recent = [r for r in rows if r.completed_at and r.completed_at >= cutoff and r.state == "succeeded"]
    fail_vm_rows: List[List[Any]] = []
    for r in rows:
        for v in (r.vms or []):
            if v.get("result") == "failed":
                fail_vm_rows.append([r.cluster_name, r.plan_name, v.get("name"), v.get("phase"), (v.get("error") or r.error or "")[:160]])
    weekly: Counter = Counter()
    for r in rows:
        if r.completed_at and r.state == "succeeded":
            iso = r.completed_at.isocalendar()
            weekly[f"{iso[0]}-H{iso[1]:02d}"] += int(r.vm_succeeded or 0)
    return gr.make_report(
        SCOPE, "mtv_migration", REPORT_TITLES["mtv_migration"],
        kpis=[kpi("Plan", len(rows)), kpi("Taşınan VM (başarılı)", vm_ok, f"/{vm_total}", "ok" if vm_ok else "info"),
              kpi("Başarısız VM", vm_bad, tone="crit" if vm_bad else "ok"),
              kpi("Çalışan plan", st_cnt.get("running", 0)), kpi("Ort. plan süresi (dk)", avg_min if avg_min is not None else "—"),
              kpi("Son 30 gün tamamlanan", len(recent))],
        sections=[
            table("Plan durumları", ["Cluster", "Plan", "Kaynak", "Durum", "VM", "Başarılı", "Başarısız", "Çalışıyor", "Başlangıç", "Bitiş", "Soğuk/Sıcak", "Kümede"],
                  [[r.cluster_name, r.plan_name, r.source_provider, _STATE_TR.get(r.state, r.state), r.vm_total, r.vm_succeeded, r.vm_failed, r.vm_running,
                    r.started_at.isoformat()[:16] if r.started_at else None, r.completed_at.isoformat()[:16] if r.completed_at else None,
                    "Sıcak" if r.warm else "Soğuk", "Evet" if r.removed_at is None else "Silindi"] for r in rows[:40]]),
            table("Başarısız VM'ler ve nedenleri", ["Cluster", "Plan", "VM", "Aşama", "Neden"], fail_vm_rows[:40]),
            table("Haftalık taşınan VM", ["Hafta", "VM"], sorted(weekly.items())[-12:]),
        ],
        recommendations=([f"{vm_bad} VM başarısız — hata nedenlerini inceleyip planı yeniden çalıştırın."] if vm_bad else []),
        methodology="MTV Plan/Migration CR'lerinin periyodik anlık görüntüsü (mtv_plan_snapshots). Süre = plan başlangıç → bitiş; yalnız başarılı planlar ortalamaya girer.",
        notes=["Kümeden silinen planlar 'Silindi' olarak kalır; geçmiş ainew'un ilk anlık görüntüsünden başlar."],
    )


# ── 14) MTV Migrasyon Hazırlık ───────────────────────────────────────────────

def generate_mtv_readiness(db: Session) -> Dict[str, Any]:
    """VMware VM'leri OpenShift hedef kapasitesine sığar mı (N+1 sonrası boşluk)."""
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.mtv import MtvPlanSnapshot
    from app.models.server import Server
    from app.services.capacity.engine import vm_demand
    from app.services.chat_quality import power_state as ps
    from app.services.synthetic_scope import synthetic_hypervisor_ids, synthetic_server_ids

    hidden_hv = synthetic_hypervisor_ids(db)
    vmw = [h for h in db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE).all() if h.id not in hidden_hv]
    hv_name = {h.id: h.name for h in vmw}
    hidden_srv = synthetic_server_ids(db)
    vms = []
    if hv_name:
        vms = [v for v in db.query(Server).filter(Server.hypervisor_id.in_(list(hv_name))).all()
               if v.id not in hidden_srv and ps.is_on(v.vm_power_state)]
    planned: set = set()
    migrated: set = set()
    for r in db.query(MtvPlanSnapshot).all():
        for v in (r.vms or []):
            n = (v.get("name") or "").lower()
            if not n:
                continue
            planned.add(n)
            if v.get("result") == "succeeded":
                migrated.add(n)
    cand = [v for v in vms if (v.vm_name or v.name or "").lower() not in migrated]
    dem_mem = dem_cpu = disk = 0.0
    big: List[Tuple[float, Any]] = []
    for v in cand:
        d = vm_demand(1, int(v.vm_cpu_count or 1), float(v.vm_memory_mb or 0) / 1024.0)
        dem_mem += d["memory_gb"]
        dem_cpu += d["cpu_cores"]
        disk += float(v.vm_disk_gb or 0)
        big.append((d["memory_gb"], v))
    big.sort(key=lambda x: -x[0])

    stats = _stats(db)
    tgt_rows: List[List[Any]] = []
    fits_all = 0
    measured = 0
    for c in _clusters(db):
        cap = _cap(stats, c.id)
        usable = [w for w in (cap.get("workers") or []) if w.get("ready") and w.get("schedulable")]
        if len(usable) < 2:
            tgt_rows.append([c.name, len(usable), None, None, None, None, "ölçülemedi (≥2 kullanılabilir worker ve tarama gerekir)"])
            continue
        measured += 1
        big_w = max(usable, key=lambda w: w["mem_gb"])
        free_mem = sum(w["mem_gb"] for w in usable) - big_w["mem_gb"] - sum(w.get("req_mem_gb", 0.0) for w in (cap.get("workers") or []))
        free_cpu = (sum(w["cpu_m"] for w in usable) - big_w["cpu_m"]) / 1000.0 - sum(w.get("req_cpu_m", 0.0) for w in (cap.get("workers") or [])) / 1000.0
        ok = free_mem >= dem_mem and free_cpu >= dem_cpu
        fits_all += 1 if ok else 0
        tgt_rows.append([c.name, len(usable), round(max(free_mem, 0), 1), round(max(free_cpu, 0), 1),
                         round(dem_mem, 1), round(dem_cpu, 1), "Sığar (N+1 sonrası)" if ok else "Sığmaz"])
    kp = [kpi("Aday VMware VM (açık)", len(cand), f"{len(vms) - len(cand)} zaten taşındı" if len(vms) != len(cand) else None),
          kpi("Toplam Memory talebi (GB)", round(dem_mem, 1)), kpi("Toplam CPU request (çekirdek)", round(dem_cpu, 1)),
          kpi("Toplam disk (GB)", round(disk, 1)), kpi("Hedefe sığan cluster", f"{fits_all}/{measured}", tone="ok" if measured and fits_all else "warn")]
    return gr.make_report(
        SCOPE, "mtv_readiness", REPORT_TITLES["mtv_readiness"],
        kpis=kp,
        sections=[
            table("Hedef cluster boşluğu (N+1 sonrası)",
                  ["Cluster", "Kullanılabilir worker", "Boş Memory (GB)", "Boş CPU (çekirdek)", "Talep Memory (GB)", "Talep CPU (çekirdek)", "Sonuç"],
                  tgt_rows, note="Boş kapasite = en büyük worker düşünce kalan allocatable − mevcut request toplamı. Depolama kapasitesi hedefte ölçülmez."),
            table("En büyük taşıma adayları", ["Kaynak vCenter", "VM", "vCPU", "Memory (GB)", "Disk (GB)", "Planda mı", "OpenShift Memory talebi (GB)"],
                  [[hv_name.get(v.hypervisor_id), v.vm_name or v.name, v.vm_cpu_count, round(float(v.vm_memory_mb or 0) / 1024.0, 1), v.vm_disk_gb,
                    (v.vm_name or v.name or "").lower() in planned, round(m, 1)] for m, v in big[:15]]),
        ] if vms else [unmeasured("Taşıma adayları", "Çalışan VMware VM bulunamadı (veya yalnız sentetik/taşınmış VM var).")],
        methodology=("Talep: VM belleği + virt-launcher yükü (0,002×bellek + 218 MiB + 8 MiB×vCPU); CPU request = vCPU ÷ 10 (varsayılan allocation ratio). "
                     "Hedef boşluk: ocp.cluster.n_plus_one ile aynı en-büyük-worker varsayımı."),
        notes=["Zamanlayıcı kuralları, depolama sınıfı ve ağ eşlemesi modellenmez; hazırlık göstergesidir, taşıma garantisi değildir."],
    )


# ── Kayıt ────────────────────────────────────────────────────────────────────

GENERATORS: Dict[str, Callable[[Session], Dict[str, Any]]] = {
    "executive_summary": generate_executive_summary,
    "capacity": generate_capacity,
    "forecast": generate_forecast,
    "capacity_plan": generate_capacity_plan,
    "risk": generate_risk,
    "riskiest_assets": generate_riskiest_assets,
    "namespace_usage": generate_namespace_usage,
    "storage": generate_storage,
    "workload_health": generate_workload_health,
    "vm_health": generate_vm_health,
    "compliance_update": generate_compliance_update,
    "operations": generate_operations,
    "mtv_migration": generate_mtv_migration,
    "mtv_readiness": generate_mtv_readiness,
}


def generate(db: Session, report_type: str, save: bool = True) -> Dict[str, Any]:
    fn = GENERATORS.get(report_type)
    if fn is None:
        raise ValueError(f"OpenShift için bilinmeyen rapor: {report_type}")
    data = fn(db)
    if save:
        from app.models.infrastructure_report import InfrastructureReport

        obj = InfrastructureReport(
            report_type=f"openshift:{report_type}",
            report_title=f"[OPENSHIFT] {REPORT_TITLES[report_type]}",
            data=data, status="ready",
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        data["_report_id"] = obj.id
    return data


def get_latest(db: Session, report_type: str) -> Optional[Dict[str, Any]]:
    from app.models.infrastructure_report import InfrastructureReport

    row = (db.query(InfrastructureReport).filter(InfrastructureReport.report_type == f"openshift:{report_type}")
           .order_by(InfrastructureReport.generated_at.desc()).first())
    if not row:
        return None
    return {**row.data, "_report_id": row.id, "_generated_at": row.generated_at.isoformat() if row.generated_at else None}


def to_markdown(report_type: str, data: Dict[str, Any], lang: str = "tr") -> str:
    return gr.to_markdown(data, scope=SCOPE, report_type=report_type, lang=lang)
