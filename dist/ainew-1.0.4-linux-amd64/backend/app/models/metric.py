"""
Metric models for time-series data storage in TimescaleDB
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class MetricData(Base):
    """Time-series metric data (hypertable for TimescaleDB)"""
    __tablename__ = "metric_data"
    
    # Composite primary key for TimescaleDB hypertable
    id = Column(Integer, autoincrement=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name = Column(String(255), nullable=False, index=True)  # cpu_usage, memory_usage, disk_usage, etc.
    value = Column(Float, nullable=False)
    unit = Column(String(50))  # percent, bytes, count, etc.
    labels = Column(Text)  # JSON string for additional labels (disk=/dev/sda1, interface=eth0)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, primary_key=True)
    
    # Relationships
    server = relationship("Server")
    
    # Composite indexes for common queries
    __table_args__ = (
        Index('idx_metric_server_name_time', 'server_id', 'metric_name', 'timestamp'),
        Index('idx_metric_name_time', 'metric_name', 'timestamp'),
    )


class MetricAggregation(Base):
    """Pre-aggregated metrics for faster queries (hourly/daily summaries)"""
    __tablename__ = "metric_aggregations"
    
    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_name = Column(String(255), nullable=False, index=True)
    
    # Aggregation period
    period = Column(String(20), nullable=False, index=True)  # '1h', '1d', '1w'
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    
    # Aggregated values
    avg_value = Column(Float)
    min_value = Column(Float)
    max_value = Column(Float)
    sum_value = Column(Float)
    count = Column(Integer)
    
    unit = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    server = relationship("Server")
    
    __table_args__ = (
        Index('idx_agg_server_metric_period', 'server_id', 'metric_name', 'period', 'period_start'),
    )


class MetricThreshold(Base):
    """Metric thresholds for alerting"""
    __tablename__ = "metric_thresholds"
    
    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), index=True)  # NULL = global
    metric_name = Column(String(255), nullable=False, index=True)
    
    # Threshold configuration
    warning_threshold = Column(Float)
    critical_threshold = Column(Float)
    operator = Column(String(10), default='>')  # '>', '<', '>=', '<=', '==', '!='
    duration_seconds = Column(Integer, default=300)  # Alert if threshold exceeded for this duration
    
    enabled = Column(Integer, default=1)  # SQLite uses INTEGER for boolean
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    server = relationship("Server")
