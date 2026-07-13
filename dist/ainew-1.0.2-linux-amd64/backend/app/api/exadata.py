"""
Exadata API — rack/kabinet envanteri, compute node ve storage cell yönetimi.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.inventory_guard import require_integrations_inventory
from app.models.exadata import ExadataRack, ExadataNode, ExadataNodeRole
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class RackCreate(BaseModel):
    name: str
    rack_name: Optional[str] = None
    model: Optional[str] = None
    datacenter: Optional[str] = None
    cabinet_label: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    connection_config: Optional[dict] = None
    meta_data: Optional[dict] = None


class RackUpdate(BaseModel):
    name: Optional[str] = None
    rack_name: Optional[str] = None
    model: Optional[str] = None
    datacenter: Optional[str] = None
    cabinet_label: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None
    connection_config: Optional[dict] = None
    meta_data: Optional[dict] = None


class NodeCreate(BaseModel):
    role: str = "compute_node"
    name: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    ilom_ip: Optional[str] = None
    status: Optional[str] = "unknown"
    position_in_rack: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[float] = None
    storage_tb: Optional[float] = None
    cell_disk_info: Optional[dict] = None
    server_id: Optional[int] = None
    meta_data: Optional[dict] = None


class NodeUpdate(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    ilom_ip: Optional[str] = None
    status: Optional[str] = None
    position_in_rack: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_gb: Optional[float] = None
    storage_tb: Optional[float] = None
    cell_disk_info: Optional[dict] = None
    server_id: Optional[int] = None
    meta_data: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_role(role: str) -> ExadataNodeRole:
    try:
        return ExadataNodeRole(role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Geçersiz role: {role}")


def _node_dict(n: ExadataNode) -> dict:
    return {
        "id": n.id,
        "rack_id": n.rack_id,
        "role": n.role.value if n.role else "other",
        "name": n.name,
        "hostname": n.hostname,
        "ip_address": n.ip_address,
        "ilom_ip": n.ilom_ip,
        "status": n.status,
        "position_in_rack": n.position_in_rack,
        "cpu_cores": n.cpu_cores,
        "memory_gb": n.memory_gb,
        "storage_tb": n.storage_tb,
        "cell_disk_info": n.cell_disk_info,
        "server_id": n.server_id,
        "meta_data": n.meta_data,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _rack_dict(r: ExadataRack, include_nodes: bool = False) -> dict:
    nodes = r.nodes or []
    compute = [n for n in nodes if n.role == ExadataNodeRole.COMPUTE_NODE]
    cells = [n for n in nodes if n.role == ExadataNodeRole.STORAGE_CELL]
    other = [n for n in nodes if n.role not in (ExadataNodeRole.COMPUTE_NODE, ExadataNodeRole.STORAGE_CELL)]

    d = {
        "id": r.id,
        "name": r.name,
        "rack_name": r.rack_name,
        "model": r.model,
        "datacenter": r.datacenter,
        "cabinet_label": r.cabinet_label,
        "hostname": r.hostname,
        "ip_address": r.ip_address,
        "status": r.status,
        "connection_config": r.connection_config,
        "meta_data": r.meta_data,
        "last_sync": r.last_sync.isoformat() if r.last_sync else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "node_count": len(nodes),
        "compute_count": len(compute),
        "cell_count": len(cells),
        "other_count": len(other),
    }
    if include_nodes:
        d["compute_nodes"] = [_node_dict(n) for n in compute]
        d["storage_cells"] = [_node_dict(n) for n in cells]
        d["other_nodes"] = [_node_dict(n) for n in other]
        d["nodes"] = [_node_dict(n) for n in nodes]
    return d


def _rack_health(r: ExadataRack) -> str:
    nodes = r.nodes or []
    if not nodes:
        return r.status or "unknown"
    statuses = [(n.status or "unknown").upper() for n in nodes]
    if any(s in ("OFFLINE", "CRITICAL", "DOWN", "FAILED") for s in statuses):
        return "critical"
    if any(s in ("WARNING", "DEGRADED") for s in statuses):
        return "warning"
    if all(s in ("ONLINE", "OK", "UP", "RUNNING") for s in statuses):
        return "healthy"
    return r.status or "unknown"


# ── Rack endpoints ────────────────────────────────────────────────────────────

@router.get("/racks")
async def list_racks(db: Session = Depends(get_db)):
    racks = db.query(ExadataRack).order_by(ExadataRack.name).all()
    return {"racks": [_rack_dict(r) for r in racks], "total": len(racks)}


@router.post("/racks")
async def create_rack(body: RackCreate, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    rack = ExadataRack(
        name=body.name,
        rack_name=body.rack_name,
        model=body.model,
        datacenter=body.datacenter,
        cabinet_label=body.cabinet_label,
        hostname=body.hostname,
        ip_address=body.ip_address,
        connection_config=body.connection_config or {},
        meta_data=body.meta_data,
        status="unknown",
    )
    db.add(rack)
    db.commit()
    db.refresh(rack)
    return _rack_dict(rack)


@router.get("/racks/{rack_id}")
async def get_rack(rack_id: int, db: Session = Depends(get_db)):
    rack = db.query(ExadataRack).filter(ExadataRack.id == rack_id).first()
    if not rack:
        raise HTTPException(status_code=404, detail="Rack bulunamadı")
    return _rack_dict(rack, include_nodes=True)


@router.put("/racks/{rack_id}")
async def update_rack(rack_id: int, body: RackUpdate, db: Session = Depends(get_db)):
    rack = db.query(ExadataRack).filter(ExadataRack.id == rack_id).first()
    if not rack:
        raise HTTPException(status_code=404, detail="Rack bulunamadı")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(rack, field, val)
    db.commit()
    db.refresh(rack)
    return _rack_dict(rack, include_nodes=True)


@router.delete("/racks/{rack_id}")
async def delete_rack(rack_id: int, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    rack = db.query(ExadataRack).filter(ExadataRack.id == rack_id).first()
    if not rack:
        raise HTTPException(status_code=404, detail="Rack bulunamadı")
    db.delete(rack)
    db.commit()
    return {"deleted": rack_id}


@router.post("/racks/{rack_id}/nodes")
async def add_node(rack_id: int, body: NodeCreate, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    rack = db.query(ExadataRack).filter(ExadataRack.id == rack_id).first()
    if not rack:
        raise HTTPException(status_code=404, detail="Rack bulunamadı")
    if body.server_id:
        srv = db.query(Server).filter(Server.id == body.server_id).first()
        if not srv:
            raise HTTPException(status_code=400, detail="server_id geçersiz")
    node = ExadataNode(
        rack_id=rack_id,
        role=_parse_role(body.role),
        name=body.name,
        hostname=body.hostname,
        ip_address=body.ip_address,
        ilom_ip=body.ilom_ip,
        status=body.status or "unknown",
        position_in_rack=body.position_in_rack,
        cpu_cores=body.cpu_cores,
        memory_gb=body.memory_gb,
        storage_tb=body.storage_tb,
        cell_disk_info=body.cell_disk_info,
        server_id=body.server_id,
        meta_data=body.meta_data,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return _node_dict(node)


@router.put("/nodes/{node_id}")
async def update_node(node_id: int, body: NodeUpdate, db: Session = Depends(get_db)):
    node = db.query(ExadataNode).filter(ExadataNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node bulunamadı")
    data = body.model_dump(exclude_unset=True)
    if "role" in data:
        data["role"] = _parse_role(data["role"])
    if data.get("server_id"):
        srv = db.query(Server).filter(Server.id == data["server_id"]).first()
        if not srv:
            raise HTTPException(status_code=400, detail="server_id geçersiz")
    for field, val in data.items():
        setattr(node, field, val)
    db.commit()
    db.refresh(node)
    return _node_dict(node)


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: int, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    node = db.query(ExadataNode).filter(ExadataNode.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node bulunamadı")
    db.delete(node)
    db.commit()
    return {"deleted": node_id}


@router.post("/racks/{rack_id}/sync")
async def sync_rack(rack_id: int, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    """Envanter senkronizasyonu — şimdilik last_sync günceller; cellcli/dbmcli entegrasyonu sonra eklenecek."""
    rack = db.query(ExadataRack).filter(ExadataRack.id == rack_id).first()
    if not rack:
        raise HTTPException(status_code=404, detail="Rack bulunamadı")
    rack.last_sync = datetime.utcnow()
    db.commit()
    return {"success": True, "rack_id": rack_id, "last_sync": rack.last_sync.isoformat(), "message": "Senkron zaman damgası güncellendi"}


# ── Cabinet view (dashboard) ────────────────────────────────────────────────

@router.get("/cabinets")
async def list_cabinets(db: Session = Depends(get_db)):
    """Tüm rack/kabinetler — compute node ve cell aynı kabinet görünümünde."""
    racks = db.query(ExadataRack).order_by(ExadataRack.datacenter, ExadataRack.name).all()
    cabinets = []
    for r in racks:
        health = _rack_health(r)
        cabinets.append({
            **_rack_dict(r, include_nodes=True),
            "health": health,
        })
    total_compute = sum(c["compute_count"] for c in cabinets)
    total_cells = sum(c["cell_count"] for c in cabinets)
    return {
        "cabinets": cabinets,
        "total_racks": len(cabinets),
        "total_compute_nodes": total_compute,
        "total_storage_cells": total_cells,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/ops/summary")
async def exadata_ops_summary(db: Session = Depends(get_db)):
    """Navbar badge — linked server events üzerinden actionable sayaç."""
    from app.api.ops_center import _active_events, ACTIVE_WINDOW_HOURS
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = _active_events(db, since, platform="exadata")
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")

    racks = db.query(ExadataRack).all()
    unhealthy_racks = sum(1 for r in racks if _rack_health(r) in ("critical", "warning"))

    return {
        "critical": critical,
        "warning": warning + unhealthy_racks,
        "action_needed": critical > 0 or unhealthy_racks > 0,
        "rack_count": len(racks),
        "unhealthy_racks": unhealthy_racks,
    }
