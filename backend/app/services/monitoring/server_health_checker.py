"""
Server Health Checker - Sunucu durumlarını otomatik kontrol eder
"""
import asyncio
import logging
import socket
from typing import Dict, List
from sqlalchemy.orm import Session
from app.models.server import Server

logger = logging.getLogger(__name__)


class ServerHealthChecker:
    """Sunucu sağlık durumunu kontrol eden servis"""
    
    @staticmethod
    def ping_server(ip_address: str, port: int = 22, timeout: int = 2) -> bool:
        """Sunucuya TCP bağlantı ile erişilebilir olup olmadığını kontrol et (rootless container içinde ICMP ping çalışmadığı için)."""
        try:
            with socket.create_connection((ip_address, port), timeout=timeout):
                return True
        except Exception as e:
            logger.debug(f"TCP ping failed for {ip_address}:{port}: {e}")
            return False
    
    @staticmethod
    def check_server_status(server: Server) -> str:
        """Sunucu durumunu kontrol et ve uygun status döndür"""
        if not server.ip_address:
            return "OFFLINE"
        
        # TCP ping ile temel erişilebilirlik kontrolü (SSH portu üzerinden)
        port = 22
        try:
            if server.connection_config and isinstance(server.connection_config, dict):
                port = int(server.connection_config.get("port", 22) or 22)
        except Exception:
            port = 22

        is_reachable = ServerHealthChecker.ping_server(server.ip_address, port=port)
        
        if not is_reachable:
            return "OFFLINE"
        
        # SSH bağlantısı varsa daha detaylı kontrol yapılabilir
        if server.connection_config and server.connection_config.get("username"):
            try:
                from app.services.monitoring.server_connector import ServerConnector
                connector = ServerConnector(server)
                test_result = connector.test_connection()
                connector.close()
                
                if test_result.get("success"):
                    return "ONLINE"
                else:
                    return "WARNING"  # Ping OK ama SSH fail
            except Exception as e:
                logger.debug(f"SSH check failed for {server.name}: {e}")
                return "WARNING"  # Ping OK ama SSH kontrol edilemedi
        
        # Ping OK, SSH yok -> ONLINE kabul et
        return "ONLINE"
    
    @staticmethod
    def update_server_statuses(db: Session) -> Dict[str, int]:
        """Tüm sunucuların durumlarını kontrol et ve güncelle"""
        try:
            servers = db.query(Server).all()
            stats = {"checked": 0, "updated": 0, "online": 0, "offline": 0, "warning": 0}
            
            for server in servers:
                stats["checked"] += 1
                old_status = server.status
                new_status = ServerHealthChecker.check_server_status(server)
                
                if old_status != new_status:
                    server.status = new_status
                    stats["updated"] += 1
                    logger.info(f"Server {server.name} ({server.ip_address}) status: {old_status} -> {new_status}")
                
                if new_status == "ONLINE":
                    stats["online"] += 1
                elif new_status == "OFFLINE":
                    stats["offline"] += 1
                elif new_status == "WARNING":
                    stats["warning"] += 1
            
            db.commit()
            return stats
            
        except Exception as e:
            logger.error(f"Server status update failed: {e}", exc_info=True)
            db.rollback()
            return {"error": str(e)}
    
    @staticmethod
    async def update_server_statuses_async(db: Session) -> Dict[str, int]:
        """Async wrapper for status update"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, ServerHealthChecker.update_server_statuses, db)
