from app.core.config import get_settings

try:
    from celery import Celery
except ImportError:  # pragma: no cover
    Celery = None  # type: ignore


def make_celery():
    settings = get_settings()
    if Celery is None:
        raise RuntimeError("celery kurulu değil")
    app = Celery("dropt", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.update(
        task_track_started=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )
    return app


celery_app = make_celery()


@celery_app.task(name="jobs.apply_job")
def apply_job_task(job_id: int, only_failed: bool = False) -> dict:
    from sqlmodel import Session

    from app.core.database import engine
    from app.models.job import Job
    from app.services.job_engine import apply_job

    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return {"ok": False, "error": "job not found"}
        try:
            result = apply_job(session, job, only_failed=only_failed)
            return {"ok": True, "job_id": result.id, "status": result.status.value}
        except Exception as exc:  # noqa: BLE001
            job = session.get(Job, job_id)
            if job is not None:
                from datetime import UTC, datetime

                from app.models.job import JobStatus
                from app.services.job_events import publish_job_event
                from app.services.preview_freshness import StalePreviewError

                # Bayat önizleme → failed değil, yeniden preview edilebilir
                if isinstance(exc, StalePreviewError):
                    job.status = JobStatus.previewed
                    job.error_message = str(exc)[:1024]
                    job.finished_at = None
                    end_status = JobStatus.previewed.value
                else:
                    job.status = JobStatus.failed
                    job.error_message = str(exc)[:1024]
                    job.finished_at = datetime.now(UTC)
                    end_status = JobStatus.failed.value
                session.add(job)
                session.commit()
                # UI WS job_end bekler; aksi halde "kuyruğa alındı %0" da kalır
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {
                        "type": "job_end",
                        "job_id": job.id,
                        "status": end_status,
                        "success": 0,
                        "failed": 0 if isinstance(exc, StalePreviewError) else 1,
                        "skipped": 0,
                        "error": str(exc)[:400],
                        "stale_preview": isinstance(exc, StalePreviewError),
                    },
                )
            return {"ok": False, "error": str(exc)}


@celery_app.task(name="audit.forward_siem")
def forward_audit_task(payload: dict) -> dict:
    from app.services.siem import forward_audit_payload

    return forward_audit_payload(payload)
