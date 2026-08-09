"""Celery worker — ağır işler (health check, ileride Ansible/bulk SSH)."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    from celery import Celery
except ImportError:  # pragma: no cover
    Celery = None  # type: ignore


def _broker_url() -> str:
    return (os.environ.get("REDIS_URL") or "redis://localhost:6379/0").strip()


def make_celery():
    if Celery is None:
        raise RuntimeError("celery kurulu değil")
    app = Celery("ainew", broker=_broker_url(), backend=_broker_url())
    app.conf.update(
        task_track_started=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        broker_connection_retry_on_startup=True,
    )
    return app


celery_app = make_celery() if Celery is not None else None


def enqueue_check_health(job_id: str) -> bool:
    """Celery'ye health check gönder. Başarısızsa False (caller thread'e düşer)."""
    if celery_app is None:
        return False
    try:
        celery_app.send_task("servers.check_health", args=[job_id])
        return True
    except Exception as exc:
        logger.warning("Celery enqueue check_health başarısız: %s", exc)
        return False


def _run_check_health(job_id: str) -> dict:
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services import bulk_job_tracker as jobs
    from app.services.monitoring.server_health_checker import ServerHealthChecker

    bg = SessionLocal()
    try:
        def _prog(done, total):
            jobs.tick(
                job_id,
                done=done,
                total=total,
                message=f"Kontrol: {done}/{total}",
            )

        stats = ServerHealthChecker.update_server_statuses(bg, on_progress=_prog)
        if stats.get("error"):
            jobs.finish(job_id, status="error", message="Durum kontrolü başarısız", error=str(stats["error"]))
            return {"ok": False, "error": stats["error"]}
        jobs.update_job(
            job_id,
            ok_count=int(stats.get("online") or 0),
            fail_count=int(stats.get("offline") or 0),
        )
        jobs.finish(
            job_id,
            status="done",
            message=(
                f"Tamamlandı: {stats.get('checked', 0)} kontrol · "
                f"{stats.get('online', 0)} online · {stats.get('offline', 0)} offline · "
                f"{stats.get('updated', 0)} güncellendi"
            ),
            result=stats,
        )
        return {"ok": True, "stats": stats}
    except Exception as e:
        logger.exception("Celery health check hatası")
        jobs.finish(job_id, status="error", message="Durum kontrolü hatası", error=str(e))
        return {"ok": False, "error": str(e)}
    finally:
        bg.close()


if celery_app is not None:
    check_health_task = celery_app.task(name="servers.check_health")(_run_check_health)
else:  # pragma: no cover
    check_health_task = _run_check_health  # type: ignore
