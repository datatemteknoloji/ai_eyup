"""
Prometheus Target Manager - File-based service discovery için target yönetimi
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

class PrometheusTargetManager:
    """Prometheus file-based service discovery için target yönetimi"""
    
    def __init__(self, targets_file: str = "/etc/prometheus/targets/node_exporter_targets.json"):
        self.targets_file = Path(targets_file)
        self.targets_file.parent.mkdir(parents=True, exist_ok=True)
        self.reload_url = "http://prometheus:9090/-/reload"
    
    def load_targets(self) -> List[Dict[str, Any]]:
        """Target dosyasını yükle"""
        try:
            if self.targets_file.exists():
                with open(self.targets_file, 'r') as f:
                    data = json.load(f)
                    return data if isinstance(data, list) else []
            return []
        except Exception as e:
            logger.error(f"Target dosyası yüklenemedi: {e}")
            return []
    
    def save_targets(self, targets: List[Dict[str, Any]]) -> bool:
        """Target dosyasını kaydet"""
        try:
            with open(self.targets_file, 'w') as f:
                json.dump(targets, f, indent=2)
            logger.info(f"Target dosyası kaydedildi: {self.targets_file}")
            return True
        except Exception as e:
            logger.error(f"Target dosyası kaydedilemedi: {e}")
            return False
    
    def add_target(self, instance: str, labels: Optional[Dict[str, str]] = None) -> bool:
        """Yeni target ekle"""
        targets = self.load_targets()
        
        # Mevcut target'ı kontrol et
        existing = next((t for t in targets if t.get("targets") and t.get("targets", [])[0] == instance), None)
        
        if existing:
            logger.info(f"Target zaten mevcut: {instance}")
            return False
        
        # Yeni target ekle
        new_target = {
            "targets": [instance],
            "labels": labels or {}
        }
        targets.append(new_target)
        
        return self.save_targets(targets)
    
    def remove_target(self, instance: str) -> bool:
        """Target kaldır"""
        targets = self.load_targets()
        
        # Target'ı bul ve kaldır
        updated_targets = [t for t in targets if not (t.get("targets") and t.get("targets", [])[0] == instance)]
        
        if len(updated_targets) == len(targets):
            logger.info(f"Target bulunamadı: {instance}")
            return False
        
        return self.save_targets(updated_targets)
    
    def list_targets(self) -> List[Dict[str, Any]]:
        """Tüm target'ları listele"""
        return self.load_targets()
    
    async def reload_prometheus_async(self) -> bool:
        """Prometheus'u async olarak reload et"""
        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp modülü yüklü değil, sync reload kullanılacak")
            return self.reload_prometheus_sync()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.reload_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        logger.info("Prometheus reload edildi")
                        return True
                    else:
                        logger.warning(f"Prometheus reload hatası: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"Prometheus reload hatası: {e}")
            return False
    
    def reload_prometheus_sync(self) -> bool:
        """Prometheus'u sync olarak reload et (fallback)"""
        try:
            import requests
            response = requests.post(self.reload_url, timeout=5)
            if response.status_code == 200:
                logger.info("Prometheus reload edildi (sync)")
                return True
            else:
                logger.warning(f"Prometheus reload hatası: {response.status_code}")
                return False
        except ImportError:
            logger.warning("requests modülü yüklü değil, Prometheus reload atlanıyor")
            return False
        except Exception as e:
            logger.error(f"Prometheus reload hatası: {e}")
            return False