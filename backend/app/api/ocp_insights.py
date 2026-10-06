"""OpenShift karar katmanı API'si — /api/v1/ocp-insights (modül: openshift).

Aynı bulgu motoru (platform="ocp", source_id=openshift_clusters.id).
Okumalar salt-okunur; yazma yalnız bulgu istisnası (DB içi) ve tur tetikleme.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import client_ip, require_module, require_role
from app.core.database import get_db
from app.models.infra_finding import InfraCheckRun, InfraFinding, InfraFindingException
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()
_module = require_module("openshift")
PLATFORM = "ocp"


def _locale(request: Request) -> str:
    return "en" if (request.headers.get("accept-language") or "").lower().startswith("en") else "tr"


def _audit(db: Session, user: User, action: str, summary: str, request: Request, **detail: Any) -> None:
    try:
        from app.services.audit import record_audit
        record_audit(db, category="ocp_insights", action=action, actor=user, summary=summary,
                     detail=detail or None, ip_address=client_ip(request))
    except Exception:
        logger.debug("audit yazılamadı", exc_info=True)


def _run_dict(r: Optional[InfraCheckRun]) -> Optional[Dict[str, Any]]:
    if not r:
        return None
    return {"id": r.id, "source_id": r.source_id, "source_name": r.source_name, "status": r.status,
            "error": r.error, "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.findings.store import summarize_findings
    from app.services.ocp_insights import latest_stats
    clusters = []
    for s in latest_stats(db):
        st = s["stats"] or {}
        clusters.append({"cluster_id": s["cluster_id"], "cluster": s["cluster"], "as_of": s["as_of"],
                         "version": st.get("version") or s["version"],
                         "n_plus_one": (st.get("capacity") or {}).get("n_plus_one"),
                         "request_pct": (st.get("capacity") or {}).get("request_pct"),
                         "reclaim": (st.get("reclaim") or {}).get("summary"),
                         "compliance": st.get("compliance")})
    last = (db.query(InfraCheckRun).filter(InfraCheckRun.platform == PLATFORM)
            .order_by(InfraCheckRun.started_at.desc()).first())
    return {"ok": True, "findings": summarize_findings(db, platforms=[PLATFORM]), "clusters": clusters,
            "last_run": _run_dict(last)}


@router.get("/capacity")
def capacity(cluster_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.ocp_insights import latest_stats
    return {"ok": True, "clusters": [{"cluster_id": s["cluster_id"], "cluster": s["cluster"], "as_of": s["as_of"],
                                      **((s["stats"] or {}).get("capacity") or {})}
                                     for s in latest_stats(db, cluster_id)]}


@router.get("/reclaim")
def reclaim(cluster_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.ocp_insights import latest_stats
    return {"ok": True, "clusters": [{"cluster_id": s["cluster_id"], "cluster": s["cluster"], "as_of": s["as_of"],
                                      **((s["stats"] or {}).get("reclaim") or {})}
                                     for s in latest_stats(db, cluster_id)]}


@router.get("/findings")
def findings(request: Request, category: Optional[str] = None,
             categories: Optional[str] = Query(None, description="virgülle ayrılmış"),
             cluster_id: Optional[int] = None, result: Optional[str] = "fail",
             severity_min: Optional[str] = None, include_excepted: bool = False,
             entity: Optional[str] = None, check_id: Optional[str] = None, limit: int = 1000,
             db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.findings.store import query_findings
    rows = query_findings(db, category=category, categories=[c for c in (categories or "").split(",") if c] or None,
                          platform=PLATFORM, source_id=cluster_id, result=result, severity_min=severity_min,
                          include_excepted=include_excepted, entity=entity, check_id=check_id, limit=limit,
                          locale=_locale(request))
    return {"findings": rows, "count": len(rows)}


class SimulateRequest(BaseModel):
    cluster_id: int
    drain_nodes: list[str] = Field(default_factory=list, max_length=50)
    cpu_cores: float = Field(0, ge=0, le=1024)
    memory_gb: float = Field(0, ge=0, le=16384)
    count: int = Field(0, ge=0, le=10000)


@router.post("/capacity/simulate")
def capacity_simulate(body: SimulateRequest, db: Session = Depends(get_db), user: User = Depends(_module)):
    """Drain + yeni iş yükü senaryosu (son tarama özetinden; canlı API çağrısı yok)."""
    from app.services.ocp_capacity_sim import simulate
    from app.services.ocp_insights import latest_stats
    st = latest_stats(db, body.cluster_id)
    if not st:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    res = simulate((st[0]["stats"] or {}).get("capacity") or {}, drain=body.drain_nodes,
                   cpu_cores=body.cpu_cores, memory_gb=body.memory_gb, count=body.count)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "Senaryo hesaplanamadı")
    res["cluster_id"], res["cluster"], res["as_of"] = st[0]["cluster_id"], st[0]["cluster"], st[0]["as_of"]
    return res


@router.get("/node-risk")
def node_risk(days: int = Query(7, ge=1, le=90), cluster_id: Optional[int] = None,
              db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.ocp_capacity_sim import node_risk as _risk
    return _risk(db, days=days, cluster_id=cluster_id)


@router.get("/changes")
def changes(days: int = Query(30, ge=1, le=365), cluster_id: Optional[int] = None,
            entity_kind: Optional[str] = None, entity: Optional[str] = None, limit: int = Query(300, ge=1, le=2000),
            db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.virt_config_drift import list_changes
    rows = list_changes(db, days=days, platform=PLATFORM, source_id=cluster_id, entity_kind=entity_kind,
                        entity=entity, limit=limit)
    return {"changes": rows, "count": len(rows)}


class BaselineRequest(BaseModel):
    cluster_id: Optional[int] = None  # boş = tüm cluster'lar
    entity_kind: Optional[str] = None
    entity_ref: Optional[str] = None


@router.post("/baseline")
def baseline(body: BaselineRequest, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_role("operator"))):
    from app.services.virt_config_drift import set_baseline
    n = set_baseline(db, platform=PLATFORM, source_id=body.cluster_id, entity_kind=body.entity_kind,
                     entity_ref=body.entity_ref, user=user.username)
    db.commit()
    _audit(db, user, "ocp_insights.baseline", f"Baseline işaretlendi ({n} varlık)", request, **body.model_dump())
    return {"ok": True, "count": n}


@router.get("/incident-timeline/{incident_id}")
def incident_timeline(incident_id: int, before_min: int = Query(120, ge=5, le=2880),
                      after_min: int = Query(60, ge=0, le=720), live: bool = True,
                      db: Session = Depends(get_db), user: User = Depends(_module)):
    from app.services.ocp_incident_timeline import build_ocp_incident_timeline
    res = build_ocp_incident_timeline(db, incident_id=incident_id, before_min=before_min,
                                      after_min=after_min, live_read=live)
    if not res.get("ok") and res.get("not_found"):
        raise HTTPException(status_code=404, detail=res.get("error") or "Olay bulunamadı")
    return res


class RunRequest(BaseModel):
    cluster_id: Optional[int] = None


@router.post("/run")
def run_now(body: RunRequest, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require_role("admin"))):
    def _job(cid):
        from app.core.database import SessionLocal
        from app.services.ocp_insights import run_ocp_cycle
        s = SessionLocal()
        try:
            run_ocp_cycle(s, cid)
        except Exception:
            logger.exception("OCP insights turu başarısız")
        finally:
            s.close()
    threading.Thread(target=_job, args=(body.cluster_id,), daemon=True, name="ocp-insights").start()
    _audit(db, user, "ocp_insights.run", "OpenShift karar katmanı turu başlatıldı", request, cluster_id=body.cluster_id)
    return {"ok": True, "queued": "thread"}


class ExceptionRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=2000)
    expires_days: Optional[int] = Field(None, ge=1, le=3650)


def _finding(db: Session, finding_id: int) -> InfraFinding:
    row = db.query(InfraFinding).filter(InfraFinding.id == finding_id, InfraFinding.platform == PLATFORM).first()
    if not row:
        raise HTTPException(status_code=404, detail="Bulgu bulunamadı")
    return row


@router.post("/findings/{finding_id}/exception")
def add_exception(finding_id: int, body: ExceptionRequest, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_role("admin"))):
    row = _finding(db, finding_id)
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
    _audit(db, user, "ocp_insights.exception_add", f"İstisna: {row.title} / {row.entity_name}", request,
           finding_id=row.id, reason=ex.reason)
    return {"ok": True, "exception_id": ex.id}


@router.delete("/findings/{finding_id}/exception")
def remove_exception(finding_id: int, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_role("admin"))):
    row = _finding(db, finding_id)
    n = (db.query(InfraFindingException)
         .filter(InfraFindingException.platform == row.platform, InfraFindingException.source_id == row.source_id,
                 InfraFindingException.entity_ref == row.entity_ref,
                 InfraFindingException.check_id == row.check_id).delete(synchronize_session=False))
    db.commit()
    _audit(db, user, "ocp_insights.exception_remove", f"İstisna kaldırıldı: {row.title}", request, finding_id=row.id)
    return {"ok": True, "removed": n}
