from collections import Counter
from app.core.database import SessionLocal
from app.models.openshift import OpenShiftCluster, OpenShiftWorkload, OpenShiftNode, OpenShiftProject
from app.services.openshift.cluster_ops import client_from_cluster
db = SessionLocal()
try:
    c = db.query(OpenShiftCluster).filter(OpenShiftCluster.name == "oVirt").first()
    cl = client_from_cluster(c)
    pods = cl.list_pods(); err = cl.last_error
    nodes = cl.list_nodes(); projs = cl.list_projects()
    live = Counter((p.get("status") or "Unknown") for p in pods)
    db_pods = Counter(w.status for w in db.query(OpenShiftWorkload).filter_by(cluster_id=c.id, kind="pod"))
    print("err:", err or "-")
    print("CANLI pod:", len(pods), dict(live))
    print("DB    pod:", sum(db_pods.values()), dict(db_pods))
    live_keys = {(p.get("namespace") or p.get("project"), p.get("name")) for p in pods}
    dbw = db.query(OpenShiftWorkload).filter_by(cluster_id=c.id, kind="pod").all()
    db_keys = {(w.project, w.name) for w in dbw}
    print("canlıda olup DB'de olmayan:", len(live_keys - db_keys), "| DB'de olup canlıda olmayan (bayat):", len(db_keys - live_keys))
    err_set = {"error", "crashloopbackoff", "runcontainererror"}
    print("hatalı(Error/CrashLoop/RunContainerError) canlı:", sum(v for k, v in live.items() if k.lower() in err_set),
          "DB:", sum(v for k, v in db_pods.items() if (k or '').lower() in err_set))
    print("node canlı:", len(nodes), "DB:", db.query(OpenShiftNode).filter_by(cluster_id=c.id).count(),
          "| proje canlı:", len(projs), "DB:", db.query(OpenShiftProject).filter_by(cluster_id=c.id).count())
finally:
    db.close()
