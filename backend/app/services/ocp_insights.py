"""OpenShift platform karar katmanı — aynı bulgu motoru, platform="ocp".

Kaynak: yalnız kube API (bastion üzerinden erişilen API token'ı); node SSH yok.
Kontroller:
  capacity  : worker request doluluğu, worker N+1 (en büyük worker drenajı), namespace kotası
  reclaim   : Pending/Lost PVC, hiçbir pod'un bağlamadığı PVC, request ≫ kullanım (metrics-server anlık)
  health    : ClusterOperator Available/Degraded, node NotReady / pressure
  drift     : MachineConfigPool Degraded; yapılandırma geçmişi (node/MCP/operatör/cluster config) + onaylı baseline sapması
  upgrade   : ClusterVersion availableUpdates
  compliance: Compliance Operator ComplianceCheckResult (kuruluysa)
Kapasite / geri kazanım özetleri InfraCheckRun.stats içinde saklanır (UI canlı çağrı yapmaz).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraCheckRun
from app.models.openshift import OpenShiftCluster
from app.services.findings.store import FindingDraft, persist_findings, utcnow

logger = logging.getLogger(__name__)

PLATFORM = "ocp"
REQ_WARN_PCT = 85.0
QUOTA_WARN_PCT = 90.0
OVER_REQ_RATIO = 0.2
OVER_REQ_MIN_CPU_M = 1000.0
OVER_REQ_MIN_MEM_GB = 2.0
_CATEGORIES = ("capacity", "reclaim", "health", "drift", "upgrade", "compliance")


def _items(client, path: str, params: Optional[dict] = None, cap: int = 20000) -> Optional[List[Dict[str, Any]]]:
    """List + continue token; 404/403 → None (API/operatör yok)."""
    out: List[Dict[str, Any]] = []
    p = dict(params or {})
    p.setdefault("limit", 500)
    while True:
        r = client._get(path, params=p, timeout=60)
        if r.status_code in (403, 404):
            return None
        if r.status_code != 200:
            raise RuntimeError(f"{path} HTTP {r.status_code}")
        body = r.json() or {}
        out.extend(body.get("items") or [])
        cont = (body.get("metadata") or {}).get("continue")
        if not cont or len(out) >= cap:
            return out
        p["continue"] = cont


def _cpu_m(v) -> float:
    from app.services.openshift.cluster_ops import _cpu_millicores
    return _cpu_millicores(v)


def _mem_gb(v) -> float:
    from app.services.openshift.ocp_client import OpenShiftClient
    return float(OpenShiftClient._parse_quantity(v) or 0.0)


def _is_worker(labels: Dict[str, str]) -> bool:
    """Compact (3 node) kümelerde master'lar da worker etiketini taşır → worker sayılır."""
    return "node-role.kubernetes.io/worker" in labels


def _pod_requests(pod: Dict[str, Any]) -> Tuple[float, float]:
    spec = pod.get("spec") or {}
    cpu = mem = 0.0
    for c in spec.get("containers") or []:
        req = ((c.get("resources") or {}).get("requests") or {})
        cpu += _cpu_m(req.get("cpu"))
        mem += _mem_gb(req.get("memory"))
    init_cpu = max((_cpu_m(((c.get("resources") or {}).get("requests") or {}).get("cpu"))
                    for c in spec.get("initContainers") or []), default=0.0)
    init_mem = max((_mem_gb(((c.get("resources") or {}).get("requests") or {}).get("memory"))
                    for c in spec.get("initContainers") or []), default=0.0)
    return max(cpu, init_cpu), max(mem, init_mem)


def _r(v, n=1):
    return round(v, n) if isinstance(v, (int, float)) else v


_CLUSTER_CONFIG_PATHS = {
    "proxy": "/apis/config.openshift.io/v1/proxies/cluster",
    "oauth": "/apis/config.openshift.io/v1/oauths/cluster",
    "apiserver": "/apis/config.openshift.io/v1/apiservers/cluster",
    "scheduler": "/apis/config.openshift.io/v1/schedulers/cluster",
    "ingress": "/apis/operator.openshift.io/v1/namespaces/openshift-ingress-operator/ingresscontrollers/default",
}


def _get_obj(client, path: str) -> Optional[Dict[str, Any]]:
    """Tek nesne; yetki/yok → None (opsiyonel yapılandırma)."""
    try:
        r = client._get(path, timeout=20)
        return (r.json() or {}) if r.status_code == 200 else None
    except Exception as exc:
        logger.debug("OCP GET %s: %s", path, exc)
        return None


def collect(cluster: OpenShiftCluster) -> Dict[str, Any]:
    from app.services.openshift.cluster_ops import client_from_cluster
    client = client_from_cluster(cluster)
    nodes = _items(client, "/api/v1/nodes") or []
    pods = _items(client, "/api/v1/pods", {"fieldSelector": "status.phase!=Succeeded,status.phase!=Failed"}) or []
    pvcs = _items(client, "/api/v1/persistentvolumeclaims") or []
    quotas = _items(client, "/api/v1/resourcequotas") or []
    cos = _items(client, "/apis/config.openshift.io/v1/clusteroperators")
    mcps = _items(client, "/apis/machineconfiguration.openshift.io/v1/machineconfigpools")
    ccr = _items(client, "/apis/compliance.openshift.io/v1alpha1/compliancecheckresults")
    metrics = None
    try:
        metrics = _items(client, "/apis/metrics.k8s.io/v1beta1/pods")
    except Exception as exc:
        logger.debug("metrics.k8s.io okunamadı: %s", exc)
    cv = None
    try:
        r = client._get("/apis/config.openshift.io/v1/clusterversions/version", timeout=20)
        if r.status_code == 200:
            cv = r.json() or {}
    except Exception:
        cv = None
    cfg = {name: _get_obj(client, path) for name, path in _CLUSTER_CONFIG_PATHS.items()}
    return {"nodes": nodes, "pods": pods, "pvcs": pvcs, "quotas": quotas, "cos": cos, "mcps": mcps,
            "ccr": ccr, "metrics": metrics, "cv": cv, "cfg": cfg}


def evaluate(cluster: OpenShiftCluster, col: Dict[str, Any]) -> Tuple[List[FindingDraft], Dict[str, Any]]:
    cname = cluster.name
    drafts: List[FindingDraft] = []
    # ── Kapasite ─────────────────────────────────────────────────────────────
    workers: Dict[str, Dict[str, Any]] = {}
    for n in col["nodes"]:
        meta = n.get("metadata") or {}
        labels = meta.get("labels") or {}
        st = n.get("status") or {}
        conds = {c.get("type"): c for c in st.get("conditions") or []}
        name = meta.get("name") or ""
        ready = (conds.get("Ready") or {}).get("status") == "True"
        bad = [t for t in ("MemoryPressure", "DiskPressure", "PIDPressure") if (conds.get(t) or {}).get("status") == "True"]
        drafts.append(FindingDraft(
            "ocp.node.condition", "node", f"node:{name}", name,
            "fail" if (not ready or bad) else "pass",
            evidence={"ready": ready, "pressure": bad, "unschedulable": bool((n.get("spec") or {}).get("unschedulable"))},
            detail=("NotReady" if not ready else "") + (f" baskı: {', '.join(bad)}" if bad else ""),
            cluster_name=cname, severity="critical" if not ready else None))
        if _is_worker(labels):
            alloc = st.get("allocatable") or {}
            workers[name] = {"name": name, "ready": ready,
                             "schedulable": not (n.get("spec") or {}).get("unschedulable"),
                             "cpu_m": _cpu_m(alloc.get("cpu")), "mem_gb": _mem_gb(alloc.get("memory")),
                             "req_cpu_m": 0.0, "req_mem_gb": 0.0, "pods": 0}
    pvc_used: set = set()
    ns_req: Dict[str, Dict[str, float]] = defaultdict(lambda: {"cpu_m": 0.0, "mem_gb": 0.0})
    for p in col["pods"]:
        meta = p.get("metadata") or {}
        ns = meta.get("namespace") or ""
        for v in (p.get("spec") or {}).get("volumes") or []:
            claim = (v.get("persistentVolumeClaim") or {}).get("claimName")
            if claim:
                pvc_used.add(f"{ns}/{claim}")
        cpu, mem = _pod_requests(p)
        ns_req[ns]["cpu_m"] += cpu
        ns_req[ns]["mem_gb"] += mem
        node = (p.get("spec") or {}).get("nodeName")
        if node in workers:
            workers[node]["req_cpu_m"] += cpu
            workers[node]["req_mem_gb"] += mem
            workers[node]["pods"] += 1
    usable = [w for w in workers.values() if w["ready"] and w["schedulable"]]
    tot_cpu = sum(w["cpu_m"] for w in usable)
    tot_mem = sum(w["mem_gb"] for w in usable)
    req_cpu = sum(w["req_cpu_m"] for w in workers.values())
    req_mem = sum(w["req_mem_gb"] for w in workers.values())
    cpu_pct = 100.0 * req_cpu / tot_cpu if tot_cpu else None
    mem_pct = 100.0 * req_mem / tot_mem if tot_mem else None
    cap: Dict[str, Any] = {
        "workers_total": len(workers), "workers_usable": len(usable),
        "allocatable": {"cpu_cores": _r(tot_cpu / 1000.0), "memory_gb": _r(tot_mem)},
        "requested": {"cpu_cores": _r(req_cpu / 1000.0), "memory_gb": _r(req_mem)},
        "request_pct": {"cpu": _r(cpu_pct), "memory": _r(mem_pct)},
        "workers": sorted([{**w, "cpu_cores": _r(w["cpu_m"] / 1000.0), "req_cpu_cores": _r(w["req_cpu_m"] / 1000.0),
                            "mem_gb": _r(w["mem_gb"]), "req_mem_gb": _r(w["req_mem_gb"]),
                            "mem_pct": _r(100.0 * w["req_mem_gb"] / w["mem_gb"]) if w["mem_gb"] else None,
                            "cpu_pct": _r(100.0 * w["req_cpu_m"] / w["cpu_m"]) if w["cpu_m"] else None}
                           for w in workers.values()], key=lambda x: -(x.get("mem_pct") or 0)),
    }
    if usable:
        hot = max(p for p in (cpu_pct or 0, mem_pct or 0))
        drafts.append(FindingDraft(
            "ocp.cluster.request_pressure", "cluster", "cluster", cname,
            "fail" if hot > REQ_WARN_PCT else "pass", evidence=cap["request_pct"],
            detail=f"Request/allocatable: CPU %{_r(cpu_pct)}, Memory %{_r(mem_pct)}", cluster_name=cname))
    if len(usable) >= 2:
        big = max(usable, key=lambda w: w["mem_gb"])
        rem_mem = tot_mem - big["mem_gb"]
        rem_cpu = tot_cpu - big["cpu_m"]
        n1_mem = 100.0 * req_mem / rem_mem if rem_mem > 0 else None
        n1_cpu = 100.0 * req_cpu / rem_cpu if rem_cpu > 0 else None
        fail = (n1_mem is None or n1_mem > 100) or (n1_cpu is not None and n1_cpu > 100)
        cap["n_plus_one"] = {"largest_worker": big["name"], "memory_after_pct": _r(n1_mem),
                             "cpu_after_pct": _r(n1_cpu), "status": "fail" if fail else (
                                 "warn" if max(n1_mem or 0, n1_cpu or 0) > 90 else "ok")}
        drafts.append(FindingDraft(
            "ocp.cluster.n_plus_one", "cluster", "cluster", cname, "fail" if fail else "pass",
            evidence=cap["n_plus_one"],
            detail=f"{big['name']} drene edilirse request: Memory %{_r(n1_mem)}, CPU %{_r(n1_cpu)}",
            cluster_name=cname))
    else:
        cap["n_plus_one"] = {"status": "single_worker" if usable else "no_data"}
    for q in col["quotas"]:
        meta = q.get("metadata") or {}
        st = q.get("status") or {}
        hard, used = st.get("hard") or {}, st.get("used") or {}
        worst, worst_key = 0.0, None
        for k, hv in hard.items():
            parse = _cpu_m if "cpu" in k else (_mem_gb if ("memory" in k or "storage" in k) else
                                                (lambda x: float(str(x or 0).rstrip("k") or 0)))
            try:
                h, u = parse(hv), parse(used.get(k, 0))
            except (TypeError, ValueError):
                continue
            if h and 100.0 * u / h > worst:
                worst, worst_key = 100.0 * u / h, k
        ref = f"quota:{meta.get('namespace')}/{meta.get('name')}"
        drafts.append(FindingDraft(
            "ocp.namespace.quota", "namespace", ref, f"{meta.get('namespace')}/{meta.get('name')}",
            "fail" if worst > QUOTA_WARN_PCT else "pass", evidence={"key": worst_key, "pct": _r(worst)},
            detail=f"{worst_key}: %{_r(worst)}" if worst_key else "", cluster_name=cname))
    # ── Geri kazanım ─────────────────────────────────────────────────────────
    rec = {"unbound": [], "unused": [], "over_request": []}
    for pvc in col["pvcs"]:
        meta = pvc.get("metadata") or {}
        key = f"{meta.get('namespace')}/{meta.get('name')}"
        phase = (pvc.get("status") or {}).get("phase")
        size = _mem_gb(((pvc.get("spec") or {}).get("resources") or {}).get("requests", {}).get("storage"))
        sc = (pvc.get("spec") or {}).get("storageClassName")
        ev = {"phase": phase, "size_gb": _r(size), "storage_class": sc, "created": meta.get("creationTimestamp")}
        if phase in ("Pending", "Lost"):
            rec["unbound"].append({"pvc": key, **ev})
            drafts.append(FindingDraft("ocp.pvc.unbound", "pvc", f"pvc:{key}", key, "fail", evidence=ev,
                                       detail=f"{phase} · {sc or '-'}", cluster_name=cname))
        elif key not in pvc_used and not (meta.get("labels") or {}).get("cdi.kubevirt.io/dataImportCron"):
            owners = [o.get("kind") for o in meta.get("ownerReferences") or []]
            if "DataVolume" in owners or "VirtualMachine" in owners:
                continue  # KubeVirt diskleri: ocp_virt reclaim tarafında değerlendirilir
            rec["unused"].append({"pvc": key, **ev})
            drafts.append(FindingDraft("ocp.pvc.unused", "pvc", f"pvc:{key}", key, "fail", evidence=ev,
                                       detail=f"{_r(size)} GB · {sc or '-'}", cluster_name=cname))
    if col.get("metrics") is not None:
        usage: Dict[str, Dict[str, float]] = defaultdict(lambda: {"cpu_m": 0.0, "mem_gb": 0.0})
        for m in col["metrics"]:
            ns = (m.get("metadata") or {}).get("namespace") or ""
            for c in m.get("containers") or []:
                u = c.get("usage") or {}
                usage[ns]["cpu_m"] += _cpu_m(u.get("cpu"))
                usage[ns]["mem_gb"] += _mem_gb(u.get("memory"))
        for ns, rq in ns_req.items():
            if ns.startswith(("openshift", "kube-")):
                continue
            u = usage.get(ns) or {"cpu_m": 0.0, "mem_gb": 0.0}
            over_cpu = rq["cpu_m"] >= OVER_REQ_MIN_CPU_M and u["cpu_m"] < rq["cpu_m"] * OVER_REQ_RATIO
            over_mem = rq["mem_gb"] >= OVER_REQ_MIN_MEM_GB and u["mem_gb"] < rq["mem_gb"] * OVER_REQ_RATIO
            if over_cpu or over_mem:
                ev = {"req_cpu_cores": _r(rq["cpu_m"] / 1000.0), "use_cpu_cores": _r(u["cpu_m"] / 1000.0, 2),
                      "req_mem_gb": _r(rq["mem_gb"]), "use_mem_gb": _r(u["mem_gb"])}
                rec["over_request"].append({"namespace": ns, **ev})
                drafts.append(FindingDraft(
                    "ocp.pod.over_request", "namespace", f"ns:{ns}", ns, "fail", evidence=ev,
                    detail=(f"Request CPU {ev['req_cpu_cores']} / kullanım {ev['use_cpu_cores']} çekirdek; "
                            f"Memory {ev['req_mem_gb']} / {ev['use_mem_gb']} GB (anlık metrics-server)"),
                    cluster_name=cname))
    # ── Sağlık / sapma / yükseltme / uyum ────────────────────────────────────
    for co in col.get("cos") or []:
        name = (co.get("metadata") or {}).get("name") or ""
        conds = {c.get("type"): c for c in (co.get("status") or {}).get("conditions") or []}
        avail = (conds.get("Available") or {}).get("status") != "False"
        deg = (conds.get("Degraded") or {}).get("status") == "True"
        msg = ((conds.get("Degraded") or {}).get("message") or (conds.get("Available") or {}).get("message") or "")[:300]
        drafts.append(FindingDraft("ocp.operator.health", "operator", f"co:{name}", name,
                                   "fail" if (deg or not avail) else "pass",
                                   evidence={"available": avail, "degraded": deg}, detail=msg, cluster_name=cname,
                                   severity="critical" if not avail else None))
    for mcp in col.get("mcps") or []:
        name = (mcp.get("metadata") or {}).get("name") or ""
        st = mcp.get("status") or {}
        conds = {c.get("type"): c for c in st.get("conditions") or []}
        deg = (conds.get("Degraded") or {}).get("status") == "True"
        ev = {"machines": st.get("machineCount"), "updated": st.get("updatedMachineCount"),
              "degraded_machines": st.get("degradedMachineCount"),
              "rendered": ((st.get("configuration") or {}).get("name"))}
        drafts.append(FindingDraft("ocp.mcp.degraded", "mcp", f"mcp:{name}", name,
                                   "fail" if (deg or (st.get("degradedMachineCount") or 0) > 0) else "pass",
                                   evidence=ev, detail=((conds.get("Degraded") or {}).get("message") or "")[:300],
                                   cluster_name=cname))
    cv = col.get("cv") or {}
    if cv:
        st = cv.get("status") or {}
        cur = ((st.get("desired") or {}).get("version")) or cluster.version
        ups = [u.get("version") for u in st.get("availableUpdates") or [] if u.get("version")]
        drafts.append(FindingDraft("ocp.cluster.update_available", "cluster", "cluster:version", cname,
                                   "fail" if ups else "pass",
                                   evidence={"current": cur, "channel": (cv.get("spec") or {}).get("channel"),
                                             "available": ups[:10]},
                                   detail=(f"{cur} → {', '.join(ups[:5])}" if ups else f"{cur} güncel"),
                                   cluster_name=cname))
    ccr = col.get("ccr")
    comp = {"installed": ccr is not None, "fail": 0, "pass": 0, "manual": 0}
    for r in ccr or []:
        meta = r.get("metadata") or {}
        status = str(r.get("status") or "").upper()
        if status in ("PASS",):
            comp["pass"] += 1
        elif status in ("MANUAL", "NOT-APPLICABLE", "INFO"):
            comp["manual"] += 1
            continue
        elif status in ("FAIL", "ERROR", "INCONSISTENT"):
            comp["fail"] += 1
        else:
            continue
        sev = str(r.get("severity") or "medium").lower()
        drafts.append(FindingDraft(
            "ocp.compliance.result", "rule", f"ccr:{meta.get('name')}", meta.get("name") or "",
            "pass" if status == "PASS" else "fail",
            evidence={"status": status, "scan": (meta.get("labels") or {}).get("compliance.openshift.io/scan-name"),
                      "rule": (meta.get("annotations") or {}).get("compliance.openshift.io/rule")},
            detail=(r.get("description") or "")[:400], cluster_name=cname,
            severity=sev if sev in ("low", "medium", "high", "critical") else None,
            title=f"Compliance: {(meta.get('annotations') or {}).get('compliance.openshift.io/rule') or meta.get('name')}",
            recommendation=(r.get("instructions") or "")[:600] or None))
    reclaim_summary = {
        "unbound": len(rec["unbound"]), "unused": len(rec["unused"]),
        "unused_gb": _r(sum(x.get("size_gb") or 0 for x in rec["unused"])),
        "over_request_namespaces": len(rec["over_request"]),
        "metrics_available": col.get("metrics") is not None,
    }
    stats = {"capacity": cap, "reclaim": {"summary": reclaim_summary, **{k: v[:200] for k, v in rec.items()}},
             "compliance": comp, "version": (cv.get("status") or {}).get("desired", {}).get("version") if cv else None}
    return drafts, stats


def _mask_url(v: Any) -> Any:
    """Proxy URL'lerinde kullanıcı:parola kısmını sakla."""
    from urllib.parse import urlsplit, urlunsplit
    if not isinstance(v, str) or "@" not in v:
        return v
    try:
        u = urlsplit(v)
        host = u.netloc.rsplit("@", 1)[-1]
        return urlunsplit((u.scheme, f"***@{host}", u.path, u.query, u.fragment))
    except ValueError:
        return "***"


def config_snapshots(cluster: OpenShiftCluster, col: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Değişiklik geçmişi için normalize yapılandırma. Gürültü (heartbeat, resourceVersion) hash'e girmez."""
    out: List[Dict[str, Any]] = []
    cname = cluster.name
    cv = col.get("cv") or {}
    if cv:
        st, sp = cv.get("status") or {}, cv.get("spec") or {}
        out.append({"kind": "cluster", "ref": "version", "name": cname,
                    "config": {"version": (st.get("desired") or {}).get("version"),
                               "image": (st.get("desired") or {}).get("image"),
                               "channel": sp.get("channel"), "upstream": sp.get("upstream")},
                    "state": {"history": len(st.get("history") or [])}})
    for n in col.get("nodes") or []:
        meta, st = n.get("metadata") or {}, n.get("status") or {}
        info = st.get("nodeInfo") or {}
        ann = meta.get("annotations") or {}
        roles = sorted(k.split("/", 1)[1] for k in (meta.get("labels") or {}) if k.startswith("node-role.kubernetes.io/"))
        taints = sorted(f"{t.get('key')}:{t.get('effect')}" for t in (n.get("spec") or {}).get("taints") or [])
        conds = {c.get("type"): c.get("status") for c in st.get("conditions") or []}
        out.append({"kind": "node", "ref": meta.get("name") or "", "name": meta.get("name") or "",
                    "config": {"roles": roles, "taints": taints, "kubelet": info.get("kubeletVersion"),
                               "os_image": info.get("osImage"), "kernel": info.get("kernelVersion"),
                               "runtime": info.get("containerRuntimeVersion"),
                               "unschedulable": bool((n.get("spec") or {}).get("unschedulable")),
                               "mc_current": ann.get("machineconfiguration.openshift.io/currentConfig"),
                               "mc_desired": ann.get("machineconfiguration.openshift.io/desiredConfig")},
                    "state": {"ready": conds.get("Ready") == "True"}})
    for m in col.get("mcps") or []:
        meta, st, sp = m.get("metadata") or {}, m.get("status") or {}, m.get("spec") or {}
        conf = st.get("configuration") or {}
        out.append({"kind": "mcp", "ref": meta.get("name") or "", "name": meta.get("name") or "",
                    "config": {"rendered": conf.get("name"), "paused": bool(sp.get("paused")),
                               "max_unavailable": sp.get("maxUnavailable"),
                               "sources": sorted(x.get("name") for x in conf.get("source") or [] if x.get("name"))},
                    "state": {"machines": st.get("machineCount"), "updated": st.get("updatedMachineCount"),
                              "degraded": st.get("degradedMachineCount")}})
    for co in col.get("cos") or []:
        meta, st = co.get("metadata") or {}, co.get("status") or {}
        out.append({"kind": "operator", "ref": meta.get("name") or "", "name": meta.get("name") or "",
                    "config": {"versions": {v.get("name"): v.get("version") for v in st.get("versions") or []}},
                    "state": {}})
    cfg = col.get("cfg") or {}
    px = cfg.get("proxy")
    if px:
        sp = px.get("spec") or {}
        out.append({"kind": "platform", "ref": "config:proxy", "name": "Proxy",
                    "config": {"httpProxy": _mask_url(sp.get("httpProxy")), "httpsProxy": _mask_url(sp.get("httpsProxy")),
                               "noProxy": sp.get("noProxy"), "trustedCA": (sp.get("trustedCA") or {}).get("name")},
                    "state": {}})
    oa = cfg.get("oauth")
    if oa:
        idps = sorted(f"{i.get('name')}:{i.get('type')}:{i.get('mappingMethod')}"
                      for i in (oa.get("spec") or {}).get("identityProviders") or [])
        out.append({"kind": "platform", "ref": "config:oauth", "name": "OAuth",
                    "config": {"identityProviders": idps,
                               "tokenConfig": (oa.get("spec") or {}).get("tokenConfig")}, "state": {}})
    ap = cfg.get("apiserver")
    if ap:
        sp = ap.get("spec") or {}
        out.append({"kind": "platform", "ref": "config:apiserver", "name": "APIServer",
                    "config": {"tlsSecurityProfile": (sp.get("tlsSecurityProfile") or {}).get("type"),
                               "audit": (sp.get("audit") or {}).get("profile"),
                               "encryption": (sp.get("encryption") or {}).get("type"),
                               "servingCerts": sorted(c.get("servingCertificate", {}).get("name") or ""
                                                      for c in (sp.get("servingCerts") or {}).get("namedCertificates") or [])},
                    "state": {}})
    sc = cfg.get("scheduler")
    if sc:
        sp = sc.get("spec") or {}
        out.append({"kind": "platform", "ref": "config:scheduler", "name": "Scheduler",
                    "config": {"mastersSchedulable": sp.get("mastersSchedulable"), "profile": sp.get("profile")},
                    "state": {}})
    ig = cfg.get("ingress")
    if ig:
        sp = ig.get("spec") or {}
        out.append({"kind": "platform", "ref": "config:ingress", "name": "IngressController/default",
                    "config": {"replicas": sp.get("replicas"), "domain": sp.get("domain"),
                               "defaultCertificate": (sp.get("defaultCertificate") or {}).get("name"),
                               "publishing": (sp.get("endpointPublishingStrategy") or {}).get("type")},
                    "state": {}})
    return out


def save_snapshots(db: Session, cluster: OpenShiftCluster, col: Dict[str, Any], now) -> int:
    from app.services.findings import store
    snaps = config_snapshots(cluster, col)
    for sn in snaps:
        store.save_config_snapshot(db, platform=PLATFORM, source_id=cluster.id, entity_kind=sn["kind"],
                                   entity_ref=sn["ref"], entity_name=sn["name"], cluster_name=cluster.name,
                                   config=sn["config"], state=sn["state"], now=now)
    return len(snaps)


def run_for_cluster(db: Session, cluster: OpenShiftCluster) -> Dict[str, Any]:
    now = utcnow()
    run = InfraCheckRun(platform=PLATFORM, source_id=cluster.id, source_name=cluster.name, kind="full",
                        status="running", started_at=now, stats={})
    db.add(run)
    db.commit()
    try:
        col = collect(cluster)
        drafts, stats = evaluate(cluster, col)
        stats["config_snapshots"] = save_snapshots(db, cluster, col, now)
        from app.services import virt_config_drift
        drafts.extend(virt_config_drift.drift_findings(db, PLATFORM, cluster.id))
        cats = list(_CATEGORIES)
        if col.get("ccr") is None:
            cats.remove("compliance")
        res = persist_findings(db, platform=PLATFORM, source_id=cluster.id, source_name=cluster.name,
                               categories=cats, drafts=drafts, run_id=run.id, now=now)
        stats.update(res)
        stats["findings"] = sum(1 for d in drafts if d.result == "fail")
        run.status = "ok"
        run.stats = stats
    except Exception as exc:
        db.rollback()
        logger.warning("OCP insights %s: %s", cluster.name, exc)
        run = db.query(InfraCheckRun).filter(InfraCheckRun.id == run.id).first() or run
        run.status = "error"
        run.error = str(exc)[:1000]
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return {"platform": PLATFORM, "source_id": cluster.id, "source_name": cluster.name,
            "status": run.status, "error": run.error, "run_id": run.id}


def run_ocp_cycle(db: Session, cluster_id: Optional[int] = None) -> List[Dict[str, Any]]:
    q = db.query(OpenShiftCluster)
    if cluster_id:
        q = q.filter(OpenShiftCluster.id == cluster_id)
    return [run_for_cluster(db, c) for c in q.order_by(OpenShiftCluster.id).all()]


def latest_stats(db: Session, cluster_id: Optional[int] = None) -> List[Dict[str, Any]]:
    out = []
    q = db.query(OpenShiftCluster)
    if cluster_id:
        q = q.filter(OpenShiftCluster.id == cluster_id)
    for c in q.order_by(OpenShiftCluster.name).all():
        run = (db.query(InfraCheckRun)
               .filter(InfraCheckRun.platform == PLATFORM, InfraCheckRun.source_id == c.id,
                       InfraCheckRun.status == "ok")
               .order_by(InfraCheckRun.started_at.desc()).first())
        out.append({"cluster_id": c.id, "cluster": c.name, "version": c.version,
                    "as_of": run.finished_at.isoformat() if run and run.finished_at else None,
                    "stats": (run.stats if run else None) or {}})
    return out
