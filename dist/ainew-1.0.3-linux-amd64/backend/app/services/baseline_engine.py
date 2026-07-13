"""
Baseline Engine — Sunucu başına normal davranış öğrenir ve alarm bastırır.

Üç katmanlı filtre:

  1. SUPPRESSION CHECK
     AnomalySuppression tablosuna bak: bu sunucu + metrik için aktif kural var mı?
     → suppress=True  → event hiç oluşturma
     → baseline_severity="info"/"warning" → severity kapat

  2. RECURRENCE DOWNGRADE
     Aynı (server, metric/title) son 3+ gündür sürekli tetikleniyorsa severity düşür.
     critical → warning  (3-7 gün tekrar)
     warning  → info     (7+ gün tekrar)

  3. PER-SERVER Z-SCORE
     baseline_metrics tablosundaki sunucuya özgü mean/std ile Z-score hesapla.
     Global eşik yerine sunucunun kendi normali kullanılır.

Dönüş:
  {
    "suppress": bool,                # True ise event oluşturma
    "effective_severity": str,       # ayarlanmış severity
    "downgrade_reason": str | None,  # neden düşürüldü
    "rule_id": int | None,           # hangi suppression kuralı uygulandı
  }
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.event import SystemEvent, AnomalySuppression, BaselineMetric

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2, "emergency": 3}
RANK_TO_SEV = {v: k for k, v in SEVERITY_RANK.items()}

# Kaç gün tekrardan sonra severity düşürülür
DOWNGRADE_AFTER_DAYS = 3
SUPPRESS_AFTER_DAYS = 7

# Tekrar sayısı: son N günde kaç farklı gün tetiklendi
RECURRENCE_WINDOW_DAYS = 14


# ── 1) Suppression kuralı kontrolü ───────────────────────────────────────────

def check_suppression(
    db: Session,
    server_id: Optional[int],
    metric_name: str,
    now: Optional[datetime] = None,
) -> Optional[AnomalySuppression]:
    """
    Aktif ve süresi dolmamış bir suppression kuralı döndürür.
    Önce sunucuya özgü, yoksa global kural aranır.
    """
    now = now or datetime.utcnow()
    base = (
        db.query(AnomalySuppression)
        .filter(
            AnomalySuppression.metric_name == metric_name,
            AnomalySuppression.active == True,
            (AnomalySuppression.expires_at == None) | (AnomalySuppression.expires_at > now),
        )
    )

    # Sunucuya özgü kural önce
    if server_id:
        rule = base.filter(
            AnomalySuppression.server_id == server_id,
            AnomalySuppression.scope == "server",
        ).first()
        if rule:
            return rule

    # Global kural fallback
    return base.filter(AnomalySuppression.scope == "global").first()


# ── 2) Recurrence kontrolü ────────────────────────────────────────────────────

def check_recurrence(
    db: Session,
    server_id: Optional[int],
    metric_name: str,
    event_type: str = "metric_anomaly",
    window_days: int = RECURRENCE_WINDOW_DAYS,
) -> Dict[str, Any]:
    """
    Son window_days içinde bu metrik/sunucu kombinasyonu kaç farklı günde tetiklendi?

    Returns:
      {
        "recurrence_days": int,  # kaç farklı günde görüldü
        "total_count": int,      # toplam event sayısı
        "is_chronic": bool,      # 3+ gündür sürüyor mu
        "is_very_chronic": bool, # 7+ gündür sürüyor mu
      }
    """
    since = datetime.utcnow() - timedelta(days=window_days)

    query = db.query(SystemEvent).filter(
        SystemEvent.event_type == event_type,
        SystemEvent.created_at >= since,
    )
    if server_id:
        query = query.filter(SystemEvent.server_id == server_id)

    # metric_name title içinde geçiyor (aiops_engine başlıklara metrik adı koyuyor)
    query = query.filter(SystemEvent.title.ilike(f"%{metric_name}%"))

    events = query.all()
    total = len(events)

    # Kaç farklı gün görüldü
    days_seen = set()
    for ev in events:
        ts = ev.created_at or ev.last_seen
        if ts:
            days_seen.add(ts.date())

    recurrence_days = len(days_seen)

    return {
        "recurrence_days": recurrence_days,
        "total_count": total,
        "is_chronic": recurrence_days >= DOWNGRADE_AFTER_DAYS,
        "is_very_chronic": recurrence_days >= SUPPRESS_AFTER_DAYS,
    }


# ── 3) Per-server Z-score ─────────────────────────────────────────────────────

def get_server_baseline(
    db: Session,
    server_id: int,
    metric_name: str,
) -> Optional[BaselineMetric]:
    """En güncel baseline_metrics kaydını döndürür."""
    return (
        db.query(BaselineMetric)
        .filter(
            BaselineMetric.server_id == server_id,
            BaselineMetric.metric_name == metric_name,
        )
        .order_by(BaselineMetric.calculated_at.desc())
        .first()
    )


def compute_per_server_z_score(
    baseline: BaselineMetric,
    current_value: float,
) -> Optional[float]:
    """Sunucunun kendi mean/std'si ile Z-score hesaplar."""
    if not baseline or not baseline.std_dev or baseline.std_dev == 0:
        return None
    return (current_value - (baseline.avg_value or 0)) / baseline.std_dev


def update_baseline_from_event(
    db: Session,
    server_id: int,
    metric_name: str,
    current_value: float,
    period: str = "rolling_7d",
):
    """
    Basit online güncelleme: mevcut baseline'a yeni değeri katar.
    Gerçek rolling window için ayrı bir cron job kullanılmalı.
    """
    bm = get_server_baseline(db, server_id, metric_name)
    if not bm:
        bm = BaselineMetric(
            server_id=server_id,
            metric_name=metric_name,
            avg_value=current_value,
            min_value=current_value,
            max_value=current_value,
            std_dev=0.0,
            sample_count=1,
            period=period,
        )
        db.add(bm)
    else:
        n = (bm.sample_count or 1)
        new_n = n + 1
        old_avg = bm.avg_value or 0.0
        new_avg = old_avg + (current_value - old_avg) / new_n
        # Welford online variance
        old_std = bm.std_dev or 0.0
        old_var = old_std ** 2
        new_var = old_var + ((current_value - old_avg) * (current_value - new_avg) - old_var) / new_n
        bm.avg_value = new_avg
        bm.std_dev = max(0.0, new_var) ** 0.5
        bm.min_value = min(bm.min_value or current_value, current_value)
        bm.max_value = max(bm.max_value or current_value, current_value)
        bm.sample_count = new_n
        bm.calculated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def apply_baseline_filter(
    db: Session,
    server_id: Optional[int],
    metric_name: str,
    severity: str,
    event_type: str = "metric_anomaly",
    current_value: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Gelen alarma üç katmanlı baseline filtresi uygular.

    Returns:
      {
        "suppress": bool,
        "effective_severity": str,
        "downgrade_reason": str | None,
        "rule_id": int | None,
        "recurrence": dict,
      }
    """
    result = {
        "suppress": False,
        "effective_severity": severity,
        "downgrade_reason": None,
        "rule_id": None,
        "recurrence": {},
    }

    # ── Katman 1: Suppression kuralı ────────────────────────────────────────
    rule = check_suppression(db, server_id, metric_name)
    if rule:
        result["rule_id"] = rule.id
        if rule.baseline_severity is None:
            # Tamamen bastır
            result["suppress"] = True
            result["downgrade_reason"] = f"Suppression kuralı #{rule.id}: {rule.reason or 'Sunucu için normal'}"
            logger.debug(
                f"[Baseline] SUPPRESS: server={server_id} metric={metric_name} rule={rule.id}"
            )
            return result
        else:
            # Severity kapat
            rule_rank = SEVERITY_RANK.get(rule.baseline_severity, 0)
            current_rank = SEVERITY_RANK.get(severity, 0)
            if current_rank > rule_rank:
                result["effective_severity"] = rule.baseline_severity
                result["downgrade_reason"] = (
                    f"Suppression kuralı #{rule.id}: max {rule.baseline_severity} "
                    f"({rule.reason or 'sunucu için normal'})"
                )
                logger.debug(
                    f"[Baseline] DOWNGRADE (rule): {severity}→{rule.baseline_severity} "
                    f"server={server_id} metric={metric_name}"
                )

    # ── Katman 2: Recurrence ────────────────────────────────────────────────
    recurrence = check_recurrence(db, server_id, metric_name, event_type)
    result["recurrence"] = recurrence

    if not result["suppress"]:
        current_eff = result["effective_severity"]
        current_rank = SEVERITY_RANK.get(current_eff, 0)

        if recurrence["is_very_chronic"]:
            # 7+ gün: maksimum warning'e düşür
            target_rank = min(current_rank, SEVERITY_RANK["warning"])
            target_sev = RANK_TO_SEV[target_rank]
            if target_sev != current_eff:
                result["effective_severity"] = target_sev
                result["downgrade_reason"] = (
                    f"Kronik alarm ({recurrence['recurrence_days']} gündür tekrar ediyor): "
                    f"{current_eff}→{target_sev}"
                )
                logger.info(
                    f"[Baseline] CHRONIC DOWNGRADE: {current_eff}→{target_sev} "
                    f"server={server_id} metric={metric_name} days={recurrence['recurrence_days']}"
                )

        elif recurrence["is_chronic"]:
            # 3-7 gün: critical → warning
            if current_eff == "critical":
                result["effective_severity"] = "warning"
                result["downgrade_reason"] = (
                    f"Tekrar eden alarm ({recurrence['recurrence_days']} gündür): "
                    f"critical→warning"
                )
                logger.info(
                    f"[Baseline] RECURRENCE DOWNGRADE: critical→warning "
                    f"server={server_id} metric={metric_name}"
                )

    # ── Katman 3: Per-server Z-score (sadece loglama + baseline güncelleme) ──
    if server_id and current_value is not None:
        baseline = get_server_baseline(db, server_id, metric_name)
        if baseline and baseline.std_dev:
            z = compute_per_server_z_score(baseline, current_value)
            if z is not None and z < 2.0 and not result["suppress"]:
                # Sunucunun kendi normali içinde → bilgi olarak sakla ama suppress önermesi
                logger.debug(
                    f"[Baseline] Per-server Z={z:.2f} < 2.0: "
                    f"server={server_id} metric={metric_name} val={current_value}"
                )
                if not result["downgrade_reason"]:
                    result["effective_severity"] = min(
                        result["effective_severity"],
                        "warning",
                        key=lambda s: SEVERITY_RANK.get(s, 0),
                    )
                    result["downgrade_reason"] = (
                        f"Per-server Z-score {z:.2f} < 2.0 (sunucu normali içinde)"
                    )

        # Baseline'ı online güncelle
        if baseline or True:
            update_baseline_from_event(db, server_id, metric_name, current_value)

    return result


# ── Suppression kural yönetimi ────────────────────────────────────────────────

def create_suppression_rule(
    db: Session,
    server_id: Optional[int],
    metric_name: str,
    reason: str = "",
    created_by: str = "system",
    baseline_severity: Optional[str] = None,  # None = tamamen bastır
    baseline_value: Optional[float] = None,
    scope: str = "server",
    expires_at: Optional[datetime] = None,
) -> AnomalySuppression:
    """Yeni bir bastırma kuralı oluşturur. Varsa günceller."""
    existing = (
        db.query(AnomalySuppression)
        .filter(
            AnomalySuppression.server_id == server_id,
            AnomalySuppression.metric_name == metric_name,
            AnomalySuppression.scope == scope,
        )
        .first()
    )
    if existing:
        existing.reason = reason or existing.reason
        existing.baseline_severity = baseline_severity
        existing.baseline_value = baseline_value
        existing.active = True
        existing.expires_at = expires_at
        db.commit()
        db.refresh(existing)
        return existing

    rule = AnomalySuppression(
        server_id=server_id,
        metric_name=metric_name,
        scope=scope,
        reason=reason,
        created_by=created_by,
        baseline_severity=baseline_severity,
        baseline_value=baseline_value,
        active=True,
        expires_at=expires_at,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    logger.info(
        f"[Baseline] Suppression kuralı oluşturuldu: "
        f"server={server_id} metric={metric_name} severity_cap={baseline_severity}"
    )
    return rule


def list_suppression_rules(
    db: Session,
    server_id: Optional[int] = None,
    active_only: bool = True,
) -> List[AnomalySuppression]:
    q = db.query(AnomalySuppression)
    if active_only:
        q = q.filter(AnomalySuppression.active == True)
    if server_id is not None:
        q = q.filter(AnomalySuppression.server_id == server_id)
    return q.order_by(AnomalySuppression.created_at.desc()).all()


def delete_suppression_rule(db: Session, rule_id: int) -> bool:
    rule = db.query(AnomalySuppression).filter(AnomalySuppression.id == rule_id).first()
    if not rule:
        return False
    rule.active = False
    db.commit()
    return True
