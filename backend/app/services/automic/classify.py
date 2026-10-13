"""Durum kodu → sınıf eşlemesi (ayardır; LLM'e bırakılmaz)."""
from __future__ import annotations
from app.services.automic.errors import note_error

from typing import Any, Dict, Optional

CLASSES = ("failed", "cancelled", "ok", "active", "other")


def _matches(code: int, rule: Dict[str, Any]) -> bool:
    if code in set(rule.get("exclude") or []):
        return False
    if code in set(rule.get("codes") or []):
        return True
    for rng in rule.get("ranges") or []:
        try:
            lo, hi = int(rng[0]), int(rng[1])
        except (TypeError, ValueError, IndexError) as _e:
            note_error("classify._matches", _e)
            continue
        if lo <= code <= hi:
            return True
    return False


def classify_status(code: Optional[int], status_classes: Dict[str, Any]) -> str:
    """Biten bir çalışmanın sınıfı. cancelled, failed'dan önce değerlendirilir."""
    if code is None:
        return "other"
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "other"
    for cls in ("cancelled", "failed", "ok"):
        rule = status_classes.get(cls)
        if isinstance(rule, dict) and _matches(c, rule):
            return cls
    return "other"


# Aktif durum grupları — DOĞRULANMADI: 24.4 TechDocs'ta "Task Status" /
# "System Return Codes of Executable Objects" sayfası bulunamadı (docs/official/24.4/STATUS_CODES_SEARCH.md).
# Gerçek veriyle (ör. UC_SGRP) kontrol edilecek. Listede olmayan kodlar "other" sayılır.
def _expand(spec: str) -> frozenset:
    out = set()
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return frozenset(out)


ACTIVE_STATUS_GROUPS: Dict[str, frozenset] = {
    # ACTIVE (çalışıyor)
    "running": _expand("1300,1310,1540-1542,1545,1546,1550,1551,1554,1557,1558,1565-1576,1578-1584,"
                       "1590-1593,1600,1701,1704,1705"),
    # WAITING (kuyrukta/ön koşul/agent bekliyor)
    "waiting": _expand("1301,1543,1552,1553,1556,1655,1665,1681-1700,1702,1703,1709-1711"),
    # BLOCKED (bloke — müdahale gerekir)
    "blocked": _expand("1544,1547,1560-1564,1898"),
}


def active_state(code: Optional[int]) -> str:
    """EH_Status → running | waiting | blocked | other | unknown (DOĞRULANMADI grup listeleri)."""
    if code is None:
        return "unknown"
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "unknown"
    for name, codes in ACTIVE_STATUS_GROUPS.items():
        if c in codes:
            return name
    return "other"


def failed_rule_text(status_classes: Dict[str, Any]) -> str:
    """Sistem prompt'u için insan-okur 'hatalı' tanımı."""
    rule = status_classes.get("failed") or {}
    parts = []
    for rng in rule.get("ranges") or []:
        if len(rng) == 2:
            lo, hi = rng
            parts.append("ANY_ABEND (1800–1899)" if (lo, hi) == (1800, 1899) else f"{lo}–{hi}")
    if rule.get("codes"):
        parts.append(", ".join(str(c) for c in rule["codes"]))
    txt = " + ".join(parts) or "tanımsız"
    if rule.get("exclude"):
        txt += f" (hariç: {', '.join(str(c) for c in rule['exclude'])})"
    return txt
