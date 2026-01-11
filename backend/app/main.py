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

@app.get("/")
async def root():
    return {"message": "Server Management API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
