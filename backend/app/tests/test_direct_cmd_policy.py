"""Linux direct_cmd hotfix: çıkarıcı enjeksiyonu + politika read_only boşlukları.

Bkz. docs/chat-quality/findings-direct-cmd.md
"""
import re

import pytest

from app.services.agent.policy import RiskLevel, classify_command
from app.services.linux_chat_intent import extract_direct_commands

_META = re.compile(r"[;&|`<>$\n\r(){}\\]")


# ── çıkarıcı: shell metakarakteri içeren komut ASLA üretilmez ─────────────────────────
@pytest.mark.parametrize("msg", [
    "df -h;reboot",
    "Admin: df -h`id`",
    "uptime -p$(id)",
    "ps -ef;touch /tmp/pwned",
    "top -b|tee /etc/x",
    "df -h&&reboot",
    "free -m>/etc/passwd",
    "ss -tulpn||id",
    "df -h\nreboot",
    "du -sh$IFS/etc",
    "ps -ef ${IFS}",
    "ip -br a;id",
])
def test_extract_never_emits_shell_metacharacters(msg):
    for cmd in extract_direct_commands(msg):
        assert not _META.search(cmd), f"{msg!r} -> {cmd!r}"


@pytest.mark.parametrize("msg,expected", [
    ("df -h", ["df -h"]),
    ("Admin: uptime", ["uptime"]),
    ("uptime?", ["uptime"]),          # noktalama komuta sızmaz
    ("lütfen vmstat 1 5 çalıştır", ["vmstat 1 5"]),
    ("free -m göster", ["free -m"]),
    ("ss -tulpn", ["ss -tulpn"]),
    ("ip -br a", ["ip -br a"]),
])
def test_extract_benign_still_works(msg, expected):
    assert extract_direct_commands(msg) == expected


def test_extract_unsafe_flag_drops_command_instead_of_running_bare():
    # "-h;reboot" güvenli değil → komut tamamen atılır (çıplak `df` çalışmaz)
    assert extract_direct_commands("df -h;reboot") == []


# ── politika: mutating olması gerekenler read_only OLMAMALI ───────────────────────────
@pytest.mark.parametrize("cmd", [
    "ss -K", "ss --kill", "ss -tK", "ss -tulpn -K",
    "ip addr flush dev eth0", "ip link set eth0 down", "ip route del default",
    "ip addr add 10.0.0.5/24 dev eth0", "ip -s link set eth0 up",
    "ip netns exec x id", "ip -b /tmp/batch",
    "df -h > /etc/x", "cat /etc/passwd > /tmp/x", "cat /etc/hosts >> /tmp/x",
    "cat < /etc/passwd",
    "sar -o /tmp/x 1 1",
    "find / -delete", "find . -exec rm {} +", "find . -execdir id ;", "find / -fprint /tmp/x",
    "route add default gw 1.1.1.1", "route del default",
    "arp -s 1.1.1.1 aa:bb:cc:dd:ee:ff", "arp -d 1.1.1.1",
    "ifconfig eth0 down", "ifconfig eth0 10.0.0.5", "ifconfig eth0 up",
    "date -s 10:00", "date --set=10:00",
    "hostname newname",
    "env FOO=1 touch /tmp/x", "env id",
    "mount /dev/sdb /mnt", "mount -o remount,rw /",
    "dnf history undo 5", "yum history rollback 3",
    "journalctl --vacuum-size=1M", "journalctl --rotate",
    "dmesg -c", "dmesg --clear",
    "ping -f 10.0.0.1",
    "df\nreboot",
])
def test_policy_not_read_only(cmd):
    assert classify_command(cmd) != RiskLevel.READ_ONLY, cmd


# ── politika: meşru teşhis komutları read_only KALMALI ───────────────────────────────
@pytest.mark.parametrize("cmd", [
    "df -h", "free -m", "uptime", "ps -ef", "ss -tulpn", "netstat -tulpn",
    "ip addr show", "ip -br a", "ip -s link", "ip route show", "ip route get 1.1.1.1",
    "ip neigh show", "ip -4 addr",
    "find /var/log -name '*.log'", "find /etc -maxdepth 1 -type f",
    "route -n", "arp -a", "arp -n", "ifconfig", "ifconfig -a", "ifconfig eth0",
    "date", "date +%F", "hostname", "hostname -f", "env", "printenv PATH",
    "mount", "mount -l", "mount -l -t ext4",
    "dnf history list", "journalctl -u sshd -n 50", "dmesg", "ping -c 3 10.0.0.1",
    "vmstat 1 5", "iostat -x 1 3", "sar -u 1 3", "lsblk", "lscpu", "uname -a",
    "journalctl -n 20 2>/dev/null",
])
def test_policy_diagnostics_still_read_only(cmd):
    assert classify_command(cmd) == RiskLevel.READ_ONLY, cmd


def test_policy_existing_behaviour_kept():
    assert classify_command("rm -rf /tmp/x") == RiskLevel.DENIED
    assert classify_command("df -h;reboot") == RiskLevel.DENIED
    assert classify_command("sudo ls") == RiskLevel.MUTATING
    assert classify_command("systemctl status sshd") == RiskLevel.READ_ONLY
    assert classify_command("systemctl restart sshd") == RiskLevel.MUTATING
    assert classify_command("") == RiskLevel.DENIED
