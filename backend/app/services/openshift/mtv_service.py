"""
MTV / Forklift — VMware → OpenShift VM taşıma.

ainew, taşıma motorunu yazmaz; kümedeki MTV CRD'lerini yönetir:
Provider, NetworkMap, StorageMap, Plan, Migration.
Kaynak vCenter kimliği Hypervisor kaydından alınır (Secret → openshift-mtv).
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.openshift import OpenShiftCluster
from app.services.hypervisor_credentials import hv_password
from app.services.openshift import cluster_ops
from app.services.openshift.ocp_client import OpenShiftClient

logger = logging.getLogger(__name__)

NS = "openshift-mtv"
FORKLIFT = "/apis/forklift.konveyor.io/v1beta1"
MANAGED_BY = "ainew"


class MtvError(Exception):
    """Kullanıcıya gösterilebilir MTV hatası."""


def _rfc1123(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", (name or "").lower().strip())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise MtvError(f"Geçersiz ad: {name}")
    return s[:63]


def _cond(obj: Dict, ctype: str) -> Optional[Dict]:
    for c in (obj.get("status", {}) or {}).get("conditions") or []:
        if c.get("type") == ctype:
            return c
    return None


def _client(cluster: OpenShiftCluster) -> OpenShiftClient:
    return cluster_ops.client_from_cluster(cluster)


def _get(client: OpenShiftClient, path: str, timeout: int = 30) -> Optional[Dict]:
    r = client._get(path, timeout=timeout)
    if r.status_code in (404, 403):
        return None
    if r.status_code >= 400:
        return None
    try:
        return r.json()
    except Exception:
        return None


def _kind_label(path: str) -> str:
    if path.endswith("/plans"):
        return "Taşıma planı"
    if path.endswith("/networkmaps"):
        return "Ağ eşlemesi"
    if path.endswith("/storagemaps"):
        return "Depolama eşlemesi"
    if path.endswith("/providers"):
        return "Sağlayıcı"
    return "Kaynak"


def _apply(client: OpenShiftClient, path: str, body: Dict, name: str) -> Dict:
    r = client._post(path, body)
    if r.status_code == 409:
        r = client.session.patch(
            f"{client.api_url}{path}/{name}",
            json=body,
            headers={**client.session.headers, "Content-Type": "application/apply-patch+yaml"},
            params={"fieldManager": "ainew", "force": "true"},
            timeout=client.timeout,
        )
    if r.status_code == 403:
        raise MtvError(
            "Yetki yok (403). Service account'a MTV yazma izni verin — "
            "paneldeki 'Yetki ver' komutunu kümede çalıştırın."
        )
    if r.status_code >= 400:
        detail = ""
        try:
            err = r.json()
            detail = err.get("message") or ""
            for c in (err.get("details", {}) or {}).get("causes", []) or []:
                fld, msg = c.get("field", ""), c.get("message", "")
                if msg:
                    detail += f" | {fld}: {msg}" if fld else f" | {msg}"
        except Exception:
            detail = (r.text or "")[:400]
        logger.error("MTV %s (%s) %s: %s", name, r.status_code, path, detail)
        raise MtvError(f"{_kind_label(path)} oluşturulamadı ({r.status_code}): {detail or 'küme ayrıntı vermedi'}")
    return r.json() if r.content else {}


def _vcenter(db: Session, hypervisor_id: int):
    hv = db.query(Hypervisor).filter(Hypervisor.id == int(hypervisor_id)).first()
    if not hv:
        raise MtvError("vCenter (hypervisor) bulunamadı")
    if hv.hypervisor_type != HypervisorType.VMWARE:
        raise MtvError("Şimdilik yalnızca VMware kaynak destekleniyor")
    from app.services.vmware.vcenter_client import VCenterClient
    client = VCenterClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or (hv.connection_config or {}).get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
    )
    return hv, client


def list_providers(cluster: OpenShiftCluster) -> List[Dict]:
    client = _client(cluster)
    try:
        data = _get(client, f"{FORKLIFT}/namespaces/{NS}/providers")
        if data is None:
            raise MtvError("Forklift API'sine erişilemedi — MTV kurulu mu?")
        out = []
        for item in data.get("items", []):
            ready = _cond(item, "Ready")
            crit = next(
                (x for x in (item.get("status", {}) or {}).get("conditions") or []
                 if x.get("category") == "Critical"),
                None,
            )
            settings = (item.get("spec") or {}).get("settings") or {}
            out.append({
                "name": item["metadata"]["name"],
                "type": (item.get("spec") or {}).get("type"),
                "url": (item.get("spec") or {}).get("url", ""),
                "ready": bool(ready and ready.get("status") == "True"),
                "error": crit.get("message") if crit else None,
                "vddk": settings.get("vddkInitImage") or None,
            })
        return out
    finally:
        client.logout()


def set_provider_vddk(cluster: OpenShiftCluster, provider_name: str, vddk_image: str, actor: str = "") -> Dict:
    pname = _rfc1123(provider_name)
    img = (vddk_image or "").strip()
    if img and not re.match(r"^[a-zA-Z0-9][\w./:@\-]{0,250}$", img):
        raise MtvError("Geçersiz imaj adresi (örn. quay.io/kurum/vddk:8.0.3)")
    body = {"spec": {"settings": {"vddkInitImage": img or None}}}
    client = _client(cluster)
    try:
        r = client._patch(
            f"{FORKLIFT}/namespaces/{NS}/providers/{pname}",
            body,
            content_type="application/merge-patch+json",
        )
        if r.status_code == 403:
            raise MtvError("Yetki yok (403) — MTV yazma izni gerekli")
        if r.status_code >= 400:
            raise MtvError(f"VDDK ayarlanamadı ({r.status_code}): {(r.text or '')[:200]}")
        return {"provider": pname, "vddk": img or None}
    finally:
        client.logout()


def create_vsphere_provider(
    cluster: OpenShiftCluster,
    db: Session,
    hypervisor_id: int,
    actor: str = "",
    vddk_init_image: str = "",
) -> Dict:
    hv, _ = _vcenter(db, hypervisor_id)
    name = _rfc1123(f"ainew-{hv.name}")
    host = hv.ip_address or hv.hostname
    url = f"https://{host}/sdk"
    user = hv.username or (hv.connection_config or {}).get("username", "")
    password = hv_password(hv)
    if not user or not password:
        raise MtvError("vCenter kullanıcı adı/parolası eksik")

    b64 = lambda v: base64.b64encode(str(v).encode()).decode()
    secret = {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {
            "name": name, "namespace": NS,
            "labels": {"createdForProviderType": "vsphere", "app.kubernetes.io/managed-by": MANAGED_BY},
        },
        "data": {
            "user": b64(user), "password": b64(password),
            "url": b64(url), "insecureSkipVerify": b64("true"),
        },
        "type": "Opaque",
    }
    provider = {
        "apiVersion": "forklift.konveyor.io/v1beta1", "kind": "Provider",
        "metadata": {
            "name": name, "namespace": NS,
            "labels": {"app.kubernetes.io/managed-by": MANAGED_BY},
        },
        "spec": {
            "type": "vsphere", "url": url,
            "secret": {"name": name, "namespace": NS},
        },
    }
    vddk = (vddk_init_image or "").strip()
    if vddk:
        if not re.match(r"^[a-zA-Z0-9][\w./:@\-]{0,250}$", vddk):
            raise MtvError("Geçersiz VDDK imaj adresi")
        provider["spec"]["settings"] = {"vddkInitImage": vddk}

    client = _client(cluster)
    try:
        _apply(client, f"/api/v1/namespaces/{NS}/secrets", secret, name)
        _apply(client, f"{FORKLIFT}/namespaces/{NS}/providers", provider, name)
        logger.info("MTV provider oluşturuldu: %s (%s) — %s", name, url, actor)
        return {"name": name, "url": url, "hypervisor_id": hv.id}
    finally:
        client.logout()


def migration_targets(cluster: OpenShiftCluster) -> Dict:
    client = _client(cluster)
    try:
        scs = []
        for s in (_get(client, "/apis/storage.k8s.io/v1/storageclasses") or {}).get("items") or []:
            ann = (s.get("metadata", {}) or {}).get("annotations") or {}
            scs.append({
                "name": s["metadata"]["name"],
                "provisioner": s.get("provisioner"),
                "default": ann.get("storageclass.kubernetes.io/is-default-class") == "true",
            })
        networks = [{"type": "pod", "name": "pod", "label": "Pod ağı (küme içi varsayılan)"}]
        nads = _get(client, "/apis/k8s.cni.cncf.io/v1/network-attachment-definitions")
        if nads:
            by_name: Dict[str, Dict] = {}
            for i in nads.get("items", []):
                md = i.get("metadata", {})
                name, ns = md.get("name"), md.get("namespace")
                if not name:
                    continue
                e = by_name.setdefault(name, {"type": "multus", "name": name, "namespaces": [], "label": name})
                if ns and ns not in e["namespaces"]:
                    e["namespaces"].append(ns)
            for e in by_name.values():
                e["namespaces"].sort()
                e["namespace"] = e["namespaces"][0] if e["namespaces"] else None
                n = len(e["namespaces"])
                e["label"] = f"{e['name']}" + (
                    f" · {n} namespace'te" if n > 1 else (f" ({e['namespace']})" if e["namespace"] else "")
                )
                networks.append(e)
        return {"storage_classes": scs, "networks": networks}
    finally:
        client.logout()


def source_refs(db: Session, hypervisor_id: int, vm_morefs: List[str]) -> Dict:
    _, vc = _vcenter(db, hypervisor_id)
    try:
        if not vc.login():
            raise MtvError("Kaynak vCenter bağlantısı canlı değil")
        return vc.get_vm_resource_refs(vm_morefs)
    except MtvError:
        raise
    except Exception as e:
        raise MtvError(str(e)) from e
    finally:
        try:
            vc.logout()
        except Exception:
            pass


def create_plan(
    cluster: OpenShiftCluster,
    db: Session,
    plan_name: str,
    provider_name: str,
    hypervisor_id: int,
    vms: List[Dict],
    target_namespace: str,
    storage_class: str,
    network: Dict,
    warm: bool = False,
    actor: str = "",
    storage_map: Optional[List[Dict]] = None,
    network_map: Optional[List[Dict]] = None,
) -> Dict:
    if not vms:
        raise MtvError("En az bir VM seçin")
    pname = _rfc1123(plan_name)
    tns = _rfc1123(target_namespace)
    _, vc = _vcenter(db, hypervisor_id)
    try:
        if not vc.login():
            raise MtvError("Kaynak vCenter bağlantısı canlı değil")

        def _net_dest(spec: Dict) -> Dict:
            if (spec or {}).get("type") == "multus":
                if not spec.get("name"):
                    raise MtvError("Multus ağ eşlemesinde ağ adı zorunlu")
                available = spec.get("namespaces") or []
                ns = spec.get("namespace")
                if tns in available:
                    ns = tns
                return {"type": "multus", "namespace": ns or tns, "name": spec["name"]}
            return {"type": "pod"}

        default_net = _net_dest(network)

        if storage_map:
            entries = []
            for m in storage_map:
                sid, sc = (m.get("source_id") or "").strip(), (m.get("storage_class") or "").strip()
                if not sid:
                    continue
                if not sc:
                    raise MtvError(f"'{m.get('source_name') or sid}' datastore'u için storage class seçilmedi")
                entries.append({"source": {"id": sid}, "destination": {"storageClass": sc}})
            if not entries:
                raise MtvError("Depolama eşlemesi boş")
            storage_entries = entries
        else:
            if not storage_class:
                raise MtvError("Storage class seçilmedi")
            datastores = vc.get_datastores()
            if not datastores:
                raise MtvError("Kaynak datastore listesi alınamadı")
            storage_entries = [
                {"source": {"id": d["moref"]}, "destination": {"storageClass": storage_class}}
                for d in datastores
            ]

        if network_map:
            entries = []
            for m in network_map:
                sid = (m.get("source_id") or "").strip()
                if not sid:
                    continue
                entries.append({"source": {"id": sid}, "destination": _net_dest(m)})
            if not entries:
                raise MtvError("Ağ eşlemesi boş")
            network_entries = entries
        else:
            networks = vc.get_networks()
            network_entries = [
                {"source": {"id": n["moref"]}, "destination": default_net} for n in networks
            ]

        netmap = {
            "apiVersion": "forklift.konveyor.io/v1beta1", "kind": "NetworkMap",
            "metadata": {
                "name": pname, "namespace": NS,
                "labels": {"app.kubernetes.io/managed-by": MANAGED_BY, "plan": pname},
            },
            "spec": {
                "provider": {
                    "source": {"name": provider_name, "namespace": NS},
                    "destination": {"name": "host", "namespace": NS},
                },
                "map": network_entries,
            },
        }
        stormap = {
            "apiVersion": "forklift.konveyor.io/v1beta1", "kind": "StorageMap",
            "metadata": {
                "name": pname, "namespace": NS,
                "labels": {"app.kubernetes.io/managed-by": MANAGED_BY, "plan": pname},
            },
            "spec": {
                "provider": {
                    "source": {"name": provider_name, "namespace": NS},
                    "destination": {"name": "host", "namespace": NS},
                },
                "map": storage_entries,
            },
        }
        plan = {
            "apiVersion": "forklift.konveyor.io/v1beta1", "kind": "Plan",
            "metadata": {
                "name": pname, "namespace": NS,
                "labels": {"app.kubernetes.io/managed-by": MANAGED_BY},
            },
            "spec": {
                "provider": {
                    "source": {"name": provider_name, "namespace": NS},
                    "destination": {"name": "host", "namespace": NS},
                },
                "targetNamespace": tns,
                "warm": bool(warm),
                "map": {
                    "network": {"name": pname, "namespace": NS},
                    "storage": {"name": pname, "namespace": NS},
                },
                "vms": [{"id": v["id"]} for v in vms],
            },
        }

        client = _client(cluster)
        try:
            try:
                _apply(
                    client, "/api/v1/namespaces",
                    {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": tns}},
                    tns,
                )
            except MtvError as e:
                logger.warning("Hedef namespace oluşturulamadı (%s): %s", tns, e)

            if any((e.get("destination") or {}).get("type") == "multus" for e in network_entries):
                nad_ns: Dict[str, set] = {}
                data = _get(client, "/apis/k8s.cni.cncf.io/v1/network-attachment-definitions") or {}
                for item in data.get("items", []):
                    md = item.get("metadata", {})
                    if md.get("name"):
                        nad_ns.setdefault(md["name"], set()).add(md.get("namespace"))
                for entry in network_entries:
                    dest = entry.get("destination") or {}
                    if dest.get("type") != "multus":
                        continue
                    avail = nad_ns.get(dest.get("name"), set())
                    if tns in avail:
                        dest["namespace"] = tns
                    elif NS in avail:
                        dest["namespace"] = NS
                    else:
                        raise MtvError(
                            f"'{dest.get('name')}' NAD hedef namespace '{tns}' veya '{NS}' içinde yok — "
                            f"NAD'i kopyalayın ya da Pod ağını seçin."
                            + (f" (Mevcut: {', '.join(sorted(a for a in avail if a)[:5])})" if avail else "")
                        )

            _apply(client, f"{FORKLIFT}/namespaces/{NS}/networkmaps", netmap, pname)
            _apply(client, f"{FORKLIFT}/namespaces/{NS}/storagemaps", stormap, pname)
            _apply(client, f"{FORKLIFT}/namespaces/{NS}/plans", plan, pname)
            logger.info("MTV planı oluşturuldu: %s (%s VM) — %s", pname, len(vms), actor)
            return {"name": pname, "vms": len(vms), "warm": bool(warm)}
        finally:
            client.logout()
    finally:
        try:
            vc.logout()
        except Exception:
            pass


def list_plans(cluster: OpenShiftCluster) -> List[Dict]:
    client = _client(cluster)
    try:
        data = _get(client, f"{FORKLIFT}/namespaces/{NS}/plans") or {}
        migs = _get(client, f"{FORKLIFT}/namespaces/{NS}/migrations") or {}
        last_mig: Dict[str, Dict] = {}
        for m in migs.get("items", []):
            p = (m.get("spec") or {}).get("plan", {}).get("name")
            if p and (
                p not in last_mig
                or m["metadata"]["creationTimestamp"] > last_mig[p]["metadata"]["creationTimestamp"]
            ):
                last_mig[p] = m
        out = []
        for item in data.get("items", []):
            name = item["metadata"]["name"]
            ready = _cond(item, "Ready")
            succeeded = _cond(item, "Succeeded")
            failed = _cond(item, "Failed")
            executing = _cond(item, "Executing")
            crit = next(
                (x for x in (item.get("status", {}) or {}).get("conditions") or []
                 if x.get("category") == "Critical"),
                None,
            )
            state = (
                "başarılı" if succeeded and succeeded.get("status") == "True"
                else "BAŞARISIZ" if failed and failed.get("status") == "True"
                else "çalışıyor" if executing and executing.get("status") == "True"
                else "hazır" if ready and ready.get("status") == "True"
                else "doğrulanıyor"
            )
            out.append({
                "name": name,
                "target_namespace": (item.get("spec") or {}).get("targetNamespace"),
                "warm": (item.get("spec") or {}).get("warm", False),
                "vm_count": len((item.get("spec") or {}).get("vms", [])),
                "state": state,
                "error": crit.get("message") if crit else None,
                "started": name in last_mig,
            })
        return out
    finally:
        client.logout()


def start_plan(cluster: OpenShiftCluster, plan_name: str, actor: str = "") -> Dict:
    pname = _rfc1123(plan_name)
    mig = {
        "apiVersion": "forklift.konveyor.io/v1beta1", "kind": "Migration",
        "metadata": {
            "generateName": f"{pname}-", "namespace": NS,
            "labels": {"app.kubernetes.io/managed-by": MANAGED_BY, "plan": pname},
        },
        "spec": {"plan": {"name": pname, "namespace": NS}},
    }
    client = _client(cluster)
    try:
        r = client._post(f"{FORKLIFT}/namespaces/{NS}/migrations", mig)
        if r.status_code == 403:
            raise MtvError("Yetki yok (403) — 'Yetki ver' komutunu kümede çalıştırın.")
        if r.status_code >= 400:
            raise MtvError(f"Başlatılamadı ({r.status_code}): {(r.text or '')[:300]}")
        created = r.json()
        logger.info("MTV taşıması başlatıldı: %s — %s", pname, actor)
        return {"migration": created["metadata"]["name"]}
    finally:
        client.logout()


def plan_status(cluster: OpenShiftCluster, plan_name: str) -> Dict:
    pname = _rfc1123(plan_name)
    client = _client(cluster)
    try:
        plan = _get(client, f"{FORKLIFT}/namespaces/{NS}/plans/{pname}")
        if plan is None:
            raise MtvError("Plan bulunamadı")
        vms_out = []
        for vm in ((plan.get("status") or {}).get("migration") or {}).get("vms") or []:
            steps = []
            for ph in (vm.get("pipeline") or []):
                pr = ph.get("progress") or {}
                steps.append({
                    "name": ph.get("description") or ph.get("name"),
                    "phase": ph.get("phase"),
                    "completed": pr.get("completed"), "total": pr.get("total"),
                })
            vms_out.append({
                "name": vm.get("name") or vm.get("id"),
                "phase": vm.get("phase"),
                "error": (vm.get("error") or {}).get("reasons"),
                "pipeline": steps,
            })
        conds = [
            {"type": x.get("type"), "status": x.get("status"), "message": x.get("message")}
            for x in (plan.get("status") or {}).get("conditions") or []
        ]
        return {"name": pname, "vms": vms_out, "conditions": conds}
    finally:
        client.logout()


def migration_pods(cluster: OpenShiftCluster, plan_name: str) -> Dict:
    pname = _rfc1123(plan_name)
    client = _client(cluster)
    try:
        plan = _get(client, f"{FORKLIFT}/namespaces/{NS}/plans/{pname}")
        if not plan:
            raise MtvError(f"Plan bulunamadı: {pname}")
        tns = (plan.get("spec") or {}).get("targetNamespace") or ""
        uid = (plan.get("metadata") or {}).get("uid") or ""
        if not tns:
            return {"namespace": "", "pods": []}
        data = _get(client, f"/api/v1/namespaces/{tns}/pods") or {}
        usage = {}
        metrics = _get(client, f"/apis/metrics.k8s.io/v1beta1/namespaces/{tns}/pods") or {}
        for m in metrics.get("items", []):
            conts = m.get("containers", []) or []
            if conts:
                usage[(m.get("metadata") or {}).get("name")] = {
                    "cpu": conts[0].get("usage", {}).get("cpu"),
                    "memory": conts[0].get("usage", {}).get("memory"),
                }
        pods = []
        for p in data.get("items", []):
            md, st = p.get("metadata", {}), p.get("status", {})
            name = md.get("name", "")
            labels = md.get("labels", {}) or {}
            belongs = (uid and uid in labels.values()) or name.startswith(f"{pname}-vm-")
            if not belongs:
                continue
            cs = st.get("containerStatuses") or []
            waiting = next(
                (
                    (x.get("state", {}).get("waiting") or {}).get("reason")
                    for x in cs
                    if (x.get("state", {}).get("waiting") or {}).get("reason")
                ),
                None,
            )
            pods.append({
                "name": name,
                "namespace": tns,
                "phase": st.get("phase"),
                "reason": waiting or st.get("reason") or st.get("phase"),
                "ready": all(x.get("ready") for x in cs) if cs else False,
                "restarts": sum(x.get("restartCount", 0) for x in cs),
                "age": cluster_ops._age(st.get("startTime") or md.get("creationTimestamp")),
                "containers": [x["name"] for x in (p.get("spec", {}) or {}).get("containers") or []],
                "usage": usage.get(name),
                "healthy": st.get("phase") in ("Running", "Succeeded") and not waiting,
            })
        pods.sort(key=lambda x: x["name"])
        return {"namespace": tns, "pods": pods}
    finally:
        client.logout()


def cancel_plan(cluster: OpenShiftCluster, plan_name: str, actor: str = "") -> Dict:
    pname = _rfc1123(plan_name)
    cancelled = []
    client = _client(cluster)
    try:
        plan = _get(client, f"{FORKLIFT}/namespaces/{NS}/plans/{pname}")
        if not plan:
            raise MtvError(f"Plan bulunamadı: {pname}")
        vms = [{"id": v["id"]} for v in (plan.get("spec") or {}).get("vms") or [] if v.get("id")]
        if not vms:
            raise MtvError("Planda VM yok")
        migs = _get(client, f"{FORKLIFT}/namespaces/{NS}/migrations") or {}
        for m in migs.get("items", []):
            if (m.get("spec") or {}).get("plan", {}).get("name") != pname:
                continue
            if (m.get("status") or {}).get("completed"):
                continue
            mname = m["metadata"]["name"]
            r = client._patch(
                f"{FORKLIFT}/namespaces/{NS}/migrations/{mname}",
                {"spec": {"cancel": vms}},
                content_type="application/merge-patch+json",
            )
            if r.status_code == 403:
                raise MtvError("Yetki yok (403) — MTV yazma izni gerekli")
            if r.status_code >= 400:
                raise MtvError(f"İptal edilemedi ({r.status_code}): {(r.text or '')[:200]}")
            cancelled.append(mname)
        if not cancelled:
            raise MtvError("İptal edilecek çalışan taşıma yok")
        logger.info("MTV taşıması iptal edildi: %s — %s", pname, actor)
        return {"plan": pname, "cancelled": cancelled, "vms": len(vms)}
    finally:
        client.logout()


def delete_plan(cluster: OpenShiftCluster, plan_name: str, actor: str = "") -> Dict:
    pname = _rfc1123(plan_name)
    deleted = []
    client = _client(cluster)
    try:
        migs = _get(client, f"{FORKLIFT}/namespaces/{NS}/migrations") or {}
        for m in migs.get("items", []):
            if (m.get("spec") or {}).get("plan", {}).get("name") == pname:
                client._delete(f"{FORKLIFT}/namespaces/{NS}/migrations/{m['metadata']['name']}")
        for kind in ("plans", "networkmaps", "storagemaps"):
            r = client._delete(f"{FORKLIFT}/namespaces/{NS}/{kind}/{pname}")
            if r.status_code == 403:
                raise MtvError("Yetki yok (403)")
            if r.status_code < 300 or r.status_code == 404:
                deleted.append(kind)
        logger.info("MTV planı silindi: %s — %s", pname, actor)
        return {"deleted": deleted}
    finally:
        client.logout()


RBAC_YAML = """apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ainew-mtv
  namespace: openshift-mtv
rules:
  - apiGroups: ["forklift.konveyor.io"]
    resources: ["*"]
    verbs: ["*"]
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "create", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ainew-kubevirt-mtv
rules:
  - apiGroups: ["kubevirt.io"]
    resources: ["virtualmachines", "virtualmachineinstances"]
    verbs: ["get", "list", "watch", "create", "delete", "patch", "update"]
  - apiGroups: ["snapshot.kubevirt.io"]
    resources: ["virtualmachinesnapshots", "virtualmachinerestores", "virtualmachinesnapshotcontents"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: ["clone.kubevirt.io"]
    resources: ["virtualmachineclones"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: ["cdi.kubevirt.io"]
    resources: ["datavolumes"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["subresources.kubevirt.io"]
    resources: ["virtualmachines/start", "virtualmachines/stop", "virtualmachines/restart"]
    verbs: ["update"]
  - apiGroups: ["subresources.kubevirt.io"]
    resources: ["virtualmachineinstances/vnc", "virtualmachineinstances/console"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list", "create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ainew-kubevirt-mtv
subjects:
  - kind: ServiceAccount
    name: ainew-viewer
    namespace: default
roleRef:
  kind: ClusterRole
  name: ainew-kubevirt-mtv
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ainew-workloads
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["patch", "update"]
  - apiGroups: ["apps"]
    resources: ["deployments/scale", "statefulsets/scale"]
    verbs: ["patch", "update"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ainew-workloads
subjects:
  - kind: ServiceAccount
    name: ainew-viewer
    namespace: default
roleRef:
  kind: ClusterRole
  name: ainew-workloads
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ainew-mtv
  namespace: openshift-mtv
subjects:
  - kind: ServiceAccount
    name: ainew-viewer
    namespace: default
roleRef:
  kind: Role
  name: ainew-mtv
  apiGroup: rbac.authorization.k8s.io
"""
