"""data_status çıkarımı — yok / alınamadı / sorulmadı."""
from app.services.chat_data_status import (
    FAILED,
    NOT_QUERIED,
    SUCCESS,
    SUCCESS_EMPTY,
    TIMEOUT,
    annotate_payload,
    format_collect_line,
    infer_tool_status,
)
from app.services.unified_tool_chat import _tool_result_to_text


def test_ok_true_is_success():
    assert infer_tool_status({"ok": True, "vms": [{"name": "a"}]}) == SUCCESS


def test_empty_list_is_success_empty():
    assert infer_tool_status({"ok": True, "vms": []}) == SUCCESS_EMPTY


def test_ok_false_is_failed():
    assert infer_tool_status({"ok": False, "error": "bağlantı yok"}) == FAILED


def test_timeout_error_is_timeout():
    assert infer_tool_status({"ok": False, "error": "SSH zaman aşımı"}) == TIMEOUT
    assert infer_tool_status("collect timeout after 30s") == TIMEOUT


def test_forced_not_queried():
    assert infer_tool_status({"ok": False, "error": "x"}, forced=NOT_QUERIED) == NOT_QUERIED


def test_annotate_adds_status_without_clobber():
    out = annotate_payload({"ok": True, "vms": []})
    assert out["data_status"] == SUCCESS_EMPTY
    assert out["vms"] == []
    kept = annotate_payload({"ok": True, "data_status": "STALE", "vms": []})
    assert kept["data_status"] == "STALE"


def test_tool_result_text_includes_status():
    text = _tool_result_to_text({"ok": True, "vms": []})
    assert "SUCCESS_EMPTY" in text


def test_collect_line_format():
    line = format_collect_line("LINUX", "NOT_QUERIED", "hedef yok.")
    assert line.startswith("LINUX: STATUS=NOT_QUERIED")
    assert "hedef yok" in line
