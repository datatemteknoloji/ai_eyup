"""
İstek başına kullanıcı rolü + modül atamaları (kısa TTL önbellekli).

Global modül-erişim middleware'i (``main._require_auth_middleware``) ve
WebSocket uçları bu yardımcıyı kullanır. Önbellek süresi kısadır; modül
ataması değişince en geç ``TTL`` saniye içinde etkili olur.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional, Tuple

TTL_SECONDS = 5.0
_MAX_ENTRIES = 2048


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str
    modules: FrozenSet[str]


_lock = threading.Lock()
_cache: Dict[Tuple[str, Any], Tuple[float, Optional[Principal]]] = {}


def invalidate() -> None:
    with _lock:
        _cache.clear()


def _load(uid: Optional[int], sub: Optional[str]) -> Optional[Principal]:
    from app.core.database import SessionLocal
    from app.models.module import UserModule
    from app.models.user import User

    db = SessionLocal()
    try:
        user = None
        if uid is not None:
            user = db.query(User).filter(User.id == uid).first()
        if user is None and sub:
            user = db.query(User).filter(User.username == sub).first()
        if user is None or not user.is_active:
            return None
        mods = frozenset(
            r[0] for r in db.query(UserModule.module_id).filter(UserModule.user_id == user.id).all()
        )
        return Principal(user.id, user.username, user.role or "viewer", mods)
    finally:
        db.close()


def principal_from_payload(payload: dict) -> Optional[Principal]:
    """JWT payload → Principal (aktif değilse / bulunamazsa None)."""
    uid = payload.get("uid")
    sub = payload.get("sub")
    key = ("u", uid if uid is not None else sub)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]
    p = _load(uid, sub)
    with _lock:
        if len(_cache) >= _MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (now, p)
    return p
