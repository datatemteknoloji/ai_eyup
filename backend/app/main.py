"""
FastAPI Main Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.version import get_app_version
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

# FastAPI app oluştur
app = FastAPI(
    title="Server Management API",
    version=get_app_version(),
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

# Global kimlik doğrulama: /auth/* ve /public/* dışındaki tüm /api/v1 endpoint'leri token ister.
# WebSocket (terminal) ve auth/public uçları muaf tutulur.
_AUTH_EXEMPT_PREFIXES = ("/api/v1/auth/", "/api/v1/public/")
# Terminal WS kendi JWT doğrulamasını query param üzerinden yapıyor


@app.middleware("http")
async def _require_auth_middleware(request, call_next):
    from starlette.responses import JSONResponse
    path = request.url.path
    method = request.method

    # Muaf: auth uçları, terminal WS, kök/health/docs, OPTIONS (CORS preflight)
    exempt = (
        method == "OPTIONS"
        or path in ("/", "/health", "/docs", "/openapi.json", "/redoc")
        or path.startswith(_AUTH_EXEMPT_PREFIXES)
        or path.startswith("/repos")
        or not path.startswith("/api/v1/")
    )
    if exempt:
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.lower().startswith("bearer ") else None
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Kimlik doğrulama gerekli"})
    from app.core.security import decode_access_token
    if not decode_access_token(token):
        return JSONResponse(status_code=401, content={"detail": "Geçersiz veya süresi dolmuş token"})
    return await call_next(request)


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

_SSH_EXECUTOR = ThreadPoolExecutor(max_workers=150, thread_name_prefix="ssh_worker")

@app.on_event("startup")
async def startup_tasks():
    """Uygulama başlangıcında yapılacak işlemler"""
    # Paralel SSH bağlantıları için geniş thread pool (10.000+ sunucu ölçeği —
    # background_tasks.py'deki run_in_executor(None, ...) çağrılarının tümü,
    # terminal.py SSH, chat.py/hypervisors.py fan-out'ları bu havuzu paylaşır)
    loop = asyncio.get_event_loop()
    loop.set_default_executor(_SSH_EXECUTOR)
    logger.info("SSH thread pool başlatıldı (max_workers=150)")

    # FastAPI'nin senkron `def` endpoint'leri (agent chat, hypervisor ask, ansible,
    # health check vb. — bkz. app/api/agent.py, hypervisors.py, ansible.py) Starlette'in
    # AnyIO tabanlı thread havuzunda çalışır; bu, yukarıdaki _SSH_EXECUTOR'dan AYRI bir
    # havuzdur ve varsayılan limiti sadece 40'tır. Bu endpoint'lerin bir kısmı LLM
    # çağrıları nedeniyle 60-180sn sürebildiğinden, birkaç eşzamanlı kullanıcı bile
    # havuzu doldurup yeni isteklerin (diğer sync endpoint'ler dahil) kuyrukta
    # beklemesine (dolaylı "hang" hissi) neden olabilir — limit yükseltildi.
    try:
        import anyio.to_thread
        anyio.to_thread.current_default_thread_limiter().total_tokens = 150
        logger.info("AnyIO sync-endpoint thread havuzu genişletildi (limit=150)")
    except Exception as e:
        logger.warning(f"AnyIO thread limiter ayarlanamadı: {e}")
    # Tabloları oluştur
    from app.core.database import engine, Base
    import app.models  # noqa: F401 - modelleri Base.metadata'ya kaydetmek için
    Base.metadata.create_all(bind=engine)

    # Hafif şema güncellemeleri (mevcut tablolara eksik kolon ekle — idempotent)
    try:
        from sqlalchemy import text as _sa_text
        # Postgres enum'a yeni hypervisor tipleri ekle — ayrı transaction, bazı Postgres
        # sürümlerinde ADD VALUE diğer DDL'lerle aynı transaction'da hata verebiliyor.
        # NOT: SQLAlchemy `Enum(HypervisorType)` sütunu değer olarak enum ÜYE ADINI
        # (örn. "OPENSHIFT_VIRT") gönderir, "openshift_virt" değerini değil — bu yüzden
        # DB enum'una üye adıyla aynı (büyük harfli) değer eklenir.
        for _enum_value in ("OPENSHIFT_VIRT", "PROXMOX"):
            try:
                with engine.begin() as _enum_conn:
                    _enum_conn.execute(_sa_text(
                        f"ALTER TYPE hypervisortype ADD VALUE IF NOT EXISTS '{_enum_value}'"
                    ))
            except Exception as _enum_e:
                logger.debug(f"hypervisortype enum migration skip ({_enum_value}): {_enum_e}")
        with engine.begin() as _conn:
            _conn.execute(_sa_text(
                "ALTER TABLE agent_actions ADD COLUMN IF NOT EXISTS requires_root BOOLEAN DEFAULT FALSE"
            ))
            _conn.execute(_sa_text(
                "ALTER TABLE system_update_plans ADD COLUMN IF NOT EXISTS snapshot_mode VARCHAR(10) DEFAULT 'skip'"
            ))
            _conn.execute(_sa_text(
                "ALTER TABLE system_update_plans ADD COLUMN IF NOT EXISTS snapshot_retention VARCHAR(20) DEFAULT '1w'"
            ))
            # VM detay kolonları — hypervisor'dan senkronize edilen tüm VM bilgileri
            for _col_sql in [
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_name VARCHAR(255)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_guest_hostname VARCHAR(255)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_guest_ip VARCHAR(45)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_cpu_count INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_memory_mb INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_disk_gb INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_power_state VARCHAR(30)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_tools_status VARCHAR(50)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_network_info JSONB",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_cluster VARCHAR(255)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_datastore VARCHAR(255)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_hardware_version VARCHAR(50)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS vm_last_sync TIMESTAMPTZ",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS windows_exporter_installed BOOLEAN DEFAULT FALSE",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS windows_exporter_running BOOLEAN DEFAULT FALSE",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS windows_exporter_last_check TIMESTAMPTZ",
                # Windows Update / Defender + Linux güvenlik denetim cache (rapor genişletme)
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_updates_pending INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_updates_critical INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_updates_last_checked TIMESTAMPTZ",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_reboot_pending BOOLEAN DEFAULT FALSE",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_defender_enabled BOOLEAN",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS win_defender_up_to_date BOOLEAN",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS linux_firewall_active BOOLEAN",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS linux_selinux_status VARCHAR(20)",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS linux_failed_logins_24h INTEGER",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS linux_security_last_check TIMESTAMPTZ",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS app_discovery_last_scan TIMESTAMPTZ",
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS ai_ready_last_check TIMESTAMPTZ",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS swap_usage_percent NUMERIC(5,2)",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS cpu_iowait_percent NUMERIC(5,2)",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS disk_io_utilization_percent NUMERIC(5,2)",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS network_rx_bytes_per_sec NUMERIC(20,2)",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS network_tx_bytes_per_sec NUMERIC(20,2)",
                "ALTER TABLE linux_inventory ADD COLUMN IF NOT EXISTS metrics_extra JSONB",
            ]:
                _conn.execute(_sa_text(_col_sql))
            _conn.execute(_sa_text(
                "ALTER TABLE package_jobs ADD COLUMN IF NOT EXISTS live_log JSONB DEFAULT '{}'"
            ))
            _conn.execute(_sa_text(
                "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS category VARCHAR(32) DEFAULT 'linux'"
            ))
            _conn.execute(_sa_text(
                "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS meta JSONB DEFAULT '{}'"
            ))
            _conn.execute(_sa_text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS allowed_tiers JSONB"
            ))
            for _idx in [
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_uptime ON linux_inventory (uptime_seconds)",
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_boot ON linux_inventory (boot_time)",
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_coll_time ON linux_inventory (collection_time)",
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_coll_status ON linux_inventory (collection_status)",
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_cpu ON linux_inventory (cpu_usage_percent)",
                "CREATE INDEX IF NOT EXISTS ix_linux_inventory_mem ON linux_inventory (memory_usage_percent)",
                "CREATE INDEX IF NOT EXISTS ix_fs_metrics_usage ON filesystem_metrics (usage_percent)",
                "CREATE INDEX IF NOT EXISTS ix_service_status_name ON service_status (service_name)",
                "CREATE INDEX IF NOT EXISTS ix_service_status_active ON service_status (active_state)",
                # system_events: last_seen/created_at neredeyse her sorguda ">= since"
                # ile filtrelenir (ops_center, anomaly detection, log collector, RCA vb.)
                # ama index'leri yoktu — 288K+ satırda her seferinde tam tablo taraması
                # oluyordu (DB CPU/IO üzerinden dolaylı "hang" kaynağı).
                "CREATE INDEX IF NOT EXISTS ix_system_events_created_at ON system_events (created_at)",
                "CREATE INDEX IF NOT EXISTS ix_system_events_last_seen ON system_events (last_seen)",
                "CREATE INDEX IF NOT EXISTS ix_system_events_server_last_seen ON system_events (server_id, last_seen)",
            ]:
                try:
                    _conn.execute(_sa_text(_idx))
                except Exception:
                    pass
    except Exception as _mig_e:
        logger.debug(f"schema migration skip: {_mig_e}")
    
    # Varsayılan admin kullanıcısını oluştur (yoksa) — sistem kilitlenmesin
    try:
        import os as _os
        from app.core.database import SessionLocal as _SLu
        from app.models.user import User as _User
        from app.core.security import hash_password as _hp
        _udb = _SLu()
        try:
            if _udb.query(_User).count() == 0:
                _admin_pw = _os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
                _udb.add(_User(
                    username="admin",
                    full_name="Yönetici",
                    role="admin",
                    hashed_password=_hp(_admin_pw),
                ))
                _udb.commit()
                logger.warning(
                    "👤 Varsayılan admin kullanıcısı oluşturuldu (kullanıcı: admin). "
                    "İlk girişten sonra parolayı değiştirin!"
                )
        finally:
            _udb.close()
    except Exception as _ue:
        logger.error(f"Admin seed hatası: {_ue}")

    # Chat Q&A cache temizliği — SSH/veri toplama hatası içeren eski yanıtlar
    # (bkz. chat_cache_service._BAD_ANSWER_PATTERNS) kalıcı olarak cache'te
    # kalıp altta yatan sorun çözüldükten sonra da tekrar tekrar dönebiliyordu.
    try:
        from app.core.database import SessionLocal as _SLc
        from app.services.chat_cache_service import purge_bad_cache_entries
        _cdb = _SLc()
        try:
            purge_bad_cache_entries(_cdb)
        finally:
            _cdb.close()
    except Exception as _ce:
        logger.debug(f"Chat cache temizliği atlandı: {_ce}")

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
    logger.info("Background tasks started (health checks every 10 minutes, TCP-only)")

    # Yarım kalan system update planlarını kurtar / devam ettir
    try:
        from app.core.database import SessionLocal as _SL2
        from app.models.system_update import SystemUpdatePlan as _SUP, SystemUpdateJob as _SUJ
        from app.services.system_update_service import (
            recover_stuck_system_update_plans as _recover_sup,
            run_system_update_plan as _rsp,
        )
        import threading as _th
        _db2 = _SL2()
        _rec = _recover_sup(_db2, max_minutes=15)
        if _rec.get("recovered_jobs") or _rec.get("finalized_plans"):
            logger.info(
                f"System update recovery: {_rec.get('recovered_jobs', 0)} takılı job, "
                f"{_rec.get('finalized_plans', 0)} plan kapatıldı"
            )
        _running_plans = _db2.query(_SUP).filter(_SUP.status == "running").all()
        for _p in _running_plans:
            _pending = _db2.query(_SUJ).filter(
                _SUJ.plan_id == _p.id,
                _SUJ.status == "pending",
            ).count()
            if _pending <= 0:
                continue
            _t = _th.Thread(target=_rsp, args=(_p.id,), daemon=True, name=f"sysupdate-{_p.id}")
            _t.start()
            logger.info(f"System update plan #{_p.id} devam ettiriliyor ({_pending} bekleyen job)")
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
            if _rows.get("prometheus_url"):
                _s.PROMETHEUS_URL = _rows["prometheus_url"]
            if _rows.get("pushgateway_url") is not None:
                _s.PUSHGATEWAY_URL = _rows["pushgateway_url"]
            if _rows.get("prometheus_linux_jobs") is not None:
                from app.core.config import _parse_job_list
                _s.PROMETHEUS_LINUX_JOBS = _parse_job_list(
                    _rows["prometheus_linux_jobs"], ["node-exporter"]
                )
            if _rows.get("prometheus_windows_jobs") is not None:
                from app.core.config import _parse_job_list
                _s.PROMETHEUS_WINDOWS_JOBS = _parse_job_list(
                    _rows["prometheus_windows_jobs"], ["windows-exporter"]
                )
            # Uzak AI gateway (örn. Bifrost) — DB'de ayarlıysa .env default'unun üzerine yazar
            if _rows.get("remote_llm_enabled") is not None:
                _s.REMOTE_LLM_ENABLED = _rows["remote_llm_enabled"].lower() == "true"
            if _rows.get("remote_llm_url"):
                _s.REMOTE_LLM_URL = _rows["remote_llm_url"]
            if _rows.get("remote_llm_model"):
                _s.REMOTE_LLM_MODEL = _rows["remote_llm_model"]
            if _rows.get("remote_llm_api_key"):
                from app.core.encryption import decrypt_secret as _dec
                _s.REMOTE_LLM_API_KEY = _dec(_rows["remote_llm_api_key"])
            if _rows.get("remote_llm_verify_ssl") is not None:
                _s.REMOTE_LLM_VERIFY_SSL = _rows["remote_llm_verify_ssl"].lower() == "true"
            if _rows.get("remote_llm_ca_bundle") is not None:
                _s.REMOTE_LLM_CA_BUNDLE = _rows["remote_llm_ca_bundle"]
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
    return {"message": "Server Management API", "version": "1.0.4"}

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
    return {"status": "healthy", "version": get_app_version()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
