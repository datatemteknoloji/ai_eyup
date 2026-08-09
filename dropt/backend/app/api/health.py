from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.services.bootstrap import get_app_name

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    return {
        "status": "ok",
        "service": get_app_name(session),
        "version": get_settings().app_version,
    }
