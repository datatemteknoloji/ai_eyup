"""
Bulk AI Ready Service - Tüm sunucuları tarayıp SSH bağlantısı yapılabilenleri AI Ready yapar
"""
import logging
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)


class BulkAIReadyService:
    """Toplu AI Ready işlemleri"""
    
    @staticmethod
    def scan_and_mark_ai_ready(db: Session, credential_id: Optional[int] = None) -> Dict:
        """
        Tüm sunucuları tara ve SSH bağlantısı yapılabilenleri AI Ready yap
        
        Args:
            db: Database session
            credential_id: Kullanılacak global credential ID (None ise default kullan)
        
        Returns:
            {
                "total_servers": int,
                "scanned": int,
                "ai_ready_marked": int,
                "failed": int,
                "results": List[Dict]
            }
        """
        # Credential bul
        if credential_id:
            credential = db.query(GlobalCredential).filter(
                GlobalCredential.id == credential_id
            ).first()
        else:
            credential = db.query(GlobalCredential).filter(
                GlobalCredential.is_default == True
            ).first()
        
        if not credential:
            return {
                "total_servers": 0,
                "scanned": 0,
                "ai_ready_marked": 0,
                "failed": 0,
                "error": "Global credential bulunamadı. Lütfen önce Settings'ten credential tanımlayın."
            }
        
        # IP adresi olan tüm sunucuları al
        servers = db.query(Server).filter(
            Server.ip_address != None,
            Server.ip_address != ""
        ).all()
        
        results = {
            "total_servers": len(servers),
            "scanned": 0,
            "ai_ready_marked": 0,
            "failed": 0,
            "results": []
        }
        
        logger.info(f"🔍 {len(servers)} sunucu taranacak (credential: {credential.name})")
        
        for server in servers:
            results["scanned"] += 1
            
            try:
                # SSH bağlantısı test et
                ssh = SSHManager(
                    host=server.ip_address,
                    username=credential.username,
                    password=credential.password,
                    private_key=credential.private_key,
                    port=credential.port,
                    sudo_password=credential.sudo_password
                )
                
                test_result = ssh.test_connection()
                ssh.close()
                
                if test_result.get("success"):
                    # Credential'ı sunucuya kaydet
                    if not server.connection_config:
                        server.connection_config = {}
                    
                    server.connection_config.update({
                        "username": credential.username,
                        "password": credential.password,
                        "private_key": credential.private_key,
                        "port": credential.port,
                        "sudo_password": credential.sudo_password
                    })
                    
                    # AI Ready işaretle
                    server.ai_ready = True
                    results["ai_ready_marked"] += 1
                    
                    results["results"].append({
                        "server_id": server.id,
                        "server_name": server.name,
                        "ip_address": server.ip_address,
                        "status": "success",
                        "message": f"✅ SSH bağlantısı başarılı",
                        "details": test_result.get("details", {})
                    })
                    
                    logger.info(f"✅ {server.name} ({server.ip_address}) - AI Ready yapıldı")
                else:
                    results["failed"] += 1
                    results["results"].append({
                        "server_id": server.id,
                        "server_name": server.name,
                        "ip_address": server.ip_address,
                        "status": "failed",
                        "message": "❌ SSH bağlantısı başarısız",
                        "details": test_result.get("message", "")
                    })
                    logger.warning(f"❌ {server.name} ({server.ip_address}) - SSH başarısız")
                    
            except Exception as e:
                results["failed"] += 1
                results["results"].append({
                    "server_id": server.id,
                    "server_name": server.name,
                    "ip_address": server.ip_address,
                    "status": "error",
                    "message": f"❌ Hata: {str(e)}"
                })
                logger.error(f"❌ {server.name} - Hata: {e}")
        
        # Değişiklikleri kaydet
        db.commit()
        
        logger.info(f"🎉 Tarama tamamlandı: {results['ai_ready_marked']}/{results['scanned']} sunucu AI Ready")
        
        return results
