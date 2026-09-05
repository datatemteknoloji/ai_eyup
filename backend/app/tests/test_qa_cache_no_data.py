"""
"Veri yok" cevabı önbelleğe girmemeli ve girmişse HIT sayılmamalı.

Üretimde gözlenen döngü: model bir turda araç sonucunu yorumlamayı atlayıp
"canlı sorguda kayıt dönmedi" dedi, cevap cache'lendi ve araç yüzeyi
düzeltildikten sonra bile kullanıcı TTL boyunca aynı yanlış cümleyi gördü.
"""
import pytest

from app.services import qa_cache


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, ex=None):
        self.store[k] = v

    def setnx(self, k, v):
        self.store.setdefault(k, v)

    def expire(self, k, ttl):
        return True

    def incr(self, k):
        self.store[k] = int(self.store.get(k) or 0) + 1
        return self.store[k]

    def delete(self, *keys):
        n = 0
        for k in keys:
            n += 1 if self.store.pop(k, None) is not None else 0
        return n

    def ttl(self, k):
        return 3600

    def scan_iter(self, pattern):
        return iter(list(self.store))


@pytest.fixture()
def fake_redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(qa_cache, "_get_redis", lambda: r)
    return r


def test_invalidate_question_removes_entry(fake_redis):
    q = "vCenter sağlık durumu nedir?"
    qa_cache.set_cached_answer(q, {"answer": "iyi"}, "m")
    assert qa_cache.get_cached_answer(q, "m") is not None
    assert qa_cache.invalidate_question(q, "m") is True
    assert qa_cache.get_cached_answer(q, "m") is None


def test_invalidate_question_is_model_scoped(fake_redis):
    q = "kaç VM var?"
    qa_cache.set_cached_answer(q, {"answer": "17"}, "a")
    qa_cache.set_cached_answer(q, {"answer": "17"}, "b")
    qa_cache.invalidate_question(q, "a")
    assert qa_cache.get_cached_answer(q, "a") is None
    assert qa_cache.get_cached_answer(q, "b") is not None


def test_invalidate_question_without_question_is_noop(fake_redis):
    assert qa_cache.invalidate_question("", "m") is False
