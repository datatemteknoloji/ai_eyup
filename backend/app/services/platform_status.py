"""
Platform stack durumu — ainew + dropt container allowlist.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.services import docker_engine as docker

logger = logging.getLogger(__name__)

# Bilinen stack container adları (compose container_name)
KNOWN_CONTAINERS: List[Dict[str, str]] = [
    {"name": "server_management_backend", "group": "ainew", "role": "API", "critical": True},
    {"name": "server_management_worker", "group": "ainew", "role": "Celery worker", "critical": True},
    {"name": "server_management_frontend", "group": "ainew", "role": "UI (nginx)", "critical": True},
    {"name": "server_management_db", "group": "ainew", "role": "TimescaleDB", "critical": True},
    {"name": "server_management_redis", "group": "ainew", "role": "Redis", "critical": True},
    {"name": "server_management_prometheus", "group": "ainew", "role": "Prometheus", "critical": False},
    {"name": "server_management_pushgateway", "group": "ainew", "role": "Pushgateway", "critical": False},
    {"name": "server_management_ollama", "group": "ainew", "role": "Ollama LLM", "critical": False},
    {"name": "dropt_api", "group": "dropt", "role": "Level 1 API", "critical": False},
    {"name": "dropt_worker", "group": "dropt", "role": "Level 1 worker", "critical": False},
    {"name": "dropt_db", "group": "dropt", "role": "Level 1 Postgres", "critical": False},
    {"name": "dropt_redis", "group": "dropt", "role": "Level 1 Redis", "critical": False},
]

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

_KNOWN_BY_NAME = {c["name"]: c for c in KNOWN_CONTAINERS}


def allowed_names() -> Set[str]:
    return set(_KNOWN_BY_NAME.keys())


def resolve_allowed(name: str) -> Optional[str]:
    """Güvenli container adı doğrula; allowlist dışıysa None."""
    name = (name or "").strip().lstrip("/")
    if not _NAME_RE.match(name):
        return None
    if name not in _KNOWN_BY_NAME:
        return None
    return name


def _parse_started(state: Dict[str, Any]) -> Optional[str]:
    raw = state.get("StartedAt") or ""
    if not raw or raw.startswith("0001"):
        return None
    return raw


def _health_status(state: Dict[str, Any]) -> Optional[str]:
    health = state.get("Health") or {}
    if isinstance(health, dict):
        return health.get("Status")
    return None


def _status_label(state: Dict[str, Any]) -> str:
    if state.get("Running"):
        h = _health_status(state)
        if h == "unhealthy":
            return "unhealthy"
        if h == "starting":
            return "starting"
        return "running"
    if state.get("Restarting"):
        return "restarting"
    if state.get("Paused"):
        return "paused"
    if state.get("Dead"):
        return "dead"
    status = (state.get("Status") or "").lower()
    if "exited" in status or state.get("ExitCode") not in (None, 0) and not state.get("Running"):
        return "exited"
    return status or "unknown"


def capability() -> Dict[str, Any]:
    readable = docker.docker_sock_readable()
    writable = docker.docker_sock_writable()
    reasons: List[str] = []
    if not readable:
        reasons.append(f"Docker soketi okunamıyor: {docker.docker_sock()}")
    return {
        "available": readable,
        "restart_allowed": writable,
        "docker_sock": docker.docker_sock(),
        "reasons": reasons,
        "known_containers": [c["name"] for c in KNOWN_CONTAINERS],
    }


def list_stack_status() -> Dict[str, Any]:
    cap = capability()
    if not cap["available"]:
        return {
            **cap,
            "containers": [],
            "summary": {"total": 0, "running": 0, "unhealthy": 0, "missing": len(KNOWN_CONTAINERS)},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        raw = docker.list_containers(all_containers=True)
    except Exception as e:
        logger.warning("container list failed: %s", e)
        return {
            **cap,
            "available": False,
            "reasons": [str(e)[:300]],
            "containers": [],
            "summary": {"total": 0, "running": 0, "unhealthy": 0, "missing": len(KNOWN_CONTAINERS)},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    by_name: Dict[str, Dict[str, Any]] = {}
    for c in raw:
        for n in c.get("Names") or []:
            by_name[n.lstrip("/")] = c

    containers: List[Dict[str, Any]] = []
    running = 0
    unhealthy = 0
    missing = 0

    for meta in KNOWN_CONTAINERS:
        name = meta["name"]
        found = by_name.get(name)
        if not found:
            missing += 1
            containers.append({
                "name": name,
                "group": meta["group"],
                "role": meta["role"],
                "critical": meta["critical"],
                "present": False,
                "status": "missing",
                "health": None,
                "state": None,
                "image": None,
                "id": None,
                "started_at": None,
                "ports": [],
                "labels": {},
            })
            continue

        cid = found.get("Id") or ""
        try:
            detail = docker.inspect_container(cid)
        except Exception:
            detail = {}
        state = (detail.get("State") or {}) if isinstance(detail, dict) else {}
        status = _status_label(state)
        health = _health_status(state)
        if status == "running":
            running += 1
        if status == "unhealthy" or health == "unhealthy":
            unhealthy += 1

        ports_raw = found.get("Ports") or []
        ports = []
        for p in ports_raw:
            if not isinstance(p, dict):
                continue
            pub = p.get("PublicPort")
            priv = p.get("PrivatePort")
            if pub or priv:
                ports.append({
                    "private": priv,
                    "public": pub,
                    "type": p.get("Type") or "tcp",
                    "ip": p.get("IP") or "",
                })

        containers.append({
            "name": name,
            "group": meta["group"],
            "role": meta["role"],
            "critical": meta["critical"],
            "present": True,
            "status": status,
            "health": health,
            "state": state.get("Status"),
            "image": (found.get("Image") or (detail.get("Config") or {}).get("Image")),
            "id": cid[:12] if cid else None,
            "started_at": _parse_started(state),
            "ports": ports,
            "labels": {
                k: v for k, v in (found.get("Labels") or {}).items()
                if k.startswith("com.docker.compose.")
            },
        })

    return {
        **cap,
        "containers": containers,
        "summary": {
            "total": len(containers),
            "running": running,
            "unhealthy": unhealthy,
            "missing": missing,
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_container_id(name: str) -> str:
    safe = resolve_allowed(name)
    if not safe:
        raise ValueError("İzin verilmeyen veya geçersiz container adı")
    found = docker.find_container_by_name(safe)
    if not found or not found.get("Id"):
        raise ValueError(f"Container bulunamadı: {safe}")
    return found["Id"]
