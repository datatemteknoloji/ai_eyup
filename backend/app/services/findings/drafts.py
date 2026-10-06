"""Bulgu → komut TASLAĞI (PowerCLI / oc). Uygulama bunları ÇALIŞTIRMAZ.

Operatör taslağı kopyalayıp kendi değişiklik sürecinde kullanır; onaylı ve
geri alınabilir uygulama için ayrı yol: /virt-insights/remediation (Agent onayı).
Değerler PowerShell tek tırnak kaçışıyla ('') yerleştirilir.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraFinding
from app.services.findings.registry import get_check


def _ps(v: Any) -> str:
    return "'" + str(v or "").replace("'", "''") + "'"


def _sh(v: Any) -> str:
    return "'" + str(v or "").replace("'", "'\"'\"'") + "'"


def _majority_ntp(db: Session, f: InfraFinding) -> List[str]:
    from app.services.virt_insights_data import latest_config
    sets = Counter()
    for h in latest_config(db, f.platform, f.source_id, "host"):
        if f.cluster_name and h.get("cluster") != f.cluster_name:
            continue
        srv = tuple((h.get("config") or {}).get("ntp_servers") or [])
        if srv:
            sets[srv] += 1
    return list(sets.most_common(1)[0][0]) if sets else []


def _majority_syslog(db: Session, f: InfraFinding) -> Optional[str]:
    vals = Counter()
    for r in (db.query(InfraFinding)
              .filter(InfraFinding.platform == f.platform, InfraFinding.source_id == f.source_id,
                      InfraFinding.check_id == "cmp.host.syslog_remote", InfraFinding.result == "pass",
                      InfraFinding.active.is_(True)).all()):
        v = (r.evidence or {}).get("logHost")
        if v:
            vals[v] += 1
    return vals.most_common(1)[0][0] if vals else None


def _host(f: InfraFinding) -> str:
    return f.entity_name or ""


def build_draft(db: Session, f: InfraFinding) -> Optional[Dict[str, Any]]:
    cdef = get_check(f.check_id)
    key = cdef.draft if cdef else None
    if not key:
        return None
    pre = ["# Taslak — ainew bu komutu çalıştırmaz. Değişiklik onayınızla, bakım penceresinde uygulayın.",
           f"# Bulgu: {f.title} · {f.entity_name}"]
    if f.platform == "vmware":
        pre.append(f"# Connect-VIServer -Server <vCenter: {f.source_name}>")
    lines: List[str] = []
    rollback: List[str] = []
    lang = "powershell"
    notes: List[str] = []
    if key == "vmw_ha_enable":
        lines = [f"Get-Cluster -Name {_ps(f.entity_name)} | Set-Cluster -HAEnabled:$true -HAAdmissionControlEnabled:$true -Confirm:$false"]
        rollback = [f"Get-Cluster -Name {_ps(f.entity_name)} | Set-Cluster -HAEnabled:$false -Confirm:$false"]
    elif key == "vmw_ntp_set":
        srv = _majority_ntp(db, f)
        if not srv:
            srv = ["<ntp1.kurum.local>", "<ntp2.kurum.local>"]
            notes.append("Cluster'da referans NTP bulunamadı; sunucu adlarını doldurun.")
        else:
            notes.append(f"NTP sunucuları cluster'daki diğer hostlardan alındı: {', '.join(srv)}")
        lines = [
            f"$h = Get-VMHost -Name {_ps(_host(f))}",
            f"Add-VMHostNtpServer -VMHost $h -NtpServer {', '.join(_ps(s) for s in srv)}",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'ntpd' | Set-VMHostService -Policy On",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'ntpd' | Restart-VMHostService -Confirm:$false",
        ]
        rollback = [f"Get-VMHostNtpServer -VMHost $h | ForEach-Object {{ Remove-VMHostNtpServer -VMHost $h -NtpServer $_ -Confirm:$false }}"]
    elif key == "vmw_ntp_restart":
        lines = [
            f"$h = Get-VMHost -Name {_ps(_host(f))}",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'ntpd' | Set-VMHostService -Policy On",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'ntpd' | Restart-VMHostService -Confirm:$false",
        ]
    elif key == "vmw_snapshot_remove":
        snaps = (f.evidence or {}).get("snapshots") or []
        lines = [f"$vm = Get-VM -Name {_ps(f.entity_name)}"]
        for s in snaps:
            lines.append(f"Get-Snapshot -VM $vm -Name {_ps(s.get('name'))} | Remove-Snapshot -Confirm:$false  # {s.get('created')}")
        notes.append("Snapshot silme geri alınamaz; yedek zincirinin (Veeam vb.) bu snapshot'a bağlı olmadığını doğrulayın.")
        if f.platform == "olvm":
            lang = "text"
            lines = ["OLVM Yönetim Portalı → Compute → Virtual Machines → " + f.entity_name + " → Snapshots → Delete"]
    elif key == "vmw_ssh_stop":
        lines = [
            f"$h = Get-VMHost -Name {_ps(_host(f))}",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'TSM-SSH' | Stop-VMHostService -Confirm:$false",
            "Get-VMHostService -VMHost $h | Where-Object Key -eq 'TSM-SSH' | Set-VMHostService -Policy Off",
        ]
        rollback = ["Get-VMHostService -VMHost $h | Where-Object Key -eq 'TSM-SSH' | Start-VMHostService"]
    elif key == "vmw_syslog_set":
        target = _majority_syslog(db, f) or "udp://<syslog.kurum.local>:514"
        lines = [
            f"$h = Get-VMHost -Name {_ps(_host(f))}",
            f"Get-AdvancedSetting -Entity $h -Name 'Syslog.global.logHost' | Set-AdvancedSetting -Value {_ps(target)} -Confirm:$false",
            "Get-VMHostFirewallException -VMHost $h -Name 'syslog' | Set-VMHostFirewallException -Enabled:$true",
        ]
        rollback = ["Get-AdvancedSetting -Entity $h -Name 'Syslog.global.logHost' | Set-AdvancedSetting -Value '' -Confirm:$false"]
    elif key == "ocpv_eviction":
        lang = "bash"
        ns, _, name = (f.entity_name or "").partition("/")
        patch = '{"spec":{"template":{"spec":{"evictionStrategy":"LiveMigrate"}}}}'
        lines = [f"oc patch vm {_sh(name)} -n {_sh(ns)} --type merge -p {_sh(patch)}"]
        notes.append("Değişiklik VM yeniden başlatıldığında (restart) etkinleşir; RWX disk gerektirir.")
    else:
        return None
    return {
        "finding_id": f.id, "language": lang, "title": cdef.title_tr if cdef else f.title,
        "script": "\n".join(pre + [""] + lines),
        "rollback": "\n".join(rollback) if rollback else None,
        "notes": notes,
        "executes": False,
    }
