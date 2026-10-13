"""Geri kazanım (right-sizing) simülasyonu — SALT OKUNUR.

"Boşta / gereğinden büyük VM'ler p95 kullanıma göre küçültülürse cluster kapasitesi nasıl değişir?"
Kaynak: `virt_reclaim._vm_rows` (aynı tespit kuralları; eşikler istekte geçici değiştirilebilir, politika kaydedilmez).

Etki hesabı `capacity.engine.place` ile aynıdır (negatif ekleme): efektif Memory %, vCPU:çekirdek oranı, N+1.
  • vCPU kazanımı YALNIZ vCPU oranını düşürür; Memory boşaltmaz ve CPU kullanımı değişmez (p95'e göre boyutlandı).
  • Memory kazanımı yalnız Memory küçültme önerisi olan VM'lerden gelir (p95 aktif Memory < %25).
  • Kazanılan Memory host'ta kullanılan Memory'den düşülür (en iyi durum / üst sınır: VM tüketimi tahsis kadar
    azalır varsayımı). VM'ler gerçekten küçültülmez; yalnız simülasyondur.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services import capacity_policy, virt_insights_data as vd, virt_reclaim
from app.services.capacity import engine as cap_engine, hierarchy as cap_hier
from app.services.virt_capacity_planner import T, _r, build_capacity

# İstekte geçici değiştirilebilen eşikler (diğer anahtarlar da kabul edilir; `capacity_policy.validate` doğrular).
TUNABLE = ("rs_window_days", "rs_target_pct", "rs_min_reduction_pct", "rs_min_vcpu")


def _n1_status(pct: Optional[float], warn: float) -> Optional[str]:
    if pct is None:
        return None
    return "fail" if pct > 100 else ("warn" if pct > warn else "ok")


def reclaim_sim(db: Session, *, hypervisor_id: Optional[int] = None, cluster: Optional[str] = None,
                thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    overrides = capacity_policy.validate(thresholds or {})            # ValueError → çağıran 400 yapar
    capacity_policy.activate(db)
    hvs = vd.virt_hypervisors(db, hypervisor_id=hypervisor_id)
    cap = build_capacity(db, hypervisor_id=hypervisor_id, cluster=cluster, with_forecast=False)
    vm = virt_reclaim._vm_rows(db, hvs, overrides)
    used_th = dict(capacity_policy.active())
    by_cluster: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for kind, rows in (("idle", vm["idle"]), ("oversized", vm["oversized"])):
        for r in rows:
            key = (r["hypervisor_id"], cap_hier.cluster_label(r.get("cluster"), r.get("host")))
            rs = r.get("rightsize") or {}
            d_vcpu = max(0, int(r["vcpu"] or 0) - int(rs.get("vcpu") or r["vcpu"] or 0))
            d_mem = max(0.0, float(r["memory_gb"] or 0) - float(rs.get("memory_gb") or r["memory_gb"] or 0))
            if d_vcpu <= 0 and d_mem <= 0:
                continue
            by_cluster.setdefault(key, {}).setdefault(r["vm"], {
                "vm": r["vm"], "kind": kind, "vcpu": r["vcpu"], "new_vcpu": rs.get("vcpu"),
                "memory_gb": r["memory_gb"], "new_memory_gb": rs.get("memory_gb"),
                "freed_vcpu": d_vcpu, "freed_memory_gb": round(d_mem, 2),
                "p95_cpu_pct": r.get("p95_cpu_pct"), "p95_mem_pct": r.get("p95_mem_pct"),
                "data_days": r.get("data_days"), "confidence": r.get("confidence") or ("medium" if kind == "idle" else None),
            })
    out: List[Dict[str, Any]] = []
    for c in cap["clusters"]:
        capacity_policy.activate(values={**(c.get("thresholds") or cap["thresholds"]), **overrides})
        vms = list(by_cluster.get((c["hypervisor_id"], c["cluster"]), {}).values())
        f_vcpu = sum(v["freed_vcpu"] for v in vms)
        f_mem = round(sum(v["freed_memory_gb"] for v in vms), 2)
        pl = cap_engine.place(c, add_mem=-f_mem, add_cpu=0.0, add_vcpu=-float(f_vcpu), vcpu_single=0, thr=T,
                              overcommit=(c["memory"] or {}).get("overcommit"))
        mem, cpu, n1 = c["memory"], c["cpu"], c["n_plus_one"]
        vms.sort(key=lambda v: (-v["freed_memory_gb"], -v["freed_vcpu"], v["vm"]))
        out.append({
            "platform": c["platform"], "hypervisor_id": c["hypervisor_id"], "hypervisor": c["hypervisor"],
            "cluster": c["cluster"], "path": c.get("path"), "standalone": bool(c.get("standalone")),
            "vms_affected": len(vms),
            "vcpu": {"freed": f_vcpu, "vms": sum(1 for v in vms if v["freed_vcpu"] > 0)},
            "memory": {"freed_gb": f_mem, "vms": sum(1 for v in vms if v["freed_memory_gb"] > 0)},
            "before": {"memory_effective_pct": mem["effective_used_pct"], "vcpu_ratio": cpu["vcpu_ratio"],
                       "n1_memory_pct": n1.get("mem_after_pct"), "n1_status": n1.get("status")},
            "after": {"memory_effective_pct": _r(pl["eff_mem_pct"]), "vcpu_ratio": _r(pl["ratio_after"], 2),
                      "n1_memory_pct": _r(pl["n1_after"]),
                      "n1_status": (n1.get("status") if n1.get("status") in ("single_host", "no_data")
                                    else _n1_status(pl["n1_after"], T.n1_warn))},
            "vcpu_ratio_limit": T.vcpu_ratio, "top": vms[:20],
        })
    capacity_policy.activate(db)
    out.sort(key=lambda r: (-r["memory"]["freed_gb"], -r["vcpu"]["freed"], r["cluster"]))
    return {
        "ok": True, "clusters": out,
        "thresholds": {k: used_th[k] for k in TUNABLE}, "overridden": sorted(overrides),
        "notes": [
            "Salt okunur simülasyon: VM'ler küçültülmez.",
            "vCPU kazanımı yalnız vCPU:çekirdek oranını düşürür; Memory boşaltmaz, CPU kullanımını değiştirmez.",
            "Memory kazanımı yalnız Memory küçültme önerisi olan VM'lerden gelir (p95 aktif Memory < %25).",
            "Kazanılan Memory host'ta kullanılan Memory'den düşülür (üst sınır: VM tüketimi tahsis kadar azalır varsayımı).",
            "Boşta VM: son 7 günün ortalama CPU'su düşük olanlar; aşırı boyutlu: p95 CPU'ya göre önerilen vCPU belirgin küçük olanlar.",
            "Memory küçültme çoğu platformda VM yeniden başlatması gerektirir.",
        ],
    }
