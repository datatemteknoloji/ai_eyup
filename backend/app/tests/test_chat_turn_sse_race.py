"""subscribe_sse: tur bitip olaylar XREAD ile durum kontrolü arasında yayınlandıysa kaybolmamalı."""
import asyncio
import json
from types import SimpleNamespace

from app.services.chat_orchestrator import service


class _FakeDB:
    def close(self):
        pass


def _run(coro_gen):
    async def _collect():
        return [x async for x in coro_gen]
    return asyncio.run(_collect())


def _parse(lines):
    return [json.loads(l[len("data: "):]) for l in lines]


def test_idle_branch_drains_unread_events_before_synthetic_done(monkeypatch):
    stream = [
        {"_id": "1-0", "token": "Mer"},
        {"_id": "2-0", "token": "haba"},
        {"_id": "3-0", "type": "debug_trace", "trace": {"x": 1}},
        {"_id": "4-0", "done": True, "session_id": 7},
    ]
    state = {"status": "running"}

    def snapshot(turn_id, after_id="0-0", count=500):
        # ilk çağrı (başlangıç replay): henüz hiçbir şey yok
        if state.get("started") is None:
            state["started"] = True
            return []
        ids = [e for e in stream if e["_id"] > after_id]
        return [dict(e) for e in ids]

    def read_new(turn_id, last, block_ms, count):
        # XREAD zaman aşımı: boş döner; bu sırada tur biter
        state["status"] = "completed"
        return []

    monkeypatch.setattr(service.events, "snapshot_events", snapshot)
    monkeypatch.setattr(service.events, "read_new_events", read_new)
    monkeypatch.setattr(service, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(
        service, "get_turn",
        lambda db, tid: SimpleNamespace(status=state["status"], session_id=7, error=None),
    )
    out = _parse(_run(service.subscribe_sse("t1")))
    toks = "".join(e.get("token", "") for e in out)
    assert toks == "Merhaba"
    assert any(e.get("type") == "debug_trace" for e in out)
    assert out[-1].get("done") is True
    assert sum(1 for e in out if e.get("done")) == 1


def test_idle_branch_synthetic_done_when_nothing_to_drain(monkeypatch):
    state = {"status": "failed"}
    monkeypatch.setattr(service.events, "snapshot_events", lambda *a, **k: [])
    monkeypatch.setattr(service.events, "read_new_events", lambda *a, **k: [])
    monkeypatch.setattr(service, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(
        service, "get_turn",
        lambda db, tid: SimpleNamespace(status=state["status"], session_id=None, error="boom"),
    )
    out = _parse(_run(service.subscribe_sse("t2")))
    assert out == [{"done": True, "session_id": None, "turn_id": "t2", "error": "boom"}]
