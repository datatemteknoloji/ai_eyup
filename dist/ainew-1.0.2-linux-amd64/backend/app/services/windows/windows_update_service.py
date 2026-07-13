"""
Windows Update management via WinRM/PowerShell.
Supports listing, installing selected or all updates, and reboot scheduling.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .winrm_client import WinRMClient

logger = logging.getLogger(__name__)


class WindowsUpdateService:
    def __init__(self, client: WinRMClient):
        self.client = client

    def list_updates(self) -> List[Dict]:
        """List all available Windows updates."""
        script = """
try {
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $result   = $searcher.Search("IsInstalled=0 and Type='Software'")
    $result.Updates | ForEach-Object {
        @{
            Title     = $_.Title
            KB        = ($_.KBArticleIDs -join ',')
            Severity  = $_.MsrcSeverity
            Mandatory = $_.IsMandatory
            RebootRequired = $_.RebootRequired
        }
    } | ConvertTo-Json -Compress
} catch {
    @() | ConvertTo-Json
}
"""
        r = self.client.run_ps(script)
        if not r["success"] or not r["stdout"].strip() or r["stdout"].strip() == "[]":
            return []
        import json
        try:
            data = json.loads(r["stdout"].strip())
            return data if isinstance(data, list) else [data]
        except Exception:
            return []

    def install_all_updates(self, auto_reboot: bool = False) -> Dict[str, Any]:
        """Install all pending updates. Optionally reboot after."""
        reboot_cmd = "Restart-Computer -Force" if auto_reboot else "# Reboot skipped"
        script = f"""
try {{
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $pending  = $searcher.Search("IsInstalled=0 and Type='Software'").Updates
    if ($pending.Count -eq 0) {{
        Write-Output "NO_UPDATES"
    }} else {{
        $downloader = $session.CreateUpdateDownloader()
        $downloader.Updates = $pending
        $downloader.Download()
        $installer = $session.CreateUpdateInstaller()
        $installer.Updates = $pending
        $result = $installer.Install()
        Write-Output "INSTALLED:$($result.InstalledCount) FAILED:$($result.FailedCount) REBOOT:$($result.RebootRequired)"
        if ($result.RebootRequired) {{ {reboot_cmd} }}
    }}
}} catch {{
    Write-Output "ERROR:$($_.Exception.Message)"
}}
"""
        r = self.client.run_ps(script)
        out = r.get("stdout", "").strip()
        if "NO_UPDATES" in out:
            return {"status": "no_updates", "message": "Bekleyen güncelleme yok"}
        if out.startswith("INSTALLED"):
            return {"status": "success", "message": out, "reboot_needed": "REBOOT:True" in out}
        return {"status": "error", "message": out or r.get("stderr", "Bilinmeyen hata")}

    def install_by_kb(self, kb_ids: List[str]) -> Dict[str, Any]:
        """Install specific KBs."""
        kb_list = ", ".join(f'"{kb}"' for kb in kb_ids)
        script = f"""
$targets = @({kb_list})
try {{
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $all = $searcher.Search("IsInstalled=0 and Type='Software'").Updates
    $filtered = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($u in $all) {{
        foreach ($kb in $u.KBArticleIDs) {{
            if ($targets -contains "KB$kb" -or $targets -contains $kb) {{
                $filtered.Add($u) | Out-Null
            }}
        }}
    }}
    if ($filtered.Count -eq 0) {{ Write-Output "NOT_FOUND" }}
    else {{
        $dl = $session.CreateUpdateDownloader(); $dl.Updates = $filtered; $dl.Download()
        $inst = $session.CreateUpdateInstaller(); $inst.Updates = $filtered
        $res = $inst.Install()
        Write-Output "INSTALLED:$($res.InstalledCount) FAILED:$($res.FailedCount)"
    }}
}} catch {{ Write-Output "ERROR:$($_.Exception.Message)" }}
"""
        r = self.client.run_ps(script)
        out = r.get("stdout", "").strip()
        if "NOT_FOUND" in out:
            return {"status": "not_found", "message": "Belirtilen KB'ler bulunamadı"}
        if out.startswith("INSTALLED"):
            return {"status": "success", "message": out}
        return {"status": "error", "message": out or r.get("stderr", "")}

    def get_installed_updates(self, count: int = 20) -> List[Dict]:
        """List recently installed updates."""
        script = f"""
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First {count} |
Select-Object HotFixID, Description, InstalledBy,
    @{{N='InstalledOn'; E={{if ($_.InstalledOn) {{$_.InstalledOn.ToString('yyyy-MM-dd')}} else {{'-'}}}}}} |
ConvertTo-Json -Compress
"""
        r = self.client.run_ps(script)
        if not r["success"]:
            return []
        import json
        try:
            data = json.loads(r["stdout"].strip())
            return data if isinstance(data, list) else [data]
        except Exception:
            return []

    def schedule_reboot(self, delay_minutes: int = 5) -> Dict[str, Any]:
        script = f"shutdown /r /t {delay_minutes * 60} /c 'Scheduled reboot via datatem AI'"
        r = self.client.run_cmd("cmd", ["/c", script])
        return {"status": "scheduled" if r["success"] else "error", "message": r.get("stderr") or "OK"}

    def cancel_reboot(self) -> Dict[str, Any]:
        r = self.client.run_cmd("cmd", ["/c", "shutdown /a"])
        return {"status": "cancelled" if r["success"] else "error"}
