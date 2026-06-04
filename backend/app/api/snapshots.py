"""
VM Snapshot API
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.server import Server
from app.models.user import User
from app.models.vm_snapshot import VMSnapshot
from app.services.audit import record_audit
from app.services.snapshot_service import (
    create_snapshot_for_server,
    delete_snapshot_record,
    list_external_snapshots,
    list_snapshots_for_server,
    server_can_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SnapshotCreateRequest(BaseModel):
    retention: str = "1w"  # 1d | 1w | 1m | indefinite
    name_prefix: Optional[str] = "manual"


@router.get("/")
def list_all_snapshots(limit: int = 100, db: Session = Depends(get_db)):
    rows = (
        db.query(VMSnapshot)
        .filter(VMSnapshot.status == "active")
        .order_by(VMSnapshot.created_at.desc())
        .limit(limit)
        .all()
    )
    from app.services.snapshot_service import _snapshot_summary
    return [_snapshot_summary(r) for r in rows]


@router.get("/capability")
def snapshot_capability(server_ids: str, db: Session = Depends(get_db)):
    """Seçili sunucuların snapshot alınabilirliğini döner."""
    ids = [int(x) for x in server_ids.split(",") if x.strip().isdigit()]
    servers = db.query(Server).filter(Server.id.in_(ids)).all() if ids else []
    by_id = {s.id: s for s in servers}
    result = []
    for sid in ids:
        srv = by_id.get(sid)
        if not srv:
            result.append({"server_id": sid, "can_snapshot": False, "reason": "Sunucu bulunamadı"})
            continue
        if server_can_snapshot(srv):
            result.append({"server_id": sid, "can_snapshot": True, "server_name": srv.name})
        elif srv.hypervisor_id and not srv.hypervisor_vm_id:
            result.append({
                "server_id": sid,
                "can_snapshot": False,
                "server_name": srv.name,
                "reason": "VM ID yok — hypervisor senkronizasyonu gerekli",
            })
        else:
            result.append({
                "server_id": sid,
                "can_snapshot": False,
                "server_name": srv.name,
                "reason": "Hypervisor bağlantısı yok (fiziksel sunucu)",
            })
    snap_ready = sum(1 for r in result if r.get("can_snapshot"))
    return {
        "servers": result,
        "total": len(result),
        "snapshot_ready": snap_ready,
        "snapshot_missing": len(result) - snap_ready,
    }


@router.get("/server/{server_id}")
def get_server_snapshots(server_id: int, db: Session = Depends(get_db)):
    srv = db.query(Server).filter_by(id=server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")
    tracked = list_snapshots_for_server(server_id, db)
    # Hypervisor bağlı olduğunda (vm_id olmasa da) dış snapshotları listele
    has_hypervisor = bool(srv.hypervisor_id)
    can_snap_now = server_can_snapshot(srv)
    external = list_external_snapshots(srv, db) if can_snap_now else {"snapshots": []}
    return {
        "tracked": tracked,
        "external": external.get("snapshots", []),
        "can_snapshot": can_snap_now,
        "hypervisor_connected": has_hypervisor,
        "vm_id_missing": has_hypervisor and not srv.hypervisor_vm_id,
        "platform": external.get("platform"),
    }


@router.post("/server/{server_id}")
def create_server_snapshot(server_id: int, req: SnapshotCreateRequest,
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    srv = db.query(Server).filter_by(id=server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")
    result = create_snapshot_for_server(
        srv, db,
        source="manual",
        retention=req.retention,
        name_prefix=req.name_prefix or "manual",
    )
    record_audit(db, category="snapshot", action="snapshot.create",
                 status="success" if result.get("success") else "failure",
                 actor=user, target_type="server", target_id=server_id, server_id=server_id,
                 summary=f"Snapshot alındı: {srv.name}",
                 detail={"retention": req.retention, "ok": result.get("success")})
    if not result.get("success") and not result.get("skipped"):
        raise HTTPException(400, result.get("message", "Snapshot oluşturulamadı"))
    return result


@router.delete("/{snapshot_id}")
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    result = delete_snapshot_record(snapshot_id, db, delete_remote=True)
    record_audit(db, category="snapshot", action="snapshot.delete",
                 status="success" if result.get("success") else "failure",
                 actor=user, target_type="snapshot", target_id=snapshot_id,
                 summary=f"Snapshot silindi (#{snapshot_id})")
    if not result.get("success"):
        raise HTTPException(400, result.get("message", "Silinemedi"))
    return result
