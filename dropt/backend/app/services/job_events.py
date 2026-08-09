"""Redis pub/sub for live job console events."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings


def _client():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def job_channel(job_id: int) -> str:
    return f"dropt:job:{job_id}:events"


def publish_job_event(job_id: int, event: dict[str, Any]) -> None:
    try:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        r = _client()
        r.publish(job_channel(job_id), payload)
    except Exception:
        pass


def publish_job_progress(
    job_id: int,
    *,
    done: int,
    total: int,
    label: str = "",
    hostname: str = "",
    session: Any | None = None,
) -> None:
    """Canlı progress bar + isteğe bağlı Job.progress_* güncellemesi."""
    if not job_id:
        return
    total_n = max(0, int(total))
    done_n = max(0, min(int(done), total_n if total_n else int(done)))
    pct = int(round(100.0 * done_n / total_n)) if total_n else 0
    pct = min(100, max(0, pct))
    if session is not None:
        try:
            from app.models.job import Job

            job = session.get(Job, job_id)
            if job is not None:
                job.progress_done = done_n
                job.progress_total = total_n or job.progress_total
                session.add(job)
                session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
    publish_job_event(
        int(job_id),
        {
            "type": "progress",
            "hostname": hostname,
            "done": done_n,
            "total": total_n,
            "percent": pct,
            "label": (label or "")[:200],
        },
    )
