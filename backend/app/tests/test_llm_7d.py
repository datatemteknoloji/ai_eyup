"""Adım 7d — run_id çözümleme, kanıtsız neden, eylem cevabı, bileşen hata gizleme."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import llm_chat_policy as lcp
from app.services.automic import why_answer as wa
from app.services.automic.components import build_components


def _tools_automic():
    import app.services.agent.tools  # noqa: F401 — döngüsel import zincirini tamamlar
    from app.services.agent import tools_automic as ta
    return ta


def test_execution_resolves_latest_failed_run_id(monkeypatch):
    ta = _tools_automic()
    captured = {}

    def fake_search(adb, system, **kw):
        captured.update(kw)
        return {"ok": True, "items": [{"run_id": 29900000001, "status_class": "failed", "client": 100}]}

    def fake_detail(adb, system, client, run_id, **kw):
        return {"ok": True, "execution": {"run_id": run_id, "status_class": "failed"}}

    monkeypatch.setattr("app.services.automic.queries.search_executions", fake_search)
    monkeypatch.setattr("app.services.automic.queries.execution_detail", fake_detail)
    monkeypatch.setattr(
        "app.services.automic.queries.find_run",
        lambda adb, system, run_id, client=None: {"client": 100, "run_id": run_id},
    )

    def fake_with_system(args, ctx, fn):
        return fn(MagicMock(), MagicMock())

    monkeypatch.setattr(ta, "_with_system", fake_with_system)
    out = ta._execution(MagicMock(), {"aspect": "detail", "object_name": "JOBS.ADV.INJECT.01"}, {})
    assert out["ok"] is True
    assert captured.get("status_class") == "failed"
    assert captured.get("sort") == "end_desc"


def test_execution_run_id_missing_friendly_error(monkeypatch):
    ta = _tools_automic()
    monkeypatch.setattr(
        "app.services.automic.queries.search_executions",
        lambda *a, **k: {"ok": True, "items": []},
    )

    def fake_with_system(args, ctx, fn):
        return fn(MagicMock(), MagicMock())

    monkeypatch.setattr(ta, "_with_system", fake_with_system)
    out = ta._execution(MagicMock(), {"aspect": "detail"}, {})
    assert out.get("code") == "run_id_missing"
    assert "RunID" in out.get("error", "")
    assert "run_id gerekli" not in out.get("error", "").lower()


def test_why_missing_evidence_markdown():
    structured = [{"tool": "automic_search_executions", "result": {"ok": True, "total": 0, "items": []}}]
    assert wa.is_why_without_evidence(structured)
    md = wa.missing_evidence_markdown(structured, english=False)
    assert "Kanıt yok" in md
    assert "hatalı çalışma" in md.lower()
    assert "Değerlendirme" not in md


def test_action_request_without_object_no_nesnenin():
    a = lcp.action_request_answer("şu işi hemen iptal et")
    assert "nesnenin" not in a
    assert "Şu an çalışan işleri" in a
    b = lcp.action_request_answer("JOBS.DWH.SYNC.01'i restart et")
    assert "son çalışmalarını" in b
    assert "nesnenin" not in b


def test_components_hide_run_id_gerekli():
    structured = [{
        "tool": "automic_execution",
        "args": {"aspect": "detail"},
        "result": {"ok": False, "error": "run_id gerekli"},
    }]
    comps = build_components(structured)
    assert len(comps) == 1
    assert comps[0]["type"] == "notice"
    assert "RunID" in comps[0]["text"]
    assert "run_id gerekli" not in comps[0]["text"].lower()

    structured.append({
        "tool": "automic_execution",
        "args": {},
        "result": {"ok": False, "error": "Connection refused", "code": "connect_failed"},
    })
    comps2 = build_components(structured)
    assert len(comps2) == 1


def test_user_message_password_masked_on_persist():
    from app.services.automic.masking import mask_text, masking_cfg_for_system

    cfg = masking_cfg_for_system(None)
    raw = "yeni şifre Test123 ile güncelle"
    masked = mask_text(raw, cfg)
    assert "Test123" not in masked
    assert "***" in masked
