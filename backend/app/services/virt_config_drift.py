"""Yapılandırma değişiklik geçmişi ve onaylı temelden (baseline) sapma.

virt_config_snapshots'ta bir varlığın ardışık iki satırı = bir değişiklik.
Baseline: operatörün "bu doğru yapılandırma" diye işaretlediği satır; en son
satır baseline'dan farklıysa `drift.entity.baseline` bulgusu üretilir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

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


def list_changes(db: Session, *, days: int = 30, platform: Optional[str] = None,
                 source_id: Optional[int] = None, entity_kind: Optional[str] = None,
                 entity: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days or 30), 365)))
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.captured_at >= since)
    if platform:
        q = q.filter(VirtConfigSnapshot.platform == platform)
    if source_id is not None:
        q = q.filter(VirtConfigSnapshot.source_id == source_id)
    if entity_kind:
        q = q.filter(VirtConfigSnapshot.entity_kind == entity_kind)
    if entity:
        q = q.filter(VirtConfigSnapshot.entity_name.ilike(f"%{entity}%"))
    rows = q.order_by(VirtConfigSnapshot.captured_at.desc()).limit(max(1, min(limit, 2000))).all()
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
        out.append({
            "id": s.id, "platform": s.platform, "source_id": s.source_id, "entity_kind": s.entity_kind,
            "entity_ref": s.entity_ref, "entity_name": s.entity_name, "cluster_name": s.cluster_name,
            "captured_at": s.captured_at.isoformat() if s.captured_at else None,
            "previous_at": prev.captured_at.isoformat() if prev.captured_at else None,
            "changes": diff, "change_count": len(diff), "is_baseline": bool(s.is_baseline),
        })
    return out


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
