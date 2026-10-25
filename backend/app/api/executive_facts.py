"""Yönetici rapor gerçekleri. Platform API'sine gitmez."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.exec_facts import build_executive_facts

router = APIRouter()


def _parse(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{name} tarihi okunamadı") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@router.get("/executive-facts")
def executive_facts(
    start: str = Query(..., description="ISO başlangıç"),
    end: str = Query(..., description="ISO bitiş, hariç"),
    db: Session = Depends(get_db),
):
    start_at = _parse(start, "start")
    end_at = _parse(end, "end")
    if end_at <= start_at:
        raise HTTPException(status_code=400, detail="Bitiş başlangıçtan sonra olmalı")
    return {"reports": build_executive_facts(db, start_at, end_at)}
