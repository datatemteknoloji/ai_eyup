"""Unified Chat — deterministik intent router + module-first orkestrasyon.

Tek structured karar: knowledge | planning_clarify | planning_agentic | live.
Domain'ler module_orchestrator ile exclusive (single) veya bilinçli multi kombinasyon.
Modül seçimi kullanıcıya SORULMAZ — belirsizlikte otomatik domain seti açılır.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import FrozenSet, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnifiedRoute:
    mode: str  # knowledge | live | planning_clarify | planning_agentic
    domains: FrozenSet[str]
    need_rag: bool
    need_live: bool
    complexity: str  # simple | normal | deep
    confidence: float
    reason: str
    wants_linux: bool = False
    wants_windows: bool = False
    wants_openshift: bool = False
    linux_specific: bool = False
    windows_specific: bool = False
    # module-first
    module_mode: str = ""  # single | multi | knowledge
    modules: Tuple[str, ...] = ()
    join_keys: Tuple[str, ...] = ()
    need_prometheus: bool = False
    persona_addendum: str = ""
    clarify_options: Tuple[str, ...] = ()  # geriye uyum; kullanılmaz


def _complexity(message: str, *, mode: str) -> str:
    if mode in ("knowledge", "planning_clarify"):
        return "simple"
    try:
        from app.services.chat_path_policy import is_deep_live_query
        from app.services.chat_planning_intent import is_depth_followup, resolve_planning_scope
        if is_deep_live_query(message) or is_depth_followup(message):
            return "deep"
        if resolve_planning_scope(message) == "mtv":
            return "deep"
    except Exception:
        pass
    return "normal"


def _from_module_plan(message: str, plan) -> UnifiedRoute:
    """ModulePlan → UnifiedRoute (clarify yok)."""
    mods = plan.modules or ()
    wants_linux = "linux" in mods or "exadata" in mods
    wants_windows = "windows" in mods
    wants_openshift = "openshift" in mods
    linux_specific = "linux" in mods
    windows_specific = "windows" in mods

    if plan.mode == "knowledge":
        return UnifiedRoute(
            mode="knowledge",
            domains=frozenset({"infra"}),
            need_rag=True,
            need_live=False,
            complexity="simple",
            confidence=plan.confidence,
            reason=plan.reason,
            module_mode="knowledge",
            need_prometheus=False,
        )

    from app.services.module_orchestrator import persona_addendum
    persona = persona_addendum(plan)

    return UnifiedRoute(
        mode="live",
        domains=plan.domains,
        need_rag=True,
        need_live=True,
        complexity=_complexity(message, mode="live"),
        confidence=plan.confidence,
        reason=plan.reason,
        wants_linux=wants_linux,
        wants_windows=wants_windows,
        wants_openshift=wants_openshift,
        linux_specific=linux_specific,
        windows_specific=windows_specific,
        module_mode=plan.mode,
        modules=mods,
        join_keys=plan.join_keys,
        need_prometheus=bool(plan.need_prometheus),
        persona_addendum=persona,
    )


def route_unified(
    message: str,
    *,
    is_followup: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
    skip_ctx: bool = False,
) -> UnifiedRoute:
    """Unified soru için tek structured rota kararı (module-first, auto)."""
    msg = message or ""

    from app.services.chat_planning_intent import (
        planning_needs_clarification,
        is_cross_platform_planning,
        resolve_planning_scope,
        is_depth_followup,
    )
    from app.services.chat_path_policy import is_knowledge_only
    from app.services.module_orchestrator import plan_modules, persona_addendum

    # 1) Planlama netleştirme (MTV / taşıma kapsamı — ayrı ürün akışı)
    if planning_needs_clarification(
        msg,
        is_followup=is_followup,
        has_episode=has_episode,
        clarification_pending=clarification_pending,
    ):
        return UnifiedRoute(
            mode="planning_clarify",
            domains=frozenset({"vcenter", "openshift", "infra"}),
            need_rag=False,
            need_live=False,
            complexity="simple",
            confidence=0.9,
            reason="planning_needs_clarification",
            wants_openshift=True,
            module_mode="multi",
            modules=("virt", "openshift"),
            join_keys=("vm_name", "hostname"),
            persona_addendum=(
                "\n\nYÖNETİCİ → Planlama netleştirme: önce kapsam seçtir; tool çağırma.\n"
            ),
        )

    # 2) Planlama agentic (scope / depth / cross-platform migrate)
    scope = resolve_planning_scope(msg)
    if scope or is_depth_followup(msg) or is_cross_platform_planning(msg):
        plan = plan_modules(msg, skip_ctx=skip_ctx)
        domains = frozenset({"vcenter", "openshift", "infra"})
        mods = plan.modules if plan.mode == "multi" and len(plan.modules) >= 2 else ("virt", "openshift")
        return UnifiedRoute(
            mode="planning_agentic",
            domains=domains,
            need_rag=True,
            need_live=True,
            complexity=_complexity(msg, mode="planning_agentic"),
            confidence=0.85,
            reason=(
                f"planning_scope:{scope}" if scope
                else ("planning_depth" if is_depth_followup(msg) else "planning_cross")
            ),
            wants_linux=False,
            wants_windows=False,
            wants_openshift=True,
            module_mode="multi",
            modules=tuple(mods),
            join_keys=plan.join_keys or ("vm_name", "hostname"),
            need_prometheus=False,
            persona_addendum=persona_addendum(plan) if plan.mode == "multi" else (
                "\n\nYÖNETİCİ → vCenter↔OpenShift planlama: vcenter + openshift READ-ONLY; "
                "Linux SSH açma. Join: vm_name/hostname.\n"
            ),
        )

    # 3) Saf bilgi / selamlaşma
    if is_knowledge_only(msg):
        from app.services.chat_path_policy import is_chitchat
        reason = "chitchat" if is_chitchat(msg) else "knowledge_only"
        return UnifiedRoute(
            mode="knowledge",
            domains=frozenset({"infra"}),
            need_rag=reason != "chitchat",
            need_live=False,
            complexity="simple",
            confidence=0.95 if reason == "chitchat" else 0.8,
            reason=reason,
            module_mode="knowledge",
        )

    # 4) Module-first canlı rota (clarify yok)
    plan = plan_modules(msg, skip_ctx=skip_ctx)
    route = _from_module_plan(msg, plan)
    logger.info(
        "[ModuleOrch] mode=%s modules=%s domains=%s conf=%.2f reason=%s prom=%s",
        plan.mode, plan.modules, sorted(plan.domains), plan.confidence,
        plan.reason, plan.need_prometheus,
    )
    return route
