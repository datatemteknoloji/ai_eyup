"""Dilim C: tekrarlayan sensör alarmı (30 günde ≥3 ayrı gün)."""
from app.services.virt_health_checks import _hardware_host
from app.services.findings.registry import CHECKS


def _host():
    return {"name": "esx1", "ref": "host-1", "state": {}, "config": {}}


def _run(sensor_days):
    hw = {"metrics": {"esx1": {"sensor_bad_count": 0, "overall_status": "green"}}, "inventory": {}, "events": {},
          "sensor_days": sensor_days}
    out = _hardware_host("vmware", _host(), "C1", hw)
    return next(d for d in out if d.check_id == "hw.host.sensor_repeat")


def test_check_registered():
    assert "hw.host.sensor_repeat" in CHECKS
    assert CHECKS["hw.host.sensor_repeat"].category == "hardware"


def test_three_bad_days_fails():
    d = _run({"esx1": {"observed_days": 30, "bad_days": 3}})
    assert d.result == "fail" and d.evidence["bad_days"] == 3


def test_two_bad_days_passes():
    assert _run({"esx1": {"observed_days": 30, "bad_days": 2}}).result == "pass"


def test_no_history_is_not_measurable():
    assert _run({}).result == "not_measurable"
    assert _run({"esx1": {"observed_days": 0, "bad_days": 0}}).result == "not_measurable"
