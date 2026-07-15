"""
NLQ allowlist schema — LLM yalnızca bu field/operator setini kullanabilir.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Set

ALLOWED_INTENTS = frozenset({"search_servers", "unsupported"})

ALLOWED_OPERATORS = frozenset({
    "=", "!=", ">", ">=", "<", "<=",
    "contains", "starts_with", "ends_with",
    "in", "not_in", "between",
    "is_null", "is_not_null",
})

# field -> python type hint for validation
FIELD_TYPES: Dict[str, str] = {
    "hostname": "string",
    "ip_address": "string",
    "environment": "string",
    "datacenter": "string",
    "application": "string",
    "application_owner": "string",
    "operating_system": "string",
    "os_version": "string",
    "kernel_version": "string",
    "uptime_seconds": "number",
    "uptime_days": "number",
    "boot_time": "datetime",
    "cpu_usage_percent": "number",
    "memory_usage_percent": "number",
    "disk_usage_percent": "number",
    "last_patch_date": "datetime",
    "last_reboot_date": "datetime",
    "collection_time": "datetime",
    "collection_status": "string",
    "service_name": "string",
    "service_status": "string",
    "service_enabled": "boolean",
    "package_name": "string",
    "package_version": "string",
    "open_port": "number",
    "status": "string",  # servers.status ONLINE etc.
}

ALLOWED_FIELDS: FrozenSet[str] = frozenset(FIELD_TYPES.keys())

DEFAULT_LIMIT = 100
HARD_MAX_LIMIT = 500
STALE_DATA_MINUTES = 30

DEFAULT_COLUMNS = [
    "hostname",
    "ip_address",
    "environment",
    "uptime_days",
    "boot_time",
    "collection_time",
    "collection_status",
]

# Query field -> (source, sql_expr key)
# source: server | inventory | filesystem | service | package | port
FIELD_SOURCE: Dict[str, str] = {
    "hostname": "server",
    "ip_address": "server",
    "environment": "server",
    "operating_system": "server",
    "os_version": "server",
    "kernel_version": "server",
    "status": "server",
    "datacenter": "inventory",
    "application": "inventory",
    "application_owner": "inventory",
    "uptime_seconds": "inventory",
    "uptime_days": "inventory",  # computed
    "boot_time": "inventory",
    "cpu_usage_percent": "inventory",
    "memory_usage_percent": "inventory",
    "disk_usage_percent": "inventory",
    "last_patch_date": "inventory",
    "last_reboot_date": "inventory",
    "collection_time": "inventory",
    "collection_status": "inventory",
    "service_name": "service",
    "service_status": "service",
    "service_enabled": "service",
    "package_name": "package",
    "package_version": "package",
    "open_port": "port",
}

STRING_OPS = frozenset({"=", "!=", "contains", "starts_with", "ends_with", "in", "not_in", "is_null", "is_not_null"})
NUMBER_OPS = frozenset({"=", "!=", ">", ">=", "<", "<=", "in", "not_in", "between", "is_null", "is_not_null"})
BOOL_OPS = frozenset({"=", "!=", "is_null", "is_not_null"})
DATETIME_OPS = frozenset({"=", "!=", ">", ">=", "<", "<=", "between", "is_null", "is_not_null"})

INJECTION_PATTERNS = (
    ";", "--", "/*", "*/", " xp_", " sp_", "drop table", "drop database",
    "insert into", "update ", "delete from", "alter table", "create table",
    "truncate ", "union select", "pg_sleep", "information_schema",
    "pg_catalog", " into outfile", "load_file",
    "ignore previous", "system prompt", "disregard instructions",
)


def operators_for_type(ftype: str) -> Set[str]:
    if ftype == "string":
        return set(STRING_OPS)
    if ftype == "number":
        return set(NUMBER_OPS)
    if ftype == "boolean":
        return set(BOOL_OPS)
    if ftype == "datetime":
        return set(DATETIME_OPS)
    return set(ALLOWED_OPERATORS)
