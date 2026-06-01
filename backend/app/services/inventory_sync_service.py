"""
Envanter sync servisi - Hypervisor'lardan VM'leri DB'ye senkronize eder.
API ve background task tarafından kullanılır.
"""
import logging
from sqlalchemy.orm import Session
from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.models.credential import GlobalCredential

logger = logging.getLogger(__name__)


def _vm_status(vm: dict) -> str:
    """oVirt/VMware ham durumunu uygulama durumuna çevirir."""
    mapping = {
        "up": "ONLINE", "powered_on": "ONLINE", "poweredon": "ONLINE", "running": "ONLINE",
        "down": "OFFLINE", "powered_off": "OFFLINE", "poweredoff": "OFFLINE",
        "stopped": "OFFLINE", "suspended": "OFFLINE",
    }
    raw = (vm.get("status") or vm.get("power_state") or "").lower().replace(" ", "_")
    return mapping.get(raw, "OFFLINE")


def sync_hypervisor_vms(db: Session, hypervisor: Hypervisor) -> dict:
    """
    Tek bir hypervisor'dan VM'leri senkronize et.
    Returns: { synced_count, total_vms, errors }
    """
    synced = 0
    errors = []
    vms = []
    htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""

    if htype == "vmware":
        try:
            from app.services.vmware.vcenter_client import VCenterClient
            client = VCenterClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hypervisor.password or (hypervisor.connection_config or {}).get("password", "")
            )
            client.login()
            vms = client.sync_vms_to_inventory()
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
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hypervisor.password or (hypervisor.connection_config or {}).get("password", ""),
                verify_ssl=False,
                port=hypervisor.port or 443,
            )
            vms = client.list_vms()
        except ImportError:
            errors.append("oVirt client modülü bulunamadı")
        except Exception as e:
            errors.append(f"oVirt bağlantı hatası: {str(e)}")
    else:
        errors.append(f"Desteklenmeyen hypervisor tipi: {htype}")

    global_cred = db.query(GlobalCredential).first()

    for vm in vms:
        vm_name = vm.get("name", "Unknown")
        vm_status_val = _vm_status(vm)
        existing = db.query(Server).filter(Server.name == vm_name).first()
        if not existing:
            conn_cfg = {}
            if global_cred:
                conn_cfg = {
                    "username": global_cred.username,
                    "password": global_cred.password,
                    "private_key": global_cred.private_key,
                    "port": global_cred.port or 22,
                    "sudo_password": global_cred.sudo_password
                }
            new_server = Server(
                name=vm_name,
                hostname=vm_name,
                ip_address=vm.get("ip_address", ""),
                status=vm_status_val,
                os_type=vm.get("os_type", ""),
                server_type="VIRTUAL",
                cpu_cores=vm.get("cpu_cores", 0),
                memory_gb=vm.get("memory_gb", 0),
                connection_config=conn_cfg,
                ai_ready=False
            )
            db.add(new_server)
            synced += 1
        else:
            existing.status = vm_status_val
            if vm.get("ip_address"):
                existing.ip_address = vm["ip_address"]
            if "cpu_cores" in vm:
                existing.cpu_cores = vm["cpu_cores"]
            if "memory_gb" in vm:
                existing.memory_gb = vm["memory_gb"]
            if vm.get("os_type"):
                existing.os_type = vm["os_type"]

    return {"synced_count": synced, "total_vms": len(vms), "errors": errors}


def sync_all_hypervisors(db: Session) -> dict:
    """
    Tüm hypervisor'lardan VM'leri senkronize et.
    Returns: { success, total_synced, hypervisors: [{ name, synced_count, total_vms, errors }] }
    """
    hypervisors = db.query(Hypervisor).all()
    if not hypervisors:
        return {"success": True, "total_synced": 0, "hypervisors": []}

    results = []
    total_synced = 0
    all_errors = []

    for h in hypervisors:
        try:
            r = sync_hypervisor_vms(db, h)
            db.commit()
            total_synced += r["synced_count"]
            all_errors.extend(r["errors"])
            results.append({
                "name": h.name,
                "synced_count": r["synced_count"],
                "total_vms": r["total_vms"],
                "errors": r["errors"]
            })
        except Exception as e:
            logger.error(f"Inventory sync error for {h.name}: {e}", exc_info=True)
            db.rollback()
            results.append({"name": h.name, "synced_count": 0, "total_vms": 0, "errors": [str(e)]})
            all_errors.append(str(e))

    return {
        "success": len(all_errors) == 0,
        "total_synced": total_synced,
        "hypervisors": results
    }
