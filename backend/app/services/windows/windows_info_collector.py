"""
Collect system information from Windows servers via WMI/PowerShell over WinRM.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from .winrm_client import WinRMClient

logger = logging.getLogger(__name__)


def _parse_json(raw: str) -> Any:
    """Try JSON parse; fall back to raw string."""
    try:
        return json.loads(raw.strip())
    except Exception:
        return raw


class WindowsInfoCollector:
    """Collects comprehensive system information from a Windows host."""

    def __init__(self, client: WinRMClient):
        self.client = client

    # ── Public API ────────────────────────────────────────────────────────────

    def collect_all(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        for key, method in [
            ("os", self._get_os_info),
            ("hardware", self._get_hardware_info),
            ("disks", self._get_disk_info),
            ("network", self._get_network_info),
        ]:
            try:
                info[key] = method()
            except Exception as exc:
                info[key] = {"error": str(exc)}
        return info

    def get_services(self, include_disabled: bool = False) -> List[Dict]:
        filter_clause = "" if include_disabled else "| Where-Object {$_.StartType -ne 'Disabled'}"
        script = f"""
Get-Service {filter_clause} |
Select-Object Name, DisplayName, Status, StartType |
Sort-Object Status -Descending |
Select-Object -First 100 |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

    def get_event_logs(
        self,
        log_name: str = "System",
        count: int = 50,
        min_level: int = 3,  # 1=Critical 2=Error 3=Warning 4=Information
    ) -> List[Dict]:
        """Fetch Windows Event Log entries."""
        script = f"""
try {{
    Get-WinEvent -LogName '{log_name}' -MaxEvents {count * 3} -ErrorAction SilentlyContinue |
    Where-Object {{$_.Level -le {min_level}}} |
    Select-Object -First {count} TimeCreated, LevelDisplayName, Id, ProviderName,
        @{{N='Message';E={{$_.Message.Substring(0,[Math]::Min(300,$_.Message.Length))}}}} |
    ConvertTo-Json -Compress
}} catch {{
    Write-Output '[]'
}}
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        if not data or data == "[]":
            return []
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

    def get_windows_updates(self) -> List[Dict]:
        """List available (not yet installed) Windows updates via COM."""
        script = """
try {
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $result   = $searcher.Search("IsInstalled=0 and Type='Software'")
    $result.Updates | ForEach-Object {
        @{
            Title      = $_.Title
            KB         = ($_.KBArticleIDs -join ',')
            Severity   = $_.MsrcSeverity
            Mandatory  = $_.IsMandatory
        }
    } | ConvertTo-Json -Compress
} catch {
    Write-Output '[]'
}
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        if not data or data == "[]":
            return []
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

    def get_performance(self) -> Dict[str, Any]:
        """Current CPU / RAM utilisation."""
        script = """
$cpu = (Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$os  = Get-CimInstance Win32_OperatingSystem
$memTotal = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$memFree  = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$memUsedPct = [math]::Round(($memTotal - $memFree) / $memTotal * 100, 1)
@{
    cpu_pct     = [math]::Round($cpu, 1)
    mem_total_gb = $memTotal
    mem_free_gb  = $memFree
    mem_used_pct = $memUsedPct
} | ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if r["success"]:
            data = _parse_json(r["stdout"])
            return data if isinstance(data, dict) else {}
        return {}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_os_info(self) -> Dict:
        script = """
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
@{
    Caption      = $os.Caption
    Version      = $os.Version
    BuildNumber  = $os.BuildNumber
    Architecture = $os.OSArchitecture
    Hostname     = $env:COMPUTERNAME
    Domain       = $cs.Domain
    LastBoot     = $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm:ss')
} | ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        return _parse_json(r["stdout"]) if r["success"] else {"error": r["stderr"]}

    def _get_hardware_info(self) -> Dict:
        script = """
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs  = Get-CimInstance Win32_ComputerSystem
@{
    CPU        = $cpu.Name
    Cores      = $cpu.NumberOfCores
    Threads    = $cpu.NumberOfLogicalProcessors
    MemoryGB   = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
    Manufacturer = $cs.Manufacturer
    Model      = $cs.Model
} | ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        return _parse_json(r["stdout"]) if r["success"] else {"error": r["stderr"]}

    def _get_disk_info(self) -> List:
        script = """
Get-PSDrive -PSProvider FileSystem |
Select-Object Name,
    @{N='UsedGB';  E={[math]::Round($_.Used  /1GB, 2)}},
    @{N='FreeGB';  E={[math]::Round($_.Free  /1GB, 2)}},
    @{N='TotalGB'; E={[math]::Round(($_.Used+$_.Free)/1GB, 2)}} |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

    def _get_network_info(self) -> List:
        script = """
Get-NetIPAddress -AddressFamily IPv4 |
Where-Object {$_.PrefixOrigin -ne 'WellKnown'} |
Select-Object InterfaceAlias, IPAddress, PrefixLength |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
