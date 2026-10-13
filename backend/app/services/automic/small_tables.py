"""Küçük referans tablo istisnası — tam okuma için tek açık liste.

HOST, MQSRV, OHG, OHGF gibi düşük satır sayılı tablolar PK/indeks parçası olmadan
tam okunabilir. Eşik aşılırsa istisna o tablo için kapatılır ve kritik uyarı üretilir.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# Kaynak AE tablo adları (büyük harf). Plan kontrolü ve collector aynı listeyi kullanır.
SMALL_REF_TABLES: FrozenSet[str] = frozenset({
    "HOST",
    "MQSRV",
    "OHG",
    "OHGF",
})

# Mantıksal şablon adı → kaynak tablo
SMALL_REF_TEMPLATES: Dict[str, str] = {
    "hosts_all": "HOST",
    "mqsrv_all": "MQSRV",
    "ohg_all": "OHG",
    "ohgf_all": "OHGF",
    "host_names_by_ids": "OH",  # OH PK IN — küçük değil ama agents join yardımcı
}

DEFAULT_ROW_THRESHOLD = 10_000


def row_threshold(settings: Optional[Dict[str, Any]]) -> int:
    g = (settings or {}).get("source_guard") or {}
    try:
        return max(100, int(g.get("small_table_row_threshold") or DEFAULT_ROW_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_ROW_THRESHOLD


def is_small_ref_table(table: str) -> bool:
    return (table or "").upper() in SMALL_REF_TABLES


def check_row_count(table: str, count: int, settings: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """(allowed, warning). allowed=False → istisna bu tur için kapalı."""
    t = (table or "").upper()
    if t not in SMALL_REF_TABLES:
        return False, f"{t} küçük referans listesinde değil"
    thr = row_threshold(settings)
    if count > thr:
        return False, (
            f"Kritik: {t} satır sayısı ({count}) eşik ({thr}) üstünde; "
            f"küçük tablo istisnası bu senkron için devre dışı."
        )
    return True, None


def risk_report_entries(settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Plan / risk raporuna eklenecek maddeler."""
    thr = row_threshold(settings)
    return [
        {
            "table": t,
            "access": "full_read_exception",
            "threshold": thr,
            "note": "Küçük referans tablosu — satır sayısı eşiği aşılırsa istisna kapanır",
        }
        for t in sorted(SMALL_REF_TABLES)
    ]
