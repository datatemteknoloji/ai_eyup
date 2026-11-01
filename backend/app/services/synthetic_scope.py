"""Sentetik / demo kayıt ayrımı.

Tek kural: bir kayıt sentetiktir eğer
- `meta_data.fake_seed` veya `meta_data.synthetic` doğruysa, veya
- adı `ZZ-FAKE` ile başlıyorsa (hypervisor, OpenShift cluster, sunucu) ya da `zz-hwdemo-` ile başlıyorsa (donanım demo sunucuları), veya
- entegrasyon `kind` değeri `_demo` ile bitiyorsa (`veeam_demo`, `hw_demo`).

Sunucu satırında ayrı bayrak yok; sentetik hypervisor'a bağlıysa sentetiktir.
Kayıt silinmez. `mark()` yalnız `synthetic: true` yazar.
Yönetici raporu bu kümeyi dışlar. Dashboard, sohbet ve /infra-reports bu modülü çağırmaz.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.integration_instance import IntegrationInstance
from app.models.openshift import OpenShiftCluster
from app.models.server import Server

NAME_PREFIX = "ZZ-FAKE"
# Donanım demo tohumunun sunucuları (zz-hwdemo-lnx-01, zz-hwdemo-win-01 …): ad kuralıyla sentetik (küçük harf; kayıt silinmez).
_DEMO_NAME_PREFIXES = ("zz-hwdemo-",)


def _meta(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def meta_is_synthetic(meta: Any) -> bool:
    m = _meta(meta)
    return bool(m.get("fake_seed") or m.get("synthetic"))


def name_is_synthetic(name: Optional[str]) -> bool:
    n = name or ""
    return n.startswith(NAME_PREFIX) or n.lower().startswith(_DEMO_NAME_PREFIXES)


def kind_is_synthetic(kind: Optional[str]) -> bool:
    return (kind or "").endswith("_demo")


def hypervisor_is_synthetic(hv: Hypervisor) -> bool:
    return meta_is_synthetic(hv.meta_data) or name_is_synthetic(hv.name)


def cluster_is_synthetic(cluster: OpenShiftCluster) -> bool:
    return meta_is_synthetic(cluster.meta_data) or name_is_synthetic(cluster.name)


def integration_is_synthetic(row: IntegrationInstance) -> bool:
    if kind_is_synthetic(row.kind):
        return True
    try:
        meta = json.loads(row.meta_json) if row.meta_json else {}
    except (TypeError, ValueError):
        meta = {}
    return meta_is_synthetic(meta)


def synthetic_hypervisor_ids(db: Session) -> Set[int]:
    return {h.id for h in db.query(Hypervisor).all() if hypervisor_is_synthetic(h)}


def synthetic_cluster_ids(db: Session) -> Set[int]:
    return {c.id for c in db.query(OpenShiftCluster).all() if cluster_is_synthetic(c)}


def synthetic_integration_ids(db: Session) -> Set[int]:
    return {r.id for r in db.query(IntegrationInstance).all() if integration_is_synthetic(r)}


def synthetic_server_ids(db: Session, hypervisor_ids: Optional[Iterable[int]] = None) -> Set[int]:
    hv_ids = set(hypervisor_ids) if hypervisor_ids is not None else synthetic_hypervisor_ids(db)
    ids: Set[int] = set()
    q = db.query(Server.id, Server.name, Server.hypervisor_id)
    for sid, name, hv_id in q.all():
        if (hv_id and hv_id in hv_ids) or name_is_synthetic(name):
            ids.add(sid)
    return ids


def _stamp_meta(meta: Any) -> Dict[str, Any]:
    out = dict(_meta(meta))
    out["synthetic"] = True
    return out


def mark(db: Session) -> Dict[str, int]:
    """Tespit edilen kayıtlara synthetic=true yazar. Silmez."""
    n_hv = n_cl = n_in = 0
    for hv in db.query(Hypervisor).all():
        if hypervisor_is_synthetic(hv) and not _meta(hv.meta_data).get("synthetic"):
            hv.meta_data = _stamp_meta(hv.meta_data)
            n_hv += 1
    for cl in db.query(OpenShiftCluster).all():
        if cluster_is_synthetic(cl) and not _meta(cl.meta_data).get("synthetic"):
            cl.meta_data = _stamp_meta(cl.meta_data)
            n_cl += 1
    for row in db.query(IntegrationInstance).all():
        if not integration_is_synthetic(row):
            continue
        try:
            meta = json.loads(row.meta_json) if row.meta_json else {}
        except (TypeError, ValueError):
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if not meta.get("synthetic"):
            meta["synthetic"] = True
            row.meta_json = json.dumps(meta, ensure_ascii=False)
            n_in += 1
    db.commit()
    return {"hypervisors": n_hv, "clusters": n_cl, "integrations": n_in}


def inventory(db: Session) -> List[Dict[str, Any]]:
    """Tespit raporu: tablo, adet, nasıl tanındı."""
    rows: List[Dict[str, Any]] = []
    hv_ids = synthetic_hypervisor_ids(db)
    for hv in db.query(Hypervisor).filter(Hypervisor.id.in_(hv_ids or [-1])).all():
        how = []
        if meta_is_synthetic(hv.meta_data):
            how.append("meta_data.fake_seed/synthetic")
        if name_is_synthetic(hv.name):
            how.append("ad ZZ-FAKE")
        rows.append({"table": "hypervisors", "id": hv.id, "name": hv.name, "how": ", ".join(how)})
    cl_ids = synthetic_cluster_ids(db)
    for cl in db.query(OpenShiftCluster).filter(OpenShiftCluster.id.in_(cl_ids or [-1])).all():
        how = []
        if meta_is_synthetic(cl.meta_data):
            how.append("meta_data.fake_seed/synthetic")
        if name_is_synthetic(cl.name):
            how.append("ad ZZ-FAKE")
        rows.append({"table": "openshift_clusters", "id": cl.id, "name": cl.name, "how": ", ".join(how)})
    for row in db.query(IntegrationInstance).all():
        if integration_is_synthetic(row):
            rows.append({
                "table": "integration_instances", "id": row.id, "name": row.label or row.kind,
                "how": f"kind={row.kind}",
            })
    srv_n = len(synthetic_server_ids(db, hv_ids))
    rows.append({
        "table": "servers", "id": None, "name": f"{srv_n} sunucu",
        "how": "sentetik hypervisor'a bağlı veya ad ZZ-FAKE",
    })
    return rows
