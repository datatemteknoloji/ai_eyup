"""
Uygulama işlemlerini activity_logs tablosuna yazar.
VM sync, Node Exporter kurulum, SSH test vb. kullanıcı işlemleri buradan loglanır.
"""
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from app.models.activity_log import ActivityLog


def log_activity(
    db: Session,
    action_type: str,
    summary: str,
    details: Optional[Dict[str, Any]] = None,
    status: str = "success",
) -> ActivityLog:
    """
    Tek bir işlem kaydı ekler.
    action_type: vm_sync, node_exporter_install, ssh_test, page_view, server_create, vb.
    status: success, failed, running
    """
    entry = ActivityLog(
        action_type=action_type,
        summary=summary,
        details=details or {},
        status=status,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
