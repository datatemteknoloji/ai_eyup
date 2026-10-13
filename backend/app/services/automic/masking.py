"""Maskeleme — LLM / modül DB / audit / UI öncesi zorunlu katman.

Karar: LLM kurum içinde çalışsa bile gizli bilgiler hiçbir koşulda LLM'e, UI'a,
sohbet geçmişine veya loglara gitmez.

Kurallar:
  - HER ZAMAN: şifre, token, API anahtarı, private key, kimlik bilgisi içeren
    bağlantı cümleleri (PWD=, password=, user/pass@host, Authorization, …)
  - Maskelenmez: Automic kullanıcı adları (NAME/DEPARTMENT)
  - Ayarlanabilir: IP (`mask_ip`) ve hostname (`mask_hostname`) — varsayılan: gösterilir
  - Ülke paketi (tr): TCKN, IBAN, telefon, e-posta
  - custom_patterns: kurum desenleri

Maskelenen değer geri çözülemez.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

logger = logging.getLogger(__name__)

MASK = "***"

_SECRET_WORDS = (
    r"(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credential|auth[_-]?token|bearer)"
)

# Automic OH kullanıcı adı NAME/DEPARTMENT — yolu/sqlplus user/pass@host ile karışmaz
# (önde / yok; sonda @ veya devam eden path karakteri yok; segmente nokta yok)
_AUTOMIC_USER_RE = re.compile(
    r"(?<![/\w.-])([A-Za-z][A-Za-z0-9_]{0,199}/[A-Za-z][A-Za-z0-9_]{0,199})(?![@\w./])"
)

# (ad, regex, ikame) — ikame grup referansı içerebilir. HER ZAMAN uygulanır.
_BASE_RULES: List[Tuple[str, str, str]] = [
    ("private_key_block",
     r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
     "[MASKED PRIVATE KEY]"),
    ("automic_secret_var",
     rf"(?i)(&\w*{_SECRET_WORDS}\w*#\s*=\s*)(\"[^\"]*\"|'[^']*'|\S+)",
     rf"\1{MASK}"),
    ("authorization_header",
     r"(?i)(authorization\s*[:=]\s*(?:basic|bearer|token)\s+)[A-Za-z0-9._~+/=-]+",
     rf"\1{MASK}"),
    ("url_credentials",
     r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)([^@\s]+)(@)",
     rf"\1{MASK}\3"),
    ("jdbc_password",
     r"(?i)((?:jdbc|odbc)[^\s]*?(?:password|pwd)\s*=\s*)([^;&\s]+)",
     rf"\1{MASK}"),
    # Bağlantı cümlesi: ...;PWD=secret;  veya password=...
    ("conn_pwd_eq",
     r"(?i)((?:^|[;\s,&])(?:PWD|PASSWORD|PASSWD)\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s;,&]+)",
     rf"\1{MASK}"),
    ("key_value_secret",
     rf"(?i)(\b[\w.-]*{_SECRET_WORDS}[\w-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)",
     rf"\1{MASK}"),
    ("cli_password_flag",
     r"(?i)(--?(?:password|passwd|pwd)(?:=|\s+))(\"[^\"]*\"|'[^']*'|\S+)",
     rf"\1{MASK}"),
    # mysql tarzı -pŞİFRE (boşluksuz); -password / -print / -port ile karışmaz
    ("cli_p_glued",
     r"(?i)(?<![A-Za-z0-9_-])(-p)(?!(?:ass(?:word|wd)|wd|rint|ath|ort|ipe|rofile)\b)([^\s]+)",
     rf"\1{MASK}"),
    # connect user/pass[@tns]
    ("connect_user_pass",
     r"(?i)(\bconnect\s+)([A-Za-z0-9_$#.]+/)([^@\s/\"';]+)(@[A-Za-z0-9_.:/-]+)?",
     rf"\1\2{MASK}\4"),
    # user/pass@host — Automic NAME/DEPT (@ yok) eşleşmez
    ("oracle_connect_string",
     r"(\b[A-Za-z0-9_$#.]+/)([^@\s/\"']+)(@[A-Za-z0-9_.:/-]+)",
     rf"\1{MASK}\3"),
    ("bare_bearer",
     r"(?i)(?<![\w-])(bearer\s+)([A-Za-z0-9._~+/=-]{8,})",
     rf"\1{MASK}"),
    ("jwt",
     r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
     MASK),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b", MASK),
]

_TR_RULES: List[Tuple[str, str, str]] = [
    ("tr_plain_password",
     r"(?i)((?:yeni\s+)?(?:şifre|sifre)\s+)([^\s,.;!?]+)",
     rf"\1{MASK}"),
    ("tr_iban", r"\bTR\d{2}[ ]?(?:\d{4}[ ]?){5}\d{2}\b", "[IBAN]"),
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
    ("tr_mobile", r"(?<!\d)(?:\+90[\s-]?|0)5\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)", "[TELEFON]"),
]

_TCKN_RE = re.compile(r"(?<!\d)([1-9]\d{10})(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
# FQDN (en az bir nokta + harf TLD); Automic JOBS.FIN.X gibi tamamen büyük kısa etiketler atlanır
_FQDN_RE = re.compile(
    r"(?<![A-Za-z0-9.-])([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+)"
    r"(?![A-Za-z0-9.-])"
)
_HOST_KV_RE = re.compile(
    r"(?i)(\b(?:host(?:name)?|server)\s*[:=]\s*)([A-Za-z0-9][A-Za-z0-9._-]{1,253})"
)

# Secrets-only cfg — audit / hata mesajı (IP/hostname/ülke dokunulmaz)
SECRETS_ONLY: Dict[str, Any] = {
    "country_pack": "none",
    "mask_ip": False,
    "mask_hostname": False,
    "custom_patterns": [],
}


def is_valid_tckn(s: str) -> bool:
    if len(s) != 11 or not s.isdigit() or s[0] == "0":
        return False
    d = [int(c) for c in s]
    if ((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10) != d[9]:
        return False
    return (sum(d[:10]) % 10) == d[10]


def _valid_ipv4(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def _looks_like_fqdn(s: str) -> bool:
    """Basit FQDN: en az bir nokta, son etiket harf (TLD), tamamen JOBS.* değil."""
    if "." not in s or len(s) > 253:
        return False
    labels = s.split(".")
    if len(labels) < 2:
        return False
    tld = labels[-1]
    if not tld.isalpha() or len(tld) < 2:
        return False
    # Automic nesne adı benzeri (hepsi kısa büyük harf etiketleri)
    if all(lb.isupper() and lb.replace("_", "").isalnum() for lb in labels):
        return False
    return True


@lru_cache(maxsize=64)
def _compile(rules: Tuple[Tuple[str, str, str], ...]) -> Tuple[Tuple[Pattern[str], str], ...]:
    out = []
    for name, rx, repl in rules:
        try:
            out.append((re.compile(rx), repl))
        except re.error as exc:
            logger.warning("Maskeleme deseni derlenemedi (%s): %s", name, exc)
    return tuple(out)


def validate_custom_patterns(patterns: Iterable[Dict[str, Any]]) -> List[str]:
    errors = []
    for p in patterns or []:
        rx = (p or {}).get("regex") or ""
        if not rx or len(rx) > 500:
            errors.append(f"{(p or {}).get('name') or '?'}: desen boş veya çok uzun")
            continue
        try:
            re.compile(rx)
        except re.error as exc:
            errors.append(f"{p.get('name') or rx}: geçersiz regex ({exc})")
    return errors


def _stash_automic_users(text: str) -> Tuple[str, Dict[str, str]]:
    placeholders: Dict[str, str] = {}

    def _repl(m: re.Match) -> str:
        key = f"\x00AU{len(placeholders)}\x00"
        placeholders[key] = m.group(0)
        return key

    return _AUTOMIC_USER_RE.sub(_repl, text), placeholders


def _restore(text: str, placeholders: Dict[str, str]) -> str:
    out = text
    for k, v in placeholders.items():
        out = out.replace(k, v)
    return out


def normalize_masking_cfg(masking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Eksik anahtarları politika varsayılanlarıyla doldurur (IP/hostname varsayılan: göster)."""
    cfg = dict(masking or {})
    cfg.setdefault("country_pack", "tr")
    cfg.setdefault("mask_ip", False)
    cfg.setdefault("mask_hostname", False)
    cfg.setdefault("custom_patterns", [])
    return cfg


# Automic NAME/DEPT stash'inden ÖNCE uygulanır (app/Secret99@… stash'e kaçmasın)
_PRE_STASH_RULE_NAMES = frozenset({
    "connect_user_pass", "oracle_connect_string", "url_credentials", "jdbc_password",
})


def mask_text(text: str, masking: Dict[str, Any] | None = None) -> str:
    """Metni ayarlara göre maskeler. Gizli alanlar her zaman; IP/hostname ayara bağlı."""
    if not text:
        return text or ""
    cfg = normalize_masking_cfg(masking)
    pre = [r for r in _BASE_RULES if r[0] in _PRE_STASH_RULE_NAMES]
    rest = [r for r in _BASE_RULES if r[0] not in _PRE_STASH_RULE_NAMES]
    out = text
    for rx, repl in _compile(tuple(pre)):
        out = rx.sub(repl, out)
    out, stashed = _stash_automic_users(out)
    rules: List[Tuple[str, str, str]] = list(rest)
    if (cfg.get("country_pack") or "tr") == "tr":
        rules.extend(_TR_RULES)
    for p in cfg.get("custom_patterns") or []:
        rx = (p or {}).get("regex")
        if rx:
            rules.append((p.get("name") or "custom", rx, "[MASKED]"))
    for rx, repl in _compile(tuple(rules)):
        out = rx.sub(repl, out)
    if (cfg.get("country_pack") or "tr") == "tr":
        out = _TCKN_RE.sub(lambda m: "[TCKN]" if is_valid_tckn(m.group(1)) else m.group(1), out)
    if cfg.get("mask_ip"):
        out = _IPV4_RE.sub(lambda m: "[IP]" if _valid_ipv4(m.group(1)) else m.group(1), out)
    if cfg.get("mask_hostname"):
        out = _HOST_KV_RE.sub(rf"\1{MASK}", out)
        out = _FQDN_RE.sub(
            lambda m: "[HOST]" if _looks_like_fqdn(m.group(1)) else m.group(1), out)
    return _restore(out, stashed)


def mask_obj(obj: Any, masking: Dict[str, Any] | None = None) -> Any:
    """dict/list içindeki tüm string değerleri maskeler."""
    if isinstance(obj, str):
        return mask_text(obj, masking)
    if isinstance(obj, dict):
        return {k: mask_obj(v, masking) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_obj(v, masking) for v in obj]
    return obj


def redact_secrets(text: str) -> str:
    """Hata / audit / log — yalnız temel secret kuralları (IP/hostname/ülke yok)."""
    return mask_text(text, SECRETS_ONLY)


def masking_cfg_for_system(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """AutomicSystem.settings → normalize edilmiş masking cfg."""
    from .defaults import effective_settings
    return normalize_masking_cfg((effective_settings(settings) or {}).get("masking"))
