"""Yedek sağlayıcı senkronu: provider.sync → bk_* tabloları → eşleştirme.

* Salt-okunur: sağlayıcıya yazılmaz; Veeam verisi `virt_vm_metrics`/Prometheus'a gitmez.
* Zaman aşımı + yeniden deneme istemcide; burada devre kesici (art arda hata).
* Başarısızlıkta eski veri korunur; durum/`last_error` yazılır, bulgular "bayat" işaretlenir.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.backup import (
    BkJob, BkProtectedObject, BkRepository, BkRestorePoint, BkSession,
)
from app.models.integration_instance import IntegrationInstance
from app.services.backup.matching import match_all
from app.services.backup.protocol import SyncCursor
from app.services.backup.registry import get_provider_factory, parse_meta
from app.services.backup.veeam_client import VeeamApiError

logger = logging.getLogger(__name__)

BREAKER_FAILS = 3
BREAKER_BASE_SEC = 300
BREAKER_MAX_SEC = 3600
RP_KEEP_DAYS = 60
GIB = 1024 ** 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def provider_stale(row: IntegrationInstance, now: Optional[datetime] = None) -> bool:
    """Son başarılı senkron > 2 × sync_interval → bayat."""
    last = _aware(row.last_sync_at)
    if last is None:
        return True
    return ((now or _now()) - last).total_seconds() > 2 * max(60, int(row.sync_interval_sec or 3600))


def data_age_sec(row: IntegrationInstance, now: Optional[datetime] = None) -> Optional[float]:
    last = _aware(row.last_sync_at)
    return None if last is None else max(0.0, ((now or _now()) - last).total_seconds())


def _breaker_open(meta: Dict[str, Any], now: datetime) -> bool:
    until = meta.get("breaker_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > now
    except ValueError:
        return False


def _vms(db: Session) -> List[Dict[str, Any]]:
    from app.services import virt_insights_data as vd
    hvs = vd.virt_hypervisors(db, platform="vmware")
    return vd.vm_allocations(db, [h.id for h in hvs])


def _upsert(db: Session, row: IntegrationInstance, snap: Dict[str, Any]) -> Dict[str, int]:
    iid = row.id
    jobs = {j.provider_job_id: j for j in db.query(BkJob).filter(BkJob.instance_id == iid).all()}
    for j in snap["jobs"]:
        o = jobs.get(j["id"])
        if o is None:
            o = BkJob(instance_id=iid, provider_job_id=j["id"])
            db.add(o)
            jobs[j["id"]] = o
        o.name, o.job_type, o.schedule, o.enabled = j["name"][:512], j["kind"], (j.get("schedule") or None), bool(j["enabled"])
        o.status, o.last_result = j.get("status"), j.get("last_result")
        o.last_run_at, o.next_run_at = j.get("last_run"), j.get("next_run")
        o.repository_provider_id, o.repository_name = j.get("repository_id"), j.get("repository_name")
        o.objects_count = j.get("objects_count")
        o.meta_json = json.dumps({"vbr_type": j.get("type")})
    db.flush()

    repos = {r.provider_repo_id: r for r in db.query(BkRepository).filter(BkRepository.instance_id == iid).all()}
    for r in snap["repos"]:
        o = repos.get(r["id"])
        if o is None:
            o = BkRepository(instance_id=iid, provider_repo_id=r["id"])
            db.add(o)
        o.name, o.repo_type, o.is_online = r["name"][:512], r.get("type"), r.get("is_online")
        cap, free = r.get("capacity_gb"), r.get("free_gb")
        o.capacity_bytes = int(cap * GIB) if cap is not None else None   # GB mi GiB mi belirsiz (api_ref #3)
        o.free_bytes = int(free * GIB) if free is not None else None
        o.used_bytes = (o.capacity_bytes - o.free_bytes) if (cap is not None and free is not None) else None

    # Oturumlar (sliding pencere; provider_session_id ile upsert)
    sess_n = 0
    if snap["sessions"]:
        existing = {s.provider_session_id: s for s in db.query(BkSession).join(BkJob, BkSession.job_id == BkJob.id)
                    .filter(BkJob.instance_id == iid).all()}
        for s in snap["sessions"]:
            job = jobs.get(str(s.get("job_id")))
            if job is None:
                continue
            o = existing.get(s["id"])
            if o is None:
                o = BkSession(job_id=job.id, provider_session_id=s["id"])
                db.add(o)
            o.started_at, o.ended_at, o.result = s.get("created"), s.get("ended"), s.get("result")
            o.session_type, o.message = s.get("type"), (s.get("message") or "")[:2000]
            sess_n += 1

    # Korunan nesneler + restore point'ler
    objs = {o.provider_object_id: o for o in db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == iid).all()}
    newest_by_name: Dict[str, Dict[str, Any]] = {}
    for rp in snap["restore_points"]:
        cur = newest_by_name.get(rp["name"])
        if cur is None or rp["created"] > cur["created"]:
            newest_by_name[rp["name"]] = rp
    matches = match_all(snap["objects"], _vms(db))
    seen_ids = set()
    for ob, server_id, method, conf in matches:
        o = objs.get(ob["id"])
        if o is None:
            o = BkProtectedObject(instance_id=iid, provider_object_id=ob["id"])
            db.add(o)
            objs[ob["id"]] = o
        seen_ids.add(ob["id"])
        o.name, o.platform = ob["name"][:512], ob["platform"]
        o.object_ref, o.path = ob.get("object_ref"), (ob.get("path") or None)
        o.restore_points_count = ob.get("restore_points_count")
        o.matched_vm_id, o.match_method, o.match_confidence = server_id, method, conf
        rp = newest_by_name.get(ob["name"])
        if rp is not None:
            prev = _aware(o.last_restore_point_at)
            if prev is None or rp["created"] > prev:
                o.last_restore_point_at = rp["created"]
                jid = snap["backup_job"].get(str(rp.get("backup_id")))
                if jid:
                    o.job_provider_id = jid
    db.flush()
    # Artık yedekte görünmeyen nesneler kaldırılır (tamamlayıcı koruma bilgisi)
    for pid, o in list(objs.items()):
        if pid not in seen_ids:
            db.delete(o)

    # Restore point geçmişi (ad → ilk nesne); (nesne, zaman) tekilleştirilir
    by_name_obj = {}
    for o in objs.values():
        if o in db.deleted or o.id is None:
            continue
        by_name_obj.setdefault(o.name, o)
    rp_n = 0
    if snap["restore_points"] and by_name_obj:
        ids = [o.id for o in by_name_obj.values()]
        mn = min(r["created"] for r in snap["restore_points"])
        have = {(r.protected_object_id, _aware(r.created_at)) for r in
                db.query(BkRestorePoint).filter(BkRestorePoint.protected_object_id.in_(ids),
                                                BkRestorePoint.created_at >= mn).all()}
        for rp in snap["restore_points"]:
            o = by_name_obj.get(rp["name"])
            if o is None or (o.id, rp["created"]) in have:
                continue
            jid = snap["backup_job"].get(str(rp.get("backup_id")))
            job = jobs.get(jid) if jid else None
            db.add(BkRestorePoint(protected_object_id=o.id, job_id=job.id if job else None,
                                  created_at=rp["created"], point_type=rp.get("type")))
            have.add((o.id, rp["created"]))
            rp_n += 1
    db.query(BkRestorePoint).filter(BkRestorePoint.created_at < _now() - timedelta(days=RP_KEEP_DAYS)).delete(
        synchronize_session=False)
    db.flush()
    return {"jobs": len(snap["jobs"]), "repositories": len(snap["repos"]), "sessions": sess_n,
            "objects": len(snap["objects"]), "restore_points_new": rp_n}


def sync_instance(db: Session, row: IntegrationInstance, *, force: bool = False, provider: Any = None) -> Dict[str, Any]:
    """Tek instance senkronu. Hata yutulur; durum satıra yazılır. Commit çağıran yapar değil — burada yapılır."""
    from app.services.capabilities import invalidate_capabilities
    now = _now()
    from app.services.backup.demo_gate import DISABLED_MSG_TR, demo_enabled, is_demo_kind
    if is_demo_kind(row.kind) and not demo_enabled():
        # F.0: DEMO kapalıyken senkron (force dahil) yok — veri üretilmez, satıra dokunulmaz.
        return {"ok": False, "skipped": "demo_disabled", "error": DISABLED_MSG_TR}
    meta = parse_meta(row)
    if not force and _breaker_open(meta, now):
        return {"ok": False, "skipped": "circuit_open", "breaker_until": meta.get("breaker_until")}
    if provider is None:
        factory = get_provider_factory(row.kind)
        if factory is None:
            return {"ok": False, "error": f"Bilinmeyen sağlayıcı: {row.kind}"}
        provider = factory(row)
    prev_status = row.last_status
    try:
        cur = provider.sync(SyncCursor(token=json.dumps(meta.get("cursor") or {})))
        snap = getattr(provider, "last_snapshot", None) or {}
        counts = _upsert(db, row, snap)
        meta["cursor"] = json.loads(cur.token or "{}")
        meta["consecutive_failures"] = 0
        meta.pop("breaker_until", None)
        meta["server"] = snap.get("server")
        meta["warnings"] = snap.get("warnings") or []
        meta["last_counts"] = counts
        row.last_sync_at, row.last_status, row.last_error = now, "ok", None
        row.meta_json = json.dumps(meta)
        db.commit()
        out = {"ok": True, "counts": counts, "warnings": meta["warnings"]}
    except VeeamApiError as e:
        db.rollback()
        out = _fail(db, row, meta, now, "auth_failed" if e.kind in ("auth", "forbidden") else "error", str(e))
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.exception("backup sync hata (instance %s)", row.id)
        out = _fail(db, row, meta, now, "error", f"Beklenmeyen hata: {type(e).__name__}")
    if prev_status != row.last_status:
        invalidate_capabilities()
    return out


def _fail(db: Session, row: IntegrationInstance, meta: Dict[str, Any], now: datetime, status: str, msg: str) -> Dict[str, Any]:
    n = int(meta.get("consecutive_failures") or 0) + 1
    meta["consecutive_failures"] = n
    if n >= BREAKER_FAILS:
        wait = min(BREAKER_BASE_SEC * (2 ** (n - BREAKER_FAILS)), BREAKER_MAX_SEC)
        meta["breaker_until"] = (now + timedelta(seconds=wait)).isoformat()
    row = db.merge(row)
    row.last_status, row.last_error, row.meta_json = status, msg[:1000], json.dumps(meta)
    db.commit()
    return {"ok": False, "error": msg, "status": status, "consecutive_failures": n}


def run_all_due(db: Session, *, force: bool = False) -> List[Dict[str, Any]]:
    """Fleet işi: enabled backup instance'ları (aralığı dolanlar) senkronlar."""
    now = _now()
    out = []
    from app.services.backup.demo_gate import active_instances
    rows = active_instances(db, include_demo=True)   # DEMO kapalıyken senkron yok
    for row in rows:
        last = _aware(row.last_sync_at)
        due = force or last is None or (now - last).total_seconds() >= max(60, int(row.sync_interval_sec or 3600))
        if not due:
            continue
        r = sync_instance(db, row, force=force)
        out.append({"instance_id": row.id, "label": row.label, **r})
    return out


def has_enabled_backup_instance() -> bool:
    """Zamanlayıcı koruması: enabled backup instance yoksa job kuyruğa HİÇ girmez."""
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            from app.services.backup.demo_gate import active_instances
            return bool(active_instances(db, include_demo=True))
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return False
