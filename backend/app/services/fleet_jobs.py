"""
Ağır filo işleri — Celery worker'da çalışır (API process'ten bağımsız).

Her runner fleet_lock ile çift çalışmayı engeller.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _db():
    from app.core.database import ThreadSessionLocal as SessionLocal
    return SessionLocal()


def run_health_check() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.monitoring.server_health_checker import ServerHealthChecker

    db = _db()
    try:
        with fleet_lock("health", ttl_sec=900) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: health check")
            return ServerHealthChecker.update_server_statuses(db) or {}
    except Exception as exc:
        logger.exception("Celery health check hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_auto_onboarding() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock

    db = _db()
    out: Dict[str, Any] = {}
    try:
        with fleet_lock("onboarding", ttl_sec=7200) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: auto-onboarding")
            from app.api.servers import update_ai_ready
            from app.api.windows import update_windows_ai_ready, install_exporter_all
            from app.services.auto_onboarding import (
                auto_install_node_exporter,
                collect_os_release_info,
                collect_windows_update_status,
                collect_linux_security_audit,
            )
            from app.services.app_discovery import discover_applications_all_servers
            from app.services import qa_cache

            out["linux_ai"] = update_ai_ready({"throttled": True}, db)
            out["win_ai"] = update_windows_ai_ready({"throttled": True}, db)
            out["os_info"] = collect_os_release_info(db)
            out["ne"] = auto_install_node_exporter(db)
            out["we"] = install_exporter_all(None, db)
            out["win_upd"] = collect_windows_update_status(db)
            out["sec"] = collect_linux_security_audit(db)
            out["apps"] = discover_applications_all_servers(db)
            qa_cache.invalidate_all()
            return out
    except Exception as exc:
        logger.exception("Celery auto-onboarding hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_nlq_linux_inventory(workers: Optional[int] = None) -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.nlq.linux_inventory_collector import (
        get_collector_status,
        run_linux_inventory_collection,
    )
    from app.services.runtime_settings import get_int

    if get_collector_status().get("running"):
        return {"skipped": True, "reason": "already_running"}

    w = workers
    if w is None:
        try:
            w = min(100, max(1, int(get_int("nlq_collector_workers"))))
        except Exception:
            w = 50

    db = _db()
    try:
        with fleet_lock("nlq", ttl_sec=3600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: NLQ linux inventory workers=%s", w)
            return run_linux_inventory_collection(db, workers=w, only_ai_ready=True) or {}
    except Exception as exc:
        logger.exception("Celery NLQ inventory hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_inventory_sync() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.inventory_sync_service import sync_all_hypervisors
    from app.services import qa_cache

    db = _db()
    try:
        with fleet_lock("inventory", ttl_sec=3600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: inventory sync")
            result = sync_all_hypervisors(db) or {}
            try:
                from app.services.ucmdb_sync_service import load_connection, sync_from_ucmdb
                ucfg = load_connection(db)
                if ucfg.get("enabled") and ucfg.get("base_url") and ucfg.get("password"):
                    result["ucmdb"] = sync_from_ucmdb(db, dry_run=False)
            except Exception as ue:
                logger.warning("uCMDB periodic sync skipped/failed: %s", ue)
            qa_cache.invalidate_all()
            try:
                from app.services.chat_cache_service import invalidate_context
                invalidate_context(db, platform="virt", all_for_platform=True)
                invalidate_context(db, platform="unified", all_for_platform=True)
            except Exception:
                pass
            return result
    except Exception as exc:
        logger.exception("Celery inventory sync hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_metric_sync() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.metric_sync import MetricSyncService

    db = _db()
    try:
        with fleet_lock("metric_sync", ttl_sec=1800) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: metric sync")
            return asyncio.run(MetricSyncService.sync_all_servers_metrics(db, minutes=12)) or {}
    except Exception as exc:
        logger.exception("Celery metric sync hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_esx_metric_sync() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.esx_metric_sync import sync_esx_metrics

    db = _db()
    try:
        with fleet_lock("esx_metric", ttl_sec=1800) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: ESX metric sync")
            return sync_esx_metrics(db) or {}
    except Exception as exc:
        logger.exception("Celery ESX metric sync hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_node_exporter_sync() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.monitoring.prometheus_metrics import (
        sync_node_exporter_running_from_prometheus,
        sync_node_exporter_targets_from_db,
    )

    db = _db()
    try:
        with fleet_lock("node_exporter", ttl_sec=600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: node exporter sync")
            targets = sync_node_exporter_targets_from_db(db) or {}
            flags = sync_node_exporter_running_from_prometheus(db) or {}
            return {"targets": targets, "flags": flags}
    except Exception as exc:
        logger.exception("Celery node exporter sync hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_windows_exporter_sync() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.monitoring.prometheus_metrics import (
        sync_windows_exporter_running_from_prometheus,
        sync_windows_exporter_targets_from_db,
    )

    db = _db()
    try:
        with fleet_lock("windows_exporter", ttl_sec=600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: windows exporter sync")
            targets = sync_windows_exporter_targets_from_db(db) or {}
            flags = sync_windows_exporter_running_from_prometheus(db) or {}
            return {"targets": targets, "flags": flags}
    except Exception as exc:
        logger.exception("Celery windows exporter sync hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_log_collection() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.log_collector import collect_all_servers_logs
    from app.services.log_anomaly_detector import detect_log_anomalies

    db = _db()
    try:
        with fleet_lock("logs", ttl_sec=3600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: log collection")
            result = collect_all_servers_logs(db, batch_mode=True) or {}
            anomalies = detect_log_anomalies(db) or []
            result["anomalies"] = len(anomalies)
            return result
    except Exception as exc:
        logger.exception("Celery log collection hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_anomaly_scan() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.anomaly_detector import detect_all_anomalies
    from app.services.aiops_engine import run_aiops_cycle

    db = _db()
    try:
        with fleet_lock("anomaly", ttl_sec=1800) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: anomaly scan")
            anomalies = detect_all_anomalies(db) or []
            cycle = run_aiops_cycle(db, anomalies) or {}
            return {"anomalies": len(anomalies), "aiops": cycle}
    except Exception as exc:
        logger.exception("Celery anomaly scan hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_windows_log_collection() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.windows_log_collector import collect_all_windows_logs

    db = _db()
    try:
        with fleet_lock("windows_logs", ttl_sec=3600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: windows log collection")
            return collect_all_windows_logs(db) or {}
    except Exception as exc:
        logger.exception("Celery windows log collection hata")
        return {"error": str(exc)}
    finally:
        db.close()


def run_windows_live_metrics() -> Dict[str, Any]:
    from app.services.fleet_mutex import fleet_lock
    from app.services.windows_live_metrics import collect_and_store

    db = _db()
    try:
        with fleet_lock("windows_live", ttl_sec=600) as ok:
            if not ok:
                return {"skipped": True}
            logger.info("Celery fleet: windows live metrics")
            payload = collect_and_store(db) or {}
            return {"ok": True, "total": payload.get("total"), "online": payload.get("online")}
    except Exception as exc:
        logger.exception("Celery windows live metrics hata")
        return {"error": str(exc)}
    finally:
        db.close()
