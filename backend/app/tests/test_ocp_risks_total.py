"""OpenShift /risks: `total` limit'ten ÖNCEKİ gerçek risk sayısıdır (dashboard «24 / 61» göstersin)."""
from app.models.openshift import OpenShiftCluster, OpenShiftWorkload
from app.services.openshift_health import list_risk_workloads, list_risk_workloads_page
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401


def _seed(db, n_bad: int):
    c = OpenShiftCluster(name="ocp", api_url="https://api.x:6443", connection_config={})
    db.add(c)
    db.flush()
    for i in range(n_bad):
        db.add(OpenShiftWorkload(cluster_id=c.id, project="app", kind="pod", name=f"bad-{i}",
                                 status="CrashLoopBackOff" if i == 0 else "Pending", node_name="w1"))
    db.add(OpenShiftWorkload(cluster_id=c.id, project="app", kind="pod", name="ok", status="Running", node_name="w1"))
    db.commit()
    return c


def test_total_is_untruncated_count(isolated_db):
    db = isolated_db
    c = _seed(db, 7)
    items, total = list_risk_workloads_page(db, cluster_id=c.id, limit=3)
    assert len(items) == 3 and total == 7
    assert items[0].name == "bad-0"           # kritik (CrashLoopBackOff) başta
    # Eski imza aynı sıralama/limit davranışını korur
    assert [w.name for w in list_risk_workloads(db, cluster_id=c.id, limit=3)] == [w.name for w in items]


def test_total_excludes_healthy_and_non_pods(isolated_db):
    db = isolated_db
    c = _seed(db, 2)
    db.add(OpenShiftWorkload(cluster_id=c.id, project="app", kind="deployment", name="dep", status="Pending"))
    db.commit()
    _, total = list_risk_workloads_page(db, cluster_id=c.id, limit=100)
    assert total == 2
