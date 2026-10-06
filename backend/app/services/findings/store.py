"""Bulgu ve config snapshot kalıcılığı.

Kural: bir tur yalnızca DEĞERLENDİRDİĞİ kategorilerin bulgularını çözer.
Toplayıcı hata verdiyse o kategori `persist_findings`'e hiç verilmez; aksi
halde geçici bir bağlantı hatası tüm açık bulguları "çözüldü" gösterirdi.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.infra_finding import (
    InfraFinding, InfraFindingException, VirtConfigSnapshot,
)
from app.services.findings.registry import (
    SEVERITY_RANK, category_of, get_check,
)

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class FindingDraft:
    check_id: str
    entity_kind: str
    entity_ref: str
    entity_name: str
    result: str                      # pass | fail | not_measurable
    evidence: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    cluster_name: Optional[str] = None
    severity: Optional[str] = None   # kataloğu ezmek için (ör. snapshot yaşına göre)
    title: Optional[str] = None      # dinamik kontroller (CVE/KB/yükseltme)
    recommendation: Optional[str] = None
    refs: Optional[List[str]] = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.entity_ref, self.check_id)


def _json_safe(v: Any) -> Any:
    return json.loads(json.dumps(v, default=str))


def persist_findings(
    db: Session,
    *,
    platform: str,
    source_id: Optional[int],
    source_name: str,
    categories: Iterable[str],
    drafts: Sequence[FindingDraft],
    run_id: Optional[int] = None,
    now: Optional[datetime] = None,
    resolve_checks: Optional[Iterable[str]] = None,
) -> Dict[str, int]:
    """Bulguları upsert eder; değerlendirilen kategoride bu turda üretilmeyenleri çözer.

    resolve_checks verilirse yalnız bu check_id'ler (":" ile biten öğe önek
    kabul edilir) çözülebilir — ör. dosya taraması yapılmayan turda sahipsiz
    disk bulguları korunur.
    """
    scope = list(resolve_checks) if resolve_checks is not None else None

    def _in_scope(cid: str) -> bool:
        if scope is None:
            return True
        return any(cid == s or (s.endswith(":") and cid.startswith(s)) for s in scope)
    now = now or utcnow()
    cats: Set[str] = set(categories)
    if not cats:
        return {"upserted": 0, "resolved": 0}

    existing: Dict[Tuple[str, str], InfraFinding] = {}
    q = db.query(InfraFinding).filter(
        InfraFinding.platform == platform,
        InfraFinding.category.in_(cats),
    )
    q = q.filter(InfraFinding.source_id == source_id) if source_id is not None else q.filter(
        InfraFinding.source_id.is_(None)
    )
    for row in q.all():
        existing[(row.entity_ref, row.check_id)] = row

    seen: Set[Tuple[str, str]] = set()
    upserted = 0
    for d in drafts:
        cat = category_of(d.check_id)
        if cat not in cats:
            continue
        if d.key in seen:
            continue
        seen.add(d.key)
        cdef = get_check(d.check_id)
        title = d.title or (cdef.title_tr if cdef else d.check_id)
        sev = d.severity or (cdef.severity if cdef else "medium")
        if d.result != "fail":
            sev = "info" if d.result == "not_measurable" else sev
        rec = d.recommendation if d.recommendation is not None else (cdef.recommendation_tr if cdef else "")
        refs = d.refs if d.refs is not None else (list(cdef.refs) if cdef else [])
        row = existing.get(d.key)
        if row is None:
            row = InfraFinding(
                platform=platform, source_id=source_id, check_id=d.check_id,
                entity_ref=d.entity_ref[:512], first_seen=now,
            )
            db.add(row)
            existing[d.key] = row
        elif not row.active or (row.result != "fail" and d.result == "fail"):
            # Yeniden açılan bulgu: ilk görülme zamanı bu açılıştan başlar
            row.first_seen = now
        row.source_name = source_name
        row.category = cat
        row.entity_kind = d.entity_kind
        row.entity_name = (d.entity_name or d.entity_ref)[:512]
        row.cluster_name = d.cluster_name
        row.result = d.result
        row.severity = sev
        row.title = title[:500]
        row.detail = d.detail
        row.evidence = _json_safe(d.evidence or {})
        row.recommendation = rec
        row.refs = refs
        row.last_seen = now
        row.active = True
        row.resolved_at = None
        row.run_id = run_id
        upserted += 1

    resolved = 0
    for key, row in existing.items():
        if key in seen or not row.active or not _in_scope(row.check_id):
            continue
        row.active = False
        row.resolved_at = now
        resolved += 1
    db.flush()
    return {"upserted": upserted, "resolved": resolved}


# ── İstisnalar ────────────────────────────────────────────────────────────────

def exception_keys(db: Session) -> Dict[Tuple[str, Optional[int], str, str], InfraFindingException]:
    now = utcnow()
    out: Dict[Tuple[str, Optional[int], str, str], InfraFindingException] = {}
    for ex in db.query(InfraFindingException).all():
        exp = _aware(ex.expires_at)
        if exp and exp < now:
            continue
        out[(ex.platform, ex.source_id, ex.entity_ref, ex.check_id)] = ex
    return out


def finding_to_dict(row: InfraFinding, exc: Optional[InfraFindingException] = None,
                    locale: str = "tr") -> Dict[str, Any]:
    cdef = get_check(row.check_id)
    title = row.title
    rec = row.recommendation
    if locale == "en" and cdef:
        title = cdef.title_en or title
        rec = cdef.recommendation_en or rec
    return {
        "id": row.id,
        "platform": row.platform,
        "source_id": row.source_id,
        "source_name": row.source_name,
        "category": row.category,
        "check_id": row.check_id,
        "entity_kind": row.entity_kind,
        "entity_ref": row.entity_ref,
        "entity_name": row.entity_name,
        "cluster_name": row.cluster_name,
        "result": row.result,
        "severity": row.severity,
        "title": title,
        "detail": row.detail,
        "evidence": row.evidence or {},
        "recommendation": rec,
        "refs": row.refs or [],
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        "active": bool(row.active),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "has_draft": bool(cdef and cdef.draft),
        "exception": (
            {
                "id": exc.id, "reason": exc.reason, "created_by": exc.created_by,
                "created_at": exc.created_at.isoformat() if exc.created_at else None,
                "expires_at": exc.expires_at.isoformat() if exc.expires_at else None,
            } if exc else None
        ),
    }


def query_findings(
    db: Session,
    *,
    category: Optional[str] = None,
    categories: Optional[Sequence[str]] = None,
    platform: Optional[str] = None,
    platforms: Optional[Sequence[str]] = None,
    source_id: Optional[int] = None,
    cluster: Optional[str] = None,
    result: Optional[str] = "fail",
    severity_min: Optional[str] = None,
    include_excepted: bool = False,
    include_resolved: bool = False,
    entity: Optional[str] = None,
    check_id: Optional[str] = None,
    limit: int = 1000,
    locale: str = "tr",
) -> List[Dict[str, Any]]:
    q = db.query(InfraFinding)
    if not include_resolved:
        q = q.filter(InfraFinding.active.is_(True))
    if category:
        q = q.filter(InfraFinding.category == category)
    if categories:
        q = q.filter(InfraFinding.category.in_(list(categories)))
    if platform:
        q = q.filter(InfraFinding.platform == platform)
    if platforms:
        q = q.filter(InfraFinding.platform.in_(list(platforms)))
    if source_id is not None:
        q = q.filter(InfraFinding.source_id == source_id)
    if cluster:
        q = q.filter(InfraFinding.cluster_name == cluster)
    if result and result != "all":
        q = q.filter(InfraFinding.result == result)
    if check_id:
        q = q.filter(InfraFinding.check_id == check_id)
    if entity:
        like = f"%{entity.strip()}%"
        q = q.filter(or_(InfraFinding.entity_name.ilike(like), InfraFinding.entity_ref.ilike(like)))
    rows = q.order_by(InfraFinding.last_seen.desc()).limit(max(1, min(int(limit or 1000), 5000))).all()
    exc = exception_keys(db)
    max_rank = SEVERITY_RANK.get(severity_min or "", None)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if max_rank is not None and SEVERITY_RANK.get(r.severity, 9) > max_rank:
            continue
        ex = exc.get((r.platform, r.source_id, r.entity_ref, r.check_id))
        if ex and not include_excepted:
            continue
        out.append(finding_to_dict(r, ex, locale=locale))
    out.sort(key=lambda f: (
        {"fail": 0, "not_measurable": 1, "pass": 2}.get(f["result"], 3),
        SEVERITY_RANK.get(f["severity"], 9),
        f.get("cluster_name") or "", f.get("entity_name") or "",
    ))
    return out


def summarize_findings(db: Session, *, platforms: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Kategori × önem sayımı (istisnalı bulgular hariç)."""
    q = db.query(InfraFinding).filter(InfraFinding.active.is_(True))
    if platforms:
        q = q.filter(InfraFinding.platform.in_(list(platforms)))
    exc = exception_keys(db)
    by_cat: Dict[str, Dict[str, int]] = {}
    excepted = 0
    not_measurable = 0
    passed = 0
    last_seen: Optional[datetime] = None
    for r in q.all():
        if (r.platform, r.source_id, r.entity_ref, r.check_id) in exc:
            excepted += 1
            continue
        if r.last_seen and (last_seen is None or _aware(r.last_seen) > _aware(last_seen)):
            last_seen = r.last_seen
        if r.result == "not_measurable":
            not_measurable += 1
            continue
        if r.result == "pass":
            passed += 1
            continue
        c = by_cat.setdefault(r.category, {"total": 0})
        c["total"] += 1
        c[r.severity] = c.get(r.severity, 0) + 1
    return {
        "by_category": by_cat,
        "excepted": excepted,
        "not_measurable": not_measurable,
        "passed": passed,
        "as_of": last_seen.isoformat() if last_seen else None,
    }


# ── Config snapshot ──────────────────────────────────────────────────────────

def payload_hash(config: Any) -> str:
    raw = json.dumps(config, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_config_snapshot(
    db: Session,
    *,
    platform: str,
    source_id: Optional[int],
    entity_kind: str,
    entity_ref: str,
    entity_name: str,
    cluster_name: Optional[str],
    config: Dict[str, Any],
    state: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> VirtConfigSnapshot:
    """`config` değişince yeni satır; `state` (bağlantı, bakım…) hash'e girmez.

    state içindeki her anahtar için `<anahtar>_since` korunur: değer değişmediyse
    ilk görüldüğü an saklanır (ör. "host 9 gündür bakımda").
    """
    now = now or utcnow()
    config = _json_safe(config or {})
    state = _json_safe(state or {})
    h = payload_hash(config)
    latest = (
        db.query(VirtConfigSnapshot)
        .filter(
            VirtConfigSnapshot.platform == platform,
            VirtConfigSnapshot.source_id == source_id,
            VirtConfigSnapshot.entity_kind == entity_kind,
            VirtConfigSnapshot.entity_ref == entity_ref[:512],
            VirtConfigSnapshot.is_latest.is_(True),
        )
        .order_by(VirtConfigSnapshot.captured_at.desc())
        .first()
    )
    prev_state = ((latest.payload or {}).get("state") or {}) if latest else {}
    since = dict(prev_state.get("_since") or {})
    for k, v in state.items():
        if k.startswith("_"):
            continue
        if latest is None or k not in prev_state or prev_state.get(k) != v or k not in since:
            since[k] = now.isoformat()
    state["_since"] = since
    payload = {"config": config, "state": state}

    if latest and latest.payload_hash == h:
        latest.payload = payload
        latest.last_seen_at = now
        latest.entity_name = entity_name
        latest.cluster_name = cluster_name
        return latest
    if latest:
        latest.is_latest = False
    row = VirtConfigSnapshot(
        platform=platform, source_id=source_id, entity_kind=entity_kind,
        entity_ref=entity_ref[:512], entity_name=entity_name, cluster_name=cluster_name,
        payload=payload, payload_hash=h, captured_at=now, last_seen_at=now,
        is_latest=True, is_baseline=False,
    )
    db.add(row)
    db.flush()
    return row


def latest_snapshots(
    db: Session,
    *,
    platform: Optional[str] = None,
    source_id: Optional[int] = None,
    entity_kind: Optional[str] = None,
) -> List[VirtConfigSnapshot]:
    q = db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.is_latest.is_(True))
    if platform:
        q = q.filter(VirtConfigSnapshot.platform == platform)
    if source_id is not None:
        q = q.filter(VirtConfigSnapshot.source_id == source_id)
    if entity_kind:
        q = q.filter(VirtConfigSnapshot.entity_kind == entity_kind)
    return q.all()


def state_since(snap: VirtConfigSnapshot, key: str) -> Optional[datetime]:
    raw = (((snap.payload or {}).get("state") or {}).get("_since") or {}).get(key)
    if not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(str(raw)))
    except ValueError:
        return None
