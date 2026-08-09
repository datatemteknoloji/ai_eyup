"""
OpenShift Container Platform envanter sync servisi — cluster'lardan node/proje/workload'ları DB'ye senkronize eder.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

logger = logging.getLogger(__name__)


def update_sync_job(cluster_id: int, db: Session | None = None, **patch) -> None:
    """OpenShiftCluster.meta_data.sync_job alanını günceller.

    Aynı DB session verilirse (önerilen) satır kilidi deadlock'u oluşmaz.
    Session verilmezse kısa ömürlü ayrı bağlantı + commit kullanılır — yalnızca
    ana session cluster satırını kilitlemiyorken güvenlidir.
    """
    owns = db is None
    if owns:
        from app.core.database import ThreadSessionLocal
        db = ThreadSessionLocal()
    try:
        cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if not cluster:
            return
        meta = dict(cluster.meta_data or {})
        job = dict(meta.get("sync_job") or {})
        job.update(patch)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        meta["sync_job"] = job
        cluster.meta_data = meta
        flag_modified(cluster, "meta_data")
        st = patch.get("status")
        if st == "running":
            cluster.status = "SYNCING"
        elif st == "done":
            cluster.status = "ONLINE"
        elif st == "error":
            cluster.status = "ERROR"
        if owns:
            db.commit()
        else:
            db.flush()
    except Exception as exc:
        logger.warning("openshift sync_job update failed (cluster=%s): %s", cluster_id, exc)
        if owns:
            db.rollback()
    finally:
        if owns:
            db.close()


def get_sync_job(cluster: OpenShiftCluster) -> dict:
    meta = cluster.meta_data or {}
    job = meta.get("sync_job") or {}
    return job if isinstance(job, dict) else {}


def _upsert_node(db: Session, cluster: OpenShiftCluster, node: dict) -> bool:
    existing = (
        db.query(OpenShiftNode)
        .filter(OpenShiftNode.cluster_id == cluster.id, OpenShiftNode.name == node["name"])
        .first()
    )
    created = False
    if not existing:
        existing = OpenShiftNode(cluster_id=cluster.id, name=node["name"])
        db.add(existing)
        created = True
    existing.role = node.get("role", existing.role or "worker")
    existing.status = node.get("status", "unknown")
    existing.cpu_cores = node.get("cpu_cores")
    existing.memory_gb = node.get("memory_gb")
    existing.cpu_usage_pct = node.get("cpu_usage_pct")
    existing.memory_usage_pct = node.get("memory_usage_pct")
    existing.kubelet_version = node.get("kubelet_version")
    existing.os_image = node.get("os_image")
    existing.pod_count = int(node.get("pod_count") or 0)
    existing.meta_data = {
        "cpu_allocatable": node.get("cpu_allocatable"),
        "memory_allocatable_gb": node.get("memory_allocatable_gb"),
        "cpu_requested": node.get("cpu_requested"),
        "memory_requested_gb": node.get("memory_requested_gb"),
        "internal_ip": node.get("internal_ip") or "",
        "external_ip": node.get("external_ip") or "",
        "hostname": node.get("hostname") or node.get("name") or "",
        "ip_address": node.get("ip_address") or node.get("internal_ip") or "",
    }
    return created


def _upsert_project(db: Session, cluster: OpenShiftCluster, project: dict, pod_counts: dict, deploy_counts: dict, route_counts: dict) -> bool:
    existing = (
        db.query(OpenShiftProject)
        .filter(OpenShiftProject.cluster_id == cluster.id, OpenShiftProject.name == project["name"])
        .first()
    )
    created = False
    if not existing:
        existing = OpenShiftProject(cluster_id=cluster.id, name=project["name"])
        db.add(existing)
        created = True
    existing.status = project.get("status", "Active")
    existing.display_name = project.get("display_name")
    existing.requester = project.get("requester")
    existing.pod_count = pod_counts.get(project["name"], 0)
    existing.deployment_count = deploy_counts.get(project["name"], 0)
    existing.route_count = route_counts.get(project["name"], 0)
    existing.meta_data = {"is_system": project.get("is_system", False)}
    return created


def _upsert_workload(db: Session, cluster: OpenShiftCluster, project: str, kind: str, item: dict) -> bool:
    existing = (
        db.query(OpenShiftWorkload)
        .filter(
            OpenShiftWorkload.cluster_id == cluster.id,
            OpenShiftWorkload.project == project,
            OpenShiftWorkload.kind == kind,
            OpenShiftWorkload.name == item["name"],
        )
        .first()
    )
    created = False
    if not existing:
        existing = OpenShiftWorkload(cluster_id=cluster.id, project=project, kind=kind, name=item["name"])
        db.add(existing)
        created = True
    existing.status = item.get("status", "unknown")
    existing.node_name = item.get("node_name")
    existing.restart_count = item.get("restart_count", 0) or 0
    existing.ready = item.get("ready")
    existing.host = item.get("host")
    meta = dict(existing.meta_data or {})
    for k in ("reason", "phase", "owner_kind", "owner_name", "to_service", "selector", "ports",
              "cpu_request", "memory_request_gb", "cluster_ip"):
        if item.get(k) is not None:
            meta[k] = item[k]
    existing.meta_data = meta or None
    return created


def _enrich_nodes_with_requests(nodes: list, pods: list) -> list:
    """Pod request toplamlarından node kapasite yüzdelerini hesapla."""
    by_node: dict = {}
    pod_counts: dict = {}
    for p in pods:
        nn = p.get("node_name") or ""
        if not nn:
            continue
        acc = by_node.setdefault(nn, {"cpu": 0.0, "mem": 0.0})
        acc["cpu"] += float(p.get("cpu_request") or 0)
        acc["mem"] += float(p.get("memory_request_gb") or 0)
        pod_counts[nn] = pod_counts.get(nn, 0) + 1

    out = []
    for n in nodes:
        item = dict(n)
        name = n["name"]
        req = by_node.get(name, {"cpu": 0.0, "mem": 0.0})
        cpu_alloc = float(n.get("cpu_allocatable") or n.get("cpu_cores") or 0) or 0.0
        mem_alloc = float(n.get("memory_allocatable_gb") or n.get("memory_gb") or 0) or 0.0
        item["cpu_requested"] = round(req["cpu"], 3)
        item["memory_requested_gb"] = round(req["mem"], 3)
        item["pod_count"] = pod_counts.get(name, 0)
        item["cpu_usage_pct"] = round((req["cpu"] / cpu_alloc) * 100, 1) if cpu_alloc > 0 else None
        item["memory_usage_pct"] = round((req["mem"] / mem_alloc) * 100, 1) if mem_alloc > 0 else None
        out.append(item)
    return out


def sync_openshift_cluster(db: Session, cluster: OpenShiftCluster, *, track_progress: bool = False) -> dict:
    """Tek bir OpenShift cluster'ından node/proje/workload envanterini senkronize eder."""
    from app.services.openshift.cluster_ops import client_from_cluster

    cluster_id = cluster.id

    def _prog(**kw):
        if track_progress and cluster_id:
            update_sync_job(cluster_id, db=db, **kw)

    _prog(status="running", phase="connecting", percent=2, message="Cluster'a bağlanılıyor...", error=None)

    client = client_from_cluster(cluster)

    errors: list = []
    nodes: list = []
    projects: list = []
    pods: list = []
    deployments: list = []
    routes: list = []
    services: list = []

    try:
        ok, detail = client.test_connection()
        if not ok:
            errors.append(f"Bağlantı hatası: {detail}")
        else:
            _prog(phase="listing", percent=10, message="Node listesi alınıyor...")
            nodes = client.list_nodes()
            _prog(phase="listing", percent=22, message=f"Proje listesi alınıyor... ({len(nodes)} node)")
            projects = client.list_projects()
            _prog(phase="listing", percent=35, message=f"Pod listesi alınıyor... ({len(projects)} proje)")
            pods = client.list_pods()
            _prog(phase="listing", percent=50, message=f"Deployment listesi alınıyor... ({len(pods)} pod)")
            deployments = client.list_deployments()
            _prog(phase="listing", percent=65, message=f"Service/Route alınıyor... ({len(deployments)} deployment)")
            routes = client.list_routes()
            services = client.list_services()
            cluster.version = client.get_version() or cluster.version
    except Exception as e:
        logger.exception("OpenShift sync error (cluster=%s)", cluster.name)
        errors.append(str(e))
    finally:
        client.logout()

    if errors and not nodes and not projects:
        _prog(status="error", phase="error", percent=100, message=errors[0], error=errors[0])
        return {"nodes": 0, "projects": 0, "pods": 0, "deployments": 0, "routes": 0, "services": 0, "errors": errors}

    nodes = _enrich_nodes_with_requests(nodes, pods)

    total_items = len(nodes) + len(projects) + len(pods) + len(deployments) + len(routes) + len(services)
    _prog(phase="saving", percent=80, message=f"Envantere kaydediliyor... ({total_items} kayıt)")

    pod_counts: dict = {}
    for p in pods:
        pod_counts[p["namespace"]] = pod_counts.get(p["namespace"], 0) + 1
    deploy_counts: dict = {}
    for d in deployments:
        deploy_counts[d["namespace"]] = deploy_counts.get(d["namespace"], 0) + 1
    route_counts: dict = {}
    for rt in routes:
        route_counts[rt["namespace"]] = route_counts.get(rt["namespace"], 0) + 1

    node_new = sum(1 for n in nodes if _upsert_node(db, cluster, n))
    _prog(phase="saving", percent=86, message=f"Projeler kaydediliyor... ({len(nodes)} node)")
    project_new = sum(1 for p in projects if _upsert_project(db, cluster, p, pod_counts, deploy_counts, route_counts))
    _prog(phase="saving", percent=90, message=f"Pod'lar kaydediliyor... ({len(projects)} proje)")
    pod_new = sum(1 for p in pods if _upsert_workload(db, cluster, p["namespace"], "pod", p))
    _prog(phase="saving", percent=94, message=f"Deployment/service/route... ({len(pods)} pod)")
    deploy_new = sum(1 for d in deployments if _upsert_workload(db, cluster, d["namespace"], "deployment", d))
    svc_new = sum(1 for s in services if _upsert_workload(db, cluster, s["namespace"], "service", s))
    route_new = sum(1 for rt in routes if _upsert_workload(db, cluster, rt["namespace"], "route", rt))

    cluster.last_sync = datetime.now(timezone.utc)
    db.add(cluster)

    result = {
        "nodes": len(nodes), "nodes_new": node_new,
        "projects": len(projects), "projects_new": project_new,
        "pods": len(pods), "pods_new": pod_new,
        "deployments": len(deployments), "deployments_new": deploy_new,
        "services": len(services), "services_new": svc_new,
        "routes": len(routes), "routes_new": route_new,
        "errors": errors,
    }

    if errors:
        _prog(status="error", phase="error", percent=100, message="; ".join(errors)[:300], error="; ".join(errors)[:300])
    else:
        _prog(
            status="done", phase="done", percent=100,
            message=f"Tamamlandı — {len(nodes)} node, {len(projects)} proje, {len(pods)} pod",
        )
    return result


def sync_all_openshift_clusters(db: Session) -> dict:
    clusters = db.query(OpenShiftCluster).all()
    if not clusters:
        return {"success": True, "total_clusters": 0, "clusters": []}

    results = []
    all_errors: list = []
    for c in clusters:
        try:
            r = sync_openshift_cluster(db, c)
            db.commit()
            results.append({"name": c.name, **r})
            all_errors.extend(r.get("errors") or [])
        except Exception as e:
            logger.error(f"OpenShift sync error for {c.name}: {e}", exc_info=True)
            db.rollback()
            results.append({"name": c.name, "errors": [str(e)]})
            all_errors.append(str(e))

    return {"success": len(all_errors) == 0, "total_clusters": len(clusters), "clusters": results}
