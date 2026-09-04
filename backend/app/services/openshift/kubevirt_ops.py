"""
KubeVirt yazma işlemleri — Atlas kubevirt_service akışının ainew uyarlaması.

Tüm yıkıcı / yaşam döngüsü çağrıları API katmanında admin ile korunmalı.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.services.openshift.kubevirt_client import KubeVirtClient

logger = logging.getLogger(__name__)

KV = "/apis/kubevirt.io/v1"
SUBRES = "/apis/subresources.kubevirt.io/v1"
SNAP = "/apis/snapshot.kubevirt.io/v1beta1"
CLONE = "/apis/clone.kubevirt.io/v1beta1"
CDI = "/apis/cdi.kubevirt.io/v1beta1"
_RE_K8S = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class KubeVirtOpError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _k8s_name(v: str, what: str) -> str:
    v = (v or "").strip().lower()
    if not _RE_K8S.match(v):
        raise KubeVirtOpError(
            f"Geçersiz {what}: küçük harf, rakam ve tire (en fazla 63 karakter)"
        )
    return v


def _raise_http(r, what: str) -> None:
    if r.status_code == 403:
        raise KubeVirtOpError(
            f"Yetki yok (403) — {what}. Service account'a KubeVirt yönetim izni gerekli.",
            403,
        )
    if r.status_code >= 400:
        msg = ""
        try:
            msg = (r.json() or {}).get("message") or ""
        except Exception:
            msg = (r.text or "")[:240]
        raise KubeVirtOpError(f"{what} başarısız (HTTP {r.status_code}): {msg or r.reason}", r.status_code)


def power_action(client: KubeVirtClient, namespace: str, name: str, action: str, actor: str = "") -> Dict[str, Any]:
    verb = {
        "power_on": "start", "start": "start",
        "power_off": "stop", "shutdown": "stop", "stop": "stop",
        "restart": "restart", "reboot": "restart", "reset": "restart",
    }.get((action or "").strip().lower())
    if not verb:
        raise KubeVirtOpError(f"Desteklenmeyen işlem: {action}")
    path = f"{SUBRES}/namespaces/{namespace}/virtualmachines/{name}/{verb}"
    r = client.session.put(f"{client.api_url}{path}", json={}, timeout=client.timeout)
    if r.status_code == 409 and verb == "start":
        return {"ok": True, "action": verb, "note": "VM zaten çalışıyor"}
    if r.status_code == 409 and verb == "stop":
        return {"ok": True, "action": verb, "note": "VM zaten durmuş"}
    _raise_http(r, f"VM {verb}")
    logger.info("KubeVirt %s: %s/%s — %s", verb, namespace, name, actor)
    return {"ok": True, "action": verb, "note": f"{name}: {verb} gönderildi"}


def delete_vm(client: KubeVirtClient, namespace: str, name: str, actor: str = "") -> Dict[str, Any]:
    r = client.session.delete(
        f"{client.api_url}{KV}/namespaces/{namespace}/virtualmachines/{name}",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        raise KubeVirtOpError("VM bulunamadı", 404)
    _raise_http(r, "VM silme")
    logger.warning("KubeVirt VM SİLİNDİ: %s/%s — %s", namespace, name, actor)
    return {"ok": True, "deleted": f"{namespace}/{name}"}


def clone_vm(
    client: KubeVirtClient,
    namespace: str,
    source: str,
    target: str,
    actor: str = "",
) -> Dict[str, Any]:
    tgt = _k8s_name(target, "hedef VM adı")
    cname = f"clone-{tgt}-{datetime.utcnow():%H%M%S}"[:63]
    body = {
        "apiVersion": "clone.kubevirt.io/v1beta1",
        "kind": "VirtualMachineClone",
        "metadata": {
            "name": cname,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "source": {"apiGroup": "kubevirt.io", "kind": "VirtualMachine", "name": source},
            "target": {"apiGroup": "kubevirt.io", "kind": "VirtualMachine", "name": tgt},
        },
    }
    r = client.session.post(
        f"{client.api_url}{CLONE}/namespaces/{namespace}/virtualmachineclones",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "Klonlama")
    return {
        "ok": True,
        "target": tgt,
        "note": "Klonlama başlatıldı; disk kopyalama boyuta göre sürebilir.",
    }


def create_snapshot(
    client: KubeVirtClient,
    namespace: str,
    vm_name: str,
    snapshot_name: str = "",
    actor: str = "",
) -> Dict[str, Any]:
    name = _k8s_name(
        snapshot_name or f"{vm_name}-{datetime.utcnow():%Y%m%d-%H%M%S}",
        "snapshot adı",
    )
    body = {
        "apiVersion": "snapshot.kubevirt.io/v1beta1",
        "kind": "VirtualMachineSnapshot",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "source": {
                "apiGroup": "kubevirt.io",
                "kind": "VirtualMachine",
                "name": vm_name,
            }
        },
    }
    r = client.session.post(
        f"{client.api_url}{SNAP}/namespaces/{namespace}/virtualmachinesnapshots",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "Snapshot oluşturma")
    return {"ok": True, "name": name}


def restore_snapshot(
    client: KubeVirtClient,
    namespace: str,
    vm_name: str,
    snapshot_name: str,
    actor: str = "",
) -> Dict[str, Any]:
    rname = f"{_k8s_name(snapshot_name, 'snapshot')}-restore-{datetime.utcnow():%H%M%S}"[:63]
    body = {
        "apiVersion": "snapshot.kubevirt.io/v1beta1",
        "kind": "VirtualMachineRestore",
        "metadata": {
            "name": rname,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "target": {
                "apiGroup": "kubevirt.io",
                "kind": "VirtualMachine",
                "name": vm_name,
            },
            "virtualMachineSnapshotName": snapshot_name,
        },
    }
    r = client.session.post(
        f"{client.api_url}{SNAP}/namespaces/{namespace}/virtualmachinerestores",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "Snapshot geri yükleme")
    return {"ok": True, "restore": rname, "note": "Geri yükleme başlatıldı; VM kapalı olmalı."}


def delete_snapshot(
    client: KubeVirtClient, namespace: str, snapshot_name: str, actor: str = ""
) -> Dict[str, Any]:
    r = client.session.delete(
        f"{client.api_url}{SNAP}/namespaces/{namespace}/virtualmachinesnapshots/{snapshot_name}",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        raise KubeVirtOpError("Snapshot bulunamadı", 404)
    _raise_http(r, "Snapshot silme")
    return {"ok": True}


def list_clones(client: KubeVirtClient, namespace: str, vm_name: str) -> list:
    r = client.session.get(
        f"{client.api_url}{CLONE}/namespaces/{namespace}/virtualmachineclones",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        return []
    _raise_http(r, "Klon listesi")
    out = []
    for item in (r.json() or {}).get("items") or []:
        spec = item.get("spec") or {}
        src = ((spec.get("source") or {}).get("name"))
        tgt = ((spec.get("target") or {}).get("name"))
        if src and src != vm_name:
            continue
        st = item.get("status") or {}
        out.append({
            "name": (item.get("metadata") or {}).get("name"),
            "target": tgt,
            "phase": st.get("phase"),
            "ready": st.get("ready"),
            "created": (item.get("metadata") or {}).get("creationTimestamp"),
        })
    out.sort(key=lambda x: x.get("created") or "", reverse=True)
    return out


def list_snapshots(client: KubeVirtClient, namespace: str, vm_name: str) -> list:
    r = client.session.get(
        f"{client.api_url}{SNAP}/namespaces/{namespace}/virtualmachinesnapshots",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        return []
    _raise_http(r, "Snapshot listesi")
    out = []
    for s in (r.json() or {}).get("items") or []:
        spec = s.get("spec") or {}
        src = (spec.get("source") or {}).get("name")
        if src and src != vm_name:
            continue
        st = s.get("status") or {}
        conds = st.get("conditions") or []
        failure = next(
            (c.get("message") for c in conds if c.get("type") == "Failure" and c.get("status") == "True"),
            None,
        )
        out.append({
            "name": (s.get("metadata") or {}).get("name"),
            "vm": src,
            "ready": st.get("readyToUse"),
            "created": (s.get("metadata") or {}).get("creationTimestamp"),
            "phase": st.get("phase"),
            "source": {"kind": (spec.get("source") or {}).get("kind"), "name": src},
            "volume_snapshots": [
                {"name": v.get("volumeSnapshotName"), "creation_time": v.get("creationTime")}
                for v in (st.get("volumeSnapshotStatus") or [])
            ],
            "indications": st.get("indications") or [],
            "failure_reason": failure,
        })
    out.sort(key=lambda x: x.get("created") or "", reverse=True)
    return out


def list_restores(client: KubeVirtClient, namespace: str, vm_name: str = "") -> list:
    """VirtualMachineRestore listesi (snapshot.kubevirt.io) — opsiyonel vm_name filtresi."""
    r = client.session.get(
        f"{client.api_url}{SNAP}/namespaces/{namespace}/virtualmachinerestores",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        return []
    _raise_http(r, "Restore listesi")
    out = []
    for item in (r.json() or {}).get("items") or []:
        spec = item.get("spec") or {}
        target = (spec.get("target") or {}).get("name")
        if vm_name and target != vm_name:
            continue
        st = item.get("status") or {}
        out.append({
            "name": (item.get("metadata") or {}).get("name"),
            "source_snapshot": spec.get("virtualMachineSnapshotName"),
            "target_vm": target,
            "complete": st.get("complete"),
            "restore_time": st.get("restoreTime"),
            "conditions": [
                {"type": c.get("type"), "status": c.get("status"), "reason": c.get("reason")}
                for c in (st.get("conditions") or [])
            ],
            "created": (item.get("metadata") or {}).get("creationTimestamp"),
        })
    out.sort(key=lambda x: x.get("created") or "", reverse=True)
    return out


def create_pvc(
    client: KubeVirtClient,
    namespace: str,
    name: str,
    size: str,
    storage_class: Optional[str] = None,
    access_mode: str = "ReadWriteOnce",
    actor: str = "",
) -> Dict[str, Any]:
    pvc_name = _k8s_name(name, "PVC adı")
    body: Dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": pvc_name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "accessModes": [access_mode or "ReadWriteOnce"],
            "resources": {"requests": {"storage": size or "10Gi"}},
        },
    }
    if storage_class:
        body["spec"]["storageClassName"] = storage_class
    r = client.session.post(
        f"{client.api_url}/api/v1/namespaces/{namespace}/persistentvolumeclaims",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "PVC oluşturma")
    logger.info("PVC created %s/%s size=%s — %s", namespace, pvc_name, size, actor)
    return {"ok": True, "name": pvc_name, "namespace": namespace}


def add_disk_datavolume(
    client: KubeVirtClient,
    namespace: str,
    vm_name: str,
    disk_name: str,
    size: str,
    storage_class: Optional[str] = None,
    actor: str = "",
) -> Dict[str, Any]:
    """
    CDI DataVolume oluştur + VM spec'e disk/volume ekle (patch).
    VM kapalıyken daha güvenli; hotplug için ayrı API gerekir.
    """
    dname = _k8s_name(disk_name, "disk adı")
    dv_body: Dict[str, Any] = {
        "apiVersion": "cdi.kubevirt.io/v1beta1",
        "kind": "DataVolume",
        "metadata": {
            "name": dname,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "pvc": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": size or "20Gi"}},
            },
            "source": {"blank": {}},
        },
    }
    if storage_class:
        dv_body["spec"]["pvc"]["storageClassName"] = storage_class

    r = client.session.post(
        f"{client.api_url}{CDI}/namespaces/{namespace}/datavolumes",
        json=dv_body,
        timeout=client.timeout,
    )
    _raise_http(r, "DataVolume oluşturma")

    # VM'e disk + volume ekle
    patch = {
        "spec": {
            "template": {
                "spec": {
                    "domain": {
                        "devices": {
                            "disks": [{"name": dname, "disk": {"bus": "virtio"}}],
                        }
                    },
                    "volumes": [{"name": dname, "dataVolume": {"name": dname}}],
                }
            }
        }
    }
    pr = client.session.patch(
        f"{client.api_url}{KV}/namespaces/{namespace}/virtualmachines/{vm_name}",
        json=patch,
        headers={
            **client.session.headers,
            "Content-Type": "application/strategic-merge-patch+json",
        },
        timeout=client.timeout,
    )
    _raise_http(pr, "VM disk ekleme")
    logger.info("Disk eklendi %s/%s + %s — %s", namespace, vm_name, dname, actor)
    return {
        "ok": True,
        "disk": dname,
        "note": "DataVolume oluşturuldu ve VM spec'e eklendi. VM yeniden başlatma gerekebilir.",
    }


def set_multus_network(
    client: KubeVirtClient,
    namespace: str,
    vm_name: str,
    nad_name: str,
    interface_name: str = "net1",
    actor: str = "",
) -> Dict[str, Any]:
    """VM'e Multus NetworkAttachmentDefinition bağla (ek NIC)."""
    iface = _k8s_name(interface_name or "net1", "arayüz adı")
    nad = (nad_name or "").strip()
    if not nad:
        raise KubeVirtOpError("NAD (network-attachment-definition) adı gerekli")
    # nad may be name or ns/name
    nad_ref = nad
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "k8s.v1.cni.cncf.io/networks": nad_ref,
                    }
                },
                "spec": {
                    "domain": {
                        "devices": {
                            "interfaces": [
                                {"name": "default", "masquerade": {}},
                                {"name": iface, "bridge": {}},
                            ]
                        }
                    },
                    "networks": [
                        {"name": "default", "pod": {}},
                        {"name": iface, "multus": {"networkName": nad_ref}},
                    ],
                },
            }
        }
    }
    pr = client.session.patch(
        f"{client.api_url}{KV}/namespaces/{namespace}/virtualmachines/{vm_name}",
        json=patch,
        headers={
            **client.session.headers,
            "Content-Type": "application/strategic-merge-patch+json",
        },
        timeout=client.timeout,
    )
    _raise_http(pr, "VM network atama")
    logger.info("Network set %s/%s nad=%s — %s", namespace, vm_name, nad_ref, actor)
    return {"ok": True, "network": nad_ref, "interface": iface}
