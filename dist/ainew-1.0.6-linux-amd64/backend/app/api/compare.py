"""
Sunucu / VM / ESX karşılaştırma API.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import compare_service as svc

router = APIRouter()


class CompareRequest(BaseModel):
    platform: str = Field(..., description="linux | windows | virt")
    entity_type: str = Field("server", description="server | vm | esx")
    ids: List[int] = Field(..., min_length=2, max_length=3)
    with_ai: bool = True
    question: Optional[str] = None


@router.get("/candidates")
def get_candidates(
    platform: str = Query("linux"),
    entity_type: str = Query("server"),
    db: Session = Depends(get_db),
):
    """Karşılaştırma için seçilebilir kayıt listesi."""
    try:
        items = svc.list_candidates(db, platform, entity_type)
        return {"items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def compare(payload: CompareRequest, db: Session = Depends(get_db)):
    """2–3 kaydı config + mimari olarak karşılaştır; isteğe bağlı AI yorumu."""
    try:
        result = await svc.run_compare(
            db,
            platform=payload.platform,
            entity_type=payload.entity_type,
            ids=payload.ids,
            with_ai=payload.with_ai,
            question=payload.question,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
