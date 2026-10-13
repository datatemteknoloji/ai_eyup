"""Canlı okuma politikası — merkezi kapı, risk filtresi, allow_live, bütçe, aktif snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.automic.defaults import DEFAULT_SETTINGS, effective_settings, validate_settings
from app.services.automic import live_read
from app.services.automic.source.sql_guard import assert_read_only


def _sys(mode="off", **extra_guard):
    g = {**DEFAULT_SETTINGS["source_guard"], "live_read_mode": mode, **extra_guard}
    return SimpleNamespace(
        id=42, name="T", settings={"source_guard": g, "collection": {"windows": [], "timezone": "UTC"}},
        clients=[100], capability={"features": {}}, source_type="fake", connection={},
    )


def _db_as_of():
    db = MagicMock()
    db.get.return_value = SimpleNamespace(
        active_snapshot_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        last_success_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        last_run_at=None,
    )
    return db


# ── defaults / prompt placeholders ────────────────────────────────────────

def test_default_live_read_off():
    assert DEFAULT_SETTINGS["source_guard"]["live_read_mode"] == "off"
    assert validate_settings({}) == []
    assert any("live_read_mode" in e for e in validate_settings({"source_guard": {"live_read_mode": "bogus"}}))


def test_prompt_has_live_read_and_last_collection_placeholders():
    from app.services.automic.prompt import SYSTEM_PROMPT_TEMPLATE
    assert "{{LIVE_READ_MODE}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{LAST_COLLECTION_TIME}}" in SYSTEM_PROMPT_TEMPLATE
    assert "Canlı okuma kapalı" in SYSTEM_PROMPT_TEMPLATE or "canlı okuma kapalı" in SYSTEM_PROMPT_TEMPLATE


# ── a) mod off → kaynak yok ───────────────────────────────────────────────

def test_a_mode_off_no_source_call(monkeypatch):
    sys = _sys("off")
    db = _db_as_of()
    built = []

    def boom(*a, **k):
        built.append(1)
        raise AssertionError("build_source çağrılmamalı")

    monkeypatch.setattr(live_read, "build_source", boom)
    for fn in ("fetch_execution", "fetch_children", "fetch_report", "fetch_object_script", "list_reports"):
        res = live_read.call(db, sys, fn, 100, 1, allow_live=None)
        assert res.ok is False and res.data_source == "denied"
        assert res.decision.reason == "policy_off"
    assert built == []


# ── b) windows_only ───────────────────────────────────────────────────────

def test_b_windows_only_outside_and_inside(monkeypatch):
    sys = _sys("windows_only")
    sys.settings["collection"] = {
        "windows": [{"days": [0, 1, 2, 3, 4, 5, 6], "from": "02:00", "to": "03:00"}],
        "timezone": "UTC", "blackout": [],
    }
    db = _db_as_of()

    with patch("app.services.automic.live_read.collection_allowed", return_value=False):
        d = live_read.evaluate(sys, "fetch_execution", allow_live=None, db=db)
        assert d.allowed is False and d.reason == "outside_window"

    with patch("app.services.automic.live_read.collection_allowed", return_value=True):
        d = live_read.evaluate(sys, "fetch_execution", allow_live=None, db=db)
        assert d.allowed is True and d.reason == "ok"


# ── c) allow_live=false ───────────────────────────────────────────────────

def test_c_allow_live_false():
    d = live_read.evaluate(_sys("always"), "fetch_execution", allow_live=False)
    assert d.allowed is False and d.reason == "allow_live_false"


# ── d) allow_live=true + mod off → deny + açıklayıcı mesaj ─────────────────

def test_d_allow_live_true_but_mode_off_explains():
    db = _db_as_of()
    d = live_read.evaluate(_sys("off"), "fetch_execution", allow_live=True, db=db)
    assert d.allowed is False and d.reason == "policy_off"
    assert "kapalı" in d.message.lower() or "off" in d.message.lower()
    assert d.as_of  # son toplama bilgisi


# ── e) orta/yüksek risk + always → yine hayır ─────────────────────────────

def test_e_medium_risk_blocked_even_always():
    for fn in ("fetch_object_header", "fetch_active_executions"):
        d = live_read.evaluate(_sys("always"), fn, allow_live=True)
        assert d.allowed is False and d.reason == "template_risk"


# ── f) bütçe aşımı ────────────────────────────────────────────────────────

def test_f_budget_exceed_falls_back_message(monkeypatch):
    monkeypatch.setattr(live_read, "get_redis", lambda: None)
    with live_read._local_lock:
        live_read._local_budget.clear()
    sys = _sys("always", live_budget_per_min=1, live_budget_per_user_per_min=1)
    sys.id = 99001
    db = _db_as_of()
    ok1, _ = live_read._budget_check(sys.id, 7, 1, 1, consume=True)
    assert ok1 is True
    d = live_read.evaluate(sys, "fetch_execution", allow_live=None, user_id=7, db=db)
    assert d.allowed is False
    assert d.reason in ("budget_global", "budget_user")
    assert "bütçe" in d.message.lower() or "modül" in d.message.lower()


# ── g) aktif işler mod off → snapshot + as_of ─────────────────────────────

def test_g_active_executions_module_snapshot_as_of():
    from app.services.automic import queries as q
    from app.models.automic import AutomicActiveExecution, AutomicCollectorState

    db = MagicMock()
    snap = datetime(2026, 3, 1, 10, 30, tzinfo=timezone.utc)
    row = SimpleNamespace(
        client=100, run_id=1, parent_run_id=None, object_name="JOBS.X", object_type="JOBS",
        status_code=1550, activation_time=None, start_time=snap, agent="A",
        snapshot_at=snap, top_run_id=None, user="u", queue="Q", platform="UNIX",
        folder="/", run_time_sec=10, ert_sec=60, ert_end_time=None, ert_calc=2,
        mrt_sec=None, srt_sec=None, signal=0,
    )
    qmock = MagicMock()
    qmock.filter.return_value = qmock
    qmock.order_by.return_value = qmock
    qmock.limit.return_value = qmock
    qmock.all.return_value = [row]
    qmock.count.return_value = 1
    db.query.return_value = qmock
    db.execute.return_value.all.return_value = []
    st = SimpleNamespace(active_snapshot_at=snap, last_success_at=snap)
    db.get.return_value = st

    sys = _sys("off")
    with patch.object(q, "_clients", return_value=[100]):
        res = q.active_executions(db, sys, limit=10)
    assert res["ok"] is True
    assert res["data_source"] == "module_db"
    assert res["as_of"]
    assert "toplama" in (res.get("freshness_note") or "").lower() or "görüntü" in (res.get("freshness_note") or "").lower()


def test_live_allowed_templates_match_risk_doc():
    assert "execution_by_id" in live_read.LIVE_ALLOWED_TEMPLATES
    assert "object_header_by_name" not in live_read.LIVE_ALLOWED_TEMPLATES
    assert "active_executions" not in live_read.LIVE_ALLOWED_TEMPLATES


def test_effective_settings_has_budgets():
    e = effective_settings({})
    assert e["source_guard"]["live_budget_per_min"] == 10
    assert e["source_guard"]["script_sync_enabled"] is True


# ── explain plan aracı: guard + V$SQL (EXPLAIN yok) ───────────────────────

def test_explain_tool_uses_vsql_not_explain_plan_for():
    from app.services.automic import explain_plans as ep
    import inspect
    src = inspect.getsource(ep._plan_via_vsql)
    assert "EXPLAIN PLAN" not in src
    assert "DBMS_XPLAN" not in src
    assert "v$sql_plan" in src.lower()
    assert "assert_read_only" in src


def test_explain_probe_sqls_pass_guard():
    assert_read_only(
        "SELECT prev_sql_id, prev_child_number FROM v$session "
        "WHERE sid = SYS_CONTEXT('USERENV', 'SID') FETCH FIRST 1 ROWS ONLY"
    )
    assert_read_only(
        "SELECT id, operation, options, object_name, cost, cardinality "
        "FROM v$sql_plan WHERE sql_id = :sql_id ORDER BY id FETCH FIRST 200 ROWS ONLY"
    )


def test_explain_risky_detect():
    from app.services.automic.explain_plans import _RISKY, _SAMPLE
    assert _RISKY.search("TABLE ACCESS FULL")
    assert _RISKY.search("INDEX FAST FULL SCAN")
    assert not _RISKY.search("INDEX RANGE SCAN")
    # INDEX FULL SCAN (MIN/MAX) beklenen iyi plan — riskli sayılmaz
    assert not _RISKY.search("INDEX FULL SCAN (MIN/MAX)")
    assert "min_run_id" in _SAMPLE and _SAMPLE["min_run_id"]["binds"] == {}
