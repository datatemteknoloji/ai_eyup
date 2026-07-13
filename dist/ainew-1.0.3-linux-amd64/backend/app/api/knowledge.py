"""
Bilgi Bankasi (Knowledge Base) API — AI'in SSH/WinRM taramalarindan ogrendigi
kalici, yapisal sunucu gerceklerini (LearnedFact) listeleme/filtreleme/
duzenleme/silme.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.learned_fact import LearnedFact
from app.models.server import Server

router = APIRouter()
logger = logging.getLogger(__name__)


class FactUpdate(BaseModel):
    value: str


@router.get("")
@router.get("/")
def list_facts(
    db: Session = Depends(get_db),
    server_id: Optional[int] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(200, le=1000),
    offset: int = 0,
):
    query = db.query(LearnedFact)
    if server_id:
        query = query.filter(LearnedFact.server_id == server_id)
    if category:
        query = query.filter(LearnedFact.category == category)
    if source:
        query = query.filter(LearnedFact.source == source)
    if q:
        like = f"%{q}%"
        query = query.filter((LearnedFact.key.ilike(like)) | (LearnedFact.value.ilike(like)))

    total = query.count()
    rows = (
        query.order_by(LearnedFact.last_confirmed_at.desc())
        .offset(max(offset, 0)).limit(min(limit, 1000)).all()
    )

    server_ids = {r.server_id for r in rows}
    servers = {s.id: s for s in db.query(Server).filter(Server.id.in_(server_ids)).all()} if server_ids else {}

    facts = []
    for r in rows:
        d = r.to_dict()
        srv = servers.get(r.server_id)
        d["server_name"] = srv.name if srv else f"#{r.server_id}"
        d["server_ip"] = srv.ip_address if srv else None
        facts.append(d)

    return {"total": total, "limit": limit, "offset": offset, "facts": facts}


@router.get("/summary")
def facts_summary(db: Session = Depends(get_db)):
    """Sunucu basina ogrenilen fact sayisi + kategori dagilimi."""
    per_server = (
        db.query(LearnedFact.server_id, func.count(LearnedFact.id))
        .group_by(LearnedFact.server_id)
        .all()
    )
    server_ids = [row[0] for row in per_server]
    servers = {s.id: s for s in db.query(Server).filter(Server.id.in_(server_ids)).all()} if server_ids else {}

    per_category = (
        db.query(LearnedFact.category, func.count(LearnedFact.id))
        .group_by(LearnedFact.category)
        .all()
    )

    return {
        "total_facts": db.query(func.count(LearnedFact.id)).scalar() or 0,
        "servers": [
            {
                "server_id": sid,
                "server_name": servers[sid].name if sid in servers else f"#{sid}",
                "server_ip": servers[sid].ip_address if sid in servers else None,
                "fact_count": count,
            }
            for sid, count in sorted(per_server, key=lambda x: -x[1])
        ],
        "categories": [{"category": c, "count": n} for c, n in sorted(per_category, key=lambda x: -x[1])],
    }


@router.put("/{fact_id}")
def update_fact(fact_id: int, body: FactUpdate, db: Session = Depends(get_db)):
    fact = db.query(LearnedFact).filter(LearnedFact.id == fact_id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    fact.value = body.value
    fact.source = "manual"
    from datetime import datetime, timezone
    fact.last_confirmed_at = datetime.now(timezone.utc)
    db.commit()
    return fact.to_dict()


@router.delete("/{fact_id}")
def delete_fact(fact_id: int, db: Session = Depends(get_db)):
    fact = db.query(LearnedFact).filter(LearnedFact.id == fact_id).first()
    if not fact:
        raise HTTPException(status_code=404, detail="Kayit bulunamadi")
    db.delete(fact)
    db.commit()
    return {"status": "deleted", "id": fact_id}


@router.delete("/server/{server_id}")
def delete_server_facts(server_id: int, db: Session = Depends(get_db)):
    """Bir sunucuya ait tum ogrenilmis bilgileri temizle (yeniden ogrenilsin)."""
    count = db.query(LearnedFact).filter(LearnedFact.server_id == server_id).delete()
    db.commit()
    return {"status": "deleted", "count": count}
