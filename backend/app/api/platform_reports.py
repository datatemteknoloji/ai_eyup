"""Modül bazlı altyapı raporları — Linux, Windows, Exadata."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.platform_report_engine import (
    PLATFORM_CATALOG,
    REPORT_TITLES,
    format_platform_report_markdown,
    generate_platform_report,
    get_latest_platform_report,
)

router = APIRouter()

VALID = frozenset({"linux", "windows", "exadata"})


class ReportRequest(BaseModel):
    report_type: str
    save: bool = True


def _check_platform(platform: str) -> str:
    p = platform.lower()
    if p not in VALID:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen platform: {platform}")
    return p


@router.get("/{platform}/catalog")
async def report_catalog(platform: str):
    p = _check_platform(platform)
    types = PLATFORM_CATALOG.get(p, [])
    return {
        "platform": p,
        "report_types": [
            {"type": t, "title": REPORT_TITLES.get(t, t), "available": True}
            for t in types
        ],
    }


@router.post("/{platform}/generate")
async def generate_report(platform: str, req: ReportRequest, db: Session = Depends(get_db)):
    p = _check_platform(platform)
    if req.report_type not in PLATFORM_CATALOG.get(p, []):
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {req.report_type}")
    try:
        data = generate_platform_report(db, p, req.report_type, save=req.save)
        md = format_platform_report_markdown(p, req.report_type, data)
        return {"success": True, "data": data, "markdown": md}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{platform}/latest/{report_type}")
async def get_latest_report(platform: str, report_type: str, db: Session = Depends(get_db)):
    p = _check_platform(platform)
    if report_type not in PLATFORM_CATALOG.get(p, []):
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {report_type}")

    cached = get_latest_platform_report(db, p, report_type)
    if cached:
        md = format_platform_report_markdown(p, report_type, cached)
        return {"source": "cache", "data": cached, "markdown": md}

    data = generate_platform_report(db, p, report_type, save=True)
    md = format_platform_report_markdown(p, report_type, data)
    return {"source": "fresh", "data": data, "markdown": md}


@router.get("/{platform}/history")
async def report_history(platform: str, limit: int = 20, db: Session = Depends(get_db)):
    from app.models.infrastructure_report import InfrastructureReport

    p = _check_platform(platform)
    prefix = f"{p}:"
    rows = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type.like(f"{prefix}%"))
        .order_by(InfrastructureReport.generated_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "platform": p,
        "reports": [
            {
                "id": r.id,
                "type": r.report_type.split(":", 1)[-1] if ":" in r.report_type else r.report_type,
                "title": r.report_title,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "status": r.status,
            }
            for r in rows
        ],
    }
