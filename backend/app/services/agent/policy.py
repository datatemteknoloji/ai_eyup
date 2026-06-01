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
]

# Komut zincirleme / enjeksiyon karakterleri (mutating sayılır, ham komutta).
_CHAINING = re.compile(r"[;&|`]|\$\(|\&\&|\|\|")


def _first_tokens(command: str) -> List[str]:
    return [t for t in command.strip().split() if t]


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
    if _CHAINING.search(cmd):
        return RiskLevel.MUTATING

    if binary in READ_ONLY_COMMANDS:
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
