"""Host seviyesinde yerleşim (H.0) — saf fonksiyonlar, deterministik.

Kurallar (Kapasite planlama, VM yerleşim önerisi ve What-if için aynı):
  • Her VM, HA rezervi (ve resource pool rezervasyonları) düşüldükten sonra TEK bir host'un boş kapasitesine sığmalı.
  • Cluster toplamı yetse de hiçbir host'a sığmıyorsa sonuç "Sığmaz — parçalanma".
  • VM diski, host'un ERİŞEBİLDİĞİ bir datastore / storage domain üzerinde olmalı; erişimi olmayan host'a yerleştirilmez.
  • vCPU > host fiziksel çekirdeği → uyarı. NUMA düğümü boyutu toplanmıyor → NUMA kontrolü yapılamadı (not_measurable).
  • Resource pool rezervasyonu okunamadıysa: sonuç düşük güven + "rezervasyonlar hesaba katılmadı" notu.
  • Motor cluster dışına kendiliğinden yerleştirme önermez; çağıran her cluster'ı bağımsız hesaplar.

HA rezervi host'lara ORANTILI dağıtılır (varsayım, çıktıda yazar): host_i kullanılabilir = mem_i × (efektif / toplam).
Kaynak (vSphere resource pool): vSphere Web Services SDK — `ResourcePool.config` (ResourceConfigSpec:
`cpuAllocation` / `memoryAllocation` → `reservation`, `limit`, `expandableReservation`); doğrulama 2026-10-13.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.services.capacity.engine import reserve_for, usable_nodes
from app.services.capacity.model import ClusterModel, ResourcePoolSpec

NOTE_POOLS_UNREAD = "Resource pool rezervasyonları okunamadı — rezervasyonlar hesaba katılmadı (düşük güven)"
NOTE_POOL_USAGE_UNKNOWN = "Havuz bellek kullanımı bilinmiyor — rezervasyonun tamamı boş kapasiteden düşüldü (temkinli)"
NOTE_NUMA = "NUMA düğümü boyutu toplanmıyor — vCPU'nun NUMA düğümüne sığması kontrol edilemedi (not_measurable)"
NOTE_DS_UNKNOWN = "Datastore / storage domain / storage class erişimi okunamadı — disk erişimi kontrol edilmedi"
NOTE_RESERVE_SPREAD = "HA rezervi host'lara orantılı dağıtılır (varsayım)"

V_FITS = "Sığar"
V_FRAG = "Sığmaz — parçalanma"
V_DS = "Sığmaz — datastore erişimi yok"
V_CAP = "Sığmaz — kapasite"
V_NONE = "Sığmaz — kullanılabilir host yok"


def pool_deduction(pools: Optional[Sequence[ResourcePoolSpec]]) -> Dict[str, Any]:
    """Rezerve edilmiş ama kullanılmamış havuz belleği (GB) — havuz dışındaki VM'ler için boş sayılmaz."""
    if pools is None:
        return {"read": False, "deduct_gb": 0.0, "pools": [], "notes": [NOTE_POOLS_UNREAD]}
    total = 0.0
    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    unknown_usage = False
    for p in pools:
        res = p.mem_reservation_gb
        if res is None or res <= 0:
            rows.append({"name": p.name, "mem_reservation_gb": res, "deducted_gb": 0.0})
            continue
        if p.used_mem_gb is None:
            unknown_usage = True
            d = float(res)
        else:
            d = max(0.0, float(res) - float(p.used_mem_gb))
        total += d
        rows.append({"name": p.name, "mem_reservation_gb": round(float(res), 2), "deducted_gb": round(d, 2),
                     "cpu_reservation_mhz": p.cpu_reservation_mhz})
    if unknown_usage:
        notes.append(NOTE_POOL_USAGE_UNKNOWN)
    return {"read": True, "deduct_gb": total, "pools": rows, "notes": notes}


def host_budgets(model: ClusterModel, mem_thr_pct: float) -> Dict[str, Any]:
    """Her kullanılabilir host için, HA rezervi + havuz rezervasyonu + eşik uygulanmış boş bellek (GB)."""
    usable = usable_nodes(model)
    mem_total = sum(n.mem_gb for n in usable)
    reserve = reserve_for(model)
    pools = pool_deduction(model.pools) if model.platform == "vmware" else {
        "read": None, "deduct_gb": 0.0, "pools": [], "notes": []}
    eff = max(mem_total - reserve["mem_gb"] - pools["deduct_gb"], 0.0)
    scale = (eff / mem_total) if mem_total > 0 else 0.0
    hosts = []
    for n in usable:
        share = n.mem_gb * scale
        cap = share * mem_thr_pct / 100.0
        hosts.append({"name": n.name, "ref": n.ref, "cores": float(n.cpu_cores or 0), "mem_gb": n.mem_gb,
                      "used_gb": n.mem_used_gb, "budget_gb": round(cap, 3),
                      "free_gb": max(cap - n.mem_used_gb, 0.0)})
    return {"hosts": hosts, "mem_total": mem_total, "reserve": reserve, "pools": pools, "effective_gb": eff}


def _ds_ok(ds: Dict[str, Any], host_ref: str, disk_gb: float, reserve_pct: float) -> bool:
    if ds.get("accessible") is False:
        return False
    refs = ds.get("host_refs")
    if refs is not None and host_ref not in refs:
        return False
    cap = float(ds.get("capacity_gb") or 0)
    free_after = float(ds.get("free_gb") or 0) - disk_gb
    return bool(cap) and free_after >= cap * reserve_pct / 100.0


def place_on_hosts(model: ClusterModel, *, vm_mem_gb: float, vm_vcpu: int, count: int = 1, disk_gb: float = 0.0,
                   datastores: Optional[List[Dict[str, Any]]] = None, ds_reserve_pct: float = 15.0,
                   mem_thr_pct: float = 85.0, only_hosts: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """`count` özdeş VM'i bu cluster'ın host'larına tek tek yerleştirir (en boş host; eşitlikte ada göre).

    `datastores`: None → erişim bilinmiyor (kontrol edilmez, not_measurable notu). Liste → her öğe
    {name, free_gb, capacity_gb, accessible, host_refs: set|None}; `host_refs` None ise datastore cluster
    düzeyinde erişilebilir kabul edilir (ör. OLVM storage domain data center seviyesindedir).
    """
    count = max(1, int(count or 1))
    b = host_budgets(model, mem_thr_pct)      # HA rezervi/havuz düşümü TÜM cluster üzerinden hesaplanır
    hosts = b["hosts"]
    if only_hosts:                            # kapsam seçici: adaylar seçili host'larla sınırlanır (opsiyonel)
        sel = set(only_hosts)
        hosts = [h for h in hosts if h["name"] in sel]
    free = {h["name"]: h["free_gb"] for h in hosts}
    ds_state = [dict(d) for d in datastores] if datastores is not None else None
    notes: List[str] = list(b["pools"]["notes"])
    warnings: List[str] = []
    if model.platform in ("vmware", "olvm", "ocp_virt"):
        notes.append(NOTE_NUMA)
    if b["reserve"]["mem_gb"] > 0:
        notes.append(NOTE_RESERVE_SPREAD)
    if disk_gb > 0 and ds_state is None:
        notes.append(NOTE_DS_UNKNOWN)

    placed: List[Dict[str, Any]] = []
    reason: Optional[str] = None
    if not hosts:
        return {"fits": False, "verdict": V_NONE, "reason": "no_host", "placed": [], "unplaced": count,
                "warnings": warnings, "notes": notes, "confidence": "low", "cluster_free_gb": 0.0,
                "host_free": [], "pools": b["pools"]["pools"]}
    max_cores = max(h["cores"] for h in hosts)
    if vm_vcpu > max_cores > 0:
        warnings.append(f"VM vCPU ({vm_vcpu}) cluster'daki en büyük host'un fiziksel çekirdeğini ({max_cores:.0f}) aşıyor")
    for i in range(count):
        cands = [h for h in hosts if free[h["name"]] >= vm_mem_gb]
        ds_pick = None
        if disk_gb > 0 and ds_state is not None:
            with_ds = []
            for h in cands:
                opts = [d for d in ds_state if _ds_ok(d, h["ref"], disk_gb, ds_reserve_pct)]
                if opts:
                    with_ds.append((h, opts))
            if not with_ds:
                reason = "datastore_access" if cands else None
                cands = []
            else:
                cands = [h for h, _ in with_ds]
        if not cands:
            if reason is None:
                total_free = sum(free.values())
                reason = "fragmentation" if total_free >= vm_mem_gb else "capacity"
            break
        cands.sort(key=lambda h: (-free[h["name"]], h["name"]))
        pick = cands[0]
        free[pick["name"]] -= vm_mem_gb
        if disk_gb > 0 and ds_state is not None:
            opts = [d for d in ds_state if _ds_ok(d, pick["ref"], disk_gb, ds_reserve_pct)]
            opts.sort(key=lambda d: (-(float(d.get("free_gb") or 0)), d["name"]))
            best = opts[0]
            best["free_gb"] = float(best.get("free_gb") or 0) - disk_gb
            ds_pick = best["name"]
        placed.append({"vm": i + 1, "host": pick["name"], "datastore": ds_pick})
        if vm_vcpu > pick["cores"] > 0:
            warnings.append(f"VM vCPU ({vm_vcpu}) host {pick['name']} fiziksel çekirdeğini ({pick['cores']:.0f}) aşıyor")
    unplaced = count - len(placed)
    fits = unplaced == 0
    verdict = V_FITS if fits else {"fragmentation": V_FRAG, "datastore_access": V_DS}.get(reason or "", V_CAP)
    low = (b["pools"]["read"] is False)
    medium = bool(b["reserve"].get("assumed"))
    confidence = "low" if low else ("medium" if medium else "high")
    return {
        "fits": fits, "verdict": verdict, "reason": None if fits else reason, "placed": placed, "unplaced": unplaced,
        "warnings": sorted(set(warnings)), "notes": notes, "confidence": confidence,
        "cluster_free_gb": round(sum(h["free_gb"] for h in hosts), 2),
        "host_free": [{"host": h["name"], "free_gb": round(h["free_gb"], 2)} for h in hosts],
        "pools": b["pools"]["pools"],
    }
