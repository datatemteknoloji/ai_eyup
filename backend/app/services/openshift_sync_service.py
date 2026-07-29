"""
OpenShift Container Platform envanter sync servisi — cluster'lardan node/proje/workload'ları DB'ye senkronize eder.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

logger = logging.getLogger(__name__)


def update_sync_job(cluster_id: int, **patch) -> None:
    """OpenShiftCluster.meta_data.sync_job alanını günceller (thread-safe, ayrı session)."""
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
        db.commit()
    except Exception as exc:
        logger.warning("openshift sync_job update failed (cluster=%s): %s", cluster_id, exc)
        db.rollback()
    finally:
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
    existing.kubelet_version = node.get("kubelet_version")
    existing.os_image = node.get("os_image")
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
    existing.restart_count = item.get("restart_count", 0)
    existing.ready = item.get("ready")
    existing.host = item.get("host")
    return created


def sync_openshift_cluster(db: Session, cluster: OpenShiftCluster, *, track_progress: bool = False) -> dict:
    """Tek bir OpenShift cluster'ından node/proje/workload envanterini senkronize eder."""
    from app.services.openshift.ocp_client import OpenShiftClient

    cluster_id = cluster.id

    def _prog(**kw):
        if track_progress and cluster_id:
            update_sync_job(cluster_id, **kw)

    _prog(status="running", phase="connecting", percent=2, message="Cluster'a bağlanılıyor...", error=None)

    cc = cluster.connection_config or {}
    use_creds = bool(cc.get("username")) and bool(cc.get("password"))
    client = OpenShiftClient(
        api_url=cc.get("api_url") or cluster.api_url,
        token="" if use_creds else (cc.get("token") or ""),
        username=cc.get("username") or "",
        password=cc.get("password") or "",
        verify_ssl=bool(cc.get("verify_ssl", False)),
    )

    errors: list = []
    nodes: list = []
    projects: list = []
    pods: list = []
    deployments: list = []
    routes: list = []

    try:
        ok, detail = client.test_connection()
        if not ok:
            errors.append(f"Bağlantı hatası: {detail}")
        else:
            _prog(phase="listing", percent=10, message="Node listesi alınıyor...")
            nodes = client.list_nodes()
            _prog(phase="listing", percent=25, message="Proje listesi alınıyor...")
            projects = client.list_projects()
            _prog(phase="listing", percent=40, message="Pod listesi alınıyor...")
            pods = client.list_pods()
            _prog(phase="listing", percent=60, message="Deployment listesi alınıyor...")
            deployments = client.list_deployments()
            _prog(phase="listing", percent=75, message="Route listesi alınıyor...")
            routes = client.list_routes()
            cluster.version = client.get_version() or cluster.version
    except Exception as e:
        logger.exception("OpenShift sync error (cluster=%s)", cluster.name)
        errors.append(str(e))
    finally:
        client.logout()

    if errors and not nodes and not projects:
        _prog(status="error", phase="error", percent=100, message=errors[0], error=errors[0])
        return {"nodes": 0, "projects": 0, "pods": 0, "deployments": 0, "routes": 0, "errors": errors}

    _prog(phase="saving", percent=88, message="Envantere kaydediliyor...")

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
    project_new = sum(1 for p in projects if _upsert_project(db, cluster, p, pod_counts, deploy_counts, route_counts))
    pod_new = sum(1 for p in pods if _upsert_workload(db, cluster, p["namespace"], "pod", p))
    deploy_new = sum(1 for d in deployments if _upsert_workload(db, cluster, d["namespace"], "deployment", d))
    route_new = sum(1 for rt in routes if _upsert_workload(db, cluster, rt["namespace"], "route", rt))

    cluster.last_sync = datetime.now(timezone.utc)
    db.add(cluster)
    db.flush()

    result = {
        "nodes": len(nodes), "nodes_new": node_new,
        "projects": len(projects), "projects_new": project_new,
        "pods": len(pods), "pods_new": pod_new,
        "deployments": len(deployments), "deployments_new": deploy_new,
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
