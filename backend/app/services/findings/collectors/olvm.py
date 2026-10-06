"""OLVM / oVirt Manager yapılandırma toplayıcısı (REST, salt-okunur).

Yalnız Manager API kullanılır; KVM hostlara SSH yoktur. Bu yüzden host NTP
ve multipath yol sayısı ölçülemez (`not_measurable` olarak raporlanır).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.hypervisor import Hypervisor
from app.services.findings.collectors import as_bool, as_list

logger = logging.getLogger(__name__)
GB = 1024 ** 3


def build_client(hv: Hypervisor):
    from app.services.hypervisor_credentials import hv_password
    from app.services.ovirt.ovirt_client import OVirtClient
    cc = hv.connection_config or {}
    return OVirtClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or cc.get("username", ""),
        password=hv_password(hv),
        verify_ssl=bool(cc.get("verify_ssl", False)),
        port=hv.port,
    )


def _nested(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _ver(v: Any) -> Optional[str]:
    if not isinstance(v, dict):
        return None
    if v.get("full_version"):
        return str(v["full_version"])
    parts = [v.get(k) for k in ("major", "minor", "build", "revision") if v.get(k) is not None]
    return ".".join(str(p) for p in parts) or None


def _ts(ms_or_iso: Any) -> Optional[str]:
    if ms_or_iso is None:
        return None
    try:
        n = int(ms_or_iso)
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(ms_or_iso)


def _safe_paged(client, path: str, *keys: str, params: Optional[dict] = None,
                fallback_params: Optional[dict] = None, timeout: int = 90) -> Optional[List[Dict[str, Any]]]:
    from app.services.ovirt.ovirt_parse import OVirtError
    try:
        return client._paged(path, *keys, params=params, timeout=timeout)
    except OVirtError as exc:
        if fallback_params is not None:
            try:
                return client._paged(path, *keys, params=fallback_params, timeout=timeout)
            except OVirtError:
                pass
        logger.info("OLVM %s okunamadı: %s", path, exc)
        return None
    except Exception as exc:
        logger.info("OLVM %s okunamadı: %s", path, exc)
        return None


def collect(hv: Hypervisor, *, file_scan: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False, "error": None, "clusters": [], "hosts": [], "datastores": [], "vms": [],
        "files": None, "file_scan": None, "unsupported_paths": [],
    }
    client = build_client(hv)
    ok, msg = client.test_connection()
    if not ok:
        out["error"] = f"OLVM Manager bağlantısı başarısız: {msg}"
        return out

    try:
        r = client._request("GET", "", timeout=20)
        pi = (r.json() or {}).get("product_info") if r.status_code == 200 and r.text else {}
        out["about"] = {"name": (pi or {}).get("name"), "version": _ver((pi or {}).get("version"))}
    except Exception:
        out["about"] = {}
    clusters_raw = _safe_paged(client, "clusters", "cluster", "clusters",
                               params={"follow": "scheduling_policy"}, fallback_params={})
    hosts_raw = _safe_paged(client, "hosts", "host", "hosts", params={"follow": "cluster"}, fallback_params={})
    if clusters_raw is None and hosts_raw is None:
        out["error"] = "OLVM cluster/host listesi okunamadı"
        return out
    sds_raw = _safe_paged(client, "storagedomains", "storage_domain", "storage_domains") or []

    cl_name: Dict[str, str] = {}
    clusters: List[Dict[str, Any]] = []
    for c in clusters_raw or []:
        cid = c.get("id") or ""
        cl_name[cid] = c.get("name") or cid
        fen = c.get("fencing_policy") if isinstance(c.get("fencing_policy"), dict) else {}
        sp = c.get("scheduling_policy") if isinstance(c.get("scheduling_policy"), dict) else {}
        props = {}
        for p in as_list(_nested(sp, "properties", "property")):
            if isinstance(p, dict) and p.get("name"):
                props[str(p["name"])] = p.get("value")
        mem = c.get("memory_policy") if isinstance(c.get("memory_policy"), dict) else {}
        affinity = _safe_paged(client, f"clusters/{cid}/affinitygroups", "affinity_group", "affinity_groups",
                               params={"follow": "vms,hosts"}, fallback_params={}) if cid else None
        groups = []
        for g in affinity or []:
            vms_rule = g.get("vms_rule") if isinstance(g.get("vms_rule"), dict) else {}
            hosts_rule = g.get("hosts_rule") if isinstance(g.get("hosts_rule"), dict) else {}
            positive = as_bool(vms_rule.get("positive")) if vms_rule else as_bool(g.get("positive"))
            groups.append({
                "name": g.get("name"),
                "vm_positive": positive,
                "vm_enforcing": as_bool(vms_rule.get("enforcing")) if vms_rule else as_bool(g.get("enforcing")),
                "vm_rule_enabled": as_bool(vms_rule.get("enabled")) if vms_rule else True,
                "host_positive": as_bool(hosts_rule.get("positive")),
                "host_enforcing": as_bool(hosts_rule.get("enforcing")),
                "host_rule_enabled": as_bool(hosts_rule.get("enabled")),
                "vms": sorted(str(v.get("name") or v.get("id")) for v in as_list(_nested(g, "vms", "vm"))
                              if isinstance(v, dict)),
                "hosts": sorted(str(h.get("name") or h.get("id")) for h in as_list(_nested(g, "hosts", "host"))
                                if isinstance(h, dict)),
            })
        clusters.append({
            "ref": cid,
            "name": c.get("name"),
            "config": {
                "fencing_enabled": as_bool(fen.get("enabled")),
                "skip_if_sd_active": as_bool(_nested(fen, "skip_if_sd_active", "enabled")),
                "skip_if_connectivity_broken": as_bool(_nested(fen, "skip_if_connectivity_broken", "enabled")),
                "scheduling_policy": sp.get("name") or sp.get("id"),
                "scheduling_properties": props,
                "ha_reservation": as_bool(c.get("ha_reservation")),
                "memory_overcommit_pct": _nested(mem, "over_commit", "percent"),
                "version": _ver(c.get("version")),
                "affinity_groups": sorted(groups, key=lambda x: str(x["name"])),
            },
            "state": {},
        })

    hosts: List[Dict[str, Any]] = []
    for h in hosts_raw or []:
        cid = _nested(h, "cluster", "id") or ""
        pm = h.get("power_management") if isinstance(h.get("power_management"), dict) else {}
        hw = h.get("hardware_information") if isinstance(h.get("hardware_information"), dict) else {}
        status = h.get("status")
        if isinstance(status, dict):
            status = status.get("state")
        hosts.append({
            "ref": h.get("id"),
            "name": h.get("name"),
            "cluster": _nested(h, "cluster", "name") or cl_name.get(cid),
            "config": {
                "version": _ver(h.get("version")) or _ver(_nested(h, "os", "version")),
                "os": _nested(h, "os", "type"),
                "power_management_enabled": as_bool(pm.get("enabled")),
                "power_management_kdump": as_bool(pm.get("kdump_detection")),
                "vendor": hw.get("manufacturer"),
                "model": hw.get("product_name"),
            },
            "state": {
                "status": str(status or "").lower(),
                "maintenance": str(status or "").lower() == "maintenance",
                "external_status": h.get("external_status"),
                "spm": _nested(h, "spm", "status", "state") or _nested(h, "spm", "status"),
            },
        })

    datastores: List[Dict[str, Any]] = []
    for sd in sds_raw:
        st = sd.get("status")
        if isinstance(st, dict):
            st = st.get("state")
        dcs = [d for d in as_list(_nested(sd, "data_centers", "data_center")) if isinstance(d, dict)]
        datastores.append({
            "ref": sd.get("id"),
            "name": sd.get("name"),
            "config": {
                "type": sd.get("type"),
                "storage_type": _nested(sd, "storage", "type"),
                "data_centers": len(dcs),
            },
            "state": {
                "status": str(st or "").lower(),
                "external_status": sd.get("external_status"),
                "accessible": str(st or "active").lower() in ("active", "up", "ok", ""),
            },
        })
    # Bağlı (attached) storage domain'lerin gerçek durumu data center altında
    try:
        dcs = _safe_paged(client, "datacenters", "data_center", "data_centers") or []
        st_by_id: Dict[str, str] = {}
        for dc in dcs:
            dcid = dc.get("id")
            if not dcid:
                continue
            for sd in _safe_paged(client, f"datacenters/{dcid}/storagedomains",
                                  "storage_domain", "storage_domains") or []:
                st = sd.get("status")
                if isinstance(st, dict):
                    st = st.get("state")
                if sd.get("id") and st:
                    st_by_id[sd["id"]] = str(st).lower()
        for d in datastores:
            if d["ref"] in st_by_id:
                d["state"]["status"] = st_by_id[d["ref"]]
                d["state"]["accessible"] = st_by_id[d["ref"]] in ("active", "up", "ok")
    except Exception as exc:
        logger.debug("OLVM datacenter storage durumu: %s", exc)

    vms_raw = _safe_paged(client, "vms", "vm", "vms", params={"follow": "snapshots,disk_attachments,cdroms"},
                          fallback_params={"follow": "snapshots"}, timeout=180) or []
    vms: List[Dict[str, Any]] = []
    attached_disks: Dict[str, str] = {}
    iso_attached: Dict[str, str] = {}
    for v in vms_raw:
        snaps = []
        for s in as_list(_nested(v, "snapshots", "snapshot")):
            if not isinstance(s, dict):
                continue
            if str(s.get("snapshot_type") or "").lower() == "active":
                continue
            snaps.append({"name": s.get("description") or s.get("id"), "id": s.get("id"),
                          "created": _ts(s.get("date")), "description": (s.get("description") or "")[:200]})
        for da in as_list(_nested(v, "disk_attachments", "disk_attachment")):
            did = _nested(da, "disk", "id") if isinstance(da, dict) else None
            if did:
                attached_disks[did] = v.get("name")
        for cd in as_list(_nested(v, "cdroms", "cdrom")):
            fid = _nested(cd, "file", "id") if isinstance(cd, dict) else None
            if fid:
                iso_attached[str(fid)] = v.get("name")
        status = v.get("status")
        vms.append({
            "ref": v.get("id"), "name": v.get("name"),
            "host_ref": _nested(v, "host", "id"),
            "power": "poweredOn" if str(status).lower() == "up" else str(status or ""),
            "template": False,
            "snapshots": snaps,
            "affinity_cluster": _nested(v, "cluster", "id"),
        })
    out.update(clusters=clusters, hosts=hosts, datastores=datastores, vms=vms)

    if file_scan:
        tmpl = _safe_paged(client, "templates", "template", "templates",
                           params={"follow": "disk_attachments"}, fallback_params=None) or []
        for t in tmpl:
            for da in as_list(_nested(t, "disk_attachments", "disk_attachment")):
                did = _nested(da, "disk", "id") if isinstance(da, dict) else None
                if did:
                    attached_disks[did] = f"template:{t.get('name')}"
        # VM'den ayrılmış ama snapshot'ta duran disk sahipsiz DEĞİLDİR (silinirse snapshot bozulur).
        for v in vms:
            for s in v["snapshots"][:20]:
                sdisks = _safe_paged(client, f"vms/{v['ref']}/snapshots/{s['id']}/disks", "disk", "disks",
                                     timeout=60) or []
                for sd in sdisks:
                    if sd.get("id") and sd["id"] not in attached_disks:
                        attached_disks[sd["id"]] = f"snapshot:{v['name']}"
        disks = _safe_paged(client, "disks", "disk", "disks", timeout=180)
        sd_name = {d["ref"]: d["name"] for d in datastores}
        files: List[Dict[str, Any]] = []
        if disks is not None:
            for d in disks:
                content = str(d.get("content_type") or "data").lower()
                did = d.get("id") or ""
                sds = [x for x in as_list(_nested(d, "storage_domains", "storage_domain")) if isinstance(x, dict)]
                ds = sd_name.get(sds[0].get("id")) if sds else None
                try:
                    actual = round(int(d.get("actual_size") or 0) / GB, 2)
                    prov = round(int(d.get("provisioned_size") or 0) / GB, 2)
                except (TypeError, ValueError):
                    actual = prov = None
                if content == "iso":
                    files.append({
                        "kind": "iso", "datastore": ds, "path": f"disk:{did}", "name": d.get("alias") or d.get("name"),
                        "size_gb": actual, "modified_at": None, "attached": did in iso_attached,
                        "owner_vm": iso_attached.get(did), "extra": {"disk_id": did},
                    })
                elif content == "data":
                    files.append({
                        "kind": "disk", "datastore": ds, "path": f"disk:{did}", "name": d.get("alias") or d.get("name"),
                        "size_gb": actual, "modified_at": None, "attached": did in attached_disks,
                        "owner_vm": attached_disks.get(did),
                        "extra": {"disk_id": did, "provisioned_gb": prov, "shareable": as_bool(d.get("shareable")),
                                  "status": d.get("status")},
                    })
            out["files"] = files
            out["file_scan"] = {"scanned": len(datastores), "failed": []}
        else:
            out["file_scan"] = {"error": "OLVM disks listesi okunamadı"}
    out["ok"] = True
    return out
