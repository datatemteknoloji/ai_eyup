"""İş-1 — bir defalık bayat pod temizliği (kullanıcı onaylı; 2026-10-15 karar).

Her gerçek (sahte olmayan) cluster için: canlı pod listesi TAM ve hatasız ise, DB'de olup canlıda olmayan
`kind='pod'` satırlarını (YALNIZ o cluster) önce JSON'a yedekler (tüm sütunlar), sonra kimlik listesiyle TEK işlemde siler.
Başka tabloya/tür'e dokunmaz. Varsayılan DRY-RUN; silmek için --apply.

Güvenlik: liste TAM değilse / hata varsa / boşsa → hiçbir şey yapmaz. Bayat sayısı --expect değerinden
--tolerance (varsayılan %10) fazla sapıyorsa DURUR (silmez, çıkış kodu 3).

Kullanım (backend konteyneri, PYTHONPATH=/app):
  python /tmp/ocp_prune_stale_pods_once.py --expect 456 --backup-dir /tmp/backup-ocp-stale [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.openshift import OpenShiftCluster, OpenShiftWorkload
from app.services.openshift.cluster_ops import client_from_cluster
from app.services.openshift.fake_cluster import is_fake


def _row_dict(r: OpenShiftWorkload) -> dict:
    out = {}
    for col in OpenShiftWorkload.__table__.columns:
        v = getattr(r, col.name)
        out[col.name] = v.isoformat() if isinstance(v, datetime) else v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", type=int, required=True)
    ap.add_argument("--tolerance", type=float, default=0.10)
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    db = SessionLocal()
    rc = 0
    try:
        for c in db.query(OpenShiftCluster).order_by(OpenShiftCluster.id).all():
            if is_fake(c):
                print(f"[{c.name}] sahte cluster → atlandı")
                continue
            client = client_from_cluster(c)
            try:
                ok, detail = client.test_connection()
                if not ok:
                    print(f"[{c.name}] bağlantı başarısız ({detail}) → HİÇBİR ŞEY yapılmadı")
                    rc = 2
                    continue
                pods = client.list_pods()
                complete = bool(getattr(client, "pods_complete", False)) and not (client.last_error or "")
            finally:
                client.logout()
            if not complete or not pods:
                print(f"[{c.name}] pod listesi TAM değil/boş (complete={complete}, n={len(pods)}, err={client.last_error!r}) → HİÇBİR ŞEY yapılmadı")
                rc = 2
                continue
            live = {(p["namespace"], p["name"]) for p in pods}
            rows = db.query(OpenShiftWorkload).filter(
                OpenShiftWorkload.cluster_id == c.id, OpenShiftWorkload.kind == "pod"
            ).all()
            stale = [r for r in rows if (r.project, r.name) not in live]
            dev = abs(len(stale) - a.expect) / max(a.expect, 1)
            print(f"[{c.name}] canlı {len(live)} · DB pod {len(rows)} · bayat {len(stale)} (beklenen {a.expect}, sapma %{dev*100:.1f})")
            if dev > a.tolerance:
                print(f"[{c.name}] sapma > %{a.tolerance*100:.0f} → DURULDU, silinmedi")
                rc = 3
                continue
            if not stale:
                continue
            os.makedirs(a.backup_dir, exist_ok=True)
            bpath = os.path.join(a.backup_dir, "openshift_workloads-stale.json")
            payload = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "cluster": {"id": c.id, "name": c.name},
                "table": "openshift_workloads",
                "kind": "pod",
                "count": len(stale),
                "rows": [_row_dict(r) for r in stale],
            }
            with open(bpath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
            os.chmod(bpath, 0o600)
            print(f"[{c.name}] yedek yazıldı: {bpath} ({len(stale)} satır)")
            if not a.apply:
                print(f"[{c.name}] DRY-RUN: silinmedi (--apply ile siler)")
                continue
            ids = [r.id for r in stale]
            deleted = (
                db.query(OpenShiftWorkload)
                .filter(OpenShiftWorkload.cluster_id == c.id, OpenShiftWorkload.kind == "pod",
                        OpenShiftWorkload.id.in_(ids))
                .delete(synchronize_session=False)
            )
            if deleted != len(ids):
                db.rollback()
                print(f"[{c.name}] BEKLENMEDİK: silinen {deleted} ≠ {len(ids)} → GERİ ALINDI")
                rc = 4
                continue
            db.commit()
            after = db.query(OpenShiftWorkload).filter(
                OpenShiftWorkload.cluster_id == c.id, OpenShiftWorkload.kind == "pod").count()
            print(f"[{c.name}] SİLİNDİ {deleted} satır · DB pod şimdi {after} (canlı {len(live)})")
    finally:
        db.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
