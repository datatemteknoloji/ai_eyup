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

from app.services import capacity_policy, virt_insights_data as vd
from app.services.capacity import adapters as cap_adapters, engine as cap_engine, engine_mode
from app.services.capacity import failover as cap_fail, hierarchy as cap_hier, placement as cap_place, sources as cap_src
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


class _Thr:
    """Aktif eşikler (capacity_policies → ContextVar); modül sabitleri yalnız varsayılandır."""
    mem = property(lambda self: capacity_policy.active()["memory"])
    cpu = property(lambda self: capacity_policy.active()["cpu"])
    ds = property(lambda self: capacity_policy.active()["datastore"])
    n1_warn = property(lambda self: capacity_policy.active()["n1_warn"])
    vcpu_ratio = property(lambda self: capacity_policy.active()["vcpu_ratio"])
    ds_reserve = property(lambda self: capacity_policy.active()["ds_reserve"])


T = _Thr()


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


RUNWAY_WINDOW_DAYS = 90
RUNWAY_MIN_DAYS = 14


def _runway(series: List[Optional[float]], current: Optional[float], threshold: float) -> Dict[str, Any]:
    """Tükenme tahmini. Eski alanlara ek olarak `state` (neden hesaplanmadı), `data_days`/`window_days`/`min_days`:
    ok | exceeded | insufficient_data | low_confidence | flat | no_current."""
    trend = compute_trend_from_series(series, min_samples=RUNWAY_MIN_DAYS)
    rng = days_to_threshold_range(current, trend, threshold)
    if current is None:
        state = "no_current"
    elif current >= threshold:
        state = "exceeded"
    elif trend.sample_count < RUNWAY_MIN_DAYS:
        state = "insufficient_data"
    elif trend.confidence in ("none", "low"):
        state = "low_confidence"
    elif rng is None:
        state = "flat"
    else:
        state = "ok"
    return {
        "threshold": threshold,
        "daily_slope": _r(trend.daily_slope, 3),
        "confidence": trend.confidence,
        "samples": trend.sample_count,
        "days": rng,
        "uncertainty": horizon_uncertainty_label(rng),
        "state": state, "data_days": trend.sample_count,
        "window_days": RUNWAY_WINDOW_DAYS, "min_days": RUNWAY_MIN_DAYS,
    }


def _cluster_ds_runway(db: Session, c: Dict[str, Any], ds: List[Dict[str, Any]], host_refs: set) -> Dict[str, Any]:
    """Cluster host'larının ERİŞEBİLDİĞİ datastore'ların runway'i (ortak datastore her cluster'da ayrı listelenir,
    toplanmaz). VMware: datastore `mounted_hosts` ∩ cluster host'ları. OLVM/OpenShift Virt: eşleme yok → ölçülemedi."""
    base = {"threshold": T.ds, "items": [], "worst": None}
    plat = c["platform"]
    if plat != "vmware":
        return {**base, "state": "unmeasurable",
                "reason": "olvm_no_mapping" if plat == "olvm" else "no_storage_mapping"}
    rows = cap_src.vmware_datastore_access(db, c["hypervisor_id"], c["cluster"], ds)
    if rows is None:
        return {**base, "state": "unmeasurable", "reason": "no_cluster_datastore_config"}
    by_name = {(d["hypervisor_id"], d["name"]): d for d in ds}
    items = []
    for r in rows:
        refs = r.get("host_refs")
        if refs is not None and not (refs & host_refs):
            continue                      # hiçbir cluster host'u bu datastore'a bağlı değil
        d = by_name.get((c["hypervisor_id"], r["name"]))
        if d is None:
            continue
        f = d.get("forecast") or {}
        items.append({"name": r["name"], "usage_pct": d.get("usage_pct"), "free_gb": d.get("free_gb"),
                      "access": "host_mount" if refs is not None else "cluster_config", "forecast": f})
    if not items:
        return {**base, "state": "unmeasurable", "reason": "no_accessible_datastore"}
    with_days = [i for i in items if (i["forecast"].get("days") or {}).get("typical") is not None]
    worst = min(with_days, key=lambda i: i["forecast"]["days"]["typical"]) if with_days else None
    items.sort(key=lambda i: ((i["forecast"].get("days") or {}).get("typical", 10 ** 9), -(i["usage_pct"] or 0)))
    return {**base, "state": "ok", "reason": None, "items": items, "worst": (
        {"name": worst["name"], "days": worst["forecast"]["days"]} if worst else None),
        "min_data_days": min((i["forecast"].get("data_days", 0) for i in items), default=0)}


def _cluster_vms(vms: List[Dict[str, Any]], hv_id: int, cluster: str, host_names: set) -> List[Dict[str, Any]]:
    out = []
    for v in vms:
        if v["hypervisor_id"] != hv_id:
            continue
        if (v.get("cluster") and v["cluster"] == cluster) or (not v.get("cluster") and v.get("host") in host_names):
            out.append(v)
    return out


def _core_legacy(usable: List[Dict[str, Any]], vc: Any, platform: str) -> Dict[str, Any]:
    """ESKİ hesap (CAPACITY_ENGINE=legacy): bir sürüm boyunca korunur; eşdeğerlik testleri karşılaştırır."""
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
        n1["status"] = "fail" if m is None or m > 100 else ("warn" if m > T.n1_warn else "ok")
        n1["cpu_warning"] = bool(n1["cpu_after_pct"] and n1["cpu_after_pct"] > 100)
    else:
        n1["status"] = "single_host" if len(usable) == 1 else "no_data"
    return {"mem_total": mem_total, "mem_used": mem_used, "cpu_total": cpu_total, "cpu_used": cpu_used,
            "reserve": reserve, "mem_eff": mem_eff, "cpu_eff": cpu_eff, "n1": n1}


def _olvm_cluster_cfg(db: Session, hv_id: int, cluster: str) -> Optional[Dict[str, Any]]:
    """OLVM cluster yapılandırması (config snapshot; ek API çağrısı yok). Yoksa None. (H.0: `capacity.sources`)"""
    return cap_src.olvm_cluster_cfg(db, hv_id, cluster)


def _core_unified(db: Session, hv, platform: str, cluster: str, hosts: List[Dict[str, Any]], vc: Any,
                  on: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ortak motor (`app.services.capacity`): düğüm kapasitesi, HA rezervi ve N+1 tek yerde."""
    cfg = _olvm_cluster_cfg(db, hv.id, cluster) if platform == "olvm" else None
    model = cap_adapters.from_virt_hosts(platform, cluster, [h for h in hosts], vc, olvm_cfg=cfg, vms_on=on,
                                         failover_hosts=_failover_hosts(db, platform, hv.id, cluster, vc))
    return cap_engine.summarize(model, T.n1_warn)


def _failover_hosts(db: Session, platform: str, hv_id: int, cluster: str, vc: Any) -> Optional[List[str]]:
    """E3: yalnız "dedicated failover hosts" politikasında ayrılmış host'ları config snapshot'tan okur (aksi: None)."""
    if platform == "vmware" and "failoverhost" in str(getattr(vc, "policy_type", "") or "").lower():
        return cap_src.vmware_failover_hosts(db, hv_id, cluster)
    return None


def _analyze_cluster(db: Session, hv, platform: str, cluster: str, hosts: List[Dict[str, Any]],
                     vms: List[Dict[str, Any]], vc: Any, p95: Dict, with_forecast: bool = True) -> Dict[str, Any]:
    usable = [h for h in hosts if h["usable"]]
    host_names = {h["host_name"] for h in hosts}
    cvms = _cluster_vms(vms, hv.id, cluster, host_names)
    on = [v for v in cvms if v["powered_on"]]

    if engine_mode() == "legacy":
        core = _core_legacy(usable, vc, platform)
    else:
        core = _core_unified(db, hv, platform, cluster, hosts, vc, on)
    mem_total, mem_used, cpu_total, cpu_used = core["mem_total"], core["mem_used"], core["cpu_total"], core["cpu_used"]
    reserve, mem_eff, cpu_eff, n1 = core["reserve"], core["mem_eff"], core["cpu_eff"], core["n1"]

    vcpu = sum(v["vcpu"] for v in on)
    alloc_mem = sum(v["memory_gb"] for v in on)
    net = None
    if platform == "vmware":
        net = _network_headroom(db, hv.id, usable, p95)

    out: Dict[str, Any] = {
        "platform": platform, "hypervisor_id": hv.id, "hypervisor": hv.name, "cluster": cluster,
        "hosts_total": len(hosts), "hosts_usable": len(usable),
        "host_names": sorted(h["host_name"] for h in usable),     # H.0 kapsam seçici (host) için
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
            **({"overcommit": core["overcommit"]} if core.get("overcommit") else {}),
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
            "memory": _runway(series["mem_pct"], out["memory"]["used_pct"], T.mem),
            "cpu": _runway(series["cpu_pct"], out["cpu"]["used_pct"], T.cpu),
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
                                      d.get("usage_pct"), T.ds)
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
        target = n1["remaining_mem_gb"] * (T.n1_warn / 100.0)
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
        hosts_needed = math.ceil(remaining / (host_gb * T.n1_warn / 100.0))
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
        try:
            db.rollback()       # başarısız sorgu işlemi "aborted" bırakmasın (sonraki okumalar etkilenmesin)
        except Exception:  # noqa: BLE001
            pass
        return {}


def build_capacity(db: Session, *, hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
                   platform: Optional[str] = None, with_forecast: bool = True) -> Dict[str, Any]:
    capacity_policy.activate(db)
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
            grouped[(hv.id, cap_hier.cluster_label(h.get("cluster_name"), h["host_name"]))].append(h)
    clusters = []
    for (hid, cname), hs in sorted(grouped.items(), key=lambda kv: (by_hv[kv[0][0]].name, kv[0][1])):
        if cluster and cname != cluster:
            continue
        hv = by_hv[hid]
        plat = vd.platform_of(hv) or "vmware"
        # H.0 #8: eşikler instance'ta varsayılan, cluster'da override (global < instance < cluster)
        th_eff = capacity_policy.activate_for(db, hid, cname)
        c_new = _analyze_cluster(db, hv, plat, cname, hs, vms, vcs.get((hid, cname)), p95,
                                 with_forecast=with_forecast)
        topo = cap_src.vmware_topology(db, hid, cname) if plat == "vmware" else {"datacenter": None, "pools": None}
        c_new["datacenter"] = topo["datacenter"]
        c_new["standalone"] = cap_hier.is_standalone(cname)
        c_new["path"] = cap_hier.path_str(hv.name, topo["datacenter"], cname)
        c_new["pools_read"] = (topo["pools"] is not None) if plat == "vmware" else None
        c_new["thresholds"] = dict(th_eff)
        # Dilim T: kartın veri zamanı = kümedeki host ölçümlerinin en yenisi (ek sorgu yok)
        ts = [h.get("timestamp") for h in hs if h.get("timestamp")]
        c_new["as_of"] = max(ts).isoformat() if ts else None
        clusters.append(c_new)
    capacity_policy.activate(db)      # küme döngüsünden sonra global eşiklere dön
    reclaim = _reclaim_by_cluster(db, hv_ids)
    for c in clusters:
        c["reclaim"] = reclaim.get((c["hypervisor_id"], c["cluster"]), {})
        c["actions"] = _actions(c, c["reclaim"], [o for o in clusters if o["hypervisor_id"] == c["hypervisor_id"]])
    ds = _datastores(db, [h.id for h in hvs if vd.platform_of(h) in ("vmware", "olvm")], with_forecast)
    for d in ds:
        d["hypervisor"] = by_hv[d["hypervisor_id"]].name if d["hypervisor_id"] in by_hv else None
    if with_forecast:
        for c in clusters:
            refs = {str(h.get("host_ref")) for h in grouped.get((c["hypervisor_id"], c["cluster"]), []) if h.get("host_ref")}
            c["datastore_runway"] = _cluster_ds_runway(db, c, ds, refs)
    as_of_all = [c["as_of"] for c in clusters if c.get("as_of")]
    return {
        "ok": True,
        "as_of": max(as_of_all) if as_of_all else None,
        "clusters": clusters,
        "datastores": ds,
        "thresholds": {"memory": T.mem, "cpu": T.cpu, "datastore": T.ds,
                       "n1_warn": T.n1_warn, "vcpu_ratio": T.vcpu_ratio, "ds_reserve": T.ds_reserve},
        "method": ("Memory birincil kısıt (N+1 kararı); CPU çekirdek-eşdeğeri, uyarı amaçlı. "
                   "Tükenme tahmini: 90 günlük günlük ortalama, Theil–Sen eğimi, aralık (hızlı/tipik/yavaş)."),
    }


def _place_legacy(c: Dict[str, Any], *, add_mem: float, add_cpu: float, add_vcpu: float, vcpu: int) -> Dict[str, Any]:
    """ESKİ yerleşim hesabı (CAPACITY_ENGINE=legacy) — eşdeğerlik testleri için korunur."""
    reasons: List[str] = []
    mem, cpu, n1 = c["memory"], c["cpu"], c["n_plus_one"]
    mem_used = (mem["used_gb"] or 0) + add_mem
    cpu_used = (cpu["used_cores"] or 0) + add_cpu
    eff_mem_pct = 100.0 * mem_used / mem["effective_gb"] if mem["effective_gb"] else None
    eff_cpu_pct = 100.0 * cpu_used / cpu["effective_cores"] if cpu["effective_cores"] else None
    n1_after = (100.0 * mem_used / n1["remaining_mem_gb"]) if n1.get("remaining_mem_gb") else None
    ratio_after = ((cpu["vcpu_allocated"] or 0) + add_vcpu) / cpu["total_cores"] if cpu["total_cores"] else None
    fits = True
    if eff_mem_pct is None or eff_mem_pct > T.mem:
        fits = False
        reasons.append(f"Effective Memory %{_r(eff_mem_pct)} > %{T.mem:.0f}")
    if n1_after is not None and n1_after > 100:
        fits = False
        reasons.append(f"N+1 bozulur (en büyük host düşünce Memory %{_r(n1_after)})")
    elif n1_after is not None and n1_after > T.n1_warn:
        reasons.append(f"N+1 sınırda (%{_r(n1_after)})")
    if eff_cpu_pct is not None and eff_cpu_pct > T.cpu:
        reasons.append(f"CPU effective %{_r(eff_cpu_pct)} — performans riski (uyarı)")
    if ratio_after and ratio_after > T.vcpu_ratio:
        reasons.append(f"vCPU:çekirdek {ratio_after:.1f}:1 (uyarı)")
    if c["hosts_usable"] == 0:
        fits = False
        reasons.append("Kullanılabilir host yok")
    if vcpu > (c.get("typical_host_cores") or 0) and c.get("typical_host_cores"):
        reasons.append(f"Tek VM vCPU ({vcpu}) host çekirdeğinden ({c['typical_host_cores']:.0f}) fazla")
    return {"fits": fits, "reasons": reasons, "eff_mem_pct": eff_mem_pct, "eff_cpu_pct": eff_cpu_pct,
            "n1_after": n1_after, "ratio_after": ratio_after}


def _cluster_models(db: Session, cap: Dict[str, Any]) -> Dict[Tuple[int, str], Any]:
    """Sonuç cluster'ları için ortak `ClusterModel`ler (host ref'li, hiyerarşi + resource pool'lu) — H.0.

    Ek vCenter/OLVM çağrısı yok: envanter/metrik tabloları ve config snapshot'ları okunur.
    """
    ids = sorted({c["hypervisor_id"] for c in cap["clusters"]})
    if not ids:
        return {}
    hvs = {h.id: h for h in vd.virt_hypervisors(db) if h.id in ids}
    hosts = vd.latest_hosts(db, ids)
    vms = vd.vm_allocations(db, ids)
    vcs = vd.virt_cluster_rows(db, ids)
    out: Dict[Tuple[int, str], Any] = {}
    for c in cap["clusters"]:
        hid, cname, plat = c["hypervisor_id"], c["cluster"], c["platform"]
        hv = hvs.get(hid)
        if hv is None:
            continue
        hs = [h for h in vd.worker_filter(db, hv, [h for h in hosts if h["hypervisor_id"] == hid])
              if cap_hier.cluster_label(h.get("cluster_name"), h["host_name"]) == cname]
        out[cap_hier.cluster_key(hid, cname)] = build_cluster_model(db, hv, plat, cname, hs, vms, vcs.get((hid, cname)))
    return out


def build_cluster_model(db: Session, hv: Any, plat: str, cname: str, hs: List[Dict[str, Any]],
                        vms: List[Dict[str, Any]], vc: Any) -> Any:
    """Tek cluster için ortak `ClusterModel` (What-if, toplu yerleşim, host-arızası ve yerleşim önerisi aynı modeli kullanır)."""
    hid = hv.id
    on = [v for v in _cluster_vms(vms, hid, cname, {h["host_name"] for h in hs}) if v["powered_on"]]
    topo = cap_src.vmware_topology(db, hid, cname) if plat == "vmware" else {"datacenter": None, "pools": None}
    cfg = _olvm_cluster_cfg(db, hid, cname) if plat == "olvm" else None
    fh = _failover_hosts(db, plat, hid, cname, vc)              # E3: ayrılmış failover host'lar
    return cap_adapters.from_virt_hosts(
        plat, cname, hs, vc, olvm_cfg=cfg, vms_on=on, instance_id=hid, instance_name=hv.name,
        datacenter=topo["datacenter"], pools=topo["pools"], failover_hosts=fh)


def _host_datastores(db: Session, cap: Dict[str, Any], c: Dict[str, Any]) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Host seviyesi yerleşim için datastore listesi. vCenter: host erişimi (`mounted_hosts`). OLVM: storage domain
    data center seviyesindedir; cluster↔data center eşlemesi okunmadığı için instance'ın domain'leri aday (not).
    OpenShift Virt: StorageClass/PV okunmuyor → None."""
    plat, hid = c["platform"], c["hypervisor_id"]
    if plat == "vmware":
        return cap_src.vmware_datastore_access(db, hid, c["cluster"], cap["datastores"]), None
    if plat == "olvm":
        rows = [{"name": d["name"], "free_gb": d.get("free_gb") or 0.0, "capacity_gb": d.get("capacity_gb") or 0.0,
                 "accessible": d.get("accessible"), "host_refs": None}
                for d in cap["datastores"] if d["hypervisor_id"] == hid]
        return (rows or None), ("OLVM storage domain'leri data center seviyesindedir; cluster'ın data center'ına bağlı "
                                "domain'ler okunmadı — instance'ın tüm domain'leri aday sayıldı")
    return None, None


def simulate(db: Session, *, vcpu: int, memory_gb: float, disk_gb: float = 0.0, count: int = 1,
             hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
             cpu_util_assumption: float = DEFAULT_CPU_ASSUMPTION,
             clusters: Optional[List[str]] = None, datacenter: Optional[str] = None,
             hosts: Optional[List[str]] = None, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
    """"Şu profilde N VM gelirse nereye sığar?" — her cluster BAĞIMSIZ hesaplanır (H.0: havuzlama yok).

    Kapsam: hypervisor_id (instance) → datacenter → cluster(lar) → (opsiyonel) host'lar. Boş kapsam = tüm ortamlar;
    sonuçlar cluster başına verilir ve sıralanır. Motor cluster dışına kendiliğinden yerleştirme önermez.
    """
    count = max(1, int(count or 1))
    vcpu = max(1, int(vcpu or 1))
    memory_gb = max(0.0, float(memory_gb or 0))
    disk_gb = max(0.0, float(disk_gb or 0))
    cpu_util_assumption = min(1.0, max(0.05, float(cpu_util_assumption or DEFAULT_CPU_ASSUMPTION)))
    cap = build_capacity(db, hypervisor_id=hypervisor_id, cluster=cluster, with_forecast=False)
    if clusters:
        sel = set(clusters)
        cap["clusters"] = [c for c in cap["clusters"] if c["cluster"] in sel]
    if datacenter:
        cap["clusters"] = [c for c in cap["clusters"] if c.get("datacenter") == datacenter]
    if platforms:
        pf = set(platforms)
        cap["clusters"] = [c for c in cap["clusters"] if c["platform"] in pf]
    models = _cluster_models(db, cap) if engine_mode() != "legacy" else {}
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
    ocp_ratio: Dict[int, Dict[str, Any]] = {}
    for c in cap["clusters"]:
        capacity_policy.activate(values=c.get("thresholds") or cap["thresholds"])   # cluster'ın etkin eşikleri
        if engine_mode() == "legacy":
            pl = _place_legacy(c, add_mem=add_mem, add_cpu=add_cpu, add_vcpu=add_vcpu, vcpu=vcpu)
        else:
            pl = cap_engine.place(c, add_mem=add_mem, add_cpu=add_cpu, add_vcpu=add_vcpu, vcpu_single=vcpu, thr=T,
                                  overcommit=(c["memory"] or {}).get("overcommit"))
        fits, reasons = pl["fits"], list(pl["reasons"])
        limiting: List[str] = list(pl.get("limiting") or ([] if fits else ["memory"]))
        warn_codes: List[str] = list(pl.get("warn_codes") or [])
        cluster_max = (cap_engine.max_additional(c, mem_each=memory_gb, thr=T,
                                                 overcommit=(c["memory"] or {}).get("overcommit"))
                       if engine_mode() != "legacy" else None)
        eff_mem_pct, eff_cpu_pct, n1_after, ratio_after = (
            pl["eff_mem_pct"], pl["eff_cpu_pct"], pl["n1_after"], pl["ratio_after"])
        mem, cpu, n1 = c["memory"], c["cpu"], c["n_plus_one"]
        ds_pick = None
        if add_disk:
            names = cluster_ds.get((c["hypervisor_id"], c["cluster"]))
            cands = [d for d in ds_by_hv.get(c["hypervisor_id"], []) if not names or d["name"] in names]
            best = None
            for d in cands:
                capg = d.get("capacity_gb") or 0
                free_after = (d.get("free_gb") or 0) - add_disk
                if capg and free_after >= capg * T.ds_reserve / 100.0:
                    if best is None or free_after > best[1]:
                        best = (d, free_after)
            if best:
                ds_pick = {"name": best[0]["name"], "free_after_gb": _r(best[1]),
                           "usage_after_pct": _r(100.0 - 100.0 * best[1] / best[0]["capacity_gb"])}
            else:
                fits = False
                if "datastore" not in limiting:
                    limiting.append("datastore")
                reasons.append(f"%{T.ds_reserve:.0f} rezerv korunarak {add_disk:.0f} GB alacak datastore yok")
        # H.0 #4/#5/#6: host seviyesinde yerleşim (HA rezervi + resource pool düşülmüş), parçalanma, datastore erişimi
        host_pl = None
        model = models.get(cap_hier.cluster_key(c["hypervisor_id"], c["cluster"]))
        if model is not None:
            dss, ds_note = _host_datastores(db, cap, c)
            host_pl = cap_place.place_on_hosts(
                model, vm_mem_gb=memory_gb, vm_vcpu=vcpu, count=count, disk_gb=disk_gb, datastores=dss,
                ds_reserve_pct=T.ds_reserve, mem_thr_pct=T.mem, only_hosts=hosts)
            for pm in host_pl["placed"]:     # H.0 #9: tam yol
                pm["path"] = cap_hier.path_str(c["hypervisor"], c.get("datacenter"), c["cluster"], pm["host"])
            if ds_note and disk_gb > 0:
                host_pl["notes"] = list(host_pl["notes"]) + [ds_note]
            if not host_pl["fits"]:
                fits = False
                for code in host_pl.get("limiting") or []:
                    if code not in limiting:
                        limiting.append(code)
                reasons.append(f"{host_pl['verdict']}: {host_pl['unplaced']}/{count} VM host'a yerleşemedi")
            if host_pl["warnings"] and "cores" not in warn_codes:
                warn_codes.append("cores")
            reasons.extend(w for w in host_pl["warnings"] if w not in reasons)
        score = None
        if eff_mem_pct is not None:
            score = round(100 - eff_mem_pct * 0.6 - (eff_cpu_pct or 0) * 0.3 - (n1_after or 0) * 0.1, 1)
        hp_max = host_pl.get("max_fit") if host_pl else None
        caps = [x for x in (cluster_max, hp_max) if x is not None]
        max_fit = min(caps) if caps else None
        if not fits and max_fit is not None:
            max_fit = min(max_fit, count - 1)      # sığmayan talepte "en fazla" istenen adetten küçüktür
        status = "fail" if not fits else ("warn" if (warn_codes or (host_pl and host_pl["confidence"] != "high")) else "ok")
        cpu_req = None
        if c["platform"] == "ocp_virt":      # E6: HCO vmiCPUAllocationRatio (okundu / varsayılan etiketi)
            rt = ocp_ratio.get(c["hypervisor_id"])
            if rt is None:
                rt = ocp_ratio[c["hypervisor_id"]] = cap_src.ocp_virt_cpu_ratio(db, c["hypervisor_id"])
            each = cap_engine.vm_cpu_request_cores(vcpu, rt["ratio"])
            cpu_req = {"ratio": rt["ratio"], "source": rt["source"], "label": rt["label"],
                       "each_cores": _r(each, 3), "total_cores": _r(each * count, 3)}
        results.append({
            "platform": c["platform"], "hypervisor_id": c["hypervisor_id"], "hypervisor": c["hypervisor"],
            "cluster": c["cluster"], "standalone": bool(c.get("standalone")),
            "fits": fits, "status": status, "limiting": limiting, "warn_codes": warn_codes,
            "max_fit": max_fit, "reasons": reasons, "score": score,
            "datacenter": c.get("datacenter"), "path": c.get("path"),
            "verdict": (host_pl["verdict"] if (host_pl and not host_pl["fits"]) else ("Sığar" if fits else "Sığmaz — kapasite/N+1")),
            "confidence": host_pl["confidence"] if host_pl else None,
            "placement": host_pl,
            **({"cpu_request": cpu_req} if cpu_req else {}),
            "after": {
                "memory_effective_pct": _r(eff_mem_pct), "cpu_effective_pct": _r(eff_cpu_pct),
                "n1_memory_pct": _r(n1_after), "vcpu_ratio": _r(ratio_after, 2),
                **({"memory_committed_pct": pl["committed_after_pct"]} if pl.get("committed_after_pct") is not None else {}),
            },
            "before": {
                "memory_effective_pct": mem["effective_used_pct"], "cpu_effective_pct": cpu["effective_used_pct"],
                "n1_memory_pct": n1.get("mem_after_pct"), "vcpu_ratio": cpu["vcpu_ratio"],
            },
            "datastore": ds_pick,
        })
    results.sort(key=lambda r: (not r["fits"], -(r["score"] or -999)))
    capacity_policy.activate(db)
    assumptions = [
        "Yeni VM'in Memory'si tamamen kullanılıyor kabul edilir (en kötü durum).",
        f"CPU kullanımı vCPU başına %{cpu_util_assumption * 100:.0f} varsayılır.",
        f"Datastore'da %{T.ds_reserve:.0f} boş alan rezervi korunur.",
        "HA rezervi cluster politikasından; okunamıyorsa 1 host varsayılır.",
        "Kullanım değerleri anlıktır (host'ların son ölçümü); tepe/p95 değildir.",
        # E4: değerlendirilmeyen kısıtlar açıkça belirtilir (sonuç 'sığar' deyip bunları garanti etmez)
        "Affinity/DRS kuralları, VM rezervasyonları (CPU/Memory reservation) ve VLAN/portgroup erişimi kontrol edilmez.",
    ]
    if any(r.get("platform") == "ocp_virt" for r in results):
        assumptions.append(ocp_overhead_assumption(memory_gb, vcpu))
        assumptions.extend(ocp_cpu_ratio_assumptions(results))
    if hosts:
        assumptions.append("Host kapsamı yalnız aday host'ları daraltır; HA rezervi ve N+1 tüm cluster üzerinden hesaplanır.")
    if any(r.get("standalone") for r in results):
        assumptions.append("'(cluster yok)' satırları bağımsız host'tur: ortak HA/vMotion havuzu varsayılmaz, her host ayrı hesaplanır.")
    return {
        "ok": True,
        "request": {"vcpu": vcpu, "memory_gb": memory_gb, "disk_gb": disk_gb, "count": count,
                    "cpu_util_assumption": cpu_util_assumption},
        "assumptions": assumptions,
        "results": results,
        "best": next((r for r in results if r["fits"]), None),
    }


def ocp_cpu_ratio_assumptions(results: List[Dict[str, Any]]) -> List[str]:
    """E6: OpenShift Virtualization CPU request = vCPU ÷ vmiCPUAllocationRatio; kaynak etiketli (okundu / varsayılan).
    Düğümlerdeki mevcut CPU request toplamı bu envanterde toplanmadığı için CPU kararı request tabanlı DEĞİL, kullanım
    varsayımlıdır — satır bunu açıkça söyler."""
    seen: Dict[str, Dict[str, Any]] = {}
    for r in results:
        cr = r.get("cpu_request")
        if cr:
            seen.setdefault(f"{cr['ratio']:g}|{cr['source']}", {**cr, "clusters": []})["clusters"].append(r["cluster"])
    out = []
    for cr in seen.values():
        out.append(f"OpenShift Virtualization CPU request: {cr['label']}; VM başına ≈ {cr['each_cores']:g} çekirdek request "
                   f"({', '.join(cr['clusters'])}). Düğümlerdeki mevcut CPU request toplamı toplanmadığından CPU kararı "
                   f"request tabanlı değil, kullanım varsayımlıdır.")
    return out


def ocp_overhead_assumption(memory_gb: float, vcpu: int) -> str:
    """E5: OpenShift Virtualization virt-launcher ek belleği — ölçülmeyen, Red Hat dokümanından gelen varsayım.
    Etiketlidir ve what-if hesabına KATILMADIĞI açıkça yazılır (bilgi amaçlı büyüklük gösterilir)."""
    from app.services.capacity.engine import vm_memory_overhead_mib
    over_gb = vm_memory_overhead_mib(float(memory_gb) * 1024.0, int(vcpu)) / 1024.0
    return (f"OpenShift Virtualization (doküman varsayımı, ölçülmedi): virt-launcher ek belleği bu hesaba katılmaz; Red Hat "
            f"dokümanına göre bu profil için VM başına ≈ {over_gb:.2f} GB (0,002×bellek + 218 MiB + 8 MiB×vCPU) ek bellek gerekir.")


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


def _vmware_mounts(db: Session, c: Dict[str, Any], hypervisor_id: int) -> Dict[str, Any]:
    if c["platform"] != "vmware":
        return {}
    from app.services.virt_placement import _ds_mounts
    try:
        return _ds_mounts(db, hypervisor_id)
    except Exception:  # noqa: BLE001
        return {}


def host_failure(db: Session, *, hypervisor_id: int, cluster: str, hosts: List[str]) -> Dict[str, Any]:
    """"X host'u (veya birkaçı) devre dışı kalırsa çalışan VM'ler kalan host'lara sığar mı?" — deterministik.

    Memory: düşen host'lardaki AÇIK VM'ler büyükten küçüğe, kalan kullanılabilir host'ların boş Memory'sine
    (en boş host; VM'in datastore'u biliniyorsa o host'a bağlı olmalı) yerleştirilir. İKİ sonuç yan yana verilir:
    tanımlı Memory (en kötü durum, karar bunun üzerindendir) ve p95 Memory (VMware: guest aktif Memory; iyimser).
    HA rezervi BU senaryoda düşülmez: rezerv tam olarak bu arızayı karşılamak içindir.
    CPU: kalan host'ların fiziksel çekirdekleri üzerinde vCPU oranı (uyarı) ve p95 CPU talebi (Sınırda / Sığmaz).
      • "Sığar" · "Sınırda" (eşik üstü ama fiziksel sınırın altı) · "Sığmaz"
    Affinity/DRS kuralları, VM rezervasyonları ve HA yeniden başlatma önceliği değerlendirilmez (not).
    Geriye dönük uyumlu: üst düzey `verdict/status/placed/unplaced/after/displaced` tanımlı Memory sonucudur;
    `overall`, `memory`, `cpu`, `p95` yeni alanlardır.
    """
    capacity_policy.activate(db)
    hosts = [h for h in dict.fromkeys(hosts or []) if h]
    if not hosts:
        return {"ok": False, "error": "En az bir host seçin"}
    ctx = _hf_context(db, hypervisor_id, cluster)
    if "error" in ctx:
        return {"ok": False, "error": ctx["error"]}
    return _hf_eval(db, ctx, hypervisor_id, cluster, hosts)


def _hf_context(db: Session, hypervisor_id: int, cluster: str) -> Dict[str, Any]:
    """Cluster için kapasite + model (host-failure hesabının ortak girdisi; matris tek sefer kurar)."""
    cap = build_capacity(db, hypervisor_id=hypervisor_id, cluster=cluster, with_forecast=False)
    c = next((x for x in cap["clusters"] if x["hypervisor_id"] == hypervisor_id and x["cluster"] == cluster), None)
    if c is None:
        return {"error": "Cluster bulunamadı"}
    model = _cluster_models(db, cap).get(cap_hier.cluster_key(hypervisor_id, cluster))
    if model is None:
        return {"error": "Cluster modeli oluşturulamadı"}
    return {"cap": cap, "c": c, "model": model}


def _hf_eval(db: Session, ctx: Dict[str, Any], hypervisor_id: int, cluster: str, hosts: List[str]) -> Dict[str, Any]:
    cap, c, model = ctx["cap"], ctx["c"], ctx["model"]
    names = {n.name for n in model.nodes}
    unknown = [h for h in hosts if h not in names]
    if unknown:
        return {"ok": False, "error": f"Bilinmeyen host: {', '.join(unknown)}"}
    capacity_policy.activate(values=c.get("thresholds") or cap["thresholds"])
    thr, cpu_thr, ratio_limit = T.mem, T.cpu, T.vcpu_ratio
    down = set(hosts)
    vms = _cluster_vms(vd.vm_allocations(db, [hypervisor_id]), hypervisor_id, cluster, names)
    on = [v for v in vms if v["powered_on"]]
    displaced = [v for v in on if v.get("host") in down]
    remaining = [n for n in model.nodes if n.usable and n.name not in down]
    mounts = _vmware_mounts(db, c, hypervisor_id)
    usage = cap_fail.p95_index(db, [hypervisor_id])
    needs = {id(v): cap_fail.vm_need(v, usage.get((hypervisor_id, v["name"]))) for v in on}
    mem_def = cap_fail.failover_place(displaced, remaining, thr, mounts, lambda v: needs[id(v)]["mem_defined"])
    mem_p95 = cap_fail.failover_place(displaced, remaining, thr, mounts, lambda v: needs[id(v)]["mem_p95"])
    cov = cap_fail.coverage([needs[id(v)] for v in on])
    cpu = None
    if displaced:
        cpu = cap_fail.cpu_check(
            remaining_cores=sum(float(n.cpu_cores or 0) for n in remaining),
            vcpu_total=sum(needs[id(v)]["vcpu"] for v in on),
            demand_cores=sum(needs[id(v)]["cpu_p95_cores"] for v in on),
            thr_pct=cpu_thr, ratio_limit=ratio_limit, cov=cov)
    overall = cap_fail.combine(mem_def, cpu) if displaced else {"verdict": "no_vm", "status": "ok", "limiting": [], "warnings": []}
    notes = ["Tanımlı Memory VM'in tahsis ettiği değerdir (en kötü durum); karar bu sütuna göredir.",
             "p95 Memory: VMware'de guest AKTİF Memory'dir (host'ta tüketilen değil) — iyimser alt sınırdır; "
             "p95 verisi olmayan VM tanımlı değerle hesaplanır.",
             "CPU p95 talebi VM p95'lerinin toplamıdır (muhafazakâr); CPU yüzdesi vCPU başına 2 GHz varsayımına dayanır.",
             "Affinity/DRS kuralları, VM rezervasyonları ve HA yeniden başlatma önceliği değerlendirilmez.",
             "HA rezervi bu senaryoda düşülmez: rezerv bu arızayı karşılamak içindir."]
    if not remaining:
        notes.append("Kalan kullanılabilir host yok: failover mümkün değil.")
    if c["platform"] == "ocp_virt":
        notes.append("OpenShift Virtualization: son yerleşim kararını kube-scheduler verir; sonuç bilgi amaçlıdır.")
    if c["platform"] == "vmware" and not mounts:
        notes.append("Datastore ↔ host erişimi okunamadı: datastore kontrolü yapılmadı.")
    out = {
        "ok": True, "path": c.get("path"), "platform": c["platform"], "hypervisor_id": hypervisor_id,
        "cluster": cluster, "down": sorted(down), "remaining_hosts": sorted(n.name for n in remaining),
        "vms_total_on_down": len(displaced),
        "displaced": {"count": len(displaced), "memory_gb": mem_def["displaced_gb"]},
        "placed": mem_def["placed"], "unplaced": mem_def["unplaced"],
        "verdict": mem_def["verdict"], "status": mem_def["status"],
        "after": {"memory_pct": mem_def["after_memory_pct"]},
        "threshold_pct": thr, "ha": c.get("ha"), "notes": notes,
        "confidence": "medium" if (c.get("ha") or {}).get("assumed") else "high",
        "overall": overall,
        "memory": {"defined": mem_def, "p95": {**mem_p95, "coverage": cov}},
        "cpu": cpu,
        "p95": {"window_days": cap_fail.p95_window_days(), "coverage": cov,
                "memory_basis": "guest_active" if c["platform"] == "vmware" else "reported"},
    }
    capacity_policy.activate(db)
    return out


def host_failure_matrix(db: Session, *, hypervisor_id: int, cluster: str) -> Dict[str, Any]:
    """Cluster'daki HER host için tek-host düşme (N+1) sonucu — salt okunur. Her satır `host_failure` ile aynı hesaptır
    (kapasite/model cluster için tek sefer kurulur). Kalan host yoksa satır `no_remaining_host` işaretlenir."""
    capacity_policy.activate(db)
    ctx = _hf_context(db, hypervisor_id, cluster)
    if "error" in ctx:
        return {"ok": False, "error": ctx["error"]}
    model = ctx["model"]
    rows: List[Dict[str, Any]] = []
    for node in sorted(model.nodes, key=lambda n: n.name):
        r = _hf_eval(db, ctx, hypervisor_id, cluster, [node.name])
        if not r.get("ok"):
            rows.append({"host": node.name, "ok": False, "error": r.get("error")})
            continue
        mem_def, mem_p95 = r["memory"]["defined"], r["memory"]["p95"]
        cpu = r.get("cpu")
        rows.append({
            "host": node.name, "ok": True, "usable": bool(node.usable),
            "vms": r["displaced"]["count"], "memory_gb": r["displaced"]["memory_gb"],
            "remaining_hosts": len(r["remaining_hosts"]), "no_remaining_host": not r["remaining_hosts"],
            "defined": {"verdict": mem_def["verdict"], "after_memory_pct": mem_def.get("after_memory_pct"),
                        "unplaced": len(mem_def["unplaced"])},
            "p95": {"verdict": mem_p95["verdict"], "after_memory_pct": mem_p95.get("after_memory_pct"),
                    "unplaced": len(mem_p95["unplaced"])},
            "cpu": ({"verdict": cpu["verdict"], "p95_pct": cpu.get("p95_pct"), "vcpu_ratio": cpu.get("vcpu_ratio"),
                     "ratio_warn": cpu.get("ratio_warn")} if cpu else None),
            "overall": r["overall"],
        })
    # F3: riske göre sırala (Sığmaz → Sınırda → Sığar → VM yok; hesaplanamayanlar sonda), eşitlikte host adı.
    _rank = {"fail": 0, "tight": 1, "fit": 2, "no_vm": 3}
    rows.sort(key=lambda r: (_rank.get((r.get("overall") or {}).get("verdict"), 9) if r.get("ok") else 9, r["host"]))
    capacity_policy.activate(db)
    c = ctx["c"]
    return {"ok": True, "hypervisor_id": hypervisor_id, "cluster": cluster, "platform": c["platform"],
            "path": c.get("path"), "hosts_total": len(rows), "single_host": len(rows) == 1,
            "threshold_pct": (c.get("thresholds") or ctx["cap"].get("thresholds") or {}).get("memory"), "rows": rows}


def capacity_findings(cap: Dict[str, Any]) -> Dict[Tuple[str, int], List[Any]]:
    """Kapasite sonucu → (platform, hypervisor_id) başına bulgu taslakları."""
    th = cap.get("thresholds") or {}
    capacity_policy.activate(values={"memory": th.get("memory"), "cpu": th.get("cpu"), "datastore": th.get("datastore"),
                                     "n1_warn": th.get("n1_warn"), "vcpu_ratio": th.get("vcpu_ratio"),
                                     "ds_reserve": th.get("ds_reserve")})
    from app.services.findings.store import FindingDraft
    out: Dict[Tuple[str, int], List[FindingDraft]] = defaultdict(list)
    for c in cap["clusters"]:
        if c.get("thresholds"):       # H.0: cluster'a özgü etkin eşikler
            capacity_policy.activate(values=c["thresholds"])
        key = (c["platform"], c["hypervisor_id"])
        ref = f"cluster:{c['cluster']}"
        n1 = c["n_plus_one"]
        from app.services.findings.registry import (
            RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS,
        )
        st = n1.get("status")
        if n1.get("evaluable"):
            out[key].append(FindingDraft(
                "cap.cluster.n_plus_one", "cluster", ref, c["cluster"],
                RESULT_FAIL if st in ("fail", "warn") else RESULT_PASS,
                evidence={k: n1.get(k) for k in ("largest_host", "largest_host_mem_gb", "remaining_mem_gb",
                                                 "mem_after_pct", "cpu_after_pct")},
                detail=(f"En büyük host ({n1.get('largest_host')}) düşünce Memory %{n1.get('mem_after_pct')}"
                        + (" — sığmıyor" if st == "fail" else " — sınırda" if st == "warn" else "")),
                cluster_name=c["cluster"], severity="critical" if st == "fail" else ("high" if st == "warn" else None),
            ))
        elif st == "single_host":
            out[key].append(FindingDraft(
                "cap.cluster.n_plus_one", "cluster", ref, c["cluster"],
                RESULT_NOT_APPLICABLE,
                evidence={"status": st, "hosts_usable": c.get("hosts_usable")},
                detail="Tek host — N+1 (failover) uygulanamaz",
                cluster_name=c["cluster"],
            ))
        fm = (c.get("forecast") or {}).get("memory") or {}
        days = (fm.get("days") or {}).get("typical") if fm.get("days") else None
        if fm:
            out[key].append(FindingDraft(
                "cap.cluster.mem_runway", "cluster", ref, c["cluster"],
                RESULT_FAIL if days is not None and days < RUNWAY_DAYS_ALERT else
                (RESULT_PASS if fm.get("confidence") not in ("none",) else RESULT_NOT_MEASURABLE),
                evidence={"used_pct": c["memory"]["used_pct"], **fm},
                detail=(f"Memory %{T.mem:.0f} eşiği aşılmış (%{c['memory']['used_pct']})" if days == 0
                        else f"Memory %{T.mem:.0f} eşiğine ~{days} gün" if days is not None
                        else "Eşiğe ulaşma öngörülmüyor / veri yetersiz"),
                cluster_name=c["cluster"], severity="critical" if days == 0 else None,
            ))
        fc = (c.get("forecast") or {}).get("cpu") or {}
        cdays = (fc.get("days") or {}).get("typical") if fc.get("days") else None
        if fc:
            out[key].append(FindingDraft(
                "cap.cluster.cpu_runway", "cluster", ref, c["cluster"],
                RESULT_FAIL if cdays is not None and cdays < RUNWAY_DAYS_ALERT else
                (RESULT_PASS if fc.get("confidence") != "none" else RESULT_NOT_MEASURABLE),
                evidence={"used_pct": c["cpu"]["used_pct"], **fc},
                detail=(f"CPU %{T.cpu:.0f} eşiği aşılmış (%{c['cpu']['used_pct']})" if cdays == 0
                        else f"CPU %{T.cpu:.0f} eşiğine ~{cdays} gün" if cdays is not None
                        else "Eşiğe ulaşma öngörülmüyor / veri yetersiz"),
                cluster_name=c["cluster"],
            ))
        ratio = c["cpu"].get("vcpu_ratio")
        if ratio is not None:
            out[key].append(FindingDraft(
                "cap.cluster.vcpu_ratio", "cluster", ref, c["cluster"],
                RESULT_FAIL if ratio > T.vcpu_ratio else RESULT_PASS,
                evidence={"vcpu": c["cpu"]["vcpu_allocated"], "cores": c["cpu"]["total_cores"], "ratio": ratio},
                detail=f"vCPU:çekirdek = {ratio}:1", cluster_name=c["cluster"],
            ))
    capacity_policy.activate(values={"memory": th.get("memory"), "cpu": th.get("cpu"), "datastore": th.get("datastore"),
                                     "n1_warn": th.get("n1_warn"), "vcpu_ratio": th.get("vcpu_ratio"),
                                     "ds_reserve": th.get("ds_reserve")})
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
                "cap.datastore.usage", "datastore", ref, d["name"], RESULT_FAIL if u >= T.ds else RESULT_PASS,
                evidence={"usage_pct": u, "free_gb": d.get("free_gb"), "capacity_gb": d.get("capacity_gb")},
                detail=f"Doluluk %{u}", severity="critical" if u >= 95 else None,
            ))
        f = d.get("forecast") or {}
        dd = (f.get("days") or {}).get("typical") if f.get("days") else None
        if f and u is not None and u < T.ds:
            out[key].append(FindingDraft(
                "cap.datastore.runway", "datastore", ref, d["name"],
                RESULT_FAIL if dd is not None and dd < DS_RUNWAY_DAYS_ALERT else
                (RESULT_PASS if f.get("confidence") != "none" else RESULT_NOT_MEASURABLE),
                evidence=f, detail=(f"%{T.ds:.0f} eşiğine ~{dd} gün" if dd is not None else "Trend yok"),
            ))
    return out


def move_scenario(db: Session, *, vcpu: int, memory_gb: float, disk_gb: float = 0.0, count: int = 1,
                  from_hypervisor_id: int, from_cluster: str, to_hypervisor_id: int, to_cluster: str,
                  cpu_util_assumption: float = DEFAULT_CPU_ASSUMPTION) -> Dict[str, Any]:
    """H.0 #10: "A cluster'ından B'ye taşı" — YALNIZ açık istekle. Motor kendiliğinden cluster dışına yerleştirmez.

    Hedef: B'ye ekleme (host seviyesinde yerleşim dahil, `simulate` ile aynı kurallar). Kaynak: A'dan çıkan
    belleğin A'nın doluluğuna etkisi (bilgi). İki cluster ayrı hesaplanır; boş kapasite toplanmaz.
    """
    if (from_hypervisor_id, from_cluster) == (to_hypervisor_id, to_cluster):
        return {"ok": False, "error": "Kaynak ve hedef cluster aynı"}
    cap = build_capacity(db, with_forecast=False)
    src = next((c for c in cap["clusters"] if c["hypervisor_id"] == from_hypervisor_id and c["cluster"] == from_cluster), None)
    if src is None:
        return {"ok": False, "error": "Kaynak cluster bulunamadı"}
    tgt = simulate(db, vcpu=vcpu, memory_gb=memory_gb, disk_gb=disk_gb, count=count, hypervisor_id=to_hypervisor_id,
                   clusters=[to_cluster], cpu_util_assumption=cpu_util_assumption)
    if not tgt["results"]:
        return {"ok": False, "error": "Hedef cluster bulunamadı"}
    mem = src["memory"]
    freed = memory_gb * count
    after_used = max((mem["used_gb"] or 0) - freed, 0.0)
    return {
        "ok": True,
        "source": {"path": src.get("path"), "freed_memory_gb": _r(freed),
                   "effective_used_pct_before": mem.get("effective_used_pct"),
                   "effective_used_pct_after": _r(100.0 * after_used / mem["effective_gb"]) if mem.get("effective_gb") else None},
        "target": tgt["results"][0],
        "assumptions": tgt["assumptions"] + ["Taşıma yalnız bu açık senaryoda hesaplanır; motor cluster dışına kendiliğinden yerleştirme önermez"],
    }
