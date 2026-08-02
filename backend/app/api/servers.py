"""
Servers API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.core.inventory_guard import require_integrations_inventory
from app.services.inventory_dedup import tag_inventory_source
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.schemas.server import ServerCreate, ServerUpdate, ServerResponse
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller
from app.services.monitoring.prometheus_metrics import node_exporter_up_for_server
from app.services.monitoring.server_health_checker import ServerHealthChecker

logger = logging.getLogger(__name__)
router = APIRouter()


def _mask_conn_config(cfg: dict | None) -> dict:
    """Şifre/anahtar alanlarını kaldırır, yalnızca bağlantı meta bilgisini döner."""
    if not cfg:
        return {}
    return {
        "username":     cfg.get("username") or "",
        "port":         cfg.get("port") or 22,
        "has_password":    bool(cfg.get("password")),
        "has_private_key": bool(cfg.get("private_key")),
        "has_sudo_password": bool(cfg.get("sudo_password")),
    }


def _parse_os_release(raw: str) -> dict:
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


@router.post("/update-ai-ready")
def update_ai_ready(body: dict = None, db: Session = Depends(get_db)):
    """
    Linux sunucularda SSH testini arka planda çalıştırır (Windows hariç).
    HTTP hemen döner — yüzlerce sunucuda nginx HTML timeout'u önlenir.
    WinRM için: POST /windows/update-ai-ready
    İlerleme: GET /servers/bulk-jobs/{job_id}

    body.throttled=true → AI Ready olanlar ready_recheck, olmayanlar not_ready_recheck
    aralığına göre atlanır (auto-onboarding). Manuel UI çağrısı throttle etmez.
    """
    import threading
    from datetime import datetime, timezone
    from app.models.credential import GlobalCredential
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services.platform_scope import is_windows_server
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services.ssh_credentials import resolve_ssh_creds
    from app.services import bulk_job_tracker as jobs
    from app.services.runtime_settings import get_int
    from app.services.scan_throttle import should_recheck_ai_ready

    body = body or {}
    server_ids = body.get("server_ids")
    throttled = bool(body.get("throttled"))
    ready_sec = get_int("ai_ready_ready_recheck_sec")
    not_ready_sec = get_int("ai_ready_not_ready_recheck_sec")
    now = datetime.now(timezone.utc)

    q = db.query(Server)
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    server_list = [
        s for s in q.filter(
            Server.ip_address != None,  # noqa: E711
            Server.ip_address != "",
        ).all()
        if not is_windows_server(s)
    ]
    if throttled:
        before = len(server_list)
        server_list = [
            s for s in server_list
            if should_recheck_ai_ready(
                ai_ready=bool(s.ai_ready),
                last_check=s.ai_ready_last_check,
                ready_recheck_sec=ready_sec,
                not_ready_recheck_sec=not_ready_sec,
                now=now,
            )
        ]
        logger.info(
            "update-ai-ready throttle: %s/%s sunucu teste alındı (ready=%ss not_ready=%ss)",
            len(server_list), before, ready_sec, not_ready_sec,
        )

    global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                  or db.query(GlobalCredential).first()

    server_snapshots = []
    for s in server_list:
        creds = resolve_ssh_creds(s, global_cred=global_cred)
        if not creds.get("has_secret"):
            continue
        server_snapshots.append({
            "id": s.id,
            "ip": creds["host"],
            "name": s.name,
            "username": creds["username"],
            "password": creds["password"],
            "private_key": creds["private_key"],
            "port": creds["port"],
        })

    workers = bulk_ssh_workers()
    queued = len(server_snapshots)
    job_id = jobs.create_job(
        "ai_ready",
        "AI Ready — SSH kontrolü",
        total=queued,
        message=f"{queued} Linux sunucu kuyruğa alındı..." if queued else "Test edilecek sunucu yok",
    )
    logger.info("update-ai-ready (arka plan kuyruk): %s sunucu, workers=%s job=%s throttled=%s", queued, workers, job_id, throttled)

    def _bg() -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.services.ssh_manager import SSHManager

        if not server_snapshots:
            jobs.finish(job_id, status="done", message="Test edilecek Linux sunucu bulunamadı.", result={"tested": 0})
            return

        def _test_one(snap: dict) -> tuple:
            try:
                ssh = SSHManager(
                    host=snap["ip"],
                    username=snap["username"],
                    password=snap["password"],
                    private_key=snap["private_key"],
                    port=snap["port"],
                )
                ok = bool(ssh.connect())
                if ok:
                    ssh.close()
                return snap["id"], ok
            except Exception:
                return snap["id"], False

        results = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ai-ready") as pool:
            futs = [pool.submit(_test_one, s) for s in server_snapshots]
            done = 0
            for f in as_completed(futs):
                sid, ok = f.result()
                results[sid] = ok
                done += 1
                jobs.tick(
                    job_id,
                    done=done,
                    total=len(server_snapshots),
                    ok_delta=1 if ok else 0,
                    fail_delta=0 if ok else 1,
                    message=f"SSH test: {done}/{len(server_snapshots)}",
                )
                if done % 100 == 0 or done == len(server_snapshots):
                    logger.info("AI Ready (arka plan) %s/%s", done, len(server_snapshots))

        thread_db = SessionLocal()
        try:
            ready_count = not_ready_count = 0
            checked_at = datetime.now(timezone.utc)
            for srv_id, ok in results.items():
                thread_db.query(Server).filter_by(id=srv_id).update({
                    "ai_ready": ok,
                    "ai_ready_last_check": checked_at,
                })
                if ok:
                    ready_count += 1
                else:
                    not_ready_count += 1
            thread_db.commit()
            logger.info(
                "AI Ready tamamlandı: %s hazır, %s bağlanamadı",
                ready_count, not_ready_count,
            )
            jobs.finish(
                job_id,
                status="done",
                message=f"Tamamlandı: {ready_count} AI Ready, {not_ready_count} bağlanamadı",
                result={"tested": queued, "ai_ready": ready_count, "not_ready": not_ready_count},
            )
        except Exception as e:
            logger.exception("AI Ready arka plan DB hatası")
            thread_db.rollback()
            jobs.finish(job_id, status="error", message="Veritabanı hatası", error=str(e))
        finally:
            thread_db.close()

    if queued:
        threading.Thread(target=_bg, daemon=True, name="update-ai-ready").start()
    else:
        jobs.finish(job_id, status="done", message="Test edilecek Linux sunucu bulunamadı.", result={"tested": 0})

    return {
        "queued": True,
        "job_id": job_id,
        "tested": queued,
        "ai_ready": None,
        "not_ready": None,
        "workers": workers,
        "throttled": throttled,
        "message": (
            f"{queued} Linux sunucuda SSH AI Ready testi arka planda başladı. "
            "Birkaç dakika içinde liste güncellenir (Windows hariç)."
            if queued else
            ("Throttle: yeniden deneme aralığı dolmadı — test atlandı." if throttled else
             "Test edilecek Linux sunucu bulunamadı (credential/IP gerekli).")
        ),
    }


@router.post("/refresh-os-info")
def refresh_os_info(body: dict = None, db: Session = Depends(get_db)):
    """SSH ile Linux sunuculardan OS/kernel bilgisini arka planda günceller."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services.platform_scope import is_linux_server
    from app.services.ssh_credentials import resolve_ssh_creds
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.models.credential import GlobalCredential
    from app.services import bulk_job_tracker as jobs

    server_ids = (body or {}).get("server_ids")
    q = db.query(Server)
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    candidates = q.filter(Server.ip_address != None).all()  # noqa: E711
    servers = [s for s in candidates if is_linux_server(s)]

    global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                  or db.query(GlobalCredential).first()

    snapshots = []
    for srv in servers:
        creds = resolve_ssh_creds(srv, global_cred=global_cred)
        if not creds.get("has_secret"):
            continue
        snapshots.append({
            "id": srv.id,
            "ip": creds["host"],
            "os_type": srv.os_type,
            "username": creds["username"],
            "password": creds["password"],
            "private_key": creds["private_key"],
            "port": creds["port"],
        })

    workers = bulk_ssh_workers()
    queued = len(snapshots)
    job_id = jobs.create_job(
        "os_refresh",
        "OS bilgisi yenileme",
        total=queued,
        message=f"{queued} Linux sunucu kuyruğa alındı..." if queued else "Yenilenecek sunucu yok",
    )
    logger.info("refresh-os-info (arka plan): %s sunucu, workers=%s job=%s", queued, workers, job_id)

    def _bg() -> None:
        from app.services.ssh_manager import SSHManager

        if not snapshots:
            jobs.finish(job_id, status="done", message="Yenilenecek Linux sunucu bulunamadı.", result={"updated": 0})
            return

        def _update_one(snap):
            try:
                ssh = SSHManager(
                    host=snap["ip"],
                    username=snap["username"] or "root",
                    password=snap["password"],
                    private_key=snap["private_key"],
                    port=snap["port"],
                )
                if not ssh.connect():
                    return snap["id"], None, "SSH bağlanamadı"
                _, raw, _ = ssh.execute_command("cat /etc/os-release 2>/dev/null")
                info = _parse_os_release(raw)
                _, k_out, _ = ssh.execute_command("uname -r")
                ssh.close()
                return snap["id"], {
                    "os_version": info.get("PRETTY_NAME"),
                    "os_release_id": info.get("ID"),
                    "os_version_id": info.get("VERSION_ID"),
                    "os_type": info.get("ID") or snap["os_type"],
                    "kernel_version": k_out.strip() or None,
                }, None
            except Exception as e:
                return snap["id"], None, str(e)

        results = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="os-info") as pool:
            futs = [pool.submit(_update_one, s) for s in snapshots]
            done = 0
            for f in as_completed(futs):
                row = f.result()
                results.append(row)
                done += 1
                ok = row[1] is not None
                jobs.tick(
                    job_id,
                    done=done,
                    total=len(snapshots),
                    ok_delta=1 if ok else 0,
                    fail_delta=0 if ok else 1,
                    message=f"OS bilgisi: {done}/{len(snapshots)}",
                )
                if done % 100 == 0 or done == len(snapshots):
                    logger.info("OS info (arka plan) %s/%s", done, len(snapshots))

        bg = SessionLocal()
        try:
            updated = failed = 0
            for srv_id, info, err in results:
                if info:
                    srv = bg.query(Server).filter_by(id=srv_id).first()
                    if srv:
                        for k, v in info.items():
                            if v:
                                setattr(srv, k, v)
                        updated += 1
                else:
                    failed += 1
            bg.commit()
            logger.info("OS info tamamlandı: updated=%s failed=%s", updated, failed)
            jobs.finish(
                job_id,
                status="done",
                message=f"Tamamlandı: {updated} güncellendi, {failed} başarısız",
                result={"updated": updated, "failed": failed},
            )
        except Exception as e:
            logger.exception("OS info arka plan DB hatası")
            bg.rollback()
            jobs.finish(job_id, status="error", message="Veritabanı hatası", error=str(e))
        finally:
            bg.close()

    if queued:
        threading.Thread(target=_bg, daemon=True, name="refresh-os-info").start()
    else:
        jobs.finish(job_id, status="done", message="Yenilenecek Linux sunucu bulunamadı.", result={"updated": 0})

    return {
        "queued": True,
        "job_id": job_id,
        "updated": queued,
        "failed": 0,
        "workers": workers,
        "message": (
            f"{queued} Linux sunucuda OS bilgisi arka planda yenileniyor."
            if queued else
            "Yenilenecek Linux sunucu bulunamadı."
        ),
    }


@router.get("/")
def list_servers(
    db: Session = Depends(get_db),
    include_node_exporter_status: bool = False,
    platform: str | None = None,
):
    """
    Sunucuları listele.

    `platform` verilmezse (varsayılan) tüm sunucular döner — Ansible, Paket
    Yöneticisi, Sistem Güncelleme gibi platform-bağımsız araçlar bunu kullanır.
    `platform=linux` — yalnızca Linux modül envanteri (VM, Windows, Exadata hariç).
    `platform=exadata` — Exadata node'larına bağlı sunucular.

    NOT: kasıtlı olarak senkron `def` — include_node_exporter_status=True iken
    her sunucu için SSH (NodeExporterInstaller) senkron/bloklayan I/O yapar; bu
    hiç `await` kullanmayan bir gövdeydi ama `async def` olduğu için o SSH turu
    boyunca event loop'u kilitliyordu (10k sunucuda ciddi bir "hang" riski).
    FastAPI senkron endpoint'leri otomatik thread pool'da çalıştırır.
    """
    try:
        query = db.query(Server)
        if platform in ("linux", "windows", "virt", "exadata"):
            from app.services.platform_scope import apply_server_platform_filter
            servers = apply_server_platform_filter(query, platform, db).all()
        else:
            servers = query.all()
        result = []
        conn_config = None
        for s in servers:
            conn_config = getattr(s, "connection_config", None) or {}
            # Hypervisor adı (relationship üzerinden)
            hv_name = s.hypervisor.name if s.hypervisor else None
            server_data = {
                "id": s.id,
                "name": s.name or "",
                "hostname": s.hostname or "",
                "ip_address": s.ip_address or "",
                "status": s.status or "UNKNOWN",
                "os_type":        s.os_type or "",
                "os_version":     s.os_version or "",
                "os_release_id":  s.os_release_id or "",
                "os_version_id":  s.os_version_id or "",
                "kernel_version": s.kernel_version or "",
                "server_type": s.server_type or "VIRTUAL",
                "cpu_cores": s.cpu_cores or 0,
                "memory_gb": s.memory_gb or 0,
                "ai_ready": bool(s.ai_ready),
                "hypervisor_id":   s.hypervisor_id,
                "hypervisor_name": hv_name,
                "connection_config": _mask_conn_config(conn_config),
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
async def list_ai_ready_servers(
    platform: str | None = None,
    db: Session = Depends(get_db),
):
    """AI ready sunucuları listele — isteğe bağlı modül filtresi."""
    try:
        from app.services.platform_scope import apply_server_platform_filter
        query = db.query(Server).filter(Server.ai_ready == True)
        query = apply_server_platform_filter(query, platform, db)
        servers = query.all()
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
            "connection_config": _mask_conn_config(s.connection_config),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None
        } for s in servers]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing AI ready servers: {str(e)}")

@router.post("/", response_model=ServerResponse, status_code=201)
async def create_server(server: ServerCreate, request: Request, db: Session = Depends(get_db)):
    """Yeni sunucu ekle (yalnızca Entegrasyonlar)"""
    require_integrations_inventory(request)
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
                    db_server.ai_ready = True
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
                        db_server.kernel_version = kernel_out.strip()
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
                    db_server.ai_ready = False
                    db_server.status = "OFFLINE"
                db.commit()
                db.refresh(db_server)
            except Exception as ssh_err:
                db_server.ai_ready = False
                logger.warning(f"SSH connect failed for new server {db_server.name}: {ssh_err}")
                db.commit()
                db.refresh(db_server)

        tag_inventory_source(db_server, "manual", {"server_type": server_type})
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(db_server, "connection_config")
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
            "connection_config": _mask_conn_config(db_server.connection_config),
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

        monitoring_fields = {"name", "ip_address", "status", "node_exporter_installed"}
        if monitoring_fields.intersection(update_data.keys()):
            from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
            sync_node_exporter_targets_from_db(db)
        
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
            "connection_config": _mask_conn_config(db_server.connection_config),
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

        from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
        sync_node_exporter_targets_from_db(db)

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
        elif server.connection_config.get("username") and server.ip_address:
            from app.services.ssh_manager import SSHManager
            ssh = SSHManager(
                host=server.ip_address,
                username=server.connection_config.get("username"),
                password=server.connection_config.get("password"),
                private_key=server.connection_config.get("private_key"),
                port=int(server.connection_config.get("port", 22) or 22),
            )
            try:
                server.ai_ready = bool(ssh.connect())
                ssh.close()
            except Exception:
                server.ai_ready = False

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


@router.get("/bulk-jobs")
def list_bulk_jobs(active: bool = False):
    """Aktif/bitmiş toplu işler (AI Ready, health check, OS refresh...)."""
    from app.services import bulk_job_tracker as jobs
    return {"jobs": jobs.list_jobs(active_only=active)}


@router.get("/bulk-jobs/{job_id}")
def get_bulk_job(job_id: str):
    from app.services import bulk_job_tracker as jobs
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İş bulunamadı")
    return job


@router.post("/check-health")
async def check_all_servers_health(
    background: bool = True,
    db: Session = Depends(get_db),
):
    """Tüm sunucuların durumlarını kontrol et (TCP).

    Varsayılan: arka planda çalışır, hemen job_id döner (UI ilerleme ekranı).
    background=false ile senkron (eski davranış) çalıştırılabilir.
    """
    import threading
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.services import bulk_job_tracker as jobs

    if not background:
        try:
            stats = await ServerHealthChecker.update_server_statuses_async(db)
            msg = "Sunucu durumları güncellendi"
            if stats.get("offline", 0) == stats.get("checked", 0) and stats.get("checked", 0) > 0:
                msg += ". Hiç ONLINE yok; backend loglarında 'OFFLINE: ... sebep:' satırlarına bakın."
            return {"success": True, "queued": False, "message": msg, "stats": stats}
        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Health check error: {str(e)}")

    total_hint = db.query(Server).count()
    job_id = jobs.create_job(
        "health_check",
        "Durum kontrolü (TCP)",
        total=total_hint,
        message=f"{total_hint} sunucu kontrol edilecek...",
    )

    def _bg() -> None:
        bg = SessionLocal()
        try:
            def _prog(done, total):
                jobs.tick(
                    job_id,
                    done=done,
                    total=total,
                    message=f"Kontrol: {done}/{total}",
                )

            stats = ServerHealthChecker.update_server_statuses(bg, on_progress=_prog)
            if stats.get("error"):
                jobs.finish(job_id, status="error", message="Durum kontrolü başarısız", error=str(stats["error"]))
                return
            jobs.update_job(
                job_id,
                ok_count=int(stats.get("online") or 0),
                fail_count=int(stats.get("offline") or 0),
            )
            jobs.finish(
                job_id,
                status="done",
                message=(
                    f"Tamamlandı: {stats.get('checked', 0)} kontrol · "
                    f"{stats.get('online', 0)} online · {stats.get('offline', 0)} offline · "
                    f"{stats.get('updated', 0)} güncellendi"
                ),
                result=stats,
            )
        except Exception as e:
            logger.exception("Health check arka plan hatası")
            jobs.finish(job_id, status="error", message="Durum kontrolü hatası", error=str(e))
        finally:
            bg.close()

    threading.Thread(target=_bg, daemon=True, name="check-health").start()
    return {
        "success": True,
        "queued": True,
        "job_id": job_id,
        "message": f"Durum kontrolü arka planda başladı ({total_hint} sunucu).",
        "stats": None,
    }

@router.post("/{server_id}/check-health")
def check_server_health(server_id: int, db: Session = Depends(get_db)):
    """
    Tek bir sunucunun durumunu kontrol et ve güncelle.

    NOT: kasıtlı olarak senkron `def` — deep=True tam SSH/WinRM auth denemesi
    yapar (senkron/bloklayan); yanlış kimlik bilgisi veya erişilemeyen bir
    sunucuda timeout'a kadar sürebilir. async def olsaydı bu süre boyunca
    event loop kilitlenirdi.
    """
    try:
        server = db.query(Server).filter(Server.id == server_id).first()
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        
        old_status = server.status
        new_status, _ = ServerHealthChecker.check_server_status(server, db, deep=True)
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


def _fetch_vcenter_vm_metrics(server: Server, db: Session) -> dict:
    """hypervisor_vm_id / name-ip ile vCenter'dan CPU/RAM/disk/net anlık metrik."""
    import time as _time
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.services.vmware.vcenter_client import VCenterClient

    cached = _vcenter_cache.get(server.id)
    if cached and cached[1] > _time.time():
        return cached[0]

    hyps = []
    if server.hypervisor_id:
        hyp = db.query(Hypervisor).filter(
            Hypervisor.id == server.hypervisor_id,
            Hypervisor.hypervisor_type == HypervisorType.VMWARE,
        ).first()
        if hyp:
            hyps = [hyp]
    if not hyps:
        hyps = db.query(Hypervisor).filter(
            Hypervisor.hypervisor_type == HypervisorType.VMWARE
        ).all()

    vcenter_stats: dict = {}
    for hyp in hyps:
        # ip_address öncelikli — hostname alanına yanlışlıkla görünen ad girilmiş olabilir
        vc_host = (hyp.ip_address or hyp.hostname or "").strip()
        vc_pass = hyp.password or (hyp.connection_config or {}).get("password", "")
        if not (vc_host and hyp.username and vc_pass):
            continue
        try:
            vc = VCenterClient(host=vc_host, username=hyp.username, password=vc_pass)
            if not vc.login():
                continue
            vm_id = server.hypervisor_vm_id
            if not vm_id:
                vm_id = vc.find_vm_by_name_or_ip(name=server.name, ip=server.ip_address or "")
            if vm_id:
                stats = vc.get_vm_live_metrics(str(vm_id))
                if stats:
                    vcenter_stats = stats
            vc.logout()
            if vcenter_stats:
                break
        except Exception as e:
            logger.warning(f"vCenter metrics fallback error: {e}")

    if vcenter_stats:
        _vcenter_cache[server.id] = (vcenter_stats, _time.time() + 60)
    return vcenter_stats


def _vcenter_metrics_payload(server_id: int, vcenter_stats: dict) -> dict:
    mtmb = vcenter_stats.get("mem_total_mb") or 0
    mumb = vcenter_stats.get("mem_used_mb") or 0
    return {
        "server_id": server_id,
        "has_node_exporter": False,
        "source": "vcenter",
        "power_state": vcenter_stats.get("power_state"),
        "cpu_percent": vcenter_stats.get("cpu_percent"),
        "mem_percent": vcenter_stats.get("mem_percent"),
        "disk_percent": vcenter_stats.get("disk_percent"),
        "load1": None,
        "load5": None,
        "uptime_seconds": vcenter_stats.get("uptime_seconds"),
        "mem_total_gb": round(mtmb / 1024, 1) if mtmb else None,
        "mem_used_gb": round(mumb / 1024, 1) if mumb else None,
        "disk_total_gb": vcenter_stats.get("disk_total_gb"),
        "disk_avail_gb": vcenter_stats.get("disk_avail_gb"),
        "cpu_num": vcenter_stats.get("num_cpu"),
        "cpu_mhz": vcenter_stats.get("cpu_mhz"),
        "disk_read_iops": vcenter_stats.get("disk_read_iops"),
        "disk_write_iops": vcenter_stats.get("disk_write_iops"),
        "net_rx_kbps": vcenter_stats.get("net_rx_kbps"),
        "net_tx_kbps": vcenter_stats.get("net_tx_kbps"),
    }


@router.get("/{server_id}/metrics-summary")
async def get_server_metrics_summary(server_id: int, db: Session = Depends(get_db)):
    """Prometheus/Node Exporter verisini doner. Veri yoksa ve sunucu VIRTUAL ise vCenter'dan alir."""
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

    if not has_prom and server.server_type == "VIRTUAL":
        import asyncio
        vcenter_stats = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _fetch_vcenter_vm_metrics(server, db)
        )
        if vcenter_stats:
            return _vcenter_metrics_payload(server_id, vcenter_stats)

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


@router.get("/{server_id}/vm-live-metrics")
async def get_vm_live_metrics(server_id: int, db: Session = Depends(get_db)):
    """Sanallaştırma VM detayı — her zaman vCenter QuickStats + Perf (CPU/RAM/disk/net)."""
    import asyncio
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if server.server_type != "VIRTUAL":
        raise HTTPException(status_code=400, detail="Yalnızca sanal makineler için")
    vcenter_stats = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _fetch_vcenter_vm_metrics(server, db)
    )
    if not vcenter_stats:
        return {
            "server_id": server_id,
            "source": None,
            "error": "vCenter metrik alınamadı (VM ID / bağlantı / Tools)",
            "cpu_percent": None,
            "mem_percent": None,
            "disk_percent": None,
            "disk_read_iops": None,
            "disk_write_iops": None,
            "net_rx_kbps": None,
            "net_tx_kbps": None,
        }
    return _vcenter_metrics_payload(server_id, vcenter_stats)

