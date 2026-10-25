"""Kilitli yönetici raporu.

Sayfa açılışı hesaplamaz. Üretim zamanlanmış işte veya «Şimdi yenile» ile
arka planda çalışır ve status=locked satırı yazar.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.infrastructure_report import InfrastructureReport
from app.services.exec_facts import build_executive_facts, save_monthly_snapshot
from app.services.exec_summary_text import compose_summary
from app.services.exec_view import build_view, demo_cards

logger = logging.getLogger(__name__)

BUNDLE = "executive_bundle"
_LOCK = 867530901
_STALE = timedelta(minutes=30)


def current_month(now: Optional[datetime] = None):
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def latest_locked(db: Session) -> Optional[InfrastructureReport]:
    return (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == BUNDLE, InfrastructureReport.status == "locked")
        .order_by(InfrastructureReport.generated_at.desc(), InfrastructureReport.id.desc())
        .first()
    )


def refresh_running(db: Session) -> bool:
    cutoff = datetime.now(timezone.utc) - _STALE
    row = (
        db.query(InfrastructureReport.id)
        .filter(
            InfrastructureReport.report_type == BUNDLE,
            InfrastructureReport.status == "generating",
            InfrastructureReport.generated_at >= cutoff,
        )
        .first()
    )
    return row is not None


def lock_elapsed_month(db: Session, now: Optional[datetime] = None) -> Optional[int]:
    """Ay döndüyse önceki ayın son kilitli paketini executive_monthly yapar."""
    start, _end = current_month(now)
    boundary = start.isoformat()
    bundles = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == BUNDLE, InfrastructureReport.status == "locked")
        .order_by(InfrastructureReport.generated_at.desc(), InfrastructureReport.id.desc())
        .all()
    )
    chosen = None
    for row in bundles:
        raw = str(((row.data or {}).get("period") or {}).get("start") or "")
        if raw and raw < boundary:
            chosen = row
            break
    if chosen is None:
        return None
    period = (chosen.data or {}).get("period") or {}
    key = str(period.get("start") or "")[:10]
    existing = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == "executive_monthly", InfrastructureReport.status == "locked")
        .all()
    )
    for row in existing:
        if str(((row.data or {}).get("period") or {}).get("start") or "")[:10] == key:
            return None
    snap = save_monthly_snapshot(db, (chosen.data or {}).get("facts"), chosen.summary, period=period)
    return snap.id


def produce_bundle(db: Session, now: Optional[datetime] = None) -> Optional[int]:
    """Kilidi alır, mevcut ayın gerçeklerini kilitler. Kilit doluysa None."""
    locked = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK}).scalar()
    if not locked:
        return None
    try:
        lock_elapsed_month(db, now)
        start, end = current_month(now)
        facts = build_executive_facts(db, start, end)
        summary = compose_summary(facts)
        view = build_view(db, facts, summary)
        row = InfrastructureReport(
            report_type=BUNDLE,
            report_title="Yönetici raporları",
            data={
                "locked": True,
                "period": {"start": start.isoformat(), "end": end.isoformat()},
                "facts": facts,
                "summary_source": summary["source"],
                "view": view,
            },
            summary=summary["text"],
            status="locked",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception:
        db.rollback()
        raise
    finally:
        try:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK})
            db.commit()
        except Exception:
            logger.exception("executive bundle lock bırakılamadı")


def _row_for_month(db: Session, month: Optional[str]) -> Optional[InfrastructureReport]:
    if not month:
        return latest_locked(db)
    monthly = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == "executive_monthly", InfrastructureReport.status == "locked")
        .order_by(InfrastructureReport.generated_at.desc())
        .all()
    )
    for row in monthly:
        if str(((row.data or {}).get("period") or {}).get("start") or "").startswith(month):
            return row
    current = latest_locked(db)
    if current and str(((current.data or {}).get("period") or {}).get("start") or "").startswith(month):
        return current
    return None


def available_months(db: Session) -> List[str]:
    found: List[str] = []
    rows = (
        db.query(InfrastructureReport)
        .filter(
            InfrastructureReport.report_type.in_([BUNDLE, "executive_monthly"]),
            InfrastructureReport.status == "locked",
        )
        .order_by(InfrastructureReport.generated_at.desc())
        .all()
    )
    for row in rows:
        label = str(((row.data or {}).get("period") or {}).get("start") or "")[:7]
        if len(label) == 7 and label not in found:
            found.append(label)
    return found


def bundle_payload(db: Session, month: Optional[str] = None) -> Dict[str, Any]:
    row = _row_for_month(db, month)
    running = refresh_running(db)
    if row is None:
        return {
            "reports": [],
            "generated_at": None,
            "status": "empty",
            "refreshing": running,
            "period": None,
            "months": available_months(db),
            "demo_cards": demo_cards(db),
        }
    data = row.data or {}
    generated = row.generated_at.isoformat() if row.generated_at else None
    return {
        "reports": data.get("facts") or [],
        "generated_at": generated,
        "status": "ready",
        "refreshing": running,
        "period": data.get("period"),
        "months": available_months(db),
        "report_id": row.id,
        "summary": row.summary,
        "summary_source": data.get("summary_source"),
        "view": data.get("view"),
        "demo_cards": demo_cards(db),
    }


def start_refresh() -> Dict[str, Any]:
    """Arka plan üretimi. İstek iş parçacığı hesaplamaz."""
    db = SessionLocal()
    try:
        if refresh_running(db):
            return {"started": False, "detail": "Üretim sürüyor"}
        marker = InfrastructureReport(
            report_type=BUNDLE,
            report_title="Yönetici raporları",
            data={"locked": False},
            status="generating",
        )
        db.add(marker)
        db.commit()
        marker_id = marker.id
    finally:
        db.close()

    def work() -> None:
        db2 = SessionLocal()
        try:
            produce_bundle(db2)
            marker_row = db2.get(InfrastructureReport, marker_id)
            if marker_row is not None and marker_row.status == "generating":
                marker_row.status = "superseded"
                db2.commit()
        except Exception:
            logger.exception("executive bundle üretilemedi")
            db2.rollback()
            marker_row = db2.get(InfrastructureReport, marker_id)
            if marker_row is not None:
                marker_row.status = "error"
                db2.commit()
        finally:
            db2.close()

    threading.Thread(target=work, daemon=True, name="exec-report").start()
    return {"started": True}
