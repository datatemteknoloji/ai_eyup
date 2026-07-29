"""
Altyapı genel özeti — Linux/Windows/VM/hypervisor/OpenShift sayıları.

Ucuz DB sorgularıyla üretilir, her sorguda güvenle kullanılabilir. `unified_chat`
(genel AI sohbeti) ve `agent` (tool-calling asistan) tarafından ortak kullanılır;
böylece "kaç sunucumuz/VM'imiz var" gibi altyapı-geneli sorular platform bazlı
SSH/WinRM araçlarına sapmadan, tek bir hızlı DB özetiyle cevaplanabilir.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.services.platform_scope import is_windows_server, is_vm


def _esxi_host_count(db: Session) -> int:
    """Senkronize ESX/KVM host sayısı — Server tablosundaki 'fiziksel' ile karıştırma."""
    try:
        n = db.execute(text("SELECT COUNT(*) FROM hypervisor_host_inventory")).scalar()
        if n:
            return int(n)
    except Exception:
        pass
    try:
        n = db.execute(text(
            "SELECT COUNT(DISTINCT host_name) FROM hypervisor_host_metrics"
        )).scalar()
        return int(n or 0)
    except Exception:
        return 0


def build_infra_overview_text(db: Session) -> str:
    all_servers = db.query(Server).all()
    linux_all = [s for s in all_servers if not is_windows_server(s)]
    windows_all = [s for s in all_servers if is_windows_server(s)]
    linux_ai = [s for s in linux_all if s.ai_ready]
    windows_ai = [s for s in windows_all if s.ai_ready]
    vms = [s for s in all_servers if is_vm(s)]
    # Server tablosunda hypervisor_id/VIRTUAL olmayan kayıtlar (nadiren gerçek fiziksel)
    physical_servers = [s for s in all_servers if not is_vm(s)]
    hypervisors = db.query(Hypervisor).all()
    esxi_hosts = _esxi_host_count(db)

    ocp_lines = []
    try:
        from app.models.openshift import OpenShiftCluster
        for c in db.query(OpenShiftCluster).all():
            ocp_lines.append(f"- {c.name}: api={c.api_url or '-'}, sürüm={c.version or '-'}")
    except Exception:
        pass

    lines = [
        "GENEL ENVANTER OZETI:",
        f"- Toplam sunucu kaydı (OS envanteri): {len(all_servers)} adet",
        f"- Linux/Unix: {len(linux_all)} adet ({len(linux_ai)} AI Ready)",
        f"- Windows: {len(windows_all)} adet ({len(windows_ai)} AI Ready)",
        f"- Sanal makine (VM, OS envanteri): {len(vms)} adet",
        f"- OS envanterinde fiziksel/bare-metal kayıt: {len(physical_servers)} adet",
        f"- Hypervisor ESX/KVM host (senkronize): {esxi_hosts} adet",
        f"- Hypervisor/entegrasyon bağlantısı: {len(hypervisors)} adet"
        + (
            f" ({', '.join(sorted(set((h.hypervisor_type.value if h.hypervisor_type else str(h.type or '-')) for h in hypervisors)))})"
            if hypervisors else ""
        ),
    ]
    if ocp_lines:
        lines.append(f"- OpenShift cluster: {len(ocp_lines)} adet")
    if linux_ai:
        lines.append("\nAI Ready Linux sunucular:")
        for s in linux_ai:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, Durum={s.status}"
            )
    if windows_ai:
        lines.append("\nAI Ready Windows sunucular:")
        for s in windows_ai:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}"
            )
    if hypervisors:
        lines.append("\nHypervisorlar:")
        for h in hypervisors:
            vm_count = sum(1 for s in vms if s.hypervisor_id == h.id)
            hv_type = (
                h.hypervisor_type.value if h.hypervisor_type else (h.type or "-")
            )
            lines.append(
                f"- {h.name} ({hv_type}): host={h.hostname or h.ip_address or '-'}, "
                f"durum={h.status or '-'}, bağlı VM={vm_count}"
            )
    if ocp_lines:
        lines.append("\nOpenShift clusterlar:")
        lines.extend(ocp_lines)
    lines.append(
        "\nNOT: 'ESX/KVM host' sanallaştırma katmanı envanteridir; "
        "'OS envanteri fiziksel kayıt' Server tablosundaki bare-metal satırlardır — "
        "birbirinin yerine kullanılmamalı."
    )
    return "\n".join(lines)
