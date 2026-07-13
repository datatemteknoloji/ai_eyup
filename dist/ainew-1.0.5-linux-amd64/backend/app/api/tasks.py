"""
Tasks API — çalışan, bekleyen ve son tamamlanan görevlerin tek noktadan görünümü.

Kaynaklar:
  • vm_snapshots    (pending / active / failed)
  • agent_actions   (pending / executed / failed)
  • package_jobs    (running / done)
  • system_update_plans (running)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User

router = APIRouter()

# ─── helpers ────────────────────────────────────────────────────────────────

def _age(dt) -> str:
    """İnsan-okunur yaş: '2 dk', '1 sa', '3 gün'."""
    if dt is None:
        return "—"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60} dk"
    if s < 86400:
        return f"{s // 3600} sa"
    return f"{s // 86400} gün"


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


# ─── snapshot tasks ──────────────────────────────────────────────────────────

def _snapshot_tasks(db: Session, include_recent_hours: int = 24) -> list:
    try:
        from app.models.vm_snapshot import VMSnapshot
        from app.models.server import Server

        cutoff = datetime.now(timezone.utc) - timedelta(hours=include_recent_hours)
        rows = (
            db.query(VMSnapshot, Server.name.label("server_name"))
            .join(Server, VMSnapshot.server_id == Server.id, isouter=True)
            .filter(
                or_(
                    VMSnapshot.status.in_(["pending", "failed"]),
                    (VMSnapshot.status == "active") & (VMSnapshot.created_at >= cutoff),
                    (VMSnapshot.status == "deleted") & (VMSnapshot.deleted_at >= cutoff),
                )
            )
            .order_by(VMSnapshot.created_at.desc())
            .limit(100)
            .all()
        )

        tasks = []
        for snap, srv_name in rows:
            tasks.append({
                "id": f"snap-{snap.id}",
                "type": "snapshot",
                "title": snap.snapshot_name or f"Snapshot #{snap.id}",
                "subtitle": srv_name or f"Server #{snap.server_id}",
                "status": snap.status,           # pending / active / failed / deleted
                "platform": snap.platform or "—",
                "source": snap.source or "manual",
                "retention": snap.retention or "—",
                "snapshot_id": snap.snapshot_id,
                "error_message": snap.error_message,
                "created_at": _iso(snap.created_at),
                "age": _age(snap.created_at),
                "server_id": snap.server_id,
                "raw_id": snap.id,
            })
        return tasks
    except Exception as e:
        return [{"id": "snap-err", "type": "error", "title": str(e), "status": "error"}]


# ─── agent action tasks ──────────────────────────────────────────────────────

def _agent_tasks(db: Session, include_recent_hours: int = 24) -> list:
    try:
        from app.models.agent_action import AgentAction
        from app.models.server import Server

        cutoff = datetime.now(timezone.utc) - timedelta(hours=include_recent_hours)
        rows = (
            db.query(AgentAction, Server.name.label("server_name"))
            .join(Server, AgentAction.server_id == Server.id, isouter=True)
            .filter(
                or_(
                    AgentAction.status == "pending",
                    AgentAction.created_at >= cutoff,
                )
            )
            .order_by(AgentAction.created_at.desc())
            .limit(100)
            .all()
        )

        tasks = []
        for act, srv_name in rows:
            tasks.append({
                "id": f"agent-{act.id}",
                "type": "agent",
                "title": act.tool_name or "Agent Eylemi",
                "subtitle": srv_name or "—",
                "preview": act.preview or "",
                "status": act.status,            # pending / approved / rejected / executed / failed
                "risk_level": act.risk_level,
                "requires_root": act.requires_root,
                "decided_by": act.decided_by,
                "created_at": _iso(act.created_at),
                "decided_at": _iso(act.decided_at),
                "executed_at": _iso(act.executed_at),
                "age": _age(act.created_at),
                "server_id": act.server_id,
                "raw_id": act.id,
            })
        return tasks
    except Exception as e:
        return []


# ─── package job tasks ───────────────────────────────────────────────────────

def _package_tasks(db: Session, include_recent_hours: int = 24) -> list:
    try:
        from app.models.package_job import PackageJob
        from app.models.server import Server

        cutoff = datetime.now(timezone.utc) - timedelta(hours=include_recent_hours)
        rows = (
            db.query(PackageJob, Server.name.label("server_name"))
            .join(Server, PackageJob.server_id == Server.id, isouter=True)
            .filter(
                or_(
                    PackageJob.status.in_(["pending", "running"]),
                    PackageJob.created_at >= cutoff,
                )
            )
            .order_by(PackageJob.created_at.desc())
            .limit(50)
            .all()
        )

        tasks = []
        for job, srv_name in rows:
            tasks.append({
                "id": f"pkg-{job.id}",
                "type": "package",
                "title": f"{job.action or 'Paket'}: {(job.package_name or '')[:40]}",
                "subtitle": srv_name or "—",
                "status": job.status,
                "created_at": _iso(job.created_at),
                "age": _age(job.created_at),
                "server_id": job.server_id,
                "raw_id": job.id,
            })
        return tasks
    except Exception:
        return []


# ─── system update tasks ─────────────────────────────────────────────────────

def _update_tasks(db: Session, include_recent_hours: int = 24) -> list:
    try:
        from app.models.system_update import SystemUpdatePlan
        from app.models.server import Server

        cutoff = datetime.now(timezone.utc) - timedelta(hours=include_recent_hours)
        rows = (
            db.query(SystemUpdatePlan, Server.name.label("server_name"))
            .join(Server, SystemUpdatePlan.server_id == Server.id, isouter=True)
            .filter(
                or_(
                    SystemUpdatePlan.status.in_(["pending", "running"]),
                    SystemUpdatePlan.created_at >= cutoff,
                )
            )
            .order_by(SystemUpdatePlan.created_at.desc())
            .limit(50)
            .all()
        )

        tasks = []
        for plan, srv_name in rows:
            tasks.append({
                "id": f"update-{plan.id}",
                "type": "update",
                "title": f"OS Güncelleme: {srv_name or 'Sunucu'}",
                "subtitle": srv_name or "—",
                "status": plan.status,
                "step": getattr(plan, "current_step", None),
                "created_at": _iso(plan.created_at),
                "age": _age(plan.created_at),
                "server_id": plan.server_id,
                "raw_id": plan.id,
            })
        return tasks
    except Exception:
        return []


# ─── endpoints ───────────────────────────────────────────────────────────────

@router.get("")
@router.get("/")
def list_tasks(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    hours: int = Query(24, ge=1, le=168),
    type: Optional[str] = None,
):
    """
    Tüm aktif ve son tamamlanan görevleri döner.

    ?type=snapshot|agent|package|update  → filtre
    ?hours=N                             → kaç saatlik geçmiş (1-168, default 24)
    """
    tasks = []

    if not type or type == "snapshot":
        tasks += _snapshot_tasks(db, hours)
    if not type or type == "agent":
        tasks += _agent_tasks(db, hours)
    if not type or type == "package":
        tasks += _package_tasks(db, hours)
    if not type or type == "update":
        tasks += _update_tasks(db, hours)

    # Sırala: önce pending/running, sonra yeniden eskiye
    priority = {"pending": 0, "running": 1, "failed": 2, "active": 3,
                "executed": 4, "approved": 5, "success": 6, "deleted": 7, "rejected": 8}
    tasks.sort(key=lambda t: (
        priority.get(t.get("status", ""), 9),
        -(datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).timestamp()
          if t.get("created_at") else 0)
    ))

    # Özet sayımlar
    summary = {
        "total": len(tasks),
        "pending": sum(1 for t in tasks if t.get("status") == "pending"),
        "running": sum(1 for t in tasks if t.get("status") == "running"),
        "failed": sum(1 for t in tasks if t.get("status") == "failed"),
        "active": sum(1 for t in tasks if t.get("status") in ("active", "executed", "success")),
    }

    return {"summary": summary, "tasks": tasks, "hours": hours}


@router.get("/active-count")
def active_task_count(db: Session = Depends(get_db),
                      _user: User = Depends(get_current_user)):
    """Navbar badge için sadece aktif görev sayısı."""
    try:
        from app.models.vm_snapshot import VMSnapshot
        from app.models.agent_action import AgentAction
        snap_pending = db.query(VMSnapshot).filter(VMSnapshot.status == "pending").count()
        agent_pending = db.query(AgentAction).filter(AgentAction.status == "pending").count()
        return {"count": snap_pending + agent_pending, "snap": snap_pending, "agent": agent_pending}
    except Exception:
        return {"count": 0, "snap": 0, "agent": 0}
