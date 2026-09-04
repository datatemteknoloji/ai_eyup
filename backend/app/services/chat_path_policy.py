"""Chat canlı yol politikası (Plan 2 Dalga 2 — TTFT).

Varsayılan: sabit collect XOR agentic (ikisi birden değil).
Ağır yol: derin keyword veya chat_force_collect_and_agentic.
Kısa follow-up + episode: sabit collect atlanır.
Knowledge-only: saf bilgi sorularında collect/agentic yok (Unified Dalga 1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEEP_LIVE_KEYWORDS = (
    "vmstat",
    "iostat",
    "1 dakika",
    "1 dak",
    "derin analiz",
    "benchmark",
    "1 saniyelik",
    "10 defa",
    "saniye aralık",
    "örnekle",
    "psi",
    "pressure",
    "kök neden",
    "kok neden",
    "root cause",
    "teşhis",
    "teshis",
    "troubleshoot",
)

# Canlı filo / teşhis / planlama — knowledge-only'yi iptal eder
_LIVE_BLOCK_KEYWORDS = (
    "filo", "filomuz", "karşılaştır", "karsilastir", "kontrol et", "kontrol edin",
    "incele", "bakıver", "bakiver", "canlı", "canli", "bizim", "ortamımız", "ortamimiz",
    "sunucuda", "sunucumuz", "cluster'da", "clusterda", "neden", "niye", "niçin", "nicin",
    "pending", "crashloop", "crash", "failed", "notready", "not ready", "down",
    "alarm", "olay", "incident", "anomali", "anomal", "kimde yüksek", "en yüksek cpu",
    "en yuksek cpu", "kaç sunucu", "kac sunucu", "listele", "göster", "goster",
    "ssh", "winrm", "bağlan", "baglan",
)

# Saf kavram / howto kalıpları
_KNOWLEDGE_HINTS = (
    "ne işe yarar", "ne ise yarar", "nedir", "ne demek", "ne anlama",
    "nasıl çalışır", "nasil calisir", "nasıl çalışır?", "açıkla", "acikla",
    "anlat", "meaning", "what is", "what does", "how does", "man page",
    "komutu ne", "flag ne", "parametre ne", "syntax", "sözdizimi", "sozdizimi",
    "farkı nedir", "farki nedir", "arasındaki fark", "arasindaki fark",
    "nasıl kullanılır", "nasil kullanilir", "nasıl yapılır", "nasil yapilir",
    "adım adım", "adim adim", "best practice", "en iyi uygulama",
)

# Kısa follow-up: sabit filo/collect atlanır (episode/playbook yeterli olabilir)
_FOLLOWUP_MAX_CHARS = 140


@dataclass(frozen=True)
class LivePathDecision:
    run_fixed_collect: bool
    run_agentic: bool
    is_deep: bool
    reason: str


def is_deep_live_query(message: Optional[str]) -> bool:
    m = (message or "").lower()
    if not m:
        return False
    return any(k in m for k in DEEP_LIVE_KEYWORDS)


def is_chitchat(message: Optional[str]) -> bool:
    try:
        from app.services.chat_chitchat_policy import is_chitchat as _ic
        return bool(_ic(message))
    except Exception:
        return False


def is_knowledge_only(message: Optional[str]) -> bool:
    """Saf bilgi/howto veya selamlaşma mı? (canlı collect/agentic gerekmez)

    Planlama/migrasyon, derin teşhis ve filo/canlı niyetleri hariç.
    """
    m = (message or "").lower().strip()
    if not m or len(m) > 400:
        return False
    if is_chitchat(message):
        return True
    try:
        from app.services.chat_planning_intent import (
            is_cross_platform_planning,
            is_depth_followup,
            resolve_planning_scope,
        )
        if is_cross_platform_planning(m) or is_depth_followup(m) or resolve_planning_scope(m):
            return False
    except Exception:
        pass
    if is_deep_live_query(m):
        return False
    # chat_intent (paylaşımlı sınıflandırıcı — virt sohbetiyle aynı motor): saf
    # kavramsal/eğitim/troubleshooting-metodolojisi sorusu, "neden"/"incele" gibi
    # basit _LIVE_BLOCK_KEYWORDS eşleşmelerine rağmen canlı SSH/WinRM/agentic
    # taramayı TETİKLEMEMELİ. Gerçek canlı teşhis istekleri zaten yukarıdaki
    # is_deep_live_query ("kök neden", "root cause" vb.) ile önce yakalanır.
    _ci_kind = None
    try:
        from app.services.chat_intent import ChatIntentKind, classify_chat_intent
        _ci = classify_chat_intent(m)
        _ci_kind = _ci.kind
        if _ci.kind == ChatIntentKind.CONCEPTUAL and _ci.confidence >= 0.7:
            return True
        if _ci.kind in (ChatIntentKind.INVENTORY, ChatIntentKind.LIVE):
            # chat_intent zaten somut bir ölçülebilir değer/envanter isteği
            # tespit etti (ör. "snapshotların boyutları nedir?") — aşağıdaki kaba
            # "X nedir?" yakalayıcısı bunu ezip knowledge_only'e düşürmesin.
            return False
    except Exception:
        pass
    if any(k in m for k in _LIVE_BLOCK_KEYWORDS):
        return False
    if any(k in m for k in _KNOWLEDGE_HINTS):
        return True
    # Kısa "X nedir?" / "X ne?" kalıbı (yalnızca chat_intent yukarıda somut bir
    # envanter/canlı sinyali tespit ETMEDIYSE — aksi halde ezme)
    if len(m) <= 80 and (
        m.endswith(" nedir") or m.endswith(" nedir?")
        or m.endswith(" ne?") or m.endswith(" ne")
        or " nedir " in m
    ):
        return True
    return False


def _force_both_from_settings() -> bool:
    try:
        from app.services import runtime_settings
        return bool(runtime_settings.get_bool("chat_force_collect_and_agentic"))
    except Exception:
        return False


def has_session_episode(*, session_id: Optional[int], platform: str) -> bool:
    if not session_id:
        return False
    try:
        from app.services.episode_memory import get_episode_block
        return bool(get_episode_block(session_id=session_id, platform=platform))
    except Exception:
        return False


def is_short_followup(message: Optional[str], *, is_followup: bool) -> bool:
    if not is_followup:
        return False
    text = (message or "").strip()
    return 0 < len(text) <= _FOLLOWUP_MAX_CHARS


def resolve_live_path(
    message: str,
    *,
    agentic_enabled: bool,
    wants_fixed_collect: bool,
    has_live_targets: bool,
    is_followup: bool = False,
    has_episode: bool = False,
    force_both: Optional[bool] = None,
    allow_agentic_without_collect: bool = False,
) -> LivePathDecision:
    """Sabit collect / agentic kararını üret.

    wants_fixed_collect: platform keyword (needs_ssh / needs_winrm / wants_linux|windows)
    has_live_targets: Dalga 1 sonrası canlı hedef listesi dolu mu
    allow_agentic_without_collect: OpenShift gibi collect'siz agentic platformlar
    """
    # Saf bilgi/howto veya chitchat: collect + agentic kapalı
    if is_knowledge_only(message):
        return LivePathDecision(
            run_fixed_collect=False,
            run_agentic=False,
            is_deep=False,
            reason="chitchat" if is_chitchat(message) else "knowledge_only",
        )

    deep = is_deep_live_query(message)
    both = deep or (force_both if force_both is not None else _force_both_from_settings())

    can_collect = bool(wants_fixed_collect and has_live_targets)
    can_agentic = bool(agentic_enabled)

    # Kısa follow-up + episode: sabit taramayı atla (TTFT); agentic gerekirse kalır
    if (
        not both
        and can_collect
        and is_short_followup(message, is_followup=is_followup)
        and has_episode
    ):
        return LivePathDecision(
            run_fixed_collect=False,
            run_agentic=can_agentic,
            is_deep=False,
            reason="followup_episode_skip_collect",
        )

    if both:
        return LivePathDecision(
            run_fixed_collect=can_collect,
            run_agentic=can_agentic,
            is_deep=deep,
            reason="deep_or_force_both",
        )

    # XOR: canlı collect gerekirdi + agentic açık → yalnız agentic (collect yok)
    if can_agentic and can_collect:
        return LivePathDecision(
            run_fixed_collect=False,
            run_agentic=True,
            is_deep=False,
            reason="agentic_first_xor",
        )

    # Agentic kapalı → klasik collect
    if can_collect:
        return LivePathDecision(
            run_fixed_collect=True,
            run_agentic=False,
            is_deep=False,
            reason="collect_only",
        )

    # Collect yok (prom-only / hedef yok): agentic yalnızca özel platformlarda
    if can_agentic and allow_agentic_without_collect:
        return LivePathDecision(
            run_fixed_collect=False,
            run_agentic=True,
            is_deep=False,
            reason="agentic_without_collect",
        )

    return LivePathDecision(
        run_fixed_collect=False,
        run_agentic=False,
        is_deep=False,
        reason="neither",
    )
