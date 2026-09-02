"""
Chat source-routing — ince LangGraph (virt / DB-first).

İş mantığı `chat_tool_policy` + `unified_tool_chat.run_read_only_tool_loop` içinde
kalır. Bu graph yalnızca karar + yürütme + WorkflowRun izi için sarmalar:

    decide_source → execute_tools → finalize

İlk tüketici: HypervisorChat (virt). Unified SSE yolu aynı generator API'yi
doğrudan kullanmaya devam eder; graph sync özet döner.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ChatSourceState(TypedDict, total=False):
    user_message: str
    model: str
    context_str: str
    server_summary: str
    max_steps: int
    platform: str
    domains: List[str]
    planning_mode: bool
    planning_depth: bool
    # karar / sonuç
    db_first: bool
    used_tools: bool
    live_escalated: bool
    tools_used: List[str]
    tool_text: str
    deterministic_answer: str
    inventory_kind: str
    status: str  # ok | skipped | error
    detail: str


def _db_from_config(config) -> Session:
    db = (config or {}).get("configurable", {}).get("db")
    if db is None:
        raise RuntimeError("chat_source graph: db Session config içinde verilmedi")
    return db


def decide_source_node(state: ChatSourceState, config) -> ChatSourceState:
    from app.services.chat_tool_policy import should_use_db_first

    domains_list = state.get("domains") or []
    domains_fs = frozenset(domains_list) if domains_list else None
    plat = (state.get("platform") or "").strip().lower()
    db_first = should_use_db_first(platform=plat, domains=domains_fs)
    logger.info(
        "[chat_source] decide platform=%s db_first=%s domains=%s",
        plat or "?",
        db_first,
        domains_list,
    )
    return {"db_first": db_first, "status": "ok"}


def execute_tools_node(state: ChatSourceState, config) -> ChatSourceState:
    db = _db_from_config(config)
    from app.services.unified_tool_chat import run_read_only_tool_loop

    domains_list = state.get("domains") or []
    domains_fs = frozenset(domains_list) if domains_list else None
    tool_text = ""
    tools_used: List[str] = []
    used_tools = False
    live_escalated = False
    status = "ok"
    detail = ""
    deterministic_answer = ""
    inventory_kind = ""

    try:
        gen = run_read_only_tool_loop(
            db,
            state.get("model") or "",
            state.get("user_message") or "",
            state.get("context_str") or "",
            state.get("server_summary") or "",
            max_steps=int(state.get("max_steps") or 6),
            domains=domains_fs,
            platform=state.get("platform"),
            planning_mode=bool(state.get("planning_mode")),
            planning_depth=bool(state.get("planning_depth")),
        )
        for item in gen:
            t = item.get("type")
            if t == "final":
                tool_text = item.get("tool_text") or ""
                tools_used = list(item.get("tools_used") or [])
                used_tools = bool(item.get("used_tools"))
                live_escalated = bool(item.get("live_escalated"))
                deterministic_answer = item.get("deterministic_answer") or ""
                inventory_kind = item.get("inventory_kind") or ""
                break
            if t == "skipped":
                status = "skipped"
                detail = str(item.get("reason") or "skipped")
                break
            if t == "error":
                status = "error"
                detail = str(item.get("detail") or "error")
                break
    except Exception as e:
        logger.warning("[chat_source] execute_tools hata: %s", e, exc_info=True)
        return {
            "status": "error",
            "detail": str(e),
            "used_tools": False,
            "tools_used": [],
            "tool_text": "",
            "live_escalated": False,
            "deterministic_answer": "",
            "inventory_kind": "",
        }

    return {
        "status": status,
        "detail": detail,
        "used_tools": used_tools,
        "tools_used": tools_used,
        "tool_text": tool_text,
        "live_escalated": live_escalated,
        "deterministic_answer": deterministic_answer,
        "inventory_kind": inventory_kind,
    }


def finalize_node(state: ChatSourceState, config) -> ChatSourceState:
    text = state.get("tool_text") or ""
    if len(text) > 48000:
        text = text[:48000]
    return {
        "tool_text": text,
        "status": state.get("status") or "ok",
        "deterministic_answer": state.get("deterministic_answer") or "",
        "inventory_kind": state.get("inventory_kind") or "",
    }


def _build_graph():
    g = StateGraph(ChatSourceState)
    g.add_node("decide_source", decide_source_node)
    g.add_node("execute_tools", execute_tools_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "decide_source")
    g.add_edge("decide_source", "execute_tools")
    g.add_edge("execute_tools", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


chat_source_app = _build_graph()


def run_chat_source_graph(
    db: Session,
    *,
    model: str,
    user_message: str,
    context_str: str = "",
    server_summary: str = "",
    max_steps: int = 6,
    platform: Optional[str] = None,
    domains: Optional[frozenset] = None,
    planning_mode: bool = False,
    planning_depth: bool = False,
    actor_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sync çalıştırır; unified_tool_chat final event ile uyumlu özet döner:
      used_tools, tool_text, tools_used, db_first, live_escalated, status, detail
    """
    inputs: ChatSourceState = {
        "user_message": user_message,
        "model": model,
        "context_str": context_str or "",
        "server_summary": server_summary or "",
        "max_steps": max_steps,
        "platform": (platform or "").strip().lower(),
        "domains": sorted(domains) if domains else [],
        "planning_mode": planning_mode,
        "planning_depth": planning_depth,
    }
    cfg = {"configurable": {"db": db}}
    try:
        from app.services.workflow_persist import run_graph_persisted

        final = run_graph_persisted(
            chat_source_app,
            dict(inputs),
            graph_name="chat_source",
            db=db,
            config=cfg,
            actor_name=actor_name or "chat",
        )
    except Exception as e:
        logger.warning("[chat_source] workflow persistence atlandı: %s", e)
        final = chat_source_app.invoke(dict(inputs), config=cfg)

    return {
        "type": "final",
        "used_tools": bool(final.get("used_tools")),
        "tool_text": final.get("tool_text") or "",
        "tools_used": list(final.get("tools_used") or []),
        "db_first": bool(final.get("db_first")),
        "live_escalated": bool(final.get("live_escalated")),
        "status": final.get("status") or "ok",
        "detail": final.get("detail") or "",
        "deterministic_answer": final.get("deterministic_answer") or "",
        "inventory_kind": final.get("inventory_kind") or "",
    }
