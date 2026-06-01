"""
LLM tool-calling katmanı (sağlayıcı-bağımsız, varsayılan Ollama).

Ollama'nın /api/chat endpoint'i `tools` parametresini ve dönüşte
message.tool_calls'u destekler (gpt-oss:20b, llama3.1, qwen2.5 vb.).

Model seçilebilir: çağıran taraf model adını verir (request.model veya get_active_model).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def chat_with_tools(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Tek tur LLM çağrısı. Dönüş:
      {
        "content": str,                 # asistan metni (varsa)
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
        "options": {"temperature": 0.2},
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL.rstrip('/')}/api/chat",
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {"content": "", "tool_calls": [], "error": f"LLM HTTP {resp.status_code}: {resp.text[:300]}"}

        data = resp.json()
        msg = data.get("message", {}) or {}
        content = msg.get("content", "") or ""

        tool_calls: List[Dict[str, Any]] = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {}) or {}
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}
            tool_calls.append({"name": fn.get("name", ""), "arguments": raw_args or {}})

        return {"content": content, "tool_calls": tool_calls, "error": None}

    except requests.exceptions.ConnectionError:
        return {"content": "", "tool_calls": [], "error": "Ollama'ya bağlanılamadı."}
    except requests.exceptions.Timeout:
        return {"content": "", "tool_calls": [], "error": "LLM zaman aşımına uğradı."}
    except Exception as e:
        logger.error(f"[AgentLLM] Hata: {e}")
        return {"content": "", "tool_calls": [], "error": str(e)}
