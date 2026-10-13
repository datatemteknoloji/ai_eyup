"""Donanım bulgusu: sensör ayrıntısı (ad, tip, durum, değer) kanıta ve Detay alanına yansır.

Regresyon: toplayıcı sensörü `state` anahtarıyla yazar; bulgu üretimi `status`/`health` okuduğu için
`evidence.sensors` boş, `detail` "—" kalıyordu.
"""
from app.services.virt_health_checks import _hardware_host, sensor_label

PSU = {"name": "Power Supply 2", "type": "power", "unit": "Watts", "state": "red", "reading": 3.0}


def _run(inv_sensors, status="red", bad=1, sensor_days=None):
    h = {"name": "esx1", "ref": "host-1", "state": {}, "config": {"vendor": "HP", "model": "DL380", "bios": "P67"}}
    hw = {"metrics": {"esx1": {"sensor_bad_count": bad, "overall_status": status}},
          "inventory": {"esx1": {"health_sensors": inv_sensors, "config_issues": []}},
          "events": {}, "sensor_days": sensor_days or {"esx1": {"observed_days": 30, "bad_days": 30}}}
    return {d.check_id: d for d in _hardware_host("vmware", h, "C1", hw)}


def test_sensor_label_uses_only_available_fields():
    assert sensor_label(PSU) == "Power Supply 2 · power · red · 3 Watts"
    assert sensor_label({"name": "Fan 1", "state": "yellow"}) == "Fan 1 · yellow"
    assert sensor_label({"name": "Temp", "state": "red", "reading": 91.5}) == "Temp · red · 91.5"


def test_state_key_is_read_and_detail_filled():
    d = _run([PSU])["hw.host.sensor_alarm"]
    assert d.result == "fail"
    assert d.evidence["sensors"] == [PSU]
    assert d.detail == "Power Supply 2 · power · red · 3 Watts"


def test_legacy_status_key_still_read():
    d = _run([{"name": "Fan 3", "status": "yellow"}])["hw.host.sensor_alarm"]
    assert d.evidence["sensors"] and d.detail.startswith("Fan 3")


def test_green_and_unknown_sensors_filtered():
    d = _run([{"name": "A", "state": "green"}, {"name": "B", "state": "unknown"}], bad=0, status="green")
    assert d["hw.host.sensor_alarm"].result == "pass"
    assert d["hw.host.sensor_alarm"].evidence["sensors"] == []


def test_overall_status_detail_names_the_sensor():
    d = _run([PSU])["hw.host.overall_status"]
    assert d.result == "fail" and d.severity == "high"
    assert d.detail == "red; Power Supply 2 · power · red · 3 Watts"
    assert d.evidence["bad_sensors"] == [PSU]


def test_overall_status_without_sensors_keeps_plain_detail():
    d = _run([], status="red", bad=0)["hw.host.overall_status"]
    assert d.detail == "red" and "bad_sensors" not in d.evidence


def test_repeat_exposes_current_sensors_only():
    d = _run([PSU])["hw.host.sensor_repeat"]
    assert d.result == "fail" and d.evidence["current_sensors"] == [PSU]
