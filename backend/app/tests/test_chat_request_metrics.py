"""Sohbet istek ölçüm altyapısı — ring buffer + Ollama süre alanları."""
from __future__ import annotations

from app.services import chat_request_metrics as crm
from app.services.automic.prompt import prompt_variable_field_report


def test_metrics_lifecycle_and_ollama_stats():
    m = crm.start("automic", "Şu an kaç iş çalışıyor?")
    crm.set_intent("data")
    crm.begin_llm_turn("tool_selection")
    crm.record_ollama_stats({
        "prompt_eval_count": 1200,
        "prompt_eval_duration": 2_000_000_000,
        "eval_count": 40,
        "eval_duration": 500_000_000,
        "load_duration": 10_000_000,
        "total_duration": 2_600_000_000,
        "message": {"content": "", "thinking": "x" * 100},
    })
    crm.mark_empty_turn(tool_parse_error=False)
    crm.record_tool("automic_active", duration_ms=12.5, rows=3, chars=200, triggered_by="llm")
    crm.record_rag("automic", 4.2)
    payload = crm.finish(m)
    assert payload is not None
    assert payload["module"] == "automic"
    assert payload["intent"] == "data"
    assert payload["rag_ms"] == 4.2
    assert len(payload["llm_turns"]) == 1
    turn = payload["llm_turns"][0]
    assert turn["prompt_eval_count"] == 1200
    assert turn["prompt_eval_duration_ms"] == 2000.0
    assert turn["eval_count"] == 40
    assert turn["empty_turn"] is True
    assert turn["thinking_chars"] == 100
    assert payload["tools"][0]["triggered_by"] == "llm"
    got = crm.get_request(payload["request_id"])
    assert got and got["request_id"] == payload["request_id"]
    recent = crm.list_recent(module="automic", limit=5)
    assert any(x["request_id"] == payload["request_id"] for x in recent)


def test_prompt_variable_fields_report_positions():
    rows = prompt_variable_field_report()
    by_name = {r["name"]: r for r in rows}
    assert "CURRENT_TIME" in by_name
    # Adım 6b: dinamik alanların hepsi en sondaki çalışma zamanı bağlamında → prefix cache güvenli
    assert all(r["prefix_cache_safe"] == "yes" for r in rows), rows
    assert "11" in by_name["CURRENT_TIME"]["location"]
    assert "LLM_MODEL" in by_name
