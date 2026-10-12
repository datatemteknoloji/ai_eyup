"""Rapor / PDF "Yöntem notları" (Dilim T2).

Notlar elle yazılmaz: `method_registry` kaydından ÜRETİLİR (yöntem, kaynak, sınırlar). Böylece
rapordaki açıklama ile ekrandaki rozet/(i) aynı metni taşır ve kayıt değişince rapor da değişir.

Her rapor türü için hangi yöntem kimliklerinin geçerli olduğu burada tek yerde tutulur.
Eşlemesi olmayan rapor türü yine de `report.numbers` + `report.narrative` notlarını alır.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from app.services import method_registry as mr

# Tüm raporlar için ortak notlar (sayılar deterministik, özet cümleleri şablon).
_BASE: Tuple[str, ...] = ("report.numbers", "report.narrative")

# (kapsam, rapor_tipi) → ek yöntem kimlikleri. kapsam: virt | linux | windows | exadata | executive
_EXTRA: Dict[Tuple[str, str], Tuple[str, ...]] = {
    ("virt", "capacity"): ("report.capacity_trend",),
    ("virt", "forecast"): ("report.capacity_trend",),
    ("virt", "capacity_plan"): ("cap.cluster.n_plus_one",),
    ("linux", "capacity"): ("report.capacity_trend", "linux.metrics"),
    ("exadata", "capacity"): ("exa.health",),
    ("executive", "executive"): ("ops.health_score", "ops.platform_cards", "ops.issues",
                                 "linux.metrics", "win.metrics", "exa.health"),
}

# Kapsam bazında her rapora eklenen kaynak notu (rapor türüne özel değilse).
_SCOPE_SOURCE: Dict[str, Tuple[str, ...]] = {
    "linux": ("linux.metrics",),
    "windows": ("win.metrics",),
    "exadata": ("exa.health",),
}


def method_ids_for(scope: str, report_type: str) -> List[str]:
    out: List[str] = list(_BASE)
    for mid in _SCOPE_SOURCE.get(scope, ()) + _EXTRA.get((scope, report_type), ()):
        if mid not in out:
            out.append(mid)
    return out


def method_notes_markdown(scope: str, report_type: str, *, lang: str = "tr",
                          extra_ids: Optional[Iterable[str]] = None) -> str:
    """"## Yöntem notları" bölümü; kayıtsız kimlik sessizce atlanır (test kaydın tam olduğunu doğrular)."""
    en = lang == "en"
    ids = method_ids_for(scope, report_type)
    for mid in extra_ids or ():
        if mid not in ids:
            ids.append(mid)
    lines: List[str] = ["", "## Method notes" if en else "## Yöntem notları", ""]
    lbl_src, lbl_lim = ("Source", "Limits") if en else ("Kaynak", "Sınırlar")
    any_ai = False
    for mid in ids:
        m = mr.resolve(mid)
        if not m:
            continue
        cls = mr.CLASS_INFO[m.cls]["label_en" if en else "label_tr"]
        method = m.method_en if en else m.method_tr
        source = m.source_en if en else m.source_tr
        limits = m.limits_en if en else m.limits_tr
        lines.append(f"- **{cls}** — {method} _{lbl_src}:_ {source} _{lbl_lim}:_ {limits}")
        any_ai = any_ai or m.uses_ai
    if any_ai:
        lines.append(f"- {mr.AI_NOTE_EN if en else mr.AI_NOTE_TR}")
    return "\n".join(lines) + "\n"
