"""
Background Tasks - Periyodik görevler
Tüm blocking (SSH, socket, vCenter) çağrılar run_in_executor ile thread pool'da çalışır.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services.monitoring.server_health_checker import ServerHealthChecker

logger = logging.getLogger(__name__)


def _rt_sec(key: str, default: int) -> int:
    """Gelişmiş ayarlardan saniye aralığı (runtime, restart gerekmez)."""
    try:
        from app.services.runtime_settings import get_int
        return int(get_int(key))
    except Exception:
        return default


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
        self.tasks.append(asyncio.create_task(self._periodic_windows_log_collection()))
        self.tasks.append(asyncio.create_task(self._periodic_virt_log_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_inventory_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_esx_metric_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_rag_reindex()))
        self.tasks.append(asyncio.create_task(self._periodic_snapshot_cleanup()))
        self.tasks.append(asyncio.create_task(self._periodic_node_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_windows_exporter_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_system_update_recovery()))
        self.tasks.append(asyncio.create_task(self._periodic_vm_sync()))
        self.tasks.append(asyncio.create_task(self._periodic_auto_onboarding()))

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
        logger.info("Background tasks stopped")

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

                db = SessionLocal()
                try:
                    logger.info(f"Running scheduled health check at {datetime.now()}")
                    loop = asyncio.get_event_loop()
                    stats = await loop.run_in_executor(
                        None, ServerHealthChecker.update_server_statuses, db
                    )
                    if stats.get("updated", 0) > 0 or stats.get("checked", 0) > 0:
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
                await asyncio.sleep(_rt_sec("health_check_interval_sec", 600))

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

                await asyncio.sleep(_rt_sec("log_collection_interval_sec", 900))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Log collection task error: {e}")
                await asyncio.sleep(_rt_sec("log_collection_interval_sec", 900))

    async def _periodic_windows_log_collection(self):
        """Windows sunuculardan WinRM ile event log toplama."""
        logger.info("Windows log collection task started (900s interval)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.windows_log_collector import collect_all_windows_logs
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, collect_all_windows_logs, db)
                    if result.get("total_saved", 0) > 0:
                        logger.warning(
                            "Windows log collection: %s yeni log, %s sunucu",
                            result["total_saved"],
                            result["servers_with_logs"],
                        )
                except Exception as e:
                    logger.error(f"Windows log collection error: {e}")
                finally:
                    db.close()
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
        """Her 5 dakikada Prometheus metriklerinden anomali tarar.
        CPU yogun olabilir -> thread pool da calistir."""
        logger.info("Anomaly scan task started (300s interval, executor)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.anomaly_detector import detect_all_anomalies
                    from app.services.aiops_engine import run_aiops_cycle

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

                    # Kapalı döngü: event üret → incident aç → otomatik RCA
                    # (Ollama çağrıları blocking olduğu için executor'da çalıştır)
                    result = await loop.run_in_executor(
                        None, run_aiops_cycle, db, anomalies
                    )
                    if result.get("created") or result.get("incidents") or result.get("rca_done"):
                        logger.warning(
                            f"AIOps cycle: {result.get('created',0)} yeni event, "
                            f"{result.get('resolved',0)} cozuldu, "
                            f"{result.get('incidents',0)} incident, "
                            f"{result.get('rca_done',0)} otomatik RCA"
                        )
                except Exception as e:
                    logger.error(f"Anomaly scan error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("anomaly_scan_interval_sec", 300))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Anomaly scan task error: {e}")
                await asyncio.sleep(_rt_sec("anomaly_scan_interval_sec", 300))

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

                await asyncio.sleep(_rt_sec("metric_sync_interval_sec", 600))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metric sync task error: {e}")
                await asyncio.sleep(_rt_sec("metric_sync_interval_sec", 600))

    async def _periodic_inventory_sync(self):
        """Ayarlardan okunan aralikta hypervisor lardan VM leri DB ye ceker."""
        DEFAULT_MINUTES = 5
        logger.info("Inventory sync task started (interval from Gelişmiş ayarlar)")
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

                    # uCMDB REST (açıksa): fiziksel + Exadata
                    try:
                        from app.services.ucmdb_sync_service import load_connection, sync_from_ucmdb
                        ucfg = load_connection(db)
                        if ucfg.get("enabled") and ucfg.get("base_url") and ucfg.get("password"):
                            ures = await loop.run_in_executor(
                                None, lambda: sync_from_ucmdb(db, dry_run=False)
                            )
                            logger.info(
                                "uCMDB sync: physical +%s/~%s, exadata fetched=%s errors=%s",
                                ures.get("created"), ures.get("updated"),
                                ures.get("exadata_fetched"), len(ures.get("errors") or []),
                            )
                    except Exception as ue:
                        logger.warning("uCMDB periodic sync skipped/failed: %s", ue)

                    from app.services import qa_cache
                    qa_cache.invalidate_all()
                except Exception as e:
                    logger.error(f"Inventory sync error: {e}", exc_info=True)
                finally:
                    db.close()

            except asyncio.CancelledError:
                logger.info("Inventory sync task cancelled")
                break
            except Exception as e:
                logger.error(f"Inventory sync task error: {e}")
                await asyncio.sleep(max(60, _rt_sec("inventory_sync_interval_minutes", 5) * 60))


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

                await asyncio.sleep(_rt_sec("esx_metric_interval_sec", 900))

            except asyncio.CancelledError:
                logger.info("ESX metric sync task cancelled")
                break
            except Exception as e:
                logger.error(f"ESX metric sync task unexpected error: {e}")
                await asyncio.sleep(_rt_sec("esx_metric_interval_sec", 900))


    async def _periodic_rag_reindex(self):
        """Her 30 dakikada incident + event kayıtlarını RAG hafızasına indeksler.
        Böylece AI Chat geçmiş olaylardan haberdar olur (kapalı döngü hafıza)."""
        logger.info("RAG reindex task started (1800s interval, first run in 300s)")
        await asyncio.sleep(300)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.rag_service import (
                        ingest_incidents_from_db,
                        ingest_events_from_db,
                    )
                    n_inc = await ingest_incidents_from_db(db)
                    n_evt = await ingest_events_from_db(db)
                    logger.info(f"RAG reindex: {n_inc} incident, {n_evt} event indekslendi")
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
        """Her 10 dakikada Prometheus up durumuna göre node_exporter_running bayrağını senkronlar."""
        logger.info("Node exporter sync task started (600s interval, first run in 120s)")
        await asyncio.sleep(120)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.monitoring.prometheus_metrics import (
                        sync_node_exporter_running_from_prometheus,
                        sync_node_exporter_targets_from_db,
                    )
                    loop = asyncio.get_event_loop()
                    target_stats = await loop.run_in_executor(
                        None, sync_node_exporter_targets_from_db, db
                    )
                    stats = await loop.run_in_executor(
                        None, sync_node_exporter_running_from_prometheus, db
                    )
                    if target_stats.get("removed_orphans") or target_stats.get("targets_before") != target_stats.get("targets_after"):
                        logger.info(
                            f"Prometheus targets: {target_stats.get('targets_before')} -> "
                            f"{target_stats.get('targets_after')} "
                            f"({target_stats.get('removed_orphans', 0)} yetim kaldırıldı)"
                        )
                    if stats.get("updated"):
                        logger.info(
                            f"Node exporter sync: {stats.get('live', 0)} canlı, "
                            f"{stats.get('cleared', 0)} temizlendi, {stats.get('promoted', 0)} eklendi"
                        )
                except Exception as e:
                    logger.error(f"Node exporter sync error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("node_exporter_sync_interval_sec", 600))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Node exporter sync task error: {e}")
                await asyncio.sleep(_rt_sec("node_exporter_sync_interval_sec", 600))

    async def _periodic_windows_exporter_sync(self):
        """Her 10 dakikada Prometheus up durumuna göre windows_exporter_running bayrağını senkronlar
        (node_exporter sync'in Windows eşleniği)."""
        logger.info("Windows exporter sync task started (600s interval, first run in 150s)")
        await asyncio.sleep(150)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    from app.services.monitoring.prometheus_metrics import (
                        sync_windows_exporter_running_from_prometheus,
                        sync_windows_exporter_targets_from_db,
                    )
                    loop = asyncio.get_event_loop()
                    target_stats = await loop.run_in_executor(
                        None, sync_windows_exporter_targets_from_db, db
                    )
                    stats = await loop.run_in_executor(
                        None, sync_windows_exporter_running_from_prometheus, db
                    )
                    if target_stats.get("removed_orphans") or target_stats.get("targets_before") != target_stats.get("targets_after"):
                        logger.info(
                            f"Windows exporter targets: {target_stats.get('targets_before')} -> "
                            f"{target_stats.get('targets_after')} "
                            f"({target_stats.get('removed_orphans', 0)} yetim kaldırıldı)"
                        )
                    if stats.get("updated"):
                        logger.info(
                            f"Windows exporter sync: {stats.get('live', 0)} canlı, "
                            f"{stats.get('cleared', 0)} temizlendi, {stats.get('promoted', 0)} eklendi"
                        )
                except Exception as e:
                    logger.error(f"Windows exporter sync error: {e}", exc_info=True)
                finally:
                    db.close()

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
        """Entegrasyonlar'dan gelen yeni sunucuları otomatik olarak Canlı Metrikler'e
        düşürür: önce SSH/WinRM ile AI Ready testi, sonra AI Ready olanlara
        Node Exporter / Windows Exporter kurulumu. Manuel müdahale gerektirmez.
        İlk çalışma: 150sn, sonra her 10 dakikada bir."""
        logger.info("Auto-onboarding task started (600s interval, first run in 150s)")
        await asyncio.sleep(150)

        while self.running:
            try:
                db = SessionLocal()
                try:
                    loop = asyncio.get_event_loop()

                    from app.api.servers import update_ai_ready
                    from app.api.windows import update_windows_ai_ready, install_exporter_all
                    from app.services.auto_onboarding import (
                        auto_install_node_exporter,
                        collect_os_release_info,
                        collect_windows_update_status,
                        collect_linux_security_audit,
                    )

                    ai_stats = await loop.run_in_executor(None, update_ai_ready, None, db)
                    if ai_stats.get("ai_ready"):
                        logger.info(f"Auto-onboarding: {ai_stats['ai_ready']} Linux sunucu AI Ready oldu")

                    win_ai_stats = await loop.run_in_executor(None, update_windows_ai_ready, None, db)
                    if win_ai_stats.get("ai_ready_count"):
                        logger.info(f"Auto-onboarding: {win_ai_stats['ai_ready_count']} Windows sunucu AI Ready oldu")

                    os_stats = await loop.run_in_executor(None, collect_os_release_info, db)
                    if os_stats.get("updated"):
                        logger.info(f"Auto-onboarding: {os_stats['updated']} sunucunun OS/kernel bilgisi toplandı")

                    ne_stats = await loop.run_in_executor(None, auto_install_node_exporter, db)
                    if ne_stats.get("success"):
                        logger.info(f"Auto-onboarding: {ne_stats['success']} sunucuya Node Exporter kuruldu")

                    we_stats = await loop.run_in_executor(None, install_exporter_all, None, db)
                    if we_stats.get("installed_count"):
                        logger.info(f"Auto-onboarding: {we_stats['installed_count']} Windows sunucuya exporter kuruldu")

                    # Yama/güvenlik raporları için cache — ağır işlemler olduğundan
                    # (COM update search, SSH turu) 6 saatten eski kontrolü olanlar için çalışır.
                    winupd_stats = await loop.run_in_executor(None, collect_windows_update_status, db)
                    if winupd_stats.get("updated"):
                        logger.info(f"Auto-onboarding: {winupd_stats['updated']} Windows sunucunun update/Defender durumu toplandı")

                    secaudit_stats = await loop.run_in_executor(None, collect_linux_security_audit, db)
                    if secaudit_stats.get("updated"):
                        logger.info(f"Auto-onboarding: {secaudit_stats['updated']} Linux sunucunun güvenlik denetimi toplandı")

                    # Uygulama/servis keşfi (Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.) —
                    # sunucu bazında en fazla 12 saatte bir taranır (app_discovery.RESCAN_INTERVAL).
                    from app.services.app_discovery import discover_applications_all_servers
                    appdisc_stats = await loop.run_in_executor(None, discover_applications_all_servers, db)
                    if appdisc_stats.get("scanned"):
                        logger.info(
                            f"Auto-onboarding: {appdisc_stats['scanned']} sunucuda uygulama taraması yapıldı "
                            f"({appdisc_stats.get('apps_found', 0)} uygulama tespit edildi)"
                        )

                    from app.services import qa_cache
                    qa_cache.invalidate_all()
                except Exception as e:
                    logger.error(f"Auto-onboarding error: {e}", exc_info=True)
                finally:
                    db.close()

                await asyncio.sleep(_rt_sec("auto_onboarding_interval_sec", 600))

            except asyncio.CancelledError:
                logger.info("Auto-onboarding task cancelled")
                break
            except Exception as e:
                logger.error(f"Auto-onboarding task error: {e}")
                await asyncio.sleep(_rt_sec("auto_onboarding_interval_sec", 600))


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
