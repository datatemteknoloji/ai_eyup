"""Automic arka plan adımı — background_tasks her dakika bir kez çağırır (thread)."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .database import automic_db_available, get_automic_thread_session

logger = logging.getLogger(__name__)

_last: Dict[str, float] = {}
_INTERVALS = {
    "quota": 15 * 60,
    "aggregate": 60 * 60,
    "retention": 6 * 3600,
    "discovery": 3600,
    "source_role": 15 * 60,  # V$DATABASE rol kontrolü (erişimi kesmez)
}
_db_down_logged = False


def _due(kind: str) -> bool:
    now = time.time()
    if now - _last.get(kind, 0) >= _INTERVALS[kind]:
        _last[kind] = now
        return True
    return False


def has_systems() -> bool:
    db = get_automic_thread_session()
    if db is None:
        return False
    try:
        from app.models.automic import AutomicSystem
        return db.query(AutomicSystem.id).first() is not None
    finally:
        db.close()


def step() -> Dict[str, Any]:
    """True dönerse DB erişilebilir. Sistem yoksa hiçbir şey yapmaz."""
    global _db_down_logged
    if not automic_db_available():
        if not _db_down_logged:
            logger.info("Automic DB erişilemiyor — Automic toplayıcı beklemede")
            _db_down_logged = True
        return {"db": False}
    _db_down_logged = False
    if not has_systems():
        return {"db": True, "systems": 0}

    from . import collector, retention, service

    out: Dict[str, Any] = {"db": True, "collect": collector.tick()}
    for kind in ("quota", "aggregate", "retention"):
        if _due(kind):
            out[kind] = retention.run_maintenance(kind)
    if _due("discovery"):
        db = get_automic_thread_session()
        if db is not None:
            try:
                out["discovery"] = service.run_daily_discovery(db)
            finally:
                db.close()
    if _due("source_role"):
        db = get_automic_thread_session()
        if db is not None:
            try:
                from .source_role import run_role_checks
                out["source_role"] = run_role_checks(db)
            finally:
                db.close()
    return out
