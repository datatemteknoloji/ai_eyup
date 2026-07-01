"""
Windows Management API
/windows prefix — WinRM connectivity, system info, services, event logs,
Windows Update, and Windows Exporter management.
"""
from __future__ import annotations

import logging
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
    # Update status in DB
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
    if test["connected"]:
        server.status = "ONLINE"
        db.commit()
    return {"saved": True, "connection_test": test}


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
    """Real-time CPU/RAM utilisation."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    collector = WindowsInfoCollector(client)
    return collector.get_performance()


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
    """Check windows_exporter installation status."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    installer = WindowsExporterInstaller(client)
    return installer.check_status()


@router.post("/servers/{server_id}/exporter/install")
def install_exporter(server_id: int, db: Session = Depends(get_db)):
    """Download and install windows_exporter as a Windows service."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    installer = WindowsExporterInstaller(client)
    result = installer.install()
    if result.get("success"):
        # Add to Prometheus windows_exporter targets
        _add_prometheus_target(server)
    return result


@router.post("/servers/{server_id}/exporter/start")
def start_exporter(server_id: int, db: Session = Depends(get_db)):
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    return WindowsExporterInstaller(client).start()


@router.post("/servers/{server_id}/exporter/uninstall")
def uninstall_exporter(server_id: int, db: Session = Depends(get_db)):
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    return WindowsExporterInstaller(client).uninstall()


# ── PS execution (power-user) ─────────────────────────────────────────────────

class PSRequest(BaseModel):
    script: str


@router.post("/servers/{server_id}/run-ps")
def run_powershell(server_id: int, body: PSRequest, db: Session = Depends(get_db)):
    """Execute arbitrary PowerShell on a Windows server (admin only)."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server, db)
    return client.run_ps(body.script)


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
    """
    Apply the global WinRM credential to all Windows servers that don't have
    their own per-server credential configured. Also marks them as os_type=windows.
    """
    gcred = _get_global_winrm(db)
    if not gcred:
        raise HTTPException(status_code=400, detail="Global WinRM credential tanımlanmamış")

    servers = db.query(Server).all()
    updated = []
    for s in servers:
        os_low = (s.os_type or "").lower()
        if "windows" not in os_low:
            continue
        cfg = s.connection_config or {}
        # Skip servers that already have their own WinRM credential
        winrm_port = cfg.get("winrm_port")
        has_own = bool(cfg.get("winrm")) and bool(cfg.get("username")) and \
                  bool(winrm_port and int(winrm_port) >= 5985)
        if has_own:
            continue
        cfg.update({
            "username": gcred["username"],
            "password": gcred["password"],
            "winrm_port": gcred["port"],
            "winrm_https": gcred["use_https"],
            "winrm": True,
            "_from_global": True,
        })
        s.connection_config = cfg
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(s, "connection_config")
        updated.append(s.name or str(s.id))

    db.commit()
    return {"applied_to": len(updated), "servers": updated}


@router.post("/global-credential/test")
def test_global_winrm_credential(body: GlobalWinRMRequest):
    """Quick connectivity test using the provided global credentials against no specific host."""
    return {
        "message": "Global credential kaydedildi. Sunucular üzerinde test etmek için 'Tümüne Uygula' butonunu kullanın.",
        "username": body.username,
        "port": body.port,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _add_prometheus_target(server: Server) -> None:
    """Add server to windows_exporter Prometheus targets file."""
    try:
        import json, os
        path = "/etc/prometheus/targets/windows_exporter_targets.json"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existing: list = []
        if os.path.exists(path):
            with open(path) as f:
                existing = json.load(f)
        target_str = f"{server.ip_address}:9182"
        # Update or add
        for group in existing:
            if target_str in group.get("targets", []):
                return  # already there
        existing.append({
            "targets": [target_str],
            "labels": {"job": "windows-exporter", "instance": server.name or server.ip_address},
        })
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as exc:
        logger.warning("Could not update windows exporter targets: %s", exc)
