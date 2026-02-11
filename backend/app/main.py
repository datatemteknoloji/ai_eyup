"""
FastAPI Main Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
import logging

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
    async def list_servers():
        return {"message": "API router not available", "error": str(e)}
    
    app.include_router(fallback_router, prefix="/api/v1")

@app.on_event("startup")
async def startup_tasks():
    """Uygulama başlangıcında yapılacak işlemler"""
    # Tabloları oluştur
    from app.core.database import engine, Base
    import app.models  # noqa: F401 - modelleri Base.metadata'ya kaydetmek için
    Base.metadata.create_all(bind=engine)
    
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

@app.on_event("shutdown")
async def shutdown_tasks():
    """Uygulama kapanırken background task'ları durdur"""
    from app.background_tasks import background_task_manager
    await background_task_manager.stop()
    logger.info("Background tasks stopped")

@app.get("/")
async def root():
    return {"message": "Server Management API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
