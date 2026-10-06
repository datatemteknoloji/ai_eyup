"""Events/incidents sorun anahtarı: aynı sunucu + aynı tip tek satır."""
from types import SimpleNamespace

from app.services.event_grouping import event_problem_key, group_events, unique_events, unique_incidents
from app.services.incident_auto import AUTO_SEVERITIES


def _ev(**kwargs):
    defaults = dict(
        id=1, server_id=10, event_type="metric_anomaly", severity="critical",
        source="prometheus", title="CPU high", raw_data={"metric": "cpu"},
        last_seen=None, created_at=None, occurrence_count=1,
        resolved=False, is_acknowledged=False, is_known=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_metric_same_server_same_metric_same_key():
    a = _ev(id=1, title="CPU %91")
    b = _ev(id=2, title="CPU %95")
    assert event_problem_key(a) == event_problem_key(b)


def test_log_entries_different_titles_differ():
    a = _ev(event_type="log_entry", source="log_collector", title="sshd: Failed password", raw_data={})
    b = _ev(event_type="log_entry", source="log_collector", title="kernel: OOM killer", raw_data={})
    assert event_problem_key(a) != event_problem_key(b)


def test_group_events_collapses_and_sums_occurrence():
    rows = [
        _ev(id=1, occurrence_count=3, title="CPU %90"),
        _ev(id=2, occurrence_count=2, title="CPU %99"),
    ]
    groups = group_events(rows)
    assert len(groups) == 1
    assert groups[0]["occurrence_count"] == 5
    assert set(groups[0]["event_ids"]) == {1, 2}


def test_unique_events_one_representative():
    rows = [_ev(id=1), _ev(id=2)]
    assert len(unique_events(rows)) == 1


def test_unique_incidents_same_problem_key():
    a = SimpleNamespace(problem_key="k1", source="auto_cpu", affected_servers=[1], status="open",
                        updated_at=None, created_at=None)
    b = SimpleNamespace(problem_key="k1", source="auto_cpu", affected_servers=[1], status="investigating",
                        updated_at=None, created_at=None)
    assert len(unique_incidents([a, b])) == 1


def test_incident_auto_has_no_time_window():
    import app.services.incident_auto as m
    assert not hasattr(m, "DEDUP_WINDOW_HOURS")
    assert "critical" in AUTO_SEVERITIES
