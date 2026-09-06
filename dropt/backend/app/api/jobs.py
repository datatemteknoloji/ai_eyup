import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from sqlmodel import Session, col, func, select

from app.api.deps import get_current_user
from app.core.database import engine, get_session
from app.core.security import TokenError, safe_decode_token
from app.models.job import Job, JobRun, JobStatus, PreviewArtifact
from app.models.server import TargetServer
from app.models.user import User
from app.modules.log_collect import list_templates
from app.schemas.job import JobCreate, JobListResponse, JobPublic, JobRunPublic, PreviewPublic
from app.services.artifacts import job_artifact_dir
from app.services.job_engine import create_job, run_preview
from app.services.job_events import job_channel
from app.worker import apply_job_task

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client:
        return (request.client.host or "")[:64]
    return ""


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    if "password" in data and data["password"]:
        data["password"] = "***"
    if "activation_key" in data and data["activation_key"]:
        data["activation_key"] = "***"
    return data


def _preview_public(p: PreviewArtifact) -> PreviewPublic:
    return PreviewPublic(
        id=p.id,  # type: ignore[arg-type]
        job_id=p.job_id,
        summary_tr=p.summary_tr,
        risk_notes=p.risk_notes,
        planned_commands=list(p.planned_commands or []),
        host_summaries=list(p.host_summaries or []),
        technical_detail=p.technical_detail,
        created_at=p.created_at,
    )


def _run_public(r: JobRun) -> JobRunPublic:
    return JobRunPublic(
        id=r.id,  # type: ignore[arg-type]
        job_id=r.job_id,
        target_server_id=r.target_server_id,
        hostname=r.hostname,
        ip=r.ip,
        status=r.status,
        dry_run=r.dry_run,
        summary_tr=r.summary_tr,
        planned_commands=list(r.planned_commands or []),
        before_state=dict(r.before_state or {}),
        after_state=dict(r.after_state or {}),
        stdout=r.stdout or "",
        stderr=r.stderr or "",
        error_message=r.error_message or "",
        started_at=r.started_at,
        finished_at=r.finished_at,
    )


def _hostnames_for_ids(session: Session, server_ids: list[int], host_map: dict[int, str] | None = None) -> list[str]:
    ids = [int(i) for i in (server_ids or []) if i is not None]
    if not ids:
        return []
    mapping = host_map
    if mapping is None:
        rows = session.exec(select(TargetServer).where(col(TargetServer.id).in_(ids))).all()
        mapping = {int(s.id): s.hostname for s in rows if s.id is not None}  # type: ignore[arg-type]
    return [mapping.get(i) or f"#{i}" for i in ids]


def _job_public(
    session: Session,
    job: Job,
    *,
    detail: bool = False,
    host_map: dict[int, str] | None = None,
) -> JobPublic:
    preview = None
    runs: list[JobRunPublic] = []
    if detail:
        p = session.exec(select(PreviewArtifact).where(PreviewArtifact.job_id == job.id)).first()
        if p:
            preview = _preview_public(p)
        runs = [_run_public(r) for r in session.exec(select(JobRun).where(JobRun.job_id == job.id)).all()]
    server_ids = list(job.server_ids or [])
    return JobPublic(
        id=job.id,  # type: ignore[arg-type]
        module=job.module,
        action=job.action,
        status=job.status,
        talep_id=job.talep_id,
        title=job.title,
        summary_tr=job.summary_tr,
        created_by_username=job.created_by_username,
        created_by_role=job.created_by_role,
        server_ids=server_ids,
        hostnames=_hostnames_for_ids(session, server_ids, host_map),
        payload=_sanitize_payload(dict(job.payload or {})),
        dry_run=job.dry_run,
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        error_message=job.error_message or "",
        created_at=job.created_at,
        updated_at=job.updated_at,
        previewed_at=job.previewed_at,
        applied_at=job.applied_at,
        finished_at=job.finished_at,
        preview=preview,
        runs=runs,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    q: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> JobListResponse:
    stmt = select(Job)
    count_stmt = select(func.count()).select_from(Job)
    if status_filter is not None:
        stmt = stmt.where(Job.status == status_filter)
        count_stmt = count_stmt.where(Job.status == status_filter)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        filt = (
            (func.lower(Job.talep_id).like(term))
            | (func.lower(Job.title).like(term))
            | (func.lower(Job.summary_tr).like(term))
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    total = session.exec(count_stmt).one()
    rows = session.exec(
        stmt.order_by(col(Job.id).desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    all_ids: set[int] = set()
    for j in rows:
        for sid in j.server_ids or []:
            try:
                all_ids.add(int(sid))
            except (TypeError, ValueError):
                continue
    host_map: dict[int, str] = {}
    if all_ids:
        servers = session.exec(select(TargetServer).where(col(TargetServer.id).in_(list(all_ids)))).all()
        host_map = {int(s.id): s.hostname for s in servers if s.id is not None}  # type: ignore[arg-type]
    return JobListResponse(
        items=[_job_public(session, j, host_map=host_map) for j in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=JobPublic, status_code=status.HTTP_201_CREATED)
def create_job_endpoint(
    body: JobCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> JobPublic:
    # Level 1 ops SSH ister — otomasyon şifresi yoksa başlatma
    from app.services.bootstrap import automation_password_is_set

    if body.server_ids and not automation_password_is_set(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce Level 1 → Ayarlar’da otomasyon kullanıcı şifresini kaydedin "
            "(vCenter / Linux envanter kaydı yeterli değildir).",
        )
    try:
        job = create_job(
            session,
            module=body.module,
            action=body.action,
            talep_id=body.talep_id,
            server_ids=body.server_ids,
            payload=body.payload,
            user_id=user.id,  # type: ignore[arg-type]
            username=user.username,
            role=user.role.value,
            client_ip=_client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _job_public(session, job, detail=True)


@router.get("/{job_id}", response_model=JobPublic)
def get_job(
    job_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> JobPublic:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İş bulunamadı")
    return _job_public(session, job, detail=True)


@router.post("/{job_id}/preview", response_model=JobPublic)
def preview_job(
    job_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> JobPublic:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İş bulunamadı")
    try:
        run_preview(session, job)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.refresh(job)
    return _job_public(session, job, detail=True)


@router.post("/{job_id}/apply", response_model=JobPublic)
def apply_job_endpoint(
    job_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    sync: bool = Query(default=False, description="True: Celery beklemeden senkron uygula"),
    only_failed: bool = Query(default=False),
) -> JobPublic:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İş bulunamadı")
    if job.status not in {JobStatus.previewed, JobStatus.partial, JobStatus.failed}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce önizleme yapılmalı",
        )

    from app.services.host_op_lock import HostLockError, assert_servers_free
    from app.services.preview_freshness import StalePreviewError

    try:
        assert_servers_free(session, job)
    except HostLockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Soft-stale bayrağı (başka apply sonrası işaretlenmiş preview)
    payload = dict(job.payload or {})
    if payload.get("_stale"):
        reason = str(payload.get("_stale_reason") or "Önizleme güncelliğini yitirdi.").strip()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{reason} Lütfen yeniden önizleyin.",
        )

    if sync:
        from app.services.job_engine import apply_job

        try:
            job = apply_job(session, job, only_failed=only_failed)
        except HostLockError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except StalePreviewError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return _job_public(session, job, detail=True)

    async_result = apply_job_task.delay(job_id, only_failed)
    job.celery_task_id = async_result.id
    job.status = JobStatus.approved
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()
    session.refresh(job)
    return _job_public(session, job, detail=True)


@router.get("/meta/log-templates")
def log_templates(_user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return list_templates()


@router.get("/{job_id}/download")
def download_job_artifact(
    job_id: int,
    run_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İş bulunamadı")
    if job.module != "log_collect":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bu iş için indirme yok")

    runs = session.exec(select(JobRun).where(JobRun.job_id == job_id)).all()
    target = None
    if run_id is not None:
        target = next((r for r in runs if r.id == run_id), None)
    else:
        target = next(
            (
                r
                for r in runs
                if r.status.value == "success" and (r.after_state or {}).get("downloadable")
            ),
            None,
        )
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İndirilebilir paket yok")

    after = dict(target.after_state or {})
    filename = after.get("artifact_filename")
    stored = after.get("artifact_path")
    if not filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paket dosyası yok")

    base = job_artifact_dir(job_id).resolve()
    if stored:
        path = Path(str(stored)).resolve()
    else:
        path = (base / str(filename)).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        path = (base / str(filename)).resolve()
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paket dosyası bulunamadı")

    return FileResponse(
        path=str(path),
        filename=str(filename),
        media_type="application/gzip",
        headers={"X-Talep-Id": job.talep_id, "X-Requested-By": user.username},
    )


def _user_from_token(session: Session, token: str) -> User | None:
    try:
        payload = safe_decode_token(token)
    except TokenError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/{job_id}")
async def job_events_ws(websocket: WebSocket, job_id: int) -> None:
    """Live job console stream (Redis pub/sub → WebSocket)."""
    await websocket.accept()
    token = websocket.query_params.get("token") or ""

    with Session(engine) as session:
        user = _user_from_token(session, token)
        if user is None:
            await websocket.send_text(json.dumps({"type": "error", "message": "Oturum geçersiz"}))
            await websocket.close(code=4401)
            return
        job = session.get(Job, job_id)
        if job is None:
            await websocket.send_text(json.dumps({"type": "error", "message": "İş bulunamadı"}))
            await websocket.close(code=4404)
            return

    await websocket.send_text(
        json.dumps({"type": "subscribed", "job_id": job_id}, ensure_ascii=False)
    )

    import redis

    from app.core.config import get_settings

    r = redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(job_channel(job_id))
    loop = asyncio.get_running_loop()

    try:
        while True:
            msg = await loop.run_in_executor(None, lambda: pubsub.get_message(timeout=1.0))
            if msg and msg.get("type") == "message":
                data = msg.get("data")
                if isinstance(data, str):
                    await websocket.send_text(data)
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") == "job_end":
                            break
                    except json.JSONDecodeError:
                        pass
            try:
                incoming = await asyncio.wait_for(websocket.receive(), timeout=0.01)
            except TimeoutError:
                continue
            if incoming.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            pubsub.unsubscribe(job_channel(job_id))
            pubsub.close()
            r.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
