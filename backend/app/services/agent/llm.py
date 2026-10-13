"""
LLM tool-calling katmanı (sağlayıcı-bağımsız, varsayılan Ollama).

Ollama'nın /api/chat endpoint'i `tools` parametresini ve dönüşte
message.tool_calls'u destekler (gpt-oss:20b, llama3.1, qwen2.5 vb.).

Model seçilebilir: çağıran taraf model adını verir (request.model veya get_active_model).

Hata toleransı:
  - Ollama 500 "error parsing tool call" → tools olmadan retry yap.
    Thinking/CoT modeller (qwen3, deepseek-r1) zaman zaman araç çağrısı
    yerine düşünce metni üretir; Ollama JSON parser'ı bunu reddeder.
    Retry'da plain metin cevap alınır, araç çağrısı olmadığı için ajan
    final yanıt olarak döndürür.
  - <think>...</think> etiketleri içerikten temizlenir.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings
from app.services import llm_gateway

logger = logging.getLogger(__name__)

# <think>...</think> veya <thinking>...</thinking> bloklarını temizler.
_THINK_RE = re.compile(r"<think(?:ing)?>\s*(.*?)\s*</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


_TEMP_CV: "contextvars.ContextVar[Optional[float]]" = contextvars.ContextVar("llm_turn_temperature", default=None)


def set_turn_temperature(value: Optional[float]) -> None:
    """Bu bağlamdaki sonraki LLM turlarının temperature değeri (None → eski varsayılan 0.1)."""
    _TEMP_CV.set(value)


def _temp() -> float:
    v = _TEMP_CV.get()
    return 0.1 if v is None else float(v)


def _strip_thinking(text: str) -> str:
    """Modelin düşünce bloklarını asistan cevabından kaldırır."""
    return _THINK_RE.sub("", text or "").strip()


def _ollama_chat(payload: Dict[str, Any], timeout: int):
    """Ollama /api/chat çağrısı — REMOTE_LLM_ENABLED ise şeffafça uzak OpenAI-uyumlu
    gateway'e (örn. Bifrost) yönlendirilir (llm_gateway üzerinden)."""
    return llm_gateway.chat_sync(
        model=payload["model"],
        messages=payload["messages"],
        tools=payload.get("tools"),
        options=payload.get("options"),
        timeout=timeout,
        think=payload.get("think"),
    )


def _force_final_answer(
    model: str, messages: List[Dict[str, Any]], timeout: int,
    *, think: Optional[str] = None, num_predict: Optional[int] = None,
) -> str:
    """gpt-oss/harmony gibi kanal-tabanlı modeller bazen "final" kanalına hiç
    geçmeden düşünce metniyle (thinking) durur — `message.content` boş kalır,
    `message.thinking` doludur ama İngilizce iç-monolog içerir, doğrudan
    kullanıcıya gösterilemez.

    Bu, tool'lar KALDIRILDIKTAN sonra bile olabiliyor (bkz. chat_with_tools'taki
    500 "tool call parse" retry'ı — o retry de content boş dönebilir). Son çare:
    konuşmaya "artık tool çağırma, mevcut sonuçlarla düz metin nihai cevap yaz"
    talimatını AÇIK bir kullanıcı mesajı olarak ekleyip tools OLMADAN tekrar sor.
    Bu da boşsa boş string döner — çağıran taraf placeholder'a düşer.
    """
    nudge = messages + [{
        "role": "user",
        "content": (
            "Yukarıdaki tool sonuçlarına bakarak sorunun NİHAİ cevabını ŞİMDİ "
            "düz metin (markdown) olarak Türkçe yaz. Başka tool ÇAĞIRMA, sadece "
            "elindeki bilgiyle özetle. Sonuç boşsa (örn. eşleşen VM/host yok) "
            "bunu net bir cümleyle bildir."
        ),
    }]
    try:
        _metrics_begin_tool_turn(nudge, None, think=think, num_predict=num_predict)
        opts: Dict[str, Any] = {"temperature": _temp()}
        if num_predict:
            opts["num_predict"] = int(num_predict)
        pl: Dict[str, Any] = {"model": model, "messages": nudge, "stream": False, "options": opts}
        if think:
            pl["think"] = think
        resp = _ollama_chat(pl, timeout)
        if resp.status_code == 200:
            msg = (resp.json().get("message", {}) or {})
            return _strip_thinking(msg.get("content", "") or "")
    except Exception as e:
        logger.error(f"[AgentLLM] final-answer nudge başarısız: {e}")
    return ""


def _parse_tool_calls(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    tool_calls: List[Dict[str, Any]] = []
    for idx, tc in enumerate(msg.get("tool_calls", []) or []):
        fn = tc.get("function", {}) or {}
        raw_args = fn.get("arguments", {})
        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception:
                raw_args = {}
        name = fn.get("name", "")
        if name:
            tool_calls.append({
                "id": tc.get("id") or f"call_{idx}_{name}",
                "name": name,
                "arguments": raw_args or {},
            })
    return tool_calls


def chat_with_tools(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
    _retry: bool = True,
    *,
    think: Optional[str] = None,
    num_predict: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tek tur LLM çağrısı. Dönüş:
      {
        "content": str,                 # asistan metni (varsa, <think> temizlenmiş)
        "tool_calls": [                 # LLM'in çağırmak istediği tool'lar
            {"name": str, "arguments": dict}
        ],
        "error": Optional[str],
      }

    Geçici bağlantı/timeout hataları (Ollama anlık yoğunluk, model yükleme vb.)
    kullanıcıya hemen hata olarak yansıtılmadan önce BİR kez otomatik tekrar
    denenir (_retry=True, iç kullanım — dışarıdan çağrılırken varsayılan davranış
    korunur).
    """
    result = _chat_with_tools_once(model, messages, tools, timeout, think=think, num_predict=num_predict)
    if result.get("error") and _retry:
        transient = (
            "bağlanılamadı" in result["error"] or "zaman aşımı" in result["error"]
            or "HTTP 500" in result["error"] or "HTTP 502" in result["error"]
            or "HTTP 503" in result["error"]
        )
        if transient:
            logger.warning(
                f"[AgentLLM] Geçici LLM hatası, 1 kez tekrar deneniyor: {result['error'][:150]}"
            )
            retry_result = _chat_with_tools_once(
                model, messages, tools, timeout, think=think, num_predict=num_predict)
            if not retry_result.get("error"):
                return retry_result
            # Retry de başarısız oldu — orijinal hatayı döndür.
            return retry_result
    return result


def _check_ctx_ratio(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """Tur prompt'unun (tahmini) num_ctx oranı; eşik (%70 varsayılan) aşılırsa log."""
    try:
        from app.services.llm_chat_policy import ctx_warn_ratio
        from app.services.llm_context_budget import estimate_tokens
        from app.services.ollama_runtime import get_num_ctx
        n_ctx = int(get_num_ctx() or 0)
        if n_ctx <= 0:
            return None
        text = "\n".join(
            (m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content") or "", ensure_ascii=False))
            for m in messages or []
        )
        tok = int(estimate_tokens(text)) + (
            int(estimate_tokens(json.dumps(tools, ensure_ascii=False))) if tools else 0
        )
        ratio = tok / n_ctx
        if ratio > ctx_warn_ratio():
            logger.warning(
                "[LLMContext] tur prompt'u num_ctx'in %%%d eşiğini aştı: ~%d / %d token (%%%d)",
                int(ctx_warn_ratio() * 100), tok, n_ctx, int(ratio * 100),
            )
        try:
            from app.services import chat_request_metrics as crm
            crm.set_turn_ctx_ratio(ratio)
        except Exception:
            pass
        return ratio
    except Exception:
        return None


def _metrics_begin_tool_turn(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    *,
    think: Optional[str] = None,
    num_predict: Optional[int] = None,
    streamed: bool = False,
) -> None:
    """Aktif sohbet ölçümüne LLM turu + token bölümü + istek parametreleri."""
    try:
        from app.services import chat_request_metrics as crm
        from app.services.ollama_runtime import get_keep_alive, get_num_ctx
    except Exception:
        return
    if crm.current() is None:
        return
    purpose = "tool_selection" if tools else "final_answer"
    crm.begin_llm_turn(purpose, think=think, num_predict=num_predict, streamed=streamed)
    _check_ctx_ratio(messages, tools)
    try:
        import hashlib
        first_sys = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")
        if not isinstance(first_sys, str):
            first_sys = str(first_sys)
        cut = first_sys.find("## 11. Çalışma zamanı bağlamı")
        static_part = first_sys if cut < 0 else first_sys[:cut]
        crm.set_turn_prefix_fingerprint(
            hashlib.sha1(static_part.encode("utf-8")).hexdigest()[:10],
            hashlib.sha1(json.dumps(tools or [], ensure_ascii=False, sort_keys=False).encode("utf-8")).hexdigest()[:10],
            len(static_part),
        )
    except Exception:
        pass
    sys_parts, hist, tool_res = [], [], []
    user = ""
    for m in messages or []:
        role = m.get("role")
        c = m.get("content") or ""
        if not isinstance(c, str):
            c = json.dumps(c, ensure_ascii=False) if c else ""
        if role == "system":
            sys_parts.append(c)
        elif role == "user":
            user = c
        elif role == "tool":
            tool_res.append(c)
        elif role == "assistant":
            hist.append(c)
    tool_json = json.dumps(tools or [], ensure_ascii=False)
    sections = crm.estimate_section_tokens(
        system="\n".join(sys_parts),
        tools_results="\n".join(tool_res),
        history="\n".join(hist),
        tool_defs_json=tool_json,
        user=user,
        budget_tokens=get_num_ctx(),
    )
    crm.set_turn_token_sections(sections)
    params = dict(crm.current().request_params or {})
    params.update({
        "temperature": _temp(),
        "think_reasoning": think or "model_default (payload'da think yok)",
        "num_predict": num_predict,
        "stream": streamed,
        "tools_count": len(tools or []),
        "tools_defs_tokens_est": sections.get("tool_definitions", 0),
        "num_ctx": get_num_ctx(),
        "keep_alive": get_keep_alive(),
    })
    crm.set_request_params(params)


def _metrics_note_empty(*, tool_parse_error: bool = False, content: str = "", tool_calls: Any = None) -> None:
    try:
        from app.services import chat_request_metrics as crm
        if not content and not tool_calls:
            crm.mark_empty_turn(tool_parse_error=tool_parse_error)
    except Exception:
        pass


def _chat_with_tools_once(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
    *,
    think: Optional[str] = None,
    num_predict: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": _temp()},
    }
    if num_predict:
        payload["options"]["num_predict"] = int(num_predict)
    if think:
        payload["think"] = think
    if tools:
        payload["tools"] = tools

    _metrics_begin_tool_turn(messages, tools, think=think, num_predict=num_predict)
    try:
        resp = _ollama_chat(payload, timeout)

        # Bozuk tool-call JSON (gpt-oss: ör. `"limit":25"`) model örnekleme hatasıdır: ÖNCE aynı istek araçlarla bir kez
        # daha denenir (tools'suz retry modeli araçsız bırakır → veri uydurma riski).
        if resp.status_code == 500 and tools and "error parsing tool call" in (resp.text or "").lower():
            logger.warning("[AgentLLM] bozuk tool-call JSON → aynı istek araçlarla 1 kez yeniden deneniyor")
            _metrics_note_empty(tool_parse_error=True)
            _metrics_begin_tool_turn(messages, tools, think=think, num_predict=num_predict)
            resp = _ollama_chat(payload, timeout)

        # ── Ollama 500 → tool call parse hatası olabilir ───────────────────
        if resp.status_code == 500:
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", "") if isinstance(err_body, dict) else str(err_body)
                # Bifrost/LiteLLM gibi uzak gateway'ler OpenAI-uyumlu iç içe
                # {"error": {"message": ..., "type": ..., "code": ...}} formatı
                # döndürebilir — bu durumda err_msg bir dict olur ve altta
                # ".lower()" çağrısı "'dict' object has no attribute 'lower'"
                # ile patlar (bkz. üretim logu). İç mesajı çıkar, olmazsa str().
                if isinstance(err_msg, dict):
                    err_msg = (
                        err_msg.get("message")
                        or err_msg.get("error")
                        or str(err_msg)
                    )
                elif not isinstance(err_msg, str):
                    err_msg = str(err_msg)
            except Exception:
                err_msg = resp.text or ""

            tool_parse_fail = (
                "parsing tool call" in err_msg.lower()
                or "tool_call" in err_msg.lower()
                or "error parsing" in err_msg.lower()
            )

            if tool_parse_fail and tools:
                # Thinking modeller araç çağrısı yerine düşünce metni üretir;
                # Ollama JSON parser'ı bunu reddeder → tools olmadan tekrar dene.
                logger.warning(
                    f"[AgentLLM] Ollama tool-call parse hatası, tools'suz retry: {err_msg[:120]}"
                )
                _metrics_note_empty(tool_parse_error=True)
                payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
                try:
                    _metrics_begin_tool_turn(messages, None, think=think, num_predict=num_predict)
                    resp2 = _ollama_chat(payload_no_tools, timeout)
                    if resp2.status_code == 200:
                        msg2 = (resp2.json().get("message", {}) or {})
                        content2 = _strip_thinking(msg2.get("content", "") or "")
                        if not content2:
                            # Retry de boş döndü (harmony "final" kanalına hiç
                            # geçmemiş olabilir) — açık talimatla bir kez daha dene.
                            content2 = _force_final_answer(model, messages, timeout, think=think, num_predict=num_predict)
                        # Tool çağrısı yok → ajan bunu final yanıt olarak değerlendirir.
                        _metrics_note_empty(content=content2, tool_calls=[])
                        return {"content": content2, "tool_calls": [], "error": None}
                except Exception as re2:
                    logger.error(f"[AgentLLM] tools'suz retry başarısız: {re2}")

            # Retry yardımcı olmadıysa veya başka bir 500 hatası
            return {"content": "", "tool_calls": [],
                    "error": f"LLM HTTP 500: {err_msg[:300]}"}

        if resp.status_code != 200:
            # Groq/OpenAI bazı modeller tools'u reddeder (400) — tools'suz bir kez dene.
            if resp.status_code == 400 and tools:
                logger.warning(
                    "[AgentLLM] HTTP 400 (tools reddi olabilir), tools'suz retry: %s",
                    (resp.text or "")[:160],
                )
                payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
                try:
                    _metrics_begin_tool_turn(messages, None, think=think, num_predict=num_predict)
                    resp2 = _ollama_chat(payload_no_tools, timeout)
                    if resp2.status_code == 200:
                        msg2 = (resp2.json().get("message", {}) or {})
                        content2 = _strip_thinking(msg2.get("content", "") or "")
                        _metrics_note_empty(content=content2, tool_calls=[])
                        return {
                            "content": content2,
                            "tool_calls": [],
                            "error": None,
                        }
                except Exception as re2:
                    logger.error("[AgentLLM] tools'suz 400 retry başarısız: %s", re2)
            return {"content": "", "tool_calls": [],
                    "error": f"LLM HTTP {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        msg = data.get("message", {}) or {}
        content = _strip_thinking(msg.get("content", "") or "")
        tool_calls = _parse_tool_calls(msg)

        if not content and not tool_calls and data.get("done_reason") == "length" and num_predict:
            # num_predict (thinking dahil) tavanı görünür çıktı üretilmeden doldu → bir kez yüksek tavanla.
            from app.services.llm_chat_policy import bumped_num_predict
            higher = bumped_num_predict(int(num_predict))
            logger.warning(
                "[AgentLLM] done_reason=length, görünür çıktı boş (num_predict=%s, eval=%s) → "
                "tek seferlik retry num_predict=%s", num_predict, data.get("eval_count"), higher,
            )
            _metrics_note_empty(content="", tool_calls=[])
            payload["options"]["num_predict"] = higher
            _metrics_begin_tool_turn(messages, tools, think=think, num_predict=higher)
            try:
                from app.services import chat_request_metrics as crm
                crm.set_turn_retry_note(f"length retry {num_predict}->{higher}")
            except Exception:
                pass
            resp_r = _ollama_chat(payload, timeout)
            if resp_r.status_code == 200:
                data = resp_r.json()
                msg = data.get("message", {}) or {}
                content = _strip_thinking(msg.get("content", "") or "")
                tool_calls = _parse_tool_calls(msg)

        if not content and not tool_calls:
            # Model tool çağırmıyor (bitirdi) ama content de boş — "final"
            # kanalına geçmeden durmuş (gpt-oss/harmony'de gözlenen bir kaçak
            # senaryo). Boş yanıt kullanıcıya "(boş yanıt)" gibi anlamsız bir
            # placeholder olarak gitmesin; açık talimatla bir kez daha dene.
            _metrics_note_empty(content="", tool_calls=[])
            content = _force_final_answer(model, messages, timeout, think=think, num_predict=num_predict)

        _metrics_note_empty(content=content, tool_calls=tool_calls)
        return {"content": content, "tool_calls": tool_calls, "error": None}

    except requests.exceptions.ConnectionError:
        return {"content": "", "tool_calls": [], "error": "Ollama'ya bağlanılamadı."}
    except requests.exceptions.Timeout:
        return {"content": "", "tool_calls": [], "error": "LLM zaman aşımına uğradı."}
    except Exception as e:
        logger.error("[AgentLLM] Hata: %s", e, exc_info=True)
        return {"content": "", "tool_calls": [], "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────
# Stream modu: tool-loop turu canlı akıtılır, tool_calls akıştan çözülür (Adım 6b)
# ─────────────────────────────────────────────────────────────────────────

# Tool çağrısı öncesi kısa "ön söz"ün kullanıcıya sızmaması için ilk bu kadar karakter tutulur
# (gpt-oss'ta tool_calls genelde içerik olmadan gelir; ~24 karakter ≈ 6 token → ilk token gecikmesi ihmal edilebilir).
_PREAMBLE_HOLD_CHARS = 24


def chat_with_tools_stream(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
    *,
    think: Optional[str] = None,
    num_predict: Optional[int] = None,
):
    """`chat_with_tools` ile aynı sonuç sözleşmesi, ama görünür içerik canlı akıtılır.

    Üretilen olaylar:
      {"type": "token", "text": str}   — kullanıcıya gösterilebilir yanıt parçası
                                         (yalnızca tool çağrısı OLMAYAN turda)
      {"type": "result", "content": str, "tool_calls": [...], "error": str|None,
       "streamed_chars": int, "done_reason": str|None}

    Hata / boş yanıt / 400-500 durumlarında tek seferlik akışsız `chat_with_tools`
    yoluna düşer (mevcut tolerans mantığı korunur); bu durumda streamed_chars=0.
    """
    from app.services import llm_gateway as gw

    attempt_np = num_predict
    for attempt in (1, 2):
        _metrics_begin_tool_turn(messages, tools, think=think, num_predict=attempt_np, streamed=True)
        options: Dict[str, Any] = {"temperature": _temp()}
        if attempt_np:
            options["num_predict"] = int(attempt_np)
        if attempt == 2:
            try:
                from app.services import chat_request_metrics as crm
                crm.set_turn_retry_note(f"length retry {num_predict}->{attempt_np}")
            except Exception:
                pass

        hold = ""            # henüz kullanıcıya bırakılmamış içerik
        released = False
        content_all = ""
        thinking_chars = 0
        streamed_chars = 0
        tool_calls_raw: List[Dict[str, Any]] = []
        done_data: Dict[str, Any] = {}
        err: Optional[Dict[str, Any]] = None
        try:
            for ev in gw.chat_stream_iter(
                model, messages, tools=tools, options=options, timeout=timeout, think=think,
            ):
                et = ev.get("type")
                if et == "thinking":
                    thinking_chars += len(ev.get("text") or "")
                elif et == "content":
                    txt = ev.get("text") or ""
                    content_all += txt
                    if tool_calls_raw:
                        continue
                    if released:
                        streamed_chars += len(txt)
                        yield {"type": "token", "text": txt}
                    else:
                        hold += txt
                        if len(hold) >= _PREAMBLE_HOLD_CHARS:
                            released = True
                            streamed_chars += len(hold)
                            yield {"type": "token", "text": hold}
                            hold = ""
                elif et == "tool_calls":
                    tool_calls_raw.extend(ev.get("calls") or [])
                elif et == "done":
                    done_data = ev.get("data") or {}
                elif et == "error":
                    err = ev
        except Exception as e:
            logger.error("[AgentLLM] stream hatası: %s", e, exc_info=True)
            err = {"status": 599, "text": str(e)}

        try:
            from app.services import chat_request_metrics as crm
            crm.note_stream_text(thinking_chars=thinking_chars, content_chars=len(content_all),
                                 content_head=content_all[:160])
        except Exception:
            pass

        if err is not None:
            if streamed_chars:
                # Kullanıcıya zaten içerik gitti — tekrar üretmeden kısmi içerikle bitir.
                yield {"type": "result", "content": _strip_thinking(content_all), "tool_calls": [],
                       "error": None, "streamed_chars": streamed_chars,
                       "done_reason": "stream_error"}
                return
            if "parsing tool call" in (err.get("text") or "").lower():
                _metrics_note_empty(tool_parse_error=True)
            logger.warning(
                "[AgentLLM] stream başarısız (HTTP %s) → akışsız yola düşülüyor: %s",
                err.get("status"), (err.get("text") or "")[:160],
            )
            res = chat_with_tools(
                model, messages, tools, timeout, think=think, num_predict=num_predict,
            )
            res.setdefault("streamed_chars", 0)
            res["streamed_chars"] = 0
            res["type"] = "result"
            yield res
            return

        tool_calls = _parse_tool_calls({"tool_calls": tool_calls_raw})
        done_reason = done_data.get("done_reason")
        content = _strip_thinking(content_all)

        if tool_calls:
            yield {"type": "result", "content": content, "tool_calls": tool_calls,
                   "error": None, "streamed_chars": 0, "done_reason": done_reason}
            return

        if not content:
            _metrics_note_empty(content="", tool_calls=[])
            if done_reason == "length" and attempt == 1 and num_predict:
                from app.services.llm_chat_policy import bumped_num_predict
                attempt_np = bumped_num_predict(int(num_predict))
                logger.warning(
                    "[AgentLLM] done_reason=length ve görünür çıktı boş (num_predict=%s, eval=%s, "
                    "reasoning~%d kr) → tek seferlik retry num_predict=%s",
                    num_predict, done_data.get("eval_count"), thinking_chars, attempt_np,
                )
                continue
            # Başka nedenle boş (harmony 'final' kanalına geçmedi) → mevcut nudge mantığı
            content = _force_final_answer(model, messages, timeout, think=think, num_predict=num_predict)
            yield {"type": "result", "content": content, "tool_calls": [], "error": None,
                   "streamed_chars": 0, "done_reason": done_reason}
            return

        # İçerik var ve tool çağrısı yok: tutulan kısmı bırak (24 karakterden kısa yanıt)
        if hold:
            streamed_chars += len(hold)
            yield {"type": "token", "text": hold}
        if done_reason == "length":
            logger.warning(
                "[AgentLLM] yanıt num_predict tavanında kesildi (num_predict=%s, eval=%s)",
                attempt_np, done_data.get("eval_count"),
            )
        yield {"type": "result", "content": content, "tool_calls": [], "error": None,
               "streamed_chars": streamed_chars, "done_reason": done_reason}
        return
