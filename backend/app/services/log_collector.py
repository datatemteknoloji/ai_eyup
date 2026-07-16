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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.server import Server
from app.models.event import SystemEvent
from app.services.incident_auto import auto_create_or_link_incident
from app.services.platform_scope import platform_for_server, get_linux_module_server_id_set, get_exadata_server_id_set
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

# Round-robin cursor: periyodik batch turlarda 15k filoyu dilim dilim dolaş
_log_cursor_lock = threading.Lock()
_log_cursors: Dict[str, int] = {"linux": 0, "exadata": 0}
# ── Gürültü azaltma sabitleri ────────────────────────────────────────────────
# Bir log satırının CRITICAL event oluşturabilmesi için kaç kez görülmesi gerekir
LOG_MIN_OCCURRENCES_CRITICAL = 3   # kritik için min 3x
LOG_MIN_OCCURRENCES_WARNING  = 2   # warning için min 2x

# Log event'lerini "öğrenme" için saydığımız pencere (saat)
LOG_LEARNING_WINDOW_HOURS = 24

def _build_journald_cmd(since_hours: int = 2, priority: Optional[int] = None) -> str:
    # Beklenen deploy: SSH kullanıcısı `adm` veya `systemd-journal` grubunda.
    # Sudo gerekmez; izin hataları caller'a stderr ile döner.
    if priority is None:
        try:
            from app.services.runtime_settings import get_int
            priority = int(get_int("log_journal_priority") or 4)
        except Exception:
            priority = 4
    priority = max(0, min(7, int(priority)))
    return (
        f"journalctl -p {priority} --since '{since_hours} hours ago' --no-pager "
        "--output=short-iso | tail -800"
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
    from app.services.ssh_credentials import resolve_ssh_creds
    from app.services.runtime_settings import get_float, get_int

    creds = resolve_ssh_creds(server, global_cred=global_cred)
    if not creds.get("username") or not creds.get("host") or not creds.get("has_secret"):
        return []

    try:
        connect_t = float(get_float("log_ssh_connect_timeout_sec") or 12)
        cmd_t = int(get_int("log_ssh_cmd_timeout_sec") or 25)
    except Exception:
        connect_t, cmd_t = 12.0, 25

    ssh = SSHManager(
        host=creds["host"],
        username=creds["username"],
        password=creds.get("password"),
        private_key=creds.get("private_key"),
        port=creds.get("port") or 22,
        sudo_password=creds.get("sudo_password") or creds.get("password"),
    )
    # password + kısa timeout: tek TCP, yavaş host'u hızlı atla (15k ölçek)
    if not ssh.connect(
        retries=1,
        auth_prefer="password",
        timeout=connect_t,
        banner_timeout=connect_t,
        auth_timeout=connect_t,
    ):
        return []

    logs = []
    try:
        journald_cmd = _build_journald_cmd(since_hours)
        syslog_cmd = _build_syslog_cmd(since_hours)
        ok, out, err = ssh.execute_command(journald_cmd, cmd_timeout=cmd_t)
        used_sudo = False
        sudo_password = creds.get("sudo_password") or creds.get("password")
        if (not ok or not (out or "").strip()) and sudo_password:
            logger.info(
                "Log collection %s: journal kullanıcı yetkisiyle boş — sudo deneniyor "
                "(tercih: kullanıcıyı adm grubuna ekleyin)",
                server.name,
            )
            ok, out, err = ssh.execute_command(journald_cmd, use_sudo=True, cmd_timeout=cmd_t)
            used_sudo = bool(ok and (out or "").strip())
        if ok and (out or "").strip():
            logs = _parse_log_lines(out)
            if used_sudo:
                logger.debug("Log collection %s: journal sudo ile alındı", server.name)
        else:
            ok2, out2, err2 = ssh.execute_command(syslog_cmd, cmd_timeout=cmd_t)
            if (not ok2 or not (out2 or "").strip()) and sudo_password:
                ok2, out2, err2 = ssh.execute_command(syslog_cmd, use_sudo=True, cmd_timeout=cmd_t)
            if ok2 and (out2 or "").strip():
                logs = _parse_log_lines(out2)
            else:
                sample = (err or err2 or "")[:160]
                logger.info(
                    "Log collection empty %s — journal/syslog yok veya yetki yok "
                    "(SSH kullanıcısını adm grubuna ekleyin). sample=%s",
                    server.name, sample,
                )
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
    log_count_in_window: Optional[int] = None

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
        # COUNT her satırda değil — sunucu başına bir kez
        if log_count_in_window is None:
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

        # ── Minimum tekrar: occurrence 1 ile kaydedilir; Ops'ta warning/error/critical
        # occurrence≥1 ile görünür (adm journal toplanınca ilk turda kaybolmaz).
        event = SystemEvent(
            server_id=server.id,
            event_type="log_entry",
            severity=severity,
            source="log_collector",
            title=clean_title,
            description=raw_line,
            raw_data={
                "platform": platform_for_server(db, server),
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


def _round_robin_batch(servers: List[Server], batch_size: int, cursor_key: str) -> List[Server]:
    """Sunucu listesinden sonraki batch'i al; cursor'ı ilerlet."""
    if not servers or batch_size <= 0 or batch_size >= len(servers):
        return list(servers)
    with _log_cursor_lock:
        n = len(servers)
        start = _log_cursors.get(cursor_key, 0) % n
        end = start + batch_size
        if end <= n:
            batch = servers[start:end]
            _log_cursors[cursor_key] = end % n
        else:
            batch = servers[start:] + servers[: end % n]
            _log_cursors[cursor_key] = end % n
        return batch


def _collect_one_server_job(
    server_id: int,
    since_hours: int,
    global_cred_id: Optional[int],
) -> Dict[str, Any]:
    """Worker thread: kendi DB oturumu ile tek sunucu log topla + kaydet."""
    from app.core.database import ThreadSessionLocal

    db = ThreadSessionLocal()
    try:
        srv = db.query(Server).filter(Server.id == server_id).first()
        if not srv:
            return {"server_id": server_id, "server": "?", "saved": 0, "ok": False}
        global_cred = None
        if global_cred_id:
            global_cred = db.query(GlobalCredential).filter(GlobalCredential.id == global_cred_id).first()
        logs = collect_server_logs(srv, global_cred, since_hours=since_hours)
        saved = 0
        if logs:
            saved = save_logs_to_db(db, srv, logs, since_hours=since_hours)
        return {
            "server_id": server_id,
            "server": srv.name,
            "saved": saved,
            "ok": True,
            "critical": sum(1 for l in logs if l["severity"] == "critical") if logs else 0,
            "error": sum(1 for l in logs if l["severity"] == "error") if logs else 0,
            "warning": sum(1 for l in logs if l["severity"] == "warning") if logs else 0,
        }
    except Exception as e:
        logger.error("Log collection failed server_id=%s: %s", server_id, e)
        return {"server_id": server_id, "server": f"id:{server_id}", "saved": 0, "ok": False, "error_msg": str(e)}
    finally:
        db.close()


def collect_all_servers_logs(
    db: Session,
    only_ai_ready: bool = True,
    since_hours: int = 2,
    progress_cb: Optional[Any] = None,
    *,
    batch_mode: bool = True,
    max_servers: Optional[int] = None,
) -> Dict[str, Any]:
    """ONLINE Linux sunuculardan paralel SSH ile log topla.

    batch_mode=True (periyodik): round-robin batch (log_collection_batch_size).
    batch_mode=False (Şimdi Tara): tüm uygun sunucular, yine paralel worker.
    """
    try:
        from app.services.runtime_settings import get_bool, get_int
        if get_bool("log_scan_ai_ready_only"):
            only_ai_ready = True
        batch_size = int(get_int("log_collection_batch_size") or 500)
    except Exception:
        only_ai_ready = True
        batch_size = 500

    from app.services.bulk_concurrency import log_ssh_workers

    q = db.query(Server).filter(Server.status.in_(["ONLINE", "WARNING"]))
    if only_ai_ready:
        q = q.filter(Server.ai_ready == True)  # noqa: E712
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()
    servers = q.order_by(Server.id).all()
    linux_ids = get_linux_module_server_id_set(db)
    servers = [s for s in servers if s.id in linux_ids]
    fleet_total = len(servers)

    if max_servers is not None and max_servers > 0:
        servers = servers[: max_servers]
    elif batch_mode and fleet_total > batch_size:
        servers = _round_robin_batch(servers, batch_size, "linux")

    workers = log_ssh_workers()
    server_ids = [s.id for s in servers]
    total = len(server_ids)
    global_cred_id = global_cred.id if global_cred else None

    logger.info(
        "Log collection start: fleet=%s batch=%s workers=%s since_hours=%s ai_ready_only=%s",
        fleet_total, total, workers, since_hours, only_ai_ready,
    )

    total_saved = 0
    server_results = []
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

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="log-ssh") as pool:
        futures = {
            pool.submit(_collect_one_server_job, sid, since_hours, global_cred_id): sid
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
                if saved > 0:
                    logger.warning(
                        "[%s] %s yeni log: %s kritik, %s hata, %s uyari",
                        name, saved,
                        result.get("critical", 0),
                        result.get("error", 0),
                        result.get("warning", 0),
                    )
                    server_results.append({
                        "server": name,
                        "saved": saved,
                        "critical": result.get("critical", 0),
                        "error": result.get("error", 0),
                        "warning": result.get("warning", 0),
                    })
            except Exception as e:
                logger.error("Log worker future failed: %s", e)
            if progress_cb:
                try:
                    progress_cb(done, total, name, saved)
                except Exception:
                    pass

    return {
        "total_servers": total,
        "fleet_total": fleet_total,
        "servers_with_logs": len(server_results),
        "total_saved": total_saved,
        "workers": workers,
        "details": server_results,
    }


def collect_exadata_servers_logs(
    db: Session,
    only_ai_ready: bool = False,
    since_hours: int = 2,
    progress_cb: Optional[Any] = None,
    *,
    batch_mode: bool = True,
) -> Dict[str, Any]:
    """Exadata node'larına bağlı sunuculardan paralel log topla."""
    exadata_ids = get_exadata_server_id_set(db)
    if not exadata_ids:
        return {"total_servers": 0, "fleet_total": 0, "servers_with_logs": 0, "total_saved": 0, "details": []}

    try:
        from app.services.runtime_settings import get_int
        batch_size = int(get_int("log_collection_batch_size") or 500)
    except Exception:
        batch_size = 500
    from app.services.bulk_concurrency import log_ssh_workers

    q = db.query(Server).filter(
        Server.id.in_(list(exadata_ids)),
        Server.status.in_(["ONLINE", "WARNING"]),
    )
    if only_ai_ready:
        q = q.filter(Server.ai_ready == True)  # noqa: E712
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    servers = q.order_by(Server.id).all()
    fleet_total = len(servers)
    if batch_mode and fleet_total > batch_size:
        servers = _round_robin_batch(servers, batch_size, "exadata")

    workers = log_ssh_workers()
    server_ids = [s.id for s in servers]
    total = len(server_ids)
    global_cred_id = global_cred.id if global_cred else None
    total_saved = 0
    server_results = []
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

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="log-exa") as pool:
        futures = {
            pool.submit(_collect_one_server_job, sid, since_hours, global_cred_id): sid
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
                if saved > 0:
                    server_results.append({"server": name, "saved": saved})
            except Exception as e:
                logger.error("Exadata log worker failed: %s", e)
            if progress_cb:
                try:
                    progress_cb(done, total, name, saved)
                except Exception:
                    pass

    return {
        "total_servers": total,
        "fleet_total": fleet_total,
        "servers_with_logs": len(server_results),
        "total_saved": total_saved,
        "workers": workers,
        "details": server_results,
    }
