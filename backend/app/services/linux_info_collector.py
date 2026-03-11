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
        ("hostname", "hostname_short"),
        ("hostname -f 2>/dev/null || hostname", "hostname_fqdn"),
    ],
    "os": [
        # Birden fazla yöntemi dene; PRETTY_NAME, VERSION, NAME, oracle-release, redhat-release hepsi
        ("( cat /etc/os-release 2>/dev/null | grep -E '^PRETTY_NAME=|^NAME=|^VERSION=|^VERSION_ID=' ; cat /etc/oracle-release 2>/dev/null ; cat /etc/redhat-release 2>/dev/null ; cat /etc/centos-release 2>/dev/null ) | sort -u | head -6", "os_info"),
        ("hostnamectl 2>/dev/null | grep -E 'Operating System|Kernel'", "os_hostnamectl"),
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
        # IP + MAC birlikte: ip addr full çıktısı (inet, ether satırları dahil)
        ("ip addr 2>/dev/null | grep -E '^[0-9]+:|link/ether|inet ' | head -60", "network_interfaces"),
        # ifconfig fallback (bazı sistemlerde ip addr yok)
        ("ifconfig 2>/dev/null | grep -E '^[a-z]|inet |ether ' | head -60 || true", "ifconfig_out"),
        # Kısa mac listesi: arayüz adı + MAC
        ("ip link show 2>/dev/null | grep -E '^[0-9]+:|link/ether' | awk '/^[0-9]+:/{iface=$2} /link\/ether/{print iface, $2}' | head -20", "mac_addresses"),
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
    "performance_deep": [
        # 10 örnek: vmstat/iostat 1 saniye aralıklı 10 kez (toplam ~10s, SSH timeout'a sığar)
        ("vmstat 1 10 2>/dev/null", "vmstat_1min"),
        ("iostat -x 1 10 2>/dev/null", "iostat_1min"),
        ("sar -u 1 10 2>/dev/null || echo 'sar not available'", "sar_cpu_1min"),
    ],
    "logs": [
        ("journalctl -p err --since '1 hour ago' --no-pager 2>/dev/null | tail -15", "error_logs"),
    ],
    "security": [
        ("last -n 10 2>/dev/null", "last_logins"),
        ("who 2>/dev/null", "current_users"),
        ("sestatus 2>/dev/null || getenforce 2>/dev/null || echo 'SELinux: not found'", "selinux_status"),
        ("systemctl is-active firewalld 2>/dev/null && firewall-cmd --state 2>/dev/null || iptables -L -n --line-numbers 2>/dev/null | head -20 || echo 'firewall: not checked'", "firewall_status"),
        ("ss -tuln 2>/dev/null | head -30", "open_ports"),
        ("cat /etc/sudoers.d/* 2>/dev/null | head -20 ; grep -v '^#' /etc/sudoers 2>/dev/null | head -20", "sudoers"),
    ],
    "packages": [
        ("rpm -qa --last 2>/dev/null | head -10", "recent_packages"),
    ],
    "cron": [
        ("crontab -l 2>/dev/null", "user_cron"),
    ],
}

KEYWORD_TO_GROUPS: dict = {

    # KERNEL / İŞLETİM SİSTEMİ
    "kernel": ["kernel", "os"], "cekirdek": ["kernel", "os"], "çekirdek": ["kernel", "os"],
    "uname": ["kernel", "os"], "uname -r": ["kernel", "os"], "uname -a": ["kernel", "os"],
    "kernel version": ["kernel", "os"], "kernel surumu": ["kernel", "os"],
    "kernel versiyonu": ["kernel", "os"], "modprobe": ["kernel"], "lsmod": ["kernel"],
    "kernel module": ["kernel"], "kernel modulu": ["kernel"], "dmesg": ["kernel", "logs"],
    "boot mesaji": ["kernel", "logs"], "initrd": ["kernel"], "grub": ["kernel"],
    "boot loader": ["kernel"], "uefi": ["kernel"], "bios": ["kernel"],
    "sysctl": ["kernel"], "kernel parametresi": ["kernel"], "/proc/version": ["kernel", "os"],
    "/proc/sys": ["kernel"],

    # İŞLETİM SİSTEMİ
    "os": ["os", "kernel"], "isletim": ["os", "kernel"], "işletim": ["os", "kernel"],
    "distro": ["os", "kernel"], "dagitim": ["os", "kernel"], "dağıtım": ["os", "kernel"],
    "release": ["os", "kernel"], "centos": ["os", "kernel"], "ubuntu": ["os", "kernel"],
    "rhel": ["os", "kernel"], "debian": ["os", "kernel"], "fedora": ["os", "kernel"],
    "suse": ["os", "kernel"], "almalinux": ["os", "kernel"], "rockylinux": ["os", "kernel"],
    "rocky linux": ["os", "kernel"], "arch linux": ["os", "kernel"],
    "oracle linux": ["os", "kernel"], "redhat": ["os", "kernel"], "red hat": ["os", "kernel"],
    "/etc/os-release": ["os", "kernel"], "/etc/redhat-release": ["os", "kernel"],
    "lsb_release": ["os", "kernel"], "os versiyonu": ["os", "kernel"],
    "os surumu": ["os", "kernel"], "hostname": ["os", "kernel"],
    "makine adi": ["os", "kernel"], "makine adı": ["os", "kernel"],
    "sunucu adi": ["os", "kernel"], "sunucu adı": ["os", "kernel"],
    "host": ["os", "kernel"], "fqdn": ["os", "kernel"], "hostnamectl": ["os", "kernel"],
    "timezone": ["os"], "saat dilimi": ["os"], "tarih": ["os"], "saat": ["os"],
    "timedatectl": ["os"], "locale": ["os"], "dil": ["os"], "encoding": ["os"],

    # CPU / İŞLEMCİ
    "cpu": ["cpu", "load"], "islemci": ["cpu", "load"], "işlemci": ["cpu", "load"],
    "processor": ["cpu", "load"], "lscpu": ["cpu", "load"], "core": ["cpu", "load"],
    "thread": ["cpu", "load"], "mhz": ["cpu", "load"], "ghz": ["cpu", "load"],
    "cpu model": ["cpu", "load"], "cpu bilgisi": ["cpu", "load"],
    "cpu kullanimi": ["cpu", "load"], "cpu kullanımı": ["cpu", "load"],
    "islemci kullanimi": ["cpu", "load"], "hyperthreading": ["cpu"],
    "numa": ["cpu", "performance_deep"], "cpu frekans": ["cpu"], "cpu frequency": ["cpu"],
    "cpu sicaklik": ["cpu", "performance_deep"], "cpu sıcaklık": ["cpu", "performance_deep"],
    "cpu temp": ["cpu", "performance_deep"], "turbo boost": ["cpu"], "cpu governor": ["cpu"],
    "cpu scaling": ["cpu"], "cstate": ["cpu", "performance_deep"], "cpufreq": ["cpu"],
    "/proc/cpuinfo": ["cpu"], "cpu architecture": ["cpu"], "cpu mimarisi": ["cpu"],
    "x86_64": ["cpu", "os"], "aarch64": ["cpu", "os"], "arm": ["cpu", "os"],
    "virtualization": ["cpu"], "sanallaştırma": ["cpu"], "sanallaştirma": ["cpu"],
    "vmx": ["cpu"], "svm": ["cpu"],

    # BELLEK / RAM
    "ram": ["memory"], "bellek": ["memory"], "memory": ["memory"],
    "free": ["memory"], "free -m": ["memory"], "free -h": ["memory"],
    "toplam ram": ["memory"], "kullanilan bellek": ["memory"], "kullanılan bellek": ["memory"],
    "swap": ["memory"], "takas": ["memory"], "buffers": ["memory"], "cache": ["memory"],
    "page cache": ["memory"], "shared memory": ["memory"], "paylasilan bellek": ["memory"],
    "available memory": ["memory"], "kullanilabilir bellek": ["memory"],
    "memory usage": ["memory"], "bellek kullanimi": ["memory"], "bellek kullanımı": ["memory"],
    "/proc/meminfo": ["memory"], "hugepages": ["memory", "performance_deep"],
    "transparent hugepage": ["memory", "performance_deep"], "thp": ["memory", "performance_deep"],
    "memory leak": ["memory", "performance_deep"], "bellek sizintisi": ["memory", "performance_deep"],
    "bellek sızıntısı": ["memory", "performance_deep"], "oom": ["memory", "performance_deep"],
    "out of memory": ["memory", "performance_deep"],
    "oom killer": ["memory", "performance_deep", "logs"],
    "slab": ["memory", "performance_deep"], "vmalloc": ["memory", "performance_deep"],
    "kmem": ["memory", "performance_deep"], "active memory": ["memory"],
    "inactive memory": ["memory"], "dirty pages": ["memory", "performance_deep"],
    "memory map": ["memory"], "mmap": ["memory"], "pmap": ["memory", "processes"],

    # DİSK / DEPOLAMA
    "disk": ["disk"], "depolama": ["disk"], "storage": ["disk"],
    "df": ["disk"], "df -h": ["disk"], "df -m": ["disk"], "lsblk": ["disk"],
    "fdisk": ["disk"], "mount": ["disk"], "bolumleme": ["disk"], "bölümleme": ["disk"],
    "partition": ["disk"], "dosya sistemi": ["disk"], "filesystem": ["disk"],
    "ext4": ["disk"], "xfs": ["disk"], "btrfs": ["disk"], "zfs": ["disk"],
    "ntfs": ["disk"], "vfat": ["disk"], "tmpfs": ["disk"],
    "disk doluluk": ["disk"], "disk doluluğu": ["disk"], "disk alani": ["disk"],
    "disk alanı": ["disk"], "disk space": ["disk"], "inodes": ["disk"], "inode": ["disk"],
    "du": ["disk"], "du -sh": ["disk"], "en buyuk dosya": ["disk"], "en büyük dosya": ["disk"],
    "large files": ["disk"], "raid": ["disk"], "mdadm": ["disk"], "lvm": ["disk"],
    "pv": ["disk"], "vg": ["disk"], "lvs": ["disk"], "pvs": ["disk"], "vgs": ["disk"],
    "logical volume": ["disk"], "volume group": ["disk"], "physical volume": ["disk"],
    "nvme": ["disk"], "ssd": ["disk"], "hdd": ["disk"], "sata": ["disk"], "scsi": ["disk"],
    "smartctl": ["disk"], "disk sagligi": ["disk"], "disk sağlığı": ["disk"],
    "disk health": ["disk"], "badblocks": ["disk"], "fstab": ["disk"], "/etc/fstab": ["disk"],
    "automount": ["disk"], "nfs": ["disk", "network"], "cifs": ["disk", "network"],
    "samba": ["disk", "network", "services"], "iscsi": ["disk", "network"],
    "multipath": ["disk"], "dm-multipath": ["disk"],

    # UPTIME / ÇALIŞMA SÜRESİ
    "uptime": ["uptime", "load"], "calisma": ["uptime", "load"], "çalışma": ["uptime", "load"],
    "ne kadar suredir": ["uptime", "load"], "ne kadar süredir": ["uptime", "load"],
    "sistem suresi": ["uptime"], "sistem süresi": ["uptime"],
    "boot": ["uptime", "kernel"], "son baslangic": ["uptime", "kernel"],
    "son başlangıç": ["uptime", "kernel"], "last boot": ["uptime", "kernel"],
    "reboot": ["uptime", "kernel", "logs"], "yeniden baslama": ["uptime", "logs"],
    "yeniden başlama": ["uptime", "logs"], "shutdown": ["uptime", "logs"],
    "kapat": ["uptime"], "sistem kapanmasi": ["uptime", "logs"],
    "who -b": ["uptime"], "last reboot": ["uptime", "logs"],

    # LOAD / YÜK
    "yuk": ["load", "cpu"], "yük": ["load", "cpu"], "load": ["load", "cpu"],
    "load average": ["load", "cpu"], "ortalama yuk": ["load", "cpu"],
    "ortalama yük": ["load", "cpu"], "sistem yuku": ["load", "cpu"],
    "sistem yükü": ["load", "cpu"], "yuksek yuk": ["load", "cpu", "performance_deep"],
    "yüksek yük": ["load", "cpu", "performance_deep"],
    "high load": ["load", "cpu", "performance_deep"],
    "overload": ["load", "cpu", "performance_deep"],
    "asiri yuk": ["load", "cpu", "performance_deep"],
    "aşırı yük": ["load", "cpu", "performance_deep"],

    # AĞ / NETWORK
    "network": ["network"], "ag": ["network"], "ağ": ["network"],
    "ip": ["network"], "ip addr": ["network"], "ip address": ["network"],
    "ip adresi": ["network"], "inet": ["network"],
    "mac": ["network"], "mac adresi": ["network"], "mac address": ["network"],
    "mac addr": ["network"], "fiziksel adres": ["network"], "ifconfig": ["network"],
    "ethernet": ["network"], "arp": ["network"], "donanim adresi": ["network"],
    "ip link": ["network"], "nmcli": ["network"], "networkmanager": ["network"],
    "network interface": ["network"], "ag arayuzu": ["network"], "ağ arayüzü": ["network"],
    "eth0": ["network"], "ens": ["network"], "enp": ["network"],
    "lo": ["network"], "loopback": ["network"], "vlan": ["network"],
    "bridge": ["network"], "bonding": ["network"], "teaming": ["network"],
    "dns": ["network"], "nameserver": ["network"], "resolv": ["network"],
    "/etc/resolv.conf": ["network"], "nslookup": ["network"], "dig": ["network"],
    "isim cozumleme": ["network"], "isim çözümleme": ["network"],
    "name resolution": ["network"], "gateway": ["network"], "ag gecidi": ["network"],
    "ağ geçidi": ["network"], "yonlendirici": ["network"], "yönlendirici": ["network"],
    "router": ["network"], "route": ["network"], "ip route": ["network"],
    "routing table": ["network"], "yonlendirme tablosu": ["network"],
    "yönlendirme tablosu": ["network"], "ping": ["network"],
    "erisim": ["network"], "erişim": ["network"], "baglanti": ["network"],
    "bağlantı": ["network"], "connectivity": ["network"], "traceroute": ["network"],
    "tracepath": ["network"], "mtr": ["network"],
    "bandwidth": ["network", "performance_deep"], "bant genisligi": ["network", "performance_deep"],
    "bant genişliği": ["network", "performance_deep"],
    "ag hizi": ["network", "performance_deep"], "ağ hızı": ["network", "performance_deep"],
    "iperf": ["network", "performance_deep"], "vnstat": ["network", "performance_deep"],
    "iftop": ["network", "performance_deep"], "nethogs": ["network", "performance_deep"],
    "tcpdump": ["network", "security"], "wireshark": ["network", "security"],
    "paket yakalama": ["network", "security"], "packet capture": ["network", "security"],
    "ipv4": ["network"], "ipv6": ["network"], "subnet": ["network"], "alt ag": ["network"],
    "cidr": ["network"], "proxy": ["network"], "nat": ["network"],
    "masquerade": ["network"], "port forwarding": ["network"],
    "port yonlendirme": ["network"], "port yönlendirme": ["network"],
    "network latency": ["network", "performance_deep"], "gecikme": ["network", "performance_deep"],
    "rtt": ["network", "performance_deep"],
    "network packet loss": ["network", "performance_deep"],
    "paket kaybi": ["network", "performance_deep"], "paket kaybı": ["network", "performance_deep"],
    "network error": ["network", "logs"], "ag hatasi": ["network", "logs"],
    "ağ hatası": ["network", "logs"], "dropped": ["network", "performance_deep"],
    "collisions": ["network"], "tx errors": ["network", "performance_deep"],
    "rx errors": ["network", "performance_deep"],

    # PORT / SOKET
    "port": ["security", "network"], "acik port": ["security", "network"],
    "açık port": ["security", "network"], "listening port": ["security", "network"],
    "dinleme": ["security", "network"], "ss": ["security", "network"],
    "netstat": ["security", "network"], "netstat -tuln": ["security", "network"],
    "soket": ["security", "network"], "socket": ["security", "network"],
    "tcp port": ["security", "network"], "udp port": ["security", "network"],
    "open ports": ["security", "network"], "lsof": ["security", "network", "processes"],
    "lsof -i": ["security", "network"], "nmap": ["security", "network"],
    "port tarama": ["security", "network"], "port scan": ["security", "network"],

    # GÜVENLİK
    "selinux": ["security"], "sestatus": ["security"], "getenforce": ["security"],
    "setenforce": ["security"], "enforcing": ["security"], "permissive": ["security"],
    "selinux context": ["security"], "security context": ["security"],
    "apparmor": ["security"], "firewall": ["security"], "firewalld": ["security"],
    "iptables": ["security"], "ip6tables": ["security"], "nftables": ["security"],
    "ufw": ["security"], "firewall kurali": ["security"], "firewall kuralı": ["security"],
    "firewall rule": ["security"], "zone": ["security"], "sudo": ["security"],
    "sudoers": ["security"], "/etc/sudoers": ["security"],
    "yetkili kullanici": ["security"], "yetkili kullanıcı": ["security"],
    "guvenlik": ["security"], "güvenlik": ["security"], "login": ["security"],
    "giris": ["security"], "giriş": ["security"], "auth": ["security"],
    "authentication": ["security"], "kimlik dogrulama": ["security"],
    "kimlik doğrulama": ["security"], "kullanici": ["security"], "kullanıcı": ["security"],
    "user": ["security"], "users": ["security"], "who": ["security"],
    "w komutu": ["security"], "oturum": ["security"], "aktif kullanici": ["security"],
    "aktif kullanıcı": ["security"], "sifre": ["security"], "şifre": ["security"],
    "password": ["security"], "passwd": ["security"], "parola": ["security"],
    "son giris": ["security"], "son giriş": ["security"], "last login": ["security"],
    "ssh": ["security"], "sshd": ["security"], "uzak baglanti": ["security"],
    "uzak bağlantı": ["security"], "remote": ["security"], "authorized_keys": ["security"],
    "ssh key": ["security"], "ssh anahtari": ["security"], "ssh anahtarı": ["security"],
    "known_hosts": ["security"], "sshd_config": ["security"], "/etc/ssh": ["security"],
    "fail2ban": ["security"], "brute force": ["security"], "ban": ["security"],
    "blocked ip": ["security"], "engellenen ip": ["security"],
    "audit": ["security", "logs"], "auditd": ["security", "logs"],
    "denetim": ["security", "logs"], "log izle": ["security", "logs"],
    "acl": ["security"], "izin": ["security"], "permission": ["security"],
    "chmod": ["security"], "chown": ["security"], "setuid": ["security"],
    "setgid": ["security"], "sticky bit": ["security"], "umask": ["security"],
    "pam": ["security"], "/etc/pam.d": ["security"], "2fa": ["security"],
    "mfa": ["security"], "otp": ["security"], "gpg": ["security"],
    "ssl": ["security"], "tls": ["security"], "sertifika": ["security"],
    "certificate": ["security"], "openssl": ["security"], "cert": ["security"],
    "ca-certificates": ["security"], "passwd dosyasi": ["security"],
    "passwd dosyası": ["security"], "/etc/passwd": ["security"],
    "/etc/shadow": ["security"], "/etc/group": ["security"],
    "grup": ["security"], "group": ["security"], "gid": ["security"], "uid": ["security"],
    "root": ["security"], "rootkit": ["security"], "rkhunter": ["security"],
    "chkrootkit": ["security"], "cve": ["security"], "vulnerability": ["security"],
    "zafiyet": ["security"], "guvensizlik": ["security"], "güvensizlik": ["security"],
    "exploit": ["security"], "intrusion": ["security"], "izinsiz giris": ["security"],
    "izinsiz giriş": ["security"], "honeypot": ["security"], "ids": ["security"],
    "ips": ["security"], "ossec": ["security"], "aide": ["security"],
    "tripwire": ["security"], "lynis": ["security"], "compliance": ["security"],
    "cis benchmark": ["security"], "hardening": ["security"], "sertlestirme": ["security"],

    # SERVİSLER
    "servis": ["services"], "service": ["services"], "systemctl": ["services"],
    "systemd": ["services"], "unit": ["services"], "daemon": ["services"],
    "aktif servis": ["services"], "calisan servis": ["services"],
    "çalışan servis": ["services"], "servis durumu": ["services"],
    "service status": ["services"], "enabled services": ["services"],
    "disabled services": ["services"], "failed service": ["services", "logs"],
    "baslamayan servis": ["services", "logs"], "başlamayan servis": ["services", "logs"],
    "servis baslat": ["services"], "servis başlat": ["services"],
    "servis durdur": ["services"], "servis yeniden baslat": ["services"],
    "service restart": ["services"], "journalctl": ["services", "logs"],
    "init.d": ["services"], "/etc/init.d": ["services"], "sysvinit": ["services"],
    "upstart": ["services"], "openrc": ["services"],
    "docker": ["services", "processes"], "container": ["services", "processes"],
    "konteyner": ["services", "processes"], "podman": ["services", "processes"],
    "imaj": ["services"], "docker image": ["services"],
    "docker container": ["services", "processes"], "docker ps": ["services", "processes"],
    "kubernetes": ["services"], "k8s": ["services"], "kubectl": ["services"],
    "helm": ["services"], "apache": ["services"], "nginx": ["services"],
    "httpd": ["services"], "web server": ["services"],
    "http": ["services", "network"], "https": ["services", "network", "security"],
    "apache2": ["services"], "vhost": ["services"], "virtual host": ["services"],
    "php": ["services"], "php-fpm": ["services"], "mysql": ["services"],
    "postgresql": ["services"], "postgres": ["services"], "mariadb": ["services"],
    "veritabani": ["services"], "veritabanı": ["services"], "database": ["services"],
    "db": ["services"], "redis": ["services"], "memcached": ["services"],
    "rabbitmq": ["services"], "kafka": ["services"], "elasticsearch": ["services"],
    "opensearch": ["services"], "mongodb": ["services"], "cassandra": ["services"],
    "tomcat": ["services"], "jboss": ["services"], "wildfly": ["services"],
    "java": ["services", "processes"], "jvm": ["services", "processes"],
    "nodejs": ["services", "processes"], "node.js": ["services", "processes"],
    "php process": ["services", "processes"], "python process": ["services", "processes"],
    "gunicorn": ["services"], "uwsgi": ["services"],
    "haproxy": ["services", "network"], "varnish": ["services"],
    "squid": ["services", "network"], "keepalived": ["services", "network"],
    "corosync": ["services"], "pacemaker": ["services"], "heartbeat": ["services"],
    "cluster": ["services"], "kume": ["services"], "küme": ["services"],
    "ntp": ["services"], "chrony": ["services"], "chronyd": ["services"],
    "time sync": ["services"], "zaman senkronizasyonu": ["services"],
    "postfix": ["services"], "sendmail": ["services"], "dovecot": ["services"],
    "mail server": ["services"], "smtp": ["services", "network"],
    "imap": ["services", "network"], "pop3": ["services", "network"],
    "rsync": ["services"], "ftp": ["services", "network", "security"],
    "vsftpd": ["services"], "proftpd": ["services"],
    "bind": ["services", "network"], "named": ["services", "network"],
    "dhcp": ["services", "network"], "dhcpd": ["services", "network"],
    "ldap": ["services", "security"], "openldap": ["services", "security"],
    "active directory": ["services", "security"], "kerberos": ["services", "security"],
    "snmp": ["services", "network"], "zabbix": ["services"], "nagios": ["services"],
    "prometheus": ["services"], "grafana": ["services"], "telegraf": ["services"],

    # SÜREÇLER / PROCESSES
    "process": ["processes"], "proses": ["processes"], "ps": ["processes"],
    "ps aux": ["processes"], "ps -ef": ["processes"], "kill": ["processes"],
    "pid": ["processes"], "calisan": ["processes"], "çalışan": ["processes"],
    "top": ["processes", "cpu", "memory"], "htop": ["processes", "cpu", "memory"],
    "atop": ["processes", "performance_deep"], "glances": ["processes", "performance_deep"],
    "zombie": ["processes"], "zombie process": ["processes"], "defunct": ["processes"],
    "process durumu": ["processes"], "process tree": ["processes"], "pstree": ["processes"],
    "nice": ["processes", "cpu"], "renice": ["processes", "cpu"],
    "priority": ["processes", "cpu"], "oncelik": ["processes", "cpu"],
    "öncelik": ["processes", "cpu"], "strace": ["processes", "performance_deep"],
    "ltrace": ["processes", "performance_deep"], "gdb": ["processes"],
    "core dump": ["processes", "logs"], "segfault": ["processes", "logs"],
    "signal": ["processes"], "sigkill": ["processes"], "sigterm": ["processes"],
    "ulimit": ["processes"], "limits.conf": ["processes"], "open files": ["processes"],
    "file descriptor": ["processes"], "fd limit": ["processes"],
    "max open files": ["processes"], "ipc": ["processes"],
    "shared memory ipc": ["processes"], "semaphore": ["processes"],
    "message queue": ["processes"], "thread count": ["processes", "cpu"],
    "fork": ["processes"],

    # LOGLAR
    "log": ["logs"], "hata": ["logs"], "error": ["logs"],
    "uyari": ["logs"], "uyarı": ["logs"], "warning": ["logs"], "mesaj": ["logs"],
    "/var/log": ["logs"], "syslog": ["logs"], "/var/log/syslog": ["logs"],
    "/var/log/messages": ["logs"], "/var/log/auth.log": ["logs", "security"],
    "/var/log/secure": ["logs", "security"], "kern.log": ["logs", "kernel"],
    "boot.log": ["logs", "kernel"], "/var/log/boot.log": ["logs", "kernel"],
    "cron log": ["logs", "cron"], "mail log": ["logs"],
    "access log": ["logs"], "error log": ["logs"],
    "apache log": ["logs", "services"], "nginx log": ["logs", "services"],
    "application log": ["logs"], "uygulama logu": ["logs"],
    "logrotate": ["logs"], "log rotation": ["logs"], "log boyutu": ["logs"],
    "log size": ["logs"], "rsyslog": ["logs"], "syslog-ng": ["logs"],
    "fluentd": ["logs"], "logstash": ["logs"], "log analiz": ["logs"],
    "log analizi": ["logs"], "log analysis": ["logs"], "grep": ["logs"],
    "awk": ["logs"], "tail -f": ["logs"], "son hatalar": ["logs"],
    "son loglar": ["logs"], "recent errors": ["logs"], "critical": ["logs"],
    "alert": ["logs", "security"], "emergency": ["logs"], "notice": ["logs"],
    "debug": ["logs"],

    # PAKETLER
    "paket": ["packages"], "rpm": ["packages"], "yum": ["packages"],
    "apt": ["packages"], "dpkg": ["packages"], "dnf": ["packages"],
    "zypper": ["packages"], "kurulu": ["packages"], "installed": ["packages"],
    "guncelleme": ["packages"], "güncelleme": ["packages"], "update": ["packages"],
    "upgrade": ["packages"], "yukseltme": ["packages"], "yükseltme": ["packages"],
    "paket listesi": ["packages"], "package list": ["packages"],
    "kurulu paketler": ["packages"], "installed packages": ["packages"],
    "paket versiyonu": ["packages"], "package version": ["packages"],
    "repo": ["packages"], "repository": ["packages"], "depo": ["packages"],
    "yum repo": ["packages"], "apt source": ["packages"], "pip": ["packages"],
    "gem": ["packages"], "npm": ["packages"], "yarn": ["packages"],
    "flatpak": ["packages"], "snap": ["packages"], "appimage": ["packages"],
    "guvensiz paket": ["packages", "security"], "güvensiz paket": ["packages", "security"],
    "vulnerable package": ["packages", "security"], "patch": ["packages", "security"],
    "yama": ["packages", "security"], "security update": ["packages", "security"],
    "guvenlik guncelleme": ["packages", "security"],
    "güvenlik güncelleme": ["packages", "security"],

    # CRON
    "cron": ["cron"], "zamanlayici": ["cron"], "zamanlayıcı": ["cron"],
    "crontab": ["cron"], "zamanlanmis gorev": ["cron"], "zamanlanmış görev": ["cron"],
    "at komutu": ["cron"], "scheduled task": ["cron"], "systemd timer": ["cron"],
    "timer unit": ["cron"], "anacron": ["cron"], "cron job": ["cron"],
    "cron log": ["cron", "logs"], "/etc/cron.d": ["cron"], "/etc/crontab": ["cron"],
    "/var/spool/cron": ["cron"], "otomatik gorev": ["cron"], "otomatik görev": ["cron"],
    "periyodik": ["cron"], "her gece": ["cron"], "every night": ["cron"],
    "daily task": ["cron"], "weekly task": ["cron"],

    # DEEP PERFORMANCE
    "vmstat": ["performance_deep"], "iostat": ["performance_deep"],
    "sar": ["performance_deep"], "mpstat": ["performance_deep"],
    "pidstat": ["performance_deep"], "perf": ["performance_deep"],
    "perf top": ["performance_deep"], "perf stat": ["performance_deep"],
    "flamegraph": ["performance_deep"], "profiling": ["performance_deep"],
    "profil": ["performance_deep"], "1 dakika": ["performance_deep"],
    "1 dak": ["performance_deep"], "1 saniyelik": ["performance_deep"],
    "10 defa": ["performance_deep"], "aralik": ["performance_deep"],
    "aralık": ["performance_deep"], "interval": ["performance_deep"],
    "surukli izle": ["performance_deep"], "sürekli izle": ["performance_deep"],
    "derin analiz": ["performance_deep"], "benchmark": ["performance_deep"],
    "stres testi": ["performance_deep"], "stress test": ["performance_deep"],
    "stress": ["performance_deep"], "sysbench": ["performance_deep"],
    "fio": ["performance_deep", "disk"], "io performans": ["performance_deep", "disk"],
    "disk performans": ["performance_deep", "disk"], "iops": ["performance_deep", "disk"],
    "disk hizi": ["performance_deep", "disk"], "disk hızı": ["performance_deep", "disk"],
    "read write": ["performance_deep", "disk"], "throughput": ["performance_deep"],
    "verim": ["performance_deep"], "latency": ["performance_deep", "network"],
    "gecikme suresi": ["performance_deep"], "gecikme süresi": ["performance_deep"],
    "response time": ["performance_deep"], "yanit suresi": ["performance_deep"],
    "yanıt süresi": ["performance_deep"],
    "context switch": ["performance_deep", "cpu"],
    "context switching": ["performance_deep", "cpu"],
    "interrupt": ["performance_deep", "cpu"], "irq": ["performance_deep", "cpu"],
    "kesme": ["performance_deep", "cpu"], "cpu bottleneck": ["performance_deep", "cpu"],
    "darboğaz": ["performance_deep"], "bottleneck": ["performance_deep"],
    "cpu wait": ["performance_deep", "cpu", "disk"], "iowait": ["performance_deep", "disk"],
    "io wait": ["performance_deep", "disk"], "disk io": ["performance_deep", "disk"],
    "block device": ["performance_deep", "disk"], "blktrace": ["performance_deep", "disk"],
    "tcp": ["performance_deep", "network"], "udp": ["performance_deep", "network"],
    "soket durumu": ["performance_deep", "network"],
    "network io": ["performance_deep", "network"],
    "ag trafico": ["performance_deep", "network"], "ağ trafiği": ["performance_deep", "network"],
    "sar -n": ["performance_deep", "network"], "tuning": ["performance_deep"],
    "optimizasyon": ["performance_deep"], "optimization": ["performance_deep"],
    "kernel tuning": ["performance_deep", "kernel"],
    "tcp tuning": ["performance_deep", "network"],
    "vm.swappiness": ["performance_deep", "memory"],
    "dirty_ratio": ["performance_deep", "memory"],
    "noop": ["performance_deep", "disk"], "cfq": ["performance_deep", "disk"],
    "io scheduler": ["performance_deep", "disk"],
    "numa balancing": ["performance_deep", "cpu"],

    # DONANIM
    "donanim": ["kernel", "os", "cpu"], "donanım": ["kernel", "os", "cpu"],
    "hardware": ["kernel", "os", "cpu"], "lshw": ["kernel", "os", "cpu"],
    "dmidecode": ["kernel", "os", "cpu"], "inxi": ["kernel", "os", "cpu"],
    "hwinfo": ["kernel", "os", "cpu"], "pci": ["kernel"], "lspci": ["kernel"],
    "usb": ["kernel"], "lsusb": ["kernel"], "gpu": ["kernel", "cpu"],
    "nvidia": ["kernel", "cpu"], "amd gpu": ["kernel", "cpu"],
    "ekran karti": ["kernel", "cpu"], "ekran kartı": ["kernel", "cpu"],
    "graphics card": ["kernel", "cpu"], "sensor": ["kernel", "performance_deep"],
    "sicaklik": ["kernel", "performance_deep"], "sıcaklık": ["kernel", "performance_deep"],
    "temperature": ["kernel", "performance_deep"], "fan": ["kernel", "performance_deep"],
    "power": ["kernel"], "guc": ["kernel"], "güç": ["kernel"],
    "ups": ["kernel"], "battery": ["kernel"], "pil": ["kernel"],

    # VİRTÜELLEŞTİRME / BULUT
    "vm": ["os", "kernel"], "virtual machine": ["os", "kernel"],
    "sanal makine": ["os", "kernel"], "vmware": ["os", "kernel"],
    "virtualbox": ["os", "kernel"], "kvm": ["os", "kernel"], "qemu": ["os", "kernel"],
    "xen": ["os", "kernel"], "hypervisor": ["os", "kernel"],
    "aws": ["os", "network"], "ec2": ["os", "network"], "azure": ["os", "network"],
    "gcp": ["os", "network"], "cloud": ["os", "network"], "bulut": ["os", "network"],
    "metadata": ["os"], "instance": ["os"], "ami": ["os"],

    # ÖZET / GENEL
    "rapor": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime", "processes"],
    "report": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime", "processes"],
    "ozet": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "özet": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "bilgi": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "genel": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "summary": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "hakkinda": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "hakkında": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "sistem bilgisi": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "durum": ["cpu", "memory", "disk", "uptime", "services"],
    "status": ["cpu", "memory", "disk", "uptime", "services"],
    "saglik": ["cpu", "memory", "disk", "uptime", "services"],
    "sağlık": ["cpu", "memory", "disk", "uptime", "services"],
    "health": ["cpu", "memory", "disk", "uptime", "services"],
    "nasil": ["cpu", "memory", "disk", "uptime", "services"],
    "nasıl": ["cpu", "memory", "disk", "uptime", "services"],
    "neler calisiyor": ["cpu", "memory", "disk", "uptime", "services"],
    "neler çalışıyor": ["cpu", "memory", "disk", "uptime", "services"],
    "performans": ["cpu", "memory", "load", "disk"],
    "performance": ["cpu", "memory", "load", "disk"],
    "yavaş": ["cpu", "memory", "load", "disk", "performance_deep"],
    "yavas": ["cpu", "memory", "load", "disk", "performance_deep"],
    "kasma": ["cpu", "memory", "load", "disk", "performance_deep"],
    "agir": ["cpu", "memory", "load", "disk", "performance_deep"],
    "ağır": ["cpu", "memory", "load", "disk", "performance_deep"],
    "slow": ["cpu", "memory", "load", "disk", "performance_deep"],
    "lag": ["cpu", "memory", "load", "disk", "performance_deep"],
    "tum": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "tüm": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "hepsi": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "full": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "detayli": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "detaylı": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "tam rapor": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "everything": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "neler var": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "kontrol et": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "incele": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "check": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "monitor": ["cpu", "memory", "disk", "load", "processes"],
    "izle": ["cpu", "memory", "disk", "load", "processes"],
    "analiz": ["cpu", "memory", "disk", "load", "performance_deep"],
    "analyze": ["cpu", "memory", "disk", "load", "performance_deep"],
    "sorun": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "problem": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "issue": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "troubleshoot": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "hata ayikla": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "hata ayıkla": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "debug": ["cpu", "memory", "disk", "load", "logs", "processes"],
    "neden": ["cpu", "memory", "disk", "load", "logs"],
    "why": ["cpu", "memory", "disk", "load", "logs"],
}

STANDARD_GROUPS = {"kernel", "os", "cpu", "memory", "disk", "uptime", "load", "security"}

# Sadece spesifik kelimeler gelinceye kadar bekleyen ekstra gruplar
EXTRA_GROUPS_KEYWORDS = {
    "performance_deep": ["vmstat", "iostat", "1 dakika", "1 dak", "derin analiz", "benchmark"],
    "logs":     ["log", "hata", "error", "journal", "syslog"],
    "processes": ["process", "proses", "ps aux", "calisan", "top"],
    "services": ["servis", "service", "systemctl", "daemon"],
    "network":  ["network", "ag", "port", "ip addr", "arayuz", "interface"],
    "packages": ["paket", "rpm", "yum", "dnf", "apt", "kurulu", "installed"],
    "security": ["selinux", "sestatus", "firewall", "sudo", "guvenlik"],
}


def detect_needed_groups(message: str) -> List[str]:
    """
    Standart grupları her zaman döndür + soru içeriğine göre ekstra gruplar ekle.
    Böylece keyword eşleşmesi olmasa bile temel veriler toplanır.
    """
    import unicodedata
    msg = unicodedata.normalize('NFKD', message.lower())
    msg = ''.join(c for c in msg if not unicodedata.combining(c))

    groups = set(STANDARD_GROUPS)

    # Ekstra grupları kontrol et
    for group, keywords in EXTRA_GROUPS_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            groups.add(group)

    # Eski keyword tablosu — geriye dönük uyumluluk
    for keyword, group_list in KEYWORD_TO_GROUPS.items():
        if keyword in msg:
            groups.update(group_list)

    # Derin performans analizi çok yavaş — sadece açıkça istenince
    if "performance_deep" in groups and not any(
        kw in msg for kw in ["vmstat", "iostat", "1 dakika", "1 dak", "benchmark"]
    ):
        groups.discard("performance_deep")

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

    is_deep = "performance_deep" in groups
    results = {}
    try:
        for group_name in groups:
            for cmd, key in COMMAND_GROUPS.get(group_name, []):
                try:
                    # Deep performance komutları (vmstat/iostat 10s) için daha uzun timeout
                    timeout = 90 if group_name == "performance_deep" else 30
                    success, stdout, stderr = ssh.execute_command(cmd, cmd_timeout=timeout)
                    output = stdout.strip() if success and stdout.strip() else (stderr.strip() if not success else "")
                    if output:
                        results[key] = output
                except Exception as e:
                    logger.debug(f"Cmd failed {cmd}: {e}")
    finally:
        ssh.close()

    return results



# Log satırlarında değişken kısımları (sayılar, hex, port adres) normalize edip uniq yap
import re as _re
_LOG_NORM = [
    (_re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'), '<UUID>'),
    (_re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '<IP>'),
    (_re.compile(r'\b0x[0-9a-fA-F]+\b'), '<HEX>'),
    (_re.compile(r'\b[0-9a-fA-F]{10,}\b'), '<HEX>'),
    (_re.compile(r'\b\d+-\d+(?:\.\d+)*\b'), '<PORT>'),
    (_re.compile(r'\b\d+\b'), '<N>'),
]

def _norm_log_key(line: str) -> str:
    msg = line
    # journalctl short-iso prefix
    m = _re.match(r'\S+T\S+\s+\S+\s+(.+)', msg)
    if m:
        msg = m.group(1)
    # syslog prefix
    m2 = _re.match(r'\w+\s+\d+\s+\d+:\d+:\d+\s+\S+\s+(.+)', msg)
    if m2:
        msg = m2.group(1)
    # hostname kelimesini soy: "hostname service: ..." → "service: ..."
    m3 = _re.match(r'^(\S+)\s+(\S+:.+)', msg)
    if m3 and ':' not in m3.group(1):
        msg = m3.group(2)
    # process[pid]: prefix soy
    msg = _re.sub(r'^\S+\[\d+\]:\s*', '', msg)
    for pat, repl in _LOG_NORM:
        msg = pat.sub(repl, msg)
    return msg.lower().strip()

def _dedup_log_lines(text: str) -> str:
    seen: dict = {}
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        key = _norm_log_key(s)
        if key in seen:
            seen[key] += 1
        else:
            seen[key] = 1
            out.append(s)
    # Tekrar sayısını satır sonuna ekle
    result = []
    used: dict = {}
    for line in out:
        key = _norm_log_key(line)
        cnt = seen.get(key, 1)
        if key not in used:
            used[key] = True
            result.append(f"{line} [x{cnt}]" if cnt > 1 else line)
    return '\n'.join(result)

def build_server_context(server, info: Dict[str, Any]) -> str:
    if info.get("error"):
        return f"[{server.name}] Hata: {info['error']}"

    lines = [f"=== {server.name} ({server.ip_address}) ==="]
    field_labels = {
        "os_info": "OS", "os_hostnamectl": "OS (hostnamectl)", "kernel_version": "Kernel",
        "hostname_short": "Hostname", "hostname_fqdn": "FQDN",
        "cpu_detail": "CPU", "cpu_usage": "CPU Kullanim", "cpu_count": "CPU Adet",
        "memory_info": "Bellek", "disk_usage": "Disk",
        "block_devices": "Disk Aygitlari", "network_interfaces": "Ag Arayuzleri (IP+MAC)", "ifconfig_out": "ifconfig", "mac_addresses": "MAC Adresleri",
        "listening_ports": "Dinlenen Portlar", "uptime": "Uptime",
        "load_avg": "Load Average", "vmstat": "vmstat",
        "vmstat_1min": "vmstat (1 dakika)", "iostat_1min": "iostat -x (1 dakika)",
        "sar_cpu_1min": "sar CPU (1 dakika)",
        "running_services": "Calisan Servisler", "failed_services": "Hatali Servisler",
        "top_processes": "En Yogun Surecler", "error_logs": "Hata Loglari",
        "last_logins": "Son Girisler", "current_users": "Aktif Kullanicilar",
        "selinux_status": "SELinux Durumu", "firewall_status": "Firewall Durumu",
        "open_ports": "Açık Portlar", "sudoers": "Sudo Yetkiler",
        "recent_packages": "Son Paketler", "user_cron": "Cron Gorevleri",
    }
    for key, label in field_labels.items():
        if key in info and info[key]:
            val = info[key].replace('"', '').strip()
            if key == "os_info":
                val = '\n'.join(
                    l.split('=', 1)[-1].strip().strip('"') for l in val.split('\n') if '=' in l
                ) or val
            # Log alanlarını normalize et: benzer satırları uniq yap
            if key in ("error_logs",):
                val = _dedup_log_lines(val)
            lines.append(f"{label}:\n{val}")

    return "\n\n".join(lines)
