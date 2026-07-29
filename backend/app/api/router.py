"""
API Router - Tüm API endpoint'lerini toplar
"""
import logging
from fastapi import APIRouter

logger = logging.getLogger(__name__)
api_router = APIRouter()

# Auth (login, kullanıcı yönetimi)
try:
    from app.api import auth
    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
except Exception as e:
    logger.error(f"Could not load auth router: {e}", exc_info=True)

# Audit Log
try:
    from app.api import audit
    api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
except Exception as e:
    logger.error(f"Could not load audit router: {e}", exc_info=True)

# Monitoring
try:
    from app.api import monitoring
    api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
except Exception as e:
    logger.error(f"Could not load monitoring router: {e}", exc_info=True)

# Metrics (dashboard kaynak kullanım özeti — Linux + Windows)
try:
    from app.api import metrics
    api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
except Exception as e:
    logger.error(f"Could not load metrics router: {e}", exc_info=True)

# Servers
try:
    from app.api import servers
    api_router.include_router(servers.router, prefix="/servers", tags=["servers"])
except Exception as e:
    logger.error(f"Could not load servers router: {e}", exc_info=True)

# Chat (Linux)
try:
    from app.api import chat
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
except Exception as e:
    logger.error(f"Could not load chat router: {e}", exc_info=True)

# Chat (Windows)
try:
    from app.api import windows_chat
    api_router.include_router(windows_chat.router, prefix="/windows-chat", tags=["windows-chat"])
except Exception as e:
    logger.error(f"Could not load windows_chat router: {e}", exc_info=True)

# Chat (Unified — Linux + Windows + Sanallaştırma)
try:
    from app.api import unified_chat
    api_router.include_router(unified_chat.router, prefix="/unified-chat", tags=["unified-chat"])
except Exception as e:
    logger.error(f"Could not load unified_chat router: {e}", exc_info=True)

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

# System Updates
try:
    from app.api import system_updates
    api_router.include_router(system_updates.router, prefix="/updates", tags=["system-updates"])
except Exception as e:
    logger.error(f"Could not load system_updates router: {e}", exc_info=True)

# VM Snapshots
try:
    from app.api import snapshots
    api_router.include_router(snapshots.router, prefix="/snapshots", tags=["snapshots"])
except Exception as e:
    logger.error(f"Could not load snapshots router: {e}", exc_info=True)

# Tasks (aktif görevler + ilerleme izleme)
try:
    from app.api import tasks
    api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
except Exception as e:
    logger.error(f"Could not load tasks router: {e}", exc_info=True)

# SSH Web Terminal
try:
    from app.api import terminal
    api_router.include_router(terminal.router, prefix="/terminal", tags=["terminal"])
except Exception as e:
    logger.error(f"Could not load terminal router: {e}", exc_info=True)

# Agentic AI (tool-calling + human-in-the-loop onay)
try:
    from app.api import agent
    api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
except Exception as e:
    logger.error(f"Could not load agent router: {e}", exc_info=True)

# RCA (karşılaştırmalı analiz + AWR parse/analiz)
try:
    from app.api import rca
    api_router.include_router(rca.router, prefix="/rca", tags=["rca"])
except Exception as e:
    logger.error(f"Could not load rca router: {e}", exc_info=True)

# Baseline (suppression kuralları + per-server adaptif eşikler)
try:
    from app.api import baseline
    api_router.include_router(baseline.router, prefix="/baseline", tags=["baseline"])
except Exception as e:
    logger.error(f"Could not load baseline router: {e}", exc_info=True)

# Ops Command Center (komuta merkezi)
try:
    from app.api import ops_center
    api_router.include_router(ops_center.router, prefix="/ops", tags=["ops"])
except Exception as e:
    logger.error(f"Could not load ops_center router: {e}", exc_info=True)

# Windows Management (WinRM, event logs, updates, exporter)
try:
    from app.api import windows
    api_router.include_router(windows.router, prefix="/windows", tags=["windows"])
except Exception as e:
    logger.error(f"Could not load windows router: {e}", exc_info=True)

# UCMDB Integration (static CSV/Excel import)
try:
    from app.api import ucmdb
    api_router.include_router(ucmdb.router, prefix="/ucmdb", tags=["ucmdb"])
except Exception as e:
    logger.error(f"Could not load ucmdb router: {e}", exc_info=True)

# Level 1 Operations (runbook tabanlı SSH operasyonlar)
try:
    from app.api import level1
    api_router.include_router(level1.router, prefix="/level1", tags=["level1"])
except Exception as e:
    logger.error(f"Could not load level1 router: {e}", exc_info=True)

# Modül yönetimi
try:
    from app.api import modules
    api_router.include_router(modules.router, prefix="/modules", tags=["modules"])
except Exception as e:
    logger.error(f"Could not load modules router: {e}", exc_info=True)

# Entegrasyonlar — envanter merkezi
try:
    from app.api import integrations
    api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
except Exception as e:
    logger.error(f"Could not load integrations router: {e}", exc_info=True)

# Exadata (Oracle DB Machine envanter)
try:
    from app.api import exadata
    api_router.include_router(exadata.router, prefix="/exadata", tags=["exadata"])
except Exception as e:
    logger.error(f"Could not load exadata router: {e}", exc_info=True)

# OpenShift Container Platform (cluster/node/proje/workload envanter + AIOps)
try:
    from app.api import openshift as openshift_api
    api_router.include_router(openshift_api.router, prefix="/openshift", tags=["openshift"])
except Exception as e:
    logger.error(f"Could not load openshift router: {e}", exc_info=True)

# Modül bazlı altyapı raporları (Linux / Windows / Exadata)
try:
    from app.api import platform_reports
    api_router.include_router(platform_reports.router, prefix="/platform-reports", tags=["platform-reports"])
except Exception as e:
    logger.error(f"Could not load platform_reports router: {e}", exc_info=True)

# Public (kimlik doğrulama gerektirmeyen — marka adı/logo)
try:
    from app.api import public
    api_router.include_router(public.router, prefix="/public", tags=["public"])
except Exception as e:
    logger.error(f"Could not load public router: {e}", exc_info=True)

# Sunucu / VM / ESX karşılaştırma
try:
    from app.api import compare
    api_router.include_router(compare.router, prefix="/compare", tags=["compare"])
except Exception as e:
    logger.error(f"Could not load compare router: {e}", exc_info=True)

# Bilgi Bankası (AI'nin öğrendiği kalıcı sunucu gerçekleri)
try:
    from app.api import knowledge
    api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
except Exception as e:
    logger.error(f"Could not load knowledge router: {e}", exc_info=True)

# Uygulama/Servis Keşfi (Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb. otomatik tespiti)
try:
    from app.api import applications
    api_router.include_router(applications.router, prefix="/applications", tags=["applications"])
except Exception as e:
    logger.error(f"Could not load applications router: {e}", exc_info=True)

# Linux NL Inventory Query (güvenli sorgu pipeline)
try:
    from app.api import nlq
    api_router.include_router(nlq.router, tags=["nlq", "ai-inventory"])
except Exception as e:
    logger.error(f"Could not load nlq router: {e}", exc_info=True)

# Platform self-update (GUI paket yükleme / apply / rollback)
try:
    from app.api import platform_update
    api_router.include_router(
        platform_update.router, prefix="/platform-update", tags=["platform-update"]
    )
except Exception as e:
    logger.error(f"Could not load platform_update router: {e}", exc_info=True)
