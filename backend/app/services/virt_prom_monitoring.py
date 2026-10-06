"""
VMware / virtualization Prometheus monitoring — vmware_exporter kataloğu.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.services.monitoring_sources import (
    load_sources_from_db,
    load_sources_runtime,
    list_by_binding,
    resolve,
    prom_base_url,
    prom_headers,
    prom_verify,
    MonitoringSource,
)

logger = logging.getLogger(__name__)

VIRT_CATALOG = [
    {"id": "vm_cpu", "title": "VM CPU Usage", "unit": "%", "prefix": "vmware",
     "query": "vmware_vm_cpu_usage_average"},
    {"id": "vm_mem", "title": "VM Memory Usage", "unit": "%", "prefix": "vmware",
     "query": "vmware_vm_mem_usage_average"},
    {"id": "host_cpu", "title": "Host CPU Usage", "unit": "%", "prefix": "vmware",
     "query": "vmware_host_cpu_usage_average"},
    {"id": "host_mem", "title": "Host Memory Usage", "unit": "%", "prefix": "vmware",
     "query": "vmware_host_mem_usage_average"},
    {"id": "ds_used", "title": "Datastore Used", "unit": "bytes", "prefix": "vmware",
     "query": "vmware_datastore_disk_used_average"},
    {"id": "vm_net_rx", "title": "VM Network Rx", "unit": "KBps", "prefix": "vmware",
     "query": "vmware_vm_net_bytesRx_average"},
    {"id": "vm_net_tx", "title": "VM Network Tx", "unit": "KBps", "prefix": "vmware",
     "query": "vmware_vm_net_bytesTx_average"},
    {"id": "vm_disk_read", "title": "VM Disk Read", "unit": "KBps", "prefix": "vmware",
     "query": "vmware_vm_disk_read_average"},
    {"id": "vm_disk_write", "title": "VM Disk Write", "unit": "KBps", "prefix": "vmware",
     "query": "vmware_vm_disk_write_average"},
]


def _virt_source(db=None, source_id: Optional[str] = None) -> Optional[MonitoringSource]:
    sources = load_sources_from_db(db) if db is not None else load_sources_runtime()
    if source_id:
        return resolve(sources, source_id=source_id)
    matched = list_by_binding(sources, "virtualization")
    return matched[0] if matched else None


def _query_range(src: MonitoringSource, query: str, start: float, end: float, step: int = 30) -> Dict[str, Any]:
    base = prom_base_url(src)
    headers = prom_headers(src)
    with httpx.Client(timeout=20.0, verify=prom_verify(src)) as client:
        resp = client.get(
            f"{base}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


def catalog() -> List[Dict[str, Any]]:
    return list(VIRT_CATALOG)


def discover_metrics(db=None, source_id: Optional[str] = None, prefix: str = "vmware_") -> Dict[str, Any]:
    src = _virt_source(db, source_id)
    if not src:
        return {"ok": False, "names": [], "error": "Virtualization Prometheus yok"}
    base = prom_base_url(src)
    headers = prom_headers(src)
    try:
        with httpx.Client(timeout=15.0, verify=prom_verify(src)) as client:
            resp = client.get(f"{base}/api/v1/label/__name__/values", headers=headers)
            resp.raise_for_status()
            names = resp.json().get("data") or []
        filtered = [n for n in names if str(n).startswith(prefix)]
        return {"ok": True, "names": filtered[:500], "source": src.public_dict()}
    except Exception as e:
        return {"ok": False, "names": [], "error": str(e)}


def overview(db=None, source_id: Optional[str] = None) -> Dict[str, Any]:
    src = _virt_source(db, source_id)
    if not src:
        return {"configured": False, "source": None, "note": "Virtualization Prometheus yok"}
    discovered = discover_metrics(db, source_id)
    return {
        "configured": True,
        "source": src.public_dict(),
        "metric_count": len(discovered.get("names") or []),
        "catalog": catalog(),
        "note": "vmware_exporter Prometheus",
    }


def _series_name(metric: Dict[str, str]) -> str:
    for k in ("vmname", "vm_name", "hostname", "host_name", "name", "ds_name", "instance"):
        if metric.get(k):
            return str(metric[k])
    return "series"


def series(
    metric_id: str,
    *,
    range_sec: int = 900,
    step: int = 30,
    source_id: Optional[str] = None,
    db=None,
    top_n: int = 8,
    raw_query: Optional[str] = None,
) -> Dict[str, Any]:
    src = _virt_source(db, source_id)
    if not src:
        return {"ok": False, "series": [], "error": "Virtualization Prometheus yok"}
    cat = {c["id"]: c for c in catalog()}
    meta = cat.get(metric_id)
    query = raw_query or (meta["query"] if meta else None)
    if not query:
        return {"ok": False, "series": [], "error": f"Bilinmeyen metrik: {metric_id}"}
    end = time.time()
    start = end - max(60, range_sec)
    try:
        data = _query_range(src, query, start, end, step)
        results = (data.get("data") or {}).get("result") or []
        scored = []
        for r in results:
            vals = r.get("values") or []
            last = float(vals[-1][1]) if vals else 0.0
            scored.append((abs(last), r))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, r in scored[:top_n]:
            m = r.get("metric") or {}
            out.append({
                "name": _series_name(m),
                "labels": m,
                "points": [{"t": int(float(ts)), "v": float(v)} for ts, v in (r.get("values") or [])],
            })
        return {
            "ok": True,
            "metric": meta or {"id": metric_id, "query": query},
            "series": out,
            "source": src.public_dict(),
        }
    except Exception as e:
        return {"ok": False, "series": [], "error": str(e)}


def run_virt_prom_query(
    *,
    mode: str = "overview",
    metric_id: Optional[str] = None,
    range_sec: int = 900,
    source_id: Optional[str] = None,
    raw_query: Optional[str] = None,
) -> Dict[str, Any]:
    if mode == "catalog":
        return {"ok": True, "catalog": catalog(), "source_kind": "virt_prometheus"}
    if mode == "discover":
        out = discover_metrics(source_id=source_id)
        out["source_kind"] = "virt_prometheus"
        return out
    if mode == "series":
        out = series(metric_id or "", range_sec=range_sec, source_id=source_id, raw_query=raw_query)
        out["source_kind"] = "virt_prometheus"
        return out
    out = overview(source_id=source_id)
    out["source_kind"] = "virt_prometheus"
    return out
