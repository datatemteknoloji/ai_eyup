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


@router.websocket("/clusters/{cluster_id}/kubevirt/vms/{namespace}/{name}/console")
async def kubevirt_serial_console(
    websocket: WebSocket,
    cluster_id: int,
    namespace: str,
    name: str,
    token: str = "",
):
    """KubeVirt serial console — tarayıcı ↔ ainew ↔ cluster API (VMI /console).

    SSH credential gerektirmez; VM Running olmalı. JWT: ?token=
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
        await websocket.send_text("\r\n\033[31mYetkilendirme hatası: geçerli bir token gerekli.\033[0m\r\n")
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    upstream = None
    try:
        # JWT: sub=username, uid=numeric id (terminal ile aynı)
        uid = payload.get("uid")
        user = (
            db.query(User).filter(User.id == uid, User.is_active == True).first()
            if uid is not None
            else None
        )
        if not user:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mYetkilendirme hatası: kullanıcı bulunamadı.\033[0m\r\n")
            await websocket.close(code=4401)
            return

        cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if not cluster:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mCluster bulunamadı.\033[0m\r\n")
            await websocket.close()
            return

        cc = cluster.connection_config or {}
        ocp_token = plain(cc.get("token") or "")
        if not ocp_token and cc.get("username") and cc.get("password"):
            # credentials path — ensure client has token
            kv = cluster_ops.kubevirt_client_from_cluster(cluster)
            ocp_token = kv.token or ""
            kv.logout()
        if not ocp_token:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mCluster token yok — Entegrasyonlar’dan token ile kaydedin.\033[0m\r\n")
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
        verify_ssl = bool(cc.get("verify_ssl", False))
        ssl_ctx = ssl.create_default_context()
        if not verify_ssl:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        await websocket.accept()
        await websocket.send_text(
            f"\r\n\033[36mKubeVirt serial console · {namespace}/{name}\033[0m\r\n"
            "\033[90m(serial binary; login için Enter)\033[0m\r\n\r\n"
        )

        try:
            ws_headers = {"Authorization": f"Bearer {ocp_token}"}
            if orig_host:
                ws_headers["Host"] = orig_host
            upstream = await websockets.connect(
                console_url,
                additional_headers=ws_headers,
                ssl=ssl_ctx,
                open_timeout=20,
                # KubeVirt serial ping'leri bozabiliyor; kapalı tut
                ping_interval=None,
                max_size=8 * 1024 * 1024,
            )
        except Exception as e:
            logger.warning("kubevirt console connect failed: %s", e)
            err = str(e)
            hint = (
                "OpenShift SA (örn. ainew-viewer) için virtualmachineinstances/console "
                "yetkisi yok (403). cluster-reader yeterli değil — ClusterRole ile "
                "get console/vnc subresource verin."
                if "403" in err
                else "VM Running mi? Ağ/API erişimi var mı?"
            )
            await websocket.send_text(
                f"\r\n\033[31mKonsol açılamadı: {err}\033[0m\r\n"
                f"\033[90m{hint}\033[0m\r\n"
            )
            await websocket.close()
            return

        # getty çoğu zaman Enter bekler — bir CR gönder
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
                    # KubeVirt /console yalnızca binary frame kabul eder
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
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("kubevirt console error")
        try:
            await websocket.send_text(f"\r\n\033[31mHata: {e}\033[0m\r\n")
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
    db: Session = Depends(get_db),
):
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster bulunamadı")
    from app.services.openshift import cluster_ops
    client = cluster_ops.client_from_cluster(cluster)
    try:
        return cluster_ops.pod_logs(
            client, namespace, pod, container=container, tail=tail, previous=previous,
        )
    finally:
        client.logout()


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
    from app.services.openshift_health import paginate_query
    query = db.query(OpenShiftProject)
    if cluster_id:
        query = query.filter(OpenShiftProject.cluster_id == cluster_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            (OpenShiftProject.name.ilike(like)) | (OpenShiftProject.display_name.ilike(like))
        )
    query = query.order_by(OpenShiftProject.name)
    items, total_all = paginate_query(query, page, page_size)
    if not include_system:
        # sayfalama sonrası filtre toplamı bozar — önce filtrele
        query2 = db.query(OpenShiftProject)
        if cluster_id:
            query2 = query2.filter(OpenShiftProject.cluster_id == cluster_id)
        if q:
            like = f"%{q.strip()}%"
            query2 = query2.filter(
                (OpenShiftProject.name.ilike(like)) | (OpenShiftProject.display_name.ilike(like))
            )
        all_p = query2.order_by(OpenShiftProject.name).all()
        filtered = [p for p in all_p if not (p.meta_data or {}).get("is_system")]
        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        total = len(filtered)
        items = filtered[(page - 1) * page_size: page * page_size]
        return {
            "projects": [_project_dict(p) for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    return {
        "projects": [_project_dict(p) for p in items],
        "total": total_all,
        "page": max(1, page),
        "page_size": min(max(1, page_size), 200),
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
