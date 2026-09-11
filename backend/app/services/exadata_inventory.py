"""Exadata sohbet envanteri — rack / compute / cell (DB, READ_ONLY).

Canlı cellcli / ASMCMD / AWR yok. cell_disk_info varsa envanter JSON'udur.
connection_config (kimlik) asla dönülmez.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.exadata import ExadataNode, ExadataNodeRole, ExadataRack
from app.services.chat_data_status import SUCCESS, SUCCESS_EMPTY

_ROLE_ALIASES = {
    "compute": ExadataNodeRole.COMPUTE_NODE,
    "compute_node": ExadataNodeRole.COMPUTE_NODE,
    "db": ExadataNodeRole.COMPUTE_NODE,
    "db_node": ExadataNodeRole.COMPUTE_NODE,
    "cell": ExadataNodeRole.STORAGE_CELL,
    "storage": ExadataNodeRole.STORAGE_CELL,
    "storage_cell": ExadataNodeRole.STORAGE_CELL,
    "ib": ExadataNodeRole.IB_SWITCH,
    "ib_switch": ExadataNodeRole.IB_SWITCH,
    "pdu": ExadataNodeRole.PDU,
    "other": ExadataNodeRole.OTHER,
}

_BAD = frozenset({"OFFLINE", "CRITICAL", "DOWN", "FAILED"})
_WARN = frozenset({"WARNING", "DEGRADED"})
_OK = frozenset({"ONLINE", "OK", "UP", "RUNNING"})


def parse_role(raw: Optional[str]) -> Optional[ExadataNodeRole]:
    if not raw:
        return None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return _ROLE_ALIASES.get(key)


def role_value(role: Any) -> str:
    if role is None:
        return "other"
    return role.value if hasattr(role, "value") else str(role)


def node_health(status: Optional[str]) -> str:
    s = (status or "unknown").upper()
    if s in _BAD:
        return "critical"
    if s in _WARN:
        return "warning"
    if s in _OK:
        return "healthy"
    return "unknown"


def rack_health(statuses: List[str], fallback: Optional[str] = None) -> str:
    if not statuses:
        return node_health(fallback)
    flags = [node_health(s) for s in statuses]
    if "critical" in flags:
        return "critical"
    if "warning" in flags:
        return "warning"
    if flags and all(f == "healthy" for f in flags):
        return "healthy"
    return node_health(fallback)


def _node_row(n: ExadataNode) -> Dict[str, Any]:
    return {
        "id": n.id,
        "rack_id": n.rack_id,
        "rack": n.rack.name if n.rack else None,
        "role": role_value(n.role),
        "name": n.name,
        "hostname": n.hostname,
        "ip_address": n.ip_address,
        "ilom_ip": n.ilom_ip,
        "status": n.status or "unknown",
        "health": node_health(n.status),
        "position_in_rack": n.position_in_rack,
        "cpu_cores": n.cpu_cores,
        "memory_gb": n.memory_gb,
        "storage_tb": n.storage_tb,
        "cell_disk_info": n.cell_disk_info,
        "linked_server_id": n.server_id,
        "note": (
            "cell_disk_info envanter alanıdır; canlı cellcli/ASMCMD değildir."
            if n.cell_disk_info else None
        ),
    }


def _rack_row(r: ExadataRack, *, include_nodes: bool = False) -> Dict[str, Any]:
    nodes = list(r.nodes or [])
    roles = [role_value(n.role) for n in nodes]
    row = {
        "id": r.id,
        "name": r.name,
        "rack_name": r.rack_name,
        "model": r.model,
        "datacenter": r.datacenter,
        "cabinet_label": r.cabinet_label,
        "hostname": r.hostname,
        "ip_address": r.ip_address,
        "status": r.status or "unknown",
        "health": rack_health([n.status or "unknown" for n in nodes], r.status),
        "last_sync": r.last_sync.isoformat() if r.last_sync else None,
        "node_count": len(nodes),
        "compute_count": sum(1 for x in roles if x == "compute_node"),
        "cell_count": sum(1 for x in roles if x == "storage_cell"),
    }
    if include_nodes:
        row["nodes"] = [_node_row(n) for n in nodes]
    return row


def list_exadata_racks(
    db: Session,
    *,
    name_filter: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    cap = max(1, min(int(limit or 50), 200))
    q = db.query(ExadataRack).options(joinedload(ExadataRack.nodes)).order_by(ExadataRack.name)
    raw = (name_filter or "").strip()
    if raw:
        like = f"%{raw}%"
        q = q.filter(
            (ExadataRack.name.ilike(like))
            | (ExadataRack.rack_name.ilike(like))
            | (ExadataRack.datacenter.ilike(like))
            | (ExadataRack.model.ilike(like))
        )
    rows = q.limit(cap).all()
    racks = [_rack_row(r) for r in rows]
    status = SUCCESS if racks else SUCCESS_EMPTY
    return {
        "ok": True,
        "data_status": status,
        "count": len(racks),
        "racks": racks,
        "note": "DB envanter; canlı cell/ILOM yok. Kimlik alanları yok.",
    }


def list_exadata_nodes(
    db: Session,
    *,
    role: Optional[str] = None,
    rack: Optional[str] = None,
    name_filter: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    cap = max(1, min(int(limit or 200), 400))
    parsed = parse_role(role)
    if role and parsed is None:
        return {
            "ok": False,
            "data_status": SUCCESS_EMPTY,
            "error": f"Geçersiz role={role}. compute_node|storage_cell|ib_switch|pdu|other",
            "nodes": [],
        }
    q = db.query(ExadataNode).options(joinedload(ExadataNode.rack)).order_by(
        ExadataNode.rack_id, ExadataNode.role, ExadataNode.name
    )
    if parsed is not None:
        q = q.filter(ExadataNode.role == parsed)
    raw_rack = (rack or "").strip()
    if raw_rack:
        like = f"%{raw_rack}%"
        q = q.join(ExadataRack).filter(
            (ExadataRack.name.ilike(like)) | (ExadataRack.rack_name.ilike(like))
        )
    raw = (name_filter or "").strip()
    if raw:
        like = f"%{raw}%"
        q = q.filter(
            (ExadataNode.name.ilike(like))
            | (ExadataNode.hostname.ilike(like))
            | (ExadataNode.ip_address == raw)
        )
    rows = q.limit(cap).all()
    nodes = [_node_row(n) for n in rows]
    return {
        "ok": True,
        "data_status": SUCCESS if nodes else SUCCESS_EMPTY,
        "count": len(nodes),
        "role_filter": role_value(parsed) if parsed else None,
        "nodes": nodes,
        "note": "DB envanter. Cell/ASM canlı metrik yok; linked_server_id varsa Linux get_* kullanılabilir.",
    }


def exadata_health_overview(db: Session) -> Dict[str, Any]:
    racks = (
        db.query(ExadataRack)
        .options(joinedload(ExadataRack.nodes))
        .order_by(ExadataRack.name)
        .all()
    )
    rack_rows = [_rack_row(r) for r in racks]
    nodes: List[ExadataNode] = []
    for r in racks:
        nodes.extend(r.nodes or [])
    compute = [n for n in nodes if role_value(n.role) == "compute_node"]
    cells = [n for n in nodes if role_value(n.role) == "storage_cell"]
    unhealthy = [row for row in rack_rows if row["health"] in ("critical", "warning")]
    empty = not racks
    return {
        "ok": True,
        "data_status": SUCCESS_EMPTY if empty else SUCCESS,
        "rack_count": len(racks),
        "node_count": len(nodes),
        "compute_count": len(compute),
        "cell_count": len(cells),
        "unhealthy_racks": unhealthy,
        "racks": rack_rows,
        "note": (
            "Kayıt yok — Exadata envanteri boş; cell CPU/ASM uydurma."
            if empty else
            "Sağlık envanter status alanından. Canlı cellcli/ASM/AWR bu araçta yok."
        ),
    }
