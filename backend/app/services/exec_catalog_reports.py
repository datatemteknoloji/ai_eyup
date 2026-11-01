"""Yönetici hazır raporları — «Tüm Ortamlar» — `/executive-reports/*`.

Her rapor beş alanı (Sanallaştırma, OpenShift, Linux, Windows, Exadata) kapsar; ama bir alan raporda
YALNIZ anlamlıysa yer alır. Hangi alanın hangi raporda hangi sağlayıcıyla (veya neden dışarıda)
olduğu `MATRIX` tablosunda bildirimsel olarak durur — kapsam dışı satırı «neden» ile birlikte
rapora yazılır, sessizce atlanmaz.

Kurallar
- Sentetik (ZZ-FAKE) hypervisor / cluster / sunucu yönetici paketine GİRMEZ (`synthetic_scope`).
- Veri yoksa/yetersizse bölüm «ölçülemedi» olur; sayı uydurulmaz. Tahmin en az 14 günlük seri ister.
- Sağlık skoru `exec_health.score_area` (yönetici paketi formülü); ekip raporu skoruyla karıştırılmaz.
- Çıktı `generic_report` şemasındadır. LLM yok; sayılar deterministiktir.
- Mevcut ekip raporlarının çıktısı değişmez; burada yalnız okunur/yeniden kullanılır.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import and_, func as sa_func, or_, text
from sqlalchemy.orm import Session

from app.core.timeutil import utc_now
from app.models.event import SystemEvent
from app.models.server import Server
from app.services import generic_report as gr
from app.services.generic_report import kpi, r1, table, tone_for_pct, unmeasured

logger = logging.getLogger(__name__)

SCOPE = "executive"
MIN_FORECAST_DAYS = 14
FORECAST_THRESHOLD = 85.0

MODULE_LABELS: Dict[str, str] = {
    "virt": "Sanallaştırma",
    "openshift": "OpenShift",
    "linux": "Linux",
    "windows": "Windows",
    "exadata": "Exadata",
}
ORDER: List[str] = list(MODULE_LABELS)

REPORT_TITLES: Dict[str, str] = {
    "executive_summary": "Tüm Ortamlar — Yönetici Özeti",
    "capacity": "Tüm Ortamlar — Kapasite",
    "forecast": "Tüm Ortamlar — Kapasite Tahmin",
    "risk": "Tüm Ortamlar — Risk",
    "riskiest_assets": "Tüm Ortamlar — En Riskli Varlıklar",
    "operations": "Tüm Ortamlar — Operasyon",
    "sla": "Tüm Ortamlar — SLA / Erişilebilirlik",
    "patch_compliance": "Tüm Ortamlar — Yama ve Uyum",
    "reclaim": "Tüm Ortamlar — Geri Kazanım",
    "monitoring_coverage": "Tüm Ortamlar — İzleme Kapsamı",
    "migration": "Sanallaştırma → OpenShift Migrasyon (MTV)",
}
CATALOG: List[str] = list(REPORT_TITLES)

_X = "excluded"

# rapor → alan → sağlayıcı adı | ("excluded", neden). Sağlayıcı adı `_PROVIDERS` içindeki işlevdir.
MATRIX: Dict[str, Dict[str, Any]] = {
    "executive_summary": {m: "summary" for m in ORDER},
    "capacity": {
        "virt": "capacity_virt", "openshift": "capacity_ocp", "linux": "capacity_linux",
        "windows": (_X, "Windows için kullanım/kapasite metriği henüz rapora bağlı değil; yalnız envanter sayılır."),
        "exadata": "capacity_exadata",
    },
    "forecast": {
        "virt": "forecast_virt", "openshift": "forecast_ocp", "linux": "forecast_linux",
        "windows": (_X, "Windows sunucuları için günlük kullanım serisi toplanmıyor; tahmin üretilemez."),
        "exadata": (_X, "Exadata kullanım serisi (CPU/Memory/depolama doluluğu) toplanmıyor; yalnız envanter var. Tahmin anlamsız olur."),
    },
    "risk": {m: "risk" for m in ORDER},
    "riskiest_assets": {m: "riskiest" for m in ORDER},
    "operations": {m: "operations" for m in ORDER},
    "sla": {m: "sla" for m in ORDER},
    "patch_compliance": {
        "virt": "patch_virt", "openshift": "patch_ocp", "linux": "patch_linux", "windows": "patch_windows",
        "exadata": (_X, "Exadata yama/firmware durumu (patchmgr/imageinfo) toplanmıyor; Exadata ekibinin Oracle takvimiyle yönetilir."),
    },
    "reclaim": {
        "virt": "reclaim_virt", "openshift": "reclaim_ocp",
        "linux": (_X, "Geri kazanım sanal katmanda ölçülür (kapalı/atıl VM); Linux sunucuları ayrıca değerlendirilmez."),
        "windows": (_X, "Geri kazanım sanal katmanda ölçülür (kapalı/atıl VM); Windows sunucuları ayrıca değerlendirilmez."),
        "exadata": (_X, "Exadata ayrılmış donanımdır; geri kazanım (kapalı/atıl VM) kavramı geçerli değil."),
    },
    "monitoring_coverage": {m: "monitoring" for m in ORDER},
    "migration": {
        "virt": "migration_virt", "openshift": "migration_ocp",
        "linux": (_X, "MTV yalnız VMware → OpenShift Virtualization taşır; fiziksel/ayrı Linux sunucular kapsam dışı."),
        "windows": (_X, "MTV yalnız VMware → OpenShift Virtualization taşır; Windows sunucuları ayrıca planlanmaz."),
        "exadata": (_X, "Exadata taşınmaz; MTV kapsamı dışındadır."),
    },
}


# ── Bağlam: sentetik dışlama + ortak okuyucular ──────────────────────────────

class Ctx:
    """Tek rapor üretimi boyunca ortak, sentetiksiz görünüm."""

    def __init__(self, db: Session):
        from app.services.synthetic_scope import (
            synthetic_cluster_ids, synthetic_hypervisor_ids, synthetic_server_ids,
        )

        self.db = db
        self.hidden_hv = set(synthetic_hypervisor_ids(db))
        self.hidden_cl = set(synthetic_cluster_ids(db))
        self.hidden_srv = set(synthetic_server_ids(db, self.hidden_hv))
        self._cache: Dict[str, Any] = {}

    def _memo(self, key: str, fn: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    # envanter
    def hypervisors(self) -> Dict[int, Any]:
        def load():
            from app.models.hypervisor import Hypervisor, HypervisorType

            rows = self.db.query(Hypervisor).all()
            return {h.id: h for h in rows
                    if h.id not in self.hidden_hv and h.hypervisor_type != HypervisorType.OPENSHIFT_VIRT}
        return self._memo("hv", load)

    def clusters(self) -> List[Any]:
        def load():
            from app.models.openshift import OpenShiftCluster

            return [c for c in self.db.query(OpenShiftCluster).order_by(OpenShiftCluster.name).all()
                    if c.id not in self.hidden_cl]
        return self._memo("cl", load)

    def servers(self, platform: str) -> List[Server]:
        def load():
            from app.services.platform_scope import server_ids_for_platform

            ids = set(server_ids_for_platform(self.db, platform)) - self.hidden_srv
            if not ids:
                return []
            rows = self.db.query(Server).filter(Server.id.in_(list(ids))).all()
            if platform == "virt":
                hv = self.hypervisors()
                rows = [s for s in rows if s.hypervisor_id is None or s.hypervisor_id in hv]
            return rows
        return self._memo(f"srv:{platform}", load)

    def exadata_nodes(self) -> List[Any]:
        def load():
            from app.models.exadata import ExadataNode, ExadataRack

            racks = {r.id: r for r in self.db.query(ExadataRack).all()}
            nodes = self.db.query(ExadataNode).all()
            return [(n, racks.get(n.rack_id)) for n in nodes if n.server_id not in self.hidden_srv]
        return self._memo("exa_nodes", load)

    def host_count(self) -> int:
        def load():
            ids = list(self.hypervisors())
            if not ids:
                return 0
            return int(self.db.execute(text(
                "SELECT count(DISTINCT (hypervisor_id, host_name)) FROM hypervisor_host_metrics "
                "WHERE timestamp >= NOW() - INTERVAL '2 days' AND hypervisor_id = ANY(:ids)"), {"ids": ids}).scalar() or 0)
        return self._memo("hosts", load)

    def ocp_nodes(self) -> int:
        def load():
            from app.models.openshift import OpenShiftNode

            ids = [c.id for c in self.clusters()]
            if not ids:
                return 0
            return int(self.db.query(sa_func.count(OpenShiftNode.id)).filter(OpenShiftNode.cluster_id.in_(ids)).scalar() or 0)
        return self._memo("ocp_nodes", load)

    # olaylar
    def event_q(self, platform: str):
        from app.services.platform_scope import apply_platform_filter

        q = apply_platform_filter(self.db.query(SystemEvent), platform, self.db)
        if self.hidden_srv:
            q = q.filter(or_(SystemEvent.server_id.is_(None), SystemEvent.server_id.notin_(list(self.hidden_srv))))
        # Eski/yan kayıtlarda hypervisor_id boş kalabilir; kalıcı anahtar `res-<id>-…` / `host-<id>-…` biçimindedir.
        if platform == "virt" and self.hidden_hv:
            ek = sa_func.json_extract_path_text(SystemEvent.raw_data, "external_key")
            pats = [f"{p}-{i}-%" for i in self.hidden_hv for p in ("res", "host")]
            q = q.filter(or_(ek.is_(None), and_(*[~ek.like(x) for x in pats])))
        # JSON ayrıştırması pahalı (milyonluk tablo): yalnız ilgili alanda uygula.
        rel = {"virt": (("hypervisor_id", self.hidden_hv),), "openshift": (("cluster_id", self.hidden_cl),)}.get(platform, ())
        for key, ids in rel:
            if ids:
                col = sa_func.json_extract_path_text(SystemEvent.raw_data, key)
                q = q.filter(or_(col.is_(None), col.notin_([str(i) for i in ids])))
        return q

    def inventory_total(self, platform: str) -> int:
        """Skor paydası: izlenen varlık sayısı (0 → «İzleme yok»)."""
        if platform == "virt":
            return self.host_count() + len(self.servers("virt"))
        if platform == "openshift":
            return self.ocp_nodes()
        if platform == "exadata":
            return len(self.exadata_nodes())
        return len(self.servers(platform))

    def inventory_text(self, platform: str) -> str:
        if platform == "virt":
            return f"{len(self.hypervisors())} kaynak, {self.host_count()} host, {len(self.servers('virt'))} VM"
        if platform == "openshift":
            return f"{len(self.clusters())} cluster, {self.ocp_nodes()} node"
        if platform == "exadata":
            racks = {r.id for _n, r in self.exadata_nodes() if r}
            return f"{len(racks)} rack, {len(self.exadata_nodes())} node"
        return f"{len(self.servers(platform))} sunucu"

    def area(self, platform: str) -> Dict[str, Any]:
        """Açık (24 sa) olaylardan varlık bazlı kritik/uyarı + yönetici skoru."""
        return self._memo(f"area:{platform}", lambda: _build_area(self, platform))


def _ekey(server_id: Optional[int], raw: Dict[str, Any], title: str) -> str:
    if server_id:
        return f"s{server_id}"
    if raw.get("cluster_id") is not None:
        return f"c{raw['cluster_id']}:{raw.get('source_object') or raw.get('node') or title[:60]}"
    if raw.get("host_name") or raw.get("hypervisor_id") is not None:
        return f"h:{raw.get('host_name') or raw.get('host') or raw.get('source_object') or title[:60]}"
    return f"t:{title[:60]}"


def _build_area(ctx: Ctx, platform: str) -> Dict[str, Any]:
    from app.services.exec_health import asset_score, score_area

    since = utc_now() - timedelta(hours=24)
    rows = (ctx.event_q(platform)
            .filter(SystemEvent.last_seen >= since, SystemEvent.resolved.is_(False))
            .with_entities(SystemEvent.server_id, SystemEvent.severity, SystemEvent.title, SystemEvent.raw_data)
            .limit(50000).all())
    ents: Dict[str, Dict[str, Any]] = {}
    for sid, sev, title, raw in rows:
        raw = raw if isinstance(raw, dict) else {}
        e = ents.setdefault(_ekey(sid, raw, title or ""), {
            "server_id": sid, "name": raw.get("source_object") or raw.get("host_name") or raw.get("host") or raw.get("node") or (title or "")[:80],
            "crit": 0, "warn": 0})
        if sev in ("critical", "emergency"):
            e["crit"] += 1
        elif sev in ("warning", "error"):
            e["warn"] += 1
    ents = {k: v for k, v in ents.items() if v["crit"] or v["warn"]}
    sids = [e["server_id"] for e in ents.values() if e["server_id"]]
    if sids:
        names = dict(ctx.db.query(Server.id, Server.name).filter(Server.id.in_(sids)).all())
        for e in ents.values():
            if e["server_id"] in names:
                e["name"] = names[e["server_id"]]
    total = ctx.inventory_total(platform)
    assets = [(e["crit"], e["warn"]) for e in ents.values()]
    assets += [(0, 0)] * max(0, total - len(assets))
    monitored = total > 0
    sc = score_area(assets, monitored=monitored)
    for e in ents.values():
        e["score"] = asset_score(e["crit"], e["warn"])
    ranked = sorted(ents.values(), key=lambda e: (e["score"], -e["crit"], -e["warn"]))
    return {
        "platform": platform, "total": total, "monitored": monitored, "entities": ranked,
        "critical_events": sum(e["crit"] for e in ents.values()),
        "warning_events": sum(e["warn"] for e in ents.values()),
        "critical_assets": sum(1 for e in ents.values() if e["crit"]), **sc,
    }


def _tag(sections: List[Dict[str, Any]], module: str) -> List[Dict[str, Any]]:
    for s in sections:
        s["module"] = MODULE_LABELS[module]
    return sections


def _status_tone(status: Optional[str]) -> str:
    return {"Normal": "ok", "Dikkat": "warn", "Kritik": "crit"}.get(status or "", "muted")


# ── Sağlayıcılar: (ctx, platform) → bölümler / yorumlar ──────────────────────

Prov = Dict[str, Any]   # {"sections": [...], "recs": [...], "kpis": {...}}


def _p_summary(ctx: Ctx, m: str) -> Prov:
    a = ctx.area(m)
    return {"row": [MODULE_LABELS[m], ctx.inventory_text(m), a["asset_count"] if a["monitored"] else None,
                    a["critical_assets"], a["critical_events"], a["warning_events"], a["score"], a["status"]], "area": a}


def _p_risk(ctx: Ctx, m: str) -> Prov:
    a = ctx.area(m)
    if not a["monitored"]:
        return {"sections": [unmeasured("Risk", "Bu alanda envanter yok / izleme yok; risk ölçülemedi.", module=MODULE_LABELS[m])]}
    rows = [[e["name"], e["crit"], e["warn"], e["score"]] for e in a["entities"][:8]]
    sec = table(
        "Açık olaylar ve en riskli varlıklar", ["Varlık", "Kritik", "Uyarı", "Varlık skoru"], rows,
        module=MODULE_LABELS[m],
        kpis=[kpi("Skor", a["score"], a["status"], _status_tone(a["status"])),
              kpi("Kritik olay (24 sa)", a["critical_events"], tone="crit" if a["critical_events"] else "ok"),
              kpi("Uyarı olayı (24 sa)", a["warning_events"], tone="warn" if a["warning_events"] else "ok")],
        note=None if rows else "Son 24 saatte açık kritik/uyarı olay yok.",
    )
    out = [sec]
    fr = _finding_counts(ctx, m)
    if fr is not None:
        out.append(table("Açık kontrol bulguları (kapasite, sağlık, uyum, yükseltme…)", ["Önem", "Adet"], fr,
                         module=MODULE_LABELS[m],
                         note="Kontrol sonuçlarının son taraması; olaylardan ayrıdır."))
    return {"sections": out}


def _finding_counts(ctx: Ctx, m: str) -> Optional[List[List[Any]]]:
    from app.models.infra_finding import InfraFinding

    if m == "virt":
        plats, hidden = ("vmware", "olvm"), ctx.hidden_hv
    elif m == "openshift":
        plats, hidden = ("ocp",), ctx.hidden_cl
    else:
        return None
    q = ctx.db.query(InfraFinding.severity, sa_func.count()).filter(
        InfraFinding.platform.in_(plats), InfraFinding.active.is_(True), InfraFinding.result == "fail")
    if hidden:
        q = q.filter(or_(InfraFinding.source_id.is_(None), InfraFinding.source_id.notin_(list(hidden))))
    cnt = dict(q.group_by(InfraFinding.severity).all())
    if not cnt:
        return []
    order = ["critical", "high", "medium", "low", "info"]
    tr = {"critical": "Kritik", "high": "Yüksek", "medium": "Orta", "low": "Düşük", "info": "Bilgi"}
    return [[tr.get(k, k), cnt[k]] for k in order if k in cnt] + [[k, v] for k, v in cnt.items() if k not in order]


def _p_riskiest(ctx: Ctx, m: str) -> Prov:
    a = ctx.area(m)
    return {"area": a, "items": [[e["name"], MODULE_LABELS[m], e["crit"], e["warn"], e["score"]] for e in a["entities"][:20]]}


def _p_operations(ctx: Ctx, m: str) -> Prov:
    since = utc_now() - timedelta(days=30)
    # Tek geçişte grupla: olay tablosu milyonlarca satır olabilir; alan başına tek sorgu.
    grp = (ctx.event_q(m).filter(SystemEvent.created_at >= since)
           .with_entities(SystemEvent.severity, SystemEvent.event_type, SystemEvent.is_acknowledged, sa_func.count())
           .group_by(SystemEvent.severity, SystemEvent.event_type, SystemEvent.is_acknowledged).all())
    sev: Counter = Counter()
    types: Counter = Counter()
    ack = 0
    for s_, t_, a_, n_ in grp:
        sev[s_] += n_
        types[t_] += n_
        if a_:
            ack += n_
    total = sum(sev.values())
    a = ctx.area(m)
    return {
        "row": [MODULE_LABELS[m], total, sev.get("critical", 0) + sev.get("emergency", 0), sev.get("warning", 0) + sev.get("error", 0),
                sev.get("info", 0), a["critical_events"] + a["warning_events"], r1(gr.pct(ack, total)) if total else None],
        "top": [[MODULE_LABELS[m], t or "—", n] for t, n in types.most_common(5)],
    }


def _p_sla(ctx: Ctx, m: str) -> Prov:
    from app.services.platform_report_engine import _sla_items

    if m == "openshift":
        return _sla_ocp(ctx)
    if m == "exadata":
        ids = {n.server_id for n, _r in ctx.exadata_nodes() if n.server_id}
        servers = [s for s in ctx.db.query(Server).filter(Server.id.in_(list(ids))).all()] if ids else []
        if not servers:
            return {"sections": [unmeasured("SLA", "Exadata düğümleri sunucu kaydına bağlı değil; olay tabanlı SLA tahmini yapılamadı.",
                                             module=MODULE_LABELS[m])]}
    else:
        servers = ctx.servers(m)
    if not servers:
        return {"sections": [unmeasured("SLA", "Bu alanda sunucu/VM yok.", module=MODULE_LABELS[m])]}
    d = _sla_items(ctx.db, servers)
    return {
        "row": [MODULE_LABELS[m], len(servers), d["servers_meeting_sla"], d["servers_missing_sla"], d["overall_sla_compliance_pct"]],
        "worst": [[MODULE_LABELS[m], i["server"], i["critical_events_30d"], i["estimated_uptime_pct"]] for i in d["sla_items"][:5]
                  if not i["sla_met"]],
    }


def _sla_ocp(ctx: Ctx) -> Prov:
    ids = [c.id for c in ctx.clusters()]
    if not ids:
        return {"sections": [unmeasured("SLA", "Kayıtlı (gerçek) OpenShift cluster yok.", module="OpenShift")]}
    rows = ctx.db.execute(text("""
        SELECT cluster_id, object_key,
               count(*) AS n,
               count(*) FILTER (WHERE lower(coalesce(status,'')) IN ('ready','true')) AS ok
        FROM ocp_resource_metrics
        WHERE kind = 'node' AND timestamp >= NOW() - INTERVAL '30 days' AND cluster_id = ANY(:ids)
        GROUP BY 1, 2
    """), {"ids": ids}).all()
    if not rows:
        return {"sections": [unmeasured("SLA", "Node durum örneği yok; Ready oranı ölçülemedi.", module="OpenShift")]}
    ratios = [(r.object_key, 100.0 * r.ok / r.n) for r in rows if r.n]
    met = sum(1 for _k, v in ratios if v >= 99.0)
    return {
        "row": ["OpenShift", len(ratios), met, len(ratios) - met, r1(100.0 * met / len(ratios))],
        "worst": [["OpenShift", k, None, r1(v)] for k, v in sorted(ratios, key=lambda x: x[1])[:5] if v < 99.0],
        "ocp_note": "OpenShift için kullanılabilirlik = 30 gün içinde node'un Ready görüldüğü örnek oranı (olay tahmini değil).",
    }


def _p_monitoring(ctx: Ctx, m: str) -> Prov:
    mod = MODULE_LABELS[m]
    if m in ("linux", "windows"):
        servers = ctx.servers(m)
        if not servers:
            return {"sections": [unmeasured("İzleme kapsamı", "Bu alanda sunucu yok.", module=mod)]}
        inst, run = ("node_exporter_installed", "node_exporter_running") if m == "linux" else \
                    ("windows_exporter_installed", "windows_exporter_running")
        n = len(servers)
        ex_run = sum(1 for s in servers if getattr(s, run, False))
        ex_inst = sum(1 for s in servers if getattr(s, inst, False))
        ai = sum(1 for s in servers if s.ai_ready)
        gaps = [[s.name, s.status or "—", bool(getattr(s, inst, False)), bool(getattr(s, run, False))]
                for s in servers if not getattr(s, run, False)][:8]
        return {"row": [mod, n, ex_inst, ex_run, r1(gr.pct(ex_run, n)), "Exporter"],
                "gaps": [[mod, *g] for g in gaps]}
    if m == "virt":
        hvs = list(ctx.hypervisors())
        if not hvs:
            return {"sections": [unmeasured("İzleme kapsamı", "Kayıtlı sanallaştırma kaynağı yok.", module=mod)]}
        fresh = {int(r[0]) for r in ctx.db.execute(text(
            "SELECT DISTINCT hypervisor_id FROM hypervisor_host_metrics WHERE timestamp >= NOW() - INTERVAL '1 hour' "
            "AND hypervisor_id = ANY(:ids)"), {"ids": hvs}).all()}
        return {"row": [mod, len(hvs), len(hvs), len(fresh), r1(gr.pct(len(fresh), len(hvs))), "Host metriği (son 1 sa)"],
                "gaps": [[mod, ctx.hypervisors()[i].name, ctx.hypervisors()[i].status or "—", None, False] for i in hvs if i not in fresh][:8]}
    if m == "openshift":
        cl = ctx.clusters()
        if not cl:
            return {"sections": [unmeasured("İzleme kapsamı", "Kayıtlı (gerçek) OpenShift cluster yok.", module=mod)]}
        fresh = {int(r[0]) for r in ctx.db.execute(text(
            "SELECT DISTINCT cluster_id FROM ocp_resource_metrics WHERE kind='node' AND timestamp >= NOW() - INTERVAL '30 minutes' "
            "AND cluster_id = ANY(:ids)"), {"ids": [c.id for c in cl]}).all()}
        return {"row": [mod, len(cl), len(cl), len(fresh), r1(gr.pct(len(fresh), len(cl))), "Node metriği (son 30 dk)"],
                "gaps": [[mod, c.name, c.status or "—", None, False] for c in cl if c.id not in fresh][:8]}
    nodes = ctx.exadata_nodes()
    if not nodes:
        return {"sections": [unmeasured("İzleme kapsamı", "Exadata düğümü yok.", module=mod)]}
    linked = [n for n, _r in nodes if n.server_id]
    return {"row": [mod, len(nodes), len(linked), len(linked), r1(gr.pct(len(linked), len(nodes))), "Sunucu kaydı bağı"],
            "gaps": [[mod, n.name, n.status or "—", None, False] for n, _r in nodes if not n.server_id][:8]}


# ── Kapasite ─────────────────────────────────────────────────────────────────

def _capacity_virt(ctx: Ctx) -> Prov:
    from app.services.virt_capacity_planner import build_capacity

    body = build_capacity(ctx.db, with_forecast=False)
    hv = ctx.hypervisors()
    cl = [c for c in body.get("clusters") or [] if c.get("hypervisor_id") in hv]
    ds = [d for d in body.get("datastores") or [] if d.get("hypervisor_id") in hv]
    if not cl:
        return {"sections": [unmeasured("Küme kapasitesi", "Sanallaştırma kümesi / host metriği yok.", module="Sanallaştırma")]}
    rows, hot, recs = [], 0, []
    for c in cl:
        mem, cpu = c.get("memory") or {}, c.get("cpu") or {}
        oc = (mem.get("overcommit") or {})
        n1 = (c.get("n_plus_one") or {}).get("status")
        mu, cu = mem.get("effective_used_pct"), cpu.get("effective_used_pct")
        if (mu or 0) >= 85 or (cu or 0) >= 80:
            hot += 1
            recs.append(f"{c.get('hypervisor')} / {c.get('cluster')}: kullanım yüksek (Memory %{mu}, CPU %{cu}) — kapasite artırımı veya VM dengelemesi planlayın.")
        rows.append([c.get("hypervisor"), c.get("cluster"), f"{c.get('hosts_usable')}/{c.get('hosts_total')}", mu, cu,
                     oc.get("committed_pct"), (cpu.get("vcpu_ratio")), n1 or "—", f"{c.get('vm_powered_on')}/{c.get('vm_count')}"])
    hot_ds = [d for d in ds if (d.get("usage_pct") or 0) >= 85]
    secs = [table("Küme kapasitesi", ["Kaynak", "Küme", "Host (kullanılabilir/toplam)", "Memory kullanım %", "CPU kullanım %",
                                       "Memory taahhüt %", "vCPU oranı", "N+1", "VM (açık/toplam)"], rows, module="Sanallaştırma",
                  kpis=[kpi("Yüksek kullanımlı küme", hot, tone="crit" if hot else "ok"),
                        kpi("Dolu datastore (≥%85)", len(hot_ds), tone="crit" if hot_ds else "ok")])]
    if ds:
        secs.append(table("Datastore doluluğu (en dolu 8)", ["Kaynak", "Datastore", "Kapasite (GB)", "Kullanılan %", "Provizyon %"],
                          [[d.get("hypervisor"), d.get("name"), d.get("capacity_gb"), d.get("usage_pct"), d.get("provisioned_pct")]
                           for d in sorted(ds, key=lambda x: -(x.get("usage_pct") or 0))[:8]], module="Sanallaştırma"))
    for d in hot_ds[:3]:
        recs.append(f"Datastore {d.get('name')} %{d.get('usage_pct')} dolu — genişletme veya taşıma planlayın.")
    return {"sections": secs, "recs": recs, "kpis": {"hot": hot + len(hot_ds)}}


def _capacity_ocp(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_capacity(ctx.db)
    sec = rep["sections"][:1]   # Cluster özeti; node ayrıntısı OpenShift ekip raporunda
    return {"sections": _tag(sec, "openshift"), "recs": rep.get("recommendations") or [],
            "notes": ["OpenShift node ayrıntısı OpenShift modülünün Hazır Raporlar sayfasındadır."]}


def _latest_metrics(ctx: Ctx, ids: List[int], names: List[str]) -> Dict[Tuple[int, str], float]:
    if not ids:
        return {}
    rows = ctx.db.execute(text("""
        SELECT DISTINCT ON (server_id, metric_name) server_id, metric_name, value
        FROM metric_data
        WHERE server_id = ANY(:ids) AND metric_name = ANY(:names) AND timestamp >= NOW() - INTERVAL '1 hour'
        ORDER BY server_id, metric_name, timestamp DESC
    """), {"ids": ids, "names": names}).all()
    return {(int(r.server_id), r.metric_name): float(r.value) for r in rows if r.value is not None}


_LINUX_METRICS = ["cpu_usage_percent", "memory_usage_percent", "disk_root_usage_percent"]


def _capacity_linux(ctx: Ctx) -> Prov:
    servers = ctx.servers("linux")
    if not servers:
        return {"sections": [unmeasured("Sunucu kullanımı", "Linux sunucu yok.", module="Linux")]}
    lm = _latest_metrics(ctx, [s.id for s in servers], _LINUX_METRICS)
    measured = {sid for sid, _n in lm}
    names = {s.id: s.name for s in servers}
    if not measured:
        return {"sections": [unmeasured("Sunucu kullanımı", f"{len(servers)} sunucudan hiçbirinde son 1 saatte CPU/Memory/Disk metriği yok; kullanım ölçülemedi.", module="Linux")]}
    rows, hot = [], 0
    for sid in measured:
        vals = [lm.get((sid, n)) for n in _LINUX_METRICS]
        if any((v or 0) >= 85 for v in vals):
            hot += 1
        rows.append([names[sid], *[r1(v) for v in vals]])
    rows.sort(key=lambda r: -max(v or 0 for v in r[1:]))
    recs = [f"Linux: {hot} sunucu ≥%85 kullanımda — kapasite veya iş yükü dengelemesi değerlendirin."] if hot else []
    return {"sections": [table(f"Sunucu kullanımı (metriği olan {len(measured)}/{len(servers)} sunucu; en yüksek 10)",
                               ["Sunucu", "CPU %", "Memory %", "Disk (/) %"], rows[:10], module="Linux",
                               kpis=[kpi("≥%85 kullanımda", hot, tone="crit" if hot else "ok"),
                                     kpi("Metriği olan", f"{len(measured)}/{len(servers)}")],
                               note="Metrik toplamayan sunucular tabloya girmez (sayı uydurulmaz).")], "recs": recs}


def _capacity_exadata(ctx: Ctx) -> Prov:
    nodes = ctx.exadata_nodes()
    if not nodes:
        return {"sections": [unmeasured("Exadata envanteri", "Exadata düğümü yok.", module="Exadata")]}
    by: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"db": 0, "cell": 0, "cores": 0, "mem": 0.0, "tb": 0.0})
    for n, r in nodes:
        e = by[(r.name if r else "—")]
        role = str(getattr(n.role, "value", n.role) or "").lower()
        e["cell" if "cell" in role or "storage" in role else "db"] += 1
        e["cores"] += int(n.cpu_cores or 0)
        e["mem"] += float(n.memory_gb or 0)
        e["tb"] += float(n.storage_tb or 0)
    rows = [[k, v["db"], v["cell"], v["cores"], r1(v["mem"]), r1(v["tb"])] for k, v in sorted(by.items())]
    return {"sections": [table("Kurulu kapasite (envanter)", ["Rack", "DB düğümü", "Cell", "CPU çekirdek", "Memory (GB)", "Depolama (TB)"], rows,
                               module="Exadata",
                               note="Yalnız KURULU kapasite. Kullanım/doluluk ölçülmediği için kullanım yüzdesi ve tahmin üretilmez.")]}


# ── Tahmin ───────────────────────────────────────────────────────────────────

def _runway_text(fc: Dict[str, Any]) -> Optional[str]:
    rng = fc.get("days_to_threshold_range") or {}
    if not rng:
        return None
    if not rng.get("typical"):
        return "eşik aşıldı"
    return f"{rng.get('fastest')}–{rng.get('slowest') if rng.get('slowest') is not None else '∞'} gün"


def _forecast_virt(ctx: Ctx) -> Prov:
    from app.services import exec_facts

    sec = exec_facts._b1(ctx.db)["sections"][0]
    hv = ctx.hypervisors()
    data = [r for r in sec.get("rows") or [] if r.get("hypervisor_id") in hv]
    if not data:
        return {"sections": [unmeasured("Eşiğe kalan süre", "Host metrik geçmişi yok.", module="Sanallaştırma")]}
    rows, soon = [], 0
    for r in data:
        rw = r.get("runway_days") or {}
        ok = r["status"] == "ok"
        txt = None
        if ok:
            txt = "eşik aşıldı" if not rw.get("typical") else f"{rw.get('fastest')}–{rw.get('slowest') if rw.get('slowest') is not None else '∞'} gün"
            if rw.get("typical") and rw["typical"] <= 365:
                soon += 1
        rows.append([hv[r["hypervisor_id"]].name, r["cluster"], r.get("memory_pct"), f"{r['days']} gün",
                     r.get("confidence") or "—", txt if ok else "ölçülemedi"])
    return {"sections": [table(f"Eşiğe kalan süre — Memory (eşik %{int(FORECAST_THRESHOLD)})",
                               ["Kaynak", "Küme", "Memory şimdi %", "Seri uzunluğu", "Trend güveni", "Eşiğe kalan (aralık)"], rows,
                               module="Sanallaştırma", kpis=[kpi("12 ay içinde eşiğe varan", soon, tone="warn" if soon else "ok")],
                               note="Düşük güven veya 14 günden kısa seride süre yazılmaz. Aralık hızlı–yavaş senaryodur.")],
            "kpis": {"soon": soon}}


def _forecast_ocp(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_forecast(ctx.db)
    soon = next((k["value"] for k in rep["kpis"] if k["label"].startswith("12 ay")), 0)
    return {"sections": _tag(rep["sections"], "openshift"), "kpis": {"soon": soon}}


def _forecast_linux(ctx: Ctx) -> Prov:
    from app.services import report_analytics as ra
    from app.services.platform_report_engine import daily_metric_series

    servers = ctx.servers("linux")
    if not servers:
        return {"sections": [unmeasured("Eşiğe kalan süre", "Linux sunucu yok.", module="Linux")]}
    metrics = ["memory_usage_percent", "disk_root_usage_percent"]
    series = daily_metric_series(ctx.db, [s.id for s in servers], metrics, days=90)
    names = {s.id: s.name for s in servers}
    longest = max((len(v) for v in series.values()), default=0)
    rows, soon = [], 0
    for (sid, metric), vals in series.items():
        if len(vals) < MIN_FORECAST_DAYS:
            continue
        fc = ra.build_threshold_forecast(vals[-1], vals, threshold=FORECAST_THRESHOLD, min_samples=MIN_FORECAST_DAYS)
        if fc.get("trend_confidence") not in ("medium", "high"):
            continue
        d = fc.get("days_to_threshold")
        if d is not None and d <= 365:
            soon += 1
            rows.append([names.get(sid), "Memory" if metric.startswith("memory") else "Disk (/)", r1(fc.get("current_pct")),
                         len(vals), fc.get("trend_confidence"), _runway_text(fc), d])
    if not series or longest < MIN_FORECAST_DAYS:
        return {"sections": [unmeasured("Eşiğe kalan süre",
                                         f"En az {MIN_FORECAST_DAYS} günlük günlük-özet serisi gerekir; en uzun seri {longest} gün. Tahmin üretilmedi.",
                                         module="Linux")]}
    rows.sort(key=lambda r: r[-1])
    for r in rows:
        r.pop()
    return {"sections": [table(f"12 ay içinde eşiğe (%{int(FORECAST_THRESHOLD)}) varan sunucular", ["Sunucu", "Kaynak", "Şimdi %", "Seri (gün)", "Trend güveni", "Eşiğe kalan (aralık)"],
                               rows[:15], module="Linux", kpis=[kpi("12 ay içinde eşiğe varan", soon, tone="warn" if soon else "ok")],
                               note="Yalnız orta/yüksek güvenli trend listelenir; liste boşsa 12 ay içinde eşiğe varan güvenilir trend yok demektir.")],
            "kpis": {"soon": soon}}


# ── Yama / Uyum ──────────────────────────────────────────────────────────────

def _patch_virt(ctx: Ctx) -> Prov:
    vms = [s for s in ctx.servers("virt") if (s.vm_power_state or "").lower() in ("poweredon", "up", "running")]
    with_status = [s for s in vms if s.vm_tools_version_status]
    if not with_status:
        return {"sections": [unmeasured("VM araçları sürümü", "Açık VM'lerde araç sürüm durumu toplanmamış (VMware Tools bilgisi yok).", module="Sanallaştırma")]}
    cnt = Counter(s.vm_tools_version_status for s in with_status)
    old = sum(v for k, v in cnt.items() if "current" not in k.lower() and "unmanaged" not in k.lower())
    rows = [[k, v] for k, v in cnt.most_common()]
    return {"sections": [table("VMware Tools sürüm durumu (açık VM)", ["Durum", "VM"], rows, module="Sanallaştırma",
                               kpis=[kpi("Güncel olmayan araç", old, tone="warn" if old else "ok"),
                                     kpi("Durumu bilinen / açık VM", f"{len(with_status)}/{len(vms)}")])],
            "recs": ([f"{old} VM'de araç sürümü güncel değil — planlı pencerede güncelleyin."] if old else [])}


def _patch_ocp(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_compliance_update(ctx.db)
    return {"sections": _tag(rep["sections"][:1], "openshift"), "kpis": {"kpis": rep["kpis"]}}


def _patch_linux(ctx: Ctx) -> Prov:
    from app.models.system_update import SystemUpdateJob

    servers = ctx.servers("linux")
    if not servers:
        return {"sections": [unmeasured("Bekleyen güncelleme", "Linux sunucu yok.", module="Linux")]}
    ids = [s.id for s in servers]
    latest: Dict[int, Any] = {}
    for j in (ctx.db.query(SystemUpdateJob).filter(SystemUpdateJob.server_id.in_(ids))
              .order_by(SystemUpdateJob.server_id, SystemUpdateJob.id.desc()).all()):
        latest.setdefault(j.server_id, j)
    if not latest:
        return {"sections": [unmeasured("Bekleyen güncelleme",
                                         f"{len(servers)} sunucudan hiçbirinde güncelleme kontrolü yapılmamış; bekleyen paket sayısı ölçülemedi (Sistem Güncelle › kontrol başlatın).",
                                         module="Linux")]}
    names = {s.id: s.name for s in servers}
    pend = {sid: len(j.packages_to_update or []) for sid, j in latest.items()}
    reboot = sum(1 for j in latest.values() if j.reboot_required)
    rows = [[names[sid], n, bool(latest[sid].reboot_required)] for sid, n in sorted(pend.items(), key=lambda x: -x[1])[:8]]
    return {"sections": [table("Bekleyen güncellemeler (kontrol edilen sunucular)", ["Sunucu", "Bekleyen paket", "Yeniden başlatma gerekli"], rows,
                               module="Linux",
                               kpis=[kpi("Kontrol edilen", f"{len(latest)}/{len(servers)}", tone="info" if len(latest) == len(servers) else "warn"),
                                     kpi("Bekleyen paket (toplam)", sum(pend.values())),
                                     kpi("Yeniden başlatma bekleyen", reboot, tone="warn" if reboot else "ok")],
                               note="Son güncelleme kontrolü sonucu; canlı SSH sorgusu yapılmaz. Kontrol edilmeyen sunucular 'temiz' sayılmaz.")]}


def _patch_windows(ctx: Ctx) -> Prov:
    servers = ctx.servers("windows")
    if not servers:
        return {"sections": [unmeasured("Windows güncellemeleri", "Windows sunucu yok.", module="Windows")]}
    checked = [s for s in servers if s.win_updates_last_checked is not None]
    if not checked:
        return {"sections": [unmeasured("Windows güncellemeleri", f"{len(servers)} sunucudan hiçbirinde güncelleme taraması yok; ölçülemedi.", module="Windows")]}
    pend = sum(int(s.win_updates_pending or 0) for s in checked)
    crit = sum(int(s.win_updates_critical or 0) for s in checked)
    reboot = sum(1 for s in checked if s.win_reboot_pending)
    rows = [[s.name, s.win_updates_pending, s.win_updates_critical, bool(s.win_reboot_pending)]
            for s in sorted(checked, key=lambda x: -(x.win_updates_critical or 0) * 1000 - (x.win_updates_pending or 0))[:8]]
    return {"sections": [table("Bekleyen Windows güncellemeleri (taranan sunucular)", ["Sunucu", "Bekleyen", "Kritik", "Yeniden başlatma bekliyor"], rows,
                               module="Windows",
                               kpis=[kpi("Taranan", f"{len(checked)}/{len(servers)}", tone="info" if len(checked) == len(servers) else "warn"),
                                     kpi("Kritik güncelleme", crit, tone="crit" if crit else "ok"),
                                     kpi("Bekleyen (toplam)", pend), kpi("Yeniden başlatma bekleyen", reboot, tone="warn" if reboot else "ok")])],
            "recs": ([f"Windows: {crit} kritik güncelleme bekliyor — bakım penceresi planlayın."] if crit else [])}


# ── Geri kazanım ─────────────────────────────────────────────────────────────

def _reclaim_virt(ctx: Ctx) -> Prov:
    from app.services.virt_capacity_planner import build_capacity

    hv = ctx.hypervisors()
    cl = [c for c in build_capacity(ctx.db, with_forecast=False).get("clusters") or [] if c.get("hypervisor_id") in hv]
    if not cl:
        return {"sections": [unmeasured("Geri kazanım", "Sanallaştırma kümesi yok.", module="Sanallaştırma")]}
    rows, off_gb, idle_gb = [], 0.0, 0.0
    for c in cl:
        rc = c.get("reclaim") or {}
        off_gb += float(rc.get("powered_off_memory_gb") or 0)
        idle_gb += float(rc.get("idle_memory_gb") or 0)
        rows.append([c.get("hypervisor"), c.get("cluster"), rc.get("powered_off_count"), rc.get("powered_off_memory_gb"),
                     rc.get("idle_count"), rc.get("idle_memory_gb"), rc.get("oversized_count"), rc.get("snapshot_gb")])
    recs = []
    if off_gb:
        recs.append(f"Kapalı VM'ler toplam {round(off_gb)} GB Memory tahsisi tutuyor — gerekmeyenleri silin/arşivleyin.")
    if idle_gb:
        recs.append(f"Atıl VM'ler ~{round(idle_gb)} GB Memory serbest bırakabilir (doğrulayarak).")
    return {"sections": [table("Geri kazanım adayları", ["Kaynak", "Küme", "Kapalı VM", "Kapalı Memory (GB)", "Atıl VM", "Atıl Memory (GB)", "Aşırı boyutlu VM", "Snapshot (GB)"],
                               rows, module="Sanallaştırma",
                               kpis=[kpi("Kapalı VM Memory tahsisi (GB)", r1(off_gb), tone="warn" if off_gb else "ok"),
                                     kpi("Atıl VM Memory (GB)", r1(idle_gb), tone="warn" if idle_gb else "ok")],
                               note="Aday listesidir; silme/küçültme kararı sahibiyle doğrulanır.")], "recs": recs}


def _reclaim_ocp(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_storage(ctx.db)
    recs = rep.get("recommendations") or []
    return {"sections": _tag(rep["sections"], "openshift"), "recs": recs}


# ── Migrasyon (MTV) ──────────────────────────────────────────────────────────

def _migration_virt(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_mtv_readiness(ctx.db)
    return {"sections": _tag(rep["sections"][:2], "virt"), "kpis": {"kpis": rep["kpis"]}, "recs": rep.get("recommendations") or []}


def _migration_ocp(ctx: Ctx) -> Prov:
    from app.services import ocp_report_engine as oe

    with oe.hide_synthetic_clusters():
        rep = oe.generate_mtv_migration(ctx.db)
    return {"sections": _tag(rep["sections"][:2], "openshift"), "kpis": {"kpis": rep["kpis"]}, "recs": rep.get("recommendations") or []}


_PROVIDERS: Dict[str, Callable[[Ctx, str], Prov]] = {
    "summary": _p_summary, "risk": _p_risk, "riskiest": _p_riskiest, "operations": _p_operations,
    "sla": _p_sla, "monitoring": _p_monitoring,
    "capacity_virt": lambda c, m: _capacity_virt(c), "capacity_ocp": lambda c, m: _capacity_ocp(c),
    "capacity_linux": lambda c, m: _capacity_linux(c), "capacity_exadata": lambda c, m: _capacity_exadata(c),
    "forecast_virt": lambda c, m: _forecast_virt(c), "forecast_ocp": lambda c, m: _forecast_ocp(c),
    "forecast_linux": lambda c, m: _forecast_linux(c),
    "patch_virt": lambda c, m: _patch_virt(c), "patch_ocp": lambda c, m: _patch_ocp(c),
    "patch_linux": lambda c, m: _patch_linux(c), "patch_windows": lambda c, m: _patch_windows(c),
    "reclaim_virt": lambda c, m: _reclaim_virt(c), "reclaim_ocp": lambda c, m: _reclaim_ocp(c),
    "migration_virt": lambda c, m: _migration_virt(c), "migration_ocp": lambda c, m: _migration_ocp(c),
}


def applicability(report_type: str) -> Dict[str, Any]:
    """UI/test için: alan → {included, reason}."""
    out = {}
    for m in ORDER:
        v = MATRIX[report_type][m]
        out[m] = {"included": not (isinstance(v, tuple) and v[0] == _X), "reason": v[1] if isinstance(v, tuple) else None}
    return out


def _run_providers(ctx: Ctx, report_type: str) -> Tuple[Dict[str, Prov], List[Dict[str, str]]]:
    results: Dict[str, Prov] = {}
    excluded: List[Dict[str, str]] = []
    for m in ORDER:
        v = MATRIX[report_type][m]
        if isinstance(v, tuple) and v[0] == _X:
            excluded.append({"module": MODULE_LABELS[m], "reason": v[1]})
            continue
        try:
            results[m] = _PROVIDERS[v](ctx, m)
        except Exception as exc:  # bir alanın hatası raporu düşürmesin; sayı uydurulmaz
            logger.warning("Yönetici raporu %s/%s: %s", report_type, m, exc, exc_info=True)
            ctx.db.rollback()
            results[m] = {"sections": [unmeasured("Veri okunamadı", "Bu alan için veri okunurken hata oluştu; ölçülemedi.", module=MODULE_LABELS[m])]}
    return results, excluded


def _collect(results: Dict[str, Prov]) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    secs: List[Dict[str, Any]] = []
    recs: List[str] = []
    notes: List[str] = []
    for m in ORDER:
        r = results.get(m)
        if not r:
            continue
        secs += r.get("sections") or []
        recs += r.get("recs") or []
        for n in r.get("notes") or []:
            if n not in notes:
                notes.append(n)
    return secs, recs, notes


_SYNTH_NOTE = "Sentetik (ZZ-FAKE) test kaynakları bu rapora dahil edilmez."
_METHOD_SCORE = ("Alan notu: her varlık için ceza = min(100, 30×kritik + 12×uyarı), varlık skoru = 100 − ceza, alan notu varlık "
                 "skorlarının ortalamasıdır (son 24 saatteki açık olaylar). Ekip raporlarındaki not farklı formülle hesaplanır.")


# ── Rapor üreticileri ────────────────────────────────────────────────────────

def _gen_summary(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "executive_summary")
    rows = [results[m]["row"] for m in ORDER]
    areas = [results[m]["area"] for m in ORDER]
    monitored = [a for a in areas if a["monitored"]]
    crit_assets = sum(a["critical_assets"] for a in areas)
    worst = min((a for a in monitored if a["score"] is not None), key=lambda a: a["score"], default=None)
    top = sorted([(e, MODULE_LABELS[a["platform"]]) for a in areas for e in a["entities"][:5]],
                 key=lambda x: (x[0]["score"], -x[0]["crit"]))[:10]
    recs = []
    for a in monitored:
        if a["status"] in ("Kritik", "Dikkat"):
            recs.append(f"{MODULE_LABELS[a['platform']]}: {a['status']} ({a['critical_assets']} kritik varlık, {a['critical_events']} kritik olay) — "
                        "en riskli varlıklar tabloda.")
    sections = [
        table("Ortam sağlığı", ["Alan", "Envanter", "İzlenen varlık", "Kritik varlık", "Kritik olay (24 sa)", "Uyarı olayı (24 sa)", "Skor", "Durum"], rows,
              note="Skor yalnız altyapı sağlığını gösterir; ekip performansı değildir. «İzleme yok» alanlar skorlanmaz."),
        table("Dikkat gerektiren varlıklar", ["Varlık", "Alan", "Kritik", "Uyarı", "Skor"],
              [[e["name"], mod, e["crit"], e["warn"], e["score"]] for e, mod in top]) if top else
        unmeasured("Dikkat gerektiren varlıklar", "Son 24 saatte açık kritik/uyarı olayı olan varlık yok."),
    ]
    mtv = _mtv_kpi(ctx)
    kp = [kpi("İzlenen alan", f"{len(monitored)}/{len(ORDER)}"),
          kpi("Kritik varlık (alan toplamı)", crit_assets, tone="crit" if crit_assets else "ok"),
          kpi("En düşük skor", (worst["score"] if worst else "—"), MODULE_LABELS[worst["platform"]] if worst else None,
              _status_tone(worst["status"]) if worst else "muted")]
    if mtv:
        kp.append(mtv)
    excl = [{"module": MODULE_LABELS[a["platform"]], "reason": "Envanter yok — izleme yok; skor üretilmedi."} for a in areas if not a["monitored"]]
    return gr.make_report(SCOPE, "executive_summary", REPORT_TITLES["executive_summary"], kpis=kp, sections=sections,
                          recommendations=recs, notes=[_SYNTH_NOTE], excluded=excl + excluded, methodology=_METHOD_SCORE)


def _mtv_kpi(ctx: Ctx) -> Optional[Dict[str, Any]]:
    from app.models.mtv import MtvPlanSnapshot

    rows = ctx.db.query(MtvPlanSnapshot).filter(MtvPlanSnapshot.cluster_id.notin_(list(ctx.hidden_cl) or [-1])).all()
    if not rows:
        return None
    ok = sum(r.vm_succeeded or 0 for r in rows)
    bad = sum(r.vm_failed or 0 for r in rows)
    return kpi("MTV taşınan VM", ok, f"{bad} başarısız" if bad else f"{len(rows)} plan", "crit" if bad else "info")


def _gen_risk(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "risk")
    secs, _r, _n = _collect(results)
    areas = [ctx.area(m) for m in ORDER]
    crit = sum(a["critical_events"] for a in areas)
    return gr.make_report(SCOPE, "risk", REPORT_TITLES["risk"],
                          kpis=[kpi("Kritik olay (24 sa)", crit, tone="crit" if crit else "ok"),
                                kpi("Uyarı olayı (24 sa)", sum(a["warning_events"] for a in areas), tone="warn")],
                          sections=secs, notes=[_SYNTH_NOTE], excluded=excluded, methodology=_METHOD_SCORE)


def _gen_riskiest(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "riskiest_assets")
    items = sorted([i for m in ORDER for i in results[m]["items"]], key=lambda r: (r[4], -r[2], -r[3]))[:20]
    sec = table("En riskli 20 varlık (tüm alanlar)", ["Varlık", "Alan", "Kritik", "Uyarı", "Varlık skoru"], items) if items else \
        unmeasured("En riskli varlıklar", "Son 24 saatte açık kritik/uyarı olayı olan varlık yok.")
    return gr.make_report(SCOPE, "riskiest_assets", REPORT_TITLES["riskiest_assets"],
                          kpis=[kpi("Listelenen varlık", len(items)),
                                kpi("Kritik olaylı varlık", sum(1 for i in items if i[2] > 0), tone="crit" if any(i[2] for i in items) else "ok")],
                          sections=[sec], notes=[_SYNTH_NOTE], excluded=excluded, methodology=_METHOD_SCORE)


def _gen_operations(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "operations")
    rows = [results[m]["row"] for m in ORDER]
    top = [r for m in ORDER for r in results[m]["top"]]
    return gr.make_report(
        SCOPE, "operations", REPORT_TITLES["operations"],
        kpis=[kpi("Olay (30 gün)", sum(r[1] for r in rows)), kpi("Kritik", sum(r[2] for r in rows), tone="crit" if any(r[2] for r in rows) else "ok"),
              kpi("Açık kritik+uyarı (24 sa)", sum(r[5] for r in rows))],
        sections=[table("Alan bazında olaylar (30 gün)", ["Alan", "Toplam", "Kritik", "Uyarı", "Bilgi", "Açık kritik+uyarı (24 sa)", "Onaylanan %"], rows),
                  table("En sık olay türleri (alan başına ilk 5)", ["Alan", "Olay türü", "Adet"], top)],
        notes=[_SYNTH_NOTE], excluded=excluded,
        methodology="SystemEvent kayıtları (oluşturulma ≤30 gün), alan filtresi `platform_scope`. Onaylanan % = onaylanan olay / toplam.")


def _gen_sla(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "sla")
    rows = [results[m]["row"] for m in ORDER if "row" in results[m]]
    secs = [s for m in ORDER for s in (results[m].get("sections") or [])]
    worst = [w for m in ORDER for w in (results[m].get("worst") or [])]
    out = []
    if rows:
        out.append(table("SLA uyumu (hedef %99, 30 gün)", ["Alan", "Varlık", "SLA'yı sağlayan", "Sağlamayan", "Uyum %"], rows))
    if worst:
        out.append(table("En düşük erişilebilirlik (alan başına en kötü 5)", ["Alan", "Varlık", "Kritik olay (30 gün)", "Tahmini erişilebilirlik %"], worst))
    notes = [_SYNTH_NOTE, "Sanallaştırma/Linux/Windows/Exadata: SLA olay yoğunluğundan TAHMİN edilir (her kritik olay −%0,5); kesin ölçüm değildir.",
             "Hem VM hem Linux olan sunucu iki alanda da görünür (alan toplamları tekilleştirilmez)."]
    for m in ORDER:
        if results[m].get("ocp_note"):
            notes.append(results[m]["ocp_note"])
    return gr.make_report(SCOPE, "sla", REPORT_TITLES["sla"],
                          kpis=[kpi("Hedef", "%99"), kpi("Ölçülen alan", f"{len(rows)}/{len(ORDER)}")],
                          sections=out + secs, notes=notes, excluded=excluded,
                          methodology="Varlık başına tahmini erişilebilirlik = 100 − 0,5×kritik olay (30 gün); ≥%99 SLA'yı sağlar. OpenShift: Ready örnek oranı.")


def _gen_monitoring(ctx: Ctx) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, "monitoring_coverage")
    rows = [results[m]["row"] for m in ORDER if "row" in results[m]]
    gaps = [g for m in ORDER for g in (results[m].get("gaps") or [])]
    secs = [s for m in ORDER for s in (results[m].get("sections") or [])]
    out = []
    if rows:
        out.append(table("İzleme kapsamı", ["Alan", "Varlık", "Kurulu/bağlı", "Veri akan", "Kapsam %", "Ölçüt"], rows,
                         note="Kapsam % = veri akan / varlık. Ölçüt alanlar arasında aynı değildir (sütunda yazılı)."))
    if gaps:
        out.append(table("İzleme boşlukları (alan başına ilk 8)", ["Alan", "Varlık", "Durum", "Exporter kurulu", "Veri akıyor"], gaps))
    recs = [f"{r[0]}: kapsam %{r[4]} — veri akmayan varlıklarda exporter/bağlantıyı onarın." for r in rows if (r[4] or 0) < 90]
    return gr.make_report(SCOPE, "monitoring_coverage", REPORT_TITLES["monitoring_coverage"],
                          kpis=[kpi("Ölçülen alan", f"{len(rows)}/{len(ORDER)}")], sections=out + secs,
                          recommendations=recs, notes=[_SYNTH_NOTE], excluded=excluded,
                          methodology="Linux/Windows: exporter çalışıyor oranı. Sanallaştırma: son 1 saatte host metriği gelen kaynaklar. OpenShift: son 30 dk node metriği. Exadata: sunucu kaydına bağlı düğüm.")


def _gen_matrix_report(ctx: Ctx, report_type: str, kpis_fn: Optional[Callable[[Dict[str, Prov]], List[Dict[str, Any]]]] = None,
                       methodology: str = "", extra_notes: Optional[List[str]] = None) -> Dict[str, Any]:
    results, excluded = _run_providers(ctx, report_type)
    secs, recs, notes = _collect(results)
    return gr.make_report(SCOPE, report_type, REPORT_TITLES[report_type],
                          kpis=kpis_fn(results) if kpis_fn else [], sections=secs, recommendations=recs,
                          notes=[_SYNTH_NOTE] + notes + (extra_notes or []), excluded=excluded, methodology=methodology)


def _gen_capacity(ctx: Ctx) -> Dict[str, Any]:
    def k(res):
        hot = (res.get("virt", {}).get("kpis") or {}).get("hot", 0)
        return [kpi("Sanallaştırma: yüksek kullanımlı küme/datastore", hot, tone="crit" if hot else "ok")]
    return _gen_matrix_report(ctx, "capacity", k,
                              "Sanallaştırma: kapasite planlayıcı (host/datastore). OpenShift: request/allocatable + kullanım. Linux: son 1 saat metriği. Exadata: yalnız kurulu envanter.")


def _gen_forecast(ctx: Ctx) -> Dict[str, Any]:
    def k(res):
        soon = sum((r.get("kpis") or {}).get("soon", 0) for r in res.values())
        return [kpi("12 ay içinde eşiğe varan", soon, tone="warn" if soon else "ok"), kpi("Eşik", f"%{int(FORECAST_THRESHOLD)}")]
    return _gen_matrix_report(ctx, "forecast", k,
                              f"Günlük ortalama serilerine Theil–Sen eğimi; en az {MIN_FORECAST_DAYS} gün; aralık eğimin %25–%75 bandından. Yalnız orta/yüksek güvenli trend süre üretir.",
                              ["Geçmişteki eğimin sürdüğünü varsayar; mevsimsellik ve planlı değişim modellenmez."])


def _gen_patch(ctx: Ctx) -> Dict[str, Any]:
    return _gen_matrix_report(ctx, "patch_compliance", None,
                              "Her alanın kendi son tarama/kontrol verisi: VMware Tools sürümü, OpenShift clusterversion/operatör, Linux Sistem Güncelle işleri, Windows güncelleme taraması.",
                              ["Taranmamış sunucu 'güncel' sayılmaz; ölçülemedi olarak işaretlenir."])


def _gen_reclaim(ctx: Ctx) -> Dict[str, Any]:
    return _gen_matrix_report(ctx, "reclaim", None,
                              "Sanallaştırma: kapalı/atıl/aşırı boyutlu VM ve snapshot (kapasite planlayıcı). OpenShift: bağlanmamış / kullanılmayan PVC.")


def _gen_migration(ctx: Ctx) -> Dict[str, Any]:
    def k(res):
        out: List[Dict[str, Any]] = []
        for m in ("openshift", "virt"):
            out += (res.get(m, {}).get("kpis") or {}).get("kpis", [])[:3]
        return out
    return _gen_matrix_report(ctx, "migration", k,
                              "MTV Plan/Migration anlık görüntüleri (geçmiş) ve VMware VM'lerinin OpenShift hedef kapasitesine (N+1 sonrası) sığma hesabı.")


GENERATORS: Dict[str, Callable[[Ctx], Dict[str, Any]]] = {
    "executive_summary": _gen_summary, "capacity": _gen_capacity, "forecast": _gen_forecast,
    "risk": _gen_risk, "riskiest_assets": _gen_riskiest, "operations": _gen_operations,
    "sla": _gen_sla, "patch_compliance": _gen_patch, "reclaim": _gen_reclaim,
    "monitoring_coverage": _gen_monitoring, "migration": _gen_migration,
}


def generate(db: Session, report_type: str, save: bool = True) -> Dict[str, Any]:
    fn = GENERATORS.get(report_type)
    if fn is None:
        raise ValueError(f"Yönetici için bilinmeyen rapor: {report_type}")
    data = fn(Ctx(db))
    data["applicability"] = applicability(report_type)
    if save:
        from app.models.infrastructure_report import InfrastructureReport

        obj = InfrastructureReport(report_type=f"executive:{report_type}", report_title=f"[YÖNETİCİ] {REPORT_TITLES[report_type]}",
                                   data=data, status="ready")
        db.add(obj)
        db.commit()
        db.refresh(obj)
        data["_report_id"] = obj.id
    return data


def get_latest(db: Session, report_type: str) -> Optional[Dict[str, Any]]:
    from app.models.infrastructure_report import InfrastructureReport

    row = (db.query(InfrastructureReport).filter(InfrastructureReport.report_type == f"executive:{report_type}")
           .order_by(InfrastructureReport.generated_at.desc()).first())
    if not row:
        return None
    return {**row.data, "_report_id": row.id, "_generated_at": row.generated_at.isoformat() if row.generated_at else None}


def to_markdown(report_type: str, data: Dict[str, Any], lang: str = "tr") -> str:
    return gr.to_markdown(data, scope=SCOPE, report_type=report_type, lang=lang)
