"""
Uygulama/Servis Keşfi API — sunucularda otomatik tespit edilen uygulamaları
(Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.) listeleme/filtreleme/silme ve
manuel "yeniden tarama" tetikleme.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.discovered_application import DiscoveredApplication
from app.models.server import Server

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
@router.get("/")
def list_applications(
    db: Session = Depends(get_db),
    server_id: Optional[int] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(500, le=2000),
    offset: int = 0,
):
    query = db.query(DiscoveredApplication)
    if server_id:
        query = query.filter(DiscoveredApplication.server_id == server_id)
    if category:
        query = query.filter(DiscoveredApplication.category == category)
    if status:
        query = query.filter(DiscoveredApplication.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (DiscoveredApplication.name.ilike(like))
            | (DiscoveredApplication.process_or_service.ilike(like))
        )

    total = query.count()
    rows = (
        query.order_by(DiscoveredApplication.name, DiscoveredApplication.server_id)
        .offset(max(offset, 0)).limit(min(limit, 2000)).all()
    )

    server_ids = {r.server_id for r in rows}
    servers = {s.id: s for s in db.query(Server).filter(Server.id.in_(server_ids)).all()} if server_ids else {}

    apps = []
    for r in rows:
        d = r.to_dict()
        srv = servers.get(r.server_id)
        d["server_name"] = srv.name if srv else f"#{r.server_id}"
        d["server_ip"] = srv.ip_address if srv else None
        apps.append(d)

    return {"total": total, "limit": limit, "offset": offset, "applications": apps}


@router.get("/summary")
def applications_summary(db: Session = Depends(get_db)):
    """Ürün başına kaç sunucuda çalıştığı + kategori dağılımı + son tarama zamanları."""
    per_name = (
        db.query(DiscoveredApplication.name, DiscoveredApplication.category,
                  func.count(DiscoveredApplication.id))
        .filter(DiscoveredApplication.status == "running")
        .group_by(DiscoveredApplication.name, DiscoveredApplication.category)
        .all()
    )
    per_category = (
        db.query(DiscoveredApplication.category, func.count(DiscoveredApplication.id))
        .filter(DiscoveredApplication.status == "running")
        .group_by(DiscoveredApplication.category)
        .all()
    )
    total_running = db.query(func.count(DiscoveredApplication.id)).filter(
        DiscoveredApplication.status == "running"
    ).scalar() or 0
    scanned_servers = db.query(func.count(Server.id)).filter(
        Server.app_discovery_last_scan.isnot(None)
    ).scalar() or 0

    return {
        "total_running": total_running,
        "scanned_servers": scanned_servers,
        "by_product": [
            {"name": n, "category": c, "server_count": count}
            for n, c, count in sorted(per_name, key=lambda x: -x[2])
        ],
        "by_category": [{"category": c, "count": n} for c, n in sorted(per_category, key=lambda x: -x[1])],
    }


@router.post("/servers/{server_id}/rescan")
def rescan_server(server_id: int, db: Session = Depends(get_db)):
    """Bir sunucu için ANINDA (rescan aralığını göz ardı ederek) uygulama taraması yapar."""
    from app.services.app_discovery import discover_applications_for_server

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadi")

    apps = discover_applications_for_server(db, server)
    return {"status": "ok", "server_id": server_id, "found": len(apps), "applications": apps}


@router.delete("/{app_id}")
def delete_application(app_id: int, db: Session = Depends(get_db)):
    app_row = db.query(DiscoveredApplication).filter(DiscoveredApplication.id == app_id).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    db.delete(app_row)
    db.commit()
    return {"status": "deleted", "id": app_id}


@router.delete("/server/{server_id}")
def delete_server_applications(server_id: int, db: Session = Depends(get_db)):
    count = db.query(DiscoveredApplication).filter(DiscoveredApplication.server_id == server_id).delete()
    db.commit()
    return {"status": "deleted", "count": count}
