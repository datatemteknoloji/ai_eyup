"""Günlük örnek: aynı günün tick'leri bir gün sayılır. Uzun pencere günlük özetten okunur."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.daily_history import reads_daily_summary
from app.services.report_analytics import aggregate_host_metrics_series, compute_trend_from_series


def test_same_day_ticks_are_one_sample_and_not_confident():
    start = datetime(2026, 10, 25, 0, 0)
    rows = [
        SimpleNamespace(timestamp=start + timedelta(hours=i), cpu_usage_pct=40 + i)
        for i in range(14)
    ]
    series = aggregate_host_metrics_series(rows, value_key="cpu_usage_pct")
    assert len(series) == 1
    trend = compute_trend_from_series(series)
    assert trend.sample_count == 1
    assert trend.confidence == "none"


def test_fourteen_distinct_days_are_fourteen_samples():
    start = datetime(2026, 10, 1)
    rows = [
        SimpleNamespace(timestamp=start + timedelta(days=i, hours=3), cpu_usage_pct=50.0)
        for i in range(14)
    ]
    series = aggregate_host_metrics_series(rows, value_key="cpu_usage_pct")
    assert len(series) == 14


def test_window_longer_than_raw_retention_uses_daily_summary():
    assert reads_daily_summary("metric_data", 31) is True
    assert reads_daily_summary("metric_data", 30) is False
    assert reads_daily_summary("hypervisor_host_metrics", 91) is True
    assert reads_daily_summary("hypervisor_host_metrics", 90) is False
    assert reads_daily_summary("virt_datastore_metrics", 181) is True
    assert reads_daily_summary("ocp_resource_metrics", 14) is False
