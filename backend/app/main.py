"""
FastAPI Main Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI app oluştur
app = FastAPI(
    title="Server Management API",
    version="1.0.0",
    description="Server Management System API"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API router'ı ekle (try-except ile hata yönetimi)
try:
    from app.api.router import api_router
    app.include_router(api_router, prefix="/api/v1")
    logger.info("API router loaded successfully")
except Exception as e:
    logger.error(f"Failed to load API router: {e}")
    import traceback
    traceback.print_exc()
    # Fallback router oluştur
    from fastapi import APIRouter
    fallback_router = APIRouter()
    
    @fallback_router.get("/servers/")
    async def list_servers_fallback():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"API router yüklenemedi: {e}")
    
    app.include_router(fallback_router, prefix="/api/v1")

_SSH_EXECUTOR = ThreadPoolExecutor(max_workers=50, thread_name_prefix="ssh_worker")

@app.on_event("startup")
async def startup_tasks():
    """Uygulama başlangıcında yapılacak işlemler"""
    # Paralel SSH bağlantıları için geniş thread pool
    loop = asyncio.get_event_loop()
    loop.set_default_executor(_SSH_EXECUTOR)
    logger.info("SSH thread pool başlatıldı (max_workers=50)")
    # Tabloları oluştur
    from app.core.database import engine, Base
    import app.models  # noqa: F401 - modelleri Base.metadata'ya kaydetmek için
    Base.metadata.create_all(bind=engine)

    # Hafif şema güncellemeleri (mevcut tablolara eksik kolon ekle — idempotent)
    try:
        from sqlalchemy import text as _sa_text
        with engine.begin() as _conn:
            _conn.execute(_sa_text(
                "ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS requires_root BOOLEAN DEFAULT FALSE"
            ))
    except Exception as _mig_e:
        logger.debug(f"agent_actions migration skip: {_mig_e}")
    
    # TimescaleDB hypertable'ları oluştur
    try:
        from app.core.init_timescale import init_timescaledb
        init_timescaledb()
        logger.info("✅ TimescaleDB initialized")
    except Exception as e:
        logger.warning(f"⚠️ TimescaleDB initialization failed (will continue without time-series optimization): {e}")
    
    # Background task'ları başlat (her 5 dakikada ping kontrolü)
    from app.background_tasks import background_task_manager
    await background_task_manager.start()
    logger.info("Background tasks started (health checks every 5 minutes)")

    # Yarım kalan system update planlarını yeniden başlat
    try:
        from app.core.database import SessionLocal as _SL2
        from app.models.system_update import SystemUpdatePlan as _SUP, SystemUpdateJob as _SUJ
        from app.services.system_update_service import run_system_update_plan as _rsp
        import threading as _th
        _db2 = _SL2()
        _running_plans = _db2.query(_SUP).filter(_SUP.status == "running").all()
        for _p in _running_plans:
            _t = _th.Thread(target=_rsp, args=(_p.id,), daemon=True, name=f"sysupdate-{_p.id}")
            _t.start()
            logger.info(f"System update plan #{_p.id} devam ettiriliyor: {_p.name}")
        _db2.close()
    except Exception as _e2:
        logger.debug(f"System update resume: {_e2}")

    # DB'deki ayarları config'e yükle
    try:
        from app.core.database import SessionLocal as _SL
        from app.models.app_settings import AppSettings as _AS
        _db = _SL()
        try:
            _rows = {r.key: r.value for r in _db.query(_AS).all()}
            from app.core.config import settings as _s
            if _rows.get("management_server_ip"):
                _s.MANAGEMENT_SERVER_IP = _rows["management_server_ip"]
            if _rows.get("ollama_active_model"):
                _s.OLLAMA_DEFAULT_MODEL = _rows["ollama_active_model"]
        finally:
            _db.close()
    except Exception as _e:
        logger.debug(f"Settings load: {_e}")

    # Yarım kalan repo sync job'larını "failed" yap — otomatik resume yok
    # (Birden fazla parallel sync başlatmak SQLAlchemy connection pool sorununa yol açıyor)
    try:
        from app.core.database import SessionLocal
        from app.models.repository import RepoSource, RepoSyncJob

        db = SessionLocal()
        stuck = db.query(RepoSource).filter(
            RepoSource.sync_status == "syncing"
        ).all()

        for repo in stuck:
            old_jobs = db.query(RepoSyncJob).filter(
                RepoSyncJob.repo_id == repo.id,
                RepoSyncJob.status.in_(["running", "pending"])
            ).all()
            for j in old_jobs:
                j.status = "failed"
                j.log = (j.log or "") + "\n[Sistem yeniden başlatıldı — sync durduruldu]"
            repo.sync_status = "failed"
            db.commit()
            logger.info(f"Repo sync durduruldu (restart): {repo.name}")

        db.close()
        if stuck:
            logger.info(f"⚠️ {len(stuck)} yarım kalan sync 'failed' olarak işaretlendi. UI'dan yeniden başlatın.")
    except Exception as e:
        logger.warning(f"Repo sync cleanup hatası: {e}")

    # RAG: Varsayılan metrik açıklamalarını arka planda seed et (Ollama hazır olmayabilir)
    async def _rag_seed_metrics():
        try:
            from app.services.rag_service import ingest_metric_descriptions
            from app.data.default_metric_descriptions import DEFAULT_METRIC_DESCRIPTIONS
            n = await ingest_metric_descriptions(DEFAULT_METRIC_DESCRIPTIONS)
            logger.info(f"RAG metrics seed: {n} chunks added")
        except Exception as e:
            logger.debug(f"RAG metrics seed skipped (Ollama/Chroma): {e}")
    asyncio.create_task(_rag_seed_metrics())

@app.on_event("shutdown")
async def shutdown_tasks():
    """Uygulama kapanırken background task'ları durdur"""
    from app.background_tasks import background_task_manager
    await background_task_manager.stop()
    _SSH_EXECUTOR.shutdown(wait=False)
    logger.info("Background tasks stopped")

@app.get("/")
async def root():
    return {"message": "Server Management API", "version": "1.0.0"}

# ─── Local repository static file serving ─────────────────────────────────────
try:
    from fastapi.staticfiles import StaticFiles
    import os
    _repos_dir = "/app/repos"
    os.makedirs(_repos_dir, exist_ok=True)
    app.mount("/repos", StaticFiles(directory=_repos_dir, html=False), name="repos")
    logger.info(f"Local repo serve: /repos → {_repos_dir}")
except Exception as _e:
    logger.warning(f"Could not mount /repos static dir: {_e}")

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
