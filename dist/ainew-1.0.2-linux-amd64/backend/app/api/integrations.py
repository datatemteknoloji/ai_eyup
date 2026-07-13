"""Entegrasyonlar — envanter kaynakları, özet ve tekilleştirme."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.models.exadata import ExadataRack, ExadataNode
from app.services.platform_scope import vm_filter_condition, get_exadata_server_ids, get_physical_host_ids
from app.services.inventory_dedup import detect_duplicate_groups, auto_deduplicate, merge_servers

router = APIRouter()


class MergeRequest(BaseModel):
    keep_id: int
    merge_ids: list[int]
    dry_run: bool = False


@router.get("/summary")
async def integrations_summary(db: Session = Depends(get_db)):
    """Tüm envanter kaynaklarının özeti."""
    total_servers = db.query(Server).count()
    vm_count = db.query(Server).filter(vm_filter_condition()).count()
    linux_physical = len(get_physical_host_ids(db))
    exadata_linked = len(get_exadata_server_ids(db))
    hypervisors = db.query(Hypervisor).count()
    exadata_racks = db.query(ExadataRack).count()
    exadata_nodes = db.query(ExadataNode).count()

    ucmdb_count = 0
    for s in db.query(Server).all():
        sources = (s.connection_config or {}).get("inventory_sources") or []
        if any(x.get("source") == "ucmdb" for x in sources):
            ucmdb_count += 1
        elif (s.connection_config or {}).get("ucmdb_import"):
            ucmdb_count += 1

    duplicate_groups = detect_duplicate_groups(db)

    return {
        "sources": [
            {
                "id": "ucmdb",
                "name": "UCMDB",
                "description": "CSV/Excel envanter import",
                "count": ucmdb_count,
                "path": "/integrations/ucmdb",
            },
            {
                "id": "hypervisor",
                "name": "vCenter / OLVM",
                "description": "Hypervisor bağlantıları ve VM sync",
                "count": hypervisors,
                "vm_count": vm_count,
                "path": "/integrations/hypervisors",
            },
            {
                "id": "physical",
                "name": "Fiziksel Hostlar",
                "description": "Linux/Windows fiziksel sunucular",
                "count": linux_physical,
                "path": "/integrations/physical-hosts",
            },
            {
                "id": "exadata",
                "name": "Exadata",
                "description": "Rack, compute node ve storage cell",
                "count": exadata_nodes,
                "rack_count": exadata_racks,
                "linked_servers": exadata_linked,
                "path": "/integrations/exadata",
            },
        ],
        "inventory": {
            "total_servers": total_servers,
            "virtual_machines": vm_count,
            "physical_hosts": linux_physical,
            "duplicate_groups": len(duplicate_groups),
            "duplicate_records": sum(g["count"] for g in duplicate_groups),
        },
    }


@router.get("/duplicates")
async def list_duplicates(db: Session = Depends(get_db)):
    groups = detect_duplicate_groups(db)
    return {"groups": groups, "total_groups": len(groups)}


@router.post("/deduplicate")
async def run_deduplicate(dry_run: bool = Query(default=True), db: Session = Depends(get_db)):
    """Mükerrer envanter kayıtlarını otomatik birleştir (varsayılan: dry_run)."""
    return auto_deduplicate(db, dry_run=dry_run)


@router.post("/merge")
async def merge_duplicate_records(body: MergeRequest, db: Session = Depends(get_db)):
    return merge_servers(db, body.keep_id, body.merge_ids, dry_run=body.dry_run)


@router.get("/physical-hosts")
async def list_physical_hosts(db: Session = Depends(get_db)):
    """Fiziksel host listesi — VM ve Exadata hariç."""
    ids = set(get_physical_host_ids(db))
    servers = db.query(Server).filter(Server.id.in_(list(ids))).order_by(Server.name).all() if ids else []
    return [
        {
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "os_type": s.os_type,
            "status": s.status,
            "tier": s.tier,
            "sources": (s.connection_config or {}).get("inventory_sources", []),
        }
        for s in servers
    ]
