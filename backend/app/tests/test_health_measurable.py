"""Boş popülasyon A değildir; olayı olmayan izlenen filo A kalır."""
from types import SimpleNamespace

from app.api.ops_center import _calc_health_score, _worst_platform_health


def _ev(severity: str):
    return SimpleNamespace(severity=severity)


def test_empty_population_is_not_a_score():
    h = _calc_health_score([], 0)
    assert h["measurable"] is False
    assert h["score"] is None
    assert h["grade"] is None


def test_no_monitoring_is_not_measurable():
    h = _calc_health_score([], 4, monitored=False)
    assert h["measurable"] is False
    assert h["score"] is None


def test_monitored_fleet_with_zero_events_stays_a():
    h = _calc_health_score([], 12)
    assert h["measurable"] is True
    assert h["score"] == 100
    assert h["grade"] == "A"


def test_overall_is_the_worst_platform_not_a_weighted_mean():
    # 1000 sunuculuk 100, tek platformluk 40'ı örtemez.
    overall = _worst_platform_health([100, None, 40])
    assert overall["health_score"] == 40
    assert overall["grade"] == "D"
    assert overall["rule"] == "worst_platform"


def test_unmeasured_platform_does_not_set_the_floor():
    overall = _worst_platform_health([None, 90])
    assert overall["health_score"] == 90
    assert overall["grade"] == "A"


def test_all_unmeasured_has_no_letter_grade():
    overall = _worst_platform_health([None, None])
    assert overall["health_score"] is None
    assert overall["grade"] is None
