"""Unit tests for NLQ builder / heuristic parse / formatter (no DB / no LLM)."""
from app.services.nlq.builder import _filter_clause
from app.services.nlq.formatter import format_answer
from app.services.nlq.parser import _heuristic_parse, detect_live_check_phrase
from app.services.nlq.validator import validate_query


def test_uptime_days_to_seconds_in_clause():
    clause = _filter_clause({"field": "uptime_days", "operator": ">", "value": 200})
    # SQLAlchemy binary expression; right-hand should be 200*86400
    assert clause.right.value == 200 * 86400


def test_builder_does_not_string_concat_sql():
    clause = _filter_clause({"field": "hostname", "operator": "contains", "value": "web"})
    s = str(clause)
    assert "'; DROP" not in s.upper()
    assert "coalesce" in s.lower() or "hostname" in s.lower()


def test_heuristic_tr_uptime():
    q = _heuristic_parse("200 günden fazla uptime olan sunucuları listele")
    assert q is not None
    assert q["intent"] == "search_servers"
    assert any(f["field"] == "uptime_days" and f["value"] == 200 for f in q["filters"])


def test_heuristic_disk_prod():
    q = _heuristic_parse("production ortamında disk kullanımı %85 üzeri sunucular")
    assert q is not None
    fields = {f["field"] for f in q["filters"]}
    assert "disk_usage_percent" in fields
    assert "environment" in fields


def test_live_phrase_detect():
    assert detect_live_check_phrase("şimdi doğrula uptime > 10 gün") is True
    assert detect_live_check_phrase("uptime 10 günden fazla") is False


def test_formatter_from_rows_only():
    validated = validate_query({
        "intent": "search_servers",
        "filters": [{"field": "uptime_days", "operator": ">", "value": 10}],
        "requested_columns": ["hostname", "uptime_days"],
    })
    md = format_answer(
        "test",
        validated,
        {
            "summary": {
                "total_found": 1,
                "unreachable_count": 0,
                "failed_collection_count": 0,
                "stale_data_count": 0,
                "stale_threshold_minutes": 30,
                "latest_collection_time": None,
            },
            "results": [{"hostname": "host-a", "uptime_days": 12.0}],
        },
    )
    assert "host-a" in md
    assert "**1** sunucu" in md


def test_stale_summary_keys_present():
    from app.services.nlq.schema import STALE_DATA_MINUTES
    assert STALE_DATA_MINUTES == 30
