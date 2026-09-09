"""Token tüketimi toplayıcısı (admin göstergesi)."""
import asyncio
import json

from app.services import llm_usage


def test_parse_openai_usage():
    parsed = llm_usage.parse_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    assert parsed == {"prompt_tokens": 100, "completion_tokens": 20}


def test_parse_ollama_usage():
    parsed = llm_usage.parse_usage({"prompt_eval_count": 7, "eval_count": 3, "done": True})
    assert parsed == {"prompt_tokens": 7, "completion_tokens": 3}


def test_parse_missing_usage_returns_none():
    assert llm_usage.parse_usage({"choices": [{"delta": {"content": "x"}}]}) is None
    assert llm_usage.parse_usage(None) is None


def test_no_snapshot_outside_scope():
    assert llm_usage.snapshot() is None


def test_multi_call_totals_accumulate():
    token = llm_usage.start()
    try:
        llm_usage.record({"usage": {"prompt_tokens": 1000, "completion_tokens": 50}})
        llm_usage.record({"usage": {"prompt_tokens": 1200, "completion_tokens": 80}})
        llm_usage.record({"choices": []})  # usage yok → yalnız kayıt sayacı artar
        snap = llm_usage.snapshot()
    finally:
        llm_usage.stop(token)

    assert snap["prompt_tokens"] == 2200
    assert snap["completion_tokens"] == 130
    assert snap["total_tokens"] == 2330
    # `calls` kullanıcıya "model çağrısı" olarak gösterilir: yalnızca usage
    # bildiren yanıtlar sayılır (akışta her SSE parçası sayılmaz).
    assert snap["calls"] == 2
    assert snap["reported_calls"] == 2
    assert snap["records"] == 3


def test_snapshot_none_when_provider_reports_nothing():
    token = llm_usage.start()
    try:
        llm_usage.record({"choices": [{"message": {"content": "hi"}}]})
        assert llm_usage.snapshot() is None
    finally:
        llm_usage.stop(token)


def _collect(agen):
    async def run():
        return [chunk async for chunk in agen]
    return asyncio.run(run())


def test_sse_injection_before_done():
    async def source():
        yield 'data: {"token": "a"}\n\n'
        yield 'data: {"done": true, "session_id": 5}\n\n'

    token = llm_usage.start()
    try:
        llm_usage.record({"usage": {"prompt_tokens": 10, "completion_tokens": 2}})
        out = _collect(llm_usage.sse_inject_before_done(source()))
    finally:
        llm_usage.stop(token)

    assert len(out) == 3
    injected = json.loads(out[1].split("data: ", 1)[1])
    assert injected["usage"]["total_tokens"] == 12
    assert json.loads(out[2].split("data: ", 1)[1])["done"] is True


def test_sse_injection_skipped_without_usage():
    async def source():
        yield 'data: {"done": true}\n\n'

    token = llm_usage.start()
    try:
        out = _collect(llm_usage.sse_inject_before_done(source()))
    finally:
        llm_usage.stop(token)
    assert len(out) == 1
