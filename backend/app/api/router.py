"""
API Router - Tüm API endpoint'lerini toplar
"""
from fastapi import APIRouter

api_router = APIRouter()

# Monitoring
try:
    from app.api import monitoring
    api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
except Exception as e:
    print(f"Warning: Could not load monitoring router: {e}")

# Servers
try:
    from app.api import servers
    api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
except Exception as e:
    print(f"Warning: Could not load servers router: {e}")

# Chat
try:
    from app.api import chat
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
except Exception as e:
    print(f"Warning: Could not load chat router: {e}")

# Alerts
try:
    from app.api import alerts
    api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
except Exception as e:
    print(f"Warning: Could not load alerts router: {e}")

# Hypervisors
try:
    from app.api import hypervisors
    api_router.include_router(hypervisors.router, prefix="/hypervisors", tags=["hypervisors"])
except Exception as e:
    print(f"Warning: Could not load hypervisors router: {e}")

# Settings (Global Credentials)
try:
    from app.api import settings
    api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
except Exception as e:
    print(f"Warning: Could not load settings router: {e}")

# AIOps Events
try:
    from app.api import events
    api_router.include_router(events.router, prefix="/events", tags=["events"])
except Exception as e:
    print(f"Warning: Could not load events router: {e}")

# AIOps Incidents
try:
    from app.api import incidents
    api_router.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
except Exception as e:
    print(f"Warning: Could not load incidents router: {e}")

# Anomaly Detection
try:
    from app.api import anomalies
    api_router.include_router(anomalies.router, prefix="/anomalies", tags=["anomalies"])
except Exception as e:
    print(f"Warning: Could not load anomalies router: {e}")

# MCP
try:
    from app.api import mcp
    api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
except Exception as e:
    print(f"Warning: Could not load mcp router: {e}")

# RAG (Runbook, Incidents, Metric descriptions)
try:
    from app.api import rag
    api_router.include_router(rag.router, prefix="/rag", tags=["rag"])
except Exception as e:
    print(f"Warning: Could not load rag router: {e}")

# Ansible/AWX
try:
    from app.api import ansible
    api_router.include_router(ansible.router, prefix="/ansible", tags=["ansible"])
except Exception as e:
    print(f"Warning: Could not load ansible router: {e}")
