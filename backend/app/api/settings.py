"""
Settings API endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()

@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    """Ayarları getir"""
    return {}
