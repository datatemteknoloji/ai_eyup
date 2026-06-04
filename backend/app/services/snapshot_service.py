"""
VM snapshot servisi — oVirt (KVM) ve VMware vCenter
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.models.vm_snapshot import VMSnapshot

logger = logging.getLogger(__name__)

RETENTION_DAYS = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
}


def retention_to_expires(retention: str) -> Optional[datetime]:
    if not retention or retention == "indefinite":
        return None
    days = RETENTION_DAYS.get(retention, 7)
    return datetime.now(timezone.utc) + timedelta(days=days)


def _snapshot_summary(rec: VMSnapshot) -> dict:
    return {
        "id": rec.id,
        "server_id": rec.server_id,
        "hypervisor_id": rec.hypervisor_id,
        "plan_id": rec.plan_id,
        "vm_id": rec.vm_id,
        "snapshot_id": rec.snapshot_id,
        "snapshot_name": rec.snapshot_name,
        "platform": rec.platform,
        "source": rec.source,
        "retention": rec.retention,
        "status": rec.status,
        "error_message": rec.error_message,
        "expires_at": rec.expires_at.isoformat() if rec.expires_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "deleted_at": rec.deleted_at.isoformat() if rec.deleted_at else None,
    }


def server_can_snapshot(server: Server) -> bool:
    return bool(server.hypervisor_id and server.hypervisor_vm_id)


def get_vm_client(hypervisor: Hypervisor):
    host = hypervisor.ip_address or hypervisor.hostname
    username = hypervisor.username or (hypervisor.connection_config or {}).get("username", "")
    password = hypervisor.password or (hypervisor.connection_config or {}).get("password", "")
    port = hypervisor.port or 443

    if hypervisor.hypervisor_type == HypervisorType.VMWARE:
        from app.services.vmware.vcenter_client import VCenterClient
        client = VCenterClient(host=host, username=username, password=password, port=port)
        if not client.login():
            raise RuntimeError("vCenter oturumu açılamadı")
        return client, "vmware"

    if hypervisor.hypervisor_type == HypervisorType.KVM:
        from app.services.ovirt.ovirt_client import OVirtClient
        client = OVirtClient(host=host, username=username, password=password, port=port)
        ok, detail = client.test_connection()
        if not ok:
            raise RuntimeError(detail or "oVirt bağlantısı kurulamadı")
        return client, "ovirt"

    raise RuntimeError(f"Snapshot desteklenmeyen hypervisor tipi: {hypervisor.hypervisor_type}")


def resolve_vm_id(server: Server, client, platform: str) -> Optional[str]:
    if server.hypervisor_vm_id:
        return server.hypervisor_vm_id
    if platform == "vmware" and hasattr(client, "find_vm_by_name_or_ip"):
        return client.find_vm_by_name_or_ip(name=server.name or "", ip=server.ip_address or "")
    return None


def create_snapshot_for_server(
    server: Server,
    db: Session,
    *,
    source: str = "manual",
    plan_id: Optional[int] = None,
    retention: str = "1w",
    name_prefix: str = "ainew",
) -> Dict:
    if not server.hypervisor_id:
        return {"success": False, "skipped": True, "message": "Hypervisor bağlantısı yok"}

    hypervisor = db.query(Hypervisor).filter_by(id=server.hypervisor_id).first()
    if not hypervisor:
        return {"success": False, "skipped": True, "message": "Hypervisor kaydı bulunamadı"}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap_name = f"{name_prefix}-{server.name}-{ts}".replace(" ", "-")[:120]

    record = VMSnapshot(
        server_id=server.id,
        hypervisor_id=hypervisor.id,
        plan_id=plan_id,
        vm_id=server.hypervisor_vm_id or "",
        snapshot_name=snap_name,
        platform="",
        source=source,
        retention=retention or "1w",
        expires_at=retention_to_expires(retention or "1w"),
        status="failed",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    client = None
    try:
        client, platform = get_vm_client(hypervisor)
        record.platform = platform
        vm_id = resolve_vm_id(server, client, platform)
        if not vm_id:
            record.error_message = "VM ID bulunamadı — hypervisor senkronizasyonu gerekli"
            db.commit()
            return {"success": False, "skipped": True, "message": record.error_message, "snapshot": _snapshot_summary(record)}

        record.vm_id = vm_id
        # Resolve sırasında bulunan VM ID'yi server kaydına kalıcı yaz
        if vm_id and not server.hypervisor_vm_id:
            server.hypervisor_vm_id = vm_id
            db.add(server)
        desc = f"Kaynak: {source}" + (f", plan #{plan_id}" if plan_id else "")
        ok, msg, snap_id = client.create_snapshot(vm_id, snap_name, desc)
        if ok:
            record.snapshot_id = snap_id
            record.status = "active"
            record.error_message = None
            db.commit()
            return {"success": True, "message": msg, "snapshot": _snapshot_summary(record)}

        record.error_message = msg
        db.commit()
        return {"success": False, "message": msg, "snapshot": _snapshot_summary(record)}
    except Exception as exc:
        logger.error(f"create_snapshot_for_server #{server.id}: {exc}", exc_info=True)
        record.error_message = str(exc)
        db.commit()
        return {"success": False, "message": str(exc), "snapshot": _snapshot_summary(record)}
    finally:
        if client and hasattr(client, "logout"):
            try:
                client.logout()
            except Exception:
                pass


def list_snapshots_for_server(server_id: int, db: Session, include_deleted: bool = False) -> List[dict]:
    q = db.query(VMSnapshot).filter(VMSnapshot.server_id == server_id)
    if not include_deleted:
        q = q.filter(VMSnapshot.status == "active")
    rows = q.order_by(VMSnapshot.created_at.desc()).all()
    return [_snapshot_summary(r) for r in rows]


def list_external_snapshots(server: Server, db: Session) -> Dict:
    if not server.hypervisor_id:
        return {"success": False, "snapshots": [], "message": "Hypervisor bağlantısı yok"}
    hypervisor = db.query(Hypervisor).filter_by(id=server.hypervisor_id).first()
    if not hypervisor:
        return {"success": False, "snapshots": [], "message": "Hypervisor bulunamadı"}

    client = None
    try:
        client, platform = get_vm_client(hypervisor)
        vm_id = resolve_vm_id(server, client, platform)
        if not vm_id:
            return {"success": False, "snapshots": [], "message": "VM ID bulunamadı"}
        snaps = client.list_snapshots(vm_id)
        return {"success": True, "vm_id": vm_id, "platform": platform, "snapshots": snaps}
    except Exception as exc:
        return {"success": False, "snapshots": [], "message": str(exc)}
    finally:
        if client and hasattr(client, "logout"):
            try:
                client.logout()
            except Exception:
                pass


def delete_snapshot_record(snapshot_id: int, db: Session, delete_remote: bool = True) -> Dict:
    rec = db.query(VMSnapshot).filter_by(id=snapshot_id).first()
    if not rec:
        return {"success": False, "message": "Snapshot kaydı bulunamadı"}
    if rec.status == "deleted":
        return {"success": True, "message": "Zaten silinmiş"}

    if delete_remote and rec.snapshot_id and rec.hypervisor_id:
        hypervisor = db.query(Hypervisor).filter_by(id=rec.hypervisor_id).first()
        if hypervisor:
            client = None
            try:
                client, _ = get_vm_client(hypervisor)
                ok, msg = client.delete_snapshot(rec.vm_id, rec.snapshot_id)
                if not ok:
                    return {"success": False, "message": msg}
            except Exception as exc:
                return {"success": False, "message": str(exc)}
            finally:
                if client and hasattr(client, "logout"):
                    try:
                        client.logout()
                    except Exception:
                        pass

    rec.status = "deleted"
    rec.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "message": "Snapshot silindi", "snapshot": _snapshot_summary(rec)}


def cleanup_expired_snapshots(db: Session) -> Dict:
    now = datetime.now(timezone.utc)
    expired = db.query(VMSnapshot).filter(
        VMSnapshot.status == "active",
        VMSnapshot.expires_at.isnot(None),
        VMSnapshot.expires_at <= now,
    ).all()

    deleted = errors = 0
    for rec in expired:
        result = delete_snapshot_record(rec.id, db, delete_remote=True)
        if result.get("success"):
            deleted += 1
        else:
            errors += 1
            logger.warning(f"Snapshot cleanup #{rec.id}: {result.get('message')}")

    return {"checked": len(expired), "deleted": deleted, "errors": errors}
