"""Adım 10 — ilk token öncesi ilerleme olayları (orkestratör `progress.py` + bekçi)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.chat_orchestrator import progress as P
from app.services import runtime_settings as rts

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def adv(self, s):
        self.t += s


def mk(**kw):
    c = Clock()
    return P.ProgressTracker(clock=c, **kw), c


# ── sözleşme / şablon ──
def test_start_emits_understood_event_shape():
    t, _ = mk()
    ev = t.start("understood")
    assert len(ev) == 1
    e = ev[0]
    assert e["type"] == "progress" and e["step"] == "understood" and isinstance(e["elapsed_s"], int) and e["text"]


def test_steps_are_the_documented_set():
    assert set(P.STEPS) == {"queued", "understood", "selecting", "querying", "queried", "thinking", "answering", "waiting"}


def test_duplicate_step_text_not_repeated():
    t, _ = mk()
    assert t.on_chunk({"phase": "collecting"}) and not t.on_chunk({"phase": "collecting"})


@pytest.mark.parametrize("chunk,step", [
    ({"phase": "collecting"}, "understood"),
    ({"phase": "tools"}, "selecting"),
    ({"type": "tool_call", "tool": "get_disk_usage", "label": "Disk kullanımı"}, "querying"),
    ({"type": "tool_result", "tool": "get_disk_usage", "label": "Disk kullanımı"}, "queried"),
    ({"phase": "answering"}, "answering"),
])
def test_chunk_to_step_mapping(chunk, step):
    t, _ = mk()
    evs = t.on_chunk(chunk)
    assert [e["step"] for e in evs] == [step]


def test_tool_label_included_but_sanitized():
    t, _ = mk()
    e = t.on_chunk({"type": "tool_call", "tool": "x", "label": "Disk\nkullanımı\t\x00 " + "A" * 200})[0]
    assert "\n" not in e["text"] and "\x00" not in e["text"] and "\t" not in e["text"]
    assert len(e["text"]) < 120 and "Disk kullanımı" in e["text"]


def test_safe_label_basic():
    assert P.safe_label(None) == "" and P.safe_label("a\r\nb") == "a b" and len(P.safe_label("x" * 100)) == 48


def test_no_user_or_tool_payload_in_text():
    t, _ = mk()
    evs = t.on_chunk({"type": "tool_call", "tool": "t", "label": "L", "args": {"host": "secret-host-01"}, "result": "S3CR3T"})
    assert "secret-host-01" not in str(evs) and "S3CR3T" not in str(evs)


# ── kalp atışı ──
def test_no_heartbeat_before_interval():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    c.adv(4.0)
    assert t.tick() == []


def test_heartbeat_after_interval_with_elapsed_and_flag():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    c.adv(6.0)
    evs = t.tick()
    assert len(evs) == 1 and evs[0]["step"] == "waiting" and evs[0]["heartbeat"] is True
    assert evs[0]["elapsed_s"] == 6 and "6 sn" in evs[0]["text"]


def test_heartbeat_repeats_every_interval_not_every_tick():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    n = 0
    for _ in range(30):
        c.adv(1.0)
        n += len(t.tick())
    assert 5 <= n <= 6  # 30 sn / 5 sn


def test_heartbeat_keeps_last_stage_text():
    t, c = mk(heartbeat_s=5)
    t.on_chunk({"type": "tool_call", "tool": "x", "label": "Prometheus sorgusu"})
    c.adv(8)
    assert "Prometheus sorgusu" in t.tick()[0]["text"]


def test_queue_heartbeat_shows_position():
    t, c = mk(heartbeat_s=5)
    t._mk("queued", "Sırada bekleniyor (sıranız: 3)")
    c.adv(6)
    ev = t.tick(queue_position=2)[0]
    assert "sıranız: 2" in ev["text"]


def test_silent_after_first_token():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    t.on_token()
    c.adv(30)
    assert t.tick() == [] and t.on_chunk({"phase": "answering"}) == []


def test_max_gap_between_events_bounded_by_heartbeat():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    last, worst = c(), 0.0
    for _ in range(120):          # 120 sn tam sessizlik (virt: hat hiç olay yayınlamıyor)
        c.adv(1.0)
        if t.tick():
            worst = max(worst, c() - last)
            last = c()
    assert worst <= 6.0


# ── sınırlar / kapatma ──
def test_stage_event_cap_60_but_heartbeats_continue():
    t, c = mk(heartbeat_s=5)
    n_stage = 0
    for i in range(100):
        n_stage += len(t.on_chunk({"type": "tool_call", "tool": "x", "label": f"L{i}"}))
    assert n_stage == 60 and t.n_emitted == 60
    c.adv(6)
    assert len(t.tick()) == 1          # aşama sınırı dolsa da uzun beklemede susmaz


def test_long_wait_never_silent_for_300s():
    t, c = mk(heartbeat_s=5)
    t.start("understood")
    last, worst = c(), 0.0
    for _ in range(600):               # 10 dk (eski sınır 60 olay ≈ 300 sn'de susuyordu)
        c.adv(1.0)
        if t.tick():
            worst = max(worst, c() - last)
            last = c()
    assert worst <= 6.0 and c() - last <= 6.0


def test_heartbeat_cap_limits_runaway():
    t, c = mk(heartbeat_s=1, max_heartbeats=10)
    t.start("understood")
    n = 0
    for _ in range(100):
        c.adv(1.0)
        n += len(t.tick())
    assert n == 10 and t.done


def test_disabled_emits_nothing():
    t, c = mk(enabled=False)
    assert t.start("understood") == [] and t.on_chunk({"phase": "tools"}) == []
    c.adv(60)
    assert t.tick() == [] and t.done


def test_heartbeat_clamped_min_1():
    t, _ = mk(heartbeat_s=0)
    assert t.heartbeat_s >= 1.0


# ── trace tabanlı (virt) ──
def test_trace_tools_produce_queried_when_hat_emits_no_tool_events():
    t, c = mk()
    t.start("understood")
    evs = t.tick(trace_tools=["db_list_vms"])
    assert evs and evs[0]["step"] == "queried" and "db_list_vms" in evs[0]["text"]
    assert t.tick(trace_tools=["db_list_vms"]) == []     # aynı araç tekrar sayılmaz


def test_trace_tools_ignored_when_hat_emits_tool_call_events():
    t, c = mk()
    t.on_chunk({"type": "tool_call", "tool": "a", "label": "A"})
    assert t.tick(trace_tools=["a"]) == []


# ── ayarlar ──
def test_build_tracker_reads_settings(monkeypatch):
    monkeypatch.setattr(rts, "get_bool", lambda k: False if k == "chat_progress_enabled" else True)
    monkeypatch.setattr(rts, "get_int", lambda k: 3 if k == "chat_progress_heartbeat_sec" else 0)
    t = P.build_tracker()
    assert t.enabled is False and t.heartbeat_s == 3.0


def test_build_tracker_safe_default_on_error(monkeypatch):
    def boom(k):
        raise RuntimeError("x")
    monkeypatch.setattr(rts, "get_bool", boom)
    t = P.build_tracker()
    assert t.enabled is True and t.heartbeat_s == 5.0


def test_settings_schema_defaults():
    a, b = rts.ADVANCED_SCHEMA["chat_progress_enabled"], rts.ADVANCED_SCHEMA["chat_progress_heartbeat_sec"]
    assert a["default"] is True and b["default"] == 5 and b["min"] == 2 and b["max"] == 30


# ── bekçi (iş parçacığı çekirdeği) ──
def test_watcher_publishes_heartbeats_and_stops_on_first_token(monkeypatch):
    from app.services.chat_orchestrator import service as S
    c = Clock()
    tr = P.ProgressTracker(clock=c, heartbeat_s=5)
    tr.start("understood")
    sent = []
    monkeypatch.setattr(S.events, "publish_event", lambda tid, ev: sent.append(ev) or 1)

    def wait(_):
        c.adv(1.0)
        if len(sent) >= 3:
            tr.on_token()
        return False

    S._progress_watch_loop("t1", tr, {}, wait)
    assert len(sent) == 3 and all(e["type"] == "progress" for e in sent) and tr.done


def test_watcher_uses_trace_tools(monkeypatch):
    from app.services.chat_orchestrator import service as S
    from app.services.chat_quality.trace import TurnTrace
    c = Clock()
    tr = P.ProgressTracker(clock=c, heartbeat_s=50)
    holder = {"tr": TurnTrace(turn_id="x")}
    holder["tr"].note_tool("db_list_vms", {}, {})
    sent = []
    monkeypatch.setattr(S.events, "publish_event", lambda tid, ev: sent.append(ev) or 1)
    calls = {"n": 0}

    def wait(_):
        calls["n"] += 1
        if calls["n"] >= 2:
            tr.on_token()
        return False

    S._progress_watch_loop("t2", tr, holder, wait)
    assert [e["step"] for e in sent] == ["queried"] and "db_list_vms" in sent[0]["text"]


def test_watcher_returns_when_stopped(monkeypatch):
    from app.services.chat_orchestrator import service as S
    tr = P.ProgressTracker(clock=Clock(), heartbeat_s=5)
    sent = []
    monkeypatch.setattr(S.events, "publish_event", lambda tid, ev: sent.append(ev) or 1)
    S._progress_watch_loop("t3", tr, {}, lambda _: True)
    assert sent == []


def test_watcher_thread_emits_while_event_loop_is_blocked(monkeypatch):
    """Hat senkron iş yapıp event döngüsünü bloklasa da kalp atışı çıkar (admin'de 11,8 sn boşluğun nedeni)."""
    import time as _t
    from app.services.chat_orchestrator import service as S
    sent = []
    monkeypatch.setattr(S.events, "publish_event", lambda tid, ev: sent.append(ev) or 1)
    tr = P.ProgressTracker(heartbeat_s=1.0)   # gerçek saat
    tr.start("understood")
    stop = S._start_progress_watch("t4", tr, {})
    try:
        _t.sleep(3.3)          # döngü yerine bu iş parçacığı bloklanıyor — bekçi ayrı iş parçacığında
    finally:
        stop.set()
    assert len([e for e in sent if e.get("heartbeat")]) >= 2


def test_tracker_is_thread_safe_smoke():
    import threading
    t = P.ProgressTracker(heartbeat_s=1.0)
    errs = []

    def w():
        try:
            for i in range(200):
                t.on_chunk({"type": "tool_call", "tool": "x", "label": f"L{i}"})
                t.tick(trace_tools=["a"])
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ths = [threading.Thread(target=w) for _ in range(4)]
    [x.start() for x in ths]
    [x.join() for x in ths]
    assert not errs and t.n_emitted <= 60


# ── entegrasyon (kaynak) ──
def test_service_hooks_present():
    src = (ROOT / "services" / "chat_orchestrator" / "service.py").read_text(encoding="utf-8")
    assert "chat_progress.build_tracker()" in src
    assert "_pw_tracker.on_chunk(chunk)" in src
    assert src.count("_pw_tracker.on_token()") >= 2
    i = src.index("    finally:\n        if _pw_tracker is not None:")
    assert "_pw_stop.set()" in src[i:i + 400]
    assert '_pw_holder["tr"] = tr' in src


def test_progress_started_before_queue_wait():
    src = (ROOT / "services" / "chat_orchestrator" / "service.py").read_text(encoding="utf-8")
    assert src.index("_start_progress_watch(turn_id, _pw_tracker, _pw_holder)") < src.index("await ai_gate.acquire(turn_id")


def test_automic_untouched_and_has_own_progress():
    for f in ("api/automation.py",):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "chat_orchestrator.progress" not in src and "chat_progress" not in src


def test_progress_module_has_no_db_or_llm_imports():
    src = (ROOT / "services" / "chat_orchestrator" / "progress.py").read_text(encoding="utf-8")
    for bad in ("sqlalchemy", "llm_gateway", "requests", "httpx", "SessionLocal"):
        assert bad not in src
