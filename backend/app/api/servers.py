"""
Servers API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.server import Server
from app.models.credential import GlobalCredential
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
        conn_config = None
        for s in servers:
            conn_config = getattr(s, "connection_config", None) or {}
            server_data = {
                "id": s.id,
                "name": s.name or "",
                "hostname": s.hostname or "",
                "ip_address": s.ip_address or "",
                "status": s.status or "UNKNOWN",
                "os_type": s.os_type or "",
                "os_version": s.os_version or "",
                "server_type": s.server_type or "VIRTUAL",
                "cpu_cores": s.cpu_cores or 0,
                "memory_gb": s.memory_gb or 0,
                "ai_ready": bool(s.ai_ready),
                "connection_config": conn_config,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None
            }
            
            # Node Exporter durumunu ekle (ONLINE sunucular: SSH varsa SSH, yoksa/hatada Prometheus)
            if include_node_exporter_status:
                if s.status == "ONLINE":
                    if conn_config and conn_config.get("username"):
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
            
            # Node Exporter: gerçek zamanlı istenmediyse DB cache kullan
            if not include_node_exporter_status:
                server_data["node_exporter"] = {
                    "installed": bool(getattr(s, "node_exporter_installed", False) or False),
                    "running": bool(getattr(s, "node_exporter_running", False) or False)
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
        
        # IP adresi zorunlu
        if not server.ip_address or not server.ip_address.strip():
            raise HTTPException(status_code=400, detail="IP adresi zorunludur")
        
        # hostname ve ip_address NOT NULL olduğu için default değerler ekle
        hostname = server.hostname or server.name
        ip_address = server.ip_address.strip()
        
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
        
        # Global credential uygula (sunucunun kendi config'i yoksa)
        if not db_server.connection_config.get("username"):
            global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
            if not global_cred:
                global_cred = db.query(GlobalCredential).first()
            if global_cred:
                db_server.connection_config = {
                    "username": global_cred.username,
                    "password": global_cred.password,
                    "private_key": global_cred.private_key,
                    "sudo_password": global_cred.sudo_password or global_cred.password,
                    "port": global_cred.port or 22,
                }
                db_server.ai_ready = True
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(db_server, "connection_config")
                db.commit()
                db.refresh(db_server)
        
        # SSH ile baglantı test et ve sunucu bilgilerini guncelle
        if db_server.connection_config.get("username") and db_server.ip_address:
            try:
                from app.services.ssh_manager import SSHManager
                ssh = SSHManager(
                    host=db_server.ip_address,
                    username=db_server.connection_config.get("username"),
                    password=db_server.connection_config.get("password"),
                    private_key=db_server.connection_config.get("private_key"),
                    port=db_server.connection_config.get("port", 22),
                )
                if ssh.connect():
                    db_server.status = "ONLINE"
                    # OS bilgisini al
                    _, os_out, _ = ssh.execute_command(
                        "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d \'\""
                    )
                    if os_out.strip():
                        db_server.os_version = os_out.strip()
                    # Kernel
                    _, kernel_out, _ = ssh.execute_command("uname -r")
                    if kernel_out.strip():
                        db_server.os_type = db_server.os_type or "linux"
                    # CPU & RAM
                    _, cpu_out, _ = ssh.execute_command("nproc")
                    if cpu_out.strip().isdigit():
                        db_server.cpu_cores = int(cpu_out.strip())
                    _, mem_out, _ = ssh.execute_command(
                        "free -g 2>/dev/null | awk '/^Mem:/{print $2}'"
                    )
                    if mem_out.strip().isdigit():
                        db_server.memory_gb = int(mem_out.strip())
                    ssh.close()
                else:
                    db_server.status = "OFFLINE"
                db.commit()
                db.refresh(db_server)
            except Exception as ssh_err:
                logger.warning(f"SSH connect failed for new server {db_server.name}: {ssh_err}")
        
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
    """Tüm sunucuların durumlarını kontrol et ve güncelle (TCP port + SSH)"""
    try:
        stats = await ServerHealthChecker.update_server_statuses_async(db)
        msg = "Sunucu durumları güncellendi"
        if stats.get("offline", 0) == stats.get("checked", 0) and stats.get("checked", 0) > 0:
            msg += ". Hiç ONLINE yok; backend loglarında 'OFFLINE: ... sebep:' satırlarına bakın (docker logs server_management_backend)."
        return {
            "success": True,
            "message": msg,
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
        new_status, _ = ServerHealthChecker.check_server_status(server)
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


# In-memory cache for vCenter metrics (avoids 3s SOAP calls on every refetch)
_vcenter_cache: dict = {}  # server_id -> (result_dict, expires_at)

@router.get("/{server_id}/metrics-summary")
async def get_server_metrics_summary(server_id: int, db: Session = Depends(get_db)):
    """Prometheus/Node Exporter verisini doner. Veri yoksa ve sunucu VIRTUAL ise vCenter'dan alir."""
    from app.models.hypervisor import Hypervisor, HypervisorType
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    from app.services.monitoring.prometheus_metrics import PrometheusMetricsService
    svc = PrometheusMetricsService()
    ip = server.ip_address

    async def _q(query: str):
        try:
            res = await svc.query_metric(query)
            if res and res.get("status") == "success":
                results = res["data"]["result"]
                if results:
                    return float(results[0]["value"][1])
        except Exception:
            pass
        return None

    ifilter = f'instance=~"{ip}:.*"'
    cpu   = await _q(f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle",{ifilter}}}[5m])) * 100)')
    mem   = await _q(f'(1 - node_memory_MemAvailable_bytes{{{ifilter}}} / node_memory_MemTotal_bytes{{{ifilter}}}) * 100')
    disk  = await _q(f'(1 - node_filesystem_avail_bytes{{mountpoint="/",{ifilter}}} / node_filesystem_size_bytes{{mountpoint="/",{ifilter}}}) * 100')
    load1 = await _q(f'node_load1{{{ifilter}}}')
    load5 = await _q(f'node_load5{{{ifilter}}}')
    uptime_s = await _q(f'node_time_seconds{{{ifilter}}} - node_boot_time_seconds{{{ifilter}}}')
    mem_total = await _q(f'node_memory_MemTotal_bytes{{{ifilter}}}')
    mem_avail = await _q(f'node_memory_MemAvailable_bytes{{{ifilter}}}')
    disk_total = await _q(f'node_filesystem_size_bytes{{mountpoint="/",{ifilter}}}')
    disk_avail = await _q(f'node_filesystem_avail_bytes{{mountpoint="/",{ifilter}}}')

    has_prom = cpu is not None

    # ── vCenter fallback: sanal sunucu, Prometheus verisi yok ──────────────
    vcenter_stats: dict = {}
    if not has_prom and server.server_type == "VIRTUAL":
        import asyncio, time as _time
        # 60 saniye cache: vCenter SOAP 3s sürüyor, her 15s refetch'te çağrılmasin
        cached = _vcenter_cache.get(server_id)
        if cached and cached[1] > _time.time():
            vcenter_stats = cached[0]
        else:
            hypervisors = db.query(Hypervisor).filter(
                Hypervisor.hypervisor_type == HypervisorType.VMWARE
            ).all()
            for hyp in hypervisors:
                vc_pass = hyp.password or (hyp.connection_config or {}).get("password", "")
                if not (hyp.hostname and hyp.username and vc_pass):
                    continue
                try:
                    from app.services.vmware.vcenter_client import VCenterClient
                    vc = VCenterClient(host=hyp.hostname, username=hyp.username, password=vc_pass)
                    if not vc.login():
                        continue
                    _srv_name, _srv_ip = server.name, ip or ""
                    vm_id = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: vc.find_vm_by_name_or_ip(name=_srv_name, ip=_srv_ip)
                    )
                    if vm_id:
                        _vm_id = vm_id
                        stats = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: vc.get_vm_quick_stats(_vm_id)
                        )
                        if stats:
                            vcenter_stats = stats
                    vc.logout()
                    if vcenter_stats:
                        break
                except Exception as e:
                    logger.warning(f"vCenter metrics fallback error: {e}")
            if vcenter_stats:
                _vcenter_cache[server_id] = (vcenter_stats, _time.time() + 60)

    if vcenter_stats:
        mtmb = vcenter_stats.get("mem_total_mb") or 0
        mumb = vcenter_stats.get("mem_used_mb") or 0
        return {
            "server_id": server_id,
            "has_node_exporter": False,
            "source": "vcenter",
            "power_state": vcenter_stats.get("power_state"),
            "cpu_percent": vcenter_stats.get("cpu_percent"),
            "mem_percent": vcenter_stats.get("mem_percent"),
            "disk_percent": None,
            "load1": None,
            "load5": None,
            "uptime_seconds": vcenter_stats.get("uptime_seconds"),
            "mem_total_gb": round(mtmb / 1024, 1) if mtmb else None,
            "mem_used_gb":  round(mumb / 1024, 1) if mumb else None,
            "disk_total_gb": None,
            "disk_avail_gb": None,
            "cpu_num": vcenter_stats.get("num_cpu"),
        }

    return {
        "server_id": server_id,
        "has_node_exporter": has_prom,
        "source": "prometheus" if has_prom else None,
        "cpu_percent": round(cpu, 1) if cpu is not None else None,
        "mem_percent": round(mem, 1) if mem is not None else None,
        "disk_percent": round(disk, 1) if disk is not None else None,
        "load1": round(load1, 2) if load1 is not None else None,
        "load5": round(load5, 2) if load5 is not None else None,
        "uptime_seconds": int(uptime_s) if uptime_s is not None else None,
        "mem_total_gb": round(mem_total / 1073741824, 1) if mem_total else None,
        "mem_used_gb": round((mem_total - mem_avail) / 1073741824, 1) if mem_total and mem_avail else None,
        "disk_total_gb": round(disk_total / 1073741824, 1) if disk_total else None,
        "disk_avail_gb": round(disk_avail / 1073741824, 1) if disk_avail else None,
    }
