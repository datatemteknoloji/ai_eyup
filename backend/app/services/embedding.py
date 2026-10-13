"""
Embedding servisi — RAG için metin vektörleme.

Öncelik:
  1) EMBEDDING_URL veya OLLAMA_URL → Ollama /api/embed (truncate=false) → /api/embeddings
  2) Aynı tabanda OpenAI-uyumlu /v1/embeddings
  3) REMOTE_LLM açıkysa REMOTE_LLM_URL /v1/embeddings (aynı model adı; veri çıkışı loglanır)

Varsayılan model: nomic-embed-text (768 boyut). Boyut uyuşmazlığında pad/kırp yok.
Yedek zincirinde farklı modele düşülürse vektör kullanılmaz (çağıran FTS'e geçer).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import remote_llm_enabled, remote_llm_ssl_verify, settings

logger = logging.getLogger(__name__)

OLLAMA_EMBED_TIMEOUT = float(os.getenv("OLLAMA_EMBED_TIMEOUT", "180"))
EMBED_CONCURRENCY = max(1, min(int(os.getenv("OLLAMA_EMBED_CONCURRENCY", "4")), 32))
EXPECTED_EMBED_DIM = 768

_last_embed_error: Optional[str] = None
_last_embed_meta: Dict[str, Any] = {}


@dataclass
class EmbedResult:
    vector: Optional[List[float]] = None
    model: str = ""
    dim: int = 0
    source: str = "failed"  # ollama_embed | ollama_embeddings | ollama_v1 | remote_v1 | failed
    error: Optional[str] = None
    usable_for_vector_search: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)


def embed_keep_alive() -> Any:
    from app.services.ollama_runtime import get_keep_alive
    return get_keep_alive()


def _with_keep_alive(payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.ollama_runtime import apply_ollama_payload
    return apply_ollama_payload(payload, include_num_ctx=False)


def embed_concurrency() -> int:
    try:
        from app.services import runtime_settings
        return max(1, min(32, int(runtime_settings.get_int("rag_embed_concurrency"))))
    except Exception:
        return EMBED_CONCURRENCY


def get_last_embed_error() -> Optional[str]:
    return _last_embed_error


def get_last_embed_meta() -> Dict[str, Any]:
    return dict(_last_embed_meta)


def _set_last_error(msg: str) -> None:
    global _last_embed_error
    _last_embed_error = (msg or "")[:800]


def _set_last_meta(meta: Dict[str, Any]) -> None:
    global _last_embed_meta
    _last_embed_meta = dict(meta or {})


def _zero_vec(dim: int = EXPECTED_EMBED_DIM) -> List[float]:
    return [0.0] * dim


def embed_base_url() -> str:
    return (
        (getattr(settings, "EMBEDDING_URL", None) or "").strip()
        or (settings.OLLAMA_URL or "").strip()
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def embed_model_name() -> str:
    """Yapılandırılmış embed modeli (yerel birincil)."""
    return (
        (settings.OLLAMA_EMBED_MODEL or "").strip()
        or "nomic-embed-text"
    )


def remote_embed_model_name() -> str:
    return (
        (getattr(settings, "REMOTE_LLM_EMBED_MODEL", None) or "").strip()
        or embed_model_name()
    )


def _parse_embedding_payload(data: dict) -> Optional[List[float]]:
    if not isinstance(data, dict):
        return None
    emb = data.get("embedding")
    if isinstance(emb, list) and emb:
        return emb
    embs = data.get("embeddings")
    if isinstance(embs, list) and embs:
        first = embs[0]
        if isinstance(first, list) and first:
            return first
        if isinstance(first, dict):
            inner = first.get("embedding")
            if isinstance(inner, list) and inner:
                return inner
    data_list = data.get("data")
    if isinstance(data_list, list) and data_list:
        first = data_list[0]
        if isinstance(first, dict):
            inner = first.get("embedding")
            if isinstance(inner, list) and inner:
                return inner
    return None


def _validate_dim(vec: Optional[List[float]], *, expected: int = EXPECTED_EMBED_DIM) -> Tuple[Optional[List[float]], Optional[str]]:
    if not vec:
        return None, "boş embedding"
    if len(vec) != int(expected):
        msg = f"embedding boyut uyuşmazlığı: got={len(vec)} expected={expected} (pad/kırp yok)"
        logger.error("RAG embed: %s", msg)
        return None, msg
    return vec, None


def _remediation_hint(base: str, model: str) -> str:
    return (
        f"RAG embedding için Ollama erişimi gerekir. "
        f"Sunucuda: `curl -s {base}/api/tags` ve `ollama pull {model}`. "
        f"Compose ile: `docker compose --profile ollama -f docker-compose.prod.yml up -d ollama` "
        f"sonra `docker exec server_management_ollama ollama pull {model}`. "
        f"OLLAMA_URL / EMBEDDING_URL (.env) backend'in gördüğü adresi göstermeli."
    )


async def _post_ollama_embed_api(
    client: httpx.AsyncClient, base: str, model: str, prompt: str
) -> Tuple[Optional[List[float]], Optional[str]]:
    """Öncelikli: /api/embed + truncate=false — uzun girdi hata verir, sessiz kesilmez."""
    try:
        payload = _with_keep_alive({
            "model": model,
            "input": prompt,
            "truncate": False,
        })
        r = await client.post(f"{base}/api/embed", json=payload)
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            vec, err = _validate_dim(vec)
            if vec:
                return vec, None
            return None, err or f"{base}/api/embed: boş embedding"
        body = (r.text or "")[:240]
        # Eski Ollama truncate alanını tanımayabilir — bir kez truncate'siz dene
        if r.status_code == 400 and "truncate" in body.lower():
            payload2 = _with_keep_alive({"model": model, "input": prompt})
            r2 = await client.post(f"{base}/api/embed", json=payload2)
            if r2.status_code == 200:
                vec = _parse_embedding_payload(r2.json())
                vec, err = _validate_dim(vec)
                if vec:
                    return vec, None
                return None, err or f"{base}/api/embed: boş embedding"
            return None, f"HTTP {r2.status_code} {base}/api/embed: {(r2.text or '')[:200]}"
        if r.status_code in (404, 405):
            return None, f"HTTP {r.status_code} {base}/api/embed"
        return None, f"HTTP {r.status_code} {base}/api/embed: {body}"
    except Exception as e:
        return None, f"{base}/api/embed erişilemedi ({type(e).__name__}: {e})"


async def _post_ollama_embeddings_legacy(
    client: httpx.AsyncClient, base: str, model: str, prompt: str
) -> Tuple[Optional[List[float]], Optional[str]]:
    try:
        r = await client.post(
            f"{base}/api/embeddings",
            json=_with_keep_alive({"model": model, "prompt": prompt}),
        )
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            vec, err = _validate_dim(vec)
            if vec:
                return vec, None
            return None, err or f"{base}/api/embeddings: boş embedding"
        return None, f"HTTP {r.status_code} {base}/api/embeddings: {(r.text or '')[:200]}"
    except Exception as e:
        return None, f"{base}/api/embeddings erişilemedi ({type(e).__name__}: {e})"


async def _post_openai_embeddings(
    client: httpx.AsyncClient,
    base: str,
    model: str,
    prompt: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    ollama_keep_alive: bool = False,
) -> Tuple[Optional[List[float]], Optional[str]]:
    url = f"{base.rstrip('/')}/v1/embeddings"
    body: Dict[str, Any] = {"model": model, "input": prompt}
    if ollama_keep_alive:
        body = _with_keep_alive(body)
    try:
        r = await client.post(url, json=body, headers=headers or {})
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            vec, err = _validate_dim(vec)
            if vec:
                return vec, None
            return None, err or f"{url}: boş embedding"
        return None, f"HTTP {r.status_code} {url}: {(r.text or '')[:200]}"
    except Exception as e:
        return None, f"{url} erişilemedi ({type(e).__name__}: {e})"


async def embed_text(text: str) -> EmbedResult:
    """Tek metin embed — model/kaynak meta ile. Vektör araması için usable bayrağı."""
    configured = embed_model_name()
    base = embed_base_url()
    prompt = (text or "").strip()
    if not prompt:
        res = EmbedResult(model=configured, error="boş metin", source="failed")
        _set_last_meta(res.__dict__)
        return res

    errors: List[str] = []
    async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:
        # 1) /api/embed truncate=false
        vec, err = await _post_ollama_embed_api(client, base, configured, prompt)
        if vec:
            res = EmbedResult(
                vector=vec, model=configured, dim=len(vec),
                source="ollama_embed", usable_for_vector_search=True,
            )
            _set_last_meta({"model": configured, "source": res.source, "dim": res.dim})
            return res
        if err:
            errors.append(err)

        # 2) legacy /api/embeddings
        vec, err = await _post_ollama_embeddings_legacy(client, base, configured, prompt)
        if vec:
            res = EmbedResult(
                vector=vec, model=configured, dim=len(vec),
                source="ollama_embeddings", usable_for_vector_search=True,
            )
            _set_last_meta({"model": configured, "source": res.source, "dim": res.dim})
            return res
        if err:
            errors.append(err)

        # 3) aynı host /v1/embeddings
        vec, err = await _post_openai_embeddings(
            client, base, configured, prompt, ollama_keep_alive=True,
        )
        if vec:
            res = EmbedResult(
                vector=vec, model=configured, dim=len(vec),
                source="ollama_v1", usable_for_vector_search=True,
            )
            _set_last_meta({"model": configured, "source": res.source, "dim": res.dim})
            return res
        if err and "erişilemedi" not in (err or ""):
            errors.append(err)

    # 4) REMOTE — yalnız aynı model adı; aksi halde vektör araması için kullanma
    if remote_llm_enabled():
        remote_base = (settings.REMOTE_LLM_URL or "").rstrip("/")
        remote_model = remote_embed_model_name()
        if remote_model != configured:
            msg = (
                f"REMOTE_LLM embed modeli ({remote_model}) yapılandırılmış yerel "
                f"modelden ({configured}) farklı — vektör araması atlanacak (FTS)"
            )
            logger.warning("RAG embed: %s", msg)
            res = EmbedResult(
                model=configured, source="failed", error=msg,
                usable_for_vector_search=False,
                extras={"remote_model": remote_model},
            )
            _set_last_error(msg)
            _set_last_meta(res.__dict__)
            return res
        headers = {
            **{
                k: v
                for k, v in {
                    "Authorization": (settings.REMOTE_LLM_API_KEY or "").strip() or None,
                    "x-bf-vk": (getattr(settings, "REMOTE_LLM_VIRTUAL_KEY", None) or "").strip() or None,
                }.items()
                if v
            },
            "Content-Type": "application/json",
        }
        verify: Any = remote_llm_ssl_verify()
        logger.warning(
            "RAG embed: uzak sağlayıcıya düşülüyor (veri çıkışı) url=%s model=%s",
            remote_base, remote_model,
        )
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT, verify=verify) as rclient:
                vec, err = await _post_openai_embeddings(
                    rclient, remote_base, remote_model, prompt, headers=headers,
                )
            if vec:
                res = EmbedResult(
                    vector=vec, model=remote_model, dim=len(vec),
                    source="remote_v1", usable_for_vector_search=True,
                    extras={"egress": True, "remote_url": remote_base},
                )
                _set_last_meta({
                    "model": remote_model, "source": res.source, "dim": res.dim, "egress": True,
                })
                return res
            if err:
                errors.append(f"REMOTE_LLM: {err}")
        except Exception as e:
            errors.append(f"REMOTE_LLM embed hata: {type(e).__name__}: {e}")

    detail = errors[0] if errors else "embedding başarısız"
    if "erişilemedi" in detail:
        detail = f"{detail}. {_remediation_hint(base, configured)}"
    _set_last_error(detail)
    res = EmbedResult(model=configured, source="failed", error=detail)
    _set_last_meta({"model": configured, "source": "failed", "error": detail})
    return res


async def _post_embed(client: httpx.AsyncClient, text: str) -> Tuple[Optional[List[float]], Optional[str]]:
    """Geriye uyum — embed_text kullanır (client yok sayılır, kendi client açar)."""
    del client  # API uyumu
    res = await embed_text(text)
    if res.vector and res.usable_for_vector_search:
        return res.vector, None
    return None, res.error or "embedding başarısız"


async def probe_embedding(*, mode: str = "light") -> Dict[str, Any]:
    base = embed_base_url()
    model = embed_model_name()
    probe_mode = (mode or "light").strip().lower()
    if probe_mode not in ("light", "full"):
        probe_mode = "light"

    out: Dict[str, Any] = {
        "ok": False,
        "base_url": base,
        "model": model,
        "remote_llm_fallback": remote_llm_enabled(),
        "error": None,
        "hint": _remediation_hint(base, model),
        "probe_mode": probe_mode,
        "expected_dim": EXPECTED_EMBED_DIM,
    }

    tags_timeout = 5.0
    full_timeout = min(15.0, OLLAMA_EMBED_TIMEOUT)
    client_timeout = full_timeout if probe_mode == "full" else tags_timeout

    try:
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            tags_ok = False
            try:
                tags = await client.get(f"{base}/api/tags")
                if tags.status_code == 200:
                    names = [
                        m.get("name") or ""
                        for m in (tags.json() or {}).get("models", [])
                        if isinstance(m, dict)
                    ]
                    out["models"] = names[:40]
                    out["model_present"] = any(
                        model == n
                        or n.startswith(model + ":")
                        or model.startswith(n.split(":")[0])
                        for n in names
                    )
                    tags_ok = True
                else:
                    out["tags_status"] = tags.status_code
                    out["error"] = f"HTTP {tags.status_code} {base}/api/tags"
            except Exception as e:
                out["tags_error"] = f"{type(e).__name__}: {e}"
                out["error"] = f"{base} erişilemedi ({type(e).__name__}: {e})"

            if probe_mode == "light":
                if tags_ok and out.get("model_present"):
                    out["ok"] = True
                    out["error"] = None
                elif tags_ok and out.get("model_present") is False:
                    out["error"] = (
                        f"Model listede yok: {model}. "
                        f"`ollama pull {model}` çalıştırın."
                    )
                return out

            if not tags_ok:
                return out
            res = await embed_text("rag health probe")
            if res.vector and res.usable_for_vector_search:
                out["ok"] = True
                out["dim"] = res.dim
                out["source"] = res.source
                out["error"] = None
            else:
                out["error"] = res.error or get_last_embed_error() or "sıfır vektör"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


async def get_embedding(text: str) -> List[float]:
    """Tek metin embedding. Başarısızsa sıfır vektör + last_error."""
    if not text or not text.strip():
        return _zero_vec()
    res = await embed_text(text)
    if res.vector and res.usable_for_vector_search:
        return res.vector
    if res.error:
        _set_last_error(res.error)
        logger.warning("Ollama embed failed: %s", res.error)
    return _zero_vec()


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    concurrency = embed_concurrency()
    sem = asyncio.Semaphore(concurrency)
    results: List[Optional[List[float]]] = [None] * len(texts)
    model = embed_model_name()

    async def _one(i: int, t: str) -> None:
        if not t or not str(t).strip():
            results[i] = _zero_vec()
            return
        async with sem:
            res = await embed_text(str(t))
            if res.vector and res.usable_for_vector_search:
                results[i] = res.vector
            else:
                if res.error:
                    _set_last_error(res.error)
                    logger.warning("Ollama embed[%s] failed: %s", i, res.error)
                results[i] = _zero_vec()

    total = len(texts)
    if total >= 20:
        logger.info(
            "RAG embed batch start: %s chunk, concurrency=%s, model=%s",
            total, concurrency, model,
        )
    await asyncio.gather(*[_one(i, t) for i, t in enumerate(texts)])
    if total >= 20:
        ok = sum(1 for v in results if v and not all(abs(float(x)) < 1e-12 for x in v))
        logger.info("RAG embed batch done: %s/%s ok", ok, total)
    return [r if r is not None else _zero_vec() for r in results]


def get_embedding_sync(text: str) -> List[float]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(get_embedding(text))).result()
        return loop.run_until_complete(get_embedding(text))
    except RuntimeError:
        return asyncio.run(get_embedding(text))
