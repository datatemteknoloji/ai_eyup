"""Soru türüne göre cevap bileşen profili — her araç sonucu otomatik basılmaz."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

_YESNO_RE = re.compile(
    r"(?i)\b(var\s+m[ıi]|yok\s+mu|mı\s*\?|mi\s*\?|mu\s*\?|mü\s*\?|"
    r"do[ğg]ru\s+mu|yanl[ıi][sş]\s+m[ıi]|hi[cç]\s+hata|hep\s+ba[sş]ar|"
    r"is\s+it\s+true|did\s+it\s+fail|any\s+fail)"
)
_COUNT_RE = re.compile(r"(?i)\b(ka[cç]|how\s+many|sayı|adet|oran|yüzde|%\s*)")
_LIST_RE = re.compile(
    r"(?i)\b(hangi\s+job|listele|list\b|en\s+[cç]ok|top\s+\d+|hata\s+veren|"
    r"failed\s+jobs?|show\s+me)"
)
_WHY_RE = re.compile(
    r"(?i)\b(neden|ni[cç]in|sebeb|why|root\s+cause)"
    r"|\b(?:sorun|problem|hata)\w*\s+ne(?:ydi|dir)\b|\bne\s+oldu\b|what\s+went\s+wrong|what\s+was\s+the\s+(?:problem|issue)")
_LASTRUN_RE = re.compile(
    r"(?i)(?:\ben\s+son\b|\bson\s+(?:kez|olarak)\b)[^?]*\b(?:ne\s+zaman|saat\s+ka[cç]ta|hangi\s+(?:tarih|saat|g[uü]n))\b"
    r"|\bne\s+zaman\b[^?]*\b(?:en\s+son|son\s+kez)\b"
    r"|\b(?:last\s+(?:run|ran|execution)|when\s+did\b[^?]*\blast\s+run)\b"
)
# "bir önceki çalışmasının raporunu göster" — odak nesnenin SON'dan bir önceki çalışması (+ raporu)
_PREVRUN_RE = re.compile(
    r"(?i)\b(?:bir\s+)?[öo]nceki\s+[cç]al[ıi][sş]ma\w*|\bprevious\s+(?:run|execution)\b"
)
_INFRA_RE = re.compile(
    r"(?i)\b(engine|pwp|\bwp\b|\bcp\b|agent|kopuk|ba[ğg]l[ıi]|sunucu|"
    r"infrastructure|hangi\s+sunucu)"
)


# ASCII-Türkçe / yazım hatalı sorular (katlanmış metin üzerinde): "joblar calisiyo mu simdi", "hata vermis mi"
_ACTIVE_FOLDED_RE = re.compile(
    r"\b(?:calis\w*|aktif|running|devam\s+ed\w*)\b")
_NOW_FOLDED_RE = re.compile(r"\b(?:simdi|su\s*an|suan|now|hala|halen|an\s+itibariyle)\b")
_RUNNING_Q_FOLDED_RE = re.compile(r"\bcalis(?:iyo|iyor)\w*\s+m[iu]\b|\bkac\s+(?:is|job)\w*\s+calis")
_ACTIVE_BLOCK_FOLDED_RE = re.compile(
    r"\b(?:hata\w*|fail\w*|abend\w*|basarisiz\w*|neden|nicin|why|dun\w*|bugun|gece|hafta\w*|ay|gun\w*|son\s+\d+|"
    r"sunucu\w*|agent\w*|host\w*|engine|pwp|nerede\w*|rapor\w*|onceki|ne\s+zaman)\b")
_YESNO_TAIL_FOLDED_RE = re.compile(r"\bm[iu]\s*\??\s*$|\bm[iu]\s*\?")


def classify_question(message: str) -> str:
    """yesno | count | list | why | infra | lastrun | prevrun | active | default"""
    from app.services.automic.tr_grammar import fold_re, fold_tr
    f = fold_tr(message)
    # "Şimdi/şu an çalışıyor mu" — yazım hatası ve ASCII fark etmez; aktif iş soruları şablondan (LLM yok)
    if (_ACTIVE_FOLDED_RE.search(f) and (_NOW_FOLDED_RE.search(f) or _RUNNING_Q_FOLDED_RE.search(f))
            and not _ACTIVE_BLOCK_FOLDED_RE.search(f)):
        return "active"
    prof = _classify_exact(message)
    if prof != "default":
        return prof
    # Katlanmış (ASCII) ikinci geçiş — yalnız ilk geçiş "default" ise
    for name, rx in (("why", _WHY_RE), ("prevrun", _PREVRUN_RE)):
        if fold_re(rx).search(f):
            return name
    if fold_re(_INFRA_RE).search(f) and not fold_re(_LIST_RE).search(f):
        return "infra"
    if (fold_re(_YESNO_RE).search(f) or _YESNO_TAIL_FOLDED_RE.search(f)) and not fold_re(_LIST_RE).search(f):
        return "yesno"
    if fold_re(_LIST_RE).search(f):
        return "list"
    if fold_re(_COUNT_RE).search(f):
        return "count"
    return "default"


def _classify_exact(message: str) -> str:
    m = message or ""
    if _WHY_RE.search(m):
        return "why"
    if _PREVRUN_RE.search(m):
        return "prevrun"
    if _LASTRUN_RE.search(m) and re.search(
            r"\b(?:JOBS|JOBP|JOBF|JOBG|VARA|SCRI|SCRP|EVNT|FILE|CALE|SYNC|HOST|XCOM)\.[A-Z0-9_.]+", m, re.I):
        return "lastrun"
    if _INFRA_RE.search(m) and not _LIST_RE.search(m):
        return "infra"
    if _YESNO_RE.search(m) and not _LIST_RE.search(m):
        return "yesno"
    if _LIST_RE.search(m):
        return "list"
    if _COUNT_RE.search(m):
        return "count"
    return "default"


def filter_components(profile: str, components: List[Dict[str, Any]],
                      structured: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Profil dışı / gereksiz bileşenleri çıkar; 10+ satır tabloları varsayılan kapalı."""
    if not components:
        return []
    # "veri yok" — başka döneme ait tablo/grafik gösterme
    no_data = False
    windows: Set[str] = set()
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict):
            continue
        if res.get("data_status") == "NO_DATA_IN_RANGE" or res.get("data_available") is False:
            no_data = True
        if res.get("from") and res.get("to"):
            windows.add(f"{res['from']}|{res['to']}")
    out: List[Dict[str, Any]] = []
    notes_seen: Set[str] = set()
    for c in components:
        t = c.get("type")
        if no_data and t in ("table", "chart", "kpi_row", "workflow_tree"):
            # Yalnız notice bırak
            continue
        if t == "notice":
            key = (c.get("text") or "")[:80]
            # return_code_note / veri kaynağı notu — oturumda bir kez (burada cevap başına)
            if key in notes_seen:
                continue
            notes_seen.add(key)
            out.append(c)
            continue
        if profile == "yesno":
            # Evet/hayır: tablo yok (tek job "Hata veren job'lar" dahil)
            if t == "table" or t == "chart":
                continue
            out.append(c)
        elif profile == "count":
            if t == "chart":
                continue
            if t == "table":
                c = {**c, "collapsed": True}
            out.append(c)
        elif profile == "list":
            # Job özeti açık; çalışma listesi kapalı
            if t == "table":
                title = (c.get("title") or "").lower()
                rows_n = int(c.get("total") or len(c.get("rows") or []))
                if "job" in title or "nesne" in title or c.get("columns") and any(
                        col.get("key") == "failed_count" for col in (c.get("columns") or [])):
                    c = {**c, "collapsed": False}
                    if rows_n > 10:
                        c = {**c, "rows": (c.get("rows") or [])[:10], "total": rows_n}
                else:
                    c = {**c, "collapsed": True}
            out.append(c)
        elif profile == "infra":
            if t in ("chart",):
                continue
            if t == "table":
                rows_n = int(c.get("total") or len(c.get("rows") or []))
                if rows_n > 10:
                    c = {**c, "collapsed": True, "rows": (c.get("rows") or [])[:10]}
            out.append(c)
        elif profile == "why":
            # Neden: 7c iskeleti metinde; bileşenler sade
            if t == "chart":
                continue
            if t == "table":
                c = {**c, "collapsed": True}
            out.append(c)
        else:
            if t == "table":
                rows_n = int(c.get("total") or len(c.get("rows") or []))
                if rows_n > 10:
                    c = {**c, "collapsed": True}
            out.append(c)
    return out[:12]


def unexpected_component_detail(profile: str, components: List[Dict[str, Any]]) -> str:
    """Kalite kuralı için: beklenmeyen bileşen varsa açıklama."""
    types = [c.get("type") for c in components]
    if profile == "yesno" and "chart" in types:
        return "yesno profilinde chart"
    if profile == "yesno" and any(
            c.get("type") == "table" and not c.get("collapsed") for c in components):
        return "yesno profilinde açık tablo"
    if profile == "infra" and "chart" in types:
        return "infra profilinde chart"
    return ""
