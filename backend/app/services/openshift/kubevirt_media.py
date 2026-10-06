"""
KubeVirt CD-ROM / ISO işlemleri.

- Mevcut bir PVC'yi (aynı namespace) VM'e CD-ROM olarak bağlama
- Başka namespace'teki PVC'yi CDI DataVolume ile **klonlayıp** bağlama
- İstemci bilgisayardan ISO yükleme (CDI upload proxy; tarayıcı → ainew → CDI)
- CD-ROM çıkarma (eject)

Tüm yazma çağrıları API katmanında admin ile korunur.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from urllib.parse import urlparse

from app.services.openshift.kubevirt_client import KubeVirtClient
from app.services.openshift.kubevirt_ops import (
    CDI,
    KV,
    KubeVirtOpError,
    _k8s_name,
    _raise_http,
    get_vm,
    patch_vm_template,
)

logger = logging.getLogger(__name__)

UPLOAD_API = "/apis/upload.cdi.kubevirt.io/v1beta1"
ISO_NAME_RX = re.compile(r"(iso|cd-?rom|dvd|install|boot|virtio-?win|\.img)", re.I)
CONTENT_TYPE_ANN = "cdi.kubevirt.io/storage.contentType"
BIND_IMMEDIATE_ANN = "cdi.kubevirt.io/storage.bind.immediate.requested"
MAX_UPLOAD_GI = 200


def _vm_running(vm: Dict[str, Any]) -> bool:
    status = (vm.get("status") or {})
    ps = (status.get("printableStatus") or "").lower()
    return ps in ("running", "migrating", "paused") or bool(status.get("ready"))


def _short(name: str, limit: int = 63) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    return name[:limit].strip("-") or "iso"


# ── Kaynak listesi ────────────────────────────────────────────────────────────

def list_iso_sources(client: KubeVirtClient, vm_namespace: str, limit: int = 600) -> Dict[str, Any]:
    """Token'ın görebildiği PVC'ler. İsim/etiketten ISO tahmini yapılır (iso_guess)."""
    r = client.session.get(
        f"{client.api_url}/api/v1/persistentvolumeclaims",
        params={"limit": 2000},
        timeout=client.timeout,
    )
    scope = "cluster"
    if r.status_code in (401, 403):
        scope = "namespace"
        r = client.session.get(
            f"{client.api_url}/api/v1/namespaces/{vm_namespace}/persistentvolumeclaims",
            timeout=client.timeout,
        )
    _raise_http(r, "PVC listesi")
    items: List[Dict[str, Any]] = []
    for it in (r.json() or {}).get("items", []):
        md = it.get("metadata") or {}
        spec = it.get("spec") or {}
        st = it.get("status") or {}
        ann = md.get("annotations") or {}
        name = md.get("name") or ""
        size = (st.get("capacity") or {}).get("storage") or (
            ((spec.get("resources") or {}).get("requests") or {}).get("storage")
        )
        labels = md.get("labels") or {}
        iso_guess = bool(ISO_NAME_RX.search(name)) or "iso" in (labels.get("app") or "").lower()
        items.append({
            "namespace": md.get("namespace") or "",
            "name": name,
            "size": size,
            "storage_class": spec.get("storageClassName"),
            "access_modes": spec.get("accessModes") or [],
            "volume_mode": spec.get("volumeMode") or "Filesystem",
            "phase": st.get("phase"),
            "content_type": ann.get(CONTENT_TYPE_ANN) or "",
            "iso_guess": iso_guess,
            "same_namespace": (md.get("namespace") or "") == vm_namespace,
        })
    items.sort(key=lambda x: (not x["same_namespace"], not x["iso_guess"], x["namespace"], x["name"]))
    truncated = len(items) > limit
    return {"items": items[:limit], "total": len(items), "truncated": truncated, "scope": scope}


def list_vm_cdroms(client: KubeVirtClient, namespace: str, vm_name: str) -> List[Dict[str, Any]]:
    vm = get_vm(client, namespace, vm_name)
    spec = (((vm.get("spec") or {}).get("template") or {}).get("spec") or {})
    disks = ((spec.get("domain") or {}).get("devices") or {}).get("disks") or []
    vols = {v.get("name"): v for v in (spec.get("volumes") or [])}
    out: List[Dict[str, Any]] = []
    for d in disks:
        if "cdrom" not in d:
            continue
        v = vols.get(d.get("name")) or {}
        src = ""
        kind = ""
        if "persistentVolumeClaim" in v:
            kind, src = "pvc", (v["persistentVolumeClaim"] or {}).get("claimName", "")
        elif "dataVolume" in v:
            kind, src = "datavolume", (v["dataVolume"] or {}).get("name", "")
        elif "containerDisk" in v:
            kind, src = "containerdisk", (v["containerDisk"] or {}).get("image", "")
        out.append({
            "disk": d.get("name"),
            "source_kind": kind,
            "source": src,
            "boot_order": d.get("bootOrder"),
        })
    return out


# ── Bağlama / çıkarma ─────────────────────────────────────────────────────────

def _get_pvc(client: KubeVirtClient, namespace: str, name: str) -> Dict[str, Any]:
    r = client.session.get(
        f"{client.api_url}/api/v1/namespaces/{namespace}/persistentvolumeclaims/{name}",
        timeout=client.timeout,
    )
    if r.status_code == 404:
        raise KubeVirtOpError(f"PVC bulunamadı: {namespace}/{name}", 404)
    _raise_http(r, "PVC okuma")
    return r.json()


def _clone_pvc_to_datavolume(
    client: KubeVirtClient, namespace: str, dv_name: str, src_ns: str, src_name: str,
) -> Dict[str, Any]:
    src = _get_pvc(client, src_ns, src_name)
    sspec = src.get("spec") or {}
    size = ((src.get("status") or {}).get("capacity") or {}).get("storage") or (
        ((sspec.get("resources") or {}).get("requests") or {}).get("storage") or "10Gi"
    )
    pvc: Dict[str, Any] = {
        "accessModes": sspec.get("accessModes") or ["ReadWriteOnce"],
        "resources": {"requests": {"storage": size}},
    }
    if sspec.get("storageClassName"):
        pvc["storageClassName"] = sspec["storageClassName"]
    if sspec.get("volumeMode"):
        pvc["volumeMode"] = sspec["volumeMode"]
    body = {
        "apiVersion": "cdi.kubevirt.io/v1beta1",
        "kind": "DataVolume",
        "metadata": {
            "name": dv_name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew"},
        },
        "spec": {
            "source": {"pvc": {"namespace": src_ns, "name": src_name}},
            "pvc": pvc,
        },
    }
    r = client.session.post(
        f"{client.api_url}{CDI}/namespaces/{namespace}/datavolumes",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "DataVolume (klon) oluşturma")
    return {"name": dv_name, "size": size}


def attach_cdrom(
    client: KubeVirtClient,
    namespace: str,
    vm_name: str,
    source_namespace: str,
    source_pvc: str,
    boot_first: bool = False,
    disk_name: str = "",
    actor: str = "",
) -> Dict[str, Any]:
    """PVC'yi VM'e CD-ROM olarak bağla (farklı namespace ise önce klonla)."""
    src_ns = _k8s_name(source_namespace or namespace, "kaynak namespace")
    src_pvc = _k8s_name(source_pvc, "kaynak PVC")
    cross = src_ns != namespace
    dname = _k8s_name(disk_name, "CD-ROM adı") if disk_name else _short(f"cdrom-{src_pvc}")
    if not dname.startswith("cdrom"):
        dname = _short(f"cdrom-{dname}")

    vm0 = get_vm(client, namespace, vm_name)
    spec0 = (((vm0.get("spec") or {}).get("template") or {}).get("spec") or {})
    for d in ((spec0.get("domain") or {}).get("devices") or {}).get("disks") or []:
        if d.get("name") == dname:
            raise KubeVirtOpError(f"'{dname}' adlı disk zaten VM'de var — önce çıkarın veya başka ad verin", 409)
    for v in spec0.get("volumes") or []:
        claim = (v.get("persistentVolumeClaim") or {}).get("claimName")
        if claim == src_pvc and not cross:
            raise KubeVirtOpError("Bu PVC zaten VM'e bağlı", 409)

    volume: Dict[str, Any]
    dv_info: Optional[Dict[str, Any]] = None
    if cross:
        dv_name = _short(f"{vm_name}-iso-{src_pvc}", 58)
        dv_info = _clone_pvc_to_datavolume(client, namespace, dv_name, src_ns, src_pvc)
        volume = {"name": dname, "dataVolume": {"name": dv_name}}
    else:
        _get_pvc(client, namespace, src_pvc)  # varlık kontrolü
        volume = {"name": dname, "persistentVolumeClaim": {"claimName": src_pvc, "readOnly": True}}

    state: Dict[str, Any] = {}

    def mutate(vm: Dict[str, Any]) -> None:
        tpl = vm.setdefault("spec", {}).setdefault("template", {})
        spec = tpl.setdefault("spec", {})
        devices = spec.setdefault("domain", {}).setdefault("devices", {})
        disks = devices.setdefault("disks", [])
        vols = spec.setdefault("volumes", [])
        cd: Dict[str, Any] = {"name": dname, "cdrom": {"bus": "sata"}}
        if boot_first:
            for d in disks:
                if isinstance(d.get("bootOrder"), int):
                    d["bootOrder"] = d["bootOrder"] + 1
            cd["bootOrder"] = 1
        disks.append(cd)
        vols.append(volume)
        state["running"] = _vm_running(vm)

    patch_vm_template(client, namespace, vm_name, mutate, "CD-ROM bağlama")
    logger.info("CD-ROM bağlandı %s/%s ← %s/%s (%s) — %s",
                namespace, vm_name, src_ns, src_pvc, "klon" if cross else "doğrudan", actor)
    running = bool(state.get("running"))
    note = "CD-ROM VM tanımına eklendi."
    if cross:
        note += " Kaynak PVC bu namespace'e klonlanıyor (boyuta göre sürer)."
    if running:
        note += " VM çalışıyor — CD-ROM'un görünmesi için VM'i yeniden başlatın."
    return {
        "ok": True,
        "disk": dname,
        "mode": "clone" if cross else "attach",
        "datavolume": dv_info,
        "restart_required": running,
        "note": note,
    }


def eject_cdrom(
    client: KubeVirtClient, namespace: str, vm_name: str, disk_name: str, actor: str = "",
) -> Dict[str, Any]:
    dname = _k8s_name(disk_name, "CD-ROM adı")
    state: Dict[str, Any] = {"found": False}

    def mutate(vm: Dict[str, Any]) -> None:
        spec = (((vm.get("spec") or {}).get("template") or {}).get("spec") or {})
        devices = (spec.get("domain") or {}).get("devices") or {}
        disks = devices.get("disks") or []
        keep = []
        for d in disks:
            if d.get("name") == dname and "cdrom" in d:
                state["found"] = True
                continue
            keep.append(d)
        if not state["found"]:
            return
        devices["disks"] = keep
        spec["volumes"] = [v for v in (spec.get("volumes") or []) if v.get("name") != dname]
        state["running"] = _vm_running(vm)

    patch_vm_template(client, namespace, vm_name, mutate, "CD-ROM çıkarma", skip_if=lambda: not state["found"])
    if not state["found"]:
        raise KubeVirtOpError("Bu adda bir CD-ROM bulunamadı", 404)
    logger.info("CD-ROM çıkarıldı %s/%s %s — %s", namespace, vm_name, dname, actor)
    running = bool(state.get("running"))
    return {
        "ok": True,
        "disk": dname,
        "restart_required": running,
        "note": "CD-ROM VM tanımından çıkarıldı." + (" VM çalışıyor — yeniden başlatınca etkili olur." if running else ""),
    }


# ── ISO yükleme (CDI upload) ──────────────────────────────────────────────────

def suggest_upload_size_gi(content_length: int) -> int:
    """ISO boyutuna filesystem payı (~%10) ekleyip GiB'e yuvarlar."""
    gi = 1024 ** 3
    need = int(content_length * 1.10) + 64 * 1024 * 1024
    return max(1, -(-need // gi))


def create_upload_datavolume(
    client: KubeVirtClient,
    namespace: str,
    name: str,
    size_gi: int,
    storage_class: Optional[str] = None,
) -> Dict[str, Any]:
    pname = _k8s_name(name, "PVC/DataVolume adı")
    if not (1 <= int(size_gi) <= MAX_UPLOAD_GI):
        raise KubeVirtOpError(f"Boyut 1–{MAX_UPLOAD_GI} GiB arasında olmalı")
    pvc: Dict[str, Any] = {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": f"{int(size_gi)}Gi"}},
    }
    if storage_class:
        pvc["storageClassName"] = storage_class
    body = {
        "apiVersion": "cdi.kubevirt.io/v1beta1",
        "kind": "DataVolume",
        "metadata": {
            "name": pname,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "ainew", "ainew/purpose": "iso-upload"},
            "annotations": {BIND_IMMEDIATE_ANN: "true"},
        },
        "spec": {"source": {"upload": {}}, "contentType": "kubevirt", "pvc": pvc},
    }
    r = client.session.post(
        f"{client.api_url}{CDI}/namespaces/{namespace}/datavolumes",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "Yükleme DataVolume'u oluşturma")
    return {"name": pname, "namespace": namespace, "size_gi": int(size_gi)}


def wait_dv_phase(
    client: KubeVirtClient,
    namespace: str,
    name: str,
    wanted: tuple = ("UploadReady",),
    timeout: float = 180.0,
    interval: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    deadline = time.monotonic() + timeout
    phase = ""
    while True:
        r = client.session.get(
            f"{client.api_url}{CDI}/namespaces/{namespace}/datavolumes/{name}",
            timeout=client.timeout,
        )
        if r.status_code == 200:
            phase = (((r.json() or {}).get("status") or {}).get("phase")) or ""
            if phase in wanted:
                return phase
            if phase == "Failed":
                raise KubeVirtOpError("DataVolume 'Failed' durumuna düştü (depolama/CDI günlüklerine bakın)", 502)
        elif r.status_code not in (404,):
            _raise_http(r, "DataVolume durumu")
        if time.monotonic() >= deadline:
            raise KubeVirtOpError(
                f"DataVolume {'/'.join(wanted)} durumuna gelmedi (son durum: {phase or 'bilinmiyor'}). "
                "StorageClass 'WaitForFirstConsumer' ise veya CDI upload pod'u başlamadıysa bu olur.",
                504,
            )
        sleep(interval)


def request_upload_token(client: KubeVirtClient, namespace: str, pvc_name: str) -> str:
    body = {
        "apiVersion": "upload.cdi.kubevirt.io/v1beta1",
        "kind": "UploadTokenRequest",
        "metadata": {"name": pvc_name, "namespace": namespace},
        "spec": {"pvcName": pvc_name},
    }
    r = client.session.post(
        f"{client.api_url}{UPLOAD_API}/namespaces/{namespace}/uploadtokenrequests",
        json=body,
        timeout=client.timeout,
    )
    _raise_http(r, "Yükleme token'ı alma")
    token = (((r.json() or {}).get("status") or {}).get("token")) or ""
    if not token:
        raise KubeVirtOpError("CDI yükleme token'ı boş döndü", 502)
    return token


def discover_upload_proxy(client: KubeVirtClient) -> str:
    """CDIConfig.status.uploadProxyURL, yoksa openshift-cnv/cdi-uploadproxy Route'u."""
    r = client.session.get(f"{client.api_url}{CDI}/cdiconfigs/config", timeout=client.timeout)
    if r.status_code == 200:
        st = (r.json() or {}).get("status") or {}
        url = st.get("uploadProxyURL") or ((r.json() or {}).get("spec") or {}).get("uploadProxyURLOverride")
        if url:
            return url if url.startswith("http") else f"https://{url}"
    for ns in ("openshift-cnv", "kubevirt-hyperconverged", "cdi"):
        rr = client.session.get(
            f"{client.api_url}/apis/route.openshift.io/v1/namespaces/{ns}/routes/cdi-uploadproxy",
            timeout=client.timeout,
        )
        if rr.status_code == 200:
            host = ((rr.json() or {}).get("spec") or {}).get("host")
            if host:
                return f"https://{host}"
    raise KubeVirtOpError(
        "CDI upload proxy adresi bulunamadı. 'cdi-uploadproxy' Route'u oluşturulmalı veya "
        "CDIConfig.spec.uploadProxyURLOverride tanımlanmalı.",
        502,
    )


def delete_datavolume(client: KubeVirtClient, namespace: str, name: str) -> None:
    try:
        client.session.delete(
            f"{client.api_url}{CDI}/namespaces/{namespace}/datavolumes/{name}",
            timeout=client.timeout,
        )
    except Exception as e:  # temizlik başarısızlığı asıl hatayı gölgelemesin
        logger.warning("DataVolume temizlenemedi %s/%s: %s", namespace, name, e)


async def stream_upload(
    proxy_url: str,
    token: str,
    body: AsyncIterator[bytes],
    content_length: int,
    verify: bool = False,
    transport: Any = None,
) -> Dict[str, Any]:
    """İstemciden gelen akışı CDI upload proxy'ye, bellekte biriktirmeden aktarır."""
    import httpx

    target = f"{proxy_url.rstrip('/')}/v1beta1/upload"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(int(content_length)),
    }
    extensions: Dict[str, Any] = {}
    try:
        from app.services.host_resolve import rewrite_url_host

        rewritten, _note, orig = rewrite_url_host(target)
        if rewritten and rewritten != target and orig:
            target = rewritten
            headers["Host"] = orig
            extensions["sni_hostname"] = orig
    except Exception:  # noqa: BLE001
        pass
    timeout = httpx.Timeout(30.0, read=None, write=None)
    kwargs: Dict[str, Any] = {"verify": verify, "timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    async with httpx.AsyncClient(**kwargs) as c:
        req = c.build_request("POST", target, headers=headers, content=body, extensions=extensions or None)
        resp = await c.send(req)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:240]
        raise KubeVirtOpError(f"CDI upload proxy hata verdi (HTTP {resp.status_code}): {detail}", 502)
    return {"ok": True, "status": resp.status_code, "host": urlparse(target).hostname}
