"""OpenShift kapasite senaryoları ve node risk kartı (deterministik).

  • simulate(): seçilen worker'lar drene edilirse ve/veya yeni iş yükü eklenirse request/allocatable
    doluluğu. Girdi son tarama özeti (InfraCheckRun.stats.capacity) — canlı API çağrısı yok.
  • node_risk(): son N günde Node olaylarının (NotReady, baskı, reboot, bağlantı kesintisi) tekrarı.
    Tahmin / zaman projeksiyonu üretmez; yalnız gözlenen olay sayısı + anlık durum.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

WARN_PCT = 85.0
_WEIGHTS = {"NodeNotReady": 3, "KubeletNotReady": 3, "NodeHasDiskPressure": 2, "NodeHasMemoryPressure": 2,
            "NodeHasPIDPressure": 2, "Rebooted": 2, "ConnectivityOutageDetected": 1, "NodeHasNoDiskPressure": 0,
            "NodeHasSufficientMemory": 0, "NodeHasSufficientPID": 0, "NodeReady": 0, "NodeSchedulable": 0}


def _pct(a: float, b: float) -> Optional[float]:
    return round(100.0 * a / b, 1) if b > 0 else None


def simulate(cap: Dict[str, Any], *, drain: List[str], cpu_cores: float = 0.0, memory_gb: float = 0.0,
             count: int = 0) -> Dict[str, Any]:
    workers = list((cap or {}).get("workers") or [])
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
    verdict = "fail" if worst > 100 else ("warn" if worst > WARN_PCT else "ok")
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


def node_risk(db: Session, *, days: int = 7, cluster_id: Optional[int] = None) -> Dict[str, Any]:
    from app.models.event import SystemEvent
    from app.models.infra_finding import InfraFinding
    days = max(1, min(int(days or 7), 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (db.query(SystemEvent).filter(SystemEvent.created_at >= since, SystemEvent.title.like("Node/%"))
            .order_by(SystemEvent.created_at.desc()).limit(5000).all())
    agg: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {"counts": Counter(), "last": None, "cluster": None})
    for e in rows:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if rd.get("platform") != "openshift":
            continue
        cid = rd.get("cluster_id")
        if cluster_id is not None and str(cid) != str(cluster_id):
            continue
        node = str(rd.get("source_object") or "").split("/", 1)[-1]
        if not node:
            continue
        a = agg[(cid, node)]
        a["counts"][str(rd.get("reason") or "?")] += 1
        a["cluster"] = rd.get("cluster_name")
        if a["last"] is None:
            a["last"] = e.created_at.isoformat() if e.created_at else None
    bad_now = {}
    q = db.query(InfraFinding).filter(InfraFinding.platform == "ocp", InfraFinding.check_id == "ocp.node.condition",
                                      InfraFinding.active.is_(True), InfraFinding.result == "fail")
    if cluster_id is not None:
        q = q.filter(InfraFinding.source_id == cluster_id)
    for f in q.all():
        bad_now[(f.source_id, f.entity_name)] = (f.evidence or {}).get("pressure") or ["NotReady"]
    for (cid, node) in bad_now:
        agg.setdefault((cid, node), {"counts": Counter(), "last": None, "cluster": None})
    out: List[Dict[str, Any]] = []
    for (cid, node), a in agg.items():
        now_bad = next((v for (sid, n), v in bad_now.items() if n == node and str(sid) == str(cid)), None)
        score = sum(_WEIGHTS.get(r, 0.5) * n for r, n in a["counts"].items()) + (5 if now_bad else 0)
        if score <= 0:
            continue
        out.append({"cluster_id": cid, "cluster": a["cluster"], "node": node, "score": round(score, 1),
                    "level": "high" if score >= 6 else ("medium" if score >= 3 else "low"),
                    "counts": dict(a["counts"].most_common()), "last_event": a["last"],
                    "unhealthy_now": bool(now_bad), "now": now_bad})
    out.sort(key=lambda x: -x["score"])
    return {"ok": True, "window_days": days, "nodes": out,
            "note": "Yalnız gözlenen Node olay sayısı ve anlık durum; arıza zamanı tahmini yapılmaz."}
