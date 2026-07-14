"""
Windows Event Log toplayıcı — WinRM ile System / Application logları SystemEvent'e yazar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.event import SystemEvent
from app.models.server import Server
from app.core.encryption import decrypt_secret
from app.services.incident_auto import auto_create_or_link_incident
from app.services.platform_scope import is_windows_server
from app.services.windows.winrm_client import WinRMClient
from app.services.windows.windows_info_collector import WindowsInfoCollector

logger = logging.getLogger(__name__)

GLOBAL_WINRM_KEY = "global_winrm_credential"
LEVEL_TO_SEV = {
    "critical": "critical",
    "error": "critical",
    "warning": "warning",
    "information": "info",
    "info": "info",
    "verbose": "info",
}


def _get_global_winrm(db: Session) -> Optional[Dict[str, Any]]:
    row = db.query(AppSettings).filter(AppSettings.key == GLOBAL_WINRM_KEY).first()
    if not row or not row.value:
        return None
    try:
        data = json.loads(row.value)
        if data.get("password"):
            data["password"] = decrypt_secret(data["password"])
        return data
    except Exception:
        return None


def _build_client(server: Server, db: Session) -> Optional[WinRMClient]:
    client = WinRMClient.from_server(server)
    if client:
        return client
    gcred = _get_global_winrm(db)
    if not gcred:
        return None
    host = server.ip_address or server.hostname
    if not host:
        return None
    return WinRMClient(
        host=host,
        username=gcred["username"],
        password=gcred["password"],
        port=gcred.get("port", 5985),
        use_https=gcred.get("use_https", False),
    )


def _norm_key(provider: str, event_id: int, message: str) -> str:
    msg = re.sub(r"\d+", "N", (message or "").lower())[:120]
    return f"{provider}|{event_id}|{msg}"


def _map_severity(level: str) -> str:
    return LEVEL_TO_SEV.get((level or "").lower(), "warning")


def collect_windows_server_logs(server: Server, db: Session, count: int = 60) -> List[Dict[str, Any]]:
    client = _build_client(server, db)
    if not client:
        return []
    collector = WindowsInfoCollector(client)
    entries: List[Dict[str, Any]] = []
    for log_name in ("System", "Application"):
        try:
            rows = collector.get_event_logs(log_name=log_name, count=count, min_level=3, hours=26)
            for row in rows:
                provider = row.get("ProviderName") or log_name
                eid = row.get("Id") or 0
                msg = row.get("Message") or ""
                level = row.get("LevelDisplayName") or "Warning"
                entries.append({
                    "log_name": log_name,
                    "provider": provider,
                    "event_id": eid,
                    "message": msg,
                    "severity": _map_severity(level),
                    "time_created": row.get("TimeCreated"),
                    "norm_key": _norm_key(provider, int(eid) if eid else 0, msg),
                })
        except Exception as exc:
            logger.warning("[%s] Windows log %s: %s", server.name, log_name, exc)
    return entries


def save_windows_logs_to_db(db: Session, server: Server, logs: List[Dict[str, Any]]) -> int:
    if not logs:
        return 0

    since = datetime.utcnow() - timedelta(hours=26)
    existing = (
        db.query(SystemEvent.id, SystemEvent.title, SystemEvent.raw_data)
        .filter(
            SystemEvent.server_id == server.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.source == "windows_collector",
            SystemEvent.created_at >= since,
        )
        .all()
    )
    existing_map: Dict[str, int] = {}
    for eid, title, raw in existing:
        key = (raw or {}).get("norm_key") or hashlib.md5((title or "").encode()).hexdigest()[:16]
        existing_map[key] = eid

    now = datetime.utcnow()
    saved = 0
    updated_ids: set = set()

    for log in logs:
        norm_key = log["norm_key"]
        title = f"[{log['provider']}] Event {log['event_id']}: {(log['message'] or '')[:160]}"
        if norm_key in existing_map:
            eid = existing_map[norm_key]
            if eid not in updated_ids:
                db.query(SystemEvent).filter(SystemEvent.id == eid).update({
                    SystemEvent.last_seen: now,
                    SystemEvent.occurrence_count: SystemEvent.occurrence_count + 1,
                })
                updated_ids.add(eid)
            continue

        event = SystemEvent(
            server_id=server.id,
            event_type="log_entry",
            severity=log["severity"],
            source="windows_collector",
            title=title[:500],
            description=log["message"],
            raw_data={
                "platform": "windows",
                "category": log["provider"],
                "log_name": log["log_name"],
                "windows_event_id": log["event_id"],
                "norm_key": norm_key,
                "collected_at": now.isoformat(),
            },
            is_acknowledged=False,
            resolved=False,
            last_seen=now,
            occurrence_count=1,
        )
        db.add(event)
        existing_map[norm_key] = -1
        saved += 1

    db.commit()

    if saved > 0:
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.server_id == server.id,
            SystemEvent.source == "windows_collector",
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("[AutoIncident] Windows event #%s: %s", ev.id, exc)

    return saved


def collect_all_windows_logs(db: Session) -> Dict[str, Any]:
    servers = (
        db.query(Server)
        .filter(Server.status.in_(["ONLINE", "WARNING"]))
        .all()
    )
    servers = [s for s in servers if is_windows_server(s)]

    total_saved = 0
    details = []
    for srv in servers:
        try:
            logs = collect_windows_server_logs(srv, db)
            if logs:
                saved = save_windows_logs_to_db(db, srv, logs)
                total_saved += saved
                if saved:
                    details.append({"server": srv.name, "saved": saved})
        except Exception as exc:
            logger.error("Windows log collection failed %s: %s", srv.name, exc)

    return {
        "total_servers": len(servers),
        "servers_with_logs": len(details),
        "total_saved": total_saved,
        "details": details,
    }
