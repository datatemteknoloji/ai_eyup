"""Kullanıcı iptali — bayrağın gerçekten pipeline'a ulaştığını doğrular.

Regresyon: `cancel_turn` yalnız DB durumunu "cancelled" yapıyordu. Çalışan
pipeline bunu hiç görmediği için iptal KOZMETİKTİ — model token üretmeye,
araçlar çalışmaya, `ai_gate` kotası tutulmaya devam ediyordu. Buradaki
testler iptalin üç kontrol noktasına da ulaştığını ve yetkisiz iptalin
engellendiğini kanıtlar.
"""
import types

import pytest
from fastapi import HTTPException

from app.services import chat_cancel
from app.services.chat_orchestrator import events


class FakeRedis:
    """Sadece bu testlerin kullandığı komutlar (set/exists/delete/xadd)."""

    def __init__(self):
        self.kv = {}
        self.published = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def exists(self, key):
        return 1 if key in self.kv else 0

    def delete(self, key):
        self.kv.pop(key, None)

    def expire(self, key, ttl):
        return True

    def xadd(self, key, fields, maxlen=None, approximate=True):
        self.published.append((key, fields))
        return "1-0"


@pytest.fixture()
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(events, "get_redis", lambda: r)
    return r


# ── 1) Bayrak katmanı ───────────────────────────────────────────────────────
def test_cancel_flag_roundtrip(redis):
    assert events.is_cancel_requested("t1") is False
    assert events.request_cancel("t1") is True
    assert events.is_cancel_requested("t1") is True
    events.clear_cancel("t1")
    assert events.is_cancel_requested("t1") is False


def test_flag_layer_survives_missing_redis(monkeypatch):
    # Redis yoksa iptal ÇALIŞMAZ ama istek de patlamaz (yalnız işbirlikçi
    # durdurma devre dışı kalır).
    monkeypatch.setattr(events, "get_redis", lambda: None)
    assert events.request_cancel("t1") is False
    assert events.is_cancel_requested("t1") is False


# ── 2) Contextvar bağlama + kısma ───────────────────────────────────────────
def test_is_cancelled_false_when_not_bound(redis):
    events.request_cancel("t1")
    # Hiçbir tura bağlı değilsek başka turun bayrağı bizi etkilemez.
    assert chat_cancel.is_cancelled() is False


def test_is_cancelled_true_for_bound_turn(redis):
    token = chat_cancel.bind("t1")
    try:
        assert chat_cancel.is_cancelled() is False
        events.request_cancel("t1")
        # force=True kısmayı atlar (250 ms cache)
        assert chat_cancel.is_cancelled(force=True) is True
    finally:
        chat_cancel.unbind(token)


def test_concurrent_turns_do_not_see_each_other(redis):
    events.request_cancel("other-turn")
    token = chat_cancel.bind("my-turn")
    try:
        assert chat_cancel.is_cancelled(force=True) is False
    finally:
        chat_cancel.unbind(token)
    assert chat_cancel.is_cancelled_for("other-turn") is True


def test_throttle_avoids_redis_call_per_token(redis, monkeypatch):
    calls = {"n": 0}
    orig = events.is_cancel_requested

    def counting(turn_id):
        calls["n"] += 1
        return orig(turn_id)

    monkeypatch.setattr(events, "is_cancel_requested", counting)
    token = chat_cancel.bind("t1")
    try:
        for _ in range(50):
            chat_cancel.is_cancelled()
    finally:
        chat_cancel.unbind(token)
    # 50 token için tek Redis okuması yeterli (250 ms pencere)
    assert calls["n"] == 1


def test_raise_if_cancelled(redis):
    token = chat_cancel.bind("t1")
    try:
        chat_cancel.raise_if_cancelled()  # bayrak yok → sessiz
        events.request_cancel("t1")
        chat_cancel.is_cancelled(force=True)  # cache'i güncelle
        with pytest.raises(chat_cancel.ChatCancelled):
            chat_cancel.raise_if_cancelled()
    finally:
        chat_cancel.unbind(token)


# ── 3) cancel_turn: bayrak + olay ───────────────────────────────────────────
class FakeTurn:
    def __init__(self, status="streaming", partial="yarım cevap"):
        self.id = "t1"
        self.status = status
        self.finished_at = None
        self.partial_response = partial
        self.session_id = 5
        self.user_id = None
        self.error = None
        self.source_plan = {}


class FakeDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_cancel_turn_sets_flag_and_publishes(redis, monkeypatch):
    from app.services.chat_orchestrator import service

    turn = FakeTurn()
    monkeypatch.setattr(service, "get_turn", lambda db, tid: turn)
    published = []
    monkeypatch.setattr(
        service.events, "publish_event", lambda tid, ev: published.append(ev) or 1,
    )
    monkeypatch.setattr(service.events, "request_cancel", events.request_cancel)

    assert service.cancel_turn(FakeDb(), "t1") is True
    assert turn.status == "cancelled"
    # Kritik: bayrak yazıldı → çalışan pipeline bunu görebilir
    assert events.is_cancel_requested("t1") is True
    assert published and published[0]["cancelled"] is True
    # Kısmi cevap iptal olayında taşınır (kullanıcı yarım yanıtı kaybetmez)
    assert published[0]["partial_response"] == "yarım cevap"


def test_cancel_turn_noop_on_finished_turn(redis, monkeypatch):
    from app.services.chat_orchestrator import service

    monkeypatch.setattr(service, "get_turn", lambda db, tid: FakeTurn(status="completed"))
    assert service.cancel_turn(FakeDb(), "t1") is False
    assert events.is_cancel_requested("t1") is False


# ── 4) Sahiplik / yetki ─────────────────────────────────────────────────────
def _user(uid, role="operator"):
    return types.SimpleNamespace(id=uid, role=role)


def test_authorize_allows_legacy_turn_without_owner():
    from app.api.chat_turns import _authorize_turn

    _authorize_turn(FakeTurn(), None)  # user_id None → zorlama yok


def test_authorize_requires_token_when_turn_has_owner():
    from app.api.chat_turns import _authorize_turn

    turn = FakeTurn()
    turn.user_id = 7
    with pytest.raises(HTTPException) as exc:
        _authorize_turn(turn, None)
    assert exc.value.status_code == 401


def test_authorize_rejects_other_user():
    from app.api.chat_turns import _authorize_turn

    turn = FakeTurn()
    turn.user_id = 7
    with pytest.raises(HTTPException) as exc:
        _authorize_turn(turn, _user(8))
    assert exc.value.status_code == 403


def test_authorize_allows_owner_and_admin():
    from app.api.chat_turns import _authorize_turn

    turn = FakeTurn()
    turn.user_id = 7
    _authorize_turn(turn, _user(7))
    _authorize_turn(turn, _user(9, role="admin"))
