from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings

_MODELS_TTL = 180  # seconds


def normalize_base_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "http://" + u
    return u.rstrip("/")


def build_direct_base(host: str, port: int) -> str:
    host = (host or "").strip()
    if not host:
        return ""
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlparse(host)
        host = parsed.hostname or host
    return f"http://{host}:{int(port)}"


def _models_cache_key(base_url: str) -> str:
    h = hashlib.sha256(base_url.encode()).hexdigest()[:16]
    return f"assistant:ollama_models:{h}"


async def list_models(base_url: str, api_key: str | None = None, timeout: float = 20.0) -> list[str]:
    base = normalize_base_url(base_url)
    if not base:
        raise ValueError("Ollama / gateway URL boş")
    cache_key = _models_cache_key(base)
    try:
        import redis

        rds = redis.from_url(get_settings().redis_url, decode_responses=True)
        cached = rds.get(cache_key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, list):
                return [str(x) for x in data]
    except Exception:
        pass

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        # Ollama native
        r = await client.get(f"{base}/api/tags")
        if r.status_code == 200:
            data = r.json()
            models = []
            for m in data.get("models") or []:
                name = m.get("name") or m.get("model")
                if name:
                    models.append(str(name))
            if models:
                out = sorted(set(models))
                try:
                    import redis

                    redis.from_url(get_settings().redis_url, decode_responses=True).setex(
                        cache_key, _MODELS_TTL, json.dumps(out)
                    )
                except Exception:
                    pass
                return out
        # OpenAI-compatible
        r2 = await client.get(f"{base}/v1/models")
        if r2.status_code == 200:
            data = r2.json()
            models = []
            for m in data.get("data") or []:
                mid = m.get("id")
                if mid:
                    models.append(str(mid))
            out = sorted(set(models))
            try:
                import redis

                redis.from_url(get_settings().redis_url, decode_responses=True).setex(
                    cache_key, _MODELS_TTL, json.dumps(out)
                )
            except Exception:
                pass
            return out
        raise ValueError(f"Model listesi alınamadı (HTTP {r.status_code}/{r2.status_code})")


async def chat_json(
    base_url: str,
    model: str,
    system: str,
    user: str,
    *,
    api_key: str | None = None,
    timeout: float = 90.0,
) -> str:
    """Returns assistant text (hopefully JSON). Tries Ollama /api/chat then OpenAI /v1/chat/completions."""
    base = normalize_base_url(base_url)
    if not base:
        raise ValueError("Ollama / gateway URL boş")
    if not model.strip():
        raise ValueError("Model seçilmedi")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        payload_ollama: dict[str, Any] = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        r = await client.post(f"{base}/api/chat", json=payload_ollama)
        if r.status_code == 200:
            data = r.json()
            msg = data.get("message") or {}
            content = msg.get("content") or data.get("response") or ""
            if content:
                return str(content)

        payload_oa = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        r2 = await client.post(f"{base}/v1/chat/completions", json=payload_oa)
        if r2.status_code == 200:
            data = r2.json()
            choices = data.get("choices") or []
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
                if content:
                    return str(content)
        detail = (r2.text or r.text or "")[:300]
        raise ValueError(f"LLM yanıtı alınamadı: {detail}")
