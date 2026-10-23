"""Donanım verisi (Dell OME / HPE OneView) — modül `hardware` (varsayılan yalnız Admin).

BMC IP ve seri/service tag YALNIZ buradan döner; `/servers` API'lerine eklenmez. Entegrasyon yoksa uç noktalar
boş/`enabled=false` döner (404/500 değil) — uygulama bugünkü gibi davranır. DEMO veri etiketlenir.
Salt-okunur: bu router yalnız GET içerir.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.hw import (
    HwAlert, HwEnclosure, HwFirmware, HwHostLink, HwManager, HwServer, HwWarranty,
)
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.infra_finding import InfraFinding
from app.models.server import Server
from app.models.user import User
from app.services.capabilities import get_capabilities
from app.services.hw.demo_gate import BANNER_TR, active_instances, demo_enabled, hw_mode
from app.services.hw.sync import data_age_sec, intervals, provider_stale
from app.services.integrations.registry import parse_meta

router = APIRouter()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _scope(db: Session):
    """(mod, instance_ids, instance_rows). mod: real | demo | none. DEMO yalnız gerçek sağlayıcı yokken."""
    mode = hw_mode(db)
    rows = active_instances(db, include_demo=(mode == "demo"))
    return mode, [r.id for r in rows], rows


def _enabled(db: Session) -> bool:
    caps = get_capabilities()
    mode = hw_mode(db)
    return ("hw" in caps and mode == "real") or ("hw_demo" in caps and mode == "demo")


def _link_info(db: Session, links: Dict[int, HwHostLink]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    sids = [l.target_id for l in links.values() if l.target_kind == "server"]
    eids = [l.target_id for l in links.values() if l.target_kind == "esxi"]
    sname = {s.id: (s.name, s.os_type, s.tier) for s in db.query(Server).filter(Server.id.in_(sids or [-1])).all()}
    ename = {e.id: (e.host_name, e.hypervisor_id) for e in
             db.query(HypervisorHostInventory).filter(HypervisorHostInventory.id.in_(eids or [-1])).all()}
    for hid, l in links.items():
        if l.target_kind == "server":
            n = sname.get(l.target_id)
            out[hid] = {"kind": "server", "id": l.target_id, "name": n[0] if n else None,
                        "os_type": n[1] if n else None, "tier": n[2] if n else None,
                        "method": l.method, "confidence": l.confidence}
        else:
            n = ename.get(l.target_id)
            out[hid] = {"kind": "esxi", "id": l.target_id, "name": n[0] if n else None,
                        "hypervisor_id": n[1] if n else None, "method": l.method, "confidence": l.confidence}
    return out


def _warranty_by_server(db: Session, ids: List[int]) -> Dict[tuple, Dict[str, Any]]:
    best: Dict[tuple, Dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for w in db.query(HwWarranty).filter(HwWarranty.instance_id.in_(ids or [-1])).all():
        e = _aware(w.end_date)
        k = (w.instance_id, w.server_ref)
        cur = best.get(k)
        if e is not None and (cur is None or (cur.get("_e") is None or e > cur["_e"])):
            best[k] = {"_e": e, "end_date": e.date().isoformat(), "service_level": w.service_level,
                       "provider": w.provider_name, "expired": e < now, "days_remaining": (e - now).days}
        elif cur is None:
            best[k] = {"_e": None, "end_date": None, "service_level": w.service_level, "provider": w.provider_name,
                       "expired": None, "days_remaining": None}
    for v in best.values():
        v.pop("_e", None)
    return best


def _server_row(s: HwServer, link: Optional[Dict[str, Any]], warranty: Optional[Dict[str, Any]],
                mgr: Optional[HwManager]) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
    if s.extra_json:
        try:
            extra = json.loads(s.extra_json)
        except Exception:  # noqa: BLE001
            extra = {}
    return {
        "id": s.id, "instance_id": s.instance_id, "vendor": s.vendor, "name": s.name, "os_hostname": s.os_hostname,
        "model": s.model, "serial": s.serial, "uuid": s.uuid, "virtual_serial": s.virtual_serial,
        "bmc_ip": s.bmc_ip, "bmc_type": s.bmc_type, "bmc_version": s.bmc_version, "bios_version": s.bios_version,
        "form_factor": s.form_factor, "enclosure_name": s.enclosure_name, "bay": s.bay, "health": s.health,
        "raw_status": s.raw_status, "power_state": s.power_state, "connected": s.connected, "cpu_count": s.cpu_count,
        "memory_gb": s.memory_gb, "web_url": s.web_url, "collected_at": _iso(s.collected_at),
        "manager": ({"name": mgr.name, "kind": mgr.manager_kind, "version": mgr.version,
                     "support_level": mgr.support_level} if mgr else None),
        "link": link, "warranty": warranty, "appliance": extra.get("appliance"),
    }


@router.get("/summary")
def summary(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    mode, ids, rows = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "demo": False}
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    linked = {l.hw_server_id for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in servers] or [-1])).all()}
    by_health: Dict[str, int] = {}
    by_vendor: Dict[str, int] = {}
    for s in servers:
        by_health[s.health] = by_health.get(s.health, 0) + 1
        by_vendor[s.vendor] = by_vendor.get(s.vendor, 0) + 1
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    alerts_24h = db.query(func.count(HwAlert.id)).filter(HwAlert.instance_id.in_(ids), HwAlert.occurred_at >= since).scalar() or 0
    active_alerts = db.query(func.count(HwAlert.id)).filter(HwAlert.instance_id.in_(ids), HwAlert.state == "active").scalar() or 0
    now = datetime.now(timezone.utc)
    return {
        "ok": True, "enabled": True, "demo": mode == "demo", "demo_banner": BANNER_TR if mode == "demo" else None,
        "total": len(servers), "matched": len(linked), "unmatched": len(servers) - len(linked),
        "by_health": by_health, "by_vendor": by_vendor, "alerts_24h": alerts_24h, "active_alerts": active_alerts,
        "providers": [{"id": r.id, "label": r.label, "kind": r.kind, "last_status": r.last_status,
                       "last_sync_at": _iso(r.last_sync_at), "stale": provider_stale(r, now),
                       "data_age_sec": data_age_sec(r, now), "auth_halted": bool(parse_meta(r).get("auth_halted")),
                       "intervals": intervals(parse_meta(r), r)} for r in rows],
    }


@router.get("/servers")
def list_servers(
    q: str = "", health: str = "", vendor: str = "", matched: str = "", form_factor: str = "",
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), _u: User = Depends(get_current_user),
):
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "servers": [], "total": 0}
    qs = db.query(HwServer).filter(HwServer.instance_id.in_(ids))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        qs = qs.filter(or_(func.lower(HwServer.name).like(like), func.lower(HwServer.serial).like(like),
                           func.lower(HwServer.model).like(like), func.lower(HwServer.bmc_ip).like(like),
                           func.lower(HwServer.os_hostname).like(like), func.lower(HwServer.enclosure_name).like(like)))
    if health:
        qs = qs.filter(HwServer.health == health)
    if vendor:
        qs = qs.filter(HwServer.vendor == vendor)
    if form_factor:
        qs = qs.filter(HwServer.form_factor == form_factor)
    if matched in ("yes", "no"):
        sub = db.query(HwHostLink.hw_server_id)
        qs = qs.filter(HwServer.id.in_(sub)) if matched == "yes" else qs.filter(~HwServer.id.in_(sub))
    total = qs.count()
    rows = qs.order_by(HwServer.name).offset(offset).limit(limit).all()
    links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in rows] or [-1])).all()}
    info = _link_info(db, links)
    war = _warranty_by_server(db, ids)
    mg = {m.id: m for m in db.query(HwManager).filter(HwManager.instance_id.in_(ids)).all()}
    return {"ok": True, "enabled": True, "demo": mode == "demo", "total": total,
            "servers": [_server_row(s, info.get(s.id), war.get((s.instance_id, s.provider_ref)), mg.get(s.manager_id)) for s in rows]}


@router.get("/servers/by-target")
def server_by_target(kind: str = Query(..., pattern="^(server|esxi)$"), id: int = Query(...),
                     db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Linux/Windows çekmece kartı ve host paneli için. Entegrasyon yok / eşleşme yok → available=false."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "available": False, "reason": "no_integration"}
    link = (db.query(HwHostLink).join(HwServer, HwServer.id == HwHostLink.hw_server_id)
            .filter(HwHostLink.target_kind == kind, HwHostLink.target_id == id, HwServer.instance_id.in_(ids)).first())
    if link is None:
        return {"ok": True, "available": False, "reason": "no_match"}
    s = db.query(HwServer).filter(HwServer.id == link.hw_server_id).first()
    info = _link_info(db, {s.id: link})
    war = _warranty_by_server(db, ids)
    mgr = db.query(HwManager).filter(HwManager.id == s.manager_id).first() if s.manager_id else None
    row = _server_row(s, info.get(s.id), war.get((s.instance_id, s.provider_ref)), mgr)
    alerts = (db.query(HwAlert).filter(HwAlert.instance_id == s.instance_id, HwAlert.server_ref == s.provider_ref)
              .order_by(HwAlert.occurred_at.desc()).limit(5).all())
    row["recent_alerts"] = [{"severity": a.severity, "state": a.state, "message": a.message,
                             "occurred_at": _iso(a.occurred_at)} for a in alerts]
    return {"ok": True, "available": True, "demo": mode == "demo", "server": row}


@router.get("/servers/{hid}")
def server_detail(hid: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    mode, ids, _ = _scope(db)
    s = db.query(HwServer).filter(HwServer.id == hid, HwServer.instance_id.in_(ids or [-1])).first() if _enabled(db) else None
    if s is None:
        raise HTTPException(404, "Donanım kaydı bulunamadı")
    link = db.query(HwHostLink).filter(HwHostLink.hw_server_id == s.id).first()
    info = _link_info(db, {s.id: link} if link else {})
    war = _warranty_by_server(db, ids)
    mgr = db.query(HwManager).filter(HwManager.id == s.manager_id).first() if s.manager_id else None
    row = _server_row(s, info.get(s.id), war.get((s.instance_id, s.provider_ref)), mgr)
    row["firmware"] = [{"name": f.name, "type": f.component_type, "version": f.version}
                       for f in db.query(HwFirmware).filter(HwFirmware.server_id == s.id).order_by(HwFirmware.name).all()]
    row["warranties"] = [{"service_level": w.service_level, "provider": w.provider_name,
                          "start_date": _iso(w.start_date), "end_date": _iso(w.end_date)}
                         for w in db.query(HwWarranty).filter(HwWarranty.instance_id == s.instance_id,
                                                              HwWarranty.server_ref == s.provider_ref).all()]
    alerts = (db.query(HwAlert).filter(HwAlert.instance_id == s.instance_id, HwAlert.server_ref == s.provider_ref)
              .order_by(HwAlert.occurred_at.desc()).limit(50).all())
    row["alerts"] = [{"severity": a.severity, "state": a.state, "category": a.category, "message": a.message,
                      "occurred_at": _iso(a.occurred_at)} for a in alerts]
    return {"ok": True, "demo": mode == "demo", "server": row}


@router.get("/alerts")
def alerts(grouped: bool = True, hours: int = Query(168, ge=1, le=720), severity: str = "", limit: int = Query(200, ge=1, le=1000),
           db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "alerts": [], "groups": []}
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    qs = db.query(HwAlert).filter(HwAlert.instance_id.in_(ids), HwAlert.state != "cleared",
                                  or_(HwAlert.occurred_at >= since, HwAlert.occurred_at.is_(None)))
    if severity:
        qs = qs.filter(HwAlert.severity == severity)
    rows = qs.order_by(HwAlert.occurred_at.desc()).limit(5000).all()
    names = {(s.instance_id, s.provider_ref): s for s in db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()}
    if not grouped:
        return {"ok": True, "enabled": True, "demo": mode == "demo", "alerts": [
            {"id": a.id, "severity": a.severity, "state": a.state, "category": a.category, "message": a.message,
             "server_id": (names.get((a.instance_id, a.server_ref)).id if names.get((a.instance_id, a.server_ref)) else None),
             "server": (names.get((a.instance_id, a.server_ref)).name if names.get((a.instance_id, a.server_ref)) else a.entity_name),
             "occurred_at": _iso(a.occurred_at)} for a in rows[:limit]]}
    groups: Dict[str, Dict[str, Any]] = {}
    rank = {"critical": 3, "warning": 2, "info": 1, "unknown": 0}
    for a in rows:
        g = groups.setdefault(a.fingerprint, {"fingerprint": a.fingerprint, "message": a.message, "category": a.category,
                                              "severity": a.severity, "count": 0, "servers": set(), "last_at": None})
        g["count"] += 1
        if rank.get(a.severity, 0) > rank.get(g["severity"], 0):
            g["severity"] = a.severity
        s = names.get((a.instance_id, a.server_ref))
        if s is not None:
            g["servers"].add(s.name)
        occ = _aware(a.occurred_at)
        if occ and (g["last_at"] is None or occ > g["last_at"]):
            g["last_at"] = occ
    out = []
    for g in groups.values():
        out.append({"fingerprint": g["fingerprint"], "message": g["message"], "category": g["category"],
                    "severity": g["severity"], "count": g["count"], "server_count": len(g["servers"]),
                    "examples": sorted(g["servers"])[:5], "last_at": _iso(g["last_at"])})
    out.sort(key=lambda x: (-rank.get(x["severity"], 0), -x["count"]))
    return {"ok": True, "enabled": True, "demo": mode == "demo", "groups": out[:limit]}


@router.get("/enclosures")
def enclosures(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "enclosures": []}
    encl = db.query(HwEnclosure).filter(HwEnclosure.instance_id.in_(ids)).order_by(HwEnclosure.name).all()
    srv = db.query(HwServer).filter(HwServer.instance_id.in_(ids), HwServer.form_factor == "blade").all()
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for s in srv:
        by_name.setdefault(s.enclosure_name or "", []).append({"id": s.id, "name": s.name, "bay": s.bay, "health": s.health,
                                                               "model": s.model})
    return {"ok": True, "enabled": True, "demo": mode == "demo", "enclosures": [
        {"id": e.id, "name": e.name, "model": e.model, "serial": e.serial, "health": e.health, "bay_count": e.bay_count,
         "servers": sorted(by_name.get(e.name, []), key=lambda x: (str(x["bay"] or "").zfill(4)))} for e in encl]}


@router.get("/unmatched")
def unmatched(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Eşleşmeyen donanım kayıtları + eşleşmeyen FİZİKSEL ainew sunucuları (iki yönlü liste)."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "hw": [], "hosts": []}
    linked = {l.hw_server_id for l in db.query(HwHostLink).all()}
    hw = [s for s in db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all() if s.id not in linked]
    t_server = {l.target_id for l in db.query(HwHostLink).filter(HwHostLink.target_kind == "server").all()}
    phys = [s for s in db.query(Server).all() if (s.server_type or "").upper() == "PHYSICAL" and s.id not in t_server]
    return {"ok": True, "enabled": True, "demo": mode == "demo",
            "hw": [{"id": s.id, "name": s.name, "vendor": s.vendor, "model": s.model, "serial": s.serial,
                    "has_serial": bool(s.serial)} for s in hw[:500]],
            "hosts": [{"id": s.id, "name": s.name, "os_type": s.os_type, "hw_serial_collected": bool(s.hw_serial),
                       "hw_checked_at": _iso(s.hw_collected_at)} for s in phys[:500]],
            "note": "Linux sunucuda seri bilgisi root/sudo dmidecode gerektirir; toplanamazsa hostname ile (düşük güven) eşleşir."}


@router.get("/findings")
def findings(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    if hw_mode(db) != "real" or "hw" not in get_capabilities():
        return {"ok": True, "enabled": False, "findings": []}
    rows = (db.query(InfraFinding).filter(InfraFinding.platform == "hw", InfraFinding.active.is_(True))
            .order_by(InfraFinding.severity, InfraFinding.last_seen.desc()).limit(500).all())
    return {"ok": True, "enabled": True, "findings": [
        {"check_id": f.check_id, "severity": f.severity, "title": f.title, "entity_name": f.entity_name,
         "detail": f.detail, "recommendation": f.recommendation, "stale": f.stale, "first_seen": _iso(f.first_seen),
         "last_seen": _iso(f.last_seen)} for f in rows]}
