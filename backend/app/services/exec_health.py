"""Yönetici alanı notu.

Ekip raporları ve dashboard `health_score.py` formülünü kullanır (ceza popülasyona bölünür).
Bu fonksiyon yalnız yönetici paketindedir. Varlık skoru ortalamasıdır.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

WEIGHT_CRITICAL = 30
WEIGHT_WARNING = 12

FORMULA_TR = (
    "Her varlıkta ceza = min(100, 30×kritik + 12×uyarı). Varlık skoru = 100 − ceza. "
    "Alan notu varlık skorlarının ortalamasıdır. Bilgi cezaya girmez. "
    "Alanda en az bir varlıkta açık kritik varsa alan en az Dikkat olur. "
    "Bu durum altyapı sağlığını gösterir, ekip performansını değil. "
    "Ekip raporlarındaki not farklı formülle hesaplanır ve bu nottan ayrışabilir."
)

Counts = Tuple[int, int]


def asset_score(critical: int, warning: int) -> int:
    penalty = min(100, int(critical) * WEIGHT_CRITICAL + int(warning) * WEIGHT_WARNING)
    return 100 - penalty


def average_score(assets: Sequence[Counts]) -> Optional[int]:
    if not assets:
        return None
    total = sum(asset_score(c, w) for c, w in assets)
    return int(round(total / len(assets)))


def status_label(score: Optional[int], *, monitored: bool, open_critical: bool) -> str:
    if not monitored:
        return "İzleme yok"
    if score is None:
        return "Ölçülemedi"
    if score >= 75:
        label = "Normal"
    elif score >= 55:
        label = "Dikkat"
    else:
        label = "Kritik"
    if open_critical and label == "Normal":
        return "Dikkat"
    return label


def score_area(assets: Sequence[Counts], *, monitored: bool, open_critical: bool = False) -> dict:
    score = average_score(assets) if monitored else None
    critical_assets = sum(1 for c, _w in assets if c > 0)
    if critical_assets and not open_critical:
        open_critical = True
    return {
        "score": score,
        "status": status_label(score, monitored=monitored, open_critical=open_critical),
        "asset_count": len(assets) if monitored else 0,
        "critical_assets": critical_assets,
        "formula": FORMULA_TR,
    }
