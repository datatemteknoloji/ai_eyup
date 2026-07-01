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

from app.core.database import get_db
from app.models.server import Server
from app.services.windows.winrm_client import WinRMClient
from app.services.windows.windows_info_collector import WindowsInfoCollector
from app.services.windows.windows_update_service import WindowsUpdateService
from app.services.windows.windows_exporter_installer import WindowsExporterInstaller

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_server_or_404(server_id: int, db: Session) -> Server:
    s = db.query(Server).filter(Server.id == server_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadı")
    return s


def _build_client(server: Server) -> WinRMClient:
    client = WinRMClient.from_server(server)
    if not client:
        raise HTTPException(
            status_code=400,
            detail="Bu sunucu için WinRM kimlik bilgisi bulunamadı. Lütfen bağlantı ayarlarını kontrol edin.",
        )
    return client


# ── Schemas ───────────────────────────────────────────────────────────────────

class WinRMCredentials(BaseModel):
    username: str
    password: str
    port: int = 5985
    use_https: bool = False


class ServiceAction(BaseModel):
    action: str  # start | stop | restart


class InstallUpdatesRequest(BaseModel):
    kb_ids: Optional[List[str]] = None  # None = all updates
    auto_reboot: bool = False


class ScheduleRebootRequest(BaseModel):
    delay_minutes: int = 5


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/servers")
def list_windows_servers(db: Session = Depends(get_db)):
    """List all servers whose os_type contains 'windows'."""
    servers = db.query(Server).all()
    result = []
    for s in servers:
        os_low = (s.os_type or "").lower()
        if "windows" in os_low or (s.connection_config or {}).get("winrm"):
            cfg = s.connection_config or {}
            result.append({
                "id": s.id,
                "name": s.name,
                "hostname": s.hostname,
                "ip_address": s.ip_address,
                "status": s.status,
                "os_type": s.os_type,
                "cpu_cores": s.cpu_cores,
                "memory_gb": s.memory_gb,
                "hypervisor_id": s.hypervisor_id,
                "hypervisor_name": getattr(s.hypervisor, "name", None) if s.hypervisor_id else None,
                "winrm_configured": bool(cfg.get("username") or cfg.get("winrm_username")),
                "winrm_port": cfg.get("winrm_port") or cfg.get("port") or 5985,
            })
    return result


@router.post("/servers/{server_id}/test-connection")
def test_connection(server_id: int, db: Session = Depends(get_db)):
    """Test WinRM connectivity for a server."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    result = client.test_connection()
    # Update status in DB
    if result["connected"]:
        server.status = "ONLINE"
        db.commit()
    return result


@router.post("/servers/{server_id}/save-credentials")
def save_credentials(server_id: int, creds: WinRMCredentials, db: Session = Depends(get_db)):
    """Save WinRM credentials to a server's connection_config."""
    server = _get_server_or_404(server_id, db)
    existing = dict(server.connection_config or {})
    existing.update({
        "username": creds.username,
        "password": creds.password,
        "winrm_port": creds.port,
        "winrm_https": creds.use_https,
        "winrm": True,
    })
    server.connection_config = existing
    if not server.os_type or "windows" not in server.os_type.lower():
        server.os_type = "windows"
    db.commit()

    # Quick connection test
    client = WinRMClient(
        host=server.ip_address,
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
    client = _build_client(server)
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
    client = _build_client(server)
    collector = WindowsInfoCollector(client)
    return collector.get_performance()


@router.get("/servers/{server_id}/services")
def get_services(server_id: int, include_disabled: bool = False, db: Session = Depends(get_db)):
    """List Windows services."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
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
    client = _build_client(server)

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
    client = _build_client(server)
    collector = WindowsInfoCollector(client)
    return collector.get_event_logs(log_name=log_name, count=count, min_level=min_level)


@router.get("/servers/{server_id}/updates")
def list_updates(server_id: int, db: Session = Depends(get_db)):
    """List pending Windows updates."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
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
    client = _build_client(server)
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
    client = _build_client(server)
    svc = WindowsUpdateService(client)
    return svc.schedule_reboot(delay_minutes=body.delay_minutes)


# ── Windows Exporter ──────────────────────────────────────────────────────────

@router.get("/servers/{server_id}/exporter/status")
def exporter_status(server_id: int, db: Session = Depends(get_db)):
    """Check windows_exporter installation status."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    installer = WindowsExporterInstaller(client)
    return installer.check_status()


@router.post("/servers/{server_id}/exporter/install")
def install_exporter(server_id: int, db: Session = Depends(get_db)):
    """Download and install windows_exporter as a Windows service."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    installer = WindowsExporterInstaller(client)
    result = installer.install()
    if result.get("success"):
        # Add to Prometheus windows_exporter targets
        _add_prometheus_target(server)
    return result


@router.post("/servers/{server_id}/exporter/start")
def start_exporter(server_id: int, db: Session = Depends(get_db)):
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    return WindowsExporterInstaller(client).start()


@router.post("/servers/{server_id}/exporter/uninstall")
def uninstall_exporter(server_id: int, db: Session = Depends(get_db)):
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    return WindowsExporterInstaller(client).uninstall()


# ── PS execution (power-user) ─────────────────────────────────────────────────

class PSRequest(BaseModel):
    script: str


@router.post("/servers/{server_id}/run-ps")
def run_powershell(server_id: int, body: PSRequest, db: Session = Depends(get_db)):
    """Execute arbitrary PowerShell on a Windows server (admin only)."""
    server = _get_server_or_404(server_id, db)
    client = _build_client(server)
    return client.run_ps(body.script)


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
