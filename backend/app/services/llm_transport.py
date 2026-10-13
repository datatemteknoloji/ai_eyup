"""LLM taşıma katmanı — REMOTE_LLM için Ollama native vs OpenAI-uyumlu.

``llm_transport_mode``: auto | ollama | openai
- auto: GET {REMOTE_LLM_URL}/api/version yanıt verirse native Ollama
- ollama / openai: elle zorlama

Keşfedilen model context uzunluğu (``/api/ps``, ``/api/show``, ``/v1/models``)
etkin bütçeyi sınırlar: min(ayar, gerçek context).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

TRANSPORT_AUTO = "auto"
TRANSPORT_OLLAMA = "ollama"
TRANSPORT_OPENAI = "openai"
_VALID_MODES = frozenset({TRANSPORT_AUTO, TRANSPORT_OLLAMA, TRANSPORT_OPENAI})

_PROBE_TTL_SEC = 60.0
_DISCOVER_TTL_SEC = 120.0

_lock = threading.Lock()
_probe_cache: Dict[str, Any] = {"at": 0.0, "url": "", "is_ollama": False}
# key → {"at": float, "ctx": Optional[int]}
_discover_by_key: Dict[str, Dict[str, Any]] = {}


def get_transport_mode(*, ai_source: Any = None) -> str:
    if ai_source is not None:
        try:
            from app.services.llm_ai_source import resolve_ai_source
            src = resolve_ai_source(ai_source)
            if src.transport_mode:
                raw = str(src.transport_mode).strip().lower()
                if raw in _VALID_MODES:
                    return raw
        except Exception:
            pass
    try:
        from app.services.runtime_settings import get_setting
        raw = str(get_setting("llm_transport_mode") or TRANSPORT_AUTO).strip().lower()
        if raw in _VALID_MODES:
            return raw
    except Exception:
        pass
    return TRANSPORT_AUTO


def clear_transport_caches() -> None:
    with _lock:
        _probe_cache.update({"at": 0.0, "url": "", "is_ollama": False})
        _discover_by_key.clear()


def probe_ollama_version(
    base_url: str,
    *,
    timeout: float = 2.0,
    verify: bool = True,
) -> Optional[Dict[str, Any]]:
    """GET {base}/api/version — Ollama ise dict, değilse None."""
    base = (base_url or "").rstrip("/")
    if not base:
        return None
    try:
        with httpx.Client(timeout=timeout, verify=verify) as client:
            resp = client.get(f"{base}/api/version")
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not isinstance(data, dict):
                return None
            # Ollama: {"version": "0.x.x"}; sahte 200 JSON'ları elemek için version şart
            if "version" in data:
                return data
            return None
    except Exception as exc:
        logger.debug("Ollama /api/version probe failed for %s: %s", base, exc)
        return None


def remote_base_url(*, ai_source: Any = None) -> str:
    from app.core.config import settings

    if ai_source is not None:
        try:
            from app.services.llm_ai_source import resolve_ai_source
            src = resolve_ai_source(ai_source)
            if src.remote_llm_url:
                return str(src.remote_llm_url).rstrip("/")
        except Exception:
            pass
    return (settings.REMOTE_LLM_URL or "").rstrip("/")


def is_remote_ollama(*, force_refresh: bool = False, ai_source: Any = None) -> bool:
    """REMOTE_LLM adresi native Ollama mı? (mod + /api/version)."""
    from app.core.config import remote_llm_enabled, remote_llm_ssl_verify

    if not remote_llm_enabled():
        return False
    mode = get_transport_mode(ai_source=ai_source)
    if mode == TRANSPORT_OLLAMA:
        return True
    if mode == TRANSPORT_OPENAI:
        return False

    base = remote_base_url(ai_source=ai_source)
    if not base:
        return False
    now = time.monotonic()
    with _lock:
        if (
            not force_refresh
            and _probe_cache["url"] == base
            and (now - float(_probe_cache["at"])) < _PROBE_TTL_SEC
        ):
            return bool(_probe_cache["is_ollama"])

    info = probe_ollama_version(base, verify=remote_llm_ssl_verify())
    is_ol = info is not None
    with _lock:
        _probe_cache.update({"at": now, "url": base, "is_ollama": is_ol})
    return is_ol


def resolve_active_transport(*, ai_source: Any = None) -> str:
    """Aktif taşıma: 'ollama' | 'openai' | 'local_ollama'."""
    from app.core.config import remote_llm_enabled

    if not remote_llm_enabled():
        return "local_ollama"
    return (
        TRANSPORT_OLLAMA
        if is_remote_ollama(ai_source=ai_source)
        else TRANSPORT_OPENAI
    )


def ollama_request_base(*, ai_source: Any = None) -> str:
    """Native Ollama istek tabanı — REMOTE Ollama veya yerel OLLAMA_URL."""
    from app.core.config import settings

    if ai_source is not None:
        try:
            from app.services.llm_ai_source import resolve_ai_source
            src = resolve_ai_source(ai_source)
            if is_remote_ollama(ai_source=src) and src.remote_llm_url:
                return str(src.remote_llm_url).rstrip("/")
            if src.ollama_url and not is_remote_ollama(ai_source=src):
                return str(src.ollama_url).rstrip("/")
        except Exception:
            pass
    if is_remote_ollama(ai_source=ai_source):
        return remote_base_url(ai_source=ai_source)
    return (settings.OLLAMA_URL or "").rstrip("/")


def _extract_ctx_from_show(data: Dict[str, Any]) -> Optional[int]:
    for key in ("context_length", "context"):
        v = data.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    details = data.get("details") or {}
    if isinstance(details, dict):
        for key in ("context_length", "context", "parameter_size"):
            v = details.get(key)
            if key == "parameter_size":
                continue
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
    info = data.get("model_info") or data.get("modelinfo") or {}
    if isinstance(info, dict):
        for k, v in info.items():
            kl = str(k).lower()
            if "context_length" in kl or kl.endswith(".context_length"):
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
    return None


def _discover_ollama_context(base: str, model: str, *, verify: bool = True) -> Optional[int]:
    from app.services.ollama_runtime import _extract_context_length

    if not base:
        return None
    try:
        with httpx.Client(timeout=5.0, verify=verify) as client:
            if model:
                ps = client.get(f"{base}/api/ps")
                if ps.status_code == 200:
                    for m in ps.json().get("models") or []:
                        name = (m.get("name") or m.get("model") or "")
                        if (
                            name == model
                            or name.startswith(model)
                            or model.startswith(name.split(":")[0])
                        ):
                            ctx = _extract_context_length(m)
                            if ctx:
                                return ctx
                show = client.post(f"{base}/api/show", json={"name": model})
                if show.status_code == 200:
                    ctx = _extract_ctx_from_show(show.json() or {})
                    if ctx:
                        return ctx
    except Exception as exc:
        logger.debug("Ollama context discover failed: %s", exc)
    return None


def _discover_openai_context(base: str, model: str, *, verify: bool = True) -> Optional[int]:
    from app.core.config import settings

    if not base:
        return None
    try:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        key = (settings.REMOTE_LLM_API_KEY or "").strip()
        vk = (settings.REMOTE_LLM_VIRTUAL_KEY or "").strip()
        if key:
            headers["Authorization"] = key
        if vk:
            headers["x-bf-vk"] = vk
        with httpx.Client(timeout=5.0, verify=verify) as client:
            resp = client.get(f"{base}/v1/models", headers=headers)
            if resp.status_code != 200:
                return None
            want = (model or settings.REMOTE_LLM_MODEL or "").strip()
            for m in resp.json().get("data") or []:
                if not isinstance(m, dict):
                    continue
                mid = (m.get("id") or m.get("name") or "").strip()
                if want and mid and mid != want and not mid.startswith(want):
                    continue
                for key in (
                    "context_length",
                    "context_window",
                    "max_model_len",
                    "max_tokens",
                ):
                    v = m.get(key)
                    if v is not None:
                        try:
                            return int(v)
                        except (TypeError, ValueError):
                            pass
                if want and mid == want:
                    break
    except Exception as exc:
        logger.debug("OpenAI /v1/models context discover failed: %s", exc)
    return None


def _source_id(ai_source: Any = None) -> str:
    try:
        from app.services.llm_ai_source import DEFAULT_AI_SOURCE_ID, resolve_ai_source
        if ai_source is None:
            return DEFAULT_AI_SOURCE_ID
        return resolve_ai_source(ai_source).id
    except Exception:
        return "default"


def discover_model_context_length(
    *,
    model: Optional[str] = None,
    force_refresh: bool = False,
    ai_source: Any = None,
) -> Optional[int]:
    """Gerçek model context penceresi; yoksa None (ayar hard-cap kullanılır)."""
    from app.core.config import get_active_model, remote_llm_enabled, remote_llm_ssl_verify, settings
    from app.services.llm_ai_source import resolve_ai_source

    src = resolve_ai_source(ai_source)
    want = (model or src.model or get_active_model() or settings.OLLAMA_DEFAULT_MODEL or "").strip()
    transport = resolve_active_transport(ai_source=src)
    base_for_key = (
        remote_base_url(ai_source=src)
        if remote_llm_enabled()
        else (src.ollama_url or settings.OLLAMA_URL or "")
    )
    cache_key = f"{src.id}|{transport}|{want}|{base_for_key}"
    now = time.monotonic()
    with _lock:
        entry = _discover_by_key.get(cache_key)
        if (
            not force_refresh
            and entry
            and (now - float(entry["at"])) < _DISCOVER_TTL_SEC
        ):
            return entry.get("ctx")

    ctx: Optional[int] = None
    if transport in ("local_ollama", TRANSPORT_OLLAMA):
        base = ollama_request_base(ai_source=src)
        verify = remote_llm_ssl_verify() if transport == TRANSPORT_OLLAMA else True
        ctx = _discover_ollama_context(base, want, verify=verify)
    elif transport == TRANSPORT_OPENAI:
        ctx = _discover_openai_context(
            remote_base_url(ai_source=src), want, verify=remote_llm_ssl_verify(),
        )

    with _lock:
        _discover_by_key[cache_key] = {"at": now, "ctx": ctx}
    return ctx


def get_discovered_context_length(*, ai_source: Any = None) -> Optional[int]:
    """Önbellekteki keşif; yoksa None (ağ çağrısı yok)."""
    sid = _source_id(ai_source)
    now = time.monotonic()
    with _lock:
        for key, entry in _discover_by_key.items():
            if not key.startswith(f"{sid}|"):
                continue
            if (now - float(entry["at"])) < _DISCOVER_TTL_SEC:
                return entry.get("ctx")
    return None


def get_real_context_ceiling(
    *,
    model: Optional[str] = None,
    allow_discover: bool = False,
    ai_source: Any = None,
) -> int:
    """Gerçek tavan = min(hard_cap ayarı, keşfedilen) veya yalnız hard_cap.

    ``allow_discover=False`` (varsayılan): yalnız önbellek — hot path'te ağ yok.
    """
    from app.services.llm_context_budget import get_gateway_hard_cap_tokens

    hard = max(2048, int(get_gateway_hard_cap_tokens(ai_source=ai_source)))
    disc = get_discovered_context_length(ai_source=ai_source)
    if disc is None and allow_discover:
        disc = discover_model_context_length(model=model, ai_source=ai_source)
    if disc and disc > 0:
        return max(2048, min(hard, int(disc)))
    return hard


def get_effective_context_tokens(
    *,
    model: Optional[str] = None,
    allow_discover: bool = True,
    ai_source: Any = None,
) -> int:
    """Etkin bütçe = min(ayar bütçesi, gerçek context tavanı) — kaynağa göre."""
    from app.services.llm_context_budget import get_context_token_budget

    desired = max(2048, int(get_context_token_budget(ai_source=ai_source)))
    real = get_real_context_ceiling(
        model=model, allow_discover=allow_discover, ai_source=ai_source,
    )
    return max(2048, min(desired, real))


def build_llm_health(*, model: Optional[str] = None, ai_source: Any = None) -> Dict[str, Any]:
    """Platform / Ayarlar sağlık kartı — taşıma + etkin bütçe + Ollama /api/ps."""
    from app.core.config import remote_llm_enabled
    from app.services.llm_ai_source import resolve_ai_source
    from app.services.ollama_runtime import check_ollama_health, get_keep_alive
    from app.services.llm_context_budget import (
        get_context_token_budget,
        get_gateway_hard_cap_tokens,
    )

    src = resolve_ai_source(ai_source)
    transport = resolve_active_transport(ai_source=src)
    mode = get_transport_mode(ai_source=src)
    desired = get_context_token_budget(ai_source=src)
    hard = get_gateway_hard_cap_tokens(ai_source=src)
    disc = discover_model_context_length(model=model, force_refresh=True, ai_source=src)
    effective = get_effective_context_tokens(model=model, ai_source=src)

    base_meta = {
        "source_id": src.id,
        "transport_mode": mode,
        "transport": transport,
        "configured_budget": desired,
        "configured_hard_cap": hard,
        "discovered_context_length": disc,
        "effective_num_ctx": effective,
        "keep_alive": get_keep_alive(ai_source=src),
    }

    if transport == TRANSPORT_OPENAI:
        return {
            **base_meta,
            "ok": True,
            "reachable": True,
            "provider": "remote_openai",
            "message": (
                "REMOTE_LLM OpenAI-uyumlu taşıma. "
                f"Etkin context bütçesi: {effective} "
                f"(ayar {desired}, tavan {hard}"
                + (f", keşif {disc}" if disc else "")
                + ")."
            ),
            "warnings": [],
            "errors": [],
            "configured_num_ctx": effective,
            "loaded_context_length": disc,
        }

    base = ollama_request_base(ai_source=src)
    health = check_ollama_health(base_url=base, model=model)
    health.update(base_meta)
    health["provider"] = "remote_ollama" if transport == TRANSPORT_OLLAMA else "ollama"
    health["configured_num_ctx"] = effective
    if disc is not None:
        health["discovered_context_length"] = disc
        if health.get("loaded_context_length") is None:
            health["loaded_context_length"] = disc
    # Eski uyarı: yüklü ≠ ayar → etkin bütçe ile karşılaştır
    warnings = list(health.get("warnings") or [])
    health["warnings"] = [
        w for w in warnings
        if "num_ctx" not in w and "ayardaki" not in w
    ]
    loaded = health.get("loaded_context_length")
    if loaded is not None and int(loaded) < int(effective):
        health["warnings"].append(
            f"Yüklü context ({loaded}) etkin bütçeden ({effective}) küçük; "
            "model yeniden yüklenebilir"
        )
    elif loaded is not None and int(loaded) != int(effective):
        health["warnings"].append(
            f"Yüklü context ({loaded}) ≠ etkin bütçe ({effective})"
        )
    if remote_llm_enabled() and transport == TRANSPORT_OLLAMA:
        health["message"] = (
            f"REMOTE_LLM native Ollama ({base}). "
            f"Etkin bütçe {effective} = min(ayar {desired}, gerçek {disc or hard})."
        )
    return health
