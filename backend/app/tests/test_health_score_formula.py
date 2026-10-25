"""Yeni sağlık notu: tekilleştirme, ayrı ağırlık, popülasyon."""
from types import SimpleNamespace

from app.services.health_score import legacy_event_score, score_events


def _ev(severity, **kw):
    raw = kw.pop("raw_data", {})
    return SimpleNamespace(severity=severity, raw_data=raw, title=kw.get("title") or severity, **kw)


def test_same_asset_and_type_counts_once_at_worst_severity():
    events = [
        _ev("warning", server_id=7, event_type="cpu_high"),
        _ev("critical", server_id=7, event_type="cpu_high"),
        _ev("critical", server_id=7, event_type="cpu_high"),
    ]
    h = score_events(events, 1)
    assert h["event_count"] == 1
    assert h["score"] == 70


def test_critical_weighs_more_than_warning():
    warning = score_events([_ev("warning", server_id=1, event_type="disk")], 1)
    critical = score_events([_ev("critical", server_id=1, event_type="disk")], 1)
    assert warning["score"] == 88
    assert critical["score"] == 70
    assert critical["score"] < warning["score"]


def test_info_does_not_change_the_score():
    h = score_events([_ev("info", server_id=1, event_type="notice")], 4)
    assert h["score"] == 100


def test_population_normalizes_one_critical():
    one = score_events([_ev("critical", server_id=1, event_type="cpu_high")], 1)
    six = score_events([_ev("critical", server_id=1, event_type="cpu_high")], 6)
    assert six["score"] > one["score"]
    assert six["score"] == 95


def test_different_assets_both_count():
    events = [
        _ev("critical", server_id=1, event_type="cpu_high"),
        _ev("critical", server_id=2, event_type="cpu_high"),
    ]
    h = score_events(events, 2)
    assert h["event_count"] == 2
    assert h["score"] == 70


def test_legacy_formula_is_the_old_weight_sum():
    events = [_ev("critical"), _ev("warning")]
    assert legacy_event_score(events, 1) == 80
