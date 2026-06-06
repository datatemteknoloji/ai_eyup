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
import requests as http_requests
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.auth import require_role
from app.models.package_job import PackageFile, PackageJob
from app.models.server import Server
from app.models.app_settings import AppSettings
from app.services.package_service import run_package_job, UPLOADS_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pkg-job")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class DeployRequest(BaseModel):
    package_file_id: int
    server_ids: List[int]
    override_user:          Optional[str] = None
    override_password:      Optional[str] = None
    override_sudo_password: Optional[str] = None

class UpgradeRequest(BaseModel):
    server_ids: List[int]
    security_only: bool = False

class CheckUpdatesRequest(BaseModel):
    server_ids: List[int]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_uploads_dir():
    os.makedirs(UPLOADS_DIR, exist_ok=True)



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


import re as _re

_SAFE_FILENAME_RE = _re.compile(r'^[A-Za-z0-9_.\-+~]+\.(deb|rpm)$')


def _sanitize_package_name(raw: str) -> str:
    """Basename al, yalnızca güvenli karakterlere izin ver, path traversal engelle."""
    name = os.path.basename(raw or "package")
    # Shell metacharacter ve path seperatör temizle
    name = _re.sub(r'[^\w.\-+~]', '_', name)
    if not _SAFE_FILENAME_RE.match(name):
        raise HTTPException(400, "Geçersiz dosya adı — yalnızca .deb ve .rpm kabul edilir, "
                                 "dosya adı harf/rakam/tire/nokta içerebilir")
    return name


@router.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _: object = Depends(require_role("operator")),
):
    _ensure_uploads_dir()

    original_name = _sanitize_package_name(file.filename or "package.rpm")
    ext = original_name.rsplit(".", 1)[-1].lower()
    pkg_type = "deb" if ext == "deb" else ("rpm" if ext == "rpm" else "unknown")

    if pkg_type == "unknown":
        raise HTTPException(400, "Yalnızca .deb ve .rpm dosyaları kabul edilir")

    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    # path traversal engeli: normpath sonucu UPLOADS_DIR içinde kalmalı
    file_path = os.path.normpath(os.path.join(UPLOADS_DIR, stored_name))
    if not file_path.startswith(os.path.abspath(UPLOADS_DIR)):
        raise HTTPException(400, "Geçersiz dosya yolu")

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
def delete_file(file_id: int, db: Session = Depends(get_db), _: object = Depends(require_role("operator"))):
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
    d["live_log"]   = job.live_log or {}
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
def delete_job(job_id: int, db: Session = Depends(get_db), _: object = Depends(require_role("operator"))):
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
def deploy_package(req: DeployRequest, db: Session = Depends(get_db), _: object = Depends(require_role("operator"))):
    pkg = db.query(PackageFile).filter_by(id=req.package_file_id).first()
    if not pkg:
        raise HTTPException(404, "Paket dosyası bulunamadı")
    if not os.path.exists(pkg.file_path):
        raise HTTPException(410, "Paket dosyası sunucuda yok, tekrar yükleyin")

    servers = _get_servers(db, req.server_ids)

    job = PackageJob(
        job_type=         "deploy",
        status=           "pending",
        title=            f"{pkg.original_name} → {len(servers)} sunucu",
        package_file_id=  pkg.id,
        server_ids=       req.server_ids,
        total_servers=    len(servers),
        completed_servers=0,
        results=          {},
        live_log=         {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Thread'e sadece ID'ler geç — session sorunu olmaz
    _executor.submit(
        run_package_job,
        job.id, req.server_ids,          # server nesnesi değil, ID listesi
        "deploy", pkg.file_path, pkg.original_name, False,
        req.override_user or None,
        req.override_password or None,
        req.override_sudo_password or None,
    )

    logger.info(f"Deploy işi #{job.id} başlatıldı: {pkg.original_name}")
    return _job_summary(job)


# ─── Upgrade ──────────────────────────────────────────────────────────────────

@router.post("/jobs/upgrade")
def upgrade_servers(req: UpgradeRequest, db: Session = Depends(get_db), _: object = Depends(require_role("operator"))):
    servers = _get_servers(db, req.server_ids)
    label   = "Güvenlik güncellemesi" if req.security_only else "Tam sistem güncellemesi"

    job = PackageJob(
        job_type=         "upgrade",
        status=           "pending",
        title=            f"{label} → {len(servers)} sunucu",
        server_ids=       req.server_ids,
        total_servers=    len(servers),
        completed_servers=0,
        results=          {},
        live_log=         {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _executor.submit(
        run_package_job,
        job.id, req.server_ids,
        "upgrade", "", "", req.security_only,
    )

    logger.info(f"Upgrade işi #{job.id} başlatıldı: {len(servers)} sunucu")
    return _job_summary(job)


# ─── Check Updates ────────────────────────────────────────────────────────────

@router.post("/jobs/check-updates")
def check_updates(req: CheckUpdatesRequest, db: Session = Depends(get_db), _: object = Depends(require_role("operator"))):
    servers = _get_servers(db, req.server_ids)

    job = PackageJob(
        job_type=         "check_updates",
        status=           "pending",
        title=            f"Güncelleme kontrolü → {len(servers)} sunucu",
        server_ids=       req.server_ids,
        total_servers=    len(servers),
        completed_servers=0,
        results=          {},
        live_log=         {},
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _executor.submit(
        run_package_job,
        job.id, req.server_ids,
        "check_updates",
    )

    return _job_summary(job)


# ─── AI Error Analysis ────────────────────────────────────────────────────────

def _get_active_model(db: Session) -> str:
    row = db.query(AppSettings).filter_by(key="ollama_active_model").first()
    return (row.value if row and row.value else None) or getattr(settings, "OLLAMA_DEFAULT_MODEL", "llama3")


@router.post("/jobs/{job_id}/analyze-error")
def analyze_job_error(job_id: int, db: Session = Depends(get_db)):
    """Başarısız paket job'ının hata çıktısını AI ile analiz eder, çözüm önerir."""
    job = db.query(PackageJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    if job.status not in ("failed", "partial"):
        raise HTTPException(400, "Sadece başarısız/kısmi işler analiz edilebilir")

    results: dict = job.results or {}
    if not results:
        raise HTTPException(400, "Sonuç kaydı yok, analiz yapılamaz")

    # Tüm başarısız sunucuların hata çıktılarını topla
    error_sections: list[str] = []
    for sid, res in results.items():
        if res.get("status") != "success":
            srv = db.query(Server).filter_by(id=int(sid)).first()
            srv_label = srv.name if srv else f"Sunucu #{sid}"
            ip = srv.ip_address if srv else ""
            os_info = f"{(srv.os_release_id or '').upper()} {srv.os_version_id or ''}" if srv else ""
            out   = (res.get("output") or "")[-2000:]
            err   = (res.get("error")  or "")[-1000:]
            error_sections.append(
                f"### {srv_label} ({ip}) {os_info}\n"
                f"**Çıktı:**\n{out}\n"
                f"**Hata:**\n{err}"
            )

    if not error_sections:
        return {"analysis": "Tüm sunucular başarılı — analiz gerekmiyor."}

    pkg_name = job.package_file.original_name if job.package_file else "paket"
    combined = "\n\n---\n\n".join(error_sections)

    prompt = f"""Linux sistem yöneticisi olarak aşağıdaki paket kurulum hatasını Türkçe analiz et:

Paket: {pkg_name}
İş tipi: {job.job_type}

{combined}

Lütfen şunları açıkla:
1. **Hatanın sebebi nedir?** (bağımlılık eksikliği, imza sorunu, sürüm uyumsuzluğu vb.)
2. **Çözüm adımları:** Hangi komutlarla/yöntemlerle düzeltilebilir?
3. **Alternatif yöntem:** Farklı bir kurulum yöntemi var mı?

Kısa, pratik ve uygulanabilir ol. Komutları kod bloğu içinde ver."""

    try:
        active_model = _get_active_model(db)
        r = http_requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": active_model, "prompt": prompt, "stream": False},
            timeout=90,
        )
        analysis = r.json().get("response", "AI yanıt vermedi") if r.status_code == 200 \
                   else f"AI servisine ulaşılamadı (HTTP {r.status_code})"
    except Exception as exc:
        analysis = f"AI analizi yapılamadı: {exc}"

    return {"analysis": analysis, "job_id": job_id, "package": pkg_name}
