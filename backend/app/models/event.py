"""
AIOps Event Models - SystemEvent, Alert, Incident, AnomalySuppression
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON, Float, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(String(100), nullable=False, index=True)  # cpu_high, memory_high, disk_full, service_down
    severity = Column(String(20), default="info", index=True)  # info, warning, critical, emergency
    source = Column(String(100))  # prometheus, ssh, agent, manual
    title = Column(String(500), nullable=False)
    description = Column(Text)
    raw_data = Column(JSON, default=dict)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(100))
    acknowledged_at = Column(DateTime(timezone=True))
    is_known = Column(Boolean, default=False)   # Bilgim Dahilinde
    known_by = Column(String(100))
    known_at = Column(DateTime(timezone=True))
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen  = Column(DateTime(timezone=True), server_default=func.now(), nullable=True, index=True)
    occurrence_count = Column(Integer, default=1)  # kaç kez tetiklendi

    server = relationship("Server", back_populates="events")

    # last_seen/created_at neredeyse her sorguda ">= since" ile filtrelenir
    # (ops_center, anomaly detection, log collector, RCA vb. — bkz. grep) ve
    # tekli index'leri eksikti; 288K+ satırlık tabloda bu her seferinde tam
    # tablo taraması demekti (DB CPU/IO üzerinden dolaylı "hang" kaynağı).
    # server_id+last_seen kombinasyonu da çok sık kullanıldığı için composite
    # index eklendi.
    __table_args__ = (
        Index("ix_system_events_server_last_seen", "server_id", "last_seen"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True, index=True)
    alert_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), default="warning", index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    metric_name = Column(String(200))
    metric_value = Column(Float)
    threshold_value = Column(Float)
    is_active = Column(Boolean, default=True, index=True)
    fired_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))

    server = relationship("Server", back_populates="alerts")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    severity = Column(String(20), default="warning", index=True)  # low, medium, high, critical
    status = Column(String(50), default="open", index=True)  # open, investigating, resolved, closed
    source = Column(String(100))  # auto_correlation, manual, alert
    affected_servers = Column(JSON, default=list)  # [server_id, ...]
    related_events = Column(JSON, default=list)  # [event_id, ...]
    root_cause = Column(Text)
    resolution = Column(Text)
    rca_result = Column(JSON, default=dict)  # AI RCA sonucu
    assigned_to = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True))


class BaselineMetric(Base):
    __tablename__ = "baseline_metrics"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    metric_name = Column(String(200), nullable=False, index=True)
    avg_value = Column(Float)
    min_value = Column(Float)
    max_value = Column(Float)
    std_dev = Column(Float)
    percentile_95 = Column(Float)
    sample_count = Column(Integer, default=0)
    period = Column(String(50))  # hourly, daily, weekly
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())


class AnomalySuppression(Base):
    """
    Sunucu + metrik bazında alarm bastırma / severity override kuralları.

    scope:
      'server'  → sadece bu sunucu için geçerli
      'global'  → tüm sunucular için geçerli (metric_name bazında)

    baseline_severity:
      None      → tamamen bastır (event oluşturma)
      'info'    → en fazla info seviyesinde oluştur
      'warning' → en fazla warning
    """
    __tablename__ = "anomaly_suppressions"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True, index=True)
    metric_name = Column(String(200), nullable=False, index=True)
    scope = Column(String(20), default="server")       # 'server' | 'global'
    reason = Column(Text)
    created_by = Column(String(100))
    baseline_value = Column(Float, nullable=True)      # normal değer referansı
    baseline_severity = Column(String(20), nullable=True)  # None=suppress, 'info', 'warning'
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    server = relationship("Server", foreign_keys=[server_id])


class RunbookExecution(Base):
    __tablename__ = "runbook_executions"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    runbook_name = Column(String(200), nullable=False)
    trigger_type = Column(String(50))  # manual, auto, scheduled
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    steps_total = Column(Integer, default=0)
    steps_completed = Column(Integer, default=0)
    output = Column(Text)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
