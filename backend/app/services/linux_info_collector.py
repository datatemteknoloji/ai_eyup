"""
Linux sunuculardan SSH ile gercek sistem bilgilerini toplar.
AI Chat icin zengin context olusturur.
"""
import logging
from typing import Dict, Any, List
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

COMMAND_GROUPS = {
    "kernel": [
        ("uname -r", "kernel_version"),
        ("uname -a", "kernel_full"),
    ],
    "os": [
        ("cat /etc/os-release 2>/dev/null | grep -E '^NAME=|^VERSION=|^PRETTY_NAME='", "os_info"),
    ],
    "cpu": [
        ("nproc", "cpu_count"),
        ("lscpu 2>/dev/null | grep -E 'Model name|Architecture|CPU.s.|Thread|Core' | head -6", "cpu_detail"),
        ("top -bn1 2>/dev/null | grep 'Cpu' | head -1", "cpu_usage"),
    ],
    "memory": [
        ("free -h", "memory_info"),
    ],
    "disk": [
        ("df -h 2>/dev/null | head -15", "disk_usage"),
        ("lsblk -d -o NAME,SIZE,TYPE 2>/dev/null | head -10", "block_devices"),
    ],
    "network": [
        ("ip addr 2>/dev/null | grep -E 'inet |^[0-9]+:' | head -20", "network_interfaces"),
        ("ss -tuln 2>/dev/null | head -20", "listening_ports"),
    ],
    "processes": [
        ("ps aux --sort=-%cpu 2>/dev/null | head -11", "top_processes"),
    ],
    "services": [
        ("systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -20", "running_services"),
        ("systemctl list-units --type=service --state=failed --no-pager 2>/dev/null | head -10", "failed_services"),
    ],
    "uptime": [
        ("uptime", "uptime"),
    ],
    "load": [
        ("cat /proc/loadavg", "load_avg"),
        ("vmstat 1 2 2>/dev/null | tail -1", "vmstat"),
    ],
    "logs": [
        ("journalctl -p err --since '1 hour ago' --no-pager 2>/dev/null | tail -15", "error_logs"),
    ],
    "security": [
        ("last -n 10 2>/dev/null", "last_logins"),
        ("who 2>/dev/null", "current_users"),
    ],
    "packages": [
        ("rpm -qa --last 2>/dev/null | head -10", "recent_packages"),
    ],
    "cron": [
        ("crontab -l 2>/dev/null", "user_cron"),
    ],
}

KEYWORD_TO_GROUPS = {
    "kernel": ["kernel", "os"], "cekirdek": ["kernel", "os"],
    "os": ["os", "kernel"], "isletim": ["os", "kernel"],
    "cpu": ["cpu", "load"], "islemci": ["cpu", "load"],
    "ram": ["memory"], "bellek": ["memory"], "memory": ["memory"],
    "disk": ["disk"], "depolama": ["disk"], "storage": ["disk"],
    "network": ["network"], "ag": ["network"], "port": ["network"], "ip": ["network"],
    "servis": ["services"], "service": ["services"],
    "process": ["processes"], "proses": ["processes"],
    "uptime": ["uptime", "load"], "calisma": ["uptime"],
    "yuk": ["load", "cpu"], "load": ["load", "cpu"],
    "log": ["logs"], "hata": ["logs"], "error": ["logs"],
    "guvenlik": ["security"], "login": ["security"], "giris": ["security"],
    "paket": ["packages"], "rpm": ["packages"], "yum": ["packages"],
    "cron": ["cron"], "zamanlayici": ["cron"],
    "rapor": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime", "processes"],
    "ozet": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "durum": ["cpu", "memory", "disk", "uptime", "services"],
    "performans": ["cpu", "memory", "load", "disk"],
    "bilgi": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "tum": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "genel": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
}


def detect_needed_groups(message: str) -> List[str]:
    import unicodedata
    msg = unicodedata.normalize('NFKD', message.lower())
    msg = ''.join(c for c in msg if not unicodedata.combining(c))
    groups = set()
    for keyword, group_list in KEYWORD_TO_GROUPS.items():
        if keyword in msg:
            groups.update(group_list)
    if not groups:
        groups = {"kernel", "os", "cpu", "memory", "disk", "uptime"}
    return list(groups)


def collect_server_info(server, groups: List[str], global_cred=None) -> Dict[str, Any]:
    conn = server.connection_config or {}
    username = conn.get("username") or (global_cred.username if global_cred else None)
    password = conn.get("password") or (global_cred.password if global_cred else None)
    private_key = conn.get("private_key") or (global_cred.private_key if global_cred else None)
    port = conn.get("port", 22) or (global_cred.port if global_cred else 22)
    sudo_password = conn.get("sudo_password") or password

    if not username:
        return {"error": "SSH credential yok"}

    ssh = SSHManager(
        host=server.ip_address or server.hostname,
        username=username, password=password,
        private_key=private_key, port=port, sudo_password=sudo_password,
    )

    if not ssh.connect():
        return {"error": f"SSH baglantisi kurulamadi: {server.ip_address}"}

    results = {}
    try:
        for group_name in groups:
            for cmd, key in COMMAND_GROUPS.get(group_name, []):
                try:
                    success, stdout, stderr = ssh.execute_command(cmd)
                    output = stdout.strip() if success and stdout.strip() else (stderr.strip() if not success else "")
                    if output:
                        results[key] = output
                except Exception as e:
                    logger.debug(f"Cmd failed {cmd}: {e}")
    finally:
        ssh.close()

    return results


def build_server_context(server, info: Dict[str, Any]) -> str:
    if info.get("error"):
        return f"[{server.name}] Hata: {info['error']}"

    lines = [f"=== {server.name} ({server.ip_address}) ==="]
    field_labels = {
        "os_info": "OS", "kernel_version": "Kernel",
        "cpu_detail": "CPU", "cpu_usage": "CPU Kullanim", "cpu_count": "CPU Adet",
        "memory_info": "Bellek", "disk_usage": "Disk",
        "block_devices": "Disk Aygitlari", "network_interfaces": "Ag Arayuzleri",
        "listening_ports": "Dinlenen Portlar", "uptime": "Uptime",
        "load_avg": "Load Average", "vmstat": "vmstat",
        "running_services": "Calisan Servisler", "failed_services": "Hatali Servisler",
        "top_processes": "En Yogun Surecler", "error_logs": "Hata Loglari",
        "last_logins": "Son Girisler", "current_users": "Aktif Kullanicilar",
        "recent_packages": "Son Paketler", "user_cron": "Cron Gorevleri",
    }
    for key, label in field_labels.items():
        if key in info and info[key]:
            val = info[key].replace('"', '').strip()
            if key == "os_info":
                val = '\n'.join(l.split('=', 1)[-1].strip() for l in val.split('\n') if '=' in l)
            lines.append(f"{label}:\n{val}")

    return "\n\n".join(lines)
