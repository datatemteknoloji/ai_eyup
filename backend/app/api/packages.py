"""
Paket Yönetimi API
  GET    /packages/files             → Yüklenen paketler listesi
  POST   /packages/files/upload      → .deb/.rpm yükle
  DELETE /packages/files/{id}        → Paketi sil
  POST   /packages/jobs/deploy       → Seçili sunuculara paket dağıt
  POST   /packages/jobs/upgrade      → Sistem güncellemesi yap
  POST   /packages/jobs/check-updates → Güncelleme listesi çıkar
  GET    /packages/jobs              → İş geçmişi
  GET    /packages/jobs/{id}         → İş detayı
  DELETE /packages/jobs/{id}         → İşi sil
"""
import os
import uuid
import logging
import asyncio
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.package_job import PackageFile, PackageJob
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.package_service import run_package_job, UPLOADS_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pkg-job")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class DeployRequest(BaseModel):
    package_file_id: int
    server_ids: List[int]

class UpgradeRequest(BaseModel):
    server_ids: List[int]
    security_only: bool = False

class CheckUpdatesRequest(BaseModel):
    server_ids: List[int]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_uploads_dir():
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def _get_global_cred(db: Session) -> Optional[GlobalCredential]:
    return db.query(GlobalCredential).filter_by(is_default=True).first() \
           or db.query(GlobalCredential).first()


def _get_servers(db: Session, server_ids: List[int]) -> List[Server]:
    servers = db.query(Server).filter(Server.id.in_(server_ids)).all()
    if not servers:
        raise HTTPException(400, "Seçilen sunucular bulunamadı")
    return servers


# ─── Package Files ────────────────────────────────────────────────────────────

@router.get("/files")
def list_files(db: Session = Depends(get_db)):
    files = db.query(PackageFile).order_by(PackageFile.created_at.desc()).all()
    return [
        {
            "id":            f.id,
            "original_name": f.original_name,
            "file_size":     f.file_size,
            "package_type":  f.package_type,
            "description":   f.description,
            "created_at":    f.created_at.isoformat() if f.created_at else None,
        }
        for f in files
    ]


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    _ensure_uploads_dir()

    original_name = file.filename or "package"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "unknown"
    pkg_type = "deb" if ext == "deb" else ("rpm" if ext == "rpm" else "unknown")

    if pkg_type == "unknown":
        raise HTTPException(400, "Yalnızca .deb ve .rpm dosyaları kabul edilir")

    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    file_path   = os.path.join(UPLOADS_DIR, stored_name)

    content = await file.read()
    with open(file_path, "wb") as fh:
        fh.write(content)

    pkg = PackageFile(
        filename=stored_name,
        original_name=original_name,
        file_path=file_path,
        file_size=len(content),
        package_type=pkg_type,
        description=description or None,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)

    logger.info(f"Paket yüklendi: {original_name} ({len(content)//1024} KB)")
    return {"id": pkg.id, "original_name": original_name, "package_type": pkg_type,
            "file_size": len(content)}


@router.delete("/files/{file_id}")
def delete_file(file_id: int, db: Session = Depends(get_db)):
    pkg = db.query(PackageFile).filter_by(id=file_id).first()
    if not pkg:
        raise HTTPException(404, "Paket bulunamadı")

    if os.path.exists(pkg.file_path):
        os.remove(pkg.file_path)

    db.delete(pkg)
    db.commit()
    return {"ok": True}


# ─── Jobs ─────────────────────────────────────────────────────────────────────

def _job_summary(job: PackageJob) -> dict:
    return {
        "id":                job.id,
        "job_type":          job.job_type,
        "status":            job.status,
        "title":             job.title,
        "total_servers":     job.total_servers,
        "completed_servers": job.completed_servers,
        "created_at":        job.created_at.isoformat() if job.created_at else None,
        "completed_at":      job.completed_at.isoformat() if job.completed_at else None,
        "package_name":      job.package_file.original_name if job.package_file else None,
    }


def _job_detail(job: PackageJob) -> dict:
    d = _job_summary(job)
    d["results"]    = job.results or {}
    d["server_ids"] = job.server_ids or []
    return d


@router.get("/jobs")
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = (
        db.query(PackageJob)
        .order_by(PackageJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_job_summary(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(PackageJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    return _job_detail(job)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(PackageJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    if job.status == "running":
        raise HTTPException(400, "Çalışan iş silinemez")
    db.delete(job)
    db.commit()
    return {"ok": True}


# ─── Deploy ───────────────────────────────────────────────────────────────────

@router.post("/jobs/deploy")
def deploy_package(req: DeployRequest, db: Session = Depends(get_db)):
    pkg = db.query(PackageFile).filter_by(id=req.package_file_id).first()
    if not pkg:
        raise HTTPException(404, "Paket dosyası bulunamadı")
    if not os.path.exists(pkg.file_path):
        raise HTTPException(410, "Paket dosyası sunucuda yok, tekrar yükleyin")

    servers    = _get_servers(db, req.server_ids)
    global_cred = _get_global_cred(db)

    job = PackageJob(
        job_type=        "deploy",
        status=          "pending",
        title=           f"{pkg.original_name} → {len(servers)} sunucu",
        package_file_id= pkg.id,
        server_ids=      req.server_ids,
        total_servers=   len(servers),
        completed_servers=0,
        results=         {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _executor.submit(
        run_package_job,
        job.id, servers, global_cred,
        "deploy", pkg.file_path, pkg.original_name,
    )

    logger.info(f"Deploy işi #{job.id} başlatıldı: {pkg.original_name}")
    return _job_summary(job)


# ─── Upgrade ──────────────────────────────────────────────────────────────────

@router.post("/jobs/upgrade")
def upgrade_servers(req: UpgradeRequest, db: Session = Depends(get_db)):
    servers     = _get_servers(db, req.server_ids)
    global_cred = _get_global_cred(db)

    label = "Güvenlik güncellemesi" if req.security_only else "Tam sistem güncellemesi"

    job = PackageJob(
        job_type=         "upgrade",
        status=           "pending",
        title=            f"{label} → {len(servers)} sunucu",
        server_ids=       req.server_ids,
        total_servers=    len(servers),
        completed_servers=0,
        results=          {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _executor.submit(
        run_package_job,
        job.id, servers, global_cred,
        "upgrade", "", "", req.security_only,
    )

    logger.info(f"Upgrade işi #{job.id} başlatıldı: {len(servers)} sunucu")
    return _job_summary(job)


# ─── Check Updates ────────────────────────────────────────────────────────────

@router.post("/jobs/check-updates")
def check_updates(req: CheckUpdatesRequest, db: Session = Depends(get_db)):
    servers     = _get_servers(db, req.server_ids)
    global_cred = _get_global_cred(db)

    job = PackageJob(
        job_type=         "check_updates",
        status=           "pending",
        title=            f"Güncelleme kontrolü → {len(servers)} sunucu",
        server_ids=       req.server_ids,
        total_servers=    len(servers),
        completed_servers=0,
        results=          {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _executor.submit(
        run_package_job,
        job.id, servers, global_cred,
        "check_updates",
    )

    return _job_summary(job)
