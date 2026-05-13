"""
oVirt/RHEV REST API Client
"""
import requests
import logging
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
