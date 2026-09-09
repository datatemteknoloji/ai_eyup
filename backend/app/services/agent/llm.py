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
    )


def _force_final_answer(model: str, messages: List[Dict[str, Any]], timeout: int) -> str:
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
        resp = _ollama_chat(
            {"model": model, "messages": nudge, "stream": False,
             "options": {"temperature": 0.1}},
            timeout,
        )
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
    result = _chat_with_tools_once(model, messages, tools, timeout)
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
            retry_result = _chat_with_tools_once(model, messages, tools, timeout)
            if not retry_result.get("error"):
                return retry_result
            # Retry de başarısız oldu — orijinal hatayı döndür.
            return retry_result
    return result


def _chat_with_tools_once(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    if tools:
        payload["tools"] = tools

    try:
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
                payload_no_tools = {k: v for k, v in payload.items() if k != "tools"}
                try:
                    resp2 = _ollama_chat(payload_no_tools, timeout)
                    if resp2.status_code == 200:
                        msg2 = (resp2.json().get("message", {}) or {})
                        content2 = _strip_thinking(msg2.get("content", "") or "")
                        if not content2:
                            # Retry de boş döndü (harmony "final" kanalına hiç
                            # geçmemiş olabilir) — açık talimatla bir kez daha dene.
                            content2 = _force_final_answer(model, messages, timeout)
                        # Tool çağrısı yok → ajan bunu final yanıt olarak değerlendirir.
                        return {"content": content2, "tool_calls": [], "error": None}
                except Exception as re2:
                    logger.error(f"[AgentLLM] tools'suz retry başarısız: {re2}")

            # Retry yardımcı olmadıysa veya başka bir 500 hatası
            return {"content": "", "tool_calls": [],
                    "error": f"LLM HTTP 500: {err_msg[:300]}"}

        if resp.status_code != 200:
            return {"content": "", "tool_calls": [],
                    "error": f"LLM HTTP {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        msg = data.get("message", {}) or {}
        content = _strip_thinking(msg.get("content", "") or "")
        tool_calls = _parse_tool_calls(msg)

        if not content and not tool_calls:
            # Model tool çağırmıyor (bitirdi) ama content de boş — "final"
            # kanalına geçmeden durmuş (gpt-oss/harmony'de gözlenen bir kaçak
            # senaryo). Boş yanıt kullanıcıya "(boş yanıt)" gibi anlamsız bir
            # placeholder olarak gitmesin; açık talimatla bir kez daha dene.
            content = _force_final_answer(model, messages, timeout)

        return {"content": content, "tool_calls": tool_calls, "error": None}

    except requests.exceptions.ConnectionError:
        return {"content": "", "tool_calls": [], "error": "Ollama'ya bağlanılamadı."}
    except requests.exceptions.Timeout:
        return {"content": "", "tool_calls": [], "error": "LLM zaman aşımına uğradı."}
    except Exception as e:
        logger.error("[AgentLLM] Hata: %s", e, exc_info=True)
        return {"content": "", "tool_calls": [], "error": str(e)}
