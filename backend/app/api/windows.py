"""
Windows Management API
/windows prefix — WinRM connectivity, system info, services, event logs,
Windows Update, and Windows Exporter management.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import json

from app.core.database import get_db
from app.models.server import Server
from app.models.app_settings import AppSettings
from app.services.windows.winrm_client import WinRMClient
from app.core.encryption import encrypt_secret, decrypt_secret
from app.services.windows.windows_info_collector import WindowsInfoCollector
from app.services.windows.windows_update_service import WindowsUpdateService
from app.services.windows.windows_exporter_installer import WindowsExporterInstaller

logger = logging.getLogger(__name__)
router = APIRouter()

GLOBAL_WINRM_KEY = "global_winrm_credential"

# /live-metrics "single-flight" cache — bkz. get_live_metrics NOT açıklaması.
_LIVE_METRICS_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_LIVE_METRICS_LOCK = threading.Lock()
_LIVE_METRICS_TTL_SEC = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_server_or_404(server_id: int, db: Session) -> Server:
    s = db.query(Server).filter(Server.id == server_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadı")
    return s


def _get_global_winrm(db: Session) -> Optional[Dict[str, Any]]:
    """Retrieve and decrypt global WinRM credential from app_settings."""
    row = db.query(AppSettings).filter(AppSettings.key == GLOBAL_WINRM_KEY).first()
    if not row or not row.value:
        return None
    try:
        data = json.loads(row.value)
        if data.get("password"):
            data["password"] = decrypt_secret(data["password"])
        return data
    except Exception:
        return None


def _build_client(server: Server, db: Optional[Session] = None) -> WinRMClient:
    """Build WinRM client: server-specific credentials first, then global fallback."""
    client = WinRMClient.from_server(server)
    if client:
        return client

    # Fallback: try global WinRM credential
    if db is not None:
        gcred = _get_global_winrm(db)
        if gcred:
            host = server.ip_address or server.hostname
            if not host:
                raise HTTPException(status_code=400, detail="Sunucunun IP adresi veya hostname'i yok.")
            return WinRMClient(
                host=host,
                username=gcred["username"],
                password=gcred["password"],
                port=gcred.get("port", 5985),
                use_https=gcred.get("use_https", False),
            )

    raise HTTPException(
        status_code=400,
        detail="Bu sunucu için WinRM kimlik bilgisi bulunamadı. Global veya sunucu bazlı WinRM credential tanımlayın.",
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class WinRMCredentials(BaseModel):
    username: str
    password: str
    port: int = 5985
    use_https: bool = False
    ip_address: Optional[str] = None  # update server IP if provided


class ServiceAction(BaseModel):
    action: str  # start | stop | restart


class InstallUpdatesRequest(BaseModel):
    kb_ids: Optional[List[str]] = None  # None = all updates
    auto_reboot: bool = False


class ScheduleRebootRequest(BaseModel):
    delay_minutes: int = 5


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/servers")
def list_windows_servers(
    db: Session = Depends(get_db),
    include_unclassified: bool = False,
):
    """
    List Windows servers.
    - Confirmed: os_type contains 'windows' or connection_config.winrm=True
    - Unclassified (include_unclassified=True): os_type is empty/"other" from hypervisor sync
    """
    servers = db.query(Server).all()
    gcred = _get_global_winrm(db)  # check once for all servers
    result = []
    for s in servers:
        os_low = (s.os_type or "").lower()
        cfg = s.connection_config or {}
        is_confirmed_windows = "windows" in os_low or bool(cfg.get("winrm"))
        is_unclassified = (
            s.hypervisor_id is not None and
            os_low in ("", "other", "unknown") and
            not any(x in os_low for x in ("linux", "rhel", "centos", "ubuntu", "ol", "rocky"))
        )

        if not is_confirmed_windows and not (include_unclassified and is_unclassified):
            continue

        # winrm_configured: server-specific OR global credential available
        winrm_port = cfg.get("winrm_port")
        has_server_winrm = bool(cfg.get("winrm")) or (winrm_port and int(winrm_port) >= 5985)
        has_server_creds = bool(cfg.get("username") or cfg.get("winrm_username"))
        has_own_winrm = has_server_winrm and has_server_creds
        has_global_winrm = bool(gcred) and bool(s.ip_address or s.hostname)

        effective_port = (winrm_port or (5985 if has_server_winrm else None)) or (gcred["port"] if gcred else None)

        result.append({
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "status": s.status,
            "os_type": s.os_type or ("unclassified" if is_unclassified else ""),
            "cpu_cores": s.cpu_cores,
            "memory_gb": s.memory_gb,
            "disk_gb": getattr(s, "vm_disk_gb", None),
            "hypervisor_id": s.hypervisor_id,
            "hypervisor_name": getattr(s.hypervisor, "name", None) if s.hypervisor_id else None,
            "winrm_configured": has_own_winrm or has_global_winrm,
            "winrm_source": "server" if has_own_winrm else ("global" if has_global_winrm else None),
            "winrm_port": effective_port,
            "confirmed_windows": is_confirmed_windows,
            "ai_ready": bool(s.ai_ready),
            "windows_exporter_installed": bool(s.windows_exporter_installed),
            "windows_exporter_running": bool(s.windows_exporter_running),
        })

    # Sort: confirmed first, then by name
    result.sort(key=lambda x: (0 if x["confirmed_windows"] else 1, x["name"] or ""))
    return result


@router.post("/servers/{server_id}/test-connection")
def test_connection(server_id: int, db: Session = Depends(get_db)):
    """Test WinRM connectivity for a server."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    result = client.test_connection()
    # Update status + ai_ready in DB
    server.ai_ready = bool(result["connected"])
    if result["connected"]:
        server.status = "ONLINE"
    db.commit()
    return result


@router.post("/servers/{server_id}/save-credentials")
def save_credentials(server_id: int, creds: WinRMCredentials, db: Session = Depends(get_db)):
    """Save WinRM credentials to a server's connection_config. Optionally update IP address."""
    server = _get_server_or_404(server_id, db)
    existing = dict(server.connection_config or {})
    existing.update({
        "username": creds.username,
        "password": encrypt_secret(creds.password),
        "winrm_port": creds.port,
        "winrm_https": creds.use_https,
        "winrm": True,
    })
    server.connection_config = existing

    # Update IP address if provided
    if creds.ip_address and creds.ip_address.strip():
        server.ip_address = creds.ip_address.strip()

    if not server.os_type or "windows" not in server.os_type.lower():
        server.os_type = "windows"
    db.commit()

    # Use the freshest host value for connection test
    host = server.ip_address or server.hostname
    if not host:
        return {"saved": True, "connection_test": {"connected": False, "message": "IP adresi girilmedi, bağlantı testi yapılamadı"}}

    client = WinRMClient(
        host=host,
        username=creds.username,
        password=creds.password,
        port=creds.port,
        use_https=creds.use_https,
    )
    test = client.test_connection()
    server.ai_ready = bool(test["connected"])
    if test["connected"]:
        server.status = "ONLINE"
    db.commit()
    return {"saved": True, "connection_test": test}


@router.post("/update-ai-ready")
def update_windows_ai_ready(body: dict = None, db: Session = Depends(get_db)):
    """
    Tüm Windows sunucularında WinRM bağlantısını arka planda test eder.
    İlerleme: GET /servers/bulk-jobs/{job_id}
    body.throttled=true → not-ready 1g / ready interval (Gelişmiş ayarlar).
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone

    from sqlalchemy.orm.attributes import flag_modified

    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.core.encryption import decrypt_secret
    from app.services.platform_scope import is_windows_server
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services import bulk_job_tracker as jobs
    from app.services.runtime_settings import get_int
    from app.services.scan_throttle import should_recheck_ai_ready

    body = body or {}
    server_ids = body.get("server_ids")
    throttled = bool(body.get("throttled"))
    ready_sec = get_int("ai_ready_ready_recheck_sec")
    not_ready_sec = get_int("ai_ready_not_ready_recheck_sec")
    now = datetime.now(timezone.utc)

    q = db.query(Server).filter(Server.ip_address != None, Server.ip_address != "")  # noqa: E711
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    candidates = [s for s in q.all() if is_windows_server(s)]
    if throttled:
        before = len(candidates)
        candidates = [
            s for s in candidates
            if should_recheck_ai_ready(
                ai_ready=bool(s.ai_ready),
                last_check=s.ai_ready_last_check,
                ready_recheck_sec=ready_sec,
                not_ready_recheck_sec=not_ready_sec,
                now=now,
            )
        ]
        logger.info(
            "windows update-ai-ready throttle: %s/%s (ready=%ss not_ready=%ss)",
            len(candidates), before, ready_sec, not_ready_sec,
        )

    if not candidates:
        job_id = jobs.create_job("win_ai_ready", "Windows AI Ready", total=0, message="Windows sunucu yok")
        jobs.finish(
            job_id,
            status="done",
            message=(
                "Throttle: yeniden deneme aralığı dolmadı."
                if throttled else
                "Windows olarak sınıflandırılmış, IP'si olan sunucu bulunamadı."
            ),
            result={"tested": 0},
        )
        return {
            "queued": True,
            "job_id": job_id,
            "tested": 0, "ai_ready_count": 0, "not_ready_count": 0, "results": [],
            "throttled": throttled,
            "message": (
                "Throttle: yeniden deneme aralığı dolmadı."
                if throttled else
                "Windows olarak sınıflandırılmış, IP'si olan sunucu bulunamadı."
            ),
        }

    gcred = _get_global_winrm(db)  # şifresi çözülmüş — sadece ana thread'de oku
    # Thread'e kopyala (dict)
    gcred_copy = dict(gcred) if gcred else None

    server_snapshots = [
        {
            "id": s.id,
            "name": s.name or s.hostname or f"#{s.id}",
            "host": (s.ip_address or s.hostname or "").strip(),
            "cfg": dict(s.connection_config or {}),
        }
        for s in candidates
    ]

    workers = bulk_ssh_workers()
    job_id = jobs.create_job(
        "win_ai_ready",
        "Windows AI Ready — WinRM",
        total=len(server_snapshots),
        message=f"{len(server_snapshots)} Windows sunucu kuyruğa alındı...",
    )
    logger.info("windows update-ai-ready: %s sunucu, workers=%s job=%s throttled=%s", len(server_snapshots), workers, job_id, throttled)

    def _bg() -> None:
        def _test_one(snap: dict):
            cfg = snap["cfg"]
            host = snap["host"]
            own_username = cfg.get("username") or cfg.get("winrm_username")
            own_raw_password = cfg.get("password") or cfg.get("winrm_password")
            winrm_port_cfg = cfg.get("winrm_port")
            has_own = bool(
                cfg.get("winrm") and own_username and own_raw_password
                and winrm_port_cfg and int(winrm_port_cfg) >= 5985
            )

            used_global = False
            if has_own:
                username = own_username
                password = decrypt_secret(own_raw_password)
                port = int(winrm_port_cfg)
                use_https = bool(cfg.get("winrm_https"))
            elif gcred_copy:
                username = gcred_copy.get("username")
                password = gcred_copy.get("password")
                port = int(gcred_copy.get("port") or 5985)
                use_https = bool(gcred_copy.get("use_https"))
                used_global = True
            else:
                return snap["id"], False, "WinRM kimlik bilgisi yok (sunucuya özel veya global tanımlı değil)", False

            if not host or not username or not password:
                return snap["id"], False, "IP/hostname veya kullanıcı adı/şifre eksik", used_global

            try:
                client = WinRMClient(host=host, username=username, password=password, port=port, use_https=use_https)
                result = client.test_connection()
                return snap["id"], bool(result.get("connected")), result.get("message", ""), used_global
            except Exception as exc:
                return snap["id"], False, str(exc), used_global

        results = []
        snap_by_id = {snap["id"]: snap for snap in server_snapshots}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="winrm-ai-ready") as pool:
            futures = {pool.submit(_test_one, snap): snap for snap in server_snapshots}
            done = 0
            for fut in as_completed(futures):
                server_id, ok, message, used_global = fut.result()
                snap = snap_by_id[server_id]
                results.append({
                    "id": server_id, "name": snap["name"], "connected": ok,
                    "message": message, "used_global_credential": used_global,
                })
                done += 1
                jobs.tick(
                    job_id,
                    done=done,
                    total=len(server_snapshots),
                    ok_delta=1 if ok else 0,
                    fail_delta=0 if ok else 1,
                    message=f"WinRM test: {done}/{len(server_snapshots)}",
                )
                if done % 100 == 0 or done == len(server_snapshots):
                    logger.info("WinRM AI Ready ilerlemesi %s/%s", done, len(server_snapshots))

        thread_db = SessionLocal()
        try:
            checked_at = datetime.now(timezone.utc)
            for r in results:
                row = thread_db.query(Server).filter_by(id=r["id"]).first()
                if not row:
                    continue
                row.ai_ready = r["connected"]
                row.ai_ready_last_check = checked_at
                if r["connected"]:
                    row.status = "ONLINE"
                    if not (row.os_type or "").strip():
                        row.os_type = "windows"
                    if r["used_global_credential"] and gcred_copy:
                        new_cfg = dict(row.connection_config or {})
                        new_cfg.update({
                            "username": gcred_copy["username"],
                            "password": encrypt_secret(gcred_copy["password"]),
                            "winrm": True,
                            "winrm_port": gcred_copy.get("port", 5985),
                            "winrm_https": gcred_copy.get("use_https", False),
                            "_from_global": True,
                        })
                        row.connection_config = new_cfg
                        flag_modified(row, "connection_config")
            thread_db.commit()
            ready_count = sum(1 for r in results if r["connected"])
            logger.info("Windows AI Ready güncellendi: %s hazır, %s bağlanamadı", ready_count, len(results) - ready_count)
            jobs.finish(
                job_id,
                status="done",
                message=f"Tamamlandı: {ready_count} AI Ready, {len(results) - ready_count} bağlanamadı",
                result={
                    "tested": len(results),
                    "ai_ready_count": ready_count,
                    "not_ready_count": len(results) - ready_count,
                },
            )
        except Exception as e:
            logger.exception("Windows AI Ready DB hatası")
            thread_db.rollback()
            jobs.finish(job_id, status="error", message="Veritabanı hatası", error=str(e))
        finally:
            thread_db.close()

    threading.Thread(target=_bg, daemon=True, name="win-update-ai-ready").start()
    return {
        "queued": True,
        "job_id": job_id,
        "tested": len(server_snapshots),
        "ai_ready_count": None,
        "not_ready_count": None,
        "results": [],
        "message": f"{len(server_snapshots)} Windows sunucuda WinRM AI Ready testi arka planda başladı.",
    }


@router.get("/servers/{server_id}/info")
def get_system_info(server_id: int, db: Session = Depends(get_db)):
    """Get comprehensive system information via WMI."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    collector = WindowsInfoCollector(client)
    info = collector.collect_all()
    # Sync basic info back to DB
    hw = info.get("hardware", {})
    os_info = info.get("os", {})
    changed = False
    if hw.get("Cores") and not server.cpu_cores:
        server.cpu_cores = hw["Cores"]
        changed = True
    if hw.get("MemoryGB") and not server.memory_gb:
        server.memory_gb = int(hw["MemoryGB"])
        changed = True
    if os_info.get("Caption") and not server.os_version:
        server.os_version = os_info["Caption"]
        changed = True
    if changed:
        db.commit()
    return info


@router.get("/servers/{server_id}/performance")
def get_performance(server_id: int, db: Session = Depends(get_db)):
    """Real-time CPU/RAM/Disk utilisation."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    collector = WindowsInfoCollector(client)
    return collector.get_performance()


@router.get("/live-metrics")
def get_live_metrics(db: Session = Depends(get_db)):
    """
    Tüm AI Ready Windows sunucularından WinRM üzerinden CPU/RAM/Disk
    kullanımını paralel olarak toplar (node_exporter/Prometheus gerektirmez).
    AI Ready olmayan sunucular WinRM sorgusuna girmeden 'offline' olarak döner.

    NOT: Sonuç kısa TTL'li (20sn) bir cache + lock ("single-flight") ile
    paylaşılır. Frontend bu uç noktayı 30sn'de bir polluyor (bkz.
    WindowsLiveMetrics.tsx); 10k ölçekte binlerce Windows sunucu varsa TEK bir
    WinRM fan-out turu dakikalar sürebilir. Cache olmadan her yeni istek
    (birden fazla açık sekme/kullanıcı dahil) kendi fan-out'unu başlatır ve
    istekler tamamlanan turlardan daha hızlı birikip WinRM bağlantı fırtınasına
    ve thread havuzu tükenmesine yol açar — cache bayatken gelen ilk istek
    hesaplar, aynı anda gelenler kilidi bekleyip taze sonucu okur.
    """
    now = time.monotonic()
    with _LIVE_METRICS_LOCK:
        if _LIVE_METRICS_CACHE["data"] is not None and (now - _LIVE_METRICS_CACHE["ts"]) < _LIVE_METRICS_TTL_SEC:
            return _LIVE_METRICS_CACHE["data"]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.services.bulk_concurrency import bulk_ssh_workers
        from app.services.platform_scope import is_windows_server

        servers = [s for s in db.query(Server).all() if is_windows_server(s)]
        gcred = _get_global_winrm(db)

        ready = [s for s in servers if s.ai_ready]
        not_ready = [s for s in servers if not s.ai_ready]

        def _fetch_one(server: Server):
            try:
                client = _build_client(server, db)
            except HTTPException:
                return server.id, {"error": "WinRM kimlik bilgisi yok"}
            collector = WindowsInfoCollector(client)
            return server.id, collector.get_performance()

        perf_by_id: Dict[int, Dict[str, Any]] = {}
        if ready:
            with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="winrm-live-metrics") as pool:
                futures = {pool.submit(_fetch_one, s): s for s in ready}
                for fut in as_completed(futures):
                    sid, perf = fut.result()
                    perf_by_id[sid] = perf

        results = []
        for s in ready:
            perf = perf_by_id.get(s.id, {})
            results.append({
                "id": s.id,
                "name": s.name or s.hostname or f"#{s.id}",
                "ip_address": s.ip_address,
                "status": s.status,
                "ai_ready": True,
                "cpu_pct": perf.get("cpu_pct"),
                "mem_used_pct": perf.get("mem_used_pct"),
                "mem_total_gb": perf.get("mem_total_gb"),
                "mem_free_gb": perf.get("mem_free_gb"),
                "disks": perf.get("disks") or [],
                "uptime_days": perf.get("uptime_days"),
                "last_boot": perf.get("last_boot"),
                "error": perf.get("error"),
            })
        for s in not_ready:
            results.append({
                "id": s.id,
                "name": s.name or s.hostname or f"#{s.id}",
                "ip_address": s.ip_address,
                "status": s.status,
                "ai_ready": False,
                "cpu_pct": None, "mem_used_pct": None, "mem_total_gb": None, "mem_free_gb": None,
                "disks": [], "uptime_days": None, "last_boot": None,
                "error": "AI Ready değil — WinRM bağlantısı kurulamadı",
            })

        results.sort(key=lambda r: (0 if r["ai_ready"] else 1, r["name"] or ""))
        successful = [r for r in results if r["ai_ready"] and r["cpu_pct"] is not None]
        payload = {
            "servers": results,
            "total": len(results),
            "online": len(successful),
            "avg_cpu_pct": round(sum(r["cpu_pct"] for r in successful) / len(successful), 1) if successful else None,
            "avg_mem_pct": round(sum(r["mem_used_pct"] for r in successful) / len(successful), 1) if successful else None,
        }
        _LIVE_METRICS_CACHE["data"] = payload
        _LIVE_METRICS_CACHE["ts"] = time.monotonic()
        return payload


@router.get("/servers/{server_id}/services")
def get_services(server_id: int, include_disabled: bool = False, db: Session = Depends(get_db)):
    """List Windows services."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    collector = WindowsInfoCollector(client)
    return collector.get_services(include_disabled=include_disabled)


@router.post("/servers/{server_id}/services/{service_name}")
def manage_service(
    server_id: int,
    service_name: str,
    body: ServiceAction,
    db: Session = Depends(get_db),
):
    """Start, stop, or restart a Windows service."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)

    action = body.action.lower()
    if action == "start":
        ps = f"Start-Service -Name '{service_name}' -ErrorAction Stop; Write-Output 'OK'"
    elif action == "stop":
        ps = f"Stop-Service -Name '{service_name}' -Force -ErrorAction Stop; Write-Output 'OK'"
    elif action == "restart":
        ps = f"Restart-Service -Name '{service_name}' -Force -ErrorAction Stop; Write-Output 'OK'"
    else:
        raise HTTPException(status_code=400, detail="Geçersiz aksiyon. start|stop|restart kullanın.")

    r = client.run_ps(ps)
    return {"success": r["success"] and "OK" in r.get("stdout", ""), "output": r.get("stderr") or ""}


@router.get("/servers/{server_id}/event-logs")
def get_event_logs(
    server_id: int,
    log_name: str = "System",
    count: int = 50,
    min_level: int = 3,
    db: Session = Depends(get_db),
):
    """Fetch Windows Event Log entries (System / Application / Security)."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    collector = WindowsInfoCollector(client)
    return collector.get_event_logs(log_name=log_name, count=count, min_level=min_level)


@router.get("/servers/{server_id}/updates")
def list_updates(server_id: int, db: Session = Depends(get_db)):
    """List pending Windows updates."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    svc = WindowsUpdateService(client)
    return {"pending": svc.list_updates(), "installed": svc.get_installed_updates()}


@router.post("/servers/{server_id}/updates/install")
def install_updates(
    server_id: int,
    body: InstallUpdatesRequest,
    db: Session = Depends(get_db),
):
    """Install all or specific Windows updates."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    svc = WindowsUpdateService(client)
    if body.kb_ids:
        return svc.install_by_kb(body.kb_ids)
    return svc.install_all_updates(auto_reboot=body.auto_reboot)


@router.post("/servers/{server_id}/reboot")
def schedule_reboot(
    server_id: int,
    body: ScheduleRebootRequest,
    db: Session = Depends(get_db),
):
    """Schedule a Windows reboot."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    svc = WindowsUpdateService(client)
    return svc.schedule_reboot(delay_minutes=body.delay_minutes)


# ── Windows Exporter ──────────────────────────────────────────────────────────

@router.get("/servers/{server_id}/exporter/status")
def exporter_status(server_id: int, db: Session = Depends(get_db)):
    """Check windows_exporter installation status (WinRM canlı kontrol + DB flag senkronu)."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    installer = WindowsExporterInstaller(client)
    result = installer.check_status()

    from datetime import datetime, timezone
    server.windows_exporter_installed = bool(result.get("installed"))
    server.windows_exporter_running = bool(result.get("running"))
    server.windows_exporter_last_check = datetime.now(timezone.utc)
    db.commit()
    return result


@router.post("/servers/{server_id}/exporter/install")
def install_exporter(server_id: int, db: Session = Depends(get_db)):
    """Download and install windows_exporter as a Windows service."""
    from app.services.monitoring.prometheus_metrics import sync_windows_exporter_targets_from_db

    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    installer = WindowsExporterInstaller(client)
    result = installer.install()
    if result.get("success"):
        server.windows_exporter_installed = True
        server.windows_exporter_running = True
        db.commit()
        try:
            sync_windows_exporter_targets_from_db(db)
        except Exception as exc:
            logger.warning("windows_exporter target sync başarısız: %s", exc)
    return result


@router.post("/servers/{server_id}/exporter/start")
def start_exporter(server_id: int, db: Session = Depends(get_db)):
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    result = WindowsExporterInstaller(client).start()
    if result.get("success"):
        server.windows_exporter_running = True
        db.commit()
    return result


@router.post("/servers/{server_id}/exporter/uninstall")
def uninstall_exporter(server_id: int, db: Session = Depends(get_db)):
    from app.services.monitoring.prometheus_metrics import sync_windows_exporter_targets_from_db

    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    result = WindowsExporterInstaller(client).uninstall()
    if result.get("success"):
        server.windows_exporter_installed = False
        server.windows_exporter_running = False
        db.commit()
        try:
            sync_windows_exporter_targets_from_db(db)
        except Exception as exc:
            logger.warning("windows_exporter target sync başarısız: %s", exc)
    return result


@router.post("/exporter/install-all")
def install_exporter_all(body: dict = None, db: Session = Depends(get_db)):
    """
    Tüm AI Ready Windows sunucularına windows_exporter'ı paralel olarak kurar
    (henüz kurulu olmayanlara). Node Exporter'ın Linux'taki bulk-install akışının
    Windows eşleniği — kurulum WinRM üzerinden PowerShell ile yapılır.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.services.platform_scope import is_windows_server
    from app.services.monitoring.prometheus_metrics import sync_windows_exporter_targets_from_db

    server_ids = (body or {}).get("server_ids")
    q = db.query(Server).filter(Server.ai_ready == True)  # noqa: E712
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    candidates = [
        s for s in q.all()
        if is_windows_server(s) and not s.windows_exporter_installed
    ]

    if not candidates:
        return {"tested": 0, "installed_count": 0, "failed_count": 0, "results": [],
                "message": "Kurulacak (AI Ready, henüz windows_exporter'sız) sunucu bulunamadı."}

    # Global credential'ı thread'ler başlamadan önce ana thread'de tek seferlik oku —
    # SQLAlchemy session thread-safe olmadığı için worker thread'lerde db.query() yapılmaz.
    gcred = _get_global_winrm(db)

    def _install_one(server: Server):
        try:
            client = WinRMClient.from_server(server)
            if not client:
                if not gcred:
                    raise ValueError("WinRM kimlik bilgisi bulunamadı (sunucuya özel veya global tanımlı değil)")
                host = server.ip_address or server.hostname
                if not host:
                    raise ValueError("Sunucunun IP adresi veya hostname'i yok")
                client = WinRMClient(
                    host=host,
                    username=gcred["username"],
                    password=gcred["password"],
                    port=gcred.get("port", 5985),
                    use_https=gcred.get("use_https", False),
                )
            result = WindowsExporterInstaller(client).install()
            return server.id, server.name, bool(result.get("success")), result.get("error") or ""
        except Exception as exc:
            return server.id, server.name, False, str(exc)

    results = []
    with ThreadPoolExecutor(max_workers=10, thread_name_prefix="winexp-install") as pool:
        futures = {pool.submit(_install_one, s): s for s in candidates}
        for fut in as_completed(futures):
            sid, name, ok, err = fut.result()
            results.append({"id": sid, "name": name, "success": ok, "error": err})

    for r in results:
        if r["success"]:
            row = db.query(Server).filter_by(id=r["id"]).first()
            if row:
                row.windows_exporter_installed = True
                row.windows_exporter_running = True
    db.commit()

    try:
        sync_windows_exporter_targets_from_db(db)
    except Exception as exc:
        logger.warning("windows_exporter target sync başarısız: %s", exc)

    installed = sum(1 for r in results if r["success"])
    return {
        "tested": len(results),
        "installed_count": installed,
        "failed_count": len(results) - installed,
        "results": sorted(results, key=lambda r: r["name"] or ""),
    }


# ── PS execution (power-user) ─────────────────────────────────────────────────

class PSRequest(BaseModel):
    script: str


@router.post("/servers/{server_id}/run-ps")
def run_powershell(server_id: int, body: PSRequest, db: Session = Depends(get_db)):
    """Execute arbitrary PowerShell on a Windows server (admin only)."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    return client.run_ps(body.script)


class WindowsAdHocRequest(BaseModel):
    server_ids: List[int]
    script: str


@router.post("/adhoc")
def run_windows_adhoc(req: WindowsAdHocRequest, db: Session = Depends(get_db)):
    """
    Seçili Windows sunucularında paralel PowerShell komutu çalıştırır
    (WinRM üzerinden) — Linux tarafındaki Ansible ad-hoc akışının Windows eşleniği.
    SADECE Windows olarak sınıflandırılmış, IP'si olan sunucularda çalışır.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.platform_scope import is_windows_server

    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    servers = [s for s in servers if is_windows_server(s)]
    servers_with_ip = [s for s in servers if s.ip_address and s.ip_address.strip()]
    servers_without_ip = [s for s in servers if not (s.ip_address and s.ip_address.strip())]

    if not servers_with_ip:
        raise HTTPException(
            status_code=400,
            detail="Seçili Windows sunucularının hiçbirinde IP adresi yok.",
        )

    # Global credential'ı thread'ler başlamadan önce tek seferlik oku (thread-safety)
    gcred = _get_global_winrm(db)

    def _run_one(server: Server):
        try:
            client = WinRMClient.from_server(server)
            if not client:
                if not gcred:
                    return server.name, {"success": False, "stdout": "", "stderr": "WinRM kimlik bilgisi yok (sunucuya özel veya global tanımlı değil)", "exit_code": -1}
                host = server.ip_address or server.hostname
                client = WinRMClient(
                    host=host,
                    username=gcred["username"],
                    password=gcred["password"],
                    port=gcred.get("port", 5985),
                    use_https=gcred.get("use_https", False),
                )
            return server.name, client.run_ps(req.script)
        except Exception as exc:
            return server.name, {"success": False, "stdout": "", "stderr": str(exc), "exit_code": -1}

    results: Dict[str, Any] = {}
    failed: List[str] = []
    with ThreadPoolExecutor(max_workers=10, thread_name_prefix="win-adhoc") as pool:
        futures = {pool.submit(_run_one, s): s for s in servers_with_ip}
        for fut in as_completed(futures):
            name, res = fut.result()
            ok = bool(res.get("success"))
            results[name] = {"rc": 0 if ok else 1, "stdout": res.get("stdout", ""), "stderr": res.get("stderr", "")}
            if not ok:
                failed.append(name)

    msg = f"{len(servers_with_ip)} Windows sunucuda PowerShell çalıştırıldı"
    if servers_without_ip:
        msg += f". ATLANMIŞ ({len(servers_without_ip)}): {', '.join(s.name for s in servers_without_ip[:5])}"
        if len(servers_without_ip) > 5:
            msg += f" ve {len(servers_without_ip) - 5} diğer"

    return {
        "success": True,
        "message": msg,
        "results": results,
        "failed": failed,
        "skipped": [s.name for s in servers_without_ip],
    }


# ── Global WinRM Credential ───────────────────────────────────────────────────

class GlobalWinRMRequest(BaseModel):
    username: str
    password: str
    port: int = 5985
    use_https: bool = False


@router.get("/global-credential")
def get_global_winrm_credential(db: Session = Depends(get_db)):
    """Return global WinRM credential (password masked)."""
    gcred = _get_global_winrm(db)
    if not gcred:
        return {"configured": False}
    return {
        "configured": True,
        "username": gcred.get("username", ""),
        "port": gcred.get("port", 5985),
        "use_https": gcred.get("use_https", False),
        "has_password": bool(gcred.get("password")),
    }


@router.post("/global-credential")
def save_global_winrm_credential(body: GlobalWinRMRequest, db: Session = Depends(get_db)):
    """Save (or update) the global WinRM credential (password encrypted at rest)."""
    data = {
        "username": body.username,
        "password": encrypt_secret(body.password),
        "port": body.port,
        "use_https": body.use_https,
    }
    row = db.query(AppSettings).filter(AppSettings.key == GLOBAL_WINRM_KEY).first()
    if row:
        row.value = json.dumps(data)
    else:
        db.add(AppSettings(key=GLOBAL_WINRM_KEY, value=json.dumps(data)))
    db.commit()
    return {"saved": True, "username": body.username, "port": body.port}


@router.delete("/global-credential", status_code=204)
def delete_global_winrm_credential(db: Session = Depends(get_db)):
    """Remove the global WinRM credential."""
    row = db.query(AppSettings).filter(AppSettings.key == GLOBAL_WINRM_KEY).first()
    if row:
        db.delete(row)
        db.commit()


@router.post("/global-credential/apply")
def apply_global_winrm_credential(db: Session = Depends(get_db)):
    """Global WinRM credential — yalnızca Windows sunuculara (Linux atlanır)."""
    from app.services.platform_scope import is_windows_server

    gcred = _get_global_winrm(db)
    if not gcred:
        raise HTTPException(status_code=400, detail="Global WinRM credential tanımlanmamış")

    servers = db.query(Server).all()
    updated = []
    skipped_linux = 0
    for s in servers:
        if not is_windows_server(s):
            skipped_linux += 1
            continue
        cfg = s.connection_config or {}
        winrm_port = cfg.get("winrm_port")
        has_own = bool(cfg.get("winrm")) and bool(cfg.get("username")) and \
                  bool(winrm_port and int(winrm_port) >= 5985)
        if has_own:
            continue
        cfg.update({
            "username": gcred["username"],
            "password": encrypt_secret(gcred["password"]),
            "winrm_port": gcred["port"],
            "winrm_https": gcred["use_https"],
            "winrm": True,
            "_from_global": True,
        })
        if not s.os_type or "windows" not in (s.os_type or "").lower():
            s.os_type = "windows"
        s.connection_config = cfg
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(s, "connection_config")
        updated.append(s.name or str(s.id))

    db.commit()
    return {
        "applied_to": len(updated),
        "servers": updated,
        "skipped_linux": skipped_linux,
        "message": f"{len(updated)} Windows sunucuya uygulandı ({skipped_linux} Linux atlandı)",
    }


@router.post("/global-credential/test")
def test_global_winrm_credential(body: GlobalWinRMRequest):
    """Quick connectivity test using the provided global credentials against no specific host."""
    return {
        "message": "Global credential kaydedildi. Sunucular üzerinde test etmek için 'Tümüne Uygula' butonunu kullanın.",
        "username": body.username,
        "port": body.port,
    }


