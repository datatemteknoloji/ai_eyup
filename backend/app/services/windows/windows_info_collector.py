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
    Select-Object -First {count} @{{N='TimeCreated';E={{$_.TimeCreated.ToString('o')}}}},
        LevelDisplayName, Id, ProviderName,
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


# ── AI Chat destek fonksiyonları (Linux linux_info_collector eşleniği) ──────
# Kelime bazlı grup tespiti + toplu bilgi toplama + LLM için metin özet üretimi.

WINDOWS_GROUP_KEYWORDS: Dict[str, List[str]] = {
    "performance": ["cpu", "ram", "memory", "bellek", "performans", "performance",
                    "kullanım", "usage", "yük", "load", "durum", "status", "özet", "genel"],
    "disk": ["disk", "depolama", "storage", "sürücü", "drive", "alan", "space",
              "c:", "d:", "dolu", "boş"],
    "services": ["servis", "service", "hizmet", "durdu", "stopped", "başla", "start",
                 "restart", "yeniden başlat"],
    "eventlog": ["log", "event log", "olay günlüğü", "günlük", "hata", "error",
                 "warning", "uyarı", "kritik", "critical", "exception"],
    "updates": ["update", "güncelleme", "yama", "patch", "kb", "windows update"],
    "network": ["network", "ağ", "ip adres", "ip address", "ethernet", "adaptör", "adapter"],
    "os": ["os", "işletim sistemi", "operating system", "windows sürüm", "version",
           "versiyon", "build", "domain", "hostname", "makine adı", "sunucu adı"],
    "hardware": ["donanım", "hardware", "cpu model", "işlemci", "processor", "ram miktarı",
                 "bellek miktarı", "model"],
}

STANDARD_WINDOWS_GROUPS = ["os", "performance"]


def detect_needed_groups(message: str) -> List[str]:
    """Mesaj içeriğine göre hangi WinRM veri gruplarının toplanacağını belirler."""
    ml = (message or "").lower()
    groups: set = set()
    for group, keywords in WINDOWS_GROUP_KEYWORDS.items():
        if any(k in ml for k in keywords):
            groups.add(group)
    if not groups:
        groups.update(STANDARD_WINDOWS_GROUPS)
    else:
        groups.add("os")
    return list(groups)


def collect_server_info(client: "WinRMClient", groups: List[str]) -> Dict[str, Any]:
    """Verilen WinRM client ile, sadece ihtiyaç duyulan grupları toplar."""
    collector = WindowsInfoCollector(client)
    info: Dict[str, Any] = {}

    if "os" in groups:
        try:
            info["os"] = collector._get_os_info()
        except Exception as exc:
            info["os"] = {"error": str(exc)}
    if "hardware" in groups:
        try:
            info["hardware"] = collector._get_hardware_info()
        except Exception as exc:
            info["hardware"] = {"error": str(exc)}
    if "performance" in groups:
        try:
            info["performance"] = collector.get_performance()
        except Exception as exc:
            info["performance"] = {"error": str(exc)}
    if "disk" in groups:
        try:
            info["disks"] = collector._get_disk_info()
        except Exception as exc:
            info["disks"] = {"error": str(exc)}
    if "network" in groups:
        try:
            info["network"] = collector._get_network_info()
        except Exception as exc:
            info["network"] = {"error": str(exc)}
    if "services" in groups:
        try:
            info["services"] = collector.get_services()
        except Exception as exc:
            info["services"] = {"error": str(exc)}
    if "eventlog" in groups:
        try:
            info["event_logs_system"] = collector.get_event_logs("System", count=20, min_level=3)
            info["event_logs_app"] = collector.get_event_logs("Application", count=20, min_level=3)
        except Exception as exc:
            info["event_logs_system"] = {"error": str(exc)}
    if "updates" in groups:
        try:
            info["updates"] = collector.get_windows_updates()
        except Exception as exc:
            info["updates"] = {"error": str(exc)}

    if not info:
        info["error"] = "Toplanacak grup bulunamadı"
    return info


def build_server_context(server_name: str, server_ip: str, info: Dict[str, Any]) -> str:
    """Toplanan WinRM verisini LLM'e verilecek okunabilir metne çevirir."""
    lines = [f"=== {server_name} ({server_ip}) ==="]

    if info.get("error") and len(info) == 1:
        lines.append(f"HATA: {info['error']}")
        return "\n".join(lines)

    os_i = info.get("os")
    if isinstance(os_i, dict) and "error" not in os_i:
        lines.append(f"OS: {os_i.get('Caption', '-')} (Build {os_i.get('BuildNumber', '-')}, {os_i.get('Architecture', '-')})")
        lines.append(f"Hostname: {os_i.get('Hostname', '-')}  Domain: {os_i.get('Domain', '-')}")
        lines.append(f"Son Açılış: {os_i.get('LastBoot', '-')}")
    elif isinstance(os_i, dict):
        lines.append(f"OS bilgisi alınamadı: {os_i.get('error')}")

    hw = info.get("hardware")
    if isinstance(hw, dict) and "error" not in hw:
        lines.append(f"CPU: {hw.get('CPU', '-')} ({hw.get('Cores', '-')} core / {hw.get('Threads', '-')} thread)")
        lines.append(f"RAM: {hw.get('MemoryGB', '-')} GB   Model: {hw.get('Manufacturer', '-')} {hw.get('Model', '-')}")

    perf = info.get("performance")
    if isinstance(perf, dict) and perf and "error" not in perf:
        lines.append(f"CPU Kullanımı: %{perf.get('cpu_pct', '-')}")
        lines.append(
            f"RAM Kullanımı: %{perf.get('mem_used_pct', '-')} "
            f"(Toplam {perf.get('mem_total_gb', '-')} GB, Boş {perf.get('mem_free_gb', '-')} GB)"
        )

    disks = info.get("disks")
    if isinstance(disks, list) and disks:
        lines.append("Diskler:")
        for d in disks:
            if isinstance(d, dict):
                lines.append(
                    f"  {d.get('Name', '-')}: Kullanılan {d.get('UsedGB', '-')} GB / "
                    f"Toplam {d.get('TotalGB', '-')} GB (Boş {d.get('FreeGB', '-')} GB)"
                )

    net = info.get("network")
    if isinstance(net, list) and net:
        lines.append("Ağ Arayüzleri:")
        for n in net:
            if isinstance(n, dict):
                lines.append(f"  {n.get('InterfaceAlias', '-')}: {n.get('IPAddress', '-')}/{n.get('PrefixLength', '-')}")

    svcs = info.get("services")
    if isinstance(svcs, list):
        running_count = len([s for s in svcs if isinstance(s, dict) and s.get("Status") == "Running"])
        stopped = [
            s for s in svcs
            if isinstance(s, dict) and s.get("Status") != "Running" and s.get("StartType") == "Automatic"
        ]
        lines.append(f"Servisler: {running_count} çalışıyor / {len(svcs)} toplam")
        if stopped:
            lines.append("DURMUŞ (Otomatik başlaması gereken) Servisler:")
            for s in stopped[:15]:
                lines.append(f"  - {s.get('DisplayName', s.get('Name'))}: {s.get('Status')}")

    evs_sys = info.get("event_logs_system")
    if isinstance(evs_sys, list) and evs_sys:
        lines.append("Son Sistem Event Log Kayıtları (Warning/Error/Critical):")
        for e in evs_sys[:15]:
            if isinstance(e, dict):
                lines.append(
                    f"  [{e.get('TimeCreated', '-')}] {e.get('LevelDisplayName', '-')} - "
                    f"{e.get('ProviderName', '-')} (ID {e.get('Id', '-')}): {(e.get('Message') or '')[:200]}"
                )

    evs_app = info.get("event_logs_app")
    if isinstance(evs_app, list) and evs_app:
        lines.append("Son Application Event Log Kayıtları:")
        for e in evs_app[:15]:
            if isinstance(e, dict):
                lines.append(
                    f"  [{e.get('TimeCreated', '-')}] {e.get('LevelDisplayName', '-')} - "
                    f"{e.get('ProviderName', '-')} (ID {e.get('Id', '-')}): {(e.get('Message') or '')[:200]}"
                )

    upds = info.get("updates")
    if isinstance(upds, list):
        lines.append(f"Bekleyen Windows Update: {len(upds)} adet")
        for u in upds[:10]:
            if isinstance(u, dict):
                lines.append(f"  - {u.get('Title', '-')} (KB{u.get('KB', '-')}, {u.get('Severity', '-')})")

    return "\n".join(lines)
