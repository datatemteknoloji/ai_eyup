"""
API Router - Tüm API endpoint'lerini toplar
"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
api_router = APIRouter()

# Monitoring
try:
    from app.api import monitoring
    api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
except Exception as e:
    logger.error(f"Could not load monitoring router: {e}", exc_info=True)

# Servers
try:
    from app.api import servers
    api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
except Exception as e:
    logger.error(f"Could not load servers router: {e}", exc_info=True)

# Chat
try:
    from app.api import chat
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
except Exception as e:
    logger.error(f"Could not load chat router: {e}", exc_info=True)

# Alerts
try:
    from app.api import alerts
    api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
except Exception as e:
    logger.error(f"Could not load alerts router: {e}", exc_info=True)

# Hypervisors
try:
    from app.api import hypervisors
    api_router.include_router(hypervisors.router, prefix="/hypervisors", tags=["hypervisors"])
except Exception as e:
    logger.error(f"Could not load hypervisors router: {e}", exc_info=True)

# Settings (Global Credentials)
try:
    from app.api import settings
    api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
except Exception as e:
    logger.error(f"Could not load settings router: {e}", exc_info=True)

# AIOps Events
try:
    from app.api import events
    api_router.include_router(events.router, prefix="/events", tags=["events"])
except Exception as e:
    logger.error(f"Could not load events router: {e}", exc_info=True)

# AIOps Incidents
try:
    from app.api import incidents
    api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
except Exception as e:
    logger.error(f"Could not load incidents router: {e}", exc_info=True)

# Anomaly Detection
try:
    from app.api import anomalies
    api_router.include_router(anomalies.router, prefix="/anomalies", tags=["anomalies"])
except Exception as e:
    logger.error(f"Could not load anomalies router: {e}", exc_info=True)

# MCP
try:
    from app.api import mcp
    api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
except Exception as e:
    logger.error(f"Could not load mcp router: {e}", exc_info=True)

# RAG (Runbook, Incidents, Metric descriptions)
try:
    from app.api import rag
    api_router.include_router(rag.router, prefix="/rag", tags=["rag"])
except Exception as e:
    logger.error(f"Could not load rag router: {e}", exc_info=True)

# Ansible/AWX
try:
    from app.api import ansible
    api_router.include_router(ansible.router, prefix="/ansible", tags=["ansible"])
except Exception as e:
    logger.error(f"Could not load ansible router: {e}", exc_info=True)

# Package Management
try:
    from app.api import packages
    api_router.include_router(packages.router, prefix="/packages", tags=["packages"])
except Exception as e:
    logger.error(f"Could not load packages router: {e}", exc_info=True)

# Local Repository Management
try:
    from app.api import repositories
    api_router.include_router(repositories.router, prefix="/repos", tags=["repositories"])
except Exception as e:
    logger.error(f"Could not load repositories router: {e}", exc_info=True)
