"""
Özel Raporlar (Custom Reports) API
====================================

Hibrit "AI keşif + deterministik dondurma" akışı:

  1) `POST /custom-reports/resolve`  — doğal dil soruyu (chat gibi) agentic
     READ_ONLY tool-loop ile çözer, o turda çağrılan tool adaylarını
     (isim+args+render önizleme) döner. HİÇBİR ŞEY KAYDETMEZ.
  2) `POST /custom-reports/`         — kullanıcının seçtiği adayı
     (tool_name+tool_args) `CustomReportDefinition` olarak kaydeder;
     bir kez ÇALIŞTIRIP doğrulayarak (last_rendered) döner.
  3) `POST /custom-reports/{id}/run` — kayıtlı tanımı YENİDEN çalıştırır
     (LLM YOK — tam deterministik, aynı tool + aynı args).
  4) `GET /custom-reports/`, `GET /custom-reports/{id}`, `PATCH`, `DELETE`.

Erişim: 'custom_reports' modülü (varsayılan yalnız Admin; Kullanıcı Yönetimi
sayfasından diğer kullanıcılara da atanabilir — bkz. app.models.module).
Düzenleme/silme: oluşturan kullanıcı VEYA admin.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import client_ip, get_current_user, require_module, user_has_module
from app.core.database import get_db
from app.models.custom_report import CustomReportDefinition
from app.models.user import User
from app.services import custom_report_engine as engine
from app.services.audit import record_audit

router = APIRouter()
logger = logging.getLogger(__name__)

_require_custom_reports = require_module("custom_reports")

_VALID_PLATFORMS = frozenset({"linux", "windows", "virt", "openshift", "exadata", "unified"})
_VALID_DIRECTIVES = frozenset({"none", "table", "json", "brief"})

# Özel rapor platform alanı → RBAC modül id (Altyapı Raporları sayfası ile aynı).
# 'unified' yalnızca custom_reports (veya admin) ile görülür/çalıştırılır.
_PLATFORM_TO_MODULE = {
    "linux": "linux",
    "windows": "windows",
    "virt": "virtualization",
    "openshift": "openshift",
    "exadata": "exadata",
}


def _is_admin(user: User) -> bool:
    return user.role in ("admin", "superadmin")


def _check_owner_or_admin(defn: CustomReportDefinition, user: User) -> None:
    if _is_admin(user):
        return
    if defn.created_by is not None and defn.created_by == user.id:
        return
    raise HTTPException(status_code=403, detail="Bu raporu yalnızca oluşturan kullanıcı veya admin düzenleyebilir/silebilir")


def _can_view_platform_reports(user: User, db: Session, platform: str) -> bool:
    """Liste/çalıştır: custom_reports VEYA ilgili platform modülü (veya admin)."""
    if _is_admin(user) or user_has_module(user, "custom_reports", db):
        return True
    mod = _PLATFORM_TO_MODULE.get((platform or "").strip().lower())
    if mod and user_has_module(user, mod, db):
        return True
    return False


def _require_view_or_run(
    defn: CustomReportDefinition,
    user: User,
    db: Session,
) -> None:
    if _can_view_platform_reports(user, db, defn.platform or ""):
        return
    raise HTTPException(
        status_code=403,
        detail="Bu özel raporu görmek/çalıştırmak için ilgili platform veya Özel Raporlar yetkisi gerekli",
    )


def _defn_to_dict(defn: CustomReportDefinition) -> Dict[str, Any]:
    return {
        "id": defn.id,
        "title": defn.title,
        "description": defn.description,
        "platform": defn.platform,
        "tool_name": defn.tool_name,
        "tool_args": defn.tool_args or {},
        "output_directive": defn.output_directive,
        "source_question": defn.source_question,
        "created_by": defn.created_by,
        "created_at": defn.created_at.isoformat() if defn.created_at else None,
        "updated_at": defn.updated_at.isoformat() if defn.updated_at else None,
        "is_active": defn.is_active,
        "last_run_at": defn.last_run_at.isoformat() if defn.last_run_at else None,
        "last_ok": defn.last_ok,
        "last_rendered": defn.last_rendered,
        "last_error": defn.last_error,
    }


# ── Şemalar ──────────────────────────────────────────────────────────────────

class ResolveRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    platform: str = "unified"
    output_directive: Optional[str] = None
    model: Optional[str] = None


class CreateReportRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    platform: str
    tool_name: str
    tool_args: Dict[str, Any] = Field(default_factory=dict)
    output_directive: Optional[str] = "table"
    source_question: Optional[str] = None


class UpdateReportRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    output_directive: Optional[str] = None
    is_active: Optional[bool] = None


# ── Keşif (kayıt YOK) ────────────────────────────────────────────────────────

@router.post("/resolve")
async def resolve_query(
    body: ResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(_require_custom_reports),
):
    plat = (body.platform or "unified").strip().lower()
    if plat not in _VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen platform: {body.platform}")
    directive = (body.output_directive or "table").strip().lower()
    if directive not in _VALID_DIRECTIVES:
        directive = "table"
    result = engine.resolve_report_query(
        db,
        question=body.question,
        platform=plat,
        output_directive=directive,
        model=body.model,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error") or "Sorgu çözümlenemedi")
    return result


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_reports(
    platform: Optional[str] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Aktif özel raporlar.

    platform verilirse (ör. virt) Altyapı Raporları sayfası bu listeyi
    kendi kataloğuna ekler. Erişim: custom_reports VEYA o platform modülü.
    platform yoksa yalnızca custom_reports (yönetim sayfası).
    """
    plat = (platform or "").strip().lower() or None
    if plat:
        if plat not in _VALID_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"Desteklenmeyen platform: {platform}")
        if not _can_view_platform_reports(user, db, plat):
            raise HTTPException(
                status_code=403,
                detail="Bu platformun özel raporlarını görmek için yetki gerekli",
            )
    else:
        if not (_is_admin(user) or user_has_module(user, "custom_reports", db)):
            raise HTTPException(
                status_code=403,
                detail="Özel rapor listesi için 'custom_reports' modül yetkisi gerekli",
            )

    q = db.query(CustomReportDefinition).filter(CustomReportDefinition.is_active == True)  # noqa: E712
    if plat:
        q = q.filter(CustomReportDefinition.platform == plat)
    rows = q.order_by(CustomReportDefinition.created_at.desc()).all()
    return {"reports": [_defn_to_dict(r) for r in rows]}


@router.post("/")
async def create_report(
    body: CreateReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_custom_reports),
):
    plat = (body.platform or "").strip().lower()
    if plat not in _VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen platform: {body.platform}")
    if not engine.is_capturable_tool(body.tool_name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{body.tool_name}' özel rapor için desteklenmiyor "
                "(READ_ONLY ve sunucudan bağımsız olmalı)."
            ),
        )
    directive = (body.output_directive or "table").strip().lower()
    if directive not in _VALID_DIRECTIVES:
        directive = "table"

    defn = CustomReportDefinition(
        title=body.title.strip(),
        description=(body.description or "").strip() or None,
        platform=plat,
        tool_name=body.tool_name,
        tool_args=body.tool_args or {},
        output_directive=directive,
        source_question=(body.source_question or "").strip() or None,
        created_by=user.id,
    )
    db.add(defn)
    db.commit()
    db.refresh(defn)

    # Kaydederken bir kez çalıştırıp doğrula + önbelleği doldur.
    run = engine.execute_definition(db, defn)
    from datetime import datetime, timezone
    defn.last_run_at = datetime.now(timezone.utc)
    defn.last_ok = bool(run.get("ok"))
    defn.last_rendered = run.get("rendered")
    defn.last_error = run.get("error")
    db.commit()
    db.refresh(defn)

    record_audit(
        db, category="custom_reports", action="custom_report.create", status="success",
        actor=user, summary=f"Özel rapor oluşturuldu: {defn.title} ({defn.tool_name})",
        target_type="custom_report_definition", target_id=defn.id,
        ip_address=client_ip(request),
    )
    return {"ok": True, "report": _defn_to_dict(defn), "run": run}


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    defn = db.query(CustomReportDefinition).filter(CustomReportDefinition.id == report_id).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Özel rapor bulunamadı")
    _require_view_or_run(defn, user, db)
    return {"report": _defn_to_dict(defn)}


@router.post("/{report_id}/run")
async def run_report(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    defn = db.query(CustomReportDefinition).filter(CustomReportDefinition.id == report_id).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Özel rapor bulunamadı")
    _require_view_or_run(defn, user, db)

    run = engine.execute_definition(db, defn)
    from datetime import datetime, timezone
    defn.last_run_at = datetime.now(timezone.utc)
    defn.last_ok = bool(run.get("ok"))
    defn.last_rendered = run.get("rendered")
    defn.last_error = run.get("error")
    db.commit()
    db.refresh(defn)

    record_audit(
        db, category="custom_reports", action="custom_report.run", status=("success" if run.get("ok") else "error"),
        actor=user, summary=f"Özel rapor çalıştırıldı: {defn.title}",
        target_type="custom_report_definition", target_id=defn.id,
        ip_address=client_ip(request),
    )
    return {"ok": True, "report": _defn_to_dict(defn), "run": run}


@router.patch("/{report_id}")
async def update_report(
    report_id: int,
    body: UpdateReportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_custom_reports),
):
    defn = db.query(CustomReportDefinition).filter(CustomReportDefinition.id == report_id).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Özel rapor bulunamadı")
    _check_owner_or_admin(defn, user)

    if body.title is not None:
        defn.title = body.title.strip() or defn.title
    if body.description is not None:
        defn.description = body.description.strip() or None
    if body.output_directive is not None:
        d = body.output_directive.strip().lower()
        defn.output_directive = d if d in _VALID_DIRECTIVES else defn.output_directive
    if body.is_active is not None:
        defn.is_active = body.is_active

    db.commit()
    db.refresh(defn)
    record_audit(
        db, category="custom_reports", action="custom_report.update", status="success",
        actor=user, summary=f"Özel rapor güncellendi: {defn.title}",
        target_type="custom_report_definition", target_id=defn.id,
        ip_address=client_ip(request),
    )
    return {"ok": True, "report": _defn_to_dict(defn)}


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_custom_reports),
):
    defn = db.query(CustomReportDefinition).filter(CustomReportDefinition.id == report_id).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Özel rapor bulunamadı")
    _check_owner_or_admin(defn, user)

    title = defn.title
    db.delete(defn)
    db.commit()
    record_audit(
        db, category="custom_reports", action="custom_report.delete", status="success",
        actor=user, summary=f"Özel rapor silindi: {title}",
        target_type="custom_report_definition", target_id=report_id,
        ip_address=client_ip(request),
    )
    return {"ok": True}
