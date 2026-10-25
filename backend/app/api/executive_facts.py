"""Yönetici rapor gerçekleri. Okuma kilitli anlık görüntüdür; hesaplama arka plandadır."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.exec_snapshot import bundle_payload, start_refresh

router = APIRouter()


@router.get("/executive-facts")
def executive_facts(month: Optional[str] = None, db: Session = Depends(get_db)):
    return bundle_payload(db, month=month)


@router.post("/executive-facts/refresh")
def executive_facts_refresh():
    return start_refresh()
