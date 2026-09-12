"""Sohbet niyeti — kelime eşlemesi ve olumsuzluk penceresi.

Substring `in` / çıplak regex, 'anlık demiyorum' ve 'vCenter'a düşme'
gibi yemleri canlı/virt kapısı sanıyordu. Tüm router'lar burayı kullanır.
"""
from __future__ import annotations

import re
from typing import Iterable, Pattern, Sequence, Tuple, Union

# Anahtar kelimeden SONRA (Türkçe fiil olumsuzluğu / yasak)
_AFTER_NEG = (
    "demiyorum", "demiyoruz", "demedin", "deme ",
    "degil", "değil",
    "sapma", "sapmadan", "sapip", "sapıp",
    "dusme", "düşme", "dusmeden", "düşmeden",
    "bakma", "bakmadan", "bakip gecme", "bakıp geçme",
    "cekmeden", "çekmeden",
    "kaydirma", "kaydırma",
    "karistirma", "karıştırma",
    "yazma", "atma", "atlama",
    "eleme",
)

# Anahtar kelimeden ÖNCE (nadiren: 'X değil')
_BEFORE_NEG = (
    "degil ", "değil ",
    "sormuyorum",
)

_WINDOW = 56
_CLAUSE_BREAK = re.compile(r"[.;!?…—\n]| - ")


def fold_intent(text: str) -> str:
    """Eşleme için küçük harf; Türkçe I/İ tutarlı olsun diye casefold."""
    return (text or "").casefold()


def _clause_slice(text: str, start: int, end: int) -> Tuple[str, str]:
    """Aynı cümle/yan cümle — ';' veya em-dash öteki yemi bu kelimeye taşımasın."""
    left = 0
    for m in _CLAUSE_BREAK.finditer(text[:start]):
        left = m.end()
    right = len(text)
    m = _CLAUSE_BREAK.search(text[end:])
    if m:
        right = end + m.start()
    clause = text[left:right]
    local_start = start - left
    local_end = end - left
    before = clause[max(0, local_start - _WINDOW):local_start]
    after = clause[local_end:local_end + _WINDOW]
    return before, after


def occurrence_negated(text: str, start: int, end: int, window: int = _WINDOW) -> bool:
    before, after = _clause_slice(text, start, end)
    if any(n in after for n in _AFTER_NEG):
        return True
    if any(n in before for n in _BEFORE_NEG):
        return True
    return False


def keyword_spans(text: str, keyword: str) -> Sequence[Tuple[int, int]]:
    if not text or not keyword:
        return ()
    key = keyword.casefold()
    hay = text if text == text.casefold() else text.casefold()
    out = []
    start = 0
    while True:
        i = hay.find(key, start)
        if i < 0:
            break
        out.append((i, i + len(key)))
        start = i + max(1, len(key))
    return out


def keyword_hit(text: str, keyword: str) -> bool:
    """Kelime geçiyor ve en az bir geçiş olumsuz değil."""
    hay = fold_intent(text)
    key = fold_intent(keyword)
    if not hay or not key:
        return False
    hits = keyword_spans(hay, key)
    if not hits:
        return False
    return any(not occurrence_negated(hay, a, b) for a, b in hits)


def any_keyword_hit(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword_hit(text, k) for k in keywords)


def regex_hit(text: str, pattern: Union[str, Pattern[str]]) -> bool:
    """Regex eşleşmesi — olumsuz penceredekiler sayılmaz."""
    hay = fold_intent(text)
    if not hay:
        return False
    rx = re.compile(pattern, re.I) if isinstance(pattern, str) else pattern
    for m in rx.finditer(hay):
        if not occurrence_negated(hay, m.start(), m.end()):
            return True
    return False


_OPS_AFTER_SONRA = (
    "mdstat", "mdadm", "systemctl", "journalctl", "journal",
    "df -", "ssh", "iostat", "failed",
)


def mixed_operational_after_sonra(text: str) -> bool:
    """'RAID nedir, sonra minio1'de mdstat' — kavram + canlı host."""
    hay = fold_intent(text)
    if "sonra" not in hay:
        return False
    after = hay.split("sonra", 1)[1]
    return any(k in after for k in _OPS_AFTER_SONRA)
