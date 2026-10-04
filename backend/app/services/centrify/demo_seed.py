"""Centrify demo seed — gerçekçi test verisi oluşturur.

WinRM bağlantısı olmadan tüm UI'ı test etmek için Centrify DB'ye
zone ağacı, roller, komutlar, atamalar, operasyonlar ve audit kaydı ekler.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Tekrarlanabilir UUID'ler
def _uid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-demo-{name}")

DN_BASE = "OU=Centrify,DC=corp,DC=example,DC=com"

# ── Zone tanımları ────────────────────────────────────────────

ZONES = [
    # İki kök zone — gerçek Centrify Access Manager yapısı
    {"key": "global",    "name": "Global",           "type": "hierarchical", "parent": None,        "desc": "Global zone — tüm domain genelinde geçerli ayarlar"},
    {"key": "universal", "name": "Universal",        "type": "hierarchical", "parent": None,        "desc": "Universal zone — organizasyonel yapı ve child zone'lar"},
    # Universal altındaki child zone'lar
    {"key": "backup",    "name": "Backup",           "type": "hierarchical", "parent": "universal", "desc": "Yedekleme sunucuları"},
    {"key": "network",   "name": "Network",          "type": "hierarchical", "parent": "universal", "desc": "Ağ altyapı sunucuları"},
    {"key": "oracle",    "name": "Oracle",            "type": "hierarchical", "parent": "universal", "desc": "Oracle veritabanı sunucuları"},
    {"key": "oracle-apps","name": "Oracle Applications","type": "hierarchical","parent": "universal","desc": "Oracle uygulama sunucuları"},
    {"key": "other-apps","name": "Other Applications","type": "hierarchical", "parent": "universal", "desc": "Diğer uygulama sunucuları"},
    {"key": "storage",   "name": "Storage",           "type": "hierarchical", "parent": "universal", "desc": "Depolama sunucuları"},
    {"key": "sybase",    "name": "Sybase",             "type": "hierarchical", "parent": "universal", "desc": "Sybase veritabanı sunucuları"},
    {"key": "tomcat",    "name": "Tomcat Applications","type": "hierarchical", "parent": "universal", "desc": "Tomcat uygulama sunucuları"},
    {"key": "websphere", "name": "Websphere Applications","type": "hierarchical","parent": "universal","desc": "Websphere uygulama sunucuları"},
    {"key": "windows",   "name": "Windows",           "type": "hierarchical", "parent": "universal", "desc": "Windows sunucuları"},
]

# ── Rol tanımları (zone_key → roller) ────────────────────────

ROLES: dict[str, list[dict]] = {
    "global": [
        {"name": "always_permit_login", "desc": "Predefined system role for allowing login", "system": True,
         "allow_local": True, "password_login": True, "sso_login": True, "user_visible": True, "audit": "none"},
        {"name": "always_deny_login",   "desc": "Predefined system role for denying login", "system": True,
         "allow_local": True, "user_visible": False, "audit": "none"},
    ],
    "universal": [
        {"name": "sysadmin",       "desc": "Tam yetkili sistem yöneticisi — tüm komutlara erişim", "system": False,
         "password_login": True, "sso_login": True, "non_restricted_shell": True, "user_visible": True,
         "console_login": True, "remote_login": True, "powershell_remote": True, "audit": "required"},
        {"name": "readonly",       "desc": "Salt okunur erişim — yalnızca görüntüleme", "system": False,
         "sso_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "security-audit", "desc": "Güvenlik denetim rolü — log ve config okuma", "system": False,
         "sso_login": True, "user_visible": True, "require_mfa": True, "audit": "required"},
    ],
    "oracle": [
        {"name": "dba-admin",    "desc": "Veritabanı yöneticisi — start/stop/backup/restore", "system": False,
         "password_login": True, "non_restricted_shell": True, "user_visible": True, "audit": "required"},
        {"name": "dba-readonly", "desc": "DB salt okunur — yalnızca SELECT ve durum sorgulama", "system": False,
         "sso_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "dba-backup",   "desc": "Yedekleme operatörü — yalnızca backup/export komutları", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "dba-oracle",   "desc": "Oracle DB yöneticisi — oracle kullanıcı komutları", "system": False,
         "password_login": True, "ad_disabled_sudo": True, "non_restricted_shell": True, "user_visible": True, "audit": "required"},
    ],
    "tomcat": [
        {"name": "app-deploy",   "desc": "Uygulama dağıtım — deploy, restart, rollback", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "app-monitor",  "desc": "Uygulama izleme — log okuma, health check", "system": False,
         "sso_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "app-restart",  "desc": "Servis yeniden başlatma — yalnızca restart", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
    ],
    "network": [
        {"name": "infra-admin",   "desc": "Altyapı yöneticisi — DNS, NTP, LDAP yönetimi", "system": False,
         "password_login": True, "sso_login": True, "non_restricted_shell": True, "user_visible": True, "require_mfa": True, "audit": "required"},
        {"name": "network-ops",   "desc": "Ağ operasyonları — firewall, routing, interface", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "monitor-admin", "desc": "İzleme yöneticisi — Prometheus, Grafana config", "system": False,
         "sso_login": True, "user_visible": True, "audit": "if_possible"},
    ],
    "backup": [
        {"name": "backup-admin",  "desc": "Yedekleme yöneticisi — tam yetki", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
        {"name": "backup-ops",    "desc": "Yedekleme operatörü — sınırlı komut", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
    ],
    "other-apps": [
        {"name": "developer",    "desc": "Geliştirici — geniş yetki", "system": False,
         "password_login": True, "sso_login": True, "non_restricted_shell": True, "user_visible": True, "audit": "if_possible"},
        {"name": "dev-lead",     "desc": "Geliştirme lideri — developer + kullanıcı yönetimi", "system": False,
         "password_login": True, "sso_login": True, "non_restricted_shell": True, "user_visible": True, "require_mfa": True, "audit": "required"},
    ],
    "websphere": [
        {"name": "was-admin",    "desc": "Websphere yöneticisi — tam yetki", "system": False,
         "password_login": True, "non_restricted_shell": True, "user_visible": True, "audit": "required"},
        {"name": "was-ops",      "desc": "Websphere operatörü — restart/deploy", "system": False,
         "password_login": True, "user_visible": True, "audit": "if_possible"},
    ],
}

# ── Komut tanımları (zone_key → komutlar) ─────────────────────

COMMANDS: dict[str, list[dict]] = {
    "universal": [
        {"name": "reboot",            "path": "/usr/sbin/reboot",                "match": "exact",  "run_as": "root", "auth": "password", "desc": "Sunucu yeniden başlatma"},
        {"name": "shutdown",           "path": "/usr/sbin/shutdown *",            "match": "glob",   "run_as": "root", "auth": "mfa",      "desc": "Sunucu kapatma"},
        {"name": "systemctl-restart",  "path": "/usr/bin/systemctl restart *",    "match": "glob",   "run_as": "root", "auth": "password", "desc": "Servis yeniden başlatma"},
        {"name": "systemctl-status",   "path": "/usr/bin/systemctl status *",     "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Servis durumu"},
        {"name": "journalctl",         "path": "/usr/bin/journalctl *",           "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Sistem günlüğü"},
        {"name": "tail-log",           "path": "/usr/bin/tail -f /var/log/*",     "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Log takip"},
        {"name": "df",                 "path": "/usr/bin/df *",                   "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Disk kullanımı"},
        {"name": "ps-aux",             "path": "/usr/bin/ps aux",                 "match": "exact",  "run_as": "root", "auth": "none",     "desc": "Süreç listesi"},
        {"name": "netstat",            "path": "/usr/sbin/ss *",                  "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Ağ bağlantıları"},
        {"name": "firewall-cmd",       "path": "/usr/bin/firewall-cmd *",         "match": "glob",   "run_as": "root", "auth": "mfa",      "desc": "Firewall kuralı"},
        {"name": "useradd",            "path": "/usr/sbin/useradd *",             "match": "glob",   "run_as": "root", "auth": "password", "desc": "Kullanıcı ekleme"},
        {"name": "passwd",             "path": "/usr/bin/passwd *",               "match": "glob",   "run_as": "root", "auth": "mfa",      "desc": "Parola değiştirme"},
        {"name": "cat-config",         "path": "/usr/bin/cat /etc/*",             "match": "glob",   "run_as": "root", "auth": "none",     "desc": "Konfigürasyon okuma"},
    ],
    "oracle": [
        {"name": "oracle-start",       "path": "/u01/app/oracle/product/*/bin/dbstart",  "match": "glob",  "run_as": "oracle", "auth": "password", "desc": "Oracle DB başlatma"},
        {"name": "oracle-stop",        "path": "/u01/app/oracle/product/*/bin/dbshut",   "match": "glob",  "run_as": "oracle", "auth": "password", "desc": "Oracle DB durdurma"},
        {"name": "oracle-listener",    "path": "/u01/app/oracle/product/*/bin/lsnrctl *","match": "glob",  "run_as": "oracle", "auth": "password", "desc": "Oracle Listener yönetimi"},
        {"name": "rman-backup",        "path": "/u01/app/oracle/product/*/bin/rman *",   "match": "glob",  "run_as": "oracle", "auth": "password", "desc": "RMAN yedekleme"},
        {"name": "sqlplus",            "path": "/u01/app/oracle/product/*/bin/sqlplus *", "match": "glob",  "run_as": "oracle", "auth": "password", "desc": "SQL*Plus oturumu"},
    ],
    "tomcat": [
        {"name": "tomcat-start",       "path": "/opt/tomcat/bin/startup.sh",     "match": "exact",  "run_as": "tomcat",  "auth": "password", "desc": "Tomcat başlatma"},
        {"name": "tomcat-stop",        "path": "/opt/tomcat/bin/shutdown.sh",    "match": "exact",  "run_as": "tomcat",  "auth": "password", "desc": "Tomcat durdurma"},
        {"name": "deploy-war",         "path": "/opt/scripts/deploy.sh *",       "match": "glob",   "run_as": "appuser", "auth": "password", "desc": "WAR deploy"},
        {"name": "rollback",           "path": "/opt/scripts/rollback.sh *",     "match": "glob",   "run_as": "appuser", "auth": "password", "desc": "Uygulama rollback"},
        {"name": "app-log",            "path": "/usr/bin/tail -f /opt/*/logs/*", "match": "glob",   "run_as": "root",    "auth": "none",     "desc": "Uygulama logları"},
        {"name": "jstack",             "path": "/usr/bin/jstack *",              "match": "glob",   "run_as": "tomcat",  "auth": "none",     "desc": "JVM thread dump"},
    ],
    "network": [
        {"name": "named-restart",      "path": "/usr/bin/systemctl restart named","match": "exact", "run_as": "root", "auth": "password", "desc": "DNS restart"},
        {"name": "rndc-reload",        "path": "/usr/sbin/rndc reload",          "match": "exact",  "run_as": "root", "auth": "password", "desc": "DNS zone reload"},
        {"name": "chrony-sources",     "path": "/usr/bin/chronyc sources",       "match": "exact",  "run_as": "root", "auth": "none",     "desc": "NTP kaynakları"},
    ],
    "websphere": [
        {"name": "was-start",         "path": "/opt/IBM/WebSphere/AppServer/bin/startServer.sh *", "match": "glob", "run_as": "wasadmin", "auth": "password", "desc": "WAS başlatma"},
        {"name": "was-stop",          "path": "/opt/IBM/WebSphere/AppServer/bin/stopServer.sh *",  "match": "glob", "run_as": "wasadmin", "auth": "password", "desc": "WAS durdurma"},
    ],
}

# Rol → komut bağlama
ROLE_COMMANDS: dict[str, dict[str, list[str]]] = {
    "universal": {
        "sysadmin": ["reboot", "shutdown", "systemctl-restart", "systemctl-status", "journalctl", "tail-log", "df", "ps-aux", "netstat", "firewall-cmd", "useradd", "passwd", "cat-config"],
        "readonly": ["systemctl-status", "journalctl", "tail-log", "df", "ps-aux", "netstat", "cat-config"],
        "security-audit": ["journalctl", "tail-log", "cat-config", "netstat", "ps-aux"],
    },
    "oracle": {
        "dba-admin": ["oracle-start", "oracle-stop", "oracle-listener", "rman-backup", "sqlplus"],
        "dba-readonly": ["sqlplus"],
        "dba-backup": ["rman-backup", "sqlplus"],
        "dba-oracle": ["oracle-start", "oracle-stop", "oracle-listener", "rman-backup", "sqlplus"],
    },
    "tomcat": {
        "app-deploy": ["tomcat-start", "tomcat-stop", "deploy-war", "rollback", "app-log", "jstack"],
        "app-monitor": ["app-log", "jstack", "tomcat-start", "tomcat-stop"],
        "app-restart": ["tomcat-start", "tomcat-stop"],
    },
    "network": {
        "infra-admin": ["named-restart", "rndc-reload", "chrony-sources"],
        "network-ops": ["named-restart", "rndc-reload"],
        "monitor-admin": ["chrony-sources"],
    },
    "websphere": {
        "was-admin": ["was-start", "was-stop"],
        "was-ops": ["was-start", "was-stop"],
    },
}

# ── Role assignment'lar ───────────────────────────────────────

ASSIGNMENTS = [
    {"zone": "universal", "role": "sysadmin",       "type": "group", "name": "GRP_Unix_SysAdmins",     "dn": "CN=GRP_Unix_SysAdmins,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "universal", "role": "sysadmin",       "type": "user",  "name": "john.smith",             "dn": "CN=John Smith,OU=Users,DC=corp,DC=example,DC=com"},
    {"zone": "universal", "role": "readonly",       "type": "group", "name": "GRP_L1_Support",         "dn": "CN=GRP_L1_Support,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "universal", "role": "security-audit", "type": "group", "name": "GRP_Security_Team",      "dn": "CN=GRP_Security_Team,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "oracle",    "role": "dba-admin",      "type": "group", "name": "GRP_DBAs",               "dn": "CN=GRP_DBAs,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "oracle",    "role": "dba-admin",      "type": "user",  "name": "maria.garcia",           "dn": "CN=Maria Garcia,OU=Users,DC=corp,DC=example,DC=com"},
    {"zone": "oracle",    "role": "dba-readonly",   "type": "group", "name": "GRP_App_Developers",     "dn": "CN=GRP_App_Developers,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "oracle",    "role": "dba-backup",     "type": "user",  "name": "backup.operator",        "dn": "CN=Backup Operator,OU=ServiceAccounts,DC=corp,DC=example,DC=com"},
    {"zone": "oracle",    "role": "dba-oracle",     "type": "group", "name": "GRP_Oracle_DBAs",        "dn": "CN=GRP_Oracle_DBAs,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "tomcat",    "role": "app-deploy",     "type": "group", "name": "GRP_Release_Engineers",  "dn": "CN=GRP_Release_Engineers,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "tomcat",    "role": "app-monitor",    "type": "group", "name": "GRP_App_Support",        "dn": "CN=GRP_App_Support,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "tomcat",    "role": "app-restart",    "type": "group", "name": "GRP_L2_Support",         "dn": "CN=GRP_L2_Support,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "network",   "role": "infra-admin",    "type": "group", "name": "GRP_Infra_Team",         "dn": "CN=GRP_Infra_Team,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "network",   "role": "network-ops",    "type": "group", "name": "GRP_Network_Ops",        "dn": "CN=GRP_Network_Ops,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "network",   "role": "monitor-admin",  "type": "user",  "name": "prometheus.admin",       "dn": "CN=Prometheus Admin,OU=ServiceAccounts,DC=corp,DC=example,DC=com"},
    {"zone": "other-apps","role": "developer",      "type": "group", "name": "GRP_Developers",         "dn": "CN=GRP_Developers,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "other-apps","role": "dev-lead",       "type": "user",  "name": "ahmet.yilmaz",           "dn": "CN=Ahmet Yilmaz,OU=Users,DC=corp,DC=example,DC=com"},
    {"zone": "websphere", "role": "was-admin",      "type": "group", "name": "GRP_WAS_Admins",         "dn": "CN=GRP_WAS_Admins,OU=Groups,DC=corp,DC=example,DC=com"},
    {"zone": "backup",    "role": "backup-admin",   "type": "group", "name": "GRP_Backup_Team",        "dn": "CN=GRP_Backup_Team,OU=Groups,DC=corp,DC=example,DC=com"},
]

# ── Computer'lar ──────────────────────────────────────────────

COMPUTERS = [
    # Ekran görüntüsündeki gerçekçi isimler
    {"zone": "other-apps","name": "mxapptest1",      "fqdn": "mxapptest1.kfs.local",             "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "mxapptest2",      "fqdn": "mxapptest2.kfs.local",             "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "drcvlp",          "fqdn": "drcvlp.kfs.local",                 "os": "Solaris [10.0]",                 "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "opcnottest",      "fqdn": "opcnottest.kfs.local",             "os": "Red Hat Enterprise Linux [6.10]","agent": "5.7.1-353"},
    {"zone": "other-apps","name": "opcnotdev",       "fqdn": "opcnotdev.kfs.local",              "os": "Red Hat Enterprise Linux [6.10]","agent": "5.7.1-353"},
    {"zone": "other-apps","name": "mxappprd1",       "fqdn": "mxappprd1.kfs.local",              "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "mxappprd2",       "fqdn": "mxappprd2.kfs.local",              "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "mxappprd3",       "fqdn": "mxappprd3.kfs.local",              "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "other-apps","name": "mxappprd4",       "fqdn": "mxappprd4.kfs.local",              "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "oracle",    "name": "oradb-prod-01",   "fqdn": "oradb-prod-01.kfs.local",          "os": "Red Hat Enterprise Linux [8.9]", "agent": "6.0.1-374"},
    {"zone": "oracle",    "name": "oradb-prod-02",   "fqdn": "oradb-prod-02.kfs.local",          "os": "Red Hat Enterprise Linux [8.9]", "agent": "6.0.1-374"},
    {"zone": "oracle-apps","name": "opclagaprd1",    "fqdn": "opclagaprd1.kfs.local",            "os": "Red Hat Enterprise Linux [6.10]","agent": "5.3.1-398"},
    {"zone": "tomcat",    "name": "appsvr-prod-01",  "fqdn": "appsvr-prod-01.kfs.local",         "os": "Red Hat Enterprise Linux [9.4]", "agent": "6.0.1-374"},
    {"zone": "tomcat",    "name": "appsvr-prod-02",  "fqdn": "appsvr-prod-02.kfs.local",         "os": "Red Hat Enterprise Linux [9.4]", "agent": "6.0.1-374"},
    {"zone": "network",   "name": "dns-prod-01",     "fqdn": "dns-prod-01.kfs.local",            "os": "Red Hat Enterprise Linux [8.8]", "agent": "6.0.1-374"},
    {"zone": "network",   "name": "monitor-prod-01", "fqdn": "monitor-prod-01.kfs.local",        "os": "Red Hat Enterprise Linux [9.4]", "agent": "6.0.1-374"},
    {"zone": "backup",    "name": "bkp-srv-01",      "fqdn": "bkp-srv-01.kfs.local",             "os": "Red Hat Enterprise Linux [8.10]","agent": "6.0.1-374"},
    {"zone": "backup",    "name": "bkp-srv-02",      "fqdn": "bkp-srv-02.kfs.local",             "os": "Red Hat Enterprise Linux [8.10]","agent": "6.0.1-374"},
    {"zone": "websphere", "name": "was-prod-01",     "fqdn": "was-prod-01.kfs.local",            "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "websphere", "name": "was-prod-02",     "fqdn": "was-prod-02.kfs.local",            "os": "Red Hat Enterprise Linux [7.9]", "agent": "6.0.1-374"},
    {"zone": "storage",   "name": "nfs-prod-01",     "fqdn": "nfs-prod-01.kfs.local",            "os": "Red Hat Enterprise Linux [8.8]", "agent": "5.9.2-429"},
    {"zone": "global",    "name": "kamelya",         "fqdn": "kamelya.kfs.local",                "os": "Solaris [6.0]",                  "agent": "5.7.1-353"},
]

# ── Computer Role'ler ─────────────────────────────────────────

COMPUTER_ROLES = [
    {"zone": "oracle",      "name": "DatabaseServers",   "desc": "Tüm veritabanı sunucuları", "members": ["oradb-prod-01", "oradb-prod-02"]},
    {"zone": "tomcat",      "name": "AppServers",        "desc": "Uygulama sunucuları",       "members": ["appsvr-prod-01", "appsvr-prod-02"]},
    {"zone": "network",     "name": "InfraServers",      "desc": "Altyapı sunucuları",        "members": ["dns-prod-01", "monitor-prod-01"]},
    {"zone": "other-apps",  "name": "MXServers",         "desc": "MX uygulama sunucuları",    "members": ["mxappprd1", "mxappprd2", "mxappprd3", "mxappprd4"]},
    {"zone": "websphere",   "name": "WASServers",        "desc": "Websphere sunucuları",      "members": ["was-prod-01", "was-prod-02"]},
    {"zone": "backup",      "name": "BackupServers",     "desc": "Yedekleme sunucuları",      "members": ["bkp-srv-01", "bkp-srv-02"]},
]

# ── UNIX Profiller ────────────────────────────────────────────

UNIX_PROFILES = [
    {"zone": "universal", "user": "john.smith",      "uid": 10001, "gid": 10000, "home": "/home/john.smith",      "shell": "/bin/bash"},
    {"zone": "universal", "user": "backup.operator", "uid": 10099, "gid": 10050, "home": "/home/backup.operator", "shell": "/bin/bash"},
    {"zone": "universal", "user": "erhan.turkmen",   "uid": 10251, "gid": 10000, "home": "/home/erhan.turkmen",   "shell": "/bin/bash"},
    {"zone": "universal", "user": "betul.urhan",     "uid": 10380, "gid": 10000, "home": "/home/betul.urhan",     "shell": "/bin/bash"},
    {"zone": "universal", "user": "lale.gurel",      "uid": 10043, "gid": 10000, "home": "/home/lale.gurel",      "shell": "/bin/bash"},
    {"zone": "universal", "user": "aytac.yologlu",   "uid": 10432, "gid": 10000, "home": "/home/aytac.yologlu",   "shell": "/bin/bash"},
    {"zone": "universal", "user": "seda.ikizler",    "uid": 10529, "gid": 10000, "home": "/home/seda.ikizler",    "shell": "/bin/bash"},
    {"zone": "universal", "user": "hulya.ertopuz",   "uid": 10552, "gid": 10000, "home": "/home/hulya.ertopuz",   "shell": "/bin/bash"},
    {"zone": "oracle",    "user": "maria.garcia",    "uid": 10002, "gid": 10010, "home": "/home/maria.garcia",    "shell": "/bin/bash"},
    {"zone": "oracle",    "user": "oracle",          "uid": 1001,  "gid": 1001,  "home": "/u01/app/oracle",       "shell": "/bin/bash"},
    {"zone": "tomcat",    "user": "tomcat",           "uid": 1002,  "gid": 1002,  "home": "/opt/tomcat",           "shell": "/sbin/nologin"},
    {"zone": "other-apps","user": "ahmet.yilmaz",    "uid": 10003, "gid": 10000, "home": "/home/ahmet.yilmaz",    "shell": "/bin/zsh"},
    {"zone": "websphere", "user": "wasadmin",         "uid": 1003,  "gid": 1003,  "home": "/opt/IBM/WebSphere",    "shell": "/bin/bash"},
]

# ── Seed fonksiyonu ───────────────────────────────────────────

def seed_demo_data() -> dict:
    """Centrify DB'ye demo verisi ekler. İdempotent: mevcutsa siler ve yeniden oluşturur."""
    from app.services.centrify.database import get_centrify_thread_session, create_centrify_tables
    from app.models.centrify_zone import (
        CentrifyZone, CentrifyRole, CentrifyCommand, CentrifyRoleCommand,
        CentrifyComputer, CentrifyComputerRole, CentrifyComputerRoleMember,
        CentrifyRoleAssignment, CentrifyUnixProfile,
        CentrifyOperation, CentrifyAuditLog, CentrifyDriftEvent,
        CentrifyIntegrationConfig,
    )

    create_centrify_tables()
    db = get_centrify_thread_session()
    if db is None:
        return {"ok": False, "error": "Centrify DB erişilemiyor"}

    try:
        # Temizle (sıra FK bağımlılıklarına göre)
        for model in [CentrifyDriftEvent, CentrifyAuditLog, CentrifyOperation,
                      CentrifyComputerRoleMember, CentrifyComputerRole,
                      CentrifyRoleCommand, CentrifyRoleAssignment,
                      CentrifyUnixProfile, CentrifyComputer,
                      CentrifyCommand, CentrifyRole, CentrifyZone]:
            db.query(model).delete()
        db.flush()

        now = datetime.now(timezone.utc)
        sync_time = now - timedelta(minutes=12)

        # 1. Zone'lar
        zone_map: dict[str, CentrifyZone] = {}
        for z in ZONES:
            dn = f"CN={z['name']},CN=Zones,{DN_BASE}"
            if z["parent"]:
                parent_name = next(zz["name"] for zz in ZONES if zz["key"] == z["parent"])
                dn = f"CN={z['name']},CN={parent_name},CN=Zones,{DN_BASE}"
            zone = CentrifyZone(
                ad_guid=_uid(f"zone-{z['key']}"),
                ad_dn=dn, name=z["name"], zone_type=z["type"],
                description=z["desc"], management_state="managed",
                last_synced_at=sync_time, last_seen_in_ad=sync_time,
            )
            db.add(zone)
            db.flush()
            zone_map[z["key"]] = zone

        # Parent ilişkileri
        for z in ZONES:
            if z["parent"] and z["parent"] in zone_map:
                zone_map[z["key"]].parent_zone_id = zone_map[z["parent"]].id
        db.flush()

        # 2. Roller
        role_map: dict[str, dict[str, CentrifyRole]] = {}
        for zkey, roles in ROLES.items():
            role_map[zkey] = {}
            zone = zone_map[zkey]
            for r in roles:
                role = CentrifyRole(
                    zone_id=zone.id,
                    ad_guid=_uid(f"role-{zkey}-{r['name']}"),
                    ad_dn=f"CN={r['name']},CN=Roles,{zone.ad_dn}",
                    name=r["name"], description=r["desc"],
                    is_system_role=r["system"],
                    management_state="managed" if not r["system"] else "imported_readonly",
                    allow_local_accounts=r.get("allow_local", False),
                    password_login_allowed=r.get("password_login", False),
                    sso_login_allowed=r.get("sso_login", False),
                    ad_disabled_sudo_cron=r.get("ad_disabled_sudo", False),
                    non_restricted_shell=r.get("non_restricted_shell", False),
                    user_visible=r.get("user_visible", True),
                    console_login_allowed=r.get("console_login", False),
                    remote_login_allowed=r.get("remote_login", False),
                    powershell_remote_allowed=r.get("powershell_remote", False),
                    rescue_login_allowed=r.get("rescue_login", False),
                    require_mfa=r.get("require_mfa", False),
                    audit_level=r.get("audit", "if_possible"),
                    last_synced_at=sync_time, last_seen_in_ad=sync_time,
                )
                db.add(role)
                db.flush()
                role_map[zkey][r["name"]] = role

        # 3. Komutlar
        cmd_map: dict[str, dict[str, CentrifyCommand]] = {}
        for zkey, cmds in COMMANDS.items():
            cmd_map[zkey] = {}
            zone = zone_map[zkey]
            for c in cmds:
                cmd = CentrifyCommand(
                    zone_id=zone.id,
                    ad_guid=_uid(f"cmd-{zkey}-{c['name']}"),
                    ad_dn=f"CN={c['name']},CN=Commands,{zone.ad_dn}",
                    name=c["name"], command_path=c["path"],
                    match_type=c["match"], run_as_user=c["run_as"],
                    auth_type=c["auth"], description=c["desc"],
                    management_state="managed",
                    last_synced_at=sync_time, last_seen_in_ad=sync_time,
                )
                db.add(cmd)
                db.flush()
                cmd_map[zkey][c["name"]] = cmd

        # 4. Role ↔ Command bağlantıları
        rc_count = 0
        for zkey, role_cmds in ROLE_COMMANDS.items():
            for role_name, cmd_names in role_cmds.items():
                if zkey not in role_map or role_name not in role_map[zkey]:
                    continue
                role = role_map[zkey][role_name]
                for cmd_name in cmd_names:
                    if zkey in cmd_map and cmd_name in cmd_map[zkey]:
                        rc = CentrifyRoleCommand(role_id=role.id, command_id=cmd_map[zkey][cmd_name].id)
                        db.add(rc)
                        rc_count += 1
        db.flush()

        # 5. Role Assignment'lar
        for a in ASSIGNMENTS:
            zkey = a["zone"]
            if zkey not in zone_map or zkey not in role_map or a["role"] not in role_map[zkey]:
                continue
            assgn = CentrifyRoleAssignment(
                zone_id=zone_map[zkey].id,
                ad_guid=_uid(f"asgn-{zkey}-{a['role']}-{a['name']}"),
                ad_dn=f"CN={a['name']},CN=Assignments,{zone_map[zkey].ad_dn}",
                role_id=role_map[zkey][a["role"]].id,
                assignee_type=a["type"],
                assignee_dn=a["dn"],
                assignee_name=a["name"],
                scope_type="zone",
                management_state="managed",
                last_synced_at=sync_time, last_seen_in_ad=sync_time,
            )
            db.add(assgn)
        db.flush()

        # 5b. Computer-scoped assignments (bilgisayar bazlı)
        # (comp_map henüz yok, aşağıda 6. adımdan sonra eklenecek)

        # 6. Computer'lar
        comp_map: dict[str, CentrifyComputer] = {}
        for c in COMPUTERS:
            comp = CentrifyComputer(
                zone_id=zone_map[c["zone"]].id,
                ad_guid=_uid(f"comp-{c['name']}"),
                ad_dn=f"CN={c['name']},CN=Computers,{zone_map[c['zone']].ad_dn}",
                name=c["name"], fqdn=c["fqdn"],
                os_type=c["os"], agent_version=c["agent"],
                management_state="managed",
                last_synced_at=sync_time, last_seen_in_ad=sync_time,
            )
            db.add(comp)
            db.flush()
            comp_map[c["name"]] = comp

        # 6b. Computer-scoped role assignments
        comp_scoped_assignments = [
            {"zone": "oracle", "computer": "oradb-prod-01", "role": "dba-admin", "type": "user", "name": "maria.garcia", "dn": "CN=Maria Garcia,OU=Users,DC=corp,DC=example,DC=com"},
            {"zone": "oracle", "computer": "oradb-prod-02", "role": "dba-backup", "type": "user", "name": "backup.operator", "dn": "CN=Backup Operator,OU=ServiceAccounts,DC=corp,DC=example,DC=com"},
            {"zone": "tomcat", "computer": "appsvr-prod-01", "role": "app-deploy", "type": "group", "name": "GRP_Release_Engineers", "dn": "CN=GRP_Release_Engineers,OU=Groups,DC=corp,DC=example,DC=com"},
            {"zone": "other-apps", "computer": "mxappprd1", "role": "developer", "type": "user", "name": "ahmet.yilmaz", "dn": "CN=Ahmet Yilmaz,OU=Users,DC=corp,DC=example,DC=com"},
            {"zone": "network", "computer": "dns-prod-01", "role": "infra-admin", "type": "group", "name": "GRP_Infra_Team", "dn": "CN=GRP_Infra_Team,OU=Groups,DC=corp,DC=example,DC=com"},
        ]
        for ca in comp_scoped_assignments:
            zkey = ca["zone"]
            comp_name = ca["computer"]
            if zkey not in zone_map or comp_name not in comp_map:
                continue
            if zkey not in role_map or ca["role"] not in role_map[zkey]:
                continue
            db.add(CentrifyRoleAssignment(
                zone_id=zone_map[zkey].id,
                computer_id=comp_map[comp_name].id,
                ad_guid=_uid(f"casgn-{comp_name}-{ca['role']}-{ca['name']}"),
                ad_dn=f"CN={ca['name']},CN=Assignments,CN={comp_name},{zone_map[zkey].ad_dn}",
                role_id=role_map[zkey][ca["role"]].id,
                assignee_type=ca["type"],
                assignee_dn=ca["dn"],
                assignee_name=ca["name"],
                scope_type="computer",
                management_state="managed",
                last_synced_at=sync_time, last_seen_in_ad=sync_time,
            ))
        db.flush()

        # 7. Computer Role'ler
        for cr_def in COMPUTER_ROLES:
            cr = CentrifyComputerRole(
                zone_id=zone_map[cr_def["zone"]].id,
                ad_guid=_uid(f"crole-{cr_def['name']}"),
                ad_dn=f"CN={cr_def['name']},CN=ComputerRoles,{zone_map[cr_def['zone']].ad_dn}",
                name=cr_def["name"], description=cr_def["desc"],
                management_state="managed",
                last_synced_at=sync_time, last_seen_in_ad=sync_time,
            )
            db.add(cr)
            db.flush()
            for member_name in cr_def["members"]:
                if member_name in comp_map:
                    db.add(CentrifyComputerRoleMember(computer_id=comp_map[member_name].id, computer_role_id=cr.id))
        db.flush()

        # 8. UNIX Profiller
        for p in UNIX_PROFILES:
            db.add(CentrifyUnixProfile(
                zone_id=zone_map[p["zone"]].id,
                user_dn=f"CN={p['user']},OU=Users,DC=corp,DC=example,DC=com",
                user_name=p["user"], uid=p["uid"], gid=p["gid"],
                home_dir=p["home"], shell=p["shell"], enabled=True,
                last_synced_at=sync_time,
            ))
        db.flush()

        # 9. Örnek operasyonlar
        ops_data = [
            {"type": "create_role", "zone": "tomcat", "status": "completed", "name": "app-restart",
             "by_name": "ahmet.yilmaz", "appr": "john.smith", "ago_h": 48},
            {"type": "clone_role", "zone": "websphere", "status": "completed", "name": "was-ops (clone of was-admin)",
             "by_name": "maria.garcia", "appr": "john.smith", "ago_h": 24},
            {"type": "create_command", "zone": "oracle", "status": "pending_approval", "name": "expdp (Data Pump Export)",
             "by_name": "maria.garcia", "appr": None, "ago_h": 2},
            {"type": "delete_role_assignment", "zone": "other-apps", "status": "failed", "name": "dev-intern ✕ developer",
             "by_name": "ahmet.yilmaz", "appr": "john.smith", "ago_h": 6, "error": "WinRM bağlantı zaman aşımı"},
            {"type": "overwrite_role", "zone": "backup", "status": "pending_approval", "name": "backup-ops (overwrite from backup-admin)",
             "by_name": "backup.operator", "appr": None, "ago_h": 1},
        ]
        for opd in ops_data:
            op = CentrifyOperation(
                correlation_id=_uid(f"op-{opd['name']}"),
                zone_id=zone_map[opd["zone"]].id,
                operation_type=opd["type"],
                desired_state={"name": opd["name"]},
                status=opd["status"],
                status_history=[{"from": "new", "to": opd["status"], "at": (now - timedelta(hours=opd["ago_h"])).isoformat()}],
                requested_by=1, requested_by_name=opd["by_name"],
                approved_by=2 if opd["appr"] else None,
                approved_by_name=opd["appr"],
                reason=f"Demo: {opd['name']}",
                error_message=opd.get("error"),
            )
            op.created_at = now - timedelta(hours=opd["ago_h"])
            db.add(op)
        db.flush()

        # 10. Audit log
        audit_entries = [
            {"action": "operation_created", "actor": "ahmet.yilmaz", "target": "app-restart", "result": "success", "ago_h": 48},
            {"action": "operation_approved", "actor": "john.smith", "target": "app-restart", "result": "success", "ago_h": 47},
            {"action": "operation_completed", "actor": "system", "target": "app-restart", "result": "success", "ago_h": 47},
            {"action": "operation_created", "actor": "maria.garcia", "target": "uat-deployer (clone)", "result": "success", "ago_h": 24},
            {"action": "operation_approved", "actor": "john.smith", "target": "uat-deployer (clone)", "result": "success", "ago_h": 23},
            {"action": "operation_completed", "actor": "system", "target": "uat-deployer (clone)", "result": "success", "ago_h": 23},
            {"action": "sync_completed", "actor": "system", "target": "Tüm zone'lar", "result": "success", "ago_h": 0},
            {"action": "operation_created", "actor": "maria.garcia", "target": "expdp komut tanımı", "result": "success", "ago_h": 2},
            {"action": "operation_failed", "actor": "system", "target": "dev-intern ataması silme", "result": "failed", "ago_h": 6},
        ]
        for ae in audit_entries:
            al = CentrifyAuditLog(
                correlation_id=_uid(f"audit-{ae['target']}-{ae['ago_h']}"),
                actor_user_id=1, actor_username=ae["actor"],
                target_type="operation", target_name=ae["target"],
                action=ae["action"], reason=f"Demo: {ae['target']}",
                result=ae["result"],
            )
            al.created_at = now - timedelta(hours=ae["ago_h"])
            db.add(al)
        db.flush()

        # 11. Drift event'leri
        drift_events = [
            {"zone": "universal", "obj": "sysadmin", "type": "role", "detail": {"field": "description", "expected": "Tam yetkili sistem yöneticisi", "actual": "Full sysadmin (changed by AD admin)"}},
            {"zone": "oracle", "obj": "dba-readonly", "type": "role", "detail": {"field": "commands", "removed": ["sqlplus"], "note": "sqlplus komutu AD tarafından kaldırılmış"}},
        ]
        for de in drift_events:
            db.add(CentrifyDriftEvent(
                zone_id=zone_map[de["zone"]].id,
                object_type=de["type"],
                object_ad_guid=_uid(f"drift-{de['obj']}"),
                object_name=de["obj"],
                expected_hash="abc123", actual_hash="def456",
                drift_details=de["detail"],
            ))
        db.flush()

        # 12. Demo config (yoksa oluştur)
        existing_cfg = db.query(CentrifyIntegrationConfig).first()
        if not existing_cfg:
            from app.core.encryption import encrypt_secret
            db.add(CentrifyIntegrationConfig(
                label="Demo Ortamı",
                winrm_host="accessmgr.corp.example.com",
                winrm_port=5985, winrm_https=False,
                service_account="service_centrify",
                password_enc=encrypt_secret("demo-password"),
                sync_interval_minutes=30,
                sync_enabled=True, enabled=True,
            ))
        db.flush()

        db.commit()

        stats = {
            "zones": len(zone_map),
            "roles": sum(len(v) for v in role_map.values()),
            "commands": sum(len(v) for v in cmd_map.values()),
            "role_commands": rc_count,
            "assignments": len(ASSIGNMENTS),
            "computers": len(COMPUTERS),
            "computer_roles": len(COMPUTER_ROLES),
            "unix_profiles": len(UNIX_PROFILES),
            "operations": len(ops_data),
            "audit_entries": len(audit_entries),
            "drift_events": len(drift_events),
        }
        logger.info("Centrify demo seed tamamlandı: %s", stats)
        return {"ok": True, **stats}

    except Exception as exc:
        db.rollback()
        logger.exception("Demo seed hatası")
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()
