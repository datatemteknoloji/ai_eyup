"""
Background Tasks - Periyodik görevler
Tüm blocking (SSH, socket, vCenter) çağrılar run_in_executor ile thread pool'da çalışır.
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
        if self.running:
            logger.warning("Background tasks already running")
            return

        self.running = True
        logger.info("Starting background tasks...")

        self.tasks.append(asyncio.create_task(self._periodic_health_check()))
        self.tasks.append(asyncio.create_task(self._periodic_metric_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_anomaly_scan()))
        self.tasks.append(asyncio.create_task(self._periodic_log_collection()))
        self.tasks.append(asyncio.create_task(self._periodic_inventory_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_esx_metric_sync()))

        logger.info("Background tasks started (health:5m, metrics:10m, anomaly:5m, logs:15m, inventory:ayarlardan, esx-metrics:15m)")

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
        logger.info("Background tasks stopped")

    async def _periodic_health_check(self):
        """Ilk 30s bekle, sonra her 5 dakikada sunucu durumlarini kontrol et.
        update_server_statuses blocking -> thread pool da calistir."""
        logger.info("Periodic health check task started (first run in 30s, then every 300s)")
        first_run = True

        while self.running:
            try:
                await asyncio.sleep(30 if first_run else 300)
                first_run = False

                if not self.running:
                    break

                db = SessionLocal()
                try:
                    logger.info(f"Running scheduled health check at {datetime.now()}")
                    loop = asyncio.get_event_loop()
                    stats = await loop.run_in_executor(
                        None, ServerHealthChecker.update_server_statuses, db
                    )
                    if stats.get("updated", 0) > 0:
                        logger.info(
                            f"Health check: {stats.get('checked',0)} checked, "
                            f"{stats.get('updated',0)} updated, "
                            f"{stats.get('online',0)} online, {stats.get('offline',0)} offline"
                        )
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

    async def _periodic_log_collection(self):
        """Her 15 dakikada ONLINE sunuculardan log toplar.
        SSH cagrilan blocking -> thread pool da calistir."""
        logger.info("Log collection task started (900s interval, executor)")
        await asyncio.sleep(90)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.log_collector import collect_all_servers_logs
                    from app.services.log_anomaly_detector import detect_log_anomalies

                    loop = asyncio.get_event_loop()

                    result = await loop.run_in_executor(
                        None, collect_all_servers_logs, db
                    )
                    if result["total_saved"] > 0:
                        logger.warning(
                            f"Log collection: {result['total_saved']} yeni log, "
                            f"{result['servers_with_logs']} sunucu"
                        )

                    anomalies = await loop.run_in_executor(
                        None, detect_log_anomalies, db
                    )
                    if anomalies:
                        critical = [a for a in anomalies if a["severity"] == "critical"]
                        logger.warning(
                            f"Log anomaly: {len(anomalies)} anomali ({len(critical)} kritik)"
                        )
                except Exception as e:
                    logger.error(f"Log collection/anomaly error: {e}")
                finally:
                    db.close()

                await asyncio.sleep(900)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Log collection task error: {e}")
                await asyncio.sleep(900)

    async def _periodic_anomaly_scan(self):
        """Her 5 dakikada Prometheus metriklerinden anomali tarar.
        CPU yogun olabilir -> thread pool da calistir."""
        logger.info("Anomaly scan task started (300s interval, executor)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.anomaly_detector import detect_all_anomalies

                    loop = asyncio.get_event_loop()
                    anomalies = await loop.run_in_executor(
                        None, detect_all_anomalies, db
                    )
                    if anomalies:
                        critical = [a for a in anomalies if a["severity"] == "critical"]
                        warning  = [a for a in anomalies if a["severity"] == "warning"]
                        logger.warning(
                            f"Anomaly scan: {len(anomalies)} anomali -- "
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

    async def _periodic_metric_sync(self):
        """Her 10 dakikada Prometheus metriklerini TimescaleDB ye yazar.
        MetricSyncService zaten async."""
        logger.info("Metric sync task started (600s interval)")
        await asyncio.sleep(60)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.metric_sync import MetricSyncService
                    stats = await MetricSyncService.sync_all_servers_metrics(db, minutes=12)
                    logger.info(
                        f"Metric sync: {stats.get('synced_servers',0)}/{stats.get('total_servers',0)} "
                        f"sunucu, {stats.get('total_metrics',0)} kayit"
                    )
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
        """Ayarlardan okunan aralikta (min 15dk) hypervisor lardan VM leri DB ye ceker.
        vCenter API cagrilan blocking -> thread pool da calistir."""
        from app.models.app_settings import AppSettings
        DEFAULT_MINUTES = 60
        logger.info("Inventory sync task started (interval from settings, default 60min)")
        await asyncio.sleep(180)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    row = db.query(AppSettings).filter(
                        AppSettings.key == "inventory_sync_interval_minutes"
                    ).first()
                    interval_min = int(row.value) if row and row.value else DEFAULT_MINUTES
                    interval_sec = max(900, interval_min * 60)
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

                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        None, sync_all_hypervisors, db
                    )
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


    async def _periodic_esx_metric_sync(self):
        """Her 15 dakikada VMware vCenter'lardan ESX host metriklerini DB'ye yazar.
        vCenter SOAP çağrıları blocking → thread pool'da çalıştır."""
        logger.info("ESX metric sync task started (900s interval, first run in 120s)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.esx_metric_sync import sync_esx_metrics
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, sync_esx_metrics, db)
                    if result["hosts"] > 0 or result["errors"]:
                        logger.info(
                            f"ESX metric sync: {result['hypervisors']} hypervisor, "
                            f"{result['hosts']} host kaydı yazıldı"
                            + (f", hatalar: {result['errors']}" if result["errors"] else "")
                        )
                except Exception as e:
                    logger.error(f"ESX metric sync error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(900)

            except asyncio.CancelledError:
                logger.info("ESX metric sync task cancelled")
                break
            except Exception as e:
                logger.error(f"ESX metric sync task unexpected error: {e}")
                await asyncio.sleep(900)


# Global instance
background_task_manager = BackgroundTaskManager()
