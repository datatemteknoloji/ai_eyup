"""
Repository Yönetimi API

GET    /repos                     → Tüm repo kaynakları
POST   /repos                     → Yeni repo ekle
PUT    /repos/{id}                → Repo güncelle
DELETE /repos/{id}                → Repo sil
GET    /repos/{id}                → Repo detayı
POST   /repos/{id}/sync           → Senkronizasyon başlat
POST   /repos/{id}/sync-metadata  → Sadece metadata sync (RPM indirmeden)
GET    /repos/{id}/jobs           → Sync geçmişi
GET    /repos/{id}/packages       → Paket listesi (arama/filtre)
GET    /repos/packages/compare    → Sunucu paketi vs repo karşılaştır
GET    /repos/{id}/client-config  → .repo dosyası üret
POST   /repos/{id}/push-config    → .repo dosyasını sunuculara SSH ile gönder
GET    /repos/templates           → Hazır repo şablonları
"""
import os
import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.repository import RepoSource, RepoSyncJob, RepoPackage
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.repo_sync_service import (
    run_repo_sync, generate_repo_file, push_repo_file_to_server,
    fetch_rhsm_certs, cancel_job, REPOS_BASE,
)
from app.services.rhsm_sync_service import (
    run_rhsm_sync, list_available_repos, check_subscription_status,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="repo-sync")


# ─── Schemas ─────────────────────────────────────────────────────────────────

class RepoCreateRequest(BaseModel):
    name:         str
    display_name: str
    repo_type:    str = "custom"   # rhel|oel|rocky|alma|centos|custom
    os_version:   Optional[str] = None
    arch:         str = "x86_64"
    base_url:     str
    auth_type:    str = "none"     # none|basic|ssl_cert
    username:     Optional[str] = None
    password:     Optional[str] = None
    ssl_cert:     Optional[str] = None
    ssl_key:      Optional[str] = None
    ssl_ca:       Optional[str] = None

class RepoUpdateRequest(BaseModel):
    display_name:         Optional[str] = None
    base_url:             Optional[str] = None
    auth_type:            Optional[str] = None
    username:             Optional[str] = None
    password:             Optional[str] = None
    ssl_cert:             Optional[str] = None
    ssl_key:              Optional[str] = None
    ssl_ca:               Optional[str] = None
    enabled:              Optional[bool] = None
    # RHSM sync
    sync_method:          Optional[str] = None
    rhsm_repo_id:         Optional[str] = None
    mirror_host:          Optional[str] = None
    mirror_port:          Optional[int] = None
    mirror_username:      Optional[str] = None
    mirror_password:      Optional[str] = None
    mirror_key:           Optional[str] = None
    mirror_download_path: Optional[str] = None

class PushConfigRequest(BaseModel):
    server_ids: List[int]
    server_ip:  str      # IP of this management server (for baseurl)
    port:       int = 8000


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _repo_summary(repo: RepoSource) -> dict:
    return {
        "id":            repo.id,
        "name":          repo.name,
        "display_name":  repo.display_name,
        "repo_type":     repo.repo_type,
        "os_version":    repo.os_version,
        "arch":          repo.arch,
        "base_url":      repo.base_url,
        "auth_type":     repo.auth_type,
        "has_ssl_cert":  bool(repo.ssl_cert),
        "enabled":       repo.enabled,
        "sync_status":   repo.sync_status,
        "last_sync":     repo.last_sync.isoformat() if repo.last_sync else None,
        "package_count": repo.package_count,
        "total_size_mb": repo.total_size_mb,
        "local_path":    repo.local_path,
        # RHSM sync
        "sync_method":          repo.sync_method or "http",
        "rhsm_repo_id":         repo.rhsm_repo_id,
        "mirror_host":          repo.mirror_host or "127.0.0.1",
        "mirror_port":          repo.mirror_port or 22,
        "mirror_username":      repo.mirror_username,
        "mirror_download_path": repo.mirror_download_path or "/var/lib/server_management/repos",
    }


def _start_sync(repo_id: int, db: Session, metadata_only: bool = False) -> dict:
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    if repo.sync_status == "syncing":
        raise HTTPException(400, "Zaten senkronize ediliyor")

    job = RepoSyncJob(repo_id=repo_id, status="pending")
    db.add(job)
    repo.sync_status = "syncing"
    db.commit()
    db.refresh(job)

    _executor.submit(run_repo_sync, repo_id, job.id, metadata_only)
    return {"job_id": job.id, "status": "started"}


# ─── Repo CRUD ────────────────────────────────────────────────────────────────

@router.get("")
def list_repos(db: Session = Depends(get_db)):
    repos = db.query(RepoSource).order_by(RepoSource.created_at.desc()).all()
    return [_repo_summary(r) for r in repos]


# /{repo_id}'den ÖNCE tanımlanmalı — aksi hâlde "aggregate-stats" integer parse hatası verir
@router.get("/aggregate-stats")
def get_aggregate_stats_route(db: Session = Depends(get_db)):
    """Gerçek zamanlı özet: disk'teki RPM sayısı, boyut, aktif sync bilgisi."""
    repos = db.query(RepoSource).all()
    total_rpm = 0; total_bytes = 0; synced_count = 0; syncing_count = 0

    for repo in repos:
        local = repo.local_path or os.path.join(REPOS_BASE, repo.name)
        if os.path.exists(local):
            for root, _, files in os.walk(local):
                for f in files:
                    if f.endswith(".rpm"):
                        total_rpm += 1
                        try: total_bytes += os.path.getsize(os.path.join(root, f))
                        except OSError: pass
        if repo.sync_status == "synced":   synced_count  += 1
        elif repo.sync_status == "syncing": syncing_count += 1

    import sqlalchemy
    row = db.execute(sqlalchemy.text("""
        SELECT COALESCE(SUM(total_packages),0), COALESCE(SUM(synced_packages),0)
        FROM repo_sync_jobs
        WHERE id IN (SELECT MAX(id) FROM repo_sync_jobs GROUP BY repo_id)
          AND status IN ('running','pending')
    """)).fetchone()

    return {
        "total_repos": len(repos), "synced_repos": synced_count, "syncing_repos": syncing_count,
        "total_rpm": total_rpm,
        "disk_mb":   round(total_bytes / (1024*1024), 0),
        "disk_gb":   round(total_bytes / (1024**3), 2),
        "active_total_packages":  int(row[0]) if row else 0,
        "active_synced_packages": int(row[1]) if row else 0,
    }


@router.post("")
def create_repo(req: RepoCreateRequest, db: Session = Depends(get_db)):
    if db.query(RepoSource).filter_by(name=req.name).first():
        raise HTTPException(400, f"'{req.name}' adlı repo zaten mevcut")

    # name slug: lowercase, no spaces
    safe_name = req.name.lower().replace(" ", "-").replace("/", "-")

    repo = RepoSource(
        name=safe_name, display_name=req.display_name,
        repo_type=req.repo_type, os_version=req.os_version,
        arch=req.arch, base_url=req.base_url.rstrip("/"),
        auth_type=req.auth_type,
        username=req.username, password=req.password,
        ssl_cert=req.ssl_cert, ssl_key=req.ssl_key, ssl_ca=req.ssl_ca,
        local_path=os.path.join(REPOS_BASE, safe_name),
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    logger.info(f"Repo oluşturuldu: {safe_name}")
    return _repo_summary(repo)


@router.get("/{repo_id}")
def get_repo(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    return _repo_summary(repo)


@router.put("/{repo_id}")
def update_repo(repo_id: int, req: RepoUpdateRequest, db: Session = Depends(get_db)):
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    for field, val in req.model_dump(exclude_none=True).items():
        setattr(repo, field, val)
    db.commit()
    return _repo_summary(repo)


@router.post("/{repo_id}/cancel-sync")
def cancel_sync(repo_id: int, db: Session = Depends(get_db)):
    """Çalışan sync işini durdur."""
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    if repo.sync_status not in ("syncing",):
        raise HTTPException(400, "Çalışan sync işi yok")

    # Çalışan job'ı bul ve iptal et
    running_job = (
        db.query(RepoSyncJob)
        .filter_by(repo_id=repo_id)
        .filter(RepoSyncJob.status.in_(["pending", "running"]))
        .order_by(RepoSyncJob.id.desc())
        .first()
    )
    if running_job:
        cancel_job(running_job.id)

    # DB'yi hemen güncelle (thread durana kadar görünür)
    repo.sync_status = "cancelled"
    if running_job:
        running_job.status = "cancelled"
        running_job.completed_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Sync iptal edildi: repo #{repo_id}")
    return {"ok": True, "message": "İptal sinyali gönderildi"}


@router.delete("/{repo_id}")
def delete_repo(repo_id: int, force: bool = False, db: Session = Depends(get_db)):
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    if repo.sync_status == "syncing" and not force:
        raise HTTPException(400, "Senkronizasyon devam ediyor. Önce durdurun veya force=true kullanın")
    # Hala syncing ise zorla iptal et
    if repo.sync_status == "syncing":
        running_job = (
            db.query(RepoSyncJob)
            .filter_by(repo_id=repo_id)
            .filter(RepoSyncJob.status.in_(["pending", "running"]))
            .order_by(RepoSyncJob.id.desc())
            .first()
        )
        if running_job:
            cancel_job(running_job.id)
    # Local files temizle
    if repo.local_path and os.path.exists(repo.local_path):
        import shutil
        shutil.rmtree(repo.local_path, ignore_errors=True)
    db.delete(repo)
    db.commit()
    return {"ok": True}


# ─── Sync ─────────────────────────────────────────────────────────────────────

@router.post("/{repo_id}/fetch-rhsm-certs")
def fetch_and_save_rhsm_certs(repo_id: int, db: Session = Depends(get_db)):
    """
    RHSM API üzerinden username/password ile sertifika al, repoya kaydet.
    auth_type otomatik olarak ssl_cert'e güncellenir.
    """
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    if not repo.username or not repo.password:
        raise HTTPException(400, "Repo'da kullanıcı adı/şifre tanımlı değil")
    try:
        certs = fetch_rhsm_certs(repo.username, repo.password)
        repo.ssl_cert  = certs["cert"]
        repo.ssl_key   = certs["key"]
        repo.auth_type = "ssl_cert"
        db.commit()
        logger.info(f"RHSM sertifikaları repo #{repo_id} için kaydedildi")
        return {
            "ok":            True,
            "consumer_uuid": certs["consumer_uuid"],
            "message":       "RHSM sertifikaları başarıyla alındı ve kaydedildi. Artık sync başlatabilirsiniz.",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"RHSM API hatası: {e}")


@router.post("/{repo_id}/sync-rhsm")
def sync_repo_rhsm(repo_id: int, db: Session = Depends(get_db)):
    """
    subscription-manager + reposync tabanlı sync.
    SSH ile mirror host'a bağlanır (varsayılan: localhost).
    """
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    if repo.sync_status == "syncing":
        raise HTTPException(400, "Zaten senkronize ediliyor")
    if not repo.rhsm_repo_id:
        raise HTTPException(400, "rhsm_repo_id tanımlı değil — repo ayarlarından ekleyin")

    job = RepoSyncJob(repo_id=repo_id, status="pending")
    db.add(job)
    repo.sync_status = "syncing"
    db.commit()
    db.refresh(job)

    _executor.submit(run_rhsm_sync, repo_id, job.id)
    logger.info(f"RHSM sync job #{job.id} başlatıldı: {repo.name}")
    return {"job_id": job.id, "status": "started", "method": "rhsm"}


@router.post("/{repo_id}/rhsm-check-status")
def rhsm_check_status(repo_id: int, db: Session = Depends(get_db)):
    """Mirror host'taki subscription-manager durumunu sorgular."""
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    result = check_subscription_status(
        host=repo.mirror_host or "127.0.0.1",
        port=repo.mirror_port or 22,
        username=repo.mirror_username or "root",
        password=repo.mirror_password,
        key=repo.mirror_key,
    )
    return result


@router.post("/{repo_id}/rhsm-list-repos")
def rhsm_list_repos(repo_id: int, db: Session = Depends(get_db)):
    """Mirror host'taki abonelikte mevcut repo ID'lerini listeler."""
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    repos = list_available_repos(
        host=repo.mirror_host or "127.0.0.1",
        port=repo.mirror_port or 22,
        username=repo.mirror_username or "root",
        password=repo.mirror_password,
        key=repo.mirror_key,
    )
    return {"repos": repos, "total": len(repos)}


@router.post("/{repo_id}/sync")
def sync_repo(repo_id: int, db: Session = Depends(get_db)):
    """Tam senkronizasyon — tüm RPM'leri indir."""
    return _start_sync(repo_id, db, metadata_only=False)


@router.post("/{repo_id}/sync-metadata")
def sync_metadata(repo_id: int, db: Session = Depends(get_db)):
    """Sadece paket listesini güncelle, RPM indirme."""
    return _start_sync(repo_id, db, metadata_only=True)


@router.get("/{repo_id}/jobs")
def list_jobs(repo_id: int, limit: int = 5, db: Session = Depends(get_db)):
    """
    Son sync işlerini döner.
    Varsayılan limit=5 — UI'da sadece son 5 iş gösterilir.
    Çok sayıda failed biriktiyse yalnızca en son olanı döner.
    """
    all_jobs = (
        db.query(RepoSyncJob)
        .filter_by(repo_id=repo_id)
        .order_by(RepoSyncJob.id.desc())
        .limit(100)    # max 100 tane al, sonra filtrele
        .all()
    )

    # Dedup: running/pending varsa onu al; her status'tan en fazla 1 tane sakla
    # ama her zaman son `limit` kadar benzersiz işi döndür
    seen_statuses = set()
    filtered = []
    for j in all_jobs:
        key = j.status
        # running/pending → her zaman göster
        if j.status in ("running", "pending"):
            filtered.append(j)
        elif key not in seen_statuses:
            seen_statuses.add(key)
            filtered.append(j)
        if len(filtered) >= limit:
            break

    return [
        {
            "id":               j.id,
            "status":           j.status,
            "total_packages":   j.total_packages,
            "synced_packages":  j.synced_packages,
            "skipped_packages": j.skipped_packages,
            "failed_packages":  j.failed_packages,
            "started_at":       j.started_at.isoformat() if j.started_at else None,
            "completed_at":     j.completed_at.isoformat() if j.completed_at else None,
            "log":              j.log,
        }
        for j in jobs
    ]


@router.get("/{repo_id}/jobs/{job_id}")
def get_job(repo_id: int, job_id: int, db: Session = Depends(get_db)):
    job = db.query(RepoSyncJob).filter_by(id=job_id, repo_id=repo_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    return {
        "id":               job.id,
        "status":           job.status,
        "total_packages":   job.total_packages,
        "synced_packages":  job.synced_packages,
        "skipped_packages": job.skipped_packages,
        "failed_packages":  job.failed_packages,
        "started_at":       job.started_at.isoformat() if job.started_at else None,
        "completed_at":     job.completed_at.isoformat() if job.completed_at else None,
        "log":              job.log,
    }


# ─── Package Browse ───────────────────────────────────────────────────────────

@router.get("/{repo_id}/packages")
def list_packages(
    repo_id: int,
    search:     str  = Query(""),
    arch:       str  = Query(""),
    downloaded: Optional[bool] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(RepoPackage).filter_by(repo_id=repo_id)
    if search:
        q = q.filter(RepoPackage.name.ilike(f"%{search}%"))
    if arch:
        q = q.filter_by(arch=arch)
    if downloaded is not None:
        q = q.filter_by(downloaded=downloaded)

    total = q.count()
    pkgs  = q.order_by(RepoPackage.name).offset(skip).limit(limit).all()

    return {
        "total": total,
        "packages": [
            {
                "id":          p.id,
                "name":        p.name,
                "version":     p.version,
                "release":     p.release,
                "epoch":       p.epoch,
                "arch":        p.arch,
                "summary":     p.summary,
                "size_bytes":  p.size_bytes,
                "downloaded":  p.downloaded,
                "location":    p.location,
            }
            for p in pkgs
        ],
    }


@router.get("/{repo_id}/progress")
def get_sync_progress(repo_id: int, db: Session = Depends(get_db)):
    """Anlık sync ilerlemesi: disk'teki gerçek RPM sayısı + son job bilgisi."""
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")

    job = (
        db.query(RepoSyncJob)
        .filter_by(repo_id=repo_id)
        .order_by(RepoSyncJob.id.desc())
        .first()
    )

    rpm_count = 0
    disk_bytes = 0
    local = repo.local_path or os.path.join(REPOS_BASE, repo.name)
    if os.path.exists(local):
        for root, _, files in os.walk(local):
            for f in files:
                if f.endswith(".rpm"):
                    rpm_count += 1
                    try:
                        disk_bytes += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass

    return {
        "repo_id":        repo_id,
        "sync_status":    repo.sync_status,
        "rpm_on_disk":    rpm_count,
        "disk_mb":        round(disk_bytes / (1024 * 1024), 1),
        "total_packages": job.total_packages if job else 0,
        "synced_packages":job.synced_packages if job else 0,
        "failed_packages":job.failed_packages if job else 0,
        "job_status":     job.status if job else None,
        "started_at":     job.started_at.isoformat() if job and job.started_at else None,
        "log_tail":       "\n".join((job.log or "").splitlines()[-8:]) if job else "",
    }


@router.get("/{repo_id}/packages/stats")
def package_stats(repo_id: int, db: Session = Depends(get_db)):
    total      = db.query(RepoPackage).filter_by(repo_id=repo_id).count()
    downloaded = db.query(RepoPackage).filter_by(repo_id=repo_id, downloaded=True).count()
    return {"total": total, "downloaded": downloaded, "pending": total - downloaded}


# ─── Client Config ────────────────────────────────────────────────────────────

@router.get("/{repo_id}/client-config")
def get_client_config(
    repo_id:    int,
    server_ip:  str = Query(..., description="Bu yönetim sunucusunun IP'si"),
    port:       int = Query(8000),
    db: Session = Depends(get_db),
):
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")
    content = generate_repo_file(repo, server_ip, port)
    return {"filename": f"{repo.name}.repo", "content": content}


@router.post("/{repo_id}/push-config")
def push_client_config(repo_id: int, req: PushConfigRequest, db: Session = Depends(get_db)):
    repo = db.query(RepoSource).filter_by(id=repo_id).first()
    if not repo:
        raise HTTPException(404, "Repo bulunamadı")

    repo_file = generate_repo_file(repo, req.server_ip, req.port)
    servers   = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    if not servers:
        raise HTTPException(400, "Sunucu bulunamadı")

    global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                  or db.query(GlobalCredential).first()

    results = {}
    for srv in servers:
        res = push_repo_file_to_server(srv, repo_file, repo.name, global_cred)
        results[str(srv.id)] = {**res, "server_name": srv.name, "server_ip": srv.ip_address}

    return {"results": results}


# ─── Templates ────────────────────────────────────────────────────────────────

# ─── Ürün bazlı şablonlar (Satellite/Foreman benzeri) ─────────────────────────
# Her ürün bir OS versiyonu, tek kimlik bilgisi ve seçilebilir kanallar içerir.
PRODUCT_TEMPLATES = [
    # ── Red Hat Enterprise Linux ──────────────────────────────────────────
    # url_template: {version} → seçilen minor release (9.5) veya major (9 = latest)
    {
        "product": "RHEL 9", "repo_type": "rhel", "os_version": "9",
        "auth_type": "basic", "arch": "x86_64", "icon": "rhel",
        "version_options": [
            {"label": "9.7 (güncel)", "value": "9.7", "is_latest": True},
            {"label": "9.6",          "value": "9.6"},
            {"label": "9.5",          "value": "9.5"},
            {"label": "9.4",          "value": "9.4"},
            {"label": "9.3",          "value": "9.3"},
            {"label": "9.2",          "value": "9.2"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",            "default": True,
             "rhsm_repo_id": "rhel-9-for-x86_64-baseos-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel9/{version}/x86_64/baseos/os/"},
            {"key": "appstream", "label": "AppStream",         "default": True,
             "rhsm_repo_id": "rhel-9-for-x86_64-appstream-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel9/{version}/x86_64/appstream/os/"},
            {"key": "ha",        "label": "High Availability", "default": False,
             "rhsm_repo_id": "rhel-9-for-x86_64-highavailability-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel9/{version}/x86_64/highavailability/os/"},
            {"key": "sap",       "label": "SAP",               "default": False,
             "rhsm_repo_id": "rhel-9-for-x86_64-sap-netweaver-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel9/{version}/x86_64/sap/os/"},
            {"key": "extras",    "label": "Extras",            "default": False,
             "rhsm_repo_id": "rhel-9-extras-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel9/{version}/x86_64/extras/os/"},
        ],
    },
    {
        "product": "RHEL 8", "repo_type": "rhel", "os_version": "8",
        "auth_type": "basic", "arch": "x86_64", "icon": "rhel",
        "version_options": [
            {"label": "8.10 (güncel)", "value": "8.10", "is_latest": True},
            {"label": "8.9",           "value": "8.9"},
            {"label": "8.8",           "value": "8.8"},
            {"label": "8.7",           "value": "8.7"},
            {"label": "8.6",           "value": "8.6"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",            "default": True,
             "rhsm_repo_id": "rhel-8-for-x86_64-baseos-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel8/{version}/x86_64/baseos/os/"},
            {"key": "appstream", "label": "AppStream",         "default": True,
             "rhsm_repo_id": "rhel-8-for-x86_64-appstream-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel8/{version}/x86_64/appstream/os/"},
            {"key": "ha",        "label": "High Availability", "default": False,
             "rhsm_repo_id": "rhel-8-for-x86_64-highavailability-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel8/{version}/x86_64/highavailability/os/"},
            {"key": "sap",       "label": "SAP",               "default": False,
             "rhsm_repo_id": "rhel-8-for-x86_64-sap-netweaver-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel8/{version}/x86_64/sap/os/"},
            {"key": "extras",    "label": "Extras",            "default": False,
             "rhsm_repo_id": "rhel-8-extras-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel8/{version}/x86_64/extras/os/"},
        ],
    },
    {
        "product": "RHEL 7", "repo_type": "rhel", "os_version": "7",
        "auth_type": "basic", "arch": "x86_64", "icon": "rhel",
        "version_options": [
            {"label": "7.9 (güncel)", "value": "7.9", "is_latest": True},
            {"label": "7.8",          "value": "7.8"},
            {"label": "7.7",          "value": "7.7"},
        ],
        "channels": [
            {"key": "server",   "label": "Server",            "default": True,
             "rhsm_repo_id": "rhel-7-server-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel/server/7/{version}/x86_64/os/"},
            {"key": "extras",   "label": "Extras",            "default": True,
             "rhsm_repo_id": "rhel-7-server-extras-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel/server/7/{version}/x86_64/extras/os/"},
            {"key": "optional", "label": "Optional",          "default": False,
             "rhsm_repo_id": "rhel-7-server-optional-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel/server/7/{version}/x86_64/optional/os/"},
            {"key": "ha",       "label": "High Availability", "default": False,
             "rhsm_repo_id": "rhel-7-server-ha-rpms",
             "url_template": "https://cdn.redhat.com/content/dist/rhel/server/7/{version}/x86_64/highavailability/os/"},
        ],
    },
    # ── Oracle Enterprise Linux ───────────────────────────────────────────
    # OEL public repo her zaman "latest" rolling'dir — URL versiyona göre değişmez.
    # Versiyon seçimi sadece repo adında/gösteriminde kullanılır (belgeleme amaçlı).
    {
        "product": "OEL 9", "repo_type": "oel", "os_version": "9",
        "auth_type": "none", "arch": "x86_64", "icon": "oel",
        "url_versioned": False,   # URL değişmez, sadece isimde kullanılır
        "version_options": [
            {"label": "9.5 (güncel)", "value": "9.5", "is_latest": True},
            {"label": "9.4",          "value": "9.4"},
            {"label": "9.3",          "value": "9.3"},
            {"label": "9.2",          "value": "9.2"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",            "default": True,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL9/baseos/latest/x86_64/"},
            {"key": "appstream", "label": "AppStream",         "default": True,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL9/appstream/x86_64/"},
            {"key": "uekr7",     "label": "UEK Release 7",     "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL9/UEKR7/x86_64/"},
            {"key": "addons",    "label": "EPEL Addons",       "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL9/addons/x86_64/"},
        ],
    },
    {
        "product": "OEL 8", "repo_type": "oel", "os_version": "8",
        "auth_type": "none", "arch": "x86_64", "icon": "oel",
        "url_versioned": False,
        "version_options": [
            {"label": "8.10 (güncel)", "value": "8.10", "is_latest": True},
            {"label": "8.9",           "value": "8.9"},
            {"label": "8.8",           "value": "8.8"},
            {"label": "8.7",           "value": "8.7"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",            "default": True,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL8/baseos/latest/x86_64/"},
            {"key": "appstream", "label": "AppStream",         "default": True,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL8/appstream/x86_64/"},
            {"key": "uekr6",     "label": "UEK Release 6",     "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL8/UEKR6/x86_64/"},
            {"key": "codeready", "label": "CodeReady Builder", "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL8/codeready/builder/x86_64/"},
        ],
    },
    {
        "product": "OEL 7", "repo_type": "oel", "os_version": "7",
        "auth_type": "none", "arch": "x86_64", "icon": "oel",
        "url_versioned": False,
        "version_options": [
            {"label": "7.9 (güncel)", "value": "7.9", "is_latest": True},
            {"label": "7.8",          "value": "7.8"},
            {"label": "7.7",          "value": "7.7"},
        ],
        "channels": [
            {"key": "latest",  "label": "Latest",        "default": True,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL7/latest/x86_64/"},
            {"key": "uekr6",   "label": "UEK Release 6", "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL7/UEKR6/x86_64/"},
            {"key": "addons",  "label": "Addons",        "default": False,
             "url_template": "https://yum.oracle.com/repo/OracleLinux/OL7/addons/x86_64/"},
        ],
    },
    # ── Rocky Linux ───────────────────────────────────────────────────────
    {
        "product": "Rocky Linux 9", "repo_type": "rocky", "os_version": "9",
        "auth_type": "none", "arch": "x86_64", "icon": "rocky",
        "version_options": [
            {"label": "9.5 (güncel)", "value": "9.5", "is_latest": True},
            {"label": "9.4",          "value": "9.4"},
            {"label": "9.3",          "value": "9.3"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",    "default": True,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/BaseOS/x86_64/os/"},
            {"key": "appstream", "label": "AppStream", "default": True,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/AppStream/x86_64/os/"},
            {"key": "extras",    "label": "Extras",    "default": False,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/extras/x86_64/os/"},
            {"key": "crb",       "label": "CRB",       "default": False,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/CRB/x86_64/os/"},
        ],
    },
    {
        "product": "Rocky Linux 8", "repo_type": "rocky", "os_version": "8",
        "auth_type": "none", "arch": "x86_64", "icon": "rocky",
        "version_options": [
            {"label": "8.10 (güncel)", "value": "8.10", "is_latest": True},
            {"label": "8.9",           "value": "8.9"},
            {"label": "8.8",           "value": "8.8"},
        ],
        "channels": [
            {"key": "baseos",    "label": "BaseOS",    "default": True,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/BaseOS/x86_64/os/"},
            {"key": "appstream", "label": "AppStream", "default": True,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/AppStream/x86_64/os/"},
            {"key": "extras",    "label": "Extras",    "default": False,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/extras/x86_64/os/"},
            {"key": "powertools","label": "PowerTools", "default": False,
             "url_template": "https://dl.rockylinux.org/pub/rocky/{version}/PowerTools/x86_64/os/"},
        ],
    },
    # ── Ubuntu (apt format — yakında desteklenecek) ───────────────────────
    {
        "product": "Ubuntu", "repo_type": "ubuntu", "os_version": "24.04",
        "auth_type": "none", "arch": "amd64", "icon": "ubuntu",
        "version_options": [
            {"label": "24.04 Noble (güncel)", "value": "noble",    "is_latest": True},
            {"label": "22.04 Jammy",          "value": "jammy"},
            {"label": "20.04 Focal",          "value": "focal"},
        ],
        "channels": [
            {"key": "main",       "label": "Main",       "default": True,
             "url_template": "http://archive.ubuntu.com/ubuntu/dists/{version}/main/binary-amd64/"},
            {"key": "updates",    "label": "Updates",    "default": True,
             "url_template": "http://archive.ubuntu.com/ubuntu/dists/{version}-updates/main/binary-amd64/"},
            {"key": "security",   "label": "Security",   "default": True,
             "url_template": "http://security.ubuntu.com/ubuntu/dists/{version}-security/main/binary-amd64/"},
            {"key": "universe",   "label": "Universe",   "default": False,
             "url_template": "http://archive.ubuntu.com/ubuntu/dists/{version}/universe/binary-amd64/"},
        ],
        "format_note": "apt",
    },
]


class BatchRepoChannel(BaseModel):
    key:                  str
    base_url:             str
    name_override:        Optional[str] = None   # tam slug override
    display_name_override: Optional[str] = None  # tam görünen ad

class BatchRepoRequest(BaseModel):
    product:        str           # "RHEL 9"
    repo_type:      str
    os_version:     str
    arch:           str = "x86_64"
    auth_type:      str = "none"
    username:       Optional[str] = None
    password:       Optional[str] = None
    ssl_cert:       Optional[str] = None
    ssl_key:        Optional[str] = None
    snapshot_label: Optional[str] = None   # "2026-05-12" gibi tarih etiketi
    channels:       List[BatchRepoChannel]


@router.post("/batch")
def create_repos_batch(req: BatchRepoRequest, db: Session = Depends(get_db)):
    """Bir ürünün seçili kanallarını tek seferde oluştur."""
    created = []
    skipped = []
    product_slug = req.product.lower().replace(" ", "-")

    label_suffix = f"-{req.snapshot_label}" if req.snapshot_label else ""

    for ch in req.channels:
        base_name = ch.name_override or f"{product_slug}-{ch.key}"
        name = (base_name + label_suffix).lower().replace(" ", "-")
        base_display = ch.display_name_override or f"{req.product} {ch.key.capitalize()}"
        display_name = f"{base_display} [{req.snapshot_label}]" if req.snapshot_label else base_display

        if db.query(RepoSource).filter_by(name=name).first():
            skipped.append(name)
            continue

        repo = RepoSource(
            name=name, display_name=display_name,
            repo_type=req.repo_type, os_version=req.os_version,
            arch=req.arch, base_url=ch.base_url.rstrip("/"),
            auth_type=req.auth_type,
            username=req.username, password=req.password,
            ssl_cert=req.ssl_cert, ssl_key=req.ssl_key,
            local_path=os.path.join(REPOS_BASE, name),
        )
        db.add(repo)
        created.append(name)

    db.commit()
    logger.info(f"Batch repo oluşturuldu: {created}, atlandı: {skipped}")
    return {"created": created, "skipped": skipped}


@router.get("/templates/products")
def get_product_templates():
    return PRODUCT_TEMPLATES


