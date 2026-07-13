"""
oVirt/RHEV REST API Client
"""
import requests
import logging
import time
from typing import List, Dict, Optional, Tuple
from requests.auth import HTTPBasicAuth
from urllib3.exceptions import InsecureRequestWarning

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
        """oVirt API bazen sayıları string olarak döndürür. Güvenli dönüşüm."""
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def list_vms(self) -> List[Dict]:
        """VM listesini getir — oVirt ve OLVM (Oracle Linux Virtualization Manager) destekli."""
        try:
            # Sayfalama: max=100 ile toplu çek
            response = self.session.get(
                f"{self.base_url}/vms",
                params={"max": 500},
                timeout=30,
            )
            if response.status_code != 200:
                logger.error(f"oVirt API error: {response.status_code} - {response.text[:200]}")
                return []

            data = response.json()
            # oVirt: {"vm": [...]}  veya  {"vms": [...]}
            vms = data.get("vm") or data.get("vms") or []
            if isinstance(vms, dict):
                vms = [vms]

            inventory = []
            for vm in vms:
                vm_name = vm.get("name", "Unknown")
                vm_id   = vm.get("id", "")

                # ── IP adresi (/vms/{id}/reporteddevices) ────────────────────
                ip_address = ""
                try:
                    rd_r = self.session.get(
                        f"{self.base_url}/vms/{vm_id}/reporteddevices",
                        timeout=10,
                    )
                    if rd_r.status_code == 200:
                        rd_data = rd_r.json()
                        devices = rd_data.get("reported_device", [])
                        if isinstance(devices, dict):
                            devices = [devices]
                        for dev in devices:
                            ip_list = dev.get("ips", {}).get("ip", [])
                            if isinstance(ip_list, dict):
                                ip_list = [ip_list]
                            for ip_entry in ip_list:
                                addr = ip_entry.get("address", "")
                                ver  = ip_entry.get("version", "v4")
                                if (addr and ver == "v4"
                                        and not addr.startswith("127.")
                                        and not addr.startswith("169.254")):
                                    ip_address = addr
                                    break
                            if ip_address:
                                break
                except Exception as exc:
                    logger.debug(f"IP bilgisi alınamadı ({vm_name}): {exc}")

                # ── CPU / RAM ─────────────────────────────────────────────────
                cpu_topology = vm.get("cpu", {}).get("topology", {})
                cores   = self._to_int(cpu_topology.get("cores",   1), 1)
                sockets = self._to_int(cpu_topology.get("sockets", 1), 1)
                threads = self._to_int(cpu_topology.get("threads", 1), 1)
                cpu_cores = cores * sockets * threads

                memory_bytes = self._to_int(vm.get("memory", 0), 0)
                memory_gb    = memory_bytes // (1024 ** 3) if memory_bytes > 0 else 0

                # ── OS Tipi ──────────────────────────────────────────────────
                os_type = vm.get("os", {}).get("type", "") or ""

                # ── Durum ────────────────────────────────────────────────────
                # oVirt status: "up" | "down" | "suspended" | "paused" | ...
                raw_status = vm.get("status", "unknown")
                if isinstance(raw_status, dict):
                    raw_status = raw_status.get("#text", raw_status.get("state", "unknown"))
                status = "ONLINE" if str(raw_status).lower() in ("up", "powering_up") else \
                         "OFFLINE" if str(raw_status).lower() in ("down", "not_responding") else \
                         str(raw_status).upper()

                inventory.append({
                    "name":       vm_name,
                    "ip_address": ip_address,
                    "hostname":   vm_name,
                    "os_type":    os_type,
                    "cpu_cores":  cpu_cores,
                    "memory_gb":  memory_gb,
                    "status":     status,
                    "vm_id":      vm_id,
                })

            logger.info(f"oVirt/OLVM {self.host}: {len(inventory)} VM senkronize edildi")
            return inventory

        except Exception as e:
            logger.error(f"oVirt list_vms error: {e}", exc_info=True)
            return []

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
        """VM'i isim veya IP ile bul, vm_id döner."""
        try:
            vms_raw = self.session.get(f"{self.base_url}/vms", params={"max": 500}, timeout=30)
            if vms_raw.status_code != 200:
                return None
            data = vms_raw.json()
            vms = data.get("vm") or data.get("vms") or []
            if isinstance(vms, dict):
                vms = [vms]

            name_l = (name or "").lower()

            # 1) İsim eşleşmesi
            if name_l:
                for vm in vms:
                    if vm.get("name", "").lower() == name_l:
                        return vm.get("id")
                # Kısmi eşleşme (hostname prefix)
                for vm in vms:
                    if name_l and vm.get("name", "").lower().startswith(name_l[:8]):
                        return vm.get("id")

            # 2) IP eşleşmesi (reporteddevices)
            if ip:
                for vm in vms:
                    vm_id = vm.get("id", "")
                    if not vm_id:
                        continue
                    try:
                        rd_r = self.session.get(
                            f"{self.base_url}/vms/{vm_id}/reporteddevices", timeout=8
                        )
                        if rd_r.status_code != 200:
                            continue
                        devices = rd_r.json().get("reported_device", [])
                        if isinstance(devices, dict):
                            devices = [devices]
                        for dev in devices:
                            for ip_entry in (dev.get("ips", {}).get("ip", []) or []):
                                if isinstance(ip_entry, dict) and ip_entry.get("address") == ip:
                                    return vm_id
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"oVirt find_vm_by_name_or_ip error: {e}")
        return None

    def get_vm_full_details(self, vm_id: str) -> Optional[Dict]:
        """VM'in tüm detaylarını tek sözlükte döner (CPU, RAM, disk, ağ, guest, cluster)."""
        try:
            r = self.session.get(f"{self.base_url}/vms/{vm_id}", timeout=20)
            if r.status_code != 200:
                return None
            vm = r.json().get("vm") or r.json()
            if isinstance(vm, list):
                vm = vm[0] if vm else {}

            # CPU
            cpu_topo = vm.get("cpu", {}).get("topology", {})
            cpu_count = (
                self._to_int(cpu_topo.get("cores", 1), 1)
                * self._to_int(cpu_topo.get("sockets", 1), 1)
                * self._to_int(cpu_topo.get("threads", 1), 1)
            )

            # RAM
            mem_bytes = self._to_int(vm.get("memory", 0), 0)
            mem_mb = mem_bytes // (1024 * 1024) if mem_bytes > 0 else 0

            # Güç durumu
            raw_status = vm.get("status", "unknown")
            if isinstance(raw_status, dict):
                raw_status = raw_status.get("#text", "unknown")
            power_state = str(raw_status).lower()

            # Cluster
            cluster_href = (vm.get("cluster") or {}).get("href", "")
            cluster_name = ""
            if cluster_href:
                try:
                    cr = self.session.get(self._resolve_url(cluster_href), timeout=8)
                    if cr.status_code == 200:
                        cd = cr.json()
                        cluster_name = (cd.get("cluster") or cd).get("name", "") if isinstance(cd, dict) else ""
                except Exception:
                    pass

            # Disk bilgileri
            disk_gb = 0
            disk_names: list = []
            try:
                da_r = self.session.get(f"{self.base_url}/vms/{vm_id}/diskattachments", timeout=10)
                if da_r.status_code == 200:
                    das = da_r.json().get("disk_attachment") or []
                    if isinstance(das, dict):
                        das = [das]
                    for da in das:
                        disk_href = (da.get("disk") or {}).get("href", "")
                        if disk_href:
                            try:
                                dr = self.session.get(self._resolve_url(disk_href), timeout=8)
                                if dr.status_code == 200:
                                    disk_d = dr.json().get("disk") or dr.json()
                                    psize = self._to_int(disk_d.get("provisioned_size", 0), 0)
                                    disk_gb += psize // (1024 ** 3)
                                    disk_names.append(disk_d.get("name", ""))
                            except Exception:
                                pass
            except Exception:
                pass

            # Guest (network + hostname via reporteddevices)
            guest_ip = ""
            networks: list = []
            guest_hostname = ""
            try:
                rd_r = self.session.get(f"{self.base_url}/vms/{vm_id}/reporteddevices", timeout=10)
                if rd_r.status_code == 200:
                    devices = rd_r.json().get("reported_device", [])
                    if isinstance(devices, dict):
                        devices = [devices]
                    for dev in devices:
                        mac = (dev.get("mac") or {}).get("address", "")
                        ips: list = []
                        for ip_entry in (dev.get("ips", {}).get("ip", []) or []):
                            if isinstance(ip_entry, dict):
                                addr = ip_entry.get("address", "")
                                ver = ip_entry.get("version", "v4")
                                if addr and not addr.startswith("127.") and not addr.startswith("169.254"):
                                    ips.append({"address": addr, "version": ver})
                                    if ver == "v4" and not guest_ip:
                                        guest_ip = addr
                        networks.append({"name": dev.get("name", ""), "mac": mac, "ips": ips})
            except Exception:
                pass

            # Guest hostname (fqdn field)
            guest_hostname = (vm.get("fqdn") or "").strip()

            # Tools status
            gstat = vm.get("guest_operating_system") or {}
            tools_status = ""
            if isinstance(gstat, dict):
                tools_status = gstat.get("kernel_version", "")
            ga_status = (vm.get("guest_status") or {})
            if isinstance(ga_status, dict):
                tools_status = ga_status.get("state", tools_status)

            # Storage domain (primary)
            storage_domain_name = ""
            try:
                if disk_names:
                    pass  # already have disk name
                sd_r = self.session.get(f"{self.base_url}/vms/{vm_id}/diskattachments", timeout=8)
                if sd_r.status_code == 200:
                    das = sd_r.json().get("disk_attachment") or []
                    if isinstance(das, dict):
                        das = [das]
                    if das:
                        disk_href = (das[0].get("disk") or {}).get("href", "")
                        if disk_href:
                            dr2 = self.session.get(self._resolve_url(disk_href), timeout=8)
                            if dr2.status_code == 200:
                                dd = dr2.json().get("disk") or dr2.json()
                                sds = (dd.get("storage_domains") or {}).get("storage_domain", [])
                                if isinstance(sds, dict):
                                    sds = [sds]
                                if sds:
                                    sd_href = sds[0].get("href", "")
                                    if sd_href:
                                        sr = self.session.get(self._resolve_url(sd_href), timeout=8)
                                        if sr.status_code == 200:
                                            sd_d = sr.json()
                                            storage_domain_name = (sd_d.get("storage_domain") or sd_d).get("name", "")
            except Exception:
                pass

            return {
                "vm_id":              vm_id,
                "vm_name":            vm.get("name", ""),
                "vm_guest_hostname":  guest_hostname or vm.get("name", ""),
                "vm_guest_ip":        guest_ip,
                "vm_cpu_count":       cpu_count,
                "vm_memory_mb":       mem_mb,
                "vm_disk_gb":         disk_gb,
                "vm_power_state":     power_state,
                "vm_tools_status":    tools_status,
                "vm_network_info":    networks,
                "vm_cluster":         cluster_name,
                "vm_datastore":       storage_domain_name,
                "vm_hardware_version": vm.get("version", {}).get("major", "") if isinstance(vm.get("version"), dict) else "",
                "os_type":            (vm.get("os") or {}).get("type", ""),
                "disk_names":         [d for d in disk_names if d],
            }
        except Exception as e:
            logger.error(f"oVirt get_vm_full_details error: {e}", exc_info=True)
            return None

