"""Admin-only system diagnostics (containers + recent jobs/audit)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, func, select

from app.api.deps import require_admin
from app.core.database import get_session
from app.models.job import AuditLog, Job
from app.models.user import User

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


def _docker_request(path: str, timeout: float = 5.0) -> Any | None:
    """Talk to Docker via unix socket if mounted."""
    sock = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
    if not os.path.exists(sock):
        return None
    try:
        import http.client
        import socket

        conn = http.client.HTTPConnection("localhost", timeout=timeout)
        conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.sock.settimeout(timeout)
        conn.sock.connect(sock)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        if resp.status >= 400:
            return None
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


@router.get("/overview")
def system_overview(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job_total = session.exec(select(func.count()).select_from(Job)).one()
    audit_total = session.exec(select(func.count()).select_from(AuditLog)).one()
    recent_jobs = session.exec(select(Job).order_by(col(Job.id).desc()).limit(10)).all()
    recent_audit = session.exec(select(AuditLog).order_by(col(AuditLog.id).desc()).limit(15)).all()

    containers = _docker_request("/containers/json?all=true") or []
    container_summaries = []
    for c in containers:
        names = c.get("Names") or []
        name = names[0].lstrip("/") if names else c.get("Id", "")[:12]
        if not any(x in name for x in ("api", "worker", "frontend", "db", "redis", "app-")):
            continue
        container_summaries.append(
            {
                "name": name,
                "state": c.get("State"),
                "status": c.get("Status"),
                "image": c.get("Image"),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "docker_available": bool(container_summaries) or _docker_request("/version") is not None,
        "counts": {"jobs": job_total, "audit": audit_total},
        "containers": container_summaries,
        "recent_jobs": [
            {
                "id": j.id,
                "title": j.title,
                "status": j.status.value if hasattr(j.status, "value") else j.status,
                "talep_id": j.talep_id,
                "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            }
            for j in recent_jobs
        ],
        "recent_audit": [
            {
                "id": a.id,
                "action": a.action,
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "username": a.username,
                "talep_id": a.talep_id,
                "message": (a.message or "")[:200],
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in recent_audit
        ],
    }


@router.get("/container-logs/{name}")
def container_logs(
    name: str,
    _admin: User = Depends(require_admin),
    tail: int = 120,
) -> dict[str, Any]:
    # Resolve container id by name
    containers = _docker_request("/containers/json?all=true") or []
    cid = None
    for c in containers:
        names = [n.lstrip("/") for n in (c.get("Names") or [])]
        if name in names or any(name in n for n in names):
            cid = c.get("Id")
            break
    if not cid:
        return {"available": False, "lines": [], "error": "Container bulunamadı veya Docker socket yok"}
    # logs endpoint returns multiplexed stream — keep simple: use JSON not available; raw text
    sock = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")
    try:
        import http.client
        import socket

        conn = http.client.HTTPConnection("localhost", timeout=8)
        conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.sock.settimeout(8)
        conn.sock.connect(sock)
        conn.request("GET", f"/containers/{cid}/logs?stdout=true&stderr=true&tail={min(tail, 400)}")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        # Strip docker stream headers roughly
        text = raw.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()][-tail:]
        return {"available": True, "name": name, "lines": lines}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "lines": [], "error": str(exc)}
