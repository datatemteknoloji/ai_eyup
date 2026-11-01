"""Adım 3 Parça 2A: route-hint ucuz ve atlanabilir (kısa üretim, slot meşgulse atla, tur içi önbellek)."""
import threading
import time

import pytest

from app.core.config import settings
from app.services import llm_activity, llm_availability as la, llm_gateway, llm_scheduler
from app.services import route_llm_hint as rh
from app.services.module_orchestrator import ModulePlan


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(la, "_redis", lambda: None)
    monkeypatch.setattr(llm_scheduler, "_redis", lambda: None)
    monkeypatch.setattr(llm_activity, "_redis", lambda: None)
    monkeypatch.setattr(llm_scheduler, "max_concurrent", lambda: 1)
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", False)
    llm_scheduler._local._active.clear()
    llm_scheduler._local._wait_chat.clear()
    llm_activity._skipped_local.clear()
    la.reset()
    rh.clear_cache()
    yield
    llm_scheduler._local._active.clear()
    llm_scheduler._local._wait_chat.clear()
    rh.clear_cache()
    la.reset()


def _plan():
    return ModulePlan(mode="knowledge", modules=(), domains=frozenset({"infra"}),
                      confidence=0.7, reason="no_module_signal")


# ── try_slot ──────────────────────────────────────────────────────────────────
def test_try_slot_free_gets_lease_and_releases():
    with llm_scheduler.try_slot("t") as lease:
        assert lease is not None and lease.wait_ms == 0.0
        assert llm_scheduler._local.state()["active"] == 1
    assert llm_scheduler._local.state()["active"] == 0


def test_try_slot_busy_returns_none_immediately():
    holding = threading.Event()
    release = threading.Event()

    def holder():
        with llm_scheduler.slot("holder"):
            holding.set()
            release.wait(3)

    t = threading.Thread(target=holder)
    t.start()
    assert holding.wait(2)
    t0 = time.perf_counter()
    with llm_scheduler.try_slot("hint") as lease:
        assert lease is None
    assert time.perf_counter() - t0 < 0.1          # beklemedi
    release.set()
    t.join()
    with llm_scheduler.try_slot("hint") as lease:   # slot boşalınca alınır
        assert lease is not None


def test_try_slot_reentrant_is_busy():
    with llm_scheduler.slot("outer"):
        with llm_scheduler.try_slot("inner") as lease:
            assert lease is None


def test_try_slot_disabled_scheduler_bypasses(monkeypatch):
    monkeypatch.setattr(llm_scheduler, "max_concurrent", lambda: 0)
    with llm_scheduler.try_slot("x") as lease:
        assert lease is not None and lease.bypassed


def test_slot_still_waits_for_other_calls():
    """slot() davranışı değişmedi: dolu slotta bekler, boşalınca alır."""
    holding = threading.Event()

    def holder():
        with llm_scheduler.slot("holder"):
            holding.set()
            time.sleep(0.3)

    t = threading.Thread(target=holder)
    t.start()
    assert holding.wait(2)
    with llm_scheduler.slot("waiter") as lease:
        assert lease.wait_ms >= 150 and not lease.bypassed
    t.join()


def test_slot_still_reentrant_bypass():
    with llm_scheduler.slot("outer"):
        with llm_scheduler.slot("inner") as lease:
            assert lease.bypassed and lease.reason == "reentrant"


# ── generate_sync(skip_if_busy / think) ───────────────────────────────────────
class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"response": "{\"modules\":[\"virt\"]}", "done": True}


def test_generate_sync_skips_when_slot_busy_without_network(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("slot meşgulken ağa çıkılmamalı")

    monkeypatch.setattr(llm_gateway.requests, "post", _boom)
    with llm_scheduler.slot("ana-cevap"):
        res = llm_gateway.generate_sync(model="m", prompt="x", best_effort=True, skip_if_busy=True)
    assert res["skipped"] == "slot_busy" and res["response"] == ""
    assert llm_activity.skipped_counts() == {"route_hint:slot_busy": 1}
    assert la.snapshot()["recent_failures"] == 0


def test_generate_sync_runs_when_slot_free(monkeypatch):
    seen = {}

    def _post(url, json=None, **_k):
        seen["payload"] = json
        return _Resp()

    monkeypatch.setattr(llm_gateway.requests, "post", _post)
    res = llm_gateway.generate_sync(model="gpt-oss:20b", prompt="x", skip_if_busy=True,
                                    think="low", options={"temperature": 0.0, "num_predict": 128})
    assert res.get("skipped") is None and res["response"]
    assert seen["payload"]["think"] == "low"
    assert seen["payload"]["options"]["num_predict"] == 128
    assert llm_scheduler._local.state()["active"] == 0


def test_think_only_for_gpt_oss(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_gateway.requests, "post", lambda url, json=None, **_k: seen.setdefault("p", json) and _Resp())
    llm_gateway.generate_sync(model="llama3:8b", prompt="x", think="low")
    assert "think" not in seen["p"]


def test_default_generate_sync_waits_and_has_no_think(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_gateway.requests, "post", lambda url, json=None, **_k: seen.setdefault("p", json) and _Resp())
    llm_gateway.generate_sync(model="gpt-oss:20b", prompt="x")
    assert "think" not in seen["p"]


# ── route hint ────────────────────────────────────────────────────────────────
def _capture(monkeypatch, response=None, skipped=False, error=None):
    calls = []

    def _fake(**kw):
        calls.append(kw)
        if skipped:
            return {"response": "", "done": True, "error": "slot_busy", "skipped": "slot_busy"}
        if error:
            return {"response": "", "done": True, "error": error}
        return {"response": response or '{"modules":["virt","linux"],"reason":"x"}', "done": True}

    monkeypatch.setattr(llm_gateway, "generate_sync", _fake)
    return calls


def test_hint_payload_is_cheap(monkeypatch):
    from app.services import llm_timeouts
    monkeypatch.setattr(llm_timeouts, "_p95", lambda cls: (None, 0))   # canlı Redis örneklerinden bağımsız
    calls = _capture(monkeypatch)
    out = rh._call_hint_llm("sunucu neden ağır", _plan())
    assert out == ("virt", "linux")
    kw = calls[0]
    assert kw["options"]["num_predict"] == 128 and kw["options"]["temperature"] == 0.0
    assert kw["think"] == "low"
    assert kw["skip_if_busy"] is True and kw["best_effort"] is True
    assert kw["timeout"] == 8.0 and rh._timeout_sec() == 8.0     # varsayılan 8 sn (örnek yokken)


def test_hint_settings_registered():
    from app.services.runtime_settings import ADVANCED_SCHEMA
    assert ADVANCED_SCHEMA["route_hint_num_predict"]["default"] == 128
    assert ADVANCED_SCHEMA["route_hint_think"]["default"] == "low"
    assert ADVANCED_SCHEMA["route_hint_think"]["choices"] == ["low", "medium", "high"]


def test_hint_uses_runtime_settings(monkeypatch):
    from app.services import runtime_settings as rts
    monkeypatch.setattr(rts, "get_int", lambda k: 64 if k == "route_hint_num_predict" else 0)
    monkeypatch.setattr(rts, "get_str", lambda k: "medium" if k == "route_hint_think" else "")
    calls = _capture(monkeypatch)
    rh._call_hint_llm("disk durumu", _plan())
    assert calls[0]["options"]["num_predict"] == 64 and calls[0]["think"] == "medium"


def test_busy_slot_skips_hint_and_keeps_keyword_plan(monkeypatch):
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    monkeypatch.setattr(llm_gateway.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ağ yok")))
    plan = _plan()
    t0 = time.perf_counter()
    with llm_scheduler.slot("ana-cevap"):
        out = rh.apply_route_llm_hint("sunucu neden ağır", plan)
    assert out is plan
    assert time.perf_counter() - t0 < 0.5                       # gecikme yok
    assert llm_activity.skipped_counts().get("route_hint:slot_busy") == 1


def test_free_slot_hint_applies_normally(monkeypatch):
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    monkeypatch.setattr(llm_gateway.requests, "post", lambda url, json=None, **_k: _Resp())
    out = rh.apply_route_llm_hint("sunucu neden ağır", _plan())
    assert out.modules == ("virt",)
    assert llm_activity.skipped_counts() == {}


def test_hint_cache_dedupes_within_turn(monkeypatch):
    calls = _capture(monkeypatch)
    for _ in range(3):                       # create_turn + boru hattı + tur sonu öneri
        assert rh._call_hint_llm("sunucu neden ağır", _plan()) == ("virt", "linux")
    assert len(calls) == 1


def test_hint_cache_also_covers_failures_and_skips(monkeypatch):
    calls = _capture(monkeypatch, error="ReadTimeout: x")
    for _ in range(3):
        assert rh._call_hint_llm("a", _plan()) == ()
    assert len(calls) == 1
    rh.clear_cache()
    calls2 = _capture(monkeypatch, skipped=True)
    for _ in range(3):
        assert rh._call_hint_llm("b", _plan()) == ()
    assert len(calls2) == 1


def test_hint_cache_key_depends_on_message_and_plan(monkeypatch):
    calls = _capture(monkeypatch)
    rh._call_hint_llm("m1", _plan())
    rh._call_hint_llm("m2", _plan())
    other = ModulePlan(mode="knowledge", modules=("linux",), domains=frozenset({"infra"}),
                       confidence=0.6, reason="single:linux")
    rh._call_hint_llm("m1", other)
    assert len(calls) == 3


def test_hint_cache_expires(monkeypatch):
    calls = _capture(monkeypatch)
    rh._call_hint_llm("m", _plan())
    monkeypatch.setattr(rh, "_CACHE_TTL_SEC", 0.0)
    rh._call_hint_llm("m", _plan())
    assert len(calls) == 2


def test_skipped_counter_in_recent_and_not_in_overlap():
    llm_activity.note_skipped("generate_sync", "slot_busy", label="route_hint")
    recs = [r for r in llm_activity.recent(limit=5) if r.get("skipped")]
    assert recs and recs[0]["skipped"] == "slot_busy"
    now = time.time()
    assert llm_activity.overlapping(now - 5, now + 1) == [] or all(
        not x.get("skipped") for x in llm_activity.overlapping(now - 5, now + 1))
