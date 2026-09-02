"""Modüller arası envanter eşleştirme — READ-ONLY join (hostname / vm_name / ip).

linux servers ⋈ virt VM/host ⋈ (isim/IP). OpenShift pod eşlemesi ad/IP ile sınırlı.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.server import Server
from app.services.entity_projection import norm_join_key
from app.services.platform_scope import is_linux_server, is_windows_server, vm_filter_condition


def cross_entity_match(
    db: Session,
    *,
    names: Optional[Sequence[str]] = None,
    modules: Optional[Sequence[str]] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """İsim/IP listesini modül envanterlerinde ara ve tek satırda birleştir."""
    wanted_mods = {
        (m or "").strip().lower()
        for m in (modules or ["linux", "windows", "virt", "openshift"])
    }
    raw_names = [str(n).strip() for n in (names or []) if str(n).strip()]
    if not raw_names:
        return {
            "ok": False,
            "error": "names gerekli (hostname / vm_name / ip)",
            "hint": "Örn. names=[office, Atlas App]",
        }

    rows: List[Dict[str, Any]] = []
    for raw in raw_names[: max(1, min(int(limit or 50), 100))]:
        key = norm_join_key(raw)
        item: Dict[str, Any] = {
            "query": raw,
            "match_key": key,
            "linux": None,
            "windows": None,
            "virt_vm": None,
            "virt_host": None,
            "sources": [],
        }

        if "linux" in wanted_mods or "windows" in wanted_mods or "virt" in wanted_mods:
            servers = (
                db.query(Server)
                .filter(
                    (Server.name.ilike(f"%{raw}%"))
                    | (Server.ip_address == raw)
                    | (Server.vm_guest_ip == raw)
                    | (Server.vm_name.ilike(f"%{raw}%"))
                    | (Server.vm_guest_hostname.ilike(f"%{raw}%"))
                )
                .limit(8)
                .all()
            )
            for s in servers:
                payload = {
                    "id": s.id,
                    "name": s.name,
                    "ip": s.ip_address or s.vm_guest_ip,
                    "os_type": s.os_type,
                    "ai_ready": bool(s.ai_ready),
                }
                if s.hypervisor_id and "virt" in wanted_mods:
                    item["virt_vm"] = {
                        **payload,
                        "vm_name": s.vm_name or s.name,
                        "host": s.vm_host_name,
                        "power_state": s.vm_power_state,
                        "hypervisor_id": s.hypervisor_id,
                    }
                    item["sources"].append("virt_vm")
                elif is_windows_server(s) and "windows" in wanted_mods:
                    item["windows"] = payload
                    item["sources"].append("windows")
                elif is_linux_server(s) and "linux" in wanted_mods:
                    item["linux"] = payload
                    item["sources"].append("linux")

        if "virt" in wanted_mods:
            if not item["virt_vm"]:
                vm = (
                    db.query(Server)
                    .filter(vm_filter_condition())
                    .filter(
                        (Server.vm_name.ilike(f"%{raw}%"))
                        | (Server.name.ilike(f"%{raw}%"))
                        | (Server.vm_guest_hostname.ilike(f"%{raw}%"))
                    )
                    .first()
                )
                if vm:
                    item["virt_vm"] = {
                        "id": vm.id,
                        "name": vm.name,
                        "vm_name": vm.vm_name or vm.name,
                        "ip": vm.vm_guest_ip or vm.ip_address,
                        "host": vm.vm_host_name,
                        "power_state": vm.vm_power_state,
                        "hypervisor_id": vm.hypervisor_id,
                    }
                    item["sources"].append("virt_vm")
            inv = (
                db.query(HypervisorHostInventory)
                .filter(HypervisorHostInventory.host_name.ilike(f"%{raw}%"))
                .first()
            )
            if inv:
                hv = db.query(Hypervisor).filter(Hypervisor.id == inv.hypervisor_id).first()
                item["virt_host"] = {
                    "host_name": inv.host_name,
                    "host_ref": inv.host_ref,
                    "hypervisor": hv.name if hv else None,
                    "version": inv.product_version,
                    "vendor": inv.vendor,
                    "model": inv.model,
                }
                item["sources"].append("virt_host")

        item["sources"] = sorted(set(item["sources"]))
        item["matched"] = bool(item["sources"])
        rows.append(item)

    matched = sum(1 for r in rows if r["matched"])
    return {
        "ok": True,
        "read_only": True,
        "count": len(rows),
        "matched": matched,
        "unmatched": len(rows) - matched,
        "rows": rows,
        "hint": (
            "Modüller arası envanter join. Canlı SSH/QueryPerf için ilgili tool'ları "
            "çağırıp bu anahtarlarla birleştir."
        ),
    }
