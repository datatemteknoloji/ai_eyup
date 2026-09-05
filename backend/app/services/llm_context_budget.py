"""
LLM context bütçesi — Gelişmiş Ayarlar (llm_context_token_budget /
llm_context_hard_cap_tokens) ile yapılandırılır.

Tüm chat yollarında prompt/metin kırpma için merkezi yardımcılar.

Section-aware bütçeleme (`budget_sections`): prompt tek bir string olarak
kesilmez. `system` (persona/kurallar) ve `protected_tail` (kullanıcı sorusu +
varsa canlı araç sonuçları) HİÇBİR KOŞULDA kesilmez — yalnızca `context`
(statik envanter/RAG dump'ı) ve gerekirse `history` (konuşma geçmişi)
kısaltılır. Bu, eski `text[:cut]` (baştan kes) davranışının prompt'un SONUNDA
duran soruyu/tool sonucunu silmesi hatasını yapısal olarak önler.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Çıkış + system rezervi (token)
_DEFAULT_RESERVE_TOKENS = 4096
_CHARS_PER_TOKEN_EST = 3.5
# Gateway hard-cap üzerine ekstra pay — tokenizer tahminimiz (char/3.5) gerçek
# tokenizer'dan sapabilir; bu pay 400 (context length exceeded) riskini azaltır.
_HARD_CAP_SAFETY_TOKENS = 2000


def get_context_token_budget() -> int:
    """Kullanıcının/adminin İSTEDİĞİ context bütçesi (Gelişmiş Ayarlar)."""
    try:
        from app.services.runtime_settings import get_setting
        raw = get_setting("llm_context_token_budget")
        return int(raw) if raw is not None else 32768
    except Exception:
        return 32768


def get_gateway_hard_cap_tokens() -> int:
    """Gateway/model'in GERÇEK maksimum context penceresi (güvenlik tavanı).

    `llm_context_token_budget` bunu aşarsa otomatik olarak buna kırpılır —
    böylece bütçe ayarı ne kadar büyük seçilirse seçilsin gateway'e model
    limitini aşan istek gitmez. Model/gateway değişip pencere büyürse
    (32K → 64K/128K) yalnızca bu ayar güncellenir, kod değişmez.
    """
    try:
        from app.services.runtime_settings import get_setting
        raw = get_setting("llm_context_hard_cap_tokens")
        return int(raw) if raw is not None else 32768
    except Exception:
        return 32768


def get_input_token_budget(*, reserve: int = _DEFAULT_RESERVE_TOKENS) -> int:
    """Efektif input bütçesi = min(istenen bütçe, gateway hard-cap − güvenlik payı) − rezerv."""
    desired = get_context_token_budget()
    hard_cap = max(2048, get_gateway_hard_cap_tokens() - _HARD_CAP_SAFETY_TOKENS)
    effective_total = min(desired, hard_cap)
    return max(2048, effective_total - reserve)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN_EST))


def truncate_text_to_token_budget(text: str, max_tokens: int, *, suffix: str = "\n\n…(context kısaltıldı)") -> Tuple[str, bool]:
    """Metni tahmini token bütçesine kırpar. (text, truncated?)"""
    if not text or max_tokens <= 0:
        return ("" if max_tokens <= 0 else (text or "")), bool(text)
    est = estimate_tokens(text)
    if est <= max_tokens:
        return text, False
    max_chars = int(max_tokens * _CHARS_PER_TOKEN_EST)
    if max_chars <= len(suffix) + 100:
        return text[:max_chars], True
    cut = max_chars - len(suffix)
    logger.info(
        "LLM context kırpıldı: ~%d token → ~%d token budget",
        est, max_tokens,
    )
    return text[:cut] + suffix, True


def apply_prompt_budget(prompt: str, *, reserve: Optional[int] = None) -> Tuple[str, bool]:
    """ESKİ davranış (geriye dönük uyumluluk): TÜM prompt'u baştan kırpar.

    DİKKAT: prompt'un SONUNDA kritik içerik (kullanıcı sorusu, tool sonucu)
    varsa bu fonksiyon onu silebilir. Yeni kodda mümkünse `budget_sections`
    kullanın — o, soruyu/tool sonucunu asla kesmez. Bu fonksiyon yalnızca
    context'in her zaman prompt'un BAŞINDA olduğu, soru içermeyen eski
    call-site'lar için bırakıldı.
    """
    budget = get_input_token_budget(reserve=reserve or _DEFAULT_RESERVE_TOKENS)
    return truncate_text_to_token_budget(prompt, budget)


def apply_context_char_budget(text: str, max_tokens: Optional[int] = None) -> str:
    """unified_tool_chat context_str için."""
    budget = max_tokens or get_input_token_budget()
    out, _ = truncate_text_to_token_budget(text, budget)
    return out


def log_section_usage(label: str, meta: Dict[str, Any]) -> None:
    """ChatGPT/Cursor'un önerdiği per-section token observability formatı.

    Örnek (OK):   [LLM_CONTEXT:HVIntelligence] system=1850 history=920 context=18740
                  tail=42 total=21552 limit=28672 truncated=False truncated_section=- final=21552
    Örnek (kesildi): ... context=91240 total=94052 limit=28672 truncated=True
                  truncated_section=context final=28650
    """
    level = logger.warning if meta.get("truncated") else logger.info
    level(
        "[LLM_CONTEXT:%s] system=%d history=%d context=%d tail=%d total=%d "
        "limit=%d truncated=%s truncated_section=%s final=%d",
        label or "-",
        meta.get("system_tokens", 0),
        meta.get("history_tokens", 0),
        meta.get("context_tokens", 0),
        meta.get("tail_tokens", 0),
        meta.get("total_tokens", 0),
        meta.get("limit", 0),
        meta.get("truncated", False),
        meta.get("truncated_section") or "-",
        meta.get("final_tokens", 0),
    )


def budget_sections(
    *,
    system: str,
    context: str = "",
    history: str = "",
    protected_tail: str,
    reserve: Optional[int] = None,
    log_label: str = "",
) -> Dict[str, Any]:
    """Section bazlı context bütçesi.

    KURAL: `system` ve `protected_tail` (kullanıcı sorusu + varsa "[CANLI ARAÇ
    SONUÇLARI]" bloğu) HİÇBİR KOŞULDA kesilmez — yalnızca `context` (statik
    envanter/RAG dump'ı, genelde en büyük ve en az kritik bölüm) ve gerekirse
    `history` (konuşma geçmişi) kısaltılır. Aşırı durumda (system+tail tek
    başına bütçeyi aşarsa) context/history sıfıra iner ama soru/tool sonucu
    yine de olduğu gibi gönderilir — sessiz veri kaybı yerine gateway'in kendi
    400'ü tercih edilir (en azından hatanın nedeni açık olur).

    Döner: {"context": str, "history": str, "meta": {...}}
    """
    reserve = _DEFAULT_RESERVE_TOKENS if reserve is None else reserve
    limit = get_input_token_budget(reserve=reserve)

    t_system = estimate_tokens(system)
    t_history = estimate_tokens(history)
    t_context = estimate_tokens(context)
    t_tail = estimate_tokens(protected_tail)
    total = t_system + t_history + t_context + t_tail

    out_context, out_history = context, history
    truncated = False
    truncated_section: Optional[str] = None

    if total > limit:
        truncated = True
        # system + protected_tail için ayrılan pay sabit (kesilmez); geri kalanı
        # context + history paylaşır.
        flex_budget = max(0, limit - t_system - t_tail)

        if t_context > 0:
            new_context_budget = min(t_context, flex_budget)
            if new_context_budget < t_context:
                out_context, _ = truncate_text_to_token_budget(context, new_context_budget)
                truncated_section = "context"
            flex_budget = max(0, flex_budget - estimate_tokens(out_context))
        if t_history > 0 and estimate_tokens(out_context) + t_history > (limit - t_system - t_tail):
            remaining = max(0, limit - t_system - t_tail - estimate_tokens(out_context))
            if remaining < t_history:
                out_history, _ = truncate_text_to_token_budget(history, remaining)
                truncated_section = "context+history" if truncated_section else "history"

        if t_system + t_tail > limit:
            logger.warning(
                "[LLM_CONTEXT:%s] system+question+tool_result tek başına bütçeyi "
                "aşıyor (system=%d tail=%d limit=%d) — context/history sıfırlansa "
                "da yetmez; kesme YAPILMADI (soru/tool sonucu korunuyor, gateway "
                "kendi limit hatasını verebilir).",
                log_label or "-", t_system, t_tail, limit,
            )

    meta = {
        "system_tokens": t_system,
        "history_tokens": t_history,
        "context_tokens": t_context,
        "tail_tokens": t_tail,
        "total_tokens": total,
        "limit": limit,
        "truncated": truncated,
        "truncated_section": truncated_section,
        "final_tokens": t_system + estimate_tokens(out_context) + estimate_tokens(out_history) + t_tail,
    }
    if log_label:
        log_section_usage(log_label, meta)
    return {"context": out_context, "history": out_history, "meta": meta}
