"""İş-1 geri yükleme: ocp_prune_stale_pods_once.py'nin yedek JSON'undan silinen pod satırlarını AYNI kimliklerle geri ekler.

Mevcut kimlikle çakışan satıra dokunmaz (ON CONFLICT DO NOTHING). Varsayılan DRY-RUN; --apply ile yazar.
  python /tmp/ocp_restore_stale_pods.py /tmp/openshift_workloads-stale.json [--apply]
"""
import json
import sys

from sqlalchemy import text

from app.core.database import SessionLocal

COLS = ["id", "cluster_id", "project", "kind", "name", "status", "node_name", "restart_count", "ready", "host",
        "meta_data", "created_at", "updated_at"]


def main() -> int:
    path = sys.argv[1]
    apply = "--apply" in sys.argv
    d = json.load(open(path, encoding="utf-8"))
    rows = d["rows"]
    db = SessionLocal()
    try:
        n = 0
        for r in rows:
            r = dict(r)
            r["meta_data"] = json.dumps(r["meta_data"]) if r.get("meta_data") is not None else None
            sql = ("INSERT INTO openshift_workloads (" + ",".join(COLS) + ") VALUES (" +
                   ",".join(f":{c}" for c in COLS) + ") ON CONFLICT (id) DO NOTHING")
            if apply:
                n += db.execute(text(sql), {c: r.get(c) for c in COLS}).rowcount or 0
        if apply:
            db.commit()
            print(f"geri eklendi: {n}/{len(rows)}")
        else:
            print(f"DRY-RUN: {len(rows)} satır geri eklenecekti (--apply ile yazar)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
