"""Donanım durumu → SystemEvent (→ Incident/RCA).

Neden: donanım alarmları yalnız Donanım ekranında kalıyordu; olay/incident/RCA/bildirim hattına girmiyordu.
Burada sağlayıcıdan çekilen DURUM (kritik sağlık, aktif kritik alarm, tekrarlayan uyarı) `SystemEvent` olarak
yazılır; böylece mevcut `incident_auto` (kritik → incident), olay listesi, RCA ve bildirimler hiç değişmeden çalışır.

Kurallar
* Yalnız GERÇEK sağlayıcı (``hw_mode == "real"``). DEMO varsayılanda olay üretmez (bulgu/rapor/skor ile aynı ilke);
  ``allow_demo=True`` (seed betiği ``events`` komutu) etiketli ``hw_demo`` kaynağıyla üretir, cleanup siler.
* Tekilleştirme: ``raw_data.external_key`` (aynı sunucu + aynı alarm tipi = TEK satır; tekrar → ``occurrence_count``).
  Koşul kalkınca satır ``resolved`` olur; geri gelirse yeniden açılır. Incident'ı kullanıcı kapatır.
* Platform etiketi: Linux/Windows sunucuya eşleşen donanım → o platformun olay listesi; ESXi host → sanallaştırma;
  eşleşmeyen → platformsuz (``hardware``). Yetki: olaylar mevcut ``/events``/``/incidents`` politikasını izler.
* Gizlilik: olay metni/raw_data BMC IP, seri/service tag, UUID, web_url İÇERMEZ (olaylar geniş kitleye görünür).
* Etki: ESXi hostta çalışan VM sayısı ve iş servisleri `raw_data.impact` içine yazılır.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.hw import HwAlert, HwHostLink, HwServer
from app.services.hw.constants import HEALTH_CRITICAL, SEV_CRITICAL, SEV_WARNING
from app.services.hw.demo_gate import active_instances, hw_mode

logger = logging.getLogger(__name__)

SOURCE_REAL = "hw_provider"
SOURCE_DEMO = "hw_demo"
ET_HEALTH = "hw_health_critical"
ET_ALERT = "hw_alert"
ET_RECUR = "hw_alert_recurring"
HW_EVENT_TYPES = (ET_HEALTH, ET_ALERT, ET_RECUR)
RECUR_THRESHOLD = 3
RECUR_WINDOW_H = 24
LOOKBACK_DAYS = 7

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def sanitize_text(msg: Optional[str], s: Optional[HwServer] = None, limit: int = 300) -> str:
    """BMC IP / IPv4 / seri / UUID değerlerini maskele (olay metni geniş kitleye görünür)."""
    out = _IPV4.sub("[ip]", msg or "")
    if s is not None:
        for tok in (s.serial, s.virtual_serial, s.uuid, s.virtual_uuid, s.bmc_ip):
            if tok and len(str(tok)) >= 4:
                out = re.sub(re.escape(str(tok)), "[id]", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()[:limit]


def _link_targets(db: Session, links: Dict[int, HwHostLink]) -> Dict[int, Dict[str, Any]]:
    """hw_server_id → {kind, id, name, platform, server_id, hypervisor_id, host_ref, cluster}."""
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.models.server import Server
    from app.services.platform_scope import platform_for_server

    sids = [l.target_id for l in links.values() if l.target_kind == "server"]
    eids = [l.target_id for l in links.values() if l.target_kind == "esxi"]
    srv = {s.id: s for s in db.query(Server).filter(Server.id.in_(sids or [-1])).all()}
    esx = {e.id: e for e in db.query(HypervisorHostInventory).filter(HypervisorHostInventory.id.in_(eids or [-1])).all()}
    out: Dict[int, Dict[str, Any]] = {}
    for hid, l in links.items():
        if l.target_kind == "server" and l.target_id in srv:
            s = srv[l.target_id]
            out[hid] = {"kind": "server", "id": s.id, "name": s.name, "server_id": s.id, "platform": platform_for_server(db, s)}
        elif l.target_kind == "esxi" and l.target_id in esx:
            e = esx[l.target_id]
            out[hid] = {"kind": "esxi", "id": e.id, "name": e.host_name, "server_id": None, "platform": "virt",
                        "hypervisor_id": e.hypervisor_id, "host_ref": e.host_ref, "host_name": e.host_name,
                        "cluster": e.cluster_name}
    return out


def _impact(db: Session, tgt: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not tgt or tgt.get("kind") != "esxi":
        return None
    try:
        from app.services.hw.impact import host_impact
        return host_impact(db, tgt["hypervisor_id"], tgt.get("host_ref"), tgt.get("host_name"))
    except Exception:  # noqa: BLE001
        logger.exception("HW etki hesabı hata")
        return None


def desired_events(db: Session, *, demo: bool = False, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Sağlayıcı DURUMUNDAN olması gereken olaylar: external_key → spec (saf okuma)."""
    now = now or datetime.now(timezone.utc)
    insts = active_instances(db, include_demo=demo)
    ids = [i.id for i in insts] or [-1]
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    by_ref = {(s.instance_id, s.provider_ref): s for s in servers}
    links = {l.hw_server_id: l for l in
             db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in servers] or [-1])).all()}
    tg = _link_targets(db, links)
    prefix = "[DEMO] " if demo else ""

    def base(s: HwServer, kind_key: str, fp: str = "") -> Dict[str, Any]:
        t = tg.get(s.id)
        name = (t or {}).get("name") or s.name or s.provider_ref
        raw: Dict[str, Any] = {
            "hw_server_id": s.id, "hw_server_key": f"{s.instance_id}:{s.provider_ref}", "vendor": s.vendor, "model": s.model,
            "fingerprint": fp, "host_name": name, "entity_name": name,
            "platform_label": "Donanım", "target_kind": (t or {}).get("kind"), "target_id": (t or {}).get("id"),
            "demo": demo,
        }
        if t and t.get("platform"):
            raw["platform"] = t["platform"]
        if t and t.get("kind") == "esxi":
            raw["hypervisor_id"] = t.get("hypervisor_id")
            raw["cluster_name"] = t.get("cluster")
        imp = _impact(db, t)
        if imp:
            raw["impact"] = imp
        return {"server_id": (t or {}).get("server_id"), "raw": raw, "name": name, "key": f"hw:{s.instance_id}:{s.provider_ref}:{kind_key}"}

    out: Dict[str, Dict[str, Any]] = {}

    # 1) sağlık kritik
    for s in servers:
        if s.health != HEALTH_CRITICAL:
            continue
        b = base(s, "health")
        imp = b["raw"].get("impact") or {}
        extra = f" Etkilenen VM: {imp['vm_count']}." if imp.get("vm_count") else ""
        out[b["key"]] = {"event_type": ET_HEALTH, "severity": "critical", "server_id": b["server_id"], "raw": b["raw"],
                         "title": f"{prefix}Donanım sağlığı kritik: {b['name']}",
                         "description": f"{(s.vendor or '').upper()} yönetim aracı sunucuyu Kritik bildiriyor "
                                        f"(model: {s.model or '—'}).{extra}", "count": 1}

    # 2) aktif kritik alarm (sunucu + alarm tipi başına tek olay) ve 3) tekrarlayan uyarı
    cutoff = now - timedelta(hours=RECUR_WINDOW_H)
    crit: Dict[tuple, List[HwAlert]] = defaultdict(list)
    warn: Dict[tuple, List[HwAlert]] = defaultdict(list)
    for a in db.query(HwAlert).filter(HwAlert.instance_id.in_(ids), HwAlert.server_ref.isnot(None),
                                      HwAlert.state != "cleared").all():
        if a.severity == SEV_CRITICAL:
            crit[(a.instance_id, a.server_ref, a.fingerprint)].append(a)
        elif a.severity == SEV_WARNING:
            occ = _aware(a.occurred_at)
            if occ is not None and occ >= cutoff:
                warn[(a.instance_id, a.server_ref, a.fingerprint)].append(a)
    for (iid, sref, fp), rows in crit.items():
        s = by_ref.get((iid, sref))
        if s is None:
            continue
        b = base(s, f"alert:{fp[:16]}", fp)
        msg = sanitize_text(rows[0].message, s, 160)
        imp = b["raw"].get("impact") or {}
        extra = f" Etkilenen VM: {imp['vm_count']}." if imp.get("vm_count") else ""
        b["raw"]["alert_count"] = len(rows)
        out[b["key"]] = {"event_type": ET_ALERT, "severity": "critical", "server_id": b["server_id"], "raw": b["raw"],
                         "title": f"{prefix}Donanım alarmı: {b['name']} — {msg}"[:480],
                         "description": f"Kritik donanım alarmı ({len(rows)} aktif kayıt, kategori: {rows[0].category or '—'}). {msg}{extra}",
                         "count": len(rows)}
    for (iid, sref, fp), rows in warn.items():
        if len(rows) < RECUR_THRESHOLD:
            continue
        s = by_ref.get((iid, sref))
        if s is None:
            continue
        b = base(s, f"recurring:{fp[:16]}", fp)
        msg = sanitize_text(rows[0].message, s, 140)
        b["raw"]["alert_count"] = len(rows)
        out[b["key"]] = {"event_type": ET_RECUR, "severity": "warning", "server_id": b["server_id"], "raw": b["raw"],
                         "title": f"{prefix}Tekrarlayan donanım uyarısı ({len(rows)}×/{RECUR_WINDOW_H}s): {b['name']} — {msg}"[:480],
                         "description": f"Son {RECUR_WINDOW_H} saatte {len(rows)} kez: {msg}", "count": len(rows)}
    return out


def sync_hw_events(db: Session, *, allow_demo: bool = False, now: Optional[datetime] = None,
                   open_incidents: bool = True) -> Dict[str, int]:
    """Durum → olay: yeni aç, süren güncelle, kalkanı çöz. İdempotent."""
    now = now or datetime.now(timezone.utc)
    mode = hw_mode(db)
    demo = mode == "demo" and allow_demo
    stats = {"created": 0, "updated": 0, "reopened": 0, "resolved": 0, "incidents": 0}
    if mode == "none" or (mode == "demo" and not allow_demo):
        # DEMO bayrağı kapalı / sağlayıcı yok: mevcut hw olaylarına DOKUNMA (veri silinmez, yalnız üretilmez)
        return stats
    source = SOURCE_DEMO if demo else SOURCE_REAL
    want = desired_events(db, demo=demo, now=now)

    since = now - timedelta(days=LOOKBACK_DAYS)
    existing: Dict[str, SystemEvent] = {}
    for ev in (db.query(SystemEvent).filter(SystemEvent.source == source, SystemEvent.event_type.in_(HW_EVENT_TYPES))
               .order_by(SystemEvent.id).all()):
        key = (ev.raw_data or {}).get("external_key")
        if not key:
            continue
        created = _aware(ev.created_at) or now
        if not ev.resolved or created >= since:
            existing[key] = ev          # en yeni kazanır (id artan)

    to_incident: List[SystemEvent] = []
    for key, sp in want.items():
        ev = existing.get(key)
        raw = dict(sp["raw"])
        raw["external_key"] = key
        if ev is None:
            ev = SystemEvent(server_id=sp["server_id"], event_type=sp["event_type"], severity=sp["severity"], source=source,
                             title=sp["title"], description=sp["description"], raw_data=raw, occurrence_count=1,
                             last_seen=now)
            db.add(ev)
            db.flush()
            stats["created"] += 1
            if sp["severity"] == "critical":
                to_incident.append(ev)
            continue
        reopened = bool(ev.resolved)
        if reopened:
            ev.resolved, ev.resolved_at = False, None
            ev.occurrence_count = (ev.occurrence_count or 1) + 1
            stats["reopened"] += 1
            if sp["severity"] == "critical":
                to_incident.append(ev)
        else:
            stats["updated"] += 1
        ev.title, ev.description, ev.severity = sp["title"], sp["description"], sp["severity"]
        ev.server_id, ev.raw_data, ev.last_seen = sp["server_id"], raw, now
    for key, ev in existing.items():
        if key not in want and not ev.resolved:
            ev.resolved, ev.resolved_at = True, now
            stats["resolved"] += 1
    db.commit()

    if open_incidents and to_incident:
        from app.services.incident_auto import auto_create_or_link_incident
        for ev in to_incident:
            try:
                if auto_create_or_link_incident(db, ev):
                    stats["incidents"] += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                logger.exception("HW olayı için incident açılamadı (event=%s)", ev.id)
    return stats


def delete_demo_events(db: Session) -> int:
    """DEMO olaylarını ve YALNIZ onlardan doğan incident'ları sil (gerçek incident'a dokunmaz)."""
    from app.models.event import Incident
    ids = {i for (i,) in db.query(SystemEvent.id).filter(SystemEvent.source == SOURCE_DEMO).all()}
    if ids:
        for inc in db.query(Incident).filter(Incident.source.like("auto_hw_%")).all():
            rel = set(inc.related_events or [])
            if rel and rel <= ids:
                db.delete(inc)
    n = db.query(SystemEvent).filter(SystemEvent.source == SOURCE_DEMO).delete(synchronize_session=False)
    db.commit()
    return n
