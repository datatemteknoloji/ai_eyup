"""
NLQ Query Builder — parametreli SQLAlchemy ifadeleri (string-SQL concat yok).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, cast, desc, asc, exists, func, not_, or_, select
from sqlalchemy.orm import Query, Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.linux_inventory import (
    FilesystemMetric, LinuxInventory, OpenPort, PackageInventory, ServiceStatus,
)
from app.models.server import Server
from app.services.nlq.schema import FIELD_SOURCE


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _col_for_field(field: str):
    if field == "hostname":
        return func.coalesce(Server.hostname, Server.name)
    if field == "ip_address":
        return Server.ip_address
    if field == "environment":
        return Server.tier
    if field == "operating_system":
        return Server.os_type
    if field == "os_version":
        return Server.os_version
    if field == "kernel_version":
        return Server.kernel_version
    if field == "status":
        return Server.status
    if field == "datacenter":
        return LinuxInventory.datacenter
    if field == "application":
        return LinuxInventory.application
    if field == "application_owner":
        return LinuxInventory.application_owner
    if field == "uptime_seconds":
        return LinuxInventory.uptime_seconds
    if field == "uptime_days":
        return LinuxInventory.uptime_seconds  # compare after converting value
    if field == "boot_time":
        return LinuxInventory.boot_time
    if field == "cpu_usage_percent":
        return LinuxInventory.cpu_usage_percent
    if field == "memory_usage_percent":
        return LinuxInventory.memory_usage_percent
    if field == "disk_usage_percent":
        return LinuxInventory.disk_usage_percent
    if field == "swap_usage_percent":
        return LinuxInventory.swap_usage_percent
    if field == "cpu_iowait_percent":
        return LinuxInventory.cpu_iowait_percent
    if field == "disk_io_utilization_percent":
        return LinuxInventory.disk_io_utilization_percent
    if field == "network_rx_bytes_per_sec":
        return LinuxInventory.network_rx_bytes_per_sec
    if field == "network_tx_bytes_per_sec":
        return LinuxInventory.network_tx_bytes_per_sec
    if field == "last_patch_date":
        return LinuxInventory.last_patch_date
    if field == "last_reboot_date":
        return LinuxInventory.last_reboot_date
    if field == "collection_time":
        return LinuxInventory.collection_time
    if field == "collection_status":
        return LinuxInventory.collection_status
    raise ValueError(f"unknown field {field}")


def _cmp(col, op: str, value: Any) -> ColumnElement:
    if op == "=":
        return col == value
    if op == "!=":
        return col != value
    if op == ">":
        return col > value
    if op == ">=":
        return col >= value
    if op == "<":
        return col < value
    if op == "<=":
        return col <= value
    if op == "contains":
        return col.ilike(f"%{value}%")
    if op == "starts_with":
        return col.ilike(f"{value}%")
    if op == "ends_with":
        return col.ilike(f"%{value}")
    if op == "in":
        return col.in_(list(value))
    if op == "not_in":
        return ~col.in_(list(value))
    if op == "between":
        return col.between(value[0], value[1])
    if op == "is_null":
        return col.is_(None)
    if op == "is_not_null":
        return col.isnot(None)
    raise ValueError(f"unsupported op {op}")


def _relative_datetime(value: Any, op: str) -> Any:
    """If value is int/float days, interpret as now - days for reboot/patch windows."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _utc_now() - timedelta(days=float(value))
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _filter_clause(f: dict) -> ColumnElement:
    field = f["field"]
    op = f["operator"]
    value = f["value"]
    src = FIELD_SOURCE.get(field, "inventory")

    if field == "uptime_days":
        # value in days → seconds
        if op in ("between",):
            value = [float(value[0]) * 86400, float(value[1]) * 86400]
        elif op in ("in", "not_in"):
            value = [float(v) * 86400 for v in value]
        elif op not in ("is_null", "is_not_null"):
            value = float(value) * 86400
        col = LinuxInventory.uptime_seconds
        return _cmp(col, op, value)

    if field in ("last_reboot_date", "last_patch_date", "boot_time", "collection_time"):
        if op == "between" and isinstance(value, (list, tuple)):
            value = [_relative_datetime(value[0], op), _relative_datetime(value[1], op)]
        elif op not in ("is_null", "is_not_null", "in", "not_in"):
            value = _relative_datetime(value, op)
        # "son 30 gün içinde reboot" → last_reboot_date >= now-30d  (operator usually >=)
        col = _col_for_field(field)
        return _cmp(col, op, value)

    if src == "service":
        conds = []
        if field == "service_name":
            conds.append(_cmp(ServiceStatus.service_name, op, value))
        elif field == "service_status":
            # active_state: active/inactive/failed
            if op in ("=", "contains") and isinstance(value, str):
                v = value.lower()
                if v in ("not_running", "down", "inactive", "stopped", "çalışmıyor"):
                    return exists().where(and_(
                        ServiceStatus.server_id == Server.id,
                        ServiceStatus.active_state != "active",
                    ))
                if v in ("running", "active", "up", "çalışıyor"):
                    return exists().where(and_(
                        ServiceStatus.server_id == Server.id,
                        ServiceStatus.active_state == "active",
                    ))
            conds.append(_cmp(ServiceStatus.active_state, op, value))
        elif field == "service_enabled":
            conds.append(_cmp(ServiceStatus.enabled, op, value))
        return exists().where(and_(ServiceStatus.server_id == Server.id, *conds))

    if src == "filesystem" or field == "disk_usage_percent":
        # disk_usage_percent filter uses inventory summary OR max FS
        if field == "disk_usage_percent":
            # Prefer inventory.disk_usage_percent; also match any FS over threshold via OR
            inv = _cmp(LinuxInventory.disk_usage_percent, op, value)
            fs_exists = exists().where(and_(
                FilesystemMetric.server_id == Server.id,
                _cmp(FilesystemMetric.usage_percent, op, value),
            ))
            return or_(inv, fs_exists)
        return exists().where(and_(
            FilesystemMetric.server_id == Server.id,
            _cmp(FilesystemMetric.usage_percent, op, value),
        ))

    if src == "package":
        conds = []
        if field == "package_name":
            conds.append(_cmp(PackageInventory.package_name, op, value))
        elif field == "package_version":
            conds.append(_cmp(PackageInventory.package_version, op, value))
        return exists().where(and_(PackageInventory.server_id == Server.id, *conds))

    if src == "port" or field == "open_port":
        return exists().where(and_(
            OpenPort.server_id == Server.id,
            _cmp(OpenPort.port, op, value),
        ))

    col = _col_for_field(field)
    return _cmp(col, op, value)


def build_query(db: Session, validated: dict) -> Tuple[Query, str]:
    """
    Returns (SQLAlchemy query, sql_template_description for audit).
    Query yields rows of (Server, LinuxInventory|None).
    """
    q = (
        db.query(Server, LinuxInventory)
        .outerjoin(LinuxInventory, LinuxInventory.server_id == Server.id)
        .filter(Server.ai_ready == True)  # noqa: E712
    )

    clauses = []
    for f in validated.get("filters") or []:
        clauses.append(_filter_clause(f))
    if clauses:
        q = q.filter(and_(*clauses))

    sort = validated.get("sort")
    if sort:
        field = sort["field"]
        direction = sort["direction"]
        if field == "uptime_days":
            col = LinuxInventory.uptime_seconds
        elif FIELD_SOURCE.get(field) in ("service", "package", "port"):
            col = LinuxInventory.uptime_seconds  # fallback
        else:
            try:
                col = _col_for_field(field)
            except ValueError:
                col = LinuxInventory.uptime_seconds
        q = q.order_by(desc(col) if direction == "desc" else asc(col))
    else:
        q = q.order_by(desc(LinuxInventory.uptime_seconds).nullslast())

    limit = int(validated.get("limit") or 100)
    q = q.limit(limit)

    template = (
        "SELECT servers.*, linux_inventory.* FROM servers "
        "LEFT JOIN linux_inventory ON linux_inventory.server_id = servers.id "
        "WHERE ai_ready AND <validated_filters> "
        f"ORDER BY <sort> LIMIT {limit}"
    )
    return q, template
