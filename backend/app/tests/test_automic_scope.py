"""Yanıt kapsamı deterministik üretilir (LLM yazmaz)."""
from app.services.automic.scope import build_scope, stub_meta


def test_scope_from_search_and_history():
    structured = [
        {"tool": "automic_search_executions", "result": {
            "ok": True, "clients": [100, 200], "from": "2026-10-09T10:00:00+00:00",
            "to": "2026-10-09T16:00:00+00:00", "total": 44, "data_source": "module_db"}},
        {"tool": "automic_history", "result": {
            "ok": True, "from": "2026-10-02T10:00:00+00:00", "to": "2026-10-09T16:30:00+00:00",
            "rows": [], "data_source": "executions"}},
    ]
    s = build_scope(structured, ["automic_search_executions", "automic_history", "automic_history"],
                    system_name="DEV", system_id=1, default_clients=[100],
                    status={"source_lag_sec": 600, "last_success_at": "2026-10-09T16:20:00+03:00"})
    assert s["clients"] == [100, 200] and s["record_count"] == 44
    # Altbilgi kullanıcı saat diliminde (7h: UTC→yerel kayması olmasın); UTC değerler ayrı alanda
    assert s["time_from_utc"] == "2026-10-02T10:00:00+00:00" and s["time_to_utc"] == "2026-10-09T16:30:00+00:00"
    assert s["time_from"] == "2026-10-02T13:00:00+03:00" and s["time_to"] == "2026-10-09T19:30:00+03:00"
    assert s["data_source"] == "db" and s["tools"] == ["automic_search_executions", "automic_history"]
    assert s["source_lag_sec"] == 600 and s["last_collection_at"].startswith("2026-10-09")
    assert s["partial"] is False and s["retention_limited"] is False


def test_scope_live_mixed_partial_and_aggregates():
    live = {"tool": "automic_search_executions", "result": {"ok": True, "data_source": "source_live", "total": 3,
                                                           "truncated": True}}
    db = {"tool": "automic_history", "result": {"ok": True, "data_source": "daily_aggregates", "rows": []}}
    assert build_scope([live])["data_source"] == "source" and build_scope([live])["partial"] is True
    s = build_scope([live, db])
    assert s["data_source"] == "mixed" and s["retention_limited"] is True


def test_scope_ignores_failed_results_and_uses_defaults():
    s = build_scope([{"tool": "automic_active", "result": {"ok": False, "error": "x", "total": 9}}],
                    default_clients=[1, 2], fallback=True)
    assert s["clients"] == [1, 2] and s["record_count"] is None and s["fallback_tools"] is True


def test_stub_meta_shape():
    m = stub_meta({"system": "X"})
    assert m["scope"] == {"system": "X"} and m["follow_ups"] == [] and m["severity"] == "info"
