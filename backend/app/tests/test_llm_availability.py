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
