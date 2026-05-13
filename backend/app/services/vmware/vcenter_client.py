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

    def _soap_login(self) -> Optional[str]:
        """SOAP SessionManager.Login ile cookie al."""
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        login_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:Login>
      <vim25:_this type="SessionManager">SessionManager</vim25:_this>
      <vim25:userName>{self.username}</vim25:userName>
      <vim25:password>{self.password}</vim25:password>
    </vim25:Login>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            soap_sess = requests.Session()
            soap_sess.verify = self.verify_ssl
            resp = soap_sess.post(soap_url, data=login_body,
                                  headers={"Content-Type": "text/xml; charset=utf-8"},
                                  timeout=10)
            if resp.status_code == 200:
                return soap_sess  # session has cookie
        except Exception as e:
            logger.warning(f"SOAP login error: {e}")
        return None

    def get_vm_quick_stats(self, vm_id: str) -> Optional[Dict]:
        """SOAP RetrievePropertiesEx ile VM CPU/RAM anlık kullanim verir."""
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("SOAP login failed, cannot get VM quick stats")
            return None

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>summary.quickStats</vim25:pathSet>
          <vim25:pathSet>summary.config.numCpu</vim25:pathSet>
          <vim25:pathSet>summary.config.memorySizeMB</vim25:pathSet>
          <vim25:pathSet>summary.runtime.powerState</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="VirtualMachine">{vm_id}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = soap_session.post(soap_url, data=soap_body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"SOAP quick_stats HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            root = ET.fromstring(resp.text)

            # Parse propSet elements: <propSet><name>X</name><val>Y</val></propSet>
            props: dict = {}
            for ps in root.iter():
                if ps.tag.split("}")[-1] == "propSet":
                    name_el = next((c for c in ps if c.tag.split("}")[-1] == "name"), None)
                    val_el  = next((c for c in ps if c.tag.split("}")[-1] == "val"),  None)
                    if name_el is not None and val_el is not None:
                        pname = name_el.text or ""
                        # collect sub-elements of val into props
                        for child in val_el:
                            props[child.tag.split("}")[-1]] = child.text
                        # also store scalar vals
                        props[pname] = val_el.text

            def _get(key: str) -> Optional[str]:
                return props.get(key)

            cpu_mhz     = int(_get("overallCpuUsage") or 0)
            mem_used    = int(_get("guestMemoryUsage") or 0)
            uptime      = int(_get("uptimeSeconds") or 0)
            num_cpu     = int(_get("summary.config.numCpu") or props.get("numCpu") or 1)
            mem_total   = int(_get("summary.config.memorySizeMB") or props.get("memorySizeMB") or 0)
            power_state = (_get("summary.runtime.powerState") or props.get("powerState") or "unknown")

            cpu_freq_mhz = 2000  # typical vCPU frequency assumption
            cpu_percent  = round((cpu_mhz / (num_cpu * cpu_freq_mhz)) * 100, 1) if num_cpu and cpu_mhz else None
            if cpu_percent is not None:
                cpu_percent = min(cpu_percent, 100.0)
            mem_percent = round((mem_used / mem_total) * 100, 1) if mem_total and mem_used else None

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


    # ── ESX Host İstatistikleri ──────────────────────────────────────────────

    def _get_root_folder(self, soap_session, soap_url: str) -> str:
        """RetrieveServiceContent ile gerçek rootFolder MOR'unu döner."""
        import xml.etree.ElementTree as ET
        body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveServiceContent>
      <vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>
    </vim25:RetrieveServiceContent>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            r = soap_session.post(soap_url, data=body,
                                  headers={"Content-Type": "text/xml; charset=utf-8"},
                                  verify=self.verify_ssl, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.text)
                for el in root.iter():
                    if el.tag.split("}")[-1] == "rootFolder":
                        return el.text or "group-d1"
        except Exception:
            pass
        return "group-d1"   # fallback

    # SOAP traversal spec XML — Folder → Datacenter → HostFolder → ComputeResource → HostSystem
    _HOST_TRAVERSAL = """
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>visitFolders</vim25:name>
            <vim25:type>Folder</vim25:type>
            <vim25:path>childEntity</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>dcToHF</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>crToH</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToHF</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>hostFolder</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>crToH</vim25:name>
            <vim25:type>ComputeResource</vim25:type>
            <vim25:path>host</vim25:path>
            <vim25:skip>false</vim25:skip>
          </vim25:selectSet>"""

    def get_all_host_stats(self) -> List[Dict]:
        """
        vCenter'daki tüm ESX host'ların CPU, RAM, Datastore ve VM sayısını döner.
        SOAP RetrieveProperties kullanır (eski vCenter API ile de uyumlu).
        """
        import xml.etree.ElementTree as ET

        soap_url     = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("get_all_host_stats: SOAP login failed")
            return []

        root_folder = self._get_root_folder(soap_session, soap_url)

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:vim25="urn:vim25"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>HostSystem</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>summary.quickStats</vim25:pathSet>
          <vim25:pathSet>summary.hardware</vim25:pathSet>
          <vim25:pathSet>summary.runtime</vim25:pathSet>
          <vim25:pathSet>vm</vim25:pathSet>
          <vim25:pathSet>datastore</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Folder">{root_folder}</vim25:obj>
          <vim25:skip>false</vim25:skip>
          {self._HOST_TRAVERSAL}
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""

        try:
            resp = soap_session.post(soap_url, data=soap_body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"get_all_host_stats HTTP {resp.status_code}: {resp.text[:300]}")
                return []

            root_xml = ET.fromstring(resp.text)
            results  = []

            def _tag(el): return el.tag.split("}")[-1]

            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue

                host_ref = None
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                if obj_el is not None:
                    host_ref = obj_el.text

                # propSet'leri düz dict'e çevir
                flat: dict = {}
                ds_refs:  list = []
                vm_refs:  list = []

                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"),  None)
                    if n_el is None or v_el is None:
                        continue
                    pname = n_el.text or ""

                    if pname == "vm":
                        vm_refs = [c.text for c in v_el if c.text]
                        continue
                    if pname == "datastore":
                        ds_refs = [c.text for c in v_el if c.text]
                        continue

                    # Scalar veya struct — tüm alt elemanları flat'e at
                    for child in v_el:
                        ct = _tag(child)
                        # otherIdentifyingInfo gibi tekrar eden listeleri atla
                        if ct not in ("otherIdentifyingInfo",):
                            flat[ct] = child.text
                    if v_el.text and v_el.text.strip():
                        flat[pname] = v_el.text.strip()

                def _f(k, default=0.0):
                    v = flat.get(k)
                    try: return float(v) if v is not None else default
                    except: return default

                def _i(k, default=0):
                    v = flat.get(k)
                    try: return int(v) if v is not None else default
                    except: return default

                host_name = flat.get("name", host_ref or "unknown")

                # CPU: cpuMhz = per-core MHz, numCpuCores = core sayısı
                cpu_usage_mhz = _f("overallCpuUsage")
                cpu_per_core  = _f("cpuMhz")
                num_cores     = _i("numCpuCores") or 1
                cpu_total_mhz = cpu_per_core * num_cores if cpu_per_core else 0.0
                cpu_usage_pct = round((cpu_usage_mhz / cpu_total_mhz) * 100, 1) \
                                if cpu_total_mhz > 0 else None

                # RAM: memorySize bytes, overallMemoryUsage MB
                mem_used_mb  = _f("overallMemoryUsage")
                mem_total_mb = round(_f("memorySize") / (1024 * 1024), 1)
                mem_usage_pct = round((mem_used_mb / mem_total_mb) * 100, 1) \
                                if mem_total_mb > 0 else None

                maintenance = flat.get("inMaintenanceMode", "false")
                in_maint    = 1 if str(maintenance).lower() == "true" else 0

                results.append({
                    "host_ref":         host_ref or "unknown",
                    "host_name":        host_name,
                    "cpu_usage_mhz":    cpu_usage_mhz,
                    "cpu_total_mhz":    cpu_total_mhz,
                    "cpu_usage_pct":    cpu_usage_pct,
                    "cpu_cores":        _i("numCpuCores"),
                    "cpu_threads":      _i("numCpuThreads"),
                    "mem_used_mb":      mem_used_mb,
                    "mem_total_mb":     mem_total_mb,
                    "mem_usage_pct":    mem_usage_pct,
                    "ds_used_gb":       None,
                    "ds_total_gb":      None,
                    "ds_usage_pct":     None,
                    "net_rx_kbps":      None,
                    "net_tx_kbps":      None,
                    "vms_running":      None,
                    "vms_total":        len(vm_refs),
                    "_ds_refs":         ds_refs,   # geçici — enrich'te kullanılır
                    "connection_state": flat.get("connectionState", "unknown"),
                    "power_state":      flat.get("powerState", "unknown"),
                    "maintenance_mode": in_maint,
                })

            if results:
                self._enrich_datastores(soap_session, soap_url, root_folder, results)
                self._enrich_vms_running(soap_session, soap_url, root_folder, results)
                for r in results:
                    r.pop("_ds_refs", None)

            logger.info(f"get_all_host_stats: {len(results)} ESX host ({self.host})")
            return results

        except Exception as e:
            logger.error(f"get_all_host_stats error: {e}", exc_info=True)
            return []

    @staticmethod
    def _parse_ds_xml(xml_text: str) -> dict:
        """
        SOAP RetrieveProperties yanıtından datastore bilgilerini çıkarır.
        Erişilemeyen (accessible=false) veya freeSpace==capacity olan stale datastore'ları filtreler.
        Dönen: ds_ref → {name, capacity_gb, used_gb}
        """
        import xml.etree.ElementTree as ET

        ds_info: dict = {}
        try:
            root_xml = ET.fromstring(xml_text)
        except Exception:
            return ds_info

        ns = "urn:vim25"

        for rv in root_xml.iter(f"{{{ns}}}returnval"):
            obj_el = rv.find(f"{{{ns}}}obj")
            ds_ref = obj_el.text if obj_el is not None else None
            if not ds_ref:
                continue

            flat: dict = {}
            for ps in rv.findall(f"{{{ns}}}propSet"):
                n_el = ps.find(f"{{{ns}}}name")
                v_el = ps.find(f"{{{ns}}}val")
                if n_el is not None and v_el is not None and n_el.text and v_el.text:
                    flat[n_el.text] = v_el.text

            try:
                cap  = float(flat.get("summary.capacity",  0) or 0)
                free = float(flat.get("summary.freeSpace", 0) or 0)
            except (ValueError, TypeError):
                continue

            name       = flat.get("summary.name", ds_ref)
            accessible = flat.get("summary.accessible", "true")
            used       = cap - free

            # Filtreler:
            # • accessible=false → NFS / erişilemeyen datastore
            # • free >= cap      → stale mount (vCenter istatistiklerini alamıyor)
            # • cap == 0         → geçersiz
            if cap > 0 and used >= 0 and str(accessible).lower() != "false" and free < cap:
                ds_info[ds_ref] = {
                    "name":        name,
                    "capacity_gb": round(cap  / (1024 ** 3), 1),
                    "used_gb":     round(used / (1024 ** 3), 1),
                }
                logger.debug(f"DS {name}: {ds_info[ds_ref]['capacity_gb']} GB total")
            else:
                logger.debug(
                    f"DS {name} ({ds_ref}) skip: cap={cap/1024**3:.1f} GB "
                    f"accessible={accessible} free_ge_cap={free >= cap}"
                )

        return ds_info

    def _enrich_datastores(self, soap_session, soap_url: str,
                           root_folder: str, results: List[Dict]):
        """
        Her host'un _ds_refs listesindeki datastore'ları doğrudan ID ile sorgular.
        Folder traversal kullanmaz — eski vCenter API'lerinde daha güvenilir.
        """
        try:
            all_ds_refs: List[str] = list({
                ref
                for r in results
                for ref in (r.get("_ds_refs") or [])
            })
            if not all_ds_refs:
                return

            obj_set_parts = []
            for ref in all_ds_refs:
                obj_set_parts.append(
                    f"        <vim25:objectSet>"
                    f"<vim25:obj type=\"Datastore\">{ref}</vim25:obj>"
                    f"<vim25:skip>false</vim25:skip>"
                    f"</vim25:objectSet>"
                )
            obj_set_xml = "\n".join(obj_set_parts)

            soap_body = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
                ' xmlns:vim25="urn:vim25">'
                "<soapenv:Body>"
                "<vim25:RetrieveProperties>"
                '<vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>'
                "<vim25:specSet>"
                "<vim25:propSet>"
                "<vim25:type>Datastore</vim25:type>"
                "<vim25:all>false</vim25:all>"
                "<vim25:pathSet>summary.capacity</vim25:pathSet>"
                "<vim25:pathSet>summary.freeSpace</vim25:pathSet>"
                "<vim25:pathSet>summary.name</vim25:pathSet>"
                "<vim25:pathSet>summary.accessible</vim25:pathSet>"
                "</vim25:propSet>"
                + obj_set_xml +
                "</vim25:specSet>"
                "</vim25:RetrieveProperties>"
                "</soapenv:Body>"
                "</soapenv:Envelope>"
            )

            resp = soap_session.post(
                soap_url, data=soap_body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=25,
            )
            if resp.status_code != 200:
                logger.warning(f"_enrich_datastores HTTP {resp.status_code}")
                return

            ds_info = self._parse_ds_xml(resp.text)

            if not ds_info:
                logger.warning("_enrich_datastores: hiç geçerli datastore bulunamadı")
                return

            for r in results:
                host_ds_refs = r.get("_ds_refs") or []
                total_cap_gb  = 0.0
                total_used_gb = 0.0
                for ref in host_ds_refs:
                    info = ds_info.get(ref)
                    if info:
                        total_cap_gb  += info["capacity_gb"]
                        total_used_gb += info["used_gb"]
                if total_cap_gb > 0:
                    r["ds_used_gb"]   = round(total_used_gb, 1)
                    r["ds_total_gb"]  = round(total_cap_gb,  1)
                    r["ds_usage_pct"] = round((total_used_gb / total_cap_gb) * 100, 1)
                    logger.info(
                        f"Host {r.get('host_name')}: DS {total_used_gb:.1f}/{total_cap_gb:.1f} GB"
                    )

        except Exception as e:
            logger.warning(f"_enrich_datastores error: {e}")

    def _enrich_vms_running(self, soap_session, soap_url: str,
                            root_folder: str, results: List[Dict]):
        """Her host'ta poweredOn VM sayısını ekler."""
        import xml.etree.ElementTree as ET

        soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:vim25="urn:vim25"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>summary.runtime</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Folder">{root_folder}</vim25:obj>
          <vim25:skip>false</vim25:skip>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>visitFolders</vim25:name>
            <vim25:type>Folder</vim25:type>
            <vim25:path>childEntity</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>dcToVF</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToVF</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>vmFolder</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
          </vim25:selectSet>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = soap_session.post(soap_url, data=soap_body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=20)
            if resp.status_code != 200:
                return

            root_xml = ET.fromstring(resp.text)
            def _tag(el): return el.tag.split("}")[-1]

            # host_ref → running vm count
            host_running: dict = {}

            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue
                host_ref_vm = None
                power_state = None
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if v_el is None:
                        continue
                    for child in v_el:
                        ct = _tag(child)
                        if ct == "host":
                            host_ref_vm = child.text
                        elif ct == "powerState":
                            power_state = child.text

                if host_ref_vm and power_state == "poweredOn":
                    host_running[host_ref_vm] = host_running.get(host_ref_vm, 0) + 1

            for r in results:
                r["vms_running"] = host_running.get(r["host_ref"], 0)

        except Exception as e:
            logger.debug(f"_enrich_vms_running error: {e}")
