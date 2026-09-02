"""
Sayfa kapsamı + kaynak planı.

Kapsam istekle gelir (linux/windows/openshift/exadata/hypervisor/unified).
Kapsam içinde yalnız gerekli kaynaklar seçilir; RAG/SSH/Prometheus kalkmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, FrozenSet, List, Optional

SCOPE_DOMAINS = {
    "linux": frozenset({"linux", "infra"}),
    "windows": frozenset({"windows", "infra"}),
    "openshift": frozenset({"openshift", "infra"}),
    "exadata": frozenset({"exadata", "linux", "infra"}),
    "hypervisor": frozenset({"vcenter", "openshift", "infra"}),
    "virt": frozenset({"vcenter", "openshift", "infra"}),
    "unified": frozenset({"linux", "windows", "openshift", "vcenter", "exadata", "infra"}),
}

_PERF = (
    "cpu", "ram", "memory", "bellek", "disk", "iowait", "latency", "iops",
    "performans", "performance", "yavaş", "yavas", "yük", "load", "swap",
    "network", "ağ", "ag", "throughput", "kullanım", "usage",
    "metrik", "metrics", "uptime", "kaynak", "detay", "kapsamlı", "kapsamli",
)
_INVENTORY = (
    "listele", "kaç", "kac", "how many", "envanter", "inventory", "özet", "ozet",
    "hangi sunucu", "hangi vm", "kapalı vm", "kapali vm", "çalışan", "calisan",
)
_TROUBLE = (
    "hata", "error", "fail", "crash", "restart", "neden", "kök", "kok", "rca",
    "yavaş", "yavas", "down", "notready", "pending", "crashloop",
)
_KNOWLEDGE = (
    "nasıl", "nasil", "nedir", "how to", "runbook", "prosedür", "prosedur",
)


@dataclass
class SourcePlan:
    scope: str
    domains: FrozenSet[str]
    intent: str
    sources: List[str]
    need_rag: bool
    rag_collections: List[str]
    need_live: bool
    need_prometheus: bool
    complexity: str
    reason: str
    suggestions_hint: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["domains"] = sorted(self.domains)
        return d


def clamp_domains(scope: str, domains: FrozenSet[str]) -> FrozenSet[str]:
    allowed = SCOPE_DOMAINS.get((scope or "").lower()) or SCOPE_DOMAINS["unified"]
    if (scope or "").lower() == "unified":
        return domains or allowed
    return frozenset(d for d in domains if d in allowed) or (allowed & {"infra"}) | (
        frozenset({next(iter(allowed - {"infra"}))} if allowed - {"infra"} else {"infra"})
    )


def plan_sources(
    message: str,
    *,
    scope: str,
    skip_ctx: bool = False,
    use_rag: bool = True,
    is_followup: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
) -> SourcePlan:
    scope_l = (scope or "unified").lower()
    if scope_l in ("virt", "hypervisor"):
        scope_l = "hypervisor"
    msg = message or ""
    ml = msg.lower()

    domains: FrozenSet[str] = SCOPE_DOMAINS.get(scope_l, SCOPE_DOMAINS["unified"])
    intent = "live"
    reason = "live"
    complexity = "normal"
    need_rag = bool(use_rag)
    need_live = not skip_ctx
    need_prom = False
    rag_cols: List[str] = []
    sources: List[str] = ["db"]

    if scope_l == "unified":
        try:
            from app.services.unified_intent_router import route_unified
            route = route_unified(
                msg,
                is_followup=is_followup,
                has_episode=has_episode,
                clarification_pending=clarification_pending,
                skip_ctx=skip_ctx,
            )
            domains = clamp_domains(scope_l, route.domains)
            intent = route.mode
            reason = route.reason
            complexity = route.complexity
            need_rag = bool(use_rag and route.need_rag)
            need_live = bool(route.need_live and not skip_ctx)
            # Module-first: Prometheus yalnız plan izin verirse
            need_prom = bool(getattr(route, "need_prometheus", False))
        except Exception:
            domains = clamp_domains(scope_l, domains)
    else:
        domains = clamp_domains(scope_l, domains)
        if any(k in ml for k in _INVENTORY) and not any(k in ml for k in _TROUBLE):
            intent = "inventory"
            reason = "db_fast_path"
            complexity = "simple"
            need_rag = False
            need_live = False
        elif any(k in ml for k in _KNOWLEDGE) and not any(k in ml for k in _TROUBLE):
            intent = "knowledge"
            reason = "knowledge"
            need_live = False

    # Kapsamlı perf kelimesi: yalnız linux/windows domain varken Prom aç
    if any(k in ml for k in _PERF) or any(k in ml for k in ("yavaş", "yavas", "darboğaz", "bottleneck")):
        if "linux" in domains or "windows" in domains or "exadata" in domains:
            need_prom = True
            intent = "performance" if intent == "live" else intent
            complexity = "deep" if any(k in ml for k in _TROUBLE) else complexity
        # virt-only: Prom açma (vcenter_perf_query)
        if domains <= frozenset({"vcenter", "infra", "openshift"}) and "linux" not in domains:
            if "vcenter" in domains and "linux" not in domains and "windows" not in domains:
                need_prom = False

    if any(k in ml for k in _TROUBLE):
        intent = "troubleshooting" if intent in ("live", "performance") else intent
        complexity = "deep"
        need_live = not skip_ctx
        need_rag = bool(use_rag)

    if need_prom:
        sources.append("prometheus")
    if need_live:
        if "linux" in domains or "exadata" in domains:
            sources.append("ssh")
        if "windows" in domains:
            sources.append("winrm")
        if "vcenter" in domains:
            sources.append("vcenter")
        if "openshift" in domains:
            sources.append("openshift")
    if need_rag:
        sources.append("rag")
        rag_cols = _rag_collections(ml, intent)

    if intent in ("inventory",) and "db" not in sources:
        sources.insert(0, "db")

    hint = ""
    if intent == "troubleshooting":
        hint = "verify"
    elif intent == "performance":
        hint = "inspect"
    elif complexity == "deep":
        hint = "verify"

    # unique preserve
    seen = set()
    uniq = []
    for s in sources:
        if s not in seen:
            seen.add(s)
            uniq.append(s)

    return SourcePlan(
        scope=scope_l,
        domains=domains,
        intent=intent,
        sources=uniq,
        need_rag=need_rag,
        rag_collections=rag_cols,
        need_live=need_live,
        need_prometheus=need_prom,
        complexity=complexity,
        reason=reason,
        suggestions_hint=hint,
    )


def _rag_collections(ml: str, intent: str) -> List[str]:
    cols: List[str] = []
    if intent == "knowledge" or any(k in ml for k in _KNOWLEDGE):
        cols.append("runbook")
    if intent in ("troubleshooting", "performance") or any(k in ml for k in _TROUBLE):
        cols.extend(["incidents", "runbook"])
    if intent == "performance" or any(k in ml for k in _PERF):
        cols.append("metric_descriptions")
    cols.append("knowledge_facts")
    seen = set()
    out = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def build_followup_suggestions(plan: SourcePlan, used_sources: Optional[List[str]] = None) -> List[dict]:
    """İkinci LLM çağrısı yok — kural tabanlı konu önerileri."""
    used = used_sources or plan.sources
    items: List[dict] = []
    if plan.need_prometheus or "prometheus" in used:
        items.append({"type": "verify", "label": "Son 2 saatlik CPU/RAM/disk trendini getir"})
    if "openshift" in plan.domains:
        items.append({"type": "inspect", "label": "Pod event ve restart sayılarını karşılaştır"})
    if "vcenter" in plan.domains:
        items.append({"type": "inspect", "label": "vCenter alarm ve datastore doluluğunu kontrol et"})
    if "linux" in plan.domains and plan.intent in ("troubleshooting", "performance"):
        items.append({"type": "verify", "label": "SSH ile iostat/journalctl kanıtını doğrula"})
    if "windows" in plan.domains:
        items.append({"type": "inspect", "label": "Windows event log ve WinRM sağlık özetini getir"})
    if plan.need_rag:
        items.append({"type": "inspect", "label": "İlgili runbook ve benzer incident'lara bak"})
    if not items:
        items.append({"type": "verify", "label": "Bu kapsamda envanter özetini yenile"})
    return items[:3]
