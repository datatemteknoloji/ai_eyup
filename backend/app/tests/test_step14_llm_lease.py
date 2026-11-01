"""Adım 14 — LLM semafor lease'i: kısa TTL + canlı sahip yenilemesi (restart'ta ölü sahip slotu uzun tutmaz)."""
from __future__ import annotations

import time
import uuid

import pytest

from app.services import llm_scheduler as sched


def _real_redis():
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        r.ping()
        return r
    except Exception:
        return None


@pytest.fixture()
def keys(monkeypatch):
    r = _real_redis()
    if r is None:
        pytest.skip("Redis yok")
    sfx = uuid.uuid4().hex[:8]
    monkeypatch.setattr(sched, "_ACTIVE_KEY", f"test:llm:lease14:active:{sfx}")
    monkeypatch.setattr(sched, "_WAIT_KEY", f"test:llm:lease14:wait:{sfx}")
    yield r
    r.delete(sched._ACTIVE_KEY, sched._WAIT_KEY)
    with sched._held_lock:
        sched._held_tokens.clear()


def test_ttl_is_short_and_renewal_configured():
    assert sched._LEASE_TTL_SEC <= 120                       # eskiden 900
    assert sched._LEASE_RENEW_EVERY_SEC * 3 <= sched._LEASE_TTL_SEC   # 2 kaçırılan yenilemeye tolerans


def test_dead_holder_frees_slot_after_ttl(keys, monkeypatch):
    monkeypatch.setattr(sched, "_LEASE_TTL_SEC", 1)
    assert sched._try_acquire("dead", sched.CHAT, 1) is True
    sched._untrack("dead")                                   # süreç öldü: yenileme yok
    assert sched._try_acquire("t2", sched.CHAT, 1) is False
    time.sleep(1.2)
    assert sched._try_acquire("t2", sched.CHAT, 1) is True   # ölü sahip slotu bıraktı


def test_live_holder_is_renewed_and_keeps_slot(keys, monkeypatch):
    monkeypatch.setattr(sched, "_LEASE_TTL_SEC", 2)
    assert sched._try_acquire("live", sched.CHAT, 1) is True
    t0 = time.time()
    while time.time() - t0 < 3.2:                            # TTL'in (2 sn) çok üstünde yaşıyor
        assert sched._renew_held() >= 1
        time.sleep(0.4)
    assert sched._try_acquire("other", sched.CHAT, 1) is False
    sched._release("live")
    assert sched._try_acquire("other", sched.CHAT, 1) is True


def test_renew_does_not_resurrect_released_token(keys):
    assert sched._try_acquire("a", sched.CHAT, 2) is True
    sched._release("a")
    sched._track("a")                                        # geç yenileme senaryosu: jeton izlenirken bırakılmış
    sched._renew_held()
    assert keys.zscore(sched._ACTIVE_KEY, "a") is None       # XX: yok olan üye eklenmez


def test_heartbeat_thread_started_on_acquire(keys):
    assert sched._try_acquire("hb", sched.CHAT, 1) is True
    assert sched._hb_thread is not None and sched._hb_thread.is_alive() and sched._hb_thread.daemon
    sched._release("hb")
    assert "hb" not in sched._held_tokens
