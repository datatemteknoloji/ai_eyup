"""UTC timeutil — metrik TZ kayması önleme."""
from datetime import datetime, timezone

from app.core.timeutil import ensure_utc, from_unix, to_iso, utc_now


def test_from_unix_is_aware_utc():
    d = from_unix(1_700_000_000)
    assert d.tzinfo is not None
    assert d.utcoffset().total_seconds() == 0


def test_ensure_utc_naive_assumes_utc():
    naive = datetime(2026, 10, 8, 12, 0, 0)
    d = ensure_utc(naive)
    assert d.tzinfo == timezone.utc
    assert d.hour == 12


def test_to_iso_ends_with_z():
    s = to_iso(datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc))
    assert s.endswith("Z")
    assert "+03" not in s


def test_utc_now_aware():
    assert utc_now().tzinfo is not None
