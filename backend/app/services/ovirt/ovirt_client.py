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
        base = self.base_url.rsplit("/api", 1)[0]
        return f"{base}{href}" if href.startswith("/") else f"{self.base_url}/{href}"

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

    def create_snapshot(self, vm_id: str, name: str, description: str = "") -> Tuple[bool, str, Optional[str]]:
        desc = name if not description else f"{name}\n{description}"
        payload = {"snapshot": {"description": desc, "persist_memorystate": False}}
        try:
            r = self.session.post(
                f"{self.base_url}/vms/{vm_id}/snapshots",
                json=payload,
                timeout=60,
            )
            if r.status_code in (200, 201):
                data = r.json() if r.text else {}
                snap = data.get("snapshot") or data
                snap_id = snap.get("id") if isinstance(snap, dict) else None
                if not snap_id and r.headers.get("Location"):
                    snap_id = r.headers["Location"].rstrip("/").split("/")[-1]
                return True, "Snapshot oluşturuldu", snap_id

            if r.status_code == 202:
                job_href = r.headers.get("Location", "")
                ok, msg = self._wait_job(job_href)
                if not ok:
                    return False, msg, None
                snaps = self.list_snapshots(vm_id)
                match = next((s for s in snaps if s["name"] == name or name in s.get("description", "")), None)
                if match:
                    return True, msg, match["id"]
                latest = snaps[-1] if snaps else None
                return True, msg, latest["id"] if latest else None

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

