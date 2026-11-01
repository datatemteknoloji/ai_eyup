"""Host ölçümü tazelik süzgeci — yeniden adlandırılan host'un hayaleti raporlara girmez."""
from datetime import datetime, timedelta, timezone

from app.services.host_freshness import fresh_hosts, split_stale_hosts

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _row(hv, name, ago_h, ref=None):
    return {"hypervisor_id": hv, "host_name": name, "host_ref": ref, "timestamp": NOW - timedelta(hours=ago_h)}


def test_renamed_host_old_name_dropped_by_age():
    rows = [_row(7, "192.168.1.112", 113), _row(7, "dtkvm01", 0.1), _row(7, "dtkvm02", 0.2)]
    fresh, stale = split_stale_hosts(rows)
    assert [r["host_name"] for r in fresh] == ["dtkvm01", "dtkvm02"]
    assert [r["host_name"] for r in stale] == ["192.168.1.112"]


def test_same_host_ref_under_two_names_keeps_newest_even_if_both_fresh():
    rows = [_row(7, "192.168.1.112", 2, "ref-a"), _row(7, "dtkvm01", 0.1, "ref-a")]
    fresh, stale = split_stale_hosts(rows)
    assert [r["host_name"] for r in fresh] == ["dtkvm01"]
    assert [r["host_name"] for r in stale] == ["192.168.1.112"]


def test_whole_hypervisor_outage_keeps_hosts_visible():
    # Toplama günlerce durduysa hepsi eski; göreli ölçüt hiçbirini düşürmez.
    rows = [_row(2, "esx1", 200), _row(2, "esx2", 201)]
    assert len(fresh_hosts(rows)) == 2


def test_hypervisors_are_independent():
    rows = [_row(1, "a", 500), _row(2, "b", 0.1)]
    # Her hypervisor kendi en yenisine göre değerlendirilir: a tek başına kendi referansı.
    assert len(fresh_hosts(rows)) == 2


def test_missing_timestamp_not_dropped():
    rows = [{"hypervisor_id": 1, "host_name": "x", "timestamp": None}, _row(1, "y", 0)]
    assert len(fresh_hosts(rows)) == 2
