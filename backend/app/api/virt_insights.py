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
    # H.0 kapsam seçici: instance (hypervisor_id) → datacenter → cluster(lar) → (opsiyonel) host(lar)
    clusters: Optional[List[str]] = None
    datacenter: Optional[str] = None
    hosts: Optional[List[str]] = None
    platforms: Optional[List[str]] = None      # vmware | olvm | ocp_virt (boş = hepsi)


@router.get("/capacity/policy")
def capacity_policy_get(db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services import capacity_policy
    return {"ok": True, **capacity_policy.payload(db)}


class CapacityPolicyBody(BaseModel):
    values: Dict[str, float]


@router.put("/capacity/policy")
def capacity_policy_put(body: CapacityPolicyBody, request: Request, db: Session = Depends(get_db),
                        user: User = Depends(require_role("admin"))):
    """Kapasite eşiklerini günceller (yalnız admin). Varsayılana eşit değer satırı siler."""
    from app.services import capacity_policy
    try:
        capacity_policy.save(db, body.values, user=getattr(user, "username", "") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, user, "capacity_policy_update", "Kapasite eşikleri güncellendi", request, values=body.values)
    return {"ok": True, **capacity_policy.payload(db)}


class CapacityOverrideBody(BaseModel):
    hypervisor_id: int
    cluster: Optional[str] = None      # None/'' = instance seviyesi varsayılan
    values: Dict[str, float]


@router.get("/capacity/policy/overrides")
def capacity_policy_overrides(hypervisor_id: int, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Instance (cluster='') ve cluster override'ları + her cluster için etkin değerler (H.0)."""
    from app.services import capacity_policy
    ov = capacity_policy.load_overrides(db, hypervisor_id)
    return {"ok": True, "hypervisor_id": hypervisor_id, "overrides": ov,
            "effective_instance": capacity_policy.effective(db, hypervisor_id, None),
            "effective_by_cluster": {c: capacity_policy.effective(db, hypervisor_id, c) for c in ov if c}}


@router.put("/capacity/policy/override")
def capacity_policy_override_put(body: CapacityOverrideBody, request: Request, db: Session = Depends(get_db),
                                 user: User = Depends(require_role("admin"))):
    from app.services import capacity_policy
    try:
        eff = capacity_policy.save_override(db, body.hypervisor_id, body.cluster, body.values,
                                            user=getattr(user, "username", "") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit(db, user, "capacity_policy_override", "Kapasite eşik override'ı güncellendi", request,
           hypervisor_id=body.hypervisor_id, cluster=body.cluster, values=body.values)
    return {"ok": True, "effective": eff}


@router.delete("/capacity/policy/override")
def capacity_policy_override_delete(request: Request, hypervisor_id: int, key: str, cluster: Optional[str] = None,
                                    db: Session = Depends(get_db),
                                    user: User = Depends(require_role("admin"))):
    from app.services import capacity_policy
    n = capacity_policy.delete_override(db, hypervisor_id, cluster, key)
    _audit(db, user, "capacity_policy_override", "Kapasite eşik override'ı silindi", request,
           hypervisor_id=hypervisor_id, cluster=cluster, key=key)
    return {"ok": True, "deleted": n, "effective": capacity_policy.effective(db, hypervisor_id, cluster)}


@router.post("/capacity/simulate")
def capacity_simulate(body: SimulateRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_capacity_planner import simulate
    return simulate(db, **body.model_dump())


class HostFailureRequest(BaseModel):
    hypervisor_id: int
    cluster: str
    hosts: List[str] = Field(..., min_length=1, max_length=64)


@router.post("/capacity/host-failure")
def capacity_host_failure(body: HostFailureRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    """"Bu host(lar) devre dışı kalırsa çalışan VM'ler kalan host'lara sığar mı?" (salt okunur, deterministik)."""
    from app.services.virt_capacity_planner import host_failure
    res = host_failure(db, **body.model_dump())
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Senaryo hesaplanamadı")
    return res


class HostFailureMatrixRequest(BaseModel):
    hypervisor_id: int
    cluster: str


@router.post("/capacity/host-failure/matrix")
def capacity_host_failure_matrix(body: HostFailureMatrixRequest, db: Session = Depends(get_db),
                                 user: User = Depends(_module)):
    """Cluster'daki her host için otomatik N+1 matrisi (salt okunur; satırlar `host-failure` ile aynı hesap)."""
    from app.services.virt_capacity_planner import host_failure_matrix
    res = host_failure_matrix(db, **body.model_dump())
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Matris hesaplanamadı")
    return res


class ReclaimSimRequest(BaseModel):
    hypervisor_id: Optional[int] = None
    cluster: Optional[str] = None
    thresholds: Optional[Dict[str, float]] = Field(None, description="GEÇİCİ eşikler (rs_window_days, rs_target_pct, ...)")


@router.post("/capacity/reclaim-sim")
def capacity_reclaim_sim(body: ReclaimSimRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    """"VM'ler p95'e göre küçültülürse cluster kapasitesi" — salt okunur; eşikler yalnız bu istekte geçerli, kaydedilmez."""
    from app.services.virt_reclaim_sim import reclaim_sim
    try:
        return reclaim_sim(db, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class BulkProfile(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    vcpu: int = Field(..., ge=1, le=512)
    memory_gb: float = Field(..., ge=0, le=16384)
    disk_gb: float = Field(0, ge=0, le=1048576)
    count: int = Field(1, ge=1, le=500)
    group: Optional[str] = Field(None, max_length=80, description="anti-affinity grubu (opsiyonel)")


class BulkPlacementRequest(BaseModel):
    profiles: List[BulkProfile] = Field(..., min_length=1, max_length=50)
    hypervisor_id: Optional[int] = None
    datacenter: Optional[str] = None
    clusters: Optional[List[str]] = None
    hosts: Optional[List[str]] = None
    platforms: Optional[List[str]] = None


@router.post("/capacity/bulk-placement")
def capacity_bulk_placement(body: BulkPlacementRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Çoklu VM profili + anti-affinity grubu için cluster başına yerleşim planı (salt okunur, kaydedilmez)."""
    from app.services.virt_bulk_placement import bulk_place
    data = body.model_dump()
    for pf in data.get("platforms") or []:
        _platforms(pf)                                   # geçersiz platform → 400
    try:
        return bulk_place(db, **data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class MoveRequest(BaseModel):
    vcpu: int = Field(..., ge=1, le=768)
    memory_gb: float = Field(..., ge=0, le=16384)
    disk_gb: float = Field(0.0, ge=0)
    count: int = Field(1, ge=1, le=500)
    from_hypervisor_id: int
    from_cluster: str
    to_hypervisor_id: int
    to_cluster: str


@router.post("/capacity/move")
def capacity_move(body: MoveRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Açık "A cluster'ından B'ye taşı" senaryosu (H.0 #10). Kendiliğinden cluster dışı yerleştirme yoktur."""
    from app.services.virt_capacity_planner import move_scenario
    res = move_scenario(db, **body.model_dump())
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Senaryo hesaplanamadı")
    return res


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


@router.get("/vms")
def list_vms_for_placement(
    q: str = "",
    limit: int = 40,
    db: Session = Depends(get_db),
    user: User = Depends(_module),
):
    """Yerleşim sekmesi için aranabilir VM listesi (envanter)."""
    from app.services import virt_insights_data as vd
    lim = max(1, min(int(limit or 40), 100))
    needle = (q or "").strip().lower()
    hvs = vd.virt_hypervisors(db)
    hv_ids = [h.id for h in hvs]
    hv_name = {h.id: h.name for h in hvs}
    rows = []
    for v in vd.vm_allocations(db, hv_ids):
        name = v.get("name") or ""
        if needle and needle not in name.lower():
            continue
        rows.append({
            "name": name,
            "hypervisor_id": v.get("hypervisor_id"),
            "hypervisor": hv_name.get(v.get("hypervisor_id")),
            "cluster": v.get("cluster"),
            "host": v.get("host"),
            "vcpu": v.get("vcpu"),
            "memory_gb": v.get("memory_gb"),
            "disk_gb": v.get("disk_gb"),
            "powered_on": v.get("powered_on"),
        })
        if len(rows) >= lim:
            break
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return {"ok": True, "items": rows}


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


@router.get("/findings/{finding_id}/context")
def finding_context_ep(finding_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Bulgu bağlamı (salt okunur, deterministik): host düşerse etki, aynı host'taki ilişkili bulgular, genel rehber."""
    from app.services.findings.context import finding_context
    return finding_context(db, _finding_or_404(db, finding_id), locale=_locale(request))


# ── AI yorumu (Yapılandırma + Donanım) — yalnız butonla üretilir ─────────────

def _ai_guard(row: InfraFinding):
    from app.services.findings import ai_comment as ac
    if row.category not in ac.AI_CATEGORIES:
        raise HTTPException(status_code=400, detail="Bu bulgu kategorisi için AI yorumu desteklenmiyor")
    return ac


@router.get("/findings/{finding_id}/ai-comment")
def finding_ai_comment_get(finding_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Kayıtlı AI yorumu + güncel olup olmadığı. Yorum ÜRETMEZ (üretim yalnız POST ile, butonla)."""
    from app.services.findings import ai_comment as ac
    row = _finding_or_404(db, finding_id)
    return ac.get_state(db, row, locale=_locale(request), username=getattr(user, "username", "") or "")


@router.post("/findings/{finding_id}/ai-comment")
async def finding_ai_comment_generate(finding_id: int, request: Request, db: Session = Depends(get_db),
                                      user: User = Depends(_module)):
    """AI yorumu üretir/yeniden üretir. Çıktı kurallarla doğrulanır; geçmezse saklanmaz ve gösterilmez."""
    row = _finding_or_404(db, finding_id)
    ac = _ai_guard(row)
    if not ac.tables_ready(db):
        raise HTTPException(status_code=503, detail=ac.TABLES_MISSING_MSG)
    uname = getattr(user, "username", "") or ""
    try:
        res = await ac.generate(db, row, locale=_locale(request), user=uname, persist=True)
    except ac.AiCommentRejected as exc:
        _audit(db, user, "finding_ai_comment_rejected", "AI yorumu doğrulamayı geçemedi", request,
               finding_id=finding_id, violations=exc.violations[:8])
        raise HTTPException(status_code=422, detail="AI yorumu kalite kurallarını geçemedi; gösterilmedi. Lütfen yeniden deneyin.")
    except ac.AiUnavailable:
        raise HTTPException(status_code=503, detail="AI servisine ulaşılamadı")
    _audit(db, user, "finding_ai_comment", "Bulgu için AI yorumu üretildi", request,
           finding_id=finding_id, version=res.get("version"), model=res.get("model"))
    return ac.get_state(db, row, locale=_locale(request), username=uname)


class AiFeedbackBody(BaseModel):
    comment_id: int
    helpful: bool
    note: Optional[str] = Field(None, max_length=500)


@router.post("/findings/{finding_id}/ai-comment/feedback")
def finding_ai_comment_feedback(finding_id: int, body: AiFeedbackBody, db: Session = Depends(get_db),
                                user: User = Depends(_module)):
    row = _finding_or_404(db, finding_id)
    ac = _ai_guard(row)
    if not ac.tables_ready(db):
        raise HTTPException(status_code=503, detail=ac.TABLES_MISSING_MSG)
    try:
        return {"ok": True, **ac.submit_feedback(db, row, comment_id=body.comment_id,
                                                  username=getattr(user, "username", "") or "",
                                                  helpful=body.helpful, note=body.note)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
    from app.models.infra_finding import VirtConfigSnapshot
    from sqlalchemy import func
    bq = db.query(func.count(VirtConfigSnapshot.id)).filter(
        VirtConfigSnapshot.is_baseline.is_(True),
        VirtConfigSnapshot.platform.in_(list(VIRT_PLATFORMS)),
    )
    baseline_count = int(bq.scalar() or 0)
    suggested = []
    if baseline_count == 0:
        # İlk senkron / baseline yok: kullanıcıya önerilen türler
        suggested = [
            {"entity_kind": "host", "note": "Önerilen: host baseline"},
            {"entity_kind": "cluster", "note": "Önerilen: cluster baseline"},
            {"entity_kind": "datastore", "note": "Önerilen: datastore baseline"},
            {"entity_kind": "platform", "note": "Önerilen: platform baseline"},
        ]
    return {
        "changes": rows,
        "count": len(rows),
        "baseline_count": baseline_count,
        "suggested_baseline": suggested,
        "empty_reason": None if rows or baseline_count else (
            "Henüz değişiklik yok. İlk taramada kayıtlar değişiklik sayılmaz; "
            "baseline işaretleyerek sapma izlemeyi başlatın."
        ),
    }


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
    from app.services.reference_sources import allowed_domains, verified_sources
    from app.services.virt_reference_checks import FEED_STALE_DAYS, package_status
    # C1: paket türü başına YALNIZ doğrulanmış resmi kaynaklar (reference_sources.json `verified: true`); uydurma bağlantı yok.
    sources = {k: verified_sources(k) for k in ("cve_feed", "kb_feed", "upgrade_matrix")}
    return {"packages": package_status(db), "allowed_domains": allowed_domains(),
            "stale_threshold_days": FEED_STALE_DAYS, "sources": sources}


@router.get("/reference/{kind}/sample")
def reference_sample(kind: str, user: User = Depends(_module)):
    from app.services.virt_reference_samples import sample_with_meta
    d = sample_with_meta(kind)
    if d is None:
        raise HTTPException(status_code=404, detail="Örnek yok")
    return d


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
           kind=kind, items=res["item_count"], source=res["source"], sha256=res["sha256"], integrity=res["integrity"])
    return {"ok": True, **res, "rag": rag}


@router.delete("/reference/{kind}")
def reference_delete(kind: str, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    """Paketi siler. Mevcut bulgular KAPANMAZ: sonraki turda "doğrulanamayan" olarak korunur."""
    from app.services.virt_reference_checks import KINDS, delete_package
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"Geçersiz paket türü: {kind}")
    if not delete_package(db, kind):
        raise HTTPException(status_code=404, detail="Paket yüklü değil")
    db.commit()
    _audit(db, user, "virt_insights.reference_delete", f"Referans paketi silindi: {kind}", request, kind=kind)
    return {"ok": True, "kind": kind,
            "note": "Mevcut bulgular kapatılmadı; sonraki turda 'doğrulanamayan' olarak işaretlenecek."}


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
