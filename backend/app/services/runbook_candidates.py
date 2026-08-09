"""Resolved incident → onay bekleyen runbook adayı (Chroma'ya otomatik yazılmaz)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _build_content(incident) -> str:
    parts = [
        f"# {incident.title or 'Incident'}",
        "",
    ]
    if incident.description:
        parts += ["## Açıklama", incident.description.strip(), ""]
    if incident.root_cause:
        parts += ["## Kök neden", incident.root_cause.strip(), ""]
    if incident.resolution:
        parts += ["## Çözüm", incident.resolution.strip(), ""]
    if incident.rca_result and not (incident.root_cause or "").strip():
        parts += ["## RCA", str(incident.rca_result).strip()[:4000], ""]
    parts += [
        f"Severity: {incident.severity or '-'}",
        f"Incident ID: {incident.id}",
    ]
    return "\n".join(parts).strip()


def maybe_create_runbook_candidate(db: Session, incident) -> Optional[Dict[str, Any]]:
    """resolved/closed + (resolution veya root_cause) → pending candidate.

    Aynı incident için zaten pending varsa güncellemez (idempotent skip).
    Chroma'ya yazmaz — admin onayında ingest_runbook_append çağrılır.
    """
    if not incident:
        return None
    status = (incident.status or "").lower()
    if status not in ("resolved", "closed"):
        return None
    resolution = (incident.resolution or "").strip()
    root = (incident.root_cause or "").strip()
    if len(resolution) < 20 and len(root) < 20:
        return None

    try:
        from app.models.runbook_candidate import RunbookCandidate

        existing = (
            db.query(RunbookCandidate)
            .filter(
                RunbookCandidate.incident_id == incident.id,
                RunbookCandidate.status == "pending",
            )
            .first()
        )
        if existing:
            return existing.to_dict()

        title = f"Incident #{incident.id}: {(incident.title or 'Çözüm')[:120]}"
        row = RunbookCandidate(
            incident_id=incident.id,
            title=title,
            content=_build_content(incident),
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Runbook candidate oluşturuldu incident=%s id=%s", incident.id, row.id)
        return row.to_dict()
    except Exception as e:
        logger.warning("Runbook candidate oluşturulamadı: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def approve_candidate(db: Session, candidate_id: int, username: str = "") -> Dict[str, Any]:
    from app.models.runbook_candidate import RunbookCandidate

    row = db.query(RunbookCandidate).filter(RunbookCandidate.id == candidate_id).first()
    if not row:
        raise ValueError("Aday bulunamadı")
    if row.status != "pending":
        raise ValueError(f"Aday zaten {row.status}")
    row.status = "approved"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = (username or "")[:120] or None
    db.commit()
    return row.to_dict()


def reject_candidate(db: Session, candidate_id: int, username: str = "") -> Dict[str, Any]:
    from app.models.runbook_candidate import RunbookCandidate

    row = db.query(RunbookCandidate).filter(RunbookCandidate.id == candidate_id).first()
    if not row:
        raise ValueError("Aday bulunamadı")
    if row.status != "pending":
        raise ValueError(f"Aday zaten {row.status}")
    row.status = "rejected"
    row.decided_at = datetime.now(timezone.utc)
    row.decided_by = (username or "")[:120] or None
    db.commit()
    return row.to_dict()
