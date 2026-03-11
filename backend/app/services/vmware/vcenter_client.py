"""
VMware vCenter REST API Client
"""
import requests
import logging
from typing import List, Dict, Optional
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)


class VCenterClient:
    """vCenter REST API client"""
    
    def __init__(self, host: str, username: str, password: str, port: int = 443, verify_ssl: bool = False):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.base_url = f"https://{host}:{port}/rest"
        self.session_id = None
        self.session = requests.Session()
        self.session.verify = verify_ssl
    
    def login(self) -> bool:
        """vCenter'a giriş yap"""
        try:
            url = f"{self.base_url}/com/vmware/cis/session"
            response = self.session.post(url, auth=(self.username, self.password))
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get("value")
                self.session.headers.update({"vmware-api-session-id": self.session_id})
                logger.info(f"vCenter login successful: {self.host}")
                return True
            else:
                logger.error(f"vCenter login failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"vCenter login error: {e}")
            return False
    
    def logout(self):
        """vCenter oturumunu kapat"""
        if self.session_id:
            try:
                url = f"{self.base_url}/com/vmware/cis/session"
                self.session.delete(url)
                logger.info("vCenter logout successful")
            except Exception as e:
                logger.error(f"vCenter logout error: {e}")
            finally:
                self.session_id = None
    
    def _api_call(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Generic API call"""
        if not self.session_id:
            logger.warning("No active session, attempting to login...")
            if not self.login():
                return None
        
        try:
            url = f"{self.base_url}{endpoint}"
            if method == "GET":
                response = self.session.get(url)
            elif method == "POST":
                response = self.session.post(url, json=data)
            elif method == "PUT":
                response = self.session.put(url, json=data)
            elif method == "DELETE":
                response = self.session.delete(url)
            else:
                return None
            
            if response.status_code in (200, 201):
                return response.json() if response.text else {}
            else:
                logger.error(f"API call failed: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"API call error: {e}")
            return None
    
    def list_vms(self) -> List[Dict]:
        """VM listesini getir"""
        response = self._api_call("GET", "/vcenter/vm")
        if not response:
            return []
        
        # vCenter bazen list, bazen dict döner
        if isinstance(response, list):
            return response
        elif isinstance(response, dict):
            return response.get("value", [])
        return []
    
    def get_vm_details(self, vm_id: str) -> Optional[Dict]:
        """Tek bir VM'in detaylarını getir"""
        response = self._api_call("GET", f"/vcenter/vm/{vm_id}")
        if not response:
            return None
        
        if isinstance(response, dict) and "value" in response:
            return response["value"]
        return response
    
    def get_vm_guest_info(self, vm_id: str) -> Optional[Dict]:
        """VM guest bilgilerini getir (IP, hostname vs)"""
        response = self._api_call("GET", f"/vcenter/vm/{vm_id}/guest/identity")
        if not response:
            return None
        
        if isinstance(response, dict) and "value" in response:
            return response["value"]
        return response
    
    def sync_vms_to_inventory(self) -> List[Dict]:
        """Tüm VM'leri inventory formatına çevir"""
        vms = self.list_vms()
        inventory = []
        
        for vm in vms:
            vm_id = vm.get("vm")
            vm_name = vm.get("name", "Unknown")
            
            # Detaylı bilgi al
            details = self.get_vm_details(vm_id) if vm_id else None
            guest_info = self.get_vm_guest_info(vm_id) if vm_id else None
            
            # Inventory formatı
            vm_data = {
                "name": vm_name,
                "ip_address": guest_info.get("ip_address", "") if guest_info else "",
                "hostname": guest_info.get("host_name", vm_name) if guest_info else vm_name,
                "os_type": guest_info.get("family", "") if guest_info else "",
                "cpu_cores": details.get("cpu", {}).get("count", 0) if details else 0,
                "memory_gb": int(details.get("memory", {}).get("size_MiB", 0) / 1024) if details else 0,
                "power_state": vm.get("power_state", "UNKNOWN")
            }
            inventory.append(vm_data)
        
        logger.info(f"Synced {len(inventory)} VMs from vCenter {self.host}")
        return inventory

    def find_vm_by_name_or_ip(self, name: str = "", ip: str = "") -> Optional[str]:
        """VM'i isim veya IP ile bul, vm_id döner."""
        vms = self.list_vms()
        if isinstance(vms, dict):
            vms = vms.get("value", [])
        name_l = name.lower()
        for vm in vms:
            if name and vm.get("name", "").lower() == name_l:
                return vm.get("vm")
        # IP ile eşleşmeye çalış (guest info)
        if ip:
            for vm in vms:
                vm_id = vm.get("vm")
                if not vm_id:
                    continue
                try:
                    guest = self.get_vm_guest_info(vm_id)
                    if guest and guest.get("ip_address") == ip:
                        return vm_id
                except Exception:
                    pass
        return None

    def get_vm_quick_stats(self, vm_id: str) -> Optional[Dict]:
        """SOAP RetrieveProperties ile VM'in anlık CPU/RAM kullanımını döner.

        Dönen dict: cpu_mhz, cpu_percent, mem_used_mb, mem_total_mb,
                    mem_percent, uptime_seconds, power_state
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrievePropertiesEx>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSpec>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>summary.quickStats</vim25:pathSet>
          <vim25:pathSet>summary.config.numCpu</vim25:pathSet>
          <vim25:pathSet>summary.config.memorySizeMB</vim25:pathSet>
          <vim25:pathSet>summary.runtime.powerState</vim25:pathSet>
        </vim25:propSpec>
        <vim25:objectSet>
          <vim25:obj type="VirtualMachine">{vm_id}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
      <vim25:options/>
    </vim25:RetrievePropertiesEx>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            headers = {
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "urn:vim25/6.0",
            }
            # Reuse the session cookie from REST login
            resp = self.session.post(soap_url, data=soap_body, headers=headers,
                                     verify=self.verify_ssl, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"SOAP quick_stats HTTP {resp.status_code}")
                return None

            root = ET.fromstring(resp.text)
            ns = {"s": "http://schemas.xmlsoap.org/soap/envelope/",
                  "v": "urn:vim25"}

            def _val(tag: str) -> Optional[str]:
                for el in root.iter():
                    if el.tag.split("}")[-1] == tag:
                        return el.text
                return None

            cpu_mhz    = int(_val("overallCpuUsage") or 0)
            mem_used   = int(_val("guestMemoryUsage") or 0)
            uptime     = int(_val("uptimeSeconds") or 0)
            num_cpu    = int(_val("numCpu") or 1)
            mem_total  = int(_val("memorySizeMB") or 0)
            power_state = _val("powerState") or "unknown"

            # CPU %: overallCpuUsage(MHz) / (numCpu * host_freq) — approximate using 2000 MHz base
            # More accurate: query host's cpuMhz, here we use a common 2.0 GHz default
            cpu_freq_mhz = 2000
            cpu_percent = round((cpu_mhz / (num_cpu * cpu_freq_mhz)) * 100, 1) if num_cpu else None
            cpu_percent = min(cpu_percent, 100.0) if cpu_percent is not None else None
            mem_percent = round((mem_used / mem_total) * 100, 1) if mem_total else None

            return {
                "cpu_mhz": cpu_mhz,
                "cpu_percent": cpu_percent,
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
                "mem_percent": mem_percent,
                "uptime_seconds": uptime,
                "power_state": power_state,
                "num_cpu": num_cpu,
                "source": "vcenter",
            }
        except Exception as e:
            logger.error(f"get_vm_quick_stats error: {e}")
            return None
