"""OpenShift notu sanallaştırma kaynağını saymaz."""
from app.models.event import SystemEvent
from app.services.platform_scope import apply_platform_filter


def test_openshift_filter_drops_virt_and_ovirt_sources(isolated_db):
    db = isolated_db
    db.add(SystemEvent(
        event_type="openshift_virt_event", source="openshift_virt_event",
        severity="critical", title="DataVolume",
        raw_data={"platform": "openshift"},
    ))
    db.add(SystemEvent(
        event_type="ovirt_event", source="ovirt_event",
        severity="warning", title="OLVM host",
        raw_data={"platform": "openshift"},
    ))
    db.add(SystemEvent(
        event_type="openshift_event", source="openshift_collector",
        severity="critical", title="Pod Failed",
        raw_data={"platform": "openshift", "cluster_id": 2, "reason": "Failed"},
    ))
    db.commit()

    titles = {row.title for row in apply_platform_filter(db.query(SystemEvent), "openshift", db).all()}
    assert titles == {"Pod Failed"}
