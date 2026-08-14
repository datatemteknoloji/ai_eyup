"""
Altyapı envanter özeti — platform-scoped.

Unified / platform=None → tüm altyapı.
linux / windows / openshift / virt / exadata → yalnızca o yüzey.
Böylece Linux AI sohbeti Windows/OCP/HV sızdırmaz; Unified çapraz kalır.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.services.platform_scope import (
    get_exadata_server_id_set,
    is_linux_module_server,
    is_vm,
    is_windows_server,
)


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


def _normalize_scope(platform: Optional[str]) -> Optional[str]:
    if not platform:
        return None
    p = platform.strip().lower()
    if p in ("", "unified", "all", "*"):
        return None
    if p in ("linux", "windows", "openshift", "virt", "exadata"):
        return p
    return None


def build_infra_overview_text(db: Session, platform: Optional[str] = None) -> str:
    """
    platform=None/unified → GENEL (tüm altyapı).
    platform=linux|windows|... → yalnızca o sohbet kapsamı.
    """
    scope = _normalize_scope(platform)
    if scope == "linux":
        return _linux_overview(db)
    if scope == "windows":
        return _windows_overview(db)
    if scope == "openshift":
        return _openshift_overview(db)
    if scope == "virt":
        return _virt_overview(db)
    if scope == "exadata":
        return _exadata_overview(db)
    return _full_overview(db)


def _linux_overview(db: Session) -> str:
    exadata_ids = get_exadata_server_id_set(db)
    all_servers = db.query(Server).all()
    linux = [
        s for s in all_servers
        if is_linux_module_server(s, exadata_ids) and not is_windows_server(s)
    ]
    ai = [s for s in linux if s.ai_ready]
    online = [s for s in linux if (s.status or "").upper() in ("ONLINE", "UP", "RUNNING")]
    lines = [
        "LINUX ENVANTER OZETI (bu sohbet yalnizca Linux kapsami):",
        f"- Linux/Unix sunucu kaydi: {len(linux)} adet",
        f"- AI Ready: {len(ai)} adet",
        f"- ONLINE (yaklasik): {len(online)} adet",
        "",
        "NOT: Windows, hypervisor ve OpenShift bu ozetten HARICTIR. "
        "Capraz altyapi icin Unified Chat / ilgili platform asistanini kullanin.",
    ]
    if ai:
        lines.append("\nAI Ready Linux sunucular:")
        for s in ai[:40]:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, Durum={s.status}"
            )
        if len(ai) > 40:
            lines.append(f"- … ve {len(ai) - 40} diger")
    return "\n".join(lines)


def _windows_overview(db: Session) -> str:
    all_servers = db.query(Server).all()
    wins = [s for s in all_servers if is_windows_server(s)]
    ai = [s for s in wins if s.ai_ready]
    lines = [
        "WINDOWS ENVANTER OZETI (bu sohbet yalnizca Windows kapsami):",
        f"- Windows sunucu kaydi: {len(wins)} adet",
        f"- AI Ready (WinRM): {len(ai)} adet",
        "",
        "NOT: Linux / OpenShift / hypervisor bu ozetten HARICTIR.",
    ]
    if ai:
        lines.append("\nAI Ready Windows sunucular:")
        for s in ai[:40]:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}"
            )
    return "\n".join(lines)


def _openshift_overview(db: Session) -> str:
    lines = [
        "OPENSHIFT ENVANTER OZETI (bu sohbet yalnizca OCP kapsami):",
    ]
    try:
        from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject
        clusters = db.query(OpenShiftCluster).order_by(OpenShiftCluster.name).all()
        lines.append(f"- Cluster sayisi: {len(clusters)}")
        for c in clusters:
            n_nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).count()
            n_proj = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == c.id).count()
            lines.append(
                f"- {c.name}: api={c.api_url or '-'}, surum={c.version or '-'}, "
                f"durum={c.status or '-'}, node={n_nodes}, proje={n_proj}"
            )
        if not clusters:
            lines.append("- Tanimli OpenShift cluster yok.")
    except Exception as e:
        lines.append(f"- OpenShift envanteri okunamadi: {e}")
    lines.append(
        "\nNOT: Linux OS envanteri ve vCenter hypervisor satirlari bu ozetten HARICTIR. "
        "OpenShift Virtualization (KubeVirt) VirtualMachine'ler bu OCP yuzeyinin "
        "sanallastirma workload'udur — 'OV sanallastirma sayilmaz' denmemeli."
    )
    return "\n".join(lines)


def _virt_overview(db: Session) -> str:
    all_servers = db.query(Server).all()
    vms = [s for s in all_servers if is_vm(s)]
    hypervisors = db.query(Hypervisor).all()
    esxi_hosts = _esxi_host_count(db)
    lines = [
        "SANALLASTIRMA ENVANTER OZETI (bu sohbet yalnizca virt/vCenter kapsami):",
        f"- Hypervisor/entegrasyon baglantisi: {len(hypervisors)} adet",
        f"- ESX/KVM host (senkronize): {esxi_hosts} adet",
        f"- OS envanterinde VM kaydi: {len(vms)} adet",
    ]
    if hypervisors:
        lines.append("\nHypervisorlar:")
        for h in hypervisors:
            vm_count = sum(1 for s in vms if s.hypervisor_id == h.id)
            hv_type = (
                h.hypervisor_type.value if h.hypervisor_type else (h.type or "-")
            )
            lines.append(
                f"- {h.name} ({hv_type}): host={h.hostname or h.ip_address or '-'}, "
                f"durum={h.status or '-'}, bagli VM={vm_count}"
            )
    lines.append(
        "\nNOT: Linux SSH yonetimi ve OpenShift pod envanteri bu ozetten HARICTIR. "
        "OpenShift Virtualization (KubeVirt) ayrica OpenShift → Virtual Machines "
        "yuzeyinde yonetilir; hypervisor satiri yoksa bile OV sanallastirmadir "
        "(openshift_virt kaydi veya OCP KubeVirt). Yalnizca VMware listesine bakip "
        "'OV yok/sayilmaz' deme."
    )
    return "\n".join(lines)


def _exadata_overview(db: Session) -> str:
    exadata_ids = get_exadata_server_id_set(db)
    all_servers = db.query(Server).all()
    nodes = [s for s in all_servers if s.id in exadata_ids]
    lines = [
        "EXADATA ENVANTER OZETI (bu sohbet yalnizca Exadata kapsami):",
        f"- Exadata'ya bagli sunucu/node kaydi: {len(nodes)} adet",
    ]
    try:
        from app.models.exadata import ExadataRack
        racks = db.query(ExadataRack).all()
        lines.append(f"- Exadata rack kaydi: {len(racks)} adet")
        for r in racks[:20]:
            lines.append(
                f"- {r.name}: model={r.model or '-'}, durum={r.status or '-'}"
            )
    except Exception:
        pass
    if nodes:
        lines.append("\nExadata node'lari:")
        for s in nodes[:40]:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or '-'}, Durum={s.status}"
            )
    lines.append(
        "\nNOT: Genel Linux filo ve Windows bu ozetten HARICTIR."
    )
    return "\n".join(lines)


def _full_overview(db: Session) -> str:
    all_servers = db.query(Server).all()
    linux_all = [s for s in all_servers if not is_windows_server(s)]
    windows_all = [s for s in all_servers if is_windows_server(s)]
    linux_ai = [s for s in linux_all if s.ai_ready]
    windows_ai = [s for s in windows_all if s.ai_ready]
    vms = [s for s in all_servers if is_vm(s)]
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
        "GENEL ENVANTER OZETI (Unified / tum altyapi):",
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
    _NAME_CAP = 40
    if linux_ai:
        lines.append("\nAI Ready Linux sunucular:")
        for s in linux_ai[:_NAME_CAP]:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, Durum={s.status}"
            )
        if len(linux_ai) > _NAME_CAP:
            lines.append(f"- … ve {len(linux_ai) - _NAME_CAP} diger")
    if windows_ai:
        lines.append("\nAI Ready Windows sunucular:")
        for s in windows_ai[:_NAME_CAP]:
            lines.append(
                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}"
            )
        if len(windows_ai) > _NAME_CAP:
            lines.append(f"- … ve {len(windows_ai) - _NAME_CAP} diger")
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
        "birbirinin yerine kullanılmamalı. "
        "OpenShift Virtualization (KubeVirt) OpenShift → Virtual Machines yüzeyinde "
        "yönetilir ve sanallaştırma ortamı SAYILIR; yalnızca hypervisors listesinde "
        "VMware görmek 'OV yok' anlamına gelmez."
    )
    return "\n".join(lines)
