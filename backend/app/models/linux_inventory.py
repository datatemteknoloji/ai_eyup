"""
Linux NL Inventory Query — merkezi snapshot tabloları.

Kimlik `servers` tablosunda kalır; bu tablolar server_id ile 1:1 / 1:N bağlanır.
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class LinuxInventory(Base):
    __tablename__ = "linux_inventory"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    fqdn = Column(String(500), nullable=True)
    datacenter = Column(String(100), nullable=True, index=True)
    application = Column(String(255), nullable=True, index=True)
    application_owner = Column(String(255), nullable=True)

    uptime_seconds = Column(BigInteger, nullable=True, index=True)
    boot_time = Column(DateTime(timezone=True), nullable=True, index=True)
    cpu_usage_percent = Column(Numeric(5, 2), nullable=True, index=True)
    memory_usage_percent = Column(Numeric(5, 2), nullable=True, index=True)
    disk_usage_percent = Column(Numeric(5, 2), nullable=True, index=True)
    load_average_1m = Column(Numeric(10, 2), nullable=True)
    load_average_5m = Column(Numeric(10, 2), nullable=True)
    load_average_15m = Column(Numeric(10, 2), nullable=True)

    # metric_data / Prometheus zenginleştirme (filtre edilebilir özet)
    swap_usage_percent = Column(Numeric(5, 2), nullable=True, index=True)
    cpu_iowait_percent = Column(Numeric(5, 2), nullable=True, index=True)
    disk_io_utilization_percent = Column(Numeric(5, 2), nullable=True)
    network_rx_bytes_per_sec = Column(Numeric(20, 2), nullable=True)
    network_tx_bytes_per_sec = Column(Numeric(20, 2), nullable=True)
    # Diğer Prom metrikleri (iops, steal, softirq, fd, procs...)
    metrics_extra = Column(JSON, nullable=True)

    last_patch_date = Column(DateTime(timezone=True), nullable=True)
    last_reboot_date = Column(DateTime(timezone=True), nullable=True)

    collection_time = Column(DateTime(timezone=True), nullable=False, index=True)
    collection_status = Column(String(30), nullable=True, index=True)  # success | failed | partial | unreachable
    collection_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FilesystemMetric(Base):
    __tablename__ = "filesystem_metrics"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    device = Column(String(255), nullable=True)
    mount_point = Column(String(500), nullable=True)
    filesystem_type = Column(String(100), nullable=True)
    total_bytes = Column(BigInteger, nullable=True)
    used_bytes = Column(BigInteger, nullable=True)
    available_bytes = Column(BigInteger, nullable=True)
    usage_percent = Column(Numeric(5, 2), nullable=True, index=True)
    collection_time = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_filesystem_metrics_server_usage", "server_id", "usage_percent"),
    )


class ServiceStatus(Base):
    __tablename__ = "service_status"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    service_name = Column(String(255), nullable=False, index=True)
    active_state = Column(String(50), nullable=True, index=True)
    sub_state = Column(String(50), nullable=True)
    enabled = Column(Boolean, nullable=True)
    collection_time = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_service_status_name_state", "service_name", "active_state"),
        UniqueConstraint("server_id", "service_name", name="uq_service_status_server_name"),
    )


class PackageInventory(Base):
    __tablename__ = "package_inventory"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    package_name = Column(String(255), nullable=False, index=True)
    package_version = Column(String(255), nullable=True)
    package_release = Column(String(100), nullable=True)
    architecture = Column(String(50), nullable=True)
    collection_time = Column(DateTime(timezone=True), nullable=False)


class OpenPort(Base):
    __tablename__ = "open_ports"

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)
    protocol = Column(String(20), nullable=True)
    local_address = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True, index=True)
    process_name = Column(String(255), nullable=True)
    pid = Column(Integer, nullable=True)
    collection_time = Column(DateTime(timezone=True), nullable=False)


class NlqQueryAudit(Base):
    __tablename__ = "nlq_query_audit"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username = Column(String(64), nullable=True)
    original_question = Column(Text, nullable=False)
    generated_query_json = Column(JSON, nullable=True)
    executed_sql_template = Column(Text, nullable=True)
    query_parameters = Column(JSON, nullable=True)
    result_count = Column(Integer, nullable=True)
    execution_duration_ms = Column(Integer, nullable=True)
    live_check_requested = Column(Boolean, default=False)
    status = Column(String(40), nullable=False, index=True)  # success | invalid_query | unsupported | error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
