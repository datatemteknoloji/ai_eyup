"""
Agent Sandbox / Policy Engine.

Tek sorumluluk: bir komutun veya tool çağrısının ÇALIŞTIRILABİLİR olup olmadığına
ve çalıştırılabilecekse İNSAN ONAYI gerekip gerekmediğine karar vermek.

Tasarım ilkeleri:
  - Varsayılan DENY: tanınmayan / şüpheli her şey reddedilir veya onaya düşer.
  - READ_ONLY  → otomatik çalıştırılabilir (teşhis komutları).
  - MUTATING   → yalnızca insan onayından sonra çalıştırılır.
  - DENIED     → asla çalıştırılmaz (yıkıcı / tehlikeli).

Bu modülün hiçbir yan etkisi yoktur (saf fonksiyonlar) — kolay test edilir.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import List


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"   # otomatik
    MUTATING = "mutating"     # onay gerekir
    DENIED = "denied"         # asla


# ── Salt-okunur teşhis komutları (otomatik çalıştırılır) ─────────────────────
# Yalnızca komutun ilk kelimesi (binary adı) baz alınır.
READ_ONLY_COMMANDS = {
    "uptime", "free", "df", "du", "ps", "top", "vmstat", "iostat", "sar",
    "ss", "netstat", "ip", "ifconfig", "arp", "route", "lsblk", "lscpu",
    "lsmod", "uname", "hostname", "whoami", "id", "date", "cat", "head",
    "tail", "grep", "wc", "stat", "find", "ls", "journalctl", "dmesg",
    "systemctl",  # yalnızca status/list-* alt komutları için (aşağıda kontrol)
    "rpm", "dpkg", "dnf", "yum", "apt", "apt-get",  # yalnızca sorgu alt komutları
    "ping", "ss", "who", "last", "env", "printenv", "mount", "lsof",
    # LVM salt-okunur sorgular
    "pvs", "vgs", "lvs", "pvdisplay", "vgdisplay", "lvdisplay",
    "pvscan", "vgscan", "lvscan",
}

# Bazı binary'ler read-only SADECE belirli alt komutlarla (aksi halde mutating/denied).
SUBCOMMAND_READONLY = {
    "systemctl": {"status", "is-active", "is-enabled", "list-units", "list-unit-files",
                  "show", "cat", "list-timers", "list-dependencies"},
    "dnf": {"list", "info", "search", "check-update", "repolist", "history", "repoquery"},
    "yum": {"list", "info", "search", "check-update", "repolist", "history"},
    "apt": {"list", "show", "search", "policy"},
    "apt-get": {"-s", "--simulate", "--dry-run"},
    "dpkg": {"-l", "-L", "-s", "--list", "--status"},
    "rpm": {"-q", "-qa", "-qi", "-ql", "--query"},
    "ip": {"addr", "a", "link", "route", "r", "neigh", "-s"},
}

# ── Yıkıcı / tehlikeli desenler → her zaman DENIED ──────────────────────────
DESTRUCTIVE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\brm\s+(-[a-z]*f|-[a-z]*r|--force|--recursive)", re.I),
    re.compile(r"\brm\s+-\w*\s*/(\s|$)", re.I),          # rm -rf /
    re.compile(r"\bmkfs(\.\w+)?\b", re.I),
    re.compile(r"\bdd\b[^|]*\bof=/dev/", re.I),
    re.compile(r"\b(shutdown|reboot|halt|poweroff|init\s+0|init\s+6)\b", re.I),
    re.compile(r">\s*/dev/(sd|nvme|vd|hd)", re.I),
    re.compile(r"\bchmod\s+-R?\s*0?777\b", re.I),
    re.compile(r"\bchown\s+-R\b.*\s/(\s|$)", re.I),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;", re.I),    # fork bomb
    re.compile(r"\bmv\s+[^|]*\s+/dev/null\b", re.I),
    re.compile(r"\b(wget|curl)\b.*\|\s*(sudo\s+)?(bash|sh)\b", re.I),  # uzaktan kod indirip çalıştırma
    re.compile(r"\buserdel\b|\bgroupdel\b", re.I),
    re.compile(r"\biptables\s+-F\b|\bufw\s+disable\b", re.I),
    re.compile(r"\btruncate\b.*\s/(?!var/log)", re.I),   # /var/log dışı truncate riskli
    re.compile(r"\bcrontab\s+-r\b", re.I),
    # LVM yıkıcı işlemleri (veri kaybı) — asla
    re.compile(r"\b(lvremove|vgremove|pvremove)\b", re.I),
    re.compile(r"\blvreduce\b", re.I),
    re.compile(r"\b(lvresize|lvextend)\b[^|]*-L\s*-", re.I),  # küçültme (-L -<size>)
    re.compile(r"\bvgreduce\b", re.I),
]

# Komut zincirleme / enjeksiyon / yönlendirme karakterleri (mutating sayılır, ham komutta).
# `>`/`<` (dosya yazma/okuma yönlendirmesi), satır sonu ve `${` genişletmesi dahil.
_CHAINING = re.compile(r"[;&|`<>\n\r]|\$\(|\$\{|\&\&|\|\|")
# Zararsız stderr atma kalıbı chaining sayılmaz.
_STDERR_NULL = re.compile(r"\s2>\s*/dev/null\b")


def _first_tokens(command: str) -> List[str]:
    return [t for t in command.strip().split() if t]


# ── Binary'ye özgü argüman doğrulaması (yalnız READ_ONLY_COMMANDS içindekiler) ──────
_IP_RO_OBJECTS = {
    "addr", "a", "address", "link", "l", "route", "r", "neigh", "n", "neighbor",
    "neighbour", "rule", "maddr", "maddress", "tunnel", "tuntap", "netconf",
    "mroute", "mrule", "vrf",
}
_IP_MUTATING_VERBS = {
    "add", "del", "delete", "set", "flush", "change", "replace", "append", "prepend",
    "exec", "save", "restore", "test",
}
# ip seçenekleri: -b/-batch dosyadan komut çalıştırır, -n/-netns ad alanı değiştirir
_IP_FORBIDDEN_OPTS = {"-b", "-batch", "-force", "-n", "-netns", "-rc", "-rcvbuf"}
_FIND_FORBIDDEN = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0",
                   "-fprintf", "-fls"}
_HOSTNAME_FLAGS = {"-f", "-i", "-I", "-s", "-d", "-A", "-a", "-y", "--fqdn", "--ip-address",
                   "--all-ip-addresses", "--short", "--domain", "--alias", "--long", "--all-fqdns"}
_FS_TYPE = re.compile(r"^[A-Za-z0-9_,.+-]+$")
_IFACE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _short_cluster_has(arg: str, ch: str) -> bool:
    """`-tK` gibi kısa bayrak kümesinde ch var mı (`--uzun` bayraklar hariç)."""
    return arg.startswith("-") and not arg.startswith("--") and ch in arg[1:]


def _ip_ok(args: List[str]) -> bool:
    low = [a.lower() for a in args]
    i = 0
    while i < len(low) and low[i].startswith("-"):
        if low[i] in _IP_FORBIDDEN_OPTS:
            return False
        i += 1
    if i >= len(low) or low[i] not in _IP_RO_OBJECTS:
        return False
    return not any(a in _IP_MUTATING_VERBS for a in low[i + 1:])


def _readonly_args_ok(binary: str, args: List[str]) -> bool:
    """READ_ONLY_COMMANDS içindeki binary'nin argümanları gerçekten salt-okunur mu."""
    low = [a.lower() for a in args]
    if binary == "ss":
        return not any(a == "--kill" or _short_cluster_has(a, "K") for a in args)
    if binary == "ip":
        return _ip_ok(args)
    if binary == "sar":
        return not any(a == "-o" or (a.startswith("-o") and not a.startswith("--")) for a in args)
    if binary == "find":
        return not any(a in _FIND_FORBIDDEN or a.startswith("-fprint") for a in low)
    if binary == "route":
        return all(a in {"-n", "-e", "-ee", "-v", "-c", "-f", "-4", "-6"} for a in low)
    if binary == "arp":
        return all(a in {"-a", "-n", "-e", "-v", "--all", "--numeric"} for a in low)
    if binary == "ifconfig":
        if not args:
            return True
        if all(a in {"-a", "-s", "-v"} for a in low):
            return True
        return len(args) == 1 and not args[0].startswith("-") and bool(_IFACE.match(args[0]))
    if binary == "date":
        return not any(a == "-s" or a.startswith("--set") or (a.startswith("-s") and not a.startswith("--"))
                       for a in low)
    if binary == "hostname":
        return all(a in _HOSTNAME_FLAGS for a in args)
    if binary == "env":
        return not args
    if binary == "mount":
        k = 0
        while k < len(low):
            if low[k] in ("-l", "--show-labels"):
                k += 1
            elif low[k] == "-t" and k + 1 < len(args) and _FS_TYPE.match(args[k + 1]):
                k += 2
            else:
                return False
        return True
    if binary == "dmesg":
        return not any(a in {"-c", "-C", "--clear", "--read-clear"} or _short_cluster_has(a, "c") or
                       _short_cluster_has(a, "C") for a in args)
    if binary == "journalctl":
        bad = ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish", "--smart-relinquish",
               "--setup-keys", "--update-catalog")
        return not any(a.startswith(bad) for a in low)
    if binary == "ping":
        return not any(_short_cluster_has(a, "f") for a in args)
    if binary in ("dnf", "yum") and low[:1] == ["history"]:
        return len(low) == 1 or low[1] in {"list", "info", "summary", "userinstalled"}
    return True


def is_destructive(command: str) -> bool:
    """Komut yıkıcı desenlerden birine uyuyor mu?"""
    for pat in DESTRUCTIVE_PATTERNS:
        if pat.search(command):
            return True
    return False


def classify_command(command: str) -> RiskLevel:
    """
    Ham bir shell komutunu sınıflandırır.

    READ_ONLY  → allowlist'teki binary + (gerekiyorsa) izinli alt komut, zincirleme yok.
    DENIED     → yıkıcı desen.
    MUTATING   → diğer her şey (onay gerektirir).
    """
    cmd = (command or "").strip()
    if not cmd:
        return RiskLevel.DENIED

    if is_destructive(cmd):
        return RiskLevel.DENIED

    tokens = _first_tokens(cmd)
    if not tokens:
        return RiskLevel.DENIED

    binary = tokens[0].lower()
    # sudo prefix'i: read-only komutlar sudo gerektirmez; sudo → en az MUTATING
    if binary == "sudo":
        return RiskLevel.MUTATING if not is_destructive(cmd) else RiskLevel.DENIED

    # Komut zincirleme varsa read-only sayma (enjeksiyon riski) → MUTATING
    if _CHAINING.search(_STDERR_NULL.sub("", cmd)):
        return RiskLevel.MUTATING

    if binary in READ_ONLY_COMMANDS:
        # Binary'ye özgü tehlikeli bayrak/alt komutlar (ör. ss -K, ip ... flush, find -delete)
        if not _readonly_args_ok(binary, tokens[1:]):
            return RiskLevel.MUTATING
        if binary == "ip":
            return RiskLevel.READ_ONLY
        # Alt komut kısıtlaması olan binary'ler
        if binary in SUBCOMMAND_READONLY:
            allowed = SUBCOMMAND_READONLY[binary]
            sub = tokens[1].lower() if len(tokens) > 1 else ""
            if sub in allowed:
                return RiskLevel.READ_ONLY
            return RiskLevel.MUTATING
        return RiskLevel.READ_ONLY

    return RiskLevel.MUTATING


def requires_approval(risk: RiskLevel) -> bool:
    return risk == RiskLevel.MUTATING


def is_allowed(risk: RiskLevel) -> bool:
    return risk != RiskLevel.DENIED
