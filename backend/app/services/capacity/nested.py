"""İç içe katman (H.0 #11): OpenShift node'u bir VM ise, alttaki platformun yolu ve alt cluster'ın N+1 durumu.

Eşleme YALNIZ envanterdeki VM adı ↔ OCP node adı (tam ad veya kısa ad; büyük/küçük harf duyarsız) ile yapılır.
Birden fazla VM aynı kısa adla eşleşirse (farklı instance'larda aynı ad) eşleme YAPILMAZ — "belirsiz" olarak
raporlanır (yanlış cluster'a bağlamaktansa ölçülemez demek). Node'un `providerID` alanı toplanmadığı için
kimlik tabanlı eşleme yok (Doğrulanmadı listesinde). Ek vCenter/OLVM/OCP çağrısı yok: yalnız envanter ve kapasite tabloları.

Alt katmanın N+1'i alt cluster'ın kendi hesabıdır (aynı motor); OCP katmanının N+1'i ayrıca verilir (iki katmanlı sonuç).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence

from app.services.capacity import hierarchy as cap_hier

NOTE_NO_MATCH = "Node adı hiçbir VM ile eşleşmedi (fiziksel olabilir veya envanterde yok) — alt katman ölçülemedi"
NOTE_AMBIGUOUS = "Node adı birden fazla VM ile eşleşiyor — alt katman belirsiz, eşleme yapılmadı"


def _short(name: str) -> str:
    return (name or "").strip().lower().split(".")[0]


def _index(vms: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in vms:
        n = (v.get("name") or "").strip().lower()
        if n:
            idx[n].append(v)
            if _short(n) != n:
                idx[_short(n)].append(v)
    return idx


def match_underlay(node_names: Sequence[str], vms: Sequence[Dict[str, Any]],
                   clusters: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """`vms`: vm_allocations satırları (name, hypervisor_id, cluster, host). `clusters`: build_capacity cluster'ları
    (hypervisor_id, cluster, hypervisor, datacenter, path, n_plus_one, platform)."""
    by_key = {cap_hier.cluster_key(c["hypervisor_id"], c["cluster"]): c for c in clusters}
    idx = _index(vms)
    nodes: List[Dict[str, Any]] = []
    for name in node_names:
        cands = {id(v): v for v in idx.get((name or "").strip().lower(), [])}
        if not cands:
            cands = {id(v): v for v in idx.get(_short(name), [])}
        row: Dict[str, Any] = {"node": name, "matched": False, "ambiguous": False, "notes": []}
        if len(cands) > 1:
            row["ambiguous"] = True
            row["notes"].append(NOTE_AMBIGUOUS)
        elif not cands:
            row["notes"].append(NOTE_NO_MATCH)
        else:
            v = next(iter(cands.values()))
            c = by_key.get(cap_hier.cluster_key(v["hypervisor_id"], v.get("cluster") or "(cluster yok)"))
            row.update({"matched": True, "vm": v.get("name"), "host": v.get("host"), "instance_id": v["hypervisor_id"],
                        "cluster": v.get("cluster") or "(cluster yok)"})
            if c is not None:
                row.update({"platform": c.get("platform"), "instance": c.get("hypervisor"),
                            "datacenter": c.get("datacenter"),
                            "path": cap_hier.path_str(c.get("hypervisor"), c.get("datacenter"), c["cluster"], v.get("host"))})
            else:
                row["notes"].append("VM'in cluster'ı kapasite tablosunda yok — alt cluster N+1 hesaplanamadı")
        nodes.append(row)

    under: Dict[Any, Dict[str, Any]] = {}
    for r in nodes:
        if not r["matched"]:
            continue
        key = cap_hier.cluster_key(r["instance_id"], r["cluster"])
        c = by_key.get(key)
        if c is None:
            continue
        u = under.setdefault(key, {"instance_id": r["instance_id"], "instance": c.get("hypervisor"),
                                   "cluster": c["cluster"], "datacenter": c.get("datacenter"),
                                   "path": cap_hier.path_str(c.get("hypervisor"), c.get("datacenter"), c["cluster"]),
                                   "n1": c.get("n_plus_one"), "nodes": [], "hosts": defaultdict(list)})
        u["nodes"].append(r["node"])
        if r.get("host"):
            u["hosts"][r["host"]].append(r["node"])
    notes: List[str] = []
    out_under: List[Dict[str, Any]] = []
    for u in under.values():
        shared = {h: ns for h, ns in u["hosts"].items() if len(ns) > 1}
        u["hosts"] = {h: ns for h, ns in u["hosts"].items()}
        u["shared_hosts"] = shared
        n1 = (u["n1"] or {}).get("status")
        u["n1_status"] = n1
        if n1 == "fail":
            notes.append(f"Alt cluster {u['path']}: N+1 bozulur — bir host düşerse OCP node'ları da etkilenir")
        for h, ns in shared.items():
            notes.append(f"{u['path']} / {h}: {len(ns)} OCP node'u aynı fiziksel host'ta ({', '.join(ns)})")
        out_under.append(u)
    out_under.sort(key=lambda u: u["path"])
    return {"nodes": nodes, "clusters": out_under, "notes": notes,
            "matched": sum(1 for r in nodes if r["matched"]), "total": len(nodes)}


def underlay_for_ocp(db, node_names: Sequence[str]) -> Optional[Dict[str, Any]]:
    """OCP node adları için alt katman bilgisi. VM/kapasite verisi okunamazsa None (OCP sayfası etkilenmez)."""
    from app.services import virt_capacity_planner as vcp
    from app.services import virt_insights_data as vd
    if not node_names:
        return None
    cap = vcp.build_capacity(db, with_forecast=False)
    ids = sorted({c["hypervisor_id"] for c in cap["clusters"]})
    if not ids:
        return None
    return match_underlay(node_names, vd.vm_allocations(db, ids), cap["clusters"])
