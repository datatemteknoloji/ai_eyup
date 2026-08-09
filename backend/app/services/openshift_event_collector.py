"""
OpenShift Container Platform event senkronizasyonu → SystemEvent (platform=openshift).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.event import SystemEvent
from app.models.openshift import OpenShiftCluster
from app.services.incident_auto import auto_create_or_link_incident

logger = logging.getLogger(__name__)

OPENSHIFT_SOURCE = "openshift_collector"


def _upsert_openshift_event(db: Session, cluster: OpenShiftCluster, item: Dict[str, Any], now: datetime) -> bool:
    ext_key = f"ocp{cluster.id}-{item.get('source_object')}-{item.get('reason')}-{item.get('timestamp')}"
    since = datetime.utcnow() - timedelta(days=7)

    # PostgreSQL JSON (non-JSONB): contains()/LIKE kırılır — astext ile filtrele
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import JSONB

    existing = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.source == OPENSHIFT_SOURCE,
            SystemEvent.created_at >= since,
            cast(SystemEvent.raw_data, JSONB)["external_key"].astext == ext_key,
        )
        .first()
    )
    if existing:
        existing.last_seen = now
        existing.occurrence_count = (existing.occurrence_count or 1) + 1
        if item.get("severity"):
            existing.severity = item["severity"]
        return False

    title = item.get("title") or "OpenShift olayı"
    event = SystemEvent(
        server_id=None,
        event_type="openshift_event",
        severity=item.get("severity") or "info",
        source=OPENSHIFT_SOURCE,
        title=title[:500],
        description=item.get("description"),
        raw_data={
            "platform": "openshift",
            "platform_label": "OpenShift Container Platform",
            "external_key": ext_key,
            "cluster_id": cluster.id,
            "cluster_name": cluster.name,
            "namespace": item.get("namespace"),
            "source_object": item.get("source_object"),
            "reason": item.get("reason"),
            "timestamp": item.get("timestamp"),
        },
        is_acknowledged=False,
        resolved=False,
        last_seen=now,
        occurrence_count=1,
    )
    db.add(event)
    return True


def sync_openshift_events_for_cluster(db: Session, cluster: OpenShiftCluster, hours: int = 48) -> Dict[str, Any]:
    """Tek OpenShift cluster'ı için event sync."""
    from app.services.openshift.cluster_ops import client_from_cluster

    client = client_from_cluster(cluster)

    try:
        items = client.list_events(hours=hours)
    except Exception as e:
        logger.exception("OpenShift event sync error (cluster=%s)", cluster.id)
        return {"success": False, "errors": [str(e)]}
    finally:
        client.logout()

    now = datetime.utcnow()
    saved = 0
    for item in items:
        if _upsert_openshift_event(db, cluster, item, now):
            saved += 1

    db.commit()

    if saved > 0:
        since_batch = datetime.utcnow() - timedelta(seconds=5)
        new_events = db.query(SystemEvent).filter(
            SystemEvent.source == OPENSHIFT_SOURCE,
            SystemEvent.created_at >= since_batch,
            SystemEvent.severity.in_(["critical", "emergency"]),
        ).all()
        for ev in new_events:
            try:
                auto_create_or_link_incident(db, ev)
            except Exception as exc:
                logger.warning("[AutoIncident] OpenShift event #%s: %s", ev.id, exc)

    return {"success": True, "cluster": cluster.name, "total_saved": saved, "total_events": len(items)}


def sync_all_openshift_events(db: Session, hours: int = 48) -> Dict[str, Any]:
    """Tüm OpenShift cluster'larından event sync."""
    clusters = db.query(OpenShiftCluster).all()
    results: List[Dict[str, Any]] = []
    total_saved = 0
    for c in clusters:
        try:
            r = sync_openshift_events_for_cluster(db, c, hours=hours)
            results.append(r)
            total_saved += r.get("total_saved", 0)
        except Exception as e:
            logger.exception("OpenShift event sync failed for %s", c.name)
            results.append({"success": False, "cluster": c.name, "errors": [str(e)]})
    return {"success": True, "total_saved": total_saved, "clusters": results}
