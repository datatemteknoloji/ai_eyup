"""
Sunucularda çalışan uygulama/servisleri (Oracle DB, PostgreSQL, MySQL/MariaDB,
MSSQL, Nginx/Apache/IIS, Tomcat, Redis, MongoDB, Kafka, RabbitMQ, Elasticsearch,
Docker/Kubernetes vb.) OTOMATİK olarak keşfeden servis.

Yaklaşım (Linux):
  Tek bir SSH turunda (round-trip'i azaltmak için) dinleyen portlar + eşleşen
  process'ler + systemd servisleri + kurulu paketler + bilinen ürünlerin
  "version" komutları toplanır (LINUX_SCAN_SCRIPT). Çıktı, bölüm başlıklarına
  (=== ... ===) göre ayrıştırılır ve FINGERPRINTS tablosundaki imzalarla
  eşleştirilir.

Yaklaşım (Windows):
  Tek bir PowerShell scripti (WINDOWS_SCAN_SCRIPT) çalışan servisleri, dinleyen
  TCP portlarını, kurulu SQL Server instance'larını, IIS durumunu ve bilinen
  ürün adlarıyla eşleşen kurulu programları JSON olarak döner.

Sonuçlar DiscoveredApplication tablosuna upsert edilir (bkz. extract_and_store
benzeri desen — app/services/fact_learning.py'deki LearnedFact yaklaşımının
uygulama envanteri için karşılığı).
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.encryption import decrypt_secret
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager
from app.services.platform_scope import is_windows_server

logger = logging.getLogger(__name__)

# Bir sunucu bu aralıktan daha sık taranmaz (uygulama envanteri sık değişmez;
# gereksiz SSH/WinRM yükü ve LLM context şişmesi engellenir). Manuel "Yeniden
# Tara" bu aralığı göz ardı eder.
RESCAN_INTERVAL = timedelta(hours=12)


def _rescan_interval() -> timedelta:
    try:
        from app.services.runtime_settings import get_int
        hours = max(1, int(get_int("app_discovery_rescan_hours")))
        return timedelta(hours=hours)
    except Exception:
        return RESCAN_INTERVAL


def _due_for_rescan(last_scan: Optional[datetime]) -> bool:
    if not last_scan:
        return True
    if last_scan.tzinfo is None:
        last_scan = last_scan.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_scan >= _rescan_interval()


# ─────────────────────────────────────────────────────────────────────────────
# LINUX
# ─────────────────────────────────────────────────────────────────────────────

# Onemli: tum anahtar kelimeler SATIR BASINDA ("^") eslesecek sekilde ankorlanir.
# Aksi halde izleme/monitoring eklentisi paketleri (ornegin "pcp-pmda-redis",
# "pcp-pmda-haproxy" — Redis/HAProxy'yi IZLEYEN PCP eklentileri, kendileri degil)
# urunun kendisiymis gibi YANLIS POZITIF tespit edilir (comm/servis/paket adi
# hep SATIR BASINDA basladigindan bu ankorla hem PROCESSES hem SERVICES hem
# PACKAGES bolumleri icin guvenli ve dogru calisir).
_PRODUCT_GREP = (
    "^postgres|^mysqld|^mariadbd|^mongod|^redis|^nginx|^httpd|^apache2|^tomcat|"
    "^catalina|^kafka|^rabbitmq|^elasticsearch|^haproxy|^sqlservr|^ora_pmon|^tnslsnr|"
    "^dockerd|^containerd|^kubelet|^memcached|^squid|^varnish|^jboss|^wildfly|^glassfish"
)

LINUX_SCAN_SCRIPT = f"""
echo '=== LISTENING_PORTS ==='
ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null
echo '=== PROCESSES ==='
ps -eo comm,args 2>/dev/null | grep -Ei '{_PRODUCT_GREP}' | grep -v grep
echo '=== SERVICES ==='
systemctl list-units --type=service --state=running --no-pager --plain 2>/dev/null | grep -Ei '{_PRODUCT_GREP}|^mssql|^oracle'
echo '=== PACKAGES ==='
(rpm -qa 2>/dev/null || dpkg -l 2>/dev/null | awk '{{print $2}}') 2>/dev/null | grep -Ei \
  '^postgresql-server|^postgresql[0-9]|^mysql-server|^mariadb-server|^mongodb-org-server|^redis-server|^nginx|^httpd|^apache2$|^tomcat($|-[0-9])|^kafka|^rabbitmq-server|^elasticsearch|^haproxy|^mssql-server|^oracle-database-(ee|se|xe|standard|enterprise)|^docker-ce($|-)|^kubelet' \
  | grep -Eiv 'preinstall|-api($|-)|-devel|-client|-jdbc|-libs($|-)|-common($|-)|-cli($|-)'
echo '=== VERSIONS ==='
# Surum: once calisan sunucu/daemon (psql/mysql/redis-cli INFO); yoksa paket surumu.
_pkg_ver() {{ rpm -q --qf '%{{VERSION}}-%{{RELEASE}}' "$1" 2>/dev/null || dpkg-query -W -f='${{Version}}' "$1" 2>/dev/null; }}
PV=$(psql -U postgres -tAc 'select version()' 2>/dev/null | head -1)
[ -z "$PV" ] && PV=$(_pkg_ver postgresql-server)
[ -z "$PV" ] && PV=$(_pkg_ver postgresql)
[ -n "$PV" ] && echo "postgres_version: $PV"
MV=$(mysql -N -e 'select version();' 2>/dev/null || mysql -u root -N -e 'select version();' 2>/dev/null)
[ -z "$MV" ] && MV=$(_pkg_ver mysql-server)
[ -z "$MV" ] && MV=$(_pkg_ver mariadb-server)
[ -n "$MV" ] && echo "mysql_version: $MV"
RV=$(redis-cli INFO server 2>/dev/null | grep -i '^redis_version:' | cut -d: -f2- | tr -d '\\r ')
[ -z "$RV" ] && RV=$(_pkg_ver redis)
[ -z "$RV" ] && RV=$(_pkg_ver redis-server)
[ -n "$RV" ] && echo "redis_version: $RV"
MOV=$(mongosh --quiet --eval 'db.version()' 2>/dev/null || mongo --quiet --eval 'db.version()' 2>/dev/null)
[ -z "$MOV" ] && MOV=$(_pkg_ver mongodb-org-server)
[ -n "$MOV" ] && echo "mongo_version: $MOV"
NV=$(nginx -v 2>&1)
[ -n "$NV" ] && echo "nginx_version: $NV"
AV=$(httpd -v 2>/dev/null | head -1); [ -z "$AV" ] && AV=$(apache2 -v 2>/dev/null | head -1)
[ -n "$AV" ] && echo "apache_version: $AV"
# Docker engine: yalnizca dockerd varsa (cli tek basina sayilmaz)
if pgrep -x dockerd >/dev/null 2>&1 || systemctl is-active docker >/dev/null 2>&1; then
  DV=$(docker --version 2>/dev/null || _pkg_ver docker-ce)
  [ -n "$DV" ] && echo "docker_version: $DV"
fi
command -v kubelet >/dev/null 2>&1 && echo "kubelet_version: $(kubelet --version 2>/dev/null | head -1)"
HV=$(haproxy -v 2>/dev/null | head -1); [ -n "$HV" ] && echo "haproxy_version: $HV"
TV=$(_pkg_ver tomcat); [ -z "$TV" ] && TV=$(_pkg_ver tomcat9); [ -n "$TV" ] && echo "tomcat_version: $TV"
# Oracle: yalnizca gercek instance/listener process'i — preinstall paketi DEGIL
ORA_PMON=$(ps -e -o comm= 2>/dev/null | grep -i '^ora_pmon' | head -1)
[ -n "$ORA_PMON" ] && echo "oracle_running: yes"
ORA_LSNR=$(ps -e -o comm= 2>/dev/null | grep -i '^tnslsnr' | head -1)
[ -n "$ORA_LSNR" ] && echo "oracle_listener_running: yes"
[ -f /etc/oratab ] && ORA_TAB=$(grep -v '^#' /etc/oratab 2>/dev/null | grep -v '^$' | head -3 | tr '\\n' ';') && [ -n "$ORA_TAB" ] && echo "oracle_oratab: $ORA_TAB"
systemctl is-active mssql-server >/dev/null 2>&1 && echo "mssql_active: yes"
MSV=$(_pkg_ver mssql-server); [ -n "$MSV" ] && echo "mssql_version: $MSV"
echo '=== END ==='
""".strip()


# process_keywords / service_keywords → calisiyor kaniti
# package_keywords → yalnizca "kurulu" (running degil)
# version_keys → surum zenginlestirme (tek basina tespit YOK)
_LINUX_FINGERPRINTS: List[Dict[str, Any]] = [
    {"name": "PostgreSQL", "category": "database", "listen_ports": [5432],
     "process_keywords": ["postgres", "postmaster"],
     "service_keywords": ["postgresql"],
     "package_keywords": ["postgresql-server", "postgresql"],
     "version_keys": ["postgres_version"]},
    {"name": "MySQL/MariaDB", "category": "database", "listen_ports": [3306],
     "process_keywords": ["mysqld", "mariadbd"],
     "service_keywords": ["mysqld", "mariadb", "mysql"],
     "package_keywords": ["mysql-server", "mariadb-server"],
     "version_keys": ["mysql_version"]},
    {"name": "MongoDB", "category": "database", "listen_ports": [27017],
     "process_keywords": ["mongod"],
     "service_keywords": ["mongod", "mongodb"],
     "package_keywords": ["mongodb-org-server", "mongodb-org"],
     "version_keys": ["mongo_version"]},
    {"name": "Redis", "category": "cache", "listen_ports": [6379],
     "process_keywords": ["redis-server"],
     "service_keywords": ["redis"],
     "package_keywords": ["redis-server", "redis"],
     "version_keys": ["redis_version"]},
    {"name": "Nginx", "category": "webserver", "listen_ports": [80, 443],
     "process_keywords": ["nginx"],
     "service_keywords": ["nginx"],
     "package_keywords": ["nginx"],
     "version_keys": ["nginx_version"],
     "exclude_substrings": ["ingress", "nginx-ingress"]},
    {"name": "Apache HTTP Server", "category": "webserver", "listen_ports": [80, 443],
     "process_keywords": ["httpd", "apache2"],
     "service_keywords": ["httpd", "apache2"],
     "package_keywords": ["httpd", "apache2"],
     "version_keys": ["apache_version"]},
    {"name": "Tomcat", "category": "appserver", "listen_ports": [8080],
     "process_keywords": ["tomcat", "catalina"],
     "service_keywords": ["tomcat"],
     "package_keywords": ["tomcat"],
     "version_keys": ["tomcat_version"]},
    {"name": "JBoss/WildFly", "category": "appserver", "listen_ports": [],
     "process_keywords": ["jboss", "wildfly", "glassfish"],
     "service_keywords": ["jboss", "wildfly"],
     "package_keywords": ["wildfly", "jboss"],
     "version_keys": []},
    {"name": "Apache Kafka", "category": "messaging", "listen_ports": [9092],
     "process_keywords": ["kafka"],
     "service_keywords": ["kafka"],
     "package_keywords": ["kafka"],
     "version_keys": []},
    {"name": "RabbitMQ", "category": "messaging", "listen_ports": [5672],
     "process_keywords": ["rabbitmq"],
     "service_keywords": ["rabbitmq"],
     "package_keywords": ["rabbitmq-server"],
     "version_keys": []},
    {"name": "Elasticsearch", "category": "database", "listen_ports": [9200],
     "process_keywords": ["elasticsearch"],
     "service_keywords": ["elasticsearch"],
     "package_keywords": ["elasticsearch"],
     "version_keys": []},
    {"name": "HAProxy", "category": "webserver", "listen_ports": [],
     "process_keywords": ["haproxy"],
     "service_keywords": ["haproxy"],
     "package_keywords": ["haproxy"],
     "version_keys": ["haproxy_version"]},
    {"name": "Microsoft SQL Server", "category": "database", "listen_ports": [1433],
     "process_keywords": ["sqlservr"],
     "service_keywords": ["mssql-server"],
     "package_keywords": ["mssql-server"],
     "version_keys": ["mssql_version"],
     "flag_keys": ["mssql_active"]},
    {"name": "Oracle Database", "category": "database", "listen_ports": [1521],
     "process_keywords": ["ora_pmon"],
     "service_keywords": [],
     "package_keywords": [],  # preinstall yanlis pozitif; yalnizca process
     "version_keys": [],
     "flag_keys": ["oracle_running"]},
    {"name": "Oracle Listener", "category": "database", "listen_ports": [1521],
     "process_keywords": ["tnslsnr"],
     "service_keywords": [],
     "package_keywords": [],
     "version_keys": [],
     "flag_keys": ["oracle_listener_running"]},
    {"name": "Docker", "category": "container_platform", "listen_ports": [],
     "process_keywords": ["dockerd"],
     "service_keywords": ["docker"],
     "package_keywords": ["docker-ce"],
     "version_keys": ["docker_version"]},
    {"name": "Kubernetes (kubelet)", "category": "container_platform", "listen_ports": [],
     "process_keywords": ["kubelet"],
     "service_keywords": ["kubelet"],
     "package_keywords": ["kubelet"],
     "version_keys": ["kubelet_version"]},
    {"name": "Memcached", "category": "cache", "listen_ports": [11211],
     "process_keywords": ["memcached"],
     "service_keywords": ["memcached"],
     "package_keywords": ["memcached"],
     "version_keys": []},
    {"name": "Squid", "category": "webserver", "listen_ports": [3128],
     "process_keywords": ["squid"],
     "service_keywords": ["squid"],
     "package_keywords": ["squid"],
     "version_keys": []},
    {"name": "Varnish", "category": "webserver", "listen_ports": [6081],
     "process_keywords": ["varnishd", "varnish"],
     "service_keywords": ["varnish"],
     "package_keywords": ["varnish"],
     "version_keys": []},
]

_SECTION_RE = re.compile(r"^===\s*(\w+)\s*===\s*$")
# ss -tlnp cikti ornegi: LISTEN 0  128  0.0.0.0:5432  0.0.0.0:*  users:(("postgres",pid=123,fd=6))
_PORT_LINE_RE = re.compile(
    r":(\d+)\s+[\d.:*\[\]]+\s+users:\(\(\"?([\w\-.]+)\"?", re.IGNORECASE
)
_PORT_ANY_RE = re.compile(r":(\d+)\s+")
_VERSION_LINE_RE = re.compile(r"^([a-z_]+):\s*(.+)$", re.IGNORECASE)
_FALSE_PKG_RE = re.compile(
    r"preinstall|-api($|-)|-devel|-client|-jdbc|-libs($|-)|-common($|-)|-cli($|-)",
    re.IGNORECASE,
)


def _split_sections(raw: str) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current = "_preamble"
    for line in (raw or "").splitlines():
        m = _SECTION_RE.match(line.strip())
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _token_in_text(token: str, text: str) -> bool:
    """Kelime/token eslesmesi — 'redis' 'pcp-pmda-redis' icinde tutmasin diye
    sinirli arama; tire/altcizgi ayiricilarina izin verir."""
    t = (token or "").strip().lower()
    if not t or not text:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text.lower()) is not None


def _first_matching_line(
    text: str,
    keywords: List[str],
    *,
    package: bool = False,
    exclude_substrings: Optional[List[str]] = None,
) -> Optional[str]:
    excludes = [e.lower() for e in (exclude_substrings or []) if e]
    for line in (text or "").splitlines():
        low = line.lower().strip()
        if not low:
            continue
        if excludes and any(ex in low for ex in excludes):
            continue
        if package and _FALSE_PKG_RE.search(low):
            continue
        for kw in keywords:
            if _token_in_text(kw, low):
                return line.strip()[:250]
    return None


def _clean_version(raw: Optional[str]) -> Optional[str]:
    """Ham surum ciktilarini kisa, okunabilir forma cevirir."""
    if not raw:
        return None
    s = raw.strip()
    if not s or s.lower() in {"yes", "no", "found", "true", "false"}:
        return None
    # redis_version:6.2.20 / key:value
    if re.match(r"^[a-z_]+_version\s*:", s, re.I):
        s = s.split(":", 1)[-1].strip()
    # nginx version: nginx/1.20.1
    m = re.search(r"nginx/([\w.\-]+)", s, re.I)
    if m:
        return m.group(1)[:120]
    # Docker version 26.1.3, build ...
    m = re.search(r"(?i)(?:docker|podman)\s+version\s+([\w.\-]+)", s)
    if m:
        return m.group(1)[:120]
    # Apache/2.4.37 (Unix)
    m = re.search(r"(?i)Apache/([\w.\-]+)", s)
    if m:
        return m.group(1)[:120]
    # PostgreSQL 13.23 on x86_64-...
    m = re.search(r"(?i)PostgreSQL\s+([\w.\-]+)", s)
    if m:
        return m.group(1)[:120]
    # kubelet version=v1.34.0
    m = re.search(r"(?i)version[=:\s]+v?([\w.\-]+)", s)
    if m and " " not in m.group(1):
        return m.group(1).lstrip("vV")[:120]
    # Genel: ilk X.Y.Z benzeri
    m = re.search(r"\b(\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)\b", s)
    if m:
        return m.group(1)[:120]
    return s[:120]


def _extract_version(versions_text: str, version_keys: List[str]) -> Optional[str]:
    """Sadece ilgili '<key>: <deger>' satirlarindan temiz surum dondurur."""
    keys = {k.lower() for k in (version_keys or []) if k}
    if not keys:
        return None
    for line in versions_text.splitlines():
        m = _VERSION_LINE_RE.match(line.strip())
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        if key not in keys:
            continue
        cleaned = _clean_version(val)
        if cleaned:
            return cleaned
    return None


def _parse_version_flags(versions_text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in versions_text.splitlines():
        m = _VERSION_LINE_RE.match(line.strip())
        if not m:
            continue
        out[m.group(1).lower()] = m.group(2).strip()
    return out


def _port_map_from_listeners(listen_text: str) -> Dict[str, List[int]]:
    """process adı (lowercase) -> dinlediği port listesi."""
    out: Dict[str, List[int]] = {}
    for line in listen_text.splitlines():
        m = _PORT_LINE_RE.search(line)
        if not m:
            continue
        port, proc = int(m.group(1)), m.group(2).lower()
        out.setdefault(proc, [])
        if port not in out[proc]:
            out[proc].append(port)
    return out


def _all_listening_ports(listen_text: str) -> set:
    ports = set()
    for line in listen_text.splitlines():
        m = _PORT_ANY_RE.search(line)
        if m:
            ports.add(int(m.group(1)))
    return ports


def _find_listen_port(
    port_map: Dict[str, List[int]],
    all_ports: set,
    process_keywords: List[str],
    preferred: List[int],
) -> Optional[int]:
    """Yalnizca dinleyen process adi fingerprint ile eslesince port dondur.
    Ortak portlara (80/443) process eslesmesi olmadan urun atama."""
    for kw in process_keywords:
        kw_l = kw.lower()
        for proc_name, plist in port_map.items():
            if _token_in_text(kw_l, proc_name) or kw_l in proc_name:
                if preferred:
                    for p in preferred:
                        if p in plist:
                            return p
                if plist:
                    return plist[0]
    return None


def parse_linux_scan(raw_output: str) -> List[Dict[str, Any]]:
    """LINUX_SCAN_SCRIPT ciktiisini fingerprint'lerle eslestirir.

    status:
      - running  → process VEYA systemd running VEYA aktif bayrak
      - installed → yalnizca paket (calismiyor)
    Port yalnizca dinleyen process eslesince yazilir (varsayilan port uydurulmaz).
    Surum ham banner yerine temizlenmis degerdir.
    """
    sections = _split_sections(raw_output)
    ports_text = sections.get("LISTENING_PORTS", "")
    proc_text = sections.get("PROCESSES", "")
    svc_text = sections.get("SERVICES", "")
    pkg_text = sections.get("PACKAGES", "")
    ver_text = sections.get("VERSIONS", "")
    port_map = _port_map_from_listeners(ports_text)
    all_ports = _all_listening_ports(ports_text)
    flags = _parse_version_flags(ver_text)

    results = []
    for fp in _LINUX_FINGERPRINTS:
        proc_kw = fp.get("process_keywords") or []
        svc_kw = fp.get("service_keywords") or []
        pkg_kw = fp.get("package_keywords") or []
        ver_keys = fp.get("version_keys") or []
        flag_keys = fp.get("flag_keys") or []
        preferred_ports = list(fp.get("listen_ports") or [])
        excludes = fp.get("exclude_substrings") or []

        proc_line = _first_matching_line(proc_text, proc_kw, exclude_substrings=excludes)
        svc_line = _first_matching_line(svc_text, svc_kw, exclude_substrings=excludes)
        pkg_line = _first_matching_line(pkg_text, pkg_kw, package=True, exclude_substrings=excludes)
        flag_hit = any(
            (flags.get(k.lower()) or "").lower() in {"yes", "true", "1", "found", "active"}
            for k in flag_keys
        )
        listen_port = _find_listen_port(port_map, all_ports, proc_kw, preferred_ports)
        # Calisan kanit varken preferred port dinleniyorsa (ss users: yoksa) yine yaz
        if listen_port is None and (proc_line or svc_line or flag_hit):
            for p in preferred_ports:
                if p in all_ports:
                    listen_port = p
                    break

        running = bool(proc_line or svc_line or flag_hit)
        installed_only = bool(pkg_line) and not running
        if not running and not installed_only:
            continue

        if proc_line:
            method, evidence = "process", proc_line
        elif svc_line:
            method, evidence = "service", svc_line
        elif flag_hit:
            method, evidence = "service", next(
                (f"{k}={flags.get(k)}" for k in flag_keys if flags.get(k)), "flag"
            )
        else:
            method, evidence = "package", pkg_line

        version = _extract_version(ver_text, ver_keys)
        if not version and pkg_line:
            m = re.search(r"[_\-](\d+\.\d+(?:\.\d+)?(?:-[\w.+]+)?)\b", pkg_line)
            if m:
                version = m.group(1)[:120]

        results.append({
            "name": fp["name"],
            "category": fp["category"],
            "version": version,
            "port": listen_port if running else None,
            "process_or_service": (evidence or "")[:200] if evidence else None,
            "detection_method": method,
            "evidence": evidence,
            "status": "running" if running else "installed",
        })
    return results


def scan_server_linux(server: Server, global_cred: Optional[GlobalCredential] = None) -> List[Dict[str, Any]]:
    """Bir Linux sunucuya SSH ile bağlanıp uygulama taraması yapar."""
    conn = server.connection_config or {}
    username = conn.get("username") or (global_cred.username if global_cred else None)
    raw_password = conn.get("password") or (global_cred.password if global_cred else None)
    raw_private_key = conn.get("private_key") or (global_cred.private_key if global_cred else None)
    password = decrypt_secret(raw_password) if raw_password else None
    private_key = decrypt_secret(raw_private_key) if raw_private_key else None
    port = conn.get("port", 22) or (global_cred.port if global_cred else 22)

    host = server.ip_address or server.hostname
    if not username or not host:
        return []

    ssh = SSHManager(host=host, username=username, password=password, private_key=private_key, port=port)
    try:
        if not ssh.connect():
            return []
        ok, out, err = ssh.execute_command(LINUX_SCAN_SCRIPT, cmd_timeout=25)
        if not ok or not out:
            return []
        return parse_linux_scan(out)
    except Exception as e:
        logger.debug(f"Uygulama taramasi basarisiz ({server.name}): {e}")
        return []
    finally:
        ssh.close()


# ─────────────────────────────────────────────────────────────────────────────
# WINDOWS
# ─────────────────────────────────────────────────────────────────────────────

WINDOWS_SCAN_SCRIPT = r"""
$result = @{}
try { $result.services = @(Get-Service -ErrorAction SilentlyContinue | Where-Object {$_.Status -eq 'Running'} | Select-Object Name,DisplayName) } catch { $result.services = @() }
try {
  $result.sql_instances = @(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL' -ErrorAction SilentlyContinue |
    ForEach-Object { $_.PSObject.Properties | Where-Object {$_.Name -notmatch '^PS'} | ForEach-Object { $_.Name } })
} catch { $result.sql_instances = @() }
try {
  $iisSvc = Get-Service W3SVC -ErrorAction SilentlyContinue
  $result.iis_installed = [bool]$iisSvc
  $result.iis_status = if ($iisSvc) { $iisSvc.Status.ToString() } else { $null }
} catch { $result.iis_installed = $false }
try {
  $result.listening_ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
} catch { $result.listening_ports = @() }
try {
  $keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
  $result.installed_programs = @(Get-ItemProperty $keys -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match '\bSQL Server\b|\bOracle\b|\bnginx\b|\bApache\b|\bTomcat\b|\bMySQL\b|\bMariaDB\b|\bPostgreSQL\b|\bMongoDB\b|\bRedis\b|\bDocker\b|\bKafka\b|\bRabbitMQ\b|\bElasticsearch\b|\bIIS\b' } |
    Select-Object DisplayName,DisplayVersion -Unique)
} catch { $result.installed_programs = @() }
$result | ConvertTo-Json -Depth 4 -Compress
""".strip()


_WIN_SERVICE_FINGERPRINTS: List[Dict[str, Any]] = [
    {"name": "Microsoft SQL Server", "category": "database", "port": 1433,
     "service_keywords": ["MSSQL", "SQL Server ("]},
    {"name": "MySQL/MariaDB", "category": "database", "port": 3306,
     "service_keywords": ["MySQL", "MariaDB"]},
    {"name": "PostgreSQL", "category": "database", "port": 5432,
     "service_keywords": ["postgresql"]},
    {"name": "MongoDB", "category": "database", "port": 27017,
     "service_keywords": ["MongoDB"]},
    {"name": "Redis", "category": "cache", "port": 6379,
     "service_keywords": ["Redis"]},
    {"name": "Nginx", "category": "webserver", "port": 80,
     "service_keywords": ["nginx"]},
    {"name": "Apache Tomcat", "category": "appserver", "port": 8080,
     "service_keywords": ["Tomcat"]},
    {"name": "Docker", "category": "container_platform", "port": None,
     "service_keywords": ["docker"]},
    {"name": "Apache Kafka", "category": "messaging", "port": 9092,
     "service_keywords": ["kafka"]},
    {"name": "RabbitMQ", "category": "messaging", "port": 5672,
     "service_keywords": ["RabbitMQ"]},
    {"name": "Elasticsearch", "category": "database", "port": 9200,
     "service_keywords": ["elasticsearch"]},
]


def parse_windows_scan(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    results: List[Dict[str, Any]] = []
    seen_names = set()
    listening = set()
    for p in data.get("listening_ports") or []:
        try:
            listening.add(int(p))
        except (TypeError, ValueError):
            pass

    services = data.get("services") or []
    if isinstance(services, dict):
        services = [services]
    for fp in _WIN_SERVICE_FINGERPRINTS:
        for svc in services:
            svc_name = str((svc or {}).get("Name") or "")
            display_name = str((svc or {}).get("DisplayName") or "")
            haystack = f"{svc_name} {display_name}".lower()
            if any(kw.lower() in haystack for kw in fp["service_keywords"]):
                if fp["name"] not in seen_names:
                    pref = fp.get("port")
                    port = pref if (pref and pref in listening) else None
                    results.append({
                        "name": fp["name"], "category": fp["category"],
                        "version": None,
                        "port": port,
                        "process_or_service": display_name or svc_name,
                        "detection_method": "service",
                        "evidence": f"Service: {display_name or svc_name}",
                        "status": "running",
                    })
                    seen_names.add(fp["name"])
                break

    # IIS: yalnizca W3SVC Running iken "calisiyor"
    iis_status = str(data.get("iis_status") or "").lower()
    if iis_status == "running":
        results.append({
            "name": "IIS (Internet Information Services)", "category": "webserver",
            "version": None,
            "port": 80 if 80 in listening else (443 if 443 in listening else None),
            "process_or_service": "W3SVC", "detection_method": "service",
            "evidence": f"W3SVC status: {data.get('iis_status')}",
            "status": "running",
        })
        seen_names.add("IIS (Internet Information Services)")
    elif data.get("iis_installed"):
        results.append({
            "name": "IIS (Internet Information Services)", "category": "webserver",
            "version": None, "port": None, "process_or_service": "W3SVC",
            "detection_method": "service",
            "evidence": f"W3SVC status: {data.get('iis_status') or 'Stopped'}",
            "status": "installed",
        })
        seen_names.add("IIS (Internet Information Services)")

    sql_instances = data.get("sql_instances") or []
    if isinstance(sql_instances, str):
        sql_instances = [sql_instances]
    if sql_instances and "Microsoft SQL Server" not in seen_names:
        # Registry instance var ama calisan servis yok → kurulu
        results.append({
            "name": "Microsoft SQL Server", "category": "database", "version": None,
            "port": 1433 if 1433 in listening else None,
            "process_or_service": ", ".join(str(i) for i in sql_instances),
            "detection_method": "registry",
            "evidence": f"Instances: {', '.join(str(i) for i in sql_instances)}",
            "status": "installed",
        })
        seen_names.add("Microsoft SQL Server")

    installed_programs = data.get("installed_programs") or []
    if isinstance(installed_programs, dict):
        installed_programs = [installed_programs]
    for prog in installed_programs:
        display_name = str((prog or {}).get("DisplayName") or "").strip()
        display_version = _clean_version(str((prog or {}).get("DisplayVersion") or "").strip() or None)
        if not display_name:
            continue
        matched = None
        for r in results:
            r0 = r["name"].split()[0].lower()
            if r0 in display_name.lower() or display_name.lower() in r["name"].lower():
                matched = r
                break
        if matched:
            if not matched.get("version") and display_version:
                matched["version"] = display_version
        elif display_name not in seen_names:
            results.append({
                "name": display_name[:120], "category": "other", "version": display_version,
                "port": None, "process_or_service": None, "detection_method": "registry",
                "evidence": f"Installed program: {display_name} {display_version or ''}".strip(),
                "status": "installed",
            })
            seen_names.add(display_name)

    return results


def scan_server_windows(server: Server, db: Session) -> List[Dict[str, Any]]:
    from app.services.windows_log_collector import _build_client
    import json as _json

    client = _build_client(server, db)
    if not client:
        return []
    try:
        r = client.run_ps(WINDOWS_SCAN_SCRIPT)
        if not r.get("success") or not r.get("stdout"):
            return []
        try:
            data = _json.loads(r["stdout"].strip())
        except Exception:
            return []
        return parse_windows_scan(data)
    except Exception as e:
        logger.debug(f"Windows uygulama taramasi basarisiz ({server.name}): {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ORTAK: upsert + toplu senkron
# ─────────────────────────────────────────────────────────────────────────────

def _clip(value: Optional[str], max_len: int) -> Optional[str]:
    if not value:
        return value
    return value[:max_len]


def upsert_discovered_apps(db: Session, server: Server, apps: List[Dict[str, Any]], source: str) -> int:
    """Bir sunucu için tespit edilen uygulama listesini DiscoveredApplication'a
    yazar. Bu taramada görülmeyen (önceden kayıtlı) uygulamalar "stopped"
    durumuna çekilir, silinmez."""
    from app.models.discovered_application import DiscoveredApplication

    now = datetime.now(timezone.utc)
    touched = 0
    try:
        for a in apps:
            a["name"] = _clip(a.get("name"), 120) or "unknown"
            a["category"] = _clip(a.get("category"), 40) or "other"
            a["version"] = _clip(_clean_version(a.get("version")) or a.get("version"), 120)
            a["process_or_service"] = _clip(a.get("process_or_service"), 200)
            a["detection_method"] = _clip(a.get("detection_method"), 30)
            st = (a.get("status") or "running").strip().lower()
            if st not in {"running", "installed", "stopped"}:
                st = "running"
            a["status"] = st

        seen_names = {a["name"] for a in apps}

        existing_rows = db.query(DiscoveredApplication).filter(
            DiscoveredApplication.server_id == server.id
        ).all()
        existing_by_name = {r.name: r for r in existing_rows}

        for app in apps:
            row = existing_by_name.get(app["name"])
            if row:
                row.category = app["category"]
                # Yeni taramadaki surum/port gercek durumu yansitsin (eski varsayilan port kalmasin)
                row.version = app.get("version")
                row.port = app.get("port")
                row.process_or_service = app.get("process_or_service") or row.process_or_service
                row.detection_method = app.get("detection_method") or row.detection_method
                row.evidence = app.get("evidence") or row.evidence
                row.status = app["status"]
                row.last_seen_at = now
                row.times_confirmed = (row.times_confirmed or 1) + 1
                row.source = source
            else:
                db.add(DiscoveredApplication(
                    server_id=server.id, name=app["name"], category=app["category"],
                    version=app.get("version"), port=app.get("port"),
                    process_or_service=app.get("process_or_service"),
                    detection_method=app.get("detection_method"), evidence=app.get("evidence"),
                    status=app["status"], source=source,
                    first_detected_at=now, last_seen_at=now, times_confirmed=1,
                ))
            touched += 1

        for name, row in existing_by_name.items():
            if name not in seen_names and row.status != "stopped":
                row.status = "stopped"
                row.port = None

        server.app_discovery_last_scan = now
        db.commit()
    except Exception as e:
        logger.debug(f"Discovered app upsert hatasi ({server.name}): {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    return touched


def sanitize_discovered_applications(db: Session) -> int:
    """Eski yanlis-pozitif / varsayilan-port kayitlarini temizler.
    package/version-only → installed; uydurma portlari siler; surumleri temizler.
    Bilinen sahte kanitli satirlar silinir."""
    from app.models.discovered_application import DiscoveredApplication

    rows = db.query(DiscoveredApplication).all()
    changed = 0
    to_delete = []
    for row in rows:
        before = (row.status, row.port, row.version, row.detection_method)
        evid = (row.evidence or "").lower()
        method = (row.detection_method or "").lower()
        name = (row.name or "").lower()

        # Sahte / yanlis pozitif — kaydi kaldir
        fake = (
            "preinstall" in evid
            or "tomcat-servlet" in evid
            or "tomcat-jsp" in evid
            or "docker-ce-cli" in evid
            or ("ingress" in evid and "nginx" in name)
            or (method == "version" and evid.strip().endswith(":") and not (row.version or "").strip())
        )
        if fake:
            to_delete.append(row)
            changed += 1
            continue

        if method in {"package", "registry", "version"} and row.status == "running":
            row.status = "installed"
            row.port = None

        if row.version:
            cleaned = _clean_version(row.version)
            row.version = cleaned

        if row.status == "installed":
            row.port = None
        if row.status == "running" and method in {"package", "version", "registry"}:
            row.status = "installed"
            row.port = None

        after = (row.status, row.port, row.version, row.detection_method)
        if after != before:
            changed += 1

    for row in to_delete:
        db.delete(row)

    if changed or to_delete:
        try:
            db.commit()
        except Exception:
            db.rollback()
            return 0
    return changed


def discover_applications_all_servers(db: Session, force: bool = False) -> Dict[str, Any]:
    """Tüm AI Ready sunucularda (rescan aralığı dolmuş olanlar) uygulama
    taraması yapar. Arka plan görevi tarafından periyodik çağrılır."""
    try:
        sanitize_discovered_applications(db)
    except Exception as e:
        logger.debug("discovered apps sanitize: %s", e)

    candidates = (
        db.query(Server)
        .filter(Server.ai_ready == True, Server.ip_address.isnot(None), Server.ip_address != "")  # noqa: E712
        .all()
    )
    if not force:
        candidates = [s for s in candidates if _due_for_rescan(s.app_discovery_last_scan)]
    if not candidates:
        return {"scanned": 0, "apps_found": 0}

    linux_servers = [s for s in candidates if not is_windows_server(s)]
    windows_servers = [s for s in candidates if is_windows_server(s)]

    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    scanned = 0
    apps_found = 0
    details = []

    def _linux_one(srv: Server):
        apps = scan_server_linux(srv, global_cred)
        return srv, apps

    from app.services.bulk_concurrency import bulk_ssh_workers

    if linux_servers:
        with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="app-discovery") as pool:
            futures = {pool.submit(_linux_one, s): s for s in linux_servers}
            for fut in as_completed(futures):
                srv = futures[fut]
                try:
                    srv2, apps = fut.result()
                    n = upsert_discovered_apps(db, srv2, apps, source="ssh")
                    scanned += 1
                    apps_found += n
                    if apps:
                        details.append({"server": srv.name, "found": len(apps)})
                except Exception as e:
                    logger.debug(f"Linux app discovery hatasi ({srv.name}): {e}")

    def _windows_one(srv: Server):
        # Thread pool içinde çalışır — kendi (salt okunur) DB oturumunu açar;
        # yazma (upsert_discovered_apps) ana thread'de, ana `db` ile yapılır.
        from app.core.database import ThreadSessionLocal
        tdb = ThreadSessionLocal()
        try:
            return srv, scan_server_windows(srv, tdb)
        finally:
            tdb.close()

    if windows_servers:
        # NOT: önceden Windows sunucular TAMAMEN SIRALI taranıyordu (WinRM turu
        # bitmeden diğerine geçilmiyordu) — 10k ölçekte binlerce Windows sunucuda
        # bir tur saatlerce sürebiliyordu. Artık Linux ile aynı desende paralel.
        with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="app-discovery-win") as pool:
            futures = {pool.submit(_windows_one, s): s for s in windows_servers}
            for fut in as_completed(futures):
                srv = futures[fut]
                try:
                    srv2, apps = fut.result()
                    n = upsert_discovered_apps(db, srv2, apps, source="winrm")
                    scanned += 1
                    apps_found += n
                    if apps:
                        details.append({"server": srv.name, "found": len(apps)})
                except Exception as e:
                    logger.debug(f"Windows app discovery hatasi ({srv.name}): {e}")

    return {"scanned": scanned, "apps_found": apps_found, "details": details}


def get_discovered_apps_block(db: Session, server: Server, max_items: int = 20) -> str:
    """Bir sunucu için tespit edilmiş (çalışan) uygulamaları LLM prompt'una
    eklenebilecek kısa bir metin bloğu olarak döner (boşsa "")."""
    if not server or not getattr(server, "id", None):
        return ""
    try:
        from app.models.discovered_application import DiscoveredApplication

        rows = (
            db.query(DiscoveredApplication)
            .filter(DiscoveredApplication.server_id == server.id, DiscoveredApplication.status == "running")
            .order_by(DiscoveredApplication.category, DiscoveredApplication.name)
            .limit(max_items)
            .all()
        )
        if not rows:
            return ""
        lines = []
        for r in rows:
            bits = [r.name]
            if r.version:
                ver = r.version
                bits.append(ver if ver.lower().startswith("v") else f"v{ver}")
            if r.port:
                bits.append(f"port {r.port}")
            how = r.detection_method or ""
            if how:
                bits.append(how)
            scan_age = ""
            if r.last_seen_at:
                last = r.last_seen_at if r.last_seen_at.tzinfo else r.last_seen_at.replace(tzinfo=timezone.utc)
                hours = max(0, int((datetime.now(timezone.utc) - last).total_seconds() // 3600))
                scan_age = f", {hours} saat once tarandi" if hours else ", az once tarandi"
            lines.append(f"- [{r.category}] " + " — ".join(bits) + scan_age)
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Discovered apps block olusturulamadi: {e}")
        return ""


def discover_applications_for_server(db: Session, server: Server) -> List[Dict[str, Any]]:
    """Tek bir sunucu için ANINDA (rescan aralığını göz ardı ederek) tarama
    yapar — 'Yeniden Tara' butonu için."""
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    if is_windows_server(server):
        apps = scan_server_windows(server, db)
        source = "winrm"
    else:
        apps = scan_server_linux(server, global_cred)
        source = "ssh"

    upsert_discovered_apps(db, server, apps, source=source)
    return apps
