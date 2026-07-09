"""
Hypervisors API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.inventory_guard import require_integrations_inventory
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.services.hypervisor_cleanup import delete_servers_cascade
from app.schemas.hypervisor import HypervisorCreate, HypervisorUpdate, HypervisorResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _mask_hv_config(cfg: dict | None) -> dict:
    """Hypervisor connection_config'den şifreleri kaldırır."""
    if not cfg:
        return {}
    return {
        "username":        cfg.get("username") or "",
        "port":            cfg.get("port") or 443,
        "has_password":    bool(cfg.get("password")),
    }


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
            client = VCenterClient(host=host, username=username, password=password, port=port or 443)
            ok = client.login()
            if not ok:
                return {
                    "success": False,
                    "message": "vCenter bağlantı hatası",
                    "details": "Giriş başarısız — host, port, kullanıcı adı veya şifreyi kontrol edin.",
                }
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

    if htype in ("proxmox",):
        try:
            from app.services.hypervisor.proxmox_client import ProxmoxClient
            client = ProxmoxClient(
                host=host, username=username, password=password, port=port or 8006, verify_ssl=False,
            )
            result = client.test_connection()
            if result["connected"]:
                return {"success": True, "message": result["message"], "details": result.get("version", "")}
            return {"success": False, "message": result["message"], "details": ""}
        except Exception as exc:
            return {"success": False, "message": "Proxmox bağlantı hatası", "details": str(exc)}

    if htype in ("hyperv",):
        try:
            from app.services.windows.winrm_client import WinRMClient
            from app.services.hypervisor.hyperv_client import HyperVClient
            winrm = WinRMClient(host=host, username=username, password=password, port=port or 5985)
            client = HyperVClient(winrm)
            result = client.test_connection()
            if result["connected"]:
                return {"success": True, "message": result["message"], "details": ""}
            return {"success": False, "message": result["message"], "details": ""}
        except Exception as exc:
            return {"success": False, "message": "Hyper-V bağlantı hatası", "details": str(exc)}

    return {"success": False, "message": f"Desteklenmeyen tip: {data.type}. vmware, kvm, proxmox veya hyperv kullanın.", "details": ""}

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
            "connection_config": _mask_hv_config(h.connection_config),
            "created_at": h.created_at,
            "updated_at": h.updated_at
        } for h in hypervisors]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing hypervisors: {str(e)}")

@router.post("/", response_model=HypervisorResponse, status_code=201)
async def create_hypervisor(hypervisor: HypervisorCreate, request: Request, db: Session = Depends(get_db)):
    """Yeni hypervisor ekle (yalnızca Entegrasyonlar)"""
    require_integrations_inventory(request)
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
            "connection_config": _mask_hv_config(db_hypervisor.connection_config),
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
            "connection_config": _mask_hv_config(db_hypervisor.connection_config),
            "created_at": db_hypervisor.created_at,
            "updated_at": db_hypervisor.updated_at
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating hypervisor: {str(e)}")

@router.post("/sync-all-vms")
async def sync_all_hypervisor_vms(request: Request, db: Session = Depends(get_db)):
    """Tüm hypervisor'lardan VM'leri tek seferde senkronize et (manuel — Entegrasyonlar)."""
    require_integrations_inventory(request)
    try:
        from app.services.inventory_sync_service import sync_all_hypervisors
        result = sync_all_hypervisors(db)
        from app.services import qa_cache
        qa_cache.invalidate_all()
        return result
    except Exception as e:
        db.rollback()
        logger.exception("sync_all_hypervisor_vms failed")
        raise HTTPException(status_code=500, detail=f"Senkronizasyon hatası: {str(e)}")


@router.post("/{hypervisor_id}/sync-vms")
async def sync_hypervisor_vms(hypervisor_id: int, request: Request, db: Session = Depends(get_db)):
    """Hypervisor'dan VM'leri senkronize et (yalnızca Entegrasyonlar)"""
    require_integrations_inventory(request)
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
                if not client.login():
                    errors.append("vCenter bağlantı hatası: giriş başarısız (host/kullanıcı/şifre kontrol edin)")
                else:
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
                    password=hypervisor.password or hypervisor.connection_config.get("password", ""),
                    port=hypervisor.port,
                    verify_ssl=False,
                )
                vms = client.list_vms()
            except ImportError:
                errors.append("oVirt client modülü bulunamadı")
            except Exception as e:
                errors.append(f"oVirt bağlantı hatası: {str(e)}")
        elif htype == "proxmox":
            try:
                from app.services.hypervisor.proxmox_client import ProxmoxClient
                client = ProxmoxClient(
                    host=hypervisor.ip_address or hypervisor.hostname,
                    username=hypervisor.username or hypervisor.connection_config.get("username", ""),
                    password=hypervisor.password or hypervisor.connection_config.get("password", ""),
                    port=hypervisor.port or 8006,
                    verify_ssl=False,
                )
                vms = client.list_vms()
            except Exception as e:
                errors.append(f"Proxmox bağlantı hatası: {str(e)}")
        elif htype == "hyperv":
            try:
                from app.services.windows.winrm_client import WinRMClient
                from app.services.hypervisor.hyperv_client import HyperVClient
                winrm = WinRMClient(
                    host=hypervisor.ip_address or hypervisor.hostname,
                    username=hypervisor.username or hypervisor.connection_config.get("username", ""),
                    password=hypervisor.password or hypervisor.connection_config.get("password", ""),
                    port=hypervisor.port or 5985,
                )
                hv_client = HyperVClient(winrm)
                vms = hv_client.list_vms()
            except Exception as e:
                errors.append(f"Hyper-V bağlantı hatası: {str(e)}")
        else:
            errors.append(f"Desteklenmeyen hypervisor tipi: {htype}")

        def _vm_status(vm: dict) -> str:
            """oVirt/VMware ham durumunu uygulama durumuna çevirir."""
            mapping = {
                # oVirt raw
                "up": "ONLINE", "powering_up": "ONLINE",
                "down": "OFFLINE", "not_responding": "OFFLINE",
                "suspended": "OFFLINE", "stopped": "OFFLINE",
                # VMware raw
                "powered_on": "ONLINE", "poweredon": "ONLINE", "running": "ONLINE",
                "powered_off": "OFFLINE", "poweredoff": "OFFLINE",
                # zaten dönüştürülmüş (list_vms içinde map edilmiş)
                "online": "ONLINE", "offline": "OFFLINE",
            }
            raw = (vm.get("status") or vm.get("power_state") or "").lower().replace(" ", "_").replace("-", "_")
            return mapping.get(raw, "UNKNOWN")

        # VM'leri sunuculara ekle/güncelle
        from app.models.credential import GlobalCredential
        
        # Global Credential'ı al (varsa)
        global_cred = db.query(GlobalCredential).first()
        
        for vm in vms:
            vm_name = vm.get("name", "Unknown")
            vm_status = _vm_status(vm)
            vm_id = (vm.get("vm_id") or "").strip()
            vm_ip = (vm.get("ip_address") or "").strip()

            existing = None
            if vm_id:
                existing = db.query(Server).filter(
                    Server.hypervisor_id == hypervisor_id,
                    Server.hypervisor_vm_id == vm_id,
                ).first()
            if not existing and vm_ip:
                existing = db.query(Server).filter(Server.ip_address == vm_ip).first()
            if not existing:
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
                    ai_ready=ai_ready_status,
                    hypervisor_id=hypervisor_id,
                    hypervisor_vm_id=vm.get("vm_id", ""),
                )
                db.add(new_server)
                synced += 1
            else:
                # Mevcut sunucuyu güncelle - connection_config ve ai_ready değerlerini KORU
                if vm_name and existing.name != vm_name:
                    existing.name = vm_name
                if vm_name and (not existing.hostname or existing.hostname == existing.name):
                    existing.hostname = vm_name
                existing.status = vm_status
                # hypervisor_id eksikse düzelt
                if not existing.hypervisor_id:
                    existing.hypervisor_id = hypervisor_id
                if vm.get("vm_id") and not existing.hypervisor_vm_id:
                    existing.hypervisor_vm_id = vm["vm_id"]
                if vm.get("ip_address"):
                    existing.ip_address = vm["ip_address"]
                if "cpu_cores" in vm:
                    existing.cpu_cores = vm["cpu_cores"]
                if "memory_gb" in vm:
                    existing.memory_gb = vm["memory_gb"]
                if vm.get("os_type"):
                    existing.os_type = vm["os_type"]
                # ÖNEMLI: connection_config ve ai_ready'ye DOKUNMA!

        db.commit()

        from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
        prom_stats = sync_node_exporter_targets_from_db(db)

        return {
            "success": len(errors) == 0,
            "hypervisor": hypervisor.name,
            "synced_count": synced,
            "total_vms": len(vms),
            "prometheus_targets": prom_stats.get("targets_after"),
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

        from app.models.hypervisor_inventory import HypervisorHostInventory
        inv_rows = (
            db.query(HypervisorHostInventory)
            .filter(HypervisorHostInventory.hypervisor_id == hypervisor_id)
            .all()
        )
        inv_by_ref = {i.host_ref: i for i in inv_rows}

        def _inv_dict(r):
            inv = inv_by_ref.get(r.host_ref)
            if not inv:
                return None
            return {
                "vendor":         inv.vendor,
                "model":          inv.model,
                "uuid":           inv.uuid,
                "cpu_model":      inv.cpu_model,
                "pnics":          inv.pnics or [],
                "vswitches":      inv.vswitches or [],
                "portgroups":     inv.portgroups or [],
                "vnics":          inv.vnics or [],
                "dns":            inv.dns or {},
                "last_synced_at": inv.last_synced_at.isoformat() if inv.last_synced_at else None,
            }

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
                    "inventory":        _inv_dict(r),
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


@router.delete("/{hypervisor_id}", status_code=200)
async def delete_hypervisor(hypervisor_id: int, request: Request, db: Session = Depends(get_db)):
    """Hypervisor sil (yalnızca Entegrasyonlar) — bu hypervisor'dan senkronize
    edilmiş tüm VM'ler ve ilişkili veriler (metrik, olay, snapshot vb.) de
    birlikte temizlenir; ortamda yetim VM kaydı bırakılmaz."""
    require_integrations_inventory(request)
    try:
        db_hypervisor = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
        if not db_hypervisor:
            raise HTTPException(status_code=404, detail="Hypervisor not found")

        server_ids = [r[0] for r in db.query(Server.id).filter(Server.hypervisor_id == hypervisor_id).all()]
        deleted_vms = delete_servers_cascade(db, server_ids)

        db.delete(db_hypervisor)
        db.commit()
        return {"deleted": True, "hypervisor_id": hypervisor_id, "deleted_vms": deleted_vms}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting hypervisor: {str(e)}")


# ── Sanallaştırma Komuta Merkezi (AIOps) ─────────────────────────────────────

@router.get("/ops/command-center")
async def virt_command_center(db: Session = Depends(get_db)):
    """vCenter / OLVM manager, ESX host kaynakları ve platform logları."""
    from app.services.virt_ops_center import build_virt_command_center
    try:
        return build_virt_command_center(db)
    except Exception as e:
        logger.exception("virt command center error")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ops/summary")
async def virt_ops_summary_endpoint(db: Session = Depends(get_db)):
    """Navbar badge — sanallaştırma katmanı özet."""
    from app.services.virt_ops_center import virt_ops_summary
    return virt_ops_summary(db)


@router.post("/sync-vcenter-events")
async def sync_vcenter_events_all(db: Session = Depends(get_db)):
    """Tüm VMware hypervisor'lardan vCenter event/alarm/task sync."""
    from app.services.vcenter_event_collector import sync_all_vcenter_events
    try:
        return sync_all_vcenter_events(db, hours=48)
    except Exception as e:
        logger.exception("vCenter event sync error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{hypervisor_id}/sync-vcenter-events")
async def sync_vcenter_events_one(hypervisor_id: int, db: Session = Depends(get_db)):
    """Tek hypervisor için vCenter event/alarm/task sync."""
    from app.services.vcenter_event_collector import sync_vcenter_events_for_hypervisor
    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        raise HTTPException(status_code=404, detail="Hypervisor bulunamadı")
    try:
        return sync_vcenter_events_for_hypervisor(db, hv, hours=48)
    except Exception as e:
        logger.exception("vCenter event sync error for %s", hypervisor_id)
        raise HTTPException(status_code=500, detail=str(e))


# ── Doğal Dil Sorgulama ──────────────────────────────────────────────────────

HV_SESSION_CATEGORY = "hypervisor"


def _hv_session_title(question: str) -> str:
    q = question.strip()
    return (q[:57] + "...") if len(q) > 60 else q


def _hv_session_dict(session, message_count: int = 0) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "message_count": message_count,
    }


def _hv_message_dict(msg) -> dict:
    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "role": msg.role,
        "content": msg.content,
        "meta": msg.meta or {},
        "created_at": msg.created_at.isoformat() if msg.created_at else "",
    }


class HypervisorAskRequest(BaseModel):
    question: str
    model: Optional[str] = None
    history: Optional[List[dict]] = None  # [{role, content}]
    session_id: Optional[int] = None


@router.get("/ask/sessions")
async def list_hypervisor_sessions(
    q: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Hypervisor AI asistan oturum geçmişi (arama destekli)."""
    from app.models.chat_session import ChatSession, ChatMessage
    from sqlalchemy import or_, func as sa_func

    query = db.query(ChatSession).filter(ChatSession.category == HV_SESSION_CATEGORY)
    if q and q.strip():
        term = f"%{q.strip()}%"
        msg_ids = [
            r[0] for r in db.query(ChatMessage.session_id)
            .filter(ChatMessage.content.ilike(term))
            .distinct()
            .all()
        ]
        filters = [ChatSession.title.ilike(term)]
        if msg_ids:
            filters.append(ChatSession.id.in_(msg_ids))
        query = query.filter(or_(*filters))

    sessions = (
        query.order_by(sa_func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    result = []
    for s in sessions:
        count = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
        result.append(_hv_session_dict(s, message_count=count))
    return result


@router.post("/ask/sessions")
async def create_hypervisor_session(db: Session = Depends(get_db)):
    """Yeni hypervisor AI oturumu."""
    from app.models.chat_session import ChatSession
    from datetime import datetime, timezone

    session = ChatSession(title="Yeni Sohbet", server_ids=[], category=HV_SESSION_CATEGORY)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _hv_session_dict(session, message_count=0)


@router.get("/ask/sessions/{session_id}/messages")
async def get_hypervisor_session_messages(session_id: int, db: Session = Depends(get_db)):
    """Oturum mesajlarını getir."""
    from app.models.chat_session import ChatSession, ChatMessage

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.category == HV_SESSION_CATEGORY,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return {"session_id": session_id, "messages": [_hv_message_dict(m) for m in rows]}


@router.delete("/ask/sessions/{session_id}")
async def delete_hypervisor_session(session_id: int, db: Session = Depends(get_db)):
    """Tek oturumu sil."""
    from app.models.chat_session import ChatSession, ChatMessage
    from sqlalchemy import delete

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.category == HV_SESSION_CATEGORY,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    db.delete(session)
    db.commit()
    return {"success": True}


@router.delete("/ask/sessions")
async def delete_all_hypervisor_sessions(db: Session = Depends(get_db)):
    """Tüm hypervisor oturumlarını sil."""
    from app.models.chat_session import ChatSession, ChatMessage
    from sqlalchemy import delete

    ids = [
        s.id for s in db.query(ChatSession.id).filter(ChatSession.category == HV_SESSION_CATEGORY).all()
    ]
    if ids:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
        db.commit()
    return {"success": True, "deleted": len(ids)}


@router.post("/ask")
async def ask_hypervisor_question(
    req: HypervisorAskRequest,
    db: Session = Depends(get_db),
):
    """
    Doğal dil ile hypervisor/VM sorgulama ve rapor istekleri.

    Örnek sorular:
    - "Kaç ESX hostum var?"
    - "Kapasite raporu oluştur"
    - "Executive summary raporu ver"
    """
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Soru boş olamaz")

    from app.models.chat_session import ChatSession, ChatMessage
    from datetime import datetime, timezone

    question = req.question.strip()
    session_id = req.session_id

    try:
        if session_id:
            session = db.query(ChatSession).filter(
                ChatSession.id == session_id,
                ChatSession.category == HV_SESSION_CATEGORY,
            ).first()
            if not session:
                raise HTTPException(status_code=404, detail="Oturum bulunamadı")
        else:
            session = ChatSession(
                title=_hv_session_title(question),
                server_ids=[],
                category=HV_SESSION_CATEGORY,
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            session_id = session.id

        db.add(ChatMessage(session_id=session_id, role="user", content=question))
        db.commit()

        # DB'den konuşma geçmişi (son 8 mesaj, yeni user hariç)
        prior = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
        history = [{"role": m.role, "content": m.content} for m in prior[:-1]][-8:]
        if req.history:
            history = req.history[-8:]

        from app.services.hypervisor_intelligence import answer_hypervisor_question
        result = answer_hypervisor_question(
            db=db,
            question=question,
            model=req.model,
            conversation_history=history,
        )

        assistant_meta = {
            "intents": result.get("intents") or [],
            "report_type": result.get("report_type"),
            "report_title": result.get("report_title"),
            "latency_ms": result.get("latency_ms"),
            "error": result.get("error"),
        }
        db.add(ChatMessage(
            session_id=session_id,
            role="assistant",
            content=result.get("answer") or "",
            meta=assistant_meta,
        ))
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            if session.title == "Yeni Sohbet" or not session.title.strip():
                session.title = _hv_session_title(question)
            session.updated_at = datetime.now(timezone.utc)
        db.commit()

        return {**result, "session_id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Sorgulama hatası: {str(e)}")


@router.get("/ask/quick-stats")
async def get_quick_stats(db: Session = Depends(get_db)):
    """Üst bar için anlık özet istatistikler."""
    from app.models.server import Server as ServerModel
    from app.models.hypervisor_metric import HypervisorHostMetric
    from app.services.platform_scope import vm_filter_condition
    from sqlalchemy import func

    vm_count = db.query(ServerModel).filter(vm_filter_condition()).count()
    powered_on = db.query(ServerModel).filter(
        vm_filter_condition(),
        ServerModel.vm_power_state.in_(["POWERED_ON", "up", "running", "poweredOn"]),
    ).count()

    # ESX host metrikleri — en son kayıt başına
    try:
        rows = db.execute(text("""
            SELECT DISTINCT ON (host_name)
                cpu_usage_pct, mem_usage_pct
            FROM hypervisor_host_metrics
            ORDER BY host_name, timestamp DESC
        """)).all()
        host_count = len(rows)
        avg_cpu = round(sum(r.cpu_usage_pct or 0 for r in rows) / host_count, 1) if host_count else 0
        avg_mem = round(sum(r.mem_usage_pct or 0 for r in rows) / host_count, 1) if host_count else 0
    except Exception:
        host_count = 0
        avg_cpu = 0.0
        avg_mem = 0.0

    return {
        "host_count": host_count,
        "vm_count": vm_count,
        "vms_powered_on": powered_on,
        "avg_cpu_pct": avg_cpu,
        "avg_mem_pct": avg_mem,
    }


@router.get("/ask/suggestions")
async def get_question_suggestions(db: Session = Depends(get_db)):
    """Örnek sorular + mevcut VM adları."""
    from app.models.server import Server as ServerModel
    from app.services.platform_scope import vm_filter_condition
    vm_names = [
        r[0] for r in db.query(ServerModel.name)
        .filter(vm_filter_condition())
        .limit(10).all()
    ]
    suggestions = [
        "Kaç ESX / KVM hostum var?",
        "Hangi host'ta kaç VM çalışıyor?",
        "ESX hostlarımın CPU ve bellek doluluk durumu nedir?",
        "VMware Tools yüklü olmayan VM'ler hangileri?",
        "Çalışmayan (powered off) VM'ler hangileri?",
        "RHEL tabanlı VM'leri listele",
        "Oracle Linux VM'leri hangileri?",
        "En yoğun ESX host hangisi?",
        "En fazla boş belleği olan host hangisi?",
        "Ortam genel sağlık değerlendirmesi yap",
        "Disk alanı en doldu olan host hangisi?",
    ]
    # İlk 2 VM adıyla karşılaştırma sorusu ekle
    if len(vm_names) >= 2:
        suggestions.insert(2, f"'{vm_names[0]}' ile '{vm_names[1]}' VM'ini karşılaştır")

    report_suggestions = [
        "Executive Summary raporu oluştur",
        "Kapasite raporu göster",
        "Risk dashboard raporu ver",
        "VM sağlık skoru raporu üret",
        "6 aylık kapasite tahmin raporu",
        "Maliyet raporu oluştur",
        "Güvenlik uyumluluk raporu göster",
        "Konsolidasyon raporu üret",
        "En riskli varlıklar raporu",
        "Performans darboğaz raporu",
    ]

    return {
        "suggestions": suggestions,
        "report_suggestions": report_suggestions,
        "sample_vms": vm_names[:8],
    }


# ── Rapor Endpoint'leri ───────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    report_type: str
    save: bool = True


@router.get("/reports/data-quality")
async def get_report_data_quality_endpoint(db: Session = Depends(get_db)):
    """Rapor veri kalitesi özeti (envanter tazeliği, metrik kapsamı)."""
    from app.services.report_engine import _report_data_quality
    return _report_data_quality(db)


@router.get("/reports/types")
async def list_report_types():
    """Desteklenen rapor tiplerini listele."""
    from app.services.report_engine import REPORT_TITLES, REPORT_REGISTRY
    return {
        "report_types": [
            {"type": k, "title": v, "available": True}
            for k, v in REPORT_TITLES.items()
        ]
    }


@router.post("/reports/generate")
async def generate_report_endpoint(
    req: ReportRequest,
    db: Session = Depends(get_db),
):
    """Rapor üret ve DB'ye kaydet."""
    from app.services.report_engine import generate_report, REPORT_REGISTRY
    if req.report_type not in REPORT_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {req.report_type}")
    try:
        data = generate_report(db, req.report_type, save=req.save)
        from app.services.report_engine import format_report_as_markdown
        md = format_report_as_markdown(req.report_type, data)
        return {"success": True, "data": data, "markdown": md}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/latest/{report_type}")
async def get_latest_report_endpoint(report_type: str, db: Session = Depends(get_db)):
    """Son kaydedilen raporu getir (yoksa anlık üret)."""
    from app.services.report_engine import get_latest_report, generate_report, REPORT_REGISTRY
    if report_type not in REPORT_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {report_type}")
    from app.services.report_engine import format_report_as_markdown
    cached = get_latest_report(db, report_type)
    if cached:
        md = format_report_as_markdown(report_type, cached)
        return {"source": "cache", "data": cached, "markdown": md}
    data = generate_report(db, report_type, save=True)
    md = format_report_as_markdown(report_type, data)
    return {"source": "fresh", "data": data, "markdown": md}


@router.get("/reports/history")
async def get_report_history(
    report_type: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Kaydedilen raporların geçmişi."""
    from app.models.infrastructure_report import InfrastructureReport
    q = db.query(InfrastructureReport)
    if report_type:
        q = q.filter(InfrastructureReport.report_type == report_type)
    rows = q.order_by(InfrastructureReport.generated_at.desc()).limit(limit).all()
    return {
        "reports": [
            {
                "id": r.id, "type": r.report_type,
                "title": r.report_title,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "status": r.status,
            }
            for r in rows
        ]
    }


# ── Business Service Map ──────────────────────────────────────────────────────

class BusinessServiceCreate(BaseModel):
    service_name: str
    service_tier: str = "standard"
    server_id: int
    department: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


@router.post("/business-services")
async def create_business_service(req: BusinessServiceCreate, db: Session = Depends(get_db)):
    """İş servisi → VM eşleşmesi ekle."""
    from app.models.infrastructure_report import BusinessServiceMap
    obj = BusinessServiceMap(**req.dict())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "service_name": obj.service_name}


@router.get("/business-services")
async def list_business_services(db: Session = Depends(get_db)):
    from app.models.infrastructure_report import BusinessServiceMap
    items = db.query(BusinessServiceMap).all()
    return {"services": [{"id": i.id, "service_name": i.service_name, "server_id": i.server_id,
                          "tier": i.service_tier, "dept": i.department} for i in items]}


# ── Cost Config ──────────────────────────────────────────────────────────────

class CostConfigUpdate(BaseModel):
    cpu_per_core: float
    ram_per_gb: float
    storage_per_gb: float
    currency: str = "TL"


@router.put("/cost-config")
async def update_cost_config(req: CostConfigUpdate, db: Session = Depends(get_db)):
    from app.models.infrastructure_report import CostConfig
    cfg = db.query(CostConfig).first()
    if not cfg:
        cfg = CostConfig(name="Varsayılan")
        db.add(cfg)
    cfg.cpu_per_core = req.cpu_per_core
    cfg.ram_per_gb = req.ram_per_gb
    cfg.storage_per_gb = req.storage_per_gb
    cfg.currency = req.currency
    db.commit()
    return {"success": True}


@router.get("/cost-config")
async def get_cost_config(db: Session = Depends(get_db)):
    from app.models.infrastructure_report import CostConfig
    cfg = db.query(CostConfig).first()
    if not cfg:
        return {"cpu_per_core": 50, "ram_per_gb": 20, "storage_per_gb": 0.5, "currency": "TL"}
    return {"cpu_per_core": cfg.cpu_per_core, "ram_per_gb": cfg.ram_per_gb,
            "storage_per_gb": cfg.storage_per_gb, "currency": cfg.currency}
