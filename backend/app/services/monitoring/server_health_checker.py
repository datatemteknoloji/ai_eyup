"""
Server Health Checker - Sunucu durumlarını otomatik kontrol eder
"""
import asyncio
import logging
import socket
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from app.models.server import Server

logger = logging.getLogger(__name__)


class ServerHealthChecker:
    """Sunucu sağlık durumunu kontrol eden servis"""

    @staticmethod
    def ping_server(ip_address: str, port: int = 22, timeout: int = 2) -> Tuple[bool, str]:
        """TCP bağlantı dener; (başarılı_mı, hata_açıklaması) döner."""
        try:
            with socket.create_connection((ip_address, port), timeout=timeout):
                return True, ""
        except socket.timeout:
            return False, "timeout"
        except ConnectionRefusedError:
            return False, "connection_refused"
        except OSError as e:
            err = "no_route" if getattr(e, "errno", None) in (113, 101, 111) else str(e)
            return False, err
        except Exception as e:
            return False, str(e)[:80]

    @staticmethod
    def check_server_status(server: Server) -> Tuple[str, str]:
        """(status, sebep) döner. Sebep sadece OFFLINE/WARNING için dolu."""
        if not (server.ip_address or "").strip():
            # IP yoksa (hypervisor sync'ten gelmiş, guest tools yok vb.)
            # mevcut durumu koru; her seferinde OFFLINE yazıp log doldurmayalım.
            current = (server.status or "UNKNOWN").upper()
            return current, ""

        port = 22
        try:
            if server.connection_config and isinstance(server.connection_config, dict):
                port = int(server.connection_config.get("port", 22) or 22)
        except Exception:
            port = 22

        is_reachable, ping_reason = ServerHealthChecker.ping_server(server.ip_address, port=port)

        if not is_reachable:
            return "OFFLINE", f"tcp_{port}_ulasilamiyor:{ping_reason}"

        if server.connection_config and server.connection_config.get("username"):
            try:
                from app.services.monitoring.server_connector import ServerConnector
                connector = ServerConnector(server)
                test_result = connector.test_connection()
                connector.close()
                if test_result.get("success"):
                    return "ONLINE", ""
                return "WARNING", "ssh_baglanamadi"
            except Exception as e:
                return "WARNING", f"ssh_hata:{str(e)[:50]}"

        return "ONLINE", ""

    @staticmethod
    def update_server_statuses(db: Session) -> Dict[str, int]:
        """Tüm sunucuların durumlarını kontrol et ve güncelle"""
        try:
            servers = db.query(Server).all()
            stats = {"checked": 0, "updated": 0, "online": 0, "offline": 0, "warning": 0}

            for server in servers:
                stats["checked"] += 1
                old_status = server.status
                new_status, reason = ServerHealthChecker.check_server_status(server)

                if old_status != new_status:
                    server.status = new_status
                    stats["updated"] += 1
                    logger.info(f"Server {server.name} ({server.ip_address}) status: {old_status} -> {new_status}")

                if new_status == "ONLINE":
                    stats["online"] += 1
                elif new_status == "OFFLINE":
                    stats["offline"] += 1
                    logger.warning(f"OFFLINE: {server.name} ({server.ip_address}) sebep: {reason}")
                elif new_status == "WARNING":
                    stats["warning"] += 1
                    logger.warning(f"WARNING: {server.name} ({server.ip_address}) sebep: {reason}")

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
