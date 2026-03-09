"""
Background Tasks - Periyodik görevler
"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.monitoring.server_health_checker import ServerHealthChecker

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Arka plan görevlerini yöneten sınıf"""
    
    def __init__(self):
        self.running = False
        self.tasks = []
    
    async def start(self):
        """Arka plan görevlerini başlat"""
        if self.running:
            logger.warning("Background tasks already running")
            return
        
        self.running = True
        logger.info("Starting background tasks...")
        
        # Her dakika sunucu durumlarını kontrol et
        self.tasks.append(asyncio.create_task(self._periodic_health_check()))
        self.tasks.append(asyncio.create_task(self._periodic_metric_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_anomaly_scan()))
        self.tasks.append(asyncio.create_task(self._periodic_log_collection()))
        self.tasks.append(asyncio.create_task(self._periodic_inventory_sync()))
        
        logger.info("Background tasks started (health:5m, metrics:10m, anomaly:5m, logs:10m, inventory:ayarlardan)")
    
    async def stop(self):
        """Arka plan görevlerini durdur"""
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
        logger.info("Background tasks stopped")
    
    async def _periodic_health_check(self):
        """İlk çalışma 30 saniye sonra, sonra her 5 dakikada bir sunucu durumlarını kontrol et"""
        logger.info("Periodic health check task started (first run in 30s, then every 300s)")
        first_run = True

        while self.running:
            try:
                # İlk seferde 30 sn bekle (backend ayağa kalkar kalkmaz durumlar güncellensin), sonra 5 dk
                await asyncio.sleep(30 if first_run else 300)
                first_run = False

                if not self.running:
                    break

                # Sunucu durumlarını kontrol et
                db = SessionLocal()
                try:
                    logger.info(f"Running scheduled health check at {datetime.now()}")
                    stats = ServerHealthChecker.update_server_statuses(db)

                    if stats.get("updated", 0) > 0:
                        logger.info(f"Health check completed: {stats.get('checked', 0)} checked, "
                                   f"{stats.get('updated', 0)} updated, "
                                   f"{stats.get('online', 0)} online, "
                                   f"{stats.get('offline', 0)} offline")
                    else:
                        logger.debug(f"Health check completed: no changes")

                except Exception as e:
                    logger.error(f"Health check error: {e}", exc_info=True)
                finally:
                    db.close()

            except asyncio.CancelledError:
                logger.info("Health check task cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in health check task: {e}", exc_info=True)
                await asyncio.sleep(300)


    async def _periodic_anomaly_scan(self):
        """Her 5 dakikada anomali taramasi yapar."""
        logger.info("Anomaly scan task started (300s interval)")
        await asyncio.sleep(60)  # Ilk tarama icin 1dk bekle
        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.anomaly_detector import detect_all_anomalies
                    anomalies = detect_all_anomalies(db)
                    if anomalies:
                        critical = [a for a in anomalies if a["severity"] == "critical"]
                        warning = [a for a in anomalies if a["severity"] == "warning"]
                        logger.warning(
                            f"Anomaly scan: {len(anomalies)} anomali - "
                            f"{len(critical)} kritik, {len(warning)} uyari"
                        )
                except Exception as e:
                    logger.error(f"Anomaly scan error: {e}")
                finally:
                    db.close()
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Anomaly scan task error: {e}")
                await asyncio.sleep(300)

    async def _periodic_log_collection(self):
        """Her 10 dakikada sunuculardan log toplar ve anomali tespiti yapar."""
        logger.info("Log collection task started (600s interval)")
        await asyncio.sleep(45)  # Ilk collection icin bekle
        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.log_collector import collect_all_servers_logs
                    from app.services.log_anomaly_detector import detect_log_anomalies
                    # Log topla
                    result = collect_all_servers_logs(db)
                    if result["total_saved"] > 0:
                        logger.warning(
                            f"Log collection: {result['total_saved']} yeni log, "
                            f"{result['servers_with_logs']} sunucu"
                        )
                    # Log anomali tespiti
                    anomalies = detect_log_anomalies(db)
                    if anomalies:
                        critical = [a for a in anomalies if a["severity"] == "critical"]
                        logger.warning(
                            f"Log anomaly: {len(anomalies)} anomali "
                            f"({len(critical)} kritik)"
                        )
                except Exception as e:
                    logger.error(f"Log collection/anomaly error: {e}")
                finally:
                    db.close()
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Log collection task error: {e}")
                await asyncio.sleep(600)

    async def _periodic_metric_sync(self):
        """Her 10 dakikada Prometheus metriklerini TimescaleDB'ye yazar."""
        logger.info("Metric sync task started (600s interval)")
        await asyncio.sleep(30)  # Ilk sync icin bekle
        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.metric_sync import MetricSyncService
                    stats = await MetricSyncService.sync_all_servers_metrics(db, minutes=12)
                    logger.info(f"Metric sync: {stats.get('synced_servers',0)}/{stats.get('total_servers',0)} sunucu, {stats.get('total_metrics',0)} kayit")
                except Exception as e:
                    logger.error(f"Metric sync error: {e}")
                finally:
                    db.close()
                await asyncio.sleep(600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metric sync task error: {e}")
                await asyncio.sleep(600)

    async def _periodic_inventory_sync(self):
        """Envanter sync - Ayarlardan okunan aralıkta (varsayılan saatte bir) hypervisor'lardan VM'leri DB'ye çeker."""
        from app.models.app_settings import AppSettings
        DEFAULT_MINUTES = 60
        logger.info("Inventory sync task started (interval from settings, default 60min)")
        await asyncio.sleep(120)  # İlk sync 2 dk sonra
        while self.running:
            try:
                db = SessionLocal()
                try:
                    row = db.query(AppSettings).filter(AppSettings.key == "inventory_sync_interval_minutes").first()
                    interval_min = int(row.value) if row and row.value else DEFAULT_MINUTES
                    interval_sec = max(900, interval_min * 60)  # min 15 dk
                except Exception:
                    interval_sec = DEFAULT_MINUTES * 60
                finally:
                    db.close()

                await asyncio.sleep(interval_sec)
                if not self.running:
                    break

                db = SessionLocal()
                try:
                    from app.services.inventory_sync_service import sync_all_hypervisors
                    result = sync_all_hypervisors(db)
                    logger.info(
                        f"Inventory sync: {result['total_synced']} sunucu, "
                        f"{len(result['hypervisors'])} hypervisor"
                    )
                except Exception as e:
                    logger.error(f"Inventory sync error: {e}", exc_info=True)
                finally:
                    db.close()
            except asyncio.CancelledError:
                logger.info("Inventory sync task cancelled")
                break
            except Exception as e:
                logger.error(f"Inventory sync task error: {e}")
                await asyncio.sleep(3600)


# Global instance
background_task_manager = BackgroundTaskManager()
