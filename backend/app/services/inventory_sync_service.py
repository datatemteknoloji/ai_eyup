"""
Envanter sync servisi - Hypervisor'lardan VM'leri DB'ye senkronize eder.
API ve background task tarafından kullanılır.
"""
import inspect
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.credential import GlobalCredential
from app.models.hypervisor import Hypervisor
from app.models.server import Server
from app.services.snapshot_service import _apply_vm_details_to_server
from app.services.virt_scope import owned_by_other_vcenter

logger = logging.getLogger(__name__)

# UI overlay + yeni tarama: updated_at bu süreden eskiyse iş ölü kabul edilir.
STALE_RUNNING_SEC = 180


def update_sync_job(hypervisor_id: int, **patch) -> None:
    """Hypervisor.meta_data.sync_job alanını güncelle (thread-safe, ayrı session)."""
    from app.core.database import ThreadSessionLocal

    last_exc = None
    for attempt in range(5):
        db = ThreadSessionLocal()
        try:
            hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
            if not hv:
                return
            now = datetime.now(timezone.utc).isoformat()
            meta = dict(hv.meta_data or {})
            job = dict(meta.get("sync_job") or {})
            job.update(patch)
            job["updated_at"] = now
            if patch.get("status") == "running":
                if patch.get("started_at"):
                    job["started_at"] = patch["started_at"]
                elif not job.get("started_at"):
                    job["started_at"] = now
                hv.status = "SYNCING"
            elif patch.get("status") == "done":
                hv.status = "ONLINE"
            elif patch.get("status") == "error":
                hv.status = "ERROR"
            meta["sync_job"] = job
            hv.meta_data = meta
            flag_modified(hv, "meta_data")
            db.commit()
            return
        except Exception as exc:
            last_exc = exc
            try:
                db.rollback()
            except Exception:
                pass
            time.sleep(0.4 * (attempt + 1))
        finally:
            db.close()
    logger.warning("sync_job update failed (hv=%s): %s", hypervisor_id, last_exc)


def job_is_stale_running(job: dict) -> bool:
    if not job or job.get("status") != "running":
        return False
    raw = job.get("updated_at") or job.get("started_at")
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() > STALE_RUNNING_SEC
    except Exception:
        return True


def expire_stale_sync_job(hypervisor_id: int, job: dict) -> dict:
    """Ölü 'running' kaydını error yapar; UI sonsuz spinner'da kalmasın."""
    if not job_is_stale_running(job):
        return job if isinstance(job, dict) else {}
    update_sync_job(
        hypervisor_id,
        status="error",
        phase="error",
        percent=100,
        message="Tarama yanıt vermeyi kesti (zaman aşımı). Yeniden tarayabilirsiniz.",
        error="stale_running",
    )
    out = dict(job or {})
    out.update({
        "status": "error",
        "phase": "error",
        "percent": 100,
        "message": "Tarama yanıt vermeyi kesti (zaman aşımı). Yeniden tarayabilirsiniz.",
        "error": "stale_running",
    })
    return out


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


def is_matchable_ip(ip: str | None) -> bool:
    """IP ile kayıt eşleştirmesine uygun mu?

    Link-local (169.254/16, fe80::/10), loopback, unspecified ve multicast adresler
    birçok sanal cihazda (güvenlik/HA appliance) ortak olur; bu adreslerle eşleştirme
    farklı VM'leri aynı kayda birleştirir. Bunlar eşleştirmede kullanılmaz.
    """
    import ipaddress

    raw = (ip or "").strip()
    if not raw:
        return False
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        # IP olmayan değer (hostname vb.) — eski davranışı koru
        return True
    return not (
        addr.is_link_local
        or addr.is_loopback
        or addr.is_unspecified
        or addr.is_multicast
    )


_UNSET: Any = object()   # `_upsert_vm_record(existing=...)`: "verilmedi" (None geçerli bir değerdir)


def _belongs_to_other_vm(
    server: Server,
    vm_id: str,
    *,
    name: str | None = None,
    ip: str | None = None,
    hypervisor_id: int | None = None,
) -> bool:
    """Kayıt başka bir VM'e (farklı dolu hypervisor_vm_id) mi ait?

    İstisna: aynı hypervisor'da ad VE IP birebir aynıysa kayıt aynı VM'dir; yalnız VM kimliği
    biçimi değişmiştir (ör. KubeVirt UID → `namespace/ad`) ve kayıt devralınır.
    """
    sid = (getattr(server, "hypervisor_vm_id", None) or "").strip()
    if not (vm_id and sid and sid != vm_id):
        return False
    if (
        hypervisor_id is not None
        and getattr(server, "hypervisor_id", None) == hypervisor_id
        and name
        and getattr(server, "name", None) == name
        and ip
        and getattr(server, "ip_address", None) == ip
    ):
        return False
    return True


def _find_existing_server(db: Session, hypervisor_id: int, vm: dict) -> Server | None:
    """VM'e karşılık gelen Server kaydını bul.

    Sıra: (hypervisor_id, vm_id) → IP → ad. IP/ad yedeği yalnızca henüz bir VM'e
    bağlanmamış (hypervisor_vm_id boş) kayıtlara uygulanır; başka bir VM'in kaydına
    yazmak (sessiz birleştirme) yapılmaz — o VM için yeni kayıt açılır.
    """
    vm_name = vm.get("name", "Unknown")
    vm_id = (vm.get("vm_id") or "").strip()
    vm_ip = (vm.get("ip_address") or "").strip()

    existing = None
    if vm_id:
        existing = db.query(Server).filter(
            Server.hypervisor_id == hypervisor_id,
            Server.hypervisor_vm_id == vm_id,
        ).first()
    if not existing and vm_ip and is_matchable_ip(vm_ip):
        by_ip = db.query(Server).filter(Server.ip_address == vm_ip).all()
        existing = next(
            (
                s for s in by_ip
                if not owned_by_other_vcenter(s.hypervisor_id, hypervisor_id)
                and not _belongs_to_other_vm(s, vm_id, name=vm_name, ip=vm_ip, hypervisor_id=hypervisor_id)
            ),
            None,
        )
    if not existing and vm_name:
        by_name = db.query(Server).filter(Server.name == vm_name).all()
        existing = next(
            (
                s for s in by_name
                if not owned_by_other_vcenter(s.hypervisor_id, hypervisor_id)
                and not _belongs_to_other_vm(s, vm_id, name=vm_name, ip=vm_ip, hypervisor_id=hypervisor_id)
            ),
            None,
        )
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


def _inventory_guest_hostname(vm: dict) -> str:
    """Inventory satırından guest OS hostname — VMware Tools / oVirt agent / KubeVirt guestOSInfo.

    `hostname` alanı çoğu client'ta guest hostname'dir (yoksa VM adına düşer).
    `vm_guest_hostname` yalnızca gerçek guest değeri taşır (KubeVirt boş bırakabilir).
    """
    explicit = (vm.get("vm_guest_hostname") or "").strip()
    if explicit:
        return explicit
    hn = (vm.get("hostname") or "").strip()
    name = (vm.get("name") or "").strip()
    # hostname yalnızca VM adı fallback'iyse guest sayma
    if hn and name and hn.lower() == name.lower():
        return ""
    return hn


def _upsert_vm_record(
    db: Session,
    hypervisor: Hypervisor,
    vm: dict,
    global_cred: GlobalCredential | None,
    client=None,
    preloaded_details: dict | None = None,
    existing: Any = _UNSET,
    commit_facts: bool = True,
) -> bool:
    """Tek VM kaydını oluşturur/günceller. Yeni kayıt ise True döner.

    `existing`: çağıran `_find_existing_server` sonucunu zaten bulduysa (None dahil) tekrar sorgulanmaz.
    """
    vm_name = vm.get("name", "Unknown")
    vm_status_val = _vm_status(vm)
    vm_id = (vm.get("vm_id") or "").strip()
    guest_hn = _inventory_guest_hostname(vm)
    # VMware sync_vms_to_inventory: hostname = Tools host_name (guest)
    # KubeVirt: hostname = guest veya VM adı; guest yoksa vm_name kullan
    row_hostname = (vm.get("hostname") or "").strip() or vm_name
    if existing is _UNSET:
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
            hostname=row_hostname,
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
            vm_name=vm_name,
            vm_guest_hostname=guest_hn or None,
        )
        db.add(existing)
        created = True
    else:
        if vm_name and existing.name != vm_name:
            existing.name = vm_name
        existing.vm_name = vm_name
        if guest_hn:
            existing.vm_guest_hostname = guest_hn
        # Hostname: guest tercih et. Elle/SSH ile konmuş ve VM adından farklıysa koru.
        cur_hn = (existing.hostname or "").strip()
        if guest_hn and (
            not cur_hn
            or cur_hn == (existing.name or "")
            or cur_hn == vm_name
            or cur_hn.lower() == (existing.vm_name or "").lower()
        ):
            existing.hostname = guest_hn
        elif not cur_hn:
            existing.hostname = row_hostname
        elif cur_hn == (existing.name or "") and row_hostname and row_hostname != vm_name:
            # Eski kayıt: hostname hâlâ VM adı, inventory guest getirmiş (VMware Tools)
            existing.hostname = row_hostname
        existing.status = vm_status_val
        if not existing.hypervisor_id:
            existing.hypervisor_id = hypervisor.id
        if vm_id and (
            not existing.hypervisor_vm_id
            or (
                # KubeVirt: eski UID → namespace/name yükselt
                "/" in vm_id and "/" not in (existing.hypervisor_vm_id or "")
            )
        ):
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

    power = vm.get("vm_power_state") or vm.get("power_state") or vm.get("status")
    if power:
        existing.vm_power_state = str(power)
    for src_key, dst in (
        ("vm_host_name", "vm_host_name"),
        ("vm_host_ref", "vm_host_ref"),
        ("vm_cluster", "vm_cluster"),
        ("vm_guest_os_full", "vm_guest_os_full"),
        ("vm_guest_ip", "vm_guest_ip"),
        ("vm_datastore", "vm_datastore"),
        ("vm_network_info", "vm_network_info"),
        ("vm_disks", "vm_disks"),
        ("vm_disk_gb", "vm_disk_gb"),
        ("vm_guest_hostname", "vm_guest_hostname"),
    ):
        val = vm.get(src_key)
        if val not in (None, "", []):
            setattr(existing, dst, val)

    db.flush()

    needs_enrichment = (
        not getattr(existing, "vm_disk_gb", None)
        or not getattr(existing, "vm_tools_status", None)
        or not getattr(existing, "vm_datastore", None)
        or not getattr(existing, "vm_last_sync", None)
        or not getattr(existing, "vm_name", None)
        or not getattr(existing, "vm_host_name", None)
    )
    if preloaded_details:
        _enrich_server_from_client(
            client, existing, vm, db, preloaded_details=preloaded_details
        )
    elif client and needs_enrichment:
        _enrich_server_from_client(client, existing, vm, db)

    try:
        from app.services.fact_learning import extract_and_store_virt_facts
        extract_and_store_virt_facts(db, existing, commit=commit_facts)
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

    from app.services.hypervisor_credentials import hv_password, hv_token, plain

    if htype == "vmware":
        try:
            from app.services.vmware.vcenter_client import VCenterClient
            client = VCenterClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hv_password(hypervisor),
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
        from app.services.ovirt.ovirt_parse import OVirtError
        try:
            from app.services.ovirt.ovirt_client import OVirtClient
            client = OVirtClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hv_password(hypervisor),
                verify_ssl=False,
                port=hypervisor.port or 443,
            )
            ok, detail = client.test_connection()
            if not ok:
                errors.append(f"oVirt bağlantı hatası: {detail or 'giriş başarısız'}")
            else:
                _prog(phase="listing", percent=8, message="VM listesi alınıyor...")
                vms = client.list_vms()
        except ImportError:
            errors.append("oVirt client modülü bulunamadı")
        except OVirtError as e:
            errors.append(f"oVirt API hatası: {str(e)}")
        except Exception as e:
            errors.append(f"oVirt bağlantı hatası: {str(e)}")
    elif htype == "proxmox":
        try:
            from app.services.hypervisor.proxmox_client import ProxmoxClient
            client = ProxmoxClient(
                host=hypervisor.ip_address or hypervisor.hostname,
                username=hypervisor.username or (hypervisor.connection_config or {}).get("username", ""),
                password=hv_password(hypervisor),
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
                password=hv_password(hypervisor),
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
            use_creds = bool(cc.get("username")) and bool(cc.get("password") or hypervisor.password)
            client = KubeVirtClient(
                api_url=cc.get("api_url") or hypervisor.hostname or hypervisor.ip_address,
                token="" if use_creds else hv_token(hypervisor),
                username=cc.get("username") or "",
                password=plain(cc.get("password")) or hv_password(hypervisor),
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

    # vCenter: eksik meta; oVirt/OLVM: her turda host/disk/OS yenile
    preloaded: dict = {}
    if (
        client
        and htype in ("vmware", "kvm")
        and vms
        and hasattr(client, "fetch_full_details_parallel")
    ):
        need = []
        for vm in vms:
            if htype == "kvm":
                need.append(vm)
                continue
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
                "%s enrichment ön-çekim: %s VM (paralel)",
                htype,
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
            before = _find_existing_server(db, hv_id, vm)
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
                existing=before,
                commit_facts=False,   # döngü 10 VM'de bir + sonunda commit eder (VM başına fsync yok)
            ):
                synced += 1
            elif was_missing_meta:
                enriched += 1
            # Küçük filolarda her VM; büyükte her 5 — UI 0/N'de kilitlenmesin.
            if track_progress and (i == 1 or i == len(vms) or i % 5 == 0):
                pct = 88 + int(10 * (i / max(len(vms), 1)))
                _prog(
                    phase="saving",
                    percent=min(98, pct),
                    message=f"Envantere kaydediliyor ({i}/{len(vms)})...",
                    vms_done=i,
                    vms_total=len(vms),
                )
            if i % 10 == 0:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    raise

        if not errors:
            seen_ids = {
                (vm.get("vm_id") or "").strip()
                for vm in vms
                if (vm.get("vm_id") or "").strip()
            }
            stale_ids = [
                sid
                for sid, vid in (
                    db.query(Server.id, Server.hypervisor_vm_id)
                    .filter(Server.hypervisor_id == hv_id, Server.hypervisor_vm_id.isnot(None))
                    .all()
                )
                if (vid or "").strip() not in seen_ids
            ]
            if stale_ids:
                from app.services.hypervisor_cleanup import delete_servers_cascade
                pruned = delete_servers_cascade(db, stale_ids)
                logger.info("Hypervisor %s: engine'de olmayan %s VM silindi", hv_id, pruned)

        hypervisor.last_sync = datetime.now(timezone.utc)
        db.add(hypervisor)
        db.commit()   # son (<10) VM'ler + fact'ler; önceden VM başına fact commit'i bunu örtüyordu
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


_HV_PARALLEL = 4   # aynı anda en çok bu kadar hypervisor (her biri kendi DB oturumunda)


def _record_sync_outcome(hypervisor_id: int, hypervisor: Hypervisor, errors: list) -> None:
    """Periyodik turun sonucunu `meta_data.sync_job` + `status` alanına yazar.

    Eskiden yalnız elle başlatılan tarama (`track_progress=True`) bunu yazıyordu; periyodik turda başarısızlık
    hiçbir yerde görünmüyordu (OLVM 11 gün boyunca "ONLINE" göründü). Kullanıcının çalışan taramasının
    üzerine yazılmaz.
    """
    try:
        job = get_sync_job(hypervisor)
        if job.get("status") == "running" and not job_is_stale_running(job):
            return
        now = datetime.now(timezone.utc).isoformat()
        if errors:
            msg = str(errors[0])[:300]
            update_sync_job(hypervisor_id, status="error", phase="error", message=msg, error=msg, last_error_at=now)
        else:
            update_sync_job(hypervisor_id, status="done", phase="done", message="Periyodik senkron tamamlandı",
                            error=None, last_success_at=now)
    except Exception:
        logger.debug("sync sonucu kaydedilemedi (hv=%s)", hypervisor_id, exc_info=True)


def _sync_one_hypervisor(session: Session, hypervisor: Hypervisor) -> dict:
    """Tek hypervisor turu: (sonuç satırı, hata listesi). Hata fırlatmaz."""
    name = hypervisor.name
    hv_id = hypervisor.id
    try:
        r = sync_hypervisor_vms(session, hypervisor)
        session.commit()
        _record_sync_outcome(hv_id, hypervisor, r["errors"])
        return {
            "name": name, "synced_count": r["synced_count"], "total_vms": r["total_vms"],
            "enriched_count": r.get("enriched_count", 0), "errors": r["errors"],
        }
    except Exception as e:
        logger.error(f"Inventory sync error for {name}: {e}", exc_info=True)
        session.rollback()
        _record_sync_outcome(hv_id, hypervisor, [str(e)])
        return {"name": name, "synced_count": 0, "total_vms": 0, "errors": [str(e)]}


def sync_all_hypervisors(db: Session) -> dict:
    """
    Tüm hypervisor'lardan VM'leri senkronize et.
    Returns: { success, total_synced, hypervisors: [{ name, synced_count, total_vms, errors }] }

    Birden fazla hypervisor varsa paralel çalışır: ulaşılamayan biri (bağlantı zaman aşımı ~10 sn)
    diğerlerinin turunu geciktirmez. Her iş parçacığı kendi DB oturumunu kullanır; sonuç sırası korunur.
    """
    # Test amaçlı sahte envanter (scripts/fake_virt_seed.py) gerçek bir yönetim API'sine bağlanamaz; atlanır
    hypervisors = [h for h in db.query(Hypervisor).all() if not (getattr(h, "meta_data", None) or {}).get("fake_seed")]
    if not hypervisors:
        return {"success": True, "total_synced": 0, "hypervisors": []}

    if len(hypervisors) == 1:
        results = [_sync_one_hypervisor(db, hypervisors[0])]
    else:
        from concurrent.futures import ThreadPoolExecutor
        from app.core.database import ThreadSessionLocal

        hv_ids = [h.id for h in hypervisors]

        def _worker(hid: int) -> dict:
            session = ThreadSessionLocal()
            try:
                hv = session.get(Hypervisor, hid)
                if hv is None:
                    return {"name": f"#{hid}", "synced_count": 0, "total_vms": 0, "errors": ["hypervisor bulunamadı"]}
                return _sync_one_hypervisor(session, hv)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=min(_HV_PARALLEL, len(hv_ids)), thread_name_prefix="inv-sync") as pool:
            results = list(pool.map(_worker, hv_ids))

    all_errors = [e for r in results for e in r["errors"]]
    return {
        "success": len(all_errors) == 0,
        "total_synced": sum(r["synced_count"] for r in results),
        "hypervisors": results,
    }
