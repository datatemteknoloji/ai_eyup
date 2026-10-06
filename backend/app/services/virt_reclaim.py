"""Atıl kaynak geri kazanımı — kapalı/atıl/aşırı boyutlu VM, snapshot, sahipsiz disk, ISO.

Atıl / aşırı boyut kriterleri `report_engine.generate_consolidation_report` ile
AYNIDIR (7 gün ort. CPU < %8 ve vCPU≥2 veya Memory≥4 GB; aşırı boyut vCPU≥4 ve
CPU < %15) — iki ekran farklı sayı göstermesin. Burada ek olarak platform /
cluster kırılımı, kapalı kalma süresi, p95 tabanlı right-size önerisi,
snapshot yaşı/büyümesi ve datastore dosya taraması vardır.

Hiçbir öğe otomatik silinmez: liste "aday"dır, istisna ile işaretlenebilir.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import virt_insights_data as vd

IDLE_CPU_PCT = 8.0
OVERSIZED_CPU_PCT = 15.0
OVERSIZED_MIN_VCPU = 4
SNAPSHOT_WARN_DAYS = 3
SNAPSHOT_HIGH_DAYS = 14
RIGHTSIZE_TARGET_PCT = 70.0
BACKUP_NOTE = ("Yedekleme (Veeam) entegrasyonu kapsam dışıdır: replica/yedek klasörleri işaretlenir, "
               "ancak yedek zinciri ve geri dönüş noktası doğrulanmaz. Silmeden önce yedek ekibiyle teyit edin.")


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def vm_usage(db: Session, hv_ids: List[int], days: int = 7) -> Dict[Tuple[int, str], Dict[str, Any]]:
    if not hv_ids:
        return {}
    rows = db.execute(text("""
        SELECT hypervisor_id, vm_name,
               avg(cpu_usage_pct) AS avg_cpu, avg(mem_usage_pct) AS avg_mem,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage_pct) AS p95_cpu,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY mem_usage_pct) AS p95_mem,
               count(*) AS samples
          FROM virt_vm_metrics
         WHERE hypervisor_id = ANY(:ids) AND timestamp > now() - make_interval(days => :d)
           AND power_state IN ('POWERED_ON', 'poweredOn', 'up', 'running')
         GROUP BY hypervisor_id, vm_name
        HAVING count(*) >= 3
    """), {"ids": hv_ids, "d": days}).mappings().all()
    return {(int(r["hypervisor_id"]), r["vm_name"]): {
        "avg_cpu_pct": round(_f(r["avg_cpu"]) or 0, 1), "avg_mem_pct": round(_f(r["avg_mem"]) or 0, 1),
        "p95_cpu_pct": round(_f(r["p95_cpu"]) or 0, 1), "p95_mem_pct": round(_f(r["p95_mem"]) or 0, 1),
        "samples": int(r["samples"] or 0),
    } for r in rows}


def last_powered_on(db: Session, hv_ids: List[int]) -> Tuple[Dict[Tuple[int, str], datetime], Optional[datetime]]:
    if not hv_ids:
        return {}, None
    rows = db.execute(text("""
        SELECT hypervisor_id, vm_name, max(timestamp) AS t
          FROM virt_vm_metrics
         WHERE hypervisor_id = ANY(:ids) AND power_state IN ('POWERED_ON', 'poweredOn', 'up', 'running')
         GROUP BY hypervisor_id, vm_name
    """), {"ids": hv_ids}).mappings().all()
    oldest = db.execute(text("SELECT min(timestamp) FROM virt_vm_metrics WHERE hypervisor_id = ANY(:ids)"),
                        {"ids": hv_ids}).scalar()
    return {(int(r["hypervisor_id"]), r["vm_name"]): r["t"] for r in rows}, oldest


def snapshot_space(db: Session, hv_ids: List[int]) -> Dict[Tuple[int, str], Dict[str, Any]]:
    """Son ve 7 gün önceki snapshot alanı → büyüme (GB/gün)."""
    if not hv_ids:
        return {}
    rows = db.execute(text("""
        WITH last AS (
          SELECT DISTINCT ON (hypervisor_id, vm_name) hypervisor_id, vm_name, snapshot_space_gb, snapshot_count, timestamp
            FROM virt_vm_metrics
           WHERE hypervisor_id = ANY(:ids) AND timestamp > now() - interval '1 day'
           ORDER BY hypervisor_id, vm_name, timestamp DESC
        ), prev AS (
          SELECT DISTINCT ON (hypervisor_id, vm_name) hypervisor_id, vm_name, snapshot_space_gb, timestamp
            FROM virt_vm_metrics
           WHERE hypervisor_id = ANY(:ids)
             AND timestamp BETWEEN now() - interval '8 days' AND now() - interval '6 days'
           ORDER BY hypervisor_id, vm_name, timestamp DESC
        )
        SELECT l.hypervisor_id, l.vm_name, l.snapshot_space_gb AS now_gb, l.snapshot_count AS cnt,
               p.snapshot_space_gb AS prev_gb, EXTRACT(EPOCH FROM (l.timestamp - p.timestamp)) / 86400 AS span
          FROM last l LEFT JOIN prev p USING (hypervisor_id, vm_name)
         WHERE COALESCE(l.snapshot_count, 0) > 0 OR COALESCE(l.snapshot_space_gb, 0) > 0
    """), {"ids": hv_ids}).mappings().all()
    out = {}
    for r in rows:
        now_gb, prev_gb, span = _f(r["now_gb"]), _f(r["prev_gb"]), _f(r["span"])
        growth = round((now_gb - prev_gb) / span, 2) if now_gb is not None and prev_gb is not None and span else None
        out[(int(r["hypervisor_id"]), r["vm_name"])] = {"space_gb": now_gb, "count": r["cnt"],
                                                       "growth_gb_day": growth}
    return out


def _rightsize(vcpu: int, mem_gb: float, u: Dict[str, Any]) -> Dict[str, Any]:
    p95c = u.get("p95_cpu_pct") or 0
    new_vcpu = max(1, math.ceil(vcpu * p95c / RIGHTSIZE_TARGET_PCT)) if vcpu else None
    if new_vcpu and new_vcpu >= vcpu:
        new_vcpu = None
    p95m = u.get("p95_mem_pct") or 0
    new_mem = None
    if mem_gb and p95m and p95m < 25:
        new_mem = max(2, int(math.ceil(mem_gb * max(p95m, 15) / 60.0 / 2.0) * 2))
        if new_mem >= mem_gb:
            new_mem = None
    return {"vcpu": new_vcpu, "memory_gb": new_mem,
            "basis": f"p95 CPU %{p95c} hedef %{RIGHTSIZE_TARGET_PCT:.0f}; Memory yalnız p95 < %25 ise (aktif bellek)"}


def _vm_rows(db: Session, hvs) -> Dict[str, List[Dict[str, Any]]]:
    hv_ids = [h.id for h in hvs]
    plat = {h.id: vd.platform_of(h) for h in hvs}
    hv_name = {h.id: h.name for h in hvs}
    vms = vd.vm_allocations(db, hv_ids)
    usage = vm_usage(db, hv_ids)
    last_on, oldest = last_powered_on(db, hv_ids)
    now = datetime.now(timezone.utc)
    off, idle, over = [], [], []
    for v in vms:
        base = {"vm": v["name"], "hypervisor_id": v["hypervisor_id"], "hypervisor": hv_name.get(v["hypervisor_id"]),
                "platform": plat.get(v["hypervisor_id"]), "cluster": v.get("cluster"), "host": v.get("host"),
                "vcpu": v["vcpu"], "memory_gb": v["memory_gb"], "disk_gb": v["disk_gb"], "tier": v.get("tier")}
        if not v["powered_on"]:
            lo = last_on.get((v["hypervisor_id"], v["name"]))
            if lo is not None and lo.tzinfo is None:
                lo = lo.replace(tzinfo=timezone.utc)
            o = oldest.replace(tzinfo=timezone.utc) if oldest is not None and oldest.tzinfo is None else oldest
            off.append({**base,
                        "last_on": lo.isoformat() if lo else None,
                        "off_days": (now - lo).days if lo else None,
                        "off_days_min": None if lo else ((now - o).days if o else None)})
            continue
        u = usage.get((v["hypervisor_id"], v["name"]))
        if not u:
            continue
        if u["avg_cpu_pct"] < IDLE_CPU_PCT and (v["vcpu"] >= 2 or v["memory_gb"] >= 4):
            idle.append({**base, **u, "rightsize": _rightsize(v["vcpu"], v["memory_gb"], u)})
        elif v["vcpu"] >= OVERSIZED_MIN_VCPU and u["avg_cpu_pct"] < OVERSIZED_CPU_PCT:
            over.append({**base, **u, "rightsize": _rightsize(v["vcpu"], v["memory_gb"], u)})
    off.sort(key=lambda r: (-(r["off_days"] or r["off_days_min"] or 0), -(r["memory_gb"] or 0)))
    idle.sort(key=lambda r: (r["avg_cpu_pct"], -(r["memory_gb"] or 0)))
    over.sort(key=lambda r: (-(r["vcpu"] or 0), r["avg_cpu_pct"]))
    return {"powered_off": off, "idle": idle, "oversized": over}


def _files(db: Session, hv_ids: List[int]) -> Dict[str, Any]:
    from app.models.infra_finding import VirtDatastoreFile
    rows = db.query(VirtDatastoreFile).filter(VirtDatastoreFile.source_id.in_(hv_ids)).all() if hv_ids else []
    by_ds: Dict[Tuple[int, str], Dict[str, int]] = defaultdict(lambda: {"attached": 0, "total": 0})
    orphans, isos = [], []
    last_scan: Dict[int, Optional[str]] = {}
    for r in rows:
        extra = r.extra or {}
        last_scan[r.source_id] = max(filter(None, [last_scan.get(r.source_id), r.as_of.isoformat() if r.as_of else None]),
                                     default=None)
        if r.kind in ("vmdk", "disk", "datavolume", "pvc"):
            st = by_ds[(r.source_id, r.datastore or "")]
            st["total"] += 1
            if r.attached:
                st["attached"] += 1
        if r.attached or extra.get("content_library") or extra.get("golden_image"):
            continue
        item = {"id": r.id, "hypervisor_id": r.source_id, "platform": r.platform, "kind": r.kind,
                "datastore": r.datastore, "path": r.path, "name": r.name, "size_gb": r.size_gb,
                "modified_at": r.modified_at.isoformat() if r.modified_at else None, "extra": extra}
        (isos if r.kind == "iso" else orphans).append(item)
    orphans.sort(key=lambda x: -(x["size_gb"] or 0))
    isos.sort(key=lambda x: -(x["size_gb"] or 0))
    return {"orphans": orphans, "isos": isos, "by_ds": by_ds, "last_scan": last_scan}


def build_reclaim(db: Session, *, hypervisor_id: Optional[int] = None, platform: Optional[str] = None,
                  cluster: Optional[str] = None) -> Dict[str, Any]:
    from app.services.findings.store import query_findings
    hvs = vd.virt_hypervisors(db, platform=platform, hypervisor_id=hypervisor_id)
    hv_ids = [h.id for h in hvs]
    vm = _vm_rows(db, hvs)
    if cluster:
        for k in vm:
            vm[k] = [r for r in vm[k] if r.get("cluster") == cluster]
    snaps_space = snapshot_space(db, hv_ids)
    snap_findings = [f for f in query_findings(db, check_id="reclaim.vm.snapshot_age", limit=5000)
                     if f["source_id"] in hv_ids and (not cluster or f.get("cluster_name") == cluster)]
    for f in snap_findings:
        s = snaps_space.get((f["source_id"], f["entity_name"]))
        if s:
            f["evidence"] = {**(f.get("evidence") or {}), "space_gb": s["space_gb"], "growth_gb_day": s["growth_gb_day"]}
    files = _files(db, hv_ids)
    used_ds = defaultdict(int)
    for v in vd.vm_allocations(db, hv_ids):
        if v.get("datastore"):
            used_ds[(v["hypervisor_id"], v["datastore"])] += 1
    unused_ds = []
    for d in vd.latest_datastores(db, [h.id for h in hvs if vd.platform_of(h) in ("vmware", "olvm")]):
        st = files["by_ds"].get((d["hypervisor_id"], d["name"]))
        if used_ds.get((d["hypervisor_id"], d["name"])):
            continue
        if st is None or st["attached"] > 0:
            continue
        unused_ds.append({**d, "files": st["total"],
                          "note": "Kayıtlı VM yok ve taramada bağlı disk bulunmadı — başka vCenter/şablon kullanımı doğrulanmalı"})
    excepted_refs = {(f["source_id"], f["entity_ref"]) for f in query_findings(
        db, category="reclaim", include_excepted=True, limit=5000) if f.get("exception")}
    orphans = [o for o in files["orphans"] if (o["hypervisor_id"], f"file:{o['path']}") not in excepted_refs]
    isos = [o for o in files["isos"] if (o["hypervisor_id"], f"file:{o['path']}") not in excepted_refs]

    def _sum(rows, k):
        return round(sum(float(r.get(k) or 0) for r in rows), 1)

    summary = {
        "powered_off": {"count": len(vm["powered_off"]), "vcpu": _sum(vm["powered_off"], "vcpu"),
                        "memory_gb": _sum(vm["powered_off"], "memory_gb"), "disk_gb": _sum(vm["powered_off"], "disk_gb")},
        "idle": {"count": len(vm["idle"]), "vcpu": _sum(vm["idle"], "vcpu"), "memory_gb": _sum(vm["idle"], "memory_gb")},
        "oversized": {"count": len(vm["oversized"]),
                      "vcpu_reclaimable": sum(max(0, r["vcpu"] - (r["rightsize"]["vcpu"] or r["vcpu"]))
                                              for r in vm["oversized"]),
                      "memory_reclaimable_gb": round(sum(max(0.0, r["memory_gb"] - (r["rightsize"]["memory_gb"] or r["memory_gb"]))
                                                         for r in vm["oversized"]), 1)},
        "snapshots": {"count": len(snap_findings),
                      "space_gb": round(sum(float((f.get("evidence") or {}).get("space_gb") or 0) for f in snap_findings), 1)},
        "orphans": {"count": len(orphans), "size_gb": _sum(orphans, "size_gb")},
        "isos": {"count": len(isos), "size_gb": _sum(isos, "size_gb")},
        "unused_datastores": {"count": len(unused_ds), "capacity_gb": _sum(unused_ds, "capacity_gb")},
    }
    summary["storage_total_gb"] = round(summary["powered_off"]["disk_gb"] + summary["snapshots"]["space_gb"]
                                        + summary["orphans"]["size_gb"] + summary["isos"]["size_gb"], 1)
    return {
        "ok": True,
        "summary": summary,
        **vm,
        "snapshots": snap_findings,
        "orphans": orphans[:500],
        "isos": isos[:500],
        "unused_datastores": unused_ds,
        "file_scan": {str(k): v for k, v in files["last_scan"].items()},
        "criteria": {
            "idle": f"7 gün ort. CPU < %{IDLE_CPU_PCT:.0f} ve (vCPU ≥ 2 veya Memory ≥ 4 GB)",
            "oversized": f"vCPU ≥ {OVERSIZED_MIN_VCPU} ve 7 gün ort. CPU < %{OVERSIZED_CPU_PCT:.0f}",
            "snapshot": f"> {SNAPSHOT_WARN_DAYS} gün (yüksek: > {SNAPSHOT_HIGH_DAYS} gün)",
            "orphan": "Hiçbir VM/şablonun dosya listesinde yok; son 7 günde değişenler yalnız 'aday'",
        },
        "notes": [BACKUP_NOTE,
                  "Paylaşımlı datastore başka bir vCenter'a kayıtlı VM'ler tarafından kullanılıyorsa sahipsiz "
                  "görünebilir; silmeden önce doğrulayın."],
    }


def reclaim_rollup_by_cluster(db: Session, hv_ids: List[int]) -> Dict[Tuple[int, str], Dict[str, Any]]:
    hvs = [h for h in vd.virt_hypervisors(db) if h.id in set(hv_ids)]
    vm = _vm_rows(db, hvs)
    snaps = snapshot_space(db, hv_ids)
    cl_of = {(v["hypervisor_id"], v["name"]): v.get("cluster") for v in vd.vm_allocations(db, hv_ids)}
    out: Dict[Tuple[int, str], Dict[str, float]] = defaultdict(lambda: {
        "powered_off_memory_gb": 0.0, "idle_memory_gb": 0.0, "oversized_memory_gb": 0.0, "snapshot_gb": 0.0,
        "powered_off_count": 0, "idle_count": 0, "oversized_count": 0})
    for r in vm["powered_off"]:
        k = (r["hypervisor_id"], r.get("cluster") or "")
        out[k]["powered_off_memory_gb"] += r["memory_gb"] or 0
        out[k]["powered_off_count"] += 1
    for r in vm["idle"]:
        k = (r["hypervisor_id"], r.get("cluster") or "")
        out[k]["idle_memory_gb"] += max(0.0, (r["memory_gb"] or 0) - (r["rightsize"]["memory_gb"] or r["memory_gb"] or 0))
        out[k]["idle_count"] += 1
    for r in vm["oversized"]:
        k = (r["hypervisor_id"], r.get("cluster") or "")
        out[k]["oversized_memory_gb"] += max(0.0, (r["memory_gb"] or 0) - (r["rightsize"]["memory_gb"] or r["memory_gb"] or 0))
        out[k]["oversized_count"] += 1
    for (hid, name), s in snaps.items():
        k = (hid, cl_of.get((hid, name)) or "")
        out[k]["snapshot_gb"] += float(s.get("space_gb") or 0)
    return {k: {kk: round(vv, 1) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in out.items()}


def _parse_dt(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def reclaim_findings(platform: str, collected: Dict[str, Any], vm_cluster: Dict[str, str]) -> List[Any]:
    """Toplayıcı çıktısından snapshot + dosya bulguları."""
    from app.services.findings.store import FindingDraft
    now = datetime.now(timezone.utc)
    out: List[FindingDraft] = []
    if platform in ("vmware", "olvm"):
        for vm in collected.get("vms") or []:
            snaps = vm.get("snapshots") or []
            if not snaps:
                continue
            ages = [(now - d).days for d in (_parse_dt(s.get("created")) for s in snaps) if d]
            oldest = max(ages) if ages else None
            fail = oldest is not None and oldest > SNAPSHOT_WARN_DAYS
            out.append(FindingDraft(
                "reclaim.vm.snapshot_age", "vm", f"vm:{vm['ref']}", vm["name"], "fail" if fail else "pass",
                evidence={"snapshots": snaps[:20], "count": len(snaps), "oldest_days": oldest},
                detail=f"{len(snaps)} snapshot, en eskisi {oldest} gün" if oldest is not None else f"{len(snaps)} snapshot",
                cluster_name=vm_cluster.get(vm["name"]),
                severity="high" if oldest is not None and oldest > SNAPSHOT_HIGH_DAYS else None,
            ))
    files = collected.get("files")
    if files is not None:
        for f in files:
            extra = f.get("extra") or {}
            if f.get("attached") or extra.get("content_library") or extra.get("golden_image"):
                continue
            ref = f"file:{f['path']}"
            if f["kind"] == "iso":
                out.append(FindingDraft(
                    "reclaim.file.unused_iso", "file", ref, f.get("name") or f["path"], "fail",
                    evidence={"datastore": f.get("datastore"), "size_gb": f.get("size_gb"), "path": f["path"]},
                    detail=f"{f.get('size_gb')} GB · {f.get('datastore')}",
                ))
                continue
            size = float(f.get("size_gb") or 0)
            sev = "high" if size >= 500 else ("medium" if size >= 50 else "low")
            notes = []
            if extra.get("recent"):
                sev, notes = "low", notes + ["son 7 günde değişmiş — yalnız aday"]
            if extra.get("replica_suspect"):
                sev, notes = "low", notes + ["replica/yedek klasörü olabilir"]
            if extra.get("delta"):
                notes.append("snapshot delta dosyası (artık zincir)")
            out.append(FindingDraft(
                "reclaim.file.orphan_disk", "file", ref, f.get("name") or f["path"], "fail",
                evidence={"datastore": f.get("datastore"), "size_gb": f.get("size_gb"), "path": f["path"],
                          "kind": f["kind"], **{k: v for k, v in extra.items() if k != "owners"}},
                detail=" · ".join([f"{size:.1f} GB", str(f.get("datastore") or "")] + notes),
                severity=sev,
            ))
    return out
