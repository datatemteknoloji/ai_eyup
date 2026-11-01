"""Donanım sağlayıcı senkronu: provider.collect → hw_* tabloları → eşleştirme → bulgular.

* Salt-okunur; sağlayıcıya yazılmaz.
* Kimlik reddi (401/403) → `auth_guard.halt` (DB'de kalıcı), yeniden deneme YOK; yalnız başarılı "Bağlantıyı test et" sürdürür.
* Aynı entegrasyona aynı anda tek deneme (`attempt_lock`; UVICORN_WORKERS=2 güvenli).
* Başarısızlıkta eski veri korunur (bayat işaretlenir); ağ/5xx için devre kesici (art arda hata).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.hw import (
    HwAlert, HwEnclosure, HwFirmware, HwHostLink, HwManager, HwServer, HwWarranty,
)
from app.models.integration_instance import IntegrationInstance
from app.services.hw import auth_guard
from app.services.hw.constants import (
    AUTH_FAILED, CATEGORY, DEFAULT_ALARM_SEC, DEFAULT_INVENTORY_SEC, DEFAULT_WARRANTY_SEC, MIN_ALARM_SEC,
)
from app.services.hw.http import HwApiError
from app.services.hw.snapshot import ALL_PARTS, PART_ALERTS, PART_INVENTORY, PART_WARRANTY, HwSnapshot
from app.services.integrations.registry import get_provider_factory, parse_meta

logger = logging.getLogger(__name__)

BREAKER_FAILS = 3
BREAKER_BASE_SEC = 300
BREAKER_MAX_SEC = 3600
ALERT_KEEP_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def intervals(meta: Dict[str, Any], row: Optional[IntegrationInstance] = None) -> Dict[str, int]:
    iv = meta.get("intervals") or {}
    alarm = int(iv.get("alarm") or (row.sync_interval_sec if row is not None and row.sync_interval_sec else DEFAULT_ALARM_SEC))
    return {PART_ALERTS: max(MIN_ALARM_SEC, alarm),
            PART_INVENTORY: max(3600, int(iv.get("inventory") or DEFAULT_INVENTORY_SEC)),
            PART_WARRANTY: max(3600, int(iv.get("warranty") or DEFAULT_WARRANTY_SEC))}


def provider_stale(row: IntegrationInstance, now: Optional[datetime] = None) -> bool:
    """Son başarılı senkron > 2 × alarm aralığı → bayat."""
    last = _aware(row.last_sync_at)
    if last is None:
        return True
    ivl = intervals(parse_meta(row), row)[PART_ALERTS]
    return ((now or _now()) - last).total_seconds() > 2 * ivl


def data_age_sec(row: IntegrationInstance, now: Optional[datetime] = None) -> Optional[float]:
    last = _aware(row.last_sync_at)
    return None if last is None else max(0.0, ((now or _now()) - last).total_seconds())


def parts_due(row: IntegrationInstance, meta: Dict[str, Any], now: datetime, *, force: bool = False) -> List[str]:
    if force:
        return list(ALL_PARTS)
    ivl = intervals(meta, row)
    at = meta.get("parts_at") or {}
    due: List[str] = []
    for part in ALL_PARTS:
        last = at.get(part)
        try:
            last_dt = datetime.fromisoformat(last) if last else None
        except ValueError:
            last_dt = None
        if last_dt is None or (now - _aware(last_dt)).total_seconds() >= ivl[part]:
            due.append(part)
    return due


def _breaker_open(meta: Dict[str, Any], now: datetime) -> bool:
    until = meta.get("breaker_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > now
    except ValueError:
        return False


_NUM = re.compile(r"(0x[0-9a-f]+|\d+(\.\d+)*|[0-9a-f]{8}-[0-9a-f-]{27})", re.I)


def fingerprint(manager_key: Optional[str], type_id: Optional[str], message: str) -> str:
    """Aynı alarm tipini sunucudan bağımsız gruplamak için (sayılar/IP/GUID normalize)."""
    norm = _NUM.sub("#", (message or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()[:200]
    return hashlib.sha1(f"{manager_key or ''}|{type_id or ''}|{norm}".encode()).hexdigest()


# ── DB uygulama ─────────────────────────────────────────────────────────────────────────────────────────────────
def _apply_managers(db: Session, row: IntegrationInstance, snap: HwSnapshot, now: datetime) -> Dict[str, HwManager]:
    have = {m.provider_key: m for m in db.query(HwManager).filter(HwManager.instance_id == row.id).all()}
    for r in snap.managers:
        m = have.get(r.key)
        if m is None:
            m = HwManager(instance_id=row.id, provider_key=r.key, manager_kind=r.kind)
            db.add(m)
            have[r.key] = m
        m.manager_kind, m.name, m.address = r.kind, (r.name or r.key)[:255], r.address
        m.version, m.api_version, m.support_level = r.version, r.api_version, r.support_level
        m.status, m.last_error = r.status, (r.error or None)
        if r.server_count is not None:
            m.server_count = r.server_count
        if r.status == "ok":
            m.last_sync_at = now
    db.flush()
    return have


def _apply_inventory(db: Session, row: IntegrationInstance, snap: HwSnapshot, mgrs: Dict[str, HwManager],
                     now: datetime) -> Dict[str, int]:
    iid = row.id
    have = {s.provider_ref: s for s in db.query(HwServer).filter(HwServer.instance_id == iid).all()}
    seen: Set[str] = set()
    for r in snap.servers:
        o = have.get(r.provider_ref)
        if o is None:
            o = HwServer(instance_id=iid, provider_ref=r.provider_ref, vendor=r.vendor)
            db.add(o)
            have[r.provider_ref] = o
        seen.add(r.provider_ref)
        mgr = mgrs.get(r.manager_key or "")
        o.manager_id = mgr.id if mgr is not None else None
        o.vendor, o.name = r.vendor, (r.name or "")[:255]
        for f in ("os_hostname", "model", "serial", "uuid", "virtual_serial", "virtual_uuid", "bmc_ip", "bmc_type",
                  "bmc_version", "bios_version", "form_factor", "enclosure_ref", "enclosure_name", "bay", "raw_status",
                  "power_state", "connected", "cpu_count", "memory_gb", "web_url"):
            v = getattr(r, f)
            if f == "bios_version" and v is None and o.bios_version and r.vendor == "dell":
                continue            # Dell BIOS yalnız firmware envanteri okunan turda gelir; okunmayan turda önceki değer korunur
            setattr(o, f, v)
        o.health = r.health
        o.extra_json = json.dumps(r.extra, default=str) if r.extra else None
        o.collected_at = now
    # yalnız envanteri TAM okunan yönetim noktalarının kayıp kayıtları silinir (hatalı appliance'ın verisi korunur)
    complete_ids = {mgrs[k].id for k in snap.complete_managers if k in mgrs}
    removed = 0
    for ref, o in list(have.items()):
        if ref not in seen and o.manager_id in complete_ids:
            db.delete(o)
            removed += 1
    db.flush()
    # şasiler
    eh = {e.provider_ref: e for e in db.query(HwEnclosure).filter(HwEnclosure.instance_id == iid).all()}
    eseen: Set[str] = set()
    for e in snap.enclosures:
        o = eh.get(e.provider_ref)
        if o is None:
            o = HwEnclosure(instance_id=iid, provider_ref=e.provider_ref)
            db.add(o)
            eh[e.provider_ref] = o
        eseen.add(e.provider_ref)
        mgr = mgrs.get(e.manager_key or "")
        o.manager_id = mgr.id if mgr is not None else None
        o.name, o.model, o.serial, o.health, o.bay_count = (e.name or "")[:255], e.model, e.serial, e.health, e.bay_count
        o.collected_at = now
    for ref, o in list(eh.items()):
        if ref not in eseen and o.manager_id in complete_ids:
            db.delete(o)
    # firmware (yalnız sağlayıcı verdiyse; sunucu başına yenilenir)
    if snap.firmware:
        db.flush()
        ids = {ref: o.id for ref, o in have.items() if o.id is not None}
        refs = {f.server_ref for f in snap.firmware}
        sid = [ids[r] for r in refs if r in ids]
        if sid:
            db.query(HwFirmware).filter(HwFirmware.server_id.in_(sid)).delete(synchronize_session=False)
        for f in snap.firmware:
            if f.server_ref in ids:
                db.add(HwFirmware(server_id=ids[f.server_ref], name=(f.name or "")[:255],
                                  component_type=f.component_type, version=f.version,
                                  status=(f.status or None) and str(f.status)[:16],
                                  component_id=(f.component_id or None) and str(f.component_id)[:64],
                                  location=(f.location or None) and str(f.location)[:255], collected_at=now))
    db.flush()
    out = {"servers": len(snap.servers), "removed": removed, "enclosures": len(snap.enclosures)}
    if snap.firmware_progress:
        out["firmware_read"] = sum(p.get("read", 0) for p in snap.firmware_progress.values())
        out["firmware_total"] = sum(p.get("total", 0) for p in snap.firmware_progress.values())
    return out


def _apply_alerts(db: Session, row: IntegrationInstance, snap: HwSnapshot, mgrs: Dict[str, HwManager],
                  now: datetime) -> Dict[str, int]:
    iid = row.id
    have = {a.provider_ref: a for a in db.query(HwAlert).filter(HwAlert.instance_id == iid).all()}
    seen: Set[str] = set()
    for r in snap.alerts:
        o = have.get(r.provider_ref)
        if o is None:
            o = HwAlert(instance_id=iid, provider_ref=r.provider_ref, first_seen_at=now)
            db.add(o)
            have[r.provider_ref] = o
        seen.add(r.provider_ref)
        mgr = mgrs.get(r.manager_key or "")
        o.manager_id = mgr.id if mgr is not None else None
        o.server_ref, o.entity_name = r.server_ref, (r.entity_name or None)
        o.severity, o.state, o.category = r.severity, r.state, (r.category or None)
        o.message = (r.message or "")[:4000]
        o.fingerprint = fingerprint(r.manager_key, r.type_id, r.message)
        o.occurred_at, o.cleared_at, o.last_seen_at = r.occurred_at, r.cleared_at, now
    # OneView/OVGD: aktif alarm listesinde artık olmayan aktif kayıtlar "temizlendi" (alarm taraması başarılıysa)
    ok_mgr_ids = {m.id for m in mgrs.values() if m.status == "ok"}
    cleared = 0
    for ref, o in have.items():
        if ref not in seen and o.state == "active" and o.manager_id in ok_mgr_ids:
            o.state, o.cleared_at = "cleared", now
            cleared += 1
    cutoff = now - timedelta(days=ALERT_KEEP_DAYS)
    db.query(HwAlert).filter(HwAlert.instance_id == iid, HwAlert.occurred_at < cutoff).delete(synchronize_session=False)
    db.flush()
    return {"alerts": len(snap.alerts), "cleared": cleared}


def _apply_warranty(db: Session, row: IntegrationInstance, snap: HwSnapshot) -> Dict[str, int]:
    iid = row.id
    have = {w.provider_ref: w for w in db.query(HwWarranty).filter(HwWarranty.instance_id == iid).all()}
    seen: Set[str] = set()
    for r in snap.warranties:
        o = have.get(r.provider_ref)
        if o is None:
            o = HwWarranty(instance_id=iid, provider_ref=r.provider_ref)
            db.add(o)
        seen.add(r.provider_ref)
        o.server_ref, o.serial = r.server_ref, r.serial
        o.service_level, o.provider_name = (r.service_level or None), r.provider_name
        o.start_date, o.end_date = r.start_date, r.end_date
    if snap.warranties:   # boş yanıt mevcut veriyi silmez (OME internetsiz olabilir)
        for ref, o in have.items():
            if ref not in seen:
                db.delete(o)
    db.flush()
    return {"warranties": len(snap.warranties)}


def _fail(db: Session, row: IntegrationInstance, meta: Dict[str, Any], msg: str, now: datetime,
          *, network: bool = True) -> None:
    from app.services.capabilities import invalidate_capabilities
    n = int(meta.get("consecutive_failures") or 0) + 1
    meta["consecutive_failures"] = n
    if n >= BREAKER_FAILS:
        wait = min(BREAKER_MAX_SEC, BREAKER_BASE_SEC * (2 ** (n - BREAKER_FAILS)))
        meta["breaker_until"] = (now + timedelta(seconds=wait)).isoformat()
    row.meta_json = json.dumps(meta)
    row.last_status, row.last_error = "error", msg[:2000]
    db.commit()
    invalidate_capabilities()


def sync_instance(db: Session, row: IntegrationInstance, *, force: bool = False, provider: Any = None,
                  parts: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Tek entegrasyon senkronu. Hata yutulur; durum satıra yazılır."""
    from app.services.capabilities import invalidate_capabilities
    from app.services.hw.demo_gate import DISABLED_MSG_TR, demo_enabled, is_demo_kind
    now = _now()
    if is_demo_kind(row.kind) and not demo_enabled():
        return {"ok": False, "skipped": "demo_disabled", "error": DISABLED_MSG_TR}
    if auth_guard.is_halted(row):
        # force dahil: yalnız başarılı "Bağlantıyı test et" sürdürür
        return {"ok": False, "skipped": "auth_halted", "error": "Kimlik doğrulama hatası nedeniyle senkron durduruldu; "
                "bilgileri düzeltip “Bağlantıyı test et” ile doğrulayın."}
    meta = parse_meta(row)
    if not force and _breaker_open(meta, now):
        return {"ok": False, "skipped": "circuit_open", "breaker_until": meta.get("breaker_until")}
    if provider is None:
        factory = get_provider_factory(row.kind)
        if factory is None:
            return {"ok": False, "error": f"Bilinmeyen sağlayıcı: {row.kind}"}
        provider = factory(row)

    with auth_guard.attempt_lock(row.id) as got:
        if not got:
            return {"ok": False, "skipped": "busy"}
        db.refresh(row)                       # kilidi bekleyen worker, diğerinin halt'ını görsün
        if auth_guard.is_halted(row):
            return {"ok": False, "skipped": "auth_halted"}
        meta = parse_meta(row)
        todo = list(parts) if parts is not None else parts_due(row, meta, now, force=force)
        if not todo:
            return {"ok": True, "skipped": "not_due"}
        try:
            since = None
            try:
                ls = meta.get("last_alert_ts")
                since = datetime.fromisoformat(ls) if ls else None
            except ValueError:
                since = None
            snap: HwSnapshot = provider.collect(todo, since_alert=since)
        except auth_guard.AuthHalt as h:
            auth_guard.halt(db, row, kind=h.kind, message=h.message, where=h.where)
            return {"ok": False, "auth_halted": True, "error": h.message, "kind": h.kind}
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):          # savunma: sağlayıcı AuthHalt'a çevirmediyse
                auth_guard.halt(db, row, kind=e.kind, message=e.message, where="collect")
                return {"ok": False, "auth_halted": True, "error": e.message, "kind": e.kind}
            _fail(db, row, meta, e.message, now)
            return {"ok": False, "error": e.message, "kind": e.kind}
        except Exception as e:  # noqa: BLE001
            logger.exception("HW sync hata (instance=%s)", row.id)
            _fail(db, row, meta, f"Beklenmeyen hata: {type(e).__name__}", now)
            return {"ok": False, "error": f"Beklenmeyen hata: {type(e).__name__}"}

        try:
            mgrs = _apply_managers(db, row, snap, now)
            counts: Dict[str, Any] = {}
            if PART_INVENTORY in snap.parts:
                counts.update(_apply_inventory(db, row, snap, mgrs, now))
            if PART_ALERTS in snap.parts:
                counts.update(_apply_alerts(db, row, snap, mgrs, now))
            if PART_WARRANTY in snap.parts:
                counts.update(_apply_warranty(db, row, snap))
            ok_mgrs = [m for m in snap.managers if m.status == "ok"]
            if snap.managers and not ok_mgrs:
                db.rollback()
                msg = next((m.error for m in snap.managers if m.error), "Hiçbir yönetim noktasından veri alınamadı")
                db.refresh(row)
                _fail(db, row, parse_meta(row), msg, now)
                return {"ok": False, "error": msg}
            meta = parse_meta(row)
            at = meta.get("parts_at") or {}
            for p in snap.parts:
                at[p] = now.isoformat()
            meta["parts_at"] = at
            if PART_ALERTS in snap.parts:
                meta["last_alert_ts"] = now.isoformat()
            if snap.firmware_cursors:                               # sınırlı firmware turu: kalan cihazlar sonraki turda
                cur = dict(meta.get("firmware_cursors") or {})
                cur.update(snap.firmware_cursors)
                meta["firmware_cursors"] = cur
            meta["consecutive_failures"] = 0
            meta.pop("breaker_until", None)
            meta["warnings"] = snap.warnings[:20]
            meta["not_measurable"] = snap.not_measurable[:20]
            lc = dict(meta.get("last_counts") or {})
            lc.update(counts)
            meta["last_counts"] = lc
            row.meta_json = json.dumps(meta)
            row.last_sync_at, row.last_status, row.last_error = now, "ok", None
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.exception("HW upsert hata (instance=%s)", row.id)
            db.refresh(row)
            _fail(db, row, parse_meta(row), f"Veri yazılamadı: {type(e).__name__}", now)
            return {"ok": False, "error": f"Veri yazılamadı: {type(e).__name__}"}

    invalidate_capabilities()
    try:
        from app.services.hw.matching import run_matching
        run_matching(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("HW eşleştirme hata")
    try:   # durum → SystemEvent → Incident (gerçek sağlayıcı; DEMO üretmez)
        from app.services.hw.events import sync_hw_events
        sync_hw_events(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("HW olay üretimi hata")
    return {"ok": True, "parts": sorted(snap.parts), "counts": counts, "warnings": snap.warnings}


def has_enabled_hw_instance_db(db: Session) -> bool:
    from app.services.hw.demo_gate import demo_enabled, is_demo_kind
    rows = (db.query(IntegrationInstance.kind)
            .filter(IntegrationInstance.category == CATEGORY, IntegrationInstance.enabled.is_(True)).all())
    return any((not is_demo_kind(k)) or demo_enabled() for (k,) in rows)


def run_all_due(db: Session) -> Dict[str, Any]:
    """Zamanlayıcı girişi: etkin donanım entegrasyonlarından vadesi gelenleri senkronlar (kimlik reddedilenler atlanır)."""
    rows = (db.query(IntegrationInstance)
            .filter(IntegrationInstance.category == CATEGORY, IntegrationInstance.enabled.is_(True)).all())
    out: Dict[str, Any] = {"instances": 0, "synced": 0, "skipped": 0, "errors": 0}
    for row in rows:
        out["instances"] += 1
        res = sync_instance(db, row)
        if res.get("ok") and not res.get("skipped"):
            out["synced"] += 1
        elif res.get("skipped"):
            out["skipped"] += 1
        else:
            out["errors"] += 1
    try:
        from app.services.hw.findings_engine import persist_hw_findings
        persist_hw_findings(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("HW bulgu üretimi hata")
    return out
