"""
Linux sunuculardan SSH ile gercek sistem bilgilerini toplar.
AI Chat icin zengin context olusturur.
"""
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from app.services.ssh_manager import SSHManager
from app.core.encryption import decrypt_secret

logger = logging.getLogger(__name__)

COMMAND_GROUPS = {
    # ── KERNEL ──────────────────────────────────────────────────────────────
    "kernel": [
        ("uname -r", "kernel_version"),
        ("uname -a", "kernel_full"),
        ("hostname", "hostname_short"),
        ("hostname -f 2>/dev/null || hostname", "hostname_fqdn"),
        ("cat /proc/version 2>/dev/null | head -1", "kernel_proc_version"),
        ("sysctl kernel.hostname kernel.ostype kernel.osrelease kernel.version 2>/dev/null", "sysctl_kernel"),
        # Hata yoksa çıktı boş kalır — collect_server_info boş sonucu da kaydeder (aşağıda).
        ("dmesg --level=err,crit,alert,emerg 2>/dev/null | tail -20 || dmesg 2>/dev/null | grep -iE 'error|fail|panic|oops|warn|oom' | tail -20", "dmesg_errors"),
        ("lsmod 2>/dev/null | head -20", "kernel_modules"),
        ("sysctl vm.swappiness vm.dirty_ratio net.ipv4.ip_forward net.ipv4.tcp_syncookies 2>/dev/null", "sysctl_important"),
    ],
    # ── İŞLETİM SİSTEMİ ─────────────────────────────────────────────────────
    "os": [
        ("( cat /etc/os-release 2>/dev/null | grep -E '^PRETTY_NAME=|^NAME=|^VERSION=|^VERSION_ID=' ; cat /etc/oracle-release 2>/dev/null ; cat /etc/redhat-release 2>/dev/null ; cat /etc/centos-release 2>/dev/null ) | sort -u | head -6", "os_info"),
        ("hostnamectl 2>/dev/null | grep -E 'Operating System|Kernel|Chassis|Virtualization|Architecture'", "os_hostnamectl"),
        ("timedatectl 2>/dev/null || date", "datetime_info"),
        ("locale 2>/dev/null | head -5", "locale_info"),
        ("cat /etc/hosts 2>/dev/null | grep -v '^#' | grep -v '^$' | head -20", "etc_hosts"),
        ("cat /etc/environment 2>/dev/null | head -10", "env_file"),
        ("cat /etc/timezone 2>/dev/null || timedatectl 2>/dev/null | grep 'Time zone'", "timezone"),
        ("systemctl get-default 2>/dev/null || runlevel 2>/dev/null", "runlevel"),
    ],
    # ── CPU / İŞLEMCİ ───────────────────────────────────────────────────────
    "cpu": [
        ("nproc", "cpu_count"),
        ("lscpu 2>/dev/null | grep -E 'Model name|Architecture|CPU.s.|Thread|Core|Socket|Vendor|MHz|Virtualization|NUMA' | head -12", "cpu_detail"),
        ("top -bn1 2>/dev/null | grep 'Cpu' | head -1", "cpu_usage"),
        ("cat /proc/cpuinfo 2>/dev/null | grep -E '^model name|^cpu MHz|^cache size|^flags' | sort -u | head -8", "cpuinfo"),
        ("grep -c '^processor' /proc/cpuinfo 2>/dev/null", "cpu_logical_count"),
        ("cpupower frequency-info 2>/dev/null | head -6 || cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null", "cpu_governor"),
        ("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{print $1/1000\" C\"}' | head -5 || sensors 2>/dev/null | grep -E 'Core|temp' | head -8", "cpu_temp"),
    ],
    # ── BELLEK / RAM ─────────────────────────────────────────────────────────
    "memory": [
        ("free -h", "memory_info"),
        ("cat /proc/meminfo 2>/dev/null | grep -E '^MemTotal|^MemFree|^MemAvailable|^Buffers|^Cached|^SwapTotal|^SwapFree|^SwapCached|^Dirty|^HugePages' | head -15", "meminfo_detail"),
        ("swapon --show 2>/dev/null || cat /proc/swaps 2>/dev/null", "swap_devices"),
        ("cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null", "thp_status"),
        ("ps aux --sort=-%mem 2>/dev/null | head -6", "top_mem_processes"),
    ],
    # ── DİSK / DEPOLAMA ──────────────────────────────────────────────────────
    "disk": [
        ("df -h 2>/dev/null | head -20", "disk_usage"),
        ("df -ih 2>/dev/null | head -15", "inode_usage"),
        ("lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL 2>/dev/null | head -20", "block_devices"),
        ("blkid 2>/dev/null | head -15", "blkid_info"),
        ("cat /etc/fstab 2>/dev/null | grep -v '^#' | grep -v '^$'", "fstab"),
        ("findmnt -t nfs,nfs4,cifs 2>/dev/null | head -10", "network_mounts"),
        ("pvs 2>/dev/null; vgs 2>/dev/null; lvs 2>/dev/null", "lvm_info"),
        ("mdadm --detail --scan 2>/dev/null | head -15", "raid_info"),
        ("iostat -dx 2>/dev/null | head -15 || vmstat -d 2>/dev/null | head -10", "disk_io"),
        ("du -sh /var/log 2>/dev/null; du -sh /tmp 2>/dev/null; du -sh /home 2>/dev/null", "dir_sizes"),
        ("find /var/log -name '*.log' -size +100M 2>/dev/null | head -5", "large_logs"),
    ],
    # ── AĞ / NETWORK ─────────────────────────────────────────────────────────
    "network": [
        ("ip addr 2>/dev/null | grep -E '^[0-9]+:|link/ether|inet ' | head -60", "network_interfaces"),
        ("ifconfig 2>/dev/null | grep -E '^[a-z]|inet |ether ' | head -60 || true", "ifconfig_out"),
        ("ip link show 2>/dev/null | grep -E '^[0-9]+:|link/ether' | awk '/^[0-9]+:/{iface=$2} /link\/ether/{print iface, $2}' | head -20", "mac_addresses"),
        ("ss -tuln 2>/dev/null | head -30", "listening_ports"),
        ("ss -s 2>/dev/null", "socket_stats"),
        ("cat /etc/resolv.conf 2>/dev/null || echo 'resolv.conf not found'", "resolv_conf"),
        ("cat /etc/nsswitch.conf 2>/dev/null | grep -E '^hosts:|^passwd:|^shadow:' || true", "nsswitch_conf"),
        ("{ ip route show default 2>/dev/null | grep .; } || { ip route 2>/dev/null | grep -i default | grep .; } || { route -n 2>/dev/null | awk '$1==\"0.0.0.0\"{print}' | grep .; } || { netstat -rn 2>/dev/null | awk '$1==\"0.0.0.0\"{print}' | grep .; } || echo 'default gateway not determined'", "default_route"),
        ("ip route 2>/dev/null | head -15 || route -n 2>/dev/null | head -15 || netstat -rn 2>/dev/null | head -15", "routing_table"),
        ("netstat -rn 2>/dev/null | head -20 || route -n 2>/dev/null | head -20", "netstat_rn"),
        ("ip -s link 2>/dev/null | head -30", "network_stats"),
        ("arp -n 2>/dev/null | head -15 || ip neigh 2>/dev/null | head -15", "arp_table"),
        ("cat /etc/hosts 2>/dev/null | grep -v '^#' | grep -v '^$' | head -20", "hosts_file"),
        ("nmcli con show 2>/dev/null | head -15 || cat /etc/sysconfig/network-scripts/ifcfg-* 2>/dev/null | head -30", "network_config"),
        ("ss -tnp 2>/dev/null | grep ESTABLISHED | head -20", "active_connections"),
    ],
    # ── PROCESSLER / SÜREÇLER ────────────────────────────────────────────────
    "processes": [
        ("ps aux --sort=-%cpu 2>/dev/null | head -15", "top_processes"),
        ("ps aux --sort=-%mem 2>/dev/null | head -10", "top_mem_procs"),
        ("ps -eo pid,ppid,user,stat,pcpu,pmem,comm 2>/dev/null | sort -k5 -rn | head -15", "proc_detail"),
        ("pstree -p 2>/dev/null | head -20 || ps --forest -eo pid,ppid,user,comm 2>/dev/null | head -20", "proc_tree"),
        ("lsof -i -n -P 2>/dev/null | grep LISTEN | head -20", "lsof_listen"),
    ],
    # ── SERVİSLER / SYSTEMD ──────────────────────────────────────────────────
    "services": [
        ("systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -30", "running_services"),
        ("systemctl list-units --type=service --state=failed --no-pager 2>/dev/null", "failed_services"),
        ("systemctl list-units --state=failed --no-pager 2>/dev/null", "all_failed_units"),
        ("systemd-analyze blame 2>/dev/null | head -15", "slow_services"),
        ("systemd-analyze 2>/dev/null | head -3", "boot_time"),
        ("journalctl -u systemd --since '1 hour ago' --no-pager 2>/dev/null | tail -5", "systemd_logs"),
        ("chkconfig --list 2>/dev/null | grep ':on' | head -15 || ls /etc/rc3.d/ 2>/dev/null | head -10", "legacy_services"),
    ],
    # ── UPTIME ──────────────────────────────────────────────────────────────
    "uptime": [
        ("uptime", "uptime"),
        ("who -b 2>/dev/null || last reboot 2>/dev/null | head -3", "last_boot"),
        ("last reboot 2>/dev/null | head -5", "reboot_history"),
    ],
    # ── LOAD / YÜK ───────────────────────────────────────────────────────────
    "load": [
        ("cat /proc/loadavg", "load_avg"),
        ("vmstat 1 3 2>/dev/null", "vmstat"),
        ("sar -u 1 3 2>/dev/null | tail -5 || true", "sar_cpu"),
    ],
    # ── PERFORMANS (DERİN) ────────────────────────────────────────────────────
    "performance_deep": [
        ("vmstat 1 5 2>/dev/null", "vmstat_1min"),
        ("iostat -x 1 5 2>/dev/null", "iostat_1min"),
        ("sar -u 1 10 2>/dev/null || echo 'sar not available'", "sar_cpu_1min"),
        ("sar -n DEV 1 5 2>/dev/null | tail -15 || true", "sar_net_1min"),
        ("sar -d 1 5 2>/dev/null | tail -10 || true", "sar_disk_1min"),
        ("pidstat 1 5 2>/dev/null | tail -15 || true", "pidstat"),
        ("cat /proc/pressure/cpu 2>/dev/null; cat /proc/pressure/memory 2>/dev/null; cat /proc/pressure/io 2>/dev/null", "psi_pressure"),
    ],
    # ── LOGLAR ──────────────────────────────────────────────────────────────
    "logs": [
        ("journalctl -p err..emerg --since '2 hours ago' --no-pager 2>/dev/null | tail -20", "error_logs"),
        ("journalctl --since '1 hour ago' --no-pager 2>/dev/null | grep -iE 'failed|error|critical|warning' | tail -15", "recent_errors"),
        ("journalctl -k --since '1 hour ago' --no-pager 2>/dev/null | tail -10", "kernel_logs"),
        ("tail -20 /var/log/messages 2>/dev/null || tail -20 /var/log/syslog 2>/dev/null", "syslog_tail"),
        ("tail -15 /var/log/secure 2>/dev/null || tail -15 /var/log/auth.log 2>/dev/null", "auth_log"),
        ("journalctl --disk-usage 2>/dev/null", "journal_disk_usage"),
    ],
    # ── GÜVENLİK ─────────────────────────────────────────────────────────────
    "security": [
        ("last -n 15 2>/dev/null", "last_logins"),
        ("lastb -n 10 2>/dev/null | head -15", "failed_logins"),
        ("who 2>/dev/null", "current_users"),
        ("w 2>/dev/null | head -10", "logged_in_users"),
        ("sestatus 2>/dev/null || getenforce 2>/dev/null || echo 'SELinux: not found'", "selinux_status"),
        ("systemctl is-active firewalld 2>/dev/null && firewall-cmd --list-all 2>/dev/null | head -20 || iptables -L -n 2>/dev/null | head -25 || nft list ruleset 2>/dev/null | head -20", "firewall_status"),
        ("ss -tuln 2>/dev/null | head -30", "open_ports"),
        ("grep -v '^#' /etc/sudoers 2>/dev/null | grep -v '^$' | head -20 ; cat /etc/sudoers.d/* 2>/dev/null | grep -v '^#' | head -10", "sudoers"),
        ("cat /etc/passwd 2>/dev/null | grep -v nologin | grep -v false | grep -v halt | grep -v shutdown | grep -v sync", "system_users"),
        ("cat /etc/group 2>/dev/null | grep -v '^#' | head -20", "system_groups"),
        ("find /home -name '.ssh' -type d 2>/dev/null | head -10", "ssh_dirs"),
        ("auditctl -l 2>/dev/null | head -10 || echo 'audit: not configured'", "audit_rules"),
        ("grep 'Failed password\|Invalid user\|session opened\|session closed' /var/log/secure 2>/dev/null | tail -10 || grep 'Failed\|Invalid\|session' /var/log/auth.log 2>/dev/null | tail -10", "auth_events"),
    ],
    # ── PAKETLER ─────────────────────────────────────────────────────────────
    "packages": [
        # "en son ne zaman güncelleme yapıldı" gibi sorulara DOĞRUDAN cevap: dnf/yum
        # transaction history en son Update/Install/Erase işleminin tarihini gösterir —
        # recent_packages (rpm -qa --last) tek paket bazlı olduğu için bazen yanıltıcı/
        # eksik olabiliyordu, bu komut tüm toplu güncelleme islemlerini tarihli listeler.
        # NOT: "dnf history" root olmadan "readonly database" hatasi verir — bu key
        # _SUDO_PREFERRED_KEYS'te oldugu icin sudo_password varsa otomatik sudo ile calisir.
        ("dnf history 2>/dev/null | head -8 || yum history 2>/dev/null | head -8 || "
         "(grep -h ' upgrade ' /var/log/apt/history.log* 2>/dev/null | tail -8) || "
         "echo 'update history not available'", "update_history"),
        ("rpm -qa --last 2>/dev/null | head -15", "recent_packages"),
        ("rpm -qa 2>/dev/null | wc -l", "rpm_count"),
        # timeout 10: air-gapped/repo'ya erisimi olmayan sunucularda check-update repo
        # metadata yenilemeye calisip uzun sure asilabiliyor — bkz. agent/tools.py'deki
        # ayni gerekce ile eklenen _package_status_cmd timeout'u.
        ("timeout 10 yum check-update 2>/dev/null | tail -5 || timeout 10 dnf check-update 2>/dev/null | tail -5 || timeout 10 apt list --upgradable 2>/dev/null | tail -5", "pending_updates"),
        ("rpm -qa 2>/dev/null | grep -iE 'kernel|java|python|nginx|apache|mysql|postgres|redis|docker|openssl' | sort | head -20 || dpkg -l 2>/dev/null | grep -iE 'kernel|java|python|nginx|apache|mysql|postgres|redis|docker|openssl' | head -20", "key_packages"),
        ("dpkg -l 2>/dev/null | tail -15 || true", "deb_packages"),
        ("pip3 list 2>/dev/null | head -15 || pip list 2>/dev/null | head -15 || true", "python_packages"),
    ],
    # ── CRON / ZAMANLANMIŞ GÖREVLER ──────────────────────────────────────────
    "cron": [
        ("crontab -l 2>/dev/null", "user_cron"),
        ("cat /etc/crontab 2>/dev/null", "system_crontab"),
        ("ls /etc/cron.d/ 2>/dev/null; cat /etc/cron.d/* 2>/dev/null | grep -v '^#' | grep -v '^$' | head -20", "cron_d"),
        ("ls /etc/cron.daily/ /etc/cron.weekly/ /etc/cron.monthly/ 2>/dev/null", "cron_dirs"),
        ("systemctl list-timers --no-pager 2>/dev/null | head -20", "systemd_timers"),
        ("at -l 2>/dev/null || atq 2>/dev/null", "at_jobs"),
    ],
    # ── DONANIM ──────────────────────────────────────────────────────────────
    "hardware": [
        ("dmidecode -t system 2>/dev/null | grep -E 'Product|Manufacturer|Version|Serial|UUID' | head -6 || cat /sys/class/dmi/id/product_name 2>/dev/null", "hw_system"),
        ("dmidecode -t memory 2>/dev/null | grep -E 'Size|Type|Speed|Manufacturer|Part Number' | grep -v 'No Module' | head -20", "hw_memory_slots"),
        ("lspci 2>/dev/null | grep -iE 'VGA|Network|Ethernet|RAID|Storage|USB|Audio' | head -20", "pci_devices"),
        ("lsusb 2>/dev/null | head -10", "usb_devices"),
        ("lshw -short 2>/dev/null | head -30 || true", "hw_summary"),
        ("cat /sys/class/dmi/id/product_name 2>/dev/null; cat /sys/class/dmi/id/board_vendor 2>/dev/null", "hw_model"),
        ("ipmitool chassis status 2>/dev/null | head -5 || true", "ipmi_status"),
    ],
    # ── SSL / SERTİFİKALAR ────────────────────────────────────────────────────
    "ssl": [
        ("find /etc/pki /etc/ssl /etc/letsencrypt 2>/dev/null -name '*.crt' -o -name '*.pem' 2>/dev/null | head -10", "cert_files"),
        ("for cert in $(find /etc/pki/tls/certs /etc/ssl/certs /etc/nginx/ssl /etc/httpd/ssl 2>/dev/null -name '*.crt' -o -name '*.pem' | head -5); do echo \"=== $cert ===\"; openssl x509 -noout -subject -issuer -dates -in $cert 2>/dev/null; done", "cert_details"),
        ("openssl version 2>/dev/null", "openssl_version"),
    ],
    # ── KONTEYNERLER / DOCKER ────────────────────────────────────────────────
    "containers": [
        ("docker ps 2>/dev/null | head -20 || true", "docker_running"),
        ("docker ps -a 2>/dev/null | head -20 || true", "docker_all"),
        ("docker images 2>/dev/null | head -15 || true", "docker_images"),
        ("docker stats --no-stream 2>/dev/null | head -15 || true", "docker_stats"),
        ("podman ps 2>/dev/null | head -15 || true", "podman_running"),
        ("podman images 2>/dev/null | head -10 || true", "podman_images"),
        ("kubectl get pods --all-namespaces 2>/dev/null | head -20 || true", "k8s_pods"),
        ("kubectl get nodes 2>/dev/null | head -10 || true", "k8s_nodes"),
        ("systemctl is-active docker 2>/dev/null; systemctl is-active podman 2>/dev/null; systemctl is-active containerd 2>/dev/null", "container_services"),
    ],
    # ── WEB SUNUCULARI ────────────────────────────────────────────────────────
    "web": [
        ("nginx -v 2>&1 | head -2; nginx -T 2>/dev/null | grep -E 'listen|server_name|root|proxy_pass' | head -20", "nginx_info"),
        ("httpd -v 2>/dev/null || apache2 -v 2>/dev/null; httpd -S 2>/dev/null | head -15 || apache2ctl -S 2>/dev/null | head -15", "apache_info"),
        ("systemctl is-active nginx apache2 httpd 2>/dev/null", "web_service_status"),
        ("ls /etc/nginx/sites-enabled/ 2>/dev/null; ls /etc/nginx/conf.d/ 2>/dev/null; ls /etc/httpd/conf.d/ 2>/dev/null", "web_vhosts"),
        ("curl -s -o /dev/null -w '%{http_code}' http://localhost 2>/dev/null || true", "web_local_check"),
    ],
    # ── VERİTABANI ────────────────────────────────────────────────────────────
    "database": [
        ("systemctl is-active postgresql mysql mariadb mongod redis-server 2>/dev/null", "db_service_status"),
        ("psql -U postgres -c '\\l' 2>/dev/null | head -15 || true", "postgres_dbs"),
        ("psql -U postgres -c 'SELECT version()' 2>/dev/null | head -3 || true", "postgres_version"),
        ("mysql -e 'SHOW DATABASES;' 2>/dev/null | head -15 || mysql -u root -e 'SHOW DATABASES;' 2>/dev/null | head -15 || true", "mysql_dbs"),
        ("mysql -e 'SELECT VERSION();' 2>/dev/null | head -3 || true", "mysql_version"),
        ("redis-cli info server 2>/dev/null | head -10 || true", "redis_info"),
        ("mongosh --eval 'db.version()' 2>/dev/null | head -3 || mongo --eval 'db.version()' 2>/dev/null | head -3 || true", "mongo_version"),
    ],
    # ── NTP / ZAMAN SENKRONİZASYONU ──────────────────────────────────────────
    "ntp": [
        ("chronyc tracking 2>/dev/null | head -10 || ntpq -p 2>/dev/null | head -10 || timedatectl show 2>/dev/null | head -5", "ntp_status"),
        ("chronyc sources 2>/dev/null | head -10 || ntpq -p 2>/dev/null | head -10", "ntp_sources"),
        ("timedatectl 2>/dev/null | grep -E 'synchronized|NTP|timezone|RTC'", "time_sync"),
    ],
    # ── KULLANICILAR ─────────────────────────────────────────────────────────
    "users": [
        ("cat /etc/passwd 2>/dev/null | awk -F: '$3>=1000 && $3!=65534{print $1,$3,$4,$6,$7}'", "real_users"),
        ("cat /etc/group 2>/dev/null | awk -F: '$4!=\"\"{print $1,$4}' | head -20", "groups_with_members"),
        ("lastlog 2>/dev/null | grep -v 'Never' | head -15", "last_login_all"),
        ("who 2>/dev/null; w 2>/dev/null | head -10", "active_sessions"),
        ("passwd -S -a 2>/dev/null | grep -v Locked | head -15 || true", "passwd_status"),
    ],
    # ── UYGULAMA / SERVİS DETAY ──────────────────────────────────────────────
    "apps": [
        ("java -version 2>&1 | head -2 || true", "java_version"),
        ("python3 --version 2>/dev/null || python --version 2>/dev/null || true", "python_version"),
        ("node --version 2>/dev/null || true", "node_version"),
        ("php --version 2>/dev/null | head -1 || true", "php_version"),
        ("ruby --version 2>/dev/null || true", "ruby_version"),
        ("go version 2>/dev/null || true", "go_version"),
        ("systemctl list-units --type=service --state=active --no-pager 2>/dev/null | grep -iE 'tomcat|wildfly|jboss|glassfish|jetty' | head -5", "java_servers"),
    ],
    # ── SISTEM LİMİTLERİ ─────────────────────────────────────────────────────
    "limits": [
        ("ulimit -a 2>/dev/null | head -15", "ulimits"),
        ("cat /proc/sys/fs/file-max 2>/dev/null; cat /proc/sys/fs/file-nr 2>/dev/null", "file_limits"),
        ("sysctl fs.file-max net.core.somaxconn net.ipv4.tcp_max_syn_backlog 2>/dev/null", "sysctl_limits"),
        ("cat /etc/security/limits.conf 2>/dev/null | grep -v '^#' | grep -v '^$' | head -20", "security_limits"),
        ("cat /proc/sys/kernel/pid_max 2>/dev/null; cat /proc/sys/kernel/threads-max 2>/dev/null", "pid_limits"),
    ],
    # ── DOSYA SİSTEMİ / PATH ─────────────────────────────────────────────────
    "filesystem": [
        ("ls -la /etc/ | head -20", "etc_listing"),
        ("ls -la /var/log/ | head -15", "log_listing"),
        ("find /tmp -mtime -1 2>/dev/null | head -10", "tmp_recent"),
        ("find /var/log -name '*.log' -newer /proc/1 2>/dev/null | head -10", "new_logs"),
        ("stat /boot 2>/dev/null | head -5; df -h /boot 2>/dev/null | tail -1", "boot_partition"),
        ("cat /proc/mounts 2>/dev/null | grep -v 'proc\|sys\|dev\|run' | head -20", "mounts"),
    ],
    # ── ADMIN LOGLARI (kıdemli sysadmin checklist) ───────────────────────────
    # Tek sunucu / teşhis sorularında: journal, dmesg, auth, cron, audit, boot,
    # paket/güncelleme logları ve yaygın app error logları.
    "admin_logs": [
        ("journalctl -p err..emerg --since '24 hours ago' --no-pager 2>/dev/null | tail -80", "admin_journal_err"),
        ("journalctl -p warning --since '6 hours ago' --no-pager 2>/dev/null | tail -40", "admin_journal_warn"),
        ("journalctl -b -p err..emerg --no-pager 2>/dev/null | tail -40", "admin_journal_boot_err"),
        ("journalctl --list-boots --no-pager 2>/dev/null | tail -8", "admin_boot_list"),
        ("(dmesg -T 2>/dev/null || dmesg 2>/dev/null) | tail -80", "admin_dmesg_recent"),
        ("(dmesg -T 2>/dev/null || dmesg 2>/dev/null) | grep -iE 'error|fail|panic|oops|oom|blocked|I/O error|reset|timeout|segfault' | tail -50", "admin_dmesg_issues"),
        ("journalctl -k -p err..alert --since '7 days ago' --no-pager -n 50 2>/dev/null", "admin_kernel_journal"),
        ("tail -n 60 /var/log/messages 2>/dev/null || tail -n 60 /var/log/syslog 2>/dev/null", "admin_syslog"),
        ("tail -n 50 /var/log/secure 2>/dev/null || tail -n 50 /var/log/auth.log 2>/dev/null", "admin_authlog"),
        ("tail -n 40 /var/log/cron 2>/dev/null || journalctl -u crond --since '24 hours ago' --no-pager 2>/dev/null | tail -30", "admin_cronlog"),
        ("tail -n 40 /var/log/boot.log 2>/dev/null || journalctl -b 0 -o short-precise --no-pager 2>/dev/null | head -40", "admin_bootlog"),
        ("tail -n 40 /var/log/audit/audit.log 2>/dev/null | grep -iE 'denied|failed|AVC|USER_AUTH' | tail -30", "admin_auditlog"),
        ("systemctl --failed --no-pager --plain 2>/dev/null; echo '---'; systemctl list-units --state=failed --no-pager 2>/dev/null | head -20", "admin_failed_units"),
        ("for u in $(systemctl list-units --state=failed --no-legend --no-pager 2>/dev/null | awk '{print $1}' | head -5); do echo \"=== journal $u ===\"; journalctl -u \"$u\" --since '24 hours ago' --no-pager 2>/dev/null | tail -15; done", "admin_failed_unit_logs"),
        ("tail -n 30 /var/log/dnf.log 2>/dev/null || tail -n 30 /var/log/yum.log 2>/dev/null || tail -n 20 /var/log/apt/history.log 2>/dev/null", "admin_pkg_log"),
        ("(tail -n 25 /var/log/nginx/error.log 2>/dev/null; tail -n 25 /var/log/httpd/error_log 2>/dev/null; tail -n 25 /var/log/apache2/error.log 2>/dev/null) | head -40", "admin_web_errorlog"),
        ("ls -lah /var/log 2>/dev/null | head -35", "admin_varlog_listing"),
        ("journalctl --disk-usage 2>/dev/null; df -h /var/log 2>/dev/null | tail -1", "admin_log_disk"),
    ],
    # Her SSH ortamında çalışan HAFİF derin paket (timeout dostu)
    "admin_lite": [
        ("sestatus 2>/dev/null || getenforce 2>/dev/null || echo 'SELinux: n/a'", "lite_selinux"),
        ("systemctl --failed --no-pager --plain 2>/dev/null | head -15", "lite_failed_units"),
        ("(dmesg -T 2>/dev/null || dmesg 2>/dev/null) | grep -iE 'error|fail|panic|oops|oom|blocked|I/O error|segfault' | tail -25", "lite_dmesg_issues"),
        ("journalctl -p err..emerg --since '6 hours ago' --no-pager 2>/dev/null | tail -30", "lite_journal_err"),
        ("tail -n 20 /var/log/secure 2>/dev/null || tail -n 20 /var/log/auth.log 2>/dev/null", "lite_authlog"),
        ("df -h 2>/dev/null | head -12", "lite_df"),
        ("free -h 2>/dev/null | head -5", "lite_free"),
        ("uptime; cat /proc/loadavg 2>/dev/null", "lite_uptime_load"),
        ("ip route show default 2>/dev/null | head -3; cat /etc/resolv.conf 2>/dev/null | head -8", "lite_net_dns"),
        ("grep -E '^(Port|PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/* 2>/dev/null | grep -v '^#' | head -15", "lite_sshd"),
        ("cat /etc/fstab 2>/dev/null | grep -v '^#' | grep -v '^$' | head -20", "lite_fstab"),
        ("sysctl vm.swappiness vm.dirty_ratio fs.file-max 2>/dev/null", "lite_sysctl"),
    ],
    # ── ADMIN CONFIGS (salt okunur, hassas sırlar süzülmüş) ──────────────────
    "admin_configs": [
        ("cat /etc/fstab 2>/dev/null | grep -v '^#' | grep -v '^$'", "cfg_fstab"),
        ("cat /etc/resolv.conf 2>/dev/null; echo '---'; grep -E '^hosts:|^passwd:|^shadow:|^group:' /etc/nsswitch.conf 2>/dev/null", "cfg_dns_nss"),
        ("cat /etc/hosts 2>/dev/null | grep -v '^#' | grep -v '^$' | head -40", "cfg_hosts"),
        ("(cat /etc/sysctl.conf 2>/dev/null; echo '--- /etc/sysctl.d ---'; for f in /etc/sysctl.d/*.conf; do [ -f \"$f\" ] && echo \"# $f\" && grep -v '^#' \"$f\" | grep -v '^$'; done) 2>/dev/null | head -80", "cfg_sysctl"),
        ("(cat /etc/security/limits.conf 2>/dev/null; ls /etc/security/limits.d/ 2>/dev/null; for f in /etc/security/limits.d/*; do [ -f \"$f\" ] && echo \"# $f\" && grep -v '^#' \"$f\" | grep -v '^$'; done) 2>/dev/null | grep -v '^#' | grep -v '^$' | head -50", "cfg_limits"),
        ("grep -E '^(Port|PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|AllowUsers|AllowGroups|MaxAuthTries|MaxStartups|ClientAlive|ListenAddress|UsePAM|ChallengeResponse|KbdInteractive)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/* 2>/dev/null | grep -v '^#' | head -40", "cfg_sshd"),
        ("cat /etc/selinux/config 2>/dev/null | grep -v '^#' | grep -v '^$'; echo '---'; getenforce 2>/dev/null; sestatus 2>/dev/null | head -12", "cfg_selinux"),
        ("(cat /etc/chrony.conf 2>/dev/null || cat /etc/ntp.conf 2>/dev/null || cat /etc/chrony/chrony.conf 2>/dev/null) | grep -v '^#' | grep -v '^$' | head -30", "cfg_time"),
        ("timedatectl 2>/dev/null | head -15", "cfg_timedatectl"),
        ("(firewall-cmd --list-all 2>/dev/null | head -35) || (iptables -L -n -v 2>/dev/null | head -40) || (nft list ruleset 2>/dev/null | head -40)", "cfg_firewall"),
        ("(nmcli -f NAME,UUID,TYPE,DEVICE,STATE con show 2>/dev/null | head -20) || (ls /etc/sysconfig/network-scripts/ifcfg-* 2>/dev/null; grep -hE '^(DEVICE|NAME|BOOTPROTO|IPADDR|GATEWAY|DNS|ONBOOT|MASTER|SLAVE)=' /etc/sysconfig/network-scripts/ifcfg-* 2>/dev/null | head -40)", "cfg_network"),
        ("ip route 2>/dev/null | head -20; echo '---'; ip -br addr 2>/dev/null | head -20", "cfg_ip_route"),
        ("cat /etc/crontab 2>/dev/null | grep -v '^#' | grep -v '^$'; echo '--- cron.d ---'; ls /etc/cron.d/ 2>/dev/null; systemctl list-timers --no-pager 2>/dev/null | head -15", "cfg_cron"),
        ("tuned-adm active 2>/dev/null; echo '---'; cat /etc/tuned/active_profile 2>/dev/null", "cfg_tuned"),
        ("systemctl get-default 2>/dev/null; echo '---'; hostnamectl 2>/dev/null | head -12", "cfg_hostname_target"),
        ("ls /etc/logrotate.d/ 2>/dev/null | head -25; echo '---'; head -40 /etc/logrotate.conf 2>/dev/null | grep -v '^#'", "cfg_logrotate"),
        ("needs-restarting -r 2>/dev/null || needs-restarting 2>/dev/null | head -20 || echo 'needs-restarting yok'", "cfg_needs_restart"),
        ("grep -vE '^(#|$)' /etc/sudoers 2>/dev/null | head -25; ls /etc/sudoers.d/ 2>/dev/null", "cfg_sudoers_summary"),
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
    "name resolution": ["network"], "gateway": ["network"], "default gw": ["network"], "gw": ["network"], "ag gecidi": ["network"],
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

    # ADMIN TEŞHİS / CONFIG (kıdemli sysadmin checklist)
    "analiz": ["admin_logs", "admin_configs", "kernel", "logs", "services"],
    "analysis": ["admin_logs", "admin_configs", "kernel", "logs"],
    "teşhis": ["admin_logs", "admin_configs", "kernel", "logs", "services", "security"],
    "teshis": ["admin_logs", "admin_configs", "kernel", "logs", "services", "security"],
    "diagnos": ["admin_logs", "admin_configs", "kernel", "logs"],
    "kök neden": ["admin_logs", "admin_configs", "kernel", "logs", "services"],
    "kok neden": ["admin_logs", "admin_configs", "kernel", "logs", "services"],
    "root cause": ["admin_logs", "admin_configs", "kernel", "logs"],
    "sorun": ["admin_logs", "admin_configs", "logs", "services", "kernel"],
    "problem": ["admin_logs", "admin_configs", "logs", "services"],
    "arıza": ["admin_logs", "admin_configs", "logs", "kernel", "services"],
    "ariza": ["admin_logs", "admin_configs", "logs", "kernel", "services"],
    "troubleshoot": ["admin_logs", "admin_configs", "logs", "kernel"],
    "config": ["admin_configs", "os", "kernel"],
    "konfig": ["admin_configs"],
    "yapılandırma": ["admin_configs", "os"],
    "yapilandirma": ["admin_configs", "os"],
    "configuration": ["admin_configs"],
    "/etc/": ["admin_configs", "filesystem"],
    "sysctl.conf": ["admin_configs", "kernel"],
    "sshd_config": ["admin_configs", "security"],
    "fstab": ["admin_configs", "disk"],
    "checklist": ["admin_logs", "admin_configs", "kernel", "os", "services", "security"],
    "health check": ["admin_logs", "admin_configs", "services", "kernel"],
    "sağlık kontrol": ["admin_logs", "admin_configs", "services", "kernel"],
    "saglik kontrol": ["admin_logs", "admin_configs", "services", "kernel"],

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
    "sistem bilgisi": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
    "sunucu bilgisi": ["kernel", "os", "cpu", "memory", "disk", "uptime"],
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
    "detayli": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "detaylı": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "tam rapor": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "tum bilgi": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "tüm bilgi": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "everything": ["kernel", "os", "cpu", "memory", "disk", "network", "services", "uptime"],
    "neler var": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "kontrol et": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "incele": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
    "check all": ["kernel", "os", "cpu", "memory", "disk", "uptime", "services"],
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
    # DONANIM
    "donanim": ["hardware"], "donanım": ["hardware"], "hardware": ["hardware"],
    "dmidecode": ["hardware"], "lspci": ["hardware"], "lsusb": ["hardware"],
    "lshw": ["hardware"], "model": ["hardware", "os"], "seri no": ["hardware"],
    "seri numarasi": ["hardware"], "server modeli": ["hardware"],
    "anakart": ["hardware"], "motherboard": ["hardware"],
    "ram slotu": ["hardware", "memory"], "memory slot": ["hardware", "memory"],
    "bios": ["hardware", "kernel"], "uefi": ["hardware", "kernel"],
    "ipmi": ["hardware"], "bmc": ["hardware"], "idrac": ["hardware"],
    "ilo": ["hardware"], "imm": ["hardware"],

    # NTP / ZAMAN
    # NOT: bare "zaman" kelimesi KASITLI OLARAK burada YOK — "ne zaman", "hangi zaman"
    # gibi Türkçe'de son derece yaygın "when" ifadeleri barındırıyor ve NTP/saat
    # senkronizasyonuyla hiçbir ilgisi olmayan sorularda (ör. "en son update ne zaman
    # yapılmış?") yanlışlıkla ntp+os grubunu tetikleyip, focused-mode mantığı yüzünden
    # asıl ilgili grubun (packages) SESSİZCE düşmesine yol açıyordu. Sadece daha
    # spesifik "zaman senkron(izasyon)" / "saat senkron" ifadeleri NTP'yi tetikler.
    "ntp": ["ntp"], "chrony": ["ntp"], "chronyc": ["ntp"], "ntpq": ["ntp"],
    "zaman senkron": ["ntp"], "time sync": ["ntp"], "senkron": ["ntp"],
    "timedatectl": ["ntp", "os"], "saat senkron": ["ntp"],
    "drift": ["ntp"], "offset": ["ntp"], "ntp server": ["ntp"],

    # DOCKER / KONTEYNER
    "docker": ["containers"], "podman": ["containers"], "konteyner": ["containers"],
    "container": ["containers"], "kubernetes": ["containers"], "kubectl": ["containers"],
    "k8s": ["containers"], "pod": ["containers"], "image": ["containers"],
    "docker ps": ["containers"], "docker image": ["containers"],
    "containerd": ["containers"], "cri-o": ["containers"],
    "namespace": ["containers"], "deployment": ["containers"],

    # WEB SUNUCUSU
    "nginx": ["web", "services"], "apache": ["web", "services"],
    "httpd": ["web", "services"], "web server": ["web"], "web sunucu": ["web"],
    "sanal host": ["web"], "virtual host": ["web"], "vhost": ["web"],
    "site": ["web"], "domain": ["web"], "ssl sertifika": ["ssl", "web"],
    "https": ["ssl", "web"], "http": ["web"],

    # VERİTABANI
    "veritabani": ["database"], "veritabanı": ["database"], "database": ["database"],
    "postgresql": ["database"], "postgres": ["database"], "psql": ["database"],
    "mysql": ["database"], "mariadb": ["database"], "mongodb": ["database"],
    "redis": ["database"], "db": ["database"], "sql": ["database"],

    # SSL / SERTİFİKA
    "ssl": ["ssl"], "tls": ["ssl"], "sertifika": ["ssl"], "certificate": ["ssl"],
    "cert": ["ssl"], "openssl": ["ssl"], "x509": ["ssl"], "pki": ["ssl"],
    "let's encrypt": ["ssl"], "letsencrypt": ["ssl"],

    # CRON / ZAMANLAMA
    "cron": ["cron"], "crontab": ["cron"], "zamanlama": ["cron"],
    "scheduled": ["cron"], "timer": ["cron", "services"], "at job": ["cron"],
    "anacron": ["cron"], "systemd timer": ["cron", "services"],

    # KULLANICILAR
    "kullanici": ["users", "security"], "kullanıcı": ["users", "security"],
    "user": ["users", "security"], "passwd": ["users", "security"],
    "/etc/passwd": ["users", "security"], "/etc/group": ["users", "security"],
    "sudo": ["users", "security"], "root": ["users", "security"],
    "oturum": ["users", "security"], "session": ["users", "security"],
    "login": ["users", "security", "logs"], "logout": ["users", "security"],
    "giriş": ["users", "security"], "çıkış": ["users", "security"],

    # UYGULAMA
    "java": ["apps"], "python": ["apps"], "node": ["apps"], "nodejs": ["apps"],
    "php": ["apps"], "ruby": ["apps"], "go": ["apps"], "golang": ["apps"],
    "tomcat": ["apps", "services"], "jboss": ["apps", "services"],
    "wildfly": ["apps", "services"],

    # DOSYA SİSTEMİ
    "/etc/": ["filesystem"], "/var/": ["filesystem"], "/tmp": ["filesystem"],
    "mount": ["filesystem", "disk"], "unmount": ["filesystem", "disk"],
    "dosya sistemi": ["filesystem", "disk"],

    # SİSTEM LİMİTLERİ
    "ulimit": ["limits"], "open files": ["limits"], "file descriptor": ["limits"],
    "max processes": ["limits"], "nproc": ["limits", "processes"],
    "connection limit": ["limits", "network"], "somaxconn": ["limits", "network"],


}

STANDARD_GROUPS = {
    "kernel", "os", "cpu", "memory", "disk", "uptime", "load", "services", "security",
    # Her ortamda hafif derin checklist (tam admin_logs/configs tanı sorularında)
    "admin_lite",
}

# Sadece spesifik kelimeler gelinceye kadar bekleyen ekstra gruplar
EXTRA_GROUPS_KEYWORDS = {
    "performance_deep": ["vmstat", "iostat", "1 dakika", "1 dak", "derin analiz", "benchmark", "psi", "pressure"],
    "logs":        ["log", "hata", "error", "journal", "syslog", "auth", "secure", "dmesg"],
    "admin_logs":  [
        "dmesg", "analiz", "teşhis", "teshis", "diagnos", "kök neden", "kok neden", "root cause",
        "sorun", "arıza", "ariza", "troubleshoot", "journalctl", "audit.log", "boot.log",
        "logları", "loglari", "tüm log", "tum log", "admin log",
    ],
    "admin_configs": [
        "config", "konfig", "yapılandırma", "yapilandirma", "configuration", "sysctl.conf",
        "sshd_config", "fstab", "limits.conf", "chrony", "tuned", "checklist",
    ],
    "processes":   ["process", "proses", "ps aux", "calisan", "çalışan", "top", "lsof", "pstree", "fork"],
    "services":    ["servis", "service", "systemctl", "daemon", "unit", "failed unit"],
    "network":     ["network", "ag", "ağ", "port", "ip addr", "arayuz", "arayüz", "interface", "dns", "resolv", "nameserver", "gateway", "ağ geçidi", "route", "arp", "nmcli"],
    "packages":    ["paket", "rpm", "yum", "dnf", "apt", "kurulu", "installed", "update", "upgrade", "pip"],
    "security":    ["selinux", "sestatus", "firewall", "sudo", "guvenlik", "güvenlik", "auth", "login", "fail2ban", "passwd", "group"],
    "hardware":    ["donanim", "donanım", "hardware", "dmidecode", "lspci", "lsusb", "lshw", "bios", "ipmi", "model", "seri"],
    "cron":        ["cron", "crontab", "zamanlama", "timer", "schedule", "at job"],
    "containers":  ["docker", "podman", "container", "konteyner", "kubernetes", "k8s", "kubectl", "pod"],
    "web":         ["nginx", "apache", "httpd", "web server", "web sunucu", "vhost", "site"],
    "database":    ["postgresql", "postgres", "mysql", "mariadb", "mongodb", "redis", "veritaban", "database"],
    "ntp":         ["ntp", "chrony", "zaman senkron", "time sync", "timedatectl"],
    "ssl":         ["ssl", "tls", "sertifika", "certificate", "cert", "openssl", "pki", "letsencrypt"],
    "users":       ["kullanici", "kullanıcı", "user", "passwd", "group", "sudo", "oturum", "session", "login"],
    "apps":        ["java", "python", "node", "nodejs", "php", "ruby", "go", "golang", "tomcat", "jboss"],
    "limits":      ["ulimit", "open files", "file descriptor", "max process", "somaxconn"],
    "filesystem":  ["/etc/", "/var/", "/tmp", "mount", "unmount", "dosya sistemi"],
}


# Sadece bu gruplardan biri istendiğinde STANDARD_GROUPS'u küçült
# "security" de dahil: STANDARD_GROUPS'ta olsa da tek başına ("selinux durumu" gibi) istendiğinde
# cpu/memory/disk/uptime/services'i beraberinde sürüklememesi gerekir.
_FOCUSED_GROUPS = {
    "network", "hardware", "containers", "web", "database", "ntp", "ssl",
    "cron", "users", "apps", "limits", "filesystem", "security", "packages",
    "admin_logs", "admin_configs", "admin_lite", "logs",
}
_MINIMAL_BASE = {"kernel", "os"}

# Filo SSH taramasında eşzamanlı üst sınır (çok büyük filolarda timeout önlemi).
# Derin admin checklist her ortamda açık; özel olarak 16'ya düşürülmez.
CHAT_SSH_FLEET_CAP = 48


def _message_wants_dmesg(message: Optional[str]) -> bool:
    if not message:
        return False
    m = message.lower()
    return any(
        k in m
        for k in (
            "dmesg", "kernel log", "kernel hata", "çekirdek log", "cekirdek log",
            "oom", "oops", "kernel panic", "segfault",
        )
    )


def _message_wants_admin_diag(message: Optional[str]) -> bool:
    """Kıdemli admin'in bakacağı log+config paketini tetikle."""
    if not message:
        return False
    m = message.lower()
    return any(
        k in m
        for k in (
            "dmesg", "analiz", "teşhis", "teshis", "diagnos", "kök neden", "kok neden",
            "root cause", "sorun", "arıza", "ariza", "troubleshoot", "checklist",
            "yapılandırma", "yapilandirma", "config", "konfig", "sshd_config",
            "sysctl.conf", "journalctl", "tüm log", "tum log", "logları incele",
            "neden yavaş", "neden dolu", "neden düştü", "neden kapandi", "neden kapandı",
            "bozul", "çök", "coktu", "çöktü", "kesinti",
        )
    )


def cap_servers_for_ssh(servers: List[Any], message: Optional[str] = None, cap: int = CHAT_SSH_FLEET_CAP) -> Tuple[List[Any], Optional[str]]:
    """Çok büyük filolarda SSH hedefini sınırla; mesajda adı geçenleri önceliklendir."""
    if not servers or len(servers) <= cap:
        return list(servers or []), None
    msg = (message or "").lower()
    mentioned = []
    rest = []
    for s in servers:
        name = (getattr(s, "name", None) or "").lower()
        ip = getattr(s, "ip_address", None) or ""
        if (name and name in msg) or (ip and ip in (message or "")):
            mentioned.append(s)
        else:
            rest.append(s)
    picked = (mentioned + rest)[:cap]
    note = (
        f"NOT: {len(servers)} AI Ready sunucudan filo SSH taraması için {len(picked)} tanesi "
        f"seçildi (üst sınır {cap}; derin log/config checklist bu host'larda çalışır). "
        f"Belirli sunucu için Hedef menüsünden seçin veya soruya adını yazın."
    )
    return picked, note


# "dnf history" gibi bazı komutlar normal kullanıcıyla exit=0 dönüp anlamsız/eksik çıktı
# (ör. "readonly database") verebiliyor — bu key'ler icin sudo_password mevcutsa önce
# sudo ile denenir (veya normal deneme "readonly database"/"not root" ile başarısız
# görünürse sudo ile tekrar denenir). Bkz. collect_server_info.
_SUDO_PREFERRED_KEYS = {"update_history"}

# KEYWORD_TO_GROUPS içindeki, tek başına mesajda belirli bir konu (extra_groups) varken
# devre dışı bırakılması gereken çok genel/geniş kapsamlı kelimeler — bkz. detect_needed_groups.
_GENERIC_BROADENING_WORDS = {"durum", "status", "saglik", "sağlık"}

# Açıkça genel sistem sorgusu olduğunu gösteren kelimeler (tam kelime veya güvenli substring)
_GENERAL_TRIGGER_WORDS = {
    "genel", "ozet", "özet", "summary", "overview", "rapor",
    "everything", "tam rapor", "tum bilgi", "tüm bilgi",
    "sistem durumu", "sistem bilgisi", "sunucu bilgisi",
    "detayli", "detaylı", "full report", "neler var",
    "kontrol et", "incele", "check all",
}


# Bu kelimeler tek başlarına ("nasılsın?", "genel olarak iyi") sıradan sohbette de
# sıkça geçtiği için has_recognized_topic()'te BAŞLI BAŞINA bir konu saymaz — sadece
# detect_needed_groups() içinde zaten belirli bir konu varsa o konuyu genişletirler
# (bkz. _GENERIC_BROADENING_WORDS / is_explicit_general orada da aynı mantıkla ele alınıyor).
_TOPIC_TOO_GENERIC_STANDALONE = {
    "durum", "status", "saglik", "sağlık", "nasil", "nasıl", "genel",
    "ozet", "özet", "hakkinda", "hakkında", "rapor", "report", "summary",
}


def has_recognized_topic(message: str) -> bool:
    """
    Mesaj, KEYWORD_TO_GROUPS veya EXTRA_GROUPS_KEYWORDS içindeki herhangi bir
    konuyla eşleşiyor mu? chat.py/unified_chat.py'deki SSH tetikleme keyword
    listeleri (SSH_ONLY_KEYWORDS/SSH_SYSINFO_KEYWORDS/vb.) bu dosyadaki çok daha
    kapsamlı sözlüklerle senkron değildi — örn. "vm.swappiness", "sysctl",
    "dirty_ratio" gibi kernel tuning terimleri detect_needed_groups() tarafında
    doğru gruba (kernel/memory/performance_deep) eşleniyordu ama chat.py hiçbir
    zaman needs_ssh=True yapmadığı için _collect_ssh() hiç çalışmıyor, SSH
    context boş kalıyor ve LLM context'siz "SSH bağlantısı sağlanamadı" gibi
    bir cevap üretiyordu (context YOK'tu, SSH GERÇEKTEN başarısız değildi).
    Bu fonksiyon, chat.py'nin needs_ssh hesaplamasına eklenerek bu sınıftaki
    sorunları (yeni bir terim eklendiğinde iki listeyi senkron tutma yükü
    olmadan) kalıcı olarak kapatır.
    """
    import unicodedata
    msg = unicodedata.normalize('NFKD', message.lower())
    msg = ''.join(c for c in msg if not unicodedata.combining(c))
    if any(kw in msg for kw in KEYWORD_TO_GROUPS if kw not in _TOPIC_TOO_GENERIC_STANDALONE):
        return True
    for keywords in EXTRA_GROUPS_KEYWORDS.values():
        if any(kw in msg for kw in keywords):
            return True
    # "vm.min_free_kbytes" gibi listede olmayan ama sysctl formatına uyan HERHANGİ bir
    # parametre adı geçiyorsa da bir konu tanınmış sayılır — bkz. extract_sysctl_params().
    if _SYSCTL_PARAM_RE.search(message.lower()):
        return True
    return False


def detect_needed_groups(message: str) -> List[str]:
    """
    Akıllı grup seçimi:
    - Odaklı sorular (network/docker/ntp/ssl vb.) → sadece ilgili gruplar + kernel+os
    - Genel sorular (cpu/disk/memory/genel/rapor vb.) → STANDARD_GROUPS + ekstralar
    
    Bu sayede 'default gw' sorusu kernel+os+network (3 grup),
    'genel sistem durumu' ise tüm standard grupları çalıştırır.
    """
    import unicodedata
    msg = unicodedata.normalize('NFKD', message.lower())
    msg = ''.join(c for c in msg if not unicodedata.combining(c))

    # 1. Ekstra grupları bul (hem EXTRA_GROUPS_KEYWORDS hem KEYWORD_TO_GROUPS)
    extra_groups: set = set()
    for group, keywords in EXTRA_GROUPS_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            extra_groups.add(group)

    # Mesaj zaten belirli bir tek konuya işaret ediyor mu (selinux->security, docker->containers vb.)?
    has_specific_topic = bool(extra_groups)

    for keyword, group_list in KEYWORD_TO_GROUPS.items():
        if keyword in msg:
            # Çok kısa keyword'ler (du, df, ps…) "durumu" içinde yanlış eşleşmesin
            if len(keyword) <= 3 and not re.search(
                rf'(?<![a-z0-9çğıöşü]){re.escape(keyword)}(?![a-z0-9çğıöşü])', msg
            ):
                continue
            # "durum"/"status"/"saglik" gibi ÇOK genel kelimeler, mesajda ZATEN belirli bir
            # konu varsa (ör. "selinux durumu") cpu/memory/disk/uptime/services'i otomatik
            # eklemesin. Bu genişletme olmasaydı "X durumu" kalıbındaki HER tek-konulu soru
            # (disk/cpu hariç) gereksiz yere STANDARD_GROUPS'un tamamını (~9 grup, 60+ komut)
            # taramak zorunda kalıyor, tek sunucuda bile 20s+ sürüp context timeout'a
            # (bkz. "selinux durumu" -> enes97 vakası) yol açıyordu.
            if keyword in _GENERIC_BROADENING_WORDS and has_specific_topic:
                continue
            extra_groups.update(group_list)

    # Kıdemli admin checklist
    # - HER ortamda: admin_lite (hızlı, ~12 komut)
    # - Tanı/analiz/dmesg/kök neden: tam admin_logs + admin_configs
    extra_groups.add("admin_lite")
    if _message_wants_admin_diag(message):
        extra_groups.update({"admin_logs", "admin_configs", "kernel", "logs", "services"})

    # Derin performans analizi çok yavaş
    if "performance_deep" in extra_groups and not any(
        kw in msg for kw in ["vmstat", "iostat", "1 dakika", "1 dak", "benchmark"]
    ):
        extra_groups.discard("performance_deep")

    # 2. Odaklı grupları ayır (network, containers, ntp, ssl vb.)
    # admin_lite her zaman eklenir ama tek başına "focused" sayılmasın
    focused_groups = (extra_groups & _FOCUSED_GROUPS) - {"admin_lite"}

    # 3. Genel mod mu? Şu durumlarda genel mod:
    #    a) Açık genel tetikleyici kelimeler varsa ("genel", "rapor", "özet"...)
    #    b) VEYA standart performans/kaynak grupları açıkça isteniyorsa
    #       (cpu, memory, disk, load - NOT sadece kernel/os/services/security)
    is_explicit_general = any(w in msg for w in _GENERAL_TRIGGER_WORDS)
    perf_groups = extra_groups & {"cpu", "memory", "disk", "load", "uptime", "processes"}
    is_resource_query = bool(perf_groups)

    # Her SSH ortamında lite derin arama
    _DEEP_ALWAYS = {"admin_lite"}
    if _message_wants_admin_diag(message):
        _DEEP_ALWAYS = {"admin_lite", "admin_logs", "admin_configs"}

    if focused_groups and not is_explicit_general and not is_resource_query:
        groups = _MINIMAL_BASE | focused_groups | {"services"} | _DEEP_ALWAYS
    elif focused_groups and is_resource_query:
        groups = _MINIMAL_BASE | focused_groups | perf_groups | {"services"} | _DEEP_ALWAYS
    elif is_resource_query and not is_explicit_general and not focused_groups and len(perf_groups) <= 2:
        groups = _MINIMAL_BASE | perf_groups | _DEEP_ALWAYS
    else:
        groups = set(STANDARD_GROUPS) | extra_groups | _DEEP_ALWAYS

    return list(groups)


# Mesajda geçen sysctl parametre adlarını yakalar — "vm.min_free_kbytes", "net.ipv4.tcp_fin_timeout"
# gibi HERHANGİ bir sysctl anahtarını (sadece sysctl_important'taki 4 sabit parametreyi değil)
# tanıyabilmek için. Sadece bilinen sysctl kök isim uzaylarıyla (vm/net/kernel/fs/...) başlayanları
# eşleştiriyoruz ki IP adresi ("192.168.1.1"), sürüm numarası ("8.0.1") veya dosya adı
# ("config.yaml") gibi noktalı ama sysctl OLMAYAN metinler yanlışlıkla eşleşmesin.
_SYSCTL_PARAM_RE = re.compile(
    r'\b(?:vm|net|kernel|fs|dev|abi|debug|crypto|user)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*\b'
)
# "tüm/bütün sysctl parametrelerini getir" gibi TAM LİSTE isteklerini yakalar (spesifik bir
# parametre adı vermeden). Bu durumda sysctl -a ile toplu bir döküm alınır (çıktı sınırlanır).
_SYSCTL_ALL_RE = re.compile(r'(tum|butun|hepsi|all)\s+(sysctl|kernel\s+parametre)', re.IGNORECASE)


def extract_sysctl_params(message: str) -> List[str]:
    """Mesajda geçen spesifik sysctl parametre adlarını (varsa) döner."""
    if not message:
        return []
    found = [m.group(0) for m in _SYSCTL_PARAM_RE.finditer(message.lower())]
    # Sıra korunarak tekilleştir, en fazla 10 parametre (aşırı uzun komut riskini sınırlar)
    seen = []
    for p in found:
        if p not in seen:
            seen.append(p)
    return seen[:10]


def wants_full_sysctl_dump(message: str) -> bool:
    """Mesaj, spesifik parametre adı vermeden TÜM sysctl çıktısını istiyor mu?"""
    if not message:
        return False
    import unicodedata
    msg = unicodedata.normalize('NFKD', message.lower())
    msg = ''.join(c for c in msg if not unicodedata.combining(c))
    return bool(_SYSCTL_ALL_RE.search(msg))


def collect_server_info(server, groups: List[str], global_cred=None, message: str = None) -> Dict[str, Any]:
    conn = server.connection_config or {}
    username = conn.get("username") or (global_cred.username if global_cred else None)
    # DB'de şifre/anahtar alanları Fernet ile şifreli tutuluyor (bkz. app.core.encryption) —
    # hem per-server connection_config hem de global credential için burada deşifre
    # edilmeden paramiko'ya verilirse auth sessizce başarısız olur (level1.py/terminal.py/
    # package_service.py bu adımı zaten yapıyordu, burada eksikti). decrypt_secret()
    # eski/plaintext satırlar için de güvenli (fallback ile aynı değeri döner).
    raw_password = conn.get("password") or (global_cred.password if global_cred else None)
    raw_private_key = conn.get("private_key") or (global_cred.private_key if global_cred else None)
    raw_sudo_password = conn.get("sudo_password") or (global_cred.sudo_password if global_cred else None)
    password = decrypt_secret(raw_password) if raw_password else None
    private_key = decrypt_secret(raw_private_key) if raw_private_key else None
    port = conn.get("port", 22) or (global_cred.port if global_cred else 22)
    sudo_password = decrypt_secret(raw_sudo_password) if raw_sudo_password else password

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
    _empty_ok_keys = {
        "dmesg_errors", "admin_dmesg_issues", "admin_journal_err", "admin_journal_warn",
        "admin_journal_boot_err", "admin_kernel_journal", "admin_auditlog",
        "admin_web_errorlog", "admin_failed_unit_logs", "admin_cronlog",
    }
    results = {}
    try:
        for group_name in groups:
            for cmd, key in COMMAND_GROUPS.get(group_name, []):
                try:
                    # Deep performance / admin log-config biraz daha uzun
                    if group_name == "performance_deep":
                        timeout = 45
                    elif group_name in ("admin_logs", "admin_configs", "admin_lite"):
                        timeout = 25 if group_name != "admin_lite" else 12
                    else:
                        timeout = 15
                    use_sudo = (
                        key in _SUDO_PREFERRED_KEYS or group_name in ("admin_logs", "admin_configs", "admin_lite")
                    ) and bool(sudo_password)
                    success, stdout, stderr = ssh.execute_command(cmd, use_sudo=use_sudo, cmd_timeout=timeout)
                    output = stdout.strip() if success and stdout.strip() else (stderr.strip() if not success else "")
                    # "dnf history" gibi bazı komutlar root olmadan calisip exit=0 dondurur
                    # ama anlamli veri vermez ("readonly database" hatasi) — sudo ile tekrar dene.
                    if (not use_sudo and key in _SUDO_PREFERRED_KEYS and sudo_password
                            and any(p in output.lower() for p in ("readonly database", "not root", "permission denied"))):
                        success, stdout, stderr = ssh.execute_command(cmd, use_sudo=True, cmd_timeout=timeout)
                        output = stdout.strip() if success and stdout.strip() else (stderr.strip() if not success else "")
                    if output:
                        results[key] = output
                    elif key in _empty_ok_keys:
                        results[key] = f"({key}: ilgili satır yok / temiz)"
                except Exception as e:
                    logger.debug(f"Cmd failed {cmd}: {e}")

        # Açık dmesg/OOM/oops isteği: son satırları da getir (sadece hata filtresi yetmez)
        if _message_wants_dmesg(message):
            extra_cmds = [
                (
                    "dmesg -T 2>/dev/null | tail -80 || dmesg 2>/dev/null | tail -80",
                    "dmesg_recent",
                    "(dmesg son satırları boş / okunamadı)",
                ),
                (
                    "dmesg --level=err,crit,alert,emerg,warn 2>/dev/null | tail -50 "
                    "|| dmesg 2>/dev/null | grep -iE 'error|fail|panic|oops|oom|warn|segfault|blocked' | tail -50",
                    "dmesg_errors",
                    "(err/warn seviyesinde dmesg satırı yok)",
                ),
                (
                    "journalctl -k -p warning..alert --since '7 days ago' --no-pager -n 40 2>/dev/null",
                    "kernel_logs",
                    "(journalctl -k uyarı/hata satırı yok)",
                ),
            ]
            for cmd, key, empty_msg in extra_cmds:
                try:
                    use_sudo = bool(sudo_password)
                    success, stdout, stderr = ssh.execute_command(cmd, use_sudo=use_sudo, cmd_timeout=20)
                    output = stdout.strip() if success and stdout and stdout.strip() else ""
                    if not output and not success and stderr:
                        output = stderr.strip()[:500]
                    results[key] = output if output else empty_msg
                except Exception as e:
                    logger.debug(f"dmesg extra cmd failed {key}: {e}")
                    results.setdefault(key, f"(dmesg toplanamadı: {e})")

        # Mesajda "vm.min_free_kbytes" gibi spesifik bir sysctl parametresi geçiyorsa —
        # sysctl_important sabit listesinde (vm.swappiness/dirty_ratio/ip_forward/tcp_syncookies)
        # olmasa bile — bunu doğrudan hedefleyen ek bir sysctl komutu çalıştır. Böylece AI
        # BİLDİĞİ HERHANGİ bir sysctl parametresini, sabit koda gerek kalmadan SSH ile
        # doğrudan sorgulayabilir.
        try:
            requested_params = extract_sysctl_params(message) if message else []
            if requested_params:
                cmd = "sysctl " + " ".join(requested_params) + " 2>/dev/null"
                success, stdout, stderr = ssh.execute_command(cmd, cmd_timeout=15)
                output = stdout.strip() if success and stdout.strip() else (stderr.strip() if not success else "")
                if output:
                    results["sysctl_requested"] = output
            elif message and wants_full_sysctl_dump(message):
                # Spesifik parametre belirtilmeden "tüm sysctl parametreleri" istendiyse —
                # çıktı çok büyük olabileceğinden (1000+ satır) LLM context'ini şişirmemek
                # için ilk 200 satırla sınırlanır.
                success, stdout, stderr = ssh.execute_command(
                    "sysctl -a 2>/dev/null | head -200", cmd_timeout=20
                )
                output = stdout.strip() if success and stdout.strip() else ""
                if output:
                    results["sysctl_all_dump"] = output + "\n... (çıktı ilk 200 satırla sınırlandı)"
        except Exception as e:
            logger.debug(f"Dynamic sysctl fetch failed: {e}")
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
        # Kernel / OS
        "kernel_version": "Kernel", "kernel_full": "Kernel (full)", "kernel_proc_version": "Kernel (/proc)",
        "sysctl_kernel": "sysctl (kernel)", "sysctl_important": "sysctl (önemli)",
        "sysctl_requested": "sysctl (sorulan parametre)", "sysctl_all_dump": "sysctl -a (tüm parametreler, kısmi)",
        "dmesg_errors": "dmesg Hatalar", "dmesg_recent": "dmesg (son satırlar)",
        "kernel_modules": "Kernel Modülleri",
        "os_info": "OS", "os_hostnamectl": "OS (hostnamectl)",
        "hostname_short": "Hostname", "hostname_fqdn": "FQDN",
        "datetime_info": "Tarih/Saat", "locale_info": "Locale", "timezone": "Timezone",
        "etc_hosts": "/etc/hosts", "env_file": "/etc/environment",
        "runlevel": "Çalışma Modu (Runlevel)",
        # CPU
        "cpu_count": "CPU Adet", "cpu_detail": "CPU", "cpu_usage": "CPU Kullanımı",
        "cpuinfo": "/proc/cpuinfo", "cpu_logical_count": "CPU (Mantıksal)",
        "cpu_governor": "CPU Governor", "cpu_temp": "CPU Sıcaklık",
        # Memory
        "memory_info": "Bellek", "meminfo_detail": "/proc/meminfo",
        "swap_devices": "Swap Aygıtları", "thp_status": "Transparent HugePage",
        "top_mem_processes": "En Çok Bellek Kullanan Süreçler",
        # Disk
        "disk_usage": "Disk Kullanımı", "inode_usage": "Inode Kullanımı",
        "block_devices": "Blok Aygıtlar", "blkid_info": "Disk UUID/FS (blkid)",
        "fstab": "/etc/fstab", "network_mounts": "Ağ Montaj Noktaları (NFS/CIFS)",
        "lvm_info": "LVM (PV/VG/LV)", "raid_info": "RAID (mdadm)",
        "disk_io": "Disk I/O İstatistikleri", "dir_sizes": "Dizin Boyutları",
        "large_logs": "Büyük Log Dosyaları",
        # Network
        "network_interfaces": "Ağ Arayüzleri (IP+MAC)", "ifconfig_out": "ifconfig",
        "mac_addresses": "MAC Adresleri", "listening_ports": "Dinlenen Portlar",
        "socket_stats": "Soket İstatistikleri (ss -s)", "resolv_conf": "/etc/resolv.conf (DNS)",
        "nsswitch_conf": "/etc/nsswitch.conf", "default_route": "Varsayılan Ağ Geçidi",
        "routing_table": "Yönlendirme Tablosu", "netstat_rn": "netstat -rn Çıktısı", "network_stats": "Ağ İstatistikleri",
        "arp_table": "ARP Tablosu", "hosts_file": "/etc/hosts",
        "network_config": "Ağ Yapılandırması", "active_connections": "Aktif Bağlantılar",
        # Processes
        "top_processes": "En Yoğun Süreçler (CPU)", "top_mem_procs": "En Yoğun Süreçler (RAM)",
        "proc_detail": "Süreç Detayları", "proc_tree": "Süreç Ağacı", "lsof_listen": "lsof (LISTEN)",
        # Services
        "running_services": "Çalışan Servisler", "failed_services": "Hatalı Servisler",
        "all_failed_units": "Tüm Hatalı Birimler", "slow_services": "Yavaş Başlayan Servisler",
        "boot_time": "Önyükleme Süresi", "systemd_logs": "Systemd Logları",
        "legacy_services": "Eski Stil Servisler",
        # Uptime/Load
        "uptime": "Uptime", "last_boot": "Son Önyükleme", "reboot_history": "Yeniden Başlama Geçmişi",
        "load_avg": "Load Average", "vmstat": "vmstat",
        "vmstat_1min": "vmstat (uzun)", "iostat_1min": "iostat -x (uzun)",
        "sar_cpu_1min": "sar CPU (uzun)", "sar_net_1min": "sar Ağ (uzun)",
        "sar_disk_1min": "sar Disk (uzun)", "pidstat": "pidstat", "psi_pressure": "PSI Baskı",
        "sar_cpu": "sar CPU",
        # Logs
        "error_logs": "Hata Logları", "recent_errors": "Son Hatalar",
        "kernel_logs": "Kernel Logları", "syslog_tail": "Syslog",
        "auth_log": "Auth Logları", "journal_disk_usage": "Journal Disk Kullanımı",
        # Security
        "last_logins": "Son Girişler", "failed_logins": "Başarısız Girişler",
        "current_users": "Aktif Kullanıcılar", "logged_in_users": "Oturum Açık Kullanıcılar",
        "selinux_status": "SELinux Durumu", "firewall_status": "Firewall",
        "open_ports": "Açık Portlar", "sudoers": "Sudo Yetkileri",
        "system_users": "Sistem Kullanıcıları", "system_groups": "Gruplar",
        "ssh_dirs": "SSH Dizinleri", "audit_rules": "Audit Kuralları", "auth_events": "Auth Olayları",
        # Packages
        "update_history": "Güncelleme Geçmişi (dnf/yum history — en son yapılan güncelleme tarihleri)",
        "recent_packages": "Son Kurulan Paketler", "rpm_count": "Paket Sayısı",
        "pending_updates": "Bekleyen Güncellemeler", "key_packages": "Anahtar Paketler",
        "deb_packages": "Debian Paketleri", "python_packages": "Python Paketleri",
        # Cron
        "user_cron": "Kullanıcı Cron", "system_crontab": "/etc/crontab",
        "cron_d": "/etc/cron.d", "cron_dirs": "Cron Dizinleri",
        "systemd_timers": "Systemd Timer'lar", "at_jobs": "at Görevleri",
        # Hardware
        "hw_system": "Donanım (Sistem)", "hw_memory_slots": "RAM Slotları",
        "pci_devices": "PCI Aygıtlar", "usb_devices": "USB Aygıtlar",
        "hw_summary": "Donanım Özeti", "hw_model": "Sunucu Modeli", "ipmi_status": "IPMI/BMC",
        # SSL
        "cert_files": "Sertifika Dosyaları", "cert_details": "Sertifika Detayları",
        "openssl_version": "OpenSSL Versiyonu",
        # Containers
        "docker_running": "Docker (Çalışan)", "docker_all": "Docker (Tümü)",
        "docker_images": "Docker Images", "docker_stats": "Docker İstatistikleri",
        "podman_running": "Podman (Çalışan)", "podman_images": "Podman Images",
        "k8s_pods": "Kubernetes Pod'lar", "k8s_nodes": "Kubernetes Node'lar",
        "container_services": "Konteyner Servisleri",
        # Web
        "nginx_info": "Nginx", "apache_info": "Apache",
        "web_service_status": "Web Servisi Durumu", "web_vhosts": "Sanal Hostlar",
        "web_local_check": "Web Yerel Erişim",
        # Database
        "db_service_status": "Veritabanı Servisleri", "postgres_dbs": "PostgreSQL Veritabanları",
        "postgres_version": "PostgreSQL Versiyonu", "mysql_dbs": "MySQL Veritabanları",
        "mysql_version": "MySQL Versiyonu", "redis_info": "Redis", "mongo_version": "MongoDB",
        # NTP
        "ntp_status": "NTP Durumu", "ntp_sources": "NTP Kaynakları", "time_sync": "Zaman Senkronizasyonu",
        # Users
        "real_users": "Gerçek Kullanıcılar", "groups_with_members": "Grup Üyelikleri",
        "last_login_all": "Son Girişler (Tümü)", "active_sessions": "Aktif Oturumlar",
        "passwd_status": "Parola Durumu",
        # Apps
        "java_version": "Java", "python_version": "Python", "node_version": "Node.js",
        "php_version": "PHP", "ruby_version": "Ruby", "go_version": "Go",
        "java_servers": "Java Uygulama Sunucuları",
        # Limits
        "ulimits": "Sistem Limitleri (ulimit)", "file_limits": "Dosya Limitleri",
        "sysctl_limits": "sysctl Limitleri", "security_limits": "/etc/security/limits.conf",
        "pid_limits": "PID Limitleri",
        # Filesystem
        "etc_listing": "/etc dizini", "log_listing": "/var/log dizini",
        "tmp_recent": "/tmp (yeni)", "new_logs": "Yeni Log Dosyaları",
        "boot_partition": "Boot Bölümü", "mounts": "Montaj Noktaları",
        # Admin logs
        "admin_journal_err": "Journal (err+ 24s)", "admin_journal_warn": "Journal (warning 6s)",
        "admin_journal_boot_err": "Journal (bu boot err+)", "admin_boot_list": "Boot geçmişi",
        "admin_dmesg_recent": "dmesg (son)", "admin_dmesg_issues": "dmesg (sorun satırları)",
        "admin_kernel_journal": "Kernel journal", "admin_syslog": "Syslog/messages",
        "admin_authlog": "Auth/secure", "admin_cronlog": "Cron log",
        "admin_bootlog": "Boot log", "admin_auditlog": "Audit (denied/fail)",
        "admin_failed_units": "Failed units", "admin_failed_unit_logs": "Failed unit journal",
        "admin_pkg_log": "Paket/güncelleme log", "admin_web_errorlog": "Web error log",
        "admin_varlog_listing": "/var/log listesi", "admin_log_disk": "Log disk kullanımı",
        # Admin lite (her ortam)
        "lite_selinux": "SELinux (lite)", "lite_failed_units": "Failed units (lite)",
        "lite_dmesg_issues": "dmesg sorun (lite)", "lite_journal_err": "Journal err (lite)",
        "lite_authlog": "Auth (lite)", "lite_df": "Disk (lite)", "lite_free": "Bellek (lite)",
        "lite_uptime_load": "Uptime/load (lite)", "lite_net_dns": "GW/DNS (lite)",
        "lite_sshd": "sshd (lite)", "lite_fstab": "fstab (lite)", "lite_sysctl": "sysctl (lite)",
        # Admin configs
        "cfg_fstab": "/etc/fstab", "cfg_dns_nss": "DNS/nsswitch", "cfg_hosts": "/etc/hosts",
        "cfg_sysctl": "sysctl conf", "cfg_limits": "limits.conf", "cfg_sshd": "sshd_config (özet)",
        "cfg_selinux": "SELinux config", "cfg_time": "NTP/chrony conf", "cfg_timedatectl": "timedatectl",
        "cfg_firewall": "Firewall kuralları", "cfg_network": "Ağ bağlantı config",
        "cfg_ip_route": "IP/route özeti", "cfg_cron": "Cron/timers", "cfg_tuned": "tuned profil",
        "cfg_hostname_target": "Hostname/default target", "cfg_logrotate": "logrotate",
        "cfg_needs_restart": "needs-restarting", "cfg_sudoers_summary": "sudoers özeti",
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
