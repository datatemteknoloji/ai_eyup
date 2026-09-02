"""
Agent LangGraph — iteratif tool-calling döngüsünün StateGraph hâli.

orchestrator._run_loop ile birebir aynı davranışı sağlar; tek fark akışın
LangGraph düğümleriyle ifade edilmesidir:

    llm_node   → LLM'e tool şeması ile sor; tool çağrısı yoksa final yanıtla biter
    tools_node → tool çağrılarını işle:
                   • read_only  → çalıştır, sonucu geri besle, döngü sürer
                   • ask_user   → AgentAction(awaiting_input) + DUR (kullanıcıya sor)
                   • mutating   → guard; engellenmezse AgentAction(pending) + DUR (onay)

İnsan onayı / soru durumlarında graph, _run_loop ile aynı terminal payload'ı
döndürür; böylece API katmanı (api/agent.py) değişmeden çalışır.

DB Session, model, ctx ve tool spec'leri config["configurable"] ile geçirilir.
Onay/yanıt sonrası süreklilik transcript'ten yeniden kurulur (kalıcı checkpoint
gerekmez) — bu da mevcut start_step temelli devam mantığıyla uyumludur.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from sqlalchemy.orm import Session

from app.models.agent_action import AgentAction
from app.services.agent import tools as tool_mod
from app.services.agent.guard import guard_command
from app.services.agent.llm import chat_with_tools
from app.services.agent.policy import RiskLevel
from app.services.agent.tools import resolve_server

logger = logging.getLogger(__name__)


class AgentGraphState(TypedDict, total=False):
    messages: List[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    step_no: int
    pending_tool_calls: List[Dict[str, Any]]
    result: Optional[Dict[str, Any]]


def _cfg(config):
    c = (config or {}).get("configurable", {})
    db: Session = c.get("db")
    if db is None:
        raise RuntimeError("Agent graph: db Session config içinde verilmedi")
    return db, c.get("model", ""), c.get("ctx", {})


# ── LLM düğümü ──────────────────────────────────────────────────────────────
def llm_node(state: AgentGraphState, config) -> AgentGraphState:
    from app.services.agent.orchestrator import MAX_STEPS

    db, model, ctx = _cfg(config)
    steps = state.get("steps", [])
    messages = state.get("messages", [])
    step_no = state.get("step_no", 0)

    if step_no >= MAX_STEPS:
        return {"result": {"status": "max_steps",
                           "answer": "Maksimum adım sayısına ulaşıldı.",
                           "steps": steps, "session_id": ctx.get("session_id")}}

    specs = tool_mod.tool_specs()
    llm = chat_with_tools(model, messages, specs)
    if llm["error"]:
        return {"result": {"status": "error", "error": llm["error"], "steps": steps,
                           "answer": "", "session_id": ctx.get("session_id")}}

    tool_calls = llm["tool_calls"]
    content = llm["content"]

    # Tool çağrısı yoksa → final yanıt.
    if not tool_calls:
        return {"result": {"status": "done", "answer": content or "(boş yanıt)",
                           "steps": steps, "session_id": ctx.get("session_id")}}

    # Asistanın tool isteğini transcript'e ekle (OpenAI: arguments STRING + id).
    messages = messages + [{
        "role": "assistant", "content": content,
        "tool_calls": [
            {
                "id": tc.get("id") or f"call_{i}_{tc.get('name') or 'tool'}",
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"] if isinstance(tc.get("arguments"), str)
                    else json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                },
            }
            for i, tc in enumerate(tool_calls)
        ],
    }]
    return {
        "messages": messages,
        "pending_tool_calls": tool_calls,
        "step_no": step_no + 1,
    }


# ── Tool düğümü ─────────────────────────────────────────────────────────────
def tools_node(state: AgentGraphState, config) -> AgentGraphState:
    from app.services.agent.orchestrator import _record_action, _requires_root_prompt

    db, model, ctx = _cfg(config)
    messages = list(state.get("messages", []))
    steps = list(state.get("steps", []))
    tool_calls = state.get("pending_tool_calls", [])

    for tc in tool_calls:
        name = tc["name"]
        args = tc["arguments"] or {}

        # ask_user → kullanıcıya seçenek sun ve DUR.
        if name == "ask_user":
            question = args.get("question") or "Lütfen seçim yapın"
            options = args.get("options") or []
            allow_multiple = bool(args.get("allow_multiple"))
            action = AgentAction(
                session_id=ctx.get("session_id"),
                tool_name="ask_user",
                arguments={"question": question, "options": options,
                           "allow_multiple": allow_multiple},
                risk_level="read_only",
                status="awaiting_input",
                preview=question,
                transcript=messages,
                model=model,
            )
            db.add(action)
            db.commit()
            db.refresh(action)
            steps.append({"type": "question", "question": question, "options": options,
                          "allow_multiple": allow_multiple, "action_id": action.id})
            return {"messages": messages, "steps": steps,
                    "result": {"status": "question", "action_id": action.id,
                               "question": question, "options": options,
                               "allow_multiple": allow_multiple, "steps": steps,
                               "session_id": ctx.get("session_id")}}

        tool = tool_mod.get_tool(name)
        if not tool:
            messages.append({"role": "tool", "name": name,
                             "content": json.dumps({"error": f"Bilinmeyen tool: {name}"})})
            steps.append({"type": "error", "tool": name, "detail": "bilinmeyen tool"})
            continue

        if tool.risk_level == RiskLevel.READ_ONLY:
            result = tool.execute(db, args, ctx)

            # Permission denied + sudo şifresi yok → onay akışıyla sor.
            if result.get("needs_sudo") and not ctx.get("sudo_password_override"):
                srv = resolve_server(db, args, ctx)
                action = AgentAction(
                    session_id=ctx.get("session_id"),
                    server_id=srv.id if srv else None,
                    tool_name="__needs_sudo__",
                    arguments={"tool": name, "args": args},
                    risk_level="read_only",
                    requires_root=True,
                    status="pending",
                    preview=f"Root yetkisi gerekiyor: {result.get('command', name)}",
                    transcript=messages,
                    model=model,
                )
                db.add(action); db.commit(); db.refresh(action)
                steps.append({"type": "approval_required", "tool": name, "args": args,
                              "preview": action.preview, "action_id": action.id,
                              "guard": {}, "requires_root": True})
                return {"messages": messages, "steps": steps,
                        "result": {"status": "pending", "action_id": action.id,
                                   "preview": action.preview, "tool": name,
                                   "requires_root": True, "needs_sudo": True,
                                   "steps": steps, "session_id": ctx.get("session_id")}}

            _record_action(db, ctx, tool, args, "executed", result=result, model=model)
            messages.append({"role": "tool", "name": name,
                             "content": json.dumps(result, ensure_ascii=False)[:8000]})
            steps.append({"type": "read_only", "tool": name, "args": args,
                          "preview": tool.preview(db, args, ctx), "result": result})
            continue

        # MUTATING → önce GUARD, sonra insan onayı.
        server = resolve_server(db, args, ctx)
        try:
            command_str = tool.build_command(args)
        except Exception as e:
            command_str = f"(komut oluşturulamadı: {e})"
        guard = guard_command(db, command_str, server.name if server else "?")

        if guard.get("decision") == "block":
            _record_action(db, ctx, tool, args, "blocked",
                           result={"guard": guard}, model=model)
            messages.append({"role": "tool", "name": name,
                             "content": json.dumps(
                                 {"blocked_by_guard": True, "reason": guard.get("reason", "")},
                                 ensure_ascii=False)})
            steps.append({"type": "blocked", "tool": name, "args": args,
                          "preview": tool.preview(db, args, ctx), "guard": guard})
            continue

        # Guard izin verdi → onay için DUR.
        requires_root = _requires_root_prompt(db, tool, command_str)
        action = _record_action(
            db, ctx, tool, args, "pending",
            result={"guard": guard}, transcript=messages, model=model,
            requires_root=requires_root,
        )
        steps.append({"type": "approval_required", "tool": name, "args": args,
                      "preview": action.preview, "action_id": action.id,
                      "guard": guard, "requires_root": requires_root})
        return {"messages": messages, "steps": steps,
                "result": {"status": "pending", "action_id": action.id,
                           "preview": action.preview, "tool": name, "args": args,
                           "guard": guard, "requires_root": requires_root,
                           "steps": steps, "session_id": ctx.get("session_id")}}

    # Tüm tool çağrıları işlendi, duraklama yok → döngüye dön.
    return {"messages": messages, "steps": steps, "pending_tool_calls": []}


# ── Yönlendirme ─────────────────────────────────────────────────────────────
def _after_llm(state: AgentGraphState) -> str:
    return END if state.get("result") else "tools"


def _after_tools(state: AgentGraphState) -> str:
    return END if state.get("result") else "llm"


def _build_graph():
    g = StateGraph(AgentGraphState)
    g.add_node("llm", llm_node)
    g.add_node("tools", tools_node)
    g.add_edge(START, "llm")
    g.add_conditional_edges("llm", _after_llm, {"tools": "tools", END: END})
    g.add_conditional_edges("tools", _after_tools, {"llm": "llm", END: END})
    return g.compile()


agent_app = _build_graph()


def run_agent_graph(
    db: Session, messages: List[Dict[str, Any]], model: str,
    ctx: Dict[str, Any], steps: List[Dict[str, Any]], start_step: int = 0,
) -> Dict[str, Any]:
    """orchestrator._run_loop'un LangGraph eşdeğeri. Aynı terminal payload'ı döner."""
    from app.services.agent.orchestrator import MAX_STEPS

    inputs = {"messages": messages, "steps": steps, "step_no": start_step,
              "pending_tool_calls": [], "result": None}
    config = {"configurable": {"db": db, "model": model, "ctx": ctx},
              "recursion_limit": MAX_STEPS * 3 + 10}

    server_ids = ctx.get("server_ids") or []
    try:
        from app.services.workflow_persist import run_graph_persisted
        final = run_graph_persisted(
            agent_app, inputs,
            graph_name="agent", db=db, config=config,
            session_id=ctx.get("session_id"),
            server_id=server_ids[0] if server_ids else None,
            actor_name=ctx.get("actor_name") or "system",
        )
    except Exception as e:
        logger.warning(f"[Agent] workflow persistence atlandı, invoke'a düşüldü: {e}")
        final = agent_app.invoke(inputs, config=config)
    result = final.get("result")
    if result:
        return result
    # Güvenlik ağı: result set edilmeden bittiyse (recursion limit vb.)
    return {"status": "max_steps", "answer": "Maksimum adım sayısına ulaşıldı.",
            "steps": final.get("steps", steps), "session_id": ctx.get("session_id")}
