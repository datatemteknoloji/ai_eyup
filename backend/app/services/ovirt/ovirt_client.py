"""
oVirt/RHEV / OLVM REST API Client
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth
from urllib3.exceptions import InsecureRequestWarning

from app.services.ovirt.ovirt_parse import (
    OVirtError,
    cluster_row,
    cpu_count,
    event_severity,
    first_ipv4,
    guest_os_full,
    host_metrics_from_stats,
    memory_bytes,
    nested_id,
    nested_name,
    next_link,
    nics_to_network_info,
    power_fields,
    statistic_map,
    storage_domain_row,
    to_int,
    unwrap_items,
    vm_stats_to_live,
)

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)


class OVirtClient:
    """oVirt/RHEV REST API client"""
    
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False, port: Optional[int] = None):
        self.host = host.strip()
        self.password = password or ""
        self.verify_ssl = verify_ssl
        if username and "@" not in username:
            self.username = f"{username.strip()}@internal"
        else:
            self.username = (username or "").strip()
        if ":" in self.host:
            netloc = self.host
        elif port and int(port) != 443:
            netloc = f"{self.host}:{port}"
        else:
            netloc = self.host
        self.base_url = f"https://{netloc}/ovirt-engine/api"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.auth = HTTPBasicAuth(self.username, self.password)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

    def test_connection(self) -> Tuple[bool, str]:
        """Bağlantıyı test et. Returns (success, detail_message)."""
        try:
            response = self.session.get(f"{self.base_url}/vms", timeout=15)
            if response.status_code == 200:
                return True, ""
            if response.status_code == 401:
                return False, "401 Yetkisiz - Kullanıcı adı veya şifre hatalı (oVirt için genelde admin)"
            if response.status_code == 403:
                return False, "403 Erişim reddedildi"
            return False, f"HTTP {response.status_code}: {(response.text or '')[:200]}"
        except requests.exceptions.SSLError:
            return False, "SSL hatası - Sertifika doğrulanamadı"
        except requests.exceptions.ConnectTimeout:
            return False, "Bağlantı zaman aşımı - Host ve port (443) erişilebilir mi?"
        except requests.exceptions.ConnectionError as e:
            logger.error(f"oVirt connection error: {e}")
            return False, "Bağlantı kurulamadı - IP/hostname ve port kontrol edin"
        except Exception as e:
            logger.error(f"oVirt connection test failed: {e}")
            return False, str(e)
    
    @staticmethod
    def _to_int(val, default: int = 0) -> int:
        return to_int(val, default)

    def _request(self, method: str, path: str, *, params=None, json=None, timeout: int = 30):
        url = path if str(path).startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        r = self.session.request(method, url, params=params, json=json, timeout=timeout)
        return r

    def _paged(self, path: str, *item_keys: str, params: Optional[dict] = None, timeout: int = 60) -> List[Dict]:
        params = dict(params or {})
        params.setdefault("max", 200)
        items: List[Dict] = []
        url = f"{self.base_url}/{path.lstrip('/')}"
        use_params = params
        pages = 0
        while url and pages < 80:
            r = self.session.get(url, params=use_params, timeout=timeout)
            if r.status_code != 200:
                raise OVirtError(
                    f"HTTP {r.status_code}: {(r.text or '')[:240]}",
                    status_code=r.status_code,
                )
            chunk = unwrap_items(r.json() if r.text else {}, *item_keys)
            items.extend(chunk)
            nxt = next_link(r.headers)
            if nxt:
                url = nxt if nxt.startswith("http") else self._resolve_url(nxt)
                use_params = None
                pages += 1
                continue
            if len(chunk) < int(params.get("max") or 200):
                break
            pages += 1
            use_params = dict(params)
            use_params["page"] = pages + 1
            url = f"{self.base_url}/{path.lstrip('/')}"
        return items

    def _inventory_row(self, vm: Dict) -> Dict:
        vm_id = vm.get("id") or ""
        vm_name = vm.get("name") or "Unknown"
        status, power = power_fields(vm.get("status"))
        mem_b = memory_bytes(vm)
        os_type = ((vm.get("os") or {}).get("type") if isinstance(vm.get("os"), dict) else "") or ""
        gos = guest_os_full(vm)
        fqdn = (vm.get("fqdn") or "").strip()
        host_name = nested_name(vm.get("host"))
        host_ref = nested_id(vm.get("host"))
        cluster_name = nested_name(vm.get("cluster"))
        nics = unwrap_items(vm.get("nics") if isinstance(vm.get("nics"), dict) else vm, "nic", "nics")
        if not nics and isinstance(vm.get("nics"), list):
            nics = [x for x in vm["nics"] if isinstance(x, dict)]
        devices = unwrap_items(
            vm.get("reported_devices") if isinstance(vm.get("reported_devices"), dict) else {},
            "reported_device", "reported_devices",
        )
        ip_address = first_ipv4(devices)
        guest_hn = fqdn if fqdn and fqdn.lower() != vm_name.lower() else (fqdn or "")
        return {
            "name": vm_name,
            "ip_address": ip_address,
            "hostname": guest_hn or vm_name,
            "os_type": gos or os_type,
            "cpu_cores": cpu_count(vm),
            "memory_gb": mem_b // (1024 ** 3) if mem_b > 0 else 0,
            "status": status,
            "power_state": power,
            "vm_id": vm_id,
            "vm_power_state": power,
            "vm_host_name": host_name or None,
            "vm_host_ref": host_ref or None,
            "vm_cluster": cluster_name or None,
            "vm_guest_hostname": guest_hn or None,
            "vm_guest_os_full": gos or None,
            "vm_guest_ip": ip_address or None,
            "vm_network_info": nics_to_network_info(nics, devices) if nics or devices else None,
        }

    def list_vms(self) -> List[Dict]:
        """VM listesi — sayfalı. HTTP hatasında OVirtError (boş liste ≠ hata)."""
        follow = "host,cluster,nics,guest_operating_system"
        try:
            raw = self._paged("vms", "vm", "vms", params={"follow": follow}, timeout=90)
        except OVirtError as exc:
            if exc.status_code in (400, 404):
                raw = self._paged("vms", "vm", "vms", timeout=90)
            else:
                raise
        inventory = [self._inventory_row(vm) for vm in raw]
        logger.info("oVirt/OLVM %s: %s VM listelendi", self.host, len(inventory))
        return inventory

    def fetch_full_details_parallel(
        self,
        vms: List[Dict],
        on_progress: Optional[Callable[[int, int], None]] = None,
        max_workers: int = 8,
    ) -> Dict[str, Dict]:
        need = []
        for vm in vms:
            vid = (vm.get("vm_id") or vm.get("id") or "").strip()
            if vid:
                need.append(vid)
        out: Dict[str, Dict] = {}
        if not need:
            return out
        workers = max(1, min(max_workers, len(need)))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(self.get_vm_full_details, vid): vid for vid in need}
            for fut in as_completed(futs):
                vid = futs[fut]
                done += 1
                try:
                    details = fut.result()
                    if details:
                        out[vid] = details
                except Exception as exc:
                    logger.debug("oVirt full_details %s: %s", vid, exc)
                if on_progress:
                    on_progress(done, len(need))
        return out

    def _resolve_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("http"):
            return href
        # href = "/ovirt-engine/api/..." → host + href (netloc only, no path duplication)
        from urllib.parse import urlparse
        parsed = urlparse(self.base_url)
        base_host = f"{parsed.scheme}://{parsed.netloc}"
        return f"{base_host}{href}" if href.startswith("/") else f"{self.base_url}/{href}"

    def _wait_job(self, job_href: str, timeout: int = 600) -> Tuple[bool, str]:
        """oVirt async job tamamlanana kadar bekle."""
        url = self._resolve_url(job_href)
        if not url:
            return False, "Job URL alınamadı"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code != 200:
                    return False, f"Job sorgu hatası HTTP {r.status_code}"
                job = r.json().get("job") or r.json()
                status = str(job.get("status", "")).lower()
                if status in ("finished", "complete", "completed"):
                    if str(job.get("fault", "")).lower() in ("", "none", "null"):
                        return True, "Tamamlandı"
                    return False, str(job.get("description") or "Job hata ile bitti")
                if status in ("failed", "aborted", "cancelled"):
                    return False, str(job.get("description") or f"Job {status}")
            except Exception as exc:
                logger.warning(f"oVirt job poll error: {exc}")
            time.sleep(3)
        return False, "Job zaman aşımı"

    def list_snapshots(self, vm_id: str) -> List[Dict]:
        try:
            r = self.session.get(f"{self.base_url}/vms/{vm_id}/snapshots", timeout=30)
            if r.status_code != 200:
                return []
            data = r.json()
            snaps = data.get("snapshot") or data.get("snapshots") or []
            if isinstance(snaps, dict):
                snaps = [snaps]
            result = []
            for s in snaps:
                if not isinstance(s, dict):
                    continue
                sid = s.get("id", "")
                if sid in ("00000000-0000-0000-0000-000000000000", ""):
                    continue
                desc = s.get("description") or s.get("id", "")
                result.append({
                    "id": sid,
                    "name": desc.split("\n")[0] if desc else sid,
                    "description": desc,
                    "date": s.get("date"),
                })
            return result
        except Exception as e:
            logger.error(f"oVirt list_snapshots error: {e}")
            return []

    def _wait_snapshot_ok(self, vm_id: str, snap_id: str, timeout: int = 600) -> bool:
        """oVirt snapshot durumu 'ok' olana kadar polling yap."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.session.get(
                    f"{self.base_url}/vms/{vm_id}/snapshots/{snap_id}",
                    timeout=15,
                )
                if r.status_code == 200:
                    snap = r.json().get("snapshot") or r.json()
                    snap_status = str(snap.get("snapshot_status", "")).lower()
                    if snap_status == "ok":
                        return True
                    if snap_status in ("broken", "deleted"):
                        return False
            except Exception as exc:
                logger.debug(f"oVirt snap poll: {exc}")
            time.sleep(5)
        return False

    def create_snapshot(self, vm_id: str, name: str, description: str = "") -> Tuple[bool, str, Optional[str]]:
        desc = name if not description else f"{name}\n{description}"
        # oVirt API: JSON'da flat yapı, XML'de <snapshot> wrapper
        payload = {"description": desc, "persist_memorystate": False}
        try:
            r = self.session.post(
                f"{self.base_url}/vms/{vm_id}/snapshots",
                json=payload,
                timeout=60,
            )
            # 200/201 — snap hemen oluştu
            if r.status_code in (200, 201):
                data = r.json() if r.text else {}
                snap = data.get("snapshot") or data
                snap_id = snap.get("id") if isinstance(snap, dict) else None
                if not snap_id and r.headers.get("Location"):
                    snap_id = r.headers["Location"].rstrip("/").split("/")[-1]
                if snap_id:
                    # Snapshot ok durumunu bekle
                    self._wait_snapshot_ok(vm_id, snap_id, timeout=300)
                return True, "Snapshot oluşturuldu", snap_id

            # 202 — async task başlatıldı, Location header'dan snap id al
            if r.status_code == 202:
                data = r.json() if r.text else {}
                snap = data.get("snapshot") or data
                snap_id = snap.get("id") if isinstance(snap, dict) else None
                if not snap_id and r.headers.get("Location"):
                    loc = r.headers["Location"].rstrip("/")
                    # Location: .../vms/{vm_id}/snapshots/{snap_id}
                    if "/snapshots/" in loc:
                        snap_id = loc.split("/snapshots/")[-1].split("/")[0]
                    else:
                        snap_id = loc.split("/")[-1]

                if snap_id and snap_id not in ("", "00000000-0000-0000-0000-000000000000"):
                    ok = self._wait_snapshot_ok(vm_id, snap_id, timeout=600)
                    if ok:
                        return True, "Snapshot oluşturuldu", snap_id
                    return False, "Snapshot ok durumuna geçmedi", None

                # snap_id yoksa eski yöntem: job takibi
                job_href = r.headers.get("Location", "")
                ok, msg = self._wait_job(job_href)
                if not ok:
                    return False, msg, None
                snaps = self.list_snapshots(vm_id)
                match = next((s for s in snaps if name in s.get("description", "") or s["name"] == name), None)
                latest = snaps[-1] if snaps else None
                found = match or latest
                return True, "Snapshot oluşturuldu", found["id"] if found else None

            return False, f"HTTP {r.status_code}: {(r.text or '')[:300]}", None
        except Exception as e:
            logger.error(f"oVirt create_snapshot error: {e}", exc_info=True)
            return False, str(e), None

    def delete_snapshot(self, vm_id: str, snapshot_id: str) -> Tuple[bool, str]:
        try:
            r = self.session.delete(
                f"{self.base_url}/vms/{vm_id}/snapshots/{snapshot_id}",
                timeout=120,
            )
            if r.status_code in (200, 204):
                return True, "Snapshot silindi"
            if r.status_code == 202:
                ok, msg = self._wait_job(r.headers.get("Location", ""))
                return ok, msg
            return False, f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        except Exception as e:
            logger.error(f"oVirt delete_snapshot error: {e}")
            return False, str(e)

    def find_vm_by_name_or_ip(self, name: str = "", ip: str = "") -> Optional[str]:
        """Tam isim veya IPv4 eşleşmesi — prefix eşleşme yok."""
        name_l = (name or "").strip().lower()
        ip_s = (ip or "").strip()
        try:
            if name_l:
                safe = name_l.replace("'", "")
                r = self.session.get(
                    f"{self.base_url}/vms",
                    params={"search": f"name={safe}", "max": 20},
                    timeout=20,
                )
                if r.status_code == 200:
                    for vm in unwrap_items(r.json(), "vm", "vms"):
                        if (vm.get("name") or "").lower() == name_l:
                            return vm.get("id")
            if ip_s:
                r = self.session.get(
                    f"{self.base_url}/vms",
                    params={"search": f"ipaddr={ip_s}", "max": 20},
                    timeout=20,
                )
                if r.status_code == 200:
                    found = unwrap_items(r.json(), "vm", "vms")
                    if len(found) == 1:
                        return found[0].get("id")
                    for vm in found:
                        devices = unwrap_items(
                            self.session.get(
                                f"{self.base_url}/vms/{vm.get('id')}/reporteddevices",
                                timeout=8,
                            ).json() if vm.get("id") else {},
                            "reported_device", "reported_devices",
                        ) if vm.get("id") else []
                        if first_ipv4(devices) == ip_s:
                            return vm.get("id")
        except Exception as e:
            logger.error("oVirt find_vm_by_name_or_ip error: %s", e)
        return None

    def get_vm_full_details(self, vm_id: str) -> Optional[Dict]:
        """CPU, RAM, disk, ağ, guest, cluster, host."""
        try:
            r = self.session.get(
                f"{self.base_url}/vms/{vm_id}",
                params={"follow": "host,cluster,nics,guest_operating_system,disk_attachments"},
                timeout=25,
            )
            if r.status_code != 200:
                r = self.session.get(f"{self.base_url}/vms/{vm_id}", timeout=20)
            if r.status_code != 200:
                return None
            payload = r.json()
            vm = payload.get("vm") or payload
            if isinstance(vm, list):
                vm = vm[0] if vm else {}

            ncpu = cpu_count(vm)
            mem_b = memory_bytes(vm)
            mem_mb = mem_b // (1024 * 1024) if mem_b > 0 else 0
            _, power_state = power_fields(vm.get("status"))

            cluster_name = nested_name(vm.get("cluster"))
            if not cluster_name:
                href = (vm.get("cluster") or {}).get("href", "")
                if href:
                    try:
                        cr = self.session.get(self._resolve_url(href), timeout=8)
                        if cr.status_code == 200:
                            cd = cr.json()
                            cluster_name = nested_name(cd.get("cluster") or cd)
                    except Exception:
                        pass

            host_name = nested_name(vm.get("host"))
            host_ref = nested_id(vm.get("host"))
            if not host_name:
                href = (vm.get("host") or {}).get("href", "")
                if href:
                    try:
                        hr = self.session.get(self._resolve_url(href), timeout=8)
                        if hr.status_code == 200:
                            hd = hr.json().get("host") or hr.json()
                            host_name = nested_name(hd)
                            host_ref = hd.get("id") or host_ref
                    except Exception:
                        pass

            disk_gb = 0
            disk_names: list = []
            vm_disks: list = []
            storage_domain_name = ""
            try:
                da_r = self.session.get(f"{self.base_url}/vms/{vm_id}/diskattachments", timeout=10)
                das = unwrap_items(da_r.json() if da_r.status_code == 200 else {}, "disk_attachment", "disk_attachments")
                for da in das:
                    disk_href = (da.get("disk") or {}).get("href", "")
                    disk_id = (da.get("disk") or {}).get("id", "")
                    if not disk_href and disk_id:
                        disk_href = f"{self.base_url}/disks/{disk_id}"
                    if not disk_href:
                        continue
                    try:
                        dr = self.session.get(self._resolve_url(disk_href), timeout=8)
                        if dr.status_code != 200:
                            continue
                        disk_d = dr.json().get("disk") or dr.json()
                        psize = self._to_int(disk_d.get("provisioned_size", 0), 0)
                        gb = psize // (1024 ** 3)
                        disk_gb += gb
                        dname = disk_d.get("name") or ""
                        disk_names.append(dname)
                        sds = unwrap_items(disk_d.get("storage_domains") or {}, "storage_domain", "storage_domains")
                        ds_name = nested_name(sds[0]) if sds else ""
                        if sds and not ds_name:
                            sd_href = sds[0].get("href", "")
                            if sd_href:
                                sr = self.session.get(self._resolve_url(sd_href), timeout=8)
                                if sr.status_code == 200:
                                    ds_name = nested_name(sr.json().get("storage_domain") or sr.json())
                        if ds_name and not storage_domain_name:
                            storage_domain_name = ds_name
                        vm_disks.append({
                            "name": dname,
                            "capacity_gb": gb,
                            "datastore": ds_name,
                            "thin": str(disk_d.get("sparse") or "").lower() in ("true", "1"),
                        })
                    except Exception:
                        continue
            except Exception:
                pass

            devices: list = []
            try:
                rd_r = self.session.get(f"{self.base_url}/vms/{vm_id}/reporteddevices", timeout=10)
                if rd_r.status_code == 200:
                    devices = unwrap_items(rd_r.json(), "reported_device", "reported_devices")
            except Exception:
                pass
            guest_ip = first_ipv4(devices)
            nics = unwrap_items(vm.get("nics") if isinstance(vm.get("nics"), dict) else {}, "nic", "nics")
            networks = nics_to_network_info(nics, devices) if (nics or devices) else []
            if not networks:
                for dev in devices:
                    mac = (dev.get("mac") or {}).get("address", "")
                    ips = []
                    ip_list = ((dev.get("ips") or {}).get("ip")) or []
                    if isinstance(ip_list, dict):
                        ip_list = [ip_list]
                    for ip_entry in ip_list:
                        if isinstance(ip_entry, dict) and ip_entry.get("address"):
                            ips.append({"address": ip_entry.get("address"), "version": ip_entry.get("version") or "v4"})
                    networks.append({"name": dev.get("name", ""), "mac": mac, "ips": ips})

            guest_hostname = (vm.get("fqdn") or "").strip()
            gstat = vm.get("guest_operating_system") or {}
            tools_status = ""
            if isinstance(gstat, dict):
                tools_status = str(gstat.get("kernel_version") or "")
            ga_status = vm.get("guest_status") or {}
            if isinstance(ga_status, dict):
                tools_status = str(ga_status.get("state") or tools_status)

            gos = guest_os_full(vm)
            return {
                "vm_id": vm_id,
                "vm_name": vm.get("name", ""),
                "vm_guest_hostname": guest_hostname or None,
                "vm_guest_ip": guest_ip,
                "vm_cpu_count": ncpu,
                "vm_memory_mb": mem_mb,
                "vm_disk_gb": disk_gb,
                "vm_power_state": power_state,
                "vm_tools_status": tools_status,
                "vm_network_info": networks,
                "vm_cluster": cluster_name,
                "vm_host_name": host_name,
                "vm_host_ref": host_ref,
                "vm_datastore": storage_domain_name,
                "vm_hardware_version": (
                    vm.get("version", {}).get("major", "") if isinstance(vm.get("version"), dict) else ""
                ),
                "vm_guest_os_full": gos,
                "os_type": gos or ((vm.get("os") or {}).get("type", "") if isinstance(vm.get("os"), dict) else ""),
                "disk_names": [d for d in disk_names if d],
                "vm_disks": vm_disks,
            }
        except Exception as e:
            logger.error("oVirt get_vm_full_details error: %s", e, exc_info=True)
            return None

    def _statistics(self, path: str) -> Dict[str, float]:
        r = self.session.get(f"{self.base_url}/{path.lstrip('/')}", timeout=15)
        if r.status_code != 200:
            return {}
        return statistic_map(r.json())

    def get_all_host_stats(self) -> List[Dict]:
        try:
            hosts = self._paged("hosts", "host", "hosts", params={"follow": "cluster,summary"}, timeout=60)
        except OVirtError:
            hosts = self._paged("hosts", "host", "hosts", timeout=60)
        out = []
        for host in hosts:
            hid = host.get("id") or ""
            stats = self._statistics(f"hosts/{hid}/statistics") if hid else {}
            if not nested_name(host.get("cluster")):
                href = (host.get("cluster") or {}).get("href", "")
                if href:
                    try:
                        cr = self.session.get(self._resolve_url(href), timeout=8)
                        if cr.status_code == 200:
                            cd = cr.json().get("cluster") or cr.json()
                            host = {**host, "cluster": cd}
                    except Exception:
                        pass
            row = host_metrics_from_stats(host, stats)
            out.append(row)
        return out

    def list_datastores_status(self) -> List[Dict]:
        sds = self._paged("storagedomains", "storage_domain", "storage_domains", timeout=60)
        rows = []
        for sd in sds:
            row = storage_domain_row(sd)
            if row.get("name"):
                rows.append(row)
        return rows

    def list_clusters_status(self) -> List[Dict]:
        clusters = self._paged("clusters", "cluster", "clusters", timeout=45)
        hosts = []
        try:
            hosts = self._paged("hosts", "host", "hosts", timeout=45)
        except OVirtError:
            hosts = []
        by_cluster: Dict[str, int] = {}
        refs: Dict[str, list] = {}
        for h in hosts:
            cid = nested_id(h.get("cluster"))
            if not cid:
                continue
            by_cluster[cid] = by_cluster.get(cid, 0) + 1
            refs.setdefault(cid, []).append(h.get("id"))
        rows = []
        for c in clusters:
            row = cluster_row(c, host_count=by_cluster.get(c.get("id") or "", 0))
            row["host_refs"] = refs.get(c.get("id") or "", [])
            if row.get("name"):
                rows.append(row)
        return rows

    def get_all_vm_live_stats(self) -> List[Dict]:
        try:
            vms = self._paged("vms", "vm", "vms", params={"follow": "host,cluster"}, timeout=90)
        except OVirtError:
            vms = self._paged("vms", "vm", "vms", timeout=90)

        def _one(vm: Dict) -> Dict:
            vid = vm.get("id") or ""
            stats = self._statistics(f"vms/{vid}/statistics") if vid else {}
            return vm_stats_to_live(vm, stats)

        if not vms:
            return []
        workers = max(1, min(8, len(vms)))
        out: List[Dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in pool.map(_one, vms):
                out.append(row)
        return out

    def collect_platform_logs(self, hours: int = 48, max_events: int = 800) -> Dict[str, List[Dict]]:
        from datetime import datetime, timedelta, timezone

        since = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        # oVirt search: events since date
        stamp = since.strftime("%Y-%m-%d %H:%M")
        events = []
        try:
            events = self._paged(
                "events",
                "event",
                "events",
                params={"search": f"time>={stamp}", "max": min(200, max_events)},
                timeout=60,
            )
        except OVirtError as exc:
            logger.warning("oVirt events search failed (%s), unfiltered page", exc)
            events = self._paged("events", "event", "events", params={"max": min(200, max_events)}, timeout=60)
        out = []
        for ev in events[:max_events]:
            sev_raw = ev.get("severity")
            if isinstance(sev_raw, dict):
                sev_raw = sev_raw.get("state") or sev_raw.get("#text")
            vm_obj = ev.get("vm") if isinstance(ev.get("vm"), dict) else {}
            host_obj = ev.get("host") if isinstance(ev.get("host"), dict) else {}
            desc = ev.get("description") or ev.get("name") or "oVirt olayı"
            out.append({
                "id": ev.get("id") or ev.get("code"),
                "event_key": ev.get("id"),
                "kind": "ovirt_event",
                "severity": event_severity(sev_raw),
                "title": desc,
                "timestamp": ev.get("time") or ev.get("origin"),
                "vm_ref": vm_obj.get("id"),
                "vm_name": vm_obj.get("name"),
                "host_ref": host_obj.get("id"),
                "host_name": host_obj.get("name"),
                "entity_name": vm_obj.get("name") or host_obj.get("name") or ev.get("name"),
                "user_name": (ev.get("user") or {}).get("name") if isinstance(ev.get("user"), dict) else None,
                "event_type_id": str(ev.get("code") or ""),
            })
        return {"events": out, "errors": []}

