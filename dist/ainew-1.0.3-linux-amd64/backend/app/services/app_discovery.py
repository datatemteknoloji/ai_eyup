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


def _due_for_rescan(last_scan: Optional[datetime]) -> bool:
    if not last_scan:
        return True
    if last_scan.tzinfo is None:
        last_scan = last_scan.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_scan >= RESCAN_INTERVAL


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
  '^postgresql-server|^postgresql[0-9]|^mysql-server|^mariadb-server|^mongodb-org|^redis|^nginx|^httpd|^apache2$|^tomcat|^kafka|^rabbitmq-server|^elasticsearch|^haproxy|^mssql-server|^oracle-database|^docker-ce|^kubelet'
echo '=== VERSIONS ==='
command -v psql >/dev/null 2>&1 && echo "postgres_version: $(psql -U postgres -tAc 'select version()' 2>/dev/null | head -1)"
command -v mysql >/dev/null 2>&1 && echo "mysql_version: $(mysql -N -e 'select version();' 2>/dev/null || mysql -u root -N -e 'select version();' 2>/dev/null)"
command -v redis-cli >/dev/null 2>&1 && echo "redis_version: $(redis-cli INFO server 2>/dev/null | grep -i '^redis_version' | tr -d '\\r')"
command -v mongosh >/dev/null 2>&1 && echo "mongo_version: $(mongosh --quiet --eval 'db.version()' 2>/dev/null)"
command -v mongo >/dev/null 2>&1 && echo "mongo_version: $(mongo --quiet --eval 'db.version()' 2>/dev/null)"
command -v nginx >/dev/null 2>&1 && echo "nginx_version: $(nginx -v 2>&1)"
command -v httpd >/dev/null 2>&1 && echo "apache_version: $(httpd -v 2>/dev/null | head -1)"
command -v apache2 >/dev/null 2>&1 && echo "apache_version: $(apache2 -v 2>/dev/null | head -1)"
command -v docker >/dev/null 2>&1 && echo "docker_version: $(docker --version 2>/dev/null)"
command -v kubectl >/dev/null 2>&1 && echo "kubectl_version: $(kubectl version --client 2>/dev/null | head -1)"
command -v haproxy >/dev/null 2>&1 && echo "haproxy_version: $(haproxy -v 2>/dev/null | head -1)"
[ -f /etc/oratab ] && echo "oracle_oratab: $(grep -v '^#' /etc/oratab 2>/dev/null | grep -v '^$' | head -3 | tr '\\n' ';')"
ORA_PMON=$(ps -e -o comm= 2>/dev/null | grep -i '^ora_pmon' | head -1)
[ -n "$ORA_PMON" ] && echo "oracle_running: yes"
ORA_LSNR=$(ps -e -o comm= 2>/dev/null | grep -i '^tnslsnr' | head -1)
[ -n "$ORA_LSNR" ] && echo "oracle_listener_running: yes"
systemctl is-active mssql-server >/dev/null 2>&1 && echo "mssql_active: yes"
(rpm -q mssql-server >/dev/null 2>&1 || dpkg -s mssql-server >/dev/null 2>&1) && echo "mssql_pkg: found"
echo '=== END ==='
""".strip()


# (name, category, default_port, [process/service/package/version keyword'leri])
_LINUX_FINGERPRINTS: List[Dict[str, Any]] = [
    {"name": "PostgreSQL", "category": "database", "port": 5432,
     "keywords": ["postgres", "postgresql"]},
    {"name": "MySQL/MariaDB", "category": "database", "port": 3306,
     "keywords": ["mysqld", "mariadbd", "mysql-server", "mariadb-server", "mysql_version"]},
    {"name": "MongoDB", "category": "database", "port": 27017,
     "keywords": ["mongod", "mongodb-org", "mongo_version"]},
    {"name": "Redis", "category": "cache", "port": 6379,
     "keywords": ["redis-server", "redis_version", "^redis$"]},
    {"name": "Nginx", "category": "webserver", "port": 80,
     "keywords": ["nginx"]},
    {"name": "Apache HTTP Server", "category": "webserver", "port": 80,
     "keywords": ["httpd", "apache2"]},
    {"name": "Tomcat", "category": "appserver", "port": 8080,
     "keywords": ["tomcat", "catalina"]},
    {"name": "JBoss/WildFly", "category": "appserver", "port": None,
     "keywords": ["jboss", "wildfly", "glassfish"]},
    {"name": "Apache Kafka", "category": "messaging", "port": 9092,
     "keywords": ["kafka"]},
    {"name": "RabbitMQ", "category": "messaging", "port": 5672,
     "keywords": ["rabbitmq"]},
    {"name": "Elasticsearch", "category": "database", "port": 9200,
     "keywords": ["elasticsearch"]},
    {"name": "HAProxy", "category": "webserver", "port": None,
     "keywords": ["haproxy"]},
    {"name": "Microsoft SQL Server", "category": "database", "port": 1433,
     "keywords": ["mssql-server", "sqlservr", "mssql_active", "mssql_pkg"]},
    {"name": "Oracle Database", "category": "database", "port": 1521,
     "keywords": ["ora_pmon", "oracle_oratab", "oracle_running", "oracle-database"]},
    {"name": "Oracle Listener", "category": "database", "port": 1521,
     "keywords": ["tnslsnr", "oracle_listener_running"]},
    {"name": "Docker", "category": "container_platform", "port": None,
     "keywords": ["dockerd", "docker-ce", "docker_version"]},
    {"name": "Kubernetes (kubelet)", "category": "container_platform", "port": None,
     "keywords": ["kubelet"]},
    {"name": "Memcached", "category": "cache", "port": 11211,
     "keywords": ["memcached"]},
    {"name": "Squid", "category": "webserver", "port": 3128,
     "keywords": ["squid"]},
    {"name": "Varnish", "category": "webserver", "port": 6081,
     "keywords": ["varnish"]},
]

_SECTION_RE = re.compile(r"^===\s*(\w+)\s*===\s*$")
# ss -tlnp cikti ornegi: LISTEN 0  128  0.0.0.0:5432  0.0.0.0:*  users:(("postgres",pid=123,fd=6))
_PORT_LINE_RE = re.compile(
    r":(\d+)\s+[\d.:*\[\]]+\s+users:\(\(\"?([\w\-.]+)\"?", re.IGNORECASE
)
_VERSION_LINE_RE = re.compile(r"^([a-z_]+):\s*(.+)$", re.IGNORECASE)


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


def _extract_version(versions_text: str, fp_keywords: List[str]) -> Optional[str]:
    """Sadece gercek '<urun>_version: <deger>' seklindeki satirlardan surum
    cikarir — 'oracle_running: yes' / 'mssql_pkg: found' gibi varlik-bayragi
    (boolean flag) satirlari kasitli olarak ATLANIR, cunku bunlarin degeri
    ('yes'/'found') bir surum degil."""
    for line in versions_text.splitlines():
        m = _VERSION_LINE_RE.match(line.strip())
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        if not key.endswith("_version"):
            continue
        for kw in fp_keywords:
            kw_clean = kw.strip("^$").lower()
            if kw_clean and kw_clean in key:
                return val[:110] if val else None
    return None


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


def parse_linux_scan(raw_output: str) -> List[Dict[str, Any]]:
    """LINUX_SCAN_SCRIPT çıktısını FINGERPRINTS ile eşleştirip yapılandırılmış
    uygulama listesi döner: [{name, category, version, port, process_or_service,
    detection_method, evidence}]."""
    sections = _split_sections(raw_output)
    ports_text = sections.get("LISTENING_PORTS", "")
    proc_text = sections.get("PROCESSES", "")
    svc_text = sections.get("SERVICES", "")
    pkg_text = sections.get("PACKAGES", "")
    ver_text = sections.get("VERSIONS", "")
    port_map = _port_map_from_listeners(ports_text)

    haystacks = {
        "process": proc_text.lower(),
        "service": svc_text.lower(),
        "package": pkg_text.lower(),
        "version": ver_text.lower(),
    }

    results = []
    for fp in _LINUX_FINGERPRINTS:
        matched_method = None
        evidence_line = None
        for method, text in haystacks.items():
            for kw in fp["keywords"]:
                kw_clean = kw.strip("^$").lower()
                if kw_clean and kw_clean in text:
                    matched_method = method
                    src_text = {"process": proc_text, "service": svc_text,
                                "package": pkg_text, "version": ver_text}[method]
                    for line in src_text.splitlines():
                        if kw_clean in line.lower():
                            evidence_line = line.strip()[:250]
                            break
                    break
            if matched_method:
                break
        if not matched_method:
            continue

        version = _extract_version(ver_text, fp["keywords"])
        port = fp.get("port")
        for kw in fp["keywords"]:
            kw_clean = kw.strip("^$").lower()
            if not kw_clean:
                continue
            matched_port = next(
                (port_list[0] for proc_name, port_list in port_map.items() if kw_clean in proc_name),
                None,
            )
            if matched_port is not None:
                port = matched_port
                break

        results.append({
            "name": fp["name"],
            "category": fp["category"],
            "version": version,
            "port": port,
            "process_or_service": evidence_line[:200] if evidence_line else None,
            "detection_method": matched_method,
            "evidence": evidence_line,
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
                    results.append({
                        "name": fp["name"], "category": fp["category"], "version": None,
                        "port": fp["port"], "process_or_service": display_name or svc_name,
                        "detection_method": "service", "evidence": f"Service: {display_name or svc_name}",
                    })
                    seen_names.add(fp["name"])
                break

    if data.get("iis_installed"):
        results.append({
            "name": "IIS (Internet Information Services)", "category": "webserver", "version": None,
            "port": 80, "process_or_service": "W3SVC", "detection_method": "service",
            "evidence": f"W3SVC status: {data.get('iis_status')}",
        })

    sql_instances = data.get("sql_instances") or []
    if isinstance(sql_instances, str):
        sql_instances = [sql_instances]
    if sql_instances and "Microsoft SQL Server" not in seen_names:
        results.append({
            "name": "Microsoft SQL Server", "category": "database", "version": None,
            "port": 1433, "process_or_service": ", ".join(str(i) for i in sql_instances),
            "detection_method": "registry", "evidence": f"Instances: {', '.join(str(i) for i in sql_instances)}",
        })
        seen_names.add("Microsoft SQL Server")

    installed_programs = data.get("installed_programs") or []
    if isinstance(installed_programs, dict):
        installed_programs = [installed_programs]
    for prog in installed_programs:
        display_name = str((prog or {}).get("DisplayName") or "").strip()
        display_version = str((prog or {}).get("DisplayVersion") or "").strip() or None
        if not display_name:
            continue
        # Zaten servis/registry ile eşleşmiş ürünlere sürüm bilgisini ekle,
        # eşleşmemiş yeni bir ürünse ("other" kategori) yeni kayıt aç.
        matched = None
        for r in results:
            if r["name"].split()[0].lower() in display_name.lower() or display_name.lower() in r["name"].lower():
                matched = r
                break
        if matched:
            if not matched.get("version"):
                matched["version"] = display_version
        elif display_name not in seen_names:
            results.append({
                "name": display_name[:120], "category": "other", "version": display_version,
                "port": None, "process_or_service": None, "detection_method": "registry",
                "evidence": f"Installed program: {display_name} {display_version or ''}".strip(),
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
        # DB kolon sinirlarini asan degerler (ornegin beklenmedik uzun installed
        # program adlari/versiyonlari) sessizce kirpilir — kolon tasmasi tum
        # taramayi rollback etmesin.
        for a in apps:
            a["name"] = _clip(a.get("name"), 120) or "unknown"
            a["category"] = _clip(a.get("category"), 40) or "other"
            a["version"] = _clip(a.get("version"), 120)
            a["process_or_service"] = _clip(a.get("process_or_service"), 200)
            a["detection_method"] = _clip(a.get("detection_method"), 30)

        seen_names = {a["name"] for a in apps}

        existing_rows = db.query(DiscoveredApplication).filter(
            DiscoveredApplication.server_id == server.id
        ).all()
        existing_by_name = {r.name: r for r in existing_rows}

        for app in apps:
            row = existing_by_name.get(app["name"])
            if row:
                row.category = app["category"]
                row.version = app.get("version") or row.version
                row.port = app.get("port") or row.port
                row.process_or_service = app.get("process_or_service") or row.process_or_service
                row.detection_method = app.get("detection_method") or row.detection_method
                row.evidence = app.get("evidence") or row.evidence
                row.status = "running"
                row.last_seen_at = now
                row.times_confirmed = (row.times_confirmed or 1) + 1
                row.source = source
            else:
                db.add(DiscoveredApplication(
                    server_id=server.id, name=app["name"], category=app["category"],
                    version=app.get("version"), port=app.get("port"),
                    process_or_service=app.get("process_or_service"),
                    detection_method=app.get("detection_method"), evidence=app.get("evidence"),
                    status="running", source=source,
                    first_detected_at=now, last_seen_at=now, times_confirmed=1,
                ))
            touched += 1

        for name, row in existing_by_name.items():
            if name not in seen_names and row.status != "stopped":
                row.status = "stopped"

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


def discover_applications_all_servers(db: Session, force: bool = False) -> Dict[str, Any]:
    """Tüm AI Ready sunucularda (rescan aralığı dolmuş olanlar) uygulama
    taraması yapar. Arka plan görevi tarafından periyodik çağrılır."""
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

    if linux_servers:
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="app-discovery") as pool:
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

    for srv in windows_servers:
        try:
            apps = scan_server_windows(srv, db)
            n = upsert_discovered_apps(db, srv, apps, source="winrm")
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
                bits.append(f"v{r.version}" if not r.version.lower().startswith(r.name.lower()[:4]) else r.version)
            if r.port:
                bits.append(f"port {r.port}")
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
