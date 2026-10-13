"""Türkçe sayı ekleri ve kısa dil yardımcıları (model üretmez; kod üretir)."""
from __future__ import annotations

import re
from typing import Optional

_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "I": "i",
})


def fold_tr(text: str) -> str:
    """ASCII-Türkçe normalleştirme (küçük harf; ı/ş/ç/ğ/ö/ü → i/s/c/g/o/u). Hem mesaj hem kalıp kaynağı için."""
    return (text or "").translate(_FOLD).lower()


def fold_re(rx: "re.Pattern[str]") -> "re.Pattern[str]":
    """Kalıbı aynı dönüşümle katla: `[ıi]` → `[ii]`, `mı` → `mi`; \\w/\\s gibi kaçışlar etkilenmez."""
    return re.compile(rx.pattern.translate(_FOLD), rx.flags | re.IGNORECASE)


# Son basamağa göre "'sı / 'si / 'su / 'sü" (16'sı, 28'i, 100'ü, 11'i)
_SI_BY_DIGIT = {
    0: "'ı", 1: "'i", 2: "'si", 3: "'ü", 4: "'ü",
    5: "'i", 6: "'sı", 7: "'si", 8: "'i", 9: "'u",
}
# 10, 20, … 90 ve 100 özel
_SI_SPECIAL = {
    10: "'u", 20: "'si", 30: "'u", 40: "'ı", 50: "'si",
    60: "'ı", 70: "'i", 80: "'i", 90: "'ı", 100: "'ü",
}


def tr_si_suffix(n: int) -> str:
    """N'si/sı/su/sü eki (örn. 16 → \"'sı\" → \"16'sı\")."""
    n = abs(int(n))
    if n in _SI_SPECIAL:
        return _SI_SPECIAL[n]
    if n > 100 and n % 100 == 0:
        return "'ü" if n == 1000 else "'ü"
    return _SI_BY_DIGIT[n % 10]


def tr_n_si(n: int) -> str:
    """16 → \"16'sı\", 11 → \"11'i\"."""
    return f"{int(n)}{tr_si_suffix(n)}"


_AGENT_HINT_RE = re.compile(
    r"\b(?:LNX|WIN|SAP|UNIX|SOL|AIX|HPUX)[A-Z0-9_-]{2,}\b|"
    r"\bagent\b|\bajans\b",
    re.I,
)
_JOB_HINT_RE = re.compile(
    r"\b(?:JOBS|JOBP|JOBF|JOBG|SCRI|SCRP|EVNT|VARA)\.[A-Z0-9_.]+",
    re.I,
)


def entity_kind_for_action(message: str) -> str:
    """Eylem reddi önerisi için varlık tipi: agent | job | generic."""
    msg = message or ""
    if _JOB_HINT_RE.search(msg):
        return "job"
    if _AGENT_HINT_RE.search(msg):
        return "agent"
    return "generic"


def action_offer_tr(message: str, obj: str = "") -> str:
    kind = entity_kind_for_action(message)
    if kind == "agent":
        who = f"`{obj}` " if obj else "bu agent'ın "
        return f"{who}durumunu ve üzerindeki işleri gösterebilirim; "
    if kind == "job":
        who = f"`{obj}` " if obj else "bu job'ın "
        return f"{who}son çalışmalarını gösterebilirim; "
    return "Şu an çalışan işleri listeleyebilirim; "


def action_offer_en(message: str, obj: str = "") -> str:
    kind = entity_kind_for_action(message)
    if kind == "agent":
        who = f"`{obj}`" if obj else "this agent"
        return f"I can show {who}'s status and its current jobs if you like. "
    if kind == "job":
        who = f"`{obj}`" if obj else "this job"
        return f"I can show recent runs for {who} if you like. "
    return "I can list currently running jobs if you like. "
