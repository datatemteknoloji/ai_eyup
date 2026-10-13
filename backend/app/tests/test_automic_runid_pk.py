"""Zaman→RunID eşleme, PK sorguları, temkinli mod, satır sınırı."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.automic.defaults import DEFAULT_SETTINGS
from app.services.automic.source.base import SourceError
from app.services.automic.source.fake import FakeSource
from app.services.automic.source.sql_guard import assert_read_only
from app.services.automic.source import templates
from app.services.automic.source.base import EXECUTION_FIELDS
from app.tests.test_automic_official_schema import _full_mapping


def test_cautious_defaults_small_chunks():
    g = DEFAULT_SETTINGS["source_guard"]
    assert g["cautious_mode"] is True
    assert g["max_rows_per_slice"] <= 500
    assert g["backfill_chunk_rows"] <= 500
    assert g["slow_query_sec"] == 10


def test_ended_executions_requires_runid_bounds():
    src = FakeSource(1, {"fake_clients": [100]}, None, {"source_guard": DEFAULT_SETTINGS["source_guard"]}, {})
    now = datetime.now(timezone.utc)
    with pytest.raises(SourceError) as ei:
        src.fetch_ended_executions([100], now - timedelta(hours=1), now, limit=10)
    assert ei.value.code == "runid_bounds_required"
    hi = src.latest_run_id(100)
    recs = src.fetch_ended_executions(
        [100], now - timedelta(hours=2), now, limit=50, id_min=hi - 5000, id_max=hi + 1)
    assert isinstance(recs, list)


def test_render_always_fetch_first():
    prof, mapping = _full_mapping()
    sql = templates.render(
        prof, "active_executions", schema="UC4", table_map=mapping["active"],
        fields=list(EXECUTION_FIELDS)[:5], clients_bind=":c0",
    )
    assert "FETCH FIRST" in sql.upper()


def test_runid_map_bounds(monkeypatch):
    from app.services.automic import runid_map

    db = MagicMock()
    db.execute.return_value.first.return_value = (1000, 2000)
    b = runid_map.bounds_for_time_range(
        db, 1, datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc), slack_hours=24)
    assert b == (1000, 2001)


def test_slow_query_disables_template(monkeypatch):
    from app.services.automic.source import oracle

    src = oracle.OracleSource(
        1, {}, None,
        {"source_guard": {"slow_query_sec": 0.0, "default_fetch_limit": 10, "arraysize": 10}},
        {"mapping": {}, "schema": "UC4"},
    )
    # connect/query stub
    monkeypatch.setattr(src, "_connect", lambda: SimpleNamespace(
        call_timeout=0, cursor=lambda: _Cur([(1,)]), thin=True))
    monkeypatch.setattr(src, "_ensure_read_only", lambda c: None)
    with pytest.raises(SourceError) as ei:
        src._query("SELECT 1 FROM dual", query_name="ended_executions")
    assert ei.value.code == "slow_query"
    assert "ended_executions" in src._disabled_templates()


class _Cur:
    def __init__(self, rows):
        self._rows = rows
        self.arraysize = 1
        self.prefetchrows = 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self._rows

    def fetchmany(self, n):
        return self._rows[:n]


def test_explain_risky_detect():
    from app.services.automic.explain_plans import _RISKY

    assert _RISKY.search("TABLE ACCESS FULL")
    assert _RISKY.search("INDEX FAST FULL SCAN")
    assert not _RISKY.search("INDEX RANGE SCAN")


def test_children_requires_runid_bounds():
    src = FakeSource(1, {"fake_clients": [100]}, None, {}, {})
    with pytest.raises(SourceError) as ei:
        src.fetch_children(100, 1, limit=10)
    assert ei.value.code == "runid_bounds_required"


def test_bounds_for_children_end_and_running():
    from app.services.automic import runid_map

    db = MagicMock()
    # bitiş+pay penceresi
    db.execute.return_value.first.return_value = (5000, 9000)
    end = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    b = runid_map.bounds_for_children(db, 1, 5000, end, slack_hours=24)
    assert b == (5000, 9001)
    # hâlâ çalışıyor → global max
    db.execute.return_value.first.return_value = (100, 99999)
    b2 = runid_map.bounds_for_children(db, 1, 5000, None, slack_hours=24)
    assert b2 == (5000, 100000)
