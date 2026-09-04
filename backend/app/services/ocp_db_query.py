"""OpenShift DB-first sorgular — chat tool kataloğu L1 (virt_db_query.py ile aynı desen).

SoT: openshift_nodes / openshift_projects (periyodik sync — bkz.
app/services/openshift_sync_service.py, tetikleyici
app/background_tasks.py::_periodic_openshift_sync, ~600sn aralık).

Bu katman canlı API'nin YERİNE geçmez: OCP API çağrıları vCenter SOAP kadar
ağır olmadığı için burada vCenter'daki gibi zorunlu "DB-first faz kilidi"
uygulanmıyor — yalnızca "önce ucuz DB'ye bak" tercih edilen ilk adım olarak
sunuluyor (bkz. unified_tool_chat._PLATFORM_HINTS["openshift"]).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _age_seconds(ts: Optional[datetime]) -> Optional[int]:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int((_utc_now() - ts).total_seconds())


def _stale(ts: Optional[datetime], max_age_sec: int) -> bool:
    age = _age_seconds(ts)
    if age is None:
        return True
    return age > max_age_sec


def _resolve_cluster(db: Session, cluster: Optional[str]) -> Optional[OpenShiftCluster]:
    """args['cluster'] (ad) ile bir OpenShiftCluster bulur; yoksa ilkini döner.

    agent/tools.py::resolve_openshift_cluster ile aynı davranış (tutarlılık
    için) — tekli cluster kurulumlarında isim verilmese de çalışır.
    """
    q = db.query(OpenShiftCluster)
    if cluster:
        name = cluster.strip().lower()
        for c in q.all():
            if c.name and c.name.lower() == name:
                return c
    return q.first()


# Senkron periyodu ~600sn; 20dk eşiği birkaç kaçırılmış turu tolere eder.
_STALE_MAX_AGE_SEC = 20 * 60


def list_ocp_nodes_db(
    db: Session,
    *,
    cluster: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """OpenShift node envanteri — DATABASE'den (periyodik sync).

    Canlı değil; stale=true veya eksikse openshift_ask / list_ocp_pods ile
    canlı doğrula.
    """
    c = _resolve_cluster(db, cluster)
    if not c:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı", "source": "db"}

    q = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == c.id)
    if role:
        q = q.filter(OpenShiftNode.role == role.strip().lower())
    if status:
        q = q.filter(OpenShiftNode.status.ilike(f"%{status.strip()}%"))
    rows = q.order_by(OpenShiftNode.name.asc()).limit(max(1, min(int(limit or 200), 1000))).all()

    nodes: List[Dict[str, Any]] = [
        {
            "name": n.name,
            "role": n.role,
            "status": n.status,
            "cpu_cores": n.cpu_cores,
            "memory_gb": n.memory_gb,
            "cpu_usage_pct": n.cpu_usage_pct,
            "memory_usage_pct": n.memory_usage_pct,
            "kubelet_version": n.kubelet_version,
            "os_image": n.os_image,
            "pod_count": n.pod_count,
        }
        for n in rows
    ]
    return {
        "ok": True,
        "source": "db",
        "cluster": c.name,
        "count": len(nodes),
        "as_of": c.last_sync.isoformat() if c.last_sync else None,
        "stale": _stale(c.last_sync, _STALE_MAX_AGE_SEC),
        "nodes": nodes,
    }


def list_ocp_projects_db(
    db: Session,
    *,
    cluster: Optional[str] = None,
    name_filter: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """OpenShift proje/namespace envanteri — DATABASE'den (periyodik sync)."""
    c = _resolve_cluster(db, cluster)
    if not c:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı", "source": "db"}

    q = db.query(OpenShiftProject).filter(OpenShiftProject.cluster_id == c.id)
    if name_filter:
        q = q.filter(OpenShiftProject.name.ilike(f"%{name_filter.strip()}%"))
    rows = q.order_by(OpenShiftProject.name.asc()).limit(max(1, min(int(limit or 200), 1000))).all()

    projects: List[Dict[str, Any]] = [
        {
            "name": p.name,
            "display_name": p.display_name,
            "status": p.status,
            "pod_count": p.pod_count,
            "deployment_count": p.deployment_count,
            "route_count": p.route_count,
            "requester": p.requester,
        }
        for p in rows
    ]
    return {
        "ok": True,
        "source": "db",
        "cluster": c.name,
        "count": len(projects),
        "as_of": c.last_sync.isoformat() if c.last_sync else None,
        "stale": _stale(c.last_sync, _STALE_MAX_AGE_SEC),
        "projects": projects,
    }
