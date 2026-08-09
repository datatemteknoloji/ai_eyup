from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, col, func, or_, select

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.job import AuditLog
from app.models.user import User
from app.schemas.job import AuditListResponse, AuditPublic

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
def list_audit(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    q: str | None = None,
    talep_id: str | None = None,
    job_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AuditListResponse:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if talep_id and talep_id.strip():
        stmt = stmt.where(AuditLog.talep_id == talep_id.strip())
        count_stmt = count_stmt.where(AuditLog.talep_id == talep_id.strip())
    if job_id is not None:
        stmt = stmt.where(AuditLog.job_id == job_id)
        count_stmt = count_stmt.where(AuditLog.job_id == job_id)
    if q and q.strip():
        term = f"%{q.strip().lower()}%"
        filt = or_(
            func.lower(AuditLog.action).like(term),
            func.lower(AuditLog.username).like(term),
            func.lower(AuditLog.hostname).like(term),
            func.lower(AuditLog.message).like(term),
            func.lower(AuditLog.talep_id).like(term),
        )
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)

    total = session.exec(count_stmt).one()
    rows = session.exec(
        stmt.order_by(col(AuditLog.id).desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        AuditPublic(
            id=r.id,  # type: ignore[arg-type]
            user_id=r.user_id,
            username=r.username,
            role=r.role,
            client_ip=r.client_ip,
            target_server_id=r.target_server_id,
            hostname=r.hostname,
            ip=r.ip,
            talep_id=r.talep_id,
            job_id=r.job_id,
            action=r.action,
            status=r.status,
            message=r.message,
            before_state=dict(r.before_state or {}),
            after_state=dict(r.after_state or {}),
            output=r.output or "",
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditListResponse(items=items, total=total, page=page, page_size=page_size)


@router.delete("/{audit_id}", include_in_schema=False)
def delete_audit_forbidden(_audit_id: int, _user: User = Depends(get_current_user)) -> None:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit kayıtları silinemez",
    )


@router.patch("/{audit_id}", include_in_schema=False)
def update_audit_forbidden(_audit_id: int, _user: User = Depends(get_current_user)) -> None:
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="Audit kayıtları değiştirilemez",
    )
