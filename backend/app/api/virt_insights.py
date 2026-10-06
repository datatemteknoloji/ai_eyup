"""Sanallaştırma karar katmanı API'si — /api/v1/virt-insights

Kapasite & what-if, yerleştirme önerisi, geri kazanım, sağlık/donanım/denetim
bulguları, değişiklik geçmişi, offline referans paketleri (CVE/KB/yükseltme),
olay zaman çizelgesi. Tüm okumalar salt-okunur; tek yazma işlemleri bulgu
istisnası, baseline işaretleme ve referans paketi yüklemedir (DB içi).
Altyapıda değişiklik yalnız Agent onay akışından geçer (bkz. /remediation).
"""
from __future__ import annotations

import csv
import io
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import client_ip, require_module, require_role
from app.core.database import get_db
from app.models.infra_finding import InfraCheckRun, InfraFinding, InfraFindingException
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

VIRT_PLATFORMS = ("vmware", "olvm", "ocp_virt")
_module = require_module("virtualization")


def _platforms(platform: Optional[str]) -> List[str]:
    if platform:
        if platform not in VIRT_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"Geçersiz platform: {platform}")
        return [platform]
    return list(VIRT_PLATFORMS)


def _locale(request: Request) -> str:
    lang = (request.headers.get("accept-language") or "").lower()
    return "en" if lang.startswith("en") else "tr"


def _audit(db: Session, user: User, action: str, summary: str, request: Optional[Request] = None,
           **detail: Any) -> None:
    try:
        from app.services.audit import record_audit
        record_audit(db, category="virt_insights", action=action, actor=user, summary=summary,
                     detail=detail or None, ip_address=client_ip(request) if request else None)
    except Exception:
        logger.debug("audit yazılamadı", exc_info=True)


# ── Özet / katalog / turlar ──────────────────────────────────────────────────

@router.get("/summary")
def summary(platform: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.findings.store import summarize_findings
    plats = _platforms(platform)
    out: Dict[str, Any] = {"ok": True, "findings": summarize_findings(db, platforms=plats)}
    try:
        from app.services.virt_reclaim import build_reclaim
        out["reclaim"] = build_reclaim(db, platform=platform)["summary"]
    except Exception as exc:
        logger.warning("reclaim özeti: %s", exc)
        out["reclaim"] = None
    n1_fail = (db.query(InfraFinding)
               .filter(InfraFinding.check_id == "cap.cluster.n_plus_one", InfraFinding.active.is_(True),
                       InfraFinding.result == "fail", InfraFinding.platform.in_(plats)).count())
    n1_total = (db.query(InfraFinding)
                .filter(InfraFinding.check_id == "cap.cluster.n_plus_one", InfraFinding.active.is_(True),
                        InfraFinding.platform.in_(plats)).count())
    out["capacity"] = {"n1_fail": n1_fail, "clusters": n1_total}
    last = (db.query(InfraCheckRun).filter(InfraCheckRun.platform.in_(plats))
            .order_by(InfraCheckRun.started_at.desc()).first())
    out["last_run"] = _run_dict(last) if last else None
    return out


@router.get("/catalog")
def catalog(request: Request, user: User = Depends(_module)):
    from app.services.findings.registry import CONTROL_TITLES, catalog as _cat
    return {"checks": [c for c in _cat(_locale(request)) if set(c["platforms"]) & set(VIRT_PLATFORMS)],
            "controls": CONTROL_TITLES}


def _run_dict(r: InfraCheckRun) -> Dict[str, Any]:
    return {
        "id": r.id, "platform": r.platform, "source_id": r.source_id, "source_name": r.source_name,
        "kind": r.kind, "status": r.status, "error": r.error, "stats": r.stats or {},
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get("/runs")
def runs(limit: int = 50, platform: Optional[str] = None, db: Session = Depends(get_db),
         user: User = Depends(_module)):
    q = db.query(InfraCheckRun).filter(InfraCheckRun.platform.in_(_platforms(platform)))
    rows = q.order_by(InfraCheckRun.started_at.desc()).limit(max(1, min(limit, 500))).all()
    return {"runs": [_run_dict(r) for r in rows]}


class RunRequest(BaseModel):
    hypervisor_id: Optional[int] = None
    platform: Optional[str] = None
    file_scan: Optional[bool] = None


@router.post("/run")
def run_now(body: RunRequest, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require_role("admin"))):
    if body.platform:
        _platforms(body.platform)
    kwargs = {"hypervisor_id": body.hypervisor_id, "platform": body.platform, "file_scan": body.file_scan}
    queued = False
    try:
        from app.worker import enqueue_fleet_job
        queued = enqueue_fleet_job("fleet.virt_insights", **kwargs)
    except Exception as exc:
        logger.info("virt_insights enqueue: %s", exc)
    if not queued:
        from app.services.fleet_jobs import run_virt_insights
        threading.Thread(target=run_virt_insights, kwargs=kwargs, daemon=True, name="virt-insights").start()
    _audit(db, user, "virt_insights.run", "Karar katmanı turu başlatıldı", request, **kwargs)
    return {"ok": True, "queued": "celery" if queued else "thread"}


# ── Kapasite ─────────────────────────────────────────────────────────────────

@router.get("/capacity")
def capacity(hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
             platform: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_capacity_planner import build_capacity
    if platform:
        _platforms(platform)
    return build_capacity(db, hypervisor_id=hypervisor_id, cluster=cluster, platform=platform)


class SimulateRequest(BaseModel):
    vcpu: int = Field(2, ge=1, le=768)
    memory_gb: float = Field(8, ge=0, le=24576)
    disk_gb: float = Field(0, ge=0, le=1_000_000)
    count: int = Field(1, ge=1, le=1000)
    hypervisor_id: Optional[int] = None
    cluster: Optional[str] = None
    cpu_util_assumption: float = Field(0.5, ge=0.05, le=1.0)


@router.post("/capacity/simulate")
def capacity_simulate(body: SimulateRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_capacity_planner import simulate
    return simulate(db, **body.model_dump())


# ── Yerleştirme ──────────────────────────────────────────────────────────────

class PlacementRequest(BaseModel):
    vm_name: Optional[str] = None
    vcpu: Optional[int] = Field(None, ge=1, le=768)
    memory_gb: Optional[float] = Field(None, ge=0)
    disk_gb: Optional[float] = Field(None, ge=0)
    hypervisor_id: Optional[int] = None
    cluster: Optional[str] = None
    top_n: int = Field(5, ge=1, le=50)


@router.post("/placement")
def placement(body: PlacementRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_placement import recommend_placement
    if not body.vm_name and not (body.vcpu and body.memory_gb is not None):
        raise HTTPException(status_code=400, detail="vm_name veya vcpu + memory_gb gerekli")
    return recommend_placement(db, **body.model_dump())


# ── Geri kazanım ─────────────────────────────────────────────────────────────

@router.get("/reclaim")
def reclaim(hypervisor_id: Optional[int] = None, platform: Optional[str] = None, cluster: Optional[str] = None,
            db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_reclaim import build_reclaim
    if platform:
        _platforms(platform)
    return build_reclaim(db, hypervisor_id=hypervisor_id, platform=platform, cluster=cluster)


# ── Bulgular ─────────────────────────────────────────────────────────────────

@router.get("/findings")
def findings(
    request: Request,
    category: Optional[str] = None,
    categories: Optional[str] = Query(None, description="virgülle ayrılmış"),
    platform: Optional[str] = None,
    hypervisor_id: Optional[int] = None,
    cluster: Optional[str] = None,
    result: Optional[str] = "fail",
    severity_min: Optional[str] = None,
    include_excepted: bool = False,
    include_resolved: bool = False,
    entity: Optional[str] = None,
    check_id: Optional[str] = None,
    limit: int = 1000,
    db: Session = Depends(get_db),
    user: User = Depends(_module),
):
    from app.services.findings.store import query_findings
    rows = query_findings(
        db, category=category, categories=[c for c in (categories or "").split(",") if c] or None,
        platforms=_platforms(platform), source_id=hypervisor_id, cluster=cluster, result=result,
        severity_min=severity_min, include_excepted=include_excepted, include_resolved=include_resolved,
        entity=entity, check_id=check_id, limit=limit, locale=_locale(request),
    )
    return {"findings": rows, "count": len(rows)}


def _finding_or_404(db: Session, finding_id: int) -> InfraFinding:
    row = db.query(InfraFinding).filter(InfraFinding.id == finding_id).first()
    if not row or row.platform not in VIRT_PLATFORMS:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")
    return row


@router.get("/findings/{finding_id}")
def finding_detail(finding_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.findings.store import exception_keys, finding_to_dict
    row = _finding_or_404(db, finding_id)
    exc = exception_keys(db).get((row.platform, row.source_id, row.entity_ref, row.check_id))
    return finding_to_dict(row, exc, locale=_locale(request))


class ExceptionRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)
    expires_days: Optional[int] = Field(None, ge=1, le=3650)


@router.post("/findings/{finding_id}/exception")
def add_exception(finding_id: int, body: ExceptionRequest, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    row = _finding_or_404(db, finding_id)
    ex = (db.query(InfraFindingException)
          .filter(InfraFindingException.platform == row.platform, InfraFindingException.source_id == row.source_id,
                  InfraFindingException.entity_ref == row.entity_ref,
                  InfraFindingException.check_id == row.check_id).first())
    if ex is None:
        ex = InfraFindingException(platform=row.platform, source_id=row.source_id,
                                   entity_ref=row.entity_ref, check_id=row.check_id)
        db.add(ex)
    ex.reason = body.reason.strip()
    ex.created_by = user.username
    ex.created_at = datetime.now(timezone.utc)
    ex.expires_at = (datetime.now(timezone.utc) + timedelta(days=body.expires_days)) if body.expires_days else None
    db.commit()
    _audit(db, user, "virt_insights.exception_add", f"İstisna: {row.title} / {row.entity_name}", request,
           finding_id=row.id, check_id=row.check_id, entity=row.entity_ref, reason=ex.reason,
           expires_days=body.expires_days)
    return {"ok": True, "exception_id": ex.id}


@router.delete("/findings/{finding_id}/exception")
def remove_exception(finding_id: int, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    row = _finding_or_404(db, finding_id)
    n = (db.query(InfraFindingException)
         .filter(InfraFindingException.platform == row.platform, InfraFindingException.source_id == row.source_id,
                 InfraFindingException.entity_ref == row.entity_ref,
                 InfraFindingException.check_id == row.check_id)
         .delete(synchronize_session=False))
    db.commit()
    _audit(db, user, "virt_insights.exception_remove", f"İstisna kaldırıldı: {row.title}", request,
           finding_id=row.id)
    return {"ok": True, "removed": n}


@router.get("/findings/{finding_id}/draft")
def finding_draft(finding_id: int, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.findings.drafts import build_draft
    row = _finding_or_404(db, finding_id)
    d = build_draft(db, row)
    if not d:
        raise HTTPException(status_code=404, detail="Bu bulgu için komut taslağı yok")
    return d


# ── Değişiklik geçmişi / baseline ────────────────────────────────────────────

@router.get("/changes")
def changes(days: int = 30, platform: Optional[str] = None, hypervisor_id: Optional[int] = None,
            entity_kind: Optional[str] = None, entity: Optional[str] = None, limit: int = 300,
            db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_config_drift import list_changes
    if platform:
        _platforms(platform)
    rows = list_changes(db, days=days, platform=platform, source_id=hypervisor_id,
                        entity_kind=entity_kind, entity=entity, limit=limit)
    rows = [r for r in rows if r["platform"] in VIRT_PLATFORMS]
    return {"changes": rows, "count": len(rows)}


class BaselineRequest(BaseModel):
    platform: Optional[str] = None       # boş = tüm sanallaştırma platformları
    hypervisor_id: Optional[int] = None  # boş = platformdaki tüm kaynaklar
    entity_kind: Optional[str] = None
    entity_ref: Optional[str] = None


@router.post("/baseline")
def baseline(body: BaselineRequest, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_role("operator"))):
    from app.services.virt_config_drift import set_baseline
    if body.platform:
        _platforms(body.platform)
    platforms = [body.platform] if body.platform else sorted(VIRT_PLATFORMS)
    n = sum(set_baseline(db, platform=p, source_id=body.hypervisor_id, entity_kind=body.entity_kind,
                         entity_ref=body.entity_ref, user=user.username) for p in platforms)
    db.commit()
    _audit(db, user, "virt_insights.baseline", f"Baseline işaretlendi ({n} varlık)", request,
           **body.model_dump())
    return {"ok": True, "count": n}


# ── Referans paketleri (CVE / KB / yükseltme matrisi) ────────────────────────

@router.get("/reference")
def reference_status(db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_reference_checks import package_status
    return {"packages": package_status(db)}


@router.get("/reference/{kind}/sample")
def reference_sample(kind: str, user: User = Depends(_module)):
    from app.services.virt_reference_samples import SAMPLES
    if kind not in SAMPLES:
        raise HTTPException(status_code=404, detail="Örnek yok")
    return SAMPLES[kind]


@router.post("/reference/{kind}")
async def reference_upload(kind: str, request: Request, payload: Dict[str, Any] = Body(...),
                           ingest_rag: bool = False, db: Session = Depends(get_db),
                           user: User = Depends(require_role("admin"))):
    from app.services.virt_reference_checks import KINDS, save_package
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"Geçersiz paket türü: {kind}")
    try:
        res = save_package(db, kind, payload, user=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    rag = None
    if kind == "kb_feed" and ingest_rag:
        try:
            from app.services.rag_service import ingest_runbook
            n = 0
            for art in payload.get("articles") or []:
                body_txt = "\n".join(filter(None, [
                    f"{art.get('id')}: {art.get('title')}", art.get("url") or "",
                    "Belirtiler: " + "; ".join(art.get("symptoms") or []), art.get("resolution") or "",
                ]))
                n += await ingest_runbook(f"KB {art.get('id')}", body_txt)
            rag = {"chunks": n}
        except Exception as exc:
            logger.warning("KB RAG ingest: %s", exc)
            rag = {"error": str(exc)}
    _audit(db, user, "virt_insights.reference_upload", f"Referans paketi yüklendi: {kind}", request,
           kind=kind, items=res["item_count"], source=res["source"])
    return {"ok": True, **res, "rag": rag}


# ── Denetim kanıtı ───────────────────────────────────────────────────────────

@router.get("/compliance")
def compliance(platform: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_compliance import compliance_report
    return compliance_report(db, platforms=_platforms(platform))


@router.get("/compliance/export")
def compliance_export(format: str = "csv", platform: Optional[str] = None, request: Request = None,
                      db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_compliance import compliance_report, compliance_rows
    rep = compliance_report(db, platforms=_platforms(platform))
    _audit(db, user, "virt_insights.compliance_export", f"Denetim kanıtı dışa aktarıldı ({format})", request)
    if format == "json":
        return rep
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["control", "control_title", "platform", "source", "cluster", "entity", "check_id", "check",
                "result", "severity", "detail", "evidence", "last_seen", "exception"])
    for r in compliance_rows(rep):
        w.writerow(r)
    buf.seek(0)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="virt-compliance-{stamp}.csv"'},
    )


# ── Olay zaman çizelgesi (RCA) ───────────────────────────────────────────────

@router.get("/incident-timeline/{incident_id}")
def incident_timeline(incident_id: int, before_min: int = 120, after_min: int = 60,
                      db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_incident_timeline import build_incident_timeline
    res = build_incident_timeline(db, incident_id=incident_id, before_min=before_min, after_min=after_min)
    if not res.get("ok") and res.get("not_found"):
        raise HTTPException(status_code=404, detail=res.get("error") or "Olay bulunamadı")
    return res


@router.get("/timeline")
def timeline(host: Optional[str] = None, vm: Optional[str] = None, datastore: Optional[str] = None,
             at: Optional[str] = None, before_min: int = 120, after_min: int = 60,
             db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_incident_timeline import build_timeline
    if not (host or vm or datastore):
        raise HTTPException(status_code=400, detail="host, vm veya datastore gerekli")
    return build_timeline(db, host=host, vm=vm, datastore=datastore, at=at,
                          before_min=before_min, after_min=after_min)


# ── Onaylı düzeltme (Agent) + yazma hesabı ───────────────────────────────────

@router.get("/remediation/catalog")
def remediation_catalog(user: User = Depends(_module)):
    from app.services.virt_remediation import ACTIONS
    return {"actions": [{"id": a.id, "title": a.title, "platforms": list(a.platforms), "check_ids": list(a.check_ids),
                         "rollback": a.rollback_note} for a in ACTIONS.values()]}


class RemediationRequest(BaseModel):
    finding_id: int
    action_id: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/remediation/propose")
def remediation_propose(body: RemediationRequest, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_role("operator"))):
    from app.services.virt_remediation import propose
    row = _finding_or_404(db, body.finding_id)
    if row.platform not in VIRT_PLATFORMS:
        raise HTTPException(status_code=400, detail="Bu platform için düzeltme yok")
    res = propose(db, row, action_id=body.action_id, params=body.params, user=user)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Öneri oluşturulamadı")
    _audit(db, user, "virt_insights.remediation_propose", f"Düzeltme önerildi: {res.get('title')}", request,
           finding_id=row.id, action_id=res.get("action_id"), agent_action_id=res.get("agent_action_id"))
    return res


class WriteCredentialRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)


@router.get("/write-credential/{hypervisor_id}")
def write_credential_status(hypervisor_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_role("admin"))):
    from app.services.virt_remediation import write_credential_status as _st
    return _st(db, hypervisor_id)


@router.put("/write-credential/{hypervisor_id}")
def write_credential_set(hypervisor_id: int, body: WriteCredentialRequest, request: Request,
                         db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    from app.services.virt_remediation import set_write_credential
    res = set_write_credential(db, hypervisor_id, body.username, body.password)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Kaydedilemedi")
    _audit(db, user, "virt_insights.write_credential_set", "Ayrı yazma hesabı tanımlandı", request,
           hypervisor_id=hypervisor_id, username=body.username)
    return res


@router.delete("/write-credential/{hypervisor_id}")
def write_credential_delete(hypervisor_id: int, request: Request, db: Session = Depends(get_db),
                            user: User = Depends(require_role("admin"))):
    from app.services.virt_remediation import clear_write_credential
    res = clear_write_credential(db, hypervisor_id)
    _audit(db, user, "virt_insights.write_credential_clear", "Yazma hesabı kaldırıldı", request,
           hypervisor_id=hypervisor_id)
    return res
