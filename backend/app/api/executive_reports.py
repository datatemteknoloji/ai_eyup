"""Yönetici hazır raporları — Tüm Ortamlar (`/executive-reports/*`).

Modül yetkisi `core/module_policy.py` (`/executive-reports` → `executive`) ile uygulanır.
Üretim senkron DB işidir; `asyncio.to_thread` + kendi oturumu ile event döngüsünden uzak tutulur.
"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.database import SessionLocal

router = APIRouter()


class ReportRequest(BaseModel):
    report_type: str
    save: bool = True
    lang: str = "tr"      # "en" → içerik İngilizce (kayıt Türkçe kalır; çıktı sınırında çevrilir)


def _lang(lang: str) -> str:
    return "en" if (lang or "").lower().startswith("en") else "tr"


def _engine():
    from app.services import exec_catalog_reports as ex

    return ex


def _check(report_type: str) -> None:
    if report_type not in _engine().CATALOG:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen rapor tipi: {report_type}")


def _generate(report_type: str, save: bool, lang: str = "tr"):
    from app.services.report_i18n import translate_report

    ex = _engine()
    db = SessionLocal()
    try:
        data = ex.generate(db, report_type, save=save)
        return translate_report(data, lang), ex.to_markdown(report_type, data, lang)
    finally:
        db.close()


def _latest(report_type: str, lang: str = "tr"):
    from app.services.report_i18n import translate_report

    ex = _engine()
    db = SessionLocal()
    try:
        cached = ex.get_latest(db, report_type)
        if cached:
            return "cache", translate_report(cached, lang), ex.to_markdown(report_type, cached, lang)
        data = ex.generate(db, report_type, save=True)
        return "fresh", translate_report(data, lang), ex.to_markdown(report_type, data, lang)
    finally:
        db.close()


def _ti(title, lang: str):
    from app.services.report_i18n import t

    return t(title, lang)


def _history(limit: int, lang: str = "tr"):
    from app.models.infrastructure_report import InfrastructureReport

    db = SessionLocal()
    try:
        rows = (db.query(InfrastructureReport)
                .filter(InfrastructureReport.report_type.like("executive:%"))
                .order_by(InfrastructureReport.generated_at.desc()).limit(max(1, min(limit, 100))).all())
        return [{
            "id": r.id,
            "type": r.report_type.split(":", 1)[-1],
            "title": _ti(r.report_title, lang),
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "status": r.status,
        } for r in rows]
    finally:
        db.close()


def _app_t(app, lang: str):
    from app.services.report_i18n import translate_report

    if lang != "en" or not isinstance(app, dict):
        return app
    return translate_report({"applicability": app}, lang)["applicability"]


@router.get("/catalog")
async def catalog(lang: str = "tr"):
    from app.services.report_i18n import t as _t

    ex = _engine()
    lg = _lang(lang)
    return {
        "platform": "executive",
        "report_types": [
            {"type": t, "title": _t(ex.REPORT_TITLES[t], lg), "available": True,
             "applicability": _app_t(ex.applicability(t), lg)}
            for t in ex.CATALOG
        ],
    }


@router.post("/generate")
async def generate_report(req: ReportRequest):
    _check(req.report_type)
    try:
        data, md = await asyncio.to_thread(_generate, req.report_type, req.save, _lang(req.lang))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True, "data": data, "markdown": md}


@router.get("/latest/{report_type}")
async def latest_report(report_type: str, lang: str = "tr"):
    _check(report_type)
    source, data, md = await asyncio.to_thread(_latest, report_type, _lang(lang))
    return {"source": source, "data": data, "markdown": md}


@router.get("/history")
async def history(limit: int = 20, lang: str = "tr"):
    return {"platform": "executive", "reports": await asyncio.to_thread(_history, limit, _lang(lang))}
