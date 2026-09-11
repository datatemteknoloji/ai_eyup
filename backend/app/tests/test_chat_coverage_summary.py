from app.services.chat_coverage import coverage_miss_summary


class _FakeQuery:
    def __init__(self, row=None):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDb:
    def query(self, *a, **k):
        return _FakeQuery(None)


def test_coverage_summary_empty_store():
    out = coverage_miss_summary(_FakeDb())
    assert out["ok"] is True
    assert out["count"] == 0
    assert out["misses"] == []
