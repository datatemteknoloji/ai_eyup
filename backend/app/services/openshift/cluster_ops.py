"""OpenShift cluster ops — Atlas backend fonksiyonlarının ainew uyarlaması.

Canlı REST (on-demand); envanter SoT sync'ten ayrıdır.
404/403 opsiyonel kaynaklarda None/boş döner — KubeVirt/MTV kurulu olmayan küme çökmez.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml

from app.models.openshift import OpenShiftCluster
from app.services.hypervisor_credentials import plain, seal_connection_secrets
from app.services.openshift.ocp_client import OpenShiftClient

logger = logging.getLogger(__name__)

OPERATOR_GROUPS = [
    {"group": "kubevirt.io", "label": "OpenShift Virtualization (KubeVirt)"},
    {"group": "cdi.kubevirt.io", "label": "Containerized Data Importer (CDI)"},
    {"group": "forklift.konveyor.io", "label": "Migration Toolkit for Virtualization (MTV)"},
    {"group": "migration.openshift.io", "label": "Migration (legacy)"},
    {"group": "k8s.cni.cncf.io", "label": "Multus CNI"},
    {"group": "operators.coreos.com", "label": "OLM / Operators"},
]

RESOURCE_KINDS = {
    "deployments": {"path": "/apis/apps/v1", "ns": True, "label": "Deployment", "resource": "deployments"},
    "statefulsets": {"path": "/apis/apps/v1", "ns": True, "label": "StatefulSet", "resource": "statefulsets"},
    "daemonsets": {"path": "/apis/apps/v1", "ns": True, "label": "DaemonSet", "resource": "daemonsets"},
    "pods": {"path": "/api/v1", "ns": True, "label": "Pod", "resource": "pods"},
    "services": {"path": "/api/v1", "ns": True, "label": "Service", "resource": "services"},
    "configmaps": {"path": "/api/v1", "ns": True, "label": "ConfigMap", "resource": "configmaps"},
    "persistentvolumeclaims": {"path": "/api/v1", "ns": True, "label": "PVC", "resource": "persistentvolumeclaims"},
    "routes": {"path": "/apis/route.openshift.io/v1", "ns": True, "label": "Route", "resource": "routes"},
    "virtualmachines": {"path": "/apis/kubevirt.io/v1", "ns": True, "label": "VirtualMachine", "resource": "virtualmachines"},
    "persistentvolumes": {"path": "/api/v1", "ns": False, "label": "PersistentVolume", "resource": "persistentvolumes"},
    "nodes": {"path": "/api/v1", "ns": False, "label": "Node", "resource": "nodes"},
    "storageclasses": {"path": "/apis/storage.k8s.io/v1", "ns": False, "label": "StorageClass", "resource": "storageclasses"},
}


def client_from_cluster(cluster: OpenShiftCluster) -> OpenShiftClient:
    cc = cluster.connection_config or {}
    token = plain(cc.get("token") or "")
    username = cc.get("username") or ""
    password = plain(cc.get("password") or "")
    use_creds = bool(username) and bool(password) and not token
    return OpenShiftClient(
        api_url=cc.get("api_url") or cluster.api_url,
        token="" if use_creds else token,
        username=username if use_creds else "",
        password=password if use_creds else "",
        verify_ssl=bool(cc.get("verify_ssl", False)),
        timeout=30,
    )


def kubevirt_client_from_cluster(cluster: OpenShiftCluster):
    """Aynı küme kimliğiyle KubeVirtClient — VM listesi/detay."""
    from app.services.openshift.kubevirt_client import KubeVirtClient
    cc = cluster.connection_config or {}
    token = plain(cc.get("token") or "")
    username = cc.get("username") or ""
    password = plain(cc.get("password") or "")
    use_creds = bool(username) and bool(password) and not token
    return KubeVirtClient(
        api_url=cc.get("api_url") or cluster.api_url,
        token="" if use_creds else token,
        username=username if use_creds else "",
        password=password if use_creds else "",
        verify_ssl=bool(cc.get("verify_ssl", False)),
        timeout=30,
    )


def seal_cluster_config(cc: dict) -> dict:
    return seal_connection_secrets(cc)


def _get_json(client: OpenShiftClient, path: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> Optional[Dict]:
    """404/403 → None (opsiyonel API'ler)."""
    try:
        r = client._get(path, params=params, timeout=timeout)
        if r.status_code in (404, 403):
            return None
        if r.status_code != 200:
            logger.debug("OCP GET %s → %s", path, r.status_code)
            return None
        return r.json() or {}
    except Exception as exc:
        logger.debug("OCP GET %s error: %s", path, exc)
        return None


def _age(ts: Optional[str]) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.strptime(ts.replace("Z", ""), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - t).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except Exception:
        return "—"


def _node_metrics_map(client: OpenShiftClient) -> Dict[str, Dict[str, float]]:
    """metrics.k8s.io node metrics — yoksa {}."""
    body = _get_json(client, "/apis/metrics.k8s.io/v1beta1/nodes", timeout=15)
    out: Dict[str, Dict[str, float]] = {}
    if not body:
        return out
    for item in body.get("items") or []:
        name = (item.get("metadata") or {}).get("name") or ""
        usage = item.get("usage") or {}
        out[name] = {
            "cpu_cores": OpenShiftClient._parse_quantity(usage.get("cpu")),
            "memory_gb": round(OpenShiftClient._parse_quantity(usage.get("memory")), 2),
        }
    return out


def cluster_overview(client: OpenShiftClient, cluster: OpenShiftCluster) -> Dict[str, Any]:
    version = client.get_version()
    api_groups = _get_json(client, "/apis", timeout=15) or {}
    group_names = {g.get("name") for g in (api_groups.get("groups") or []) if g.get("name")}

    operators = []
    for op in OPERATOR_GROUPS:
        installed = any(g == op["group"] or g.startswith(op["group"] + ".") for g in group_names)
        operators.append({**op, "installed": installed})

    kv = next((o for o in operators if o["group"] == "kubevirt.io"), {})
    cdi = next((o for o in operators if o["group"] == "cdi.kubevirt.io"), {})
    mtv = next((o for o in operators if o["group"] == "forklift.konveyor.io"), {})
    missing = []
    if not kv.get("installed"):
        missing.append("KubeVirt")
    if not cdi.get("installed"):
        missing.append("CDI")
    if not mtv.get("installed"):
        missing.append("MTV/Forklift")

    metrics = _node_metrics_map(client)
    nodes_raw = client.list_nodes()
    nodes = []
    cpu_total = mem_total = cpu_used = mem_used = 0.0
    ready_n = 0
    for n in nodes_raw:
        name = n["name"]
        usage = metrics.get(name)
        pressure = []
        # pressure from live node if we refetch — skip heavy; use status only
        cpu_total += float(n.get("cpu_cores") or 0)
        mem_total += float(n.get("memory_gb") or 0)
        if (n.get("status") or "").lower() == "ready":
            ready_n += 1
        if usage:
            cpu_used += usage["cpu_cores"]
            mem_used += usage["memory_gb"]
        nodes.append({
            "name": name,
            "ready": (n.get("status") or "").lower() == "ready",
            "roles": [n.get("role") or "worker"],
            "cpu": n.get("cpu_cores"),
            "memory_gb": n.get("memory_gb"),
            "kubelet": n.get("kubelet_version"),
            "os": n.get("os_image"),
            "internal_ip": n.get("internal_ip") or "",
            "external_ip": n.get("external_ip") or "",
            "hostname": n.get("hostname") or name,
            "ip_address": n.get("ip_address") or n.get("internal_ip") or "",
            "usage": {
                "cpu_cores": usage["cpu_cores"],
                "memory_gb": usage["memory_gb"],
            } if usage else None,
            "cpu_request_pct": n.get("cpu_usage_pct"),
            "memory_request_pct": n.get("memory_usage_pct"),
        })

    pods = client.list_pods()
    pods_running = sum(1 for p in pods if (p.get("phase") or p.get("status")) == "Running" or p.get("status") == "Running")

    sc_body = _get_json(client, "/apis/storage.k8s.io/v1/storageclasses", timeout=20)
    storage_classes = []
    if sc_body:
        for sc in sc_body.get("items") or []:
            meta = sc.get("metadata") or {}
            ann = meta.get("annotations") or {}
            storage_classes.append({
                "name": meta.get("name"),
                "provisioner": sc.get("provisioner"),
                "default": ann.get("storageclass.kubernetes.io/is-default-class") == "true",
            })

    nad_body = _get_json(client, "/apis/k8s.cni.cncf.io/v1/network-attachment-definitions", timeout=15)
    nads = None
    if nad_body is not None:
        by_name: Dict[str, Dict[str, Any]] = {}
        for nad in nad_body.get("items") or []:
            meta = nad.get("metadata") or {}
            name = meta.get("name") or ""
            if not name:
                continue
            if name not in by_name:
                by_name[name] = {"name": name, "namespaces": 0}
            by_name[name]["namespaces"] += 1
        nads = list(by_name.values())

    projects = client.list_projects()
    user_ns = [p["name"] for p in projects if not p.get("is_system")]

    kv_count = None
    if kv.get("installed"):
        vm_body = _get_json(client, "/apis/kubevirt.io/v1/virtualmachines", params={"limit": 500}, timeout=20)
        if vm_body:
            kv_count = len(vm_body.get("items") or [])

    return {
        "cluster": {
            "id": cluster.id,
            "name": cluster.name,
            "api_url": cluster.api_url,
            "verify_ssl": bool((cluster.connection_config or {}).get("verify_ssl")),
            "status": cluster.status,
        },
        "version": version,
        "operators": operators,
        "migration_ready": len(missing) == 0,
        "migration_missing": missing,
        "nodes": nodes,
        "capacity": {
            "cpu_cores": round(cpu_total, 1),
            "cpu_used_cores": round(cpu_used, 2) if metrics else None,
            "memory_gb": round(mem_total, 1),
            "memory_used_gb": round(mem_used, 1) if metrics else None,
            "nodes_total": len(nodes),
            "nodes_ready": ready_n,
            "pods_running": pods_running,
            "pods_total": len(pods),
            "metrics_available": bool(metrics),
        },
        "storage_classes": storage_classes,
        "network_attachment_definitions": nads,
        "namespaces": {"total": len(projects), "user": user_ns[:50], "user_count": len(user_ns)},
        "kubevirt_vms": kv_count,
    }


def cluster_health(client: OpenShiftClient) -> Dict[str, Any]:
    degraded: List[Dict] = []
    progressing: List[Dict] = []
    unavailable: List[Dict] = []

    co = _get_json(client, "/apis/config.openshift.io/v1/clusteroperators", timeout=30)
    if co:
        for item in co.get("items") or []:
            name = (item.get("metadata") or {}).get("name") or ""
            conds = {c.get("type"): c for c in (item.get("status") or {}).get("conditions") or []}
            avail = conds.get("Available") or {}
            prog = conds.get("Progressing") or {}
            deg = conds.get("Degraded") or {}
            entry = {
                "name": name,
                "reason": (deg.get("reason") or prog.get("reason") or avail.get("reason") or ""),
                "message": (deg.get("message") or prog.get("message") or "")[:240],
            }
            if deg.get("status") == "True":
                degraded.append(entry)
            if prog.get("status") == "True":
                progressing.append(entry)
            if avail.get("status") == "False":
                unavailable.append(entry)

    nodes = client.list_nodes()
    not_ready = [n["name"] for n in nodes if (n.get("status") or "").lower() != "ready"]

    # Node pressure via live fetch
    pressured: List[str] = []
    nbody = _get_json(client, "/api/v1/nodes", params={"limit": 200}, timeout=20)
    if nbody:
        for n in nbody.get("items") or []:
            name = (n.get("metadata") or {}).get("name") or ""
            for c in (n.get("status") or {}).get("conditions") or []:
                if c.get("type") in ("MemoryPressure", "DiskPressure", "PIDPressure") and c.get("status") == "True":
                    pressured.append(f"{name}:{c.get('type')}")

    cv = _get_json(client, "/apis/config.openshift.io/v1/clusterversions/version", timeout=15)
    version = None
    updating = False
    update_message = ""
    if cv:
        status = cv.get("status") or {}
        hist = status.get("history") or []
        if hist:
            version = hist[0].get("version")
        for c in status.get("conditions") or []:
            if c.get("type") == "Progressing" and c.get("status") == "True":
                updating = True
                update_message = (c.get("message") or "")[:240]

    mcp_body = _get_json(client, "/apis/machineconfiguration.openshift.io/v1/machineconfigpools", timeout=20)
    mcps = []
    if mcp_body:
        for p in mcp_body.get("items") or []:
            name = (p.get("metadata") or {}).get("name") or ""
            st = p.get("status") or {}
            conds = {c.get("type"): c for c in st.get("conditions") or []}
            mcps.append({
                "name": name,
                "ready": (conds.get("Updated") or {}).get("status") == "True",
                "updating": (conds.get("Updating") or {}).get("status") == "True",
                "degraded": (conds.get("Degraded") or {}).get("status") == "True",
                "machine_count": st.get("machineCount"),
                "ready_count": st.get("readyMachineCount"),
            })

    overall = "healthy"
    if degraded or unavailable or not_ready or any(m.get("degraded") for m in mcps):
        overall = "critical"
    elif progressing or updating or any(m.get("updating") for m in mcps) or pressured:
        overall = "warning"

    return {
        "overall": overall,
        "version": version,
        "updating": updating,
        "update_message": update_message,
        "operators": {
            "degraded": degraded,
            "progressing": progressing,
            "unavailable": unavailable,
            "total": len((co or {}).get("items") or []) if co else 0,
        },
        "nodes_not_ready": not_ready,
        "nodes_pressured": pressured,
        "machine_config_pools": mcps,
    }


def storage_overview(client: OpenShiftClient) -> Dict[str, Any]:
    sc_body = _get_json(client, "/apis/storage.k8s.io/v1/storageclasses", timeout=20) or {"items": []}
    storage_classes = []
    for sc in sc_body.get("items") or []:
        meta = sc.get("metadata") or {}
        ann = meta.get("annotations") or {}
        storage_classes.append({
            "name": meta.get("name"),
            "provisioner": sc.get("provisioner"),
            "default": ann.get("storageclass.kubernetes.io/is-default-class") == "true",
            "reclaim": sc.get("reclaimPolicy"),
            "binding": sc.get("volumeBindingMode"),
        })

    pv_body = _get_json(client, "/api/v1/persistentvolumes", params={"limit": 500}, timeout=30) or {"items": []}
    pvs = []
    for pv in pv_body.get("items") or []:
        meta = pv.get("metadata") or {}
        spec = pv.get("spec") or {}
        status = pv.get("status") or {}
        claim = spec.get("claimRef") or {}
        cap = (spec.get("capacity") or {}).get("storage")
        pvs.append({
            "name": meta.get("name"),
            "capacity_gb": round(OpenShiftClient._parse_quantity(cap), 2) if cap else None,
            "phase": status.get("phase"),
            "storage_class": spec.get("storageClassName"),
            "claim": f"{claim.get('namespace')}/{claim.get('name')}" if claim.get("name") else None,
            "access_modes": spec.get("accessModes") or [],
            "reclaim": spec.get("persistentVolumeReclaimPolicy"),
        })

    pvc_body = _get_json(client, "/api/v1/persistentvolumeclaims", params={"limit": 500}, timeout=30) or {"items": []}
    pvcs = []
    for pvc in pvc_body.get("items") or []:
        meta = pvc.get("metadata") or {}
        spec = pvc.get("spec") or {}
        status = pvc.get("status") or {}
        cap = (status.get("capacity") or spec.get("resources", {}).get("requests") or {}).get("storage")
        pvcs.append({
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "phase": status.get("phase"),
            "capacity_gb": round(OpenShiftClient._parse_quantity(cap), 2) if cap else None,
            "storage_class": spec.get("storageClassName"),
            "volume": spec.get("volumeName"),
        })

    pending = [p for p in pvcs if (p.get("phase") or "") == "Pending"]
    return {
        "storage_classes": storage_classes,
        "persistent_volumes": pvs,
        "persistent_volume_claims": pvcs,
        "summary": {
            "storage_classes": len(storage_classes),
            "pvs": len(pvs),
            "pvcs": len(pvcs),
            "pvcs_pending": len(pending),
        },
    }


def pod_detail(client: OpenShiftClient, namespace: str, pod: str) -> Optional[Dict[str, Any]]:
    body = _get_json(client, f"/api/v1/namespaces/{namespace}/pods/{pod}", timeout=20)
    if not body:
        return None
    meta = body.get("metadata") or {}
    spec = body.get("spec") or {}
    status = body.get("status") or {}
    containers = []
    for cs in status.get("containerStatuses") or []:
        state = cs.get("state") or {}
        waiting = state.get("waiting") or {}
        terminated = state.get("terminated") or {}
        running = state.get("running") or {}
        containers.append({
            "name": cs.get("name"),
            "image": cs.get("image"),
            "ready": cs.get("ready"),
            "restart_count": cs.get("restartCount"),
            "state": "waiting" if waiting else ("terminated" if terminated else ("running" if running else "unknown")),
            "reason": waiting.get("reason") or terminated.get("reason"),
            "message": (waiting.get("message") or terminated.get("message") or "")[:300],
        })

    ev_body = _get_json(
        client,
        f"/api/v1/namespaces/{namespace}/events",
        params={"fieldSelector": f"involvedObject.name={pod},involvedObject.kind=Pod", "limit": 20},
        timeout=15,
    )
    events = []
    for ev in (ev_body or {}).get("items") or []:
        events.append({
            "type": ev.get("type"),
            "reason": ev.get("reason"),
            "message": (ev.get("message") or "")[:300],
            "count": ev.get("count"),
            "last_timestamp": ev.get("lastTimestamp") or ev.get("eventTime"),
        })

    return {
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "phase": status.get("phase"),
        "node": spec.get("nodeName"),
        "pod_ip": status.get("podIP"),
        "start_time": status.get("startTime"),
        "labels": meta.get("labels") or {},
        "containers": containers,
        "conditions": status.get("conditions") or [],
        "events": events[:15],
        "age": _age(meta.get("creationTimestamp")),
    }


def pod_logs(
    client: OpenShiftClient,
    namespace: str,
    pod: str,
    *,
    container: Optional[str] = None,
    tail: int = 300,
    previous: bool = False,
) -> Dict[str, Any]:
    tail = max(1, min(int(tail or 300), 5000))
    params: Dict[str, Any] = {"tailLines": tail, "timestamps": "true"}
    if container:
        params["container"] = container
    if previous:
        params["previous"] = "true"
    try:
        r = client._get(f"/api/v1/namespaces/{namespace}/pods/{pod}/log", params=params, timeout=45)
        if r.status_code == 403:
            return {"ok": False, "logs": "", "error": "Log okuma yetkisi yok (RBAC)"}
        if r.status_code == 404:
            return {"ok": False, "logs": "", "error": "Pod veya container bulunamadı"}
        if r.status_code != 200:
            return {"ok": False, "logs": "", "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}"}
        return {"ok": True, "logs": r.text or "", "error": None}
    except Exception as exc:
        return {"ok": False, "logs": "", "error": str(exc)[:300]}


def list_resources(client: OpenShiftClient, kind: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    meta = RESOURCE_KINDS.get(kind)
    if not meta:
        return {"kind": kind, "items": [], "error": f"Bilinmeyen kind: {kind}"}
    # Namespace verilmezse cluster-wide liste (K8s destekler); verilirse NS filtresi
    if meta["ns"] and namespace:
        path = f"{meta['path']}/namespaces/{namespace}/{meta['resource']}"
    else:
        path = f"{meta['path']}/{meta['resource']}"
    body = _get_json(client, path, params={"limit": 500}, timeout=45)
    if body is None:
        return {"kind": kind, "items": [], "error": "Kaynak API yok veya yetki yok (404/403)"}
    items = []
    for it in body.get("items") or []:
        m = it.get("metadata") or {}
        info = _resource_info(kind, it)
        items.append({
            "name": m.get("name"),
            "namespace": m.get("namespace"),
            "age": _age(m.get("creationTimestamp")),
            "info": info,
        })
    return {"kind": kind, "label": meta["label"], "items": items, "total": len(items), "error": None}


def _resource_info(kind: str, it: dict) -> str:
    st = it.get("status") or {}
    spec = it.get("spec") or {}
    if kind == "deployments":
        ready = st.get("readyReplicas") or 0
        desired = spec.get("replicas") or 0
        return f"{ready}/{desired}"
    if kind == "pods":
        return st.get("phase") or "?"
    if kind == "routes":
        return (spec.get("host") or "")[:80]
    if kind == "services":
        return spec.get("type") or "ClusterIP"
    if kind == "persistentvolumeclaims":
        return st.get("phase") or "?"
    if kind == "virtualmachines":
        return ((st.get("printableStatus") or st.get("phase") or "?"))
    if kind == "storageclasses":
        return it.get("provisioner") or ""
    if kind == "nodes":
        conds = st.get("conditions") or []
        ready = next((c for c in conds if c.get("type") == "Ready"), None)
        return "Ready" if ready and ready.get("status") == "True" else "NotReady"
    return ""


def get_resource_yaml(client: OpenShiftClient, kind: str, name: str, namespace: Optional[str] = None) -> Dict[str, Any]:
    meta = RESOURCE_KINDS.get(kind)
    if not meta:
        return {"ok": False, "yaml": "", "error": f"Bilinmeyen kind: {kind}"}
    if meta["ns"] and not namespace:
        return {"ok": False, "yaml": "", "error": "namespace gerekli"}
    path = (
        f"{meta['path']}/namespaces/{namespace}/{meta['resource']}/{name}"
        if meta["ns"]
        else f"{meta['path']}/{meta['resource']}/{name}"
    )
    body = _get_json(client, path, timeout=30)
    if not body:
        return {"ok": False, "yaml": "", "error": "Kaynak bulunamadı veya yetki yok"}
    # managedFields temizle
    if "metadata" in body and isinstance(body["metadata"], dict):
        body["metadata"].pop("managedFields", None)
    try:
        text = yaml.safe_dump(body, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception:
        import json
        text = json.dumps(body, indent=2, ensure_ascii=False)
    return {"ok": True, "yaml": text, "error": None}


def resource_kinds() -> List[Dict[str, Any]]:
    return [
        {"id": k, "label": v["label"], "namespaced": v["ns"]}
        for k, v in RESOURCE_KINDS.items()
    ]


def list_datavolumes(client: OpenShiftClient, namespace: Optional[str] = None) -> Dict[str, Any]:
    """CDI DataVolume listesi (cdi.kubevirt.io) — CDI operatörü kurulu değilse 404/None döner."""
    path = (
        f"/apis/cdi.kubevirt.io/v1beta1/namespaces/{namespace}/datavolumes"
        if namespace else "/apis/cdi.kubevirt.io/v1beta1/datavolumes"
    )
    body = _get_json(client, path, params={"limit": 500}, timeout=30)
    if body is None:
        return {
            "items": [], "total": 0,
            "error": "CDI (DataVolume) API'sine erişilemedi — CDI/Containerized Data Importer operatörü kurulu olmayabilir veya SA yetkisi yok (404/403)",
        }
    items = []
    for dv in body.get("items") or []:
        meta = dv.get("metadata") or {}
        spec = dv.get("spec") or {}
        status = dv.get("status") or {}
        source = spec.get("source") or {}
        source_type = next(iter(source.keys()), "") if source else ""
        pvc_spec = spec.get("pvc") or spec.get("storage") or {}
        size = ((pvc_spec.get("resources") or {}).get("requests") or {}).get("storage")
        src_pvc = source.get("pvc") or {}
        items.append({
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "phase": status.get("phase"),
            "progress": status.get("progress"),
            "size": size,
            "storage_class": pvc_spec.get("storageClassName"),
            "source_type": source_type,
            "source_http_url": (source.get("http") or {}).get("url"),
            "source_registry_url": (source.get("registry") or {}).get("url"),
            "source_pvc": f"{src_pvc.get('namespace','')}/{src_pvc.get('name','')}".strip("/") or None,
            "condition_bound": next(
                (c.get("status") for c in (status.get("conditions") or []) if c.get("type") == "Bound"), None,
            ),
            "created": meta.get("creationTimestamp"),
        })
    return {"items": items, "total": len(items), "error": None}


def list_migrations(client: OpenShiftClient, namespace: Optional[str] = None) -> Dict[str, Any]:
    """KubeVirt Live Migration (VirtualMachineInstanceMigration) listesi — namespace verilmezse cluster-wide."""
    path = (
        f"/apis/kubevirt.io/v1/namespaces/{namespace}/virtualmachineinstancemigrations"
        if namespace else "/apis/kubevirt.io/v1/virtualmachineinstancemigrations"
    )
    body = _get_json(client, path, params={"limit": 200}, timeout=30)
    if body is None:
        return {
            "items": [], "total": 0,
            "error": "KubeVirt Migration API'sine erişilemedi — OpenShift Virtualization kurulu olmayabilir veya SA yetkisi yok (404/403)",
        }
    items = []
    for m in body.get("items") or []:
        meta = m.get("metadata") or {}
        spec = m.get("spec") or {}
        status = m.get("status") or {}
        mstate = status.get("migrationState") or {}
        items.append({
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "vm": spec.get("vmiName"),
            "phase": status.get("phase"),
            "source_node": mstate.get("sourceNode"),
            "target_node": mstate.get("targetNode"),
            "start_time": mstate.get("startTimestamp"),
            "end_time": mstate.get("endTimestamp"),
            "data_processed_bytes": mstate.get("dataProcessed"),
            "data_remaining_bytes": mstate.get("dataRemaining"),
            "data_total_bytes": mstate.get("dataTotal"),
            "transfer_rate_bytes_per_sec": mstate.get("transferRate"),
            "pending": (status.get("phase") in ("Pending", "Scheduling", "Scheduled")),
            "running": (status.get("phase") == "Running"),
            "succeeded": (status.get("phase") == "Succeeded"),
            "failed": bool(mstate.get("failed")) or (status.get("phase") == "Failed"),
            "completed": bool(mstate.get("completed")),
            "abort_status": mstate.get("abortStatus"),
            "created": meta.get("creationTimestamp"),
        })
    items.sort(key=lambda x: x.get("created") or "", reverse=True)
    return {"items": items, "total": len(items), "error": None}


def resource_quota_overview(client: OpenShiftClient, namespace: str) -> Dict[str, Any]:
    """Namespace ResourceQuota + LimitRange — CPU/bellek limit+used, obje sayısı sınırları."""
    ns = (namespace or "").strip()
    if not ns:
        return {"error": "namespace gerekli", "resource_quotas": [], "limit_ranges": []}
    rq_body = _get_json(client, f"/api/v1/namespaces/{ns}/resourcequotas", timeout=20)
    lr_body = _get_json(client, f"/api/v1/namespaces/{ns}/limitranges", timeout=20)
    quotas = []
    for rq in (rq_body or {}).get("items") or []:
        meta = rq.get("metadata") or {}
        status = rq.get("status") or {}
        quotas.append({
            "name": meta.get("name"),
            "hard": status.get("hard") or {},
            "used": status.get("used") or {},
        })
    limits = []
    for lr in (lr_body or {}).get("items") or []:
        meta = lr.get("metadata") or {}
        spec = lr.get("spec") or {}
        limits.append({"name": meta.get("name"), "limits": spec.get("limits") or []})
    return {
        "namespace": ns,
        "resource_quotas": quotas,
        "limit_ranges": limits,
        "has_quota": bool(quotas),
        "has_limit_range": bool(limits),
        "error": None if (rq_body is not None or lr_body is not None) else "ResourceQuota/LimitRange API'sine erişilemedi (403)",
    }


def network_overview(client: OpenShiftClient) -> Dict[str, Any]:
    """Multus NAD + Service/Route özet sayıları."""
    nad_body = _get_json(client, "/apis/k8s.cni.cncf.io/v1/network-attachment-definitions", timeout=15)
    nads: Optional[List[Dict[str, Any]]] = None
    if nad_body is not None:
        by_name: Dict[str, Dict[str, Any]] = {}
        for nad in nad_body.get("items") or []:
            meta = nad.get("metadata") or {}
            name = meta.get("name") or ""
            ns = meta.get("namespace") or ""
            if name not in by_name:
                by_name[name] = {"name": name, "namespaces": 0, "namespace_list": []}
            by_name[name]["namespaces"] += 1
            if ns:
                by_name[name]["namespace_list"].append(ns)
        nads = list(by_name.values())

    svc_body = _get_json(client, "/api/v1/services", params={"limit": 1}, timeout=15)
    route_body = _get_json(client, "/apis/route.openshift.io/v1/routes", params={"limit": 1}, timeout=15)
    return {
        "network_attachment_definitions": nads,
        "has_multus": nads is not None,
        "services_hint": (svc_body or {}).get("metadata", {}).get("remainingItemCount"),
        "routes_available": route_body is not None,
    }


def scale_workload(
    client: OpenShiftClient, kind: str, namespace: str, name: str, replicas: int,
) -> Dict[str, Any]:
    if kind not in ("deployments", "statefulsets"):
        return {"ok": False, "error": "Yalnızca Deployment/StatefulSet ölçeklenebilir"}
    if not (0 <= replicas <= 100):
        return {"ok": False, "error": "Replika sayısı 0-100 arası olmalı"}
    path = f"/apis/apps/v1/namespaces/{namespace}/{kind}/{name}/scale"
    r = client._patch(
        path,
        {"spec": {"replicas": replicas}},
        content_type="application/merge-patch+json",
    )
    if r.status_code == 403:
        return {"ok": False, "error": "Yetki yok (403) — SA’ya apps scale izni gerekli"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}"}
    return {"ok": True, "replicas": replicas}


def restart_workload(
    client: OpenShiftClient, kind: str, namespace: str, name: str,
) -> Dict[str, Any]:
    if kind not in ("deployments", "statefulsets", "daemonsets"):
        return {"ok": False, "error": "Bu tür yeniden başlatılamaz"}
    ts = datetime.now(timezone.utc).isoformat()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"ainew.datatem/restartedAt": ts},
                },
            },
        },
    }
    path = f"/apis/apps/v1/namespaces/{namespace}/{kind}/{name}"
    r = client._patch(path, body, content_type="application/strategic-merge-patch+json")
    if r.status_code == 403:
        return {"ok": False, "error": "Yetki yok (403) — SA’ya apps patch izni gerekli"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}"}
    return {"ok": True}


def delete_pod(client: OpenShiftClient, namespace: str, name: str) -> Dict[str, Any]:
    r = client._delete(f"/api/v1/namespaces/{namespace}/pods/{name}")
    if r.status_code == 403:
        return {"ok": False, "error": "Yetki yok (403)"}
    if r.status_code == 404:
        return {"ok": False, "error": "Pod bulunamadı"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}"}
    return {"ok": True}
