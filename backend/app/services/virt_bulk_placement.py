"""Toplu talep yerleşimi: birden fazla VM profili + anti-affinity grubu → cluster başına yerleşim planı.

Her cluster BAĞIMSIZ hesaplanır (toplama yok). Kurallar tek VM what-if ve host arızasıyla aynıdır:
  • HA rezervi + resource pool + Memory eşiği `placement.host_budgets` ile düşülür (host'lara orantılı).
  • VM'ler Memory'ye göre büyükten küçüğe, en boş host'a (eşitlikte ada göre) yerleştirilir.
  • Aynı anti-affinity grubundaki VM'ler FARKLI host'lara yerleşir; yetmezse "anti_affinity".
  • VM diski host'un erişebildiği datastore'da olmalı (host erişimi biliniyorsa).
  • CPU: host arızasındaki `failover.cpu_check` (p95 talebi vs etkin çekirdek; vCPU oranı yalnız uyarı).
Plan KAYDEDİLMEZ; istemci CSV olarak dışa aktarır.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services import capacity_policy, virt_insights_data as vd
from app.services.capacity import engine as cap_engine, failover as cap_fail, hierarchy as cap_hier
from app.services.capacity import placement as cap_place
from app.services.virt_capacity_planner import (
    DEFAULT_CPU_ASSUMPTION, T, _cluster_models, _cluster_vms, _host_datastores, _r, build_capacity)

MAX_PROFILES = 50
MAX_VMS = 2000


def normalize_profiles(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Girdiyi doğrular ve sadeleştirir (ValueError → 400)."""
    if not profiles:
        raise ValueError("En az bir VM profili girin")
    if len(profiles) > MAX_PROFILES:
        raise ValueError(f"En fazla {MAX_PROFILES} profil girilebilir")
    out, seen, total = [], set(), 0
    for p in profiles:
        name = str(p.get("name") or "").strip()
        if not name:
            raise ValueError("Profil adı boş olamaz")
        if name in seen:
            raise ValueError(f"Profil adı tekrar ediyor: {name}")
        seen.add(name)
        count = int(p.get("count") or 1)
        vcpu = int(p.get("vcpu") or 0)
        mem = float(p.get("memory_gb") or 0)
        disk = float(p.get("disk_gb") or 0)
        if count < 1 or count > 500:
            raise ValueError(f"{name}: adet 1–500 olmalı")
        if vcpu < 1:
            raise ValueError(f"{name}: vCPU en az 1 olmalı")
        if mem < 0 or disk < 0:
            raise ValueError(f"{name}: Memory/disk negatif olamaz")
        total += count
        out.append({"name": name, "count": count, "vcpu": vcpu, "memory_gb": mem, "disk_gb": disk,
                    "group": (str(p.get("group") or "").strip() or None)})
    if total > MAX_VMS:
        raise ValueError(f"Toplam VM sayısı en fazla {MAX_VMS} olabilir")
    return out


def expand(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vms = []
    for p in profiles:
        for i in range(1, p["count"] + 1):
            vms.append({**p, "vm": p["name"] if p["count"] == 1 else f"{p['name']}-{i}", "profile": p["name"]})
    return vms


def place_bulk(hosts: List[Dict[str, Any]], vms: List[Dict[str, Any]], datastores: Optional[List[Dict[str, Any]]],
               ds_reserve_pct: float) -> Dict[str, Any]:
    """Saf yerleştirme (DB yok): `hosts` = `host_budgets()["hosts"]`. Deterministik."""
    free = {h["name"]: h["free_gb"] for h in hosts}
    ds_state = [dict(d) for d in datastores] if datastores is not None else None
    on_host: Dict[str, set] = defaultdict(set)         # grup → dolu host'lar
    plan: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, Any]] = []
    for v in sorted(vms, key=lambda x: (-x["memory_gb"], -x["vcpu"], x["vm"])):
        mem, disk, grp = v["memory_gb"], v["disk_gb"], v.get("group")
        reason: Optional[str] = None
        cands = [h for h in hosts if free[h["name"]] >= mem]
        if not hosts:
            reason = "no_host"
        elif not cands:
            reason = "fragmentation" if sum(free.values()) >= mem else "memory"
        if reason is None and grp:
            cands = [h for h in cands if h["name"] not in on_host[grp]]
            if not cands:
                reason = "anti_affinity"
        if reason is None and disk > 0 and ds_state is not None:
            cands = [h for h in cands if any(cap_place._ds_ok(d, h["ref"], disk, ds_reserve_pct) for d in ds_state)]
            if not cands:
                reason = "datastore"
        if reason is not None:
            unplaced.append({"vm": v["vm"], "profile": v["profile"], "group": grp, "memory_gb": mem, "reason": reason})
            continue
        cands.sort(key=lambda h: (-free[h["name"]], h["name"]))
        pick = cands[0]
        free[pick["name"]] -= mem
        ds_pick = None
        if disk > 0 and ds_state is not None:
            opts = sorted((d for d in ds_state if cap_place._ds_ok(d, pick["ref"], disk, ds_reserve_pct)),
                          key=lambda d: (-(float(d.get("free_gb") or 0)), d["name"]))
            opts[0]["free_gb"] = float(opts[0].get("free_gb") or 0) - disk
            ds_pick = opts[0]["name"]
        if grp:
            on_host[grp].add(pick["name"])
        plan.append({"vm": v["vm"], "profile": v["profile"], "group": grp, "vcpu": v["vcpu"], "memory_gb": mem,
                     "disk_gb": disk, "host": pick["name"], "datastore": ds_pick})
    plan.sort(key=lambda r: (r["host"], r["vm"]))
    return {"plan": plan, "unplaced": unplaced, "free": free}


def bulk_place(db: Session, *, profiles: List[Dict[str, Any]], hypervisor_id: Optional[int] = None,
               clusters: Optional[List[str]] = None, datacenter: Optional[str] = None,
               hosts: Optional[List[str]] = None, platforms: Optional[List[str]] = None,
               cpu_util_assumption: float = DEFAULT_CPU_ASSUMPTION) -> Dict[str, Any]:
    profiles = normalize_profiles(profiles)
    vms = expand(profiles)
    util = min(1.0, max(0.05, float(cpu_util_assumption or DEFAULT_CPU_ASSUMPTION)))
    cap = build_capacity(db, hypervisor_id=hypervisor_id, with_forecast=False)
    if clusters:
        cap["clusters"] = [c for c in cap["clusters"] if c["cluster"] in set(clusters)]
    if datacenter:
        cap["clusters"] = [c for c in cap["clusters"] if c.get("datacenter") == datacenter]
    if platforms:
        cap["clusters"] = [c for c in cap["clusters"] if c["platform"] in set(platforms)]
    models = _cluster_models(db, cap)
    hv_ids = sorted({c["hypervisor_id"] for c in cap["clusters"]})
    all_vms = vd.vm_allocations(db, hv_ids)
    usage = cap_fail.p95_index(db, hv_ids) if hv_ids else {}
    groups: Dict[str, int] = defaultdict(int)
    for v in vms:
        if v["group"]:
            groups[v["group"]] += 1
    results: List[Dict[str, Any]] = []
    for c in cap["clusters"]:
        capacity_policy.activate(values=c.get("thresholds") or cap["thresholds"])
        model = models.get(cap_hier.cluster_key(c["hypervisor_id"], c["cluster"]))
        if model is None:
            continue
        b = cap_place.host_budgets(model, T.mem)
        hs = b["hosts"]
        if hosts:
            hs = [h for h in hs if h["name"] in set(hosts)]
        dss, ds_note = _host_datastores(db, cap, c)
        r = place_bulk(hs, vms, dss, T.ds_reserve)
        notes = list(b["pools"]["notes"])
        if b["reserve"]["mem_gb"] > 0:
            notes.append(cap_place.NOTE_RESERVE_SPREAD)
        if ds_note and any(v["disk_gb"] > 0 for v in vms):
            notes.append(ds_note)
        if dss is None and any(v["disk_gb"] > 0 for v in vms):
            notes.append(cap_place.NOTE_DS_UNKNOWN)
        for g, n in groups.items():
            if n > len(hs):
                notes.append(f"Anti-affinity grubu '{g}' {n} VM içeriyor ama bu cluster'da yalnız {len(hs)} uygun host var.")
        if hosts:
            notes.append("Host kapsamı yalnız aday host'ları daraltır; HA rezervi tüm cluster üzerinden hesaplanır.")
        # küme geneli etki (yerleşenler üzerinden) — tek VM what-if ile aynı motor
        placed_mem = sum(p["memory_gb"] for p in r["plan"])
        placed_vcpu = sum(p["vcpu"] for p in r["plan"])
        pl = cap_engine.place(c, add_mem=placed_mem, add_cpu=placed_vcpu * util, add_vcpu=float(placed_vcpu),
                              vcpu_single=max((p["vcpu"] for p in r["plan"]), default=0), thr=T,
                              overcommit=(c["memory"] or {}).get("overcommit"))
        # CPU: host arızasıyla aynı kontrol — mevcut açık VM'lerin p95 talebi + yeni VM'ler (vCPU × varsayım)
        names = {n.name for n in model.nodes}
        on = [v for v in _cluster_vms(all_vms, c["hypervisor_id"], c["cluster"], names) if v["powered_on"]]
        needs = [cap_fail.vm_need(v, usage.get((c["hypervisor_id"], v["name"]))) for v in on]
        cores = float((c["cpu"] or {}).get("effective_cores") or (c["cpu"] or {}).get("total_cores") or 0)
        cov = cap_fail.coverage(needs)
        cpu = cap_fail.cpu_check(
            remaining_cores=cores, vcpu_total=sum(n["vcpu"] for n in needs) + placed_vcpu,
            demand_cores=sum(n["cpu_p95_cores"] for n in needs) + placed_vcpu * util,
            thr_pct=T.cpu, ratio_limit=T.vcpu_ratio, cov=cov) if r["plan"] else None
        limiting: List[str] = []
        for u in r["unplaced"]:
            code = {"memory": "memory", "fragmentation": "fragmentation", "datastore": "datastore",
                    "anti_affinity": "anti_affinity", "no_host": "no_host"}[u["reason"]]
            if code not in limiting:
                limiting.append(code)
        warn_codes: List[str] = []
        if r["plan"] and not pl["fits"]:
            for code in pl.get("limiting") or []:
                if code not in limiting:
                    limiting.append(code)
        if cpu and cpu["verdict"] == "fail" and "cpu" not in limiting:
            limiting.append("cpu")
        if cpu and cpu["verdict"] == "tight":
            warn_codes.append("cpu")
        if cpu and cpu["ratio_warn"]:
            warn_codes.append("vcpu_ratio")
        fits = not r["unplaced"] and not limiting
        by_host: Dict[str, Dict[str, Any]] = {}
        for h in hs:
            by_host[h["name"]] = {"host": h["name"], "vms": 0, "memory_gb": 0.0, "free_after_gb": _r(r["free"][h["name"]], 2)}
        for p in r["plan"]:
            by_host[p["host"]]["vms"] += 1
            by_host[p["host"]]["memory_gb"] = _r(by_host[p["host"]]["memory_gb"] + p["memory_gb"], 2)
        mem, cp, n1 = c["memory"], c["cpu"], c["n_plus_one"]
        results.append({
            "platform": c["platform"], "hypervisor_id": c["hypervisor_id"], "hypervisor": c["hypervisor"],
            "cluster": c["cluster"], "path": c.get("path"), "standalone": bool(c.get("standalone")),
            "requested": len(vms), "placed": len(r["plan"]), "unplaced_count": len(r["unplaced"]),
            "fits": fits, "status": "fail" if not fits else ("warn" if warn_codes else "ok"),
            "limiting": limiting, "warn_codes": warn_codes,
            "plan": [{**p, "path": cap_hier.path_str(c["hypervisor"], c.get("datacenter"), c["cluster"], p["host"])}
                     for p in r["plan"]],
            "unplaced": r["unplaced"], "by_host": list(by_host.values()), "cpu": cpu,
            "before": {"memory_effective_pct": mem["effective_used_pct"], "vcpu_ratio": cp["vcpu_ratio"],
                       "n1_memory_pct": n1.get("mem_after_pct")},
            "after": {"memory_effective_pct": _r(pl["eff_mem_pct"]), "vcpu_ratio": _r(pl["ratio_after"], 2),
                      "n1_memory_pct": _r(pl["n1_after"])},
            "notes": notes, "confidence": "medium" if (c.get("ha") or {}).get("assumed") else "high",
        })
    capacity_policy.activate(db)
    results.sort(key=lambda x: (not x["fits"], x["unplaced_count"], x["cluster"]))
    return {
        "ok": True,
        "request": {"profiles": profiles, "total_vms": len(vms), "cpu_util_assumption": util},
        "assumptions": [
            "Yeni VM'lerin Memory'si tamamen kullanılıyor kabul edilir (en kötü durum).",
            f"Yeni VM'lerin CPU kullanımı vCPU başına %{util * 100:.0f} varsayılır.",
            "Her cluster bağımsız hesaplanır; kapasite cluster'lar arasında toplanmaz.",
            "HA rezervi cluster politikasından; okunamıyorsa 1 host varsayılır.",
            "Aynı anti-affinity grubundaki VM'ler farklı host'lara yerleşir (sert kural).",
            "Plan kaydedilmez; CSV olarak dışa aktarılabilir.",
        ],
        "results": results,
    }
