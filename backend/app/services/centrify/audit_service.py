"""Centrify audit servisi — append-only log.

Her yazma işlemi, onay ve durum değişikliği loglanır.
UPDATE/DELETE yasak — yalnızca INSERT.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    *,
    correlation_id: uuid.UUID,
    operation_id: int | None = None,
    actor_user_id: int,
    actor_username: str,
    target_type: str,
    target_name: str | None = None,
    target_ad_guid: uuid.UUID | None = None,
    action: str,
    reason: str,
    details: dict | None = None,
    approved_by_id: int | None = None,
    approved_by_name: str | None = None,
    result: str = "success",
) -> None:
    """Audit log kaydı ekle."""
    from app.models.centrify_zone import CentrifyAuditLog

    entry = CentrifyAuditLog(
        correlation_id=correlation_id,
        operation_id=operation_id,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        target_type=target_type,
        target_name=target_name,
        target_ad_guid=target_ad_guid,
        action=action,
        reason=reason,
        details=details,
        approved_by_id=approved_by_id,
        approved_by_name=approved_by_name,
        result=result,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
