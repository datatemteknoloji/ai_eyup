"""Mimari GUIDE snapshot — sır sızdırmaz, sayılar/örnekler döner."""
from app.services.architecture_guide import _names, _safe_count


def test_names_limit_and_skip_empty():
    class Row:
        def __init__(self, name=None, hostname=None):
            self.name = name
            self.hostname = hostname

    rows = [Row("alpha"), Row(None, "beta.local"), Row("gamma")]
    assert _names(rows, limit=3) == ["alpha", "beta.local", "gamma"]
    assert _names([Row(""), Row(None)], limit=3) == []


def test_safe_count_swallows_errors():
    assert _safe_count(lambda: 4) == 4
    assert _safe_count(lambda: None) == 0
    assert _safe_count(lambda: 1 / 0) == 0
