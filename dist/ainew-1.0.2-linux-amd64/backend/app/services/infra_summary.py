"""
Altyapı genel özeti — Linux/Windows/VM/hypervisor sayıları.

Ucuz DB sorgularıyla üretilir, her sorguda güvenle kullanılabilir. `unified_chat`
(genel AI sohbeti) ve `agent` (tool-calling asistan) tarafından ortak kullanılır;
böylece "kaç sunucumuz/VM'imiz var" gibi altyapı-geneli sorular platform bazlı
SSH/WinRM araçlarına sapmadan, tek bir hızlı DB özetiyle cevaplanabilir.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.services.platform_scope import is_windows_server, is_vm


def build_infra_overview_text(db: Session) -> str:
    all_servers = db.query(Server).all()
    linux_all = [s for s in all_servers if not is_windows_server(s)]
    windows_all = [s for s in all_servers if is_windows_server(s)]
    linux_ai = [s for s in linux_all if s.ai_ready]
    windows_ai = [s for s in windows_all if s.ai_ready]
    vms = [s for s in all_servers if is_vm(s)]
    physical = [s for s in all_servers if not is_vm(s)]
    hypervisors = db.query(Hypervisor).all()

    lines = [
        "GENEL ENVANTER OZETI:",
        f"- Toplam sunucu: {len(all_servers)} adet",
        f"- Linux/Unix sunucu: {len(linux_all)} adet ({len(linux_ai)} AI Ready)",
        f"- Windows sunucu: {len(windows_all)} adet ({len(windows_ai)} AI Ready)",
        f"- Sanal makine (VM) toplam: {len(vms)} adet, fiziksel host: {len(physical)} adet",
        f"- Hypervisor/entegrasyon: {len(hypervisors)} adet"
        + (f" ({', '.join(sorted(set(h.hypervisor_type.value for h in hypervisors if h.hypervisor_type)))})" if hypervisors else ""),
    ]
    if linux_ai:
        lines.append("\nAI Ready Linux sunucular:")
        for s in linux_ai:
            lines.append(f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, Durum={s.status}")
    if windows_ai:
        lines.append("\nAI Ready Windows sunucular:")
        for s in windows_ai:
            lines.append(f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}")
    if hypervisors:
        lines.append("\nHypervisorlar:")
        for h in hypervisors:
            vm_count = sum(1 for s in vms if s.hypervisor_id == h.id)
            lines.append(f"- {h.name} ({h.type or '-'}): host={h.hostname or '-'}, durum={h.status or '-'}, VM sayisi={vm_count}")
    return "\n".join(lines)
