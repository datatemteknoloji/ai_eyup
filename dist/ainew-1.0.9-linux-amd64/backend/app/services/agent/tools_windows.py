"""
Agent tools for Windows servers — PowerShell equivalents of Linux SSH tools.
These are called by the orchestrator when the target server has os_type=windows.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.server import Server

logger = logging.getLogger(__name__)


def _build_client(server: Server):
    from app.services.windows.winrm_client import WinRMClient
    client = WinRMClient.from_server(server)
    if not client:
        raise ValueError(f"'{server.name}' için WinRM kimlik bilgisi bulunamadı.")
    return client


# ── Tool definitions (mirrors Linux tools schema) ─────────────────────────────

WINDOWS_TOOLS = [
    {
        "name": "win_diagnostic",
        "description": (
            "Windows sunucusunda tanı çalıştır: CPU/RAM/Disk kullanımı, çalışan servisler, "
            "son event log hataları."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer", "description": "Sunucu ID"},
                "server_name": {"type": "string", "description": "Sunucu adı (ID yerine)"},
            },
        },
    },
    {
        "name": "win_read_event_logs",
        "description": "Windows Event Log'dan hata ve uyarıları oku (System/Application/Security).",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer"},
                "server_name": {"type": "string"},
                "log_name": {
                    "type": "string",
                    "enum": ["System", "Application", "Security"],
                    "description": "Log kanal adı",
                },
                "count": {"type": "integer", "description": "Okunacak kayıt sayısı (varsayılan: 30)"},
            },
            "required": [],
        },
    },
    {
        "name": "win_manage_service",
        "description": "Windows servisini başlat, durdur veya yeniden başlat.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer"},
                "server_name": {"type": "string"},
                "service_name": {"type": "string", "description": "Servis adı (ör. Spooler, W32Time)"},
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "restart"],
                    "description": "Yapılacak işlem",
                },
            },
            "required": ["service_name", "action"],
        },
    },
    {
        "name": "win_run_powershell",
        "description": "Windows sunucusunda PowerShell komutu çalıştır (READ_ONLY teşhis için).",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer"},
                "server_name": {"type": "string"},
                "script": {"type": "string", "description": "Çalıştırılacak PowerShell betiği"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "win_list_updates",
        "description": "Bekleyen Windows Update listesini getir.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer"},
                "server_name": {"type": "string"},
            },
        },
    },
    {
        "name": "win_install_updates",
        "description": "Seçili veya tüm Windows güncellemelerini kur (MUTATING).",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "integer"},
                "server_name": {"type": "string"},
                "kb_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kurulacak KB listesi. Boş bırakılırsa tümü kurulur.",
                },
            },
        },
    },
]

MUTATING_WIN_TOOLS = {"win_manage_service", "win_install_updates"}


def execute_windows_tool(
    tool_name: str,
    args: Dict[str, Any],
    db: Session,
    ctx: Dict[str, Any],
) -> str:
    """Dispatch and execute a Windows agent tool; returns string result."""
    server = _resolve_server(db, args, ctx)

    if tool_name == "win_diagnostic":
        return _win_diagnostic(server)
    elif tool_name == "win_read_event_logs":
        return _win_read_event_logs(server, args)
    elif tool_name == "win_manage_service":
        return _win_manage_service(server, args)
    elif tool_name == "win_run_powershell":
        return _win_run_ps(server, args)
    elif tool_name == "win_list_updates":
        return _win_list_updates(server)
    elif tool_name == "win_install_updates":
        return _win_install_updates(server, args)
    return json.dumps({"error": f"Bilinmeyen Windows aracı: {tool_name}"})


def _resolve_server(db: Session, args: Dict, ctx: Dict) -> Server:
    sid = args.get("server_id") or ctx.get("server_id")
    sname = args.get("server_name") or ctx.get("server_name")
    if sid:
        s = db.query(Server).filter(Server.id == sid).first()
        if s:
            return s
    if sname:
        s = db.query(Server).filter(Server.name == sname).first()
        if s:
            return s
    # fallback: first Windows server
    s = db.query(Server).filter(Server.os_type.ilike("%windows%")).first()
    if s:
        return s
    raise ValueError("Sunucu bulunamadı. server_id veya server_name belirtin.")


def _win_diagnostic(server: Server) -> str:
    client = _build_client(server)
    from app.services.windows.windows_info_collector import WindowsInfoCollector
    collector = WindowsInfoCollector(client)
    perf = collector.get_performance()
    disks = collector.collect_all().get("disks", [])
    services_down = [
        s for s in collector.get_services()
        if str(s.get("Status", "")).lower() not in ("running", "4") and
           str(s.get("StartType", "")).lower() not in ("disabled", "manual")
    ][:10]
    result = {
        "server": server.name,
        "os": server.os_type,
        "performance": perf,
        "disks": disks,
        "stopped_auto_services": services_down,
    }
    return json.dumps(result, default=str)


def _win_read_event_logs(server: Server, args: Dict) -> str:
    client = _build_client(server)
    from app.services.windows.windows_info_collector import WindowsInfoCollector
    collector = WindowsInfoCollector(client)
    logs = collector.get_event_logs(
        log_name=args.get("log_name", "System"),
        count=args.get("count", 30),
    )
    return json.dumps({"server": server.name, "log_name": args.get("log_name", "System"), "entries": logs}, default=str)


def _win_manage_service(server: Server, args: Dict) -> str:
    client = _build_client(server)
    action = args.get("action", "").lower()
    svc = args.get("service_name", "")
    ps_map = {
        "start": f"Start-Service -Name '{svc}' -ErrorAction Stop; Write-Output 'OK'",
        "stop": f"Stop-Service -Name '{svc}' -Force -ErrorAction Stop; Write-Output 'OK'",
        "restart": f"Restart-Service -Name '{svc}' -Force -ErrorAction Stop; Write-Output 'OK'",
    }
    if action not in ps_map:
        return json.dumps({"error": "Geçersiz aksiyon"})
    r = client.run_ps(ps_map[action])
    return json.dumps({
        "server": server.name,
        "service": svc,
        "action": action,
        "success": r["success"] and "OK" in r.get("stdout", ""),
        "error": r.get("stderr") or None,
    })


def _win_run_ps(server: Server, args: Dict) -> str:
    client = _build_client(server)
    r = client.run_ps(args.get("script", ""))
    return json.dumps({"server": server.name, "stdout": r.get("stdout", ""), "stderr": r.get("stderr", ""), "exit_code": r.get("exit_code")})


def _win_list_updates(server: Server) -> str:
    client = _build_client(server)
    from app.services.windows.windows_update_service import WindowsUpdateService
    svc = WindowsUpdateService(client)
    updates = svc.list_updates()
    return json.dumps({"server": server.name, "pending_count": len(updates), "updates": updates})


def _win_install_updates(server: Server, args: Dict) -> str:
    client = _build_client(server)
    from app.services.windows.windows_update_service import WindowsUpdateService
    svc = WindowsUpdateService(client)
    kb_ids = args.get("kb_ids")
    if kb_ids:
        result = svc.install_by_kb(kb_ids)
    else:
        result = svc.install_all_updates()
    return json.dumps({"server": server.name, **result})
