"""
Merkezi audit servisi — tüm alt sistemlerin denetim kaydı yazdığı tek nokta.

Tasarım ilkeleri:
  • Asla exception fırlatmaz (audit yazımı asıl işi bozmamalı).
  • Verilen Session ile yazar; yoksa kendi (thread-safe) session'ını açar.
  • Aktör; User nesnesi, kullanıcı adı string'i veya None olabilir.
"""
import logging
from typing import Any, Dict, Optional, Union

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

Actor = Union[None, str, Any]  # Any => app.models.user.User


def _actor_fields(actor: Actor) -> Dict[str, Any]:
    if actor is None:
        return {"actor_id": None, "actor_name": "system"}
    if isinstance(actor, str):
        return {"actor_id": None, "actor_name": actor}
    # User nesnesi varsayımı
    return {
        "actor_id": getattr(actor, "id", None),
        "actor_name": getattr(actor, "username", None) or "system",
    }


def record_audit(
    db: Optional[Session],
    *,
    category: str,
    action: str,
    status: str = "success",
    actor: Actor = None,
    summary: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Union[str, int]] = None,
    server_id: Optional[int] = None,
    detail: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> Optional[int]:
    """Bir audit kaydı yazar. Hata olursa sessizce yutar, asla yükseltmez."""
    own_session = False
    session = db
    try:
        if session is None:
            from app.core.database import ThreadSessionLocal
            session = ThreadSessionLocal()
            own_session = True

        fields = _actor_fields(actor)
        entry = AuditLog(
            category=category,
            action=action,
            status=status,
            summary=summary,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            server_id=server_id,
            detail=detail,
            ip_address=ip_address,
            **fields,
        )
        session.add(entry)
        session.commit()
        return entry.id
    except Exception as e:
        try:
            if session is not None:
                session.rollback()
        except Exception:
            pass
        logger.warning(f"[audit] kayıt yazılamadı ({category}.{action}): {e}")
        return None
    finally:
        if own_session and session is not None:
            try:
                session.close()
            except Exception:
                pass
