"""
OpenShift Container Platform API — cluster bağlantısı, envanter (node/proje/workload) ve AIOps özet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.inventory_guard import require_integrations_inventory
from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TestConnectionRequest(BaseModel):
    api_url: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = False


class ClusterCreate(BaseModel):
    name: str
    api_url: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = False


class ClusterUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cluster_dict(c: OpenShiftCluster) -> dict:
    from app.services.openshift_sync_service import get_sync_job
    cc = c.connection_config or {}
    return {
        "id": c.id,
        "name": c.name,
        "api_url": c.api_url,
        "auth_method": "credentials" if cc.get("username") else "token",
        "username": cc.get("username") or "",
        "has_token": bool(cc.get("token")),
        "verify_ssl": bool(cc.get("verify_ssl", False)),
        "status": c.status,
        "version": c.version,
        "sync_job": get_sync_job(c) or None,
        "last_sync": c.last_sync.isoformat() if c.last_sync else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _node_dict(n: OpenShiftNode) -> dict:
    return {
        "id": n.id, "cluster_id": n.cluster_id, "name": n.name, "role": n.role,
        "status": n.status, "cpu_cores": n.cpu_cores, "memory_gb": n.memory_gb,
        "kubelet_version": n.kubelet_version, "os_image": n.os_image, "pod_count": n.pod_count,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


def _project_dict(p: OpenShiftProject) -> dict:
    meta = p.meta_data or {}
    return {
        "id": p.id, "cluster_id": p.cluster_id, "name": p.name, "status": p.status,
        "display_name": p.display_name, "requester": p.requester,
        "pod_count": p.pod_count, "deployment_count": p.deployment_count, "route_count": p.route_count,
        "is_system": bool(meta.get("is_system", False)),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _workload_dict(w: OpenShiftWorkload) -> dict:
    return {
        "id": w.id, "cluster_id": w.cluster_id, "project": w.project, "kind": w.kind, "name": w.name,
        "status": w.status, "node_name": w.node_name, "restart_count": w.restart_count,
        "ready": w.ready, "host": w.host,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


# ── Test connection ───────────────────────────────────────────────────────────

@router.post("/test-connection")
async def test_connection(data: TestConnectionRequest):
    try:
        from app.services.openshift.ocp_client import OpenShiftClient
        token = (data.token or "").strip()
        client = OpenShiftClient(
            api_url=data.api_url,
            token=token,
            username=data.username if not token else "",
            password=data.password if not token else "",
            verify_ssl=data.verify_ssl,
        )
        ok, detail = client.test_connection()
        if ok:
            return {"success": True, "message": "OpenShift bağlantısı başarılı", "details": ""}
        return {"success": False, "message": "OpenShift bağlantı hatası", "details": detail or "Yanıt alınamadı"}
    except Exception as e:
        return {"success": False, "message": "OpenShift bağlantı hatası", "details": str(e)}


# ── Cluster CRUD ──────────────────────────────────────────────────────────────

@router.get("/clusters")
async def list_clusters(db: Session = Depends(get_db)):
    clusters = db.query(OpenShiftCluster).order_by(OpenShiftCluster.name).all()
    return {"clusters": [_cluster_dict(c) for c in clusters], "total": len(clusters)}


@router.post("/clusters", status_code=201)
async def create_cluster(body: ClusterCreate, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    existing = db.query(OpenShiftCluster).filter(OpenShiftCluster.name == body.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{body.name}' adında bir cluster zaten var")

    token = (body.token or "").strip()
    connection_config: Dict[str, Any] = {"api_url": body.api_url.strip(), "verify_ssl": body.verify_ssl}
    if token:
        connection_config["token"] = token
    elif body.username and body.password:
        connection_config["username"] = body.username
        connection_config["password"] = body.password
    else:
        raise HTTPException(status_code=400, detail="Bearer Token veya kullanıcı adı/şifre gerekli")

    cluster = OpenShiftCluster(
        name=body.name,
        api_url=body.api_url.strip(),
        connection_config=connection_config,
        status="unknown",
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return _cluster_dict(cluster)


@router.put("/clusters/{cluster_id}")
async def update_cluster(cluster_id: int, body: ClusterUpdate, db: Session = Depends(get_db)):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    cc = dict(cluster.connection_config or {})
    if body.name is not None:
        cluster.name = body.name
    if body.api_url is not None:
        cluster.api_url = body.api_url.strip()
        cc["api_url"] = body.api_url.strip()
    if body.token:
        cc["token"] = body.token
        cc.pop("username", None)
        cc.pop("password", None)
    elif body.username and body.password:
        cc["username"] = body.username
        cc["password"] = body.password
        cc.pop("token", None)
    if body.verify_ssl is not None:
        cc["verify_ssl"] = body.verify_ssl
    cluster.connection_config = cc
    db.commit()
    db.refresh(cluster)
    return _cluster_dict(cluster)


@router.delete("/clusters/{cluster_id}")
async def delete_cluster(cluster_id: int, request: Request, db: Session = Depends(get_db)):
    require_integrations_inventory(request)
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    db.delete(cluster)
    db.commit()
    return {"deleted": True, "cluster_id": cluster_id}


@router.get("/clusters/{cluster_id}/sync-status")
async def cluster_sync_status(cluster_id: int, db: Session = Depends(get_db)):
    from app.services.openshift_sync_service import get_sync_job
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    node_count = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == cluster_id).count()
    project_count = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == cluster_id).count()
    return {
        "cluster_id": cluster.id, "cluster_name": cluster.name, "status": cluster.status,
        "sync_job": get_sync_job(cluster), "node_count": node_count, "project_count": project_count,
    }


@router.post("/clusters/{cluster_id}/sync")
async def sync_cluster(cluster_id: int, request: Request, background: bool = True, db: Session = Depends(get_db)):
    """Cluster envanterini (node/proje/workload) ve olaylarını senkronize et."""
    require_integrations_inventory(request)
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")

    from app.services.openshift_sync_service import sync_openshift_cluster, update_sync_job, get_sync_job

    if background:
        job = get_sync_job(cluster)
        if job.get("status") == "running":
            return {"success": True, "started": False, "background": True, "message": "Tarama zaten devam ediyor", "sync_job": job}

        update_sync_job(cluster.id, status="running", phase="queued", percent=1, message="Tarama kuyruğa alındı...", error=None)

        import threading
        from app.core.database import ThreadSessionLocal

        cid = cluster.id
        cname = cluster.name

        def _worker():
            wdb = ThreadSessionLocal()
            try:
                c = wdb.query(OpenShiftCluster).filter(OpenShiftCluster.id == cid).first()
                if not c:
                    return
                sync_openshift_cluster(wdb, c, track_progress=True)
                wdb.commit()
                from app.services.openshift_event_collector import sync_openshift_events_for_cluster
                sync_openshift_events_for_cluster(wdb, c, hours=48)
            except Exception as exc:
                logger.exception("background OpenShift sync failed (cluster=%s)", cid)
                wdb.rollback()
                update_sync_job(cid, status="error", phase="error", percent=100, message=str(exc)[:300], error=str(exc)[:300])
            finally:
                wdb.close()

        threading.Thread(target=_worker, name=f"openshift-sync-{cid}", daemon=True).start()
        return {"success": True, "started": True, "background": True, "cluster_id": cid, "cluster": cname, "message": "Senkronizasyon başlatıldı"}

    result = sync_openshift_cluster(db, cluster, track_progress=True)
    db.commit()
    return {"success": len(result.get("errors") or []) == 0, "background": False, "cluster": cluster.name, **result}


# ── Envanter ───────────────────────────────────────────────────────────────

@router.get("/nodes")
async def list_nodes(cluster_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(OpenShiftNode)
    if cluster_id:
        q = q.filter(OpenShiftNode.cluster_id == cluster_id)
    nodes = q.order_by(OpenShiftNode.role, OpenShiftNode.name).all()
    return {"nodes": [_node_dict(n) for n in nodes], "total": len(nodes)}


@router.get("/projects")
async def list_projects(cluster_id: Optional[int] = None, include_system: bool = False, db: Session = Depends(get_db)):
    q = db.query(OpenShiftProject)
    if cluster_id:
        q = q.filter(OpenShiftProject.cluster_id == cluster_id)
    projects = q.order_by(OpenShiftProject.name).all()
    if not include_system:
        projects = [p for p in projects if not (p.meta_data or {}).get("is_system")]
    return {"projects": [_project_dict(p) for p in projects], "total": len(projects)}


@router.get("/workloads")
async def list_workloads(
    cluster_id: Optional[int] = None,
    project: Optional[str] = None,
    kind: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(OpenShiftWorkload)
    if cluster_id:
        q = q.filter(OpenShiftWorkload.cluster_id == cluster_id)
    if project:
        q = q.filter(OpenShiftWorkload.project == project)
    if kind:
        q = q.filter(OpenShiftWorkload.kind == kind)
    items = q.order_by(OpenShiftWorkload.project, OpenShiftWorkload.name).limit(2000).all()
    return {"workloads": [_workload_dict(w) for w in items], "total": len(items)}


# ── AIOps Komuta Merkezi ──────────────────────────────────────────────────────

@router.get("/ops/summary")
async def openshift_ops_summary(db: Session = Depends(get_db)):
    """Navbar badge — OpenShift olay özeti."""
    from app.api.ops_center import _active_events, ACTIVE_WINDOW_HOURS

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = _active_events(db, since, platform="openshift")
    critical = sum(1 for e in events if e.severity in ("critical", "emergency"))
    warning = sum(1 for e in events if e.severity == "warning")

    clusters = db.query(OpenShiftCluster).all()
    unhealthy = sum(1 for c in clusters if c.status == "ERROR")

    return {
        "critical": critical,
        "warning": warning + unhealthy,
        "total": critical + warning + unhealthy,
        "action_needed": critical > 0 or unhealthy > 0,
        "cluster_count": len(clusters),
        "unhealthy_clusters": unhealthy,
    }


@router.get("/ops/command-center")
async def openshift_command_center(db: Session = Depends(get_db)):
    """Cluster durumu, node sağlığı ve son olaylar."""
    from app.api.ops_center import _active_events, ACTIVE_WINDOW_HOURS

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = _active_events(db, since, platform="openshift")

    clusters = db.query(OpenShiftCluster).all()
    cluster_summaries: List[Dict[str, Any]] = []
    for c in clusters:
        nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id).all()
        not_ready = [n for n in nodes if (n.status or "").lower() != "ready"]
        projects = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == c.id).count()
        cluster_summaries.append({
            "id": c.id,
            "name": c.name,
            "api_url": c.api_url,
            "status": c.status,
            "version": c.version,
            "node_count": len(nodes),
            "not_ready_nodes": [n.name for n in not_ready],
            "project_count": projects,
            "last_sync": c.last_sync.isoformat() if c.last_sync else None,
        })

    critical_events = [e for e in events if e.severity in ("critical", "emergency")]
    warning_events = [e for e in events if e.severity == "warning"]

    def _ev_dict(e) -> dict:
        raw = e.raw_data or {}
        return {
            "id": e.id, "title": e.title, "severity": e.severity,
            "cluster_name": raw.get("cluster_name"), "namespace": raw.get("namespace"),
            "source_object": raw.get("source_object"), "last_seen": e.last_seen.isoformat() if e.last_seen else None,
        }

    return {
        "clusters": cluster_summaries,
        "critical_events": [_ev_dict(e) for e in critical_events[:50]],
        "warning_events": [_ev_dict(e) for e in warning_events[:50]],
        "total_events": len(events),
        "generated_at": datetime.utcnow().isoformat(),
    }
