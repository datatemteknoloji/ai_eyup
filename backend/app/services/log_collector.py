"""
Log Collector - Sunuculardan SSH ile warning/error/critical log toplar,
SystemEvent tablosuna kaydeder.

Gürültü azaltma kuralları:
  - LOG_MIN_OCCURRENCES: kritik log event oluşabilmesi için minimum tekrar sayısı
  - LEARNING_MODE_HOURS: sistem ilk başladığında bu kadar saat sadece veri toplar,
    alarm üretmez (baseline öğrenir)
"""
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.server import Server
from app.models.event import SystemEvent
from app.services.incident_auto import auto_create_or_link_incident
from app.services.platform_scope import is_linux_server
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

# ── Gürültü azaltma sabitleri ────────────────────────────────────────────────
# Bir log satırının CRITICAL event oluşturabilmesi için kaç kez görülmesi gerekir
LOG_MIN_OCCURRENCES_CRITICAL = 3   # kritik için min 3x
LOG_MIN_OCCURRENCES_WARNING  = 2   # warning için min 2x

# Log event'lerini "öğrenme" için saydığımız pencere (saat)
LOG_LEARNING_WINDOW_HOURS = 24

def _build_journald_cmd(since_hours: int = 2) -> str:
    return (
        f"journalctl -p 4 --since '{since_hours} hours ago' --no-pager "
        "--output=short-iso 2>/dev/null | tail -500"
    )

def _build_syslog_cmd(since_hours: int = 2) -> str:
    mins = since_hours * 60
    return (
        "grep -E '(WARNING|ERROR|CRITICAL|FAULT|FAILED|error|warning|critical|fault|failed)' "
        "/var/log/messages /var/log/syslog /var/log/secure 2>/dev/null | "
        f"awk -v d=\"$(date -d '{mins} minutes ago' '+%b %d %H:%M' 2>/dev/null || "
        f"date -v-{mins}M '+%b %d %H:%M')\" '$0 > d' | tail -300"
    )

JOURNALD_CMD = _build_journald_cmd(2)
SYSLOG_CMD = _build_syslog_cmd(2)

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
    line_lower = line.lower()
    if any(k in line_lower for k in ['error', 'err ', ' err', 'fault', 'failed', 'critical', 'crit']):
        return "error", "General Error"
    if any(k in line_lower for k in ['warning', 'warn ']):
        return "warning", "General Warning"
    return "warning", "General"


_SKIP_PATTERNS = [
    "-- Logs begin at", "-- No entries --", "-- Reboot --", "-- Boot ",
    "Logs begin at", "journalctl: ", "Selected fields:", "lines 1-",
    "(END)", "-- Journal begins",
]


def _is_meta_line(line: str) -> bool:
    stripped = line.strip()
    for pat in _SKIP_PATTERNS:
        if pat in stripped:
            return True
    if stripped.startswith("-- ") and stripped.endswith(" --"):
        return True
    if len(stripped) < 15:
        return True
    return False


# Sıra önemli: önce spesifik (UUID, IP, hex, addr), sonra genel sayı
_NORMALIZE_PATTERNS = [
    (re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), '<UUID>'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '<IP>'),
    (re.compile(r'\b0x[0-9a-fA-F]+\b'), '<HEX>'),
    (re.compile(r'\b[0-9a-fA-F]{10,}\b'), '<HEX>'),
    # USB/PCI port: "11-2", "3-1.2", "0000:03:00.0"
    (re.compile(r'\b\d+[:\-]\d+(?:[:\-.]\d+)+\b'), '<ADDR>'),
    # Genel tamsayı (negatif dahil: error -62)
    (re.compile(r'-?\b\d+\b'), '<N>'),
    (re.compile(r'T\d{2}:\d{2}:\d{2}'), 'T<TIME>'),
    (re.compile(r'\d{4}-\d{2}-\d{2}'), '<DATE>'),
]


def _strip_log_prefix(msg: str) -> str:
    """Timestamp, hostname ve process prefix'lerini soy; sadece mesaj kısmını döndür."""
    # journalctl short-iso: "2024-01-01T12:00:00+0300 hostname proc[pid]: message"
    m = re.match(r'\S+T\S+\s+\S+\s+(.+)', msg)
    if m:
        msg = m.group(1)
    # syslog: "Jan  1 12:00:00 hostname message"
    m2 = re.match(r'\w+\s+\d+\s+\d+:\d+:\d+\s+\S+\s+(.+)', msg)
    if m2:
        msg = m2.group(1)
    # Satır hâlâ "hostname service: ..." formatında başlıyorsa hostname'i soy.
    # Kural: ilk kelimede ":" yoksa ve ikinci "kelime:" varsa → hostname'dir.
    m3 = re.match(r'^(\S+)\s+(\S+:.+)', msg)
    if m3 and ':' not in m3.group(1):
        msg = m3.group(2)
    # process[pid]: kısmını da soy
    msg = re.sub(r'^\S+\[\d+\]:\s*', '', msg)
    return msg.strip()


def _normalize_for_dedup(line: str) -> str:
    """
    Sayısal/değişken kısımları <N>, <IP>, <UUID>, <ADDR> vb. ile değiştirerek
    benzer log satırlarını tek bir key'e düşürür.

    Örnek:
      "usb 11-2: device not accepting address 101, error -62"
      "usb 11-3: device not accepting address 102, error -62"
      → ikisi de: "usb <addr>: device not accepting address <n>, error <n>"
    """
    msg = _strip_log_prefix(line)
    for pattern, replacement in _NORMALIZE_PATTERNS:
        msg = pattern.sub(replacement, msg)
    return msg.lower().strip()


def _parse_log_lines(output: str) -> List[Dict[str, Any]]:
    """Log satirlarini parse et, benzer tekrarlari normalize ederek uniq yap."""
    entries = []
    seen: set = set()
    seen_counts: dict = {}
    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue
        if _is_meta_line(line):
            continue
        if len(line) > 1000:
            line = line[:1000] + "..."
        severity, category = _detect_severity_and_category(line)
        key = _normalize_for_dedup(line)
        if key in seen:
            seen_counts[key] = seen_counts.get(key, 1) + 1
            continue
        seen.add(key)
        seen_counts[key] = 1
        entries.append({
            "line": line,
            "severity": severity,
            "category": category,
        })
    # Tekrar sayısını ilk örneğe ekle
    for entry in entries:
        k = _normalize_for_dedup(entry["line"])
        cnt = seen_counts.get(k, 1)
        if cnt > 1:
            entry["line"] = entry["line"] + " [x" + str(cnt) + "]"
    return entries


def collect_server_logs(
    server: Server,
    global_cred: Optional[GlobalCredential] = None,
    since_hours: int = 2,
) -> List[Dict[str, Any]]:
    """Bir sunucudan SSH ile log topla. since_hours: kac saatlik gecmis log."""
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
        journald_cmd = _build_journald_cmd(since_hours)
        syslog_cmd = _build_syslog_cmd(since_hours)
        ok, out, err = ssh.execute_command(journald_cmd)
        if ok and out.strip():
            logs = _parse_log_lines(out)
        else:
            ok2, out2, _ = ssh.execute_command(syslog_cmd)
            if ok2 and out2.strip():
                logs = _parse_log_lines(out2)
    finally:
        ssh.close()

    return logs


def _clean_title_for_storage(line: str) -> str:
    """Title olarak kaydedilecek satırdan timestamp ve hostname prefix soyar."""
    return _strip_log_prefix(line)


def save_logs_to_db(db: Session, server: Server, logs: List[Dict[str, Any]], since_hours: int = 2) -> int:
    """Toplanan loglari SystemEvent tablosuna kaydet.

    Ayni normalize key ile kayit varsa yeni kayit acmaz, mevcut kaydın last_seen
    alanini gunceller. Boylece "Son Olusum" zamani gercek son gorulme zamanini gosterir.
    """
    if not logs:
        return 0

    since = datetime.utcnow() - timedelta(hours=max(since_hours + 1, 25))
    existing_rows = db.query(SystemEvent.id, SystemEvent.title).filter(
        SystemEvent.server_id == server.id,
        SystemEvent.created_at >= since,
        SystemEvent.event_type == "log_entry"
    ).all()
    # norm_key -> event id mapping
    existing_map: dict = {_normalize_for_dedup(e[1])[:120]: e[0] for e in existing_rows}

    now = datetime.utcnow()
    saved = 0
    updated_ids: set = set()

    for log in logs:
        raw_line = log["line"]
        clean_title = _clean_title_for_storage(raw_line)[:200]
        norm_key = _normalize_for_dedup(raw_line)[:120]

        if norm_key in existing_map:
            eid = existing_map[norm_key]
            if eid not in updated_ids:
                # occurrence_count artır
                db.query(SystemEvent).filter(SystemEvent.id == eid).update(
                    {
                        "last_seen": now,
                        "occurrence_count": SystemEvent.occurrence_count + 1,
                    },
                    synchronize_session=False,
                )
                updated_ids.add(eid)
            continue

        severity = log["severity"]

        # ── Öğrenme modu: ilk LOG_LEARNING_WINDOW_HOURS saatte kritik basma ──
        # Bu pencerede kaç farklı log tipi gördük? Az veri varsa warning'e düşür
        learning_since = now - timedelta(hours=LOG_LEARNING_WINDOW_HOURS)
        log_count_in_window = db.query(SystemEvent).filter(
            SystemEvent.server_id == server.id,
            SystemEvent.event_type == "log_entry",
            SystemEvent.created_at >= learning_since,
        ).count()

        if log_count_in_window < 50:
            # Yeterli veri yok — öğrenme modu, kritikleri warning'e düşür
            if severity == "critical":
                severity = "warning"
                logger.debug(
                    f"[LogCollector] Öğrenme modu: {server.name} critical→warning "
                    f"(sadece {log_count_in_window} log var)"
                )

        # ── Minimum tekrar filtresi: ilk görüldüğünde sadece kaydedilir ──────
        # occurrence_count 1 olarak başlar; tekrar görülünce yükselir.
        # OpsCenter sadece yeterli tekrarı olan olayları gösterir.
        event = SystemEvent(
            server_id=server.id,
            event_type="log_entry",
            severity=severity,
            source="log_collector",
            title=clean_title,
            description=raw_line,
            raw_data={
                "platform": "linux",
                "category": log["category"],
                "collected_at": now.isoformat(),
                "min_occurrences_critical": LOG_MIN_OCCURRENCES_CRITICAL,
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
    # Critical/emergency log eventler -> otomatik incident
    if saved > 0:
        # commit sonrası oluşan eventleri bul ve auto-incident kontrol et
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.server_id == server.id,
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(['critical', 'emergency'])
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning(f'[AutoIncident] event #{ev.id} hatasi: {exc}')
    return saved


def collect_all_servers_logs(db: Session, only_ai_ready: bool = False, since_hours: int = 2) -> Dict[str, Any]:
    """Tum ONLINE sunuculardan SSH ile log topla. since_hours=168 ile 7 gunluk backfill yapilabilir."""
    q = db.query(Server).filter(Server.status.in_(["ONLINE", "WARNING"]))
    if only_ai_ready:
        q = q.filter(Server.ai_ready == True)
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()
    servers = q.all()
    servers = [s for s in servers if is_linux_server(s)]

    total_saved = 0
    server_results = []

    for srv in servers:
        try:
            logs = collect_server_logs(srv, global_cred, since_hours=since_hours)
            if logs:
                saved = save_logs_to_db(db, srv, logs, since_hours=since_hours)
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
