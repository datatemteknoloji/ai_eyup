"""
Alerts API endpoints
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db

router = APIRouter()

@router.get("/")
async def list_alerts(
    status: Optional[str] = Query(None, description="Alert status filter"),
    db: Session = Depends(get_db)
):
    """Alert'leri listele"""
    # Şimdilik boş liste döndür (alert modeli yoksa)
    return []
