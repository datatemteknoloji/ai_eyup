"""
Background Tasks - Periyodik görevler
Ağır işler Celery'ye enqueue edilir; API process yalnızca scheduler tick atar.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


def _rt_sec(key: str, default: int) -> int:
    """Gelişmiş ayarlardan saniye aralığı (runtime, restart gerekmez)."""
    try:
        from app.services.runtime_settings import get_int
        return int(get_int(key))
    except Exception:
        return default


async def _enqueue_or_run(task_name: str, local_callable, *, label: str) -> None:
    """Önce Celery; worker yoksa local (executor / await)."""
    try:
        from app.worker import enqueue_fleet_job
        if enqueue_fleet_job(task_name):
            logger.info("%s → Celery", label)
            return
    except Exception as exc:
        logger.warning("%s Celery enqueue hata, local: %s", label, exc)

    logger.info("%s → local fallback", label)
    if asyncio.iscoroutinefunction(local_callable):
        await local_callable()
        return
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, local_callable)


class BackgroundTaskManager:
    """Arka plan görevlerini yöneten sınıf"""

    def __init__(self):
        self.running = False
        self.tasks = []
        self._scheduler_lock_fh = None

    def _try_become_scheduler(self) -> bool:
        """Uvicorn multi-worker'da tek scheduler — process-içi fcntl lock."""
        try:
            import fcntl
            path = os.environ.get("AINEW_BG_SCHEDULER_LOCK", "/tmp/ainew_bg_scheduler.lock")
            fh = open(path, "w", encoding="utf-8")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.write(str(os.getpid()))
            fh.flush()
            self._scheduler_lock_fh = fh
            return True
        except Exception as exc:
            # BlockingIOError / OSError → başka worker aldı
            logger.info("BG scheduler lock alınamadı (%s) — bu worker scheduler değil", exc)
            try:
                if self._scheduler_lock_fh:
                    self._scheduler_lock_fh.close()
            except Exception:
                pass
            self._scheduler_lock_fh = None
            return False

    async def start(self):
        if self.running:
            logger.warning("Background tasks already running")
            return

        # Multi-uvicorn: yalnızca bir process scheduler olsun (fcntl lock)
        if not self._try_become_scheduler():
            logger.info("Background scheduler başka worker'da — bu process atlanıyor")
            return

        self.running = True
        logger.info("Starting background tasks...")

        self.tasks.append(asyncio.create_task(self._periodic_health_check()))
        self.tasks.append(asyncio.create_task(self._periodic_metric_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_anomaly_scan()))
        self.tasks.append(asyncio.create_task(self._periodic_log_collection()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_log_collection()))
        self.tasks.append(asyncio.create_task(self._periodic_virt_log_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_inventory_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_esx_metric_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_rag_reindex()))
        self.tasks.append(asyncio.create_task(self._periodic_snapshot_cleanup()))
        self.tasks.append(asyncio.create_task(self._periodic_event_cleanup()))
        self.tasks.append(asyncio.create_task(self._periodic_node_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_system_update_recovery()))
        self.tasks.append(asyncio.create_task(self._periodic_vm_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_openshift_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_auto_onboarding()))
        self.tasks.append(asyncio.create_task(self._periodic_linux_inventory_nlq()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_live_metrics()))
        self.tasks.append(asyncio.create_task(self._syslog_receiver_supervisor()))

        logger.info("Background tasks started (intervals: Ayarlar → Gelişmiş)")

    async def stop(self):
        if not self.running:
            return

        self.running = False
        logger.info("Stopping background tasks...")

        for task in self.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.tasks.clear()
        try:
            from app.services.syslog_receiver import syslog_receiver_manager
            await syslog_receiver_manager.stop()
        except Exception:
            pass
        logger.info("Background tasks stopped")

    async def _syslog_receiver_supervisor(self):
        """UDP syslog alıcı — Ayarlar → syslog_receiver_enabled."""
        from app.services.syslog_receiver import syslog_receiver_manager
        await syslog_receiver_manager.start_supervisor()

    async def _periodic_health_check(self):
        """Ilk 30s bekle, sonra periyodik sunucu durumu (TCP). Tam SSH/WinRM burada yok."""
        logger.info("Periodic health check task started (interval from Gelişmiş ayarlar)")
        first_run = True

        while self.running:
            try:
                interval = max(120, _rt_sec("health_check_interval_sec", 600))
                await asyncio.sleep(30 if first_run else interval)
                first_run = False
                if not self.running:
                    break
                from app.services.fleet_jobs import run_health_check
                await _enqueue_or_run("fleet.health_check", run_health_check, label="health")
            except asyncio.CancelledError:
                logger.info("Health check task cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in health check task: {e}", exc_info=True)
                await asyncio.sleep(_rt_sec("health_check_interval_sec", 600))

    async def _periodic_log_collection(self):
        """Periyodik Linux log toplama — Celery (fallback local)."""
        logger.info("Log collection task started (batch/workers, Celery)")
        await asyncio.sleep(90)

        while self.running:
            try:
                from app.services.fleet_jobs import run_log_collection
                await _enqueue_or_run("fleet.log_collection", run_log_collection, label="logs")
                await asyncio.sleep(_rt_sec("log_collection_interval_sec", 300))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Log collection task error: {e}")
                await asyncio.sleep(_rt_sec("log_collection_interval_sec", 300))

    async def _periodic_windows_log_collection(self):
        """Windows sunuculardan WinRM ile event log toplama."""
        logger.info("Windows log collection task started (900s interval)")
        await asyncio.sleep(120)

        while self.running:
            try:
                from app.services.fleet_jobs import run_windows_log_collection
                await _enqueue_or_run(
                    "fleet.windows_log_collection",
                    run_windows_log_collection,
                    label="windows_logs",
                )
                await asyncio.sleep(_rt_sec("windows_log_interval_sec", 900))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Windows log task error: {e}")
                await asyncio.sleep(_rt_sec("windows_log_interval_sec", 900))

    async def _periodic_virt_log_sync(self):
        """Hypervisor olaylarını SystemEvent'e senkronize et."""
        logger.info("Virt log sync task started (900s interval)")
        await asyncio.sleep(150)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.virt_log_collector import sync_virt_logs_to_db
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, sync_virt_logs_to_db, db)
                    if result.get("total_saved", 0) > 0:
                        logger.info(
                            "Virt log sync: %s yeni olay (virt=%s, vcenter=%s)",
                            result["total_saved"],
                            result.get("virt_saved", 0),
                            result.get("vcenter_saved", 0),
                        )
                        from app.services import qa_cache
                        qa_cache.invalidate_all()
                except Exception as e:
                    logger.error(f"Virt log sync error: {e}")
                finally:
                    db.close()
                await asyncio.sleep(_rt_sec("virt_log_interval_sec", 900))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Virt log sync task error: {e}")
                await asyncio.sleep(_rt_sec("virt_log_interval_sec", 900))

    async def _periodic_anomaly_scan(self):
        """Anomaly + AIOps — Celery (fallback local)."""
        logger.info("Anomaly scan task started (300s interval, Celery)")
        await asyncio.sleep(120)

        while self.running:
            try:
                from app.services.fleet_jobs import run_anomaly_scan
                await _enqueue_or_run("fleet.anomaly_scan", run_anomaly_scan, label="anomaly")
                await asyncio.sleep(_rt_sec("anomaly_scan_interval_sec", 300))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Anomaly scan task error: {e}")
                await asyncio.sleep(_rt_sec("anomaly_scan_interval_sec", 300))

    async def _periodic_metric_sync(self):
        """Prometheus → TimescaleDB — Celery."""
        logger.info("Metric sync task started (600s interval, Celery)")
        await asyncio.sleep(60)

        while self.running:
            try:
                from app.services.fleet_jobs import run_metric_sync
                await _enqueue_or_run("fleet.metric_sync", run_metric_sync, label="metric_sync")
                await asyncio.sleep(_rt_sec("metric_sync_interval_sec", 600))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metric sync task error: {e}")
                await asyncio.sleep(_rt_sec("metric_sync_interval_sec", 600))

    async def _periodic_inventory_sync(self):
        """Hypervisor VM inventory — Celery."""
        DEFAULT_MINUTES = 5
        logger.info("Inventory sync task started (Celery, interval from Gelişmiş ayarlar)")
        await asyncio.sleep(60)

        while self.running:
            try:
                try:
                    interval_min = max(1, _rt_sec("inventory_sync_interval_minutes", DEFAULT_MINUTES))
                    interval_sec = max(60, interval_min * 60)
                except Exception:
                    interval_sec = DEFAULT_MINUTES * 60

                await asyncio.sleep(interval_sec)
                if not self.running:
                    break

                from app.services.fleet_jobs import run_inventory_sync
                await _enqueue_or_run(
                    "fleet.inventory_sync", run_inventory_sync, label="inventory"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Inventory sync task error: {e}", exc_info=True)
                await asyncio.sleep(max(60, _rt_sec("inventory_sync_interval_minutes", 5) * 60))

    async def _periodic_openshift_sync(self):
        """OpenShift Container Platform cluster'larından envanter + olay senkronizasyonu (10 dk)."""
        logger.info("OpenShift sync task started (600s interval)")
        await asyncio.sleep(180)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.openshift_sync_service import sync_all_openshift_clusters
                    from app.services.openshift_event_collector import sync_all_openshift_events

                    loop = asyncio.get_event_loop()
                    inv_result = await loop.run_in_executor(None, sync_all_openshift_clusters, db)
                    if inv_result.get("total_clusters", 0) > 0:
                        ev_result = await loop.run_in_executor(None, sync_all_openshift_events, db)
                        logger.info(
                            "OpenShift sync: %s cluster, %s yeni olay",
                            inv_result.get("total_clusters", 0),
                            ev_result.get("total_saved", 0),
                        )
                        from app.services import qa_cache
                        qa_cache.invalidate_all()
                except Exception as e:
                    logger.error(f"OpenShift sync error: {e}", exc_info=True)
                finally:
                    db.close()
                await asyncio.sleep(_rt_sec("openshift_sync_interval_sec", 600))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"OpenShift sync task error: {e}")
                await asyncio.sleep(_rt_sec("openshift_sync_interval_sec", 600))

    async def _periodic_esx_metric_sync(self):
        """ESX host metrikleri — Celery."""
        logger.info("ESX metric sync task started (900s interval, Celery)")
        await asyncio.sleep(120)

        while self.running:
            try:
                from app.services.fleet_jobs import run_esx_metric_sync
                await _enqueue_or_run("fleet.esx_metric_sync", run_esx_metric_sync, label="esx_metric")
                await asyncio.sleep(_rt_sec("esx_metric_interval_sec", 900))
            except asyncio.CancelledError:
                logger.info("ESX metric sync task cancelled")
                break
            except Exception as e:
                logger.error(f"ESX metric sync task unexpected error: {e}")
                await asyncio.sleep(_rt_sec("esx_metric_interval_sec", 900))

    async def _periodic_rag_reindex(self):
        """Her 30 dakikada incident + event + Bilgi Bankası kayıtlarını RAG hafızasına indeksler.
        Böylece AI Chat geçmiş olaylardan ve öğrenilmiş sunucu bilgilerinden haberdar olur."""
        logger.info("RAG reindex task started (1800s interval, first run in 300s)")
        await asyncio.sleep(300)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.rag_service import (
                        ingest_incidents_from_db,
                        ingest_events_from_db,
                        ingest_knowledge_from_db,
                    )
                    n_inc = await ingest_incidents_from_db(db)
                    n_evt = await ingest_events_from_db(db)
                    n_kb = await ingest_knowledge_from_db(db)
                    logger.info(
                        f"RAG reindex: {n_inc} incident, {n_evt} event, {n_kb} knowledge chunk indekslendi"
                    )
                except Exception as e:
                    logger.error(f"RAG reindex error: {e}")
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("rag_reindex_interval_sec", 1800))

            except asyncio.CancelledError:
                logger.info("RAG reindex task cancelled")
                break
            except Exception as e:
                logger.error(f"RAG reindex task error: {e}")
                await asyncio.sleep(_rt_sec("rag_reindex_interval_sec", 1800))


    async def _periodic_snapshot_cleanup(self):
        """Süresi dolmuş VM snapshot kayıtlarını hypervisor'dan siler."""
        logger.info("Snapshot cleanup task started (3600s interval, first run in 600s)")
        await asyncio.sleep(600)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.snapshot_service import cleanup_expired_snapshots
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, cleanup_expired_snapshots, db)
                    if result.get("deleted") or result.get("errors"):
                        logger.info(
                            f"Snapshot cleanup: {result.get('deleted', 0)} silindi, "
                            f"{result.get('errors', 0)} hata"
                        )
                except Exception as e:
                    logger.error(f"Snapshot cleanup error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("snapshot_cleanup_interval_sec", 3600))

            except asyncio.CancelledError:
                logger.info("Snapshot cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Snapshot cleanup task error: {e}")
                await asyncio.sleep(_rt_sec("snapshot_cleanup_interval_sec", 3600))


    async def _periodic_event_cleanup(self):
        """system_events tablosu sınırsız büyümesin diye eski kayıtları periyodik siler
        (varsayılan: 180 günden eski, 6 saatte bir kontrol)."""
        logger.info("Event cleanup task started (interval from Gelişmiş ayarlar)")
        await asyncio.sleep(300)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.event_retention import cleanup_old_events
                    retention_days = _rt_sec("event_retention_days", 180)
                    loop = asyncio.get_event_loop()
                    stats = await loop.run_in_executor(
                        None, lambda: cleanup_old_events(db, retention_days=retention_days)
                    )
                    if stats.get("deleted"):
                        logger.info(f"Event cleanup: {stats['deleted']} eski kayıt silindi")
                except Exception as e:
                    logger.error(f"Event cleanup error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("event_cleanup_interval_sec", 21600))

            except asyncio.CancelledError:
                logger.info("Event cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Event cleanup task error: {e}")
                await asyncio.sleep(_rt_sec("event_cleanup_interval_sec", 21600))

    async def _periodic_system_update_recovery(self):
        """Takılı kalan system update job/planlarını periyodik temizler."""
        logger.info("System update recovery task started (300s interval, first run in 120s)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.system_update_service import recover_stuck_system_update_plans
                    loop = asyncio.get_event_loop()
                    stats = await loop.run_in_executor(
                        None, lambda: recover_stuck_system_update_plans(db, 20)
                    )
                    # Package jobs için de cleanup
                    from app.models.package_job import PackageJob as _PJ
                    _pkg_cutoff = datetime.now(timezone.utc) - timedelta(minutes=20)
                    _stuck_pkgs = db.query(_PJ).filter(
                        _PJ.status == "running",
                        _PJ.created_at < _pkg_cutoff,
                    ).all()
                    for _pj in _stuck_pkgs:
                        _pj.status = "failed"
                        _pj.completed_at = datetime.now(timezone.utc)
                    if _stuck_pkgs:
                        db.commit()
                        logger.warning(f"Package job cleanup: {len(_stuck_pkgs)} takılı iş temizlendi")
                    if stats.get("recovered_jobs") or stats.get("finalized_plans"):
                        logger.warning(
                            f"System update stuck recovery: {stats.get('recovered_jobs', 0)} job, "
                            f"{stats.get('finalized_plans', 0)} plan"
                        )
                except Exception as e:
                    logger.error(f"System update recovery error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("sysupdate_recovery_interval_sec", 300))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"System update recovery task error: {e}")
                await asyncio.sleep(_rt_sec("sysupdate_recovery_interval_sec", 300))

    async def _periodic_node_exporter_sync(self):
        """Node exporter targets/flags — Celery."""
        logger.info("Node exporter sync task started (600s interval, Celery)")
        await asyncio.sleep(120)

        while self.running:
            try:
                from app.services.fleet_jobs import run_node_exporter_sync
                await _enqueue_or_run(
                    "fleet.node_exporter_sync", run_node_exporter_sync, label="node_exporter"
                )
                await asyncio.sleep(_rt_sec("node_exporter_sync_interval_sec", 600))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Node exporter sync task error: {e}")
                await asyncio.sleep(_rt_sec("node_exporter_sync_interval_sec", 600))

    async def _periodic_windows_exporter_sync(self):
        """Windows exporter targets/flags — Celery."""
        logger.info("Windows exporter sync task started (600s interval, Celery)")
        await asyncio.sleep(150)

        while self.running:
            try:
                from app.services.fleet_jobs import run_windows_exporter_sync
                await _enqueue_or_run(
                    "fleet.windows_exporter_sync",
                    run_windows_exporter_sync,
                    label="windows_exporter",
                )
                await asyncio.sleep(_rt_sec("windows_exporter_sync_interval_sec", 600))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Windows exporter sync task error: {e}")
                await asyncio.sleep(_rt_sec("windows_exporter_sync_interval_sec", 600))

    async def _periodic_vm_sync(self):
        """
        hypervisor_id var ama hypervisor_vm_id eksik sunucular için otomatik VM arama.
        İlk çalışma: 60sn, sonra her 2 saatte bir.
        Ek olarak vm_last_sync'i 24 saatten eski olanları da yeniler.
        """
        logger.info("VM auto-sync task started (first run in 60s, then every 2h)")
        await asyncio.sleep(60)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, _run_vm_sync_batch, db
                    )
                    from app.services import qa_cache
                    qa_cache.invalidate_all()
                except Exception as e:
                    logger.error(f"VM auto-sync error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("vm_auto_sync_interval_sec", 7200))

            except asyncio.CancelledError:
                logger.info("VM auto-sync task cancelled")
                break
            except Exception as e:
                logger.error(f"VM auto-sync task error: {e}")
                await asyncio.sleep(_rt_sec("vm_auto_sync_interval_sec", 7200))


    async def _periodic_auto_onboarding(self):
        """AI Ready + exporter onboarding — Celery (SSH fırtınasının ana kaynağı)."""
        logger.info("Auto-onboarding task started (600s interval, Celery)")
        await asyncio.sleep(150)

        while self.running:
            try:
                from app.services.fleet_jobs import run_auto_onboarding
                await _enqueue_or_run(
                    "fleet.auto_onboarding", run_auto_onboarding, label="onboarding"
                )
                await asyncio.sleep(_rt_sec("auto_onboarding_interval_sec", 600))
            except asyncio.CancelledError:
                logger.info("Auto-onboarding task cancelled")
                break
            except Exception as e:
                logger.error(f"Auto-onboarding task error: {e}")
                await asyncio.sleep(_rt_sec("auto_onboarding_interval_sec", 600))

    async def _periodic_linux_inventory_nlq(self):
        """Linux NL inventory snapshot — Celery."""
        logger.info("Linux NL inventory collector task started (Celery)")
        await asyncio.sleep(180)
        while self.running:
            try:
                from app.services.fleet_jobs import run_nlq_linux_inventory
                await _enqueue_or_run(
                    "fleet.nlq_linux_inventory",
                    run_nlq_linux_inventory,
                    label="nlq",
                )
                await asyncio.sleep(_rt_sec("nlq_collector_interval_sec", 900))
            except asyncio.CancelledError:
                logger.info("Linux NL inventory collector cancelled")
                break
            except Exception as e:
                logger.error(f"Linux NL inventory collector error: {e}", exc_info=True)
                await asyncio.sleep(_rt_sec("nlq_collector_interval_sec", 900))

    async def _periodic_windows_live_metrics(self):
        """Windows WinRM live-metrics cache — Celery."""
        logger.info("Windows live-metrics cache task started (Celery)")
        await asyncio.sleep(90)
        while self.running:
            try:
                from app.services.fleet_jobs import run_windows_live_metrics
                await _enqueue_or_run(
                    "fleet.windows_live_metrics",
                    run_windows_live_metrics,
                    label="windows_live",
                )
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("Windows live-metrics task cancelled")
                break
            except Exception as e:
                logger.error(f"Windows live-metrics task error: {e}", exc_info=True)
                await asyncio.sleep(60)

def _run_vm_sync_batch(db) -> None:
    """
    Blocking işlev — thread pool'da çalışır.
    1. hypervisor_id var, hypervisor_vm_id yok → hemen sync et
    2. hypervisor_vm_id var ama vm_last_sync > 24 saat önce → yenile
    """
    from datetime import datetime, timezone, timedelta
    from app.models.server import Server
    from app.services.snapshot_service import search_and_sync_vm_details

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=24)

    # Henüz VM ID'si bilinmeyen sunucular
    missing = (
        db.query(Server)
        .filter(
            Server.hypervisor_id.isnot(None),
            Server.hypervisor_vm_id.is_(None),
        )
        .all()
    )

    # VM ID'si var ama son senkronizasyon 24 saatten eski
    stale = (
        db.query(Server)
        .filter(
            Server.hypervisor_id.isnot(None),
            Server.hypervisor_vm_id.isnot(None),
            (Server.vm_last_sync.is_(None)) | (Server.vm_last_sync < stale_cutoff),
        )
        .all()
    )

    targets = missing + stale
    if not targets:
        return

    logger.info(f"VM auto-sync: {len(missing)} eksik ID, {len(stale)} eski kayıt — toplam {len(targets)}")

    ok_count = 0
    for srv in targets:
        try:
            result = search_and_sync_vm_details(srv, db)
            if result.get("found"):
                ok_count += 1
                logger.debug(f"VM sync OK: {srv.name} → {result.get('vm_id')}")
            else:
                logger.debug(f"VM sync miss: {srv.name} — {result.get('message', '')}")
        except Exception as e:
            logger.warning(f"VM sync hata ({srv.name}): {e}")

    if ok_count:
        logger.info(f"VM auto-sync tamamlandı: {ok_count}/{len(targets)} güncellendi")


# Global instance
background_task_manager = BackgroundTaskManager()
