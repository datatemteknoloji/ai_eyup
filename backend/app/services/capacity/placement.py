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

from app.services.capacity import rules_vmware
from app.services.capacity.engine import reserve_for, usable_nodes
from app.services.capacity.model import ClusterModel, ResourcePoolSpec

NOTE_POOLS_UNREAD = "Resource pool rezervasyonları okunamadı — rezervasyonlar hesaba katılmadı (düşük güven)"
NOTE_POOL_USAGE_UNKNOWN = "Havuz bellek kullanımı bilinmiyor — rezervasyonun tamamı boş kapasiteden düşüldü (temkinli)"
NOTE_NUMA = "NUMA düğümü boyutu toplanmıyor — vCPU'nun NUMA düğümüne sığması kontrol edilemedi (not_measurable)"
NOTE_DS_UNKNOWN = "Datastore / storage domain / storage class erişimi okunamadı — disk erişimi kontrol edilmedi"
NOTE_RESERVE_SPREAD = "HA rezervi host'lara orantılı dağıtılır (varsayım)"
NOTE_DEDICATED = "Ayrılmış failover host'lar yerleşime kapalıdır (yalnız HA yeniden başlatma için): {names}"
NOTE_SLOT_FIT = "HA slot kontrolü (admission control): {needed} slot gerekli, {free} boş slot var"

V_FITS = "Sığar"
V_FRAG = "Sığmaz — parçalanma"
V_DS = "Sığmaz — datastore erişimi yok"
V_CAP = "Sığmaz — kapasite"
V_NONE = "Sığmaz — kullanılabilir host yok"
V_SLOT = "Sığmaz — HA slot (admission control)"


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
    """Her kullanılabilir host için, HA rezervi + havuz rezervasyonu + eşik uygulanmış boş bellek (GB).

    E3: "ayrılmış failover host" politikasında bu host'lar yerleşime KAPALIDIR (listeye girmez; kapasiteleri zaten
    rezerv sayıldığı için ayrıca oransal düşüm yapılmaz). Diğer politikalarda rezerv host'lara orantılı dağıtılır.
    """
    usable = usable_nodes(model)
    reserve = reserve_for(model)
    closed = set(reserve.get("closed_hosts") or [])
    nodes = [n for n in usable if n.name not in closed]
    mem_total = sum(n.mem_gb for n in nodes)
    pools = pool_deduction(model.pools) if model.platform == "vmware" else {
        "read": None, "deduct_gb": 0.0, "pools": [], "notes": []}
    reserve_gb = 0.0 if closed else reserve["mem_gb"]
    eff = max(mem_total - reserve_gb - pools["deduct_gb"], 0.0)
    scale = (eff / mem_total) if mem_total > 0 else 0.0
    hosts = []
    for n in nodes:
        share = n.mem_gb * scale
        cap = share * mem_thr_pct / 100.0
        hosts.append({"name": n.name, "ref": n.ref, "cores": float(n.cpu_cores or 0), "mem_gb": n.mem_gb,
                      "used_gb": n.mem_used_gb, "budget_gb": round(cap, 3),
                      "free_gb": max(cap - n.mem_used_gb, 0.0)})
    return {"hosts": hosts, "mem_total": mem_total, "reserve": reserve, "pools": pools, "effective_gb": eff,
            "closed_hosts": sorted(closed)}


def reserve_notes(b: Dict[str, Any]) -> List[str]:
    """Rezerv/kapalı host açıklamaları (What-if ve toplu yerleşimde ortak)."""
    if b.get("closed_hosts"):
        return [NOTE_DEDICATED.format(names=", ".join(b["closed_hosts"]))]
    return [NOTE_RESERVE_SPREAD] if b["reserve"]["mem_gb"] > 0 else []


def _ds_ok(ds: Dict[str, Any], host_ref: str, disk_gb: float, reserve_pct: float) -> bool:
    if ds.get("accessible") is False:
        return False
    refs = ds.get("host_refs")
    if refs is not None and host_ref not in refs:
        return False
    cap = float(ds.get("capacity_gb") or 0)
    free_after = float(ds.get("free_gb") or 0) - disk_gb
    return bool(cap) and free_after >= cap * reserve_pct / 100.0


# ── Tek yerleşim çekirdeği (E2) ──────────────────────────────────────────────
# What-if (`place_on_hosts`), toplu yerleşim (`virt_bulk_placement.place_bulk`), host-arızası simülasyonu
# (`failover.failover_place`) ve "VM nereye gitsin" önerisinin (`virt_placement.recommend_placement`) SIĞAR/SIĞMAZ
# kararı tek kuralla verilir: bir host, bütçesi (HA rezervi + havuz düşümü + eşik uygulanmış boş bellek) VM'in
# belleğini karşılıyorsa ve (varsa) disk/erişim koşulları sağlanıyorsa adaydır. Yöntemler yalnız ÜSTÜNE farklı katman
# ekler (puanlama, anti-affinity, "Sınırda" kademesi); sığma kararını değiştirmez.

def fits_host(free_gb: float, need_gb: float) -> bool:
    """Tek kural: boş bütçe ≥ ihtiyaç. Tüm yerleşim yolları bunu kullanır."""
    return float(free_gb) >= float(need_gb)


def memory_candidates(hosts: Sequence[Dict[str, Any]], need_gb: float) -> List[Dict[str, Any]]:
    """Bellek bütçesi VM'e yeten host'lar (`host_budgets()["hosts"]` satırları)."""
    return [h for h in hosts if fits_host(h["free_gb"], need_gb)]


def place_vms(hosts: Sequence[Dict[str, Any]], vms: Sequence[Dict[str, Any]],
              datastores: Optional[List[Dict[str, Any]]] = None, ds_reserve_pct: float = 15.0, *,
              physical_free: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """VM'leri büyükten küçüğe tek tek host'lara yerleştirir (saf, deterministik).

    `hosts`: {name, ref, free_gb}. `vms`: {vm, memory_gb, vcpu, disk_gb, group?, allowed?}.
      • en boş host seçilir (eşitlikte ada göre);
      • `group`: aynı gruptaki VM'ler farklı host'lara (anti-affinity);
      • `allowed`: VM'in gidebileceği host adları (ör. mevcut datastore'u bağlı olanlar); None → kısıt yok;
      • `datastores` (None → disk erişimi bilinmiyor): disk için erişilebilir + rezerv korunmuş datastore gerekir;
      • `physical_free` verilirse: eşik bütçesi yetmeyen VM, fiziksel boş belleğe sığıyorsa "tight" kademesine
        yerleşir (host-arızası senaryosu: "Sınırda"); verilmezse yalnız bütçe geçerlidir.
    Dönüş: {plan, unplaced, free, ds_state}; `unplaced[*].reason`: no_host | memory | fragmentation | datastore |
    anti_affinity.
    """
    hosts = list(hosts)
    free = {h["name"]: float(h["free_gb"]) for h in hosts}
    phys = dict(physical_free) if physical_free is not None else None
    ds_state = [dict(d) for d in datastores] if datastores is not None else None
    by_name = {h["name"]: h for h in hosts}
    on_host: Dict[str, set] = {}
    plan: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, Any]] = []
    def _vm_key(x: Dict[str, Any]):      # eşit boyutlarda sayısal VM no doğal sırada (1,2,…,10), metin ad alfabetik
        vm = x["vm"]
        return (0, vm, "") if isinstance(vm, int) else (1, 0, str(vm))

    order = sorted(vms, key=lambda x: (-float(x["memory_gb"]), -float(x.get("vcpu") or 0), _vm_key(x)))
    for v in order:
        mem, disk, grp = float(v["memory_gb"]), float(v.get("disk_gb") or 0), v.get("group")
        allowed = v.get("allowed")
        reason: Optional[str] = None
        in_scope = [h for h in hosts if allowed is None or h["name"] in allowed]
        cands = [h for h in in_scope if fits_host(free[h["name"]], mem)]
        level = "comfortable"
        if not cands and phys is not None:
            cands = [h for h in in_scope if fits_host(phys[h["name"]], mem)]
            level = "tight"
        if not hosts:
            reason = "no_host"
        elif not cands:
            mem_ok_elsewhere = any(fits_host((phys or free)[h["name"]], mem) for h in hosts)
            if allowed is not None and mem_ok_elsewhere:
                reason = "datastore"
            else:
                reason = "fragmentation" if sum(free.values()) >= mem else "memory"
        if reason is None and grp:
            cands = [h for h in cands if h["name"] not in on_host.get(grp, set())]
            if not cands:
                reason = "anti_affinity"
        if reason is None and disk > 0 and ds_state is not None:
            cands = [h for h in cands if any(_ds_ok(d, h["ref"], disk, ds_reserve_pct) for d in ds_state)]
            if not cands:
                reason = "datastore"
        if reason is not None:
            unplaced.append({**{k: v[k] for k in v if k != "allowed"}, "reason": reason})
            continue
        cands.sort(key=lambda h: (-free[h["name"]], h["name"]))
        pick = cands[0]
        free[pick["name"]] -= mem
        if phys is not None:
            phys[pick["name"]] -= mem
        ds_pick = None
        if disk > 0 and ds_state is not None:
            opts = sorted((d for d in ds_state if _ds_ok(d, by_name[pick["name"]]["ref"], disk, ds_reserve_pct)),
                          key=lambda d: (-(float(d.get("free_gb") or 0)), d["name"]))
            opts[0]["free_gb"] = float(opts[0].get("free_gb") or 0) - disk
            ds_pick = opts[0]["name"]
        if grp:
            on_host.setdefault(grp, set()).add(pick["name"])
        plan.append({**{k: v[k] for k in v if k != "allowed"}, "host": pick["name"], "datastore": ds_pick, "level": level})
    return {"plan": plan, "unplaced": unplaced, "free": free, "ds_state": ds_state}


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
    notes.extend(reserve_notes(b))
    if disk_gb > 0 and ds_state is None:
        notes.append(NOTE_DS_UNKNOWN)

    if not hosts:
        return {"fits": False, "verdict": V_NONE, "reason": "no_host", "placed": [], "unplaced": count,
                "warnings": warnings, "notes": notes, "confidence": "low", "cluster_free_gb": 0.0,
                "host_free": [], "pools": b["pools"]["pools"], "limiting": ["no_host"], "max_fit": 0}
    max_cores = max(h["cores"] for h in hosts)
    if vm_vcpu > max_cores > 0:
        warnings.append(f"VM vCPU ({vm_vcpu}) cluster'daki en büyük host'un fiziksel çekirdeğini ({max_cores:.0f}) aşıyor")
    # E2: ortak yerleşim çekirdeği (toplu yerleşim ve host-arızası ile aynı kural)
    r = place_vms(hosts, [{"vm": i + 1, "memory_gb": vm_mem_gb, "vcpu": vm_vcpu, "disk_gb": disk_gb}
                          for i in range(count)], ds_state, ds_reserve_pct)
    free = r["free"]
    ds_state = r["ds_state"]
    cores_of = {h["name"]: h["cores"] for h in hosts}
    placed = []
    for p in sorted(r["plan"], key=lambda x: x["vm"]):
        placed.append({"vm": p["vm"], "host": p["host"], "datastore": p["datastore"]})
        if vm_vcpu > cores_of[p["host"]] > 0:
            warnings.append(f"VM vCPU ({vm_vcpu}) host {p['host']} fiziksel çekirdeğini ({cores_of[p['host']]:.0f}) aşıyor")
    reason = {"memory": "capacity", "fragmentation": "fragmentation", "datastore": "datastore_access"}.get(
        r["unplaced"][0]["reason"]) if r["unplaced"] else None
    unplaced = count - len(placed)
    fits = unplaced == 0
    verdict = V_FITS if fits else {"fragmentation": V_FRAG, "datastore_access": V_DS}.get(reason or "", V_CAP)
    # E3: slot politikası (vCenter admission control) — bellek yetse bile boş slot yoksa VM açılamaz
    slots = rules_vmware.slot_check(model, count) if model.platform == "vmware" else None
    slot_block = bool(slots and not slots["fits"])
    if slots:
        notes.append(NOTE_SLOT_FIT.format(needed=slots["needed_slots"], free=slots["unreserved_slots"]))
        notes.append(slots["assumption"])
    if slot_block:
        if fits:
            verdict, reason = V_SLOT, "ha_slots"
        fits = False
    low = (b["pools"]["read"] is False)
    medium = bool(b["reserve"].get("assumed"))
    confidence = "low" if low else ("medium" if medium else "high")
    # En fazla kaç özdeş VM sığar: istenen adet yerleştiyse aynı durumdan devam edilir (en fazla _MAX_FIT_CAP).
    max_fit: Optional[int] = None
    if vm_mem_gb > 0 or (disk_gb > 0 and ds_state is not None):
        max_fit = len(placed)
        if fits:
            extra = _extra_fit(hosts, free, ds_state, vm_mem_gb, disk_gb, ds_reserve_pct, _MAX_FIT_CAP - max_fit)
            max_fit += extra
        if slots and max_fit is not None:
            max_fit = min(max_fit, int(slots["unreserved_slots"]))
    limiting = [] if (fits and not slot_block) else [_REASON_CODE.get(reason or "", "memory")]
    if slot_block and "ha_slots" not in limiting:
        limiting = [c for c in limiting if c != "memory" or unplaced > 0] + ["ha_slots"]
    return {
        "fits": fits, "verdict": verdict, "reason": None if fits else reason, "placed": placed, "unplaced": unplaced,
        "warnings": sorted(set(warnings)), "notes": notes, "confidence": confidence,
        "cluster_free_gb": round(sum(h["free_gb"] for h in hosts), 2),
        "host_free": [{"host": h["name"], "free_gb": round(h["free_gb"], 2)} for h in hosts],
        "pools": b["pools"]["pools"],
        "limiting": limiting,
        "max_fit": max_fit,
        **({"slots": slots} if slots else {}),
    }


_MAX_FIT_CAP = 2000
_REASON_CODE = {"capacity": "memory", "fragmentation": "fragmentation", "datastore_access": "datastore",
                "no_host": "no_host", "ha_slots": "ha_slots"}


def _extra_fit(hosts: Sequence[Dict[str, Any]], free: Dict[str, float], ds_state: Optional[List[Dict[str, Any]]],
               vm_mem_gb: float, disk_gb: float, ds_reserve_pct: float, limit: int) -> int:
    """Mevcut yerleşimden sonra aynı profilden kaç VM daha sığar (ortak çekirdek `place_vms`; girdileri değiştirmez)."""
    if limit <= 0 or (vm_mem_gb <= 0 and disk_gb <= 0):
        return 0
    cur = [{**h, "free_gb": free[h["name"]]} for h in hosts]
    r = place_vms(cur, [{"vm": i, "memory_gb": vm_mem_gb, "vcpu": 0, "disk_gb": disk_gb} for i in range(limit)],
                  ds_state, ds_reserve_pct)
    return len(r["plan"])
