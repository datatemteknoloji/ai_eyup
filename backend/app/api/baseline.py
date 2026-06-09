"""
Baseline API — Suppression kuralları + per-server baseline yönetimi.

Endpoint'ler:
  GET    /baseline/suppressions                 — kural listesi
  POST   /baseline/suppressions                 — yeni kural oluştur
  DELETE /baseline/suppressions/{id}            — kuralı devre dışı bırak
  POST   /baseline/suppressions/from-event/{id} — event'ten otomatik kural
  GET    /baseline/recurrence/{server_id}       — sunucunun tekrarlayan metrikleri
  GET    /baseline/stats/{server_id}            — sunucu baseline istatistikleri
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.event import AnomalySuppression, SystemEvent, BaselineMetric
from app.services.baseline_engine import (
    create_suppression_rule,
    list_suppression_rules,
    delete_suppression_rule,
    check_recurrence,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Şemalar ──────────────────────────────────────────────────────────────────

class SuppressionCreate(BaseModel):
    server_id: Optional[int] = None
    metric_name: str
    reason: str = ""
    baseline_severity: Optional[str] = None  # None=tamamen bastır, 'info', 'warning'
    baseline_value: Optional[float] = None
    scope: str = "server"                    # 'server' | 'global'
    expires_in_days: Optional[int] = None    # None = süresiz


class SuppressionOut(BaseModel):
    id: int
    server_id: Optional[int]
    metric_name: str
    scope: str
    reason: Optional[str]
    baseline_severity: Optional[str]
    baseline_value: Optional[float]
    active: bool
    created_at: Optional[datetime]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Endpoint'ler ─────────────────────────────────────────────────────────────

@router.get("/suppressions", response_model=List[SuppressionOut])
async def get_suppressions(
    server_id: Optional[int] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    """Aktif suppression kurallarını listeler."""
    return list_suppression_rules(db, server_id=server_id, active_only=active_only)


@router.post("/suppressions", response_model=SuppressionOut)
async def create_suppression(
    req: SuppressionCreate,
    db: Session = Depends(get_db),
):
    """
    Yeni suppression kuralı oluşturur.

    baseline_severity=None → event hiç oluşturulmaz (tam bastırma)
    baseline_severity='warning' → en fazla warning olarak oluşturulur
    """
    if req.baseline_severity and req.baseline_severity not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="baseline_severity: info | warning | critical | null")
    if req.scope not in ("server", "global"):
        raise HTTPException(status_code=400, detail="scope: server | global")
    if req.scope == "server" and not req.server_id:
        raise HTTPException(status_code=400, detail="server kapsamı için server_id gerekli")

    expires_at = None
    if req.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=req.expires_in_days)

    rule = create_suppression_rule(
        db=db,
        server_id=req.server_id,
        metric_name=req.metric_name,
        reason=req.reason,
        created_by="api",
        baseline_severity=req.baseline_severity,
        baseline_value=req.baseline_value,
        scope=req.scope,
        expires_at=expires_at,
    )
    return rule


@router.post("/suppressions/from-event/{event_id}", response_model=SuppressionOut)
async def create_suppression_from_event(
    event_id: int,
    baseline_severity: Optional[str] = "warning",
    expires_in_days: Optional[int] = None,
    reason: str = "",
    db: Session = Depends(get_db),
):
    """
    Bir event'i referans alarak suppression kuralı oluşturur.
    'Bu sunucu için normal' butonunun backend endpoint'i.
    """
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")

    # metric_name: raw_data'dan al, yoksa title'dan çıkar
    metric_name = (event.raw_data or {}).get("metric") or event.title[:200]

    expires_at = None
    if expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

    rule = create_suppression_rule(
        db=db,
        server_id=event.server_id,
        metric_name=metric_name,
        reason=reason or f"Event #{event_id} referansıyla oluşturuldu: {event.title[:100]}",
        created_by="ui",
        baseline_severity=baseline_severity,
        baseline_value=(event.raw_data or {}).get("current_value"),
        scope="server",
        expires_at=expires_at,
    )
    logger.info(
        f"[Baseline API] from-event: event={event_id} metric={metric_name} "
        f"server={event.server_id} cap={baseline_severity}"
    )
    return rule


@router.delete("/suppressions/{rule_id}")
async def deactivate_suppression(rule_id: int, db: Session = Depends(get_db)):
    """Suppression kuralını devre dışı bırakır (silmez)."""
    ok = delete_suppression_rule(db, rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Kural bulunamadı")
    return {"ok": True, "rule_id": rule_id}


@router.get("/recurrence/{server_id}")
async def server_recurrence(
    server_id: int,
    window_days: int = 14,
    db: Session = Depends(get_db),
):
    """
    Bu sunucunun son {window_days} gündeki tekrarlayan metriklerini döndürür.
    Her metrik için recurrence_days ve toplam sayıyı gösterir.
    """
    # Bu sunucunun son window_days içindeki metric_anomaly event'lerini grupla
    from sqlalchemy import func as sqlfunc
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=window_days)
    events = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.server_id == server_id,
            SystemEvent.event_type == "metric_anomaly",
            SystemEvent.created_at >= since,
        )
        .all()
    )

    # metric_name bazında grupla
    from collections import defaultdict
    metric_days: dict = defaultdict(set)
    metric_counts: dict = defaultdict(int)
    metric_severity: dict = defaultdict(str)

    for ev in events:
        metric = (ev.raw_data or {}).get("metric") or ev.title[:100]
        ts = ev.created_at or ev.last_seen
        if ts:
            metric_days[metric].add(ts.date())
        metric_counts[metric] += 1
        # En yüksek severity'yi sakla
        sev = ev.severity or "info"
        cur = metric_severity.get(metric, "info")
        sev_rank = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}
        if sev_rank.get(sev, 0) > sev_rank.get(cur, 0):
            metric_severity[metric] = sev

    result = []
    for metric, days in metric_days.items():
        rd = len(days)
        result.append({
            "metric": metric,
            "recurrence_days": rd,
            "total_count": metric_counts[metric],
            "max_severity": metric_severity.get(metric, "info"),
            "is_chronic": rd >= 3,
            "is_very_chronic": rd >= 7,
            "has_suppression": bool(
                db.query(AnomalySuppression)
                .filter(
                    AnomalySuppression.server_id == server_id,
                    AnomalySuppression.metric_name == metric,
                    AnomalySuppression.active == True,
                )
                .first()
            ),
        })

    result.sort(key=lambda x: x["recurrence_days"], reverse=True)
    return {"server_id": server_id, "window_days": window_days, "metrics": result}


@router.get("/stats/{server_id}")
async def server_baseline_stats(server_id: int, db: Session = Depends(get_db)):
    """Per-server baseline istatistiklerini döndürür."""
    baselines = (
        db.query(BaselineMetric)
        .filter(BaselineMetric.server_id == server_id)
        .order_by(BaselineMetric.metric_name)
        .all()
    )
    suppressions = list_suppression_rules(db, server_id=server_id, active_only=True)

    return {
        "server_id": server_id,
        "baselines": [
            {
                "metric_name": b.metric_name,
                "avg_value": b.avg_value,
                "std_dev": b.std_dev,
                "min_value": b.min_value,
                "max_value": b.max_value,
                "sample_count": b.sample_count,
                "period": b.period,
                "calculated_at": b.calculated_at.isoformat() if b.calculated_at else None,
            }
            for b in baselines
        ],
        "suppression_count": len(suppressions),
        "suppressions": [
            {
                "id": s.id,
                "metric_name": s.metric_name,
                "baseline_severity": s.baseline_severity,
                "reason": s.reason,
                "scope": s.scope,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            }
            for s in suppressions
        ],
    }
