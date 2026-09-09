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
from app.services import (
    chat_cancel,
    llm_availability,
    llm_context_budget as budget,
    llm_usage,
)

logger = logging.getLogger(__name__)


def _payload_chars(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for m in messages or []:
        c = m.get("content")
        total += len(c) if isinstance(c, str) else len(str(c or ""))
    return total


def _note_prompt_tokens(prompt_chars: int, data: Dict[str, Any]) -> None:
    """Gerçek prompt token sayısıyla karakter/token tahminini kalibre eder."""
    try:
        usage = (data or {}).get("usage") or {}
        actual = (
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or (data or {}).get("prompt_eval_count")
        )
        if actual:
            budget.record_actual_usage(prompt_chars, int(actual))
    except Exception:
        pass


def _remote_chat_url() -> str:
    return settings.REMOTE_LLM_URL.rstrip("/") + "/v1/chat/completions"


def _requests_timeout(timeout: Optional[float]) -> Any:
    """(connect, read) — bağlanamayan gateway'de uzun beklemeyi keser."""
    read = 120.0 if timeout is None else float(timeout)
    return (llm_availability.CONNECT_TIMEOUT_SEC, read)


def _httpx_timeout(timeout: Optional[float]) -> httpx.Timeout:
    read = 180.0 if timeout is None else float(timeout)
    return httpx.Timeout(read, connect=llm_availability.CONNECT_TIMEOUT_SEC)


# Gateway `stream_options` (usage) alanını reddettiyse bir daha gönderilmez.
_stream_usage_supported = True


def _note_remote_status(status_code: int, body: str = "") -> None:
    """Uzak yanıtın devre kesiciye etkisi (4xx istek hatası sayılmaz)."""
    if status_code == 200:
        llm_availability.record_success()
    elif llm_availability.is_retryable_status(status_code):
        llm_availability.record_failure(f"HTTP {status_code}: {(body or '')[:200]}")


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


def _normalize_messages_openai(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ollama-tarzı transcript'i OpenAI/LiteLLM uyumlu hale getir.

    Kritik: tool_calls.function.arguments STRING olmalı (dict → 400 unmarshal).
    tool sonuçlarında tool_call_id zorunlu.
    """
    out: List[Dict[str, Any]] = []
    # name → kalan call id kuyruğu (çoklu aynı tool)
    pending_ids: Dict[str, List[str]] = {}

    for i, raw in enumerate(messages or []):
        if not isinstance(raw, dict):
            continue
        m = dict(raw)
        role = m.get("role")

        if role == "assistant" and m.get("tool_calls"):
            new_tcs = []
            for j, tc in enumerate(m.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                tc = dict(tc)
                fn = dict(tc.get("function") or {})
                args = fn.get("arguments", "{}")
                if isinstance(args, (dict, list)):
                    fn["arguments"] = json.dumps(args, ensure_ascii=False)
                elif args is None:
                    fn["arguments"] = "{}"
                else:
                    fn["arguments"] = str(args)
                name = fn.get("name") or "tool"
                tc_id = tc.get("id") or f"call_{i}_{j}_{name}"
                tc["id"] = tc_id
                tc["type"] = tc.get("type") or "function"
                tc["function"] = fn
                new_tcs.append(tc)
                pending_ids.setdefault(name, []).append(tc_id)
            m["tool_calls"] = new_tcs
            if m.get("content") == "":
                m["content"] = None
            out.append(m)
            continue

        if role == "tool":
            name = m.get("name") or ""
            tc_id = m.get("tool_call_id")
            if not tc_id:
                queue = pending_ids.get(name) or []
                if queue:
                    tc_id = queue.pop(0)
                else:
                    # isim eşleşmezse herhangi bir bekleyen id
                    for q in pending_ids.values():
                        if q:
                            tc_id = q.pop(0)
                            break
                tc_id = tc_id or f"call_orphan_{i}_{name or 'tool'}"
            nm = {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": m.get("content") if m.get("content") is not None else "",
            }
            if name:
                nm["name"] = name
            out.append(nm)
            continue

        out.append(m)
    return out


def _normalize_messages_ollama(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transcript'i native Ollama /api/chat sözleşmesine çevir.

    OpenAI'nin tersi: `tool_calls.function.arguments` OBJE olmalı. String
    gönderilirse Ollama isteği çözemez ve HTTP 400 "Value looks like object,
    but can't find closing '}' symbol" döner — araç çağrısı içeren her çok
    adımlı sohbet ilk turdan sonra bu hataya düşüyordu.
    Ayrıca native API `tool_call_id` alanını tanımaz.
    """
    out: List[Dict[str, Any]] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        m = dict(raw)

        if m.get("role") == "assistant" and m.get("tool_calls"):
            new_tcs = []
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tc = dict(tc)
                fn = dict(tc.get("function") or {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except Exception:
                        args = {}
                fn["arguments"] = args if isinstance(args, dict) else {}
                tc["function"] = fn
                tc.pop("id", None)
                tc.pop("type", None)
                new_tcs.append(tc)
            m["tool_calls"] = new_tcs
            m["content"] = m.get("content") or ""

        if m.get("role") == "tool":
            m.pop("tool_call_id", None)
            m["content"] = m.get("content") if m.get("content") is not None else ""

        out.append(m)
    return out


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
    messages, _ = budget.enforce_messages_budget(messages, label="chat_sync")
    if remote_llm_enabled():
        if llm_availability.is_open():
            # Yerel modele sessizce düşmüyoruz — istek hızlıca reddedilir.
            return _SyncChatResult(503, llm_availability.friendly_error())
        payload: Dict[str, Any] = {
            "model": _resolve_model(model),
            "messages": _normalize_messages_openai(messages),
        }
        if tools:
            payload["tools"] = tools
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        try:
            resp = requests.post(
                _remote_chat_url(), headers=_remote_headers(), json=payload,
                timeout=_requests_timeout(timeout),
                verify=remote_llm_ssl_verify(),
            )
        except Exception as e:
            logger.error(f"[LLMGateway] uzak sohbet hatası: {e}")
            llm_availability.record_failure(f"{type(e).__name__}: {e}")
            return _SyncChatResult(599, llm_availability.friendly_error(str(e)))
        _note_remote_status(resp.status_code, resp.text)
        if resp.status_code != 200:
            return _SyncChatResult(resp.status_code, resp.text)
        try:
            data = resp.json()
        except Exception:
            return _SyncChatResult(resp.status_code, resp.text)
        llm_usage.record(data)
        _note_prompt_tokens(_payload_chars(payload.get("messages") or []), data)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        return _SyncChatResult(200, resp.text, {"message": msg, "done": True})

    payload = {
        "model": model,
        "messages": _normalize_messages_ollama(messages),
        "stream": False,
    }
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    resp = requests.post(f"{settings.OLLAMA_URL.rstrip('/')}/api/chat", json=payload, timeout=timeout)
    if resp.status_code == 200:
        try:
            llm_usage.record(resp.json())
        except Exception:
            pass
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
    prompt, _ = budget.enforce_prompt_budget(prompt, system=system, label="generate_async")
    if remote_llm_enabled():
        if llm_availability.is_open():
            return {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(),
                "remote_unavailable": True,
            }
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
        try:
            async with httpx.AsyncClient(verify=remote_llm_ssl_verify()) as remote_client:
                resp = await remote_client.post(
                    _remote_chat_url(), headers=_remote_headers(), json=payload,
                    timeout=_httpx_timeout(timeout),
                )
        except Exception as e:
            logger.error("[LLMGateway] uzak generate hatası: %s", e)
            llm_availability.record_failure(f"{type(e).__name__}: {e}")
            return {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(str(e)),
                "remote_unavailable": True,
            }
        _note_remote_status(resp.status_code, resp.text)
        if resp.status_code != 200:
            return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        data = resp.json()
        llm_usage.record(data)
        _note_prompt_tokens(_payload_chars(messages), data)
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
    data = resp.json()
    llm_usage.record(data)
    return data


def generate_sync(
    *,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """generate_async'in senkron (requests tabanlı) eşleniği."""
    prompt, _ = budget.enforce_prompt_budget(prompt, system=system, label="generate_sync")
    if remote_llm_enabled():
        if llm_availability.is_open():
            return {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(),
                "remote_unavailable": True,
            }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages}
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        try:
            resp = requests.post(
                _remote_chat_url(), headers=_remote_headers(), json=payload,
                timeout=_requests_timeout(timeout),
                verify=remote_llm_ssl_verify(),
            )
        except Exception as e:
            logger.error("[LLMGateway] uzak generate_sync hatası: %s", e)
            llm_availability.record_failure(f"{type(e).__name__}: {e}")
            return {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(str(e)),
                "remote_unavailable": True,
            }
        _note_remote_status(resp.status_code, resp.text)
        if resp.status_code != 200:
            return {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        data = resp.json()
        llm_usage.record(data)
        _note_prompt_tokens(_payload_chars(messages), data)
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
    data = resp.json()
    llm_usage.record(data)
    return data


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
    global _stream_usage_supported

    prompt, _ = budget.enforce_prompt_budget(prompt, system=system, label="stream_generate")
    if remote_llm_enabled():
        if llm_availability.is_open():
            yield {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(),
                "remote_unavailable": True,
            }
            return
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: Dict[str, Any] = {"model": _resolve_model(model), "messages": messages, "stream": True}
        temp = (options or {}).get("temperature")
        if temp is not None:
            payload["temperature"] = temp
        # Token sayımı için son chunk'ta usage istenir. Desteklemeyen gateway
        # 400 dönerse alan kaldırılıp aynı istek bir kez yeniden denenir ve
        # bir daha hiç gönderilmez (sohbet bu yüzden bozulmaz).
        if _stream_usage_supported:
            payload["stream_options"] = {"include_usage": True}
        try:
            # Not: CALLER'ın client'ı (yerel Ollama için verify=True ile oluşturulmuş) yerine
            # REMOTE_LLM_VERIFY_SSL'e göre kendi kısa ömürlü client'ımızı kullanıyoruz —
            # kurumsal self-signed gateway'lerde CERTIFICATE_VERIFY_FAILED hatasını önlemek için.
            req_timeout = _httpx_timeout(timeout)
            async with httpx.AsyncClient(verify=remote_llm_ssl_verify(), timeout=req_timeout) as remote_client:
                for attempt in (1, 2):
                    async with remote_client.stream("POST", _remote_chat_url(), headers=_remote_headers(), json=payload, timeout=req_timeout) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode(errors="ignore")
                            if attempt == 1 and resp.status_code == 400 and "stream_options" in payload:
                                _stream_usage_supported = False
                                logger.warning(
                                    "[LLMGateway] gateway stream usage (stream_options) kabul etmedi, "
                                    "token sayımı olmadan devam: %s", body[:200],
                                )
                                payload.pop("stream_options", None)
                                continue
                            _note_remote_status(resp.status_code, body)
                            yield {"response": "", "done": True, "error": f"HTTP {resp.status_code}: {body[:300]}"}
                            return
                        llm_availability.record_success()
                        async for line in resp.aiter_lines():
                            # Kullanıcı iptali: `return` ile çıkmak `async with
                            # client.stream(...)` bloğunu kapatır → HTTP bağlantısı
                            # düşer ve uzak model üretimi fiilen durur (aksi hâlde
                            # iptalden sonra da token faturası işlemeye devam eder).
                            if chat_cancel.is_cancelled():
                                logger.info("[LLMGateway] uzak stream kullanıcı iptaliyle kapatıldı")
                                yield {"response": "", "done": True, "cancelled": True}
                                return
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            if data == "[DONE]":
                                yield {"response": "", "done": True}
                                return
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            llm_usage.record(chunk)
                            if chunk.get("usage"):
                                _note_prompt_tokens(_payload_chars(messages), chunk)
                            try:
                                token = chunk["choices"][0]["delta"].get("content", "")
                            except Exception:
                                continue
                            if token:
                                yield {"response": token, "done": False}
                        yield {"response": "", "done": True}
                        return
        except Exception as e:
            logger.error(f"[LLMGateway] uzak stream hatası: {e}")
            llm_availability.record_failure(f"{type(e).__name__}: {e}")
            yield {
                "response": "", "done": True,
                "error": llm_availability.friendly_error(str(e)),
                "remote_unavailable": True,
            }
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
            if chat_cancel.is_cancelled():
                logger.info("[LLMGateway] yerel stream kullanıcı iptaliyle kapatıldı")
                yield {"response": "", "done": True, "cancelled": True}
                return
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except Exception:
                continue
            if chunk.get("done"):
                llm_usage.record(chunk)
            yield chunk
            if chunk.get("done"):
                return
