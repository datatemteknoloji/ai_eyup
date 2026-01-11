"""
Monitoring API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.models.server import Server
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller
from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/node-exporter/install/{server_id}")
async def install_node_exporter(server_id: int, db: Session = Depends(get_db)):
    """AI ready sunucuya Node Exporter kur ve Prometheus'a ekle"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if not server.ai_ready:
        raise HTTPException(status_code=400, detail="Server must be AI ready to install Node Exporter")
    
    if not server.connection_config or not server.connection_config.get("username"):
        raise HTTPException(status_code=400, detail="Server must have SSH credentials to install Node Exporter")
    
    try:
        installer = NodeExporterInstaller(server)
        result = installer.install()
        
        # Kurulum başarılıysa Prometheus'a target ekle
        if result.get("success"):
            instance = f"{server.ip_address}:9100"
            target_manager = PrometheusTargetManager()
            added = target_manager.add_target(
                instance=instance,
                labels={
                    "server_id": str(server.id),
                    "server_name": server.name,
                    "job": "node-exporter"
                }
            )
            
            if added:
                result["prometheus_target_added"] = True
                result["prometheus_instance"] = instance
            else:
                result["prometheus_target_warning"] = "Target eklenemedi, manuel olarak eklenmeli"
            
            # Async reload (opsiyonel) - fallback to sync
            try:
                await target_manager.reload_prometheus_async()
            except:
                try:
                    target_manager.reload_prometheus_sync()
                except:
                    pass
        
        # Bağlantıyı kapat
        installer.connector.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Node Exporter kurulum hatası (Server ID: {server_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kurulum hatası: {str(e)}")

@router.post("/node-exporter/uninstall/{server_id}")
async def uninstall_node_exporter(server_id: int, db: Session = Depends(get_db)):
    """Sunucudan Node Exporter kaldır ve Prometheus'tan çıkar"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if not server.connection_config or not server.connection_config.get("username"):
        raise HTTPException(status_code=400, detail="Server must have SSH credentials to uninstall Node Exporter")
    
    try:
        installer = NodeExporterInstaller(server)
        result = installer.uninstall()
        
        # Prometheus'tan target kaldır
        if result.get("success"):
            instance = f"{server.ip_address}:9100"
            target_manager = PrometheusTargetManager()
            removed = target_manager.remove_target(instance=instance)
            
            if removed:
                result["prometheus_target_removed"] = True
            
            # Async reload - fallback to sync
            try:
                await target_manager.reload_prometheus_async()
            except:
                try:
                    target_manager.reload_prometheus_sync()
                except:
                    pass
        
        # Bağlantıyı kapat
        installer.connector.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Node Exporter kaldırma hatası (Server ID: {server_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kaldırma hatası: {str(e)}")

@router.get("/node-exporter/download/{arch}")
async def download_node_exporter_binary(arch: str):
    """Node Exporter binary'sini backend sunucusundan indir"""
    from fastapi.responses import FileResponse
    from pathlib import Path
    from app.core.config import settings
    
    try:
        # Binary dosya yolu
        storage_path = Path(settings.NODE_EXPORTER_STORAGE_PATH)
        arch_dir = storage_path / arch
        binary_file = arch_dir / "node_exporter"
        
        # Binary var mı kontrol et
        if not binary_file.exists():
            # Genel binary'yi dene
            general_binary = storage_path / "node_exporter"
            if general_binary.exists():
                binary_file = general_binary
            else:
                raise HTTPException(status_code=404, detail=f"Node Exporter binary bulunamadı (arch: {arch})")
        
        # Binary'yi servis et
        return FileResponse(
            path=str(binary_file.absolute()),
            filename=f"node_exporter-{arch}",
            media_type="application/octet-stream"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Binary download hatası (arch: {arch}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Binary indirme hatası: {str(e)}")

@router.get("/node-exporter/list-ai-ready")
async def list_ai_ready_servers(db: Session = Depends(get_db)):
    """AI Ready ve credential'lı sunucuları listele"""
    try:
        servers = db.query(Server).filter(
            Server.ai_ready == True,
            Server.connection_config.isnot(None)
        ).all()
        
        result = []
        for server in servers:
            conn_config = server.connection_config or {}
            username = conn_config.get("username", "")
            
            if username and server.ip_address:
                # Node Exporter durumunu kontrol et
                status_info = {"installed": False, "running": False}
                try:
                    installer = NodeExporterInstaller(server)
                    status_info = installer.check_status()
                    installer.connector.close()
                except:
                    pass
                
                result.append({
                    "id": server.id,
                    "name": server.name,
                    "ip_address": server.ip_address,
                    "hostname": server.hostname,
                    "os_type": server.os_type,
                    "username": username,
                    "port": conn_config.get("port", 22),
                    "node_exporter": {
                        "installed": status_info.get("installed", False),
                        "running": status_info.get("running", False)
                    }
                })
        
        return {
            "total": len(result),
            "servers": result
        }
        
    except Exception as e:
        logger.error(f"AI Ready sunucular listesi hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Liste hatası: {str(e)}")

@router.get("/node-exporter/status/{server_id}")
async def check_node_exporter_status(server_id: int, db: Session = Depends(get_db)):
    """Node Exporter durumunu kontrol et"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if not server.connection_config or not server.connection_config.get("username"):
        raise HTTPException(status_code=400, detail="Server must have SSH credentials to check Node Exporter status")
    
    try:
        installer = NodeExporterInstaller(server)
        result = installer.check_status()
        
        # Bağlantıyı kapat
        installer.connector.close()
        
        return {
            "server_id": server_id,
            "server_name": server.name,
            "server_ip": server.ip_address,
            **result
        }
        
    except Exception as e:
        logger.error(f"Node Exporter durum kontrolü hatası (Server ID: {server_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Durum kontrolü hatası: {str(e)}")
