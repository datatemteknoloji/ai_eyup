"""
Envanter sync servisi - Hypervisor'lardan VM'leri DB'ye senkronize eder.
API ve background task tarafından kullanılır.
"""
import inspect
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.credential import GlobalCredential
from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.services.snapshot_service import _apply_vm_details_to_server

logger = logging.getLogger(__name__)


def update_sync_job(hypervisor_id: int, **patch) -> None:
    """Hypervisor.meta_data.sync_job alanını güncelle (thread-safe, ayrı session)."""
    from app.core.database import ThreadSessionLocal

    db = ThreadSessionLocal()
    try:
        hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
        if not hv:
            return
        meta = dict(hv.meta_data or {})
        job = dict(meta.get("sync_job") or {})
        job.update(patch)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["sync_job"] = job
        hv.meta_data = meta
        flag_modified(hv, "meta_data")
        st = patch.get("status")
        if st == "running":
            hv.status = "SYNCING"
        elif st == "done":
            hv.status = "ONLINE"
        elif st == "error":
            hv.status = "ERROR"
        db.commit()
    except Exception as exc:
        logger.warning("sync_job update failed (hv=%s): %s", hypervisor_id, exc)
        db.rollback()
    finally:
        db.close()


def get_sync_job(hypervisor: Hypervisor) -> dict:
    meta = hypervisor.meta_data or {}
    job = meta.get("sync_job") or {}
    return job if isinstance(job, dict) else {}


def _vm_status(vm: dict) -> str:
    """oVirt/VMware ham durumunu uygulama durumuna çevirir."""
    mapping = {
        "up": "ONLINE", "powered_on": "ONLINE", "poweredon": "ONLINE", "running": "ONLINE",
        "down": "OFFLINE", "powered_off": "OFFLINE", "poweredoff": "OFFLINE",
        "stopped": "OFFLINE", "suspended": "OFFLINE", "online": "ONLINE", "offline": "OFFLINE",
    }
    raw = (vm.get("status") or vm.get("power_state") or "").lower().replace(" ", "_").replace("-", "_")
    return mapping.get(raw, "OFFLINE")


def _find_existing_server(db: Session, hypervisor_id: int, vm: dict) -> Server | None:
    vm_name = vm.get("name", "Unknown")
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
    return existing


def _enrich_server_from_client(
    client,
    server: Server,
    vm: dict,
    db: Session,
    preloaded_details: dict | None = None,
) -> None:
    """Hypervisor client'tan tam VM detaylarını çeker ve server kaydına yazar."""
    if preloaded_details:
        _apply_vm_details_to_server(server, preloaded_details, db)
        return
    vm_id = (vm.get("vm_id") or server.hypervisor_vm_id or "").strip()
    if not vm_id or not hasattr(client, "get_vm_full_details"):
        return
    try:
        sig = inspect.signature(client.get_vm_full_details)
        if "name" in sig.parameters:
            details = client.get_vm_full_details(vm_id, name=server.name or vm.get("name", ""))
        else:
            details = client.get_vm_full_details(vm_id)
        if details:
            _apply_vm_details_to_server(server, details, db)
    except Exception as exc:
        logger.debug("VM detay zenginleştirme atlandı (%s): %s", server.name, exc)


def _upsert_vm_record(
    db: Session,
    hypervisor: Hypervisor,
    vm: dict,
    global_cred: GlobalCredential | None,
    client=None,
    preloaded_details: dict | None = None,
) -> bool:
    """Tek VM kaydını oluşturur/günceller. Yeni kayıt ise True döner."""
    vm_name = vm.get("name", "Unknown")
    vm_status_val = _vm_status(vm)
    vm_id = (vm.get("vm_id") or "").strip()
    existing = _find_existing_server(db, hypervisor.id, vm)
    created = False

    if not existing:
        conn_cfg = {}
        if global_cred:
            conn_cfg = {
                "username": global_cred.username,
                "password": global_cred.password,
                "private_key": global_cred.private_key,
                "port": global_cred.port or 22,
                "sudo_password": global_cred.sudo_password,
            }
        existing = Server(
            name=vm_name,
            hostname=vm_name,
            ip_address=vm.get("ip_address", ""),
            status=vm_status_val,
            os_type=vm.get("os_type", ""),
            server_type="VIRTUAL",
            cpu_cores=vm.get("cpu_cores", 0),
            memory_gb=vm.get("memory_gb", 0),
            connection_config=conn_cfg,
            ai_ready=False,
            hypervisor_id=hypervisor.id,
            hypervisor_vm_id=vm_id,
        )
        db.add(existing)
        created = True
    else:
        if vm_name and existing.name != vm_name:
            existing.name = vm_name
        if vm_name and (not existing.hostname or existing.hostname == existing.name):
            existing.hostname = vm_name
        existing.status = vm_status_val
        if not existing.hypervisor_id:
            existing.hypervisor_id = hypervisor.id
        if vm_id and not existing.hypervisor_vm_id:
            existing.hypervisor_vm_id = vm_id
        if not existing.server_type:
            existing.server_type = "VIRTUAL"
        if vm.get("ip_address"):
            existing.ip_address = vm["ip_address"]
        if "cpu_cores" in vm:
            existing.cpu_cores = vm["cpu_cores"]
        if "memory_gb" in vm:
            existing.memory_gb = vm["memory_gb"]
        if vm.get("os_type"):
            existing.os_type = vm["os_type"]

    power = vm.get("power_state") or vm.get("status")
    if power and not existing.vm_power_state:
        existing.vm_power_state = str(power)

    db.flush()

    needs_enrichment = (
        not existing.vm_disk_gb
        or not existing.vm_tools_status
        or not existing.vm_datastore
        or not existing.vm_last_sync
    )
    if preloaded_details:
        _enrich_server_from_client(
            client, existing, vm, db, preloaded_details=preloaded_details
        )
    elif client and needs_enrichment:
        _enrich_server_from_client(client, existing, vm, db)

    try:
        from app.services.fact_learning import extract_and_store_virt_facts
        extract_and_store_virt_facts(db, existing)
    except Exception as exc:
        logger.debug("Virt fact learning atlandı (%s): %s", existing.name, exc)

    return created


def sync_hypervisor_vms(db: Session, hypervisor: Hypervisor, *, track_progress: bool = False) -> dict:
    """
    Tek bir hypervisor'dan VM'leri senkronize et.
    Returns: { synced_count, total_vms, errors, enriched_count }
    track_progress=True ise meta_data.sync_job güncellenir (UI tarama ekranı).
    """
    hv_id = hypervisor.id

    def _prog(**kw):
        if track_progress and hv_id:
            update_sync_job(hv_id, **kw)

    synced = 0
    enriched = 0
    errors = []
    vms = []
    client = None
    htype = hypervisor.hypervisor_type.value if hypervisor.hypervisor_type else ""

    _prog(
        status="running",
        phase="connecting",
        percent=2,
        message="Hypervisor'a bağlanılıyor...",
        vms_done=0,
        vms_total=0,
        error=None,
    )

    if htype == "vmware":
        try:
            from app.services.vmware.vcenter_client import VCenterClient
            client = VCenterClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hypervisor.password or (hypervisor.connection_config or {}).get("password", ""),
            )
            if not client.login():
                errors.append("vCenter bağlantı hatası: giriş başarısız (host/kullanıcı/şifre kontrol edin)")
            else:
                _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
                vms = client.sync_vms_to_inventory()
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
            _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
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
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hypervisor.password or (hypervisor.connection_config or {}).get("password", ""),
                port=hypervisor.port or 8006,
                verify_ssl=False,
            )
            _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
            vms = client.list_vms()
        except ImportError:
            errors.append("Proxmox client modülü bulunamadı")
        except Exception as e:
            errors.append(f"Proxmox bağlantı hatası: {str(e)}")
    elif htype == "hyperv":
        try:
            from app.services.windows.winrm_client import WinRMClient
            from app.services.hypervisor.hyperv_client import HyperVClient
            winrm = WinRMClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hypervisor.password or (hypervisor.connection_config or {}).get("password", ""),
                port=hypervisor.port or 5985,
            )
            client = HyperVClient(winrm)
            _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
            vms = client.list_vms()
        except ImportError:
            errors.append("Hyper-V client modülü bulunamadı")
        except Exception as e:
            errors.append(f"Hyper-V bağlantı hatası: {str(e)}")
    elif htype == "openshift_virt":
        try:
            from app.services.openshift.kubevirt_client import KubeVirtClient
            cc = hypervisor.connection_config or {}
            use_creds = bool(cc.get("username")) and bool(cc.get("password"))
            client = KubeVirtClient(
                api_url=cc.get("api_url") or hypervisor.hostname or hypervisor.ip_address,
                token="" if use_creds else (cc.get("token") or hypervisor.password or ""),
                username=cc.get("username") or "",
                password=cc.get("password") or "",
                verify_ssl=bool(cc.get("verify_ssl", False)),
            )
            _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
            vms = client.list_vms()
        except ImportError:
            errors.append("OpenShift Virtualization client modülü bulunamadı")
        except Exception as e:
            errors.append(f"OpenShift Virtualization bağlantı hatası: {str(e)}")
    else:
        errors.append(f"Desteklenmeyen hypervisor tipi: {htype}")

    if errors and not vms:
        _prog(status="error", phase="error", percent=100, message=errors[0], error=errors[0])
        return {
            "synced_count": 0,
            "total_vms": 0,
            "enriched_count": 0,
            "errors": errors,
        }

    _prog(
        phase="listed",
        percent=12,
        message=f"{len(vms)} VM bulundu, detaylar taranıyor...",
        vms_total=len(vms),
        vms_done=0,
    )

    global_cred = db.query(GlobalCredential).first()

    # vCenter: eksik meta için full_details'i 10 paralel worker ile önceden çek
    preloaded: dict = {}
    if (
        client
        and htype == "vmware"
        and vms
        and hasattr(client, "fetch_full_details_parallel")
    ):
        need = []
        for vm in vms:
            existing = _find_existing_server(db, hypervisor.id, vm)
            if (
                existing is None
                or not existing.vm_disk_gb
                or not existing.vm_tools_status
                or not existing.vm_datastore
                or not existing.vm_last_sync
            ):
                need.append(vm)
        if need:
            logger.info(
                "vCenter enrichment ön-çekim: %s VM (paralel)",
                len(need),
            )
            _prog(
                phase="enriching",
                percent=15,
                message=f"VM detayları taranıyor (0/{len(need)})...",
                vms_total=len(need),
                vms_done=0,
            )

            def _enrich_prog(done: int, total: int):
                # listing 15% → saving 85%
                pct = 15 + int(70 * (done / max(total, 1)))
                _prog(
                    phase="enriching",
                    percent=min(85, pct),
                    message=f"VM detayları taranıyor ({done}/{total})...",
                    vms_done=done,
                    vms_total=total,
                )

            preloaded = client.fetch_full_details_parallel(need, on_progress=_enrich_prog)

    _prog(
        phase="saving",
        percent=88,
        message="Envantere kaydediliyor...",
        vms_total=len(vms),
        vms_done=0,
    )

    try:
        for i, vm in enumerate(vms, 1):
            before = _find_existing_server(db, hypervisor.id, vm)
            was_missing_meta = (
                before is None
                or not before.vm_disk_gb
                or not before.vm_tools_status
            )
            vid = (vm.get("vm_id") or "").strip()
            if _upsert_vm_record(
                db,
                hypervisor,
                vm,
                global_cred,
                client=client,
                preloaded_details=preloaded.get(vid) if vid else None,
            ):
                synced += 1
            elif was_missing_meta:
                enriched += 1
            if track_progress and (i % 25 == 0 or i == len(vms)):
                pct = 88 + int(10 * (i / max(len(vms), 1)))
                _prog(
                    phase="saving",
                    percent=min(98, pct),
                    message=f"Envantere kaydediliyor ({i}/{len(vms)})...",
                    vms_done=i,
                    vms_total=len(vms),
                )

        hypervisor.last_sync = datetime.now(timezone.utc)
        db.add(hypervisor)
    finally:
        if client and hasattr(client, "logout"):
            try:
                client.logout()
            except Exception:
                pass

    result = {
        "synced_count": synced,
        "total_vms": len(vms),
        "enriched_count": enriched,
        "errors": errors,
    }
    if errors:
        _prog(
            status="error",
            phase="error",
            percent=100,
            message="; ".join(errors)[:300],
            error="; ".join(errors)[:300],
            vms_done=len(vms),
            vms_total=len(vms),
            synced_count=synced,
        )
    else:
        _prog(
            status="done",
            phase="done",
            percent=100,
            message=f"Tamamlandı — {len(vms)} VM (yeni: {synced})",
            vms_done=len(vms),
            vms_total=len(vms),
            synced_count=synced,
            enriched_count=enriched,
        )
    return result


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
                "enriched_count": r.get("enriched_count", 0),
                "errors": r["errors"],
            })
        except Exception as e:
            logger.error(f"Inventory sync error for {h.name}: {e}", exc_info=True)
            db.rollback()
            results.append({"name": h.name, "synced_count": 0, "total_vms": 0, "errors": [str(e)]})
            all_errors.append(str(e))

    return {
        "success": len(all_errors) == 0,
        "total_synced": total_synced,
        "hypervisors": results,
    }
