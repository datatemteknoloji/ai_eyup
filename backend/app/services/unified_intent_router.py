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


def _route_unified_core(
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
    try:
        from app.services.route_llm_hint import apply_route_llm_hint
        plan = apply_route_llm_hint(msg, plan)
    except Exception:
        pass
    route = _from_module_plan(msg, plan)
    logger.info(
        "[ModuleOrch] mode=%s modules=%s domains=%s conf=%.2f reason=%s prom=%s",
        plan.mode, plan.modules, sorted(plan.domains), plan.confidence,
        plan.reason, plan.need_prometheus,
    )
    return route


_HW_PERSONA = (
    "\n\nYÖNETİCİ → DONANIM (Dell OME / HPE OneView): yalnız `hw_server_status` / `hw_alerts_summary` araçlarıyla cevapla; "
    "sayıları (total, total_all_servers, by_health_all, active_alerts) aynen aktar, tahmin etme. Garanti sorusunda "
    "`warranty` süzgecini kullan; 'truncated' true ise listeyi tam sayıp 'N tane' deme, 'total' değerini söyle. "
    "İlgili araç sonucu bu turda zaten verildi (araç mesajı); önce ona bak. Sonuç listesi boşsa ('total': 0) «bu adla/süzgeçle "
    "donanım kaydı yok» de — «sorgulanmadı» DEME. BMC/iDRAC/iLO IP adresi, firmware sürümü, seri/service tag ve kimlik bilgisi "
    "sohbette paylaşılmaz ve araçta yoktur: istenirse «bu bilgi sohbette paylaşılmaz; yetkili kullanıcılar Donanım sayfasında "
    "görür» de. Alan ve araç adlarını (warranty_expired, by_health, hw_server_status vb.) yazma; Türkçe anlat. Sayıyı SÜZGEÇLİ alandan (`total`/`by_health`) al, tüm-kayıt alanlarını (`*_all*`) yalnız genel toplam sorulursa kullan. "
    "Liste verirken TOPLAM sayıyı (total / total_all_servers) açıkça yaz (ör. «6 sunucu kritik»); liste kısaltıldıysa belirt. "
    "Araç `demo:true` dönerse cevapta açıkça 'DEMO veri' yaz. Araç hata dönerse donanım verisi uydurma.\n"
)


def route_unified(
    message: str,
    *,
    is_followup: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
    skip_ctx: bool = False,
    hw_allowed: bool = True,
) -> UnifiedRoute:
    """Çekirdek rota + (yetenek açıkken) donanım sinyali. `hw_allowed=False` (kullanıcıda `hardware` modülü yok) →
    çekirdek rota AYNEN (ör. «fiziksel sunucu» yazan Linux kullanıcısı Linux envanterine gider).

    Donanım sinyali (`tools_hw.hw_intent`) yalnız `hw`/`hw_demo` yeteneği açıkken rotayı değiştirir; yetenek yoksa çekirdek
    rota AYNEN döner (donanım entegrasyonsuz ortam bugünkü gibi davranır). Başka platform sinyali yoksa tool alanı yalnız
    `hw`; varsa mevcut alanlara `hw` eklenir. Planlama rotalarına dokunulmaz."""
    r = _route_unified_core(message, is_followup=is_followup, has_episode=has_episode,
                            clarification_pending=clarification_pending, skip_ctx=skip_ctx)
    try:
        if r.mode in ("planning_clarify", "planning_agentic"):
            return r
        from app.services.hw.intent import hw_active, hw_intent, other_platform_signal
        if not hw_allowed or not hw_intent(message) or not hw_active():
            return r
        import dataclasses
        if other_platform_signal(message):
            return dataclasses.replace(
                r, mode="live" if r.mode == "knowledge" else r.mode,
                domains=frozenset(set(r.domains) | {"hw"}), need_live=True, complexity="normal",
                reason=f"hw_signal+{r.reason}", persona_addendum=(r.persona_addendum or "") + _HW_PERSONA)
        return dataclasses.replace(
            r, mode="live", domains=frozenset({"hw"}), need_rag=False, need_live=True, complexity="normal",
            confidence=max(r.confidence, 0.8), reason="hw_signal", wants_linux=False, wants_windows=False,
            wants_openshift=False, linux_specific=False, windows_specific=False, module_mode="single",
            modules=("hw",), join_keys=(), need_prometheus=False, persona_addendum=_HW_PERSONA)
    except Exception:  # noqa: BLE001 — donanım katmanı hatası çekirdek rotayı bozmaz
        return r
