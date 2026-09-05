"""unified_tool_chat.run_read_only_tool_loop — LLM hatasında kısmi sonuç kaybı.

Regresyon (üretim bulgusu): "Kapasite raporu göster" sorgusunda db-first
araç döngüsü 2 adımda başarıyla `db_list_esx_hosts` çağırdı (used_tools=True,
tools_used=["db_list_esx_hosts"]), ama 3. LLM turunda uzak gateway'den nested
dict hata gövdesi geldi (agent/llm.py: "'dict' object has no attribute
'lower'"). Eski kod bu durumda çıplak `{"type": "error"}` yield edip
dönüyordu — chat_source_graph bunun üstüne used_tools/tools_used/tool_text'i
sıfırlıyordu (tools_used=[] olarak loglandı) ve zaten toplanmış envanter
verisi (agentic_extra) fallback'e hiç aktarılmıyordu.

Bu test: bir adım başarılı tool çağrısı + ikinci adımda LLM hatası
senaryosunda `_finalize()` yoluna düşüldüğünü ve tool_text/tools_used/
used_tools'un korunduğunu doğrular.
"""
from __future__ import annotations

import pytest

from app.services import unified_tool_chat as utc
from app.services.agent.policy import RiskLevel


class _FakeTool:
    def __init__(self):
        self.risk_level = RiskLevel.READ_ONLY
        self.domains = frozenset({"infra", "vcenter"})

    def preview(self, db, args, ctx):
        return "DB ESXi host listesi"

    def execute(self, db, args, ctx):
        return {"ok": True, "hosts": [{"name": "esx01", "cpu_pct": 13.5}]}


@pytest.fixture(autouse=True)
def _patch_agent_tools(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.tools.tool_specs_read_only",
        lambda domains=None: [{"type": "function", "function": {"name": "db_list_esx_hosts"}}],
    )
    monkeypatch.setattr("app.services.agent.tools.get_tool", lambda name: _FakeTool())
    monkeypatch.setattr("app.services.agent.tools.resolve_server", lambda db, args, ctx: None)
    monkeypatch.setattr("app.services.chat_tool_policy.should_use_db_first", lambda **kw: True)
    monkeypatch.setattr(
        "app.services.chat_tool_policy.result_needs_live_escalation", lambda name, result: False
    )


def test_llm_error_after_tool_success_preserves_partial_result(monkeypatch):
    calls = {"n": 0}

    def _fake_chat_with_tools(model, messages, tools, timeout=90):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": "", "error": None,
                "tool_calls": [{"id": "call_1", "name": "db_list_esx_hosts", "arguments": {}}],
            }
        # Gerçek üretim bulgusu: nested-dict gateway hatası (agent/llm.py'de
        # ayrıca test edildi) — burada üst katmanın davranışı test ediliyor.
        return {"content": "", "tool_calls": [], "error": "'dict' object has no attribute 'lower'"}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", _fake_chat_with_tools)

    gen = utc.run_read_only_tool_loop(
        db=None, model="gpt-oss-120b", user_message="Kapasite raporu göster",
        context_str="", server_summary="", max_steps=6,
        domains=frozenset({"infra", "vcenter"}), platform="virt",
    )
    events = list(gen)
    finals = [e for e in events if e.get("type") == "final"]

    assert len(finals) == 1, f"final event bulunamadı: {events}"
    final = finals[0]
    assert final["used_tools"] is True
    assert final["tools_used"] == ["db_list_esx_hosts"]
    assert "esx01" in final["tool_text"]
    assert final.get("partial_due_to_llm_error") is True
    assert final.get("status_detail") == "'dict' object has no attribute 'lower'"


def test_llm_error_before_any_tool_call_still_skips(monkeypatch):
    """Hiç tool çağrılmadan LLM hata verirse eski davranış (skipped) korunmalı —
    kaybedilecek bir sonuç yok."""
    def _fake_chat_with_tools(model, messages, tools, timeout=90):
        return {"content": "", "tool_calls": [], "error": "Ollama'ya bağlanılamadı."}

    monkeypatch.setattr("app.services.agent.llm.chat_with_tools", _fake_chat_with_tools)

    gen = utc.run_read_only_tool_loop(
        db=None, model="gpt-oss-120b", user_message="Kapasite raporu göster",
        context_str="", server_summary="", max_steps=6,
        domains=frozenset({"infra", "vcenter"}), platform="virt",
    )
    events = list(gen)
    assert events[-1]["type"] == "skipped"
    assert events[-1]["reason"] == "Ollama'ya bağlanılamadı."
