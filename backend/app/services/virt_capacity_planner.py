"""Cluster kapasite planlayıcı — effective kapasite, HA rezervi, N+1, tükenme, what-if.

Tüm hesap deterministiktir (LLM yalnız anlatır). Memory birincil kısıttır:
çalışan VM'in Memory'si host'a sığmazsa HA yeniden başlatma olmaz; CPU ise
aşırı abonelikle "yavaşlar" ama çalışır. Bu yüzden N+1 kararı Memory ile,
CPU yalnız uyarı olarak verilir.

Aksiyon sırası (ucuzdan pahalıya): geri kazanım → right-size → taşıma → yatırım.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services import virt_insights_data as vd
from app.services.report_analytics import (
    compute_trend_from_series, days_to_threshold_range, horizon_uncertainty_label,
)

MEM_THRESHOLD = 85.0
CPU_THRESHOLD = 80.0
DS_THRESHOLD = 85.0
N1_WARN_PCT = 90.0
VCPU_RATIO_WARN = 4.0
DS_RESERVE_PCT = 15.0
DEFAULT_CPU_ASSUMPTION = 0.5
RUNWAY_DAYS_ALERT = 90
DS_RUNWAY_DAYS_ALERT = 60


def _r(v: Optional[float], n: int = 1) -> Optional[float]:
    return None if v is None else round(float(v), n)


def _ha_reserve(platform: str, vc: Any, usable: List[Dict[str, Any]]) -> Dict[str, Any]:
    """HA politikasına göre ayrılan Memory/CPU (GB / çekirdek-eşdeğeri)."""
    mem_total = sum(h["mem_total_gb"] for h in usable)
    cpu_total = sum(float(h.get("cpu_cores") or 0) for h in usable)
    by_mem = sorted(usable, key=lambda h: h["mem_total_gb"], reverse=True)
    if len(usable) < 2:
        return {"policy": "single_host", "label": "Tek host — HA rezervi uygulanamaz (failover yok)",
                "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
    if platform == "vmware" and vc is not None:
        if not vc.ha_enabled:
            return {"policy": "ha_off", "label": "HA kapalı — rezerv yok", "mem_gb": 0.0, "cpu_cores": 0.0,
                    "assumed": False}
        if not vc.admission_control_enabled:
            return {"policy": "ac_off", "label": "Admission control kapalı — rezerv garanti değil",
                    "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
        pt = str(vc.policy_type or "").lower()
        if "resource" in pt or "percent" in pt or vc.mem_failover_pct:
            mp = float(vc.mem_failover_pct or 0)
            cp = float(vc.cpu_failover_pct or 0)
            return {"policy": "percentage", "label": f"Yüzde politikası (CPU %{cp:.0f} / Memory %{mp:.0f})",
                    "mem_gb": mem_total * mp / 100.0, "cpu_cores": cpu_total * cp / 100.0, "assumed": False}
        n = int(vc.failover_level or 1)
        top = by_mem[:n]
        return {"policy": "failover_level", "label": f"Host failover seviyesi = {n}",
                "mem_gb": sum(h["mem_total_gb"] for h in top),
                "cpu_cores": sum(float(h.get("cpu_cores") or 0) for h in top), "assumed": False}
    top = by_mem[:1]
    return {"policy": "assumed_n1", "label": "Varsayım: 1 host rezerv (platform politikası okunmadı)",
            "mem_gb": sum(h["mem_total_gb"] for h in top),
            "cpu_cores": sum(float(h.get("cpu_cores") or 0) for h in top), "assumed": True}


def _runway(series: List[Optional[float]], current: Optional[float], threshold: float) -> Dict[str, Any]:
    trend = compute_trend_from_series(series, min_samples=14)
    rng = days_to_threshold_range(current, trend, threshold)
    return {
        "threshold": threshold,
        "daily_slope": _r(trend.daily_slope, 3),
        "confidence": trend.confidence,
        "samples": trend.sample_count,
        "days": rng,
        "uncertainty": horizon_uncertainty_label(rng),
    }


def _cluster_vms(vms: List[Dict[str, Any]], hv_id: int, cluster: str, host_names: set) -> List[Dict[str, Any]]:
    out = []
    for v in vms:
        if v["hypervisor_id"] != hv_id:
            continue
        if (v.get("cluster") and v["cluster"] == cluster) or (not v.get("cluster") and v.get("host") in host_names):
            out.append(v)
    return out


def _analyze_cluster(db: Session, hv, platform: str, cluster: str, hosts: List[Dict[str, Any]],
                     vms: List[Dict[str, Any]], vc: Any, p95: Dict, with_forecast: bool = True) -> Dict[str, Any]:
    usable = [h for h in hosts if h["usable"]]
    host_names = {h["host_name"] for h in hosts}
    cvms = _cluster_vms(vms, hv.id, cluster, host_names)
    on = [v for v in cvms if v["powered_on"]]

    mem_total = sum(h["mem_total_gb"] for h in usable)
    mem_used = sum(h["mem_used_gb"] for h in usable)
    cpu_total = sum(float(h.get("cpu_cores") or 0) for h in usable)
    cpu_used = sum(h["cpu_used_cores"] for h in usable)
    reserve = _ha_reserve(platform, vc, usable)
    mem_eff = max(mem_total - reserve["mem_gb"], 0.0)
    cpu_eff = max(cpu_total - reserve["cpu_cores"], 0.0)

    largest = max(usable, key=lambda h: h["mem_total_gb"], default=None)
    n1: Dict[str, Any] = {"evaluable": len(usable) >= 2}
    if largest and len(usable) >= 2:
        rem_mem = mem_total - largest["mem_total_gb"]
        rem_cpu = cpu_total - float(largest.get("cpu_cores") or 0)
        n1.update({
            "largest_host": largest["host_name"],
            "largest_host_mem_gb": _r(largest["mem_total_gb"]),
            "remaining_mem_gb": _r(rem_mem),
            "mem_after_pct": _r(100.0 * mem_used / rem_mem) if rem_mem > 0 else None,
            "cpu_after_pct": _r(100.0 * cpu_used / rem_cpu) if rem_cpu > 0 else None,
        })
        m = n1["mem_after_pct"]
        n1["status"] = "fail" if m is None or m > 100 else ("warn" if m > N1_WARN_PCT else "ok")
        n1["cpu_warning"] = bool(n1["cpu_after_pct"] and n1["cpu_after_pct"] > 100)
    else:
        n1["status"] = "single_host" if len(usable) == 1 else "no_data"

    vcpu = sum(v["vcpu"] for v in on)
    alloc_mem = sum(v["memory_gb"] for v in on)
    net = None
    if platform == "vmware":
        net = _network_headroom(db, hv.id, usable, p95)

    out: Dict[str, Any] = {
        "platform": platform, "hypervisor_id": hv.id, "hypervisor": hv.name, "cluster": cluster,
        "hosts_total": len(hosts), "hosts_usable": len(usable),
        "hosts_excluded": [
            {"host": h["host_name"],
             "reason": "bakım modunda" if h.get("maintenance_mode") else f"bağlantı: {h.get('connection_state')}"}
            for h in hosts if not h["usable"]
        ],
        "memory": {
            "total_gb": _r(mem_total), "used_gb": _r(mem_used), "reserved_gb": _r(reserve["mem_gb"]),
            "effective_gb": _r(mem_eff),
            "used_pct": _r(100.0 * mem_used / mem_total) if mem_total else None,
            "effective_used_pct": _r(100.0 * mem_used / mem_eff) if mem_eff else None,
            "allocated_gb": _r(alloc_mem),
            "allocation_ratio": _r(alloc_mem / mem_total, 2) if mem_total else None,
        },
        "cpu": {
            "total_cores": _r(cpu_total), "used_cores": _r(cpu_used), "reserved_cores": _r(reserve["cpu_cores"]),
            "effective_cores": _r(cpu_eff),
            "used_pct": _r(100.0 * cpu_used / cpu_total) if cpu_total else None,
            "effective_used_pct": _r(100.0 * cpu_used / cpu_eff) if cpu_eff else None,
            "vcpu_allocated": vcpu,
            "vcpu_ratio": _r(vcpu / cpu_total, 2) if cpu_total else None,
        },
        "ha": reserve,
        "n_plus_one": n1,
        "network": net,
        "vm_count": len(cvms), "vm_powered_on": len(on),
        "typical_host_mem_gb": _r(sorted(h["mem_total_gb"] for h in usable)[len(usable) // 2]) if usable else None,
        "typical_host_cores": (sorted(float(h.get("cpu_cores") or 0) for h in usable)[len(usable) // 2]
                               if usable else None),
    }
    if with_forecast:
        series = vd.daily_cluster_series(db, hv.id, cluster, [h["host_name"] for h in usable])
        out["forecast"] = {
            "memory": _runway(series["mem_pct"], out["memory"]["used_pct"], MEM_THRESHOLD),
            "cpu": _runway(series["cpu_pct"], out["cpu"]["used_pct"], CPU_THRESHOLD),
        }
    return out


def _network_headroom(db: Session, hv_id: int, usable: List[Dict[str, Any]], p95: Dict) -> Optional[Dict[str, Any]]:
    from app.models.hypervisor_inventory import HypervisorHostInventory
    inv = {i.host_name: i for i in db.query(HypervisorHostInventory)
           .filter(HypervisorHostInventory.hypervisor_id == hv_id).all()}
    rows = []
    for h in usable:
        i = inv.get(h["host_name"])
        pn = [p for p in (i.pnics or [] if i else []) if isinstance(p, dict)]
        cap_mb = sum(int(p.get("link_speed_mb") or 0) for p in pn)
        if not cap_mb:
            continue
        pk = p95.get((hv_id, h["host_name"])) or {}
        kbps = float(pk.get("net_p95") or 0)
        rows.append({"host": h["host_name"], "link_mb": cap_mb, "p95_mbps": round(kbps * 8 / 1000, 1),
                     "util_pct": round(100.0 * kbps * 8 / 1000 / cap_mb, 1)})
    if not rows:
        return None
    rows.sort(key=lambda r: r["util_pct"], reverse=True)
    return {"hosts": rows[:10], "max_util_pct": rows[0]["util_pct"],
            "note": "p95 (Rx+Tx) / toplam fiziksel link hızı — tek NIC doygunluğunu göstermez"}


def _datastores(db: Session, hv_ids: List[int], with_forecast: bool = True) -> List[Dict[str, Any]]:
    out = []
    for d in vd.latest_datastores(db, hv_ids):
        cap = d.get("capacity_gb") or 0
        row = dict(d)
        row["provisioned_pct"] = (
            _r(100.0 * ((d.get("used_gb") or 0) + (d.get("uncommitted_gb") or 0)) / cap) if cap else None
        )
        if with_forecast:
            row["forecast"] = _runway(vd.daily_datastore_series(db, d["hypervisor_id"], d["name"]),
                                      d.get("usage_pct"), DS_THRESHOLD)
        out.append(row)
    out.sort(key=lambda r: (r.get("usage_pct") or 0), reverse=True)
    return out


def _actions(c: Dict[str, Any], reclaim: Dict[str, Any], others: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ucuzdan pahalıya aksiyon önerileri + yatırım ihtiyacı (host adedi)."""
    acts: List[Dict[str, Any]] = []
    mem = c["memory"]
    need_gb = 0.0
    n1 = c["n_plus_one"]
    if n1.get("remaining_mem_gb"):
        target = n1["remaining_mem_gb"] * (N1_WARN_PCT / 100.0)
        need_gb = max(0.0, (mem["used_gb"] or 0) - target)
    rc = reclaim or {}
    rec_off = float(rc.get("powered_off_memory_gb") or 0)
    rec_idle = float(rc.get("idle_memory_gb") or 0)
    rec_size = float(rc.get("oversized_memory_gb") or 0)
    if rec_off or rc.get("snapshot_gb") or rc.get("orphan_gb"):
        acts.append({
            "step": 1, "kind": "reclaim",
            "title": "Geri kazanım",
            "detail": (f"Kapalı VM'ler {rec_off:.0f} GB Memory tahsisi tutuyor (çalışan Memory'yi azaltmaz, "
                       f"yeniden açılma riskini kaldırır); snapshot {float(rc.get('snapshot_gb') or 0):.0f} GB, "
                       f"sahipsiz disk {float(rc.get('orphan_gb') or 0):.0f} GB."),
            "memory_gb": round(rec_off, 1),
        })
    if rec_idle or rec_size:
        acts.append({
            "step": 2, "kind": "right_size", "title": "Right-size",
            "detail": f"Atıl VM'ler {rec_idle:.0f} GB, aşırı boyutlu VM'ler ~{rec_size:.0f} GB Memory serbest bırakabilir.",
            "memory_gb": round(rec_idle + rec_size, 1),
        })
    movable = [o for o in others if o["cluster"] != c["cluster"] and (o["memory"].get("effective_used_pct") or 100) < 70
               and o["n_plus_one"].get("status") == "ok"]
    if need_gb > 0 and movable:
        best = sorted(movable, key=lambda o: o["memory"].get("effective_used_pct") or 100)[0]
        acts.append({
            "step": 3, "kind": "move", "title": "Taşıma",
            "detail": (f"{best['hypervisor']} / {best['cluster']} cluster'ında effective Memory doluluğu "
                       f"%{best['memory'].get('effective_used_pct')} — bazı VM'ler oraya taşınabilir "
                       "(ağ/datastore erişimi doğrulanmalı)."),
            "target": {"hypervisor_id": best["hypervisor_id"], "cluster": best["cluster"]},
        })
    freed = rec_idle + rec_size
    remaining = max(0.0, need_gb - freed)
    host_gb = c.get("typical_host_mem_gb") or 0
    if remaining > 0 and host_gb:
        hosts_needed = math.ceil(remaining / (host_gb * N1_WARN_PCT / 100.0))
        acts.append({
            "step": 4, "kind": "invest", "title": "Yatırım",
            "detail": (f"Geri kazanım ve right-size sonrası N+1 için ~{remaining:.0f} GB Memory açığı kalıyor: "
                       f"mevcut host profiliyle ({host_gb:.0f} GB) {hosts_needed} host eklenmeli."),
            "hosts_needed": hosts_needed, "memory_gap_gb": round(remaining, 1),
        })
    elif need_gb > 0:
        acts.append({"step": 4, "kind": "invest", "title": "Yatırım gerekmiyor (koşullu)",
                     "detail": f"N+1 açığı ({need_gb:.0f} GB) geri kazanım + right-size ile kapanabilir; "
                               "önce bunları uygulayın.", "hosts_needed": 0})
    return acts


def _reclaim_by_cluster(db: Session, hv_ids: List[int]) -> Dict[Tuple[int, str], Dict[str, Any]]:
    try:
        from app.services.virt_reclaim import reclaim_rollup_by_cluster
        return reclaim_rollup_by_cluster(db, hv_ids)
    except Exception:
        return {}


def build_capacity(db: Session, *, hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
                   platform: Optional[str] = None, with_forecast: bool = True) -> Dict[str, Any]:
    hvs = vd.virt_hypervisors(db, platform=platform, hypervisor_id=hypervisor_id)
    hv_ids = [h.id for h in hvs]
    hosts = vd.latest_hosts(db, hv_ids)
    vms = vd.vm_allocations(db, hv_ids)
    vcs = vd.virt_cluster_rows(db, hv_ids)
    p95 = vd.host_p95(db, hv_ids)
    by_hv = {h.id: h for h in hvs}
    grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for hv in hvs:
        hv_hosts = [h for h in hosts if h["hypervisor_id"] == hv.id]
        hv_hosts = vd.worker_filter(db, hv, hv_hosts)
        for h in hv_hosts:
            grouped[(hv.id, h.get("cluster_name") or "(cluster yok)")].append(h)
    clusters = []
    for (hid, cname), hs in sorted(grouped.items(), key=lambda kv: (by_hv[kv[0][0]].name, kv[0][1])):
        if cluster and cname != cluster:
            continue
        hv = by_hv[hid]
        plat = vd.platform_of(hv) or "vmware"
        clusters.append(_analyze_cluster(db, hv, plat, cname, hs, vms, vcs.get((hid, cname)), p95,
                                         with_forecast=with_forecast))
    reclaim = _reclaim_by_cluster(db, hv_ids)
    for c in clusters:
        c["reclaim"] = reclaim.get((c["hypervisor_id"], c["cluster"]), {})
        c["actions"] = _actions(c, c["reclaim"], [o for o in clusters if o["hypervisor_id"] == c["hypervisor_id"]])
    ds = _datastores(db, [h.id for h in hvs if vd.platform_of(h) in ("vmware", "olvm")], with_forecast)
    for d in ds:
        d["hypervisor"] = by_hv[d["hypervisor_id"]].name if d["hypervisor_id"] in by_hv else None
    return {
        "ok": True,
        "clusters": clusters,
        "datastores": ds,
        "thresholds": {"memory": MEM_THRESHOLD, "cpu": CPU_THRESHOLD, "datastore": DS_THRESHOLD,
                       "n1_warn": N1_WARN_PCT, "vcpu_ratio": VCPU_RATIO_WARN},
        "method": ("Memory birincil kısıt (N+1 kararı); CPU çekirdek-eşdeğeri, uyarı amaçlı. "
                   "Tükenme tahmini: 90 günlük günlük ortalama, Theil–Sen eğimi, aralık (hızlı/tipik/yavaş)."),
    }


def simulate(db: Session, *, vcpu: int, memory_gb: float, disk_gb: float = 0.0, count: int = 1,
             hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
             cpu_util_assumption: float = DEFAULT_CPU_ASSUMPTION) -> Dict[str, Any]:
    """"Şu profilde N VM gelirse nereye sığar?" — her cluster için sonuç."""
    count = max(1, int(count or 1))
    vcpu = max(1, int(vcpu or 1))
    memory_gb = max(0.0, float(memory_gb or 0))
    disk_gb = max(0.0, float(disk_gb or 0))
    cpu_util_assumption = min(1.0, max(0.05, float(cpu_util_assumption or DEFAULT_CPU_ASSUMPTION)))
    cap = build_capacity(db, hypervisor_id=hypervisor_id, cluster=cluster, with_forecast=False)
    add_mem = memory_gb * count
    add_cpu = vcpu * count * cpu_util_assumption
    add_vcpu = vcpu * count
    add_disk = disk_gb * count
    ds_by_hv: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for d in cap["datastores"]:
        if d.get("accessible") is not False:
            ds_by_hv[d["hypervisor_id"]].append(d)
    cluster_ds = _cluster_datastore_names(db, cap["clusters"])
    results = []
    for c in cap["clusters"]:
        reasons: List[str] = []
        mem, cpu, n1 = c["memory"], c["cpu"], c["n_plus_one"]
        mem_used = (mem["used_gb"] or 0) + add_mem
        cpu_used = (cpu["used_cores"] or 0) + add_cpu
        eff_mem_pct = 100.0 * mem_used / mem["effective_gb"] if mem["effective_gb"] else None
        eff_cpu_pct = 100.0 * cpu_used / cpu["effective_cores"] if cpu["effective_cores"] else None
        n1_after = (100.0 * mem_used / n1["remaining_mem_gb"]) if n1.get("remaining_mem_gb") else None
        ratio_after = ((cpu["vcpu_allocated"] or 0) + add_vcpu) / cpu["total_cores"] if cpu["total_cores"] else None
        fits = True
        if eff_mem_pct is None or eff_mem_pct > MEM_THRESHOLD:
            fits = False
            reasons.append(f"Effective Memory %{_r(eff_mem_pct)} > %{MEM_THRESHOLD:.0f}")
        if n1_after is not None and n1_after > 100:
            fits = False
            reasons.append(f"N+1 bozulur (en büyük host düşünce Memory %{_r(n1_after)})")
        elif n1_after is not None and n1_after > N1_WARN_PCT:
            reasons.append(f"N+1 sınırda (%{_r(n1_after)})")
        if eff_cpu_pct is not None and eff_cpu_pct > CPU_THRESHOLD:
            reasons.append(f"CPU effective %{_r(eff_cpu_pct)} — performans riski (uyarı)")
        if ratio_after and ratio_after > VCPU_RATIO_WARN:
            reasons.append(f"vCPU:çekirdek {ratio_after:.1f}:1 (uyarı)")
        if c["hosts_usable"] == 0:
            fits = False
            reasons.append("Kullanılabilir host yok")
        if vcpu > (c.get("typical_host_cores") or 0) and c.get("typical_host_cores"):
            reasons.append(f"Tek VM vCPU ({vcpu}) host çekirdeğinden ({c['typical_host_cores']:.0f}) fazla")
        ds_pick = None
        if add_disk:
            names = cluster_ds.get((c["hypervisor_id"], c["cluster"]))
            cands = [d for d in ds_by_hv.get(c["hypervisor_id"], []) if not names or d["name"] in names]
            best = None
            for d in cands:
                capg = d.get("capacity_gb") or 0
                free_after = (d.get("free_gb") or 0) - add_disk
                if capg and free_after >= capg * DS_RESERVE_PCT / 100.0:
                    if best is None or free_after > best[1]:
                        best = (d, free_after)
            if best:
                ds_pick = {"name": best[0]["name"], "free_after_gb": _r(best[1]),
                           "usage_after_pct": _r(100.0 - 100.0 * best[1] / best[0]["capacity_gb"])}
            else:
                fits = False
                reasons.append(f"%{DS_RESERVE_PCT:.0f} rezerv korunarak {add_disk:.0f} GB alacak datastore yok")
        score = None
        if eff_mem_pct is not None:
            score = round(100 - eff_mem_pct * 0.6 - (eff_cpu_pct or 0) * 0.3 - (n1_after or 0) * 0.1, 1)
        results.append({
            "platform": c["platform"], "hypervisor_id": c["hypervisor_id"], "hypervisor": c["hypervisor"],
            "cluster": c["cluster"], "fits": fits, "reasons": reasons, "score": score,
            "after": {
                "memory_effective_pct": _r(eff_mem_pct), "cpu_effective_pct": _r(eff_cpu_pct),
                "n1_memory_pct": _r(n1_after), "vcpu_ratio": _r(ratio_after, 2),
            },
            "before": {
                "memory_effective_pct": mem["effective_used_pct"], "cpu_effective_pct": cpu["effective_used_pct"],
                "n1_memory_pct": n1.get("mem_after_pct"), "vcpu_ratio": cpu["vcpu_ratio"],
            },
            "datastore": ds_pick,
        })
    results.sort(key=lambda r: (not r["fits"], -(r["score"] or -999)))
    return {
        "ok": True,
        "request": {"vcpu": vcpu, "memory_gb": memory_gb, "disk_gb": disk_gb, "count": count,
                    "cpu_util_assumption": cpu_util_assumption},
        "assumptions": [
            "Yeni VM'in Memory'si tamamen kullanılıyor kabul edilir (en kötü durum).",
            f"CPU kullanımı vCPU başına %{cpu_util_assumption * 100:.0f} varsayılır.",
            f"Datastore'da %{DS_RESERVE_PCT:.0f} boş alan rezervi korunur.",
            "HA rezervi cluster politikasından; okunamıyorsa 1 host varsayılır.",
        ],
        "results": results,
        "best": next((r for r in results if r["fits"]), None),
    }


def _cluster_datastore_names(db: Session, clusters: List[Dict[str, Any]]) -> Dict[Tuple[int, str], set]:
    """VMware: cluster'ın gördüğü datastore'lar (config snapshot). Diğerleri: kısıt yok."""
    out: Dict[Tuple[int, str], set] = {}
    by_hv = defaultdict(list)
    for c in clusters:
        if c["platform"] == "vmware":
            by_hv[c["hypervisor_id"]].append(c["cluster"])
    for hid, names in by_hv.items():
        cl = {x["name"]: x for x in vd.latest_config(db, "vmware", hid, "cluster")}
        ds = {x["ref"]: x["name"] for x in vd.latest_config(db, "vmware", hid, "datastore")}
        for n in names:
            refs = ((cl.get(n) or {}).get("config") or {}).get("datastore_refs") or []
            if refs:
                out[(hid, n)] = {ds.get(r, r) for r in refs}
    return out


def capacity_findings(cap: Dict[str, Any]) -> Dict[Tuple[str, int], List[Any]]:
    """Kapasite sonucu → (platform, hypervisor_id) başına bulgu taslakları."""
    from app.services.findings.store import FindingDraft
    out: Dict[Tuple[str, int], List[FindingDraft]] = defaultdict(list)
    for c in cap["clusters"]:
        key = (c["platform"], c["hypervisor_id"])
        ref = f"cluster:{c['cluster']}"
        n1 = c["n_plus_one"]
        if n1.get("evaluable"):
            st = n1.get("status")
            out[key].append(FindingDraft(
                "cap.cluster.n_plus_one", "cluster", ref, c["cluster"],
                "fail" if st in ("fail", "warn") else "pass",
                evidence={k: n1.get(k) for k in ("largest_host", "largest_host_mem_gb", "remaining_mem_gb",
                                                 "mem_after_pct", "cpu_after_pct")},
                detail=(f"En büyük host ({n1.get('largest_host')}) düşünce Memory %{n1.get('mem_after_pct')}"
                        + (" — sığmıyor" if st == "fail" else " — sınırda" if st == "warn" else "")),
                cluster_name=c["cluster"], severity="critical" if st == "fail" else ("high" if st == "warn" else None),
            ))
        fm = (c.get("forecast") or {}).get("memory") or {}
        days = (fm.get("days") or {}).get("typical") if fm.get("days") else None
        if fm:
            out[key].append(FindingDraft(
                "cap.cluster.mem_runway", "cluster", ref, c["cluster"],
                "fail" if days is not None and days < RUNWAY_DAYS_ALERT else
                ("pass" if fm.get("confidence") not in ("none",) else "not_measurable"),
                evidence={"used_pct": c["memory"]["used_pct"], **fm},
                detail=(f"Memory %{MEM_THRESHOLD:.0f} eşiği aşılmış (%{c['memory']['used_pct']})" if days == 0
                        else f"Memory %{MEM_THRESHOLD:.0f} eşiğine ~{days} gün" if days is not None
                        else "Eşiğe ulaşma öngörülmüyor / veri yetersiz"),
                cluster_name=c["cluster"], severity="critical" if days == 0 else None,
            ))
        fc = (c.get("forecast") or {}).get("cpu") or {}
        cdays = (fc.get("days") or {}).get("typical") if fc.get("days") else None
        if fc:
            out[key].append(FindingDraft(
                "cap.cluster.cpu_runway", "cluster", ref, c["cluster"],
                "fail" if cdays is not None and cdays < RUNWAY_DAYS_ALERT else
                ("pass" if fc.get("confidence") != "none" else "not_measurable"),
                evidence={"used_pct": c["cpu"]["used_pct"], **fc},
                detail=(f"CPU %{CPU_THRESHOLD:.0f} eşiği aşılmış (%{c['cpu']['used_pct']})" if cdays == 0
                        else f"CPU %{CPU_THRESHOLD:.0f} eşiğine ~{cdays} gün" if cdays is not None
                        else "Eşiğe ulaşma öngörülmüyor / veri yetersiz"),
                cluster_name=c["cluster"],
            ))
        ratio = c["cpu"].get("vcpu_ratio")
        if ratio is not None:
            out[key].append(FindingDraft(
                "cap.cluster.vcpu_ratio", "cluster", ref, c["cluster"],
                "fail" if ratio > VCPU_RATIO_WARN else "pass",
                evidence={"vcpu": c["cpu"]["vcpu_allocated"], "cores": c["cpu"]["total_cores"], "ratio": ratio},
                detail=f"vCPU:çekirdek = {ratio}:1", cluster_name=c["cluster"],
            ))
    for d in cap["datastores"]:
        plat = "vmware"
        for c in cap["clusters"]:
            if c["hypervisor_id"] == d["hypervisor_id"]:
                plat = c["platform"]
                break
        key = (plat, d["hypervisor_id"])
        ref = f"datastore:{d['ref'] or d['name']}"
        u = d.get("usage_pct")
        if u is not None:
            out[key].append(FindingDraft(
                "cap.datastore.usage", "datastore", ref, d["name"], "fail" if u >= DS_THRESHOLD else "pass",
                evidence={"usage_pct": u, "free_gb": d.get("free_gb"), "capacity_gb": d.get("capacity_gb")},
                detail=f"Doluluk %{u}", severity="critical" if u >= 95 else None,
            ))
        f = d.get("forecast") or {}
        dd = (f.get("days") or {}).get("typical") if f.get("days") else None
        if f and u is not None and u < DS_THRESHOLD:
            out[key].append(FindingDraft(
                "cap.datastore.runway", "datastore", ref, d["name"],
                "fail" if dd is not None and dd < DS_RUNWAY_DAYS_ALERT else
                ("pass" if f.get("confidence") != "none" else "not_measurable"),
                evidence=f, detail=(f"%{DS_THRESHOLD:.0f} eşiğine ~{dd} gün" if dd is not None else "Trend yok"),
            ))
    return out
