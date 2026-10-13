"""Hostname gösterim sırası ve elle atama.

Sıra: elle agent → HOST_HostName → IP eşlemesi → ters DNS (kapalı) → yalnız IP.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.automic import AutomicHostnameOverride

logger = logging.getLogger(__name__)

SRC_MANUAL_AGENT = "manual_agent"
SRC_AUTOMIC = "automic"
SRC_IP_MAP = "ip_map"
SRC_DNS = "dns"
SRC_IP_ONLY = "ip_only"

SRC_LABEL_TR = {
    SRC_MANUAL_AGENT: "elle atandı",
    SRC_AUTOMIC: "Automic",
    SRC_IP_MAP: "IP eşlemesi",
    SRC_DNS: "DNS",
    SRC_IP_ONLY: "yalnız IP",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _overrides(db: Session, system_id: int) -> Dict[Tuple[str, str], str]:
    rows = db.query(AutomicHostnameOverride).filter(
        AutomicHostnameOverride.system_id == int(system_id)
    ).all()
    return {(r.kind, r.key): r.hostname for r in rows}


def resolve_hostname(
    *,
    agent_name: Optional[str] = None,
    ip: Optional[str] = None,
    hostname_automic: Optional[str] = None,
    overrides: Optional[Dict[Tuple[str, str], str]] = None,
    settings: Optional[Dict[str, Any]] = None,
    allow_dns: Optional[bool] = None,
) -> Dict[str, Optional[str]]:
    """{hostname, source, source_label, automic_hostname, manual_hostname}."""
    ov = overrides or {}
    manual = ov.get(("agent", (agent_name or "").strip())) if agent_name else None
    if manual:
        return {
            "hostname": manual,
            "source": SRC_MANUAL_AGENT,
            "source_label": SRC_LABEL_TR[SRC_MANUAL_AGENT],
            "automic_hostname": hostname_automic or None,
            "manual_hostname": manual,
        }
    if hostname_automic and str(hostname_automic).strip():
        return {
            "hostname": str(hostname_automic).strip(),
            "source": SRC_AUTOMIC,
            "source_label": SRC_LABEL_TR[SRC_AUTOMIC],
            "automic_hostname": str(hostname_automic).strip(),
            "manual_hostname": None,
        }
    ip_s = (ip or "").strip()
    if ip_s:
        mapped = ov.get(("ip", ip_s))
        if mapped:
            return {
                "hostname": mapped,
                "source": SRC_IP_MAP,
                "source_label": SRC_LABEL_TR[SRC_IP_MAP],
                "automic_hostname": None,
                "manual_hostname": None,
            }
        infra = (settings or {}).get("infrastructure") or {}
        dns_on = allow_dns if allow_dns is not None else bool(infra.get("reverse_dns_enabled"))
        if dns_on:
            try:
                host, _, _ = socket.gethostbyaddr(ip_s)
                if host:
                    return {
                        "hostname": host,
                        "source": SRC_DNS,
                        "source_label": SRC_LABEL_TR[SRC_DNS],
                        "automic_hostname": None,
                        "manual_hostname": None,
                    }
            except Exception as exc:
                note_error("hostname_resolve.resolve_hostname", exc)
        return {
            "hostname": ip_s,
            "source": SRC_IP_ONLY,
            "source_label": SRC_LABEL_TR[SRC_IP_ONLY],
            "automic_hostname": None,
            "manual_hostname": None,
        }
    return {
        "hostname": None,
        "source": None,
        "source_label": None,
        "automic_hostname": None,
        "manual_hostname": None,
    }


def set_override(
    db: Session, system_id: int, kind: str, key: str, hostname: str, *,
    updated_by: Optional[str] = None,
) -> AutomicHostnameOverride:
    kind = kind if kind in ("agent", "ip") else "agent"
    key = (key or "").strip()
    hostname = (hostname or "").strip()
    row = db.get(AutomicHostnameOverride, {
        "system_id": int(system_id), "kind": kind, "key": key,
    })
    if row is None:
        row = AutomicHostnameOverride(
            system_id=int(system_id), kind=kind, key=key,
            hostname=hostname[:256], updated_at=_now(), updated_by=updated_by,
        )
        db.add(row)
    else:
        row.hostname = hostname[:256]
        row.updated_at = _now()
        row.updated_by = updated_by
    return row


def delete_override(db: Session, system_id: int, kind: str, key: str) -> bool:
    row = db.get(AutomicHostnameOverride, {
        "system_id": int(system_id), "kind": kind, "key": (key or "").strip(),
    })
    if not row:
        return False
    db.delete(row)
    return True


def orphan_agent_overrides(db: Session, system_id: int, known_agents: List[str]) -> List[Dict[str, Any]]:
    known = {a.strip() for a in known_agents}
    rows = db.query(AutomicHostnameOverride).filter(
        AutomicHostnameOverride.system_id == int(system_id),
        AutomicHostnameOverride.kind == "agent",
    ).all()
    return [
        {"agent": r.key, "hostname": r.hostname, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows if r.key not in known
    ]


def load_overrides(db: Session, system_id: int) -> Dict[Tuple[str, str], str]:
    return _overrides(db, system_id)
