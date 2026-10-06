"""Level 1 dashboard özeti — bağlı kullanıcılar, son işlem yapılan sunucular, son işlemler, istatistik."""
from __future__ import annotations

from collections import Counter, OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session, col, func, select

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.job import AuditLog, Job, JobStatus
from app.models.security import PortalSession
from app.models.server import ServerStatus, TargetServer
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ONLINE_WINDOW_MIN = 15
RECENT_USER_HOURS = 24


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _status(v: Any) -> str:
    return getattr(v, "value", v) or ""


@router.get("")
def level1_dashboard(
    me: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    now = _now()
    online_since = now - timedelta(minutes=ONLINE_WINDOW_MIN)
    recent_since = now - timedelta(hours=RECENT_USER_HOURS)
    d1 = now - timedelta(hours=24)
    d7 = now - timedelta(days=7)

    # ── Bağlı kullanıcılar ────────────────────────────────────────────────
    sess_rows = session.exec(
        select(PortalSession)
        .where(col(PortalSession.revoked_at).is_(None))
        .where(PortalSession.absolute_expires_at > now)
        .where(PortalSession.last_seen_at >= recent_since)
        .order_by(col(PortalSession.last_seen_at).desc())
    ).all()
    roles = {u.username: _status(u.role) for u in session.exec(select(User)).all()}
    users: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for s in sess_rows:
        u = users.get(s.username)
        if u is None:
            users[s.username] = {
                "username": s.username,
                "role": roles.get(s.username, ""),
                "last_seen_at": _iso(s.last_seen_at),
                "login_at": _iso(s.created_at),
                "online": s.last_seen_at >= online_since,
                "sessions": 1,
                "is_me": s.username == me.username,
            }
        else:
            u["sessions"] += 1
            if s.created_at and (u["login_at"] is None or _iso(s.created_at) < u["login_at"]):
                u["login_at"] = _iso(s.created_at)

    # ── Son işlem yapılan sunucular (audit) ──────────────────────────────
    audit_rows = session.exec(
        select(AuditLog)
        .where(col(AuditLog.target_server_id).is_not(None))
        .order_by(col(AuditLog.id).desc())
        .limit(400)
    ).all()
    recent_servers: "OrderedDict[int, dict[str, Any]]" = OrderedDict()
    for a in audit_rows:
        sid = int(a.target_server_id)  # type: ignore[arg-type]
        if sid in recent_servers:
            recent_servers[sid]["op_count"] += 1
            continue
        if len(recent_servers) >= 8:
            continue
        recent_servers[sid] = {
            "server_id": sid,
            "hostname": a.hostname,
            "ip": a.ip,
            "last_action": a.action,
            "last_status": _status(a.status),
            "last_message": (a.message or "")[:160],
            "username": a.username,
            "at": _iso(a.created_at),
            "op_count": 1,
        }

    # ── Son işlemler (job) ────────────────────────────────────────────────
    jobs = session.exec(select(Job).order_by(col(Job.id).desc()).limit(10)).all()
    ids: set[int] = set()
    for j in jobs:
        for sid in j.server_ids or []:
            try:
                ids.add(int(sid))
            except (TypeError, ValueError):
                pass
    host_map: dict[int, str] = {}
    if ids:
        host_map = {
            int(s.id): s.hostname  # type: ignore[arg-type]
            for s in session.exec(select(TargetServer).where(col(TargetServer.id).in_(list(ids)))).all()
        }
    recent_ops = [
        {
            "id": j.id,
            "title": j.title or f"{j.module}/{j.action}",
            "module": j.module,
            "action": j.action,
            "status": _status(j.status),
            "dry_run": bool(j.dry_run),
            "username": j.created_by_username,
            "at": _iso(j.created_at),
            "finished_at": _iso(j.finished_at),
            "hosts": [host_map.get(int(x), str(x)) for x in (j.server_ids or [])[:3] if str(x).isdigit()],
            "host_count": len(j.server_ids or []),
            "error": (j.error_message or "")[:160],
        }
        for j in jobs
    ]

    # ── İstatistikler ─────────────────────────────────────────────────────
    jobs_7d = session.exec(select(Job).where(Job.created_at >= d7)).all()
    by_status_24h: Counter[str] = Counter()
    by_status_7d: Counter[str] = Counter()
    operators: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    daily: dict[str, dict[str, int]] = {}
    for i in range(6, -1, -1):
        daily[(now - timedelta(days=i)).strftime("%Y-%m-%d")] = {"success": 0, "failed": 0, "other": 0}
    for j in jobs_7d:
        st = _status(j.status)
        by_status_7d[st] += 1
        if j.created_at and j.created_at >= d1:
            by_status_24h[st] += 1
        operators[j.created_by_username] += 1
        actions[f"{j.module}/{j.action}"] += 1
        day = j.created_at.strftime("%Y-%m-%d") if j.created_at else ""
        if day in daily:
            key = "success" if st == "success" else "failed" if st in ("failed", "partial") else "other"
            daily[day][key] += 1
    done_7d = by_status_7d["success"] + by_status_7d["failed"] + by_status_7d["partial"]
    success_rate = round(by_status_7d["success"] * 100 / done_7d) if done_7d else None

    srv_total = session.exec(select(func.count()).select_from(TargetServer)).one()
    srv_by: dict[str, int] = {
        _status(k): int(v)
        for k, v in session.exec(select(TargetServer.status, func.count()).group_by(TargetServer.status)).all()
    }
    problem_servers = session.exec(
        select(TargetServer)
        .where(TargetServer.status.in_([ServerStatus.unreachable, ServerStatus.unknown]))  # type: ignore[attr-defined]
        .order_by(col(TargetServer.updated_at).desc())
        .limit(6)
    ).all()
    failed_recent = session.exec(
        select(Job)
        .where(Job.created_at >= d1)
        .where(Job.status.in_([JobStatus.failed, JobStatus.partial]))  # type: ignore[attr-defined]
        .order_by(col(Job.id).desc())
        .limit(5)
    ).all()

    return {
        "generated_at": _iso(now),
        "online_window_minutes": ONLINE_WINDOW_MIN,
        "users": list(users.values()),
        "recent_servers": list(recent_servers.values()),
        "recent_ops": recent_ops,
        "stats": {
            "jobs_24h": sum(by_status_24h.values()),
            "jobs_7d": sum(by_status_7d.values()),
            "running_now": by_status_7d["running"],
            "failed_24h": by_status_24h["failed"] + by_status_24h["partial"],
            "success_rate_7d": success_rate,
            "by_status_7d": dict(by_status_7d),
            "servers_total": int(srv_total),
            "servers_by_status": srv_by,
            "top_operators_7d": [{"username": u, "count": c} for u, c in operators.most_common(5)],
            "top_actions_7d": [{"action": a, "count": c} for a, c in actions.most_common(5)],
            "daily_7d": [{"date": d, **v} for d, v in daily.items()],
        },
        "attention": {
            "failed_jobs": [
                {"id": j.id, "title": j.title or f"{j.module}/{j.action}", "username": j.created_by_username,
                 "at": _iso(j.created_at), "error": (j.error_message or "")[:160]}
                for j in failed_recent
            ],
            "problem_servers": [
                {"server_id": s.id, "hostname": s.hostname, "ip": s.ip, "status": _status(s.status),
                 "message": (s.last_connection_message or "")[:160]}
                for s in problem_servers
            ],
        },
    }
