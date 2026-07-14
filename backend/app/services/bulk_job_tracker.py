"""
Toplu (bulk) uzun işler için in-memory ilerleme takibi.

vCenter sync_job benzeri: UI overlay GET /servers/bulk-jobs/{id} ile poll eder.
Process restart'ta kaybolur — kabul edilebilir (işler de daemon thread'de).
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_MAX_JOBS = 40


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
        "status": "running",  # running | done | error
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
    with _lock:
        _jobs[jid] = job
        _prune_locked()
    return jid


def _prune_locked() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    # Eski bitmiş işleri at
    finished = sorted(
        (j for j in _jobs.values() if j["status"] in ("done", "error")),
        key=lambda j: j.get("finished_at") or 0,
    )
    while len(_jobs) > _MAX_JOBS and finished:
        old = finished.pop(0)
        _jobs.pop(old["id"], None)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def list_jobs(*, active_only: bool = False) -> List[Dict[str, Any]]:
    with _lock:
        items = list(_jobs.values())
    if active_only:
        items = [j for j in items if j.get("status") == "running"]
    items.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
    return [dict(j) for j in items]


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if not j or j.get("status") != "running":
            return
        for k, v in fields.items():
            if k in ("id", "started_at"):
                continue
            j[k] = v
        _recompute_percent_locked(j)


def tick(
    job_id: str,
    *,
    done: Optional[int] = None,
    total: Optional[int] = None,
    ok_delta: int = 0,
    fail_delta: int = 0,
    message: Optional[str] = None,
) -> None:
    with _lock:
        j = _jobs.get(job_id)
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
        _recompute_percent_locked(j)


def _recompute_percent_locked(j: Dict[str, Any]) -> None:
    total = int(j.get("total") or 0)
    done = int(j.get("done") or 0)
    if total > 0:
        j["percent"] = max(1, min(99, int(round(100.0 * done / total))))
    elif j.get("status") == "running":
        j["percent"] = max(3, int(j.get("percent") or 3))


def finish(
    job_id: str,
    *,
    status: str = "done",
    message: Optional[str] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return
        j["status"] = status if status in ("done", "error") else "done"
        j["finished_at"] = time.time()
        j["percent"] = 100 if j["status"] == "done" else int(j.get("percent") or 0)
        if message is not None:
            j["message"] = message
        if error is not None:
            j["error"] = error
        if result is not None:
            j["result"] = result
