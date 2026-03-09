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
    
    def list_vms(self) -> List[Dict]:
        """VM listesini getir"""
        try:
            response = self.session.get(f"{self.base_url}/vms")
            if response.status_code != 200:
                logger.error(f"oVirt API error: {response.status_code} - {response.text}")
                return []
            
            data = response.json()
            vms = data.get("vm", [])
            
            inventory = []
            for vm in vms:
                vm_name = vm.get("name", "Unknown")
                vm_id = vm.get("id")
                
                # NIC bilgisi al (IP için)
                ip_address = ""
                try:
                    nic_response = self.session.get(f"{self.base_url}/vms/{vm_id}/nics")
                    if nic_response.status_code == 200:
                        nics = nic_response.json().get("nic", [])
                        for nic in nics:
                            reported_devices = nic.get("reported_devices", {})
                            if reported_devices:
                                reported_device = reported_devices.get("reported_device", [])
                                if reported_device and len(reported_device) > 0:
                                    ips = reported_device[0].get("ips", {}).get("ip", [])
                                    if ips and len(ips) > 0:
                                        ip_address = ips[0].get("address", "")
                                        break
                except Exception as e:
                    logger.warning(f"Could not get IP for VM {vm_name}: {e}")
                
                # VM detayları
                cpu_topology = vm.get("cpu", {}).get("topology", {})
                cpu_cores = cpu_topology.get("cores", 0) * cpu_topology.get("sockets", 1)
                memory_bytes = vm.get("memory", 0)
                memory_gb = int(memory_bytes / (1024**3)) if memory_bytes else 0
                
                vm_data = {
                    "name": vm_name,
                    "ip_address": ip_address,
                    "hostname": vm_name,
                    "os_type": vm.get("os", {}).get("type", ""),
                    "cpu_cores": cpu_cores,
                    "memory_gb": memory_gb,
                    "status": vm.get("status", "unknown")
                }
                inventory.append(vm_data)
            
            logger.info(f"Synced {len(inventory)} VMs from oVirt {self.host}")
            return inventory
            
        except Exception as e:
            logger.error(f"oVirt list_vms error: {e}")
            return []
