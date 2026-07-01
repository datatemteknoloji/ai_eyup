"""
Windows Exporter installer/manager.
Downloads and registers windows_exporter.exe as a Windows service via WinRM.
Prometheus scrapes port 9182 for CPU, memory, disk, network metrics.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from .winrm_client import WinRMClient

logger = logging.getLogger(__name__)

EXPORTER_VERSION = "0.29.2"
EXPORTER_URL = (
    f"https://github.com/prometheus-community/windows_exporter/releases/download/"
    f"v{EXPORTER_VERSION}/windows_exporter-{EXPORTER_VERSION}-amd64.exe"
)
INSTALL_DIR = "C:\\windows_exporter"
EXE_PATH = f"{INSTALL_DIR}\\windows_exporter.exe"
SERVICE_NAME = "windows_exporter"
DEFAULT_PORT = 9182
COLLECTORS = "cpu,cs,logical_disk,net,os,service,system,memory"


class WindowsExporterInstaller:
    def __init__(self, client: WinRMClient):
        self.client = client

    def check_status(self) -> Dict[str, Any]:
        """Check if windows_exporter service is installed and running."""
        script = f"""
$svc = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $svc) {{
    @{{ installed = $false; running = $false; status = 'not_installed' }} | ConvertTo-Json -Compress
}} else {{
    @{{
        installed = $true
        running   = ($svc.Status -eq 'Running')
        status    = $svc.Status.ToString()
    }} | ConvertTo-Json -Compress
}}
"""
        r = self.client.run_ps(script)
        if r["success"]:
            import json
            try:
                return json.loads(r["stdout"].strip())
            except Exception:
                pass
        return {"installed": False, "running": False, "status": "unknown", "error": r.get("stderr")}

    def install(self) -> Dict[str, Any]:
        """Download windows_exporter and register as Windows service."""
        steps = []

        # 1. Create install directory
        r = self.client.run_ps(f"New-Item -ItemType Directory -Force -Path '{INSTALL_DIR}' | Out-Null; Write-Output 'OK'")
        steps.append({"step": "create_dir", "ok": r["success"] and "OK" in r["stdout"]})

        # 2. Download binary
        dl_script = f"""
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri '{EXPORTER_URL}' -OutFile '{EXE_PATH}' -UseBasicParsing
Write-Output 'DOWNLOADED'
"""
        r = self.client.run_ps(dl_script)
        ok = r["success"] and "DOWNLOADED" in r["stdout"]
        steps.append({"step": "download", "ok": ok, "error": r.get("stderr") if not ok else None})
        if not ok:
            return {"success": False, "steps": steps, "error": "İndirme başarısız: " + (r.get("stderr") or "")}

        # 3. Create Windows service
        svc_script = f"""
$existing = Get-Service -Name '{SERVICE_NAME}' -ErrorAction SilentlyContinue
if ($null -ne $existing) {{
    Stop-Service -Name '{SERVICE_NAME}' -Force -ErrorAction SilentlyContinue
    sc.exe delete '{SERVICE_NAME}' | Out-Null
    Start-Sleep -Seconds 2
}}
New-Service -Name '{SERVICE_NAME}' `
    -BinaryPathName '"{EXE_PATH}" --collectors.enabled {COLLECTORS} --telemetry.addr ":{DEFAULT_PORT}"' `
    -DisplayName 'Windows Exporter (Prometheus)' `
    -StartupType Automatic
Write-Output 'SERVICE_CREATED'
"""
        r = self.client.run_ps(svc_script)
        ok = r["success"] and "SERVICE_CREATED" in r["stdout"]
        steps.append({"step": "create_service", "ok": ok, "error": r.get("stderr") if not ok else None})
        if not ok:
            return {"success": False, "steps": steps, "error": "Servis oluşturulamadı: " + (r.get("stderr") or "")}

        # 4. Start service
        r = self.client.run_ps(f"Start-Service -Name '{SERVICE_NAME}'; Write-Output 'STARTED'")
        ok = r["success"] and "STARTED" in r["stdout"]
        steps.append({"step": "start_service", "ok": ok})

        # 5. Firewall rule for port 9182
        fw_script = f"""
New-NetFirewallRule -DisplayName 'Windows Exporter Prometheus' `
    -Direction Inbound -Protocol TCP -LocalPort {DEFAULT_PORT} -Action Allow `
    -ErrorAction SilentlyContinue | Out-Null
Write-Output 'FW_OK'
"""
        r = self.client.run_ps(fw_script)
        steps.append({"step": "firewall", "ok": "FW_OK" in r.get("stdout", "")})

        return {"success": True, "steps": steps, "port": DEFAULT_PORT}

    def uninstall(self) -> Dict[str, Any]:
        script = f"""
Stop-Service -Name '{SERVICE_NAME}' -Force -ErrorAction SilentlyContinue
sc.exe delete '{SERVICE_NAME}' | Out-Null
Remove-Item -Path '{INSTALL_DIR}' -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'REMOVED'
"""
        r = self.client.run_ps(script)
        return {"success": r["success"] and "REMOVED" in r.get("stdout", "")}

    def start(self) -> Dict[str, Any]:
        r = self.client.run_ps(f"Start-Service -Name '{SERVICE_NAME}'; Write-Output 'OK'")
        return {"success": r["success"] and "OK" in r.get("stdout", "")}

    def stop(self) -> Dict[str, Any]:
        r = self.client.run_ps(f"Stop-Service -Name '{SERVICE_NAME}' -Force; Write-Output 'OK'")
        return {"success": r["success"] and "OK" in r.get("stdout", "")}
