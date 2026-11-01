"""Incident detayındaki «İlgili donanım» kartı verisi.

İki yoldan donanım bulunur: (1) incident'ın `hw_*` olayları (olay → donanım kaydı); (2) incident'ın etkilenen
sunucularından (`affected_servers`) eşleşmiş donanım kaydı — donanım sağlığı ok değilse (ör. CPU alarmı veren sunucunun
diski/PSU'su arızalı). Çıktı HER ZAMAN özetlenmiştir: BMC IP, seri/service tag, UUID, konsol bağlantısı YOK.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.event import Incident, SystemEvent
from app.models.hw import HwAlert, HwHostLink, HwServer
from app.services.hw.demo_gate import active_instances, hw_mode
from app.services.hw.events import HW_EVENT_TYPES, sanitize_text


def hardware_for_incident(db: Session, inc: Incident) -> Dict[str, Any]:
    mode = hw_mode(db)
    if mode == "none":
        return {"enabled": False, "items": []}
    ids = [i.id for i in active_instances(db, include_demo=(mode == "demo"))] or [-1]
    hw_ids: Dict[int, List[int]] = {}      # hw_server_id → olay id'leri
    impact: Dict[int, Dict[str, Any]] = {}
    ev_ids = list(inc.related_events or [])
    if ev_ids:
        for ev in db.query(SystemEvent).filter(SystemEvent.id.in_(ev_ids), SystemEvent.event_type.in_(HW_EVENT_TYPES)).all():
            raw = ev.raw_data or {}
            hid = raw.get("hw_server_id")
            if hid:
                hw_ids.setdefault(int(hid), []).append(ev.id)
                if raw.get("impact"):
                    impact[int(hid)] = raw["impact"]
    via_event = set(hw_ids)
    sids = [int(x) for x in (inc.affected_servers or []) if str(x).isdigit()]
    if sids:
        for l in db.query(HwHostLink).filter(HwHostLink.target_kind == "server", HwHostLink.target_id.in_(sids)).all():
            hw_ids.setdefault(l.hw_server_id, [])
    items: List[Dict[str, Any]] = []
    if not hw_ids:
        return {"enabled": True, "items": items}
    servers = db.query(HwServer).filter(HwServer.id.in_(list(hw_ids)), HwServer.instance_id.in_(ids)).all()
    for s in servers:
        if s.id not in via_event and s.health in ("ok", "unknown"):
            continue                       # yalnız-affected yolu: sağlıklı donanım gürültü olmasın
        alerts = (db.query(HwAlert).filter(HwAlert.instance_id == s.instance_id, HwAlert.server_ref == s.provider_ref,
                                           HwAlert.state == "active").order_by(HwAlert.occurred_at.desc()).limit(5).all())
        link = db.query(HwHostLink).filter(HwHostLink.hw_server_id == s.id).first()
        items.append({
            "hw_server_id": s.id, "name": s.name, "vendor": s.vendor, "model": s.model, "health": s.health,
            "power_state": s.power_state, "connected": s.connected,
            "enclosure": (f"{s.enclosure_name}{' / ' + str(s.bay) if s.bay else ''}" if s.enclosure_name else None),
            "link": ({"kind": link.target_kind, "id": link.target_id} if link else None),
            "event_ids": hw_ids.get(s.id, []), "via": "event" if s.id in via_event else "affected_server",
            "alerts": [{"severity": a.severity, "message": sanitize_text(a.message, s, 200),
                        "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None} for a in alerts],
            "impact": impact.get(s.id),
        })
    return {"enabled": True, "demo": mode == "demo", "items": items}
