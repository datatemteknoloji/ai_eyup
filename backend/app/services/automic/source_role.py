"""Automic kaynak DB rol bilgisi (V$DATABASE) — bilgilendirme; erişimi engellemez.

Kaynak türü (primary / standby / kopya) varsayılmaz. Kurulumda gözlemlenen rol
saklanır; periyodik kontrol sapmada uyarı üretir ama toplama/SELECT devam eder.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.audit import record_audit

from .defaults import effective_settings
from .source.base import SourceError
from .source.factory import build_source

logger = logging.getLogger(__name__)

PRIMARY_WARNING = (
    "Canlı primary veritabanı; sorgular Automic performansını etkileyebilir. "
    "Kurulumu tamamlamak için açık onay gerekir."
)

ROLE_CHECK_DEFAULT_SEC = 15 * 60


def role_display(role: Optional[str], *, known: bool = True) -> str:
    if not known or not role:
        return "bilinmiyor"
    return str(role)


def read_role_from_source(src) -> Dict[str, Any]:
    """Kaynak adaptöründen rol oku; yoksa bilinmiyor."""
    if hasattr(src, "read_database_role"):
        info = src.read_database_role() or {}
        return {
            "database_role": info.get("database_role"),
            "open_mode": info.get("open_mode"),
            "role_known": bool(info.get("role_known")),
        }
    return {"database_role": None, "open_mode": None, "role_known": False}


def enrich_test_details(details: Dict[str, Any]) -> Dict[str, Any]:
    """test_connection details → UI alanları."""
    out = dict(details or {})
    role = out.get("database_role")
    known = out.get("role_known")
    if known is None:
        known = role is not None
    out["role_known"] = bool(known)
    out["database_role_display"] = role_display(role, known=bool(known))
    out["open_mode_display"] = role_display(out.get("open_mode"), known=bool(known and out.get("open_mode")))
    role_u = (role or "").upper()
    out["primary_warning"] = role_u == "PRIMARY"
    out["requires_primary_ack"] = role_u == "PRIMARY"
    return out


def require_primary_ack_or_raise(*, database_role: Optional[str], primary_ack: bool) -> None:
    from fastapi import HTTPException

    if (database_role or "").upper() == "PRIMARY" and not primary_ack:
        raise HTTPException(
            422,
            "Kaynak DATABASE_ROLE=PRIMARY. Canlı primary veritabanı; sorgular Automic "
            "performansını etkileyebilir. Kurulumu tamamlamak için açık onay (primary_ack) gerekli.",
        )


def build_source_info(
    role_info: Dict[str, Any],
    *,
    primary_ack: bool = False,
    ack_user: Optional[str] = None,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    role = role_info.get("database_role")
    known = bool(role_info.get("role_known"))
    prev = previous or {}
    info: Dict[str, Any] = {
        "installed_database_role": role,
        "installed_open_mode": role_info.get("open_mode"),
        "installed_role_known": known,
        "installed_at": prev.get("installed_at") or now,
        "last_database_role": role,
        "last_open_mode": role_info.get("open_mode"),
        "last_role_known": known,
        "last_role_check_at": now,
        "role_drift": False,
        "role_drift_message": None,
    }
    if (role or "").upper() == "PRIMARY" and primary_ack:
        info["primary_ack"] = True
        info["primary_ack_by"] = ack_user
        info["primary_ack_at"] = now
    elif prev.get("primary_ack"):
        info["primary_ack"] = prev.get("primary_ack")
        info["primary_ack_by"] = prev.get("primary_ack_by")
        info["primary_ack_at"] = prev.get("primary_ack_at")
    return info


def check_system_role(db: Session, system) -> Dict[str, Any]:
    """Periyodik rol kontrolü. Sapmada erişimi DURDURMAZ; uyarı + audit + settings güncellemesi."""
    st = effective_settings(system.settings)
    prev = dict((st.get("source_info") or {}))
    try:
        with build_source(system) as src:
            role_info = read_role_from_source(src)
    except SourceError as exc:
        logger.warning("Automic kaynak rol kontrolü başarısız [%s]: %s", system.name, exc)
        return {"ok": False, "error": str(exc), "system_id": system.id}

    now = datetime.now(timezone.utc).isoformat()
    cur_role = role_info.get("database_role")
    installed = prev.get("installed_database_role")
    drift = False
    drift_msg = None
    if prev.get("installed_role_known") and role_info.get("role_known") and installed and cur_role:
        if str(installed).upper() != str(cur_role).upper():
            drift = True
            drift_msg = (
                f"Kaynak DATABASE_ROLE değişti: kurulumda '{installed}', şimdi '{cur_role}'. "
                "Erişim devam ediyor; performans/güncellik etkisini kontrol edin."
            )
            logger.warning("Automic kaynak rol sapması [%s]: %s → %s", system.name, installed, cur_role)
            try:
                record_audit(
                    db, category="automic", action="source_role_drift", status="warning",
                    actor="system",
                    summary=f"Automic kaynak rol sapması: {system.name}",
                    target_type="automic_system", target_id=system.id,
                    detail={"installed": installed, "current": cur_role,
                            "open_mode": role_info.get("open_mode")},
                )
            except Exception as _e:
                note_error("source_role.check_system_role", _e)
            # Yönetici bildirimi: audit + logger (ayrı bildirim kanalı yoksa)
            logger.error(
                "YÖNETİCİ UYARISI: Automic sistemi '%s' kaynak rolü değişti (%s → %s). Erişim kesilmedi.",
                system.name, installed, cur_role,
            )

    info = {
        **prev,
        "last_database_role": cur_role,
        "last_open_mode": role_info.get("open_mode"),
        "last_role_known": bool(role_info.get("role_known")),
        "last_role_check_at": now,
        "role_drift": drift,
        "role_drift_message": drift_msg,
    }
    # installed_* yoksa ilk kontrolde doldur
    if "installed_database_role" not in prev and "installed_at" not in prev:
        info["installed_database_role"] = cur_role
        info["installed_open_mode"] = role_info.get("open_mode")
        info["installed_role_known"] = bool(role_info.get("role_known"))
        info["installed_at"] = now

    settings = dict(system.settings or {})
    settings["source_info"] = info
    system.settings = settings
    db.commit()
    return {"ok": True, "system_id": system.id, "role_drift": drift, "source_info": info}


def run_role_checks(db: Session) -> Dict[int, Any]:
    from app.models.automic import AutomicSystem

    out: Dict[int, Any] = {}
    for s in db.query(AutomicSystem).filter(AutomicSystem.enabled.is_(True)).all():
        if (s.source_type or "").lower() not in ("db_oracle", "fake"):
            continue
        try:
            out[s.id] = check_system_role(db, s)
        except Exception as exc:
            db.rollback()
            out[s.id] = {"ok": False, "error": str(exc)}
            logger.warning("Automic rol kontrolü [%s]: %s", s.name, exc)
    return out


def source_info_public(settings: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    info = (settings or {}).get("source_info")
    if not info:
        return None
    return {
        "installed_database_role": info.get("installed_database_role"),
        "installed_open_mode": info.get("installed_open_mode"),
        "installed_role_display": role_display(
            info.get("installed_database_role"),
            known=bool(info.get("installed_role_known", info.get("installed_database_role") is not None)),
        ),
        "last_database_role": info.get("last_database_role"),
        "last_open_mode": info.get("last_open_mode"),
        "last_role_display": role_display(
            info.get("last_database_role"),
            known=bool(info.get("last_role_known", info.get("last_database_role") is not None)),
        ),
        "last_role_check_at": info.get("last_role_check_at"),
        "role_drift": bool(info.get("role_drift")),
        "role_drift_message": info.get("role_drift_message"),
        "primary_ack": bool(info.get("primary_ack")),
        "primary_ack_by": info.get("primary_ack_by"),
        "primary_ack_at": info.get("primary_ack_at"),
    }
