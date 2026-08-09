"""OpenShift health / risk / inventory yardımcıları."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload

RISK_STATUSES = frozenset({
    "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerError",
    "InvalidImageName", "OOMKilled", "Error", "Failed", "Unknown", "Pending",
    "RunContainerError", "ContainerCannotRun",
})


def is_risk_pod(w: OpenShiftWorkload) -> bool:
    if (w.kind or "").lower() != "pod":
        return False
    st = (w.status or "").strip()
    if st in RISK_STATUSES:
        return True
    if st.lower() in ("failed", "unknown", "pending"):
        return True
    if (w.restart_count or 0) >= 5:
        return True
    meta = w.meta_data or {}
    reason = (meta.get("reason") or "").strip()
    if reason in RISK_STATUSES:
        return True
    return False


def risk_severity(w: OpenShiftWorkload) -> str:
    st = (w.status or "")
    reason = ((w.meta_data or {}).get("reason") or "")
    if st in ("CrashLoopBackOff", "OOMKilled", "Failed", "Error") or reason in ("CrashLoopBackOff", "OOMKilled"):
        return "critical"
    if st in ("ImagePullBackOff", "ErrImagePull", "CreateContainerError", "Unknown") or (w.restart_count or 0) >= 10:
        return "high"
    return "warning"


def build_health_board(db: Session, cluster_id: Optional[int] = None) -> Dict[str, Any]:
    cq = db.query(OpenShiftCluster)
    if cluster_id:
        cq = cq.filter(OpenShiftCluster.id == cluster_id)
    clusters = cq.order_by(OpenShiftCluster.name).all()

    board: List[Dict[str, Any]] = []
    totals = {
        "clusters": len(clusters),
        "nodes": 0,
        "nodes_not_ready": 0,
        "projects": 0,
        "pods": 0,
        "risk_pods": 0,
        "deployments": 0,
        "routes": 0,
    }

    # N+1 önleme: tüm child satırlarını tek seferde çek
    cluster_ids = [c.id for c in clusters]
    nodes_by_cid: Dict[int, List[OpenShiftNode]] = {cid: [] for cid in cluster_ids}
    projects_by_cid: Dict[int, List[OpenShiftProject]] = {cid: [] for cid in cluster_ids}
    workloads_by_cid: Dict[int, List[OpenShiftWorkload]] = {cid: [] for cid in cluster_ids}
    if cluster_ids:
        for n in db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id.in_(cluster_ids)).all():
            nodes_by_cid.setdefault(n.cluster_id, []).append(n)
        for p in db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id.in_(cluster_ids)).all():
            projects_by_cid.setdefault(p.cluster_id, []).append(p)
        for w in db.query(OpenShiftWorkload).filter(OpenShiftWorkload.cluster_id.in_(cluster_ids)).all():
            workloads_by_cid.setdefault(w.cluster_id, []).append(w)

    for c in clusters:
        nodes = nodes_by_cid.get(c.id) or []
        projects = projects_by_cid.get(c.id) or []
        workloads = workloads_by_cid.get(c.id) or []
        pods = [w for w in workloads if (w.kind or "").lower() == "pod"]
        risk = [w for w in pods if is_risk_pod(w)]
        not_ready = [n for n in nodes if (n.status or "").lower() != "ready"]
        deploys = sum(1 for w in workloads if (w.kind or "").lower() == "deployment")
        routes = sum(1 for w in workloads if (w.kind or "").lower() == "route")
        user_projects = [p for p in projects if not (p.meta_data or {}).get("is_system")]

        cpu_vals = [n.cpu_usage_pct for n in nodes if n.cpu_usage_pct is not None]
        mem_vals = [n.memory_usage_pct for n in nodes if n.memory_usage_pct is not None]

        health = "healthy"
        if c.status == "ERROR" or not_ready or any(risk_severity(w) == "critical" for w in risk):
            health = "critical"
        elif risk or c.status == "SYNCING":
            health = "warning"
        elif c.status not in ("ONLINE", "online", "Ready"):
            health = "unknown"

        entry = {
            "id": c.id,
            "name": c.name,
            "api_url": c.api_url,
            "status": c.status,
            "version": c.version,
            "health": health,
            "last_sync": c.last_sync.isoformat() if c.last_sync else None,
            "node_count": len(nodes),
            "nodes_ready": len(nodes) - len(not_ready),
            "nodes_not_ready": [n.name for n in not_ready],
            "project_count": len(user_projects),
            "pod_count": len(pods),
            "risk_pod_count": len(risk),
            "deployment_count": deploys,
            "route_count": routes,
            "avg_cpu_request_pct": round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None,
            "avg_memory_request_pct": round(sum(mem_vals) / len(mem_vals), 1) if mem_vals else None,
            "top_risks": [
                {
                    "name": w.name,
                    "project": w.project,
                    "status": w.status,
                    "restart_count": w.restart_count or 0,
                    "severity": risk_severity(w),
                    "node_name": w.node_name,
                }
                for w in sorted(risk, key=lambda x: (0 if risk_severity(x) == "critical" else 1, -(x.restart_count or 0)))[:8]
            ],
        }
        board.append(entry)
        totals["nodes"] += len(nodes)
        totals["nodes_not_ready"] += len(not_ready)
        totals["projects"] += len(user_projects)
        totals["pods"] += len(pods)
        totals["risk_pods"] += len(risk)
        totals["deployments"] += deploys
        totals["routes"] += routes

    overall = "healthy"
    if any(b["health"] == "critical" for b in board):
        overall = "critical"
    elif any(b["health"] == "warning" for b in board):
        overall = "warning"
    elif not board:
        overall = "empty"

    return {"overall": overall, "totals": totals, "clusters": board}


def list_risk_workloads(
    db: Session,
    *,
    cluster_id: Optional[int] = None,
    limit: int = 100,
) -> List[OpenShiftWorkload]:
    q = db.query(OpenShiftWorkload).filter(OpenShiftWorkload.kind == "pod")
    if cluster_id:
        q = q.filter(OpenShiftWorkload.cluster_id == cluster_id)
    pods = q.all()
    risks = [w for w in pods if is_risk_pod(w)]
    risks.sort(key=lambda w: (
        0 if risk_severity(w) == "critical" else (1 if risk_severity(w) == "high" else 2),
        -(w.restart_count or 0),
        w.project or "",
        w.name or "",
    ))
    return risks[:limit]


def paginate_query(q, page: int, page_size: int) -> Tuple[list, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return items, total


def filter_workloads_query(
    db: Session,
    *,
    cluster_id: Optional[int] = None,
    project: Optional[str] = None,
    kind: Optional[str] = None,
    q: Optional[str] = None,
    risk_only: bool = False,
):
    query = db.query(OpenShiftWorkload)
    if cluster_id:
        query = query.filter(OpenShiftWorkload.cluster_id == cluster_id)
    if project:
        query = query.filter(OpenShiftWorkload.project == project)
    if kind:
        query = query.filter(OpenShiftWorkload.kind == kind)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(OpenShiftWorkload.name.ilike(like), OpenShiftWorkload.project.ilike(like)))
    query = query.order_by(OpenShiftWorkload.project, OpenShiftWorkload.kind, OpenShiftWorkload.name)
    if risk_only:
        # risk filtresi Python tarafında — status çeşitliliği JSON/meta içeriyor
        return query
    return query
