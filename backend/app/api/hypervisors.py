"""
Hypervisors API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.hypervisor import Hypervisor, HypervisorType
from app.schemas.hypervisor import HypervisorCreate, HypervisorUpdate, HypervisorResponse

router = APIRouter()


class TestConnectionRequest(BaseModel):
    type: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = 443
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/test-connection")
async def test_connection(data: TestConnectionRequest):
    """Arayüzden bağlantı testi (VMware / oVirt-KVM)."""
    host = (data.ip_address or data.hostname or "").strip()
    if not host:
        return {"success": False, "message": "Host (IP veya hostname) gerekli", "details": ""}
    port = data.port or 443
    username = (data.username or "").strip()
    password = data.password or ""
    htype = (data.type or "").lower()

    if htype == "vmware":
        try:
            from app.services.vmware.vcenter_client import VCenterClient
            client = VCenterClient(host=host, username=username, password=password)
            client.login()
            client.logout()
            return {"success": True, "message": "vCenter bağlantısı başarılı", "details": ""}
        except ImportError:
            return {"success": False, "message": "vCenter modülü yüklenemedi", "details": ""}
        except Exception as e:
            return {"success": False, "message": "vCenter bağlantı hatası", "details": str(e)}

    if htype == "kvm":
        try:
            from app.services.ovirt.ovirt_client import OVirtClient
            client = OVirtClient(
                host=host,
                username=username,
                password=password,
                verify_ssl=False,
                port=port,
            )
            ok, detail = client.test_connection()
            if ok:
                return {"success": True, "message": "oVirt bağlantısı başarılı", "details": ""}
            return {"success": False, "message": "oVirt bağlantı hatası", "details": detail or "Yanıt alınamadı"}
        except ImportError as e:
            return {"success": False, "message": "oVirt modülü yüklenemedi", "details": str(e)}
        except Exception as e:
            return {"success": False, "message": "oVirt bağlantı hatası", "details": str(e)}

    return {"success": False, "message": f"Desteklenmeyen tip: {data.type}. vmware veya kvm kullanın.", "details": ""}

@router.get("/", response_model=List[HypervisorResponse])
async def list_hypervisors(db: Session = Depends(get_db)):
    """Hypervisor'ları listele"""
    try:
        hypervisors = db.query(Hypervisor).all()
        return [{
            "id": h.id,
            "name": h.name,
            "type": h.hypervisor_type.value if h.hypervisor_type else None,
            "hostname": h.hostname,
            "ip_address": h.ip_address,
            "port": h.port,
            "username": h.username,
            "connection_config": h.connection_config,
            "created_at": h.created_at,
            "updated_at": h.updated_at
        } for h in hypervisors]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing hypervisors: {str(e)}")

@router.post("/", response_model=HypervisorResponse, status_code=201)
async def create_hypervisor(hypervisor: HypervisorCreate, db: Session = Depends(get_db)):
    """Yeni hypervisor ekle"""
    try:
        # Aynı isimde hypervisor var mı kontrol et
        existing = db.query(Hypervisor).filter(Hypervisor.name == hypervisor.name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Hypervisor with name '{hypervisor.name}' already exists")
        
        # Hypervisor type'ı enum'a çevir
        try:
            hypervisor_type = HypervisorType(hypervisor.type.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid hypervisor type: {hypervisor.type}. Valid types: vmware, hyperv, kvm, xen")
        
        # Connection config'i oluştur
        connection_config = hypervisor.connection_config or {}
        if hypervisor.username and hypervisor.password:
            connection_config.setdefault("username", hypervisor.username)
            connection_config.setdefault("password", hypervisor.password)
        
        # hostname ve ip_address NOT NULL olduğu için default değerler ekle
        hostname = hypervisor.hostname or hypervisor.name
        ip_address = hypervisor.ip_address or ""
        
        # Yeni hypervisor oluştur
        db_hypervisor = Hypervisor(
            name=hypervisor.name,
            hypervisor_type=hypervisor_type,
            hostname=hostname,
            ip_address=ip_address,
            port=hypervisor.port or 443,
            username=hypervisor.username,
            password=hypervisor.password,  # Should be encrypted in production
            connection_config=connection_config
        )
        
        db.add(db_hypervisor)
        db.commit()
        db.refresh(db_hypervisor)
        
        return {
            "id": db_hypervisor.id,
            "name": db_hypervisor.name,
            "type": db_hypervisor.type,
            "hostname": db_hypervisor.hostname,
            "ip_address": db_hypervisor.ip_address,
            "port": db_hypervisor.port,
            "username": db_hypervisor.username,
            "connection_config": db_hypervisor.connection_config,
            "created_at": db_hypervisor.created_at,
            "updated_at": db_hypervisor.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating hypervisor: {str(e)}")

@router.put("/{hypervisor_id}", response_model=HypervisorResponse)
async def update_hypervisor(hypervisor_id: int, hypervisor: HypervisorUpdate, db: Session = Depends(get_db)):
    """Hypervisor güncelle"""
    try:
        db_hypervisor = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
        if not db_hypervisor:
            raise HTTPException(status_code=404, detail="Hypervisor not found")
        
        # Güncellenecek alanları güncelle
        update_data = hypervisor.dict(exclude_unset=True)
        
        # type -> hypervisor_type mapping
        if "type" in update_data:
            try:
                update_data["hypervisor_type"] = HypervisorType(update_data.pop("type").lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid hypervisor type. Valid types: vmware, hyperv, kvm, xen")
        
        for key, value in update_data.items():
            setattr(db_hypervisor, key, value)
        
        db.commit()
        db.refresh(db_hypervisor)
        
        return {
            "id": db_hypervisor.id,
            "name": db_hypervisor.name,
            "type": db_hypervisor.hypervisor_type.value if db_hypervisor.hypervisor_type else None,
            "hostname": db_hypervisor.hostname,
            "ip_address": db_hypervisor.ip_address,
            "port": db_hypervisor.port,
            "username": db_hypervisor.username,
            "connection_config": db_hypervisor.connection_config,
            "created_at": db_hypervisor.created_at,
            "updated_at": db_hypervisor.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating hypervisor: {str(e)}")

@router.post("/{hypervisor_id}/sync-vms")
async def sync_hypervisor_vms(hypervisor_id: int, db: Session = Depends(get_db)):
    """Hypervisor'dan VM'leri senkronize et"""
    from app.models.server import Server
    try:
        hypervisor = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
        if not hypervisor:
            raise HTTPException(status_code=404, detail="Hypervisor not found")

        synced = 0
        errors = []
        vms = []

        htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""
        
        if htype == "vmware":
            try:
                from app.services.vmware.vcenter_client import VCenterClient
                client = VCenterClient(
                    host=hypervisor.ip_address or hypervisor.hostname,
                    username=hypervisor.username or hypervisor.connection_config.get("username", ""),
                    password=hypervisor.password or hypervisor.connection_config.get("password", "")
                )
                client.login()
                vms = client.sync_vms_to_inventory()  # CPU/RAM için detaylı API
                client.logout()
            except ImportError:
                errors.append("VMware client modülü bulunamadı")
            except Exception as e:
                errors.append(f"vCenter bağlantı hatası: {str(e)}")
        elif htype == "kvm":
            try:
                from app.services.ovirt.ovirt_client import OVirtClient
                client = OVirtClient(
                    host=hypervisor.ip_address or hypervisor.hostname,
                    username=hypervisor.username or hypervisor.connection_config.get("username", ""),
                    password=hypervisor.password or hypervisor.connection_config.get("password", "")
                )
                vms = client.list_vms()
            except ImportError:
                errors.append("oVirt client modülü bulunamadı")
            except Exception as e:
                errors.append(f"oVirt bağlantı hatası: {str(e)}")
        else:
            errors.append(f"Desteklenmeyen hypervisor tipi: {htype}")

        def _vm_status(vm: dict) -> str:
            """oVirt/VMware ham durumunu uygulama durumuna çevirir.
            oVirt: status ('up'/'down'), VMware: power_state ('POWERED_ON'/'POWERED_OFF').
            """
            mapping = {
                "up": "ONLINE", "powered_on": "ONLINE", "poweredon": "ONLINE", "running": "ONLINE",
                "down": "OFFLINE", "powered_off": "OFFLINE", "poweredoff": "OFFLINE",
                "stopped": "OFFLINE", "suspended": "OFFLINE",
            }
            raw = (vm.get("status") or vm.get("power_state") or "").lower().replace(" ", "_")
            return mapping.get(raw, "OFFLINE")

        # VM'leri sunuculara ekle/güncelle
        from app.models.credential import GlobalCredential
        
        # Global Credential'ı al (varsa)
        global_cred = db.query(GlobalCredential).first()
        
        for vm in vms:
            vm_name = vm.get("name", "Unknown")
            vm_status = _vm_status(vm)
            existing = db.query(Server).filter(Server.name == vm_name).first()
            if not existing:
                # Yeni sunucu: Global Credential varsa connection_config'e koy
                conn_cfg = {}
                if global_cred:
                    conn_cfg = {
                        "username": global_cred.username,
                        "password": global_cred.password,
                        "private_key": global_cred.private_key,
                        "port": global_cred.port or 22,
                        "sudo_password": global_cred.sudo_password
                    }
                
                # ai_ready: SADECE IP adresi varsa ve SSH başarılıysa true
                # Hypervisor sync sırasında SSH test yapmıyoruz, sadece IP kontrolü
                ai_ready_status = False  # Varsayılan: false
                if vm.get("ip_address") and vm.get("ip_address").strip():
                    # IP var, credential uygula/SSH test yap seçeneği kullanıcıya bırakılır
                    ai_ready_status = False  # Kullanıcı "Apply Credential" ile test edecek
                
                new_server = Server(
                    name=vm_name,
                    hostname=vm_name,
                    ip_address=vm.get("ip_address", ""),
                    status=vm_status,
                    os_type=vm.get("os_type", ""),
                    server_type="VIRTUAL",
                    cpu_cores=vm.get("cpu_cores", 0),
                    memory_gb=vm.get("memory_gb", 0),
                    connection_config=conn_cfg,
                    ai_ready=ai_ready_status
                )
                db.add(new_server)
                synced += 1
            else:
                # Mevcut sunucuyu güncelle - connection_config ve ai_ready değerlerini KORU
                existing.status = vm_status          # hypervisor'ın gerçek durumu
                if vm.get("ip_address"):
                    existing.ip_address = vm["ip_address"]
                # CPU/RAM: VM'den gelen değeri yaz (0 bile olsa; 0 = bilinmeyen/ayarlanmamış)
                if "cpu_cores" in vm:
                    existing.cpu_cores = vm["cpu_cores"]
                if "memory_gb" in vm:
                    existing.memory_gb = vm["memory_gb"]
                if vm.get("os_type"):
                    existing.os_type = vm["os_type"]
                # ÖNEMLI: connection_config ve ai_ready'ye DOKUNMA!

        db.commit()

        return {
            "success": len(errors) == 0,
            "hypervisor": hypervisor.name,
            "synced_count": synced,
            "total_vms": len(vms),
            "errors": errors
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Sync error: {str(e)}")


@router.get("/{hypervisor_id}/host-metrics")
async def get_host_metrics(
    hypervisor_id: int,
    host_name: Optional[str] = None,
    hours: int = 24,
    db: Session = Depends(get_db),
):
    """
    ESX host kaynak metriklerini döner.
    - host_name verilmezse tüm host'ların son kaydı döner (özet)
    - host_name verilirse o host'un son `hours` saatlik geçmişi döner
    """
    from app.models.hypervisor_metric import HypervisorHostMetric
    from sqlalchemy import func as sa_func
    from datetime import datetime, timezone, timedelta

    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        raise HTTPException(status_code=404, detail="Hypervisor bulunamadı")

    if host_name:
        # Belirli bir host'un zaman serisi
        since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 720)))
        rows = (
            db.query(HypervisorHostMetric)
            .filter(
                HypervisorHostMetric.hypervisor_id == hypervisor_id,
                HypervisorHostMetric.host_name == host_name,
                HypervisorHostMetric.timestamp >= since,
            )
            .order_by(HypervisorHostMetric.timestamp.asc())
            .all()
        )
        return {
            "hypervisor_id": hypervisor_id,
            "host_name": host_name,
            "hours": hours,
            "count": len(rows),
            "metrics": [
                {
                    "timestamp":        r.timestamp.isoformat(),
                    "cpu_usage_pct":    r.cpu_usage_pct,
                    "cpu_usage_mhz":    r.cpu_usage_mhz,
                    "cpu_total_mhz":    r.cpu_total_mhz,
                    "cpu_cores":        r.cpu_cores,
                    "mem_used_mb":      r.mem_used_mb,
                    "mem_total_mb":     r.mem_total_mb,
                    "mem_usage_pct":    r.mem_usage_pct,
                    "ds_used_gb":       r.ds_used_gb,
                    "ds_total_gb":      r.ds_total_gb,
                    "ds_usage_pct":     r.ds_usage_pct,
                    "net_rx_kbps":      r.net_rx_kbps,
                    "net_tx_kbps":      r.net_tx_kbps,
                    "vms_running":      r.vms_running,
                    "vms_total":        r.vms_total,
                    "connection_state": r.connection_state,
                    "power_state":      r.power_state,
                    "maintenance_mode": r.maintenance_mode,
                }
                for r in rows
            ],
        }
    else:
        # Tüm host'ların son kaydı (özet / anlık tablo)
        subq = (
            db.query(
                HypervisorHostMetric.host_name,
                sa_func.max(HypervisorHostMetric.timestamp).label("last_ts"),
            )
            .filter(HypervisorHostMetric.hypervisor_id == hypervisor_id)
            .group_by(HypervisorHostMetric.host_name)
            .subquery()
        )
        rows = (
            db.query(HypervisorHostMetric)
            .join(
                subq,
                (HypervisorHostMetric.host_name == subq.c.host_name)
                & (HypervisorHostMetric.timestamp == subq.c.last_ts),
            )
            .filter(HypervisorHostMetric.hypervisor_id == hypervisor_id)
            .order_by(HypervisorHostMetric.host_name)
            .all()
        )
        return {
            "hypervisor_id":   hypervisor_id,
            "hypervisor_name": hv.name,
            "host_count":      len(rows),
            "hosts": [
                {
                    "host_name":        r.host_name,
                    "host_ref":         r.host_ref,
                    "last_updated":     r.timestamp.isoformat(),
                    "cpu_usage_pct":    r.cpu_usage_pct,
                    "cpu_usage_mhz":    r.cpu_usage_mhz,
                    "cpu_total_mhz":    r.cpu_total_mhz,
                    "cpu_cores":        r.cpu_cores,
                    "mem_used_mb":      r.mem_used_mb,
                    "mem_total_mb":     r.mem_total_mb,
                    "mem_usage_pct":    r.mem_usage_pct,
                    "ds_used_gb":       r.ds_used_gb,
                    "ds_total_gb":      r.ds_total_gb,
                    "ds_usage_pct":     r.ds_usage_pct,
                    "vms_running":      r.vms_running,
                    "vms_total":        r.vms_total,
                    "connection_state": r.connection_state,
                    "power_state":      r.power_state,
                    "maintenance_mode": r.maintenance_mode,
                }
                for r in rows
            ],
        }


@router.post("/{hypervisor_id}/host-metrics/sync")
async def trigger_esx_metric_sync(hypervisor_id: int, db: Session = Depends(get_db)):
    """
    Manuel tetikleme: belirli hypervisor için ESX metrik sync yap.
    (15 dk'yı beklemeden anlık çekmek için)
    """
    import asyncio
    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        raise HTTPException(status_code=404, detail="Hypervisor bulunamadı")
    if hv.hypervisor_type != HypervisorType.VMWARE:
        raise HTTPException(status_code=400, detail="Sadece VMware hypervisor'lar destekleniyor")

    try:
        from app.services.esx_metric_sync import sync_esx_metrics
        # Tek hypervisor için çalıştır (DB'den yalnızca bu ID ile filtrele)
        # sync_esx_metrics tüm VMware'leri çalıştırır; ayrı bir db session açıyoruz
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, sync_esx_metrics, db)
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{hypervisor_id}", status_code=204)
async def delete_hypervisor(hypervisor_id: int, db: Session = Depends(get_db)):
    """Hypervisor sil"""
    try:
        db_hypervisor = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
        if not db_hypervisor:
            raise HTTPException(status_code=404, detail="Hypervisor not found")
        
        db.delete(db_hypervisor)
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting hypervisor: {str(e)}")
