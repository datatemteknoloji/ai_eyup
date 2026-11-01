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


def _hw_logs_any_enabled() -> bool:
    """Host log bayraklarından (3a / ipmitool in-band / BMC Redfish) biri açık mı? Hepsi kapalıysa iş kuyruğa girmez."""
    try:
        from app.services.hw.host_logs import any_enabled
        return bool(any_enabled())
    except Exception:
        return False


async def _enqueue_or_run(task_name: str, local_callable, *, label: str) -> None:
    """Önce Celery; worker yoksa local (executor / await)."""
    try:
        from app.worker import enqueue_fleet_job
        # Adım 11: enqueue_fleet_job Celery ping'i (senkron, ~1–2 sn) yapar — event döngüsünü tıkamasın
        if await asyncio.to_thread(enqueue_fleet_job, task_name):
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
        self.tasks.append(asyncio.create_task(self._periodic_virt_insights()))
        self.tasks.append(asyncio.create_task(self._periodic_backup_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_hw_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_hw_host_logs()))
        self.tasks.append(asyncio.create_task(self._periodic_rag_reindex()))
        self.tasks.append(asyncio.create_task(self._periodic_rag_maintenance()))
        self.tasks.append(asyncio.create_task(self._periodic_snapshot_cleanup()))
        self.tasks.append(asyncio.create_task(self._periodic_event_cleanup()))
        self.tasks.append(asyncio.create_task(self._periodic_node_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_system_update_recovery()))
        self.tasks.append(asyncio.create_task(self._periodic_vm_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_openshift_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_ocp_monitoring_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_auto_onboarding()))
        self.tasks.append(asyncio.create_task(self._periodic_linux_inventory_nlq()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_live_metrics()))
        self.tasks.append(asyncio.create_task(self._periodic_dashboard_stats()))
        self.tasks.append(asyncio.create_task(self._periodic_automic()))
        self.tasks.append(asyncio.create_task(self._periodic_executive_report()))
        self.tasks.append(asyncio.create_task(self._syslog_receiver_supervisor()))

        logger.info("Background tasks started (intervals: Ayarlar → Gelişmiş)")

    async def _periodic_executive_report(self):
        """Kilitli yönetici raporu. Sayfa açılışı bu hesabı yapmaz."""
        logger.info("Executive report snapshot task started (24h)")
        await asyncio.sleep(120)
        while self.running:
            try:
                from app.core.database import SessionLocal
                from app.services.exec_snapshot import produce_bundle

                def _run():
                    db = SessionLocal()
                    try:
                        return produce_bundle(db)
                    finally:
                        db.close()

                await asyncio.to_thread(_run)
                await asyncio.sleep(24 * 3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Executive report snapshot error: {e}")
                await asyncio.sleep(3600)

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

    async def _periodic_dashboard_stats(self):
        """Sağlık sayaçlarını (event + incident) periyodik say. Sayfa açılışı önbellekten okur."""
        logger.info("Dashboard stats cache warmer started (60s)")
        await asyncio.sleep(20)
        while self.running:
            try:
                from app.services.dashboard_stats_cache import refresh_dashboard_stat_caches
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, refresh_dashboard_stat_caches)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Dashboard stats cache error: %s", e)
            await asyncio.sleep(60)

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
                        await asyncio.to_thread(qa_cache.invalidate_all)  # Adım 11: Redis SCAN event döngüsünü bloklamasın
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
                        try:
                            from app.services.openshift.ocp_monitoring import sync_all_ocp_monitoring_metrics
                            mon = await loop.run_in_executor(None, sync_all_ocp_monitoring_metrics, db)
                        except Exception as mon_exc:
                            logger.warning("OCP monitoring metric sync: %s", mon_exc)
                            mon = {}
                        try:
                            # Hazır raporlar › MTV Migrasyon: Plan/Migration anlık görüntüsü (salt-okunur GET)
                            from app.services.openshift.mtv_history import sync_all_mtv_history
                            await loop.run_in_executor(None, sync_all_mtv_history, db)
                        except Exception as mtv_exc:
                            logger.warning("MTV geçmiş anlık görüntüsü: %s", mtv_exc)
                        logger.info(
                            "OpenShift sync: %s cluster, %s yeni olay, monitoring rows=%s",
                            inv_result.get("total_clusters", 0),
                            ev_result.get("total_saved", 0),
                            mon.get("rows", 0),
                        )
                        from app.services import qa_cache
                        await asyncio.to_thread(qa_cache.invalidate_all)  # Adım 11: Redis SCAN event döngüsünü bloklamasın
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

    async def _periodic_ocp_monitoring_sync(self):
        """OCP Monitoring Timescale örnekleri — varsayılan 60s (geçmiş birikir)."""
        logger.info("OCP monitoring metric sync started (60s interval)")
        await asyncio.sleep(20)

        while self.running:
            try:
                from app.services.fleet_jobs import run_ocp_monitoring_sync
                await _enqueue_or_run(
                    "fleet.ocp_monitoring_sync",
                    run_ocp_monitoring_sync,
                    label="ocp_monitoring",
                )
                await asyncio.sleep(_rt_sec("ocp_monitoring_interval_sec", 60))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"OCP monitoring sync task error: {e}")
                await asyncio.sleep(_rt_sec("ocp_monitoring_interval_sec", 60))

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

    async def _periodic_virt_insights(self):
        """Sanallaştırma karar katmanı — Celery (ilk tur metrik sync'ten sonra)."""
        logger.info("Virt insights task started (Celery, first run in 600s)")
        await asyncio.sleep(600)

        while self.running:
            try:
                from app.services.fleet_jobs import run_virt_insights
                await _enqueue_or_run("fleet.virt_insights", run_virt_insights, label="virt_insights")
                await asyncio.sleep(_rt_sec("virt_insights_interval_sec", 3600))
            except asyncio.CancelledError:
                logger.info("Virt insights task cancelled")
                break
            except Exception as e:
                logger.error(f"Virt insights task unexpected error: {e}")
                await asyncio.sleep(_rt_sec("virt_insights_interval_sec", 3600))

    async def _periodic_backup_sync(self):
        """Opsiyonel yedek sağlayıcı senkronu. Enabled instance yoksa HİÇBİR iş kuyruğa girmez
        (Veeam'siz ortam bugünkü gibi davranır); tick yalnız tek hafif DB sorgusudur."""
        logger.info("Backup sync scheduler started (yalnız enabled instance varken iş üretir)")
        await asyncio.sleep(120)

        while self.running:
            try:
                from app.services.backup.sync import has_enabled_backup_instance
                if await asyncio.to_thread(has_enabled_backup_instance):
                    from app.services.fleet_jobs import run_backup_sync
                    await _enqueue_or_run("fleet.backup_sync", run_backup_sync, label="backup_sync")
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                logger.info("Backup sync task cancelled")
                break
            except Exception as e:
                logger.error(f"Backup sync task unexpected error: {e}")
                await asyncio.sleep(300)

    async def _periodic_hw_sync(self):
        """Opsiyonel donanım sağlayıcı senkronu (Dell OME / HPE OneView). Etkin entegrasyon yoksa HİÇBİR iş kuyruğa
        girmez (donanım entegrasyonsuz ortam bugünkü gibi davranır); tick yalnız tek hafif DB sorgusudur."""
        logger.info("Hardware sync scheduler started (yalnız enabled instance varken iş üretir)")
        await asyncio.sleep(150)

        while self.running:
            try:
                from app.services.hw.registry_util import has_enabled_hw_instance
                if await asyncio.to_thread(has_enabled_hw_instance):
                    from app.services.fleet_jobs import run_hw_sync
                    await _enqueue_or_run("fleet.hw_sync", run_hw_sync, label="hw_sync")
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                logger.info("Hardware sync task cancelled")
                break
            except Exception as e:
                logger.error(f"Hardware sync task unexpected error: {e}")
                await asyncio.sleep(300)

    async def _periodic_hw_host_logs(self):
        """Faz 3a: host donanım logları. `hw_host_logs_enabled` KAPALIyken (varsayılan) iş kuyruğa HİÇ girmez;
        tick yalnız ayar okumasıdır."""
        logger.info("Host hardware logs scheduler started (yalnız ayar açıkken iş üretir)")
        await asyncio.sleep(240)

        while self.running:
            try:
                from app.services.runtime_settings import get_bool
                if await asyncio.to_thread(_hw_logs_any_enabled):
                    from app.services.fleet_jobs import run_hw_host_logs
                    await _enqueue_or_run("fleet.hw_host_logs", run_hw_host_logs, label="hw_host_logs")
                    await asyncio.sleep(_rt_sec("hw_host_logs_interval_sec", 3600))
                else:
                    await asyncio.sleep(300)
            except asyncio.CancelledError:
                logger.info("Host hardware logs task cancelled")
                break
            except Exception as e:
                logger.error(f"Host hardware logs task unexpected error: {e}")
                await asyncio.sleep(300)

    async def _periodic_rag_reindex(self):
        """RAG reindex tetikleyici — asıl embedding işi Celery worker'ında çalışır.

        API process'i yalnızca zamanlayıcı tick'i atar; incident/event/knowledge
        embedding'i `fleet.rag_reindex` ile ayrı process'e gider (Level 1 dahil
        hiçbir backend bileşeni bu yüzden yavaşlamaz). Kayıt imzası değişmemişse
        embed hiç yapılmaz (bkz. rag_service.select_changed_chunks)."""
        logger.info("RAG reindex scheduler started (Celery, first run in 300s)")
        await asyncio.sleep(300)

        while self.running:
            try:
                from app.services.fleet_jobs import run_rag_reindex
                await _enqueue_or_run("fleet.rag_reindex", run_rag_reindex, label="rag_reindex")
                await asyncio.sleep(_rt_sec("rag_reindex_interval_sec", 1800))

            except asyncio.CancelledError:
                logger.info("RAG reindex task cancelled")
                break
            except Exception as e:
                logger.error(f"RAG reindex task error: {e}")
                await asyncio.sleep(_rt_sec("rag_reindex_interval_sec", 1800))


    async def _periodic_rag_maintenance(self):
        """Öksüz RAG chunk temizliği — event/incident retention sonrası bakım.

        Embedding yapmaz (yalnızca DB silme), bu yüzden reindex'ten ayrı ve
        çok daha seyrek çalışır. Asıl iş Celery worker'ında."""
        logger.info("RAG maintenance scheduler started (first run in 900s)")
        await asyncio.sleep(900)

        while self.running:
            try:
                from app.services.fleet_jobs import run_rag_maintenance
                await _enqueue_or_run(
                    "fleet.rag_maintenance", run_rag_maintenance, label="rag_maintenance",
                )
                await asyncio.sleep(_rt_sec("rag_maintenance_interval_sec", 86400))

            except asyncio.CancelledError:
                logger.info("RAG maintenance task cancelled")
                break
            except Exception as e:
                logger.error(f"RAG maintenance task error: {e}")
                await asyncio.sleep(_rt_sec("rag_maintenance_interval_sec", 86400))

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
                    await asyncio.to_thread(qa_cache.invalidate_all)  # Adım 11: Redis SCAN event döngüsünü bloklamasın
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

    async def _periodic_automic(self):
        """Automic (UC4) collector + bakım — ayrı executor, DB yoksa uzun bekleme."""
        from concurrent.futures import ThreadPoolExecutor

        logger.info("Automic scheduler task started (60s tick)")
        await asyncio.sleep(90)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="automic")
        try:
            while self.running:
                delay = 60
                try:
                    from app.services.automic.scheduler import step
                    res = await asyncio.get_event_loop().run_in_executor(pool, step)
                    if not res.get("db"):
                        delay = 600
                    elif not res.get("systems", 1):
                        delay = 300
                except asyncio.CancelledError:
                    logger.info("Automic scheduler cancelled")
                    break
                except Exception as e:
                    logger.error(f"Automic scheduler error: {e}", exc_info=True)
                await asyncio.sleep(delay)
        finally:
            pool.shutdown(wait=False)

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

# hypervisor_id → time.monotonic() değeri; bu zamana kadar toplu VM sync o hypervisor'ı atlar
# (erişilemeyen vCenter/oVirt için her sunucuda 10 sn bağlantı zaman aşımı yaşanmasın).
_VM_SYNC_BACKOFF: dict = {}


def _run_vm_sync_batch(db) -> None:
    """
    Blocking işlev — thread pool'da çalışır.
    1. hypervisor_id var, hypervisor_vm_id yok → hemen sync et
    2. hypervisor_vm_id var ama vm_last_sync > 24 saat önce → yenile
    """
    import time as _time
    from collections import OrderedDict
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import or_
    from app.core.database import SessionLocal
    from app.models.server import Server
    from app.services.snapshot_service import search_and_sync_vm_details

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=24)

    # Hedef listesi: yalnız (id, hypervisor_id) — ORM nesnesi tutulmaz. Eksik VM ID'si
    # VEYA son senkronizasyon 24 saatten eski olanlar.
    rows = (
        db.query(Server.id, Server.hypervisor_id)
        .filter(
            Server.hypervisor_id.isnot(None),
            or_(
                Server.hypervisor_vm_id.is_(None),
                Server.vm_last_sync.is_(None),
                Server.vm_last_sync < stale_cutoff,
            ),
        )
        .order_by(Server.hypervisor_id, Server.id)
        .all()
    )
    # Listeyi aldıktan sonra işlemi KAPAT: aksi halde tüm tur boyunca (saatlerce) açık kalıp
    # TimescaleDB retention'ın AccessExclusive kilidini engeller → uygulama kilitlenir.
    try:
        db.rollback()
    except Exception:
        pass

    if not rows:
        return

    by_hv: "OrderedDict[int, list]" = OrderedDict()
    for sid, hv_id in rows:
        by_hv.setdefault(hv_id, []).append(sid)

    logger.info(f"VM auto-sync: {len(rows)} sunucu, {len(by_hv)} hypervisor")

    max_seconds = int(os.getenv("VM_AUTO_SYNC_MAX_SECONDS", "1800"))
    breaker_threshold = int(os.getenv("VM_AUTO_SYNC_BREAKER_FAILS", "2"))
    backoff_seconds = int(os.getenv("VM_AUTO_SYNC_BACKOFF_SECONDS", "1800"))
    deadline = _time.monotonic() + max_seconds

    ok_count = 0
    attempted = 0
    skipped_unreachable = 0
    for hv_id, server_ids in by_hv.items():
        if _time.monotonic() < _VM_SYNC_BACKOFF.get(hv_id, 0.0):
            skipped_unreachable += len(server_ids)
            logger.info("VM auto-sync: hypervisor #%s geri çekilme süresinde — %d sunucu atlandı",
                        hv_id, len(server_ids))
            continue

        consecutive_unreachable = 0
        for idx, sid in enumerate(server_ids):
            if _time.monotonic() > deadline:
                logger.warning("VM auto-sync: süre sınırı (%ss) doldu; kalan sunucular sonraki tura", max_seconds)
                break
            # Sunucu başına KISA oturum: ağ beklemesi sırasında açık işlem tutulmaz.
            s = SessionLocal()
            try:
                srv = s.get(Server, sid)
                if srv is None:
                    continue
                attempted += 1
                result = search_and_sync_vm_details(srv, s)
                if result.get("found"):
                    ok_count += 1
                    consecutive_unreachable = 0
                    logger.debug(f"VM sync OK: #{sid} → {result.get('vm_id')}")
                elif result.get("unreachable"):
                    consecutive_unreachable += 1
                    logger.debug(f"VM sync miss: #{sid} — {result.get('message', '')}")
                else:
                    consecutive_unreachable = 0
                    logger.debug(f"VM sync miss: #{sid} — {result.get('message', '')}")
            except Exception as e:
                logger.warning(f"VM sync hata (#{sid}): {e}")
            finally:
                try:
                    s.rollback()
                except Exception:
                    pass
                s.close()

            if consecutive_unreachable >= breaker_threshold:
                rest = len(server_ids) - idx - 1
                skipped_unreachable += rest
                _VM_SYNC_BACKOFF[hv_id] = _time.monotonic() + backoff_seconds
                logger.warning(
                    "VM auto-sync: hypervisor #%s erişilemiyor (%d ardışık başarısız oturum) — "
                    "kalan %d sunucu atlandı, %d sn geri çekilme",
                    hv_id, consecutive_unreachable, rest, backoff_seconds,
                )
                break
        else:
            # Hiç kesilmediyse hypervisor ulaşılabilir
            _VM_SYNC_BACKOFF.pop(hv_id, None)

    logger.info(
        "VM auto-sync tamamlandı: %d/%d güncellendi (%d atlandı: erişilemeyen hypervisor)",
        ok_count, attempted, skipped_unreachable,
    )


# Global instance
background_task_manager = BackgroundTaskManager()
