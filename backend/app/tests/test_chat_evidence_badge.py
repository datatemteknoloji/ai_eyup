from app.services.chat_evidence_badge import (
    HIGH,
    HIDDEN,
    LOW,
    MEDIUM,
    collect_had_failure,
    evidence_sse_field,
    merge_evidence_meta,
    score_evidence_badge,
)


def test_knowledge_and_chitchat_hidden():
    assert score_evidence_badge(kind="chitchat")["level"] == HIDDEN
    assert score_evidence_badge(kind="knowledge")["level"] == HIDDEN
    assert score_evidence_badge(kind="planning")["level"] == HIDDEN
    assert score_evidence_badge(kind="planning_clarify")["level"] == HIDDEN
    assert evidence_sse_field(score_evidence_badge(kind="knowledge")) == {}



def test_deterministic_high():
    b = score_evidence_badge(kind="deterministic")
    assert b["level"] == HIGH
    assert "deterministik" in b["reason"]


def test_cache_is_medium_not_high():
    assert score_evidence_badge(kind="cache")["level"] == MEDIUM


def test_live_with_tools_and_evidence_high():
    b = score_evidence_badge(
        kind="live",
        tools_used=["db_list_vms"],
        has_tool_text=True,
        has_evidence=True,
    )
    assert b["level"] == HIGH


def test_no_data_despite_evidence_is_low():
    b = score_evidence_badge(
        kind="live",
        tools_used=["db_list_vms"],
        has_tool_text=True,
        has_evidence=True,
        answer_no_data=True,
    )
    assert b["level"] == LOW


def test_live_without_any_evidence_is_low():
    b = score_evidence_badge(kind="live")
    assert b["level"] == LOW
    assert "kanıt yok" in b["reason"]


def test_collect_only_is_medium():
    b = score_evidence_badge(kind="live", has_collect=True)
    assert b["level"] == MEDIUM


def test_collect_failure_is_low():
    assert collect_had_failure("LINUX: STATUS=TIMEOUT x")
    b = score_evidence_badge(kind="live", collect_failed=True)
    assert b["level"] == LOW


def test_merge_skips_hidden():
    meta = merge_evidence_meta({"usage": {"total_tokens": 3}}, {"level": HIDDEN, "reason": "x"})
    assert "evidence" not in meta
    meta2 = merge_evidence_meta({"usage": {"total_tokens": 3}}, {"level": LOW, "reason": "y"})
    assert meta2["evidence"]["level"] == LOW
    assert meta2["usage"]["total_tokens"] == 3
