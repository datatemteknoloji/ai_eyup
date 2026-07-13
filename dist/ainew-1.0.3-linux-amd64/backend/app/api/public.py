"""
Public (kimlik doğrulama gerektirmeyen) uçlar — marka adı ve logo.
Login sayfası henüz JWT'ye sahip olmadığından bu bilgiler açık uçlardan okunur.
"""
import logging
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from app.core.database import get_db
from app.models.app_settings import AppSettings

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_APP_NAME = "datatem AI"
LOGO_DIR = "/app/uploads/branding"

_EXT_TO_MEDIA_TYPE = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _get_setting(db: Session, key: str) -> str:
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    return row.value if row and row.value else ""


@router.get("/branding")
async def get_branding(db: Session = Depends(get_db)):
    """Marka adı + logo var mı bilgisi — açık uç, giriş ekranından da çağrılır."""
    app_name = _get_setting(db, "branding_app_name") or DEFAULT_APP_NAME
    logo_filename = _get_setting(db, "branding_logo_filename")
    has_logo = bool(logo_filename) and os.path.isfile(os.path.join(LOGO_DIR, logo_filename))
    return {"app_name": app_name, "has_logo": has_logo}


@router.get("/logo")
async def get_logo(db: Session = Depends(get_db)):
    """Yüklenmiş logo dosyasını döner."""
    logo_filename = _get_setting(db, "branding_logo_filename")
    if not logo_filename:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Logo yüklenmemiş")

    path = os.path.join(LOGO_DIR, logo_filename)
    if not os.path.isfile(path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Logo dosyası bulunamadı")

    ext = os.path.splitext(logo_filename)[1].lower()
    media_type = _EXT_TO_MEDIA_TYPE.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})
