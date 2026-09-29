"""OpenShift Monitoring — Virt Monitoring eşleniği.

Kaynak: kube API + metrics.k8s.io → Timescale `ocp_resource_metrics`.
Prometheus / kubevirt_vmi_* / Linux PROMETHEUS_URL yok.
Kimlik: (cluster_id, kind, object_key) — iki küme birleşmez.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.openshift import OpenShiftCluster, OcpResourceMetric
from app.services.openshift.cluster_ops import client_from_cluster
from app.services.openshift.ocp_client import OpenShiftClient

logger = logging.getLogger(__name__)

SYSTEM_NS_PREFIXES = ("openshift", "kube-", "default")
VM_NAME_LABELS = ("vm.kubevirt.io/name", "kubevirt.io/domain")
MAX_METRIC_PAGES = 40
POD_PAGE_LIMIT = 500
MAX_SERIES_OBJECTS = 8
STALE_MINUTES = 20

RANGE_SPEC: Dict[str, Dict[str, Any]] = {
    "15m": {"minutes": 15, "bucket": None},
    "30m": {"minutes": 30, "bucket": None},
    "1h": {"minutes": 60, "bucket": None},
    "2h": {"minutes": 120, "bucket": None},
    "8h": {"minutes": 480, "bucket": None},
    "24h": {"minutes": 1440, "bucket": None},
    "7d": {"minutes": 10080, "bucket": "1 hour"},
    "30d": {"minutes": 43200, "bucket": "4 hours"},
    "60d": {"minutes": 86400, "bucket": "4 hours"},
}

_METRICS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "node": {
        "cpu_pct": ("cpu_pct", "%"),
        "memory_pct": ("memory_pct", "%"),
        "cpu_used_cores": ("cpu_used_cores", "core"),
        "memory_used_gb": ("memory_used_gb", "GB"),
    },
    "pod": {
        "cpu_used_cores": ("cpu_used_cores", "core"),
        "memory_used_gb": ("memory_used_gb", "GB"),
        "cpu_pct": ("cpu_pct", "%"),
        "memory_pct": ("memory_pct", "%"),
        "restarts": ("restarts", "count"),
    },
    "vm": {
        "cpu_used_cores": ("cpu_used_cores", "core"),
        "memory_used_gb": ("memory_used_gb", "GB"),
        "cpu_pct": ("cpu_pct", "%"),
        "memory_pct": ("memory_pct", "%"),
    },
}

DEFAULT_SLOTS = {
    "node": ["cpu_pct", "memory_pct", "cpu_used_cores", "memory_used_gb"],
    "pod": ["cpu_used_cores", "memory_used_gb", "restarts", "cpu_pct"],
    "vm": ["cpu_used_cores", "memory_used_gb", "cpu_pct", "memory_pct"],
}


def object_ref(cluster_id: int, kind: str, name: str, namespace: Optional[str] = None) -> str:
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    ns = (namespace or "").strip()
    if ns:
        return f"{cluster_id}:{kind}:{ns}/{name}"
    return f"{cluster_id}:{kind}:{name}"


def parse_object_ref(raw: str) -> Tuple[Optional[int], str, str, Optional[str]]:
    """→ (cluster_id|None, kind, name, namespace|None)."""
    s = (raw or "").strip()
    if not s:
        return None, "", "", None
    parts = s.split(":", 2)
    if len(parts) == 3 and parts[0].isdigit():
        cid = int(parts[0])
        kind = parts[1].lower()
        rest = parts[2]
        if "/" in rest:
            ns, name = rest.split("/", 1)
            return cid, kind, name, ns
        return cid, kind, rest, None
    # yedek: yalnız object_key
    if "/" in s:
        ns, name = s.split("/", 1)
        return None, "", name, ns
    return None, "", s, None


def is_system_namespace(name: Optional[str]) -> bool:
    n = (name or "").strip()
    return bool(n) and n.startswith(SYSTEM_NS_PREFIXES)


def virt_launcher_vm_name(pod_name: str, labels: Optional[Dict[str, Any]] = None) -> Optional[str]:
    for key in VM_NAME_LABELS:
        val = (labels or {}).get(key)
        if val:
            return str(val).strip()
    name = (pod_name or "").strip()
    prefix = "virt-launcher-"
    if name.startswith(prefix):
        rest = name[len(prefix):]
        if "-" in rest:
            return rest.rsplit("-", 1)[0] or None
        return rest or None
    return None


def _pct(used: Optional[float], total: Optional[float]) -> Optional[float]:
    if used is None or total is None or total <= 0:
        return None
    try:
        return round(max(0.0, min(100.0, (float(used) / float(total)) * 100.0)), 1)
    except (TypeError, ValueError):
        return None


def _r(v: Any, n: int = 3) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def _merge_metric_row(prev: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Aynı (kind, object_key) çakışınca birleştir — virt-launcher çoğulları vb."""
    out = dict(prev)
    for col in ("cpu_used_cores", "memory_used_gb", "cpu_allocatable", "memory_allocatable_gb"):
        a, b = prev.get(col), new.get(col)
        if a is None and b is None:
            out[col] = None
        elif a is None:
            out[col] = b
        elif b is None:
            out[col] = a
        else:
            try:
                out[col] = round(float(a) + float(b), 4)
            except (TypeError, ValueError):
                out[col] = b
    ra, rb = prev.get("restarts"), new.get("restarts")
    if ra is None and rb is None:
        out["restarts"] = None
    else:
        out["restarts"] = int(ra or 0) + int(rb or 0)
    # Son gelen status/node bilgisi
    for col in ("status", "node_name", "role", "name", "namespace"):
        if new.get(col) not in (None, ""):
            out[col] = new.get(col)
    out["cpu_pct"] = _pct(out.get("cpu_used_cores"), out.get("cpu_allocatable"))
    out["memory_pct"] = _pct(out.get("memory_used_gb"), out.get("memory_allocatable_gb"))
    return out


def dedupe_metric_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """PK (timestamp, cluster_id, kind, object_key) çakışmasını önle — aynı örnek anında tek satır.

    Özellikle aynı VM için birden fazla virt-launcher pod'u (migration/eski+yeni)
    aynı object_key ile iki INSERT üretip UniqueViolation + boş tabloya yol açıyordu.
    """
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in rows or []:
        kind = (r.get("kind") or "").strip()
        ok = (r.get("object_key") or "").strip()
        if not kind or not ok:
            continue
        key = (kind, ok)
        if key not in by_key:
            by_key[key] = dict(r)
        else:
            by_key[key] = _merge_metric_row(by_key[key], r)
    return list(by_key.values())


def _sum_container_usage(containers: Iterable[Dict[str, Any]]) -> Tuple[float, float]:
    cpu = 0.0
    mem_gb = 0.0
    for c in containers or []:
        usage = (c or {}).get("usage") or {}
        cpu += OpenShiftClient._parse_quantity(usage.get("cpu"))
        mem_gb += OpenShiftClient._parse_quantity(usage.get("memory"))
    return cpu, mem_gb


def _list_metrics_items(client: OpenShiftClient, path: str) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    continue_token: Optional[str] = None
    saw_ok = False
    try:
        for _ in range(MAX_METRIC_PAGES):
            params: Dict[str, Any] = {"limit": str(POD_PAGE_LIMIT)}
            if continue_token:
                params["continue"] = continue_token
            r = client._get(path, params=params, timeout=20)
            if r.status_code in (404, 403):
                return None if not saw_ok else items
            if r.status_code != 200:
                return None if not saw_ok else items
            saw_ok = True
            body = r.json() or {}
            items.extend(body.get("items") or [])
            continue_token = (body.get("metadata") or {}).get("continue") or None
            if not continue_token:
                break
        return items
    except Exception as exc:
        logger.debug("OCP metrics %s error: %s", path, exc)
        return None if not saw_ok else items


def _node_usage_map(items: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    if not items:
        return out
    for item in items:
        name = ((item.get("metadata") or {}).get("name") or "").strip()
        if not name:
            continue
        usage = item.get("usage") or {}
        out[name] = {
            "cpu_cores": OpenShiftClient._parse_quantity(usage.get("cpu")),
            "memory_gb": round(OpenShiftClient._parse_quantity(usage.get("memory")), 3),
        }
    return out


def _pod_usage_map(items: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    if not items:
        return out
    for item in items:
        md = item.get("metadata") or {}
        name = (md.get("name") or "").strip()
        ns = (md.get("namespace") or "").strip()
        if not name:
            continue
        cpu, mem_gb = _sum_container_usage(item.get("containers") or [])
        out[f"{ns}/{name}"] = {
            "cpu_cores": round(cpu, 4),
            "memory_gb": round(mem_gb, 3),
        }
    return out


def parse_range(raw: Optional[str]) -> str:
    key = (raw or "8h").strip().lower()
    return key if key in RANGE_SPEC else "8h"


def metric_catalog(kind: str) -> List[Dict[str, str]]:
    k = (kind or "node").strip().lower()
    if k not in _METRICS:
        raise ValueError("kind node|pod|vm olmalı")
    return [{"id": mid, "column": col, "unit": unit} for mid, (col, unit) in _METRICS[k].items()]


def _metric_column(kind: str, metric: str) -> Tuple[str, str]:
    k = (kind or "").strip().lower()
    mid = (metric or "").strip()
    if k not in _METRICS or mid not in _METRICS[k]:
        raise ValueError(f"bilinmeyen metrik: {kind}/{metric}")
    col, unit = _METRICS[k][mid]
    if not str(col).replace("_", "").isalnum():
        raise ValueError("geçersiz kolon")
    return col, unit


def collect_live_rows(cluster: OpenShiftCluster) -> Tuple[List[Dict[str, Any]], bool]:
    """Canlı API → yazılacak satırlar + metrics_available."""
    cid = int(cluster.id)
    client = client_from_cluster(cluster)
    try:
        nodes_raw = client.list_nodes() or []
        pods_raw = client.list_pods() or []
        node_items = _list_metrics_items(client, "/apis/metrics.k8s.io/v1beta1/nodes")
        pod_items = _list_metrics_items(client, "/apis/metrics.k8s.io/v1beta1/pods")
    finally:
        try:
            client.logout()
        except Exception:
            pass

    node_usage = _node_usage_map(node_items)
    pod_usage = _pod_usage_map(pod_items)
    metrics_available = node_items is not None or pod_items is not None
    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []

    for n in nodes_raw:
        name = n.get("name") or ""
        if not name:
            continue
        usage = node_usage.get(name)
        cpu_alloc = float(n.get("cpu_allocatable") or n.get("cpu_cores") or 0) or 0.0
        mem_alloc = float(n.get("memory_allocatable_gb") or n.get("memory_gb") or 0) or 0.0
        cpu_used = usage["cpu_cores"] if usage else None
        mem_used = usage["memory_gb"] if usage else None
        rows.append({
            "timestamp": now,
            "cluster_id": cid,
            "kind": "node",
            "object_key": name,
            "name": name,
            "namespace": None,
            "role": n.get("role") or "worker",
            "status": n.get("status") or "Unknown",
            "node_name": name,
            "cpu_used_cores": _r(cpu_used),
            "memory_used_gb": _r(mem_used),
            "cpu_allocatable": _r(cpu_alloc, 2),
            "memory_allocatable_gb": _r(mem_alloc, 2),
            "cpu_pct": _pct(cpu_used, cpu_alloc),
            "memory_pct": _pct(mem_used, mem_alloc),
            "restarts": None,
        })

    for p in pods_raw:
        ns = p.get("namespace") or ""
        name = p.get("name") or ""
        if not name:
            continue
        key = f"{ns}/{name}"
        usage = pod_usage.get(key)
        cpu_used = usage["cpu_cores"] if usage else None
        mem_used = usage["memory_gb"] if usage else None
        cpu_req = p.get("cpu_request")
        mem_req = p.get("memory_request_gb")
        labels = p.get("labels") or {}
        phase = (p.get("phase") or p.get("status") or "").strip()
        base = {
            "timestamp": now,
            "cluster_id": cid,
            "namespace": ns,
            "status": p.get("status") or phase or "Unknown",
            "node_name": p.get("node_name") or "",
            "cpu_used_cores": _r(cpu_used, 4),
            "memory_used_gb": _r(mem_used),
            "cpu_allocatable": _r(cpu_req, 3),
            "memory_allocatable_gb": _r(mem_req, 3),
            "cpu_pct": _pct(cpu_used, float(cpu_req) if cpu_req else None),
            "memory_pct": _pct(mem_used, float(mem_req) if mem_req else None),
            "restarts": int(p.get("restart_count") or 0),
            "role": None,
        }
        if not is_system_namespace(ns):
            rows.append({
                **base,
                "kind": "pod",
                "object_key": key,
                "name": name,
            })
        vm_name = virt_launcher_vm_name(name, labels)
        if vm_name:
            rows.append({
                **base,
                "kind": "vm",
                "object_key": f"{ns}/{vm_name}",
                "name": vm_name,
            })

    return dedupe_metric_rows(rows), metrics_available


def sync_cluster_metrics(db: Session, cluster: OpenShiftCluster) -> Dict[str, Any]:
    rows, metrics_available = collect_live_rows(cluster)
    n = 0
    try:
        for r in rows:
            db.add(OcpResourceMetric(**r))
            n += 1
        if n:
            db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    return {
        "cluster_id": cluster.id,
        "rows": n,
        "metrics_available": metrics_available,
    }


def sync_all_ocp_monitoring_metrics(db: Session) -> Dict[str, Any]:
    clusters = db.query(OpenShiftCluster).order_by(OpenShiftCluster.name).all()
    total = 0
    details = []
    for c in clusters:
        try:
            r = sync_cluster_metrics(db, c)
            total += int(r.get("rows") or 0)
            details.append(r)
        except Exception as exc:
            logger.warning("OCP monitoring sync cluster=%s: %s", c.name, exc)
            try:
                db.rollback()
            except Exception:
                pass
            details.append({"cluster_id": c.id, "error": str(exc)[:200]})
    return {"clusters": len(clusters), "rows": total, "details": details}


def ensure_fresh_sample(db: Session, cluster: OpenShiftCluster, max_age_sec: int = 90) -> bool:
    """Son örnek bayatsa canlı sync. True = sync yapıldı."""
    row = db.execute(
        text(
            """
            SELECT max(timestamp) AS ts FROM ocp_resource_metrics
            WHERE cluster_id = :cid
            """
        ),
        {"cid": cluster.id},
    ).mappings().first()
    ts = row["ts"] if row else None
    if ts is not None:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age <= max_age_sec:
            return False
    try:
        sync_cluster_metrics(db, cluster)
        return True
    except Exception as exc:
        logger.warning("OCP ensure_fresh_sample: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _top_sql(db: Session, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(r) for r in db.execute(text(sql), params).mappings().all()]


def build_overview(db: Session, cluster_id: int) -> Dict[str, Any]:
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise ValueError("Cluster bulunamadı")
    ensure_fresh_sample(db, cluster)

    latest = _top_sql(
        db,
        """
        SELECT DISTINCT ON (kind, object_key)
               kind, object_key, name, namespace, role, status, node_name,
               cpu_pct, memory_pct, cpu_used_cores, memory_used_gb,
               cpu_allocatable, memory_allocatable_gb, restarts, timestamp
        FROM ocp_resource_metrics
        WHERE cluster_id = :cid
          AND timestamp >= now() - interval '45 minutes'
        ORDER BY kind, object_key, timestamp DESC
        """,
        {"cid": cluster_id},
    )

    nodes = [r for r in latest if r["kind"] == "node"]
    pods = [r for r in latest if r["kind"] == "pod"]
    vms = [r for r in latest if r["kind"] == "vm"]

    ready = sum(1 for n in nodes if (n.get("status") or "").lower() == "ready")
    not_ready = len(nodes) - ready
    masters = [n for n in nodes if (n.get("role") or "") == "master"]
    workers = [n for n in nodes if (n.get("role") or "") in ("worker", "infra", "")]

    def _grade_node(n: Dict[str, Any]) -> str:
        if (n.get("status") or "").lower() != "ready":
            return "critical"
        cpu = n.get("cpu_pct")
        mem = n.get("memory_pct")
        if (cpu is not None and cpu >= 90) or (mem is not None and mem >= 92):
            return "critical"
        if (cpu is not None and cpu >= 75) or (mem is not None and mem >= 80):
            return "warning"
        if cpu is None and mem is None:
            return "unknown"
        return "healthy"

    grades = [g for g in (_grade_node(n) for n in nodes)]
    host_counts = {
        "healthy": grades.count("healthy"),
        "warning": grades.count("warning"),
        "critical": grades.count("critical"),
        "unknown": grades.count("unknown"),
    }
    if host_counts["critical"]:
        grade, label = "critical", "Kritik"
    elif host_counts["warning"]:
        grade, label = "warning", "Uyarı"
    elif host_counts["healthy"]:
        grade, label = "healthy", "Sağlıklı"
    else:
        grade, label = "unknown", "Bilinmeyen"

    avail = round(100.0 * ready / len(nodes), 1) if nodes else None

    def _avg(rows: List[Dict], key: str) -> Optional[float]:
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _delta(kind: str, col: str, hours: int) -> Optional[float]:
        cur = _avg([r for r in latest if r["kind"] == kind], col)
        past = _top_sql(
            db,
            f"""
            SELECT avg({col}) AS v FROM (
              SELECT DISTINCT ON (object_key) {col}
              FROM ocp_resource_metrics
              WHERE cluster_id = :cid AND kind = :kind
                AND timestamp <= now() - (:h * interval '1 hour')
                AND timestamp >= now() - ((:h + 2) * interval '1 hour')
              ORDER BY object_key, timestamp DESC
            ) t
            """,
            {"cid": cluster_id, "kind": kind, "h": hours},
        )
        pv = past[0]["v"] if past else None
        if cur is None or pv is None:
            return None
        return round(cur - float(pv), 1)

    last_ts = max((r["timestamp"] for r in latest), default=None)
    age_min = None
    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age_min = int((datetime.now(timezone.utc) - last_ts).total_seconds() // 60)

    metrics_ok = any(n.get("cpu_pct") is not None or n.get("cpu_used_cores") is not None for n in nodes) or any(
        p.get("cpu_used_cores") is not None for p in pods
    )

    top_cpu_nodes = sorted(
        [n for n in nodes if n.get("cpu_pct") is not None],
        key=lambda x: -(x.get("cpu_pct") or 0),
    )[:5]
    top_mem_nodes = sorted(
        [n for n in nodes if n.get("memory_pct") is not None],
        key=lambda x: -(x.get("memory_pct") or 0),
    )[:5]
    top_cpu_pods = sorted(
        [p for p in pods if p.get("cpu_used_cores") is not None],
        key=lambda x: -(x.get("cpu_used_cores") or 0),
    )[:8]
    top_cpu_vms = sorted(
        [v for v in vms if v.get("cpu_used_cores") is not None],
        key=lambda x: -(x.get("cpu_used_cores") or 0),
    )[:5]

    summary_parts = [
        f"{cluster.name}: {ready}/{len(nodes)} node ready",
        f"{len(masters)} master · {len(workers)} worker",
        f"{len(pods)} pod · {len(vms)} VM",
    ]
    if _avg(nodes, "cpu_pct") is not None:
        summary_parts.append(f"ortalama node CPU {_avg(nodes, 'cpu_pct')}% · bellek {_avg(nodes, 'memory_pct')}%")
    if not metrics_ok:
        summary_parts.append("metrics.k8s.io yok veya boş — kullanım serileri dolmayabilir")

    return {
        "ok": True,
        "source": "metrics.k8s.io",
        "prometheus": False,
        "cluster": {
            "id": cluster.id,
            "name": cluster.name,
            "api_url": cluster.api_url,
            "status": cluster.status,
            "version": cluster.version,
        },
        "health": {
            "grade": grade,
            "label": label,
            "availability_pct": avail,
            "hosts": host_counts,
            "nodes_ready": ready,
            "nodes_not_ready": not_ready,
        },
        "data_source": {
            "state": "connected" if metrics_ok else ("missing" if not latest else "partial"),
            "last_sample": last_ts.isoformat() if hasattr(last_ts, "isoformat") else None,
            "age_min": age_min,
            "stale": bool(age_min is not None and age_min >= STALE_MINUTES),
            "metrics_available": metrics_ok,
        },
        "inventory": {
            "nodes": len(nodes),
            "masters": len(masters),
            "workers": len(workers),
            "pods": len(pods),
            "vms": len(vms),
        },
        "comparison": {
            "cpu": {
                "current": _avg(nodes, "cpu_pct"),
                "d24h": _delta("node", "cpu_pct", 24),
                "d7d": _delta("node", "cpu_pct", 24 * 7),
            },
            "memory": {
                "current": _avg(nodes, "memory_pct"),
                "d24h": _delta("node", "memory_pct", 24),
                "d7d": _delta("node", "memory_pct", 24 * 7),
            },
        },
        "top_consumers": {
            "node_cpu": [
                {"name": n["name"], "value": n.get("cpu_pct"), "role": n.get("role"), "id": object_ref(cluster_id, "node", n["name"])}
                for n in top_cpu_nodes
            ],
            "node_memory": [
                {"name": n["name"], "value": n.get("memory_pct"), "role": n.get("role"), "id": object_ref(cluster_id, "node", n["name"])}
                for n in top_mem_nodes
            ],
            "pod_cpu": [
                {"name": f"{p.get('namespace')}/{p['name']}", "value": p.get("cpu_used_cores"),
                 "id": object_ref(cluster_id, "pod", p["name"], p.get("namespace"))}
                for p in top_cpu_pods
            ],
            "vm_cpu": [
                {"name": f"{v.get('namespace')}/{v['name']}", "value": v.get("cpu_used_cores"),
                 "id": object_ref(cluster_id, "vm", v["name"], v.get("namespace"))}
                for v in top_cpu_vms
            ],
        },
        "summary": " · ".join(summary_parts),
        "limits": {
            "disk_network_migration": False,
            "note": "Anlık CPU/bellek (metrics.k8s.io). Disk/net/migration ve kubevirt_vmi_* yok.",
        },
    }


def list_objects(
    db: Session,
    *,
    cluster_id: int,
    kind: str = "node",
    q: str = "",
    limit: int = 200,
) -> Dict[str, Any]:
    kind = (kind or "node").strip().lower()
    if kind not in ("node", "pod", "vm"):
        raise ValueError("kind node|pod|vm olmalı")
    limit = max(1, min(int(limit or 200), 500))
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise ValueError("Cluster bulunamadı")
    ensure_fresh_sample(db, cluster)

    rows = _top_sql(
        db,
        """
        SELECT DISTINCT ON (object_key)
               object_key, name, namespace, role, status, node_name,
               cpu_pct, memory_pct, cpu_used_cores, memory_used_gb, restarts, timestamp
        FROM ocp_resource_metrics
        WHERE cluster_id = :cid AND kind = :kind
          AND timestamp >= now() - interval '45 minutes'
        ORDER BY object_key, timestamp DESC
        """,
        {"cid": cluster_id, "kind": kind},
    )
    ql = (q or "").strip().lower()
    items = []
    for r in rows:
        hint_parts = []
        if r.get("role"):
            hint_parts.append(str(r["role"]))
        if r.get("status"):
            hint_parts.append(str(r["status"]))
        if r.get("namespace"):
            hint_parts.append(str(r["namespace"]))
        if r.get("node_name") and kind != "node":
            hint_parts.append(f"node {r['node_name']}")
        if r.get("cpu_pct") is not None:
            hint_parts.append(f"CPU {r['cpu_pct']}%")
        elif r.get("cpu_used_cores") is not None:
            hint_parts.append(f"CPU {r['cpu_used_cores']}c")
        if r.get("memory_pct") is not None:
            hint_parts.append(f"Mem {r['memory_pct']}%")
        elif r.get("memory_used_gb") is not None:
            hint_parts.append(f"Mem {r['memory_used_gb']}GB")
        hint = " · ".join(hint_parts)
        oid = object_ref(cluster_id, kind, r["name"], r.get("namespace"))
        blob = f"{r.get('name')} {r.get('namespace') or ''} {r.get('role') or ''} {r.get('status') or ''} {r.get('node_name') or ''}".lower()
        if ql and ql not in blob:
            continue
        items.append({
            "id": oid,
            "name": r["name"],
            "namespace": r.get("namespace"),
            "role": r.get("role"),
            "status": r.get("status"),
            "hint": hint,
            "cluster_id": cluster_id,
            "cluster_name": cluster.name,
        })
        if len(items) >= limit:
            break
    return {"ok": True, "kind": kind, "cluster_id": cluster_id, "items": items, "total": len(items)}


def parse_names(raw: Optional[str], extra: Optional[Sequence[str]] = None) -> List[str]:
    parts: List[str] = []
    if raw:
        parts.extend(x.strip() for x in raw.split(",") if x.strip())
    if extra:
        parts.extend(str(x).strip() for x in extra if str(x).strip())
    seen = set()
    out: List[str] = []
    for p in parts:
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= MAX_SERIES_OBJECTS:
            break
    return out


def query_series(
    db: Session,
    *,
    cluster_id: int,
    kind: str,
    names: Sequence[str],
    metric: str,
    range_key: str,
) -> Dict[str, Any]:
    kind = (kind or "node").strip().lower()
    names = parse_names(None, names)
    if not names:
        return {
            "ok": True,
            "kind": kind,
            "metric": metric,
            "range": parse_range(range_key),
            "series": [],
            "note": "nesne seçilmedi — seri çekilmedi",
        }
    cluster = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
    if not cluster:
        raise ValueError("Cluster bulunamadı")
    ensure_fresh_sample(db, cluster)

    column, unit = _metric_column(kind, metric)
    rng = parse_range(range_key)
    minutes = int(RANGE_SPEC[rng]["minutes"])
    bucket = RANGE_SPEC[rng]["bucket"]

    keys: List[str] = []
    for n in names:
        cid, knd, name, ns = parse_object_ref(n)
        if cid is not None and cid != cluster_id:
            continue
        if knd and knd != kind:
            continue
        if ns:
            keys.append(f"{ns}/{name}")
        else:
            keys.append(name)
    if not keys:
        return {"ok": True, "kind": kind, "metric": metric, "range": rng, "series": [], "note": "geçersiz seçim"}

    pair_clauses = []
    params: Dict[str, Any] = {"cid": cluster_id, "kind": kind, "mins": minutes}
    for i, key in enumerate(keys):
        pair_clauses.append(f"object_key = :k{i}")
        params[f"k{i}"] = key
    where_keys = "(" + " OR ".join(pair_clauses) + ")"

    def _rows_for(mins: int, buck: Optional[str]) -> List[Dict[str, Any]]:
        qparams = {**params, "mins": mins}
        if buck:
            sql = f"""
            SELECT object_key, name, namespace,
                   time_bucket('{buck}', timestamp) AS ts,
                   avg({column}) AS value
            FROM ocp_resource_metrics
            WHERE cluster_id = :cid AND kind = :kind
              AND timestamp >= now() - (:mins * interval '1 minute')
              AND {where_keys}
            GROUP BY object_key, name, namespace, ts
            ORDER BY object_key, ts
            """
        else:
            sql = f"""
            SELECT object_key, name, namespace, timestamp AS ts, {column} AS value
            FROM ocp_resource_metrics
            WHERE cluster_id = :cid AND kind = :kind
              AND timestamp >= now() - (:mins * interval '1 minute')
              AND {where_keys}
            ORDER BY object_key, timestamp
            """
        return _top_sql(db, sql, qparams)

    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for r in _rows_for(minutes, bucket):
        key = str(r.get("object_key") or "")
        ts = r.get("ts")
        by_key.setdefault(key, []).append({
            "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
            "v": _r(r.get("value"), 3),
        })

    expanded = False
    if not by_key or any(len(pts) < 2 for pts in by_key.values()):
        widen = max(minutes, 480)
        if widen != minutes or bucket:
            by_key2: Dict[str, List[Dict[str, Any]]] = {}
            for r in _rows_for(widen, None if widen <= 1440 else "1 hour"):
                key = str(r.get("object_key") or "")
                ts = r.get("ts")
                by_key2.setdefault(key, []).append({
                    "t": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
                    "v": _r(r.get("value"), 3),
                })
            if by_key2:
                by_key = by_key2
                expanded = True
                minutes = widen

    # display names from last query keys
    name_map = {}
    for r in _rows_for(max(minutes, 60), None)[:500]:
        name_map[str(r["object_key"])] = (
            f"{r.get('namespace')}/{r.get('name')}" if r.get("namespace") else r.get("name")
        )

    series = []
    for key, points in by_key.items():
        display = name_map.get(key) or key
        ns = None
        name = key
        if "/" in key:
            ns, name = key.split("/", 1)
        series.append({
            "name": display,
            "object": key,
            "ref": object_ref(cluster_id, kind, name, ns),
            "cluster_id": cluster_id,
            "points": points,
            "outside_window": expanded,
        })
    series.sort(key=lambda s: (s.get("name") or ""))
    last_ts = None
    for s in series:
        if s["points"]:
            last_ts = s["points"][-1]["t"]
    return {
        "ok": True,
        "kind": kind,
        "metric": metric,
        "column": column,
        "unit": unit,
        "range": rng if not expanded else f"{minutes}m",
        "as_of": last_ts,
        "native_interval_min": 1,
        "series": series,
        "prometheus": False,
        "source": "ocp_resource_metrics",
    }


# Geriye uyumluluk — eski snapshot endpoint
def build_monitoring_snapshot(cluster: OpenShiftCluster, **kwargs) -> Dict[str, Any]:
    from sqlalchemy.orm import object_session
    db = object_session(cluster)
    if db is None:
        rows, metrics_available = collect_live_rows(cluster)
        # session yoksa sadece canlı özet
        nodes = [r for r in rows if r["kind"] == "node"]
        return {
            "ok": True,
            "source": "metrics.k8s.io",
            "prometheus": False,
            "cluster": {"id": cluster.id, "name": cluster.name},
            "metrics_available": metrics_available,
            "capacity": {},
            "nodes": nodes,
            "pods": [r for r in rows if r["kind"] == "pod"][: kwargs.get("pod_limit", 80)],
            "projects": [],
            "vms": [r for r in rows if r["kind"] == "vm"],
        }
    return build_overview(db, int(cluster.id))
