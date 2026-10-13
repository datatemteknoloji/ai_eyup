"""Host arızası ve toplu yerleşim için ortak parçalar (saf, deterministik).

• p95 kullanım: `virt_vm_metrics` (VM başına p95 CPU/Memory %). VMware'de `mem_usage_pct` = guest AKTİF Memory
  (`guestMemoryUsage`) / tanımlı Memory; host'ta TÜKETİLEN Memory değildir (alt sınır, iyimser). `cpu_usage_pct` =
  kullanılan MHz / (vCPU × 2000 MHz varsayımı). Verisi olmayan VM tanımlı değerle hesaplanır (kapsama sayısı döner).
• Yerleştirme: büyükten küçüğe; eşik altı host'lar tercih edilir, yoksa fiziksel sınıra kadar ("Sınırda").
• CPU: (a) vCPU oranı politika oranını aşarsa UYARI (karara karışmaz); (b) p95 CPU talebi eşik (%80) üstü ama kalan
  fiziksel çekirdeklerin altındaysa "Sınırda"; (c) fiziksel çekirdekleri aşarsa "Sığmaz (CPU)".
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Set

from sqlalchemy.orm import Session

from app.services import capacity_policy


def _r(v: Optional[float], n: int = 1) -> Optional[float]:
    return None if v is None else round(float(v), n)


def p95_window_days() -> int:
    return int(capacity_policy.active().get("rs_window_days", 30))


def p95_index(db: Session, hv_ids: Sequence[int], days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """VM adı → p95 kullanım. Aynı adlı VM'ler farklı instance'larda ayrışsın diye (hv, ad) anahtarıyla döner."""
    from app.services import virt_reclaim
    return virt_reclaim.vm_usage(db, list(hv_ids), days=int(days or p95_window_days()))


def vm_need(v: Dict[str, Any], usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Bir VM'in tanımlı ve p95 ihtiyacı. p95 yoksa tanımlı değer kullanılır (`*_p95` False)."""
    mem = float(v.get("memory_gb") or 0)
    vcpu = float(v.get("vcpu") or 0)
    u = usage or {}
    p95m = u.get("p95_mem_pct")
    p95c = u.get("p95_cpu_pct")
    has_mem = bool(usage) and p95m is not None and float(p95m) > 0     # 0 = guest aracı yok/ölçülemedi sayılır
    has_cpu = bool(usage) and p95c is not None
    return {
        "mem_defined": mem, "mem_p95": mem * float(p95m) / 100.0 if has_mem else mem, "mem_has_p95": has_mem,
        "vcpu": vcpu, "cpu_p95_cores": vcpu * float(p95c) / 100.0 if has_cpu else vcpu, "cpu_has_p95": has_cpu,
    }


def coverage(needs: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    return {"vms_total": len(needs), "mem_with_p95": sum(1 for n in needs if n["mem_has_p95"]),
            "cpu_with_p95": sum(1 for n in needs if n["cpu_has_p95"])}


def failover_place(items: Sequence[Dict[str, Any]], nodes: Sequence[Any], thr_pct: float,
                   mounts: Optional[Dict[str, Set[str]]], need_gb: Callable[[Dict[str, Any]], float]) -> Dict[str, Any]:
    """`items` (VM'ler; name/memory_gb/datastore) kalan `nodes`a (model Node) tek tek yerleştirilir.

    E2: yerleştirme kuralı ortak çekirdektedir (`placement.place_vms`; What-if ve toplu yerleşimle aynı). Bu işlevin
    ÜSTÜNE eklediği katman: eşik bütçesi yetmezse fiziksel boş belleğe "tight" ("Sınırda") kademesi ve VM'in mevcut
    datastore'unu görebilen host kısıtı. HA rezervi bu senaryoda düşülmez (rezerv tam olarak bu arızayı karşılar).
    """
    from app.services.capacity import placement as cap_place
    hosts = [{"name": n.name, "ref": n.ref, "free_gb": n.mem_gb * thr_pct / 100.0 - n.mem_used_gb} for n in nodes]
    phys = {n.name: n.mem_gb - n.mem_used_gb for n in nodes}
    ref_of = {n.name: n.ref for n in nodes}
    vms = []
    for v in items:
        m = (mounts or {}).get(v.get("datastore") or "") if v.get("datastore") else None
        allowed = {n.name for n in nodes if ref_of.get(n.name) in m} if m else None
        vms.append({"vm": v.get("name"), "memory_gb": float(need_gb(v)), "vcpu": float(v.get("vcpu") or 0),
                    "disk_gb": 0.0, "allowed": allowed})
    r = cap_place.place_vms(hosts, vms, None, 0.0, physical_free=phys)
    placed: List[Dict[str, Any]] = [{"vm": p["vm"], "memory_gb": _r(p["memory_gb"]), "host": p["host"],
                                     "level": p["level"]} for p in r["plan"]]
    unplaced: List[Dict[str, Any]] = [{"vm": u["vm"], "memory_gb": _r(u["memory_gb"]),
                                       "reason": "memory" if u["reason"] == "fragmentation" else u["reason"]}
                                      for u in r["unplaced"]]
    if not items:
        verdict = "no_vm"
    elif unplaced:
        verdict = "fail"
    elif any(p["level"] == "tight" for p in placed):
        verdict = "tight"
    else:
        verdict = "fit"
    rem_total = sum(n.mem_gb for n in nodes)
    rem_used = sum(n.mem_used_gb for n in nodes) + sum(p["memory_gb"] or 0 for p in placed)
    return {"verdict": verdict, "status": {"fail": "fail", "tight": "warn"}.get(verdict, "ok"),
            "placed": placed, "unplaced": unplaced,
            "displaced_gb": _r(sum(need_gb(v) for v in items)),
            "after_memory_pct": _r(100.0 * rem_used / rem_total) if rem_total else None}


def cpu_check(*, remaining_cores: float, vcpu_total: float, demand_cores: float, thr_pct: float,
              ratio_limit: float, cov: Dict[str, int]) -> Dict[str, Any]:
    """Kalan host'larda CPU kontrolü. Oran aşımı yalnız uyarıdır (`ratio_warn`); karar p95 talebine göredir."""
    if remaining_cores <= 0:
        return {"verdict": "fail", "status": "fail", "limiting": "no_host", "remaining_cores": 0.0,
                "vcpu_total": _r(vcpu_total), "vcpu_ratio": None, "ratio_limit": ratio_limit, "ratio_warn": False,
                "p95_demand_cores": _r(demand_cores), "p95_pct": None, "threshold_pct": thr_pct, "coverage": cov}
    pct = 100.0 * demand_cores / remaining_cores
    if demand_cores > remaining_cores:
        verdict = "fail"
    elif pct > thr_pct:
        verdict = "tight"
    else:
        verdict = "fit"
    ratio = vcpu_total / remaining_cores
    return {"verdict": verdict, "status": {"fail": "fail", "tight": "warn"}.get(verdict, "ok"),
            "limiting": "cpu" if verdict != "fit" else None, "remaining_cores": _r(remaining_cores),
            "vcpu_total": _r(vcpu_total), "vcpu_ratio": _r(ratio, 2), "ratio_limit": ratio_limit,
            "ratio_warn": ratio > ratio_limit, "p95_demand_cores": _r(demand_cores), "p95_pct": _r(pct),
            "threshold_pct": thr_pct, "coverage": cov}


_RANK = {"fit": 0, "no_vm": 0, "tight": 1, "fail": 2}


def combine(memory: Dict[str, Any], cpu: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Genel karar = Memory (tanımlı) ve CPU'nun kötüsü; sınırlayan kodlar ve uyarılar ayrı."""
    parts = [("memory", memory)] + ([("cpu", cpu)] if cpu else [])
    worst = max((p[1]["verdict"] for p in parts), key=lambda v: _RANK.get(v, 0))
    limiting: List[str] = []
    for code, p in parts:
        if _RANK.get(p["verdict"], 0) >= max(1, _RANK.get(worst, 0)) and p["verdict"] not in ("fit", "no_vm"):
            no_host = (p.get("limiting") == "no_host") if code == "cpu" else any(
                u.get("reason") == "no_host" for u in p.get("unplaced") or [])
            limiting.append("no_host" if no_host else code)
    warnings = ["vcpu_ratio"] if cpu and cpu.get("ratio_warn") else []
    return {"verdict": worst, "status": {"fail": "fail", "tight": "warn"}.get(worst, "ok"),
            "limiting": list(dict.fromkeys(limiting)), "warnings": warnings}
