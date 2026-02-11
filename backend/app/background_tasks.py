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
        
        logger.info("Background tasks started")
    
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
        """Her 5 dakikada bir sunucu durumlarını kontrol et"""
        logger.info("Periodic health check task started (300s interval)")
        
        while self.running:
            try:
                # 5 dakika bekle (300 saniye)
                await asyncio.sleep(300)
                
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
                # Hatada bile devam et
                await asyncio.sleep(300)


# Global instance
background_task_manager = BackgroundTaskManager()
