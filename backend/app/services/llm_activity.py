"""LLM çağrı etkinlik kaydı — kuyruk (Ollama Parallel:1) teşhisi için.

Her gateway çağrısı (chat_sync / chat stream / generate / stream_generate) başlangıç-bitiş
zamanı, model ve ÇAĞIRAN modül ile kaydedilir. Çok süreç / konteyner (backend + worker)
için Redis'e (fail-open) yazılır. `overlapping()` bir isteğin süresiyle çakışan DİĞER
çağrıları döner; admin: GET /settings/llm-activity.
"""
from __future__ import annotations

import contextlib
import json
import logging
import sys
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_REDIS_LIST = "ainew:llm_activity"
_REDIS_TTL = 3600
_MAX = 500
_lock = threading.Lock()
_recent: List[Dict[str, Any]] = []
_inflight: Dict[int, Dict[str, Any]] = {}
_seq = 0

_SKIP_PREFIXES = (
    "app.services.llm_gateway", "app.services.llm_activity", "app.services.llm_usage",
    "app.services.agent.llm", "contextlib", "asyncio", "threading", "concurrent",
    "httpx", "requests", "anyio", "starlette",
)


def _caller_module() -> str:
    try:
        f = sys._getframe(2)
        depth = 0
        while f is not None and depth < 25:
            name = f.f_globals.get("__name__", "")
            if name and not name.startswith(_SKIP_PREFIXES):
                return f"{name}.{f.f_code.co_name}"
            f = f.f_back
            depth += 1
    except Exception:
        pass
    return "unknown"


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


@contextlib.contextmanager
def track(kind: str, model: str, *, label: str = "", lease: Any = None) -> Iterator[Dict[str, Any]]:
    """with llm_activity.track('chat_sync', model): ... — çağrıyı kaydeder."""
    global _seq
    rec: Dict[str, Any] = {
        "kind": kind, "model": model, "label": label,
        "caller": _caller_module(), "start": time.time(),
        "request_id": None, "module": None,
    }
    if lease is not None:
        rec["priority"] = getattr(lease, "priority", None)
        rec["sched_wait_ms"] = round(float(getattr(lease, "wait_ms", 0.0) or 0.0), 1)
    try:
        from app.services import chat_request_metrics as crm
        cur = crm.current()
        if cur is not None:
            rec["request_id"] = cur.request_id
            rec["module"] = cur.module
    except Exception:
        pass
    with _lock:
        _seq += 1
        key = _seq
        _inflight[key] = rec
    try:
        yield rec
    finally:
        rec["end"] = time.time()
        rec["duration_ms"] = round((rec["end"] - rec["start"]) * 1000, 1)
        with _lock:
            _inflight.pop(key, None)
            _recent.append(rec)
            if len(_recent) > _MAX:
                del _recent[: len(_recent) - _MAX]
        r = _redis()
        if r is not None:
            try:
                r.lpush(_REDIS_LIST, json.dumps(rec, ensure_ascii=False, default=str))
                r.ltrim(_REDIS_LIST, 0, _MAX - 1)
                r.expire(_REDIS_LIST, _REDIS_TTL)
            except Exception as exc:
                logger.debug("llm_activity redis: %s", exc)


def recent(limit: int = 100, since: Optional[float] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    r = _redis()
    if r is not None:
        try:
            for blob in r.lrange(_REDIS_LIST, 0, _MAX - 1) or []:
                try:
                    x = json.loads(blob)
                except Exception:
                    continue
                k = (x.get("start"), x.get("caller"), x.get("kind"))
                if k in seen:
                    continue
                seen.add(k)
                out.append(x)
        except Exception:
            pass
    with _lock:
        for x in list(_recent) + list(_inflight.values()):
            k = (x.get("start"), x.get("caller"), x.get("kind"))
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
    if since is not None:
        out = [x for x in out if (x.get("end") or time.time()) >= since]
    out.sort(key=lambda x: x.get("start") or 0, reverse=True)
    return out[: max(1, limit)]


def overlapping(t0: float, t1: float, *, exclude_request_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """[t0, t1] ile çakışan, belirtilen isteğe AİT OLMAYAN LLM çağrıları (özet)."""
    res: List[Dict[str, Any]] = []
    for x in recent(limit=_MAX, since=t0):
        s = x.get("start") or 0
        e = x.get("end") or time.time()
        if s > t1 or e < t0:
            continue
        if exclude_request_id and x.get("request_id") == exclude_request_id:
            continue
        ov = max(0.0, min(e, t1) - max(s, t0))
        res.append({
            "kind": x.get("kind"), "model": x.get("model"), "caller": x.get("caller"),
            "module": x.get("module"), "request_id": x.get("request_id"),
            "overlap_ms": round(ov * 1000, 1), "duration_ms": x.get("duration_ms"),
        })
    return res
