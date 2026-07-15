"""
Platform self-update API — admin only.
Paket upload / sunucu drop klasörü / prepare / apply / rollback.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import client_ip, require_role
from app.core.database import get_db
from app.models.user import User
from app.services import platform_update as pu
from app.services.audit import record_audit

logger = logging.getLogger(__name__)
router = APIRouter()


class PrepareRequest(BaseModel):
    path: str = Field(..., description="updates/ altındaki arşiv veya dizin yolu")
    allow_downgrade: bool = False


class ApplyRequest(BaseModel):
    prepared_path: str
    confirm_version: str = Field(..., description="Hedef sürümü tekrar yazın")


class RollbackRequest(BaseModel):
    confirm: bool = False


def _require_capable():
    cap = pu.capability()
    if not cap["enabled"]:
        raise HTTPException(
            status_code=400,
            detail="Platform güncelleme kullanılamıyor: " + "; ".join(cap.get("reasons") or []),
        )
    return cap


@router.get("/status")
def platform_update_status(_admin: User = Depends(require_role("admin"))):
    return pu.capability()


@router.get("/packages")
def platform_update_packages(_admin: User = Depends(require_role("admin"))):
    _require_capable()
    return {"packages": pu.list_packages()}


@router.post("/upload")
async def platform_update_upload(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    _require_capable()
    try:
        info = pu.save_upload(file.filename or "package.tar.gz", file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("platform update upload failed")
        raise HTTPException(status_code=500, detail=str(e))

    record_audit(
        db,
        category="platform",
        action="update_upload",
        actor=admin,
        summary=f"Platform paket yüklendi: {info.get('name')} ({info.get('version')})",
        target_type="package",
        target_id=info.get("version"),
        detail=info,
        ip_address=client_ip(request),
    )
    return {"success": True, "package": info}


@router.post("/prepare")
def platform_update_prepare(
    body: PrepareRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    _require_capable()
    try:
        result = pu.prepare_package(body.path, allow_downgrade=body.allow_downgrade)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("platform update prepare failed")
        raise HTTPException(status_code=500, detail=str(e))

    record_audit(
        db,
        category="platform",
        action="update_prepare",
        actor=admin,
        summary=f"Paket hazırlandı: {result.get('current_version')} → {result.get('target_version')}",
        target_type="package",
        target_id=result.get("target_version"),
        detail=result,
        ip_address=client_ip(request),
    )
    return result


@router.post("/apply")
def platform_update_apply(
    body: ApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    _require_capable()
    job = pu.read_status()
    if job.get("state") == "running":
        raise HTTPException(status_code=409, detail="Zaten bir güncelleme/geri alma çalışıyor")

    try:
        from pathlib import Path
        p = Path(body.prepared_path)
        pu._safe_under(pu.updates_dir(), p)
        info = pu._inspect_package_dir(p)
    except Exception:
        info = None
    if not info:
        raise HTTPException(status_code=400, detail="Hazır paket bulunamadı")

    if (body.confirm_version or "").strip().lstrip("vV") != info["version"]:
        raise HTTPException(
            status_code=400,
            detail=f"Onay sürümü eşleşmiyor (beklenen: {info['version']})",
        )

    try:
        result = pu.apply_update(str(p), actor_name=admin.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("platform update apply failed")
        raise HTTPException(status_code=500, detail=str(e))

    record_audit(
        db,
        category="platform",
        action="update_apply",
        actor=admin,
        summary=f"Platform güncelleme uygulandı: {result.get('old_version')} → {result.get('new_version')}",
        target_type="platform",
        target_id=result.get("new_version"),
        detail=result,
        ip_address=client_ip(request),
    )
    return result


@router.post("/rollback")
def platform_update_rollback(
    body: RollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    _require_capable()
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true gerekli")
    job = pu.read_status()
    if job.get("state") == "running":
        raise HTTPException(status_code=409, detail="Zaten bir güncelleme/geri alma çalışıyor")

    try:
        result = pu.rollback_update(actor_name=admin.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("platform update rollback failed")
        raise HTTPException(status_code=500, detail=str(e))

    record_audit(
        db,
        category="platform",
        action="update_rollback",
        actor=admin,
        summary="Platform geri alma başlatıldı",
        target_type="platform",
        detail=result,
        ip_address=client_ip(request),
    )
    return result


@router.get("/job")
def platform_update_job(_admin: User = Depends(require_role("admin"))):
    return pu.read_status()
