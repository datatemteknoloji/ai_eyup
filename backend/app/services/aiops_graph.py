"""
AIOps LangGraph — kapalı döngü otomasyonun StateGraph hâli.

Akış (graph düğümleri):
    detect  → anomali tespiti (yalnızca anomaly verilmediyse)
    persist → anomalileri SystemEvent'e çevir, kritikleri incident'a bağla
    rca     → bekleyen otomatik incident'lar için AI RCA
    memory  → değişiklik olduysa incident/event kayıtlarını RAG hafızasına indeksle

Mevcut servis fonksiyonları (aiops_engine, anomaly_detector, rag_service) düğüm
olarak sarmalanır; iş mantığı değişmez, sadece orkestrasyon LangGraph'a taşınır.

DB Session düğümlere `config={"configurable": {"db": ...}}` üzerinden geçirilir,
böylece graph modül yüklenirken bir kez derlenir ve her tur yeniden kullanılır.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, START, END
from sqlalchemy.orm import Session

from app.services.aiops_engine import (
    persist_anomalies_as_events,
    auto_rca_pending_incidents,
)

logger = logging.getLogger(__name__)


class AIOpsState(TypedDict, total=False):
    anomalies: Optional[List[Dict[str, Any]]]
    persist_result: Dict[str, int]
    rca_done: int
    reindexed: Dict[str, int]


def _db_from_config(config) -> Session:
    db = (config or {}).get("configurable", {}).get("db")
    if db is None:
        raise RuntimeError("AIOps graph: db Session config içinde verilmedi")
    return db


# ── Düğümler ────────────────────────────────────────────────────────────────
def detect_node(state: AIOpsState, config) -> AIOpsState:
    """anomalies verilmediyse Prometheus/TimescaleDB üzerinden tespit yap."""
    if state.get("anomalies") is not None:
        return {}
    db = _db_from_config(config)
    from app.services.anomaly_detector import detect_all_anomalies
    anomalies = detect_all_anomalies(db)
    return {"anomalies": anomalies or []}


def persist_node(state: AIOpsState, config) -> AIOpsState:
    db = _db_from_config(config)
    anomalies = state.get("anomalies") or []
    result = persist_anomalies_as_events(db, anomalies)
    return {"persist_result": result}


def rca_node(state: AIOpsState, config) -> AIOpsState:
    db = _db_from_config(config)
    try:
        done = auto_rca_pending_incidents(db)
    except Exception as e:
        logger.error(f"[AIOps graph] Auto-RCA hatası: {e}")
        done = 0
    return {"rca_done": done}


def memory_node(state: AIOpsState, config) -> AIOpsState:
    """Değişiklik olduğunda incident/event/knowledge kayıtlarını RAG hafızasına indeksler."""
    db = _db_from_config(config)
    try:
        from app.services.rag_service import (
            ingest_incidents_from_db,
            ingest_events_from_db,
            ingest_knowledge_from_db,
        )

        async def _run() -> Dict[str, int]:
            n_inc = await ingest_incidents_from_db(db)
            n_evt = await ingest_events_from_db(db)
            n_kb = await ingest_knowledge_from_db(db)
            return {"incidents": n_inc, "events": n_evt, "knowledge": n_kb}

        # run_aiops_cycle executor thread'inde çalışır; burada yeni event loop güvenli.
        reindexed = asyncio.run(_run())
        logger.info(
            f"[AIOps graph] RAG hafıza güncellendi: "
            f"{reindexed['incidents']} incident, {reindexed['events']} event, "
            f"{reindexed['knowledge']} knowledge"
        )
        return {"reindexed": reindexed}
    except Exception as e:
        logger.error(f"[AIOps graph] RAG hafıza indeksleme hatası: {e}")
        return {"reindexed": {"incidents": 0, "events": 0, "knowledge": 0, "error": str(e)}}


# ── Koşullu yönlendirme ─────────────────────────────────────────────────────
def _should_reindex(state: AIOpsState) -> str:
    """Anlamlı bir değişiklik olduysa hafızayı güncelle, yoksa bitir."""
    pr = state.get("persist_result") or {}
    changed = bool(
        pr.get("created") or pr.get("incidents") or state.get("rca_done")
    )
    return "memory" if changed else END


# ── Graph derleme ───────────────────────────────────────────────────────────
def _build_graph():
    g = StateGraph(AIOpsState)
    g.add_node("detect", detect_node)
    g.add_node("persist", persist_node)
    g.add_node("rca", rca_node)
    g.add_node("memory", memory_node)

    g.add_edge(START, "detect")
    g.add_edge("detect", "persist")
    g.add_edge("persist", "rca")
    g.add_conditional_edges("rca", _should_reindex, {"memory": "memory", END: END})
    g.add_edge("memory", END)
    return g.compile()


# Modül yüklenirken bir kez derle.
aiops_app = _build_graph()


def run_aiops_graph(
    db: Session, anomalies: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    AIOps graph'ını çalıştırır ve aiops_engine.run_aiops_cycle ile uyumlu özet döner.

    anomalies=None verilirse graph kendi tespitini yapar (detect düğümü);
    background task zaten tespit ettiyse listeyi geçer ve çift tespit önlenir.
    """
    try:
        from app.services.workflow_persist import run_graph_persisted
        final = run_graph_persisted(
            aiops_app,
            {"anomalies": anomalies},
            graph_name="aiops",
            db=db,
            config={"configurable": {"db": db}},
            actor_name="system",
        )
    except Exception as e:
        # Workflow kaydı/stream başarısızsa düz invoke ile devam et (iş bozulmasın).
        logger.warning(f"[AIOps] workflow persistence atlandı, invoke'a düşüldü: {e}")
        final = aiops_app.invoke(
            {"anomalies": anomalies},
            config={"configurable": {"db": db}},
        )
    persist_result = final.get("persist_result") or {}
    return {
        **persist_result,
        "rca_done": final.get("rca_done", 0),
        "reindexed": final.get("reindexed"),
    }
