"""Ollama istek runtime parametreleri — müşteri sunucu varsayılanına güvenilmez.

Her yerel Ollama çağrısında keep_alive ve (chat) num_ctx uygulama ayarından
açıkça gönderilir.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(\d+)([smhd])$", re.I)


def parse_keep_alive(raw: Any) -> Any:
    """-1 | 0 | saniye (int) | '10m'/'24h' | None (gönderme).

    ``default`` / ``omit`` / boş → None (alanı ekleme — nadiren).
    """
    if raw is None:
        return -1
    s = str(raw).strip()
    if not s:
        return -1
    low = s.lower()
    if low in ("default", "omit", "none"):
        return None
    if low.lstrip("-").isdigit() and s.count("-") <= 1:
        try:
            return int(s)
        except ValueError:
            return s
    if _DURATION_RE.match(s):
        return s
    return s


def get_keep_alive(*, ai_source: Any = None) -> Any:
    """Uygulama ayarı `ollama_keep_alive`; AiSource override; yoksa env; varsayılan -1."""
    if ai_source is not None:
        try:
            from app.services.llm_ai_source import resolve_ai_source
            src = resolve_ai_source(ai_source)
            if src.keep_alive is not None and str(src.keep_alive).strip() != "":
                return parse_keep_alive(src.keep_alive)
        except Exception:
            pass
    try:
        from app.services.runtime_settings import get_setting
        raw = get_setting("ollama_keep_alive")
        if raw is not None and str(raw).strip() != "":
            return parse_keep_alive(raw)
    except Exception:
        pass
    env = (os.getenv("OLLAMA_KEEP_ALIVE") or os.getenv("OLLAMA_EMBED_KEEP_ALIVE") or "-1").strip()
    return parse_keep_alive(env)


def get_num_ctx(*, ai_source: Any = None) -> int:
    """Chat options.num_ctx — etkin bütçe = min(ayar, gerçek context); kaynağa göre."""
    try:
        from app.services.llm_transport import get_effective_context_tokens
        return int(get_effective_context_tokens(ai_source=ai_source))
    except Exception:
        try:
            from app.services.llm_context_budget import (
                get_context_token_budget,
                get_gateway_hard_cap_tokens,
            )
            return max(
                2048,
                min(
                    int(get_context_token_budget(ai_source=ai_source)),
                    int(get_gateway_hard_cap_tokens(ai_source=ai_source)),
                ),
            )
        except Exception:
            return 32768


def apply_ollama_payload(
    payload: Dict[str, Any],
    *,
    include_num_ctx: bool = False,
    ai_source: Any = None,
) -> Dict[str, Any]:
    """Yerel Ollama JSON gövdesine keep_alive (+ isteğe bağlı num_ctx) ekler."""
    out = dict(payload or {})
    ka = get_keep_alive(ai_source=ai_source)
    if ka is not None:
        out["keep_alive"] = ka
    if include_num_ctx:
        opts = dict(out.get("options") or {})
        opts["num_ctx"] = get_num_ctx(ai_source=ai_source)
        out["options"] = opts
    return out


def _extract_context_length(model: Dict[str, Any]) -> Optional[int]:
    for key in ("context_length", "context"):
        v = model.get(key)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    details = model.get("details") or {}
    if isinstance(details, dict):
        for key in ("context_length", "context"):
            v = details.get(key)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
    # parameters string: "num_ctx                        8192"
    params = model.get("parameters") or details.get("parameter_size")
    if isinstance(model.get("parameters"), str):
        m = re.search(r"num_ctx\s+(\d+)", model["parameters"], re.I)
        if m:
            return int(m.group(1))
    return None


def check_ollama_health(
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Ollama /api/tags + /api/ps sağlık özeti.

    Uyarılar erişimi engellemez: ``ok`` yalnızca bağlantı/temel erişim için False olur.
    """
    from app.core.config import get_active_model, settings

    base = (base_url or settings.OLLAMA_URL or "").rstrip("/")
    want = (model or get_active_model() or settings.OLLAMA_DEFAULT_MODEL or "").strip()
    configured_ctx = get_num_ctx()
    out: Dict[str, Any] = {
        "ok": False,
        "reachable": False,
        "provider": "ollama",
        "base_url": base,
        "model": want,
        "model_loaded": False,
        "configured_num_ctx": configured_ctx,
        "loaded_context_length": None,
        "size": None,
        "size_vram": None,
        "vram_ratio": None,
        "keep_alive": get_keep_alive(),
        "warnings": [],
        "errors": [],
        "running_models": [],
    }
    if not base:
        out["errors"].append("OLLAMA_URL tanımlı değil")
        return out

    try:
        with httpx.Client(timeout=timeout) as client:
            tags = client.get(f"{base}/api/tags")
            if tags.status_code != 200:
                out["errors"].append(f"/api/tags HTTP {tags.status_code}")
                return out
            out["reachable"] = True
            tag_names = [
                (m.get("name") or "")
                for m in (tags.json().get("models") or [])
                if m.get("name")
            ]
            out["installed_models"] = tag_names
            if want and not any(
                want == n or n.startswith(want + ":") or want.startswith(n.split(":")[0])
                for n in tag_names
            ):
                out["warnings"].append(
                    f"Model '{want}' Ollama'da yüklü görünmüyor (ollama pull gerekir)"
                )

            ps = client.get(f"{base}/api/ps")
            if ps.status_code != 200:
                out["warnings"].append(f"/api/ps HTTP {ps.status_code} — çalışan model bilgisi alınamadı")
                out["ok"] = True  # bağlantı var
                return out

            running = ps.json().get("models") or []
            out["running_models"] = [
                {
                    "name": m.get("name") or m.get("model"),
                    "size": m.get("size"),
                    "size_vram": m.get("size_vram"),
                    "context_length": _extract_context_length(m),
                }
                for m in running
            ]

            match = None
            for m in running:
                name = (m.get("name") or m.get("model") or "")
                if not want or name == want or name.startswith(want) or want.startswith(name.split(":")[0]):
                    match = m
                    if want and (name == want or name.startswith(want + ":")):
                        break
            if match is None and want:
                out["warnings"].append(
                    f"Model '{want}' şu an bellekte değil (/api/ps boş veya başka model). "
                    "İlk istekte yüklenecek."
                )
            elif match is not None:
                out["model_loaded"] = True
                size = match.get("size")
                size_vram = match.get("size_vram")
                out["size"] = size
                out["size_vram"] = size_vram
                if size and size_vram is not None and int(size) > 0:
                    ratio = float(size_vram) / float(size)
                    out["vram_ratio"] = round(ratio * 100.0, 1)
                    if ratio < 0.99:
                        out["warnings"].append(
                            f"Model kısmen CPU'da (VRAM %{out['vram_ratio']:.0f}); "
                            "performans düşük olacak"
                        )
                ctx = _extract_context_length(match)
                out["loaded_context_length"] = ctx
                if ctx is not None and int(ctx) != int(configured_ctx):
                    out["warnings"].append(
                        f"Yüklü context ({ctx}) ayardaki num_ctx ({configured_ctx}) ile eşleşmiyor"
                    )

            out["ok"] = True
            return out
    except httpx.ConnectError as exc:
        out["errors"].append(f"Bağlantı hatası: {exc}")
        return out
    except httpx.TimeoutException:
        out["errors"].append("Zaman aşımı — Ollama yanıt vermedi")
        return out
    except Exception as exc:
        out["errors"].append(str(exc)[:300])
        return out


async def check_ollama_health_async(
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    import asyncio
    return await asyncio.to_thread(
        check_ollama_health, base_url=base_url, model=model, timeout=timeout,
    )
