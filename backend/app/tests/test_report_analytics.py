"""report_analytics unit tests."""
from app.services.report_analytics import (
    compute_trend_from_series,
    project_cpu,
    project_storage_memory,
    days_to_threshold,
    percentile,
)


def test_cpu_negative_trend_does_not_go_to_zero():
    trend = compute_trend_from_series([30, 25, 20, 15, 12, 10, 9, 9.5], min_samples=5)
    pt = project_cpu(current_pct=9.5, p95_pct=12.0, trend=trend, horizon_days=90)
    assert pt.value_pct > 0
    assert pt.method in ("mean_revert_floor", "p95_stable", "conservative_growth")


def test_storage_decline_floors_at_current():
    trend = compute_trend_from_series([50, 48, 45, 40, 35], min_samples=3)
    assert trend.daily_slope < 0
    pt = project_storage_memory(20.0, trend, 365, floor_pct=20.0)
    assert pt.value_pct >= 20.0


def test_storage_growth_capped_at_100():
    trend = compute_trend_from_series([10, 15, 20, 25, 30, 35], min_samples=3)
    pt = project_storage_memory(50.0, trend, 365)
    assert pt.value_pct <= 100.0


def test_days_to_threshold_negative_slope_returns_none():
    assert days_to_threshold(50.0, -0.5, confidence="medium") is None


def test_days_to_threshold_already_above():
    assert days_to_threshold(85.0, 0.1) == 0


def test_percentile():
    assert percentile([1, 2, 3, 4, 100], 95) >= 4


def test_insufficient_samples_stable():
    trend = compute_trend_from_series([9.5], min_samples=14)
    assert trend.confidence == "none"
    pt = project_storage_memory(9.5, trend, 90)
    assert pt.value_pct == 9.5
    assert pt.confidence == "none"
