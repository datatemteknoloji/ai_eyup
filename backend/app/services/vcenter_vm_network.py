"""
vCenter VM ağ / VLAN — canlı SOAP sorgusu.

DB'de per-VM VLAN tutulmaz; AI "vmlerin vlan idlerini ver" tarzı sorularda
`VCenterClient.get_all_vm_network_vlans()` ile anlık çeker (standart vSwitch + vDS).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.services.hypervisor_credentials import hv_password

logger = logging.getLogger(__name__)


def _vmware_hypervisors(db: Session) -> List[Hypervisor]:
    return [
        hv for hv in db.query(Hypervisor).all()
        if (hv.hypervisor_type.value if hv.hypervisor_type else "") == "vmware"
    ]


def _build_client(hv: Hypervisor):
    from app.services.vmware.vcenter_client import VCenterClient
    return VCenterClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or (hv.connection_config or {}).get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
        verify_ssl=False,
    )


def fetch_live_vm_vlans(db: Session) -> Dict[str, Any]:
    """Tüm VMware hypervisor'lardan VM NIC → port-group → VLAN listesini döner."""
    hvs = _vmware_hypervisors(db)
    if not hvs:
        return {"rows": [], "errors": ["Tanımlı VMware hypervisor yok"], "hypervisors": 0}

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for hv in hvs:
        client = _build_client(hv)
        try:
            raw = client.get_all_vm_network_vlans() or []
        except Exception as exc:
            logger.error("get_all_vm_network_vlans failed for %s: %s", hv.name, exc, exc_info=True)
            errors.append(f"{hv.name}: {exc}")
            continue
        for r in raw:
            rows.append({
                **r,
                "hypervisor": hv.name,
            })

    rows.sort(key=lambda x: ((x.get("vm_name") or "").lower(), x.get("nic") or ""))
    return {"rows": rows, "errors": errors, "hypervisors": len(hvs)}
