"""Uzak LLM devre kesici + fail-fast davranışı."""
import pytest

from app.services import llm_availability as la


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    # Redis'e dokunmadan saf process-içi durum test edilir
    monkeypatch.setattr(la, "_redis", lambda: None)
    la.reset()
    yield
    la.reset()


def test_circuit_closed_by_default():
    assert la.is_open() is False


def test_circuit_opens_after_threshold():
    for _ in range(la.FAILURE_THRESHOLD - 1):
        la.record_failure("connect timeout")
    assert la.is_open() is False

    la.record_failure("connect timeout")
    assert la.is_open() is True
    assert la.snapshot()["circuit_open"] is True
    assert la.snapshot()["reopen_in_sec"] > 0


def test_success_closes_circuit():
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("boom")
    assert la.is_open() is True

    la.record_success()
    assert la.is_open() is False
    assert la.snapshot()["recent_failures"] == 0


def test_failures_outside_window_do_not_open(monkeypatch):
    la._cfg()   # runtime_settings okuması (kendi monotonic çağrısı) sahte saatten önce ısıtılır
    ticks = iter([0.0, 1000.0, 2000.0, 2000.0, 2000.0])
    monkeypatch.setattr(la.time, "monotonic", lambda: next(ticks))
    la.record_failure("a")
    la.record_failure("b")
    la.record_failure("c")
    assert la.is_open() is False


def test_friendly_error_never_suggests_local_model():
    msg = la.friendly_error("HTTP 502")
    assert "yerel modele aktarılmaz" in msg
    assert "HTTP 502" in msg
    # Kullanıcıya "yerele geçilsin mi?" sorusu sorulmaz
    assert "?" not in msg.split("(")[0]


@pytest.mark.parametrize(
    "status,expected",
    [(500, True), (502, True), (503, True), (429, True), (408, True),
     (400, False), (401, False), (404, False), (200, False)],
)
def test_retryable_status(status, expected):
    assert la.is_retryable_status(status) is expected


# ── Adım 3: best_effort + yoklamalı devre kesici + yarı açık ─────────────────────
import asyncio
import threading
import time

import requests

from app.core.config import settings
from app.services import llm_gateway, llm_transport


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture
def remote_timeouts(monkeypatch):
    """Uzak (OpenAI-uyumlu) LLM aktif; her istek ReadTimeout verir. Yerel Ollama'ya düşüş yok."""
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", True)
    monkeypatch.setattr(settings, "REMOTE_LLM_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "REMOTE_LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "REMOTE_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "REMOTE_LLM_VIRTUAL_KEY", "")
    monkeypatch.setattr(llm_transport, "get_transport_mode", lambda **_k: "openai")
    calls = {"n": 0}

    def _post(*_a, **_k):
        calls["n"] += 1
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=8.0)")

    monkeypatch.setattr(llm_gateway.requests, "post", _post)
    return calls


def test_best_effort_timeout_does_not_feed_circuit(remote_timeouts, monkeypatch):
    probes = []
    monkeypatch.setattr(la, "_probe_health", lambda: probes.append(1) or False)
    for _ in range(la.FAILURE_THRESHOLD + 3):
        res = llm_gateway.generate_sync(model="m", prompt="x", timeout=8.0, best_effort=True)
        assert res["response"] == "" and res["error"]
        # kullanıcıya dönük kibar mesaj üretilmez
        assert "yerel modele aktarılmaz" not in res["error"]
    assert la.snapshot()["recent_failures"] == 0
    assert la.is_open() is False
    assert probes == []
    assert remote_timeouts["n"] == la.FAILURE_THRESHOLD + 3     # çağrılar ağa gitti (devre kapalı)


def test_normal_call_timeouts_open_circuit_when_probe_fails(remote_timeouts, monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        res = llm_gateway.generate_sync(model="m", prompt="x", timeout=8.0)
        assert "yerel modele aktarılmaz" in res["error"]
    assert la.is_open() is True
    # devre açıkken ağa gidilmez (sessiz yerel düşüş de yok)
    n = remote_timeouts["n"]
    res = llm_gateway.generate_sync(model="m", prompt="x", timeout=8.0)
    assert res.get("remote_unavailable") and remote_timeouts["n"] == n


def test_best_effort_returns_fast_without_network_when_open(remote_timeouts, monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("ReadTimeout: x")
    assert la.is_open() is True
    n = remote_timeouts["n"]
    res = llm_gateway.generate_sync(model="m", prompt="x", best_effort=True)
    assert res["remote_unavailable"] and "yerel modele aktarılmaz" not in res["error"]
    assert remote_timeouts["n"] == n


def test_probe_ok_does_not_open_circuit(monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: True)
    for _ in range(la.FAILURE_THRESHOLD * 2):
        la.record_failure("ReadTimeout: yavaş")
    assert la.is_open() is False
    assert la.snapshot()["recent_failures"] < la.FAILURE_THRESHOLD    # eşikte sayaç sıfırlanır


def test_probe_failure_opens_circuit(monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("ReadTimeout: x")
    assert la.is_open() is True


def test_no_probe_target_opens_like_before(monkeypatch):
    """Uzak LLM etkin değil / yoklanamıyor (None) → eski davranış: eşikte aç."""
    monkeypatch.setattr(la, "_probe_health", lambda: None)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("boom")
    assert la.is_open() is True


@pytest.mark.parametrize("detail", [
    "ConnectError: [Errno 111] Connection refused",
    "ConnectionError: HTTPConnectionPool: Max retries exceeded (Caused by NewConnectionError('x'))",
    "ConnectTimeout: timed out",
    "SSLError: CERTIFICATE_VERIFY_FAILED",
    "gaierror: [Errno -2] Name or service not known",
])
def test_hard_connect_errors_open_without_probe(monkeypatch, detail):
    def _no_probe():
        raise AssertionError("bağlantı reddi/DNS/TLS'te yoklama gerekmez")

    monkeypatch.setattr(la, "_probe_health", _no_probe)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure(detail)
    assert la.is_open() is True


def test_read_timeout_is_not_hard_connect_error():
    assert not la._HARD_CONNECT_RE.search(
        "ReadTimeout: HTTPConnectionPool(host='x', port=11434): Read timed out. (read timeout=8.0)")


def test_half_open_probe_success_closes(monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("ReadTimeout: x")
    assert la.is_open() is True
    # OPEN_SEC doldu → ilk istekte tek yoklama; sunucu geri geldi → kapanır
    la._open_until = time.monotonic() - 1
    monkeypatch.setattr(la, "_probe_health", lambda: True)
    assert la.is_open() is False
    assert la.snapshot()["circuit_open"] is False and la.snapshot()["recent_failures"] == 0
    assert la.is_open() is False


def test_half_open_probe_failure_reopens(monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("ReadTimeout: x")
    la._open_until = time.monotonic() - 1
    assert la.is_open() is True          # yoklama başarısız → yeniden açıldı
    assert la.snapshot()["reopen_in_sec"] > 0


def test_half_open_probe_runs_once(monkeypatch):
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(la.FAILURE_THRESHOLD):
        la.record_failure("ReadTimeout: x")
    la._open_until = time.monotonic() - 1
    calls = []
    monkeypatch.setattr(la, "_probe_health", lambda: calls.append(1) or True)
    for _ in range(5):
        la.is_open()
    assert len(calls) == 1


def test_probe_result_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_transport, "probe_remote_health", lambda timeout=3.0: calls.append(1) or True)
    assert la._probe_health() is True
    assert la._probe_health() is True
    assert len(calls) == 1


def test_probe_none_is_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_transport, "probe_remote_health", lambda timeout=3.0: calls.append(1))
    assert la._probe_health() is None and la._probe_health() is None
    assert len(calls) == 2


def test_event_loop_does_not_block_on_probe(monkeypatch):
    """Olay döngüsünde yoklama arka plan iş parçacığında koşar; döngü bloklanmaz, devre sonra açılır."""
    gate = threading.Event()
    loop_threads = []

    def _slow_probe():
        loop_threads.append(threading.current_thread().name)
        gate.wait(2.0)
        return False

    monkeypatch.setattr(la, "_probe_health", _slow_probe)

    async def run():
        t0 = time.time()
        for _ in range(la.FAILURE_THRESHOLD):
            la.record_failure("ReadTimeout: x")
        elapsed = time.time() - t0
        return elapsed

    elapsed = asyncio.run(run())
    assert elapsed < 0.5                        # döngü yoklamayı beklemedi
    gate.set()
    assert _wait(la.is_open)
    assert loop_threads and loop_threads[0] == "llm-circuit-probe"


def test_single_probe_in_flight(monkeypatch):
    """Eşik aşıldıktan sonra gelen ek hatalar ikinci bir yoklama başlatmaz."""
    gate = threading.Event()
    calls = []

    def _slow():
        calls.append(1)
        gate.wait(2.0)
        return True

    monkeypatch.setattr(la, "_probe_health", _slow)

    async def run():
        for _ in range(la.FAILURE_THRESHOLD + 4):
            la.record_failure("ReadTimeout: x")

    asyncio.run(run())
    time.sleep(0.1)
    assert len(calls) == 1
    gate.set()


def test_route_hint_timeout_keeps_keyword_plan_and_does_not_feed_circuit(remote_timeouts, monkeypatch):
    from app.services.route_llm_hint import apply_route_llm_hint
    from app.services.module_orchestrator import ModulePlan

    plan = ModulePlan(
        mode="knowledge", modules=(), domains=frozenset({"infra"}),
        confidence=0.7, reason="no_module_signal",
    )
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    from app.services import route_llm_hint
    route_llm_hint.clear_cache()
    for i in range(la.FAILURE_THRESHOLD + 2):       # farklı turlar (farklı mesaj) — önbellek devreye girmez
        out = apply_route_llm_hint(f"sunucu neden ağır {i}", plan)
        assert out is plan or out.modules == plan.modules
    assert remote_timeouts["n"] >= la.FAILURE_THRESHOLD + 2
    assert la.snapshot()["recent_failures"] == 0
    assert la.is_open() is False


def test_cfg_defaults_match_previous_constants():
    thr, win, opn, prb = la._cfg()
    assert (thr, win, opn, prb) == (3, 60.0, 45.0, 3.0)


def test_cfg_reads_runtime_settings(monkeypatch):
    from app.services import runtime_settings as rts
    vals = {"llm_circuit_failure_threshold": 5, "llm_circuit_failure_window_sec": 30,
            "llm_circuit_open_sec": 10, "llm_circuit_probe_timeout_sec": 2}
    monkeypatch.setattr(rts, "get_int", lambda k: vals[k])
    la.reset()
    assert la._cfg() == (5, 30.0, 10.0, 2.0)
    monkeypatch.setattr(la, "_probe_health", lambda: False)
    for _ in range(4):
        la.record_failure("ReadTimeout: x")
    assert la.is_open() is False
    la.record_failure("ReadTimeout: x")
    assert la.is_open() is True


def test_runtime_settings_registered_with_same_defaults():
    from app.services.runtime_settings import ADVANCED_SCHEMA
    exp = {"llm_circuit_failure_threshold": 3, "llm_circuit_failure_window_sec": 60,
           "llm_circuit_open_sec": 45, "llm_circuit_probe_timeout_sec": 3}
    for k, v in exp.items():
        m = ADVANCED_SCHEMA[k]
        assert m["default"] == v and m["group"] == "llm_chat" and m["env"]
        assert m["min"] <= v <= m["max"]


def test_probe_remote_health_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "REMOTE_LLM_ENABLED", False)
    assert llm_transport.probe_remote_health() is None
