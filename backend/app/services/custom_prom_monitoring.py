"""
Other / custom Prometheus — generic metric explorer (binding=none).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.services.monitoring_sources import (
    load_sources_from_db,
    load_sources_runtime,
    resolve,
    list_custom,
    prom_base_url,
    prom_headers,
    prom_verify,
    is_prom_compatible,
    source_label_matchers,
    apply_source_matchers,
    MonitoringSource,
)

logger = logging.getLogger(__name__)

_SAFE_METRIC = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
MAX_SERIES = 8


def _resolve_custom(db=None, source_id: Optional[str] = None) -> Optional[MonitoringSource]:
    sources = load_sources_from_db(db) if db is not None else load_sources_runtime()
    if source_id:
        src = resolve(sources, source_id=source_id)
        if src and src.binding == "none":
            return src
        return None
    customs = list_custom(sources)
    return customs[0] if customs else None


def _custom_source(db=None, source_id: Optional[str] = None) -> Optional[MonitoringSource]:
    """Yalnız Prom uyumlu Other kaynağı."""
    src = _resolve_custom(db, source_id)
    if src and is_prom_compatible(src):
        return src
    return None


def _reject_non_prom(src: MonitoringSource) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": (
            f"Kaynak {src.label!r} ({src.collector_type}) PromQL gezgini ile açılamaz. "
            "prometheus / telegraf (Prom endpoint) / opentelemetry (Prom endpoint) kullanın; "
            "Zabbix metrik adaptörü için Monitoring hub → Zabbix kaynağı veya zabbix_query kullanın."
        ),
        "source": src.public_dict(),
        "source_kind": "custom_prometheus",
    }


def list_sources(db=None) -> List[Dict[str, Any]]:
    sources = load_sources_from_db(db) if db is not None else load_sources_runtime()
    return [s.public_dict() for s in list_custom(sources)]


def search_metrics(
    q: str = "",
    *,
    source_id: Optional[str] = None,
    db=None,
    limit: int = 200,
) -> Dict[str, Any]:
    raw = _resolve_custom(db, source_id)
    if not raw:
        return {"ok": False, "names": [], "error": "Other kaynağı yok"}
    if not is_prom_compatible(raw):
        out = _reject_non_prom(raw)
        out["names"] = []
        return out
    src = raw
    base = prom_base_url(src)
    headers = prom_headers(src)
    matchers = source_label_matchers(src)
    try:
        with httpx.Client(timeout=15.0, verify=prom_verify(src)) as client:
            if matchers:
                # Job/extra scoped metric names
                resp = client.get(
                    f"{base}/api/v1/series",
                    params={"match[]": f"{{{matchers}}}"},
                    headers=headers,
                )
                resp.raise_for_status()
                series_rows = resp.json().get("data") or []
                names_set = set()
                for row in series_rows:
                    n = (row or {}).get("__name__")
                    if n:
                        names_set.add(str(n))
                names = sorted(names_set)
            else:
                resp = client.get(f"{base}/api/v1/label/__name__/values", headers=headers)
                resp.raise_for_status()
                names = [str(n) for n in (resp.json().get("data") or [])]
        needle = (q or "").strip().lower()
        if needle:
            names = [n for n in names if needle in n.lower()]
        return {"ok": True, "names": names[:limit], "source": src.public_dict()}
    except Exception as e:
        return {"ok": False, "names": [], "error": str(e)}


def label_values(
    label_name: str,
    *,
    source_id: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    src = _custom_source(db, source_id)
    if not src:
        return {"ok": False, "values": [], "error": "Other Prometheus kaynağı yok"}
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", label_name or ""):
        return {"ok": False, "values": [], "error": "Geçersiz label adı"}
    base = prom_base_url(src)
    headers = prom_headers(src)
    try:
        with httpx.Client(timeout=12.0, verify=prom_verify(src)) as client:
            resp = client.get(f"{base}/api/v1/label/{label_name}/values", headers=headers)
            resp.raise_for_status()
            return {"ok": True, "values": resp.json().get("data") or [], "source": src.public_dict()}
    except Exception as e:
        return {"ok": False, "values": [], "error": str(e)}


def series(
    metric: str,
    *,
    range_sec: int = 900,
    step: int = 30,
    source_id: Optional[str] = None,
    db=None,
    top_n: int = MAX_SERIES,
) -> Dict[str, Any]:
    src = _custom_source(db, source_id)
    if not src:
        return {"ok": False, "series": [], "error": "Other Prometheus kaynağı yok"}
    metric = (metric or "").strip()
    if not _SAFE_METRIC.match(metric):
        return {"ok": False, "series": [], "error": "Geçersiz metrik adı (yalnızca güvenli isimler)"}
    query = apply_source_matchers(metric, src)
    end = time.time()
    start = end - max(60, range_sec)
    base = prom_base_url(src)
    headers = prom_headers(src)
    try:
        with httpx.Client(timeout=20.0, verify=prom_verify(src)) as client:
            resp = client.get(
                f"{base}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        results = (data.get("data") or {}).get("result") or []
        scored = []
        for r in results:
            vals = r.get("values") or []
            last = float(vals[-1][1]) if vals else 0.0
            scored.append((abs(last), r))
        scored.sort(key=lambda x: -x[0])
        out = []
        for _, r in scored[: max(1, min(top_n, MAX_SERIES))]:
            m = r.get("metric") or {}
            name = m.get("instance") or m.get("job") or metric
            # compact label dump
            extra = [f"{k}={v}" for k, v in m.items() if k not in ("__name__",) and k not in ("instance", "job")]
            if extra:
                name = f"{name} {{{','.join(extra[:3])}}}"
            out.append({
                "name": str(name)[:80],
                "labels": m,
                "points": [{"t": int(float(ts)), "v": float(v)} for ts, v in (r.get("values") or [])],
            })
        return {
            "ok": True,
            "metric": metric,
            "query": query,
            "series": out,
            "source": src.public_dict(),
            "source_kind": "custom_prometheus",
        }
    except Exception as e:
        return {"ok": False, "series": [], "error": str(e)}


def instant_query(
    query: str,
    *,
    source_id: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Chat için kısıtlı instant query — yalnızca güvenli metrik adı veya basit selectors."""
    src = _custom_source(db, source_id)
    if not src:
        return {"ok": False, "error": "Other Prometheus kaynağı yok", "source_kind": "custom_prometheus"}
    q = (query or "").strip()
    if not q or len(q) > 500:
        return {"ok": False, "error": "Geçersiz sorgu", "source_kind": "custom_prometheus"}
    q = apply_source_matchers(q, src)
    base = prom_base_url(src)
    headers = prom_headers(src)
    try:
        with httpx.Client(timeout=12.0, verify=prom_verify(src)) as client:
            resp = client.get(f"{base}/api/v1/query", params={"query": q}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = (data.get("data") or {}).get("result") or []
        rows = []
        for r in results[:50]:
            m = r.get("metric") or {}
            val = r.get("value")
            rows.append({
                "metric": m,
                "value": float(val[1]) if val and len(val) >= 2 else None,
            })
        return {
            "ok": True,
            "rows": rows,
            "query": q,
            "source": src.public_dict(),
            "source_kind": f"custom:{src.label}",
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "source_kind": "custom_prometheus"}


def run_custom_prom_query(
    *,
    mode: str = "search",
    source_id: Optional[str] = None,
    metric: Optional[str] = None,
    query: Optional[str] = None,
    q: Optional[str] = None,
    range_sec: int = 900,
) -> Dict[str, Any]:
    if mode == "list_sources":
        return {"ok": True, "sources": list_sources(), "source_kind": "custom_prometheus"}
    if mode == "search":
        return search_metrics(q or metric or "", source_id=source_id)
    if mode == "series" and metric:
        return series(metric, range_sec=range_sec, source_id=source_id)
    if mode in ("query", "instant") and (query or metric):
        return instant_query(query or metric or "", source_id=source_id)
    return {"ok": False, "error": "mode/search|series|query|list_sources", "source_kind": "custom_prometheus"}
