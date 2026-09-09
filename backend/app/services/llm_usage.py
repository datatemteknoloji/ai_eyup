"""LLM token tüketimi — istek başına toplayıcı (admin göstergesi).

Sağlayıcıdan gelen gerçek `usage` alanları toplanır:
  - OpenAI uyumlu (Bifrost/LiteLLM): prompt_tokens / completion_tokens / total_tokens
  - Ollama native: prompt_eval_count / eval_count

Araç çağrısı (tool-calling) döngüsünde bir soru için birden fazla model
çağrısı yapılır; burada hepsi tek bir toplamda birikir. Sağlayıcı usage
vermezse alan boş kalır — tahmin üretilmez (yanıltıcı sayı gösterilmez).
"""
from __future__ import annotations

import contextvars
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)

_current: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "ainew_llm_usage", default=None
)


def start() -> Any:
    """Yeni bir toplama kapsamı başlat. Dönen token `stop()` için saklanır."""
    return _current.set({"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "reported": 0})


def stop(token: Any) -> None:
    try:
        _current.reset(token)
    except Exception:
        pass


def _as_int(value: Any) -> int:
    try:
        n = int(value)
        return n if n > 0 else 0
    except (TypeError, ValueError):
        return 0


def parse_usage(data: Any) -> Optional[Dict[str, int]]:
    """Sağlayıcı yanıtından prompt/completion token sayısını çıkar."""
    if not isinstance(data, dict):
        return None

    usage = data.get("usage")
    if isinstance(usage, dict):
        prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
        completion = _as_int(usage.get("completion_tokens") or usage.get("output_tokens"))
        if prompt or completion:
            return {"prompt_tokens": prompt, "completion_tokens": completion}

    # Ollama native
    prompt = _as_int(data.get("prompt_eval_count"))
    completion = _as_int(data.get("eval_count"))
    if prompt or completion:
        return {"prompt_tokens": prompt, "completion_tokens": completion}
    return None


def record(data: Any) -> None:
    """Model yanıtını (dict) ver; usage varsa aktif kapsama eklenir."""
    acc = _current.get()
    if acc is None:
        return
    acc["calls"] = int(acc.get("calls") or 0) + 1
    parsed = parse_usage(data)
    if not parsed:
        return
    acc["prompt_tokens"] += parsed["prompt_tokens"]
    acc["completion_tokens"] += parsed["completion_tokens"]
    acc["reported"] = int(acc.get("reported") or 0) + 1


def snapshot() -> Optional[Dict[str, Any]]:
    """Aktif kapsamın toplamı. Hiç usage bildirilmediyse None."""
    acc = _current.get()
    if not acc or not acc.get("reported"):
        return None
    prompt = int(acc.get("prompt_tokens") or 0)
    completion = int(acc.get("completion_tokens") or 0)
    reported = int(acc.get("reported") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        # `calls` = usage bildiren model YANITI sayısı (tool-calling turunda
        # birden fazla olur). Akış modunda her SSE parçası record() çağırır;
        # ham parça sayısı kullanıcıya "model çağrısı" gibi gösterilmemeli.
        "calls": reported,
        "reported_calls": reported,
        "records": int(acc.get("calls") or 0),
    }


def _is_done_event(chunk: Any) -> bool:
    if not isinstance(chunk, str) or "data: " not in chunk:
        return False
    try:
        payload = json.loads(chunk.split("data: ", 1)[1].strip())
    except Exception:
        return False
    return bool(isinstance(payload, dict) and payload.get("done"))


async def sse_inject_before_done(agen: AsyncIterator[Any]) -> AsyncIterator[Any]:
    """SSE akışına `done`'dan hemen önce tek bir `usage` olayı ekler.

    Sohbet yolunda `done` birden çok yerde üretildiği için enjeksiyon tek
    merkezde yapılır; usage yoksa hiçbir şey eklenmez.
    """
    injected = False
    async for chunk in agen:
        if not injected and _is_done_event(chunk):
            injected = True
            snap = snapshot()
            if snap:
                yield "data: " + json.dumps({"usage": snap}, ensure_ascii=False) + "\n\n"
        yield chunk
