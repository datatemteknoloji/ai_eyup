"""
OpenShift Container Platform API — cluster bağlantısı, envanter (node/proje/workload) ve AIOps özet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.inventory_guard import require_integrations_inventory
from app.core.auth import require_role
from app.models.user import User
from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.services.audit import record_audit

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
    meta = n.meta_data or {}
    return {
        "id": n.id, "cluster_id": n.cluster_id, "name": n.name, "role": n.role,
        "status": n.status, "cpu_cores": n.cpu_cores, "memory_gb": n.memory_gb,
        "cpu_usage_pct": n.cpu_usage_pct, "memory_usage_pct": n.memory_usage_pct,
        "cpu_allocatable": meta.get("cpu_allocatable"),
        "memory_allocatable_gb": meta.get("memory_allocatable_gb"),
        "cpu_requested": meta.get("cpu_requested"),
        "memory_requested_gb": meta.get("memory_requested_gb"),
        "internal_ip": meta.get("internal_ip") or "",
        "external_ip": meta.get("external_ip") or "",
        "hostname": meta.get("hostname") or n.name,
        "ip_address": meta.get("ip_address") or meta.get("internal_ip") or "",
        "kubelet_version": n.kubelet_version, "os_image": n.os_image, "pod_count": n.pod_count or 0,
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
    from app.services.openshift_health import is_risk_pod, risk_severity
    meta = w.meta_data or {}
    risk = is_risk_pod(w)
    return {
        "id": w.id, "cluster_id": w.cluster_id, "project": w.project, "kind": w.kind, "name": w.name,
        "status": w.status, "node_name": w.node_name, "restart_count": w.restart_count,
        "ready": w.ready, "host": w.host,
        "reason": meta.get("reason"),
        "owner_kind": meta.get("owner_kind"),
        "owner_name": meta.get("owner_name"),
        "to_service": meta.get("to_service"),
        "is_risk": risk,
        "risk_severity": risk_severity(w) if risk else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


# ── Test connection ───────────────────────────────────────────────────────────

@router.post("/test-connection")
def test_connection(data: TestConnectionRequest):
    # NOT: kasıtlı olarak senkron `def` — OpenShiftClient.test_connection() senkron/
    # bloklayan bir REST çağrısı yapar; async def olsaydı yanlış/erişilemeyen bir
    # API URL'de event loop timeout süresi boyunca kilitlenirdi (bkz. hypervisors.py
    # /test-connection'daki aynı düzeltme).
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
async def create_cluster(
    body: ClusterCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
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

    from app.services.openshift.cluster_ops import seal_cluster_config
    connection_config = seal_cluster_config(connection_config)

    cluster = OpenShiftCluster(
        name=body.name,
        api_url=body.api_url.strip(),
        connection_config=connection_config,
        status="unknown",
    )
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    record_audit(
        db,
        category="openshift",
        action="cluster.create",
        status="success",
        actor=admin,
        summary=f"OpenShift küme eklendi: {cluster.name}",
        target_type="openshift_cluster",
        target_id=cluster.id,
        detail={"api_url": cluster.api_url},
        ip_address=request.client.host if request.client else None,
    )
    return _cluster_dict(cluster)


@router.put("/clusters/{cluster_id}")
async def update_cluster(
    cluster_id: int,
    body: ClusterUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    require_integrations_inventory(request)
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
    from app.services.openshift.cluster_ops import seal_cluster_config
    cluster.connection_config = seal_cluster_config(cc)
    db.commit()
    db.refresh(cluster)
    record_audit(
        db,
        category="openshift",
        action="cluster.update",
        status="success",
        actor=admin,
        summary=f"OpenShift küme güncellendi: {cluster.name}",
        target_type="openshift_cluster",
        target_id=cluster.id,
        detail={"token_updated": bool(body.token), "api_url": cluster.api_url},
        ip_address=request.client.host if request.client else None,
    )
    return _cluster_dict(cluster)


@router.delete("/clusters/{cluster_id}")
async def delete_cluster(
    cluster_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    require_integrations_inventory(request)
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    name = cluster.name
    db.delete(cluster)
    db.commit()
    record_audit(
        None,
        category="openshift",
        action="cluster.delete",
        status="success",
        actor=admin,
        summary=f"OpenShift bağlantısı silindi: {name}",
        target_type="openshift_cluster",
        target_id=cluster_id,
        ip_address=request.client.host if request.client else None,
    )
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
def sync_cluster(cluster_id: int, request: Request, background: bool = True, db: Session = Depends(get_db)):
    """
    Cluster envanterini (node/proje/workload) ve olaylarını senkronize et.

    NOT: kasıtlı olarak senkron `def` — background=false dalı senkron/bloklayan
    OpenShift REST çağrıları yapar (event loop'u kilitlemesin diye).
    """
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
                try:
                    from app.services.openshift_event_collector import sync_openshift_events_for_cluster
                    sync_openshift_events_for_cluster(wdb, c, hours=48)
                    wdb.commit()
                except Exception as exc:
                    logger.exception("OpenShift event sync failed (cluster=%s)", cid)
                    wdb.rollback()
            except Exception as exc:
                logger.exception("background OpenShift sync failed (cluster=%s)", cid)
                wdb.rollback()
                try:
                    update_sync_job(cid, status="error", phase="error", percent=100, message=str(exc)[:300], error=str(exc)[:300])
                except Exception:
                    pass
            finally:
                wdb.close()

        threading.Thread(target=_worker, name=f"openshift-sync-{cid}", daemon=True).start()
        return {"success": True, "started": True, "background": True, "cluster_id": cid, "cluster": cname, "message": "Senkronizasyon başlatıldı"}

    result = sync_openshift_cluster(db, cluster, track_progress=True)
    db.commit()
    return {"success": len(result.get("errors") or []) == 0, "background": False, "cluster": cluster.name, **result}


# ── Envanter ───────────────────────────────────────────────────────────────

@router.get("/health-board")
async def health_board(cluster_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Cluster health board — risk, NotReady, kapasite özeti."""
    from app.services.openshift_health import build_health_board
    return build_health_board(db, cluster_id=cluster_id)


@router.get("/risks")
async def list_risks(cluster_id: Optional[int] = None, limit: int = 100, db: Session = Depends(get_db)):
    from app.services.openshift_health import list_risk_workloads
    items = list_risk_workloads(db, cluster_id=cluster_id, limit=min(max(limit, 1), 500))
    return {"risks": [_workload_dict(w) for w in items], "total": len(items)}


@router.get("/clusters/{cluster_id}/topology")
def project_topology(cluster_id: int, project: str, db: Session = Depends(get_db)):
    """Canlı topology: Route → Service → Deployment → Pod → Node (seçili proje)."""
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    if not (project or "").strip():
        raise HTTPException(status_code=400, detail="project parametresi gerekli")

    from app.services.openshift.cluster_ops import client_from_cluster
    client = client_from_cluster(cluster)
    try:
        topo = client.get_project_topology(project.strip())
        topo["cluster_id"] = cluster_id
        topo["cluster_name"] = cluster.name
        return topo
    except Exception as e:
        logger.exception("topology error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/overview")
def cluster_overview_api(
    cluster_id: int,
    fresh: bool = False,
    db: Session = Depends(get_db),
):
    """Cluster overview — Redis TTL cache (varsayılan 30s). fresh=1 ile bypass."""
    import json

    cache_key = f"ainew:ocp:overview:{cluster_id}"
    if not fresh:
        try:
            from app.core.redis_client import get_redis

            r = get_redis()
            if r is not None:
                cached = r.get(cache_key)
                if cached:
                    logger.info("ocp overview cache hit cluster_id=%s", cluster_id)
                    return json.loads(cached)
        except Exception as exc:
            logger.debug("ocp overview cache read skip: %s", exc)

    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        result = cluster_ops.cluster_overview(client, cluster)
    except Exception as e:
        logger.exception("overview error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()

    try:
        from app.core.redis_client import get_redis
        from app.services.runtime_settings import get_setting

        ttl = int(get_setting("ocp_overview_cache_ttl_sec") or 30)
        if ttl > 0:
            r = get_redis()
            if r is not None:
                r.setex(
                    cache_key,
                    ttl,
                    json.dumps(result, ensure_ascii=False, default=str),
                )
                logger.info("ocp overview cache miss→set cluster_id=%s ttl=%s", cluster_id, ttl)
    except Exception as exc:
        logger.debug("ocp overview cache write skip: %s", exc)

    return result


@router.get("/monitoring/overview")
def ocp_monitoring_overview(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Cluster monitoring özeti — metrics.k8s.io → Timescale. Prometheus yok."""
    from app.services.openshift.ocp_monitoring import build_overview
    try:
        return build_overview(db, cluster_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("ocp monitoring overview")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.get("/monitoring/objects")
def ocp_monitoring_objects(
    cluster_id: int,
    kind: str = "node",
    q: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Node / Pod / VM seçici."""
    from app.services.openshift.ocp_monitoring import list_objects
    try:
        return list_objects(db, cluster_id=cluster_id, kind=kind, q=q, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("ocp monitoring objects")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.get("/monitoring/metrics")
def ocp_monitoring_metrics(kind: str = "node"):
    """Grafik preset whitelist."""
    from app.services.openshift.ocp_monitoring import metric_catalog
    try:
        return {"ok": True, "kind": kind, "metrics": metric_catalog(kind)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/monitoring/series")
def ocp_monitoring_series(
    cluster_id: int,
    kind: str = "node",
    names: str = "",
    metric: str = "cpu_pct",
    range: str = "8h",
    db: Session = Depends(get_db),
):
    """Seçili nesnelerin Timescale serisi."""
    from app.services.openshift.ocp_monitoring import parse_names, query_series
    try:
        return query_series(
            db,
            cluster_id=cluster_id,
            kind=kind,
            names=parse_names(names),
            metric=metric,
            range_key=range,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("ocp monitoring series")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.post("/monitoring/sync")
def ocp_monitoring_sync(
    cluster_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """metrics.k8s.io örneklerini Timescale'e yaz (manuel tetik)."""
    from app.services.openshift.ocp_monitoring import sync_all_ocp_monitoring_metrics, sync_cluster_metrics
    try:
        if cluster_id is not None:
            cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
            if not cluster:
                raise HTTPException(status_code=404, detail="Cluster bulunamadı")
            return {"ok": True, **sync_cluster_metrics(db, cluster)}
        return {"ok": True, **sync_all_ocp_monitoring_metrics(db)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ocp monitoring sync")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


# ── Prometheus mode (Kubernetes Views default · GPU · KubeVirt) ─────────────

@router.get("/monitoring/prom/overview")
def ocp_prom_overview(source_id: Optional[str] = None, db: Session = Depends(get_db)):
    from app.services.openshift.ocp_prom_monitoring import overview
    return overview(db, source_id=source_id)


@router.get("/monitoring/prom/templates")
def ocp_prom_templates():
    from app.services.openshift.ocp_prom_monitoring import templates
    return {"ok": True, "templates": templates()}


@router.get("/monitoring/prom/catalog")
def ocp_prom_catalog(family: Optional[str] = None):
    from app.services.openshift.ocp_prom_monitoring import catalog
    return {"ok": True, "metrics": catalog(family)}


@router.get("/monitoring/prom/labels")
def ocp_prom_labels(
    kind: str = "namespace",
    namespace: Optional[str] = None,
    source_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.services.openshift.ocp_prom_monitoring import label_options
    return label_options(kind, namespace=namespace, source_id=source_id, db=db)


@router.get("/monitoring/prom/views")
def ocp_prom_views(
    view: str = "global",
    range_sec: int = 900,
    source_id: Optional[str] = None,
    top_n: int = 6,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.services.openshift.ocp_prom_monitoring import views_bundle
    try:
        return views_bundle(
            view,
            range_sec=range_sec,
            source_id=source_id,
            db=db,
            top_n=top_n,
            namespace=namespace,
            node=node,
            pod=pod,
            instance=instance,
        )
    except Exception as e:
        logger.exception("ocp monitoring views")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.get("/monitoring/prom/allocation")
def ocp_prom_allocation(source_id: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db)):
    from app.services.openshift.ocp_prom_monitoring import allocation_table
    return allocation_table(db, source_id=source_id, limit=limit)


@router.get("/monitoring/prom/series")
def ocp_prom_series(
    metric: str = "gpu_util",
    range_sec: int = 900,
    source_id: Optional[str] = None,
    top_n: int = 8,
    namespace: Optional[str] = None,
    node: Optional[str] = None,
    pod: Optional[str] = None,
    instance: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.services.openshift.ocp_prom_monitoring import series
    try:
        return series(
            metric,
            range_sec=range_sec,
            source_id=source_id,
            db=db,
            top_n=top_n,
            namespace=namespace,
            node=node,
            pod=pod,
            instance=instance,
        )
    except Exception as e:
        logger.exception("ocp monitoring series")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.get("/clusters/{cluster_id}/monitoring")
def cluster_monitoring_api(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """Geriye uyumluluk — overview ile aynı."""
    from app.services.openshift.ocp_monitoring import build_overview
    try:
        return build_overview(db, cluster_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("ocp monitoring error cluster_id=%s", cluster_id)
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e


@router.get("/clusters/{cluster_id}/operators-health")
def cluster_operators_health(cluster_id: int, db: Session = Depends(get_db)):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.cluster_health(client)
    except Exception as e:
        logger.exception("operators-health error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/storage")
def cluster_storage(cluster_id: int, db: Session = Depends(get_db)):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.storage_overview(client)
    except Exception as e:
        logger.exception("storage error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


# ── Access / RBAC (READ-ONLY) ─────────────────────────────────────────────────

def _access_client(cluster_id: int, db: Session):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    return cluster, cluster_ops.client_from_cluster(cluster)


@router.get("/clusters/{cluster_id}/access/overview")
def access_overview(cluster_id: int, db: Session = Depends(get_db)):
    """Users/Groups/Roles/Bindings sayıları + OAuth IdP + token yetki teşhisi."""
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import access_overview as _ov
        return _ov(client)
    except Exception as e:
        logger.exception("access overview")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/access/list")
def access_list(
    cluster_id: int,
    kind: str,
    namespace: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """kind=users|groups|identities|roles|clusterroles|rolebindings|clusterrolebindings|serviceaccounts"""
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import list_access
        out = list_access(client, kind, namespace=namespace, q=q, limit=limit)
        if not out.get("ok") and out.get("error"):
            # Yetki yok → 200 + ok:false (UI göstersin); cluster yok değil
            return out
        return out
    except Exception as e:
        logger.exception("access list")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/access/get")
def access_get(
    cluster_id: int,
    kind: str,
    name: str,
    namespace: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import get_access
        out = get_access(client, kind, name, namespace=namespace)
        if not out.get("ok"):
            raise HTTPException(status_code=404, detail=out.get("error") or "bulunamadı")
        return out
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("access get")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/access/subject")
def access_subject(
    cluster_id: int,
    subject_kind: str = "User",
    subject_name: str = "",
    subject_namespace: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """User/Group/SA için RoleBinding + ClusterRoleBinding listesi."""
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import subject_bindings
        return subject_bindings(
            client,
            subject_kind=subject_kind,
            subject_name=subject_name,
            subject_namespace=subject_namespace,
            namespace=namespace,
            limit=limit,
        )
    except Exception as e:
        logger.exception("access subject")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/access/can-i")
def access_can_i(
    cluster_id: int,
    verb: str = "get",
    resource: str = "pods",
    api_group: str = "",
    namespace: Optional[str] = None,
    name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Kayıtlı cluster token SelfSubjectAccessReview."""
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import self_can_i
        return self_can_i(
            client, verb=verb, resource=resource, api_group=api_group,
            namespace=namespace, name=name,
        )
    except Exception as e:
        logger.exception("access can-i")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/access/identity-providers")
def access_identity_providers(cluster_id: int, db: Session = Depends(get_db)):
    _, client = _access_client(cluster_id, db)
    try:
        from app.services.openshift.ocp_access import identity_providers
        return identity_providers(client)
    except Exception as e:
        logger.exception("access idp")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/kubevirt/vms")
def cluster_kubevirt_vms(cluster_id: int, db: Session = Depends(get_db)):
    """KubeVirt VirtualMachine listesi (canlı) — proje, node, phase, CPU/mem, IP."""
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    kv = cluster_ops.kubevirt_client_from_cluster(cluster)
    try:
        ok, msg = kv.test_connection()
        if not ok and "KubeVirt API bulunamadı" in (msg or ""):
            return {"vms": [], "total": 0, "installed": False, "message": msg}
        if not ok:
            raise HTTPException(status_code=502, detail=msg or "KubeVirt bağlantı hatası")
        vms = kv.list_vms() or []
        return {"vms": vms, "total": len(vms), "installed": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("kubevirt vms list error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        kv.logout()


@router.get("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}")
def cluster_kubevirt_vm_detail(
    cluster_id: int, namespace: str, name: str, db: Session = Depends(get_db),
):
    """Tek VM detayı — disk→PVC→PV, NIC, guest OS, worker node."""
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    kv = cluster_ops.kubevirt_client_from_cluster(cluster)
    try:
        detail = kv.get_vm_full_details(f"{namespace}/{name}")
        if not detail:
            raise HTTPException(status_code=404, detail="VM bulunamadı veya KubeVirt erişilemiyor")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("kubevirt vm detail error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        kv.logout()


def _kv_cluster_client(cluster_id: int, db: Session):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    return cluster, cluster_ops.kubevirt_client_from_cluster(cluster)


class KvPowerBody(BaseModel):
    action: str  # start|stop|restart|power_on|power_off


class KvCloneBody(BaseModel):
    target_name: str


class KvSnapshotBody(BaseModel):
    snapshot_name: Optional[str] = None


class KvRestoreBody(BaseModel):
    snapshot_name: str


class KvPvcBody(BaseModel):
    namespace: str
    name: str
    size: str = "10Gi"
    storage_class: Optional[str] = None
    access_mode: str = "ReadWriteOnce"


class KvDiskBody(BaseModel):
    disk_name: str
    size: str = "20Gi"
    storage_class: Optional[str] = None


class KvNetworkBody(BaseModel):
    nad_name: str
    interface_name: str = "net1"


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/power")
def kubevirt_vm_power(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvPowerBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.power_action(kv, namespace, name, body.action, actor=admin.username)
        record_audit(
            db, category="openshift", action=f"kubevirt.power.{result.get('action')}",
            status="success", actor=admin,
            summary=f"VM {result.get('action')}: {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.delete("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}")
def kubevirt_vm_delete(
    cluster_id: int,
    namespace: str,
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.delete_vm(kv, namespace, name, actor=admin.username)
        record_audit(
            db, category="openshift", action="kubevirt.vm.delete", status="success",
            actor=admin, summary=f"VM silindi: {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/clone")
def kubevirt_vm_clone(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvCloneBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.clone_vm(kv, namespace, name, body.target_name, actor=admin.username)
        record_audit(
            db, category="openshift", action="kubevirt.vm.clone", status="success",
            actor=admin,
            summary=f"VM klon: {namespace}/{name} → {result.get('target')} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.get("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/snapshots")
def kubevirt_vm_snapshots(
    cluster_id: int, namespace: str, name: str, db: Session = Depends(get_db),
):
    from app.services.openshift import kubevirt_ops as kvops
    _, kv = _kv_cluster_client(cluster_id, db)
    try:
        return {"snapshots": kvops.list_snapshots(kv, namespace, name)}
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.get("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/clones")
def kubevirt_vm_clones(
    cluster_id: int, namespace: str, name: str, db: Session = Depends(get_db),
):
    from app.services.openshift import kubevirt_ops as kvops
    _, kv = _kv_cluster_client(cluster_id, db)
    try:
        return {"clones": kvops.list_clones(kv, namespace, name)}
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/snapshots")
def kubevirt_vm_snapshot_create(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvSnapshotBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.create_snapshot(
            kv, namespace, name, body.snapshot_name or "", actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.snapshot.create", status="success",
            actor=admin,
            summary=f"Snapshot: {result.get('name')} ← {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/snapshots/restore")
def kubevirt_vm_snapshot_restore(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvRestoreBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.restore_snapshot(
            kv, namespace, name, body.snapshot_name, actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.snapshot.restore", status="success",
            actor=admin,
            summary=f"Snapshot restore: {body.snapshot_name} → {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.delete("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/snapshots/{snapshot_name}")
def kubevirt_vm_snapshot_delete(
    cluster_id: int,
    namespace: str,
    name: str,
    snapshot_name: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.delete_snapshot(kv, namespace, snapshot_name, actor=admin.username)
        record_audit(
            db, category="openshift", action="kubevirt.snapshot.delete", status="success",
            actor=admin,
            summary=f"Snapshot silindi: {snapshot_name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/pvc")
def kubevirt_create_pvc(
    cluster_id: int,
    body: KvPvcBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    ns = (body.namespace or "").strip()
    if not ns:
        raise HTTPException(status_code=400, detail="namespace gerekli")
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.create_pvc(
            kv, ns, body.name, body.size,
            storage_class=body.storage_class, access_mode=body.access_mode,
            actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.pvc.create", status="success",
            actor=admin, summary=f"PVC: {ns}/{result.get('name')} ({cluster.name})",
            target_type="pvc", target_id=f"{ns}/{result.get('name')}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/disk")
def kubevirt_vm_add_disk(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvDiskBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.add_disk_datavolume(
            kv, namespace, name, body.disk_name, body.size,
            storage_class=body.storage_class, actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.disk.add", status="success",
            actor=admin,
            summary=f"Disk eklendi: {body.disk_name} → {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/network")
def kubevirt_vm_set_network(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvNetworkBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvops.set_multus_network(
            kv, namespace, name, body.nad_name,
            interface_name=body.interface_name, actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.network.set", status="success",
            actor=admin,
            summary=f"Network: {body.nad_name} → {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


class KvCdromBody(BaseModel):
    source_namespace: Optional[str] = None
    source_pvc: str
    boot_first: bool = False
    disk_name: Optional[str] = None


@router.get("/clusters/{cluster_id}/kubevirt/iso-sources")
def kubevirt_iso_sources(
    cluster_id: int,
    namespace: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """CD-ROM olarak bağlanabilecek PVC'ler (erişilebilen namespace'ler dahil)."""
    from app.services.openshift import kubevirt_media as kvmedia
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        return kvmedia.list_iso_sources(kv, namespace)
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.get("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/cdroms")
def kubevirt_vm_cdroms(
    cluster_id: int,
    namespace: str,
    name: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_media as kvmedia
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        return {"cdroms": kvmedia.list_vm_cdroms(kv, namespace, name)}
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/cdrom")
def kubevirt_vm_attach_cdrom(
    cluster_id: int,
    namespace: str,
    name: str,
    body: KvCdromBody,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_media as kvmedia
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvmedia.attach_cdrom(
            kv, namespace, name,
            source_namespace=(body.source_namespace or namespace),
            source_pvc=body.source_pvc,
            boot_first=body.boot_first,
            disk_name=body.disk_name or "",
            actor=admin.username,
        )
        record_audit(
            db, category="openshift", action="kubevirt.cdrom.attach", status="success",
            actor=admin,
            summary=(
                f"CD-ROM bağlandı: {body.source_namespace or namespace}/{body.source_pvc} "
                f"→ {namespace}/{name} ({cluster.name})"
            ),
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.delete("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/cdrom/{disk_name}")
def kubevirt_vm_eject_cdrom(
    cluster_id: int,
    namespace: str,
    name: str,
    disk_name: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import kubevirt_media as kvmedia
    from app.services.openshift import kubevirt_ops as kvops
    cluster, kv = _kv_cluster_client(cluster_id, db)
    try:
        result = kvmedia.eject_cdrom(kv, namespace, name, disk_name, actor=admin.username)
        record_audit(
            db, category="openshift", action="kubevirt.cdrom.eject", status="success",
            actor=admin,
            summary=f"CD-ROM çıkarıldı: {disk_name} ← {namespace}/{name} ({cluster.name})",
            target_type="kubevirt_vm", target_id=f"{namespace}/{name}",
            ip_address=request.client.host if request.client else None,
        )
        return result
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    finally:
        kv.logout()


@router.post("/clusters/{cluster_id}/kubevirt/iso-upload")
async def kubevirt_iso_upload(
    cluster_id: int,
    request: Request,
    namespace: str,
    name: str,
    storage_class: Optional[str] = None,
    size_gi: Optional[int] = None,
    attach_vm: Optional[str] = None,
    boot_first: bool = False,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """
    İstemci bilgisayardan ISO yükle: gövde ham ISO baytlarıdır (application/octet-stream).
    Akış bellekte biriktirilmeden CDI upload proxy'ye aktarılır.
    """
    from starlette.concurrency import run_in_threadpool
    from app.services.openshift import kubevirt_media as kvmedia
    from app.services.openshift import kubevirt_ops as kvops

    cl = request.headers.get("content-length") or ""
    if not cl.isdigit() or int(cl) <= 0:
        raise HTTPException(status_code=411, detail="Content-Length gerekli (dosya boyutu)")
    length = int(cl)
    ns = (namespace or "").strip()
    if not ns:
        raise HTTPException(status_code=400, detail="namespace gerekli")
    try:
        pname = kvops._k8s_name(name, "PVC adı")
        if attach_vm:
            kvops._k8s_name(attach_vm, "VM adı")
    except kvops.KubeVirtOpError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    need_gi = kvmedia.suggest_upload_size_gi(length)
    size = int(size_gi) if size_gi else need_gi
    if size * (1024 ** 3) < length:
        raise HTTPException(status_code=400, detail=f"Boyut yetersiz: en az {need_gi} GiB gerekli")

    cluster, kv = _kv_cluster_client(cluster_id, db)
    actor = admin.username
    ip = request.client.host if request.client else None
    verify = bool(getattr(cluster, "verify_ssl", False))

    def _prepare():
        kvmedia.create_upload_datavolume(kv, ns, pname, size, storage_class)
        try:
            kvmedia.wait_dv_phase(kv, ns, pname, ("UploadReady",), timeout=180)
            token = kvmedia.request_upload_token(kv, ns, pname)
            proxy = kvmedia.discover_upload_proxy(kv)
            return token, proxy
        except Exception:
            kvmedia.delete_datavolume(kv, ns, pname)
            raise

    def _finish():
        kvmedia.wait_dv_phase(kv, ns, pname, ("Succeeded",), timeout=600)
        if attach_vm:
            return kvmedia.attach_cdrom(
                kv, ns, attach_vm, ns, pname, boot_first=boot_first, actor=actor,
            )
        return None

    async def _body():
        async for chunk in request.stream():
            if chunk:
                yield chunk

    try:
        db.rollback()  # uzun yükleme boyunca DB bağlantısını havuza bırak
        try:
            token, proxy = await run_in_threadpool(_prepare)
        except kvops.KubeVirtOpError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        try:
            await kvmedia.stream_upload(proxy, token, _body(), length, verify=verify)
        except kvops.KubeVirtOpError as e:
            await run_in_threadpool(kvmedia.delete_datavolume, kv, ns, pname)
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001  (bağlantı kopması, TLS, vb.)
            logger.warning("ISO upload hatası %s/%s: %s", ns, pname, e)
            await run_in_threadpool(kvmedia.delete_datavolume, kv, ns, pname)
            raise HTTPException(status_code=502, detail=f"ISO yükleme kesildi: {e}") from e
        try:
            attached = await run_in_threadpool(_finish)
        except kvops.KubeVirtOpError as e:
            raise HTTPException(
                status_code=e.status_code,
                detail=f"ISO yüklendi ({ns}/{pname}) ancak sonraki adım başarısız: {e}",
            ) from e
        record_audit(
            db, category="openshift", action="kubevirt.iso.upload", status="success",
            actor=admin,
            summary=(
                f"ISO yüklendi: {ns}/{pname} ({length // (1024 * 1024)} MiB, {cluster.name})"
                + (f" → {attach_vm}" if attach_vm else "")
            ),
            target_type="pvc", target_id=f"{ns}/{pname}", ip_address=ip,
        )
        return {
            "ok": True,
            "namespace": ns,
            "pvc": pname,
            "size_gi": size,
            "bytes": length,
            "attached": attached,
        }
    finally:
        await run_in_threadpool(kv.logout)


@router.websocket("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/console")
async def kubevirt_vnc_console(
    websocket: WebSocket,
    cluster_id: int,
    namespace: str,
    name: str,
    token: str = "",
):
    """KubeVirt VNC — tarayıcı (noVNC) ↔ ainew ↔ cluster /vnc subresource.

    Atlas ile aynı jump modeli. SSH/guest parola yok; auth = OCP Bearer (proxy).
    JWT: ?token=  · noVNC subprotocol: binary · upstream: plain.kubevirt.io
    """
    import asyncio
    import ssl
    from urllib.parse import urlparse

    import websockets
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.core.security import decode_access_token
    from app.models.user import User
    from app.services.hypervisor_credentials import plain
    from app.services.openshift import cluster_ops

    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    upstream = None
    try:
        uid = payload.get("uid")
        user = (
            db.query(User).filter(User.id == uid, User.is_active == True).first()
            if uid is not None
            else None
        )
        if not user:
            await websocket.accept()
            await websocket.close(code=4401)
            return
        from app.core.auth import can_open_shell
        if not can_open_shell(user, db, "openshift", "operator"):
            await websocket.accept()
            await websocket.close(code=4403, reason="openshift modülü ve operator rolü gerekli")
            return

        cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if not cluster:
            await websocket.accept()
            await websocket.close(code=1011, reason="Cluster bulunamadı")
            return

        cc = cluster.connection_config or {}
        ocp_token = plain(cc.get("token") or "")
        if not ocp_token and cc.get("username") and cc.get("password"):
            kv = cluster_ops.kubevirt_client_from_cluster(cluster)
            ocp_token = kv.token or ""
            kv.logout()
        if not ocp_token:
            await websocket.accept()
            await websocket.close(code=1011, reason="Cluster token yok")
            return

        api_url = (cc.get("api_url") or cluster.api_url or "").rstrip("/")
        from app.services.host_resolve import rewrite_url_host
        resolved_api, _note, orig_host = rewrite_url_host(
            api_url if "://" in api_url else f"https://{api_url}"
        )
        parsed = urlparse(resolved_api)
        host = parsed.netloc or parsed.path
        vnc_url = (
            f"wss://{host}/apis/subresources.kubevirt.io/v1"
            f"/namespaces/{namespace}/virtualmachineinstances/{name}/vnc"
        )
        verify_ssl = bool(cc.get("verify_ssl", False))
        ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        # noVNC binary subprotocol
        await websocket.accept(subprotocol="binary")

        try:
            ws_headers = {"Authorization": f"Bearer {ocp_token}"}
            if orig_host:
                ws_headers["Host"] = orig_host
            connect_kwargs = dict(
                ssl=ssl_ctx,
                open_timeout=20,
                ping_interval=None,
                max_size=16 * 1024 * 1024,
                subprotocols=["plain.kubevirt.io"],
            )
            try:
                upstream = await websockets.connect(
                    vnc_url, additional_headers=ws_headers, **connect_kwargs
                )
            except TypeError:
                upstream = await websockets.connect(
                    vnc_url, extra_headers=ws_headers, **connect_kwargs
                )
        except Exception as e:
            logger.warning("kubevirt VNC connect failed: %s", e)
            err = str(e)
            reason = (
                "VNC yetkisi yok (403) — virtualmachineinstances/vnc get verin"
                if "403" in err
                else ("VM instance yok (404) — Running mi?" if "404" in err else err[:120])
            )
            try:
                await websocket.close(code=1011, reason=reason[:120])
            except Exception:
                pass
            return

        async def pump_up():
            try:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except Exception:
                pass

        async def pump_down():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    data = msg.get("bytes")
                    text = msg.get("text")
                    if data is not None:
                        await upstream.send(data)
                    elif text is not None:
                        await upstream.send(text.encode("utf-8", errors="replace"))
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        t1 = asyncio.create_task(pump_up())
        t2 = asyncio.create_task(pump_down())
        _done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("kubevirt VNC console error")
        try:
            await websocket.close(code=1011, reason=str(e)[:100])
        except Exception:
            pass
    finally:
        db.close()
        if upstream is not None:
            try:
                await upstream.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/console/serial")
async def kubevirt_serial_console(
    websocket: WebSocket,
    cluster_id: int,
    namespace: str,
    name: str,
    token: str = "",
):
    """Eski serial console (TTY login) — gerekirse yedek."""
    import asyncio
    import ssl
    from urllib.parse import urlparse

    import websockets
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.core.security import decode_access_token
    from app.models.user import User
    from app.services.hypervisor_credentials import plain
    from app.services.openshift import cluster_ops

    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.accept()
        await websocket.send_text("\r\n\033[31mYetkilendirme hatası.\033[0m\r\n")
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    upstream = None
    try:
        uid = payload.get("uid")
        user = (
            db.query(User).filter(User.id == uid, User.is_active == True).first()
            if uid is not None else None
        )
        if not user:
            await websocket.accept()
            await websocket.close(code=4401)
            return
        from app.core.auth import can_open_shell
        if not can_open_shell(user, db, "openshift", "operator"):
            await websocket.accept()
            await websocket.close(code=4403, reason="openshift modülü ve operator rolü gerekli")
            return
        cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if not cluster:
            await websocket.accept()
            await websocket.close()
            return
        cc = cluster.connection_config or {}
        ocp_token = plain(cc.get("token") or "")
        if not ocp_token and cc.get("username") and cc.get("password"):
            kv = cluster_ops.kubevirt_client_from_cluster(cluster)
            ocp_token = kv.token or ""
            kv.logout()
        if not ocp_token:
            await websocket.accept()
            await websocket.close()
            return
        api_url = (cc.get("api_url") or cluster.api_url or "").rstrip("/")
        from app.services.host_resolve import rewrite_url_host
        resolved_api, _note, orig_host = rewrite_url_host(
            api_url if "://" in api_url else f"https://{api_url}"
        )
        parsed = urlparse(resolved_api)
        host = parsed.netloc or parsed.path
        console_url = (
            f"wss://{host}/apis/subresources.kubevirt.io/v1"
            f"/namespaces/{namespace}/virtualmachineinstances/{name}/console"
        )
        ssl_ctx = ssl.create_default_context()
        if not bool(cc.get("verify_ssl", False)):
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        await websocket.accept()
        await websocket.send_text(
            f"\r\n\033[36mSerial · {namespace}/{name}\033[0m\r\n"
        )
        ws_headers = {"Authorization": f"Bearer {ocp_token}"}
        if orig_host:
            ws_headers["Host"] = orig_host
        try:
            try:
                upstream = await websockets.connect(
                    console_url, additional_headers=ws_headers, ssl=ssl_ctx,
                    open_timeout=20, ping_interval=None, max_size=8 * 1024 * 1024,
                )
            except TypeError:
                upstream = await websockets.connect(
                    console_url, extra_headers=ws_headers, ssl=ssl_ctx,
                    open_timeout=20, ping_interval=None, max_size=8 * 1024 * 1024,
                )
        except Exception as e:
            await websocket.send_text(f"\r\n\033[31m{e}\033[0m\r\n")
            await websocket.close()
            return
        try:
            await upstream.send(b"\r")
        except Exception:
            pass

        async def pump_up():
            try:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except Exception:
                pass

        async def pump_down():
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    data = msg.get("bytes")
                    text = msg.get("text")
                    if data is not None:
                        await upstream.send(data)
                    elif text is not None:
                        await upstream.send(text.encode("utf-8", errors="replace"))
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        t1 = asyncio.create_task(pump_up())
        t2 = asyncio.create_task(pump_down())
        _d, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("kubevirt serial console error")
    finally:
        db.close()
        if upstream is not None:
            try:
                await upstream.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/resource-kinds")
async def list_resource_kinds():
    from app.services.openshift.cluster_ops import resource_kinds
    return {"kinds": resource_kinds()}


@router.get("/clusters/{cluster_id}/resources")
def cluster_resources(
    cluster_id: int,
    kind: str,
    namespace: Optional[str] = None,
    db: Session = Depends(get_db),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.list_resources(client, kind, namespace=namespace)
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/resource-detail")
def cluster_resource_detail(
    cluster_id: int,
    kind: str,
    name: str,
    namespace: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Deployment/Pod/PVC/… Atlas tarzı detay (koşullar, env, pod’lar, olaylar)."""
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        detail = cluster_ops.resource_detail(client, kind, name, namespace=namespace)
        if not detail:
            raise HTTPException(status_code=404, detail="Kaynak bulunamadı veya yetki yok")
        return detail
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/resource-yaml")
def cluster_resource_yaml(
    cluster_id: int,
    kind: str,
    name: str,
    namespace: Optional[str] = None,
    db: Session = Depends(get_db),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.get_resource_yaml(client, kind, name, namespace=namespace)
    finally:
        client.logout()


class WorkloadActionBody(BaseModel):
    kind: str
    namespace: str
    name: str
    replicas: Optional[int] = None


@router.post("/clusters/{cluster_id}/workload/scale")
def workload_scale(
    cluster_id: int,
    body: WorkloadActionBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    if body.replicas is None:
        raise HTTPException(status_code=400, detail="replicas gerekli")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        result = cluster_ops.scale_workload(
            client, body.kind, body.namespace, body.name, int(body.replicas),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=403 if "403" in (result.get("error") or "") else 400,
                                detail=result.get("error") or "Ölçekleme başarısız")
        return result
    finally:
        client.logout()


@router.post("/clusters/{cluster_id}/workload/restart")
def workload_restart(
    cluster_id: int,
    body: WorkloadActionBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        result = cluster_ops.restart_workload(client, body.kind, body.namespace, body.name)
        if not result.get("ok"):
            raise HTTPException(status_code=403 if "403" in (result.get("error") or "") else 400,
                                detail=result.get("error") or "Yeniden başlatma başarısız")
        return result
    finally:
        client.logout()


@router.post("/clusters/{cluster_id}/pod/delete")
def pod_delete(
    cluster_id: int,
    body: WorkloadActionBody,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        result = cluster_ops.delete_pod(client, body.namespace, body.name)
        if not result.get("ok"):
            raise HTTPException(status_code=403 if "403" in (result.get("error") or "") else 400,
                                detail=result.get("error") or "Pod silinemedi")
        return result
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/network")
def cluster_network(cluster_id: int, db: Session = Depends(get_db)):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.network_overview(client)
    except Exception as e:
        logger.exception("network error")
        raise HTTPException(status_code=502, detail=str(e)[:300]) from e
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/pods/{namespace}/{pod}")
def cluster_pod_detail(cluster_id: int, namespace: str, pod: str, db: Session = Depends(get_db)):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        detail = cluster_ops.pod_detail(client, namespace, pod)
        if not detail:
            raise HTTPException(status_code=404, detail="Pod bulunamadı")
        return detail
    finally:
        client.logout()


@router.get("/clusters/{cluster_id}/pods/{namespace}/{pod}/logs")
def cluster_pod_logs(
    cluster_id: int,
    namespace: str,
    pod: str,
    container: Optional[str] = None,
    tail: int = 300,
    previous: bool = False,
    timestamps: bool = True,
    db: Session = Depends(get_db),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.pod_logs(
            client, namespace, pod,
            container=container, tail=tail, previous=previous, timestamps=timestamps,
        )
    finally:
        client.logout()


@router.websocket("/clusters/{cluster_id}/pods/{namespace}/{pod}/exec")
async def cluster_pod_exec(
    websocket: WebSocket,
    cluster_id: int,
    namespace: str,
    pod: str,
    token: str = "",
    container: str = "",
    shell: str = "/bin/sh",
):
    """Pod exec terminal — tarayıcı ↔ ainew ↔ kube API exec (Atlas protokolü).

    JWT: ?token=  · Opsiyonel: container=
    Upstream: v4.channel.k8s.io
    Tarayıcı → {"type":"input","data":"..."} | {"type":"resize","cols":N,"rows":M}
    Tarayıcı ← düz metin (stdout/stderr birleşik)
    """
    import asyncio
    import json
    import ssl
    from urllib.parse import quote, urlencode, urlparse

    import websockets
    from app.core.database import ThreadSessionLocal as SessionLocal
    from app.core.security import decode_access_token
    from app.models.user import User
    from app.services.hypervisor_credentials import plain
    from app.services.openshift import cluster_ops

    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.accept()
        await websocket.send_text("\r\n\033[31mYetkilendirme hatası.\033[0m\r\n")
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    upstream = None
    try:
        uid = payload.get("uid")
        user = (
            db.query(User).filter(User.id == uid, User.is_active == True).first()
            if uid is not None
            else None
        )
        if not user:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mKullanıcı bulunamadı.\033[0m\r\n")
            await websocket.close(code=4401)
            return
        from app.core.auth import can_open_shell
        if not can_open_shell(user, db, "openshift", "operator"):
            await websocket.accept()
            await websocket.close(code=4403, reason="openshift modülü ve operator rolü gerekli")
            return

        cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if not cluster:
            await websocket.accept()
            await websocket.close(code=1011, reason="Cluster bulunamadı")
            return

        cc = cluster.connection_config or {}
        ocp_token = plain(cc.get("token") or "")
        if not ocp_token and cc.get("username") and cc.get("password"):
            client = cluster_ops.client_from_cluster(cluster)
            ocp_token = client.token or ""
            client.logout()
        if not ocp_token:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mCluster token yok.\033[0m\r\n")
            await websocket.close(code=1011)
            return

        # Container seçilmemişse pod detayından ilkini al
        cont = (container or "").strip()
        if not cont:
            client = cluster_ops.client_from_cluster(cluster)
            try:
                detail = cluster_ops.pod_detail(client, namespace, pod) or {}
                for c in (detail.get("containers") or []):
                    if c.get("name"):
                        cont = c["name"]
                        break
            finally:
                client.logout()
        if not cont:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mContainer bulunamadı.\033[0m\r\n")
            await websocket.close(code=1011)
            return

        api_url = (cc.get("api_url") or cluster.api_url or "").rstrip("/")
        from app.services.host_resolve import rewrite_url_host
        resolved_api, _note, orig_host = rewrite_url_host(
            api_url if "://" in api_url else f"https://{api_url}"
        )
        parsed = urlparse(resolved_api)
        host = parsed.netloc or parsed.path
        # Atlas: bash -l tercih, yoksa sh (prompt stderr'de kalsın)
        qs = urlencode([
            ("stdin", "true"),
            ("stdout", "true"),
            ("stderr", "true"),
            ("tty", "true"),
            ("container", cont),
            ("command", "/bin/sh"),
            ("command", "-c"),
            ("command", "command -v bash >/dev/null 2>&1 && exec bash -l || exec sh"),
        ])
        exec_url = (
            f"wss://{host}/api/v1/namespaces/{quote(namespace, safe='')}"
            f"/pods/{quote(pod, safe='')}/exec?{qs}"
        )
        verify_ssl = bool(cc.get("verify_ssl", False))
        ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        await websocket.accept()
        await websocket.send_text(
            f"\033[90mBağlanılıyor: {namespace}/{pod} · {cont}\033[0m\r\n"
        )

        ws_headers = {"Authorization": f"Bearer {ocp_token}"}
        if orig_host:
            ws_headers["Host"] = orig_host
        try:
            try:
                upstream = await websockets.connect(
                    exec_url,
                    ssl=ssl_ctx,
                    additional_headers=ws_headers,
                    subprotocols=["v4.channel.k8s.io", "v3.channel.k8s.io", "v2.channel.k8s.io"],
                    max_size=8 * 1024 * 1024,
                )
            except TypeError:
                upstream = await websockets.connect(
                    exec_url,
                    ssl=ssl_ctx,
                    extra_headers=ws_headers,
                    subprotocols=["v4.channel.k8s.io", "v3.channel.k8s.io", "v2.channel.k8s.io"],
                    max_size=8 * 1024 * 1024,
                )
        except Exception as e:
            await websocket.send_text(f"\r\n\033[31mExec bağlantı hatası: {e}\033[0m\r\n")
            await websocket.close()
            return

        async def pump_up():
            """kube → browser: stdout/stderr düz metin (Atlas)."""
            try:
                async for message in upstream:
                    raw = message if isinstance(message, (bytes, bytearray)) else str(message).encode()
                    if not raw:
                        continue
                    channel, data = raw[0], raw[1:]
                    if channel in (1, 2) and data:  # stdout / stderr
                        await websocket.send_text(data.decode("utf-8", errors="replace"))
                    elif channel == 3 and data:  # error
                        try:
                            err = json.loads(data.decode("utf-8", errors="replace"))
                            if err.get("status") != "Success":
                                await websocket.send_text(
                                    f"\r\n[oturum sonlandı: {err.get('message', 'bilinmeyen')}]\r\n"
                                )
                        except Exception:
                            pass
            except Exception:
                pass

        async def pump_down():
            """browser → kube: {"type":"input"|"resize", ...} (Atlas JSON)."""
            try:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    raw_text = msg.get("text")
                    raw_bytes = msg.get("bytes")
                    if raw_text is not None:
                        try:
                            payload = json.loads(raw_text)
                        except Exception:
                            # düz metin → stdin (geriye uyum)
                            await upstream.send(b"\x00" + raw_text.encode("utf-8", errors="replace"))
                            continue
                        if payload.get("type") == "input":
                            data = (payload.get("data") or "").encode("utf-8", errors="replace")
                            await upstream.send(b"\x00" + data)
                        elif payload.get("type") == "resize":
                            dims = json.dumps({
                                "Width": int(payload.get("cols", 80)),
                                "Height": int(payload.get("rows", 24)),
                            }).encode()
                            await upstream.send(b"\x04" + dims)
                    elif raw_bytes is not None:
                        raw = bytes(raw_bytes)
                        if raw.startswith(b"\x01") and b"," in raw[1:]:
                            try:
                                dims = raw[1:].decode("ascii", errors="ignore")
                                cols_s, rows_s = dims.split(",", 1)
                                payload_r = json.dumps({
                                    "Width": int(cols_s),
                                    "Height": int(rows_s),
                                }).encode()
                                await upstream.send(b"\x04" + payload_r)
                            except Exception:
                                await upstream.send(b"\x00" + raw)
                        else:
                            await upstream.send(b"\x00" + raw)
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        t1 = asyncio.create_task(pump_up())
        t2 = asyncio.create_task(pump_down())
        _d, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("pod exec error")
    finally:
        db.close()
        if upstream is not None:
            try:
                await upstream.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/nodes")
async def list_nodes(
    cluster_id: Optional[int] = None,
    q: Optional[str] = None,
    not_ready_only: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(OpenShiftNode)
    if cluster_id:
        query = query.filter(OpenShiftNode.cluster_id == cluster_id)
    if q:
        query = query.filter(OpenShiftNode.name.ilike(f"%{q.strip()}%"))
    nodes = query.order_by(OpenShiftNode.role, OpenShiftNode.name).all()
    if not_ready_only:
        nodes = [n for n in nodes if (n.status or "").lower() != "ready"]
    return {"nodes": [_node_dict(n) for n in nodes], "total": len(nodes)}


@router.get("/projects")
async def list_projects(
    cluster_id: Optional[int] = None,
    include_system: bool = False,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(OpenShiftProject)
    if cluster_id:
        query = query.filter(OpenShiftProject.cluster_id == cluster_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (OpenShiftProject.name.ilike(like)) | (OpenShiftProject.display_name.ilike(like))
        )
    query = query.order_by(OpenShiftProject.name)
    if not include_system:
        # sayfalama sonrası filtre toplamı bozar — önce filtrele
        all_p = query.all()
        filtered = [p for p in all_p if not (p.meta_data or {}).get("is_system")]
        page = max(1, page)
        page_size = min(max(1, page_size), 1000)
        total = len(filtered)
        items = filtered[(page - 1) * page_size: page * page_size]
        return {
            "projects": [_project_dict(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    page = max(1, page)
    page_size = min(max(1, page_size), 1000)
    total_all = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "projects": [_project_dict(p) for p in items],
        "total": total_all,
        "page": page,
        "page_size": page_size,
    }


@router.get("/workloads")
async def list_workloads(
    cluster_id: Optional[int] = None,
    project: Optional[str] = None,
    kind: Optional[str] = None,
    q: Optional[str] = None,
    risk_only: bool = False,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    from app.services.openshift_health import filter_workloads_query, is_risk_pod, paginate_query
    query = filter_workloads_query(
        db, cluster_id=cluster_id, project=project, kind=kind, q=q, risk_only=risk_only,
    )
    if risk_only:
        all_items = query.all()
        filtered = [w for w in all_items if is_risk_pod(w)]
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        total = len(filtered)
        items = filtered[(page - 1) * page_size: page * page_size]
    else:
        items, total = paginate_query(query, page, page_size)
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
    return {
        "workloads": [_workload_dict(w) for w in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ── AIOps Komuta Merkezi ──────────────────────────────────────────────────────

@router.get("/ops/summary")
async def openshift_ops_summary(db: Session = Depends(get_db)):
    """Navbar badge — OpenShift olay özeti."""
    from app.api.ops_center import _active_events, ACTIVE_WINDOW_HOURS
    from app.services.event_grouping import unique_events

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = unique_events(_active_events(db, since, platform="openshift"))
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
    from app.services.event_grouping import unique_events

    since = datetime.utcnow() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    events = unique_events(_active_events(db, since, platform="openshift"))

    clusters = db.query(OpenShiftCluster).all()
    cluster_ids = [c.id for c in clusters]
    nodes_by_cid: Dict[int, List[OpenShiftNode]] = {cid: [] for cid in cluster_ids}
    project_count_by_cid: Dict[int, int] = {cid: 0 for cid in cluster_ids}
    if cluster_ids:
        for n in db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id.in_(cluster_ids)).all():
            nodes_by_cid.setdefault(n.cluster_id, []).append(n)
        for cid, cnt in (
            db.query(OpenShiftProject.cluster_id, func.count(OpenShiftProject.id))
            .filter(OpenShiftProject.cluster_id.in_(cluster_ids))
            .group_by(OpenShiftProject.cluster_id)
            .all()
        ):
            project_count_by_cid[cid] = int(cnt or 0)

    cluster_summaries: List[Dict[str, Any]] = []
    for c in clusters:
        nodes = nodes_by_cid.get(c.id) or []
        not_ready = [n for n in nodes if (n.status or "").lower() != "ready"]
        cluster_summaries.append({
            "id": c.id,
            "name": c.name,
            "api_url": c.api_url,
            "status": c.status,
            "version": c.version,
            "node_count": len(nodes),
            "not_ready_nodes": [n.name for n in not_ready],
            "project_count": project_count_by_cid.get(c.id, 0),
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


# ── MTV / Forklift ────────────────────────────────────────────────────────────

class MtvProviderIn(BaseModel):
    hypervisor_id: int
    vddk_init_image: str = ""


class MtvVddkIn(BaseModel):
    vddk_init_image: str = ""


class MtvPlanIn(BaseModel):
    plan_name: str
    provider_name: str
    hypervisor_id: int
    vms: list  # [{"id": "vm-123", "name": "..."}]
    target_namespace: str = "vm-migrasyon"
    storage_class: str = ""
    network: dict = {"type": "pod"}
    warm: bool = False
    storage_map: Optional[list] = None
    network_map: Optional[list] = None


class MtvSourceRefsIn(BaseModel):
    hypervisor_id: int
    vm_morefs: list


def _mtv_cluster(cluster_id: int, db: Session) -> OpenShiftCluster:
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    return cluster


@router.get("/clusters/{cluster_id}/mtv/rbac")
def mtv_rbac(cluster_id: int, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    _mtv_cluster(cluster_id, db)
    return {"yaml": mtv_service.RBAC_YAML}


@router.get("/clusters/{cluster_id}/mtv/providers")
def mtv_providers(cluster_id: int, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.list_providers(cluster)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/clusters/{cluster_id}/mtv/providers")
def mtv_create_provider(
    cluster_id: int,
    body: MtvProviderIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.create_vsphere_provider(
            cluster, db, body.hypervisor_id, vddk_init_image=body.vddk_init_image,
        )
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/clusters/{cluster_id}/mtv/providers/{provider_name}/vddk")
def mtv_set_vddk(
    cluster_id: int,
    provider_name: str,
    body: MtvVddkIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.set_provider_vddk(cluster, provider_name, body.vddk_init_image)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/clusters/{cluster_id}/mtv/providers/{provider_name}")
def mtv_delete_provider(
    cluster_id: int,
    provider_name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.delete_provider(cluster, provider_name)
    except mtv_service.MtvError as e:
        msg = str(e)
        code = 409 if "kullanılıyor" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e


@router.get("/clusters/{cluster_id}/mtv/targets")
def mtv_targets(cluster_id: int, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.migration_targets(cluster)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/clusters/{cluster_id}/mtv/source-refs")
def mtv_source_refs(cluster_id: int, body: MtvSourceRefsIn, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.source_refs(db, body.hypervisor_id, body.vm_morefs or [])
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/clusters/{cluster_id}/mtv/source-vms")
def mtv_source_vms(cluster_id: int, hypervisor_id: int, db: Session = Depends(get_db)):
    """Envanterdeki VMware VM'ler (moref = hypervisor_vm_id) — plan sihirbazı."""
    from app.models.server import Server
    from app.models.hypervisor import Hypervisor, HypervisorType
    _mtv_cluster(cluster_id, db)
    hv = db.query(Hypervisor).filter(
        Hypervisor.id == hypervisor_id,
        Hypervisor.hypervisor_type == HypervisorType.VMWARE,
    ).first()
    if not hv:
        raise HTTPException(status_code=404, detail="VMware hypervisor bulunamadı")
    rows = (
        db.query(Server)
        .filter(Server.hypervisor_id == hypervisor_id, Server.hypervisor_vm_id.isnot(None))
        .order_by(Server.name)
        .all()
    )
    return [
        {
            "moref": s.hypervisor_vm_id,
            "name": s.vm_name or s.name,
            "power_state": s.vm_power_state or s.status or "",
            "hypervisor_id": hypervisor_id,
            "ip": s.vm_guest_ip or s.ip_address,
        }
        for s in rows
        if s.hypervisor_vm_id
    ]


@router.get("/clusters/{cluster_id}/mtv/plans")
def mtv_plans(cluster_id: int, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.list_plans(cluster)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/clusters/{cluster_id}/mtv/plans")
def mtv_create_plan(
    cluster_id: int,
    body: MtvPlanIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.create_plan(
            cluster, db, body.plan_name, body.provider_name, body.hypervisor_id,
            body.vms, body.target_namespace, body.storage_class, body.network or {"type": "pod"},
            body.warm, storage_map=body.storage_map or None, network_map=body.network_map or None,
        )
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/clusters/{cluster_id}/mtv/plans/{plan_name}/pods")
def mtv_plan_pods(cluster_id: int, plan_name: str, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.migration_pods(cluster, plan_name)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/clusters/{cluster_id}/mtv/plans/{plan_name}/cancel")
def mtv_cancel(
    cluster_id: int,
    plan_name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.cancel_plan(cluster, plan_name)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/clusters/{cluster_id}/mtv/plans/{plan_name}/start")
def mtv_start(
    cluster_id: int,
    plan_name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.start_plan(cluster, plan_name)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/clusters/{cluster_id}/mtv/plans/{plan_name}/status")
def mtv_status(cluster_id: int, plan_name: str, db: Session = Depends(get_db)):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.plan_status(cluster, plan_name)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.delete("/clusters/{cluster_id}/mtv/plans/{plan_name}")
def mtv_delete(
    cluster_id: int,
    plan_name: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    from app.services.openshift import mtv_service as mtv_service
    cluster = _mtv_cluster(cluster_id, db)
    try:
        return mtv_service.delete_plan(cluster, plan_name)
    except mtv_service.MtvError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
