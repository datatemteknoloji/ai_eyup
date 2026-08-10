"""
Toplu (bulk) uzun işler için ilerleme takibi — Redis (multi-worker güvenli).

Redis yoksa process-memory fallback (tek worker / fail-open).
UI overlay GET /servers/bulk-jobs/{id} ile poll eder.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_KEY = "ainew:bulkjob:{id}"
_INDEX = "ainew:bulkjobs"
_TTL_RUNNING = 6 * 3600
_TTL_DONE = 24 * 3600
_MAX_JOBS = 40

_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}


def _rkey(job_id: str) -> str:
    return _KEY.format(id=job_id)


def _dump(job: Dict[str, Any]) -> str:
    return json.dumps(job, ensure_ascii=False, default=str)


def _load(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_redis(job: Dict[str, Any]) -> bool:
    r = get_redis()
    if r is None:
        return False
    jid = job["id"]
    ttl = _TTL_RUNNING if job.get("status") == "running" else _TTL_DONE
    try:
        pipe = r.pipeline()
        pipe.setex(_rkey(jid), ttl, _dump(job))
        pipe.zadd(_INDEX, {jid: float(job.get("started_at") or time.time())})
        pipe.expire(_INDEX, _TTL_DONE)
        pipe.execute()
        _prune_redis(r)
        return True
    except Exception as exc:
        logger.debug("bulk_job redis save failed: %s", exc)
        return False


def _prune_redis(r) -> None:
    try:
        ids = r.zrange(_INDEX, 0, -1)
        if len(ids) <= _MAX_JOBS:
            return
        # En eski bitmiş işleri at
        finished: list[tuple[float, str]] = []
        for jid in ids:
            j = _load(r.get(_rkey(jid)))
            if not j:
                r.zrem(_INDEX, jid)
                continue
            if j.get("status") in ("done", "error", "cancelled"):
                finished.append((float(j.get("finished_at") or j.get("started_at") or 0), jid))
        finished.sort()
        while len(ids) > _MAX_JOBS and finished:
            _, jid = finished.pop(0)
            r.delete(_rkey(jid))
            r.zrem(_INDEX, jid)
            ids = [x for x in ids if x != jid]
    except Exception:
        pass


def create_job(
    kind: str,
    title: str,
    *,
    total: int = 0,
    message: str = "Başlatılıyor...",
) -> str:
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    job = {
        "id": jid,
        "kind": kind,
        "title": title,
        "status": "running",
        "percent": 1 if total else 3,
        "message": message,
        "done": 0,
        "total": int(total) or 0,
        "ok_count": 0,
        "fail_count": 0,
        "error": None,
        "started_at": now,
        "finished_at": None,
        "result": {},
    }
    if not _save_redis(job):
        with _lock:
            _jobs[jid] = job
            _prune_mem_locked()
    return jid


def _prune_mem_locked() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    finished = sorted(
        (j for j in _jobs.values() if j["status"] in ("done", "error", "cancelled")),
        key=lambda j: j.get("finished_at") or 0,
    )
    while len(_jobs) > _MAX_JOBS and finished:
        old = finished.pop(0)
        _jobs.pop(old["id"], None)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    r = get_redis()
    if r is not None:
        try:
            j = _load(r.get(_rkey(job_id)))
            if j:
                return dict(j)
        except Exception:
            pass
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def list_jobs(*, active_only: bool = False) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    r = get_redis()
    if r is not None:
        try:
            ids = r.zrevrange(_INDEX, 0, _MAX_JOBS - 1)
            for jid in ids:
                j = _load(r.get(_rkey(jid)))
                if j:
                    items.append(j)
        except Exception:
            items = []
    if not items:
        with _lock:
            items = [dict(j) for j in _jobs.values()]
    if active_only:
        items = [j for j in items if j.get("status") == "running"]
    items.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
    return [dict(j) for j in items]


def update_job(job_id: str, **fields: Any) -> None:
    j = get_job(job_id)
    if not j or j.get("status") != "running":
        return
    for k, v in fields.items():
        if k in ("id", "started_at"):
            continue
        j[k] = v
    _recompute_percent(j)
    if not _save_redis(j):
        with _lock:
            if job_id in _jobs:
                _jobs[job_id] = j


def tick(
    job_id: str,
    *,
    done: Optional[int] = None,
    total: Optional[int] = None,
    ok_delta: int = 0,
    fail_delta: int = 0,
    message: Optional[str] = None,
) -> None:
    j = get_job(job_id)
    if not j or j.get("status") != "running":
        return
    if total is not None:
        j["total"] = int(total)
    if done is not None:
        j["done"] = int(done)
    if ok_delta:
        j["ok_count"] = int(j.get("ok_count") or 0) + int(ok_delta)
    if fail_delta:
        j["fail_count"] = int(j.get("fail_count") or 0) + int(fail_delta)
    if message is not None:
        j["message"] = message
    _recompute_percent(j)
    if not _save_redis(j):
        with _lock:
            if job_id in _jobs:
                _jobs[job_id] = j


def _recompute_percent(j: Dict[str, Any]) -> None:
    total = int(j.get("total") or 0)
    done = int(j.get("done") or 0)
    if total > 0:
        j["percent"] = max(1, min(99, int(round(100.0 * done / total))))
    elif j.get("status") == "running":
        j["percent"] = max(3, int(j.get("percent") or 3))


def request_cancel(job_id: str) -> bool:
    """Kullanıcı iptali — çalışan job'a cancel_requested işaretler."""
    j = get_job(job_id)
    if not j or j.get("status") != "running":
        return False
    j["cancel_requested"] = True
    j["message"] = "İptal isteniyor…"
    if not _save_redis(j):
        with _lock:
            if job_id in _jobs:
                _jobs[job_id] = j
    return True


def is_cancelled(job_id: str) -> bool:
    j = get_job(job_id)
    return bool(j and (j.get("cancel_requested") or j.get("status") == "cancelled"))


def finish(
    job_id: str,
    *,
    status: str = "done",
    message: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    j = get_job(job_id)
    if not j:
        return
    if j.get("status") in ("done", "error", "cancelled"):
        # İptal sonrası "done" ile ezme; error/cancelled üzerine yazılabilir
        if status == "done":
            return
    allowed = ("done", "error", "cancelled")
    j["status"] = status if status in allowed else "done"
    j["finished_at"] = time.time()
    j["percent"] = 100 if j["status"] in ("done", "cancelled") else int(j.get("percent") or 0)
    if message is not None:
        j["message"] = message
    if error is not None:
        j["error"] = error
    if result is not None:
        j["result"] = result
    if not _save_redis(j):
        with _lock:
            if job_id in _jobs:
                _jobs[job_id] = j
