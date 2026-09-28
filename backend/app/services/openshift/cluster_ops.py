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



def _cpu_millicores(val) -> float:
    """K8s CPU quantity → millicore (Atlas)."""
    s = str(val or "0").strip()
    if not s:
        return 0.0
    try:
        if s.endswith("n"):
            return round(float(s[:-1]) / 1_000_000, 1)
        if s.endswith("u"):
            return round(float(s[:-1]) / 1000, 1)
        if s.endswith("m"):
            return float(s[:-1])
        return float(s) * 1000
    except (TypeError, ValueError):
        return 0.0


def _memory_mb(val) -> float:
    """K8s memory quantity → MB (Atlas)."""
    gb = OpenShiftClient._parse_quantity(val)
    return round(gb * 1024, 1)


def pod_detail(client: OpenShiftClient, namespace: str, pod: str) -> Optional[Dict[str, Any]]:
    """
    Pod tam ayrıntısı — Atlas PodDetail çekmecesini besler.

    GÜVENLİK: Secret DEĞERLERİ çözümlenmez; yalnızca referans gösterilir.
    """
    body = _get_json(client, f"/api/v1/namespaces/{namespace}/pods/{pod}", timeout=20)
    if not body:
        return None
    md = body.get("metadata") or {}
    st = body.get("status") or {}
    spec = body.get("spec") or {}

    all_status = {
        cs["name"]: cs
        for cs in (st.get("containerStatuses") or []) + (st.get("initContainerStatuses") or [])
        if cs.get("name")
    }

    def _env(ct: dict) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for e in ct.get("env") or []:
            if not isinstance(e, dict):
                continue
            src = e.get("valueFrom") or {}
            if "secretKeyRef" in src:
                ref = src["secretKeyRef"] or {}
                out.append({
                    "name": e.get("name"), "from": "secret",
                    "ref": f"{ref.get('name')}/{ref.get('key')}", "value": None,
                })
            elif "configMapKeyRef" in src:
                ref = src["configMapKeyRef"] or {}
                out.append({
                    "name": e.get("name"), "from": "configmap",
                    "ref": f"{ref.get('name')}/{ref.get('key')}", "value": None,
                })
            elif "fieldRef" in src:
                out.append({
                    "name": e.get("name"), "from": "field",
                    "ref": (src["fieldRef"] or {}).get("fieldPath"), "value": None,
                })
            elif "resourceFieldRef" in src:
                out.append({
                    "name": e.get("name"), "from": "resource",
                    "ref": (src["resourceFieldRef"] or {}).get("resource"), "value": None,
                })
            else:
                out.append({
                    "name": e.get("name"), "from": "literal",
                    "ref": None, "value": e.get("value", ""),
                })
        return out

    def _build(ct: dict, is_init: bool = False) -> Dict[str, Any]:
        cs = all_status.get(ct.get("name") or "", {}) or {}
        state = cs.get("state") or {}
        if "running" in state:
            state_str, since = "running", (state.get("running") or {}).get("startedAt")
        elif "waiting" in state:
            state_str, since = (state.get("waiting") or {}).get("reason", "waiting"), None
        elif "terminated" in state:
            t = state.get("terminated") or {}
            state_str, since = t.get("reason", "terminated"), t.get("finishedAt")
        else:
            state_str, since = "?", None
        last = (cs.get("lastState") or {}).get("terminated") or {}
        res = ct.get("resources") or {}
        return {
            "name": ct.get("name"),
            "image": ct.get("image"),
            "init": is_init,
            "ready": bool(cs.get("ready")),
            "restarts": cs.get("restartCount") or 0,
            "restart_count": cs.get("restartCount") or 0,
            "state": state_str,
            "reason": state_str if state_str not in ("running", "?", "terminated") else None,
            "since": since,
            "last_exit": (
                {"reason": last.get("reason"), "code": last.get("exitCode"), "at": last.get("finishedAt")}
                if last else None
            ),
            "ports": [
                {"port": x.get("containerPort"), "protocol": x.get("protocol", "TCP"), "name": x.get("name")}
                for x in (ct.get("ports") or [])
            ],
            "requests": res.get("requests") or {},
            "limits": res.get("limits") or {},
            "mounts": [
                {"name": m.get("name"), "path": m.get("mountPath"), "readonly": bool(m.get("readOnly"))}
                for m in (ct.get("volumeMounts") or [])
            ],
            "env": _env(ct),
            "command": ct.get("command") or [],
            "args": ct.get("args") or [],
        }

    containers = [_build(ct) for ct in (spec.get("containers") or [])]
    init_containers = [_build(ct, True) for ct in (spec.get("initContainers") or [])]

    owner = ""
    owners = []
    for o in md.get("ownerReferences") or []:
        if not owner:
            owner = f"{o.get('kind')}/{o.get('name')}"
        owners.append({
            "kind": o.get("kind"),
            "name": o.get("name"),
            "api_version": o.get("apiVersion"),
            "controller": o.get("controller"),
        })

    volumes = []
    for v in spec.get("volumes") or []:
        if not isinstance(v, dict):
            continue
        vtype = next((k for k in v if k != "name"), "?")
        detail = ""
        raw = v.get(vtype) or {}
        if isinstance(raw, dict):
            if vtype == "persistentVolumeClaim":
                detail = raw.get("claimName") or ""
            elif vtype == "configMap":
                detail = raw.get("name") or ""
            elif vtype == "secret":
                detail = raw.get("secretName") or raw.get("name") or ""
            elif vtype == "hostPath":
                detail = raw.get("path") or ""
            elif vtype == "emptyDir":
                detail = "emptyDir"
        volumes.append({"name": v.get("name"), "type": vtype, "detail": detail})

    usage: Dict[str, Any] = {}
    m_body = _get_json(
        client,
        f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods/{pod}",
        timeout=10,
    )
    metrics = None
    if m_body:
        cpu_sum = 0.0
        mem_sum = 0.0
        per_c = []
        for ct in m_body.get("containers") or []:
            u = ct.get("usage") or {}
            mcores = _cpu_millicores(u.get("cpu", "0"))
            mb = _memory_mb(u.get("memory", "0"))
            usage[ct.get("name")] = {"cpu_millicores": mcores, "memory_mb": mb}
            cpu_sum += mcores
            mem_sum += mb
            per_c.append({
                "name": ct.get("name"),
                "cpu_cores": round(mcores / 1000, 4),
                "memory_gb": round(mb / 1024, 4),
                "cpu_millicores": mcores,
                "memory_mb": mb,
            })
        metrics = {
            "cpu_cores": round(cpu_sum / 1000, 4),
            "memory_gb": round(mem_sum / 1024, 4),
            "containers": per_c,
            "source": "metrics.k8s.io",
        }

    conds = [
        {
            "type": x.get("type"),
            "status": x.get("status"),
            "reason": x.get("reason") or "",
            "message": (x.get("message") or "")[:200],
        }
        for x in (st.get("conditions") or [])
    ]

    ev = _get_json(
        client,
        f"/api/v1/namespaces/{namespace}/events",
        params={"fieldSelector": f"involvedObject.name={pod}", "limit": 40},
        timeout=15,
    ) or {}
    events = sorted(
        (
            {
                "type": e.get("type"),
                "reason": e.get("reason"),
                "message": (e.get("message") or "")[:300],
                "count": e.get("count") or 1,
                "age": _age(e.get("lastTimestamp") or e.get("eventTime")),
                "last_timestamp": e.get("lastTimestamp") or e.get("eventTime"),
                "warning": e.get("type") == "Warning",
            }
            for e in (ev.get("items") or [])
        ),
        key=lambda x: -(x["count"] or 0),
    )[:25]

    return {
        "kind": "Pod",
        "kind_id": "pods",
        "name": pod,
        "namespace": namespace,
        "phase": st.get("phase"),
        "status_badge": st.get("phase") or "—",
        "node": spec.get("nodeName"),
        "host_ip": st.get("hostIP"),
        "pod_ip": st.get("podIP"),
        "start_time": st.get("startTime"),
        "created_at": md.get("creationTimestamp"),
        "age": _age(md.get("creationTimestamp")),
        "owner": owner,
        "owner_refs": owners,
        "qos": st.get("qosClass"),
        "qos_class": st.get("qosClass"),
        "service_account": spec.get("serviceAccountName") or "default",
        "restart_policy": spec.get("restartPolicy") or "Always",
        "node_selector": spec.get("nodeSelector") or {},
        "labels": md.get("labels") or {},
        "annotations": {
            k: (str(v)[:120] + ("…" if len(str(v)) > 120 else ""))
            for k, v in list((md.get("annotations") or {}).items())[:40]
        },
        "containers": containers,
        "init_containers": init_containers,
        "volumes": volumes,
        "usage": usage,
        "metrics": metrics,
        "conditions": conds,
        "events": events,
    }



def _events_for(
    client: OpenShiftClient,
    namespace: Optional[str],
    *,
    kind: str,
    name: str,
    limit: int = 40,
) -> List[Dict[str, Any]]:
    params = {
        "fieldSelector": f"involvedObject.name={name},involvedObject.kind={kind}",
        "limit": limit,
    }
    path = (
        f"/api/v1/namespaces/{namespace}/events"
        if namespace
        else "/api/v1/events"
    )
    body = _get_json(client, path, params=params, timeout=15)
    events = []
    for ev in (body or {}).get("items") or []:
        events.append({
            "type": ev.get("type"),
            "reason": ev.get("reason"),
            "message": (ev.get("message") or "")[:400],
            "count": ev.get("count"),
            "last_timestamp": ev.get("lastTimestamp") or ev.get("eventTime"),
        })
    return events


def _volume_summaries_from_pod_template(spec: dict) -> List[Dict[str, Any]]:
    volumes = []
    for v in ((spec.get("template") or {}).get("spec") or {}).get("volumes") or []:
        if not isinstance(v, dict):
            continue
        vtype = next((k for k in v.keys() if k != "name"), "unknown")
        detail = v.get(vtype) or {}
        extra = ""
        if isinstance(detail, dict):
            if vtype == "persistentVolumeClaim":
                extra = detail.get("claimName") or ""
            elif vtype == "secret":
                extra = detail.get("secretName") or ""
            elif vtype == "configMap":
                extra = detail.get("name") or ""
        volumes.append({"name": v.get("name"), "type": vtype, "detail": extra})
    return volumes


def _containers_from_pod_template(spec: dict) -> List[Dict[str, Any]]:
    out = []
    pod_spec = (spec.get("template") or {}).get("spec") or {}
    for c in pod_spec.get("containers") or []:
        env = []
        for e in c.get("env") or []:
            if not isinstance(e, dict):
                continue
            if "value" in e:
                val = str(e.get("value") or "")
            elif e.get("valueFrom"):
                vf = e["valueFrom"]
                if "secretKeyRef" in vf:
                    val = f"secret:{vf['secretKeyRef'].get('name')}/{vf['secretKeyRef'].get('key')}"
                elif "configMapKeyRef" in vf:
                    val = f"configmap:{vf['configMapKeyRef'].get('name')}/{vf['configMapKeyRef'].get('key')}"
                else:
                    val = "valueFrom"
            else:
                val = ""
            env.append({"name": e.get("name"), "value": val[:200]})
        res = c.get("resources") or {}
        out.append({
            "name": c.get("name"),
            "image": c.get("image"),
            "env": env,
            "requests": res.get("requests") or {},
            "limits": res.get("limits") or {},
            "ports": c.get("ports") or [],
        })
    return out


def _match_labels_selector(labels: dict, selector: dict) -> bool:
    if not selector:
        return False
    for k, v in selector.items():
        if labels.get(k) != v:
            return False
    return True


def _related_pods(
    client: OpenShiftClient,
    namespace: str,
    *,
    selector: Optional[dict] = None,
    owner_kind: Optional[str] = None,
    owner_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    body = _get_json(
        client,
        f"/api/v1/namespaces/{namespace}/pods",
        params={"limit": 500},
        timeout=30,
    )
    pods = []
    for it in (body or {}).get("items") or []:
        meta = it.get("metadata") or {}
        labels = meta.get("labels") or {}
        if selector and not _match_labels_selector(labels, selector):
            continue
        if owner_kind and owner_name:
            owners = meta.get("ownerReferences") or []
            if not any(
                o.get("kind") == owner_kind and o.get("name") == owner_name for o in owners
            ):
                continue
        st = it.get("status") or {}
        spec = it.get("spec") or {}
        ready = 0
        total = 0
        restarts = 0
        for cs in st.get("containerStatuses") or []:
            total += 1
            if cs.get("ready"):
                ready += 1
            restarts += cs.get("restartCount") or 0
        pods.append({
            "name": meta.get("name"),
            "namespace": meta.get("namespace"),
            "phase": st.get("phase"),
            "ready": f"{ready}/{total}" if total else "0/0",
            "restarts": restarts,
            "node": spec.get("nodeName"),
            "age": _age(meta.get("creationTimestamp")),
            "pod_ip": st.get("podIP"),
        })
    return pods


def workload_detail(
    client: OpenShiftClient,
    kind: str,
    namespace: str,
    name: str,
) -> Optional[Dict[str, Any]]:
    """
    Deployment/StatefulSet/DaemonSet — Atlas WorkloadDetail şekli:
    replicas, services, routes, containers (env/mounts/secret), pods, events.
    """
    meta = RESOURCE_KINDS.get(kind)
    if not meta or not meta["ns"] or kind not in ("deployments", "statefulsets", "daemonsets"):
        return None

    def _sel_match(selector: Dict, labels: Dict) -> bool:
        return bool(selector) and all(labels.get(k) == v for k, v in selector.items())

    obj = _get_json(
        client,
        f"{meta['path']}/namespaces/{namespace}/{kind}/{name}",
        timeout=30,
    )
    if not obj:
        return None

    md, spec, st = obj.get("metadata") or {}, obj.get("spec") or {}, obj.get("status") or {}
    tmpl = ((spec.get("template") or {}).get("spec") or {})

    containers: List[Dict[str, Any]] = []
    init_list = tmpl.get("initContainers") or []
    for cont in (tmpl.get("containers") or []) + init_list:
        env = []
        for e in cont.get("env") or []:
            if not isinstance(e, dict):
                continue
            src = e.get("valueFrom") or {}
            ref = (src.get("configMapKeyRef") or src.get("secretKeyRef") or {})
            env.append({
                "name": e.get("name"),
                "value": e.get("value"),
                "from": (
                    "Secret" if "secretKeyRef" in src else
                    "ConfigMap" if "configMapKeyRef" in src else
                    "field" if "fieldRef" in src else
                    "resource" if "resourceFieldRef" in src else None
                ),
                "ref": f"{ref.get('name')}/{ref.get('key')}" if ref.get("name") else (
                    (src.get("fieldRef") or {}).get("fieldPath") if "fieldRef" in src else None
                ),
                "secret": "secretKeyRef" in src,
            })
        res = cont.get("resources") or {}
        containers.append({
            "name": cont.get("name"),
            "image": cont.get("image"),
            "init": cont in init_list,
            "ports": [
                f"{p.get('containerPort')}/{p.get('protocol', 'TCP')}"
                for p in (cont.get("ports") or [])
            ],
            "requests": res.get("requests") or {},
            "limits": res.get("limits") or {},
            "env": env,
            "mounts": [
                {"name": m.get("name"), "path": m.get("mountPath"), "readonly": bool(m.get("readOnly"))}
                for m in (cont.get("volumeMounts") or [])
            ],
        })

    sel = ((spec.get("selector") or {}).get("matchLabels") or {})
    pods_all = (_get_json(client, f"/api/v1/namespaces/{namespace}/pods", params={"limit": 500}, timeout=30) or {}).get("items") or []
    my_pods = [p for p in pods_all if _sel_match(sel, (p.get("metadata") or {}).get("labels") or {})]
    pods = []
    for p in my_pods:
        pst = p.get("status") or {}
        cs = pst.get("containerStatuses") or []
        pods.append({
            "name": (p.get("metadata") or {}).get("name"),
            "namespace": namespace,
            "phase": pst.get("phase"),
            "healthy": pst.get("phase") in ("Running", "Succeeded"),
            "ready": f"{sum(1 for x in cs if x.get('ready'))}/{len(cs)}" if cs else "0/0",
            "restarts": sum(x.get("restartCount", 0) for x in cs),
            "node": (p.get("spec") or {}).get("nodeName"),
            "age": _age(pst.get("startTime") or (p.get("metadata") or {}).get("creationTimestamp")),
            "containers": [x.get("name") for x in ((p.get("spec") or {}).get("containers") or []) if x.get("name")],
            "pod_ip": pst.get("podIP"),
        })

    pod_labels = (my_pods[0].get("metadata") or {}).get("labels") or {} if my_pods else {}
    svcs_raw = (_get_json(client, f"/api/v1/namespaces/{namespace}/services", params={"limit": 500}, timeout=20) or {}).get("items") or []
    svcs = [s for s in svcs_raw if _sel_match((s.get("spec") or {}).get("selector") or {}, pod_labels)]
    svc_names = {(s.get("metadata") or {}).get("name") for s in svcs}
    routes_raw = (_get_json(
        client, f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes",
        params={"limit": 500}, timeout=20,
    ) or {}).get("items") or []
    routes = [
        r for r in routes_raw
        if ((r.get("spec") or {}).get("to") or {}).get("name") in svc_names
    ]

    events = []
    names = {name} | {p["name"] for p in pods if p.get("name")}
    data = _get_json(client, f"/api/v1/namespaces/{namespace}/events", params={"limit": 200}, timeout=20) or {}
    for e in data.get("items") or []:
        io = e.get("involvedObject") or {}
        if io.get("name") not in names:
            continue
        events.append({
            "time": e.get("lastTimestamp") or e.get("eventTime"),
            "last_timestamp": e.get("lastTimestamp") or e.get("eventTime"),
            "type": e.get("type"),
            "warning": e.get("type") == "Warning",
            "reason": e.get("reason"),
            "message": (e.get("message") or "")[:200],
            "kind": io.get("kind"),
            "name": io.get("name"),
            "count": e.get("count") or 1,
        })
    events.sort(key=lambda x: x.get("time") or "", reverse=True)

    replicas = {
        "desired": spec.get("replicas", st.get("desiredNumberScheduled")),
        "ready": st.get("readyReplicas", st.get("numberReady", 0)) or 0,
        "available": st.get("availableReplicas", st.get("numberAvailable")),
        "updated": st.get("updatedReplicas", st.get("updatedNumberScheduled")),
    }
    strategy = ((spec.get("strategy") or {}) or (spec.get("updateStrategy") or {}) or {}).get("type")

    volumes = []
    for v in tmpl.get("volumes") or []:
        if not isinstance(v, dict):
            continue
        vtype = (
            "ConfigMap" if "configMap" in v else
            "Secret" if "secret" in v else
            "PVC" if "persistentVolumeClaim" in v else
            "emptyDir" if "emptyDir" in v else
            "diğer"
        )
        volumes.append({"name": v.get("name"), "type": vtype})

    services = [
        {
            "name": (s.get("metadata") or {}).get("name"),
            "type": (s.get("spec") or {}).get("type"),
            "cluster_ip": (s.get("spec") or {}).get("clusterIP"),
            "ports": [
                f"{p.get('port')}→{p.get('targetPort')}/{p.get('protocol', 'TCP')}"
                for p in ((s.get("spec") or {}).get("ports") or [])
            ],
        }
        for s in svcs
    ]
    route_list = [
        {
            "name": (r.get("metadata") or {}).get("name"),
            "host": (r.get("spec") or {}).get("host"),
            "tls": bool((r.get("spec") or {}).get("tls")),
        }
        for r in routes
    ]

    # Flat env for older UI paths
    env_flat = []
    for c in containers:
        for e in c.get("env") or []:
            env_flat.append({
                "container": c.get("name"),
                "name": e.get("name"),
                "value": e.get("value"),
                "from": e.get("from"),
                "ref": e.get("ref"),
                "secret": e.get("secret"),
            })

    configuration = {
        "Ad": name,
        "Namespace": namespace,
        "Tür": meta["label"],
        "Oluşturulma": _age(md.get("creationTimestamp")),
        "Güncelleme stratejisi": strategy or "—",
        "Replika": f"{replicas['ready']}/{replicas['desired'] if replicas['desired'] is not None else '?'} hazır"
                  + (f" · {replicas['available']} kullanılabilir" if replicas.get("available") is not None else ""),
        "Selector": ", ".join(f"{k}={v}" for k, v in sel.items()) or "—",
    }

    return {
        "kind": meta["label"],
        "kind_key": kind,
        "kind_id": kind,
        "name": name,
        "namespace": namespace,
        "status_badge": f"{replicas['ready']}/{replicas['desired'] if replicas['desired'] is not None else '?'} hazır",
        "labels": md.get("labels") or {},
        "annotations": {
            k: v for k, v in (md.get("annotations") or {}).items()
            if not k.startswith("kubectl.kubernetes.io/last-applied")
        },
        "created": md.get("creationTimestamp"),
        "created_at": md.get("creationTimestamp"),
        "age": _age(md.get("creationTimestamp")),
        "replicas": replicas,
        "strategy": strategy,
        "selector": sel,
        "containers": containers,
        "volumes": volumes,
        "pods": pods,
        "related_pods": pods,
        "services": services,
        "routes": route_list,
        "related_resources": (
            [{"kind": "Service", "name": s["name"], "info": f"{s.get('type')} · {s.get('cluster_ip')}", "age": ""} for s in services]
            + [{"kind": "Route", "name": r["name"], "info": r.get("host") or "", "age": ""} for r in route_list]
        ),
        "conditions": [
            {
                "type": x.get("type"),
                "status": x.get("status"),
                "reason": x.get("reason"),
                "message": (x.get("message") or "")[:200],
            }
            for x in (st.get("conditions") or [])
        ],
        "events": events[:30],
        "env": env_flat,
        "configuration": configuration,
        "metrics": None,
        "owner_refs": [],
    }


def resource_detail(
    client: OpenShiftClient,
    kind: str,
    name: str,
    namespace: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Deployment/DS/STS/Service/PVC/… için Atlas tarzı detay paketi."""
    if kind == "pods":
        if not namespace:
            return None
        return pod_detail(client, namespace, name)

    if kind in ("deployments", "statefulsets", "daemonsets"):
        if not namespace:
            return None
        return workload_detail(client, kind, namespace, name)

    meta_kind = RESOURCE_KINDS.get(kind)
    if not meta_kind:
        return None
    if meta_kind["ns"] and not namespace:
        return None
    path = (
        f"{meta_kind['path']}/namespaces/{namespace}/{meta_kind['resource']}/{name}"
        if meta_kind["ns"]
        else f"{meta_kind['path']}/{meta_kind['resource']}/{name}"
    )
    body = _get_json(client, path, timeout=30)
    if not body:
        return None

    meta = body.get("metadata") or {}
    spec = body.get("spec") or {}
    status = body.get("status") or {}
    k8s_kind = meta_kind["label"]

    conditions = []
    for c in status.get("conditions") or []:
        conditions.append({
            "type": c.get("type"),
            "status": c.get("status"),
            "reason": c.get("reason") or "",
            "message": (c.get("message") or "")[:400],
            "last_transition": c.get("lastTransitionTime"),
        })

    configuration: Dict[str, Any] = {
        "Ad": meta.get("name"),
        "Namespace": meta.get("namespace") or "—",
        "Tür": k8s_kind,
        "Oluşturulma": _age(meta.get("creationTimestamp")),
    }

    related_resources: List[Dict[str, Any]] = []
    related_pods: List[Dict[str, Any]] = []
    volumes = _volume_summaries_from_pod_template(spec) if kind in (
        "deployments", "statefulsets", "daemonsets",
    ) else []
    containers = _containers_from_pod_template(spec) if kind in (
        "deployments", "statefulsets", "daemonsets",
    ) else []
    status_badge = _resource_info(kind, body) or "—"

    if kind == "deployments":
        strategy = (spec.get("strategy") or {}).get("type") or "—"
        ready = status.get("readyReplicas") or 0
        desired = spec.get("replicas") if spec.get("replicas") is not None else 0
        avail = status.get("availableReplicas")
        updated = status.get("updatedReplicas")
        configuration["Güncelleme stratejisi"] = strategy
        configuration["Replika"] = (
            f"{ready}/{desired} hazır"
            + (f" · {avail} kullanılabilir" if avail is not None else "")
            + (f" · {updated} güncel" if updated is not None else "")
        )
        sel = (spec.get("selector") or {}).get("matchLabels") or {}
        configuration["Selector"] = ", ".join(f"{k}={v}" for k, v in sel.items()) or "—"
        status_badge = f"{ready}/{desired} hazır"
        # ReplicaSets
        rs_body = _get_json(
            client,
            f"/apis/apps/v1/namespaces/{namespace}/replicasets",
            params={"limit": 200},
            timeout=25,
        )
        for rs in (rs_body or {}).get("items") or []:
            owners = (rs.get("metadata") or {}).get("ownerReferences") or []
            if any(o.get("kind") == "Deployment" and o.get("name") == name for o in owners):
                rs_st = rs.get("status") or {}
                rs_spec = rs.get("spec") or {}
                related_resources.append({
                    "kind": "ReplicaSet",
                    "name": (rs.get("metadata") or {}).get("name"),
                    "info": f"{rs_st.get('readyReplicas') or 0}/{rs_spec.get('replicas') or 0}",
                    "age": _age((rs.get("metadata") or {}).get("creationTimestamp")),
                })
        related_pods = _related_pods(client, namespace or "", selector=sel)

    elif kind == "statefulsets":
        ready = status.get("readyReplicas") or 0
        desired = spec.get("replicas") if spec.get("replicas") is not None else 0
        configuration["Replika"] = f"{ready}/{desired} hazır"
        configuration["Servis adı"] = spec.get("serviceName") or "—"
        sel = (spec.get("selector") or {}).get("matchLabels") or {}
        configuration["Selector"] = ", ".join(f"{k}={v}" for k, v in sel.items()) or "—"
        status_badge = f"{ready}/{desired} hazır"
        related_pods = _related_pods(client, namespace or "", selector=sel)

    elif kind == "daemonsets":
        desired = status.get("desiredNumberScheduled") or 0
        ready = status.get("numberReady") or 0
        configuration["Replika"] = f"{ready}/{desired} hazır (node)"
        configuration["Güncel"] = status.get("currentNumberScheduled")
        configuration["Kullanılabilir"] = status.get("numberAvailable")
        sel = (spec.get("selector") or {}).get("matchLabels") or {}
        configuration["Selector"] = ", ".join(f"{k}={v}" for k, v in sel.items()) or "—"
        status_badge = f"{ready}/{desired} hazır"
        related_pods = _related_pods(client, namespace or "", selector=sel)

    elif kind == "services":
        configuration["Tür"] = f"Service / {spec.get('type') or 'ClusterIP'}"
        configuration["Cluster IP"] = spec.get("clusterIP") or "—"
        configuration["External IP"] = ", ".join(spec.get("externalIPs") or []) or "—"
        ports = []
        for p in spec.get("ports") or []:
            ports.append(
                f"{p.get('port')}"
                + (f":{p.get('targetPort')}" if p.get("targetPort") is not None else "")
                + f"/{p.get('protocol') or 'TCP'}"
                + (f" ({p.get('name')})" if p.get("name") else "")
            )
        configuration["Portlar"] = ", ".join(ports) or "—"
        sel = spec.get("selector") or {}
        configuration["Selector"] = ", ".join(f"{k}={v}" for k, v in sel.items()) or "—"
        status_badge = spec.get("type") or "ClusterIP"
        if sel:
            related_pods = _related_pods(client, namespace or "", selector=sel)

    elif kind == "routes":
        configuration["Host"] = spec.get("host") or "—"
        configuration["Path"] = spec.get("path") or "/"
        to = spec.get("to") or {}
        configuration["Hedef"] = f"{to.get('kind')}/{to.get('name')}" if to else "—"
        tls = spec.get("tls") or {}
        configuration["TLS"] = tls.get("termination") or "yok"
        status_badge = (status.get("ingress") or [{}])[0].get("host") or spec.get("host") or "—"

    elif kind == "persistentvolumeclaims":
        configuration["Faz"] = status.get("phase") or "—"
        configuration["Erişim"] = ", ".join(spec.get("accessModes") or []) or "—"
        configuration["StorageClass"] = (
            spec.get("storageClassName")
            or (meta.get("annotations") or {}).get("volume.beta.kubernetes.io/storage-class")
            or "—"
        )
        req = ((spec.get("resources") or {}).get("requests") or {}).get("storage")
        configuration["İstek"] = req or "—"
        configuration["Kapasite"] = ((status.get("capacity") or {}).get("storage")) or "—"
        configuration["Volume"] = spec.get("volumeName") or status.get("phase") or "—"
        status_badge = status.get("phase") or "—"
        volumes = [{
            "name": spec.get("volumeName") or name,
            "type": "PersistentVolume",
            "detail": req or "",
        }]

    elif kind == "persistentvolumes":
        configuration["Faz"] = status.get("phase") or "—"
        configuration["Kapasite"] = ((spec.get("capacity") or {}).get("storage")) or "—"
        configuration["Erişim"] = ", ".join(spec.get("accessModes") or []) or "—"
        configuration["Reclaim"] = spec.get("persistentVolumeReclaimPolicy") or "—"
        configuration["StorageClass"] = spec.get("storageClassName") or "—"
        claim = (spec.get("claimRef") or {})
        configuration["Claim"] = (
            f"{claim.get('namespace')}/{claim.get('name')}" if claim.get("name") else "—"
        )
        status_badge = status.get("phase") or "—"

    elif kind == "configmaps":
        data = body.get("data") or {}
        binary = body.get("binaryData") or {}
        configuration["Anahtar sayısı"] = len(data) + len(binary)
        configuration["Anahtarlar"] = ", ".join(list(data.keys())[:20]) or "—"
        status_badge = f"{len(data)} key"
        related_resources = [
            {"kind": "Key", "name": k, "info": f"{len(str(v))} karakter", "age": ""}
            for k, v in list(data.items())[:50]
        ]

    elif kind == "nodes":
        configuration["Tür"] = "Node"
        addr = {a.get("type"): a.get("address") for a in status.get("addresses") or []}
        configuration["Internal IP"] = addr.get("InternalIP") or "—"
        configuration["Hostname"] = addr.get("Hostname") or meta.get("name")
        configuration["OS"] = (status.get("nodeInfo") or {}).get("osImage") or "—"
        configuration["Kernel"] = (status.get("nodeInfo") or {}).get("kernelVersion") or "—"
        configuration["Kubelet"] = (status.get("nodeInfo") or {}).get("kubeletVersion") or "—"
        cap = status.get("capacity") or {}
        configuration["CPU / RAM"] = f"{cap.get('cpu', '—')} / {cap.get('memory', '—')}"
        ready = next((c for c in conditions if c.get("type") == "Ready"), None)
        status_badge = "Ready" if ready and ready.get("status") == "True" else "NotReady"

    owners = []
    for o in meta.get("ownerReferences") or []:
        owners.append({
            "kind": o.get("kind"),
            "name": o.get("name"),
            "api_version": o.get("apiVersion"),
            "controller": o.get("controller"),
        })

    events = _events_for(
        client,
        namespace if meta_kind["ns"] else None,
        kind=k8s_kind,
        name=name,
    )

    env_flat = []
    for c in containers:
        for e in c.get("env") or []:
            env_flat.append({
                "container": c.get("name"),
                "name": e.get("name"),
                "value": e.get("value"),
            })

    return {
        "kind": k8s_kind,
        "kind_id": kind,
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "status_badge": status_badge,
        "age": _age(meta.get("creationTimestamp")),
        "created_at": meta.get("creationTimestamp"),
        "labels": meta.get("labels") or {},
        "annotations": {
            k: (str(v)[:120] + ("…" if len(str(v)) > 120 else ""))
            for k, v in list((meta.get("annotations") or {}).items())[:40]
        },
        "owner_refs": owners,
        "conditions": conditions,
        "configuration": configuration,
        "volumes": volumes,
        "containers": containers,
        "env": env_flat,
        "related_pods": related_pods,
        "related_resources": related_resources,
        "events": events[:30],
        "metrics": None,
    }



def pod_logs(
    client: OpenShiftClient,
    namespace: str,
    pod: str,
    *,
    container: Optional[str] = None,
    tail: int = 300,
    previous: bool = False,
    timestamps: bool = True,
) -> Dict[str, Any]:
    tail = max(1, min(int(tail or 300), 5000))
    params: Dict[str, Any] = {
        "tailLines": tail,
        "timestamps": "true" if timestamps else "false",
    }
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
        # Multi-container: API 400 "choose one of: [a b c]" — ilk app container'ı dene
        if r.status_code == 400 and not container:
            import re
            msg = (r.text or "")
            m = re.search(r"choose one of:\s*\[([^\]]+)\]", msg)
            if m:
                names = [x.strip() for x in m.group(1).split() if x.strip()]
                # init-* / *-init tercih etme
                preferred = next(
                    (n for n in names if not n.startswith("init-") and "init-" not in n),
                    names[0] if names else None,
                )
                if preferred:
                    retry = pod_logs(
                        client, namespace, pod,
                        container=preferred, tail=tail, previous=previous, timestamps=timestamps,
                    )
                    if retry.get("ok"):
                        retry["container"] = preferred
                        retry["containers"] = names
                        retry["auto_container"] = True
                    else:
                        retry["containers"] = names
                    return retry
                return {
                    "ok": False, "logs": "",
                    "error": "Pod çok container’lı; container seçin",
                    "containers": names,
                }
        if r.status_code != 200:
            return {"ok": False, "logs": "", "error": f"HTTP {r.status_code}: {(r.text or '')[:200]}"}
        out = {"ok": True, "logs": r.text or "", "error": None}
        if container:
            out["container"] = container
        return out
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
