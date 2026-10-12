"""Ortak kapasite senaryo motoru — saf fonksiyonlar (DB/ağ yok), deterministik.

Eski motorlarla BİREBİR aynı girdiler için aynı sonuçlar üretir (eşdeğerlik testleri). Yeni platform
etkenleri yalnız girdi VARSA devreye girer (yoksa None → eski davranış):

  • vCenter HA admission control: failover level / yüzde politikası / admission control kapalı / HA kapalı
    (eski `_ha_reserve` ile aynı).
  • OLVM: `ha_reservation` (Scheduling Policy → Enable HA Reservation) ve `memory_overcommit_pct`
    (Optimization → Memory Optimization: None=100, For Server Load=150, For Desktop Load=200).
  • OpenShift Virtualization: VM başına virt-launcher bellek yükü, vCPU başına CPU request
    (`vmiCPUAllocationRatio`) ve MachineConfigPool `maxUnavailable` (rolling update).

Resmi kaynaklar (doğrulama tarihi 2026-10-13) her fonksiyonda belirtilmiştir.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.services.capacity.model import ClusterModel, Demand, HaSpec, Node

OCP_WARN_PCT = 85.0
# OpenShift Virtualization varsayılan CPU allocation ratio (Red Hat "OpenShift Virtualization Cluster Sizing Guide":
# "default maximum of 10:1 … 100 millicores for each vCPU"). Küme değeri okunmadıysa bu varsayılan kullanılır.
DEFAULT_VMI_CPU_ALLOCATION_RATIO = 10.0


def _r(v: Optional[float], n: int = 1) -> Optional[float]:
    return None if v is None else round(float(v), n)


def _pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * a / b, 1) if b > 0 else None


# ── Düğüm kapasitesi / HA rezervi / N+1 (virt) ───────────────────────────────

def usable_nodes(model: ClusterModel) -> List[Node]:
    return [n for n in model.nodes if n.usable]


def reserve_for(model: ClusterModel) -> Dict[str, Any]:
    """HA politikasına göre ayrılan bellek/CPU (GB / çekirdek).

    vCenter: vSphere HA admission control — "Host failures cluster tolerates" (failover_level = N en büyük host),
    "Percentage of cluster resources reserved" (yüzde), admission control kapalı / HA kapalı → rezerv yok.
    OLVM: HA Reservation kapalıysa (açıkça False) Manager kapasite garantisi vermez → rezerv yok. Açıkken
    ayrılacak miktarın hesabı resmi Oracle belgesinde tanımlı DEĞİL → 1 host varsayımı (assumed=True).
    """
    usable = usable_nodes(model)
    mem_total = sum(n.mem_gb for n in usable)
    cpu_total = sum(float(n.cpu_cores or 0) for n in usable)
    by_mem = sorted(usable, key=lambda n: n.mem_gb, reverse=True)
    if len(usable) < 2:
        return {"policy": "single_host", "label": "Tek host — HA rezervi uygulanamaz (failover yok)",
                "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
    if model.reserve_mode == "none":
        return {"policy": "none", "label": "Rezerv yok (platformda HA rezervi kavramı yok)",
                "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
    if model.platform == "vmware" and model.ha is not None:
        vc: HaSpec = model.ha
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
                "mem_gb": sum(h.mem_gb for h in top),
                "cpu_cores": sum(float(h.cpu_cores or 0) for h in top), "assumed": False}
    if model.platform == "olvm" and model.ha_reservation is False:
        return {"policy": "ha_reservation_off",
                "label": "HA Reservation kapalı — Manager HA kapasitesini garanti etmez, rezerv yok",
                "mem_gb": 0.0, "cpu_cores": 0.0, "assumed": False}
    top = by_mem[:1]
    label = "Varsayım: 1 host rezerv (platform politikası okunmadı)"
    if model.platform == "olvm" and model.ha_reservation is True:
        label = "HA Reservation açık — ayrılan miktar resmi belgede tanımlı değil; varsayım: 1 host rezerv"
    return {"policy": "assumed_n1", "label": label,
            "mem_gb": sum(h.mem_gb for h in top),
            "cpu_cores": sum(float(h.cpu_cores or 0) for h in top), "assumed": True}


def n_plus_one(usable: Sequence[Node], mem_used: float, cpu_used: float, n1_warn: float) -> Dict[str, Any]:
    """En büyük (bellek) host düşünce kalan kapasitede doluluk; karar Memory ile verilir, CPU yalnız uyarı."""
    mem_total = sum(n.mem_gb for n in usable)
    cpu_total = sum(float(n.cpu_cores or 0) for n in usable)
    largest = max(usable, key=lambda n: n.mem_gb, default=None)
    n1: Dict[str, Any] = {"evaluable": len(usable) >= 2}
    if largest and len(usable) >= 2:
        rem_mem = mem_total - largest.mem_gb
        rem_cpu = cpu_total - float(largest.cpu_cores or 0)
        n1.update({
            "largest_host": largest.name,
            "largest_host_mem_gb": _r(largest.mem_gb),
            "remaining_mem_gb": _r(rem_mem),
            "mem_after_pct": _r(100.0 * mem_used / rem_mem) if rem_mem > 0 else None,
            "cpu_after_pct": _r(100.0 * cpu_used / rem_cpu) if rem_cpu > 0 else None,
        })
        m = n1["mem_after_pct"]
        n1["status"] = "fail" if m is None or m > 100 else ("warn" if m > n1_warn else "ok")
        n1["cpu_warning"] = bool(n1["cpu_after_pct"] and n1["cpu_after_pct"] > 100)
    else:
        n1["status"] = "single_host" if len(usable) == 1 else "no_data"
    return n1


def summarize(model: ClusterModel, n1_warn: float) -> Dict[str, Any]:
    """Küme düzeyi toplamlar, HA rezervi, effective kapasite ve N+1 — tek hesap noktası."""
    usable = usable_nodes(model)
    mem_total = sum(n.mem_gb for n in usable)
    mem_used = sum(n.mem_used_gb for n in usable)
    cpu_total = sum(float(n.cpu_cores or 0) for n in usable)
    cpu_used = sum(n.cpu_used_cores for n in usable)
    reserve = reserve_for(model)
    mem_eff = max(mem_total - reserve["mem_gb"], 0.0)
    cpu_eff = max(cpu_total - reserve["cpu_cores"], 0.0)
    out: Dict[str, Any] = {
        "mem_total": mem_total, "mem_used": mem_used, "cpu_total": cpu_total, "cpu_used": cpu_used,
        "reserve": reserve, "mem_eff": mem_eff, "cpu_eff": cpu_eff,
        "n1": n_plus_one(usable, mem_used, cpu_used, n1_warn),
        "usable": len(usable),
    }
    oc = model.mem_overcommit_pct
    if oc is not None and oc > 0:
        # OLVM: zamanlayıcı fiziksel belleğin %oc'sine kadar VM yerleştirir (Memory Optimization).
        # Taahhüt tabanı = çalışan VM bellek tahsisi; kapasite = (fiziksel − rezerv) × oc/100.
        sched = mem_eff * oc / 100.0
        out["overcommit"] = {
            "pct": float(oc), "scheduling_gb": sched, "committed_gb": float(model.mem_allocated_gb or 0.0),
            "committed_pct": _r(100.0 * float(model.mem_allocated_gb or 0.0) / sched) if sched > 0 else None,
        }
    return out


# ── Yerleşim (what-if) — virt ────────────────────────────────────────────────

def place(c: Dict[str, Any], *, add_mem: float, add_cpu: float, add_vcpu: float, vcpu_single: int,
          thr: Any, overcommit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """"Şu talep bu kümeye sığar mı?" — `c`: küme çözümlemesi (memory/cpu/n_plus_one/hosts_usable/...).

    Kararı eşikler (`thr.mem`, `thr.n1_warn`, `thr.cpu`, `thr.vcpu_ratio`) verir; veri-yoksa alanlar None.
    """
    reasons: List[str] = []
    mem, cpu, n1 = c["memory"], c["cpu"], c["n_plus_one"]
    mem_used = (mem["used_gb"] or 0) + add_mem
    cpu_used = (cpu["used_cores"] or 0) + add_cpu
    eff_mem_pct = 100.0 * mem_used / mem["effective_gb"] if mem["effective_gb"] else None
    eff_cpu_pct = 100.0 * cpu_used / cpu["effective_cores"] if cpu["effective_cores"] else None
    n1_after = (100.0 * mem_used / n1["remaining_mem_gb"]) if n1.get("remaining_mem_gb") else None
    ratio_after = ((cpu["vcpu_allocated"] or 0) + add_vcpu) / cpu["total_cores"] if cpu["total_cores"] else None
    fits = True
    if eff_mem_pct is None or eff_mem_pct > thr.mem:
        fits = False
        reasons.append(f"Effective Memory %{_r(eff_mem_pct)} > %{thr.mem:.0f}")
    if n1_after is not None and n1_after > 100:
        fits = False
        reasons.append(f"N+1 bozulur (en büyük host düşünce Memory %{_r(n1_after)})")
    elif n1_after is not None and n1_after > thr.n1_warn:
        reasons.append(f"N+1 sınırda (%{_r(n1_after)})")
    if eff_cpu_pct is not None and eff_cpu_pct > thr.cpu:
        reasons.append(f"CPU effective %{_r(eff_cpu_pct)} — performans riski (uyarı)")
    if ratio_after and ratio_after > thr.vcpu_ratio:
        reasons.append(f"vCPU:çekirdek {ratio_after:.1f}:1 (uyarı)")
    if c["hosts_usable"] == 0:
        fits = False
        reasons.append("Kullanılabilir host yok")
    if vcpu_single > (c.get("typical_host_cores") or 0) and c.get("typical_host_cores"):
        reasons.append(f"Tek VM vCPU ({vcpu_single}) host çekirdeğinden ({c['typical_host_cores']:.0f}) fazla")
    committed_after_pct = None
    if overcommit and overcommit.get("scheduling_gb"):
        committed_after_pct = _r(100.0 * (overcommit["committed_gb"] + add_mem) / overcommit["scheduling_gb"])
        if committed_after_pct is not None and committed_after_pct > 100:
            fits = False
            reasons.append(f"Bellek taahhüdü %{committed_after_pct}: zamanlayıcı sınırı (%{overcommit['pct']:.0f} "
                           "overcommit) aşılır")
    return {"fits": fits, "reasons": reasons, "eff_mem_pct": eff_mem_pct, "eff_cpu_pct": eff_cpu_pct,
            "n1_after": n1_after, "ratio_after": ratio_after, "committed_after_pct": committed_after_pct}


# ── Drene senaryosu — OpenShift (request / allocatable) ──────────────────────

def drain(workers: Sequence[Dict[str, Any]], *, drain_names: Sequence[str], cpu_cores: float = 0.0,
          memory_gb: float = 0.0, count: int = 0) -> Dict[str, Any]:
    """Seçilen worker'lar drene edilirse ve/veya yeni iş yükü eklenirse request/allocatable doluluğu.

    Girdi `ocp_insights.evaluate` çıktısındaki `capacity.workers` biçimindedir (cpu_m, mem_gb, req_*).
    """
    workers = list(workers or [])
    drain = list(drain_names or [])
    if not workers:
        return {"ok": False, "error": "Worker verisi yok — önce taramayı çalıştırın"}
    names = {w["name"] for w in workers}
    unknown = [d for d in drain if d not in names]
    if unknown:
        return {"ok": False, "error": f"Bilinmeyen node: {', '.join(unknown)}"}
    cpu_cores, memory_gb, count = max(0.0, float(cpu_cores or 0)), max(0.0, float(memory_gb or 0)), max(0, int(count or 0))
    usable = [w for w in workers if w.get("ready") and w.get("schedulable")]
    remaining = [w for w in usable if w["name"] not in set(drain)]
    if not remaining:
        return {"ok": True, "verdict": "fail", "reason": "Zamanlanabilir worker kalmıyor", "drain": drain,
                "remaining_workers": 0, "notes": []}
    alloc_cpu = sum(w["cpu_m"] for w in remaining)
    alloc_mem = sum(w["mem_gb_raw"] if "mem_gb_raw" in w else w["mem_gb"] for w in remaining)
    req_cpu = sum(w["req_cpu_m"] for w in workers)
    req_mem = sum(w["req_mem_gb"] for w in workers)
    add_cpu_m, add_mem = cpu_cores * 1000.0 * count, memory_gb * count
    after_cpu, after_mem = _pct(req_cpu + add_cpu_m, alloc_cpu), _pct(req_mem + add_mem, alloc_mem)
    before_cpu = _pct(req_cpu, sum(w["cpu_m"] for w in usable))
    before_mem = _pct(req_mem, sum(w.get("mem_gb", 0) for w in usable))
    worst = max(after_cpu or 0, after_mem or 0)
    verdict = "fail" if worst > 100 else ("warn" if worst > OCP_WARN_PCT else "ok")
    free_cpu, free_mem = alloc_cpu - req_cpu, alloc_mem - req_mem
    fit_more: Optional[int] = None
    if cpu_cores > 0 or memory_gb > 0:
        lim = []
        if cpu_cores > 0:
            lim.append(free_cpu / (cpu_cores * 1000.0))
        if memory_gb > 0:
            lim.append(free_mem / memory_gb)
        fit_more = max(0, int(math.floor(min(lim)))) if lim else None
    return {
        "ok": True, "verdict": verdict, "drain": drain, "remaining_workers": len(remaining),
        "before": {"cpu_pct": before_cpu, "memory_pct": before_mem},
        "after": {"cpu_pct": after_cpu, "memory_pct": after_mem},
        "allocatable_after": {"cpu_cores": round(alloc_cpu / 1000.0, 1), "memory_gb": round(alloc_mem, 1)},
        "free_after": {"cpu_cores": round(free_cpu / 1000.0, 1), "memory_gb": round(free_mem, 1)},
        "added": {"cpu_cores": cpu_cores, "memory_gb": memory_gb, "count": count},
        "max_additional": fit_more,
        "notes": [
            "Hesap request/allocatable toplamıdır; node seçici, taint, anti-affinity ve RWO volume kısıtları değerlendirilmez.",
            "Drene edilen node'daki DaemonSet pod'ları başka node'a taşınmaz; hesap bunları taşınacak sayar (temkinli).",
            "Eşik: >%85 uyarı, >%100 sığmaz.",
        ],
    }


def worker_n_plus_one(usable: Sequence[Dict[str, Any]], req_cpu_m: float, req_mem_gb: float) -> Dict[str, Any]:
    """OpenShift: en büyük (allocatable bellek) worker düşünce request/allocatable — düğüm kapasitesi tek yerde.

    Ham (yuvarlanmamış) yüzdeler döner; karar eski `ocp_insights.evaluate` ile aynıdır:
    Memory > %100 (veya kalan yok) ya da CPU > %100 → fail; > %90 → warn.
    """
    tot_cpu = sum(w["cpu_m"] for w in usable)
    tot_mem = sum(w["mem_gb"] for w in usable)
    big = max(usable, key=lambda w: w["mem_gb"])
    rem_mem = tot_mem - big["mem_gb"]
    rem_cpu = tot_cpu - big["cpu_m"]
    n1_mem = 100.0 * req_mem_gb / rem_mem if rem_mem > 0 else None
    n1_cpu = 100.0 * req_cpu_m / rem_cpu if rem_cpu > 0 else None
    fail = (n1_mem is None or n1_mem > 100) or (n1_cpu is not None and n1_cpu > 100)
    status = "fail" if fail else ("warn" if max(n1_mem or 0, n1_cpu or 0) > 90 else "ok")
    return {"big": big, "n1_mem": n1_mem, "n1_cpu": n1_cpu, "fail": fail, "status": status}


# ── OpenShift Virtualization etkenleri ───────────────────────────────────────

def vm_memory_overhead_mib(memory_mib: float, vcpus: int, *, graphics: int = 0, sriov_or_gpu: int = 0,
                           extra_mib: float = 0.0) -> float:
    """VM başına virt-launcher bellek yükü (MiB).

    Kaynak: Red Hat OpenShift Container Platform — Virtualization → Installing → "Memory overhead"
    (docs.redhat.com …/virtualization/installing, 4.12 ve 4.18'de doğrulandı):
        overhead ≈ 0.002 × istenen bellek + 218 MiB + 8 MiB × vCPU + 16 MiB × grafik aygıtı + ek yük
        ek yük: her SR-IOV ağ aygıtı / GPU için 1 GiB.
    NOT: 4.13 sayfasında katsayı "1.002" yazıyor; 4.12, 4.18 ve Red Hat Cluster Sizing Guide "0.002" diyor —
    belge tutarsızlığı, çoğunluk (0.002) kullanıldı. SEV (+256 MiB) / TPM (+53 MiB) yalnız yeni sürüm
    belgelerinde var; gerekirse `extra_mib` ile verilir (kodlanmadı).
    """
    return (0.002 * float(memory_mib) + 218.0 + 8.0 * int(vcpus) + 16.0 * int(graphics)
            + 1024.0 * int(sriov_or_gpu) + float(extra_mib))


def vm_cpu_request_cores(vcpus: int, allocation_ratio: float = DEFAULT_VMI_CPU_ALLOCATION_RATIO) -> float:
    """VM podunun CPU request'i = vCPU × 1/vmiCPUAllocationRatio (HCO `spec.resourceRequirements`; varsayılan 10).

    Kaynak: Red Hat OpenShift Virtualization Cluster Sizing Guide ("100 millicores for each vCPU … default 10:1")
    ve HyperConverged API alan açıklaması. Oran > 0 olmalıdır. Ayrılmış (dedicated) CPU'lu VM'lerde etkisizdir —
    bu fonksiyon dedicated CPU'yu modellemez.
    """
    if not allocation_ratio or allocation_ratio <= 0:
        raise ValueError("allocation_ratio > 0 olmalı")
    return float(vcpus) / float(allocation_ratio)


def vm_demand(count: int, vcpus: int, memory_gib: float, *, allocation_ratio: float = DEFAULT_VMI_CPU_ALLOCATION_RATIO,
              graphics: int = 0, sriov_or_gpu: int = 0) -> Dict[str, float]:
    """`count` VM için OpenShift'te zamanlama talebi (pod request): bellek = VM belleği + virt-launcher yükü."""
    count = max(0, int(count))
    over_gib = vm_memory_overhead_mib(memory_gib * 1024.0, vcpus, graphics=graphics, sriov_or_gpu=sriov_or_gpu) / 1024.0
    return {
        "count": count,
        "memory_gb_each": memory_gib + over_gib, "overhead_gb_each": over_gib,
        "cpu_cores_each": vm_cpu_request_cores(vcpus, allocation_ratio),
        "memory_gb": count * (memory_gib + over_gib), "cpu_cores": count * vm_cpu_request_cores(vcpus, allocation_ratio),
    }


def parse_max_unavailable(value: Union[int, str, None]) -> Tuple[Optional[int], Optional[str]]:
    """MachineConfigPool `spec.maxUnavailable` → (tam sayı, uyarı).

    Kaynak: OCP Machine APIs — MachineConfigPool: varsayılan 1; 0 verilirse 1'e döner; sayı veya yüzde olabilir.
    Yüzdenin düğüm sayısına nasıl yuvarlandığı resmi belgede YOK → yüzde değerlendirilmez (None + açıklama).
    """
    if value is None or value == "":
        return 1, None
    if isinstance(value, bool):
        return None, "geçersiz maxUnavailable"
    if isinstance(value, int):
        return (value if value >= 1 else 1), None
    s = str(value).strip()
    if s.endswith("%"):
        return None, ("maxUnavailable yüzde olarak verilmiş; yüzdenin düğüm sayısına yuvarlanması resmi belgede "
                      "tanımlı değil — senaryo ölçülemedi")
    try:
        n = int(s)
    except ValueError:
        return None, "geçersiz maxUnavailable"
    return (n if n >= 1 else 1), None


def rolling_update(workers: Sequence[Dict[str, Any]], max_unavailable: Union[int, str, None] = None, *,
                   cpu_cores: float = 0.0, memory_gb: float = 0.0, count: int = 0) -> Dict[str, Any]:
    """MCP rolling update'te EN KÖTÜ an: aynı anda `maxUnavailable` düğüm erişilemez.

    MCP, havuzdaki herhangi bir nedenle erişilemeyen düğümleri (cordon, arızalı düğüm dahil) sayar; bu yüzden
    zaten erişilemeyen düğümler bütçeden düşer. En kötü durum: kalan en büyük (allocatable bellek) düğümler
    birlikte drene olur. PDB'ler drene saygı duyar (modellenmez). `workers` bu havuzun düğümleridir.
    """
    n, warn = parse_max_unavailable(max_unavailable)
    if n is None:
        return {"ok": True, "verdict": "not_measurable", "reason": warn, "drain": [], "max_unavailable": max_unavailable}
    workers = list(workers or [])
    usable = [w for w in workers if w.get("ready") and w.get("schedulable")]
    already = len(workers) - len(usable)
    budget = max(0, n - already)
    pick = sorted(usable, key=lambda w: (-w["mem_gb"], w["name"]))[:budget]
    res = drain(workers, drain_names=[w["name"] for w in pick], cpu_cores=cpu_cores, memory_gb=memory_gb, count=count)
    if res.get("ok"):
        res["rolling_update"] = {"max_unavailable": n, "already_unavailable": already,
                                 "additional_drained": [w["name"] for w in pick]}
        res["notes"] = list(res.get("notes") or []) + [
            "MCP maxUnavailable, havuzda herhangi bir nedenle erişilemeyen düğümleri de sayar; hesap en büyük düğümlerin birlikte drene olduğu en kötü anı gösterir.",
            "Pod Disruption Budget'lar drene saygı duyar; hesap PDB'leri değerlendirmez.",
        ]
    return res
