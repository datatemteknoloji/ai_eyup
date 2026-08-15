"""
LLM Gateway — yerel Ollama ile uzak, OpenAI-uyumlu bir sağlayıcı (örn. Bifrost) arasında
tek bir arayüz üzerinden yönlendirme yapar.

settings.REMOTE_LLM_ENABLED=true ve URL ayarlıysa, TÜM chat/agent/analiz
çağrıları REMOTE_LLM_URL'deki OpenAI-uyumlu `/v1/chat/completions` endpoint'ine gider;
aksi halde davranış değişmeden yerel Ollama'ya (OLLAMA_URL) gider. API Key / Virtual Key
isteğe bağlıdır.

Bu modül, çağıran kodun mevcut Ollama şekilli beklentilerini (generate: {"response","done"},
chat: {"message": {"content","tool_calls"}}) korur — böylece tüm call-site'lar minimal
değişiklikle bu modülü kullanabilir.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import requests

from app.core.config import settings, remote_llm_enabled, remote_llm_ssl_verify

logger = logging.getLogger(__name__)


def _remote_chat_url() -> str:
    return settings.REMOTE_LLM_URL.rstrip("/") + "/v1/chat/completions"


def _remote_headers(
    api_key: Optional[str] = None,
    virtual_key: Optional[str] = None,
) -> Dict[str, str]:
    """Uzak gateway header'ları — iki yol birlikte veya ayrı kullanılabilir.

    Bifrost (güncel / sıkı VK): yalnızca Virtual Key → ``x-bf-vk: sk-bf-…``
    (Authorization gönderilmez; curl ile aynı şekil).

    Eski / Authorization yolu: yalnızca API Key → ``Authorization`` (Bearer yok).

    İkisi doluysa her iki header da gider (gateway auth + VK senaryosu).
    İkisi boşsa yalnızca Content-Type kalır — çağıran 401/400 görür.
    """
    key = (api_key if api_key is not None else settings.REMOTE_LLM_API_KEY) or ""
    vk = (virtual_key if virtual_key is not None else settings.REMOTE_LLM_VIRTUAL_KEY) or ""
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if key.strip():
        headers["Authorization"] = key.strip()
    if vk.strip():
        headers["x-bf-vk"] = vk.strip()
    return headers


def _resolve_model(requested_model: Optional[str]) -> str:
    """Uzak sağlayıcıda sabit bir model tanımlıysa onu kullan (farklı model adı uzayları
    karışmasın diye) — yoksa çağıranın istediği modeli oldugu gibi dener."""
    return settings.REMOTE_LLM_MODEL or requested_model or ""


def active_model_label(requested_model: Optional[str] = None) -> str:
    """UI/loglarda gösterilecek 'şu an kullanılan model' etiketi."""
    if remote_llm_enabled():
        return _resolve_model(requested_model) or "(uzak model)"
    return requested_model or settings.OLLAMA_DEFAULT_MODEL


def resolve_model_for_tier(
    tier: str,
    requested_model: Optional[str] = None,
) -> tuple:
    """Unified model tier: (model_name, tier_used).

    tier: \"fast\" | \"strong\"
    - fast: chat_model_fast doluysa onu kullan; boşsa strong yoluna düş (regresyonsuz)
    - strong: request/UI modeli varsa onu koru; yoksa chat_model_strong; o da boşsa requested
    """
    try:
        from app.services import runtime_settings
        fast = (runtime_settings.get_str("chat_model_fast") or "").strip()
        strong_cfg = (runtime_settings.get_str("chat_model_strong") or "").strip()
    except Exception:
        fast, strong_cfg = "", ""

    requested = (requested_model or "").strip()
    t = (tier or "strong").strip().lower()

    if t == "fast" and fast:
        return fast, "fast"

    if requested:
        return requested, "strong"
    if strong_cfg:
        return strong_cfg, "strong"
    return requested or settings.OLLAMA_DEFAULT_MODEL, "strong"


# ─────────────────────────────────────────────────────────────────────────
# Senkron sohbet (agent tool-calling, guard) — requests tabanlı
# ─────────────────────────────────────────────────────────────────────────

class _SyncChatResult:
    """requests.Response benzeri ince sarmalayıcı: .status_code, .text, .json()"""
    def __init__(self, status_code: int, text: str, data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self.text = text
        self._data = data

    def json(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        return json.loads(self.text)


def chat_sync(
    model: str,
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: int = 120,
) -> _SyncChatResult:
    """
    Ollama /api/chat ile aynı sözleşmeye sahip senkron sohbet çağrısı.
    Dönüş: .status_code, .json() -> {"message": {"content", "tool_calls"?}}
    """
    if remote_llm_enabled():
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages}
        if tools:
            payload["tools"] = tools
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        try:
            resp = requests.post(
                _remote_chat_url(), headers=_remote_headers(), json=payload, timeout=timeout,
                verify=remote_llm_ssl_verify(),
            )
        except Exception as e:
            logger.error(f"[LLMGateway] uzak sohbet hatası: {e}")
            return _SyncChatResult(599, str(e))
        if resp.status_code != 200:
            return _SyncChatResult(resp.status_code, resp.text)
        try:
            data = resp.json()
        except Exception:
            return _SyncChatResult(resp.status_code, resp.text)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        return _SyncChatResult(200, resp.text, {"message": msg, "done": True})

    payload = {"model": model, "messages": messages, "stream": False}
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    resp = requests.post(f"{settings.OLLAMA_URL.rstrip('/')}/api/chat", json=payload, timeout=timeout)
    return resp


# ─────────────────────────────────────────────────────────────────────────
# Asenkron, tek seferlik tamamlama (arka plan analiz görevleri) — httpx tabanlı
# ─────────────────────────────────────────────────────────────────────────

async def generate_async(
    client: httpx.AsyncClient,
    *,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Ollama /api/generate (stream=False) ile aynı sözleşmeye sahip async çağrı.
    Dönüş: {"response": str, "done": True}
    """
    if remote_llm_enabled():
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages}
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        # Not: burada CALLER'ın (yerel Ollama için oluşturulmuş, verify=True) client'ı değil,
        # REMOTE_LLM_VERIFY_SSL'e göre kendi kısa ömürlü client'ımızı kullanıyoruz — kurumsal
        # self-signed gateway'lerde CERTIFICATE_VERIFY_FAILED hatasını önlemek için.
        async with httpx.AsyncClient(verify=remote_llm_ssl_verify()) as remote_client:
            resp = await remote_client.post(_remote_chat_url(), headers=_remote_headers(), json=payload, timeout=timeout)
        if resp.status_code != 200:
            return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message", {}) or {}).get("content", "")
        return {"response": text, "done": True}

    payload = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    resp = await client.post(f"{settings.OLLAMA_URL.rstrip('/')}/api/generate", json=payload, timeout=timeout)
    if resp.status_code != 200:
        return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    return resp.json()


def generate_sync(
    *,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """generate_async'in senkron (requests tabanlı) eşleniği."""
    if remote_llm_enabled():
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages}
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        resp = requests.post(
            _remote_chat_url(), headers=_remote_headers(), json=payload, timeout=timeout,
            verify=remote_llm_ssl_verify(),
        )
        if resp.status_code != 200:
            return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message", {}) or {}).get("content", "")
        return {"response": text, "done": True}

    payload = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    resp = requests.post(f"{settings.OLLAMA_URL.rstrip('/')}/api/generate", json=payload, timeout=timeout)
    if resp.status_code != 200:
        return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────
# Asenkron streaming (kullanıcıya SSE ile akıtılan chat yanıtları)
# ─────────────────────────────────────────────────────────────────────────

async def stream_generate(
    client: httpx.AsyncClient,
    *,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Ollama /api/generate (stream=True) ile aynı sözleşmeye sahip async üreteç.
    Her adımda {"response": <delta metin>, "done": bool} verir.
    """
    if remote_llm_enabled():
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages, "stream": True}
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        try:
            # Not: CALLER'ın client'ı (yerel Ollama için verify=True ile oluşturulmuş) yerine
            # REMOTE_LLM_VERIFY_SSL'e göre kendi kısa ömürlü client'ımızı kullanıyoruz —
            # kurumsal self-signed gateway'lerde CERTIFICATE_VERIFY_FAILED hatasını önlemek için.
            req_timeout = timeout if timeout is not None else 180.0
            async with httpx.AsyncClient(verify=remote_llm_ssl_verify(), timeout=req_timeout) as remote_client:
                async with remote_client.stream("POST", _remote_chat_url(), headers=_remote_headers(), json=payload, timeout=req_timeout) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {body.decode(errors='ignore')[:300]}"}
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            yield {"response": "", "done": True}
                            return
                        try:
                            chunk = json.loads(data)
                            token = chunk["choices"][0]["delta"].get("content", "")
                        except Exception:
                            continue
                        if token:
                            yield {"response": token, "done": False}
                    yield {"response": "", "done": True}
        except Exception as e:
            logger.error(f"[LLMGateway] uzak stream hatası: {e}")
            yield {"response": "", "done": True, "error": str(e)}
        return

    payload = {"model": model, "prompt": prompt, "stream": True}
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options
    async with client.stream("POST", f"{settings.OLLAMA_URL.rstrip('/')}/api/generate", json=payload, timeout=timeout) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            yield {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {body.decode(errors='ignore')[:300]}"}
            return
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue
            yield chunk
            if chunk.get("done"):
                return
