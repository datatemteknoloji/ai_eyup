"""Faz 3a — host donanım logu sınıflandırıcı (SAF fonksiyonlar; DB/ağ yok).

Girdi: tek log satırı (ESXi vmkernel/vmkwarning, Linux journal/dmesg, Windows olay) veya SEL kaydı.
Çıktı: `(kategori, önem)` ya da donanımla ilgisiz ise `None` (gürültü ÜRETİLMEZ).

Kural: önce özel/kritik kalıplar, sonra genel kalıplar; ilk eşleşme kazanır. Bellek tek-bit düzeltilmiş (CE) = uyarı,
düzeltilemez (UE) / MCE = kritik. SEL kayıtları tanım gereği donanımdır: kalıp bulunamazsa `platform` + sözcük
sezgisiyle önem verilir.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, List, NamedTuple, Optional, Tuple

SEV_CRITICAL, SEV_WARNING, SEV_INFO = "critical", "warning", "info"
_RANK = {SEV_INFO: 0, SEV_WARNING: 1, SEV_CRITICAL: 2}

SOURCES = ("esxi_sel", "esxi_vmkernel", "linux_journal", "windows_event")
CATEGORIES = ("memory", "cpu", "storage", "power", "thermal", "pcie", "network", "platform")


class Classified(NamedTuple):
    category: str
    severity: str


def worse(a: str, b: str) -> str:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def _r(p: str) -> "re.Pattern[str]":
    return re.compile(p, re.I)


# (kalıp, kategori, önem) — ESXi / Linux / SEL metinleri için ORTAK sıra. İlk eşleşme kazanır.
_TEXT_RULES: List[Tuple["re.Pattern[str]", str, str]] = [
    # ── CPU / MCE ─────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"uncorrect\w*.*(machine check|mce|processor)|(machine check|mce).*uncorrect|fatal.*machine check"
        r"|machine check exception|\bMCE:.*(panic|fatal)|Hardware Error.*(fatal|uncorrect)"), "cpu", SEV_CRITICAL),
    (_r(r"machine check|\bmce\b|mca:|Hardware Error|Machine Check Events logged"), "cpu", SEV_WARNING),
    (_r(r"temperature above threshold|cpu clock throttled|\b(core|package)\b.*throttl|thermal.*throttl"
        r"|throttl\w*.*thermal"), "thermal", SEV_WARNING),
    (_r(r"processor.*(fail|fault|disabled|ierr|catastrophic)|\bIERR\b|\bCATERR\b|\bcpu\s?\d*\s+(failed|failure|fault|offline due)"),
     "cpu", SEV_CRITICAL),
    # ── Bellek ────────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"uncorrect\w*.*(memory|ecc|dimm)|(memory|ecc|dimm).*uncorrect|\bEDAC\b.*\bUE\b|\bUE\b.*\bEDAC\b|multi-bit"
        r"|memory.*(fail|disabled|mirror(ing)? (lost|fail))|dimm.*(fail|disabled)|memory.*spare.*(lost|fail)"),
     "memory", SEV_CRITICAL),
    (_r(r"correct\w*.*(memory|ecc|dimm)|(memory|ecc|dimm).*correct|\bEDAC\b.*\bCE\b|\bECC\b|\bDIMM\b|single-bit"
        r"|memory.*(error|degrad|threshold)"), "memory", SEV_WARNING),
    # ── Güç ───────────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"power supply.*(fail|lost|loss|absent|ac lost|critical)|psu.*(fail|lost|loss|absent)"
        r"|redundancy lost|power (loss|lost|failure)|ac (power )?lost|voltage.*(critical|out of range|fail)"),
     "power", SEV_CRITICAL),
    (_r(r"power supply|\bpsu\b|power.*(warning|degrad|capping)|voltage.*(warn|low|high)"), "power", SEV_WARNING),
    # ── Isı / fan ─────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"(temperature|thermal|inlet|ambient).*(critical|upper (critical|non-recoverable)|exceed|overheat|shutdown)"
        r"|overheat|thermal (trip|shutdown)|fan.*(fail|stopped|absent|critical)"), "thermal", SEV_CRITICAL),
    (_r(r"temperature.*(warn|high|above|exceed|threshold|non-critical)|thermal.*(warn|event|limit|threshold)"
        r"|fan.*(warn|degrad|low speed|redundan)"), "thermal", SEV_WARNING),
    # ── PCIe ──────────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"AER:.*uncorrect\w*.*fatal|pcie.*fatal|uncorrected \(fatal\)|pci.*fatal error"), "pcie", SEV_CRITICAL),
    (_r(r"\bAER\b|pcieport.*error|pcie.*(bus )?error|pci.*error|corrected error received|uncorrected \(non-fatal\)"),
     "pcie", SEV_WARNING),
    # ── Depolama (donanım düzeyi) ─────────────────────────────────────────────────────────────────────────────
    (_r(r"medium error|unrecovered read error|critical medium error|predictive failure|smart.*(fail|pre-fail)"
        r"|smartd.*(FAILED|Pre-Fail|Offline uncorrectable|Currently unreadable|unreadable)"
        r"|drive.*(fail|fault|removed|predictive)|disk.*(failed|fault)|raid.*(degrad|fail|offline)"
        r"|md:.*degraded|DegradedArray|virtual disk.*(degrad|fail|offline)|sense data: 0x[34] 0x"), "storage", SEV_CRITICAL),
    (_r(r"nvme\d*.*(timeout|i/o error|reset|controller is down|fail|abort)|\bata\d+(\.\d+)?:.*"
        r"(exception|failed command|SError|hard resetting link|link is slow)"
        r"|lost access to volume|all paths down|\bAPD\b|permanent device loss|\bPDL\b|path.*(failed|dead|lost)"
        r"|NMP.*(path|fail|error).*(dead|offline|failed over)|storahci|stornvme"
        r"|(naa\.|eui\.|scsi|lun).*(removed|permanently inaccessible)"
        r"|abort.*scsi|scsi.*(abort|timeout|reset)"), "storage", SEV_WARNING),
    # ── Ağ kartı (fiziksel) ───────────────────────────────────────────────────────────────────────────────────
    (_r(r"vmnic\d+.*(link (is )?down|down|transmit timed out)|NETDEV WATCHDOG|nic link down|\bNIC\b.*(fail|firmware|reset|hang)"
        r"|\b(ixgbe|i40e|bnxt_en|qede|mlx\d\w*|tg3|igb|e1000e)\b.*(error|fail|reset|hang|timeout|link down)"),
     "network", SEV_WARNING),
    # ── Platform ──────────────────────────────────────────────────────────────────────────────────────────────
    (_r(r"\bNMI\b|non-?maskable|BlueScreen|purple diagnostic|kernel panic|watchdog.*(timeout|reset|expired)"
        r"|unexpected (shutdown|reboot)|system (reset|crash)|bios.*(error|corrupt)|firmware.*(error|fail|corrupt)"
        r"|\bipmi\w*.*(error|fail|timeout)|bmc.*(error|fail|reset)|sensor.*(failed|fault)"), "platform", SEV_CRITICAL),
    (_r(r"\bsel\b.*(full|nearly)|chassis intrusion|intrusion"), "platform", SEV_WARNING),
]

# SEL: kalıp yoksa sözcük sezgisi (kayıt zaten donanım kaydıdır)
_SEL_CRIT = _r(r"critical|fail|fault|lost|error|asserted.*(non-recoverable)|non-recoverable|unrecoverable")
_SEL_WARN = _r(r"warning|degrad|non-critical|predictive|threshold|deasserted.*(fail)|assert")


def classify_text(msg: str) -> Optional[Classified]:
    """ESXi vmkernel/vmkwarning ve Linux journal satırları için. Donanımla ilgisiz → None."""
    text = (msg or "").strip()
    if len(text) < 8:
        return None
    for pat, cat, sev in _TEXT_RULES:
        if pat.search(text):
            return Classified(cat, sev)
    return None


def classify_sel(msg: str) -> Classified:
    """SEL kaydı: her zaman donanım. Önce ortak kalıplar; yoksa `platform` + sözcük sezgisi."""
    c = classify_text(msg)
    if c is not None:
        return c
    text = msg or ""
    if _SEL_CRIT.search(text):
        return Classified("platform", SEV_CRITICAL)
    if _SEL_WARN.search(text):
        return Classified("platform", SEV_WARNING)
    return Classified("platform", SEV_INFO)


# ── Windows ──────────────────────────────────────────────────────────────────────────────────────────────────
# (sağlayıcı alt dizgisi, {olay_id: (kategori, önem)}, varsayılan (kategori, önem) | None)
_WIN_PROVIDERS = [
    ("whea-logger", {18: ("cpu", SEV_CRITICAL), 1: ("platform", SEV_CRITICAL), 20: ("memory", SEV_WARNING),
                     19: ("cpu", SEV_WARNING), 17: ("pcie", SEV_WARNING), 47: ("memory", SEV_WARNING),
                     46: ("memory", SEV_WARNING)}, ("platform", SEV_WARNING)),
    ("kernel-processor-power", {37: ("thermal", SEV_WARNING), 35: ("cpu", SEV_INFO)}, None),
    ("kernel-power", {41: ("platform", SEV_CRITICAL), 137: ("power", SEV_WARNING)}, None),
    ("wer-systemerrorreporting", {1001: ("platform", SEV_CRITICAL)}, None),
    ("disk", {7: ("storage", SEV_CRITICAL), 11: ("storage", SEV_WARNING), 15: ("storage", SEV_WARNING),
              51: ("storage", SEV_WARNING), 52: ("storage", SEV_CRITICAL), 153: ("storage", SEV_WARNING),
              157: ("storage", SEV_WARNING)}, None),
    ("storahci", {129: ("storage", SEV_WARNING), 153: ("storage", SEV_WARNING)}, ("storage", SEV_WARNING)),
    ("stornvme", {}, ("storage", SEV_WARNING)),
    ("volmgr", {46: ("storage", SEV_WARNING), 161: ("storage", SEV_WARNING)}, None),
    ("server administrator", {}, ("platform", SEV_WARNING)),      # Dell OMSA
    ("smart array", {}, ("storage", SEV_WARNING)),                # HPE
    ("hpsamgmt", {}, ("platform", SEV_WARNING)),
]


def classify_windows(provider: str, event_id: Optional[int], message: str, level_sev: Optional[str] = None) -> Optional[Classified]:
    """Windows olayı: sağlayıcı + olay no tablosu; tabloda yoksa mesaj kalıpları. `level_sev` (olay düzeyi) yalnız
    tabloda varsayılan olan sağlayıcılarda kritik/uyarı ayrımına yardım eder."""
    prov = (provider or "").lower()
    for sub, by_id, default in _WIN_PROVIDERS:
        if sub in prov:
            if event_id is not None and int(event_id) in by_id:
                c, s = by_id[int(event_id)]
                return Classified(c, s)
            if default is not None:
                c, s = default
                if level_sev == SEV_CRITICAL and s != SEV_CRITICAL and sub in ("whea-logger", "stornvme", "storahci"):
                    s = SEV_CRITICAL
                return Classified(c, s)
            break
    return classify_text(message)


# ── Normalize / anahtar ──────────────────────────────────────────────────────────────────────────────────────
_TS_PREFIXES = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?\s*"),   # ISO (ESXi/journal)
    re.compile(r"^\s*\[\s*\d+\.\d+\]\s*"),                                                         # dmesg uptime
    re.compile(r"^\s*[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+"),                             # syslog
    re.compile(r"^\s*(cpu\d+:\d+\S*\)|\S+\s+)?(WARNING|ALERT|INFO|NOTICE):?\s*", re.I),            # ESXi seviye öneki
]
_VOLATILE = re.compile(r"0x[0-9a-f]+|\b[0-9a-f]{8}-[0-9a-f-]{27}\b|\b\d{1,3}(?:\.\d{1,3}){3}\b|\d+", re.I)


def normalize_message(msg: str) -> str:
    out = msg or ""
    for _ in range(2):
        for p in _TS_PREFIXES:
            out = p.sub("", out, count=1)
    out = _VOLATILE.sub("#", out.lower())
    return re.sub(r"\s+", " ", out).strip()[:200]


def event_key(source: str, msg: str) -> str:
    return hashlib.sha1(f"{source}|{normalize_message(msg)}".encode("utf-8", "ignore")).hexdigest()[:40]


# ── Zaman damgası ────────────────────────────────────────────────────────────────────────────────────────────
_TS_HEAD = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")


def parse_ts(text: Optional[str]) -> Optional[datetime]:
    """Metnin başındaki ISO zaman damgası (UTC'ye çevrilir); yoksa None."""
    if not text:
        return None
    m = _TS_HEAD.match(text)
    if not m:
        return None
    raw = m.group(1).replace(" ", "T")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    raw = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Metin maskeleme (kartta/API'de gösterilen metin) ─────────────────────────────────────────────────────────
_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_WWN = re.compile(r"\b(?:naa|eui|t10)\.[0-9a-f]{8,}\b", re.I)
_MAC = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.I)


def mask_text(msg: Optional[str], limit: int = 400) -> str:
    out = _IPV4.sub("[ip]", msg or "")
    out = _UUID.sub("[id]", out)
    out = _MAC.sub("[mac]", out)
    out = _WWN.sub("[dev]", out)
    return re.sub(r"\s+", " ", out).strip()[:limit]


def prefilter_tokens() -> List[str]:
    """SQL ILIKE ön süzgeci (Linux/Windows `SystemEvent` taraması): kaba ama dar; sınıflandırıcı yeniden doğrular."""
    return ["machine check", "mce:", "edac", "hardware error", "pcieport", "aer:", "thermal", "temperature above",
            "throttl", "ecc", "dimm", "nvme", "smartd", "power supply", "ipmi", "whea", "kernel-power",
            "bugcheck", "storahci", "stornvme", "volmgr", "processor-power", "medium error", "unrecovered read",
            "degraded", "failed command", "sererror", "server administrator", "smart array", "[disk]"]
