"""vCenter yapılandırma toplayıcısı (salt-okunur SOAP PropertyCollector).

ESXi'ye doğrudan bağlanmaz: NTP, servis durumu, vmknic/vSwitch/uplink,
multipath, lockdown ve HA/DRS kuralları vCenter'ın HostSystem /
ClusterComputeResource nesnelerinden okunur. Syslog hedefi host'un
OptionManager'ından `QueryOptions` ile okunur (yine vCenter üzerinden).

Datastore dosya taraması (sahipsiz VMDK / ISO) `SearchDatastoreSubFolders_Task`
kullanır — bu bir "task" üretir ama hiçbir şeyi değiştirmez (yalnız listeleme).
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.models.hypervisor import Hypervisor
from app.services.findings.collectors import as_bool, as_list

logger = logging.getLogger(__name__)

HOST_PATHS = [
    "name", "parent",
    "runtime.connectionState", "runtime.inMaintenanceMode",
    "summary.overallStatus",
    "config.product.version", "config.product.build", "config.product.fullName",
    "config.dateTimeInfo.ntpConfig.server",
    "config.service.service",
    "config.network.vnic", "config.network.vswitch", "config.network.proxySwitch",
    "config.network.pnic", "config.network.dnsConfig",
    "config.virtualNicManagerInfo.netConfig",
    "config.storageDevice.multipathInfo.lun",
    "config.lockdownMode",
    "configManager.advancedOption",
    "summary.hardware.vendor", "summary.hardware.model",
    "hardware.biosInfo.biosVersion",
]
CLUSTER_PATHS = ["name", "host", "datastore", "configurationEx", "summary.numEffectiveHosts"]
DS_PATHS = [
    "name", "summary.type", "summary.accessible", "summary.multipleHostAccess",
    "summary.capacity", "summary.freeSpace", "summary.uncommitted",
    "summary.maintenanceMode", "host", "browser",
]
VM_PATHS = ["name", "runtime.host", "runtime.powerState", "config.template", "snapshot.rootSnapshotList"]
VM_FILE_PATHS = VM_PATHS + ["layoutEx.file", "config.hardware.device"]

SAN_TRANSPORTS = (
    "HostFibreChannelTargetTransport",
    "HostInternetScsiTargetTransport",
    "HostFibreChannelOverEthernetTargetTransport",
)
_SYSTEM_FOLDER_RE = re.compile(r"^(\.|vmkdump|vmkdump$|\.vsphere-ha|\.sdd\.sf|\.dvsdata|\.naa|\.locker)", re.I)
_REPLICA_RE = re.compile(r"(replica|_replica|veeam|zerto|srm)", re.I)


_VERSIONED_CLS = None


def _versioned_cls():
    """Ayrı property-red önbelleği olan VCenterClient alt sınıfı.

    SOAPAction sürüm başlığı olmayan çağrılar vCenter'ın en eski API sürümüyle
    yanıtlanır (layoutEx, lockdownMode … InvalidProperty); süreç geneli önbellek
    o redleri tutar. Sürümlü oturum kendi önbellek ad alanını kullanır.
    """
    global _VERSIONED_CLS
    if _VERSIONED_CLS is None:
        from app.services.vmware.vcenter_client import VCenterClient, _HostScopedPropCache

        class _Versioned(VCenterClient):
            @property
            def _invalid_prop_cache(self):
                return _HostScopedPropCache(self._INVALID_PROPS_BY_HOST, f"{self.host}:versioned:")
        _VERSIONED_CLS = _Versioned
    return _VERSIONED_CLS


def versioned_session(client) -> Tuple[Any, str, Dict[str, Any]]:
    """SOAP oturumu + SOAPAction: urn:vim25/<apiVersion>. Döner (sess, url, about)."""
    url = f"https://{client.host}:{client.port}/sdk"
    sess = client._soap_login()
    if not sess:
        return None, url, {}
    about = {}
    try:
        about = read_about(client, sess, url)
    except Exception as exc:
        logger.debug("vCenter about okunamadı: %s", exc)
    api = str(about.get("apiVersion") or "").strip()
    if re.fullmatch(r"[0-9][0-9.]*", api):
        sess.headers["SOAPAction"] = f"urn:vim25/{api}"
    return sess, url, about


def build_client(hv: Hypervisor):
    from app.services.hypervisor_credentials import hv_password
    cc = hv.connection_config or {}
    return _versioned_cls()(
        host=hv.ip_address or hv.hostname,
        username=hv.username or cc.get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
        verify_ssl=bool(cc.get("verify_ssl", False)),
    )


def _soap_logout(client, sess, url: str) -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body><vim25:Logout><vim25:_this type="SessionManager">SessionManager</vim25:_this></vim25:Logout></soapenv:Body>
</soapenv:Envelope>"""
    try:
        sess.post(url, data=body, headers={"Content-Type": "text/xml; charset=utf-8"},
                  verify=client.verify_ssl, timeout=10)
    except Exception:
        pass


def _ref_key(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("_value") or v.get("value") or "")
    return str(v or "")


def _pnic_names(raw: Any) -> List[str]:
    out = []
    for p in as_list(raw):
        s = str(p or "")
        # "key-vim.host.PhysicalNic-vmnic0" → vmnic0
        out.append(s.rsplit("-", 1)[-1] if "PhysicalNic-" in s else s)
    return [x for x in out if x]


def _parse_host(row: Dict[str, Any]) -> Dict[str, Any]:
    services = {}
    for s in as_list(row.get("config.service.service")):
        if isinstance(s, dict) and s.get("key"):
            services[str(s["key"])] = {
                "running": bool(as_bool(s.get("running"))),
                "policy": s.get("policy"),
            }

    vmknics = []
    for v in as_list(row.get("config.network.vnic")):
        if not isinstance(v, dict):
            continue
        ip = ((v.get("spec") or {}).get("ip") or {}) if isinstance(v.get("spec"), dict) else {}
        vmknics.append({
            "device": v.get("device"),
            "portgroup": v.get("portgroup") or "",
            "ip": ip.get("ipAddress") if isinstance(ip, dict) else None,
        })

    vmotion = []
    for nc in as_list(row.get("config.virtualNicManagerInfo.netConfig")):
        if not isinstance(nc, dict) or str(nc.get("nicType")) != "vmotion":
            continue
        for sel in as_list(nc.get("selectedVnic")):
            vmotion.append(str(sel).rsplit("-", 1)[-1])

    vswitches = []
    for vs in as_list(row.get("config.network.vswitch")):
        if not isinstance(vs, dict):
            continue
        spec = vs.get("spec") if isinstance(vs.get("spec"), dict) else {}
        teaming = (((spec.get("policy") or {}).get("nicTeaming") or {}).get("nicOrder") or {}) \
            if isinstance(spec.get("policy"), dict) else {}
        vswitches.append({
            "name": vs.get("name"),
            "kind": "standard",
            "uplinks": sorted(_pnic_names(vs.get("pnic"))),
            "active": sorted(str(x) for x in as_list(teaming.get("activeNic"))),
            "standby": sorted(str(x) for x in as_list(teaming.get("standbyNic"))),
            "portgroups": len(as_list(vs.get("portgroup"))),
        })
    for ps in as_list(row.get("config.network.proxySwitch")):
        if not isinstance(ps, dict):
            continue
        vswitches.append({
            "name": ps.get("dvsName") or ps.get("dvsUuid"),
            "kind": "distributed",
            "uplinks": sorted(_pnic_names(ps.get("pnic"))),
            "active": [], "standby": [],
            "portgroups": None,
        })

    pnics = []
    for p in as_list(row.get("config.network.pnic")):
        if not isinstance(p, dict):
            continue
        ls = p.get("linkSpeed") if isinstance(p.get("linkSpeed"), dict) else None
        pnics.append({"device": p.get("device"), "link_speed_mb": int(ls.get("speedMb") or 0) if ls else 0,
                      "up": bool(ls)})

    luns = []
    for lun in as_list(row.get("config.storageDevice.multipathInfo.lun")):
        if not isinstance(lun, dict):
            continue
        paths = [p for p in as_list(lun.get("path")) if isinstance(p, dict)]
        transports = {
            str((p.get("transport") or {}).get("_type") or "") if isinstance(p.get("transport"), dict) else ""
            for p in paths
        }
        san = any(t in SAN_TRANSPORTS for t in transports)
        alive = [p for p in paths if str(p.get("pathState") or p.get("state") or "").lower() in ("active", "standby")]
        pol = lun.get("policy") if isinstance(lun.get("policy"), dict) else {}
        luns.append({
            "id": lun.get("id") or lun.get("key"),
            "paths": len(paths),
            "alive_paths": len(alive),
            "san": san,
            "policy": pol.get("policy"),
        })

    dns = row.get("config.network.dnsConfig") if isinstance(row.get("config.network.dnsConfig"), dict) else {}
    ntp = sorted(str(x) for x in as_list(row.get("config.dateTimeInfo.ntpConfig.server")) if x)
    return {
        "ref": row.get("_ref"),
        "name": row.get("name"),
        "cluster_ref": _ref_key(row.get("parent")),
        "advanced_option_ref": _ref_key(row.get("configManager.advancedOption")),
        "config": {
            "version": row.get("config.product.version"),
            "build": row.get("config.product.build"),
            "full_name": row.get("config.product.fullName"),
            "ntp_servers": ntp,
            "ntp_policy": (services.get("ntpd") or {}).get("policy"),
            "ssh_policy": (services.get("TSM-SSH") or {}).get("policy"),
            "shell_policy": (services.get("TSM") or {}).get("policy"),
            "dns_servers": sorted(str(x) for x in as_list(dns.get("address")) if x),
            "domain": dns.get("domainName"),
            "vmknics": vmknics,
            "vmotion_vmknics": sorted(set(vmotion)),
            "vswitches": vswitches,
            "pnics": pnics,
            "luns": sorted(luns, key=lambda x: str(x.get("id"))),
            "lockdown_mode": row.get("config.lockdownMode"),
            "vendor": row.get("summary.hardware.vendor"),
            "model": row.get("summary.hardware.model"),
            "bios": row.get("hardware.biosInfo.biosVersion"),
        },
        "state": {
            "connection": row.get("runtime.connectionState"),
            "maintenance": bool(as_bool(row.get("runtime.inMaintenanceMode"))),
            "overall_status": row.get("summary.overallStatus"),
            "ntpd_running": (services.get("ntpd") or {}).get("running"),
            "ssh_running": (services.get("TSM-SSH") or {}).get("running"),
            "shell_running": (services.get("TSM") or {}).get("running"),
        },
    }


def _parse_rules(cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rules = []
    for r in as_list(cfg.get("rule")):
        if not isinstance(r, dict):
            continue
        t = str(r.get("_type") or "")
        kind = (
            "vm_anti_affinity" if "AntiAffinity" in t else
            "vm_affinity" if t.endswith("ClusterAffinityRuleSpec") else
            "vm_host" if "VmHost" in t else
            "dependency" if "Dependency" in t else t
        )
        rules.append({
            "name": r.get("name"),
            "kind": kind,
            "enabled": bool(as_bool(r.get("enabled"))),
            "mandatory": bool(as_bool(r.get("mandatory"))),
            "vms": sorted(_ref_key(v) for v in as_list(r.get("vm"))),
            "vm_group": r.get("vmGroupName"),
            "affine_host_group": r.get("affineHostGroupName"),
            "anti_affine_host_group": r.get("antiAffineHostGroupName"),
        })
    groups = []
    for g in as_list(cfg.get("group")):
        if not isinstance(g, dict):
            continue
        t = str(g.get("_type") or "")
        groups.append({
            "name": g.get("name"),
            "kind": "host" if "Host" in t else "vm",
            "members": sorted(_ref_key(x) for x in as_list(g.get("host") or g.get("vm"))),
        })
    return sorted(rules, key=lambda x: str(x["name"])), sorted(groups, key=lambda x: str(x["name"]))


def _parse_cluster(row: Dict[str, Any]) -> Dict[str, Any]:
    cfg = row.get("configurationEx") if isinstance(row.get("configurationEx"), dict) else {}
    das = cfg.get("dasConfig") if isinstance(cfg.get("dasConfig"), dict) else {}
    drs = cfg.get("drsConfig") if isinstance(cfg.get("drsConfig"), dict) else {}
    pol = das.get("admissionControlPolicy") if isinstance(das.get("admissionControlPolicy"), dict) else {}
    ptype = str(pol.get("_type") or "")
    iso = []
    for opt in as_list(das.get("option")):
        if isinstance(opt, dict) and str(opt.get("key") or "").lower().startswith("das.isolationaddress"):
            iso.append(str(opt.get("value")))
    rules, groups = _parse_rules(cfg)
    return {
        "ref": row.get("_ref"),
        "name": row.get("name"),
        "host_refs": [_ref_key(h) for h in as_list(row.get("host"))],
        "datastore_refs": [_ref_key(d) for d in as_list(row.get("datastore"))],
        "config": {
            "ha_enabled": as_bool(das.get("enabled")),
            "host_monitoring": das.get("hostMonitoring"),
            "admission_control_enabled": as_bool(das.get("admissionControlEnabled")),
            "admission_policy": {
                "type": (
                    "percentage" if "Resources" in ptype else
                    "failover_level" if "FailoverLevel" in ptype else
                    "dedicated_hosts" if "FailoverHost" in ptype else ptype or None
                ),
                "cpu_pct": pol.get("cpuFailoverResourcesPercent"),
                "mem_pct": pol.get("memoryFailoverResourcesPercent"),
                "failover_level": pol.get("failoverLevel"),
                "auto_compute": as_bool(pol.get("autoComputePercentages")),
                "failover_hosts": [_ref_key(h) for h in as_list(pol.get("failoverHosts"))],
            },
            "isolation_addresses": sorted(iso),
            "drs_enabled": as_bool(drs.get("enabled")),
            "drs_behavior": drs.get("defaultVmBehavior"),
            "drs_migration_threshold": drs.get("vmotionRate"),
            "rules": rules,
            "groups": groups,
        },
        "state": {"effective_hosts": row.get("summary.numEffectiveHosts")},
    }


def _parse_datastore(row: Dict[str, Any]) -> Dict[str, Any]:
    mounts = []
    for m in as_list(row.get("host")):
        if not isinstance(m, dict):
            continue
        mi = m.get("mountInfo") if isinstance(m.get("mountInfo"), dict) else {}
        mounts.append({
            "host_ref": _ref_key(m.get("key")),
            "mounted": as_bool(mi.get("mounted")) is not False,
            "accessible": as_bool(mi.get("accessible")) is not False,
        })
    gb = 1024 ** 3

    def _f(k):
        try:
            return round(float(row.get(k)) / gb, 2)
        except (TypeError, ValueError):
            return None

    return {
        "ref": row.get("_ref"),
        "name": row.get("name"),
        "browser": _ref_key(row.get("browser")),
        "config": {
            "type": row.get("summary.type"),
            "multiple_host_access": as_bool(row.get("summary.multipleHostAccess")),
            "mounted_hosts": sorted(m["host_ref"] for m in mounts if m["mounted"]),
        },
        "state": {
            "accessible": as_bool(row.get("summary.accessible")) is not False,
            "maintenance": row.get("summary.maintenanceMode"),
            "capacity_gb": _f("summary.capacity"),
            "free_gb": _f("summary.freeSpace"),
            "uncommitted_gb": _f("summary.uncommitted"),
            "inaccessible_mounts": sorted(m["host_ref"] for m in mounts if not m["accessible"]),
        },
    }


def _flatten_snapshots(tree: Any, out: List[Dict[str, Any]], depth: int = 0) -> None:
    for node in as_list(tree):
        if not isinstance(node, dict) or depth > 32:
            continue
        out.append({
            "name": node.get("name"),
            "id": node.get("id"),
            "ref": _ref_key(node.get("snapshot")),
            "created": node.get("createTime"),
            "description": (node.get("description") or "")[:200],
            "quiesced": as_bool(node.get("quiesced")),
        })
        _flatten_snapshots(node.get("childSnapshotList"), out, depth + 1)


def _parse_vm(row: Dict[str, Any], with_files: bool) -> Dict[str, Any]:
    snaps: List[Dict[str, Any]] = []
    _flatten_snapshots(row.get("snapshot.rootSnapshotList"), snaps)
    vm = {
        "ref": row.get("_ref"),
        "name": row.get("name"),
        "host_ref": _ref_key(row.get("runtime.host")),
        "power": row.get("runtime.powerState"),
        "template": bool(as_bool(row.get("config.template"))),
        "snapshots": snaps,
    }
    if with_files:
        files = []
        for f in as_list(row.get("layoutEx.file")):
            if isinstance(f, dict) and f.get("name"):
                files.append(str(f["name"]))
        isos = []
        for dev in as_list(row.get("config.hardware.device")):
            if not isinstance(dev, dict) or "Cdrom" not in str(dev.get("_type") or ""):
                continue
            b = dev.get("backing") if isinstance(dev.get("backing"), dict) else {}
            if b.get("fileName"):
                isos.append(str(b["fileName"]))
        vm["files"] = files
        vm["isos"] = isos
    return vm


def query_syslog_hosts(client, sess, url: str, option_refs: Dict[str, str]) -> Dict[str, Optional[str]]:
    """host_ref → Syslog.global.logHost değeri (QueryOptions, salt-okunur)."""
    out: Dict[str, Optional[str]] = {}
    for href, oref in option_refs.items():
        if not oref:
            continue
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:QueryOptions>
      <vim25:_this type="OptionManager">{oref}</vim25:_this>
      <vim25:name>Syslog.global.logHost</vim25:name>
    </vim25:QueryOptions>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = sess.post(url, data=body, headers={"Content-Type": "text/xml; charset=utf-8"},
                             verify=client.verify_ssl, timeout=15)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.text)
            val = ""
            for el in root.iter():
                if el.tag.split("}")[-1] == "value":
                    val = (el.text or "").strip()
                    break
            out[href] = val
        except Exception as exc:
            logger.debug("QueryOptions(%s) hata: %s", href, exc)
    return out


def _search_datastore(client, sess, url: str, browser_ref: str, ds_name: str,
                      timeout_sec: int = 600) -> Optional[List[Dict[str, Any]]]:
    from app.services.vmware.vcenter_client import _xml_text
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soapenv:Body>
    <vim25:SearchDatastoreSubFolders_Task>
      <vim25:_this type="HostDatastoreBrowser">{browser_ref}</vim25:_this>
      <vim25:datastorePath>{_xml_text(f"[{ds_name}]")}</vim25:datastorePath>
      <vim25:searchSpec>
        <vim25:query xsi:type="vim25:VmDiskFileQuery">
          <vim25:details>
            <vim25:diskType>false</vim25:diskType>
            <vim25:capacityKb>true</vim25:capacityKb>
            <vim25:hardwareVersion>false</vim25:hardwareVersion>
            <vim25:thin>true</vim25:thin>
          </vim25:details>
        </vim25:query>
        <vim25:query xsi:type="vim25:IsoImageFileQuery"/>
        <vim25:details>
          <vim25:fileType>true</vim25:fileType>
          <vim25:fileSize>true</vim25:fileSize>
          <vim25:modification>true</vim25:modification>
          <vim25:fileOwner>false</vim25:fileOwner>
        </vim25:details>
        <vim25:searchCaseInsensitive>true</vim25:searchCaseInsensitive>
        <vim25:matchPattern>*.vmdk</vim25:matchPattern>
        <vim25:matchPattern>*.iso</vim25:matchPattern>
      </vim25:searchSpec>
    </vim25:SearchDatastoreSubFolders_Task>
  </soapenv:Body>
</soapenv:Envelope>"""
    root = client._soap_post(sess, url, body, timeout=60)
    if root is None:
        return None
    task_id = None
    for el in root.iter():
        if el.tag.split("}")[-1] == "returnval" and (el.text or "").strip():
            task_id = el.text.strip()
            break
    if not task_id:
        return None
    deadline = time.time() + timeout_sec
    poll = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet><vim25:type>Task</vim25:type><vim25:all>false</vim25:all>
          <vim25:pathSet>info.state</vim25:pathSet><vim25:pathSet>info.result</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet><vim25:obj type="Task">{task_id}</vim25:obj><vim25:skip>false</vim25:skip></vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
    while time.time() < deadline:
        proot = client._soap_post(sess, url, poll, timeout=120)
        if proot is None:
            return None
        row = None
        for rv in proot.iter():
            if rv.tag.split("}")[-1] == "returnval":
                row = client._soap_returnval_props(rv)
                break
        state = str((row or {}).get("info.state") or "").lower()
        if state == "error":
            return None
        if state == "success":
            res = (row or {}).get("info.result")
            return [r for r in as_list(res) if isinstance(r, dict)]
        time.sleep(3)
    return None


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def scan_files(client, sess, url: str, datastores: List[Dict[str, Any]],
               vms: List[Dict[str, Any]], max_datastores: int = 200,
               vm_files_known: bool = True) -> Dict[str, Any]:
    """VMDK + ISO listesi; layoutEx / CD-ROM backing ile eşleşmeyenler sahipsiz.

    vm_files_known=False (layoutEx okunamadı) → VMDK'ler listelenmez; aksi halde
    her disk yanlışlıkla sahipsiz görünürdü.
    """
    attached = set()
    owner: Dict[str, str] = {}
    for vm in vms:
        for f in vm.get("files") or []:
            k = f.strip().lower()
            attached.add(k)
            owner.setdefault(k, vm["name"])
    iso_attached: Dict[str, str] = {}
    for vm in vms:
        for f in vm.get("isos") or []:
            iso_attached[f.strip().lower()] = vm["name"]

    files: List[Dict[str, Any]] = []
    scanned = 0
    failed: List[str] = []
    now = datetime.now(timezone.utc)
    for ds in datastores[:max_datastores]:
        if not ds.get("browser") or not (ds.get("state") or {}).get("accessible", True):
            continue
        res = _search_datastore(client, sess, url, ds["browser"], ds["name"])
        if res is None:
            failed.append(ds["name"])
            continue
        scanned += 1
        for folder in res:
            fpath = str(folder.get("folderPath") or "")
            rel_folder = fpath.split("]", 1)[-1].strip().strip("/")
            top = rel_folder.split("/", 1)[0] if rel_folder else ""
            if top and _SYSTEM_FOLDER_RE.match(top):
                continue
            for fi in as_list(folder.get("file")):
                if not isinstance(fi, dict) or not fi.get("path"):
                    continue
                name = str(fi["path"])
                low = name.lower()
                if low.endswith("-ctk.vmdk"):
                    continue
                fp = fpath.strip()
                full = f"{fp} {name}" if fp.endswith("]") else f"{fp.rstrip('/')}/{name}"
                key = full.strip().lower()
                ftype = str(fi.get("_type") or "")
                is_iso = low.endswith(".iso") or "IsoImage" in ftype
                try:
                    size_gb = round(int(fi.get("fileSize") or 0) / (1024 ** 3), 2)
                except (TypeError, ValueError):
                    size_gb = None
                mod = _parse_ts(fi.get("modification"))
                if is_iso:
                    att = key in iso_attached
                    files.append({
                        "kind": "iso", "datastore": ds["name"], "path": full, "name": name,
                        "size_gb": size_gb, "modified_at": mod, "attached": att,
                        "owner_vm": iso_attached.get(key),
                        "extra": {"content_library": "contentlib-" in key},
                    })
                    continue
                if not vm_files_known:
                    continue
                flat_key = key[:-5] + "-flat.vmdk"
                att = key in attached or flat_key in attached
                files.append({
                    "kind": "vmdk", "datastore": ds["name"], "path": full, "name": name,
                    "size_gb": size_gb, "modified_at": mod, "attached": att,
                    "owner_vm": owner.get(key) or owner.get(flat_key),
                    "extra": {
                        "delta": bool(re.search(r"-\d{6}\.vmdk$", low)),
                        "replica_suspect": bool(_REPLICA_RE.search(rel_folder)),
                        "content_library": "contentlib-" in key,
                        "recent": bool(mod and (now - mod).days < 7),
                        "capacity_gb": round(int(fi.get("capacityKb") or 0) / (1024 ** 2), 2)
                        if fi.get("capacityKb") else None,
                        "thin": as_bool(fi.get("thin")),
                        "shared_datastore": bool((ds.get("config") or {}).get("multiple_host_access")),
                    },
                })
    return {"files": files, "scanned": scanned, "failed": failed, "vm_files_known": vm_files_known}


def read_about(client, sess, url: str) -> Dict[str, Any]:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body><vim25:RetrieveServiceContent><vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>
  </vim25:RetrieveServiceContent></soapenv:Body>
</soapenv:Envelope>"""
    root = client._soap_post(sess, url, body, timeout=20)
    if root is None:
        return {}
    for el in root.iter():
        if el.tag.split("}")[-1] == "about":
            d = client._soap_val_to_py(el) or {}
            return {k: d.get(k) for k in ("fullName", "version", "build", "apiVersion", "productLineId")
                    if isinstance(d, dict)}
    return {}


def read_vlcm_hcl(client, clusters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """vLCM donanım uyumluluk raporu (yalnız image-managed cluster'larda vardır)."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        if not client.login():
            return out
    except Exception:
        return out
    base = f"https://{client.host}:{client.port}/api"
    for c in clusters:
        try:
            r = client.session.get(
                f"{base}/esx/settings/clusters/{c['ref']}/software/reports/hardware-compatibility", timeout=30)
        except Exception as exc:
            out[c["name"]] = {"available": False, "reason": str(exc)[:200]}
            continue
        if r.status_code == 200:
            body = r.json() if r.text else {}
            out[c["name"]] = {"available": True, "status": body.get("status"),
                              "server": body.get("server_compatibility") or body.get("hcl_compliance"),
                              "updated": body.get("updated") or body.get("generated_at")}
        else:
            out[c["name"]] = {"available": False, "reason": f"HTTP {r.status_code}"}
    try:
        client.logout()
    except Exception:
        pass
    return out


def collect(hv: Hypervisor, *, file_scan: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False, "error": None, "clusters": [], "hosts": [], "datastores": [], "vms": [],
        "files": None, "file_scan": None, "unsupported_paths": [], "syslog": {}, "about": {}, "hcl": {},
    }
    client = build_client(hv)
    sess, url, about = versioned_session(client)
    out["about"] = about
    if not sess:
        out["error"] = "vCenter SOAP oturumu açılamadı (kimlik bilgisi / erişim)"
        return out
    unsupported: List[str] = []
    try:
        kw = dict(limit=100000, soap_session=sess, soap_url=url)
        hosts_raw = client.retrieve_properties("HostSystem", HOST_PATHS, **kw)
        unsupported += [f"HostSystem.{p}" for p in getattr(client, "last_unsupported_paths", []) or []]
        clusters_raw = client.retrieve_properties("ClusterComputeResource", CLUSTER_PATHS, **kw)
        unsupported += [f"Cluster.{p}" for p in getattr(client, "last_unsupported_paths", []) or []]
        ds_raw = client.retrieve_properties("Datastore", DS_PATHS, **kw)
        vm_raw = client.retrieve_properties("VirtualMachine", VM_FILE_PATHS if file_scan else VM_PATHS, **kw)
        vm_unsupported = list(getattr(client, "last_unsupported_paths", []) or [])
        unsupported += [f"VirtualMachine.{p}" for p in vm_unsupported]
        if not hosts_raw and not clusters_raw:
            out["error"] = "vCenter boş yanıt döndü (yetki veya bağlantı)"
            return out

        clusters = [_parse_cluster(r) for r in clusters_raw]
        cl_by_ref = {c["ref"]: c for c in clusters}
        hosts = []
        for r in hosts_raw:
            h = _parse_host(r)
            c = cl_by_ref.get(h["cluster_ref"])
            h["cluster"] = c["name"] if c else None
            hosts.append(h)
        host_name = {h["ref"]: h["name"] for h in hosts}
        for c in clusters:
            c["host_names"] = sorted(host_name.get(r, r) for r in c["host_refs"])
        datastores = [_parse_datastore(r) for r in ds_raw]
        vms = [_parse_vm(r, file_scan) for r in vm_raw]
        vm_name = {v["ref"]: v["name"] for v in vms}
        # Kural/grup üyelerini okunur isimle zenginleştir
        for c in clusters:
            for rule in c["config"]["rules"]:
                rule["vm_names"] = sorted(vm_name.get(x, x) for x in rule["vms"])
            for g in c["config"]["groups"]:
                g["member_names"] = sorted(
                    (host_name if g["kind"] == "host" else vm_name).get(x, x) for x in g["members"]
                )
        out.update(clusters=clusters, hosts=hosts, datastores=datastores, vms=vms)
        try:
            out["hcl"] = read_vlcm_hcl(client, clusters)
        except Exception as exc:
            logger.debug("vLCM HCL okunamadı: %s", exc)
        try:
            out["syslog"] = query_syslog_hosts(
                client, sess, url, {h["ref"]: h.get("advanced_option_ref") for h in hosts
                                    if (h["state"].get("connection") == "connected")},
            )
        except Exception as exc:
            logger.info("syslog okuma atlandı (%s): %s", hv.name, exc)
        if file_scan:
            try:
                out["file_scan"] = scan_files(client, sess, url, datastores, vms,
                                              vm_files_known="layoutEx.file" not in vm_unsupported)
                out["files"] = out["file_scan"]["files"]
            except Exception as exc:
                logger.warning("datastore taraması başarısız (%s): %s", hv.name, exc)
                out["file_scan"] = {"error": str(exc)}
        out["ok"] = True
        out["unsupported_paths"] = sorted(set(unsupported))
        return out
    except Exception as exc:
        logger.exception("vCenter config toplama hatası (%s)", hv.name)
        out["error"] = f"vCenter okuma hatası: {exc}"
        return out
    finally:
        _soap_logout(client, sess, url)
