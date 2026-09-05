"""
DECOUPLE fallback'i yalnız TEK araçlık envanter turlarında çalışmalı.

Regresyon: "bir host arızalanırsa HA kapasitesi yeter mi?" sorusunda model
db_list_clusters + db_list_esx_hosts'u birlikte çağırdı; fallback son aracın
envanter tablosunu deterministik cevap sayıp bastı ve HA sorusu cevapsız
kaldı. Birden fazla farklı araç başarılıysa cevap LLM sentezine bırakılır.
"""
from __future__ import annotations

import pytest

from app.services import unified_tool_chat as utc
from app.services.agent.policy import RiskLevel


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.risk_level = RiskLevel.READ_ONLY
        self.domains = frozenset({"infra", "vcenter"})

    def preview(self, db, args, ctx):
        return f"{self.name} önizleme"

    def execute(self, db, args, ctx):
        if self.name == "db_list_clusters":
            return {"ok": True, "count": 0, "clusters": []}
        return {"ok": True, "hosts": [{"name": "esx01", "cpu_pct": 13.5}],
                "as_of": "2026-09-05T17:00:00"}


@pytest.fixture(autouse=True)
def _patch_agent_tools(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.tools.tool_specs_read_only",
        lambda domains=None: [
            {"type": "function", "function": {"name": "db_list_esx_hosts"}},
            {"type": "function", "function": {"name": "db_list_clusters"}},
        ],
    )
    monkeypatch.setattr("app.services.agent.tools.get_tool", lambda name: _FakeTool(name))
    monkeypatch.setattr("app.services.agent.tools.resolve_server", lambda db, args, ctx: None)
    monkeypatch.setattr("app.services.chat_tool_policy.should_use_db_first", lambda **kw: True)
    monkeypatch.setattr(
        "app.services.chat_tool_policy.result_needs_live_escalation",
        lambda name, result: False,
    )


def _run(question, tool_names):
    steps = {"n": 0}

    def _fake_chat_with_tools(model, messages, tools, timeout=90):
        steps["n"] += 1
        if steps["n"] == 1:
            return {
                "content": "", "error": None,
                "tool_calls": [
                    {"id": f"call_{i}", "name": n, "arguments": {}}
                    for i, n in enumerate(tool_names)
                ],
            }
        return {"content": "özet", "tool_calls": [], "error": None}

    import app.services.agent.llm as agent_llm
    orig = agent_llm.chat_with_tools
    agent_llm.chat_with_tools = _fake_chat_with_tools
    try:
        events = list(utc.run_read_only_tool_loop(
            db=None, model="m", user_message=question, context_str="",
            server_summary="", max_steps=3,
            domains=frozenset({"infra", "vcenter"}), platform="virt",
        ))
    finally:
        agent_llm.chat_with_tools = orig
    return [e for e in events if e.get("type") == "final"][0]


def test_multiple_tools_skip_deterministic_inventory_render():
    final = _run(
        "bir host arızalanırsa mevcut HA kapasitesiyle VM'ler yeniden başlatılabilir mi?",
        ["db_list_clusters", "db_list_esx_hosts"],
    )
    assert "deterministic_answer" not in final
    assert set(final["tools_used"]) == {"db_list_clusters", "db_list_esx_hosts"}
    assert "esx01" in final["tool_text"]


def test_single_inventory_tool_still_renders_deterministically():
    final = _run("esxi hostları listele", ["db_list_esx_hosts"])
    assert "ESXi Host Envanteri" in (final.get("deterministic_answer") or "")
