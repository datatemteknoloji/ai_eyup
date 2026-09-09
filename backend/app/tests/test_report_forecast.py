"""Kapasite tahmini — dayanıklı eğim (Theil–Sen) ve belirsizlik aralığı."""
from app.services.report_analytics import (
    build_threshold_forecast,
    compute_trend_from_series,
    days_to_threshold_range,
    linear_regression_slope,
    pct_per_day_to_gb,
    theil_sen_slope,
)


def test_theil_sen_matches_clean_linear_trend():
    ys = [10 + 0.5 * i for i in range(20)]
    slope, low, high = theil_sen_slope(list(range(20)), ys)
    assert abs(slope - 0.5) < 1e-9
    assert low is not None and high is not None
    assert abs(high - low) < 1e-9  # gürültü yoksa aralık daralır


def test_theil_sen_resists_single_spike():
    ys = [50 + 0.1 * i for i in range(30)]
    ys[15] = 99.0  # tek seferlik yedek işi / ölçüm hatası
    xs = list(range(30))

    ols_slope, _ = linear_regression_slope(xs, ys)
    robust_slope, _, _ = theil_sen_slope(xs, ys)

    assert abs(robust_slope - 0.1) < abs(ols_slope - 0.1)


def test_trend_uses_robust_slope_and_exposes_range():
    series = [40 + 0.2 * i for i in range(30)]
    series[7] = 95.0
    trend = compute_trend_from_series(series)

    assert abs(trend.daily_slope - 0.2) < 0.1
    assert trend.slope_low is not None
    assert trend.slope_high is not None
    assert trend.method == "theil_sen"


def test_days_to_threshold_range_brackets_typical():
    # gürültülü ama artan disk kullanımı
    series = [50 + 0.3 * i + (1.5 if i % 3 == 0 else -1.0) for i in range(30)]
    trend = compute_trend_from_series(series)
    rng = days_to_threshold_range(60.0, trend, 80.0)

    assert rng is not None
    assert rng["fastest"] <= rng["typical"]
    assert rng["slowest"] is None or rng["slowest"] >= rng["typical"]


def test_range_none_when_no_growth():
    trend = compute_trend_from_series([50.0] * 30)
    assert days_to_threshold_range(50.0, trend, 80.0) is None


def test_range_zero_when_threshold_already_passed():
    trend = compute_trend_from_series([80 + 0.1 * i for i in range(30)])
    rng = days_to_threshold_range(92.0, trend, 80.0)
    assert rng == {"typical": 0, "fastest": 0, "slowest": 0}


def test_threshold_forecast_no_data_is_not_no_growth():
    fc = build_threshold_forecast(70.0, [70.0, 71.0])
    assert fc["trend_confidence"] == "none"
    assert fc["days_to_threshold"] is None
    assert fc["days_to_threshold_range"] is None
    assert fc["sample_days"] == 2


def test_threshold_forecast_growth_with_gb():
    series = [60 + 0.5 * i for i in range(30)]
    fc = build_threshold_forecast(74.0, series, total_gb=1000.0)

    assert fc["current_pct"] == 74.0
    assert fc["daily_growth_pct"] > 0
    assert fc["daily_growth_gb"] == 5.0
    assert fc["days_to_threshold"] == 12
    assert fc["days_to_threshold_range"]["typical"] == 12
    assert fc["threshold_pct"] == 80.0


def test_pct_per_day_to_gb_handles_missing_capacity():
    assert pct_per_day_to_gb(0.5, None) is None
    assert pct_per_day_to_gb(0.5, 0) is None
    assert pct_per_day_to_gb(1.0, 500.0) == 5.0
