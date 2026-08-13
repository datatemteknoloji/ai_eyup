"""Celery worker — ağır filo işleri + bulk health check."""
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

# task_name → runner in fleet_jobs
_FLEET_TASKS = {
    "fleet.health_check": "run_health_check",
    "fleet.auto_onboarding": "run_auto_onboarding",
    "fleet.nlq_linux_inventory": "run_nlq_linux_inventory",
    "fleet.inventory_sync": "run_inventory_sync",
    "fleet.metric_sync": "run_metric_sync",
    "fleet.esx_metric_sync": "run_esx_metric_sync",
    "fleet.node_exporter_sync": "run_node_exporter_sync",
    "fleet.windows_exporter_sync": "run_windows_exporter_sync",
    "fleet.log_collection": "run_log_collection",
    "fleet.anomaly_scan": "run_anomaly_scan",
    "fleet.windows_log_collection": "run_windows_log_collection",
    "fleet.windows_live_metrics": "run_windows_live_metrics",
}


def celery_workers_available(*, timeout: float = 0.8) -> bool:
    """En az bir Celery worker ping'e cevap veriyor mu?"""
    if celery_app is None:
        return False
    try:
        insp = celery_app.control.inspect(timeout=timeout)
        if insp is None:
            return False
        ping = insp.ping() or {}
        return bool(ping)
    except Exception as exc:
        logger.debug("Celery inspect/ping başarısız: %s", exc)
        return False


def enqueue_fleet_job(task_name: str, *args, **kwargs) -> bool:
    """Filo işini Celery'ye gönder. Worker yoksa False (caller local fallback)."""
    if task_name not in _FLEET_TASKS and task_name != "servers.check_health":
        logger.warning("Bilinmeyen fleet task: %s", task_name)
        return False
    if celery_app is None:
        return False
    if not celery_workers_available():
        logger.info("Celery worker yok — %s local fallback", task_name)
        return False
    try:
        celery_app.send_task(task_name, args=list(args), kwargs=kwargs)
        return True
    except Exception as exc:
        logger.warning("Celery enqueue %s başarısız: %s", task_name, exc)
        return False


def enqueue_check_health(job_id: str) -> bool:
    """Celery'ye health check gönder. Worker yoksa / hata varsa False (caller thread'e düşer)."""
    return enqueue_fleet_job("servers.check_health", job_id)


def _run_check_health(job_id: str) -> dict:
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services import bulk_job_tracker as jobs
    from app.services.monitoring.server_health_checker import ServerHealthChecker

    bg = SessionLocal()
    try:
        jobs.update_job(job_id, message="Durum kontrolü çalışıyor…", queued_via="celery")

        def _prog(done, total):
            if jobs.is_cancelled(job_id):
                return
            jobs.tick(
                job_id,
                done=done,
                total=total,
                message=f"Kontrol: {done}/{total}",
            )

        stats = ServerHealthChecker.update_server_statuses(
            bg, on_progress=_prog, cancel_check=lambda: jobs.is_cancelled(job_id)
        )
        if jobs.is_cancelled(job_id):
            jobs.finish(
                job_id,
                status="cancelled",
                message=(
                    f"İptal edildi ({stats.get('checked', 0)}/{stats.get('total') or stats.get('checked', 0)} tamamlandı)"
                ),
                result=stats,
            )
            return {"ok": False, "cancelled": True, "stats": stats}
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


def _bind_fleet_tasks() -> None:
    if celery_app is None:
        return
    from app.services import fleet_jobs

    for task_name, fn_name in _FLEET_TASKS.items():
        fn = getattr(fleet_jobs, fn_name)
        celery_app.task(name=task_name)(fn)

    celery_app.task(name="servers.check_health")(_run_check_health)


_bind_fleet_tasks()
