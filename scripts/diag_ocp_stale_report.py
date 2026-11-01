"""OpenShift bayat satır DRY-RUN raporu — YALNIZ OKUR (canlı API GET + DB SELECT); hiçbir şey silmez/yazmaz.

Her gerçek (sahte olmayan) cluster için: pod / deployment / service / route / node / proje
canlı anahtar kümesi ↔ DB anahtar kümesi; "DB'de olup canlıda olmayan" (bayat) sayısı,
bayatların updated_at dağılımı ve örnekler. Başarısız/kısmi liste çekimi (client.last_error)
olan türde bayat HESAPLANMAZ ("güvenilmez") — gerçek prune'un da aynı kuralı izlemesi gerekir.

Kullanım (backend konteyneri, PYTHONPATH=/app):
  python /tmp/diag_ocp_stale_report.py [--json /tmp/ocp-stale.json]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from app.core.database import SessionLocal
from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.services.openshift.cluster_ops import client_from_cluster
from app.services.openshift.fake_cluster import is_fake


def _age_bucket(ts, now):
    if ts is None:
        return "updated_at NULL"
    d = (now - ts).days
    return "<1g" if d < 1 else ("1-7g" if d <= 7 else ">7g")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    out = []
    try:
        for c in db.query(OpenShiftCluster).order_by(OpenShiftCluster.id).all():
            if is_fake(c):
                out.append({"cluster": c.name, "skipped": "sahte (fake) cluster"})
                continue
            cl = client_from_cluster(c)
            live = {}
            try:
                for kind, fn in (
                    ("pod", cl.list_pods), ("deployment", cl.list_deployments),
                    ("service", cl.list_services), ("route", cl.list_routes),
                    ("node", cl.list_nodes), ("project", cl.list_projects),
                ):
                    cl.last_error = ""
                    items = fn()
                    live[kind] = {"items": items, "err": cl.last_error or ""}
            finally:
                try:
                    cl.logout()
                except Exception:
                    pass
            rep = {"cluster": c.name, "last_sync": str(c.last_sync), "kinds": {}}
            for kind in ("pod", "deployment", "service", "route"):
                rows = db.query(OpenShiftWorkload).filter_by(cluster_id=c.id, kind=kind).all()
                lk = {(i.get("namespace"), i.get("name")) for i in live[kind]["items"]}
                dk = {(r.project, r.name): r for r in rows}
                stale = [dk[k] for k in dk if k not in lk]
                reliable = not live[kind]["err"]
                rep["kinds"][kind] = {
                    "live": len(lk), "db": len(dk), "live_err": live[kind]["err"] or None,
                    "stale": len(stale) if reliable else "güvenilmez (liste hatası)",
                    "missing_in_db": len(lk - set(dk)),
                    "stale_by_updated_at": dict(Counter(_age_bucket(r.updated_at, now) for r in stale)) if reliable else None,
                    "db_newest_updated_at": str(max((r.updated_at for r in rows if r.updated_at), default=None)),
                    "stale_examples": [f"{r.project}/{r.name}" for r in stale[:5]] if reliable else [],
                }
            for kind, model, key in (("node", OpenShiftNode, "name"), ("project", OpenShiftProject, "name")):
                rows = db.query(model).filter_by(cluster_id=c.id).all()
                lk = {i.get("name") for i in live[kind]["items"]}
                dk = {getattr(r, key) for r in rows}
                reliable = not live[kind]["err"]
                rep["kinds"][kind] = {
                    "live": len(lk), "db": len(dk), "live_err": live[kind]["err"] or None,
                    "stale": len(dk - lk) if reliable else "güvenilmez (liste hatası)",
                    "missing_in_db": len(lk - dk),
                }
            out.append(rep)
    finally:
        db.close()
    txt = json.dumps(out, ensure_ascii=False, indent=1, default=str)
    print(txt)
    if a.json:
        open(a.json, "w").write(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
