"""
Servers API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.server import Server
from app.schemas.server import ServerCreate, ServerUpdate, ServerResponse
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller

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
            
            # Node Exporter durumunu ekle (eğer istenirse ve sunucu credential'lı ise)
            # Sadece ONLINE sunucular için kontrol et (OFFLINE sunucular timeout olur)
            if include_node_exporter_status and s.connection_config and s.connection_config.get("username") and s.status == "ONLINE":
                try:
                    import signal
                    import threading
                    
                    # Timeout ile kontrol et (5 saniye)
                    result = {"installed": False, "running": False}
                    timeout_occurred = threading.Event()
                    
                    def check_with_timeout():
                        try:
                            installer = NodeExporterInstaller(s)
                            status = installer.check_status()
                            installer.connector.close()
                            result["installed"] = status.get("installed", False)
                            result["running"] = status.get("running", False)
                        except Exception:
                            pass
                        finally:
                            timeout_occurred.set()
                    
                    thread = threading.Thread(target=check_with_timeout)
                    thread.daemon = True
                    thread.start()
                    thread.join(timeout=5)  # 5 saniye timeout
                    
                    if thread.is_alive():
                        # Timeout oldu, varsayılan değerleri kullan
                        server_data["node_exporter"] = {
                            "installed": False,
                            "running": False
                        }
                    else:
                        server_data["node_exporter"] = result
                except Exception:
                    server_data["node_exporter"] = {
                        "installed": False,
                        "running": False
                    }
            elif include_node_exporter_status:
                # OFFLINE veya credential'sız sunucular için varsayılan değer
                server_data["node_exporter"] = {
                    "installed": False,
                    "running": False
                }
            
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
