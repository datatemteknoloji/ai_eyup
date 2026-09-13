"""
Altyapı raporları — ortak istatistik ve tahmin yardımcıları.

Naif OLS % extrapolasyonu yerine:
- Eğim: Theil–Sen (ikili eğimlerin medyanı) — tek bir spike trendi bozmaz
- Belirsizlik: ikili eğim dağılımının %25–%75 aralığı → "35–60 gün" gibi aralık
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
    # İkili eğim dağılımının alt/üst çeyreği — tahmin aralığı için
    slope_low: Optional[float] = None
    slope_high: Optional[float] = None
    method: str = "theil_sen"


@dataclass
class ForecastPoint:
    value_pct: float
    confidence: str
    method: str
    note: Optional[str] = None
    raw_value_pct: Optional[float] = None  # floor öncesi ham extrapolasyon
    floored: bool = False


def _clamp_pct(v: float) -> float:
    return round(max(0.0, min(100.0, float(v))), 1)


def horizon_uncertainty_label(rng: Optional[Dict[str, Any]]) -> str:
    """Eşiğe kalan gün aralığının genişliği — trend R² 'güven'inden ayrı.

    narrow | moderate | wide | none | already
    """
    if not rng:
        return "none"
    if rng.get("typical") == 0:
        return "already"
    fastest, slowest = rng.get("fastest"), rng.get("slowest")
    if fastest is None:
        return "none"
    if slowest is None:
        return "wide"
    span = int(slowest) - int(fastest)
    if span >= 365 or (fastest > 0 and slowest / max(fastest, 1) >= 5):
        return "wide"
    if span >= 90:
        return "moderate"
    return "narrow"


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


def pairwise_slopes(xs: Sequence[float], ys: Sequence[float]) -> List[float]:
    """Tüm nokta çiftleri için (y2-y1)/(x2-x1). Theil–Sen'in temeli."""
    n = min(len(xs), len(ys))
    out: List[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = float(xs[j]) - float(xs[i])
            if dx == 0:
                continue
            out.append((float(ys[j]) - float(ys[i])) / dx)
    return out


def theil_sen_slope(
    xs: Sequence[float],
    ys: Sequence[float],
) -> Tuple[float, Optional[float], Optional[float]]:
    """Dayanıklı eğim: (medyan, %25, %75).

    OLS tek bir sıçramadan (VM taşındı, yedek işi) ciddi etkilenir; ikili
    eğimlerin medyanı bu tür aykırı değerlere karşı dayanıklıdır. %25/%75
    çeyrekleri tahmini "aralık" olarak sunmayı sağlar.
    """
    slopes = pairwise_slopes(xs, ys)
    if not slopes:
        return 0.0, None, None
    med = percentile(slopes, 50) or 0.0
    return float(med), percentile(slopes, 25), percentile(slopes, 75)


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
    # Güven seviyesi için OLS R² (uyum iyiliği), eğim için Theil–Sen
    _ols_slope, r2 = linear_regression_slope(xs, clean)
    daily, slope_low, slope_high = theil_sen_slope(xs, clean)

    if r2 is None:
        conf = "low"
    elif r2 >= 0.5 and len(clean) >= 30:
        conf = "high"
    elif r2 >= 0.2 and len(clean) >= min_samples:
        conf = "medium"
    else:
        conf = "low"

    return TrendResult(
        daily_slope=daily,
        confidence=conf,
        sample_count=len(clean),
        r_squared=r2,
        slope_low=slope_low,
        slope_high=slope_high,
    )


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


def days_to_threshold_range(
    current_pct: Optional[float],
    trend: TrendResult,
    threshold: float = 80.0,
) -> Optional[Dict[str, Any]]:
    """Eşiğe kalan gün ARALIĞI: {"typical", "fastest", "slowest"}.

    Tek bir "43 gün" yerine eğim belirsizliğini yansıtır. `slowest` None ise
    "bu senaryoda eşiğe hiç ulaşılmıyor" demektir (yavaş uçta trend düz/negatif).
    """
    typical = days_to_threshold(
        current_pct, trend.daily_slope, threshold, confidence=trend.confidence,
    )
    if typical is None:
        return None
    out: Dict[str, Any] = {"typical": typical, "fastest": typical, "slowest": typical}
    if typical == 0:
        return out
    # Hızlı uç = en dik eğim, yavaş uç = en yatay eğim
    fastest = days_to_threshold(
        current_pct, trend.slope_high if trend.slope_high is not None else trend.daily_slope,
        threshold, confidence=trend.confidence,
    )
    slowest = days_to_threshold(
        current_pct, trend.slope_low if trend.slope_low is not None else trend.daily_slope,
        threshold, confidence=trend.confidence,
    )
    out["fastest"] = min(x for x in (fastest, typical) if x is not None)
    out["slowest"] = slowest if slowest is None else max(slowest, typical)
    return out


def pct_per_day_to_gb(daily_slope_pct: float, total_gb: Optional[float]) -> Optional[float]:
    """Yüzde/gün → GB/gün (kapasite biliniyorsa). Rapor metni için."""
    if not total_gb:
        return None
    try:
        return round(float(daily_slope_pct) * float(total_gb) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def project_storage_memory(
    current_pct: float,
    trend: TrendResult,
    horizon_days: int,
    *,
    floor_pct: Optional[float] = None,
) -> ForecastPoint:
    """Disk/Memory projeksiyonu.

    Floor yalnızca istatistiksel güven düşükse (none/low) uygulanır —
    'değer kritik' tek başına floor tetiklemez. medium/high + düşüşte ham
    extrapolasyon gösterilir (alt sınır %0).
    """
    _ = floor_pct  # API uyumu; floor artık current_pct ile low-conf'ta yapılır
    raw = _clamp_pct(current_pct + trend.daily_slope * horizon_days)

    if trend.confidence == "none":
        return ForecastPoint(
            value_pct=_clamp_pct(current_pct),
            confidence="none",
            method="stable",
            note="Yetersiz metrik geçmişi — mevcut seviye gösterildi",
            raw_value_pct=raw,
            floored=True,
        )

    if trend.confidence == "low":
        # Düşük güven: extrapolasyona güvenme; ham değeri şeffaflık için tut
        return ForecastPoint(
            value_pct=_clamp_pct(current_pct),
            confidence="low",
            method="stable_low_conf",
            note=(
                "Düşük trend güveni — projeksiyon mevcut seviyede sabit "
                f"(ham {horizon_days}g: %{raw})"
            ),
            raw_value_pct=raw,
            floored=True,
        )

    # medium / high — ham trend (düşüş dahil)
    if trend.daily_slope < -0.001:
        return ForecastPoint(
            value_pct=raw,
            confidence=trend.confidence,
            method="linear_decline",
            note="Düşüş trendi — ham extrapolasyon (taban yok)",
            raw_value_pct=raw,
            floored=False,
        )
    if trend.daily_slope > 0.001:
        return ForecastPoint(
            value_pct=raw,
            confidence=trend.confidence,
            method="linear_growth",
            note=None,
            raw_value_pct=raw,
            floored=False,
        )
    return ForecastPoint(
        value_pct=_clamp_pct(current_pct),
        confidence=trend.confidence,
        method="stable",
        note="Anlamlı eğim yok — mevcut seviye",
        raw_value_pct=raw,
        floored=False,
    )


def project_cpu(
    current_pct: float,
    p95_pct: Optional[float],
    trend: TrendResult,
    horizon_days: int,
) -> ForecastPoint:
    """CPU oynak — ortalama lineer extrapolasyon yerine p95 + muhafazakâr eğim."""
    base = p95_pct if p95_pct is not None else current_pct
    floor = max(current_pct, base * 0.85)
    # Ham (kullanıcı kafadan current×slope sanmasın diye ayrı tutulur)
    raw_from_current = _clamp_pct(current_pct + trend.daily_slope * horizon_days)
    raw_conservative = _clamp_pct(base + trend.daily_slope * horizon_days * 0.5)

    if trend.confidence in ("none", "low") or abs(trend.daily_slope) < 0.01:
        return ForecastPoint(
            value_pct=_clamp_pct(base),
            confidence=trend.confidence if trend.confidence != "none" else "low",
            method="p95_stable",
            note=(
                "CPU: p95/mevcut taban (düşük güven veya zayıf eğim) — "
                f"ham current×eğim {horizon_days}g: %{raw_from_current}"
            ),
            raw_value_pct=raw_from_current,
            floored=True,
        )

    if trend.daily_slope > 0:
        return ForecastPoint(
            value_pct=raw_conservative,
            confidence=trend.confidence,
            method="conservative_growth",
            note=(
                f"CPU: p95 taban (%{_clamp_pct(base)}) + eğimin %50'si "
                f"(ham current×eğim: %{raw_from_current})"
            ),
            raw_value_pct=raw_from_current,
            floored=False,
        )

    # Negatif + yeterli güven: mean-revert floor (CPU %0'a inmesin)
    return ForecastPoint(
        value_pct=_clamp_pct(floor),
        confidence=trend.confidence,
        method="mean_revert_floor",
        note=f"CPU düşüş — taban; ham current×eğim: %{raw_from_current}",
        raw_value_pct=raw_from_current,
        floored=True,
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


def build_threshold_forecast(
    current_pct: Optional[float],
    series: Sequence[Optional[float]],
    *,
    threshold: float = 80.0,
    min_samples: int = 7,
    total_gb: Optional[float] = None,
) -> Dict[str, Any]:
    """Tek metrik için kompakt tahmin paketi (Linux/Windows kapasite raporları).

    Günlük seri yeterli değilse `confidence="none"` ve tahmin üretilmez —
    "veri yok" ile "büyüme yok" karıştırılmaz.
    """
    trend = compute_trend_from_series(series, min_samples=min_samples)
    out: Dict[str, Any] = {
        "current_pct": None if current_pct is None else _clamp_pct(current_pct),
        "daily_growth_pct": round(trend.daily_slope, 4),
        "daily_growth_gb": pct_per_day_to_gb(trend.daily_slope, total_gb),
        "trend_confidence": trend.confidence,
        "sample_days": trend.sample_count,
        "days_to_threshold": None,
        "days_to_threshold_range": None,
        "threshold_pct": threshold,
    }
    if trend.confidence == "none" or current_pct is None:
        return out
    out["days_to_threshold"] = days_to_threshold(
        current_pct, trend.daily_slope, threshold, confidence=trend.confidence,
    )
    out["days_to_threshold_range"] = days_to_threshold_range(current_pct, trend, threshold)
    return out


def _projection_kind(method: str) -> str:
    """UI için: growth | decline | stable | floor."""
    if method in ("linear_growth", "conservative_growth"):
        return "growth"
    if method == "linear_decline":
        return "decline"
    if method in ("stable_decline", "mean_revert_floor", "stable_low_conf"):
        return "floor"
    return "stable"


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
    mem_range = days_to_threshold_range(current.get("mem_pct"), mem_trend)
    ds_range = days_to_threshold_range(current.get("ds_pct"), ds_trend)
    out: Dict[str, Any] = {
        "host": host,
        "current": current,
        "critical_now": {
            "cpu": (current.get("cpu_pct") or 0) >= 80,
            "memory": (current.get("mem_pct") or 0) >= 80,
            "storage": (current.get("ds_pct") or 0) >= 80,
        },
        "daily_growth": {
            "cpu_pct_per_day": round(cpu_trend.daily_slope, 4),
            "mem_pct_per_day": round(mem_trend.daily_slope, 4),
            "ds_pct_per_day": round(ds_trend.daily_slope, 4),
        },
        "trend_fit": {
            "cpu": cpu_trend.confidence,
            "memory": mem_trend.confidence,
            "storage": ds_trend.confidence,
        },
        # Geriye uyumluluk
        "trend_confidence": {
            "cpu": cpu_trend.confidence,
            "memory": mem_trend.confidence,
            "storage": ds_trend.confidence,
        },
        "horizon_uncertainty": {
            "memory": horizon_uncertainty_label(mem_range),
            "storage": horizon_uncertainty_label(ds_range),
        },
        "days_to_80pct": {
            "memory": mem_range,
            "storage": ds_range,
        },
        "cpu_projection_note": (
            "CPU projeksiyonu p95 taban + eğimin %50'si kullanır; "
            "tablodaki 'Şimdi' anlık değerle kafadan çarpım yapmayın."
        ),
        "methodology": (
            "Eğim: Theil–Sen; trend uyumu R² tabanlı; eşiğe gün aralığı eğim "
            "IQR'sinden (tarih belirsizliği ayrı). Floor yalnızca düşük/yok "
            "güvende. Disk/Memory medium+ düşüşte ham extrapolasyon. "
            "CPU: p95 + muhafazakâr (%50) eğim."
        ),
    }
    metric_meta: Dict[str, Any] = {}
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
            "cpu_raw_pct": cpu_f.raw_value_pct,
            "mem_raw_pct": mem_f.raw_value_pct,
            "ds_raw_pct": ds_f.raw_value_pct,
        }
        if key == "forecast_12m":
            metric_meta = {
                "cpu": {
                    "method": cpu_f.method,
                    "kind": _projection_kind(cpu_f.method),
                    "note": cpu_f.note,
                    "confidence": cpu_f.confidence,
                    "fit": cpu_trend.confidence,
                    "raw_12m_pct": cpu_f.raw_value_pct,
                    "floored": cpu_f.floored,
                },
                "mem": {
                    "method": mem_f.method,
                    "kind": _projection_kind(mem_f.method),
                    "note": mem_f.note,
                    "confidence": mem_f.confidence,
                    "fit": mem_trend.confidence,
                    "horizon_uncertainty": horizon_uncertainty_label(mem_range),
                    "raw_12m_pct": mem_f.raw_value_pct,
                    "floored": mem_f.floored,
                },
                "ds": {
                    "method": ds_f.method,
                    "kind": _projection_kind(ds_f.method),
                    "note": ds_f.note,
                    "confidence": ds_f.confidence,
                    "fit": ds_trend.confidence,
                    "horizon_uncertainty": horizon_uncertainty_label(ds_range),
                    "raw_12m_pct": ds_f.raw_value_pct,
                    "floored": ds_f.floored,
                },
            }
    out["metric_projection"] = metric_meta
    out["narrative"] = narrate_forecast_host(out)
    return out


def _fit_tr(fit: str) -> str:
    return {"high": "yüksek", "medium": "orta", "low": "düşük", "none": "yetersiz"}.get(fit, fit)


def _unc_tr(u: str) -> str:
    return {
        "narrow": "dar",
        "moderate": "orta",
        "wide": "geniş",
        "already": "eşik aşılmış",
        "none": "hesaplanamadı",
    }.get(u, u)


def narrate_capacity_host(item: Dict[str, Any]) -> List[str]:
    """Kural-tabanlı kapasite host yorumu — yalnızca payload sayılarından."""
    lines: List[str] = []
    host = item.get("host", "Host")
    mem = item.get("memory") or {}
    stor = item.get("storage") or {}
    cpu = item.get("cpu") or {}

    mem_pct = mem.get("used_pct")
    ds_pct = stor.get("used_pct")
    cpu_pct = cpu.get("used_pct")

    # 1) Şu an kritik (projeksiyondan bağımsız)
    crit_bits = []
    if mem_pct is not None and mem_pct >= 90:
        crit_bits.append(f"Memory kritik (%{mem_pct})")
    elif mem_pct is not None and mem_pct >= 80:
        crit_bits.append(f"Memory yüksek (%{mem_pct})")
    if ds_pct is not None and ds_pct >= 90:
        crit_bits.append(f"Disk kritik (%{ds_pct})")
    elif ds_pct is not None and ds_pct >= 80:
        crit_bits.append(f"Disk yüksek (%{ds_pct})")
    if cpu_pct is not None and cpu_pct >= 80:
        crit_bits.append(f"CPU yüksek (%{cpu_pct})")
    if crit_bits:
        lines.append(f"{host}: şu an {' · '.join(crit_bits)} — mevcut durum acil izleme gerektirir.")
    else:
        lines.append(f"{host}: anlık kaynak kullanımı eşik altında (CPU %{cpu_pct}, Memory %{mem_pct}, Disk %{ds_pct}).")

    # 2) Trend / eşiğe gün — memory
    mem_days = mem.get("days_to_80pct")
    mem_rng = mem.get("days_to_80pct_range")
    mem_fit = mem.get("trend_confidence") or "none"
    mem_growth = mem.get("daily_growth_pct")
    if mem_pct is not None and mem_pct >= 80:
        lines.append(
            f"Memory zaten %80 üzerinde; eşiğe kalan süre 0. "
            f"Trend uyumu {_fit_tr(mem_fit)}"
            + (f", günlük eğim {mem_growth}%/gün." if mem_growth is not None else ".")
        )
    elif mem_days is not None and mem_rng:
        unc = horizon_uncertainty_label(mem_rng)
        fastest, slowest = mem_rng.get("fastest"), mem_rng.get("slowest")
        if slowest is None:
            span = f"en iyimser {fastest} gün (yavaş uçta eşiğe ulaşmıyor)"
        else:
            span = f"{fastest}–{slowest} gün"
        lines.append(
            f"Memory trend uyumu {_fit_tr(mem_fit)}; %80 için tahmini süre {span} "
            f"(tarih belirsizliği: {_unc_tr(unc)}). Kesin tarih yerine izlemeye devam edilmeli."
        )
    elif mem_growth is not None and mem_growth <= 0:
        lines.append(
            f"Memory yükselen trend yok (eğim {mem_growth}%/gün, uyum {_fit_tr(mem_fit)}) — "
            "eşiğe süre hesaplanmadı."
        )

    # 3) Disk
    ds_days = stor.get("days_to_80pct")
    ds_rng = stor.get("days_to_80pct_range")
    ds_fit = stor.get("trend_confidence") or "none"
    ds_growth = stor.get("daily_growth_pct")
    if ds_pct is not None and ds_pct >= 80:
        lines.append(f"Disk zaten %80 üzerinde (%{ds_pct}). Kapasite planlaması gözden geçirilmeli.")
    elif ds_days is not None and ds_rng:
        unc = horizon_uncertainty_label(ds_rng)
        fastest, slowest = ds_rng.get("fastest"), ds_rng.get("slowest")
        if slowest is None:
            span = f"en iyimser {fastest} gün"
        else:
            span = f"{fastest}–{slowest} gün"
        lines.append(
            f"Disk trend uyumu {_fit_tr(ds_fit)}; %80'e tahmini ulaşım {span} içinde "
            f"(tarih belirsizliği: {_unc_tr(unc)})."
        )
    elif ds_growth is not None:
        lines.append(
            f"Disk eğimi {ds_growth}%/gün (uyum {_fit_tr(ds_fit)}) — "
            "anlamlı eşiğe-süre üretilmedi."
        )

    lines.append("Bu metin kural tabanlıdır; yatırım tavsiyesi değil, kapasite planlaması için bilgilendirmedir.")
    return lines


def narrate_forecast_host(payload: Dict[str, Any]) -> List[str]:
    """Forecast host yorumu — floor sonrası durum + ham şeffaflık."""
    lines: List[str] = []
    host = payload.get("host", "Host")
    cur = payload.get("current") or {}
    meta = payload.get("metric_projection") or {}
    crit = payload.get("critical_now") or {}
    f12 = payload.get("forecast_12m") or {}

    if crit.get("memory"):
        lines.append(
            f"Memory şu an kritik seviyede (%{cur.get('mem_pct')}). "
            "Uzun vadeli projeksiyon bunu gölgelemez — mevcut durum önceliklidir."
        )
    if crit.get("storage"):
        lines.append(f"Disk şu an kritik/yüksek (%{cur.get('ds_pct')}).")

    for key, label in (("mem", "Memory"), ("ds", "Disk"), ("cpu", "CPU")):
        m = meta.get(key) or {}
        kind = m.get("kind")
        raw = m.get("raw_12m_pct")
        shown = f12.get(f"{key}_pct") if key != "cpu" else f12.get("cpu_pct")
        if key == "mem":
            shown = f12.get("mem_pct")
        elif key == "ds":
            shown = f12.get("ds_pct")
        fit = m.get("fit") or m.get("confidence")
        if kind == "floor" and raw is not None and shown is not None:
            lines.append(
                f"{label}: projeksiyon tabanda sabit (%{shown}); "
                f"ham 12ay %{raw} (düşük güven veya CPU koruması). Trend uyumu {_fit_tr(fit or '')}."
            )
        elif kind == "decline" and shown is not None:
            lines.append(
                f"{label}: düşüş trendi yansıtılıyor (12ay %{shown}). "
                f"Trend uyumu {_fit_tr(fit or '')}."
            )
        elif kind == "growth" and key == "cpu":
            lines.append(
                "CPU: p95 taban + eğimin %50'si ile muhafazakâr büyüme — "
                "anlık % × günlük eğim ile eşleşmez."
            )
        elif kind == "growth" and shown is not None:
            unc = m.get("horizon_uncertainty")
            extra = f" Tarih belirsizliği: {_unc_tr(unc)}." if unc else ""
            lines.append(
                f"{label}: büyüme projeksiyonu (12ay %{shown}), trend uyumu {_fit_tr(fit or '')}.{extra}"
            )

    ds_unc = (payload.get("horizon_uncertainty") or {}).get("storage")
    ds_rng = (payload.get("days_to_80pct") or {}).get("storage")
    if ds_unc == "wide" and ds_rng and ds_rng.get("typical") not in (None, 0):
        lines.append(
            f"Disk için trend uyumu iyi olsa bile eşiğe ulaşma aralığı geniş "
            f"({ds_rng.get('fastest')}–{ds_rng.get('slowest')} gün) — kesin tarih verilmemeli."
        )

    if not lines:
        lines.append(f"{host}: belirgin kritik durum veya güçlü trend sinyali yok.")
    return lines


def narrate_risk_report(data: Dict[str, Any]) -> List[str]:
    """Risk dashboard özeti — en kötü sinyale öncelik."""
    risks = data.get("risks") or {}
    lines: List[str] = []
    level = data.get("risk_level") or "Normal"
    score = data.get("risk_score")
    crit = data.get("critical_event_count") or 0
    warn = data.get("warning_event_count") or 0

    lines.append(
        f"Genel risk seviyesi: {level}"
        + (f" (skor {score}/100)." if score is not None else ".")
    )

    mem_h = risks.get("high_memory_hosts") or []
    cpu_h = risks.get("high_cpu_hosts") or []
    ds_h = risks.get("high_storage_hosts") or []
    if mem_h:
        worst = max(mem_h, key=lambda h: h.get("mem_pct") or 0)
        lines.append(
            f"En kritik kaynak baskısı: Memory — {worst.get('host')} %{worst.get('mem_pct')} "
            f"({len(mem_h)} host eşik üstü). Ortalamaya bakılmamalı."
        )
    if ds_h:
        worst = max(ds_h, key=lambda h: h.get("ds_pct") or 0)
        lines.append(
            f"Disk baskısı: {worst.get('host')} %{worst.get('ds_pct')} ({len(ds_h)} host)."
        )
    if cpu_h:
        worst = max(cpu_h, key=lambda h: h.get("cpu_pct") or 0)
        lines.append(
            f"CPU baskısı: {worst.get('host')} %{worst.get('cpu_pct')} ({len(cpu_h)} host)."
        )
    if crit:
        top = (risks.get("top_alarm_servers") or [{}])[0]
        if top.get("server"):
            lines.append(
                f"Son 7 günde {crit} kritik/hata olayı; en yoğun: {top.get('server')} "
                f"({top.get('events')} olay)."
            )
        else:
            lines.append(f"Son 7 günde {crit} kritik/hata ve {warn} uyarı olayı.")
    no_tools = risks.get("no_tools_vms") or []
    if no_tools:
        lines.append(
            f"{len(no_tools)} açık VM'de VMware Tools eksik/çalışmıyor — izlenebilirlik riski."
        )
    maint = risks.get("maintenance_hosts") or []
    if maint:
        lines.append(f"Bakım modunda host: {', '.join(maint)}.")

    if not mem_h and not cpu_h and not ds_h and not crit and not no_tools:
        lines.append("Eşik üstü host veya kritik olay kümesi yok — görünür risk düşük.")

    lines.append(
        "Yorum kural tabanlıdır; güvenlik açığı taraması değildir. "
        "Öncelik en kötü host/olaya verilmiştir."
    )
    return lines


def narrate_consolidation_report(data: Dict[str, Any]) -> List[str]:
    """Konsolidasyon yorumu — reclaim vs idle ayrımı."""
    lines: List[str] = []
    poff = data.get("powered_off_vms") or {}
    idle = data.get("idle_vms") or {}
    over = data.get("oversized_vms") or {}
    pot = data.get("consolidation_potential") or {}
    cov = data.get("usage_metrics_coverage") or {}

    lines.append(
        f"Kapalı VM: {poff.get('count', 0)} adet — geri kazanılabilir tahsis "
        f"{pot.get('reclaimable_vcpu', 0)} vCPU / {pot.get('reclaimable_ram_gb', 0)} GB RAM / "
        f"{pot.get('reclaimable_disk_gb', 0)} GB disk (kesin aday; silmeden önce doğrulayın)."
    )
    lines.append(
        f"Düşük kullanımlı (idle) açık VM: {idle.get('count', 0)} — inceleme adayı "
        f"{pot.get('idle_candidate_vcpu', 0)} vCPU / {pot.get('idle_candidate_ram_gb', 0)} GB RAM "
        "(otomatik silme önerisi değil)."
    )
    if over.get("count"):
        lines.append(
            f"Aşırı tahsis adayı (idle dışı): {over.get('count')} VM — "
            "usage veya allocation heuristic (basis alanına bakın)."
        )
    covered = cov.get("vms_with_7d_samples")
    total = cov.get("powered_on_vms")
    if covered is not None and total:
        lines.append(
            f"7 günlük kullanım metriği kapsamı: {covered}/{total} açık VM. "
            "Kapsam düşükse oversized/idle listeleri eksik kalabilir."
        )
    # En kötü idle örneği
    idle_vms = idle.get("vms") or []
    if idle_vms:
        worst = idle_vms[0]
        lines.append(
            f"Örnek idle: {worst.get('vm')} ({worst.get('cpu')} vCPU, 7g ort. CPU %{worst.get('avg_cpu_pct')})."
        )
    lines.append(
        "Yorum bilgilendirme amaçlıdır; rightsizing kararı iş etkisiyle birlikte gözden geçirilmelidir."
    )
    return lines
