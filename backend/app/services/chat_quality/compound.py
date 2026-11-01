"""Bileşik sayım sorusu ayrıştırma (Adım 6c-1).

«Kaç VM var ve OpenShift'te kaç node var?», «Kapalı VM sayısı kaç, hatalı pod sayısı kaç?»,
«Kaç Linux sunucum, kaç VM ve kaç OpenShift node var?» → parçalar. Bölme yalnız ayraçta (`,` `;` «ve»
«ayrıca» «hem de» «and») ve her parçada bir sayım işareti varsa yapılır; aksi halde tek parça (bölünmez).
Zamirli parça («kaçı kapalı?») önceki parçanın konusunu/kapsamını devralır.

Saf modül; cevap üretimi `count_rules.count_response` içinde (parça başına kural, desteklenmeyen parça
açık not; hiçbir parça kural yolunda değilse None → normal akış).
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.services.chat_quality.claims import fold

_SEP_RE = re.compile(r"\s*(?:,|;|\bve\b|\bayrıca\b|\bayrica\b|\bhem de\b|\band\b|\bplus\b)\s*", re.IGNORECASE)
_COUNT_RE = re.compile(r"\b(?:kac\w*|sayisi\w*|adedi\w*|how many|number of)\b")
_PRONOUN_RE = re.compile(r"\b(?:kaci|kacinin|kactanesi|kac tanesi|how many of (?:them|those))\b")
_STATE_WORDS = re.compile(
    r"\b(kapali|acik|calisan|askida|hatali|sorunlu|bekleyen|powered off|powered on|off|on|running|stopped)\b"
)
_MAX_PARTS = 4
# Yönerge / açıklama isteği olan cümle bölünmez (liste, grafik, karşılaştırma, neden)
_NO_SPLIT_RE = re.compile(
    r"\b(?:goster\w*|listele\w*|liste\w*|grafik\w*|chart|graph|ciz\w*|tablo\w*|karsilastir\w*|trend\w*|"
    r"neden|niye|nicin|why|show|list|plot)\b"
)


def _has_count(text: str) -> bool:
    return bool(_COUNT_RE.search(fold(text)))


def split_parts(message: str) -> List[str]:
    """Bileşik sayım sorusunu parçalara ayır; bölünemiyorsa tek elemanlı liste."""
    msg = (message or "").strip()
    if not msg or len(msg) > 300 or "\n" in msg.strip():
        return [msg]
    mf = fold(msg)
    if len(_COUNT_RE.findall(mf)) < 2 or _NO_SPLIT_RE.search(mf):
        return [msg]
    pieces: List[str] = []
    last = 0
    for m in _SEP_RE.finditer(msg):
        pieces.append(msg[last:m.start()])
        last = m.end()
    pieces.append(msg[last:])
    pieces = [p.strip(" ?.!") for p in pieces]
    # sayım işareti olmayan parça komşusuna yapışır (ad içindeki «ve», «A ve B arasındaki fark» …)
    merged: List[str] = []
    for p in pieces:
        if not p:
            continue
        if merged and not _has_count(p):
            merged[-1] = f"{merged[-1]} ve {p}"
        elif not merged and not _has_count(p):
            merged.append(p)
        else:
            if merged and not _has_count(merged[-1]):
                merged[-1] = f"{merged[-1]} ve {p}"
            else:
                merged.append(p)
    if len(merged) < 2 or len(merged) > _MAX_PARTS:
        return [msg]
    return [(p[:1].upper() + p[1:]) + "?" for p in merged]


def resolve_pronoun(part: str, previous: Optional[str]) -> Optional[str]:
    """«kaçı kapalı?» → önceki parçanın sayım cümlesine durum sözcüğünü ekle. Çözülemezse None."""
    if not previous:
        return None
    pf = fold(part)
    if not _PRONOUN_RE.search(pf):
        return None
    st = _STATE_WORDS.search(pf)
    if not st:
        return None
    prev = previous.rstrip(" ?")
    m = re.search(r"\b(kaç|kac)\b", prev, re.IGNORECASE)
    if m:
        return f"{prev[:m.end()]} {st.group(1)}{prev[m.end():]}?"
    return None


def is_compound(message: str) -> bool:
    return len(split_parts(message)) > 1
