from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.core.config import get_settings
from app.models.job import AuditLog, AuditStatus


def write_audit(
    session: Session,
    *,
    action: str,
    status: AuditStatus,
    message: str = "",
    user_id: int | None = None,
    username: str = "",
    role: str = "",
    client_ip: str = "",
    target_server_id: int | None = None,
    hostname: str = "",
    ip: str = "",
    talep_id: str = "",
    job_id: int | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    output: str = "",
) -> AuditLog:
    row = AuditLog(
        user_id=user_id,
        username=username,
        role=role,
        client_ip=client_ip,
        target_server_id=target_server_id,
        hostname=hostname,
        ip=ip,
        talep_id=talep_id,
        job_id=job_id,
        action=action,
        status=status,
        message=message,
        before_state=before_state or {},
        after_state=after_state or {},
        output=output[:20000],
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    settings = get_settings()
    if settings.siem_enabled and (settings.siem_webhook_url or "").strip():
        payload = {
            "id": row.id,
            "action": row.action,
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "message": row.message,
            "username": row.username,
            "role": row.role,
            "client_ip": row.client_ip,
            "hostname": row.hostname,
            "ip": row.ip,
            "talep_id": row.talep_id,
            "job_id": row.job_id,
            "target_server_id": row.target_server_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        try:
            from app.worker import forward_audit_task

            forward_audit_task.delay(payload)
        except Exception:
            try:
                from app.services.siem import forward_audit_payload

                forward_audit_payload(payload)
            except Exception:
                pass

    return row
