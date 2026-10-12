"""Yedek & DR görünümü — /api/v1/virt-insights/backup (modül: virtualization).

Yalnız `backup` capability varken anlamlıdır; yoksa summary `enabled=false` döner
ve diğer uçlar 404 verir (Veeam'siz ortamda sekme/kart hiç gösterilmez).
Tüm rakamlar deterministik motordan gelir (rpo_engine); RTO tahmin edilmez.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_module, require_role
from app.core.database import get_db
from app.models.backup import BkJob, BkProtectedObject, BkRepository, BkRpoPolicy
from app.models.user import User
from app.services.backup import rpo_engine as eng
from app.services.backup.matching import CONF_LOW, CONF_NONE
from app.services.capabilities import get_capabilities

router = APIRouter()
_module = require_module("virtualization")


def _view_available() -> bool:
    """Yedekleme ekranı: gerçek sağlayıcı ('backup') VEYA — yalnız açık bayrakla — demo."""
    from app.services.backup.demo_gate import DEMO_CAPABILITY
    caps = get_capabilities()
    return "backup" in caps or DEMO_CAPABILITY in caps


def _need_backup() -> None:
    if not _view_available():
        raise HTTPException(404, "Yedek sağlayıcısı yapılandırılmadı")


@router.get("/summary")
def backup_summary(db: Session = Depends(get_db), _u: User = Depends(_module)):
    if not _view_available():
        return {"enabled": False}
    return {"enabled": True, **eng.summary(db, include_demo=True)}


@router.get("/rpo")
def backup_rpo(state: Optional[str] = Query(None, description="protected|unprotected|low_match"),
               rpo_state: Optional[str] = Query(None, description="ok|breach|no_target"),
               q: Optional[str] = None, limit: int = Query(500, ge=1, le=5000),
               db: Session = Depends(get_db), _u: User = Depends(_module)):
    _need_backup()
    rows = eng.vm_protection(db, include_demo=True)
    if state:
        rows = [r for r in rows if r["state"] == state]
    if rpo_state:
        rows = [r for r in rows if r["rpo_state"] == rpo_state]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in str(r["name"] or "").lower()]
    rows.sort(key=lambda r: (r["state"] != "unprotected", r["rpo_state"] != "breach", str(r["name"] or "").lower()))
    return {"vms": rows[:limit], "count": len(rows)}


@router.get("/jobs")
def backup_jobs(db: Session = Depends(get_db), _u: User = Depends(_module)):
    _need_backup()
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    jobs = db.query(BkJob).filter(BkJob.instance_id.in_(ids or [-1])).order_by(BkJob.name).all()
    return {"jobs": [{
        "id": j.id, "name": j.name, "type": j.job_type, "enabled": j.enabled, "status": j.status,
        "last_result": j.last_result, "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None, "schedule": j.schedule,
        "repository": j.repository_name, "objects": j.objects_count,
    } for j in jobs]}


@router.get("/repositories")
def backup_repositories(db: Session = Depends(get_db), _u: User = Depends(_module)):
    _need_backup()
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    repos = db.query(BkRepository).filter(BkRepository.instance_id.in_(ids or [-1])).order_by(BkRepository.name).all()
    return {"repositories": [{
        "id": r.id, "name": r.name, "type": r.repo_type, "online": r.is_online,
        "capacity_gb": round(r.capacity_bytes / 1024 ** 3, 1) if r.capacity_bytes else None,
        "free_gb": round(r.free_bytes / 1024 ** 3, 1) if r.free_bytes is not None else None,
        "used_pct": eng.repo_used_pct(r), "warn_pct": eng.REPO_WARN_PCT,
    } for r in repos]}


@router.get("/unmatched")
def backup_unmatched(db: Session = Depends(get_db), _u: User = Depends(_module)):
    """Yedekte görünen ama ainew VM'ine güvenle eşleşmeyen nesneler (inceleme listesi)."""
    _need_backup()
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    rows = (db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_(ids or [-1]),
                                               BkProtectedObject.match_confidence.in_((CONF_LOW, CONF_NONE)))
            .order_by(BkProtectedObject.name).limit(1000).all())
    return {"objects": [{"id": o.id, "name": o.name, "path": o.path, "confidence": o.match_confidence,
                         "method": o.match_method, "matched_vm_id": o.matched_vm_id,
                         "last_restore_point_at": o.last_restore_point_at.isoformat() if o.last_restore_point_at else None}
                        for o in rows], "count": len(rows)}


class PolicyBody(BaseModel):
    scope_kind: str = Field("all", description="vm | cluster | all")
    scope_ref: str = ""
    target_rpo_min: Optional[int] = Field(None, ge=1, le=60 * 24 * 90)
    target_rto_min: Optional[int] = Field(None, ge=1, le=60 * 24 * 90)
    label: Optional[str] = None


def _pol(p: BkRpoPolicy) -> Dict[str, Any]:
    return {"id": p.id, "scope_kind": p.scope_kind, "scope_ref": p.scope_ref, "target_rpo_min": p.target_rpo_min,
            "target_rto_min": p.target_rto_min, "label": p.label}


@router.get("/policies")
def list_policies(db: Session = Depends(get_db), _u: User = Depends(_module)):
    _need_backup()
    return {"policies": [_pol(p) for p in db.query(BkRpoPolicy).order_by(BkRpoPolicy.id).all()],
            "note": "Hedef RPO/RTO ainew'de tanımlanır (Veeam'den gelmez). RTO yalnız hedef olarak saklanır, tahmin edilmez."}


@router.post("/policies")
def add_policy(body: PolicyBody, db: Session = Depends(get_db), _u: User = Depends(require_role("admin"))):
    _need_backup()
    if body.scope_kind not in eng.SCOPE_KINDS:
        raise HTTPException(400, f"Geçersiz kapsam: {body.scope_kind}")
    if body.scope_kind != "all" and not body.scope_ref.strip():
        raise HTTPException(400, "Kapsam adı gerekli (VM veya cluster adı)")
    if not body.target_rpo_min and not body.target_rto_min:
        raise HTTPException(400, "Hedef RPO veya RTO girin")
    ref = "" if body.scope_kind == "all" else body.scope_ref.strip()
    p = (db.query(BkRpoPolicy).filter(BkRpoPolicy.scope_kind == body.scope_kind, BkRpoPolicy.scope_ref == ref).first()
         or BkRpoPolicy(scope_kind=body.scope_kind, scope_ref=ref))
    p.target_rpo_min, p.target_rto_min, p.label = body.target_rpo_min, body.target_rto_min, body.label
    db.add(p)
    db.commit()
    from app.services.backup.rpo_engine import persist_backup_findings
    persist_backup_findings(db)   # hedef değişince RPO bulguları hemen yenilenir
    return _pol(p)


@router.delete("/policies/{pid}")
def delete_policy(pid: int, db: Session = Depends(get_db), _u: User = Depends(require_role("admin"))):
    _need_backup()
    p = db.query(BkRpoPolicy).filter(BkRpoPolicy.id == pid).first()
    if p is None:
        raise HTTPException(404, "Politika bulunamadı")
    db.delete(p)
    db.commit()
    from app.services.backup.rpo_engine import persist_backup_findings
    persist_backup_findings(db)
    return {"ok": True}


@router.get("/findings")
def backup_findings_list(result: str = Query("fail"), limit: int = Query(500, ge=1, le=5000),
                         db: Session = Depends(get_db), _u: User = Depends(_module)):
    """Yedek bulguları (platform=backup). Yalnız capability varken."""
    _need_backup()
    from app.services.findings.store import query_findings
    from app.services.backup.demo_gate import DEMO_PLATFORM, backup_mode
    plat = DEMO_PLATFORM if backup_mode(db) == "demo" else "backup"
    rows = query_findings(db, platforms=[plat], result=result, include_excepted=False, limit=limit,
                          include_demo=(plat == DEMO_PLATFORM))
    return {"findings": rows, "count": len(rows)}


@router.get("/evidence")
def backup_evidence(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _u: User = Depends(_module)):
    """ISO 27001 A.8.13 kanıtı (işler, başarı oranı, kapsam, geri yükleme testi kaydı — yoksa 'eksik')."""
    _need_backup()
    from app.services.backup import extras
    return extras.evidence(db, days=days)


@router.get("/correlations")
def backup_correlations(hours: int = Query(72, ge=1, le=24 * 14), db: Session = Depends(get_db), _u: User = Depends(_module)):
    """Yedek hatasından önce yapılandırma değişikliği olan işler (zamansal korelasyon)."""
    _need_backup()
    from app.services.backup import extras
    return {"items": extras.failure_after_change(db, hours=hours)}


@router.get("/capacity-whatif")
def backup_capacity_whatif(add_vms: int = Query(0, ge=0, le=10000), avg_vm_gb: Optional[float] = Query(None, gt=0),
                           db: Session = Depends(get_db), _u: User = Depends(_module)):
    _need_backup()
    from app.services.backup import extras
    return extras.repo_whatif(db, add_vms=add_vms, avg_vm_gb=avg_vm_gb)
