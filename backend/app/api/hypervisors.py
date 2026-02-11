"""
Hypervisors API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.hypervisor import Hypervisor, HypervisorType
from app.schemas.hypervisor import HypervisorCreate, HypervisorUpdate, HypervisorResponse

router = APIRouter()

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
                vms = client.list_vms()
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

        for vm in vms:
            vm_name = vm.get("name", "Unknown")
            existing = db.query(Server).filter(Server.name == vm_name).first()
            if not existing:
                new_server = Server(
                    name=vm_name,
                    hostname=vm_name,
                    ip_address=vm.get("ip_address", ""),
                    status="OFFLINE",
                    os_type=vm.get("os_type", ""),
                    server_type="VIRTUAL",
                    cpu_cores=vm.get("cpu_cores", 0),
                    memory_gb=vm.get("memory_gb", 0),
                    connection_config={}
                )
                db.add(new_server)
                synced += 1
            else:
                # Mevcut sunucuyu güncelle
                if vm.get("ip_address"):
                    existing.ip_address = vm["ip_address"]
                if vm.get("cpu_cores"):
                    existing.cpu_cores = vm["cpu_cores"]
                if vm.get("memory_gb"):
                    existing.memory_gb = vm["memory_gb"]
                if vm.get("os_type"):
                    existing.os_type = vm["os_type"]

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
