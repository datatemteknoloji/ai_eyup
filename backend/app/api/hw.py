"""Donanım verisi (Dell OME / HPE OneView) — modül `hardware` (varsayılan yalnız Admin).

BMC IP ve seri/service tag YALNIZ buradan döner; `/servers` API'lerine eklenmez. Entegrasyon yoksa uç noktalar
boş/`enabled=false` döner (404/500 değil) — uygulama bugünkü gibi davranır. DEMO veri etiketlenir.
Salt-okunur (donanıma yazılmaz): GET + ainew-içi elle eşleştirme (`/links`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, user_has_module
from app.core.database import get_db
from app.models.hw import (
    HwAlert, HwEnclosure, HwFirmware, HwFirmwareAccept, HwFirmwareReference, HwHostLink, HwLogEntry, HwManager, HwServer,
    HwWarranty,
)
from app.models.hypervisor import Hypervisor
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.infra_finding import InfraFinding
from app.models.server import Server
from app.models.user import User
from app.services.capabilities import get_capabilities
from app.services.hw.events import sanitize_text
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


# ── Host sınıfı (Hardware sayfası gruplaması) ─────────────────────────────────────────────────────────────────────
# Her portal kaydı TAM BİR sınıfa girer (toplam = sınıf toplamı). Öncelik: hypervisor eşleşmesi > şasi/blade > tekil fiziksel.
#   esxi / ocp / olvm / hv_other : portal kaydı bir hypervisor host envanterine (HypervisorHostInventory) eşleşmiş;
#                                  sınıf o hypervisor'ün türünden gelir (VMWARE / OPENSHIFT_VIRT / KVM-oVirt / diğer)
#   chassis                      : blade veya şasi/yuva bilgisi var (hypervisor'e eşleşmemiş)
#   physical                     : Linux/Windows sunucuya eşleşmiş VEYA eşleşmemiş rack/standalone (tekil fiziksel)
HOST_CLASSES = ("esxi", "ocp", "olvm", "hv_other", "chassis", "physical")
_HV_CLASS = {"vmware": "esxi", "openshift_virt": "ocp", "kvm": "olvm"}


def _classify_all(db: Session, ids: List[int]) -> Dict[int, str]:
    """{hw_server.id: sınıf} — kapsamdaki TÜM kayıtlar için (süzme/sayfalama öncesi). 3 sorgu."""
    rows = db.query(HwServer.id, HwServer.form_factor, HwServer.enclosure_name).filter(
        HwServer.instance_id.in_(ids or [-1])).all()
    links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(
        HwHostLink.hw_server_id.in_([r.id for r in rows] or [-1])).all()}
    eids = [l.target_id for l in links.values() if l.target_kind == "esxi"]
    types: Dict[int, str] = {}
    if eids:
        for iid, ht in (db.query(HypervisorHostInventory.id, Hypervisor.hypervisor_type)
                        .join(Hypervisor, Hypervisor.id == HypervisorHostInventory.hypervisor_id)
                        .filter(HypervisorHostInventory.id.in_(eids)).all()):
            types[iid] = str(getattr(ht, "value", ht)).lower()
    out: Dict[int, str] = {}
    for r in rows:
        l = links.get(r.id)
        if l is not None and l.target_kind == "esxi":
            out[r.id] = _HV_CLASS.get(types.get(l.target_id, ""), "hv_other")
        elif (r.form_factor or "").lower() == "blade" or r.enclosure_name:
            out[r.id] = "chassis"
        else:
            out[r.id] = "physical"
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


# `hardware` modülü olmayan platform kullanıcıları (Linux/Windows/Sanallaştırma sayfası) yalnız ÖZET görür:
# sağlık, model, şasi/yuva, garanti, alarm — BMC adresi, seri/service tag, UUID, firmware sürümleri ve konsol bağlantısı YOK.
_RESTRICTED_DROP = ("serial", "uuid", "virtual_serial", "bmc_ip", "bmc_type", "bmc_version", "bios_version", "web_url",
                    "os_hostname", "appliance", "manager", "firmware", "firmware_collected_at", "firmware_status")


def _restrict_row(row: Dict[str, Any], s: HwServer) -> Dict[str, Any]:
    for k in _RESTRICTED_DROP:
        row.pop(k, None)
    row["restricted"] = True
    if row.get("recent_alerts"):
        for a in row["recent_alerts"]:
            a["message"] = sanitize_text(a.get("message"), s)
    return row


@router.get("/summary")
def summary(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    mode, ids, rows = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "demo": False}
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    linked = {l.hw_server_id for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in servers] or [-1])).all()}
    by_health: Dict[str, int] = {}
    by_vendor: Dict[str, int] = {}
    by_class: Dict[str, int] = {}
    for c in _classify_all(db, ids).values():
        by_class[c] = by_class.get(c, 0) + 1
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
        "by_health": by_health, "by_vendor": by_vendor, "by_class": by_class, "alerts_24h": alerts_24h, "active_alerts": active_alerts,
        "providers": [{"id": r.id, "label": r.label, "kind": r.kind, "last_status": r.last_status,
                       "last_sync_at": _iso(r.last_sync_at), "stale": provider_stale(r, now),
                       "data_age_sec": data_age_sec(r, now), "auth_halted": bool(parse_meta(r).get("auth_halted")),
                       "intervals": intervals(parse_meta(r), r)} for r in rows],
    }


SORT_KEYS = ("name", "vendor", "model", "serial", "bmc_ip", "bmc_version", "bios_version", "health", "enclosure", "warranty", "match")
_HEALTH_RANK = {"critical": 0, "warning": 1, "unknown": 2, "ok": 3}      # asc = en kötü önce


def _ip_key(v: Optional[str]):
    """10.2.0.9 < 10.10.0.1 (sayısal); IP olmayan metin sona."""
    parts = (v or "").split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return (0, tuple(int(p) for p in parts), "")
    return (1, (), (v or "").lower())


def _sort_hw(rows: List[HwServer], key: str, direction: str, war: Dict[tuple, Dict[str, Any]],
             info: Dict[int, Dict[str, Any]]) -> List[HwServer]:
    """Doğal (sayı duyarlı, büyük/küçük harf duyarsız) sıralama; boş değerler yönden bağımsız SONA."""
    nat = _nat_key

    def val(s: HwServer):
        if key == "name":
            return nat(s.name)
        if key == "vendor":
            return (s.vendor or "").lower() or None
        if key == "model":
            return nat(s.model) if s.model else None
        if key == "serial":
            return (s.serial or "").lower() or None
        if key == "bmc_ip":
            return _ip_key(s.bmc_ip) if s.bmc_ip else None
        if key == "bmc_version":
            return nat(s.bmc_version) if s.bmc_version else None      # 2.9 < 2.10 (sayı duyarlı)
        if key == "bios_version":
            return nat(s.bios_version) if s.bios_version else None
        if key == "health":
            return _HEALTH_RANK.get(s.health, 2)
        if key == "enclosure":
            return (nat(s.enclosure_name), nat(str(s.bay or ""))) if s.enclosure_name else None
        if key == "warranty":
            w = war.get((s.instance_id, s.provider_ref)) or {}
            return w.get("end_date")                      # ISO tarih: metin sırası = tarih sırası
        if key == "match":
            n = (info.get(s.id) or {}).get("name")
            return nat(n) if n else None
        return None

    keyed = [(val(s), s) for s in rows]
    have = [(v, s) for v, s in keyed if v is not None]
    none = [s for v, s in keyed if v is None]
    have.sort(key=lambda x: (x[0], nat(x[1].name)), reverse=(direction == "desc"))
    return [s for _v, s in have] + sorted(none, key=lambda s: nat(s.name))


@router.get("/problem-servers")
def problem_servers(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
                    _u: User = Depends(get_current_user)):
    """Dashboard «Donanım alarmları» kartları: sağlığı kritik/uyarı, bağlantısız veya aktif alarmı olan donanım kayıtları.
    Sıra: kritik sağlık → aktif kritik alarm sayısı → uyarı. Alarm metinleri maskelenir (BMC/seri yok)."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "total": 0, "items": []}
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    alerts: Dict[tuple, List[HwAlert]] = {}
    for a in (db.query(HwAlert).filter(HwAlert.instance_id.in_(ids), HwAlert.state != "cleared",
                                       HwAlert.severity.in_(("critical", "warning")), HwAlert.server_ref.isnot(None))
              .order_by(HwAlert.occurred_at.desc()).all()):
        alerts.setdefault((a.instance_id, a.server_ref), []).append(a)
    links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in servers] or [-1])).all()}
    info = _link_info(db, links)
    items = []
    for s in servers:
        al = alerts.get((s.instance_id, s.provider_ref), [])
        crit = sum(1 for a in al if a.severity == "critical")
        warn = len(al) - crit
        if s.health in ("ok", "unknown") and s.connected is not False and not al:
            continue
        top = al[0] if al else None
        li = info.get(s.id) or {}
        items.append({
            "id": s.id, "name": s.name, "vendor": s.vendor, "model": s.model, "health": s.health,
            "connected": s.connected, "critical_alerts": crit, "warning_alerts": warn,
            "top_alert": sanitize_text(top.message, s, 160) if top else None,
            "last_alert_at": _iso(top.occurred_at) if top else None,
            "enclosure": s.enclosure_name, "bay": s.bay,
            "target": ({"kind": li.get("kind"), "id": li.get("id"), "name": li.get("name")} if li else None),
        })
    items.sort(key=lambda x: (_HEALTH_RANK.get(x["health"], 2), -x["critical_alerts"], -x["warning_alerts"], x["name"].lower()))
    return {"ok": True, "enabled": True, "demo": mode == "demo", "total": len(items), "items": items[:limit]}


@router.get("/servers")
def list_servers(
    q: str = "", health: str = "", vendor: str = "", matched: str = "", form_factor: str = "", host_class: str = "",
    limit: int = Query(200, ge=1, le=2000), offset: int = Query(0, ge=0),
    sort_by: str = "", sort_dir: str = "asc",
    db: Session = Depends(get_db), _u: User = Depends(get_current_user),
):
    """Filo listesi. `sort_by` (beyaz liste): name | vendor | model | serial | bmc_ip | bmc_version | bios_version | health | enclosure | warranty | match.
    Sıralama TÜM süzülmüş kayıtlar üzerinde yapılır (sayfa dilimi sıralamadan sonra alınır); boş değerler her yönde sona düşer."""
    if sort_by and sort_by not in SORT_KEYS:
        raise HTTPException(422, f"Geçersiz sıralama alanı: {sort_by}")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(422, "sort_dir asc|desc olmalı")
    if host_class and host_class not in HOST_CLASSES:
        raise HTTPException(422, f"Geçersiz host_class: {host_class}")
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "servers": [], "total": 0}
    classes = _classify_all(db, ids)
    qs = db.query(HwServer).filter(HwServer.instance_id.in_(ids))
    if host_class:
        qs = qs.filter(HwServer.id.in_([i for i, c in classes.items() if c == host_class] or [-1]))
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
    war = _warranty_by_server(db, ids)
    if sort_by:
        allrows = qs.all()
        all_links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in allrows] or [-1])).all()}
        all_info = _link_info(db, all_links)
        rows = _sort_hw(allrows, sort_by, sort_dir, war, all_info)[offset:offset + limit]
        info = all_info
    else:
        rows = qs.order_by(HwServer.name).offset(offset).limit(limit).all()
        links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in rows] or [-1])).all()}
        info = _link_info(db, links)
    mg = {m.id: m for m in db.query(HwManager).filter(HwManager.instance_id.in_(ids)).all()}
    return {"ok": True, "enabled": True, "demo": mode == "demo", "total": total,
            "servers": [{**_server_row(s, info.get(s.id), war.get((s.instance_id, s.provider_ref)), mg.get(s.manager_id)),
                         "host_class": classes.get(s.id)} for s in rows]}


@router.get("/servers/by-target")
def server_by_target(kind: str = Query(..., pattern="^(server|esxi)$"), id: int = Query(...),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
    full = user_has_module(user, "hardware", db)
    if not full:
        row = _restrict_row(row, s)
    return {"ok": True, "available": True, "demo": mode == "demo", "restricted": not full, "server": row}


@router.get("/targets-health")
def targets_health(kind: str = Query("server", pattern="^(server|esxi)$"),
                   db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Liste sayfalarındaki donanım rozeti için: hedef id → {health, alerts(aktif kritik), warranty_expired}.
    Yalnız sağlık özeti döner (BMC/seri YOK) — platform modülü yetkisi yeter."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "items": {}}
    rows = (db.query(HwHostLink, HwServer).join(HwServer, HwServer.id == HwHostLink.hw_server_id)
            .filter(HwHostLink.target_kind == kind, HwServer.instance_id.in_(ids or [-1])).all())
    refs = [(s.instance_id, s.provider_ref) for _l, s in rows]
    crit: Dict[tuple, int] = {}
    if refs:
        for a in db.query(HwAlert).filter(HwAlert.instance_id.in_(ids), HwAlert.state != "cleared",
                                          HwAlert.severity == "critical", HwAlert.server_ref.isnot(None)).all():
            crit[(a.instance_id, a.server_ref)] = crit.get((a.instance_id, a.server_ref), 0) + 1
    war = _warranty_by_server(db, ids)
    items = {}
    for l, s in rows:
        w = war.get((s.instance_id, s.provider_ref)) or {}
        items[str(l.target_id)] = {"health": s.health, "power_state": s.power_state, "connected": s.connected,
                                   "critical_alerts": crit.get((s.instance_id, s.provider_ref), 0),
                                   "warranty_expired": w.get("expired"), "warranty_days": w.get("days_remaining")}
    return {"ok": True, "enabled": True, "demo": mode == "demo", "items": items}


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
    fw = db.query(HwFirmware).filter(HwFirmware.server_id == s.id).all()
    # Installed önce (kurulu sürüm), Available (önceki/yedek) sonra; ad doğal sırada
    fw.sort(key=lambda f: (0 if (f.status or "Installed") == "Installed" else 1, (f.component_type or ""), _nat_key(f.name)))
    row["firmware"] = [{"name": f.name, "type": f.component_type, "version": f.version, "status": f.status,
                        "component_id": f.component_id, "location": f.location} for f in fw]
    row["firmware_collected_at"] = _iso(max((f.collected_at for f in fw if f.collected_at), default=None))
    from app.services.hw.firmware_compare import compare_all
    cmp_ = compare_all(db, [s], full=True).get(s.id)
    if cmp_:
        cmp_.pop("_server", None)
    row["firmware_status"] = cmp_
    row["warranties"] = [{"service_level": w.service_level, "provider": w.provider_name,
                          "start_date": _iso(w.start_date), "end_date": _iso(w.end_date)}
                         for w in db.query(HwWarranty).filter(HwWarranty.instance_id == s.instance_id,
                                                              HwWarranty.server_ref == s.provider_ref).all()]
    alerts = (db.query(HwAlert).filter(HwAlert.instance_id == s.instance_id, HwAlert.server_ref == s.provider_ref)
              .order_by(HwAlert.occurred_at.desc()).limit(50).all())
    row["alerts"] = [{"severity": a.severity, "state": a.state, "category": a.category, "message": a.message,
                      "occurred_at": _iso(a.occurred_at)} for a in alerts]
    if link is not None and link.target_kind == "esxi":
        inv = db.query(HypervisorHostInventory).filter(HypervisorHostInventory.id == link.target_id).first()
        if inv is not None:
            from app.services.hw.impact import host_impact
            row["impact"] = host_impact(db, inv.hypervisor_id, inv.host_ref, inv.host_name)
    row["history"] = _history(db, s.id)
    return {"ok": True, "demo": mode == "demo", "server": row}


def _history(db: Session, hid: int, limit: int = 30) -> List[Dict[str, Any]]:
    """Sağlık/alarm geçmişi: bu donanım kaydına ait olaylar (açılış/çözülme) — ek tablo gerekmez."""
    from app.models.event import SystemEvent
    from app.services.hw.events import HW_EVENT_TYPES
    rows = (db.query(SystemEvent).filter(SystemEvent.event_type.in_(HW_EVENT_TYPES))
            .order_by(SystemEvent.created_at.desc()).limit(400).all())
    out = []
    for e in rows:
        if (e.raw_data or {}).get("hw_server_id") != hid:
            continue
        out.append({"event_id": e.id, "type": e.event_type, "severity": e.severity, "title": e.title,
                    "opened_at": _iso(e.created_at), "last_seen": _iso(e.last_seen), "resolved": bool(e.resolved),
                    "resolved_at": _iso(e.resolved_at), "count": e.occurrence_count or 1})
        if len(out) >= limit:
            break
    return out


@router.get("/warranty-report")
def warranty_report(days: int = Query(180, ge=1, le=1825), include_ok: bool = False,
                    db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Garanti / yenileme raporu: süresi bitmiş + `days` gün içinde bitecek (varsayılan 180) kayıtlar."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "items": []}
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([x.id for x in servers] or [-1])).all()}
    info = _link_info(db, links)
    war = _warranty_by_server(db, ids)
    items = []
    for s in servers:
        w = war.get((s.instance_id, s.provider_ref))
        if not w or w.get("end_date") is None:
            continue
        d = w.get("days_remaining")
        if not include_ok and d is not None and d > days:
            continue
        li = info.get(s.id) or {}
        items.append({"id": s.id, "name": s.name, "vendor": s.vendor, "model": s.model, "serial": s.serial,
                      "end_date": w["end_date"], "days_remaining": d, "expired": w.get("expired"),
                      "service_level": w.get("service_level"), "tier": li.get("tier"), "target": li.get("name"),
                      "target_kind": li.get("kind")})
    items.sort(key=lambda x: (x["days_remaining"] if x["days_remaining"] is not None else 10**9))
    return {"ok": True, "enabled": True, "demo": mode == "demo", "days": days, "total": len(items),
            "expired": sum(1 for i in items if i["expired"]), "items": items}


class LinkBody(BaseModel):
    hw_server_id: int
    target_kind: str
    target_id: int


@router.post("/links")
def create_manual_link(body: LinkBody, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Eşleşmeyen donanım kaydını bir ainew hedefine ELLE bağla (yalnız ainew tarafına yazar; donanıma dokunmaz).
    Otomatik eşleştirme bu bağı bozmaz (`method=manual`)."""
    if body.target_kind not in ("server", "esxi"):
        raise HTTPException(400, "Geçersiz hedef türü")
    mode, ids, _ = _scope(db)
    s = db.query(HwServer).filter(HwServer.id == body.hw_server_id, HwServer.instance_id.in_(ids or [-1])).first()
    if s is None:
        raise HTTPException(404, "Donanım kaydı bulunamadı")
    exists = (db.query(Server.id).filter(Server.id == body.target_id).first() if body.target_kind == "server" else
              db.query(HypervisorHostInventory.id).filter(HypervisorHostInventory.id == body.target_id).first())
    if not exists:
        raise HTTPException(404, "Hedef bulunamadı")
    taken = db.query(HwHostLink).filter(HwHostLink.target_kind == body.target_kind, HwHostLink.target_id == body.target_id,
                                        HwHostLink.hw_server_id != s.id).first()
    if taken is not None:
        raise HTTPException(409, "Bu hedef zaten başka bir donanım kaydına bağlı; önce o bağı kaldırın")
    link = db.query(HwHostLink).filter(HwHostLink.hw_server_id == s.id).first()
    if link is None:
        link = HwHostLink(hw_server_id=s.id, target_kind=body.target_kind, target_id=body.target_id,
                          method="manual", confidence="exact")
        db.add(link)
    else:
        link.target_kind, link.target_id, link.method, link.confidence = body.target_kind, body.target_id, "manual", "exact"
    db.commit()
    return {"ok": True}


@router.delete("/links/{hw_server_id}")
def delete_link(hw_server_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Bağı kaldır (elle ya da otomatik). Otomatik eşleşme sonraki senkronda yeniden kurulabilir."""
    n = db.query(HwHostLink).filter(HwHostLink.hw_server_id == hw_server_id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": n}


# ── Firmware: referans sunucu karşılaştırması (yalnız ainew'e yazar; donanıma dokunmaz) ─────────────────────────────

def _fw_payload(db: Session, ids: List[int]) -> Dict[str, Any]:
    from app.services.hw import firmware_compare as FC
    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids or [-1])).all()
    cmp_ = FC.compare_all(db, servers)
    fw_info: Dict[int, Dict[str, Any]] = {}
    for sid, n, ts in (db.query(HwFirmware.server_id, func.count(HwFirmware.id), func.max(HwFirmware.collected_at))
                       .filter(HwFirmware.server_id.in_([s.id for s in servers] or [-1])).group_by(HwFirmware.server_id).all()):
        fw_info[sid] = {"rows": n, "collected_at": _iso(ts)}
    refs = db.query(HwFirmwareReference).all()
    enc_names = {e.id: e.name for e in db.query(HwEnclosure).filter(HwEnclosure.instance_id.in_(ids or [-1])).all()}
    by_id = {s.id: s for s in servers}
    groups: Dict[tuple, Dict[str, Any]] = {}
    for s in sorted(servers, key=lambda x: (x.vendor, _nat_key(x.model), _nat_key(x.name))):
        mk = FC._model_key(s.vendor, s.model)
        g = groups.setdefault(mk, {"vendor": s.vendor, "model": s.model or "", "total": 0, "with_firmware": 0, "outdated": 0,
                                   "accepted": 0, "unknown": 0, "reference": None, "chassis_refs": [], "servers": []})
        r = cmp_[s.id]
        info = fw_info.get(s.id)
        g["total"] += 1
        g["with_firmware"] += 1 if (info or s.bmc_version or s.bios_version) else 0
        g["outdated"] += 1 if r["status"] == FC.ST_OUTDATED else 0
        g["accepted"] += 1 if r["status"] == FC.ST_ACCEPTED else 0
        g["unknown"] += 1 if r["status"] == FC.ST_UNKNOWN else 0
        g["servers"].append({"id": s.id, "name": s.name, "enclosure_name": s.enclosure_name, "bay": s.bay,
                             "status": r["status"], "reference": r["reference"], "compared": r["compared"],
                             "outdated": r["outdated"], "accepted": r["accepted"], "unknown": r["unknown"],
                             "components": r["components"], "firmware_rows": (info or {}).get("rows", 0),
                             "firmware_collected_at": (info or {}).get("collected_at"),
                             "bmc_version": s.bmc_version, "bios_version": s.bios_version})
    for r in refs:
        rs = by_id.get(r.reference_server_id)
        if rs is None:
            continue
        g = groups.get(FC._model_key(r.vendor, r.model))
        if g is None:
            continue
        item = {"id": r.id, "server_id": rs.id, "server_name": rs.name, "scope": r.scope, "set_by": r.set_by,
                "created_at": _iso(r.created_at)}
        if r.scope == "chassis":
            g["chassis_refs"].append({**item, "enclosure_id": r.enclosure_id, "enclosure_name": enc_names.get(r.enclosure_id)})
        else:
            g["reference"] = item
    return {"groups": list(groups.values())}


@router.get("/firmware/compare")
def firmware_compare(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    """Model gruplarına göre firmware karşılaştırması. Referans: model kapsamı + şasi kapsamı (şasi > model)."""
    mode, ids, _ = _scope(db)
    if not _enabled(db):
        return {"ok": True, "enabled": False, "groups": []}
    return {"ok": True, "enabled": True, "demo": mode == "demo", **_fw_payload(db, ids)}


class FwRefBody(BaseModel):
    server_id: int
    scope: str = "model"                      # model | chassis


@router.post("/firmware/references")
def set_firmware_reference(body: FwRefBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Bir sunucuyu referans yap (model ya da şasi kapsamı). Yalnız ainew'e yazılır."""
    from app.services.hw import firmware_compare as FC
    if body.scope not in ("model", "chassis"):
        raise HTTPException(400, "Geçersiz kapsam (model | chassis)")
    mode, ids, _ = _scope(db)
    s = db.query(HwServer).filter(HwServer.id == body.server_id, HwServer.instance_id.in_(ids or [-1])).first()
    if s is None:
        raise HTTPException(404, "Donanım kaydı bulunamadı")
    if not (s.model or "").strip():
        raise HTTPException(400, "Sunucunun modeli bilinmiyor; referans yapılamaz")
    has_fw = db.query(HwFirmware.id).filter(HwFirmware.server_id == s.id).first() is not None or s.bmc_version or s.bios_version
    if not has_fw:
        raise HTTPException(400, "Bu sunucuda firmware verisi yok; referans yapılamaz")
    eid: Optional[int] = None
    if body.scope == "chassis":
        eid = FC.enclosure_of(db, [s]).get(s.id)
        if eid is None:
            raise HTTPException(400, "Sunucunun şasisi belirlenemedi; şasi kapsamlı referans yapılamaz")
    mk = FC._model_key(s.vendor, s.model)
    cur = next((r for r in db.query(HwFirmwareReference).filter(HwFirmwareReference.scope == body.scope).all()
                if FC._model_key(r.vendor, r.model) == mk and r.enclosure_id == eid), None)
    who = getattr(user, "username", None)
    if cur is None:
        db.add(HwFirmwareReference(scope=body.scope, vendor=s.vendor, model=s.model.strip(), enclosure_id=eid,
                                   reference_server_id=s.id, set_by=who))
    else:
        cur.reference_server_id, cur.set_by = s.id, who
    db.commit()
    return {"ok": True}


@router.delete("/firmware/references/{ref_id}")
def delete_firmware_reference(ref_id: int, db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    n = db.query(HwFirmwareReference).filter(HwFirmwareReference.id == ref_id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": n}


class FwAcceptBody(BaseModel):
    server_id: int
    component_keys: Optional[List[str]] = None   # boş/None → şu an düşük olan TÜM bileşenler
    note: Optional[str] = Field(None, max_length=500)


@router.post("/firmware/accept")
def accept_firmware(body: FwAcceptBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """«Kabul edildi»: bileşenin MEVCUT sürümü bilinçli olarak referanstan düşük bırakıldı. Sürüm değişince kabul düşer."""
    from app.services.hw import firmware_compare as FC
    mode, ids, _ = _scope(db)
    s = db.query(HwServer).filter(HwServer.id == body.server_id, HwServer.instance_id.in_(ids or [-1])).first()
    if s is None:
        raise HTTPException(404, "Donanım kaydı bulunamadı")
    res = FC.compare_all(db, [s], full=True)[s.id]
    want = set(body.component_keys) if body.component_keys else None
    targets = [c for c in res["components"] if c["state"] in (FC.ST_OUTDATED, FC.ST_ACCEPTED) and (want is None or c["key"] in want)]
    if not targets:
        raise HTTPException(404, "Kabul edilecek düşük sürümlü bileşen yok")
    who = getattr(user, "username", None)
    for c in targets:
        row = db.query(HwFirmwareAccept).filter(HwFirmwareAccept.server_id == s.id, HwFirmwareAccept.component_key == c["key"]).first()
        if row is None:
            db.add(HwFirmwareAccept(server_id=s.id, component_key=c["key"], accepted_version=c["version"],
                                    note=(body.note or None), accepted_by=who))
        else:
            row.accepted_version, row.note, row.accepted_by = c["version"], (body.note or None), who
    db.commit()
    return {"ok": True, "accepted": len(targets)}


@router.delete("/firmware/accept/{server_id}")
def unaccept_firmware(server_id: int, component_key: Optional[str] = None, db: Session = Depends(get_db),
                      _u: User = Depends(get_current_user)):
    q = db.query(HwFirmwareAccept).filter(HwFirmwareAccept.server_id == server_id)
    if component_key:
        q = q.filter(HwFirmwareAccept.component_key == component_key)
    n = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": n}


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
        return {"ok": True, "enabled": False, "enclosures": [], "unassigned": []}
    encl = sorted(db.query(HwEnclosure).filter(HwEnclosure.instance_id.in_(ids)).all(), key=lambda e: _nat_key(e.name))
    srv = db.query(HwServer).filter(HwServer.instance_id.in_(ids), HwServer.form_factor == "blade").all()
    blades, unassigned = _blades_by_enclosure(encl, srv)
    out = []
    for e in encl:
        servers = sorted(blades.get(e.id, []), key=_bay_order)
        out.append({"id": e.id, "name": e.name, "model": e.model, "serial": e.serial, "health": e.health,
                    "bay_count": e.bay_count, "servers": servers, "empty_bays": _empty_bays(e.bay_count, servers)})
    return {"ok": True, "enabled": True, "demo": mode == "demo", "enclosures": out,
            "unassigned": sorted(unassigned, key=lambda x: (_nat_key(x["enclosure"]), _bay_order(x), _nat_key(x["name"])))}


def _bay_order(x: Dict[str, Any]):
    """Bay sırası: doğal sıralama, bay'i olmayan SONA."""
    return (x["bay"] is None or x["bay"] == "", _nat_key(x["bay"]))


MAX_BAY_PLACEHOLDERS = 64


def _empty_bays(bay_count: Any, servers: List[Dict[str, Any]]) -> Optional[List[int]]:
    """Sunucu kaydı OLMAYAN yuva numaraları (1..bay_count). Hesaplanamıyorsa `None` (yer tutucu gösterilmez):
    yuva sayısı bilinmiyorsa / makul değilse, herhangi bir sunucunun yuvası boş ya da sayısal değilse (`1a`, `Sled-3`)
    ya da sunucu yuvası sayı aralığı dışındaysa. «Kayıt yok» ≠ «boş»: geniş (full-height/double-wide) blade ikinci yuvayı da
    kaplar; bu yüzden arayüz «boş» DEMEZ, «sunucu kaydı yok» der."""
    if isinstance(bay_count, bool) or not isinstance(bay_count, int) or not (0 < bay_count <= MAX_BAY_PLACEHOLDERS):
        return None
    occupied = set()
    for sv in servers:
        b = str(sv.get("bay") if sv.get("bay") is not None else "").strip()
        if not b.isdigit():
            return None
        occupied.add(int(b))
    if any(n < 1 or n > bay_count for n in occupied):
        return None
    return [n for n in range(1, bay_count + 1) if n not in occupied]


def _nat_key(v: Optional[str]) -> list:
    """Doğal sıralama anahtarı (büyük/küçük harf duyarsız): `Sled-2` < `Sled-10`, `1a` < `1b` < `2a`."""
    import re as _re
    return [int(t) if t.isdigit() else t for t in _re.split(r"(\d+)", str(v if v is not None else "").lower())]


def _ref_tail(ref: Optional[str]) -> Optional[str]:
    """Şasi `provider_ref` kuyruğu: OneView/OVGD `<yönetim noktası>|/rest/enclosures/<id>` → `<id>`; OME `<Id>` → `<Id>`."""
    p = (ref or "").split("|", 1)[-1].rstrip("/")
    return p.rsplit("/", 1)[-1] or None


def _blades_by_enclosure(encl: List[HwEnclosure], srv: List[HwServer]):
    """Blade → şasi eşleşmesi (`hw_enclosures.id` → blade listesi). Anahtar HER ZAMAN (instance, yönetim noktası) ile başlar;
    iki OME/OneView'da aynı şasi adı (`Encl1`) blade'leri karıştırmaz.
    1) Kimlik: sunucunun `enclosure_ref` (OneView/OVGD `locationUri` kuyruğu) == şasi `provider_ref` kuyruğu.
    2) Ad: yalnız kimlik yoksa (OME: `ChassisName`; dokümanda şasi kimliği YOK) ve o yönetim noktasında ad TEKİL ise.
       Ad birden çok şasiye uyuyorsa tahmin YAPILMAZ (blade yanlış şasiye yazılmaz).
    Dönüş: (şasi id → blade listesi, şasisi belirlenemeyen blade listesi). Aynı yuvada birden çok sunucu olabilir
    (çok düğümlü blade/sled): hepsi listelenir, arayüz yuvaya göre gruplar."""
    by_ref: Dict[tuple, int] = {}
    by_name: Dict[tuple, List[int]] = {}
    for e in encl:
        tail = _ref_tail(e.provider_ref)
        if tail:
            by_ref[(e.instance_id, e.manager_id, tail)] = e.id
        by_name.setdefault((e.instance_id, e.manager_id, e.name or ""), []).append(e.id)
    out: Dict[int, List[Dict[str, Any]]] = {}
    unassigned: List[Dict[str, Any]] = []
    for s in srv:
        eid = by_ref.get((s.instance_id, s.manager_id, s.enclosure_ref)) if s.enclosure_ref else None
        if eid is None:
            cand = by_name.get((s.instance_id, s.manager_id, s.enclosure_name or ""), [])
            eid = cand[0] if len(cand) == 1 else None
        item = {"id": s.id, "name": s.name, "bay": s.bay, "health": s.health, "model": s.model}
        if eid is not None:
            out.setdefault(eid, []).append(item)
        else:
            unassigned.append({**item, "enclosure": s.enclosure_name})
    return out, unassigned


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
    import difflib
    from app.services.hw.identity import short_host
    t_esxi = {l.target_id for l in db.query(HwHostLink).filter(HwHostLink.target_kind == "esxi").all()}
    cand_pool = [("server", p.id, p.name, [short_host(n) for n in (p.name, p.hostname) if n]) for p in phys]
    cand_pool += [("esxi", e.id, e.host_name, [short_host(e.host_name)]) for e in
                  db.query(HypervisorHostInventory).all() if e.id not in t_esxi]

    def _cands(s: HwServer) -> List[Dict[str, Any]]:
        names = [x for x in (short_host(s.os_hostname), short_host(s.name)) if x]
        scored = []
        for kind, tid, tname, keys in cand_pool:
            best = max((difflib.SequenceMatcher(None, a, b).ratio() for a in names for b in keys if b), default=0.0)
            if best >= 0.6:
                scored.append((best, kind, tid, tname))
        scored.sort(reverse=True)
        return [{"kind": k, "id": i, "name": n, "score": round(sc, 2)} for sc, k, i, n in scored[:3]]

    return {"ok": True, "enabled": True, "demo": mode == "demo",
            "hw": [{"id": s.id, "name": s.name, "vendor": s.vendor, "model": s.model, "serial": s.serial,
                    "has_serial": bool(s.serial), "candidates": _cands(s)} for s in hw[:500]],
            "hosts": [{"id": s.id, "name": s.name, "os_type": s.os_type, "hw_serial_collected": bool(s.hw_serial),
                       "hw_checked_at": _iso(s.hw_collected_at)} for s in phys[:500]],
            "note": "Linux sunucuda seri bilgisi root/sudo dmidecode gerektirir; toplanamazsa hostname ile (düşük güven) eşleşir."}


@router.get("/host-logs")
def host_logs(
    kind: Optional[str] = Query(None, pattern="^(server|esxi|hw)$"), id: Optional[int] = Query(None),
    severity: str = Query("", pattern="^(|critical|warning|info|all)$"), days: int = Query(7, ge=1, le=30),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Faz 3a — host kaynaklı donanım logları (ESXi SEL/vmkernel, Linux/Windows donanım olayları).

    iLO/iDRAC'e bağlanılmaz; sağlayıcı (OME/OneView) şart DEĞİL. Metinler kayıtta maskelidir (IPv4/UUID/MAC/WWN).
    Hedef (`kind`+`id`) verilirse platform modülü yetkisi yeter (GRANTS); filo görünümü (hedefsiz) `hardware` modülüdür.
    Özellik kapalı ve kayıt yoksa `enabled=false` + boş liste döner (404/500 değil).
    """
    from sqlalchemy import case
    from app.models.hw import HwLogEntry
    from app.services.hw import host_logs as HL

    if (kind is None) != (id is None):
        raise HTTPException(422, "kind ve id birlikte verilmeli")
    if (kind is None or kind == "hw") and not user_has_module(user, "hardware", db):
        raise HTTPException(403, "Filo / portal kaydı donanım logları için `hardware` modülü yetkisi gerekir.")
    flag = HL.enabled()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.query(HwLogEntry).filter(HwLogEntry.target_kind.isnot(None), HwLogEntry.last_seen_at >= since)
    if kind is not None:
        q = q.filter(HwLogEntry.target_kind == kind, HwLogEntry.target_id == id)
    base_total = q.count()
    if not flag and base_total == 0:
        return {"ok": True, "enabled": False, "available": False, "total": 0, "items": [], "counts": {}}
    counts = {sv: n for sv, n in q.with_entities(HwLogEntry.severity, func.count(HwLogEntry.id)).group_by(HwLogEntry.severity).all()}
    sev = severity or ""
    if sev in ("critical", "warning", "info"):
        q = q.filter(HwLogEntry.severity == sev)
    elif sev == "":
        q = q.filter(HwLogEntry.severity.in_(("critical", "warning")))
    rank = case((HwLogEntry.severity == "critical", 0), (HwLogEntry.severity == "warning", 1), else_=2)
    rows = q.order_by(rank, HwLogEntry.last_seen_at.desc()).limit(limit).all()
    sids = {r.target_id for r in rows if r.target_kind == "server"}
    eids = {r.target_id for r in rows if r.target_kind == "esxi"}
    sname = {s.id: s.name for s in db.query(Server).filter(Server.id.in_(list(sids) or [-1])).all()}
    ename = {e.id: e.host_name for e in db.query(HypervisorHostInventory).filter(
        HypervisorHostInventory.id.in_(list(eids) or [-1])).all()}
    hids = {r.target_id for r in rows if r.target_kind == "hw"}
    hname = {h.id: h.name for h in db.query(HwServer).filter(HwServer.id.in_(list(hids) or [-1])).all()}
    lr = HL.last_run() or {}
    return {
        "ok": True, "enabled": flag, "available": base_total > 0, "total": q.count(), "counts": counts, "days": days,
        "last_run_at": lr.get("at"), "last_run_errors": int(lr.get("errors") or 0),
        "items": [{
            "id": r.id, "severity": r.severity, "category": r.category, "source": r.source,
            "message": r.message, "occurrences": r.occurrences, "first_seen_at": _iso(r.first_seen_at),
            "last_seen_at": _iso(r.last_seen_at),
            "target": {"kind": r.target_kind, "id": r.target_id,
                       "name": (sname if r.target_kind == "server" else hname if r.target_kind == "hw" else ename).get(r.target_id)},
        } for r in rows],
        "note": "Kaynak: vCenter SEL/vmkernel ve mevcut Linux/Windows log toplayıcıları (iLO/iDRAC'e bağlanılmaz). "
                "Boş sonuç = donanım hatası yok anlamına gelmeyebilir (kaynak desteklemiyor olabilir).",
    }


_LOG_SOURCES = ("esxi_sel", "esxi_vmkernel", "linux_journal", "windows_event", "ipmi_sel", "bmc_redfish", "portal_alert")
_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


def _target_classes(db: Session, pairs: List[tuple], scope_ids: List[int]) -> Dict[tuple, str]:
    """{(target_kind, target_id): host_class}. esxi → hypervisor türü; hw → portal sınıfı; server → physical."""
    out: Dict[tuple, str] = {}
    eids = [i for k, i in pairs if k == "esxi"]
    if eids:
        for iid, ht in (db.query(HypervisorHostInventory.id, Hypervisor.hypervisor_type)
                        .join(Hypervisor, Hypervisor.id == HypervisorHostInventory.hypervisor_id)
                        .filter(HypervisorHostInventory.id.in_(eids)).all()):
            out[("esxi", iid)] = _HV_CLASS.get(str(getattr(ht, "value", ht)).lower(), "hv_other")
    hids = [i for k, i in pairs if k == "hw"]
    if hids:
        rows = db.query(HwServer.id).filter(HwServer.id.in_(hids)).all()
        sub = _classify_all(db, scope_ids) if scope_ids else {}      # kapsamdaki tüm portal kayıtları (3 sorgu)
        for (hid,) in rows:
            out[("hw", hid)] = sub.get(hid, "physical")
    for k, i in pairs:
        if k == "server":
            out[("server", i)] = "physical"
    return out


def _chassis_alerts(db: Session, scope_ids: List[int], since: datetime) -> List[Dict[str, Any]]:
    """Şasiye ait portal alarmları. OME: `server_ref` == şasi `provider_ref` (şasi de bir cihazdır). OneView: `server_ref` boş
    + `entity_name` == şasi adı (alarmın kaynağı `/rest/enclosures/…`). Sunucu/blade alarmı şasiye YAZILMAZ."""
    if not scope_ids:
        return []
    encl = db.query(HwEnclosure).filter(HwEnclosure.instance_id.in_(scope_ids)).all()
    if not encl:
        return []
    by_ref = {(e.instance_id, str(e.provider_ref)): e for e in encl}
    by_name = {(e.instance_id, (e.name or "").strip().lower()): e for e in encl if (e.name or "").strip()}
    srv_refs = {(s.instance_id, str(s.provider_ref)) for s in db.query(HwServer).filter(HwServer.instance_id.in_(scope_ids)).all()}
    q = db.query(HwAlert).filter(HwAlert.instance_id.in_(scope_ids), HwAlert.state != "cleared",
                                 or_(HwAlert.occurred_at >= since, HwAlert.occurred_at.is_(None)))
    out: List[Dict[str, Any]] = []
    for a in q.order_by(HwAlert.occurred_at.desc()).limit(5000).all():
        e = None
        if a.server_ref and (a.instance_id, str(a.server_ref)) not in srv_refs:
            e = by_ref.get((a.instance_id, str(a.server_ref)))
        if e is None and not a.server_ref:
            e = by_name.get((a.instance_id, (a.entity_name or "").strip().lower()))
        if e is None:
            continue
        out.append({"alert": a, "enclosure": e})
    return out


@router.get("/log-overview")
def log_overview(
    host_class: str = Query("", pattern="^(|esxi|ocp|olvm|hv_other|chassis|physical)$"),
    source: str = Query("", pattern="^(|esxi_sel|esxi_vmkernel|linux_journal|windows_event|ipmi_sel|bmc_redfish|portal_alert)$"),
    severity: str = Query("", pattern="^(|critical|warning|info|all)$"),
    days: int = Query(7, ge=1, le=30), limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Faz 3b — «Donanım Logları» sekmesi: tüm donanım log kaynakları (ESXi SEL/vmkernel, Linux/Windows, ipmitool in-band,
    BMC Redfish) + şasi alarmları, host sınıfına göre. Yalnız `hardware` modülü. Metinler maskelidir."""
    from app.services.hw import bmc_logs, host_logs as HL, ipmi_inband

    if not user_has_module(user, "hardware", db):
        raise HTTPException(403, "Donanım logları için `hardware` modülü yetkisi gerekir.")
    mode, scope_ids, _ = _scope(db)
    hw_on = _enabled(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    flags = {"esxi_sel": HL.enabled(), "esxi_vmkernel": HL.enabled(), "linux_journal": HL.enabled(),
             "windows_event": HL.enabled(), "ipmi_sel": ipmi_inband.enabled(), "bmc_redfish": bmc_logs.enabled(),
             "portal_alert": hw_on}

    sevs = ("critical", "warning") if severity in ("",) else (("critical", "warning", "info") if severity == "all" else (severity,))
    base = db.query(HwLogEntry).filter(HwLogEntry.target_kind.isnot(None), HwLogEntry.last_seen_at >= since)
    # 1) pencerede hedef/kaynak başına özet (sınıf + kaynak sayaçları için)
    agg = (base.filter(HwLogEntry.severity.in_(sevs))
           .with_entities(HwLogEntry.target_kind, HwLogEntry.target_id, HwLogEntry.source, func.count(HwLogEntry.id)).
           group_by(HwLogEntry.target_kind, HwLogEntry.target_id, HwLogEntry.source).all())
    pairs = sorted({(k, i) for k, i, _s, _n in agg})
    cmap = _target_classes(db, pairs, scope_ids)
    by_class: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    hosts_by_source: Dict[str, set] = {}
    for k, i, src, n in agg:
        c = cmap.get((k, i), "physical")
        by_class[c] = by_class.get(c, 0) + n
        by_source[src] = by_source.get(src, 0) + n
        hosts_by_source.setdefault(src, set()).add((k, i))
    chassis = [x for x in _chassis_alerts(db, scope_ids, since) if x["alert"].severity in sevs] if hw_on else []
    if chassis:
        by_class["chassis"] = by_class.get("chassis", 0) + len(chassis)
        by_source["portal_alert"] = by_source.get("portal_alert", 0) + len(chassis)
        hosts_by_source["portal_alert"] = {("enclosure", x["enclosure"].id) for x in chassis}

    sev_counts = {sv: n for sv, n in base.with_entities(HwLogEntry.severity, func.count(HwLogEntry.id))
                  .group_by(HwLogEntry.severity).all()}
    items: List[Dict[str, Any]] = []
    # 2) satırlar
    if source != "portal_alert" and host_class != "chassis":
        q = base.filter(HwLogEntry.severity.in_(sevs))
        if source:
            q = q.filter(HwLogEntry.source == source)
        if host_class:
            keep = [p for p in pairs if cmap.get(p, "physical") == host_class]
            if not keep:
                from sqlalchemy import false
                q = q.filter(false())
            else:
                from sqlalchemy import tuple_
                q = q.filter(tuple_(HwLogEntry.target_kind, HwLogEntry.target_id).in_(keep))
        from sqlalchemy import case
        rank = case((HwLogEntry.severity == "critical", 0), (HwLogEntry.severity == "warning", 1), else_=2)
        rows = q.order_by(rank, HwLogEntry.last_seen_at.desc()).limit(limit).all()
        names: Dict[tuple, Optional[str]] = {}
        sid = {r.target_id for r in rows if r.target_kind == "server"}
        eid = {r.target_id for r in rows if r.target_kind == "esxi"}
        hid = {r.target_id for r in rows if r.target_kind == "hw"}
        for x in db.query(Server.id, Server.name).filter(Server.id.in_(list(sid) or [-1])).all():
            names[("server", x[0])] = x[1]
        for x in db.query(HypervisorHostInventory.id, HypervisorHostInventory.host_name).filter(
                HypervisorHostInventory.id.in_(list(eid) or [-1])).all():
            names[("esxi", x[0])] = x[1]
        for x in db.query(HwServer.id, HwServer.name).filter(HwServer.id.in_(list(hid) or [-1])).all():
            names[("hw", x[0])] = x[1]
        for r in rows:
            items.append({
                "id": f"l{r.id}", "severity": r.severity, "category": r.category, "source": r.source,
                "message": r.message, "occurrences": r.occurrences, "first_seen_at": _iso(r.first_seen_at),
                "last_seen_at": _iso(r.last_seen_at), "host_class": cmap.get((r.target_kind, r.target_id), "physical"),
                "target": {"kind": r.target_kind, "id": r.target_id, "name": names.get((r.target_kind, r.target_id))},
            })
    if chassis and source in ("", "portal_alert") and host_class in ("", "chassis"):
        from app.services.hw import host_log_rules as R
        for x in chassis[:limit]:
            a, e = x["alert"], x["enclosure"]
            items.append({
                "id": f"a{a.id}", "severity": a.severity if a.severity in ("critical", "warning", "info") else "info",
                "category": a.category, "source": "portal_alert", "message": R.mask_text(a.message, 400),
                "occurrences": 1, "first_seen_at": _iso(a.first_seen_at), "last_seen_at": _iso(a.occurred_at or a.last_seen_at),
                "host_class": "chassis", "target": {"kind": "enclosure", "id": e.id, "name": e.name},
            })
    items.sort(key=lambda it: (_SEV_RANK.get(it["severity"], 3), -(datetime.fromisoformat(it["last_seen_at"]).timestamp()
                                                                    if it.get("last_seen_at") else 0)))
    items = items[:limit]
    lr = HL.last_run() or {}
    any_on = any(flags.values())
    available = bool(sum(by_source.values()) or sev_counts)
    return {
        "ok": True, "enabled": any_on, "available": available, "demo": mode == "demo", "days": days,
        "total": len(items), "items": items,
        "counts": {"by_class": by_class, "by_source": by_source, "by_severity": sev_counts},
        "sources": [{"key": k, "enabled": bool(flags.get(k)), "entries": by_source.get(k, 0),
                     "hosts": len(hosts_by_source.get(k, set()))} for k in _LOG_SOURCES],
        "last_run_at": lr.get("at"), "last_run_errors": int(lr.get("errors") or 0),
        "note": "OME yalnız Uyarı/Kritik alarmları saklar; şasi alarmı portalın verdiği kadardır. Boş sonuç = donanım hatası yok "
                "anlamına gelmeyebilir (kaynak kapalı/desteklenmiyor olabilir).",
    }


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
