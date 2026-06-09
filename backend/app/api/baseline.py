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

    # Mevcut event'i bilinen olarak işaretle (listeden kaldır)
    event.is_known = True
    event.known_at = datetime.utcnow()
    event.known_by = "suppression_rule"

    # Aynı sunucu + metrik için açık diğer eventleri de kapat
    from app.models.event import SystemEvent as SE
    sibling_events = (
        db.query(SE)
        .filter(
            SE.server_id == event.server_id,
            SE.resolved == False,  # noqa: E712
            SE.is_known == False,  # noqa: E712
            SE.id != event_id,
        )
        .all()
    )
    for sib in sibling_events:
        sib_metric = (sib.raw_data or {}).get("metric") or sib.title[:200]
        if sib_metric == metric_name:
            sib.is_known = True
            sib.known_at = datetime.utcnow()
            sib.known_by = "suppression_rule"

    db.commit()

    logger.info(
        f"[Baseline API] from-event: event={event_id} metric={metric_name} "
        f"server={event.server_id} cap={baseline_severity} "
        f"siblings_closed={len([s for s in sibling_events if s.is_known])}"
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


@router.get("/correlation")
async def correlation_view(
    server_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Anomali tespiti + tekrarlayan alarm + suppression kuralı korelasyonu.

    Her satır bir metric_name etrafında şunları birleştirir:
      - Şu an aktif anomali var mı?
      - Kaç gündür tekrar ediyor?
      - Aktif suppression kuralı var mı?
      - Son event severity'si nedir?
    """
    from datetime import datetime, timedelta
    from collections import defaultdict

    now = datetime.utcnow()
    window = timedelta(days=14)
    since = now - window

    # Tüm metric_anomaly event'leri (son 14 gün)
    q = db.query(SystemEvent).filter(
        SystemEvent.event_type == "metric_anomaly",
        SystemEvent.created_at >= since,
    )
    if server_id:
        q = q.filter(SystemEvent.server_id == server_id)

    events = q.order_by(SystemEvent.created_at.desc()).all()

    # metric_name bazında grupla
    metric_data: dict = defaultdict(lambda: {
        "metric": "",
        "servers": set(),
        "days_seen": set(),
        "total_count": 0,
        "max_severity": "info",
        "last_seen": None,
        "last_event_id": None,
        "last_server_id": None,
        "last_server_name": None,
        "suppression_rule": None,
        "occurrence_counts": [],
    })

    sev_rank = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}

    for ev in events:
        metric = (ev.raw_data or {}).get("metric") or ev.title[:100]
        d = metric_data[metric]
        d["metric"] = metric
        if ev.server_id:
            d["servers"].add(ev.server_id)
        ts = ev.created_at or ev.last_seen
        if ts:
            d["days_seen"].add(ts.date())
            if d["last_seen"] is None or ts > d["last_seen"]:
                d["last_seen"] = ts
                d["last_event_id"] = ev.id
                d["last_server_id"] = ev.server_id
                d["last_server_name"] = getattr(ev.server, "name", None) if ev.server_id else None
        d["total_count"] += 1
        if sev_rank.get(ev.severity, 0) > sev_rank.get(d["max_severity"], 0):
            d["max_severity"] = ev.severity
        if ev.occurrence_count:
            d["occurrence_counts"].append(ev.occurrence_count)

    # Suppression kurallarını çek
    rules_q = db.query(AnomalySuppression).filter(AnomalySuppression.active == True)
    if server_id:
        rules_q = rules_q.filter(
            (AnomalySuppression.server_id == server_id) | (AnomalySuppression.scope == "global")
        )
    rules = {r.metric_name: r for r in rules_q.all()}

    result = []
    for metric, d in metric_data.items():
        recurrence_days = len(d["days_seen"])
        rule = rules.get(metric)
        result.append({
            "metric": metric,
            "recurrence_days": recurrence_days,
            "total_count": d["total_count"],
            "max_severity": d["max_severity"],
            "last_seen": d["last_seen"].isoformat() if d["last_seen"] else None,
            "last_event_id": d["last_event_id"],
            "last_server_id": d["last_server_id"],
            "server_count": len(d["servers"]),
            "is_chronic": recurrence_days >= 3,
            "is_very_chronic": recurrence_days >= 7,
            "suppression": {
                "id": rule.id,
                "active": True,
                "baseline_severity": rule.baseline_severity,
                "reason": rule.reason,
                "scope": rule.scope,
            } if rule else None,
            "effective_severity": rule.baseline_severity if rule and rule.baseline_severity else (
                "warning" if recurrence_days >= 7 and d["max_severity"] == "critical" else d["max_severity"]
            ),
            "is_suppressed": rule is not None and rule.baseline_severity is None,
            "is_downgraded": (
                (rule is not None and rule.baseline_severity is not None) or
                recurrence_days >= 3
            ),
        })

    result.sort(key=lambda x: (x["recurrence_days"], sev_rank.get(x["max_severity"], 0)), reverse=True)
    return {
        "server_id": server_id,
        "window_days": 14,
        "total_metrics": len(result),
        "chronic_count": sum(1 for r in result if r["is_chronic"]),
        "suppressed_count": sum(1 for r in result if r["is_suppressed"]),
        "downgraded_count": sum(1 for r in result if r["is_downgraded"] and not r["is_suppressed"]),
        "metrics": result,
    }


@router.get("/digest")
async def daily_digest(
    date: Optional[str] = None,  # ISO tarih: 2026-06-09
    db: Session = Depends(get_db),
):
    """
    Günlük alarm özeti.
    date belirtilmezse bugün kullanılır.
    """
    from app.services.storm_detector import generate_daily_digest
    import datetime as dt

    target = None
    if date:
        try:
            target = dt.datetime.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz tarih formatı (YYYY-MM-DD bekleniyor)")

    return generate_daily_digest(db, target)


class TierUpdate(BaseModel):
    tier: str


@router.patch("/servers/{server_id}/tier")
async def set_server_tier(
    server_id: int,
    body: TierUpdate,
    db: Session = Depends(get_db),
):
    tier = body.tier
    """
    Sunucu tier'ını ayarlar: production | staging | development | unknown.
    Tier, alarm severity filtrelemesini etkiler:
      production  → tüm severity geçer
      staging     → max warning
      development → max info
    """
    from app.models.server import Server
    valid = ("production", "staging", "development", "unknown")
    if tier not in valid:
        raise HTTPException(status_code=400, detail=f"Geçerli tier: {', '.join(valid)}")

    from app.models.server import Server
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadı")

    server.tier = tier  # type: ignore[attr-defined]
    db.commit()
    logger.info(f"[Baseline] Server #{server_id} tier={tier}")
    return {"server_id": server_id, "tier": tier, "ok": True}


@router.get("/servers/tiers")
async def list_server_tiers(db: Session = Depends(get_db)):
    """Tüm sunucuların tier bilgisini listeler."""
    from app.models.server import Server
    servers = db.query(Server).order_by(Server.name).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "tier": getattr(s, "tier", "unknown") or "unknown",
        }
        for s in servers
    ]


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
