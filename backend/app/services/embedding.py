"""
Embedding servisi — RAG için metin vektörleme.

Öncelik:
  1) EMBEDDING_URL veya OLLAMA_URL → Ollama /api/embeddings (+ /api/embed fallback)
  2) Aynı tabanda OpenAI-uyumlu /v1/embeddings (yeni Ollama / gateway)
  3) REMOTE_LLM açıkysa REMOTE_LLM_URL /v1/embeddings

Varsayılan model: nomic-embed-text (768 boyut).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import remote_llm_enabled, remote_llm_ssl_verify, settings

logger = logging.getLogger(__name__)

OLLAMA_EMBED_TIMEOUT = float(os.getenv("OLLAMA_EMBED_TIMEOUT", "60"))
# Büyük PDF'lerde sıralı embed dakikalar sürer; paralel sınırla hızlandır
EMBED_CONCURRENCY = max(1, min(int(os.getenv("OLLAMA_EMBED_CONCURRENCY", "8")), 32))

# Son başarısız embedding ayrıntısı (UI/RuntimeError için)
_last_embed_error: Optional[str] = None


def get_last_embed_error() -> Optional[str]:
    return _last_embed_error


def _set_last_error(msg: str) -> None:
    global _last_embed_error
    _last_embed_error = (msg or "")[:800]


def _zero_vec(dim: int = 768) -> List[float]:
    return [0.0] * dim


def embed_base_url() -> str:
    """RAG embedding için hedef kök URL (chat Ollama'sından ayrı seçilebilir)."""
    return (
        (getattr(settings, "EMBEDDING_URL", None) or "").strip()
        or (settings.OLLAMA_URL or "").strip()
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def embed_model_name() -> str:
    return (
        (getattr(settings, "REMOTE_LLM_EMBED_MODEL", None) or "").strip()
        or (settings.OLLAMA_EMBED_MODEL or "").strip()
        or "nomic-embed-text"
    )


def _parse_embedding_payload(data: dict) -> Optional[List[float]]:
    """Hem /api/embeddings hem /api/embed hem /v1/embeddings yanıtlarını destekle."""
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


def _remediation_hint(base: str, model: str) -> str:
    return (
        f"RAG embedding için Ollama erişimi gerekir. "
        f"Sunucuda: `curl -s {base}/api/tags` ve `ollama pull {model}`. "
        f"Compose ile: `docker compose --profile ollama -f docker-compose.prod.yml up -d ollama` "
        f"sonra `docker exec server_management_ollama ollama pull {model}`. "
        f"OLLAMA_URL / EMBEDDING_URL (.env) backend'in gördüğü adresi göstermeli."
    )


async def _post_ollama_native(
    client: httpx.AsyncClient, base: str, model: str, prompt: str
) -> Tuple[Optional[List[float]], Optional[str]]:
    try:
        r = await client.post(
            f"{base}/api/embeddings",
            json={"model": model, "prompt": prompt},
        )
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            if vec:
                return vec, None
            return None, f"{base}/api/embeddings: boş embedding döndü"
        err_body = (r.text or "")[:240]
        if r.status_code in (404, 405) or "not found" in err_body.lower():
            r2 = await client.post(
                f"{base}/api/embed",
                json={"model": model, "input": prompt},
            )
            if r2.status_code == 200:
                vec = _parse_embedding_payload(r2.json())
                if vec:
                    return vec, None
                return None, f"{base}/api/embed: boş embedding döndü"
            return None, f"HTTP {r2.status_code} {base}/api/embed: {(r2.text or '')[:200]}"
        return None, f"HTTP {r.status_code} {base}/api/embeddings model={model}: {err_body}"
    except Exception as e:
        return None, f"{base} erişilemedi ({type(e).__name__}: {e})"


async def _post_openai_embeddings(
    client: httpx.AsyncClient,
    base: str,
    model: str,
    prompt: str,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[List[float]], Optional[str]]:
    url = f"{base.rstrip('/')}/v1/embeddings"
    try:
        r = await client.post(
            url,
            json={"model": model, "input": prompt},
            headers=headers or {},
        )
        if r.status_code == 200:
            vec = _parse_embedding_payload(r.json())
            if vec:
                return vec, None
            return None, f"{url}: boş embedding döndü"
        return None, f"HTTP {r.status_code} {url}: {(r.text or '')[:200]}"
    except Exception as e:
        return None, f"{url} erişilemedi ({type(e).__name__}: {e})"


async def _post_embed(client: httpx.AsyncClient, text: str) -> Tuple[Optional[List[float]], Optional[str]]:
    """Embedding isteği — Ollama native → aynı host /v1 → REMOTE_LLM /v1."""
    base = embed_base_url()
    model = embed_model_name()
    prompt = text.strip()
    errors: List[str] = []

    vec, err = await _post_ollama_native(client, base, model, prompt)
    if vec:
        return vec, None
    if err:
        errors.append(err)

    # Yeni Ollama / bazı gateway'ler OpenAI embeddings yolu sunar (auth yok)
    vec, err = await _post_openai_embeddings(client, base, model, prompt)
    if vec:
        return vec, None
    if err and "erişilemedi" not in (err or ""):
        # Bağlantı tamamen yoksa tekrar yazmaya gerek yok
        errors.append(err)

    if remote_llm_enabled():
        remote_base = (settings.REMOTE_LLM_URL or "").rstrip("/")
        remote_model = (
            (getattr(settings, "REMOTE_LLM_EMBED_MODEL", None) or "").strip()
            or model
        )
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
        # SSL: remote_llm_ssl_verify bool veya CA path; httpx verify=...
        verify: Any = remote_llm_ssl_verify()
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT, verify=verify) as rclient:
                vec, err = await _post_openai_embeddings(
                    rclient, remote_base, remote_model, prompt, headers=headers
                )
            if vec:
                return vec, None
            if err:
                errors.append(f"REMOTE_LLM: {err}")
        except Exception as e:
            errors.append(f"REMOTE_LLM embed hata: {type(e).__name__}: {e}")

    detail = errors[0] if errors else "embedding başarısız"
    if "erişilemedi" in detail:
        detail = f"{detail}. {_remediation_hint(base, model)}"
    return None, detail


async def probe_embedding() -> Dict[str, Any]:
    """UI /rag/status için embedding sağlık kontrolü (tek kısa istek)."""
    base = embed_base_url()
    model = embed_model_name()
    out: Dict[str, Any] = {
        "ok": False,
        "base_url": base,
        "model": model,
        "remote_llm_fallback": remote_llm_enabled(),
        "error": None,
        "hint": _remediation_hint(base, model),
    }
    try:
        async with httpx.AsyncClient(timeout=min(15.0, OLLAMA_EMBED_TIMEOUT)) as client:
            # Önce tags — hızlı bağlantı testi
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
                        model == n or n.startswith(model + ":") or model.startswith(n.split(":")[0])
                        for n in names
                    )
                else:
                    out["tags_status"] = tags.status_code
            except Exception as e:
                out["tags_error"] = f"{type(e).__name__}: {e}"

            vec, err = await _post_embed(client, "rag health probe")
            if vec and not all(abs(float(x)) < 1e-12 for x in vec):
                out["ok"] = True
                out["dim"] = len(vec)
            else:
                out["error"] = err or get_last_embed_error() or "sıfır vektör"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


async def get_embedding(text: str) -> List[float]:
    """Tek bir metin için embedding döndür. Başarısızsa sıfır vektör + last_error."""
    if not text or not text.strip():
        return _zero_vec()
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:
            vec, err = await _post_embed(client, text)
            if vec:
                return vec
            if err:
                _set_last_error(err)
                logger.warning("Ollama embed failed: %s", err)
            return _zero_vec()
    except Exception as e:
        msg = f"Embedding error: {e}"
        _set_last_error(msg)
        logger.warning(msg)
        return _zero_vec()


async def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Birden fazla metin için paralel embedding (semaphore ile sınırlı)."""
    if not texts:
        return []

    sem = asyncio.Semaphore(EMBED_CONCURRENCY)
    results: List[Optional[List[float]]] = [None] * len(texts)

    async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT) as client:

        async def _one(i: int, t: str) -> None:
            if not t or not str(t).strip():
                results[i] = _zero_vec()
                return
            async with sem:
                vec, err = await _post_embed(client, str(t))
                if vec:
                    results[i] = vec
                else:
                    if err:
                        _set_last_error(err)
                        logger.warning("Ollama embed[%s] failed: %s", i, err)
                    results[i] = _zero_vec()

        total = len(texts)
        if total >= 20:
            logger.info(
                "RAG embed batch start: %s chunk, concurrency=%s, model=%s",
                total, EMBED_CONCURRENCY, embed_model_name(),
            )

        await asyncio.gather(*[_one(i, t) for i, t in enumerate(texts)])

    if total >= 20:
        ok = sum(1 for v in results if v and not all(abs(float(x)) < 1e-12 for x in v))
        logger.info("RAG embed batch done: %s/%s ok", ok, total)

    return [r if r is not None else _zero_vec() for r in results]


def get_embedding_sync(text: str) -> List[float]:
    """Senkron embedding (Chroma embedding function için)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(get_embedding(text))).result()
        return loop.run_until_complete(get_embedding(text))
    except RuntimeError:
        return asyncio.run(get_embedding(text))
