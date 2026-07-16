"""
UDP Syslog alıcı — rsyslog / syslog-ng forward → SystemEvent.

RFC3164 (öncelikli) + basit RFC5424. Hostname veya kaynak IP ile Server eşleştirir.
Ayarlar: syslog_receiver_enabled, syslog_receiver_port, syslog_receiver_min_severity.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# PRI = facility * 8 + severity (0=emerg … 7=debug)
_RFC3164 = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<msg>.*)$",
    re.DOTALL,
)
_RFC5424 = re.compile(
    r"^<(?P<pri>\d{1,3})>\d+\s+"
    r"(?P<ts>\S+)\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<app>\S+)\s+"
    r"\S+\s+\S+\s+"
    r"(?P<msg>.*)$",
    re.DOTALL,
)

_SEV_NAME = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}

# UI / Ops severity: emergency+alert+critical → critical; err → error; warn → warning
_SEV_MAP = {
    0: "critical",
    1: "critical",
    2: "critical",
    3: "error",
    4: "warning",
    5: "warning",
    6: "warning",
    7: "warning",
}


def parse_syslog_datagram(data: bytes) -> Optional[dict]:
    try:
        text = data.decode("utf-8", errors="replace").strip()
    except Exception:
        return None
    if not text:
        return None

    m = _RFC3164.match(text) or _RFC5424.match(text)
    if m:
        pri = int(m.group("pri"))
        severity = pri % 8
        facility = pri // 8
        host = (m.group("host") or "").strip()
        msg = (m.group("msg") or "").strip()
        return {
            "pri": pri,
            "severity_num": severity,
            "facility": facility,
            "hostname": host,
            "message": msg or text[:500],
            "raw": text[:2000],
        }

    # PRI yoksa ham satır
    return {
        "pri": None,
        "severity_num": 4,
        "facility": 1,
        "hostname": "",
        "message": text[:500],
        "raw": text[:2000],
    }


def _resolve_server_id(db, hostname: str, peer_ip: str) -> Optional[int]:
    from app.models.server import Server
    from sqlalchemy import func, or_

    host = (hostname or "").strip().rstrip(".")
    # FQDN → short
    short = host.split(".")[0] if host else ""
    ip = (peer_ip or "").strip()

    q = db.query(Server.id)
    conds = []
    if host:
        conds.append(func.lower(Server.hostname) == host.lower())
        conds.append(func.lower(Server.name) == host.lower())
    if short and short.lower() != host.lower():
        conds.append(func.lower(Server.hostname) == short.lower())
        conds.append(func.lower(Server.name) == short.lower())
        conds.append(Server.hostname.ilike(f"{short}.%"))
    if ip:
        conds.append(Server.ip_address == ip)

    if not conds:
        return None
    row = q.filter(or_(*conds)).first()
    return int(row[0]) if row else None


def ingest_syslog_message(
    *,
    hostname: str,
    peer_ip: str,
    message: str,
    severity_num: int,
    raw: str,
    facility: int = 1,
) -> bool:
    """Tek syslog satırını SystemEvent olarak kaydet. True = yazıldı."""
    from app.core.database import ThreadSessionLocal
    from app.models.event import SystemEvent
    from app.services.log_collector import _normalize_for_dedup, _clean_title_for_storage
    from app.services.runtime_settings import get_int

    try:
        min_sev = int(get_int("syslog_receiver_min_severity") or 4)
    except Exception:
        min_sev = 4
    if severity_num > min_sev:
        return False

    db = ThreadSessionLocal()
    try:
        server_id = _resolve_server_id(db, hostname, peer_ip)
        if not server_id:
            logger.debug(
                "Syslog eşleşme yok host=%s ip=%s msg=%s",
                hostname, peer_ip, (message or "")[:80],
            )
            return False

        sev = _SEV_MAP.get(severity_num, "warning")
        title = _clean_title_for_storage(message)[:200] or message[:200]
        norm = _normalize_for_dedup(message)[:120]
        now = datetime.utcnow()

        # Son 24s aynı normalize key → occurrence artır
        since = now - timedelta(hours=24)
        existing = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.server_id == server_id,
                SystemEvent.event_type == "log_entry",
                SystemEvent.source == "syslog_receiver",
                SystemEvent.created_at >= since,
            )
            .order_by(SystemEvent.id.desc())
            .limit(80)
            .all()
        )
        for ev in existing:
            if _normalize_for_dedup(ev.title or "")[:120] == norm:
                ev.last_seen = now
                ev.occurrence_count = int(ev.occurrence_count or 1) + 1
                db.commit()
                return True

        ev = SystemEvent(
            server_id=server_id,
            event_type="log_entry",
            severity=sev,
            source="syslog_receiver",
            title=title,
            description=message[:4000],
            raw_data={
                "transport": "udp_syslog",
                "peer_ip": peer_ip,
                "hostname": hostname,
                "facility": facility,
                "severity_num": severity_num,
                "severity_name": _SEV_NAME.get(severity_num, "unknown"),
                "raw": raw[:1000],
            },
            is_acknowledged=False,
            resolved=False,
            last_seen=now,
            occurrence_count=1,
        )
        db.add(ev)
        db.commit()
        return True
    except Exception as e:
        logger.warning("Syslog ingest hata: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        db.close()


class _SyslogProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self._loop = asyncio.get_event_loop()
        self._accepted = 0
        self._dropped = 0

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        peer_ip = addr[0] if addr else ""
        parsed = parse_syslog_datagram(data)
        if not parsed:
            self._dropped += 1
            return

        def _work():
            return ingest_syslog_message(
                hostname=parsed.get("hostname") or "",
                peer_ip=peer_ip,
                message=parsed.get("message") or "",
                severity_num=int(parsed.get("severity_num") or 4),
                raw=parsed.get("raw") or "",
                facility=int(parsed.get("facility") or 1),
            )

        fut = self._loop.run_in_executor(None, _work)

        def _done(f):
            try:
                ok = f.result()
                if ok:
                    self._accepted += 1
                else:
                    self._dropped += 1
            except Exception:
                self._dropped += 1

        fut.add_done_callback(_done)


class SyslogReceiverManager:
    """Ayar değişince yeniden bağlanabilen UDP syslog dinleyici."""

    def __init__(self):
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[_SyslogProtocol] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start_supervisor(self):
        self._running = True
        logger.info("Syslog receiver supervisor started")
        while self._running:
            try:
                await self._reconcile()
            except Exception as e:
                logger.error("Syslog receiver reconcile: %s", e)
            await asyncio.sleep(15)

    async def stop(self):
        self._running = False
        await self._close_socket()

    async def _reconcile(self):
        from app.services.runtime_settings import get_bool, get_int

        enabled = False
        port = 5514
        try:
            enabled = bool(get_bool("syslog_receiver_enabled"))
            port = int(get_int("syslog_receiver_port") or 5514)
        except Exception:
            pass

        if not enabled:
            if self._transport:
                logger.info("Syslog alıcı kapalı — socket kapatılıyor")
                await self._close_socket()
            return

        # Port değiştiyse yeniden aç
        current_port = None
        if self._transport:
            try:
                sock = self._transport.get_extra_info("sockname")
                if sock:
                    current_port = sock[1]
            except Exception:
                current_port = None

        if self._transport and current_port == port:
            return

        await self._close_socket()
        loop = asyncio.get_event_loop()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _SyslogProtocol(),
                local_addr=("0.0.0.0", port),
            )
            self._transport = transport
            self._protocol = protocol
            logger.warning("Syslog UDP alıcı dinliyor: 0.0.0.0:%s", port)
        except OSError as e:
            logger.error("Syslog UDP bind başarısız port=%s: %s", port, e)

    async def _close_socket(self):
        if self._transport:
            try:
                self._transport.close()
            except Exception:
                pass
        self._transport = None
        self._protocol = None


syslog_receiver_manager = SyslogReceiverManager()
