"""
Servers API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.server import Server
from app.schemas.server import ServerCreate, ServerUpdate, ServerResponse
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller
from app.services.monitoring.prometheus_metrics import node_exporter_up_for_server
from app.services.monitoring.server_health_checker import ServerHealthChecker

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/")
async def list_servers(db: Session = Depends(get_db), include_node_exporter_status: bool = False):
    """Tüm sunucuları listele"""
    try:
        servers = db.query(Server).all()
        result = []
        for s in servers:
            server_data = {
                "id": s.id,
                "name": s.name,
                "hostname": s.hostname,
                "ip_address": s.ip_address,
                "status": s.status,
                "os_type": s.os_type,
                "os_version": s.os_version,
                "server_type": s.server_type,
                "cpu_cores": s.cpu_cores,
                "memory_gb": s.memory_gb,
                "ai_ready": s.ai_ready,
                "connection_config": s.connection_config,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            }
            
            # Node Exporter durumunu ekle (ONLINE sunucular: SSH varsa SSH, yoksa/hatada Prometheus)
            if include_node_exporter_status:
                if s.status == "ONLINE":
                    if s.connection_config and s.connection_config.get("username"):
                        try:
                            installer = NodeExporterInstaller(s)
                            node_exporter_status = installer.check_status()
                            installer.connector.close()
                            server_data["node_exporter"] = {
                                "installed": node_exporter_status.get("installed", False),
                                "running": node_exporter_status.get("running", False)
                            }
                        except Exception:
                            server_data["node_exporter"] = {"installed": False, "running": False}
                        # SSH sonucu kurulu/çalışır göstermiyorsa Prometheus fallback
                        if not server_data["node_exporter"]["installed"]:
                            if node_exporter_up_for_server(s.ip_address, s.hostname):
                                server_data["node_exporter"] = {"installed": True, "running": True}
                    else:
                        # Credential yok ama ONLINE: sadece Prometheus'tan bak (sunucuda node_exporter çalışıyor olabilir)
                        if s.ip_address or s.hostname:
                            up = node_exporter_up_for_server(s.ip_address, s.hostname)
                            server_data["node_exporter"] = {"installed": up, "running": up}
                        else:
                            server_data["node_exporter"] = {"installed": False, "running": False}
                else:
                    server_data["node_exporter"] = {"installed": False, "running": False}
            
            result.append(server_data)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing servers: {str(e)}")

@router.get("/ai-ready/list")
async def list_ai_ready_servers(db: Session = Depends(get_db)):
    """AI ready sunucuları listele"""
    try:
        servers = db.query(Server).filter(Server.ai_ready == True).all()
        return [{
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "status": s.status,
            "os_type": s.os_type,
            "os_version": s.os_version,
            "server_type": s.server_type,
            "cpu_cores": s.cpu_cores,
            "memory_gb": s.memory_gb,
            "ai_ready": s.ai_ready,
            "connection_config": s.connection_config,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        } for s in servers]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing AI ready servers: {str(e)}")

@router.post("/", response_model=ServerResponse, status_code=201)
async def create_server(server: ServerCreate, db: Session = Depends(get_db)):
    """Yeni sunucu ekle"""
    try:
        # Aynı isimde sunucu var mı kontrol et
        existing = db.query(Server).filter(Server.name == server.name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Server with name '{server.name}' already exists")
        
        # Yeni sunucu oluştur
        # Status için geçerli değerler: ONLINE, OFFLINE, WARNING, CRITICAL
        status = server.status or "OFFLINE"
        if status.upper() not in ["ONLINE", "OFFLINE", "WARNING", "CRITICAL"]:
            status = "OFFLINE"
        
        # hostname ve ip_address NOT NULL olduğu için default değerler ekle
        hostname = server.hostname or server.name
        ip_address = server.ip_address or ""
        
        # server_type NOT NULL olduğu için default değer ekle
        server_type = server.server_type or "VIRTUAL"
        
        db_server = Server(
            name=server.name,
            hostname=hostname,
            ip_address=ip_address,
            status=status.upper(),
            os_type=server.os_type,
            os_version=server.os_version,
            server_type=server_type,
            cpu_cores=server.cpu_cores or 0,
            memory_gb=server.memory_gb or 0,
            ai_ready=server.ai_ready or False,
            connection_config=server.connection_config or {}
        )
        
        db.add(db_server)
        db.commit()
        db.refresh(db_server)
        
        return {
            "id": db_server.id,
            "name": db_server.name,
            "hostname": db_server.hostname,
            "ip_address": db_server.ip_address,
            "status": db_server.status,
            "os_type": db_server.os_type,
            "os_version": db_server.os_version,
            "server_type": db_server.server_type,
            "cpu_cores": db_server.cpu_cores,
            "memory_gb": db_server.memory_gb,
            "ai_ready": db_server.ai_ready,
            "connection_config": db_server.connection_config,
            "created_at": db_server.created_at,
            "updated_at": db_server.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating server: {str(e)}")

@router.put("/{server_id}", response_model=ServerResponse)
async def update_server(server_id: int, server: ServerUpdate, db: Session = Depends(get_db)):
    """Sunucu güncelle"""
    try:
        db_server = db.query(Server).filter(Server.id == server_id).first()
        if not db_server:
            raise HTTPException(status_code=404, detail="Server not found")
        
        # Güncellenecek alanları güncelle
        update_data = server.dict(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_server, key, value)
        
        db.commit()
        db.refresh(db_server)
        
        return {
            "id": db_server.id,
            "name": db_server.name,
            "hostname": db_server.hostname,
            "ip_address": db_server.ip_address,
            "status": db_server.status,
            "os_type": db_server.os_type,
            "os_version": db_server.os_version,
            "server_type": db_server.server_type,
            "cpu_cores": db_server.cpu_cores,
            "memory_gb": db_server.memory_gb,
            "ai_ready": db_server.ai_ready,
            "connection_config": db_server.connection_config,
            "created_at": db_server.created_at,
            "updated_at": db_server.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating server: {str(e)}")

@router.delete("/{server_id}", status_code=204)
async def delete_server(server_id: int, db: Session = Depends(get_db)):
    """Sunucu sil"""
    try:
        db_server = db.query(Server).filter(Server.id == server_id).first()
        if not db_server:
            raise HTTPException(status_code=404, detail="Server not found")
        
        db.delete(db_server)
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting server: {str(e)}")

@router.post("/{server_id}/credentials")
async def update_server_credentials(server_id: int, credentials: dict, db: Session = Depends(get_db)):
    """Sunucu SSH credential'larını güncelle"""
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")

        if not server.connection_config:
            server.connection_config = {}

        for field in ["username", "password", "private_key", "sudo_password", "port"]:
            if field in credentials and credentials[field]:
                server.connection_config[field] = credentials[field]

        if "ai_ready" in credentials:
            server.ai_ready = credentials["ai_ready"]
        elif server.connection_config.get("username"):
            server.ai_ready = True

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(server, "connection_config")
        db.commit()
        db.refresh(server)

        return {
            "success": True,
            "server_id": server.id,
            "ai_ready": server.ai_ready,
            "has_credentials": bool(server.connection_config.get("username"))
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-health")
async def check_all_servers_health(db: Session = Depends(get_db)):
    """Tüm sunucuların durumlarını kontrol et ve güncelle (ping + SSH)"""
    try:
        stats = await ServerHealthChecker.update_server_statuses_async(db)
        return {
            "success": True,
            "message": "Sunucu durumları güncellendi",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Health check error: {str(e)}")

@router.post("/{server_id}/check-health")
async def check_server_health(server_id: int, db: Session = Depends(get_db)):
    """Tek bir sunucunun durumunu kontrol et ve güncelle"""
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        
        old_status = server.status
        new_status = ServerHealthChecker.check_server_status(server)
        server.status = new_status
        db.commit()
        
        return {
            "success": True,
            "server_id": server_id,
            "server_name": server.name,
            "old_status": old_status,
            "new_status": new_status,
            "changed": old_status != new_status
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Health check failed for server {server_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Health check error: {str(e)}")
