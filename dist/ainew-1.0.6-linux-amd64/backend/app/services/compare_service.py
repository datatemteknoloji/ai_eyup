"""
OS / VM / ESX karşılaştırma servisi.

- Linux/Windows: OS config (sürüm, kernel, güvenlik) + kaynaklar
- VM: sanal makine config + vCPU/RAM/disk
- ESX: donanım özellikleri (marka/model, CPU, RAM, NIC) + kapasite
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_active_model
from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.services.platform_scope import is_windows_server

logger = logging.getLogger(__name__)

MAX_ENTITIES = 3


def _nz(v: Any, default: str = "—") -> str:
    if v is None or v == "" or v == []:
        return default
    if isinstance(v, float):
        return f"{v:.2f}" if v != int(v) else str(int(v))
    if isinstance(v, list):
        return ", ".join(str(x) for x in v) if v else default
    return str(v)


def _linux_profile(db: Session, server: Server) -> Dict[str, Any]:
    """Linux OS bazlı karşılaştırma profili."""
    return {
        "id": server.id,
        "label": server.name or server.hostname or server.ip_address,
        "entity_type": "server",
        "platform": "linux",
        "config": {
            "hostname": server.hostname,
            "ip": server.ip_address,
            "os_type": server.os_type,
            "os_version": server.os_version,
            "os_release_id": server.os_release_id,
            "os_version_id": server.os_version_id,
            "kernel": server.kernel_version,
            "status": server.status,
            "tier": server.tier,
            "firewall_active": server.linux_firewall_active,
            "selinux": server.linux_selinux_status,
            "failed_logins_24h": server.linux_failed_logins_24h,
            "ai_ready": server.ai_ready,
            "node_exporter": bool(server.node_exporter_running),
        },
        "architecture": {
            "cpu_cores": server.cpu_cores,
            "memory_gb": server.memory_gb,
            "disk_gb": server.vm_disk_gb,
            "server_type": server.server_type,
        },
    }


def _windows_profile(db: Session, server: Server) -> Dict[str, Any]:
    """Windows OS bazlı karşılaştırma profili."""
    return {
        "id": server.id,
        "label": server.name or server.hostname or server.ip_address,
        "entity_type": "server",
        "platform": "windows",
        "config": {
            "hostname": server.hostname,
            "ip": server.ip_address,
            "os_type": server.os_type,
            "os_version": server.os_version,
            "status": server.status,
            "tier": server.tier,
            "reboot_pending": server.win_reboot_pending,
            "defender_enabled": getattr(server, "win_defender_enabled", None),
            "defender_up_to_date": getattr(server, "win_defender_up_to_date", None),
            "updates_pending": getattr(server, "win_updates_pending", None),
            "updates_critical": getattr(server, "win_updates_critical", None),
            "windows_exporter": bool(getattr(server, "windows_exporter_running", False)),
            "ai_ready": server.ai_ready,
        },
        "architecture": {
            "cpu_cores": server.cpu_cores,
            "memory_gb": server.memory_gb,
            "disk_gb": server.vm_disk_gb,
            "server_type": server.server_type,
        },
    }


def _vm_profile(db: Session, server: Server) -> Dict[str, Any]:
    """Sanal makine (VM) karşılaştırma profili."""
    nets = server.vm_network_info or []
    ip_list = []
    for n in nets if isinstance(nets, list) else []:
        for ip in (n.get("ips") or []):
            if isinstance(ip, dict):
                ip_list.append(ip.get("address"))
            else:
                ip_list.append(str(ip))
    return {
        "id": server.id,
        "label": server.vm_name or server.name or server.hostname,
        "entity_type": "vm",
        "platform": "virt",
        "config": {
            "vm_name": server.vm_name or server.name,
            "guest_hostname": server.vm_guest_hostname or server.hostname,
            "guest_ip": server.vm_guest_ip or server.ip_address,
            "os_type": server.os_type,
            "os_version": server.os_version,
            "power_state": server.vm_power_state,
            "tools_status": server.vm_tools_status,
            "tier": server.tier,
            "hw_version": server.vm_hardware_version,
            "cluster": server.vm_cluster,
            "datastore": server.vm_datastore,
            "hypervisor": server.hypervisor.name if server.hypervisor else None,
        },
        "architecture": {
            "vcpu": server.vm_cpu_count or server.cpu_cores,
            "memory_mb": server.vm_memory_mb,
            "memory_gb": round((server.vm_memory_mb or 0) / 1024, 1) if server.vm_memory_mb else server.memory_gb,
            "disk_gb": server.vm_disk_gb,
            "network_ips": ", ".join([x for x in ip_list if x]) or None,
        },
    }


def _esx_profile(db: Session, hv: Hypervisor) -> Dict[str, Any]:
    """ESX donanım odaklı karşılaştırma profili."""
    inv = (
        db.query(HypervisorHostInventory)
        .filter(HypervisorHostInventory.hypervisor_id == hv.id)
        .order_by(HypervisorHostInventory.id.asc())
        .first()
    )
    metric = (
        db.query(HypervisorHostMetric)
        .filter(HypervisorHostMetric.hypervisor_id == hv.id)
        .order_by(HypervisorHostMetric.timestamp.desc())
        .first()
    )
    vm_count = db.query(Server).filter(Server.hypervisor_id == hv.id).count()
    config: Dict[str, Any] = {
        "name": hv.name,
        "hostname": hv.hostname,
        "ip": hv.ip_address,
        "type": hv.type,
        "status": hv.status,
        "last_sync": hv.last_sync.isoformat() if hv.last_sync else None,
        "vm_count": vm_count,
    }
    # Donanım özellikleri → architecture
    architecture: Dict[str, Any] = {}
    if inv:
        config["dns"] = (inv.dns or {}).get("servers") if isinstance(inv.dns, dict) else None
        architecture.update({
            "vendor": inv.vendor,
            "model": inv.model,
            "uuid": inv.uuid,
            "cpu_model": inv.cpu_model,
            "pnic_count": len(inv.pnics or []),
            "vswitch_count": len(inv.vswitches or []),
            "portgroup_count": len(inv.portgroups or []),
            "vnic_count": len(inv.vnics or []),
        })
        # Fiziksel NIC hız özeti
        speeds = []
        for nic in (inv.pnics or []):
            if isinstance(nic, dict) and nic.get("link_speed_mb"):
                speeds.append(f"{nic.get('device', '?')}:{nic['link_speed_mb']}Mb")
        if speeds:
            architecture["pnic_speeds"] = ", ".join(speeds)
    if metric:
        architecture.update({
            "cpu_cores": metric.cpu_cores,
            "memory_gb": round((metric.mem_total_mb or 0) / 1024, 1) if metric.mem_total_mb else None,
            "cpu_usage_pct": metric.cpu_usage_pct,
            "mem_usage_pct": metric.mem_usage_pct,
            "datastore_usage_pct": metric.ds_usage_pct,
            "vms_running": metric.vms_running,
            "vms_total": metric.vms_total,
            "connection_state": metric.connection_state,
        })
    return {
        "id": hv.id,
        "label": hv.name,
        "entity_type": "esx",
        "platform": "virt",
        "config": config,
        "architecture": architecture,
    }


def list_candidates(db: Session, platform: str, entity_type: str) -> List[Dict[str, Any]]:
    platform = (platform or "linux").lower()
    entity_type = (entity_type or "server").lower()

    if platform == "virt" and entity_type == "esx":
        rows = db.query(Hypervisor).order_by(Hypervisor.name).all()
        return [
            {
                "id": h.id,
                "name": h.name,
                "hostname": h.hostname,
                "ip_address": h.ip_address,
                "status": h.status,
                "type": h.type,
            }
            for h in rows
        ]

    if platform == "virt" and entity_type == "vm":
        rows = (
            db.query(Server)
            .filter(Server.hypervisor_id.isnot(None))
            .order_by(Server.name)
            .limit(500)
            .all()
        )
        return [
            {
                "id": s.id,
                "name": s.vm_name or s.name,
                "hostname": s.vm_guest_hostname or s.hostname,
                "ip_address": s.vm_guest_ip or s.ip_address,
                "status": s.vm_power_state or s.status,
                "os": s.os_version or s.os_type,
                "hypervisor": s.hypervisor.name if s.hypervisor else None,
            }
            for s in rows
        ]

    # linux / windows servers
    rows = db.query(Server).order_by(Server.name).limit(500).all()
    out = []
    for s in rows:
        win = is_windows_server(s)
        if platform == "windows" and not win:
            continue
        if platform == "linux" and win:
            continue
        # virt olmayan fiziksel/VM linux/windows envanteri
        if platform in ("linux", "windows") and s.hypervisor_id and platform == "virt":
            continue
        out.append({
            "id": s.id,
            "name": s.name,
            "hostname": s.hostname,
            "ip_address": s.ip_address,
            "status": s.status,
            "os": s.os_version or s.os_type,
            "cpu_cores": s.cpu_cores,
            "memory_gb": s.memory_gb,
        })
    return out


def build_profiles(
    db: Session,
    platform: str,
    entity_type: str,
    ids: List[int],
) -> List[Dict[str, Any]]:
    if not ids or len(ids) < 2:
        raise ValueError("En az 2 kayıt seçilmeli")
    if len(ids) > MAX_ENTITIES:
        raise ValueError(f"En fazla {MAX_ENTITIES} kayıt karşılaştırılabilir")

    platform = platform.lower()
    entity_type = entity_type.lower()
    profiles: List[Dict[str, Any]] = []

    if platform == "virt" and entity_type == "esx":
        for i in ids:
            hv = db.query(Hypervisor).filter(Hypervisor.id == i).first()
            if not hv:
                raise ValueError(f"Hypervisor bulunamadı: {i}")
            profiles.append(_esx_profile(db, hv))
        return profiles

    if platform == "virt" and entity_type == "vm":
        for i in ids:
            s = db.query(Server).filter(Server.id == i).first()
            if not s or not s.hypervisor_id:
                raise ValueError(f"VM bulunamadı: {i}")
            profiles.append(_vm_profile(db, s))
        return profiles

    for i in ids:
        s = db.query(Server).filter(Server.id == i).first()
        if not s:
            raise ValueError(f"Sunucu bulunamadı: {i}")
        if platform == "windows" or is_windows_server(s):
            profiles.append(_windows_profile(db, s))
        else:
            profiles.append(_linux_profile(db, s))
    return profiles


FIELD_LABELS = {
    "hostname": "Hostname",
    "ip": "IP",
    "os_type": "OS Tipi",
    "os_version": "OS Sürümü",
    "os_release_id": "OS Release",
    "os_version_id": "OS Version ID",
    "kernel": "Kernel",
    "status": "Durum",
    "tier": "Ortam / Tier",
    "firewall_active": "Firewall",
    "selinux": "SELinux",
    "failed_logins_24h": "Başarısız Login (24s)",
    "ai_ready": "AI Ready",
    "node_exporter": "Node Exporter",
    "reboot_pending": "Reboot Bekliyor",
    "defender_enabled": "Defender",
    "defender_up_to_date": "Defender Güncel",
    "updates_pending": "Bekleyen Güncelleme",
    "updates_critical": "Kritik Güncelleme",
    "windows_exporter": "Windows Exporter",
    "cpu_cores": "CPU Çekirdek",
    "memory_gb": "RAM (GB)",
    "disk_gb": "Disk (GB)",
    "server_type": "Sunucu Tipi",
    "hypervisor": "Hypervisor",
    "vm_cluster": "Cluster",
    "vm_datastore": "Datastore",
    "hw_version": "HW Versiyon",
    "vm_name": "VM Adı",
    "guest_hostname": "Guest Hostname",
    "guest_ip": "Guest IP",
    "power_state": "Güç",
    "tools_status": "VMware Tools",
    "cluster": "Cluster",
    "datastore": "Datastore",
    "vcpu": "vCPU",
    "memory_mb": "RAM (MB)",
    "network_ips": "Ağ IP'leri",
    "name": "Ad",
    "type": "Tip",
    "last_sync": "Son Sync",
    "vm_count": "VM Sayısı",
    "vendor": "Vendor (donanım)",
    "model": "Model (donanım)",
    "cpu_model": "CPU Model",
    "dns": "DNS",
    "pnic_count": "Fiziksel NIC sayısı",
    "pnic_speeds": "Fiziksel NIC hızları",
    "vswitch_count": "vSwitch",
    "portgroup_count": "Port Group",
    "vnic_count": "VMkernel NIC",
    "uuid": "UUID",
    "cpu_usage_pct": "CPU %",
    "mem_usage_pct": "RAM %",
    "datastore_usage_pct": "Datastore %",
    "vms_running": "Çalışan VM",
    "vms_total": "Toplam VM",
    "connection_state": "Bağlantı",
}


def compute_diffs(profiles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Alan bazlı karşılaştırma: aynı / farklı."""
    categories = ("config", "architecture")
    result: Dict[str, Any] = {"config": [], "architecture": [], "summary": {}}

    for cat in categories:
        keys: List[str] = []
        seen = set()
        for p in profiles:
            for k in (p.get(cat) or {}):
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        rows = []
        same = diff = 0
        for key in keys:
            values = [_nz((p.get(cat) or {}).get(key)) for p in profiles]
            identical = len(set(values)) == 1
            if identical:
                same += 1
            else:
                diff += 1
            rows.append({
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "values": values,
                "identical": identical,
            })
        result[cat] = rows
        result["summary"][cat] = {"same": same, "different": diff, "total": same + diff}

    result["summary"]["total_same"] = sum(result["summary"][c]["same"] for c in categories)
    result["summary"]["total_different"] = sum(result["summary"][c]["different"] for c in categories)
    return result


def profiles_to_prompt(profiles: List[Dict[str, Any]], diffs: Dict[str, Any]) -> str:
    lines = ["## KARŞILAŞTIRILAN KAYITLAR\n"]
    for i, p in enumerate(profiles):
        lines.append(f"### {i + 1}. {p.get('label')} (id={p.get('id')}, tip={p.get('entity_type')})")
        for cat in ("config", "architecture"):
            lines.append(f"  [{cat}]")
            for k, v in (p.get(cat) or {}).items():
                lines.append(f"    - {FIELD_LABELS.get(k, k)}: {_nz(v)}")
        lines.append("")
    lines.append("## FARK ÖZETİ")
    lines.append(
        f"Aynı alan: {diffs['summary']['total_same']}, "
        f"Farklı alan: {diffs['summary']['total_different']}"
    )
    for cat in ("config", "architecture"):
        diff_rows = [r for r in diffs.get(cat, []) if not r["identical"]]
        if not diff_rows:
            continue
        lines.append(f"\n### Farklı {cat} alanları")
        for r in diff_rows:
            pairs = ", ".join(f"{profiles[i]['label']}={r['values'][i]}" for i in range(len(profiles)))
            lines.append(f"- {r['label']}: {pairs}")
    return "\n".join(lines)


async def ai_interpret(
    db: Session,
    profiles: List[Dict[str, Any]],
    diffs: Dict[str, Any],
    question: Optional[str] = None,
) -> str:
    """LLM ile karşılaştırma yorumu üret."""
    from app.services.llm_gateway import generate_async

    entity = (profiles[0].get("entity_type") if profiles else "server") or "server"
    context = profiles_to_prompt(profiles, diffs)

    if entity == "esx":
        default_q = (
            "Bu ESX hostları donanım özellikleri (vendor, model, CPU, RAM, NIC) ve "
            "kapasite açısından karşılaştır. Kritik donanım farklarını ve riskleri madde madde yaz."
        )
        system = (
            "Sen bir sanallaştırma/altyapı mühendisisin. ESX donanım karşılaştırmasını "
            "Türkçe, net ve uygulanabilir yorumla. Uydurma veri ekleme."
        )
    elif entity == "vm":
        default_q = (
            "Bu sanal makineleri VM config ve kaynak (vCPU/RAM/disk) açısından karşılaştır. "
            "Kritik farkları ve hizalama önerilerini madde madde yaz."
        )
        system = (
            "Sen bir sanallaştırma mühendisisin. VM karşılaştırmasını Türkçe, net yorumla. "
            "Uydurma veri ekleme."
        )
    else:
        default_q = (
            "Bu kayıtları OS config (sürüm, kernel/güvenlik) ve kaynaklar açısından karşılaştır. "
            "Kritik OS farklarını, güvenlik boşluklarını ve hizalama önerilerini madde madde yaz."
        )
        system = (
            "Sen bir sistem yöneticisisin. OS bazlı karşılaştırmayı Türkçe, net yorumla. "
            "Uydurma veri ekleme; sadece bağlamdaki farklara dayan."
        )

    user_q = (question or "").strip() or default_q
    prompt = f"{system}\n\n{context}\n\n## SORU\n{user_q}\n\n## YANIT\n"
    model = get_active_model(db)
    try:
        data = await generate_async(
            model=model,
            prompt=prompt,
            options={"temperature": 0.2, "num_predict": 1200},
            timeout=90.0,
        )
        text = (data or {}).get("response") or ""
        if not text and isinstance(data, dict):
            msg = (data.get("message") or {})
            text = msg.get("content") or ""
        return text.strip() or "AI yorumu üretilemedi (boş yanıt)."
    except Exception as e:
        logger.warning("Karşılaştırma AI yorumu başarısız: %s", e)
        return f"AI yorumu alınamadı: {e}"


async def run_compare(
    db: Session,
    *,
    platform: str,
    entity_type: str,
    ids: List[int],
    with_ai: bool = True,
    question: Optional[str] = None,
) -> Dict[str, Any]:
    profiles = build_profiles(db, platform, entity_type, ids)
    diffs = compute_diffs(profiles)
    ai_text = None
    if with_ai:
        ai_text = await ai_interpret(db, profiles, diffs, question)
    return {
        "platform": platform,
        "entity_type": entity_type,
        "profiles": profiles,
        "diffs": diffs,
        "ai_analysis": ai_text,
        "labels": [p.get("label") for p in profiles],
    }
