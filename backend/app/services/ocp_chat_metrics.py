"""OpenShift Monitoring → sohbet tool / çapraz sorgu (Timescale `ocp_resource_metrics`).

Virt'teki `db_metric_trend` + `query_series` eşleniği. Prometheus / kubevirt_vmi_* yok.
Kimlik: (cluster_id, kind, object_key).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster
from app.services.openshift.ocp_monitoring import (
    MAX_SERIES_OBJECTS,
    _METRICS,
    _metric_column,
    build_overview,
    ensure_fresh_sample,
    list_objects,
    metric_catalog,
    object_ref,
    parse_names,
    parse_range,
    query_series,
)

logger = logging.getLogger(__name__)

_VALID_KINDS = frozenset({"node", "pod", "vm"})
_VALID_MODES = frozenset({"overview", "top", "series", "trend", "cross", "catalog"})


def _resolve_cluster(db: Session, cluster: Optional[str] = None) -> Optional[OpenShiftCluster]:
    q = db.query(OpenShiftCluster)
    name = (cluster or "").strip().lower()
    if name:
        for c in q.all():
            if c.name and c.name.lower() == name:
                return c
            if c.api_url and name in (c.api_url or "").lower():
                return c
    return q.first()


def _canon_kind(raw: Optional[str]) -> str:
    k = (raw or "node").strip().lower()
    if k in ("nodes", "worker", "master", "esxi"):
        return "node"
    if k in ("pods", "workload", "deployment"):
        return "pod"
    if k in ("vms", "kubevirt", "virtualmachine", "virtualmachines"):
        return "vm"
    return k if k in _VALID_KINDS else "node"


def _canon_metric(kind: str, raw: Optional[str]) -> str:
    mid = (raw or "").strip().lower().replace(" ", "_")
    aliases = {
        "cpu": "cpu_pct",
        "cpu_percent": "cpu_pct",
        "cpu_%": "cpu_pct",
        "memory": "memory_pct",
        "mem": "memory_pct",
        "mem_pct": "memory_pct",
        "memory_percent": "memory_pct",
        "ram": "memory_pct",
        "bellek": "memory_pct",
        "cores": "cpu_used_cores",
        "cpu_cores": "cpu_used_cores",
        "memory_gb": "memory_used_gb",
        "mem_gb": "memory_used_gb",
        "ram_gb": "memory_used_gb",
        "restart": "restarts",
    }
    mid = aliases.get(mid, mid)
    catalog = _METRICS.get(kind) or {}
    if mid in catalog:
        return mid
    # kind için varsayılan
    if "cpu_pct" in catalog:
        return "cpu_pct"
    if "cpu_used_cores" in catalog:
        return "cpu_used_cores"
    return next(iter(catalog), "cpu_pct")


def query_top(
    db: Session,
    *,
    cluster_id: int,
    kind: str = "node",
    metric: str = "cpu_pct",
    top_n: int = 10,
    order: str = "highest",
    namespace: Optional[str] = None,
    name_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Son örneklerden Top-N (anlık filo)."""
    kind = _canon_kind(kind)
    metric = _canon_metric(kind, metric)
    column, unit = _metric_column(kind, metric)
    limit = max(1, min(int(top_n or 10), 50))
    desc = (order or "highest").strip().lower() not in ("lowest", "asc", "improving")
    direction = "DESC" if desc else "ASC"

    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        return {"ok": False, "error": "Cluster bulunamadı"}
    ensure_fresh_sample(db, cluster)

    params: Dict[str, Any] = {"cid": cluster_id, "kind": kind, "lim": limit}
    extra = ""
    if namespace:
        params["ns"] = namespace.strip()
        extra += " AND namespace = :ns"
    if name_filter:
        params["nf"] = f"%{name_filter.strip()}%"
        extra += " AND (name ILIKE :nf OR object_key ILIKE :nf OR coalesce(namespace,'') ILIKE :nf)"

    rows = db.execute(
        text(
            f"""
            SELECT * FROM (
              SELECT DISTINCT ON (object_key)
                     object_key, name, namespace, role, status, node_name,
                     cpu_pct, memory_pct, cpu_used_cores, memory_used_gb, restarts, timestamp
              FROM ocp_resource_metrics
              WHERE cluster_id = :cid AND kind = :kind
                AND timestamp >= now() - interval '45 minutes'
                {extra}
              ORDER BY object_key, timestamp DESC
            ) latest
            WHERE {column} IS NOT NULL
            ORDER BY {column} {direction}
            LIMIT :lim
            """
        ),
        params,
    ).mappings().all()

    items = []
    for r in rows:
        display = f"{r['namespace']}/{r['name']}" if r.get("namespace") else r["name"]
        items.append({
            "name": display,
            "object_key": r["object_key"],
            "ref": object_ref(cluster_id, kind, r["name"], r.get("namespace")),
            "value": float(r[column]) if r.get(column) is not None else None,
            "unit": unit,
            "metric": metric,
            "role": r.get("role"),
            "status": r.get("status"),
            "node_name": r.get("node_name"),
            "as_of": r["timestamp"].isoformat() if r.get("timestamp") else None,
        })
    return {
        "ok": True,
        "mode": "top",
        "cluster": {"id": cluster.id, "name": cluster.name},
        "kind": kind,
        "metric": metric,
        "unit": unit,
        "order": "highest" if desc else "lowest",
        "items": items,
        "source": "ocp_resource_metrics",
        "note": "Anlık son örnek (metrics.k8s.io → Timescale). Disk/net/migration yok.",
    }


def query_trend(
    db: Session,
    *,
    cluster_id: int,
    kind: str = "node",
    metric: str = "cpu_pct",
    days: float = 7,
    top_n: int = 10,
    order: str = "worsening",
    namespace: Optional[str] = None,
    name_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Pencere içi avg/last/delta — filo trend (Virt db_metric_trend sade eşleniği)."""
    kind = _canon_kind(kind)
    metric = _canon_metric(kind, metric)
    column, unit = _metric_column(kind, metric)
    limit = max(1, min(int(top_n or 10), 50))
    window_days = max(0.05, min(float(days or 7), 30.0))
    order_key = (order or "worsening").strip().lower()

    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        return {"ok": False, "error": "Cluster bulunamadı"}

    params: Dict[str, Any] = {"cid": cluster_id, "kind": kind, "days": window_days, "lim": limit}
    extra = ""
    if namespace:
        params["ns"] = namespace.strip()
        extra += " AND namespace = :ns"
    if name_filter:
        params["nf"] = f"%{name_filter.strip()}%"
        extra += " AND (name ILIKE :nf OR object_key ILIKE :nf)"

    # delta = last - first (zaman sırasına göre)
    if order_key in ("highest", "last"):
        order_sql = "last_v DESC NULLS LAST"
    elif order_key in ("lowest",):
        order_sql = "last_v ASC NULLS LAST"
    elif order_key in ("improving",):
        order_sql = "delta ASC NULLS LAST"
    else:
        order_sql = "delta DESC NULLS LAST"

    rows = db.execute(
        text(
            f"""
            WITH win AS (
              SELECT object_key, name, namespace, node_name, timestamp, {column} AS v
              FROM ocp_resource_metrics
              WHERE cluster_id = :cid AND kind = :kind
                AND timestamp >= now() - (:days * interval '1 day')
                AND {column} IS NOT NULL
                {extra}
            ),
            agg AS (
              SELECT object_key,
                     max(name) AS name,
                     max(namespace) AS namespace,
                     max(node_name) AS node_name,
                     avg(v) AS avg_v,
                     max(v) AS max_v,
                     min(v) AS min_v,
                     (array_agg(v ORDER BY timestamp ASC))[1] AS first_v,
                     (array_agg(v ORDER BY timestamp DESC))[1] AS last_v,
                     count(*) AS samples
              FROM win
              GROUP BY object_key
            )
            SELECT *, (last_v - first_v) AS delta
            FROM agg
            WHERE samples >= 2
            ORDER BY {order_sql}
            LIMIT :lim
            """
        ),
        params,
    ).mappings().all()

    items = []
    for r in rows:
        display = f"{r['namespace']}/{r['name']}" if r.get("namespace") else r["name"]
        delta = float(r["delta"]) if r.get("delta") is not None else None
        direction = None
        if delta is not None:
            if delta > 0.5:
                direction = "artıyor"
            elif delta < -0.5:
                direction = "azalıyor"
            else:
                direction = "kararlı"
        items.append({
            "name": display,
            "object_key": r["object_key"],
            "ref": object_ref(cluster_id, kind, r["name"], r.get("namespace")),
            "avg": round(float(r["avg_v"]), 2) if r.get("avg_v") is not None else None,
            "last": round(float(r["last_v"]), 2) if r.get("last_v") is not None else None,
            "max": round(float(r["max_v"]), 2) if r.get("max_v") is not None else None,
            "min": round(float(r["min_v"]), 2) if r.get("min_v") is not None else None,
            "delta": round(delta, 2) if delta is not None else None,
            "direction": direction,
            "samples": int(r["samples"] or 0),
            "node_name": r.get("node_name"),
            "unit": unit,
        })
    return {
        "ok": True,
        "mode": "trend",
        "cluster": {"id": cluster.id, "name": cluster.name},
        "kind": kind,
        "metric": metric,
        "unit": unit,
        "days": window_days,
        "order": order_key,
        "items": items,
        "source": "ocp_resource_metrics",
        "retention_days": 30,
        "note": (
            "Örnek ~60 sn; deploy öncesi geçmiş yok. "
            "Disk/net/migration ve kubevirt_vmi_* bu SoT'ta yok."
        ),
    }


def query_cross(
    db: Session,
    *,
    cluster_id: int,
    metric: str = "cpu_pct",
    top_n: int = 5,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """Yüksek yüklü node'lar ⋈ o node'daki pod/VM (çapraz)."""
    node_metric = _canon_metric("node", metric)
    limit = max(1, min(int(top_n or 5), 15))
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        return {"ok": False, "error": "Cluster bulunamadı"}
    ensure_fresh_sample(db, cluster)

    top_nodes = query_top(
        db, cluster_id=cluster_id, kind="node", metric=node_metric, top_n=limit, order="highest",
    )
    rows = []
    for n in top_nodes.get("items") or []:
        node_name = (n.get("name") or "").split("/")[-1]
        pod_on_node = []
        try:
            column, _u = _metric_column("pod", "cpu_used_cores")
            params = {"cid": cluster_id, "nn": node_name, "lim": 8}
            extra_ns = ""
            if namespace:
                params["ns"] = namespace.strip()
                extra_ns = " AND namespace = :ns"
            prow = db.execute(
                text(
                    f"""
                    SELECT * FROM (
                      SELECT DISTINCT ON (object_key)
                             object_key, name, namespace, node_name,
                             cpu_used_cores, memory_used_gb, cpu_pct, memory_pct, restarts, timestamp
                      FROM ocp_resource_metrics
                      WHERE cluster_id = :cid AND kind = 'pod'
                        AND node_name = :nn
                        AND timestamp >= now() - interval '45 minutes'
                        {extra_ns}
                      ORDER BY object_key, timestamp DESC
                    ) t
                    WHERE {column} IS NOT NULL
                    ORDER BY {column} DESC
                    LIMIT :lim
                    """
                ),
                params,
            ).mappings().all()
            for p in prow:
                pod_on_node.append({
                    "name": f"{p['namespace']}/{p['name']}",
                    "ref": object_ref(cluster_id, "pod", p["name"], p.get("namespace")),
                    "cpu_used_cores": float(p["cpu_used_cores"]) if p.get("cpu_used_cores") is not None else None,
                    "memory_used_gb": float(p["memory_used_gb"]) if p.get("memory_used_gb") is not None else None,
                })
        except Exception as exc:
            logger.warning("ocp cross pods: %s", exc)

        vms_on = []
        try:
            params = {"cid": cluster_id, "nn": node_name, "lim": 5}
            vrow = db.execute(
                text(
                    """
                    SELECT * FROM (
                      SELECT DISTINCT ON (object_key)
                             object_key, name, namespace, node_name,
                             cpu_used_cores, memory_used_gb, timestamp
                      FROM ocp_resource_metrics
                      WHERE cluster_id = :cid AND kind = 'vm'
                        AND node_name = :nn
                        AND timestamp >= now() - interval '45 minutes'
                      ORDER BY object_key, timestamp DESC
                    ) t
                    ORDER BY cpu_used_cores DESC NULLS LAST
                    LIMIT :lim
                    """
                ),
                params,
            ).mappings().all()
            for v in vrow:
                vms_on.append({
                    "name": f"{v['namespace']}/{v['name']}",
                    "ref": object_ref(cluster_id, "vm", v["name"], v.get("namespace")),
                    "cpu_used_cores": float(v["cpu_used_cores"]) if v.get("cpu_used_cores") is not None else None,
                    "memory_used_gb": float(v["memory_used_gb"]) if v.get("memory_used_gb") is not None else None,
                })
        except Exception as exc:
            logger.warning("ocp cross vms: %s", exc)

        rows.append({
            "node": n,
            "pods": pod_on_node,
            "vms": vms_on,
        })

    return {
        "ok": True,
        "mode": "cross",
        "cluster": {"id": cluster.id, "name": cluster.name},
        "metric": node_metric,
        "rows": rows,
        "source": "ocp_resource_metrics",
        "note": "Node yükü + aynı node'daki pod/VM (anlık). Join anahtarı: node_name.",
    }


def run_ocp_monitoring_query(
    db: Session,
    *,
    mode: str = "overview",
    kind: str = "node",
    metric: Optional[str] = None,
    names: Optional[Sequence[str]] = None,
    name_filter: Optional[str] = None,
    cluster: Optional[str] = None,
    range_key: Optional[str] = None,
    lookback_hours: Optional[float] = None,
    days: Optional[float] = None,
    top_n: int = 10,
    order: Optional[str] = None,
    namespace: Optional[str] = None,
    list_catalog: bool = False,
) -> Dict[str, Any]:
    """Sohbet tool giriş noktası."""
    if list_catalog or (mode or "").strip().lower() == "catalog":
        k = _canon_kind(kind)
        return {
            "ok": True,
            "mode": "catalog",
            "kind": k,
            "metrics": metric_catalog(k),
            "note": "Yalnız CPU/Memory (+ pod restarts). Disk/net/migration yok.",
        }

    cl = _resolve_cluster(db, cluster)
    if not cl:
        return {"ok": False, "error": "OpenShift cluster kaydı yok — Integrations → OpenShift"}

    m = (mode or "overview").strip().lower()
    if m not in _VALID_MODES:
        m = "overview"
    k = _canon_kind(kind)

    if m == "overview":
        out = build_overview(db, int(cl.id))
        out["mode"] = "overview"
        return out

    if m == "top":
        return query_top(
            db,
            cluster_id=int(cl.id),
            kind=k,
            metric=metric or "cpu_pct",
            top_n=top_n,
            order=order or "highest",
            namespace=namespace,
            name_filter=name_filter,
        )

    if m == "trend":
        d = days
        if d is None and lookback_hours is not None:
            d = float(lookback_hours) / 24.0
        return query_trend(
            db,
            cluster_id=int(cl.id),
            kind=k,
            metric=metric or "cpu_pct",
            days=d if d is not None else 7,
            top_n=top_n,
            order=order or "worsening",
            namespace=namespace,
            name_filter=name_filter or (names[0] if names else None),
        )

    if m == "cross":
        return query_cross(
            db,
            cluster_id=int(cl.id),
            metric=metric or "cpu_pct",
            top_n=top_n,
            namespace=namespace,
        )

    # series
    name_list = parse_names(None, names)
    if not name_list and name_filter:
        inv = list_objects(db, cluster_id=int(cl.id), kind=k, q=name_filter, limit=MAX_SERIES_OBJECTS)
        name_list = [it["id"] for it in (inv.get("items") or [])][:MAX_SERIES_OBJECTS]
    if not name_list:
        return {
            "ok": False,
            "error": "series için names gerekli (ör. worker-1 veya ns/pod-adı)",
            "hint": "Filo Top-N için mode=top; trend için mode=trend; özet için mode=overview",
        }

    rk = range_key
    if not rk and lookback_hours is not None:
        h = float(lookback_hours)
        if h <= 0.25:
            rk = "15m"
        elif h <= 0.5:
            rk = "30m"
        elif h <= 1:
            rk = "1h"
        elif h <= 2:
            rk = "2h"
        elif h <= 8:
            rk = "8h"
        elif h <= 24:
            rk = "24h"
        elif h <= 168:
            rk = "7d"
        else:
            rk = "30d"
    rk = parse_range(rk or "8h")
    mid = _canon_metric(k, metric)
    out = query_series(
        db,
        cluster_id=int(cl.id),
        kind=k,
        names=name_list,
        metric=mid,
        range_key=rk,
    )
    out["mode"] = "series"
    out["cluster"] = {"id": cl.id, "name": cl.name}
    # LLM için özet istatistik (ham points kısalt)
    slim = []
    for s in out.get("series") or []:
        pts = s.get("points") or []
        vals = [p["v"] for p in pts if p.get("v") is not None]
        slim.append({
            "name": s.get("name"),
            "ref": s.get("ref"),
            "points": len(pts),
            "avg": round(sum(vals) / len(vals), 2) if vals else None,
            "last": vals[-1] if vals else None,
            "min": round(min(vals), 2) if vals else None,
            "max": round(max(vals), 2) if vals else None,
            # Grafik UI sohbet meta.charts ile gelir; tool'da son 24 nokta yeter
            "tail": pts[-24:] if pts else [],
        })
    out["series_summary"] = slim
    # Token koruması — tam points serisini şişirme
    out.pop("series", None)
    return out
