"""
oVirt/RHEV REST API Client
"""
import requests
import logging
from typing import List, Dict, Optional
from requests.auth import HTTPBasicAuth
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)


class OVirtClient:
    """oVirt/RHEV REST API client"""
    
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = False):
        self.host = host
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        # oVirt admin@internal format
        if "@" not in username:
            self.username = f"{username}@internal"
        self.base_url = f"https://{host}/ovirt-engine/api"
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.auth = HTTPBasicAuth(self.username, self.password)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
    
    def test_connection(self) -> bool:
        """Bağlantıyı test et"""
        try:
            response = self.session.get(f"{self.base_url}/vms")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"oVirt connection test failed: {e}")
            return False
    
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
