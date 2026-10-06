"""VM yerleştirme önerisi — filtre + puan (deterministik, açıklanabilir).

Filtreler (sert): bakım / bağlantısız host, yetersiz boş Memory, N+1'i bozma,
zorunlu (must) affinity / anti-affinity kuralları, datastore görünürlüğü.
Puan (0-100): boş Memory .35 · CPU payı .25 · CPU ready p95 .15 ·
disk latency p95 .15 · cluster dengesi .10. "Should" kurallar ceza puanıdır.

OpenShift Virtualization'da son kararı kube-scheduler verir; sonuç bilgi amaçlıdır.
Uygulama (vMotion / migrate) bu motorun işi değildir — Agent onay akışına gider.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.services import virt_insights_data as vd

WEIGHTS = {"memory": 0.35, "cpu": 0.25, "ready": 0.15, "latency": 0.15, "balance": 0.10}
MEM_HEADROOM_PCT = 5.0
READY_BAD_PCT = 10.0
LATENCY_BAD_MS = 30.0
SHOULD_PENALTY = 15.0


def _vm_lookup(db: Session, name: str, hypervisor_id: Optional[int]) -> Optional[Dict[str, Any]]:
    hvs = vd.virt_hypervisors(db, hypervisor_id=hypervisor_id)
    low = name.strip().lower()
    for v in vd.vm_allocations(db, [h.id for h in hvs]):
        if str(v["name"] or "").lower() == low:
            return v
    return None


def _vmware_rules(db: Session, hv_id: int, cluster: str) -> Dict[str, Any]:
    cl = next((c for c in vd.latest_config(db, "vmware", hv_id, "cluster") if c["name"] == cluster), None)
    cfg = (cl or {}).get("config") or {}
    groups = {g["name"]: g for g in cfg.get("groups") or []}
    return {"rules": [r for r in cfg.get("rules") or [] if r.get("enabled")], "groups": groups}


def _olvm_groups(db: Session, hv_id: int, cluster: str) -> List[Dict[str, Any]]:
    cl = next((c for c in vd.latest_config(db, "olvm", hv_id, "cluster") if c["name"] == cluster), None)
    return ((cl or {}).get("config") or {}).get("affinity_groups") or []


def _ds_mounts(db: Session, hv_id: int) -> Dict[str, Set[str]]:
    return {d["name"]: set((d.get("config") or {}).get("mounted_hosts") or [])
            for d in vd.latest_config(db, "vmware", hv_id, "datastore")}


def _constraints(db: Session, platform: str, hv_id: int, cluster: str, vm_name: Optional[str],
                 vms_by_host: Dict[str, Set[str]]) -> Dict[str, Any]:
    """Host adı → (yasak sebebi | ceza) haritası + açıklama listesi."""
    banned: Dict[str, str] = {}
    only: Optional[Set[str]] = None
    penalty: Dict[str, List[str]] = defaultdict(list)
    applied: List[Dict[str, Any]] = []
    if not vm_name:
        return {"banned": banned, "only": only, "penalty": penalty, "applied": applied}
    if platform == "vmware":
        rr = _vmware_rules(db, hv_id, cluster)
        for r in rr["rules"]:
            members = set(r.get("vm_names") or [])
            kind = r.get("kind")
            if kind == "vm_anti_affinity" and vm_name in members:
                others = members - {vm_name}
                hosts = {h for h, vs in vms_by_host.items() if vs & others}
                for h in hosts:
                    banned.setdefault(h, f"anti-affinity '{r['name']}'")
                applied.append({"rule": r["name"], "kind": kind, "effect": f"{len(hosts)} host hariç"})
            elif kind == "vm_affinity" and vm_name in members:
                others = members - {vm_name}
                hosts = {h for h, vs in vms_by_host.items() if vs & others}
                if hosts:
                    only = hosts if only is None else (only & hosts)
                    applied.append({"rule": r["name"], "kind": kind, "effect": f"yalnız {', '.join(sorted(hosts))}"})
            elif kind == "vm_host":
                vg = rr["groups"].get(r.get("vm_group") or "")
                if not vg or vm_name not in set(vg.get("member_names") or []):
                    continue
                aff = rr["groups"].get(r.get("affine_host_group") or "")
                anti = rr["groups"].get(r.get("anti_affine_host_group") or "")
                if aff:
                    hs = set(aff.get("member_names") or [])
                    if r.get("mandatory"):
                        only = hs if only is None else (only & hs)
                    else:
                        for h in vms_by_host:
                            if h not in hs:
                                penalty[h].append(f"should-run '{r['name']}'")
                    applied.append({"rule": r["name"], "kind": "vm_host_affine",
                                    "mandatory": r.get("mandatory"), "hosts": sorted(hs)})
                if anti:
                    hs = set(anti.get("member_names") or [])
                    for h in hs:
                        if r.get("mandatory"):
                            banned.setdefault(h, f"vm-host anti-affinity '{r['name']}'")
                        else:
                            penalty[h].append(f"should-not-run '{r['name']}'")
                    applied.append({"rule": r["name"], "kind": "vm_host_anti", "mandatory": r.get("mandatory"),
                                    "hosts": sorted(hs)})
    elif platform == "olvm":
        for g in _olvm_groups(db, hv_id, cluster):
            members = set(g.get("vms") or [])
            if vm_name not in members:
                continue
            others = members - {vm_name}
            if g.get("vm_rule_enabled") is not False and g.get("vm_positive") is False:
                hosts = {h for h, vs in vms_by_host.items() if vs & others}
                for h in hosts:
                    if g.get("vm_enforcing"):
                        banned.setdefault(h, f"negatif affinity '{g['name']}'")
                    else:
                        penalty[h].append(f"negatif affinity (soft) '{g['name']}'")
                applied.append({"rule": g["name"], "kind": "vm_negative", "enforcing": g.get("vm_enforcing")})
            if g.get("vm_rule_enabled") is not False and g.get("vm_positive") is True and others:
                hosts = {h for h, vs in vms_by_host.items() if vs & others}
                if hosts and g.get("vm_enforcing"):
                    only = hosts if only is None else (only & hosts)
                applied.append({"rule": g["name"], "kind": "vm_positive", "enforcing": g.get("vm_enforcing")})
            if g.get("hosts") and g.get("host_rule_enabled"):
                hs = set(g["hosts"])
                if g.get("host_positive") is not False:
                    if g.get("host_enforcing"):
                        only = hs if only is None else (only & hs)
                    else:
                        for h in vms_by_host:
                            if h not in hs:
                                penalty[h].append(f"host affinity (soft) '{g['name']}'")
                else:
                    for h in hs:
                        if g.get("host_enforcing"):
                            banned.setdefault(h, f"host negatif affinity '{g['name']}'")
                        else:
                            penalty[h].append(f"host negatif affinity (soft) '{g['name']}'")
                applied.append({"rule": g["name"], "kind": "host_affinity", "hosts": sorted(hs)})
    return {"banned": banned, "only": only, "penalty": penalty, "applied": applied}


def recommend_placement(db: Session, *, vm_name: Optional[str] = None, vcpu: Optional[int] = None,
                        memory_gb: Optional[float] = None, disk_gb: Optional[float] = None,
                        hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
                        top_n: int = 5) -> Dict[str, Any]:
    vm = None
    if vm_name:
        vm = _vm_lookup(db, vm_name, hypervisor_id)
        if not vm:
            return {"ok": False, "error": f"VM bulunamadı: {vm_name}"}
        hypervisor_id = vm["hypervisor_id"]
        vcpu = vcpu or vm["vcpu"]
        memory_gb = memory_gb if memory_gb is not None else vm["memory_gb"]
    vcpu = int(vcpu or 1)
    memory_gb = float(memory_gb or 0)
    hvs = vd.virt_hypervisors(db, hypervisor_id=hypervisor_id)
    hv_by = {h.id: h for h in hvs}
    hosts = vd.latest_hosts(db, [h.id for h in hvs])
    p95 = vd.host_p95(db, [h.id for h in hvs])
    allocs = vd.vm_allocations(db, [h.id for h in hvs])
    vms_by_host: Dict[Tuple[int, str], Set[str]] = defaultdict(set)
    for a in allocs:
        if a.get("host") and a["powered_on"]:
            vms_by_host[(a["hypervisor_id"], a["host"])].add(a["name"])

    by_cluster: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for hv in hvs:
        for h in vd.worker_filter(db, hv, [x for x in hosts if x["hypervisor_id"] == hv.id]):
            by_cluster[(hv.id, h.get("cluster_name") or "(cluster yok)")].append(h)

    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    rules_applied: List[Dict[str, Any]] = []
    mounts_cache: Dict[int, Dict[str, Set[str]]] = {}
    for (hid, cname), chosts in by_cluster.items():
        if cluster and cname != cluster:
            continue
        hv = hv_by[hid]
        platform = vd.platform_of(hv) or "vmware"
        usable = [h for h in chosts if h["usable"]]
        mem_total = sum(h["mem_total_gb"] for h in usable)
        mem_used = sum(h["mem_used_gb"] for h in usable)
        largest = max((h["mem_total_gb"] for h in usable), default=0)
        in_cluster = bool(vm and (vm.get("cluster") == cname or vm.get("host") in {h["host_name"] for h in chosts}))
        add = 0.0 if in_cluster else memory_gb
        n1_after = (100.0 * (mem_used + add) / (mem_total - largest)) if mem_total - largest > 0 else None
        avg_mem_pct = 100.0 * mem_used / mem_total if mem_total else 0
        cons = _constraints(db, platform, hid, cname, vm["name"] if vm else None,
                            {h["host_name"]: vms_by_host.get((hid, h["host_name"]), set()) for h in chosts})
        if cons["applied"]:
            rules_applied.extend([{**a, "cluster": cname} for a in cons["applied"]])
        ds_hosts: Optional[Set[str]] = None
        if platform == "vmware" and vm and vm.get("datastore"):
            if hid not in mounts_cache:
                mounts_cache[hid] = _ds_mounts(db, hid)
            m = mounts_cache[hid].get(vm["datastore"])
            if m:
                ds_hosts = m
        for h in chosts:
            name = h["host_name"]
            base = {"hypervisor_id": hid, "hypervisor": hv.name, "platform": platform, "cluster": cname, "host": name}
            if vm and vm.get("host") == name:
                rejected.append({**base, "reason": "VM zaten bu host'ta"})
                continue
            if not h["usable"]:
                rejected.append({**base, "reason": "bakım modunda" if h.get("maintenance_mode")
                                 else f"bağlantı: {h.get('connection_state')}"})
                continue
            free = h["mem_total_gb"] - h["mem_used_gb"]
            need = memory_gb * (1 + MEM_HEADROOM_PCT / 100.0)
            if free < need:
                rejected.append({**base, "reason": f"boş Memory {free:.0f} GB < gerekli {need:.0f} GB"})
                continue
            if n1_after is not None and n1_after > 100 and not in_cluster:
                rejected.append({**base, "reason": f"cluster N+1 bozulur (Memory %{n1_after:.0f})"})
                continue
            if name in cons["banned"]:
                rejected.append({**base, "reason": cons["banned"][name]})
                continue
            if cons["only"] is not None and name not in cons["only"]:
                rejected.append({**base, "reason": "zorunlu affinity kuralı dışında"})
                continue
            if ds_hosts is not None and h.get("host_ref") and h["host_ref"] not in ds_hosts:
                rejected.append({**base, "reason": f"datastore '{vm['datastore']}' bu host'a bağlı değil"})
                continue
            pk = p95.get((hid, name)) or {}
            cpu_p95 = float(pk.get("cpu_p95") or h.get("cpu_usage_pct") or 0)
            ready = float(pk.get("ready_p95") or 0)
            lat = float(pk.get("lat_p95") or 0)
            mem_after_pct = 100.0 * (h["mem_used_gb"] + memory_gb) / h["mem_total_gb"] if h["mem_total_gb"] else 100
            comp = {
                "memory": max(0.0, 1 - mem_after_pct / 100.0),
                "cpu": max(0.0, 1 - cpu_p95 / 100.0),
                "ready": max(0.0, 1 - min(ready / READY_BAD_PCT, 1.0)),
                "latency": max(0.0, 1 - min(lat / LATENCY_BAD_MS, 1.0)),
                "balance": max(0.0, 1 - abs(mem_after_pct - avg_mem_pct) / 100.0),
            }
            score = 100.0 * sum(WEIGHTS[k] * v for k, v in comp.items())
            pen = cons["penalty"].get(name) or []
            score -= SHOULD_PENALTY * len(pen)
            candidates.append({
                **base, "score": round(score, 1),
                "breakdown": {k: round(v * 100, 1) for k, v in comp.items()},
                "penalties": pen,
                "metrics": {"mem_free_gb": round(free, 1), "mem_after_pct": round(mem_after_pct, 1),
                            "cpu_p95_pct": round(cpu_p95, 1), "ready_p95_pct": round(ready, 2),
                            "latency_p95_ms": round(lat, 1), "vms_running": h.get("vms_running")},
                "cluster_n1_after_pct": round(n1_after, 1) if n1_after is not None else None,
                "informational": platform == "ocp_virt",
            })
    candidates.sort(key=lambda c: -c["score"])
    notes = ["Puan: boş Memory %35 · CPU payı %25 · CPU ready p95 %15 · disk latency p95 %15 · denge %10; "
             "'should' kural ihlali başına -15."]
    if any(c["informational"] for c in candidates):
        notes.append("OpenShift Virtualization: son kararı kube-scheduler verir; liste bilgi amaçlıdır.")
    if vm and vm.get("platform") != "vmware" and not rules_applied:
        notes.append("Kural bilgisi son config snapshot'ından okunur; ilk tur tamamlanmadıysa kurallar boş görünür.")
    return {
        "ok": True,
        "request": {"vm": vm["name"] if vm else None, "vcpu": vcpu, "memory_gb": memory_gb, "disk_gb": disk_gb,
                    "current_host": vm.get("host") if vm else None, "current_cluster": vm.get("cluster") if vm else None},
        "candidates": candidates[:max(1, top_n)],
        "rejected": rejected[:200],
        "rules": rules_applied,
        "weights": WEIGHTS,
        "notes": notes,
    }
