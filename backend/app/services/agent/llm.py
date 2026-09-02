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
    """
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

        return {"content": content, "tool_calls": tool_calls, "error": None}

    except requests.exceptions.ConnectionError:
        return {"content": "", "tool_calls": [], "error": "Ollama'ya bağlanılamadı."}
    except requests.exceptions.Timeout:
        return {"content": "", "tool_calls": [], "error": "LLM zaman aşımına uğradı."}
    except Exception as e:
        logger.error(f"[AgentLLM] Hata: {e}")
        return {"content": "", "tool_calls": [], "error": str(e)}
