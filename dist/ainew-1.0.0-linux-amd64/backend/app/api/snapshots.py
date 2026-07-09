"""
VM Snapshot API
"""
import logging
from typing import List, Optional

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    search_and_sync_vm_details,
    server_can_snapshot,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SnapshotCreateRequest(BaseModel):
    retention: str = "1w"  # 1d | 1w | 1m | indefinite
    name_prefix: Optional[str] = "DTT"


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


@router.get("/server/{server_id}/vm-details")
def get_vm_details(server_id: int, db: Session = Depends(get_db)):
    """Server kaydındaki mevcut VM detaylarını döner."""
    srv = db.query(Server).filter_by(id=server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")
    return {
        "server_id": srv.id,
        "server_name": srv.name,
        "hypervisor_id": srv.hypervisor_id,
        "hypervisor_vm_id": srv.hypervisor_vm_id,
        "vm_name": srv.vm_name,
        "vm_guest_hostname": srv.vm_guest_hostname,
        "vm_guest_ip": srv.vm_guest_ip,
        "vm_cpu_count": srv.vm_cpu_count,
        "vm_memory_mb": srv.vm_memory_mb,
        "vm_disk_gb": srv.vm_disk_gb,
        "vm_power_state": srv.vm_power_state,
        "vm_tools_status": srv.vm_tools_status,
        "vm_network_info": srv.vm_network_info,
        "vm_cluster": srv.vm_cluster,
        "vm_datastore": srv.vm_datastore,
        "vm_hardware_version": srv.vm_hardware_version,
        "vm_last_sync": srv.vm_last_sync.isoformat() if srv.vm_last_sync else None,
        "can_snapshot": server_can_snapshot(srv),
    }


@router.post("/server/{server_id}/search-vm")
def search_vm_and_sync(server_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """
    Hypervisor üzerinde bu sunucu için VM'i arar; bulunca
    VM ID + tüm detayları (hostname, IP, CPU, RAM, disk, ağ…) server kaydına yazar.
    """
    srv = db.query(Server).filter_by(id=server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")
    if not srv.hypervisor_id:
        raise HTTPException(400, "Bu sunucuya bağlı hypervisor yok")

    result = search_and_sync_vm_details(srv, db)
    record_audit(db, category="snapshot", action="snapshot.search_vm",
                 status="success" if result.get("found") else "failure",
                 actor=user, target_type="server", target_id=server_id, server_id=server_id,
                 summary=result.get("message", "")[:200])
    if not result.get("found"):
        raise HTTPException(404, result.get("message", "VM bulunamadı"))
    return result


_SNAP_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="snap")


def _run_snapshot_bg(server_id: int, retention: str, name_prefix: str,
                     actor_id: int, actor_name: str, pending_snapshot_id: int) -> None:
    """Background thread: snapshot alır, DB kaydını günceller, audit yazar."""
    from app.core.database import ThreadSessionLocal
    from app.models.vm_snapshot import VMSnapshot
    db = ThreadSessionLocal()
    try:
        srv = db.query(Server).filter_by(id=server_id).first()
        if not srv:
            return
        pending = db.query(VMSnapshot).filter_by(id=pending_snapshot_id).first()
        result = create_snapshot_for_server(
            srv, db,
            source="manual",
            retention=retention,
            name_prefix=name_prefix,
            existing_record=pending,
        )
        record_audit(db, category="snapshot", action="snapshot.create",
                     status="success" if result.get("success") else "failure",
                     actor=actor_name,
                     target_type="server", target_id=server_id, server_id=server_id,
                     summary=f"Snapshot {'alındı' if result.get('success') else 'başarısız'}: {srv.name}",
                     detail={"retention": retention, "ok": result.get("success"),
                             "message": result.get("message", "")})
    except Exception as exc:
        logger.error(f"Snapshot background task #{server_id}: {exc}", exc_info=True)
        try:
            from app.models.vm_snapshot import VMSnapshot as _VS
            rec = db.query(_VS).filter_by(id=pending_snapshot_id).first()
            if rec and rec.status == "pending":
                rec.status = "failed"
                rec.error_message = str(exc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/server/{server_id}")
async def create_server_snapshot(server_id: int, req: SnapshotCreateRequest,
                                 background_tasks: BackgroundTasks,
                                 db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """
    Snapshot oluşturur.

    vCenter/oVirt SOAP task'ları dakikalarca sürebilir.
    İstek hemen döner (accepted), snapshot background'da tamamlanır.
    GET /snapshots/server/{id} ile durumu takip edin.
    """
    srv = db.query(Server).filter_by(id=server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")
    if not srv.hypervisor_id:
        raise HTTPException(400, "Hypervisor bağlantısı yok")

    # VM ID eksikse önce otomatik ara ve kaydet
    if not srv.hypervisor_vm_id:
        from app.services.snapshot_service import search_and_sync_vm_details
        sync_result = await asyncio.to_thread(search_and_sync_vm_details, srv, db)
        db.refresh(srv)
        if not sync_result.get("found"):
            raise HTTPException(400, f"VM bulunamadı: {sync_result.get('message', 'Hypervisor üzerinde eşleşme yok')}")

    if not server_can_snapshot(srv):
        raise HTTPException(400, "VM ID alınamadı — hypervisor bağlantısını kontrol edin")

    # DB'ye "pending" kayıt at ki frontend hemen görsün
    from app.models.vm_snapshot import VMSnapshot
    from app.services.snapshot_service import retention_to_expires
    import datetime, uuid as _uuid
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_name = f"{req.name_prefix or 'DTT'}-{srv.name}-{ts}".replace(" ", "-")[:120]
    pending_rec = VMSnapshot(
        server_id=srv.id,
        hypervisor_id=srv.hypervisor_id,
        vm_id=srv.hypervisor_vm_id or "",
        snapshot_name=snap_name,
        platform="",
        source="manual",
        retention=req.retention or "1w",
        expires_at=retention_to_expires(req.retention or "1w"),
        status="pending",
    )
    db.add(pending_rec)
    db.commit()
    db.refresh(pending_rec)

    record_audit(db, category="snapshot", action="snapshot.create_started",
                 actor=user, target_type="server", target_id=server_id, server_id=server_id,
                 summary=f"Snapshot başlatıldı: {srv.name}")

    # Gerçek işi background'a at
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _SNAP_EXECUTOR,
        _run_snapshot_bg,
        server_id, req.retention or "1w", req.name_prefix or "DTT",
        user.id, user.username, pending_rec.id,
    )

    return {
        "success": True,
        "accepted": True,
        "message": f"Snapshot işlemi başlatıldı: {snap_name}",
        "snapshot": {
            "id": pending_rec.id,
            "snapshot_name": snap_name,
            "status": "pending",
            "retention": req.retention or "1w",
            "created_at": pending_rec.created_at.isoformat() if pending_rec.created_at else None,
        },
    }


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
