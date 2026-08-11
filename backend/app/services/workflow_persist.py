"""
LangGraph graph çalıştırmalarını PostgreSQL'e kalıcılaştıran ince katman.

Resmi langgraph PostgresSaver, sabitlediğimiz langgraph 0.2.76 (pydantic 2.5 uyumu
için) ile bağımlılık çakışması yaşadığından; aynı işlevi (dayanıklı workflow state
+ düğüm geçiş izi) sağlayan kendi Postgres kayıt mekanizmamızı kullanıyoruz.

`run_graph_persisted(...)`:
  • Benzersiz thread_id üretir, WorkflowRun(running) açar.
  • graph.stream ile düğüm düğüm ilerler, her düğümü steps'e işler.
  • Son state'i toplar, WorkflowRun'ı completed/error olarak kapatır.
  • Son state'i döndürür (graph.invoke ile aynı sonuç).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.workflow_run import WorkflowRun

logger = logging.getLogger(__name__)


def _summarize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """final_state'i şişirmemek için büyük/transient alanları kırparak özetler."""
    if not isinstance(state, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in state.items():
        if k in ("messages", "pending_tool_calls", "anomalies"):
            # Hacimli ham veriyi saklamak yerine sayısını tut.
            out[k + "_count"] = len(v) if isinstance(v, (list, tuple)) else None
        elif k in ("tool_text", "user_message", "context_str", "server_summary"):
            s = str(v) if v is not None else ""
            out[k] = (s[:800] + "…") if len(s) > 800 else s
        elif k == "result" and isinstance(v, dict):
            out["result"] = {kk: v.get(kk) for kk in ("status", "tool", "action_id", "answer")
                             if kk in v}
        else:
            out[k] = v
    return out


def run_graph_persisted(
    compiled_graph,
    inputs: Dict[str, Any],
    *,
    graph_name: str,
    db: Session,
    config: Optional[Dict[str, Any]] = None,
    session_id: Optional[int] = None,
    server_id: Optional[int] = None,
    actor_name: Optional[str] = None,
    audit_db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Graph'ı düğüm düğüm çalıştırır ve WorkflowRun olarak PostgreSQL'e kaydeder.

    db: graph düğümlerinin kullandığı Session (config configurable.db ile aynı olmalı).
    audit_db: WorkflowRun yazımı için ayrı session; verilmezse db kullanılır.
    """
    wf_db = audit_db or db
    thread_id = uuid.uuid4().hex[:16]

    run: Optional[WorkflowRun] = None
    try:
        run = WorkflowRun(
            graph_name=graph_name,
            thread_id=thread_id,
            status="running",
            session_id=session_id,
            server_id=server_id,
            actor_name=actor_name,
            input=_summarize_state(inputs),
            steps=[],
        )
        wf_db.add(run)
        wf_db.commit()
        wf_db.refresh(run)
    except Exception as e:
        logger.warning(f"[workflow] WorkflowRun açılamadı ({graph_name}): {e}")
        try:
            wf_db.rollback()
        except Exception:
            pass
        run = None

    steps: List[Dict[str, str]] = []
    final_state: Dict[str, Any] = {}
    cfg = dict(config or {})
    cfg.setdefault("configurable", {})["thread_id"] = thread_id

    try:
        # stream_mode="updates" → her düğümden sonra {node_name: state_delta}
        for update in compiled_graph.stream(inputs, config=cfg, stream_mode="updates"):
            if not isinstance(update, dict):
                continue
            for node_name, delta in update.items():
                steps.append({"node": node_name,
                              "ts": datetime.now(timezone.utc).isoformat()})
                if isinstance(delta, dict):
                    final_state.update(delta)

        # Son state'i toplamak için get_state yerine biriken delta yeterli;
        # ancak girdideki başlangıç alanlarını da koru.
        merged = {**inputs, **final_state}

        if run is not None:
            try:
                run.status = "completed"
                run.steps = steps
                run.final_state = _summarize_state(merged)
                run.phase = (merged.get("result") or {}).get("status") if isinstance(
                    merged.get("result"), dict) else (steps[-1]["node"] if steps else None)
                wf_db.commit()
            except Exception as e:
                logger.warning(f"[workflow] WorkflowRun kapatılamadı: {e}")
                wf_db.rollback()

        return merged

    except Exception as e:
        logger.error(f"[workflow] graph stream hatası ({graph_name}): {e}", exc_info=True)
        if run is not None:
            try:
                run.status = "error"
                run.steps = steps
                run.error = str(e)
                wf_db.commit()
            except Exception:
                wf_db.rollback()
        # Hata halinde çağırana yükselt — üst katman legacy fallback'e düşebilsin.
        raise
