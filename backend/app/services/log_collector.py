"""
Log Collector - Sunuculardan SSH ile warning/error/critical log toplar,
SystemEvent tablosuna kaydeder.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.server import Server
from app.models.event import SystemEvent
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

# Journald priority seviyeleri: 0=emerg,1=alert,2=crit,3=err,4=warning
# Biz 4 (warning) ve ustunu aliyoruz
JOURNALD_CMD = (
    "journalctl -p 4 --since '10 minutes ago' --no-pager "
    "--output=short-iso 2>/dev/null | tail -200"
)

# Syslog fallback
SYSLOG_CMD = (
    "grep -E '(WARNING|ERROR|CRITICAL|FAULT|FAILED|error|warning|critical|fault|failed)' "
    "/var/log/messages /var/log/syslog /var/log/secure 2>/dev/null | "
    "awk -v d=\"$(date -d '10 minutes ago' '+%b %d %H:%M' 2>/dev/null || "
    "date -v-10M '+%b %d %H:%M')\" '$0 > d' | tail -100"
)

# Kernel OOM / Disk / HW hata pattern'leri
CRITICAL_PATTERNS = [
    (re.compile(r'Out of memory|oom.kill|oom-kill', re.I), "OOM Killer", "critical"),
    (re.compile(r'kernel panic', re.I), "Kernel Panic", "critical"),
    (re.compile(r'EXT\d-fs error|XFS.*error|filesystem.*read.only', re.I), "Filesystem Error", "critical"),
    (re.compile(r'I/O error|blk_update_request.*error|medium error', re.I), "Disk I/O Error", "critical"),
    (re.compile(r'NFS.*timed out|NFS.*server not responding', re.I), "NFS Timeout", "critical"),
    (re.compile(r'segfault|segmentation fault', re.I), "Segmentation Fault", "critical"),
    (re.compile(r'CPU\d+.*hardware error|mce.*bank', re.I), "CPU Hardware Error", "critical"),
    (re.compile(r'multipathd.*failed|path.*failed', re.I), "Multipath Failure", "critical"),
]

WARNING_PATTERNS = [
    (re.compile(r'authentication failure|Failed password|Invalid user', re.I), "Auth Failure", "warning"),
    (re.compile(r'Connection refused|Connection timed out', re.I), "Connection Issue", "warning"),
    (re.compile(r'RAID.*degraded|md:.*failed', re.I), "RAID Degraded", "warning"),
    (re.compile(r'swap.*low|memory.*low|no space left', re.I), "Resource Low", "warning"),
    (re.compile(r'service.*failed|unit.*failed|systemd.*failed', re.I), "Service Failed", "warning"),
    (re.compile(r'firewalld|SELinux.*denied|AVC.*denied', re.I), "Security Event", "warning"),
    (re.compile(r'chrony.*offset|time.*sync.*lost', re.I), "Time Sync Issue", "warning"),
    (re.compile(r'certificate.*expire|SSL.*error|TLS.*error', re.I), "SSL/TLS Issue", "warning"),
]


def _detect_severity_and_category(line: str):
    for pattern, category, severity in CRITICAL_PATTERNS:
        if pattern.search(line):
            return severity, category
    for pattern, category, severity in WARNING_PATTERNS:
        if pattern.search(line):
            return severity, category
    # Genel seviye tespiti
    line_lower = line.lower()
    if any(k in line_lower for k in ['error', 'err ', ' err', 'fault', 'failed', 'critical', 'crit']):
        return "error", "General Error"
    if any(k in line_lower for k in ['warning', 'warn ']):
        return "warning", "General Warning"
    return "warning", "General"


def _parse_log_lines(output: str) -> List[Dict[str, Any]]:
    """Log satirlarini parse et, tekrarlari filtrele."""
    entries = []
    seen = set()
    for line in output.split('\n'):
        line = line.strip()
        if not line or len(line) < 10:
            continue
        # Cok uzun satirlari kisalt
        if len(line) > 1000:
            line = line[:1000] + "..."
        severity, category = _detect_severity_and_category(line)
        # Tekrar kontrolu (ilk 80 karakter hash)
        key = line[:80]
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "line": line,
            "severity": severity,
            "category": category,
        })
    return entries


def collect_server_logs(
    server: Server,
    global_cred: Optional[GlobalCredential] = None
) -> List[Dict[str, Any]]:
    """Bir sunucudan SSH ile log topla."""
    conn = server.connection_config or {}
    username = conn.get("username") or (global_cred.username if global_cred else None)
    password = conn.get("password") or (global_cred.password if global_cred else None)
    private_key = conn.get("private_key") or (global_cred.private_key if global_cred else None)
    port = conn.get("port", 22) or 22
    sudo_password = conn.get("sudo_password") or password

    if not username or not (server.ip_address or server.hostname):
        return []

    ssh = SSHManager(
        host=server.ip_address or server.hostname,
        username=username, password=password,
        private_key=private_key, port=port,
        sudo_password=sudo_password,
    )
    if not ssh.connect():
        return []

    logs = []
    try:
        # 1. journalctl dene
        ok, out, err = ssh.execute_command(JOURNALD_CMD)
        if ok and out.strip():
            logs = _parse_log_lines(out)
        else:
            # 2. Syslog fallback
            ok2, out2, _ = ssh.execute_command(SYSLOG_CMD)
            if ok2 and out2.strip():
                logs = _parse_log_lines(out2)
    finally:
        ssh.close()

    return logs


def save_logs_to_db(db: Session, server: Server, logs: List[Dict[str, Any]]) -> int:
    """Toplanan loglari SystemEvent tablosuna kaydet (duplicate atla)."""
    if not logs:
        return 0

    # Son 15 dakikadaki mevcut event'leri al (duplicate kontrolu)
    since = datetime.utcnow() - timedelta(minutes=15)
    existing = db.query(SystemEvent.title).filter(
        SystemEvent.server_id == server.id,
        SystemEvent.created_at >= since,
        SystemEvent.event_type == "log_entry"
    ).all()
    existing_titles = {e[0][:80] for e in existing}

    saved = 0
    for log in logs:
        title = log["line"][:200]
        if title[:80] in existing_titles:
            continue
        event = SystemEvent(
            server_id=server.id,
            event_type="log_entry",
            severity=log["severity"],
            source="log_collector",
            title=title,
            description=log["line"],
            raw_data={
                "category": log["category"],
                "collected_at": datetime.utcnow().isoformat(),
            },
            is_acknowledged=False,
            resolved=False,
        )
        db.add(event)
        existing_titles.add(title[:80])
        saved += 1

    if saved > 0:
        db.commit()
    return saved


def collect_all_servers_logs(db: Session) -> Dict[str, Any]:
    """Tum ONLINE AI-ready sunuculardan log topla."""
    servers = db.query(Server).filter(
        Server.ai_ready == True,
        Server.status == "ONLINE"
    ).all()

    global_cred = db.query(GlobalCredential).filter(
        GlobalCredential.is_default == True
    ).first()
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    total_saved = 0
    server_results = []

    for srv in servers:
        try:
            logs = collect_server_logs(srv, global_cred)
            if logs:
                saved = save_logs_to_db(db, srv, logs)
                total_saved += saved
                critical_count = sum(1 for l in logs if l["severity"] == "critical")
                error_count = sum(1 for l in logs if l["severity"] == "error")
                warning_count = sum(1 for l in logs if l["severity"] == "warning")
                if saved > 0:
                    logger.warning(
                        f"[{srv.name}] {saved} yeni log: "
                        f"{critical_count} kritik, {error_count} hata, {warning_count} uyari"
                    )
                    server_results.append({
                        "server": srv.name,
                        "saved": saved,
                        "critical": critical_count,
                        "error": error_count,
                        "warning": warning_count,
                    })
        except Exception as e:
            logger.error(f"Log collection failed {srv.name}: {e}")

    return {
        "total_servers": len(servers),
        "servers_with_logs": len(server_results),
        "total_saved": total_saved,
        "details": server_results,
    }
