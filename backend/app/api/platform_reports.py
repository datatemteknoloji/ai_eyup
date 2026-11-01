"""Modül bazlı altyapı raporları — Linux, Windows, Exadata, OpenShift.

Modül yetkisi `core/module_policy.py` (`/platform-reports/{platform}`) ile uygulanır."""
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.services.platform_report_engine import (
    PLATFORM_CATALOG,
    REPORT_TITLES,
    format_platform_report_markdown,
    generate_platform_report,
    get_latest_platform_report,
)

router = APIRouter()

VALID = frozenset({"linux", "windows", "exadata", "openshift"})


class ReportRequest(BaseModel):
    report_type: str
    save: bool = True
    lang: str = "tr"      # yalnız openshift hazır raporları: "en" → içerik İngilizce


def _lang(lang: str) -> str:
    return "en" if (lang or "").lower().startswith("en") else "tr"


def _check_platform(platform: str) -> str:
    p = platform.lower()
    if p not in VALID:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen platform: {platform}")
    return p


def _types(p: str):
    if p == "openshift":
        from app.services import ocp_report_engine as oe
        return oe.CATALOG
    return PLATFORM_CATALOG.get(p, [])


def _titles(p: str):
    if p == "openshift":
        from app.services import ocp_report_engine as oe
        return oe.REPORT_TITLES
    return REPORT_TITLES


def _ocp_generate(report_type: str, save: bool, lang: str = "tr"):
    """Ayrı iş parçacığı + kendi oturumu (async yolda senkron DB işi yok)."""
    from app.services import ocp_report_engine as oe

    db = SessionLocal()
    try:
        from app.services.report_i18n import translate_report

        data = oe.generate(db, report_type, save=save)
        return translate_report(data, lang), oe.to_markdown(report_type, data, lang)
    finally:
        db.close()


def _ocp_latest(report_type: str, lang: str = "tr"):
    from app.services import ocp_report_engine as oe
    from app.services.report_i18n import translate_report

    db = SessionLocal()
    try:
        cached = oe.get_latest(db, report_type)
        if cached:
            return "cache", translate_report(cached, lang), oe.to_markdown(report_type, cached, lang)
        data = oe.generate(db, report_type, save=True)
        return "fresh", translate_report(data, lang), oe.to_markdown(report_type, data, lang)
    finally:
        db.close()


@router.get("/{platform}/catalog")
async def report_catalog(platform: str, lang: str = "tr", db: Session = Depends(get_db)):
    p = _check_platform(platform)
    titles = _titles(p)
    if p == "openshift" and _lang(lang) == "en":
        from app.services.report_i18n import t as _t

        titles = {k: _t(v, "en") for k, v in titles.items()}
    return {
        "platform": p,
        "report_types": [
            {"type": t, "title": titles.get(t, t), "available": True}
            for t in _types(p)
        ],
    }


@router.post("/{platform}/generate")
async def generate_report(platform: str, req: ReportRequest, db: Session = Depends(get_db)):
    p = _check_platform(platform)
    if req.report_type not in _types(p):
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {req.report_type}")
    try:
        if p == "openshift":
            data, md = await asyncio.to_thread(_ocp_generate, req.report_type, req.save, _lang(req.lang))
            return {"success": True, "data": data, "markdown": md}
        data = generate_platform_report(db, p, req.report_type, save=req.save)
        md = format_platform_report_markdown(p, req.report_type, data)
        return {"success": True, "data": data, "markdown": md}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{platform}/latest/{report_type}")
async def get_latest_report(platform: str, report_type: str, lang: str = "tr", db: Session = Depends(get_db)):
    p = _check_platform(platform)
    if report_type not in _types(p):
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {report_type}")

    if p == "openshift":
        source, data, md = await asyncio.to_thread(_ocp_latest, report_type, _lang(lang))
        return {"source": source, "data": data, "markdown": md}

    cached = get_latest_platform_report(db, p, report_type)
    if cached:
        md = format_platform_report_markdown(p, report_type, cached)
        return {"source": "cache", "data": cached, "markdown": md}

    data = generate_platform_report(db, p, report_type, save=True)
    md = format_platform_report_markdown(p, report_type, data)
    return {"source": "fresh", "data": data, "markdown": md}


def _hist_title(title, p: str, lang: str):
    if p != "openshift" or _lang(lang) != "en":
        return title
    from app.services.report_i18n import t

    return t(title, "en")


@router.get("/{platform}/history")
async def report_history(platform: str, limit: int = 20, lang: str = "tr", db: Session = Depends(get_db)):
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
                "title": _hist_title(r.report_title, p, lang),
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "status": r.status,
            }
            for r in rows
        ],
    }
