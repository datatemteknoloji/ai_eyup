"""Linux kapasite raporu — günlük seri eşlemesi ve tahmin bloğu."""
from collections import namedtuple

from app.services import report_analytics as ra
from app.services.platform_report_engine import daily_metric_series

Row = namedtuple("Row", "server_id metric_name day avg_val")


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _StubSession:
    """SQL çalıştırmayan minimal Session — sorgu sonucu sabit."""

    def __init__(self, rows, raise_exc=None):
        self.rows = rows
        self.raise_exc = raise_exc
        self.calls = 0

    def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return _StubResult(self.rows)


def test_series_grouped_by_server_and_metric():
    rows = [
        Row(1, "memory_usage_percent", "d1", 50.0),
        Row(1, "memory_usage_percent", "d2", 51.0),
        Row(2, "disk_root_usage_percent", "d1", 70.0),
    ]
    series = daily_metric_series(_StubSession(rows), [1, 2], ["memory_usage_percent"])

    assert series[(1, "memory_usage_percent")] == [50.0, 51.0]
    assert series[(2, "disk_root_usage_percent")] == [70.0]


def test_no_servers_means_no_query():
    stub = _StubSession([])
    assert daily_metric_series(stub, [], ["memory_usage_percent"]) == {}
    assert stub.calls == 0


def test_metric_table_error_is_not_fatal():
    stub = _StubSession([], raise_exc=RuntimeError("relation metric_data does not exist"))
    assert daily_metric_series(stub, [1], ["memory_usage_percent"]) == {}


def test_forecast_only_for_servers_with_history():
    growing = [60 + 0.4 * i for i in range(30)]
    fc_growing = ra.build_threshold_forecast(72.0, growing)
    fc_empty = ra.build_threshold_forecast(72.0, [])

    assert fc_growing["days_to_threshold"] is not None
    assert fc_growing["trend_confidence"] in ("low", "medium", "high")
    assert fc_empty["days_to_threshold"] is None
    assert fc_empty["trend_confidence"] == "none"
