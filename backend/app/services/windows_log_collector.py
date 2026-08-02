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


def collect_windows_server_logs(
    server: Server, db: Session, count: int = 60, since_hours: int = 26
) -> List[Dict[str, Any]]:
    client = _build_client(server, db)
    if not client:
        return []
    collector = WindowsInfoCollector(client)
    entries: List[Dict[str, Any]] = []
    for log_name in ("System", "Application"):
        try:
            rows = collector.get_event_logs(log_name=log_name, count=count, min_level=3, hours=since_hours)
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


def save_windows_logs_to_db(
    db: Session, server: Server, logs: List[Dict[str, Any]], since_hours: int = 26
) -> int:
    if not logs:
        return 0

    since = datetime.utcnow() - timedelta(hours=since_hours)
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


def _collect_one_windows_server_job(server_id: int, since_hours: int) -> Dict[str, Any]:
    """Worker thread: kendi DB oturumu ile tek Windows sunucu log topla + kaydet."""
    from app.core.database import ThreadSessionLocal

    db = ThreadSessionLocal()
    try:
        srv = db.query(Server).filter(Server.id == server_id).first()
        if not srv:
            return {"server_id": server_id, "server": "?", "saved": 0, "ok": False}
        try:
            logs = collect_windows_server_logs(srv, db, since_hours=since_hours)
            saved = save_windows_logs_to_db(db, srv, logs, since_hours=since_hours) if logs else 0
            return {"server_id": server_id, "server": srv.name, "saved": saved, "ok": True}
        except Exception as exc:
            logger.error("Windows log collection failed %s: %s", srv.name, exc)
            return {"server_id": server_id, "server": srv.name, "saved": 0, "ok": False}
    finally:
        db.close()


def collect_all_windows_logs(
    db: Session,
    progress_cb: Optional[Any] = None,
    since_hours: int = 26,
    batch_mode: bool = True,
) -> Dict[str, Any]:
    """ONLINE/WARNING Windows sunuculardan PARALEL WinRM ile log toplar.

    NOT: Önceden bu fonksiyon sunucuları tek tek, tamamen sıralı (bir WinRM oturumu
    bitmeden diğerine geçmeden) işliyordu — 10k ölçekte (örn. 3000 Windows sunucu)
    bir tur saatlerce sürüyor, windows_log_interval_sec (varsayılan 900sn) içine
    asla sığmıyor ve arka arkaya turlar üst üste binerek backlog oluşturuyordu.
    Artık Linux log toplama (log_collector.py) ile aynı desen kullanılıyor:
    round-robin batch + ThreadPoolExecutor (her worker kendi DB oturumunu açar).
    """
    try:
        from app.services.runtime_settings import get_int
        batch_size = int(get_int("windows_log_batch_size") or 500)
    except Exception:
        batch_size = 500

    from app.services.bulk_concurrency import windows_log_workers
    from app.services.log_collector import _round_robin_batch
    from concurrent.futures import ThreadPoolExecutor, as_completed

    servers = (
        db.query(Server)
        .filter(Server.status.in_(["ONLINE", "WARNING"]))
        .all()
    )
    servers = [s for s in servers if is_windows_server(s)]
    fleet_total = len(servers)

    if batch_mode and fleet_total > batch_size:
        servers = _round_robin_batch(servers, batch_size, "windows")

    workers = windows_log_workers()
    server_ids = [s.id for s in servers]
    total = len(server_ids)

    logger.info(
        "Windows log collection start: fleet=%s batch=%s workers=%s since_hours=%s",
        fleet_total, total, workers, since_hours,
    )

    total_saved = 0
    details = []
    done = 0

    if total == 0:
        return {
            "total_servers": 0,
            "fleet_total": fleet_total,
            "servers_with_logs": 0,
            "total_saved": 0,
            "workers": workers,
            "details": [],
        }

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="win-log") as pool:
        futures = {
            pool.submit(_collect_one_windows_server_job, sid, since_hours): sid
            for sid in server_ids
        }
        for fut in as_completed(futures):
            done += 1
            saved = 0
            name = "?"
            try:
                result = fut.result()
                name = result.get("server") or "?"
                saved = int(result.get("saved") or 0)
                total_saved += saved
                if saved:
                    details.append({"server": name, "saved": saved})
            except Exception as exc:
                logger.error("Windows log worker error: %s", exc)
            if progress_cb:
                try:
                    progress_cb(done, total, name, saved)
                except Exception:
                    pass

    return {
        "total_servers": total,
        "fleet_total": fleet_total,
        "servers_with_logs": len(details),
        "total_saved": total_saved,
        "workers": workers,
        "details": details,
    }
