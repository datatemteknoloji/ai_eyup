"""
API Router - Tüm API endpoint'lerini toplar
"""
from fastapi import APIRouter

api_router = APIRouter()

# Monitoring router (Node Exporter için gerekli)
try:
    from app.api import monitoring
    api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
except Exception as e:
    print(f"Warning: Could not load monitoring router: {e}")

# Diğer router'ları ekle (opsiyonel)
try:
    from app.api import servers
    api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
except Exception as e:
    print(f"Warning: Could not load servers router: {e}")

try:
    from app.api import chat
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
except Exception as e:
    print(f"Warning: Could not load chat router: {e}")

try:
    from app.api import alerts
    api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
except Exception as e:
    print(f"Warning: Could not load alerts router: {e}")

try:
    from app.api import hypervisors
    api_router.include_router(hypervisors.router, prefix="/hypervisors", tags=["hypervisors"])
except Exception as e:
    print(f"Warning: Could not load hypervisors router: {e}")

try:
    from app.api import settings
    api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
except Exception as e:
    print(f"Warning: Could not load settings router: {e}")
