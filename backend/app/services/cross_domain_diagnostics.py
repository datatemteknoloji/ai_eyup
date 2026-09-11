"""Linux guest iowait × vCenter VM disk latency — aynı pencere, join şart.

Graph yok. Eşleşme yalnızca servers.hypervisor_id / vm_name / IP.
Metrik yoksa uydurulmaz; data_status ile ayrılır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.server import Server
from app.services.chat_data_status import (
    NOT_QUERIED,
    PARTIAL,
    SUCCESS,
    SUCCESS_EMPTY,
)
from app.services.platform_scope import is_linux_server, vm_filter_condition

logger = logging.getLogger(__name__)

TH = {
    "guest_iowait_pct": 20.0,   # chat.py / anomaly_detector ile uyumlu
    "vm_disk_latency_ms": 20.0,  # virt_diagnostics.TH
}

_IOWAIT_SQL = """
    SELECT count(*) AS samples,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS iowait_p95
    FROM metric_data
    WHERE server_id = :sid
      AND metric_name = 'cpu_iowait_percent'
      AND timestamp >= now() - (:hours * interval '1 hour')
"""

_VM_DLAT_SQL = """
    SELECT max(vm_name) AS vm_name,
           max(host_name) AS host_name,
           count(*) AS samples,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_latency_ms) AS dlat_p95
    FROM virt_vm_metrics
    WHERE timestamp >= now() - (:hours * interval '1 hour')
      AND vm_name ILIKE :vm
    GROUP BY vm_name
    ORDER BY dlat_p95 DESC NULLS LAST
    LIMIT 1
"""


def _f(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def classify_io_pair(
    guest_iowait_p95: Optional[float],
    vm_disk_latency_p95_ms: Optional[float],
) -> Dict[str, Any]:
    """Saf kural — DB yok. Eksik kanıtta korelasyon iddia etme."""
    iw = _f(guest_iowait_p95)
    dl = _f(vm_disk_latency_p95_ms)
    iw_hi = iw is not None and iw > TH["guest_iowait_pct"]
    dl_hi = dl is not None and dl > TH["vm_disk_latency_ms"]

    if iw is None and dl is None:
        return {
            "layer": "unknown",
            "severity": "none",
            "correlated": False,
            "verdict": "Aynı pencerede ne guest iowait ne VM disk latency ölçümü var.",
            "action": "metric_sync / virt metrik collect kontrol edin.",
        }
    if iw is None:
        return {
            "layer": "virt_only",
            "severity": "medium" if dl_hi else "none",
            "correlated": False,
            "verdict": (
                "VM disk latency ölçüldü ama guest iowait yok; Linux×virt korelasyon kurulamadı."
                if dl_hi else
                "Guest iowait yok; VM disk latency eşik altında."
            ),
            "action": "Linux node_exporter / metric_data cpu_iowait_percent bekleyin.",
        }
    if dl is None:
        return {
            "layer": "guest_only",
            "severity": "medium" if iw_hi else "none",
            "correlated": False,
            "verdict": (
                "Guest iowait yüksek ama vCenter disk latency yok; hypervisor depolama kanıtı yok."
                if iw_hi else
                "vCenter disk latency yok; guest iowait eşik altında."
            ),
            "action": "virt_vm_metrics / disk_latency_ms sync kontrol edin.",
        }
    if iw_hi and dl_hi:
        return {
            "layer": "storage",
            "severity": "high",
            "correlated": True,
            "verdict": (
                "Aynı pencerede guest iowait ve VM disk latency birlikte yüksek — "
                "depolama katmanı korelasyonu."
            ),
            "action": "Datastore/LUN ve guest I/O kuyruğunu birlikte inceleyin.",
        }
    if iw_hi and not dl_hi:
        return {
            "layer": "guest",
            "severity": "medium",
            "correlated": False,
            "verdict": "Guest iowait yüksek, vCenter disk latency normal — sorun guest/OS veya kuyruk.",
            "action": "iostat/kuyruk ve snapshot zincirine bakın; host datastore'u suçlamayın.",
        }
    if dl_hi and not iw_hi:
        return {
            "layer": "hypervisor",
            "severity": "medium",
            "correlated": False,
            "verdict": "VM disk latency yüksek, guest iowait normal — hypervisor/storage tarafı.",
            "action": "ESXi/datastore latency; guest beklemiyor olabilir.",
        }
    return {
        "layer": "none",
        "severity": "none",
        "correlated": False,
        "verdict": "Ölçülen pencerede iowait ve disk latency eşik altında.",
        "action": "-",
    }


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _same_ip(a: Server, b: Server) -> bool:
    ips_a = {x for x in (a.ip_address, a.vm_guest_ip) if x}
    ips_b = {x for x in (b.ip_address, b.vm_guest_ip) if x}
    return bool(ips_a & ips_b)


def _same_vm_name(a: Server, b: Server) -> bool:
    names_a = {_norm(x) for x in (a.vm_name, a.name, a.vm_guest_hostname) if x}
    names_b = {_norm(x) for x in (b.vm_name, b.name, b.vm_guest_hostname) if x}
    return bool(names_a & names_b)


def _proven_join(linux: Optional[Server], virt: Optional[Server]) -> Optional[str]:
    if linux is None or virt is None:
        return None
    if linux.id == virt.id:
        return "same_row"
    if _same_ip(linux, virt):
        return "ip"
    if _same_vm_name(linux, virt):
        if linux.hypervisor_id and virt.hypervisor_id and linux.hypervisor_id == virt.hypervisor_id:
            return "hypervisor_id"
        return "name"
    return None


def resolve_linux_virt_pair(db: Session, name: str) -> Dict[str, Any]:
    raw = (name or "").strip()
    if not raw:
        return {"ok": False, "error": "name gerekli (hostname / vm_name / ip)", "join": None}

    q = db.query(Server).filter(
        (Server.name.ilike(f"%{raw}%"))
        | (Server.ip_address == raw)
        | (Server.vm_guest_ip == raw)
        | (Server.vm_name.ilike(f"%{raw}%"))
        | (Server.vm_guest_hostname.ilike(f"%{raw}%"))
    )
    rows = q.limit(12).all()
    linux = next((s for s in rows if is_linux_server(s)), None)
    virt = next((s for s in rows if s.hypervisor_id), None)
    if virt is None:
        virt = (
            db.query(Server)
            .filter(vm_filter_condition())
            .filter(
                (Server.vm_name.ilike(f"%{raw}%"))
                | (Server.name.ilike(f"%{raw}%"))
                | (Server.vm_guest_hostname.ilike(f"%{raw}%"))
            )
            .first()
        )
    if linux is None and virt is not None and is_linux_server(virt):
        linux = virt

    if linux is None and virt is None:
        return {"ok": True, "join": None, "linux": None, "virt_vm": None}

    join = _proven_join(linux, virt)

    return {
        "ok": True,
        "join": join,
        "linux": None if linux is None else {
            "id": linux.id,
            "name": linux.name,
            "ip": linux.ip_address or linux.vm_guest_ip,
        },
        "virt_vm": None if virt is None else {
            "id": virt.id,
            "vm_name": virt.vm_name or virt.name,
            "host": virt.vm_host_name,
            "hypervisor_id": virt.hypervisor_id,
        },
    }


def _guest_iowait(db: Session, server_id: int, hours: float) -> Dict[str, Any]:
    try:
        row = db.execute(text(_IOWAIT_SQL), {"sid": server_id, "hours": hours}).first()
        mapping = dict(row._mapping) if row else {}
        val = _f(mapping.get("iowait_p95"))
        samples = int(mapping.get("samples") or 0)
        if val is not None and samples:
            return {"value": val, "samples": samples, "source": "metric_data"}
    except Exception as exc:
        logger.debug("guest iowait metric_data: %s", exc)
    try:
        from app.models.linux_inventory import LinuxInventory
        inv = db.query(LinuxInventory).filter(LinuxInventory.server_id == server_id).first()
        snap = _f(getattr(inv, "cpu_iowait_percent", None) if inv else None)
        if snap is not None:
            return {"value": snap, "samples": 1, "source": "linux_inventory_snapshot"}
    except Exception as exc:
        logger.debug("guest iowait inventory: %s", exc)
    return {"value": None, "samples": 0, "source": None}


def _vm_disk_latency(db: Session, vm_name: str, hours: float) -> Dict[str, Any]:
    try:
        row = db.execute(
            text(_VM_DLAT_SQL), {"hours": hours, "vm": f"%{vm_name}%"}
        ).first()
        mapping = dict(row._mapping) if row else {}
        val = _f(mapping.get("dlat_p95"))
        samples = int(mapping.get("samples") or 0)
        return {
            "value": val,
            "samples": samples,
            "vm_name": mapping.get("vm_name"),
            "host_name": mapping.get("host_name"),
            "source": "virt_vm_metrics" if samples else None,
        }
    except Exception as exc:
        logger.debug("vm disk latency: %s", exc)
        return {"value": None, "samples": 0, "source": None}


def correlate_linux_virt_io(
    db: Session,
    *,
    name: Optional[str] = None,
    hours: float = 24,
) -> Dict[str, Any]:
    raw = (name or "").strip()
    if not raw:
        return {
            "ok": False,
            "data_status": NOT_QUERIED,
            "error": "name gerekli (Linux hostname / VM adı / IP)",
        }
    window = max(0.25, min(float(hours or 24), 168.0))
    pair = resolve_linux_virt_pair(db, raw)
    if not pair.get("ok"):
        return {**pair, "data_status": NOT_QUERIED}
    if not pair.get("linux") and not pair.get("virt_vm"):
        return {
            "ok": True,
            "data_status": SUCCESS_EMPTY,
            "join": None,
            "window_hours": window,
            "note": "Bu ad/IP ile Linux veya VM kaydı bulunamadı — korelasyon yok.",
            "thresholds": dict(TH),
        }
    if pair.get("linux") and pair.get("virt_vm") and not pair.get("join"):
        return {
            "ok": True,
            "data_status": PARTIAL,
            "join": pair.get("join"),
            "linux": pair.get("linux"),
            "virt_vm": pair.get("virt_vm"),
            "window_hours": window,
            "note": "Linux ve VM bulundu ama güvenilir join yok; metrik birleştirilmedi.",
            "thresholds": dict(TH),
        }

    linux = pair.get("linux") or {}
    virt = pair.get("virt_vm") or {}
    guest = (
        _guest_iowait(db, int(linux["id"]), window)
        if linux.get("id") else {"value": None, "samples": 0, "source": None}
    )
    vm_lat = (
        _vm_disk_latency(db, str(virt.get("vm_name") or ""), window)
        if virt.get("vm_name") else {"value": None, "samples": 0, "source": None}
    )
    finding = classify_io_pair(guest.get("value"), vm_lat.get("value"))
    both = guest.get("value") is not None and vm_lat.get("value") is not None
    status = SUCCESS if both else PARTIAL
    return {
        "ok": True,
        "data_status": status,
        "join": pair.get("join"),
        "window_hours": window,
        "thresholds": dict(TH),
        "linux": linux or None,
        "virt_vm": virt or None,
        "guest_iowait_p95": guest.get("value"),
        "guest_iowait_source": guest.get("source"),
        "guest_samples": guest.get("samples"),
        "vm_disk_latency_p95_ms": vm_lat.get("value"),
        "vm_latency_source": vm_lat.get("source"),
        "vm_samples": vm_lat.get("samples"),
        **finding,
    }
