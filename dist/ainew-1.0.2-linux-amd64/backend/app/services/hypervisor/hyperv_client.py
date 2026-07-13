"""
Hyper-V client via WinRM + PowerShell.
Manages VMs on Windows Server Hyper-V using Hyper-V PowerShell module.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _parse_json(raw: str) -> Any:
    try:
        return json.loads(raw.strip())
    except Exception:
        return raw


class HyperVClient:
    """Manage Hyper-V VMs via WinRM/PowerShell."""

    def __init__(self, winrm_client):
        """winrm_client: WinRMClient instance pointing to Hyper-V host."""
        self.client = winrm_client

    def test_connection(self) -> Dict[str, Any]:
        r = self.client.run_ps("Get-VMHost | ConvertTo-Json -Compress")
        if r["success"] and r["stdout"].strip():
            data = _parse_json(r["stdout"])
            host_name = data.get("Name", "") if isinstance(data, dict) else ""
            return {"connected": True, "message": f"Hyper-V bağlantısı başarılı: {host_name}"}
        return {
            "connected": False,
            "message": r.get("stderr") or "Hyper-V modülü bulunamadı veya bağlantı başarısız",
        }

    def list_vms(self) -> List[Dict]:
        """List all VMs on this Hyper-V host."""
        script = """
Get-VM | Select-Object Name, VMId, State, Generation,
    @{N='cpu_cores';E={$_.ProcessorCount}},
    @{N='memory_gb';E={[math]::Round($_.MemoryAssigned/1GB,1)}},
    @{N='memory_startup_gb';E={[math]::Round($_.MemoryStartup/1GB,1)}},
    @{N='uptime_sec';E={$_.Uptime.TotalSeconds}},
    Path, Version |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        if not data:
            return []
        raw_list = data if isinstance(data, list) else [data]
        vms = []
        for v in raw_list:
            state = str(v.get("State", "")).lower()
            vms.append({
                "vm_id": str(v.get("VMId", "")),
                "name": v.get("Name", ""),
                "status": "ONLINE" if state in ("running", "2") else "OFFLINE",
                "power_state": state,
                "cpu_cores": v.get("cpu_cores", 0),
                "memory_gb": v.get("memory_gb", 0),
                "os_type": "",
                "ip_address": "",
                "uptime": int(v.get("uptime_sec", 0)),
            })
        return vms

    def get_vm_detail(self, vm_name: str) -> Dict:
        script = f"""
$vm = Get-VM -Name '{vm_name}' -ErrorAction SilentlyContinue
if (-not $vm) {{ @{{error='VM bulunamadı'}} | ConvertTo-Json; return }}
$nics = Get-VMNetworkAdapter -VMName '{vm_name}' | 
    Select-Object Name, IPAddresses, SwitchName
$disks = Get-VMHardDiskDrive -VMName '{vm_name}' |
    Select-Object Path, @{{N='SizeGB';E={{[math]::Round((Get-Item $_.Path -ErrorAction SilentlyContinue).Length/1GB,2)}}}}
@{{
    Name       = $vm.Name
    State      = $vm.State.ToString()
    Cores      = $vm.ProcessorCount
    MemoryGB   = [math]::Round($vm.MemoryAssigned/1GB,2)
    Generation = $vm.Generation
    Version    = $vm.Version
    NICs       = $nics
    Disks      = $disks
}} | ConvertTo-Json -Depth 5 -Compress
"""
        r = self.client.run_ps(script)
        return _parse_json(r["stdout"]) if r["success"] else {"error": r.get("stderr")}

    def start_vm(self, vm_name: str) -> Dict:
        r = self.client.run_ps(f"Start-VM -Name '{vm_name}' -ErrorAction Stop; Write-Output 'OK'")
        return {"success": r["success"] and "OK" in r.get("stdout", ""), "error": r.get("stderr") or ""}

    def stop_vm(self, vm_name: str, force: bool = False) -> Dict:
        cmd = "Stop-VM" if not force else "Stop-VM -Force"
        r = self.client.run_ps(f"{cmd} -Name '{vm_name}' -ErrorAction Stop; Write-Output 'OK'")
        return {"success": r["success"] and "OK" in r.get("stdout", ""), "error": r.get("stderr") or ""}

    def get_host_info(self) -> Dict:
        script = """
$h = Get-VMHost
@{
    Name           = $h.Name
    NumaNodesCount = $h.NumaNodesCount
    LogicalProcessorCount = $h.LogicalProcessorCount
    MemoryCapacityGB = [math]::Round($h.MemoryCapacity/1GB, 2)
    VirtualMachineCount = (Get-VM).Count
    HyperVVersion  = (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -ErrorAction SilentlyContinue).Version
} | ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        return _parse_json(r["stdout"]) if r["success"] else {"error": r.get("stderr")}

    def create_snapshot(self, vm_name: str, snapshot_name: str) -> Dict:
        r = self.client.run_ps(
            f"Checkpoint-VM -Name '{vm_name}' -SnapshotName '{snapshot_name}'; Write-Output 'OK'"
        )
        return {"success": r["success"] and "OK" in r.get("stdout", ""), "error": r.get("stderr") or ""}

    def list_snapshots(self, vm_name: str) -> List[Dict]:
        script = f"""
Get-VMSnapshot -VMName '{vm_name}' |
Select-Object Name, SnapshotType, CreationTime,
    @{{N='ParentName'; E={{$_.ParentSnapshotName}}}} |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        data = _parse_json(r["stdout"])
        return data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

    @classmethod
    def from_hypervisor(cls, hv) -> "HyperVClient":
        """Build from Hypervisor ORM object (must have WinRM credentials)."""
        from app.services.windows.winrm_client import WinRMClient
        client = WinRMClient(
            host=hv.host,
            username=hv.username,
            password=hv.password,
            port=hv.port or 5985,
        )
        return cls(client)
