"""Doğrulayıcı müdahalesinde sohbet geçmişindeki asistan mesajını düzeltir (DB düzeltmesi)."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def fix_assistant_message(db, row, *, replace: Optional[str] = None, append: Optional[str] = None) -> bool:
    """Bu turdan sonra yazılan son asistan mesajını değiştirir/ekler; yoksa (akış kesildiyse) ekler.

    Gizli (ephemeral) oturumda ve oturumsuz turda hiçbir şey yazmaz.
    """
    try:
        payload = row.payload or {}
        if payload.get("ephemeral") or row.session_id is None:
            return False
        from app.models.chat_session import ChatMessage, ChatSession
        msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == row.session_id, ChatMessage.role == "assistant",
                    ChatMessage.created_at >= row.created_at)
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if msg is None:
            if replace is None and append is None:
                return False
            db.add(ChatMessage(session_id=row.session_id, role="assistant",
                               content=(replace if replace is not None else (append or "").strip()),
                               meta={"guard": "inserted"}))
        else:
            if replace is not None:
                msg.content = replace
                meta = dict(msg.meta or {})
                meta["guard"] = "replaced"
                msg.meta = meta
            elif append:
                msg.content = (msg.content or "") + append
        s = db.query(ChatSession).filter(ChatSession.id == row.session_id).first()
        if s is not None:
            from datetime import datetime, timezone
            s.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception:
        logger.warning("[ChatGuard] asistan mesajı düzeltilemedi", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return False
