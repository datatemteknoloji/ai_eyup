"""Adım 13 — `ai_gate` v2: lease/slot, ölü bekleyen, hızlı şerit, kuyruk sınırı, kullanıcı limiti, oturum seri, metrik.

Gerçek Redis ile (benzersiz test anahtarları; canlı `ainew:ai:*` anahtarlarına dokunulmaz). Redis yoksa atlanır.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import pytest

from app.services.chat_orchestrator import ai_gate as g

ROOT = Path(__file__).resolve().parents[1]


def _real_redis():
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        r.ping()
        return r
    except Exception:
        return None


@pytest.fixture()
def gate(monkeypatch):
    r = _real_redis()
    if r is None:
        pytest.skip("Redis yok")
    sfx = uuid.uuid4().hex[:8]
    monkeypatch.setattr(g, "_LEASE", f"test:ai:lease:{sfx}")
    monkeypatch.setattr(g, "_WAITQ", f"test:ai:waitq:{sfx}")
    monkeypatch.setattr(g, "_HB", f"test:ai:hb:{sfx}:")
    monkeypatch.setattr(g, "_STATS", f"test:ai:stats:{sfx}")
    monkeypatch.setattr(g, "_AVG", f"test:ai:avg:{sfx}")
    monkeypatch.setattr(g, "_UACT", f"test:chat:uact:{sfx}:{{uid}}")
    monkeypatch.setattr(g, "_UTURN", f"test:chat:uturn:{sfx}:{{turn}}")
    monkeypatch.setattr(g, "_SESS", f"test:chat:sess:{sfx}:{{sid}}")
    cfg = {"limit": 1, "max_wait": 180, "max_queue": 0, "user_limit": 2, "bonus": 45, "serial": True}
    monkeypatch.setattr(g, "_limit", lambda: cfg["limit"])
    monkeypatch.setattr(g, "max_wait_sec", lambda: cfg["max_wait"])
    monkeypatch.setattr(g, "max_queue", lambda: cfg["max_queue"])
    monkeypatch.setattr(g, "user_limit", lambda: cfg["user_limit"])
    monkeypatch.setattr(g, "fast_bonus_sec", lambda: cfg["bonus"])
    monkeypatch.setattr(g, "session_serial_enabled", lambda: cfg["serial"])
    monkeypatch.setattr(g, "_llm_cap", lambda: 1)
    from app.services.chat_orchestrator import events
    monkeypatch.setattr(events, "is_cancel_requested", lambda tid: False)
    yield cfg
    keys = r.keys(f"test:*:{sfx}*") + r.keys(f"test:ai:hb:{sfx}:*")
    if keys:
        r.delete(*keys)


def _poll(token, score=None, enqueue=True, limit=None, mq=0):
    st, rank, _c = g._poll(token, time.time() if score is None else score, enqueue, limit or g._limit(), mq, token)
    return st, rank


# ── slot / FIFO / lease ──────────────────────────────────────────────────────────────────────────────────────────

def test_limit_and_fifo(gate):
    gate["limit"] = 2
    s = time.time()
    assert _poll("t1", s)[0] == 1
    assert _poll("t2", s + 0.001)[0] == 1
    assert _poll("t3", s + 0.002)[0] == 0               # slot dolu → bekliyor
    assert _poll("t4", s + 0.003) == (0, 1)             # t3'ün arkasında (rank 1)
    assert g.held_count() == 2 and g.queue_len() == 2
    g.release("t1")
    assert _poll("t4", enqueue=False)[0] == 0           # sıra t3'te: t4 geçemez
    assert _poll("t3", enqueue=False)[0] == 1
    g.release("t2"); g.release("t3")
    assert _poll("t4", enqueue=False)[0] == 1


def test_lease_expires_for_crashed_holder_and_renew_keeps(gate, monkeypatch):
    monkeypatch.setattr(g, "LEASE_TTL_SEC", -1)           # anında süresi dolmuş lease (çökmüş sahip)
    assert _poll("dead")[0] == 1
    monkeypatch.setattr(g, "LEASE_TTL_SEC", 240)
    assert _poll("alive")[0] == 1                         # ölü sahibin slotu geri geldi
    g.renew("alive")
    assert g.held_count() == 1
    g.release("alive"); g.release("alive")                # çift release zararsız
    assert g.held_count() == 0


def test_renew_reclaims_expired_slot_so_accounting_stays_exact(gate, monkeypatch):
    monkeypatch.setattr(g, "LEASE_TTL_SEC", -1)
    assert _poll("slow")[0] == 1                          # lease süresi doldu (uzun sessizlik)
    assert g.held_count() == 0
    monkeypatch.setattr(g, "LEASE_TTL_SEC", 240)
    g.renew("slow")                                       # tur hâlâ yaşıyor → yeniden sayılır
    assert g.held_count() == 1


def test_dead_waiter_at_head_does_not_block_queue(gate, monkeypatch):
    monkeypatch.setattr(g, "HB_TTL_SEC", 1)
    s = time.time()
    assert _poll("holder", s)[0] == 1
    assert _poll("ghost", s + 0.001)[0] == 0              # kuyruğa girdi, sonra süreç «öldü» (bir daha yoklamıyor)
    assert _poll("alive", s + 0.002) == (0, 1)
    time.sleep(1.3)                                       # ghost'un canlılık işareti sona erdi
    g.release("holder")
    # alive yoklayınca baştaki ölü kayıt atılır ve alive slotu alır
    assert _poll("alive", enqueue=False)[0] == 1
    assert g.queue_len() == 0


def test_enqueue_sweeps_dead_entries(gate, monkeypatch):
    monkeypatch.setattr(g, "HB_TTL_SEC", 1)
    s = time.time()
    _poll("holder", s)
    for i in range(3):
        _poll(f"ghost{i}", s + 0.01 * (i + 1))
    assert g.queue_len() == 3
    time.sleep(1.3)
    _poll("fresh", s + 1)                                 # kuyruğa girerken ölüler süpürülür
    assert g.queue_len() == 1


def test_dropped_entry_requeues_with_same_score(gate):
    """Canlılık işareti kaçırılıp kayıt atılmışsa (-2) çağıran aynı skorla yeniden girer."""
    s = time.time()
    _poll("holder", s)
    assert _poll("w", s + 1, enqueue=False)[0] == -2      # kuyrukta değil
    assert _poll("w", s + 1, enqueue=True)[0] == 0


# ── hızlı şerit ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_fast_lane_jumps_ahead_but_not_past_old_waiters(gate):
    now = time.time()
    _poll("holder", now - 100)
    _poll("normal_new", now)                              # normal, şimdi geldi
    _poll("fast_new", now + 0.5 - gate["bonus"])          # hızlı: skor = gelişi − 45 sn
    _poll("normal_old", now - 60)                         # 60 sn önce gelen normal: hızlıdan önce kalır
    order = []
    for _ in range(3):
        tok = [t for t in ("normal_new", "fast_new", "normal_old") if t not in order]
        g.release("holder" if not order else order[-1])
        for t in tok:
            if _poll(t, enqueue=False)[0] == 1:
                order.append(t)
                break
    assert order == ["normal_old", "fast_new", "normal_new"]


def test_bonus_zero_is_plain_fifo(gate):
    gate["bonus"] = 0
    s = time.time()
    _poll("holder", s)
    _poll("a", s + 0.001)
    _poll("b", s + 0.002 - gate["bonus"])
    g.release("holder")
    assert _poll("b", enqueue=False)[0] == 0
    assert _poll("a", enqueue=False)[0] == 1


def test_classify_lane():
    assert g.classify_lane("Merhaba") == g.FAST
    assert g.classify_lane("Hangi Linux sunucularında disk doluluğu yüzde 80 üzerinde?") == g.NORMAL
    assert g.classify_lane("") == g.NORMAL and g.classify_lane(None) == g.NORMAL


# ── kuyruk sınırı + kabul ───────────────────────────────────────────────────────────────────────────────────────

def test_lua_queue_cap_enforced(gate):
    s = time.time()
    _poll("holder", s)
    assert _poll("q1", s + 0.1, mq=2)[0] == 0
    assert _poll("q2", s + 0.2, mq=2)[0] == 0
    assert _poll("q3", s + 0.3, mq=2)[0] == -1            # kuyruk dolu


def test_admit_queue_full_and_user_limit(gate):
    gate["max_queue"] = 1
    s = time.time()
    _poll("holder", s)
    g.admit("t1", 7)                                      # kuyruk boş → kabul
    _poll("waiter", s + 0.1)
    with pytest.raises(g.AdmissionError) as e:
        g.admit("t2", 8)
    assert e.value.reason == "queue_full" and e.value.status == 429 and "yoğun" in e.value.detail
    gate["max_queue"] = 0
    g.admit("a2", 7)                                      # 7 numaralı kullanıcı: 2/2
    with pytest.raises(g.AdmissionError) as e2:
        g.admit("a3", 7)
    assert e2.value.reason == "user_limit" and "Önceki sorularınız" in e2.value.detail
    g.admit("b1", 9)                                      # başka kullanıcı etkilenmez
    g.turn_finished("t1")                                 # biri bitince yer açılır
    g.admit("a3", 7)
    g.turn_finished("a3"); g.turn_finished("a3")          # idempotent
    g.admit("anon", None)                                 # user_id yok → limit uygulanmaz
    gate["user_limit"] = 0
    for i in range(5):
        g.admit(f"free{i}", 7)                            # 0 = kapalı
    snap = g.snapshot()["stats"]
    assert snap.get("rej_queue_full") == 1 and snap.get("rej_user_limit") == 1


def test_http_bridge_maps_admission_to_429_without_creating_turn(monkeypatch):
    from fastapi import HTTPException
    from app.services.chat_orchestrator import http_bridge as hb

    def _boom(turn_id, user_id):
        raise g.AdmissionError("user_limit", g.MSG_USER_LIMIT)

    called = []
    monkeypatch.setattr(hb.ai_gate, "admit", _boom)
    monkeypatch.setattr(hb, "create_turn", lambda *a, **k: called.append(1))
    with pytest.raises(HTTPException) as e:
        hb.attach_and_stream(platform="unified", payload={}, message="x", session_id=None,
                             pipeline=lambda *a, **k: None, user_id=5)
    assert e.value.status_code == 429 and e.value.detail == g.MSG_USER_LIMIT
    assert called == []                                   # tur/DB kaydı oluşmadı


# ── async acquire: timeout / iptal / thread tutmama ────────────────────────────────────────────────────────────

def test_async_acquire_timeout_cleans_queue_and_message(gate):
    async def main():
        a = await g.acquire("t-a", message="uzun veri sorusu 12345")
        assert a.ok and a.first_position == 0
        b = await g.acquire("t-b", message="uzun veri sorusu 12345", timeout=0.6)
        assert not b.ok and b.reason == "timeout" and "bekleme süresi" in b.message and "AI kuyruğu zaman aşımı" not in b.message
        assert g.queue_len() == 0                         # zaman aşımında kuyruktan çıktı
        g.release("t-a")
        c = await g.acquire("t-c", message="x")
        assert c.ok
        g.release("t-c")
    asyncio.run(main())
    st = g.snapshot()["stats"]
    assert st["timeouts"] == 1 and st["acquired"] == 2 and st["wait_count"] == 2


def test_async_acquire_cancel_leaves_queue(gate, monkeypatch):
    from app.services.chat_orchestrator import events
    monkeypatch.setattr(events, "is_cancel_requested", lambda tid: tid == "t-x")

    async def main():
        assert (await g.acquire("t-a", message="m")).ok
        r = await g.acquire("t-x", message="m", timeout=5)
        assert not r.ok and r.reason == "cancelled"
        assert g.queue_len() == 0
        g.release("t-a")
    asyncio.run(main())


def test_async_acquire_queue_full_fast_reject(gate):
    gate["max_queue"] = 1

    async def main():
        assert (await g.acquire("t-a", message="m")).ok
        w = asyncio.create_task(g.acquire("t-b", message="m", timeout=1.0))
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        r = await g.acquire("t-c", message="m", timeout=30)
        assert not r.ok and r.reason == "queue_full" and "yoğun" in r.message
        assert time.monotonic() - t0 < 1.0                # 30 sn beklemeden anında
        assert (await w).reason == "timeout"
        g.release("t-a")
    asyncio.run(main())


def test_many_waiters_do_not_exhaust_chat_io_threads(gate):
    """120 bekleyen (> 96 işçi) tur: bekleme iş parçacığı TUTMAZ; hepsi bütçe içinde sonuçlanır, döngü bloklanmaz."""
    from app.core import chat_executor

    async def main():
        assert (await g.acquire("holder", message="m")).ok
        ticks = []

        async def ticker():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        tk = asyncio.create_task(ticker())
        t0 = time.monotonic()
        res = await asyncio.gather(*[g.acquire(f"w{i}", message="m", timeout=1.2) for i in range(120)])
        took = time.monotonic() - t0
        tk.cancel()
        assert all(r.reason == "timeout" for r in res)
        assert took < 6.0, took
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.5
        assert g.queue_len() == 0
        g.release("holder")
    assert chat_executor.CHAT_IO_WORKERS < 120
    asyncio.run(main())


def test_waiter_promoted_when_slot_frees(gate):
    async def main():
        assert (await g.acquire("t-a", message="m")).ok
        w = asyncio.create_task(g.acquire("t-b", message="m", timeout=10))
        await asyncio.sleep(0.4)
        assert not w.done()
        g.release("t-a")
        r = await asyncio.wait_for(w, 5)
        assert r.ok and r.first_position == 0 or r.first_position >= 0
        assert r.wait_ms >= 300
        g.release("t-b")
    asyncio.run(main())


# ── oturum başına seri ──────────────────────────────────────────────────────────────────────────────────────────

def test_session_serial_waits_for_previous_turn(gate):
    async def main():
        assert (await g.session_acquire(10, "turn-1")).ok
        waited = []

        async def note():
            waited.append(1)

        t = asyncio.create_task(g.session_acquire(10, "turn-2", timeout=10, on_wait=note))
        await asyncio.sleep(0.6)
        assert not t.done() and waited == [1]
        other = await g.session_acquire(11, "turn-3")     # farklı oturum etkilenmez
        assert other.ok
        g.session_release(10, "turn-2")                    # sahibi olmayan release kilidi AÇMAZ
        await asyncio.sleep(0.5)
        assert not t.done()
        g.session_release(10, "turn-1")
        r = await asyncio.wait_for(t, 5)
        assert r.ok and r.wait_ms >= 500
        g.session_release(10, "turn-2"); g.session_release(11, "turn-3")
    asyncio.run(main())
    assert g.snapshot()["stats"].get("session_waited") == 1


def test_session_serial_timeout_and_disabled_and_no_session(gate):
    async def main():
        assert (await g.session_acquire(None, "t0")).ok          # oturum yok → atla
        assert (await g.session_acquire(20, "t1")).ok
        r = await g.session_acquire(20, "t2", timeout=0.5)
        assert not r.ok and r.reason == "timeout" and "önceki soru" in r.message
        gate["serial"] = False
        assert (await g.session_acquire(20, "t3")).ok            # kapalıyken serileştirme yok
        gate["serial"] = True
        g.session_release(20, "t1")
        assert (await g.session_acquire(20, "t2")).ok
        g.session_release(20, "t2")
    asyncio.run(main())


def test_session_lock_cancel_while_waiting(gate, monkeypatch):
    from app.services.chat_orchestrator import events
    monkeypatch.setattr(events, "is_cancel_requested", lambda tid: tid == "t2")

    async def main():
        assert (await g.session_acquire(30, "t1")).ok
        r = await g.session_acquire(30, "t2", timeout=5)
        assert not r.ok and r.reason == "cancelled"
        g.session_release(30, "t1")
    asyncio.run(main())


# ── ETA / metrik / yedek ────────────────────────────────────────────────────────────────────────────────────────

def test_eta_and_expected_position(gate):
    assert g.expected_position() == 0 and g.eta_seconds(0) == 0     # slot boş
    _poll("holder")
    assert g.expected_position() == 1                               # dolu → 1. sıra
    g.release("holder", held_since=time.monotonic() - 10.0)         # EWMA: 0.8*15 + 0.2*10 = 14 sn
    assert 13.5 <= g.avg_turn_sec() <= 14.5
    _poll("holder2")
    gate["limit"] = 2
    _poll("holder3")
    assert g.eta_seconds(2) == round(2 * g.avg_turn_sec() / 2)
    assert g.queue_position("nobody") == 0


def test_prometheus_text_and_snapshot(gate):
    async def main():
        assert (await g.acquire("t-a", message="m")).ok
        await g.acquire("t-b", message="m", timeout=0.4)
        g.release("t-a")
    asyncio.run(main())
    txt = g.render_prometheus()
    for name in ("ainew_chat_gate_held", "ainew_chat_gate_limit", "ainew_chat_gate_queue_len", "ainew_chat_gate_queue_limit",
                 "ainew_chat_gate_llm_cap", "ainew_chat_gate_avg_turn_seconds", "ainew_chat_gate_acquired_total",
                 "ainew_chat_gate_timeouts_total", 'ainew_chat_gate_rejected_total{reason="queue_full"}',
                 'ainew_chat_gate_rejected_total{reason="user_limit"}', "ainew_chat_gate_wait_seconds_count"):
        assert name in txt, name
    buckets = [int(l.rsplit(" ", 1)[1]) for l in txt.splitlines() if l.startswith("ainew_chat_gate_wait_seconds_bucket")]
    assert buckets == sorted(buckets) and buckets[-1] == 1          # birikimli histogram, +Inf = sayaç (yalnız slot alanlar)
    assert "ainew_chat_gate_timeouts_total 1" in txt
    snap = g.snapshot()
    gate["limit"] = 3
    assert "llm_max_concurrent" in g.snapshot().get("note", "")     # kapı 3 > LLM 1 uyarısı
    assert snap["held"] == 0


def test_local_fallback_without_redis(monkeypatch):
    monkeypatch.setattr(g, "_redis", lambda: None)
    monkeypatch.setattr(g, "_local", g._Local())
    from app.services.chat_orchestrator import events
    monkeypatch.setattr(events, "is_cancel_requested", lambda tid: False)
    monkeypatch.setattr(g, "_limit", lambda: 1)
    monkeypatch.setattr(g, "max_queue", lambda: 0)
    monkeypatch.setattr(g, "max_wait_sec", lambda: 10)
    monkeypatch.setattr(g, "fast_bonus_sec", lambda: 45)
    g.admit("x", 1)                                                  # Redis yok → fail-open

    async def main():
        a = await g.acquire("a", message="m")
        assert a.ok
        b = await g.acquire("b", message="m", timeout=0.4)
        assert b.reason == "timeout"
        g.release("a")
        assert (await g.acquire("c", message="m")).ok
        g.release("c")
    asyncio.run(main())


# ── ayar şeması + kaynak sözleşmeleri ───────────────────────────────────────────────────────────────────────────

def test_settings_schema_defaults():
    from app.services import runtime_settings as rts
    A = rts.ADVANCED_SCHEMA
    assert A["chat_gate_max_wait_sec"]["default"] == 180 and A["chat_gate_max_wait_sec"]["min"] >= 10
    assert A["chat_gate_max_queue"]["default"] == 20 and A["chat_gate_max_queue"]["min"] == 0
    assert A["chat_user_max_active_turns"]["default"] == 2 and A["chat_user_max_active_turns"]["min"] == 0
    assert A["chat_gate_fast_bonus_sec"]["default"] == 45 and A["chat_gate_fast_bonus_sec"]["min"] == 0
    assert A["chat_session_serial_enabled"]["default"] is True
    assert A["chat_ai_max_concurrent"]["default"] == 3                # (g): canlı ayar bu adımda DEĞİŞMEDİ


def test_service_wiring_source_contract():
    svc = (ROOT / "services" / "chat_orchestrator" / "service.py").read_text(encoding="utf-8")
    assert "ai_gate.try_acquire" not in svc and "ai_gate.release()" not in svc
    assert svc.index("ai_gate.session_acquire(") < svc.index("await ai_gate.acquire(turn_id")
    assert "ai_gate.session_release(_sess_id, turn_id)" in svc and "ai_gate.turn_finished(turn_id)" in svc
    assert "if _gate_held:" in svc                                    # pipeline'a girmeden çıkışta slot sızdırma yok
    assert svc.count("ai_gate.renew(turn_id, _sess_id)") >= 1
    assert 'tr.note_path("gate"' in svc
    br = (ROOT / "services" / "chat_orchestrator" / "http_bridge.py").read_text(encoding="utf-8")
    assert br.index("ai_gate.admit(turn_id, user_id)") < br.index("create_turn(")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"/metrics/chat-gate"' in main_src
