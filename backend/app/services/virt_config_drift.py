"""Yapılandırma değişiklik geçmişi ve onaylı temelden (baseline) sapma.

virt_config_snapshots'ta bir varlığın ardışık iki satırı = bir değişiklik.
Baseline: operatörün "bu doğru yapılandırma" diye işaretlediği satır; en son
satır baseline'dan farklıysa `drift.entity.baseline` bulgusu üretilir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.infra_finding import VirtConfigSnapshot
from app.services.findings.store import FindingDraft

MAX_DIFF_ITEMS = 200


def _flatten(obj: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k in sorted(obj):
            _flatten(obj[k], f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix] = sorted(obj, key=lambda x: str(x))
        else:
            for i, x in enumerate(obj):
                key = None
                if isinstance(x, dict):
                    key = x.get("name") or x.get("id") or x.get("device")
                _flatten(x, f"{prefix}[{key if key is not None else i}]", out)
    else:
        out[prefix] = obj
    return out


def diff_configs(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    a, b = _flatten(old or {}), _flatten(new or {})
    changes = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            changes.append({
                "path": k,
                "op": "added" if k not in a else ("removed" if k not in b else "changed"),
                "old": a.get(k), "new": b.get(k),
            })
            if len(changes) >= MAX_DIFF_ITEMS:
                break
    return changes


def _cfg(s: VirtConfigSnapshot) -> Dict[str, Any]:
    return ((s.payload or {}).get("config") or {})


def _entity_key(s: VirtConfigSnapshot) -> Tuple[str, Optional[int], str, str]:
    return (s.platform, s.source_id, s.entity_kind, s.entity_ref)


def _baseline_map(db: Session, platforms: Optional[Sequence[str]] = None,
                  source_id: Optional[int] = None) -> Dict[Tuple[str, Optional[int], str, str], VirtConfigSnapshot]:
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.is_baseline.is_(True))
    if platforms:
        q = q.filter(VirtConfigSnapshot.platform.in_(list(platforms)))
    if source_id is not None:
        q = q.filter(VirtConfigSnapshot.source_id == source_id)
    return {_entity_key(b): b for b in q.all()}


def list_changes(db: Session, *, days: int = 30, platform: Optional[str] = None,
                 platforms: Optional[Sequence[str]] = None,
                 source_id: Optional[int] = None, entity_kind: Optional[str] = None,
                 entity: Optional[str] = None, limit: int = 300, ack: str = "hide") -> List[Dict[str, Any]]:
    """ARDIŞIK değişiklik geçmişi (bir varlığın iki ardışık snapshot'ı arasındaki fark).

    Bu liste baseline'dan BAĞIMSIZDIR; baseline sapması (`baseline_overview`) ayrı bir kavramdır.
    `ack`: `hide` (varsayılan; «gözden geçirildi» işaretliler gizlenir) | `only` | `all`.
    """
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days or 30), 365)))
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.captured_at >= since)
    plats = list(platforms) if platforms else ([platform] if platform else None)
    if plats:
        q = q.filter(VirtConfigSnapshot.platform.in_(plats))
    if source_id is not None:
        q = q.filter(VirtConfigSnapshot.source_id == source_id)
    if entity_kind:
        q = q.filter(VirtConfigSnapshot.entity_kind == entity_kind)
    if entity:
        q = q.filter(VirtConfigSnapshot.entity_name.ilike(f"%{entity}%"))
    if ack == "hide":
        q = q.filter(VirtConfigSnapshot.ack_at.is_(None))
    elif ack == "only":
        q = q.filter(VirtConfigSnapshot.ack_at.isnot(None))
    rows = q.order_by(VirtConfigSnapshot.captured_at.desc()).limit(max(1, min(limit, 2000))).all()
    # Varlık düzeyinde baseline var mı (satır baseline snapshot'ın kendisi olmayabilir; "kaldır" için).
    baselined = _baseline_map(db, plats, source_id)
    out = []
    for s in rows:
        prev = (
            db.query(VirtConfigSnapshot)
            .filter(
                VirtConfigSnapshot.platform == s.platform,
                VirtConfigSnapshot.source_id == s.source_id,
                VirtConfigSnapshot.entity_kind == s.entity_kind,
                VirtConfigSnapshot.entity_ref == s.entity_ref,
                VirtConfigSnapshot.captured_at < s.captured_at,
            )
            .order_by(VirtConfigSnapshot.captured_at.desc())
            .first()
        )
        if prev is None:
            continue  # ilk görülme — değişiklik değil
        diff = diff_configs(_cfg(prev), _cfg(s))
        if not diff:
            continue
        b = baselined.get(_entity_key(s))
        out.append({
            "id": s.id, "platform": s.platform, "source_id": s.source_id, "entity_kind": s.entity_kind,
            "entity_ref": s.entity_ref, "entity_name": s.entity_name, "cluster_name": s.cluster_name,
            "captured_at": s.captured_at.isoformat() if s.captured_at else None,
            "previous_at": prev.captured_at.isoformat() if prev.captured_at else None,
            "changes": diff, "change_count": len(diff), "is_baseline": bool(s.is_baseline),
            "has_baseline": b is not None,
            "baseline_at": b.baseline_at.isoformat() if b is not None and b.baseline_at else None,
            "baseline_by": b.baseline_by if b is not None else None,
            "acked": s.ack_at is not None,
            "ack_by": s.ack_by,
            "ack_at": s.ack_at.isoformat() if s.ack_at else None,
        })
    return out


def baseline_overview(db: Session, *, platforms: Optional[Sequence[str]] = None,
                      source_id: Optional[int] = None, entity_kind: Optional[str] = None,
                      with_diff: bool = False) -> Dict[str, Any]:
    """Baseline'ı OLAN varlıklar + CANLI sapma durumu (bulgu turunu beklemez).

    Her öğe: hangi snapshot baseline (id, zaman, kim), güncel snapshot, baseline→güncel fark sayısı.
    `with_diff=True` ilk 50 farkı da döndürür. Özet: işaretli/sapmış sayıları, tür kırılımı, son işaretleme.
    """
    base = _baseline_map(db, platforms, source_id)
    if entity_kind:
        base = {k: v for k, v in base.items() if k[2] == entity_kind}
    latest: Dict[Tuple[str, Optional[int], str, str], VirtConfigSnapshot] = {}
    if base:
        lq = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.is_latest.is_(True))
        if platforms:
            lq = lq.filter(VirtConfigSnapshot.platform.in_(list(platforms)))
        if source_id is not None:
            lq = lq.filter(VirtConfigSnapshot.source_id == source_id)
        latest = {_entity_key(x): x for x in lq.all() if _entity_key(x) in base}
    items: List[Dict[str, Any]] = []
    by_kind: Dict[str, int] = {}
    drifted_by_kind: Dict[str, int] = {}
    for key, b in base.items():
        cur = latest.get(key)
        diff: List[Dict[str, Any]] = []
        if cur is not None and cur.id != b.id:
            diff = diff_configs(_cfg(b), _cfg(cur))
        kind = key[2]
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if diff:
            drifted_by_kind[kind] = drifted_by_kind.get(kind, 0) + 1
        item = {
            "platform": key[0], "source_id": key[1], "entity_kind": kind, "entity_ref": key[3],
            "entity_name": (cur or b).entity_name, "cluster_name": (cur or b).cluster_name,
            "baseline_id": b.id,
            "baseline_at": b.baseline_at.isoformat() if b.baseline_at else None,
            "baseline_by": b.baseline_by,
            "baseline_captured_at": b.captured_at.isoformat() if b.captured_at else None,
            "latest_id": cur.id if cur is not None else None,
            "latest_at": cur.captured_at.isoformat() if cur is not None and cur.captured_at else None,
            "drift_count": len(diff),
            "status": "drift" if diff else "same",
        }
        if with_diff:
            item["changes"] = diff[:50]
        items.append(item)
    items.sort(key=lambda i: (-i["drift_count"], i["entity_kind"], i["entity_name"] or ""))
    marks = [(b.baseline_at, b.baseline_by) for b in base.values() if b.baseline_at]
    last = max(marks, key=lambda m: m[0]) if marks else (None, None)
    return {
        "items": items,
        "count": len(items),
        "drifted": sum(1 for i in items if i["drift_count"]),
        "by_kind": by_kind,
        "drifted_by_kind": drifted_by_kind,
        "marked_at": last[0].isoformat() if last[0] else None,
        "marked_by": last[1],
    }


def baseline_compare(db: Session, *, platform: str, source_id: Optional[int], entity_kind: str,
                     entity_ref: str) -> Optional[Dict[str, Any]]:
    """Tek varlık: baseline yapılandırması ↔ güncel yapılandırma farkı (alan bazlı)."""
    q = db.query(VirtConfigSnapshot).filter(
        VirtConfigSnapshot.platform == platform, VirtConfigSnapshot.entity_kind == entity_kind,
        VirtConfigSnapshot.entity_ref == entity_ref)
    q = q.filter(VirtConfigSnapshot.source_id == source_id) if source_id is not None \
        else q.filter(VirtConfigSnapshot.source_id.is_(None))
    b = q.filter(VirtConfigSnapshot.is_baseline.is_(True)).first()
    if b is None:
        return None
    cur = q.filter(VirtConfigSnapshot.is_latest.is_(True)).first() or b
    diff = [] if cur.id == b.id else diff_configs(_cfg(b), _cfg(cur))
    return {
        "platform": platform, "source_id": source_id, "entity_kind": entity_kind, "entity_ref": entity_ref,
        "entity_name": cur.entity_name or b.entity_name,
        "baseline": {"id": b.id, "baseline_at": b.baseline_at.isoformat() if b.baseline_at else None,
                     "baseline_by": b.baseline_by,
                     "captured_at": b.captured_at.isoformat() if b.captured_at else None},
        "latest": {"id": cur.id, "captured_at": cur.captured_at.isoformat() if cur.captured_at else None},
        "changes": diff, "change_count": len(diff),
        "same": not diff,
    }


def ack_changes(db: Session, ids: Sequence[int], user: str, *, undo: bool = False,
                platforms: Optional[Sequence[str]] = None) -> int:
    """Değişiklik satırlarını «gözden geçirildi» işaretle / geri al. Snapshot SİLİNMEZ, sapma etkilenmez."""
    ids = [int(i) for i in dict.fromkeys(ids)][:2000]
    if not ids:
        return 0
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.id.in_(ids))
    if platforms:
        q = q.filter(VirtConfigSnapshot.platform.in_(list(platforms)))
    vals = ({VirtConfigSnapshot.ack_by: None, VirtConfigSnapshot.ack_at: None} if undo
            else {VirtConfigSnapshot.ack_by: (user or "")[:100], VirtConfigSnapshot.ack_at: datetime.now(timezone.utc)})
    n = q.update(vals, synchronize_session=False)
    db.flush()
    return int(n or 0)


def prune_snapshots(db: Session, *, retention_days: int = 365, keep_last: int = 20,
                    platforms: Optional[Sequence[str]] = None, dry_run: bool = True) -> Dict[str, Any]:
    """Eski değişiklik geçmişini temizler. Korunanlar: güncel (`is_latest`), baseline, her varlığın en yeni
    `keep_last` snapshot'ı ve `retention_days` içindekiler. Varsayılan `dry_run=True` → yalnız sayar."""
    retention_days = max(30, int(retention_days))
    keep_last = max(2, int(keep_last))
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    q = db.query(VirtConfigSnapshot).filter(
        VirtConfigSnapshot.is_latest.is_(False), VirtConfigSnapshot.is_baseline.is_(False),
        VirtConfigSnapshot.captured_at < cutoff)
    if platforms:
        q = q.filter(VirtConfigSnapshot.platform.in_(list(platforms)))
    candidates = q.order_by(VirtConfigSnapshot.captured_at.desc()).all()
    # varlık başına en yeni keep_last snapshot korunur
    rank_q = db.query(VirtConfigSnapshot.id, VirtConfigSnapshot.platform, VirtConfigSnapshot.source_id,
                      VirtConfigSnapshot.entity_kind, VirtConfigSnapshot.entity_ref).order_by(
                          VirtConfigSnapshot.captured_at.desc())
    if platforms:
        rank_q = rank_q.filter(VirtConfigSnapshot.platform.in_(list(platforms)))
    seen: Dict[Tuple, int] = {}
    keep: set = set()
    for sid, plat, src, kind, ref in rank_q.all():
        k = (plat, src, kind, ref)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] <= keep_last:
            keep.add(sid)
    doomed = [c.id for c in candidates if c.id not in keep]
    if not dry_run and doomed:
        for k in range(0, len(doomed), 1000):
            db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.id.in_(doomed[k:k + 1000])).delete(
                synchronize_session=False)
        db.flush()
    return {"dry_run": dry_run, "retention_days": retention_days, "keep_last": keep_last,
            "candidates": len(doomed), "deleted": 0 if dry_run else len(doomed)}


def changes_payload(db: Session, *, platforms: Sequence[str], days: int = 30, platform: Optional[str] = None,
                    source_id: Optional[int] = None, entity_kind: Optional[str] = None,
                    entity: Optional[str] = None, limit: int = 300, ack: str = "hide",
                    suggested_kinds: Sequence[str] = ()) -> Dict[str, Any]:
    """`/changes` yanıtı (virt + OCP ortak): ardışık değişiklikler + baseline özeti + «neden sapma 0» açıklaması.

    İki ayrı kavram: `changes` = ardışık geçmiş (baseline'dan bağımsız); `drifted_count` = baseline'dan CANLI sapma.
    Sapma yalnız baseline'ı OLAN varlıklar için hesaplanır → değişen ama baseline'ı olmayan varlıklar
    (`changed_unbaselined*`) sapma sayısına girmez; ekran bunu açıkça gösterir.
    """
    plats = [platform] if platform else list(platforms)
    rows = list_changes(db, days=days, platforms=plats, source_id=source_id, entity_kind=entity_kind,
                        entity=entity, limit=limit, ack=ack)
    ov = baseline_overview(db, platforms=list(platforms), source_id=source_id)
    base_keys = {(i["platform"], i["source_id"], i["entity_kind"], i["entity_ref"]) for i in ov["items"]}
    changed = {(r["platform"], r["source_id"], r["entity_kind"], r["entity_ref"]) for r in rows}
    unbased = [k for k in changed if k not in base_keys]
    unbased_kinds: Dict[str, int] = {}
    for k in unbased:
        unbased_kinds[k[2]] = unbased_kinds.get(k[2], 0) + 1
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days or 30), 365)))
    aq = db.query(VirtConfigSnapshot.id).filter(
        VirtConfigSnapshot.ack_at.isnot(None), VirtConfigSnapshot.captured_at >= since,
        VirtConfigSnapshot.platform.in_(plats))
    if source_id is not None:
        aq = aq.filter(VirtConfigSnapshot.source_id == source_id)
    acked_total = aq.count()
    baseline_count = ov["count"]
    return {
        "changes": rows,
        "count": len(rows),
        "baseline_count": baseline_count,
        "baseline_by_kind": ov["by_kind"],
        "baseline_marked_at": ov["marked_at"],
        "baseline_marked_by": ov["marked_by"],
        "drifted_count": ov["drifted"],
        "drifted_by_kind": ov["drifted_by_kind"],
        "changed_entities": len(changed),
        "changed_unbaselined": len(unbased),
        "changed_unbaselined_kinds": unbased_kinds,
        "acked_total": acked_total,
        "ack_mode": ack,
        "suggested_baseline": [] if baseline_count else [
            {"entity_kind": k, "note": f"Önerilen: {k} baseline"} for k in suggested_kinds],
        "empty_reason": None if rows or baseline_count else (
            "Henüz değişiklik yok. İlk taramada kayıtlar değişiklik sayılmaz; "
            "baseline işaretleyerek sapma izlemeyi başlatın."
        ),
    }


def set_baseline(db: Session, *, platform: str, source_id: Optional[int], entity_kind: Optional[str] = None,
                 entity_ref: Optional[str] = None, user: str = "") -> int:
    """Seçilen varlık(lar)ın EN SON yapılandırmasını baseline yapar."""
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.platform == platform,
                                            VirtConfigSnapshot.is_latest.is_(True))
    q = q.filter(VirtConfigSnapshot.source_id == source_id) if source_id is not None else q
    if entity_kind:
        q = q.filter(VirtConfigSnapshot.entity_kind == entity_kind)
    if entity_ref:
        q = q.filter(VirtConfigSnapshot.entity_ref == entity_ref)
    now = datetime.now(timezone.utc)
    n = 0
    for s in q.all():
        (db.query(VirtConfigSnapshot)
         .filter(VirtConfigSnapshot.platform == s.platform, VirtConfigSnapshot.source_id == s.source_id,
                 VirtConfigSnapshot.entity_kind == s.entity_kind, VirtConfigSnapshot.entity_ref == s.entity_ref,
                 VirtConfigSnapshot.is_baseline.is_(True), VirtConfigSnapshot.id != s.id)
         .update({VirtConfigSnapshot.is_baseline: False}, synchronize_session=False))
        s.is_baseline = True
        s.baseline_by = user
        s.baseline_at = now
        n += 1
    db.flush()
    return n


def clear_baseline(db: Session, *, platform: str, source_id: Optional[int], entity_kind: Optional[str] = None,
                   entity_ref: Optional[str] = None) -> int:
    """Seçilen varlık(lar)ın baseline işaretini kaldırır (snapshot geçmişi SİLİNMEZ).

    Değişiklik geçmişi korunur; yalnız `is_baseline` kalkar, böylece sapma izleme o varlık için durur
    ve mevcut sapma bulguları bir sonraki karar katmanı turunda çözülür.
    """
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.platform == platform,
                                            VirtConfigSnapshot.is_baseline.is_(True))
    if source_id is not None:
        q = q.filter(VirtConfigSnapshot.source_id == source_id)
    if entity_kind:
        q = q.filter(VirtConfigSnapshot.entity_kind == entity_kind)
    if entity_ref:
        q = q.filter(VirtConfigSnapshot.entity_ref == entity_ref)
    n = q.update({VirtConfigSnapshot.is_baseline: False, VirtConfigSnapshot.baseline_by: None,
                  VirtConfigSnapshot.baseline_at: None}, synchronize_session=False)
    db.flush()
    return int(n or 0)


def drift_findings(db: Session, platform: str, source_id: Optional[int]) -> List[FindingDraft]:
    base: Dict[Tuple[str, str], VirtConfigSnapshot] = {}
    for s in db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.platform == platform,
                                                 VirtConfigSnapshot.source_id == source_id,
                                                 VirtConfigSnapshot.is_baseline.is_(True)).all():
        base[(s.entity_kind, s.entity_ref)] = s
    if not base:
        return []
    out: List[FindingDraft] = []
    for s in db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.platform == platform,
                                                 VirtConfigSnapshot.source_id == source_id,
                                                 VirtConfigSnapshot.is_latest.is_(True)).all():
        b = base.get((s.entity_kind, s.entity_ref))
        if b is None:
            continue
        diff = [] if b.id == s.id else diff_configs(_cfg(b), _cfg(s))
        out.append(FindingDraft(
            "drift.entity.baseline", s.entity_kind, f"{s.entity_kind}:{s.entity_ref}", s.entity_name or s.entity_ref,
            "fail" if diff else "pass",
            evidence={"baseline_at": b.baseline_at.isoformat() if b.baseline_at else None,
                      "baseline_by": b.baseline_by, "changes": diff[:50], "change_count": len(diff)},
            detail=f"{len(diff)} alan farklı" if diff else "", cluster_name=s.cluster_name,
        ))
    return out
