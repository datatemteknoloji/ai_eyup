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

Son kapı (`enforce_prompt_budget` / `enforce_messages_budget`): bütçeleme
çağıranın elinde olduğu için bir yol bunu atlarsa (ya da tool sonuçları
prompt kurulduktan sonra büyürse) gateway'e hard-cap'i aşan istek gidebilir.
Bu iki fonksiyon `llm_gateway` içinde, HTTP isteğinden hemen önce çalışır ve
payload'ı model penceresine sığdırır.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Çıkış + system rezervi (token)
_DEFAULT_RESERVE_TOKENS = 4096
# Muhafazakâr başlangıç oranı: Türkçe metin + JSON/Markdown tablo ağırlıklı
# promptlarda gerçek tokenizer 3.5 char/token'dan daha kötü davranabiliyor.
# Gerçek `usage.prompt_tokens` geldikçe `record_actual_usage` ile kalibre edilir.
_CHARS_PER_TOKEN_EST = 3.0
_CAL_FLOOR, _CAL_CEIL = 2.0, 4.5
_CAL_ALPHA = 0.25
_CAL_MIN_SAMPLES = 3
_CAL_SAFETY = 0.95  # kalibre oranı %5 muhafazakâr tut
_cal_lock = threading.Lock()
_cal_state: Dict[str, Any] = {"ratio": None, "samples": 0, "last_observed": None}
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


def _effective_ratio(raw: float) -> float:
    """Kalibre oran her zaman biraz muhafazakâr (küçük) tarafta tutulur."""
    return min(_CAL_CEIL, max(_CAL_FLOOR, raw * _CAL_SAFETY))


def chars_per_token() -> float:
    """Kullanılan karakter/token oranı — gerçek `usage` verisiyle kalibre edilir.

    Başlangıç değeri muhafazakârdır (token sayısını olduğundan fazla tahmin
    eder), böylece ilk isteklerde model penceresi aşılmaz. Uzak gateway
    `usage.prompt_tokens` döndürdükçe oran gerçek tokenizer'a yakınsar.
    """
    with _cal_lock:
        if _cal_state["samples"] >= _CAL_MIN_SAMPLES and _cal_state["ratio"]:
            return _effective_ratio(float(_cal_state["ratio"]))
    return _CHARS_PER_TOKEN_EST


def record_actual_usage(prompt_chars: int, actual_prompt_tokens: int) -> None:
    """Gerçek prompt token sayısıyla karakter/token oranını kalibre eder (EWMA).

    `llm_gateway` uzak yanıttaki `usage.prompt_tokens` ile çağırır. Oran
    [_CAL_FLOOR, _CAL_CEIL] aralığına kelepçelenir; böylece bozuk/eksik bir
    usage alanı bütçeyi uçuk değerlere taşımaz.
    """
    try:
        chars = int(prompt_chars)
        tokens = int(actual_prompt_tokens)
    except Exception:
        return
    if chars < 2000 or tokens <= 0:
        # Kısa promptlarda sistem şablonu/oran gürültüsü yüksek — örneklemeye alma.
        return
    observed = chars / float(tokens)
    if not (_CAL_FLOOR <= observed <= _CAL_CEIL):
        return
    with _cal_lock:
        prev = _cal_state["ratio"]
        # Ham EWMA saklanır; muhafazakâr pay (_CAL_SAFETY) okuma anında
        # uygulanır — aksi hâlde her turda çarpılıp birikirdi.
        ratio = observed if prev is None else (1 - _CAL_ALPHA) * float(prev) + _CAL_ALPHA * observed
        _cal_state["ratio"] = min(_CAL_CEIL, max(_CAL_FLOOR, ratio))
        _cal_state["samples"] = int(_cal_state["samples"]) + 1
        _cal_state["last_observed"] = round(observed, 3)


def calibration_snapshot() -> Dict[str, Any]:
    # Not: `_cal_lock` reentrant değil — kilit altında chars_per_token()
    # çağrılmaz, oran burada aynı mantıkla hesaplanır.
    with _cal_lock:
        samples = int(_cal_state["samples"])
        ratio = _cal_state["ratio"]
        calibrated = bool(samples >= _CAL_MIN_SAMPLES and ratio)
        return {
            "chars_per_token": round(
                _effective_ratio(float(ratio)) if calibrated else _CHARS_PER_TOKEN_EST, 3
            ),
            "default": _CHARS_PER_TOKEN_EST,
            "calibrated": calibrated,
            "samples": samples,
            "last_observed": _cal_state["last_observed"],
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token()))


def truncate_text_to_token_budget(text: str, max_tokens: int, *, suffix: str = "\n\n…(context kısaltıldı)") -> Tuple[str, bool]:
    """Metni tahmini token bütçesine kırpar. (text, truncated?)"""
    if not text or max_tokens <= 0:
        return ("" if max_tokens <= 0 else (text or "")), bool(text)
    est = estimate_tokens(text)
    if est <= max_tokens:
        return text, False
    max_chars = int(max_tokens * chars_per_token())
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


# ─────────────────────────────────────────────────────────────────────────
# Son kapı (hard gate) — gateway'e HTTP isteği gitmeden hemen önce
# ─────────────────────────────────────────────────────────────────────────

_MIDDLE_MARKER = "\n\n…(model context penceresine sığması için orta bölüm kırpıldı)…\n\n"
# Rol/ayraç payı ve kırpma işaretçisi yuvarlamaları için küçük emniyet payı.
_GATE_SLACK_TOKENS = 16


def get_payload_hard_limit(*, reserve: int = _DEFAULT_RESERVE_TOKENS) -> int:
    """Gateway'e gidebilecek en fazla INPUT token'ı.

    hard-cap − tokenizer güvenlik payı − çıkış (completion) rezervi. Bu, hangi
    bütçe ayarı seçilmiş olursa olsun modelin kendi penceresine göre hesaplanan
    mutlak tavandır.
    """
    cap = max(2048, get_gateway_hard_cap_tokens() - _HARD_CAP_SAFETY_TOKENS)
    return max(1024, cap - max(0, reserve))


def truncate_middle(text: str, max_tokens: int, *, head_ratio: float = 0.35) -> Tuple[str, bool]:
    """Metnin ORTASINI kırpar; baş (persona/kurallar) ve son (soru) korunur."""
    if not text:
        return text, False
    if estimate_tokens(text) <= max_tokens:
        return text, False
    max_chars = max(200, int(max_tokens * chars_per_token()))
    if max_chars <= len(_MIDDLE_MARKER) + 200:
        return text[-max_chars:], True
    keep = max_chars - len(_MIDDLE_MARKER)
    head = int(keep * head_ratio)
    tail = keep - head
    return text[:head] + _MIDDLE_MARKER + text[-tail:], True


def enforce_prompt_budget(
    prompt: str,
    *,
    system: Optional[str] = None,
    label: str = "",
    reserve: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Tek string prompt için son kapı — hard limit aşılıyorsa ortadan kırpar.

    Normal akışta `budget_sections` zaten sığdırmış olur ve burada hiçbir şey
    değişmez. Bir çağıran bütçelemeyi atladıysa (ya da tool sonuçları prompt
    kurulduktan sonra büyüdüyse) bu fonksiyon modelin "context length
    exceeded" hatasını sessiz veri kaybı yerine kontrollü kırpmaya çevirir.
    """
    limit = get_payload_hard_limit(reserve=reserve or _DEFAULT_RESERVE_TOKENS)
    t_system = estimate_tokens(system or "")
    t_prompt = estimate_tokens(prompt or "")
    total = t_system + t_prompt
    meta: Dict[str, Any] = {
        "limit": limit,
        "system_tokens": t_system,
        "prompt_tokens": t_prompt,
        "total_tokens": total,
        "final_tokens": total,
        "truncated": False,
    }
    if total <= limit:
        return prompt, meta

    allowed = max(1024, limit - t_system - _GATE_SLACK_TOKENS)
    out, truncated = truncate_middle(prompt or "", allowed)
    meta["truncated"] = truncated
    meta["final_tokens"] = t_system + estimate_tokens(out)
    logger.warning(
        "[LLM_HARD_GATE:%s] prompt hard limit aşıyordu: ~%d token → ~%d "
        "(limit=%d, system=%d) — orta bölüm kırpıldı",
        label or "-", total, meta["final_tokens"], limit, t_system,
    )
    return out, meta


def _message_text(msg: Dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    try:
        import json as _json
        return _json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def _message_tokens(msg: Dict[str, Any]) -> int:
    tokens = estimate_tokens(_message_text(msg))
    calls = msg.get("tool_calls")
    if calls:
        try:
            import json as _json
            tokens += estimate_tokens(_json.dumps(calls, ensure_ascii=False))
        except Exception:
            pass
    return tokens + 4  # rol/ayraç payı


def enforce_messages_budget(
    messages: List[Dict[str, Any]],
    *,
    label: str = "",
    reserve: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Chat (messages) payload'ı için son kapı.

    Mesaj SİLİNMEZ — yalnızca içerik kısaltılır. Bunun nedeni OpenAI
    sözleşmesi: `tool_calls` içeren assistant mesajı ile ona ait `tool`
    yanıtları ayrılırsa gateway 400 döner. Kısaltma sırası: önce büyük tool
    çıktıları ve eski mesajlar, en son (mecbur kalınırsa) son kullanıcı
    mesajı ve system.
    """
    limit = get_payload_hard_limit(reserve=reserve or _DEFAULT_RESERVE_TOKENS)
    if not messages:
        return messages, {"limit": limit, "total_tokens": 0, "final_tokens": 0, "truncated": False}

    tokens = [_message_tokens(m) for m in messages]
    total = sum(tokens)
    meta: Dict[str, Any] = {
        "limit": limit,
        "message_count": len(messages),
        "total_tokens": total,
        "final_tokens": total,
        "truncated": False,
        "shrunk_messages": 0,
    }
    if total <= limit:
        return messages, meta

    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if (messages[i].get("role") or "") == "user":
            last_user_idx = i
            break

    def _priority(i: int) -> tuple:
        role = (messages[i].get("role") or "").lower()
        if role == "system":
            group = 3
        elif i == last_user_idx:
            group = 2
        elif role == "tool":
            group = 0
        else:
            group = 1
        return (group, -tokens[i])

    order = sorted(range(len(messages)), key=_priority)
    out = [dict(m) for m in messages]
    current = total

    for floor in (1500, 500, 150):
        for i in order:
            if current <= limit:
                break
            if tokens[i] <= floor:
                continue
            target = max(floor, tokens[i] - (current - limit) - _GATE_SLACK_TOKENS)
            text = _message_text(out[i])
            if not isinstance(out[i].get("content"), str) or not text:
                continue
            new_text, truncated = truncate_middle(text, target, head_ratio=0.2)
            if not truncated:
                continue
            out[i]["content"] = new_text
            new_tokens = _message_tokens(out[i])
            current -= max(0, tokens[i] - new_tokens)
            tokens[i] = new_tokens
            meta["shrunk_messages"] = int(meta["shrunk_messages"]) + 1
        if current <= limit:
            break

    meta["truncated"] = meta["shrunk_messages"] > 0
    meta["final_tokens"] = current
    logger.warning(
        "[LLM_HARD_GATE:%s] messages hard limit aşıyordu: ~%d token → ~%d "
        "(limit=%d, kısaltılan mesaj=%d)",
        label or "-", total, current, limit, meta["shrunk_messages"],
    )
    return out, meta
