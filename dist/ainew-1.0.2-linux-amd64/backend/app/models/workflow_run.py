"""
Workflow çalıştırma kaydı — LangGraph graph'larının dayanıklı state'i (Postgres).

Her graph invoke'u (agent turu, AIOps döngüsü) bir WorkflowRun satırı oluşturur;
düğüm geçişleri `steps`'e, son durum `final_state`'e yazılır. Böylece workflow
state PostgreSQL'de kalıcı ve sorgulanabilir olur.
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, index=True)

    graph_name = Column(String(40), nullable=False, index=True)   # agent | aiops
    thread_id = Column(String(64), nullable=False, index=True)    # invoke başına benzersiz

    status = Column(String(20), default="running", index=True)    # running|completed|error
    phase = Column(String(40), nullable=True)                     # son düğüm / terminal durum (pending|done|...)

    session_id = Column(Integer, nullable=True, index=True)
    server_id = Column(Integer, nullable=True, index=True)
    actor_name = Column(String(100), nullable=True)

    input = Column(JSONB, nullable=True)         # invoke girdisi (özet)
    steps = Column(JSONB, nullable=True)         # düğüm yürütme izi [{node, ts}, ...]
    final_state = Column(JSONB, nullable=True)   # son state özeti
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
