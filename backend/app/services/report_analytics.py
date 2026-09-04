"""
Altyapı raporları — ortak istatistik ve tahmin yardımcıları.

Naif OLS % extrapolasyonu yerine:
- Disk/Memory: mutlak GB trend + medyan taban
- CPU: ortalama trend extrapolasyonu yok; p95 tabanlı stabil projeksiyon
- Kalite kapısı: yetersiz örnek / düşük güven → tahmin yok veya mevcut seviye
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class TrendResult:
    daily_slope: float
    confidence: str  # high | medium | low | none
    sample_count: int
    r_squared: Optional[float] = None


@dataclass
class ForecastPoint:
    value_pct: float
    confidence: str
    method: str
    note: Optional[str] = None


def _clamp_pct(v: float) -> float:
    return round(max(0.0, min(100.0, float(v))), 1)


def linear_regression_slope(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, Optional[float]]:
    """Basit OLS: slope ve R². xs eşit aralıklı zaman (gün) olabilir."""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0, None
    x = list(xs[:n])
    y = list(ys[:n])
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, y))
    den = sum((xi - x_mean) ** 2 for xi in x)
    if den == 0:
        return 0.0, None
    slope = num / den
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    if ss_tot == 0:
        return slope, 1.0 if abs(slope) < 1e-9 else 0.0
    y_hat = [y_mean + slope * (xi - x_mean) for xi in x]
    ss_res = sum((yi - fh) ** 2 for yi, fh in zip(y, y_hat))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, round(r2, 4)


def compute_trend_from_series(
    values: Sequence[Optional[float]],
    *,
    min_samples: int = 14,
) -> TrendResult:
    """Zaman serisi (en eski → en yeni) üzerinden günlük eğim (% veya GB)."""
    clean = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if len(clean) < min_samples:
        return TrendResult(daily_slope=0.0, confidence="none", sample_count=len(clean))

    # Günlük aggregate varsayımı: her nokta ~1 gün
    xs = list(range(len(clean)))
    slope, r2 = linear_regression_slope(xs, clean)
    # n nokta → günlük değişim (n-1 gün aralığı normalize)
    daily = slope  # zaten per-index; index = gün

    if r2 is None:
        conf = "low"
    elif r2 >= 0.5 and len(clean) >= 30:
        conf = "high"
    elif r2 >= 0.2 and len(clean) >= min_samples:
        conf = "medium"
    else:
        conf = "low"

    return TrendResult(daily_slope=daily, confidence=conf, sample_count=len(clean), r_squared=r2)


def days_to_threshold(
    current_pct: Optional[float],
    daily_growth: float,
    threshold: float = 80.0,
    *,
    confidence: str = "medium",
) -> Optional[int]:
    """Pozitif trend ile eşiğe kalan gün. Zaten geçildiyse 0; düşüş/stabil → None."""
    if current_pct is None:
        return None
    if current_pct >= threshold:
        return 0
    if confidence == "none" or confidence == "low":
        return None
    if daily_growth <= 0.001:
        return None
    return int((threshold - current_pct) / daily_growth)


def project_storage_memory(
    current_pct: float,
    trend: TrendResult,
    horizon_days: int,
    *,
    floor_pct: Optional[float] = None,
) -> ForecastPoint:
    """Disk/Memory: trend + medyan taban; negatif extrapolasyon yok."""
    floor = floor_pct if floor_pct is not None else current_pct
    if trend.confidence == "none":
        return ForecastPoint(
            value_pct=_clamp_pct(current_pct),
            confidence="none",
            method="stable",
            note="Yetersiz metrik geçmişi — mevcut seviye gösterildi",
        )
    raw = current_pct + trend.daily_slope * horizon_days
    if trend.daily_slope < 0:
        # Düşüş trendi: mevcut seviyenin altına inme (CPU gibi 0'a gitme)
        val = max(floor, raw)
        method = "stable_decline"
        note = "Düşüş trendi — taban mevcut seviye"
    else:
        val = raw
        method = "linear_growth"
        note = None
    return ForecastPoint(
        value_pct=_clamp_pct(val),
        confidence=trend.confidence,
        method=method,
        note=note,
    )


def project_cpu(
    current_pct: float,
    p95_pct: Optional[float],
    trend: TrendResult,
    horizon_days: int,
) -> ForecastPoint:
    """CPU oynak — ortalama lineer extrapolasyon yapmıyoruz."""
    base = p95_pct if p95_pct is not None else current_pct
    floor = max(current_pct, base * 0.85)

    if trend.confidence in ("none", "low") or abs(trend.daily_slope) < 0.01:
        return ForecastPoint(
            value_pct=_clamp_pct(base),
            confidence=trend.confidence if trend.confidence != "none" else "low",
            method="p95_stable",
            note="CPU için ortalama trend extrapolasyonu uygulanmadı (p95/mevcut taban)",
        )

    if trend.daily_slope > 0:
        val = min(100.0, base + trend.daily_slope * horizon_days * 0.5)
        return ForecastPoint(
            value_pct=_clamp_pct(val),
            confidence=trend.confidence,
            method="conservative_growth",
            note="CPU büyüme tahmini muhafazakâr (eğimin %50'si)",
        )

    # Negatif trend: 0'a inme — tabanda kal
    return ForecastPoint(
        value_pct=_clamp_pct(floor),
        confidence=trend.confidence,
        method="mean_revert_floor",
        note="CPU düşüş trendi — %0 extrapolasyonu yok",
    )


def aggregate_host_metrics_series(
    rows: Sequence[Any],
    *,
    value_key: str,
) -> List[Optional[float]]:
    """SQL satırlarından günlük ortalama seri (timestamp DESC → ASC)."""
    if not rows:
        return []
    # rows: objects with .timestamp and attribute value_key
    by_day: Dict[str, List[float]] = {}
    for r in rows:
        ts = getattr(r, "timestamp", None)
        val = getattr(r, value_key, None)
        if ts is None or val is None:
            continue
        day = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        by_day.setdefault(day, []).append(float(val))
    days = sorted(by_day.keys())
    return [sum(by_day[d]) / len(by_day[d]) for d in days]


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def build_forecast_payload(
    host: str,
    current: Dict[str, float],
    *,
    cpu_trend: TrendResult,
    mem_trend: TrendResult,
    ds_trend: TrendResult,
    cpu_p95: Optional[float] = None,
) -> Dict[str, Any]:
    """Tek host için 3/6/12 ay tahmin paketi."""
    horizons = {"forecast_3m": 90, "forecast_6m": 180, "forecast_12m": 365}
    out: Dict[str, Any] = {
        "host": host,
        "current": current,
        "daily_growth": {
            "cpu_pct_per_day": round(cpu_trend.daily_slope, 4),
            "mem_pct_per_day": round(mem_trend.daily_slope, 4),
            "ds_pct_per_day": round(ds_trend.daily_slope, 4),
        },
        "trend_confidence": {
            "cpu": cpu_trend.confidence,
            "memory": mem_trend.confidence,
            "storage": ds_trend.confidence,
        },
        "methodology": (
            "Disk/Memory: günlük trend + düşüşte taban; "
            "CPU: p95 tabanlı, %0 extrapolasyonu yok"
        ),
    }
    for key, days in horizons.items():
        cpu_f = project_cpu(current["cpu_pct"], cpu_p95, cpu_trend, days)
        mem_f = project_storage_memory(current["mem_pct"], mem_trend, days)
        ds_f = project_storage_memory(current["ds_pct"], ds_trend, days)
        out[key] = {
            "cpu_pct": cpu_f.value_pct,
            "mem_pct": mem_f.value_pct,
            "ds_pct": ds_f.value_pct,
            "cpu_method": cpu_f.method,
            "mem_method": mem_f.method,
            "ds_method": ds_f.method,
        }
    return out
