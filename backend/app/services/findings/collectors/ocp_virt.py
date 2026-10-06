"""OpenShift Virtualization toplayıcısı (kube API, salt-okunur GET).

Bastion üzerinden erişilen API URL'i kullanılır; master/worker'a SSH yoktur.
VirtualMachine ham spec'i (evictionStrategy, runStrategy, volumes),
HyperConverged durumu ve DataVolume/PVC envanteri okunur.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.services.findings.collectors import as_list

logger = logging.getLogger(__name__)


def _client(db: Session, hv: Hypervisor):
    from app.services.openshift_virt_host_metrics import _resolve_cluster
    cluster = _resolve_cluster(db, hv)
    if cluster is not None:
        from app.services.openshift.cluster_ops import kubevirt_client_from_cluster
        return kubevirt_client_from_cluster(cluster), cluster
    from app.services.hypervisor_credentials import hv_password, hv_token, plain
    from app.services.openshift.kubevirt_client import KubeVirtClient
    cc = hv.connection_config or {}
    use_creds = bool(cc.get("username")) and bool(cc.get("password") or hv.password)
    return KubeVirtClient(
        api_url=cc.get("api_url") or hv.hostname or hv.ip_address,
        token="" if use_creds else hv_token(hv),
        username=cc.get("username") or "",
        password=plain(cc.get("password")) or hv_password(hv),
        verify_ssl=bool(cc.get("verify_ssl", False)),
    ), None


def _items(client, path: str, timeout: int = 45) -> Optional[List[Dict[str, Any]]]:
    out: List[Dict[str, Any]] = []
    cont = None
    for _ in range(40):
        params: Dict[str, Any] = {"limit": 500}
        if cont:
            params["continue"] = cont
        try:
            r = client._get(path, params=params, timeout=timeout)
        except Exception as exc:
            logger.info("kube GET %s: %s", path, exc)
            return None
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            logger.info("kube GET %s HTTP %s", path, r.status_code)
            return None
        body = r.json() or {}
        out.extend(body.get("items") or [])
        cont = (body.get("metadata") or {}).get("continue")
        if not cont:
            break
    return out


def _cond(obj: Dict[str, Any], ctype: str) -> Optional[Dict[str, Any]]:
    for c in as_list(((obj.get("status") or {}).get("conditions"))):
        if isinstance(c, dict) and c.get("type") == ctype:
            return c
    return None


def _qty_gb(v: Any) -> Optional[float]:
    from app.services.openshift.ocp_client import OpenShiftClient
    try:
        return round(OpenShiftClient._parse_quantity(v), 2) if v is not None else None
    except Exception:
        return None


def collect(db: Session, hv: Hypervisor, *, file_scan: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False, "error": None, "clusters": [], "hosts": [], "datastores": [], "vms": [],
        "platform": {}, "files": None, "file_scan": None, "unsupported_paths": [],
    }
    client, cluster = _client(db, hv)
    vms_raw = _items(client, "/apis/kubevirt.io/v1/virtualmachines")
    if vms_raw is None:
        out["error"] = "KubeVirt VirtualMachine listesi okunamadı (token / RBAC)"
        return out
    vmis = _items(client, "/apis/kubevirt.io/v1/virtualmachineinstances") or []
    vmi_by = {f"{(i.get('metadata') or {}).get('namespace')}/{(i.get('metadata') or {}).get('name')}": i for i in vmis}

    kv = _items(client, "/apis/kubevirt.io/v1/kubevirts") or []
    default_eviction = None
    for k in kv:
        default_eviction = (((k.get("spec") or {}).get("configuration") or {}).get("evictionStrategy")) \
            or default_eviction
    hco = _items(client, "/apis/hco.kubevirt.io/v1beta1/hyperconvergeds") or []
    hco_state = None
    for h in hco:
        default_eviction = ((h.get("spec") or {}).get("evictionStrategy")) or default_eviction
        av = _cond(h, "Available")
        dg = _cond(h, "Degraded")
        hco_state = {
            "name": (h.get("metadata") or {}).get("name"),
            "namespace": (h.get("metadata") or {}).get("namespace"),
            "available": (av or {}).get("status"),
            "degraded": (dg or {}).get("status"),
            "message": (dg or av or {}).get("message"),
            "version": ((h.get("status") or {}).get("versions") or [{}])[0].get("version")
            if (h.get("status") or {}).get("versions") else None,
        }
    out["platform"] = {"default_eviction": default_eviction, "hco": hco_state,
                       "cluster_name": cluster.name if cluster else hv.name}

    referenced: Dict[str, str] = {}
    vms: List[Dict[str, Any]] = []
    for vm in vms_raw:
        meta = vm.get("metadata") or {}
        ns, name = meta.get("namespace") or "", meta.get("name") or ""
        key = f"{ns}/{name}"
        spec = vm.get("spec") or {}
        tspec = ((spec.get("template") or {}).get("spec") or {})
        for vol in as_list(tspec.get("volumes")):
            if not isinstance(vol, dict):
                continue
            dv = (vol.get("dataVolume") or {}).get("name")
            pvc = (vol.get("persistentVolumeClaim") or {}).get("claimName")
            for ref in (dv, pvc):
                if ref:
                    referenced[f"{ns}/{ref}"] = key
        for dvt in as_list(spec.get("dataVolumeTemplates")):
            n = ((dvt or {}).get("metadata") or {}).get("name") if isinstance(dvt, dict) else None
            if n:
                referenced[f"{ns}/{n}"] = key
        lm = _cond(vm, "LiveMigratable") or _cond(vmi_by.get(key) or {}, "LiveMigratable")
        run_strategy = spec.get("runStrategy") or ("Always" if spec.get("running") else "Halted")
        printable = (vm.get("status") or {}).get("printableStatus")
        vmi = vmi_by.get(key) or {}
        vms.append({
            "ref": key, "name": name, "namespace": ns,
            "host_ref": (vmi.get("status") or {}).get("nodeName"),
            "power": "poweredOn" if str(printable).lower() == "running" else "poweredOff",
            "config": {
                "eviction_strategy": tspec.get("evictionStrategy"),
                "run_strategy": run_strategy,
            },
            "state": {
                "printable": printable,
                "live_migratable": (lm or {}).get("status"),
                "live_migratable_reason": (lm or {}).get("reason"),
                "live_migratable_message": ((lm or {}).get("message") or "")[:300],
            },
            "snapshots": [],
        })
    out["vms"] = vms

    if file_scan:
        dvs = _items(client, "/apis/cdi.kubevirt.io/v1beta1/datavolumes")
        pvcs = _items(client, "/api/v1/persistentvolumeclaims")
        files: List[Dict[str, Any]] = []
        dv_keys = set()
        if dvs is not None:
            for dv in dvs:
                meta = dv.get("metadata") or {}
                key = f"{meta.get('namespace')}/{meta.get('name')}"
                dv_keys.add(key)
                owners = [o.get("kind") for o in as_list(meta.get("ownerReferences")) if isinstance(o, dict)]
                golden = "DataImportCron" in owners or str(meta.get("namespace")).startswith(
                    "openshift-virtualization-os-images")
                storage = ((dv.get("spec") or {}).get("storage") or (dv.get("spec") or {}).get("pvc") or {})
                size = _qty_gb(((storage.get("resources") or {}).get("requests") or {}).get("storage"))
                files.append({
                    "kind": "datavolume", "datastore": storage.get("storageClassName"), "path": key,
                    "name": meta.get("name"), "size_gb": size, "modified_at": meta.get("creationTimestamp"),
                    "attached": key in referenced or golden or "VirtualMachine" in owners,
                    "owner_vm": referenced.get(key),
                    "extra": {"golden_image": golden, "phase": (dv.get("status") or {}).get("phase"),
                              "owners": owners},
                })
        if pvcs is not None:
            for p in pvcs:
                meta = p.get("metadata") or {}
                key = f"{meta.get('namespace')}/{meta.get('name')}"
                ann = meta.get("annotations") or {}
                owners = [o.get("kind") for o in as_list(meta.get("ownerReferences")) if isinstance(o, dict)]
                is_vm_disk = (
                    "cdi.kubevirt.io/storage.contentType" in ann
                    or any(k.startswith("cdi.kubevirt.io") for k in ann)
                )
                if not is_vm_disk or "DataVolume" in owners or key in dv_keys:
                    continue
                golden = str(meta.get("namespace")).startswith("openshift-virtualization-os-images")
                files.append({
                    "kind": "pvc", "datastore": (p.get("spec") or {}).get("storageClassName"), "path": key,
                    "name": meta.get("name"),
                    "size_gb": _qty_gb(((p.get("status") or {}).get("capacity") or {}).get("storage")),
                    "modified_at": meta.get("creationTimestamp"),
                    "attached": key in referenced or golden,
                    "owner_vm": referenced.get(key),
                    "extra": {"golden_image": golden, "phase": (p.get("status") or {}).get("phase")},
                })
        if dvs is None and pvcs is None:
            out["file_scan"] = {"error": "DataVolume/PVC listesi okunamadı"}
        else:
            out["files"] = files
            out["file_scan"] = {"scanned": 1, "failed": []}
    out["ok"] = True
    return out
