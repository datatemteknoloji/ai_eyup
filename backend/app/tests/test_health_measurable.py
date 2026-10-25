"""Boş popülasyon A değildir; olayı olmayan izlenen filo A kalır."""
from types import SimpleNamespace

from app.api.ops_center import _calc_health_score, _weighted_health


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


def test_unmeasured_platform_is_left_out_of_the_average():
    # Boş linux (None) ortalamayı 100'e çekmez; yalnız ölçülen 70 kalır.
    overall = _weighted_health([(None, 1), (70, 4)])
    assert overall["health_score"] == 70
    assert overall["measurable"] is True


def test_all_unmeasured_has_no_letter_grade():
    overall = _weighted_health([(None, 0), (None, 3)])
    assert overall["health_score"] is None
    assert overall["grade"] is None
