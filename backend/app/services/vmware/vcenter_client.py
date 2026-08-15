"""
VMware vCenter REST API Client
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Tuple, Any

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)

# VM sync / enrichment paralel worker sayısı (env ile override edilebilir)
DEFAULT_SYNC_WORKERS = 10


def _sync_workers(requested: Optional[int] = None) -> int:
    if requested is not None and requested > 0:
        return max(1, min(int(requested), 64))
    try:
        from app.services.runtime_settings import get_int
        return max(1, min(get_int("vcenter_sync_workers"), 64))
    except Exception:
        pass
    raw = (os.environ.get("VCENTER_SYNC_WORKERS") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return max(1, min(int(raw), 64))
    return DEFAULT_SYNC_WORKERS


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
            response = self.session.post(url, auth=(self.username, self.password), timeout=10)
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
                self.session.delete(url, timeout=10)
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
            # NOT: timeout olmadan requests.Session çağrısı vCenter yanıt vermezse
            # (ağ sorunu / aşırı yüklü host) thread'i SONSUZA KADAR bloklar — thread
            # havuzu (bkz. main.py _SSH_EXECUTOR) zamanla tükenir ve dolaylı "hang"e
            # yol açar. list_vms() dahil çoğu vCenter çağrısı bu fonksiyondan geçtiği
            # için timeout eklendi.
            if method == "GET":
                response = self.session.get(url, timeout=30)
            elif method == "POST":
                response = self.session.post(url, json=data, timeout=30)
            elif method == "PUT":
                response = self.session.put(url, json=data, timeout=30)
            elif method == "DELETE":
                response = self.session.delete(url, timeout=30)
            else:
                return None
            
            if response.status_code in (200, 201):
                return response.json() if response.text else {}

            # VMware Tools kurulu/çalışmıyor olan VM'lerde guest/* endpoint'leri
            # (identity, local filesystem vb.) 503 tools_not_running döner — bu
            # beklenen bir durum; ERROR olarak loglamak her sync turunda onlarca
            # satır gürültü üretir. Aynı şekilde Tools çalışsa bile guest info
            # vermeyen VM'ler information_not_available / SERVICE_UNAVAILABLE alır.
            body = response.text or ""
            if response.status_code == 503 and (
                "tools_not_running" in body
                or "VMware Tools are not running" in body
                or "information_not_available" in body
                or "provided no information" in body
            ):
                logger.debug(
                    "Guest API unavailable (VMware Tools / guest info) for %s: %s",
                    endpoint, body[:200],
                )
                return None

            logger.error(f"API call failed: {response.status_code} - {body}")
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
    
    @staticmethod
    def _guest_text(val) -> str:
        """vCenter localization dict / string / None → düz metin.

        guest.identity.full_name çoğu sürümde string değil
        ``{"id": "...", "default_message": "Red Hat Enterprise Linux 9 (64-bit)"}``.
        """
        if val is None:
            return ""
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, dict):
            for k in ("default_message", "full_name", "name", "label", "id", "value", "status"):
                inner = val.get(k)
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
            return ""
        return str(val).strip()

    @staticmethod
    def _guest_os_family_fallback(guest_os_id) -> str:
        """VMware `guest_OS` alanından ("WINDOWS_2019_64", "RHEL_8_64" vb.) family tahmini üretir.

        `guest/identity` endpoint'i (family/full_name) VMware Tools'un VM içinde
        çalışıyor olmasını gerektirir — Tools kurulu değilse boş döner ve VM
        yanlışlıkla Linux sayılabilir (windows/linux platform modüllerinin
        sunucuyu doğru sınıflandırması için kritik). `guest_OS` ise VM
        oluşturulurken belirlenen konfigürasyon alanıdır, Tools'a bağlı değildir.
        """
        g = VCenterClient._guest_text(guest_os_id).upper()
        if not g:
            return ""
        if "WIN" in g:
            return "windowsGuest"
        return "linuxGuest"

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

    def clone_session(self) -> "VCenterClient":
        """Aynı oturum ID'si ile thread-safe kopya (ayrı requests.Session)."""
        sibling = VCenterClient(
            host=self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            verify_ssl=self.verify_ssl,
        )
        sibling.session_id = self.session_id
        if self.session_id:
            sibling.session.headers.update({"vmware-api-session-id": self.session_id})
        return sibling

    def _inventory_row_from_vm(self, vm: Dict) -> Dict:
        """Tek VM için details+guest çekip inventory satırına çevir (thread içinde çağrılır)."""
        vm_id = vm.get("vm")
        vm_name = vm.get("name", "Unknown")
        details = self.get_vm_details(vm_id) if vm_id else None
        guest_info = self.get_vm_guest_info(vm_id) if vm_id else None
        os_family = (guest_info.get("family", "") if guest_info else "") or \
            self._guest_os_family_fallback((details or {}).get("guest_OS", ""))
        return {
            "name": vm_name,
            "vm_id": vm_id or "",
            "ip_address": guest_info.get("ip_address", "") if guest_info else "",
            "hostname": guest_info.get("host_name", vm_name) if guest_info else vm_name,
            "os_type": os_family,
            "cpu_cores": details.get("cpu", {}).get("count", 0) if details else 0,
            "memory_gb": int(details.get("memory", {}).get("size_MiB", 0) / 1024) if details else 0,
            "power_state": vm.get("power_state", "UNKNOWN"),
        }

    def sync_vms_to_inventory(self, max_workers: Optional[int] = None) -> List[Dict]:
        """Tüm VM'leri inventory formatına çevir (varsayılan 10 paralel worker)."""
        vms = self.list_vms()
        if not vms:
            return []

        workers = _sync_workers(max_workers)
        # Küçük envanterde havuz maliyeti gereksiz
        if len(vms) <= 1 or workers == 1:
            inventory = [self._inventory_row_from_vm(vm) for vm in vms]
            logger.info(f"Synced {len(inventory)} VMs from vCenter {self.host} (serial)")
            return inventory

        inventory: List[Optional[Dict]] = [None] * len(vms)

        def _worker(idx: int, vm: Dict) -> Tuple[int, Dict]:
            try:
                row = self.clone_session()._inventory_row_from_vm(vm)
                return idx, row
            except Exception as exc:
                logger.warning(
                    "VM sync worker hatası (%s): %s",
                    vm.get("name") or vm.get("vm"),
                    exc,
                )
                return idx, {
                    "name": vm.get("name", "Unknown"),
                    "vm_id": vm.get("vm") or "",
                    "ip_address": "",
                    "hostname": vm.get("name", "Unknown"),
                    "os_type": "",
                    "cpu_cores": 0,
                    "memory_gb": 0,
                    "power_state": vm.get("power_state", "UNKNOWN"),
                }

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, i, vm) for i, vm in enumerate(vms)]
            done = 0
            for fut in as_completed(futures):
                idx, row = fut.result()
                inventory[idx] = row
                done += 1
                if done % 50 == 0 or done == len(vms):
                    logger.info(
                        "vCenter VM sync ilerlemesi %s/%s (workers=%s) @ %s",
                        done, len(vms), workers, self.host,
                    )

        out = [r for r in inventory if r is not None]
        logger.info(
            f"Synced {len(out)} VMs from vCenter {self.host} (parallel workers={workers})"
        )
        return out

    def fetch_full_details_parallel(
        self,
        items: List[Dict],
        max_workers: Optional[int] = None,
        on_progress=None,
    ) -> Dict[str, Dict]:
        """
        Birden fazla VM için get_vm_full_details'i paralel çalıştırır.
        items: [{"vm_id": "...", "name": "..."}, ...]
        Dönüş: {vm_id: details_dict}
        on_progress(done, total) opsiyonel ilerleme callback'i.
        """
        workers = _sync_workers(max_workers)
        targets = [
            ((it.get("vm_id") or "").strip(), it.get("name") or "")
            for it in items
            if (it.get("vm_id") or "").strip()
        ]
        if not targets:
            return {}
        if len(targets) == 1 or workers == 1:
            vid, name = targets[0]
            det = self.get_vm_full_details(vid, name=name)
            return {vid: det} if det else {}

        result: Dict[str, Dict] = {}

        def _one(vid: str, name: str) -> Tuple[str, Optional[Dict]]:
            try:
                return vid, self.clone_session().get_vm_full_details(vid, name=name)
            except Exception as exc:
                logger.debug("parallel full_details hatası (%s): %s", vid, exc)
                return vid, None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_one, vid, name) for vid, name in targets]
            done = 0
            for fut in as_completed(futs):
                vid, det = fut.result()
                if det:
                    result[vid] = det
                done += 1
                if on_progress:
                    try:
                        on_progress(done, len(targets))
                    except Exception:
                        pass
                if done % 50 == 0 or done == len(targets):
                    logger.info(
                        "vCenter full_details ilerlemesi %s/%s (workers=%s)",
                        done, len(targets), workers,
                    )
        return result

    def _api_call_raw(self, method: str, endpoint: str, data: Optional[Dict] = None):
        """Status code ile birlikte yanıt döner."""
        if not self.session_id:
            if not self.login():
                return None, 0, ""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = self.session.get(url, timeout=60)
            elif method == "POST":
                response = self.session.post(url, json=data, timeout=120)
            elif method == "DELETE":
                response = self.session.delete(url, timeout=120)
            else:
                return None, 0, ""
            body = response.json() if response.text else {}
            return body, response.status_code, response.text
        except Exception as e:
            logger.error(f"API call error: {e}")
            return None, 0, str(e)

    # ── Snapshot — REST + SOAP fallback ─────────────────────────────────────

    def _soap_wait_task(self, soap_session, soap_url: str, task_id: str,
                        timeout: int = 300) -> Tuple[bool, str]:
        """
        Verilen Task MOR tamamlanana kadar polling yapar. (success, message/result)

        SOAP RetrieveProperties yanıtı:
          <propSet>
            <name>info.state</name>
            <val xsi:type="TaskInfoState">success|error|running|queued</val>
          </propSet>
        """
        import xml.etree.ElementTree as ET, time
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>Task</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>info.state</vim25:pathSet>
          <vim25:pathSet>info.error</vim25:pathSet>
          <vim25:pathSet>info.result</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Task">{task_id}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
            try:
                resp = soap_session.post(soap_url, data=body,
                                         headers={"Content-Type": "text/xml; charset=utf-8"},
                                         verify=self.verify_ssl, timeout=15)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.text)

                    def _tag(el): return el.tag.split("}")[-1]

                    # propSet'leri key→value sözlüğüne çevir
                    props: dict = {}
                    for ps in root.iter():
                        if _tag(ps) != "propSet":
                            continue
                        name_el = next((c for c in ps if _tag(c) == "name"), None)
                        val_el  = next((c for c in ps if _tag(c) == "val"),  None)
                        if name_el is not None and val_el is not None:
                            key = (name_el.text or "").strip()
                            # val direkt text ya da alt elementlerin birleşimi
                            val_text = (val_el.text or "").strip()
                            if not val_text:
                                # localizedMessage, message vb. alt elemandan al
                                for child in val_el:
                                    if _tag(child) in ("localizedMessage", "message", "fault"):
                                        val_text = (child.text or "").strip()
                                        break
                            props[key] = val_text

                    state      = props.get("info.state", "").lower()
                    err_msg    = props.get("info.error", "task hata ile bitti")
                    result_val = props.get("info.result", "")

                    logger.debug(f"_soap_wait_task {task_id}: state={state!r}")

                    if state == "success":
                        return True, result_val or "success"
                    if state == "error":
                        return False, err_msg or "task hata ile bitti"
                    # running / queued → bekle
                    elif state not in ("running", "queued", ""):
                        # Bilinmeyen durum — yine bekle
                        logger.warning(f"_soap_wait_task unknown state: {state!r}")
            except Exception as e:
                logger.debug(f"_soap_wait_task poll error: {e}")
            time.sleep(4)
        return False, "task zaman aşımı"

    def _list_snapshots_soap(self, vm_id: str) -> List[Dict]:
        """SOAP RetrieveProperties ile snapshot listesini okur."""
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return []
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>snapshot</vim25:pathSet>
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
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=20)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)

            def _tag(el): return el.tag.split("}")[-1]

            result: List[Dict] = []
            for snap_el in root.iter():
                if _tag(snap_el) not in ("VirtualMachineSnapshotTree", "rootSnapshotList"):
                    continue
                snap_id = ""
                snap_name = ""
                snap_desc = ""
                snap_time = ""
                for child in snap_el:
                    ct = _tag(child)
                    if ct == "snapshot" and child.text:
                        snap_id = child.text
                    elif ct == "name":
                        snap_name = child.text or ""
                    elif ct == "description":
                        snap_desc = child.text or ""
                    elif ct == "createTime":
                        snap_time = child.text or ""
                if snap_id:
                    result.append({
                        "id": snap_id,
                        "name": snap_name or snap_id,
                        "description": snap_desc,
                        "create_time": snap_time,
                        "state": "SUCCEEDED",
                    })
            return result
        except Exception as e:
            logger.error(f"_list_snapshots_soap error: {e}")
            return []

    def _create_snapshot_soap(self, vm_id: str, name: str,
                               description: str = "") -> Tuple[bool, str, Optional[str]]:
        """SOAP CreateSnapshot_Task ile snapshot oluşturur."""
        import xml.etree.ElementTree as ET
        import html as _html
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return False, "SOAP oturumu açılamadı", None

        safe_name = _html.escape(name)
        safe_desc = _html.escape(description or name)
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:CreateSnapshot_Task>
      <vim25:_this type="VirtualMachine">{vm_id}</vim25:_this>
      <vim25:name>{safe_name}</vim25:name>
      <vim25:description>{safe_desc}</vim25:description>
      <vim25:memory>false</vim25:memory>
      <vim25:quiesce>false</vim25:quiesce>
    </vim25:CreateSnapshot_Task>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=30)
            if resp.status_code != 200:
                return False, f"SOAP HTTP {resp.status_code}: {resp.text[:200]}", None

            root = ET.fromstring(resp.text)
            task_id = None
            for el in root.iter():
                if el.tag.split("}")[-1] == "returnval" and el.text:
                    task_id = el.text
                    break

            if not task_id:
                return False, "Task ID alınamadı", None

            ok, msg = self._soap_wait_task(soap_session, soap_url, task_id, timeout=300)
            if ok:
                # Snapshot ID = task result ya da name bazlı arama
                snap_id = msg if msg and msg != "success" else None
                if not snap_id:
                    snaps = self._list_snapshots_soap(vm_id)
                    match = next((s for s in snaps if s["name"] == name), None)
                    snap_id = (match or (snaps[-1] if snaps else {})).get("id")
                return True, "Snapshot oluşturuldu (SOAP)", snap_id
            return False, msg, None
        except Exception as e:
            logger.error(f"_create_snapshot_soap error: {e}", exc_info=True)
            return False, str(e), None

    def _delete_snapshot_soap(self, vm_id: str, snapshot_id: str) -> Tuple[bool, str]:
        """
        SOAP RemoveSnapshot_Task ile snapshot siler.

        snapshot_id: Snapshot MOR — örn. "snapshot-12037"
        consolidate parametresi eski vCenter'larda 500 verebileceğinden dahil edilmez.
        """
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return False, "SOAP oturumu açılamadı"

        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RemoveSnapshot_Task>
      <vim25:_this type="VirtualMachineSnapshot">{snapshot_id}</vim25:_this>
      <vim25:removeChildren>false</vim25:removeChildren>
    </vim25:RemoveSnapshot_Task>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=30)
            if resp.status_code == 500:
                # 500 genellikle snapshot MOR hatalı veya zaten silinmiş
                logger.warning(f"_delete_snapshot_soap 500: {resp.text[:300]}")
                # SOAP Fault içinde "not found" varsa başarı say
                if "not found" in resp.text.lower() or "NotFound" in resp.text:
                    return True, "Snapshot zaten silinmiş"
                return False, f"SOAP HTTP 500: {resp.text[:200]}"
            if resp.status_code != 200:
                return False, f"SOAP HTTP {resp.status_code}"

            root = ET.fromstring(resp.text)
            task_id = None
            for el in root.iter():
                if el.tag.split("}")[-1] == "returnval" and el.text:
                    task_id = el.text
                    break

            if not task_id:
                return False, "Task ID alınamadı"

            ok, msg = self._soap_wait_task(soap_session, soap_url, task_id, timeout=120)
            return ok, "Snapshot silindi (SOAP)" if ok else msg
        except Exception as e:
            logger.error(f"_delete_snapshot_soap error: {e}", exc_info=True)
            return False, str(e)

    def list_snapshots(self, vm_id: str) -> List[Dict]:
        # REST dene
        response = self._safe_api(f"/vcenter/vm/{vm_id}/snapshot")
        if response is not None:
            items = response if isinstance(response, list) else response.get("value", [])
            result = []
            for item in items:
                snap_id = item.get("snapshot") or item.get("id")
                if not snap_id:
                    continue
                result.append({
                    "id": snap_id,
                    "name": item.get("name") or snap_id,
                    "description": item.get("description") or "",
                    "create_time": item.get("create_time"),
                    "state": item.get("state"),
                })
            if result:
                return result
        # SOAP fallback
        return self._list_snapshots_soap(vm_id)

    def create_snapshot(self, vm_id: str, name: str, description: str = "") -> Tuple[bool, str, Optional[str]]:
        # REST dene
        payload = {"name": name, "description": description or name, "memory": False, "quiesce": False}
        body, status, text = self._api_call_raw("POST", f"/vcenter/vm/{vm_id}/snapshot", payload)
        if status in (200, 201, 202) and body:
            snap_id = body.get("value") if isinstance(body, dict) else None
            return True, "Snapshot oluşturuldu", snap_id
        if status not in (404, 0):
            logger.warning(f"create_snapshot REST HTTP {status}: {(text or '')[:200]}")
        # SOAP fallback (404 veya diğer hata)
        logger.info(f"create_snapshot SOAP fallback: vm={vm_id}")
        return self._create_snapshot_soap(vm_id, name, description)

    def delete_snapshot(self, vm_id: str, snapshot_id: str) -> Tuple[bool, str]:
        # REST dene
        _, status, text = self._api_call_raw("DELETE", f"/vcenter/vm/{vm_id}/snapshot/{snapshot_id}")
        if status in (200, 204):
            return True, "Snapshot silindi"
        if status not in (404, 0):
            logger.warning(f"delete_snapshot REST HTTP {status}: {(text or '')[:200]}")
        # SOAP fallback
        logger.info(f"delete_snapshot SOAP fallback: vm={vm_id} snap={snapshot_id}")
        return self._delete_snapshot_soap(vm_id, snapshot_id)

    def _safe_api(self, endpoint: str) -> Optional[Dict]:
        """404/diğer hata durumlarında None döner, exception fırlatmaz."""
        try:
            return self._api_call("GET", endpoint)
        except Exception:
            return None

    def _vm_disks_soap(self, vm_id: str) -> int:
        """
        SOAP RetrieveProperties ile VM disk kapasitesini okur.
        REST hardware/disk endpoint'i eski vCenter'larda 404 verebilir.
        Döner: toplam disk GB (int).
        """
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return 0
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>config.hardware.device</vim25:pathSet>
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
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=15)
            if resp.status_code != 200:
                return 0
            root = ET.fromstring(resp.text)
            total_bytes = 0
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                # VirtualDisk objects have <capacityInBytes> or <capacityInKB>
                if tag == "capacityInBytes" and el.text:
                    try:
                        total_bytes += int(el.text)
                    except ValueError:
                        pass
                elif tag == "capacityInKB" and el.text and total_bytes == 0:
                    try:
                        total_bytes += int(el.text) * 1024
                    except ValueError:
                        pass
            return int(total_bytes / (1024 ** 3)) if total_bytes > 0 else 0
        except Exception as e:
            logger.debug(f"_vm_disks_soap error: {e}")
            return 0

    def _vm_datastore_soap(self, vm_id: str) -> str:
        """
        SOAP RetrieveProperties ile VM'in bağlı olduğu datastore adını okur.
        config.datastoreUrl veya datastore referansı üzerinden çalışır.
        Döner: datastore adı str (bulunamazsa "").
        """
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return ""
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>config.datastoreUrl</vim25:pathSet>
          <vim25:pathSet>config.files.vmPathName</vim25:pathSet>
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
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=15)
            if resp.status_code != 200:
                return ""
            root = ET.fromstring(resp.text)
            # config.files.vmPathName → "[DatastoreName] vm/vm.vmx"
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag == "vmPathName" and el.text and el.text.startswith("["):
                    end = el.text.find("]")
                    if end > 1:
                        return el.text[1:end].strip()
            # config.datastoreUrl → DatastoreUrl array, name attribute
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag == "DatastoreUrl":
                    name_el = el.find(".//{urn:vim25}name") or el.find(".//{*}name")
                    if name_el is not None and name_el.text:
                        return name_el.text.strip()
            return ""
        except Exception as e:
            logger.debug(f"_vm_datastore_soap error: {e}")
            return ""

    def _vm_placement_soap(self, vm_id: str) -> Dict[str, str]:
        """
        SOAP ile VM'in runtime.host + parent (cluster/host) bilgisini çözer.
        Döner: {host_ref, host_name, cluster_name}
        """
        import xml.etree.ElementTree as ET
        out = {"host_ref": "", "host_name": "", "cluster_name": ""}
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return out
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>runtime.host</vim25:pathSet>
          <vim25:pathSet>name</vim25:pathSet>
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
            resp = soap_session.post(
                soap_url, data=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=15,
            )
            if resp.status_code != 200:
                return out
            root = ET.fromstring(resp.text)

            def _tag(el):
                return el.tag.split("}")[-1]

            host_ref = ""
            for rv in root.iter():
                if _tag(rv) != "returnval":
                    continue
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    if (n_el.text or "") == "runtime.host":
                        host_ref = (v_el.text or "").strip()
                        # type attr may be on val
                        if not host_ref and len(list(v_el)) == 0:
                            host_ref = (v_el.attrib.get("type") and "") or ""
                        # ManagedObjectReference often has text = host-12
                        if not host_ref:
                            host_ref = "".join(v_el.itertext()).strip()
            if not host_ref:
                return out
            out["host_ref"] = host_ref

            # Host name + parent (cluster)
            hbody = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>HostSystem</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>parent</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="HostSystem">{host_ref}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
            hresp = soap_session.post(
                soap_url, data=hbody,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=15,
            )
            if hresp.status_code != 200:
                return out
            hroot = ET.fromstring(hresp.text)
            parent_ref = ""
            parent_type = ""
            for rv in hroot.iter():
                if _tag(rv) != "returnval":
                    continue
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = n_el.text or ""
                    if pname == "name":
                        out["host_name"] = (v_el.text or "").strip()
                    elif pname == "parent":
                        parent_ref = "".join(v_el.itertext()).strip()
                        parent_type = v_el.attrib.get("type") or ""
                        for child in v_el:
                            if _tag(child) in ("ManagedObjectReference",) or child.attrib.get("type"):
                                parent_type = child.attrib.get("type") or parent_type
                                parent_ref = (child.text or parent_ref or "").strip()

            if parent_ref and "Cluster" in (parent_type or "Cluster"):
                cbody = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>ClusterComputeResource</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="ClusterComputeResource">{parent_ref}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
                cresp = soap_session.post(
                    soap_url, data=cbody,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    verify=self.verify_ssl, timeout=15,
                )
                if cresp.status_code == 200:
                    croot = ET.fromstring(cresp.text)
                    for el in croot.iter():
                        if _tag(el) == "val" and el.text and el.text.strip():
                            # first name val
                            pass
                    for rv in croot.iter():
                        if _tag(rv) != "returnval":
                            continue
                        for ps in rv:
                            if _tag(ps) != "propSet":
                                continue
                            n_el = next((c for c in ps if _tag(c) == "name"), None)
                            v_el = next((c for c in ps if _tag(c) == "val"), None)
                            if n_el is not None and (n_el.text or "") == "name" and v_el is not None:
                                out["cluster_name"] = (v_el.text or "").strip()
            return out
        except Exception as e:
            logger.debug("_vm_placement_soap error: %s", e)
            return out

    def _vm_nics_soap(self, vm_id: str, guest_ip: str = "") -> list:
        """
        SOAP ile VM ağ adaptörlerini (MAC + label) okur.
        REST hardware/ethernet endpoint'i eski vCenter'larda 404 verebilir.
        """
        import xml.etree.ElementTree as ET
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return []
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>config.hardware.device</vim25:pathSet>
          <vim25:pathSet>guest.net</vim25:pathSet>
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
            resp = soap_session.post(soap_url, data=body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=15)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)

            def _tag(el): return el.tag.split("}")[-1]

            # guest.net → MAC → IP mapping
            mac_ips: dict = {}
            for gnet in root.iter():
                if _tag(gnet) != "GuestNicInfo" and _tag(gnet) != "net":
                    continue
                mac = ""
                ips: list = []
                for child in gnet:
                    ct = _tag(child)
                    if ct == "macAddress":
                        mac = child.text or ""
                    elif ct in ("ipAddress", "ipAddresses"):
                        for ip_el in child:
                            ip_val = (ip_el.text or "").strip()
                            if ip_val and not ip_val.startswith("fe80") and ":" not in ip_val:
                                ips.append({"address": ip_val, "version": "v4"})
                if mac:
                    mac_ips[mac.lower()] = ips

            # config.hardware.device → VirtualEthernetCard objects
            nics: list = []
            for device in root.iter():
                if not self._is_ethernet_device(device):
                    continue
                label = ""
                mac = ""
                portgroup = ""
                for child in device:
                    ct = _tag(child)
                    if ct == "label":
                        label = child.text or ""
                    elif ct == "macAddress":
                        mac = child.text or ""
                    elif ct == "deviceInfo":
                        for sub in child:
                            if _tag(sub) == "label":
                                label = sub.text or ""
                    elif ct == "backing":
                        for sub in child:
                            if _tag(sub) == "deviceName" and (sub.text or "").strip():
                                portgroup = sub.text.strip()
                            elif _tag(sub) == "port":
                                for p in sub:
                                    if _tag(p) == "portgroupKey" and (p.text or "").strip():
                                        portgroup = p.text.strip()

                nic_ips = mac_ips.get((mac or "").lower(), [])
                # Fallback: guest IP bilgisi varsa ilk NIC'e ekle
                if not nic_ips and guest_ip and not nics:
                    nic_ips = [{"address": guest_ip, "version": "v4"}]

                entry = {"name": label or f"NIC {len(nics)+1}", "mac": mac, "ips": nic_ips}
                if portgroup:
                    entry["portgroup"] = portgroup
                nics.append(entry)

            return nics
        except Exception as e:
            logger.debug(f"_vm_nics_soap error: {e}")
            return []

    def get_vm_full_details(self, vm_id: str, name: str = "") -> Optional[Dict]:
        """
        VM'in tüm detaylarını (CPU, RAM, disk, ağ, guest, cluster) tek sözlükte döner.
        REST hardware/* endpoint'leri 404 verirse SOAP'a düşer.
        """
        try:
            details = self.get_vm_details(vm_id) or {}
            guest   = self.get_vm_guest_info(vm_id) or {}

            # CPU / RAM
            cpu_count = (details.get("cpu") or {}).get("count", 0)
            mem_mb    = (details.get("memory") or {}).get("size_MiB", 0)

            # Power state & hardware version
            power_state = details.get("power_state", "UNKNOWN")
            hw_version  = (details.get("hardware") or {}).get("version", "")

            # Guest info
            guest_hostname = guest.get("host_name", "")
            guest_ip       = guest.get("ip_address", "")

            # ── Disk kapasitesi & Datastore ──────────────────────────────────
            disk_gb = 0
            datastore_name = ""
            disks_detail: list = []

            # 1) REST disk list endpoint (yeni vCenter)
            disks_resp = self._safe_api(f"/vcenter/vm/{vm_id}/hardware/disk")
            if disks_resp:
                disk_list = disks_resp if isinstance(disks_resp, list) else (disks_resp.get("value") or [])
                for disk in disk_list:
                    cap_bytes = disk.get("capacity") or disk.get("value", {}).get("capacity") or 0
                    disk_key = disk.get("disk") or disk.get("key", "")
                    label = disk.get("label") or (f"disk-{disk_key}" if disk_key else "disk")
                    thin = None
                    ds_for_disk = ""
                    if disk_key:
                        dd = self._safe_api(f"/vcenter/vm/{vm_id}/hardware/disk/{disk_key}") or {}
                        val = dd.get("value") or dd
                        cap_bytes = cap_bytes or val.get("capacity", 0)
                        label = val.get("label") or label
                        backing = val.get("backing") or {}
                        thin = backing.get("type") == "VMDK_FILE" and backing.get("thin") is True
                        if thin is None and "thin" in backing:
                            thin = bool(backing.get("thin"))
                        vmdk = backing.get("vmdk_file", "")
                        if vmdk and vmdk.startswith("["):
                            end = vmdk.find("]")
                            if end > 1:
                                ds_for_disk = vmdk[1:end].strip()
                                if not datastore_name:
                                    datastore_name = ds_for_disk
                    gb = int(cap_bytes) // (1024 ** 3) if cap_bytes else 0
                    disk_gb += gb
                    disks_detail.append({
                        "label": label,
                        "capacity_gb": gb,
                        "thin": thin,
                        "datastore": ds_for_disk or None,
                    })

            # 2) Fallback: SOAP config.hardware.device
            if disk_gb == 0:
                disk_gb = self._vm_disks_soap(vm_id)

            # 3) Datastore fallback: SOAP datastore adını çek
            if not datastore_name:
                datastore_name = self._vm_datastore_soap(vm_id)

            # ── Ağ adaptörleri ───────────────────────────────────────────────
            networks: list = []
            # 1) REST ethernet endpoint (yeni vCenter)
            nics_resp = self._safe_api(f"/vcenter/vm/{vm_id}/hardware/ethernet")
            if nics_resp:
                nic_list = nics_resp if isinstance(nics_resp, list) else (nics_resp.get("value") or [])
                for idx, nic in enumerate(nic_list):
                    nic_key = nic.get("nic") or nic.get("key", "")
                    mac = nic.get("mac_address", "")
                    label = nic.get("label", f"NIC {idx+1}")
                    portgroup = ""
                    if nic_key:
                        nd = self._safe_api(f"/vcenter/vm/{vm_id}/hardware/ethernet/{nic_key}") or {}
                        val = nd.get("value") or nd
                        mac   = val.get("mac_address", mac) or mac
                        label = val.get("label", label) or label
                        backing = val.get("backing") or {}
                        portgroup = (
                            backing.get("network_name")
                            or backing.get("network")
                            or ""
                        )
                        if isinstance(portgroup, dict):
                            portgroup = portgroup.get("name") or ""
                    entry = {
                        "name": label,
                        "mac": mac,
                        "ips": [{"address": guest_ip, "version": "v4"}] if guest_ip and idx == 0 else [],
                    }
                    if portgroup:
                        entry["portgroup"] = str(portgroup)
                    networks.append(entry)

            # 2) Fallback: SOAP guest.net + config.hardware.device
            if not networks:
                networks = self._vm_nics_soap(vm_id, guest_ip=guest_ip)

            # 3) Son çare: sadece guest IP'den minimal NIC oluştur
            if not networks and guest_ip:
                networks = [{"name": "eth0", "mac": "", "ips": [{"address": guest_ip, "version": "v4"}]}]

            # ── Cluster / Host yerleşimi ─────────────────────────────────────
            placement = self._vm_placement_soap(vm_id) or {}
            host_ref = placement.get("host_ref") or ""
            host_name = placement.get("host_name") or ""
            cluster_name = (
                placement.get("cluster_name")
                or details.get("resource_pool")
                or ""
            )
            # Tools full_name çoğu zaman daha okunaklıdır ("Red Hat Enterprise Linux 9 (64-bit)");
            # guest_OS yalnızca major id verir (RHEL_9_64). Minor sürüm SSH /etc/os-release'ten gelir.
            # REST identity.full_name localization dict olabilir — .strip() çökmesin.
            _full = self._guest_text(guest.get("full_name"))
            _gid = self._guest_text(details.get("guest_OS"))
            guest_os_full = _full or _gid

            return {
                "vm_id":               vm_id,
                "vm_name":             name or details.get("name", ""),
                "vm_guest_hostname":   guest_hostname,
                "vm_guest_ip":         guest_ip,
                "vm_cpu_count":        cpu_count,
                "vm_memory_mb":        mem_mb,
                "vm_disk_gb":          disk_gb,
                "vm_disks":            disks_detail or None,
                "vm_power_state":      power_state,
                "vm_tools_status":     self._guest_text(guest.get("tools_status")),
                "vm_network_info":     networks,
                "vm_cluster":          str(cluster_name) if cluster_name else "",
                "vm_datastore":        datastore_name,
                "vm_hardware_version": hw_version,
                "vm_host_name":        host_name,
                "vm_host_ref":         host_ref,
                "vm_guest_os_full":    guest_os_full,
                "os_type":             self._guest_text(guest.get("family")) or self._guest_os_family_fallback(details.get("guest_OS", "")),
            }
        except Exception as e:
            logger.error(f"VCenter get_vm_full_details error: {e}", exc_info=True)
            return None

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
          <vim25:pathSet>guest.disk</vim25:pathSet>
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
            guest_disks: List[Dict] = []
            for ps in root.iter():
                if ps.tag.split("}")[-1] == "propSet":
                    name_el = next((c for c in ps if c.tag.split("}")[-1] == "name"), None)
                    val_el  = next((c for c in ps if c.tag.split("}")[-1] == "val"),  None)
                    if name_el is not None and val_el is not None:
                        pname = name_el.text or ""
                        if pname == "guest.disk":
                            for gdi in val_el.iter():
                                if gdi.tag.split("}")[-1] != "GuestDiskInfo":
                                    continue
                                flat_d = {
                                    c.tag.split("}")[-1]: (c.text or "").strip()
                                    for c in gdi
                                }
                                if flat_d.get("capacity"):
                                    guest_disks.append(flat_d)
                            continue
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

            disk_percent = None
            disk_total_gb = None
            disk_avail_gb = None
            if guest_disks:
                total_cap = 0
                total_free = 0
                for d in guest_disks:
                    try:
                        cap = int(d.get("capacity") or 0)
                        free = int(d.get("freeSpace") or 0)
                    except (TypeError, ValueError):
                        continue
                    if cap > 0:
                        total_cap += cap
                        total_free += max(0, free)
                if total_cap > 0:
                    disk_percent = round((1 - total_free / total_cap) * 100, 1)
                    disk_total_gb = round(total_cap / (1024 ** 3), 1)
                    disk_avail_gb = round(total_free / (1024 ** 3), 1)

            return {
                "cpu_mhz": cpu_mhz,
                "cpu_percent": cpu_percent,
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
                "mem_percent": mem_percent,
                "disk_percent": disk_percent,
                "disk_total_gb": disk_total_gb,
                "disk_avail_gb": disk_avail_gb,
                "uptime_seconds": uptime,
                "power_state": power_state,
                "num_cpu": num_cpu,
                "source": "vcenter",
            }
        except Exception as e:
            logger.error(f"get_vm_quick_stats error: {e}")
            return None

    def _perf_manager_and_counters(self, soap_session, soap_url: str):
        """performanceManager MOR + virtualDisk read/write average counter ID'leri."""
        import xml.etree.ElementTree as ET
        if getattr(self, "_perf_cache", None):
            return self._perf_cache

        body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveServiceContent>
      <vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>
    </vim25:RetrieveServiceContent>
  </soapenv:Body>
</soapenv:Envelope>"""
        resp = soap_session.post(
            soap_url, data=body,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            verify=self.verify_ssl, timeout=15,
        )
        if resp.status_code != 200:
            return None
        root = ET.fromstring(resp.text)
        perf_mgr = None
        for el in root.iter():
            if el.tag.split("}")[-1] == "perfManager" and (el.text or "").strip():
                perf_mgr = el.text.strip()
                break
        if not perf_mgr:
            return None

        # Counter catalog
        body2 = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>PerformanceManager</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>perfCounter</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="PerformanceManager">{perf_mgr}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
        resp2 = soap_session.post(
            soap_url, data=body2,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            verify=self.verify_ssl, timeout=30,
        )
        if resp2.status_code != 200:
            return None
        root2 = ET.fromstring(resp2.text)
        wanted = {
            ("virtualDisk", "numberReadAveraged", "average"): "read",
            ("virtualDisk", "numberWriteAveraged", "average"): "write",
            ("net", "bytesRx", "average"): "net_rx",
            ("net", "bytesTx", "average"): "net_tx",
            # CPU Ready (ms / interval) — VM bazlı contention
            ("cpu", "ready", "summation"): "cpu_ready",
            # Disk latency (ms)
            ("disk", "totalLatency", "average"): "disk_latency",
            ("virtualDisk", "totalReadLatency", "average"): "disk_read_lat",
            ("virtualDisk", "totalWriteLatency", "average"): "disk_write_lat",
            ("datastore", "totalReadLatency", "average"): "ds_read_lat",
            ("datastore", "totalWriteLatency", "average"): "ds_write_lat",
        }
        found: Dict[str, int] = {}
        # Each PerfCounterInfo is typically under val/*/ or PropSet children
        current: Dict[str, str] = {}
        for el in root2.iter():
            tag = el.tag.split("}")[-1]
            if tag == "key" and el.text and el.text.isdigit():
                current = {"key": el.text}
            elif tag in ("groupInfo", "nameInfo", "rollupType") and current is not None:
                # nested name/key under groupInfo/nameInfo
                pass
            elif tag == "key" and current and "group" not in current:
                # ambiguous — prefer structured walk below
                pass

        # Structured: find PerfCounterInfo elements
        for pci in root2.iter():
            if pci.tag.split("}")[-1] != "PerfCounterInfo" and not (
                pci.tag.split("}")[-1] == "perfCounter"
            ):
                # counters often appear as ArrayOfPerfCounterInfo children named PerfCounterInfo
                pass

        counters_xml = []
        for el in root2.iter():
            if el.tag.split("}")[-1] in ("PerfCounterInfo",):
                counters_xml.append(el)
        # Fallback: any element with child key + groupInfo
        if not counters_xml:
            for el in root2.iter():
                kids = {c.tag.split("}")[-1] for c in list(el)}
                if "groupInfo" in kids and "nameInfo" in kids and "key" in kids:
                    counters_xml.append(el)

        for pci in counters_xml:
            flat: Dict[str, str] = {}
            key_el = next((c for c in pci if c.tag.split("}")[-1] == "key"), None)
            rollup_el = next((c for c in pci if c.tag.split("}")[-1] == "rollupType"), None)
            group_name = None
            counter_name = None
            for child in pci:
                ct = child.tag.split("}")[-1]
                if ct == "groupInfo":
                    gn = next((c for c in child if c.tag.split("}")[-1] == "key"), None)
                    group_name = gn.text if gn is not None else None
                elif ct == "nameInfo":
                    nn = next((c for c in child if c.tag.split("}")[-1] == "key"), None)
                    counter_name = nn.text if nn is not None else None
            if key_el is None or not group_name or not counter_name:
                continue
            rollup = (rollup_el.text or "").strip() if rollup_el is not None else ""
            slot = wanted.get((group_name, counter_name, rollup))
            if slot:
                try:
                    found[slot] = int(key_el.text)
                except (TypeError, ValueError):
                    pass

        if not found:
            logger.debug("VMware perf counters for VM disk/net not found")
            return None

        self._perf_cache = (perf_mgr, found)
        return self._perf_cache

    def get_vm_disk_iops(self, vm_id: str) -> Optional[Dict]:
        """Geriye uyum: get_vm_perf_io yalnızca disk alanlarını döner."""
        perf = self.get_vm_perf_io(vm_id)
        if not perf:
            return None
        if perf.get("disk_read_iops") is None and perf.get("disk_write_iops") is None:
            return None
        return {
            "disk_read_iops": perf.get("disk_read_iops"),
            "disk_write_iops": perf.get("disk_write_iops"),
            "source": "vcenter_perf",
        }

    def get_vm_perf_io(self, vm_id: str) -> Optional[Dict]:
        """
        PerformanceManager QueryPerf — virtualDisk IOPS + net bytesRx/Tx (KB/s civarı).
        Guest filesystem % vermez; o get_vm_quick_stats(guest.disk) ile gelir.
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return None
        try:
            cache = self._perf_manager_and_counters(soap_session, soap_url)
            if not cache:
                return None
            perf_mgr, found = cache
            metric_xml = ""
            for slot, cid in found.items():
                metric_xml += (
                    f"<vim25:metricId><vim25:counterId>{cid}</vim25:counterId>"
                    f"<vim25:instance>*</vim25:instance></vim25:metricId>"
                )
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:QueryPerf>
      <vim25:_this type="PerformanceManager">{perf_mgr}</vim25:_this>
      <vim25:querySpec>
        <vim25:entity type="VirtualMachine">{vm_id}</vim25:entity>
        <vim25:maxSample>1</vim25:maxSample>
        {metric_xml}
        <vim25:intervalId>20</vim25:intervalId>
      </vim25:querySpec>
    </vim25:QueryPerf>
  </soapenv:Body>
</soapenv:Envelope>"""
            resp = soap_session.post(
                soap_url, data=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=20,
            )
            if resp.status_code != 200:
                logger.debug("QueryPerf HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            root = ET.fromstring(resp.text)
            series_vals: List[tuple] = []
            for el in root.iter():
                tag = el.tag.split("}")[-1]
                if tag == "counterId" and el.text and el.text.isdigit():
                    series_vals.append(("cid", int(el.text)))
                elif tag == "value":
                    nums: List[float] = []
                    if el.text and el.text.strip():
                        try:
                            nums.append(float(el.text.strip()))
                        except ValueError:
                            pass
                    for c in el:
                        if c.text and c.text.strip():
                            try:
                                nums.append(float(c.text.strip()))
                            except ValueError:
                                pass
                    if nums:
                        series_vals.append(("val", nums[-1]))

            current_cid = None
            sums: Dict[int, List[float]] = {}
            for kind, v in series_vals:
                if kind == "cid":
                    current_cid = int(v)
                    sums.setdefault(current_cid, [])
                elif kind == "val" and current_cid is not None:
                    sums[current_cid].append(float(v))

            def _sum_slot(slot: str) -> Optional[float]:
                cid = found.get(slot)
                if cid is None:
                    return None
                vals = sums.get(cid, [])
                return sum(vals) if vals else 0.0

            read_iops = _sum_slot("read")
            write_iops = _sum_slot("write")
            net_rx = _sum_slot("net_rx")
            net_tx = _sum_slot("net_tx")
            cpu_ready = _sum_slot("cpu_ready")
            disk_lat = _sum_slot("disk_latency")
            disk_r_lat = _sum_slot("disk_read_lat")
            disk_w_lat = _sum_slot("disk_write_lat")
            if all(v is None for v in (
                read_iops, write_iops, net_rx, net_tx,
                cpu_ready, disk_lat, disk_r_lat, disk_w_lat,
            )):
                return None
            return {
                "disk_read_iops": round(read_iops, 2) if read_iops is not None else None,
                "disk_write_iops": round(write_iops, 2) if write_iops is not None else None,
                # VMware net.bytesRx/Tx average ≈ KB/s (instance aggregate)
                "net_rx_kbps": round(net_rx, 2) if net_rx is not None else None,
                "net_tx_kbps": round(net_tx, 2) if net_tx is not None else None,
                "cpu_ready_ms": round(cpu_ready, 2) if cpu_ready is not None else None,
                "disk_latency_ms": round(disk_lat, 2) if disk_lat is not None else None,
                "disk_read_latency_ms": round(disk_r_lat, 2) if disk_r_lat is not None else None,
                "disk_write_latency_ms": round(disk_w_lat, 2) if disk_w_lat is not None else None,
                "source": "vcenter_perf",
            }
        except Exception as e:
            logger.warning("get_vm_perf_io error: %s", e)
            return None

    def get_vm_live_metrics(self, vm_id: str) -> Optional[Dict]:
        """QuickStats (CPU/RAM/disk%) + PerformanceManager (disk IOPS + net)."""
        stats = self.get_vm_quick_stats(vm_id)
        if not stats:
            return None
        perf = self.get_vm_perf_io(vm_id) or {}
        stats.update({
            "disk_read_iops": perf.get("disk_read_iops"),
            "disk_write_iops": perf.get("disk_write_iops"),
            "net_rx_kbps": perf.get("net_rx_kbps"),
            "net_tx_kbps": perf.get("net_tx_kbps"),
        })
        return stats

    def get_all_vm_perf_io(self, vm_refs: List[str]) -> Dict[str, Dict]:
        """
        TÜM verilen VM'ler için disk IOPS + network throughput'u az sayıda (chunk'lı)
        SOAP QueryPerf çağrısıyla toplu getirir — VM başına ayrı çağrı yapmaz.
        Dönen: vm_ref -> {disk_read_iops, disk_write_iops, net_rx_kbps, net_tx_kbps}
        """
        import xml.etree.ElementTree as ET

        if not vm_refs:
            return {}
        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return {}

        cache = self._perf_manager_and_counters(soap_session, soap_url)
        if not cache:
            return {}
        perf_mgr, found = cache
        if not found:
            return {}

        metric_xml = "".join(
            f"<vim25:metricId><vim25:counterId>{cid}</vim25:counterId>"
            f"<vim25:instance>*</vim25:instance></vim25:metricId>"
            for cid in found.values()
        )

        def _tag(el):
            return el.tag.split("}")[-1]

        results: Dict[str, Dict] = {}
        chunk_size = 100
        for i in range(0, len(vm_refs), chunk_size):
            chunk = vm_refs[i:i + chunk_size]
            query_specs = "".join(
                f'<vim25:querySpec><vim25:entity type="VirtualMachine">{ref}</vim25:entity>'
                f"<vim25:maxSample>1</vim25:maxSample>{metric_xml}"
                f"<vim25:intervalId>20</vim25:intervalId></vim25:querySpec>"
                for ref in chunk
            )
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:QueryPerf>
      <vim25:_this type="PerformanceManager">{perf_mgr}</vim25:_this>
      {query_specs}
    </vim25:QueryPerf>
  </soapenv:Body>
</soapenv:Envelope>"""
            try:
                resp = soap_session.post(
                    soap_url, data=body,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    verify=self.verify_ssl, timeout=45,
                )
                if resp.status_code != 200:
                    logger.debug("get_all_vm_perf_io HTTP %s: %s", resp.status_code, resp.text[:200])
                    continue
                root = ET.fromstring(resp.text)
                for rv in root.iter():
                    if _tag(rv) != "returnval":
                        continue
                    entity_el = next((c for c in rv if _tag(c) == "entity"), None)
                    if entity_el is None or not entity_el.text:
                        continue
                    vm_ref = entity_el.text

                    sums: Dict[int, List[float]] = {}
                    for val_el in rv:
                        if _tag(val_el) != "value":
                            continue
                        id_el = next((c for c in val_el if _tag(c) == "id"), None)
                        cid = None
                        if id_el is not None:
                            cid_el = next((c for c in id_el if _tag(c) == "counterId"), None)
                            if cid_el is not None and cid_el.text:
                                try:
                                    cid = int(cid_el.text)
                                except ValueError:
                                    cid = None
                        if cid is None:
                            continue
                        nums = []
                        for c in val_el:
                            if _tag(c) == "value" and c.text and c.text.strip():
                                try:
                                    nums.append(float(c.text.strip()))
                                except ValueError:
                                    pass
                        if nums:
                            sums.setdefault(cid, []).extend(nums)

                    def _sum_slot(slot: str) -> Optional[float]:
                        cid = found.get(slot)
                        if cid is None:
                            return None
                        vals = sums.get(cid, [])
                        return round(sum(vals), 2) if vals else 0.0

                    results[vm_ref] = {
                        "disk_read_iops": _sum_slot("read"),
                        "disk_write_iops": _sum_slot("write"),
                        "net_rx_kbps": _sum_slot("net_rx"),
                        "net_tx_kbps": _sum_slot("net_tx"),
                        "cpu_ready_ms": _sum_slot("cpu_ready"),
                        "disk_latency_ms": _sum_slot("disk_latency"),
                        "disk_read_latency_ms": _sum_slot("disk_read_lat"),
                        "disk_write_latency_ms": _sum_slot("disk_write_lat"),
                        "ds_read_latency_ms": _sum_slot("ds_read_lat"),
                        "ds_write_latency_ms": _sum_slot("ds_write_lat"),
                    }
            except Exception as e:
                logger.warning("get_all_vm_perf_io chunk error: %s", e)

        return results


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
                    # summary.hardware zaten çekiliyor — vendor/model bedavaya çıkar
                    "host_vendor":      flat.get("vendor"),
                    "host_model":       flat.get("model"),
                    "host_uuid":        flat.get("uuid"),
                    "cpu_model":        flat.get("cpuModel"),
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

    # Folder → Datacenter → vmFolder (recursive) → VirtualMachine
    _VM_TRAVERSAL = """
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>visitFolders</vim25:name>
            <vim25:type>Folder</vim25:type>
            <vim25:path>childEntity</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>dcToVmF</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToVmF</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>vmFolder</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
          </vim25:selectSet>"""

    def get_all_vm_live_stats(self) -> List[Dict]:
        """
        Tüm VM'lerin CANLI performans/durum verisini tek SOAP çağrısıyla toplar:
        güç durumu, boot zamanı (→ uptime), CPU/RAM anlık kullanım, memory
        ballooning/swap ve snapshot sayısı/en eski snapshot tarihi.

        CPU Ready / disk latency PerformanceManager QueryPerf ile ayrıca
        get_all_vm_perf_io üzerinden gelir. customValue (Custom Attributes)
        bu çağrıda toplanır. (summary.storage bazı ESXi/vCenter sürümlerinde
        InvalidProperty verdiği için dahil edilmez.)
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("get_all_vm_live_stats: SOAP login failed")
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
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>runtime.powerState</vim25:pathSet>
          <vim25:pathSet>runtime.bootTime</vim25:pathSet>
          <vim25:pathSet>runtime.host</vim25:pathSet>
          <vim25:pathSet>summary.quickStats</vim25:pathSet>
          <vim25:pathSet>snapshot</vim25:pathSet>
          <vim25:pathSet>customValue</vim25:pathSet>
          <vim25:pathSet>config.hardware.numCPU</vim25:pathSet>
          <vim25:pathSet>guest.disk</vim25:pathSet>
          <vim25:pathSet>guest.toolsVersionStatus2</vim25:pathSet>
          <vim25:pathSet>config.cpuHotAddEnabled</vim25:pathSet>
          <vim25:pathSet>config.memoryHotAddEnabled</vim25:pathSet>
          <vim25:pathSet>config.cpuAllocation</vim25:pathSet>
          <vim25:pathSet>config.memoryAllocation</vim25:pathSet>
          <vim25:pathSet>config.hardware.device</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Folder">{root_folder}</vim25:obj>
          <vim25:skip>false</vim25:skip>
          {self._VM_TRAVERSAL}
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""

        try:
            resp = soap_session.post(soap_url, data=soap_body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=90)
            if resp.status_code != 200:
                logger.warning(f"get_all_vm_live_stats HTTP {resp.status_code}: {resp.text[:300]}")
                return []

            root_xml = ET.fromstring(resp.text)
            results = []

            def _tag(el): return el.tag.split("}")[-1]

            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue

                vm_ref = None
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                if obj_el is not None:
                    vm_ref = obj_el.text

                flat: dict = {}
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = n_el.text or ""

                    if pname == "snapshot":
                        create_times = [c.text for c in v_el.iter() if _tag(c) == "createTime" and c.text]
                        flat["snapshot_count"] = len(create_times)
                        flat["snapshot_oldest"] = min(create_times) if create_times else None
                        continue
                    if pname == "customValue":
                        attrs = []
                        for cv in v_el.iter():
                            ct = _tag(cv)
                            if ct not in ("CustomFieldValue", "CustomFieldStringValue"):
                                continue
                            key_el = next((c for c in cv if _tag(c) == "key"), None)
                            val_el = next((c for c in cv if _tag(c) == "value"), None)
                            if key_el is not None or val_el is not None:
                                attrs.append({
                                    "key": (key_el.text if key_el is not None else None),
                                    "value": (val_el.text if val_el is not None else None),
                                })
                        flat["_custom_attrs"] = attrs
                        continue
                    if pname == "summary.quickStats":
                        for child in v_el:
                            flat[_tag(child)] = child.text
                        continue
                    if pname == "guest.disk":
                        guest_disks = []
                        for gdi in v_el:
                            if _tag(gdi) != "GuestDiskInfo":
                                continue
                            d = {_tag(c): (c.text or "").strip() for c in gdi}
                            if d.get("capacity"):
                                guest_disks.append(d)
                        flat["_guest_disks"] = guest_disks
                        continue
                    if pname == "config.cpuAllocation":
                        for child in v_el:
                            flat[f"cpuAlloc_{_tag(child)}"] = child.text
                        continue
                    if pname == "config.memoryAllocation":
                        for child in v_el:
                            flat[f"memAlloc_{_tag(child)}"] = child.text
                        continue
                    if pname == "config.hardware.device":
                        # Polimorfik dizi: her <VirtualDevice> elemanının GERÇEK alt tipi
                        # tag adında değil xsi:type özniteliğinde gelir (ör.
                        # <VirtualDevice xsi:type="VirtualDisk">) — bu yüzden _tag()
                        # yerine xsi:type öznitelik değerine bakılır.
                        _XSI_NS = "{http://www.w3.org/2001/XMLSchema-instance}type"
                        disks: List[Dict[str, Any]] = []
                        nics: List[Dict[str, Any]] = []
                        for dev in v_el:
                            dtype = dev.attrib.get(_XSI_NS) or _tag(dev)
                            if dtype == "VirtualDisk":
                                backing = next((c for c in dev if _tag(c) == "backing"), None)
                                thin = None
                                if backing is not None:
                                    thin_el = next((c for c in backing if _tag(c) == "thinProvisioned"), None)
                                    thin = thin_el.text if thin_el is not None else None
                                disks.append({"thin_provisioned": thin})
                            elif "Ethernet" in dtype:
                                conn = next((c for c in dev if _tag(c) == "connectable"), None)
                                connected = None
                                if conn is not None:
                                    c_el = next((c for c in conn if _tag(c) == "connected"), None)
                                    connected = c_el.text if c_el is not None else None
                                nics.append({"connected": connected})
                        flat["_disk_devices"] = disks
                        flat["_nic_devices"] = nics
                        continue
                    # skaler değerler (name, runtime.powerState, runtime.bootTime, config.hardware.numCPU,
                    # guest.toolsVersionStatus2, config.cpuHotAddEnabled, config.memoryHotAddEnabled)
                    if v_el.text and v_el.text.strip():
                        flat[pname] = v_el.text.strip()

                def _f(k, default=None):
                    v = flat.get(k)
                    try:
                        return float(v) if v is not None else default
                    except Exception:
                        return default

                def _i(k, default=None):
                    v = flat.get(k)
                    try:
                        return int(float(v)) if v is not None else default
                    except Exception:
                        return default

                # Guest içi disk doluluk % (VMware Tools guest.disk — Tools çalışmıyorsa boş kalır)
                guest_disks = flat.get("_guest_disks") or []
                guest_disk_pct = guest_disk_total_gb = guest_disk_avail_gb = None
                if guest_disks:
                    try:
                        total_cap = sum(int(d.get("capacity") or 0) for d in guest_disks)
                        total_free = sum(max(0, int(d.get("freeSpace") or 0)) for d in guest_disks)
                        if total_cap > 0:
                            guest_disk_pct = round((1 - total_free / total_cap) * 100, 1)
                            guest_disk_total_gb = round(total_cap / (1024 ** 3), 1)
                            guest_disk_avail_gb = round(total_free / (1024 ** 3), 1)
                    except Exception:
                        pass

                # Thin/Thick provisioning (VM'in tüm diskleri aynı tipteyse net sonuç, karışıksa "mixed")
                disk_devices = flat.get("_disk_devices") or []
                thin_flags = [d.get("thin_provisioned") for d in disk_devices if d.get("thin_provisioned") is not None]
                disk_provisioning = None
                if thin_flags:
                    if all(t == "true" for t in thin_flags):
                        disk_provisioning = "thin"
                    elif all(t == "false" for t in thin_flags):
                        disk_provisioning = "thick"
                    else:
                        disk_provisioning = "mixed"

                nic_devices = flat.get("_nic_devices") or []
                nic_disconnected = sum(1 for n in nic_devices if n.get("connected") == "false")

                results.append({
                    "vm_ref": vm_ref,
                    "name": flat.get("name", vm_ref or "unknown"),
                    "power_state": flat.get("runtime.powerState", "unknown"),
                    "boot_time": flat.get("runtime.bootTime"),
                    "host_ref": flat.get("runtime.host"),
                    "num_cpu": _i("config.hardware.numCPU"),
                    "cpu_usage_mhz": _f("overallCpuUsage"),
                    "cpu_demand_mhz": _f("overallCpuDemand"),
                    "guest_mem_usage_mb": _f("guestMemoryUsage"),
                    "host_mem_usage_mb": _f("hostMemoryUsage"),
                    "ballooned_mb": _f("balloonedMemory"),
                    "swapped_mb": _f("swappedMemory"),
                    "compressed_kb": _f("compressedMemory"),
                    "uptime_seconds": _i("uptimeSeconds"),
                    "snapshot_count": flat.get("snapshot_count", 0),
                    "snapshot_oldest": flat.get("snapshot_oldest"),
                    "snapshot_space_gb": None,
                    "custom_attrs": flat.get("_custom_attrs") or [],
                    "guest_disk_pct": guest_disk_pct,
                    "guest_disk_total_gb": guest_disk_total_gb,
                    "guest_disk_avail_gb": guest_disk_avail_gb,
                    "disk_provisioning": disk_provisioning,
                    "nic_total": len(nic_devices),
                    "nic_disconnected": nic_disconnected,
                    "cpu_hot_add": flat.get("config.cpuHotAddEnabled"),
                    "memory_hot_add": flat.get("config.memoryHotAddEnabled"),
                    "cpu_reservation_mhz": _i("cpuAlloc_reservation"),
                    "cpu_limit_mhz": _i("cpuAlloc_limit"),
                    "memory_reservation_mb": _i("memAlloc_reservation"),
                    "memory_limit_mb": _i("memAlloc_limit"),
                    "tools_version_status": flat.get("guest.toolsVersionStatus2"),
                })

            logger.info(f"get_all_vm_live_stats: {len(results)} VM ({self.host})")
            return results

        except Exception as e:
            logger.error(f"get_all_vm_live_stats error: {e}", exc_info=True)
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

    def list_datastores_status(self) -> List[Dict[str, Any]]:
        """
        Tüm datastore'ları TEK TEK (host bazlı toplama yapmadan) isim/kapasite/
        erişilebilirlik/bağlı host sayısıyla listeler. 'Datastore'a erişemeyen var mı',
        'hangi datastore erişilemez durumda' gibi sorularda kullanılır.
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("list_datastores_status: SOAP login failed")
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
          <vim25:type>Datastore</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>summary.name</vim25:pathSet>
          <vim25:pathSet>summary.type</vim25:pathSet>
          <vim25:pathSet>summary.capacity</vim25:pathSet>
          <vim25:pathSet>summary.freeSpace</vim25:pathSet>
          <vim25:pathSet>summary.accessible</vim25:pathSet>
          <vim25:pathSet>host</vim25:pathSet>
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
            <vim25:selectSet><vim25:name>dcToDF</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToDF</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>datastoreFolder</vim25:path>
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
                                     verify=self.verify_ssl, timeout=30)
            if resp.status_code != 200:
                logger.warning("list_datastores_status HTTP %s: %s", resp.status_code, resp.text[:200])
                return []

            root = ET.fromstring(resp.text)

            def _tag(el):
                return el.tag.split("}")[-1]

            results: List[Dict[str, Any]] = []
            for rv in root.iter():
                if _tag(rv) != "returnval":
                    continue
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                ds_ref = obj_el.text if obj_el is not None else None

                flat: Dict[str, str] = {}
                host_count = 0
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = n_el.text or ""
                    if pname == "host":
                        host_count = sum(1 for c in v_el if _tag(c) == "DatastoreHostMount")
                        continue
                    if v_el.text and v_el.text.strip():
                        flat[pname] = v_el.text.strip()

                try:
                    cap = float(flat.get("summary.capacity", 0) or 0)
                    free = float(flat.get("summary.freeSpace", 0) or 0)
                except (TypeError, ValueError):
                    cap = free = 0.0

                results.append({
                    "ref": ds_ref,
                    "name": flat.get("summary.name", ds_ref),
                    "type": flat.get("summary.type"),
                    "capacity_gb": round(cap / (1024 ** 3), 1) if cap > 0 else None,
                    "free_gb": round(free / (1024 ** 3), 1) if cap > 0 else None,
                    "used_gb": round((cap - free) / (1024 ** 3), 1) if cap > 0 else None,
                    "usage_pct": round((cap - free) / cap * 100, 1) if cap > 0 else None,
                    "accessible": flat.get("summary.accessible", "true").lower() != "false",
                    "host_count": host_count,
                })
            return results
        except Exception as e:
            logger.error("list_datastores_status error: %s", e, exc_info=True)
            return []

    def list_clusters_status(self) -> List[Dict[str, Any]]:
        """
        ClusterComputeResource listesi: ad, HA/DRS durumu, host/VM sayısı (canlı SOAP).
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("list_clusters_status: SOAP login failed")
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
          <vim25:type>ClusterComputeResource</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>summary.totalCpu</vim25:pathSet>
          <vim25:pathSet>summary.numCpuCores</vim25:pathSet>
          <vim25:pathSet>summary.totalMemory</vim25:pathSet>
          <vim25:pathSet>summary.numHosts</vim25:pathSet>
          <vim25:pathSet>summary.overallStatus</vim25:pathSet>
          <vim25:pathSet>configuration.dasConfig.enabled</vim25:pathSet>
          <vim25:pathSet>configuration.drsConfig.enabled</vim25:pathSet>
          <vim25:pathSet>configuration.drsConfig.defaultVmBehavior</vim25:pathSet>
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
            <vim25:selectSet><vim25:name>dcToHf</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>crToH</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToHf</vim25:name>
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
          </vim25:selectSet>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            resp = soap_session.post(
                soap_url, data=soap_body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=30,
            )
            if resp.status_code != 200:
                logger.warning("list_clusters_status HTTP %s: %s", resp.status_code, resp.text[:200])
                return []

            root = ET.fromstring(resp.text)

            def _tag(el):
                return el.tag.split("}")[-1]

            results: List[Dict[str, Any]] = []
            for rv in root.iter():
                if _tag(rv) != "returnval":
                    continue
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                if obj_el is None:
                    continue
                obj_type = obj_el.get("type") or ""
                if obj_type and obj_type != "ClusterComputeResource":
                    continue
                ref = obj_el.text

                flat: Dict[str, str] = {}
                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = n_el.text or ""
                    if v_el.text and v_el.text.strip():
                        flat[pname] = v_el.text.strip()

                if not flat.get("name") and not ref:
                    continue
                try:
                    total_mem = float(flat.get("summary.totalMemory", 0) or 0)
                    mem_gb = round(total_mem / (1024 ** 3), 1) if total_mem else None
                except (TypeError, ValueError):
                    mem_gb = None
                ha = flat.get("configuration.dasConfig.enabled", "").lower()
                drs = flat.get("configuration.drsConfig.enabled", "").lower()
                results.append({
                    "ref": ref,
                    "name": flat.get("name") or ref,
                    "hosts": int(flat["summary.numHosts"]) if flat.get("summary.numHosts", "").isdigit() else None,
                    "cpu_cores": int(flat["summary.numCpuCores"]) if flat.get("summary.numCpuCores", "").isdigit() else None,
                    "memory_gb": mem_gb,
                    "overall_status": flat.get("summary.overallStatus"),
                    "ha_enabled": ha in ("true", "1") if ha else None,
                    "drs_enabled": drs in ("true", "1") if drs else None,
                    "drs_behavior": flat.get("configuration.drsConfig.defaultVmBehavior"),
                })
            return results
        except Exception as e:
            logger.error("list_clusters_status error: %s", e, exc_info=True)
            return []

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

    @staticmethod
    def _xml_struct_to_dict(el, tag_fn):
        """
        Bir XML elementini nested dict/list yapısına çevirir (genel amaçlı).
        Aynı tag birden fazla kez tekrar ediyorsa (örn. birden fazla pnic/vswitch) liste olur.
        Leaf node (çocuğu olmayan) ise doğrudan text değerini döner.
        """
        children = list(el)
        if not children:
            return el.text
        out: dict = {}
        for child in children:
            tag = tag_fn(child)
            val = VCenterClient._xml_struct_to_dict(child, tag_fn)
            if tag in out:
                if not isinstance(out[tag], list):
                    out[tag] = [out[tag]]
                out[tag].append(val)
            else:
                out[tag] = val
        return out

    def get_all_host_network_info(self) -> Dict[str, Dict]:
        """
        vCenter'daki tüm ESX host'ların ağ yapılandırmasını (fiziksel NIC, vSwitch,
        port group/VLAN, VMkernel NIC, DNS) ve donanım kimlik bilgisini (vendor/model/uuid)
        döner. host_ref → {...} sözlüğü şeklinde.

        get_all_host_stats() metriklerden ayrı tutulur çünkü bu bilgi çok nadir değişir
        (metrikler 15 dk'da bir, bu ise daha seyrek senkronize edilebilir).
        """
        import re
        import xml.etree.ElementTree as ET

        soap_url     = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("get_all_host_network_info: SOAP login failed")
            return {}

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
          <vim25:pathSet>config.network</vim25:pathSet>
          <vim25:pathSet>hardware.systemInfo</vim25:pathSet>
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

        def _tag(el): return el.tag.split("}")[-1]

        def _as_list(x):
            if x is None:
                return []
            return x if isinstance(x, list) else [x]

        try:
            resp = soap_session.post(soap_url, data=soap_body,
                                     headers={"Content-Type": "text/xml; charset=utf-8"},
                                     verify=self.verify_ssl, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"get_all_host_network_info HTTP {resp.status_code}: {resp.text[:300]}")
                return {}

            root_xml = ET.fromstring(resp.text)
            out: Dict[str, Dict] = {}

            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue

                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                host_ref = obj_el.text if obj_el is not None else None
                if not host_ref:
                    continue

                host_name = None
                net_struct: dict = {}
                hw_struct: dict = {}

                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"),  None)
                    if n_el is None or v_el is None:
                        continue
                    pname = (n_el.text or "").strip()

                    if pname == "name":
                        host_name = v_el.text
                    elif pname == "config.network":
                        net_struct = self._xml_struct_to_dict(v_el, _tag) or {}
                    elif pname == "hardware.systemInfo":
                        hw_struct = self._xml_struct_to_dict(v_el, _tag) or {}

                # ── Fiziksel NIC'ler ──────────────────────────────────────────────
                pnics = []
                for p in _as_list(net_struct.get("pnic")):
                    if not isinstance(p, dict):
                        continue
                    link = p.get("linkSpeed") if isinstance(p.get("linkSpeed"), dict) else {}
                    spec = p.get("spec") if isinstance(p.get("spec"), dict) else {}
                    pnics.append({
                        "device":        p.get("device"),
                        "mac":           p.get("mac"),
                        "link_speed_mb": link.get("speedMb"),
                        "full_duplex":   link.get("duplex"),
                        "mtu":           spec.get("mtu"),
                    })

                # ── vSwitch'ler ───────────────────────────────────────────────────
                # vSwitch.pnic/portgroup referansları "key-vim.host.PhysicalNic-vmnic1" gibi
                # MOR key'leri olarak gelir; okunabilirlik için bilinen ön eki temizliyoruz.
                def _short_key(k):
                    if not isinstance(k, str):
                        return k
                    return re.sub(r"^key-vim\.host\.\w+-", "", k)

                vswitches = []
                for vs in _as_list(net_struct.get("vswitch")):
                    if not isinstance(vs, dict):
                        continue
                    spec = vs.get("spec") if isinstance(vs.get("spec"), dict) else {}
                    vswitches.append({
                        "name":       vs.get("name"),
                        "num_ports":  spec.get("numPorts"),
                        "pnics":      [_short_key(k) for k in _as_list(vs.get("pnic"))],
                        "portgroups": [_short_key(k) for k in _as_list(vs.get("portgroup"))],
                    })

                # ── Port group / VLAN ─────────────────────────────────────────────
                portgroups = []
                for pg in _as_list(net_struct.get("portgroup")):
                    if not isinstance(pg, dict):
                        continue
                    spec = pg.get("spec") if isinstance(pg.get("spec"), dict) else {}
                    portgroups.append({
                        "name":         spec.get("name"),
                        "vlan_id":      spec.get("vlanId"),
                        "vswitch_name": spec.get("vswitchName"),
                    })

                # ── VMkernel NIC'ler (vnic) ────────────────────────────────────────
                vnics = []
                for vn in _as_list(net_struct.get("vnic")):
                    if not isinstance(vn, dict):
                        continue
                    spec = vn.get("spec") if isinstance(vn.get("spec"), dict) else {}
                    ip   = spec.get("ip") if isinstance(spec.get("ip"), dict) else {}
                    dhcp_val = ip.get("dhcp")
                    vnics.append({
                        "device":      vn.get("device"),
                        "portgroup":   vn.get("portgroup"),
                        "mtu":         spec.get("mtu"),
                        "ip_address":  ip.get("ipAddress"),
                        "subnet_mask": ip.get("subnetMask"),
                        "dhcp":        str(dhcp_val).lower() == "true" if dhcp_val is not None else None,
                    })

                # ── DNS ayarları ──────────────────────────────────────────────────
                dns_struct = net_struct.get("dnsConfig") if isinstance(net_struct.get("dnsConfig"), dict) else {}
                dns_dhcp   = dns_struct.get("dhcp")
                dns_info = {
                    "host_name":   dns_struct.get("hostName"),
                    "domain_name": dns_struct.get("domainName"),
                    "dhcp":        str(dns_dhcp).lower() == "true" if dns_dhcp is not None else None,
                    "servers":     _as_list(dns_struct.get("address")),
                }

                out[host_ref] = {
                    "host_name":  host_name,
                    "vendor":     hw_struct.get("vendor"),
                    "model":      hw_struct.get("model"),
                    "uuid":       hw_struct.get("uuid"),
                    "pnics":      pnics,
                    "vswitches":  vswitches,
                    "portgroups": portgroups,
                    "vnics":      vnics,
                    "dns":        dns_info,
                }

            logger.info(f"get_all_host_network_info: {len(out)} ESX host ({self.host})")
            return out

        except Exception as e:
            logger.error(f"get_all_host_network_info error: {e}", exc_info=True)
            return {}

    # Folder → Datacenter → networkFolder → (Folder | DistributedVirtualPortgroup)
    _NETWORK_FOLDER_TRAVERSAL = """
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>visitFolders</vim25:name>
            <vim25:type>Folder</vim25:type>
            <vim25:path>childEntity</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>dcToNetF</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToNetF</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>networkFolder</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
          </vim25:selectSet>"""

    _ETH_CARD_TAGS = frozenset({
        "VirtualVmxnet3", "VirtualVmxnet", "VirtualE1000",
        "VirtualE1000e", "VirtualPCNet32", "VirtualSriovEthernetCard",
        "VirtualEthernetCard",
    })
    _ETH_XSI_EXACT = frozenset({
        "VirtualEthernetCard",
        "VirtualVmxnet3", "VirtualVmxnet2", "VirtualVmxnet",
        "VirtualE1000", "VirtualE1000e", "VirtualPCNet32",
        "VirtualSriovEthernetCard",
    })

    @staticmethod
    def _soap_xsi_type(el) -> str:
        for k, v in (el.attrib or {}).items():
            if k.endswith("type") or k == "type":
                return (v or "").split(":")[-1]
        return ""

    @classmethod
    def _is_ethernet_device(cls, el) -> bool:
        """SOAP'ta NIC çoğu zaman <VirtualDevice xsi:type=\"VirtualVmxnet3\"> gelir."""
        tag = el.tag.split("}")[-1]
        if tag in cls._ETH_CARD_TAGS:
            return True
        xt = cls._soap_xsi_type(el)
        return xt in cls._ETH_XSI_EXACT

    def get_dvs_portgroup_vlans(self) -> Dict[str, Dict[str, Any]]:
        """
        Distributed Virtual Port Group → VLAN haritası.
        Dönüş: {portgroup_key_or_name: {name, key, vlan_id, vlan_label}}
        Hem MoRef (dvportgroup-N) hem görünen ad ile bakılabilir.
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("get_dvs_portgroup_vlans: SOAP login failed")
            return {}

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
          <vim25:type>DistributedVirtualPortgroup</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>key</vim25:pathSet>
          <vim25:pathSet>config.defaultPortConfig.vlan</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Folder">{root_folder}</vim25:obj>
          <vim25:skip>false</vim25:skip>
          {self._NETWORK_FOLDER_TRAVERSAL}
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""

        def _tag(el):
            return el.tag.split("}")[-1]

        def _xsi_type(el) -> str:
            for k, v in (el.attrib or {}).items():
                if k.endswith("type") or k == "type":
                    return (v or "").split(":")[-1]
            return ""

        def _parse_vlan(vlan_el) -> tuple:
            """(vlan_id: Optional[int], vlan_label: str)"""
            if vlan_el is None:
                return None, ""
            xt = _xsi_type(vlan_el)
            if xt == "VmwareDistributedVirtualSwitchVlanIdSpec" or not xt:
                for c in vlan_el:
                    if _tag(c) == "vlanId" and (c.text or "").strip().isdigit():
                        vid = int(c.text.strip())
                        return vid, str(vid)
            if xt == "VmwareDistributedVirtualSwitchTrunkVlanSpec":
                ranges = []
                for c in vlan_el:
                    if _tag(c) != "vlanId":
                        continue
                    start = end = None
                    for sub in c:
                        st = _tag(sub)
                        if st == "start" and (sub.text or "").strip().isdigit():
                            start = int(sub.text.strip())
                        elif st == "end" and (sub.text or "").strip().isdigit():
                            end = int(sub.text.strip())
                    if start is not None and end is not None:
                        ranges.append(f"{start}-{end}" if start != end else str(start))
                    elif (c.text or "").strip().isdigit():
                        ranges.append(c.text.strip())
                label = ",".join(ranges) if ranges else "trunk"
                return None, f"trunk({label})"
            if xt == "VmwareDistributedVirtualSwitchPvlanSpec":
                for c in vlan_el:
                    if _tag(c) == "pvlanId" and (c.text or "").strip().isdigit():
                        vid = int(c.text.strip())
                        return vid, f"pvlan({vid})"
            return None, xt or "unknown"

        try:
            resp = soap_session.post(
                soap_url, data=soap_body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=60,
            )
            if resp.status_code != 200:
                # Bazı ortamlarda DVS tipi yok → InvalidType (standart vSwitch yeter)
                if "InvalidType" in (resp.text or "") or "DistributedVirtualPortgroup" in (resp.text or ""):
                    logger.info("get_dvs_portgroup_vlans: DVS tipi yok / desteklenmiyor (standart PG kullanılacak)")
                else:
                    logger.warning("get_dvs_portgroup_vlans HTTP %s: %s", resp.status_code, resp.text[:300])
                return {}

            root_xml = ET.fromstring(resp.text)
            out: Dict[str, Dict[str, Any]] = {}

            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                pg_key = (obj_el.text or "").strip() if obj_el is not None else ""
                name = ""
                key_prop = ""
                vlan_id = None
                vlan_label = ""

                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = (n_el.text or "").strip()
                    if pname == "name":
                        name = (v_el.text or "").strip()
                    elif pname == "key":
                        key_prop = (v_el.text or "").strip()
                    elif pname == "config.defaultPortConfig.vlan":
                        vlan_id, vlan_label = _parse_vlan(v_el)

                keys = [k for k in (pg_key, key_prop, name) if k]
                entry = {
                    "name": name or pg_key,
                    "key": key_prop or pg_key,
                    "vlan_id": vlan_id,
                    "vlan_label": vlan_label if vlan_label else (str(vlan_id) if vlan_id is not None else ""),
                }
                for k in keys:
                    out[k] = entry

            logger.info("get_dvs_portgroup_vlans: %s entries (%s)", len(out), self.host)
            return out
        except Exception as e:
            logger.error("get_dvs_portgroup_vlans error: %s", e, exc_info=True)
            return {}

    def get_all_vm_network_vlans(self) -> List[Dict[str, Any]]:
        """
        Tüm VM'lerin NIC → port-group → VLAN eşlemesini tek/ iki SOAP çağrısıyla döner
        (standart vSwitch + Distributed Switch).

        Dönüş satırları:
          {vm_ref, vm_name, nic, mac, portgroup, vlan_id, vlan_label, backing_type}
        """
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            logger.warning("get_all_vm_network_vlans: SOAP login failed")
            return []

        # Standart port-group adı → VLAN (host envanteri)
        std_vlan: Dict[str, Any] = {}
        try:
            for _href, info in (self.get_all_host_network_info() or {}).items():
                for pg in info.get("portgroups") or []:
                    pname = (pg.get("name") or "").strip()
                    if pname and pname not in std_vlan:
                        std_vlan[pname] = pg.get("vlan_id")
        except Exception as exc:
            logger.warning("get_all_vm_network_vlans: host PG map failed: %s", exc)

        dvs_map = {}
        try:
            dvs_map = self.get_dvs_portgroup_vlans() or {}
        except Exception as exc:
            logger.warning("get_all_vm_network_vlans: DVS map failed: %s", exc)

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
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>config.hardware.device</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="Folder">{root_folder}</vim25:obj>
          <vim25:skip>false</vim25:skip>
          {self._VM_TRAVERSAL}
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""

        def _tag(el):
            return el.tag.split("}")[-1]

        def _xsi_type(el) -> str:
            for k, v in (el.attrib or {}).items():
                if k.endswith("type") or k == "type":
                    return (v or "").split(":")[-1]
            return ""

        def _text_child(parent, name: str) -> str:
            for c in parent:
                if _tag(c) == name and (c.text or "").strip():
                    return c.text.strip()
            return ""

        rows: List[Dict[str, Any]] = []
        try:
            resp = soap_session.post(
                soap_url, data=soap_body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl, timeout=90,
            )
            if resp.status_code != 200:
                logger.warning("get_all_vm_network_vlans HTTP %s: %s", resp.status_code, resp.text[:300])
                return []

            root_xml = ET.fromstring(resp.text)
            for rv in root_xml.iter():
                if _tag(rv) != "returnval":
                    continue
                obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                vm_ref = (obj_el.text or "").strip() if obj_el is not None else ""
                vm_name = ""
                devices_el = None

                for ps in rv:
                    if _tag(ps) != "propSet":
                        continue
                    n_el = next((c for c in ps if _tag(c) == "name"), None)
                    v_el = next((c for c in ps if _tag(c) == "val"), None)
                    if n_el is None or v_el is None:
                        continue
                    pname = (n_el.text or "").strip()
                    if pname == "name":
                        vm_name = (v_el.text or "").strip()
                    elif pname == "config.hardware.device":
                        devices_el = v_el

                if devices_el is None:
                    continue

                for device in devices_el.iter():
                    if not self._is_ethernet_device(device):
                        continue
                    # Cihaz ağacında iç içe tekrar etmeyi önle: yalnızca xsi/tag eth kökü
                    # (Ethernet kartının çocuğunda eth tipi olmaz).
                    label = ""
                    mac = ""
                    backing = None
                    for child in device:
                        ct = _tag(child)
                        if ct == "macAddress":
                            mac = (child.text or "").strip()
                        elif ct == "deviceInfo":
                            for sub in child:
                                if _tag(sub) == "label":
                                    label = (sub.text or "").strip()
                        elif ct == "backing":
                            backing = child

                    portgroup = ""
                    backing_type = "unknown"
                    vlan_id = None
                    vlan_label = ""

                    if backing is not None:
                        bt = self._soap_xsi_type(backing)
                        if "DistributedVirtualPort" in bt:
                            backing_type = "distributed"
                            pg_key = ""
                            for c in backing:
                                if _tag(c) == "port":
                                    pg_key = _text_child(c, "portgroupKey")
                                    break
                            portgroup = pg_key
                            info = dvs_map.get(pg_key) or {}
                            if info:
                                portgroup = info.get("name") or pg_key
                                vlan_id = info.get("vlan_id")
                                vlan_label = info.get("vlan_label") or ""
                        elif "OpaqueNetwork" in bt:
                            backing_type = "opaque"
                            portgroup = _text_child(backing, "opaqueNetworkId") or _text_child(backing, "deviceName")
                        else:
                            # VirtualEthernetCardNetworkBackingInfo (standart vSwitch)
                            backing_type = "standard"
                            portgroup = _text_child(backing, "deviceName")
                            if portgroup in std_vlan:
                                vlan_id = std_vlan[portgroup]
                                # vlan_id bazen string gelir
                                try:
                                    vlan_id = int(vlan_id) if vlan_id is not None and str(vlan_id).strip() != "" else vlan_id
                                except (TypeError, ValueError):
                                    pass
                                vlan_label = str(vlan_id) if vlan_id is not None else ""

                    if vlan_id is not None and not vlan_label:
                        vlan_label = str(vlan_id)

                    rows.append({
                        "vm_ref": vm_ref,
                        "vm_name": vm_name or vm_ref or "unknown",
                        "nic": label or "NIC",
                        "mac": mac,
                        "portgroup": portgroup or "-",
                        "vlan_id": vlan_id,
                        "vlan_label": vlan_label or ("—" if vlan_id is None else str(vlan_id)),
                        "backing_type": backing_type,
                    })

            logger.info("get_all_vm_network_vlans: %s NIC satırı (%s)", len(rows), self.host)
            return rows
        except Exception as e:
            logger.error("get_all_vm_network_vlans error: %s", e, exc_info=True)
            return []

    # ── vCenter Event / Alarm / Task Toplama (SOAP EventManager) ───────────────

    def _soap_tag(self, el) -> str:
        return el.tag.split("}")[-1]

    def _soap_post(self, soap_session, soap_url: str, body: str, timeout: int = 60):
        import xml.etree.ElementTree as ET
        try:
            resp = soap_session.post(
                soap_url,
                data=body,
                headers={"Content-Type": "text/xml; charset=utf-8"},
                verify=self.verify_ssl,
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.warning("SOAP HTTP %s: %s", resp.status_code, resp.text[:300])
                return None
            return ET.fromstring(resp.text)
        except Exception as exc:
            logger.error("SOAP post error: %s", exc)
            return None

    def _get_service_content_refs(self, soap_session, soap_url: str) -> Dict[str, str]:
        """eventManager, alarmManager, rootFolder MOR referanslarını döner."""
        body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveServiceContent>
      <vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>
    </vim25:RetrieveServiceContent>
  </soapenv:Body>
</soapenv:Envelope>"""
        root = self._soap_post(soap_session, soap_url, body, timeout=15)
        refs: Dict[str, str] = {
            "eventManager": "eventManager",
            "alarmManager": "alarmManager",
            "rootFolder": "group-d1",
        }
        if root is None:
            return refs
        for el in root.iter():
            tag = self._soap_tag(el)
            if tag in refs and el.text:
                refs[tag] = el.text
        return refs

    @staticmethod
    def _map_vim_event_severity(event_type_id: str, message: str, extra: Dict) -> str:
        et = (event_type_id or "").lower()
        msg = (message or "").lower()
        blob = f"{et} {msg}"

        if extra.get("task_error"):
            return "critical"
        if extra.get("alarm_status") in ("red", "critical"):
            return "critical"
        if extra.get("alarm_status") in ("yellow", "warning"):
            return "warning"

        critical_kw = (
            "error", "failed", "failure", "fault", "lost", "cannot", "denied",
            "timeout", "corrupt", "invalid", "disconnected", "notresponding",
            "hostconnectionlost", "vmfailed", "alarmstatuschanged",
        )
        warning_kw = ("warning", "degraded", "queued", "pending", "reconfigured")

        if any(k in blob for k in critical_kw):
            if "warning" in blob and "error" not in blob and "failed" not in blob:
                return "warning"
            return "critical"
        if any(k in blob for k in warning_kw):
            return "warning"
        return "info"

    def _parse_event_argument(self, child) -> Dict[str, Optional[str]]:
        """VmEventArgument / HostEventArgument / ManagedEntityEventArgument veya düz MOR.

        Tipik SOAP:
          <vm><name>myvm</name><vm type="VirtualMachine">vm-123</vm></vm>
          <entity><name>myvm</name><entity type="VirtualMachine">vm-123</entity></entity>
          <host type="HostSystem">host-21</host>
        """
        result: Dict[str, Optional[str]] = {"type": None, "value": None, "name": None}
        direct_type = child.get("type")
        direct_text = (child.text or "").strip() if child.text else ""
        if direct_type and direct_text:
            result["type"] = direct_type
            result["value"] = direct_text

        for sub in list(child):
            st = self._soap_tag(sub)
            sub_text = (sub.text or "").strip() if sub.text else ""
            if st == "name" and sub_text:
                result["name"] = sub_text
            elif sub.get("type") and sub_text:
                result["type"] = sub.get("type")
                result["value"] = sub_text
            elif st in ("vm", "host", "entity", "computeResource", "datacenter", "ds", "net"):
                nested = self._parse_event_argument(sub)
                if nested.get("type"):
                    result["type"] = nested["type"]
                if nested.get("value"):
                    result["value"] = nested["value"]
                if nested.get("name") and not result.get("name"):
                    result["name"] = nested["name"]
        return result

    def _parse_vim_event_element(self, el) -> Optional[Dict]:
        """Tek bir SOAP Event returnval elementini normalize eder."""
        data: Dict[str, Any] = {}
        entity_arg: Dict[str, Optional[str]] = {}
        for child in el:
            tag = self._soap_tag(child)
            if tag in ("host", "vm", "computeResource", "datacenter", "ds", "net", "entity"):
                parsed = self._parse_event_argument(child)
                if tag == "entity":
                    entity_arg = parsed
                else:
                    data[tag] = parsed
            elif tag in ("key", "chainId", "createdTime", "userName", "fullFormattedMessage",
                         "message", "eventTypeId", "changeTag"):
                data[tag] = child.text or ""
            elif tag == "info" and self._soap_tag(child) == "TaskInfo":
                for sub in child:
                    st = self._soap_tag(sub)
                    if st == "error":
                        data["task_error"] = True
                    elif st == "state" and (sub.text or "").lower() == "error":
                        data["task_error"] = True
            elif tag in ("to", "from") and self._soap_tag(child) == "AlarmStatus":
                for sub in child:
                    if self._soap_tag(sub) == "overallStatus":
                        data["alarm_status"] = (sub.text or "").lower()

        event_key = data.get("key") or data.get("chainId")
        if not event_key:
            return None

        # xsi:type genelde gerçek event sınıfını taşır (örn. "UserLoginSessionEvent",
        # "TaskEvent", "AlarmStatusChangedEvent") — eventTypeId çoğu event tipinde boştur.
        xsi_type = el.get("{http://www.w3.org/2001/XMLSchema-instance}type") or ""
        event_type = data.get("eventTypeId") or xsi_type or self._soap_tag(el)
        title = (
            data.get("fullFormattedMessage")
            or data.get("message")
            or event_type
            or "vCenter event"
        )
        host_ref = (data.get("host") or {}).get("value")
        vm_ref = (data.get("vm") or {}).get("value")
        entity_name = (
            (data.get("vm") or {}).get("name")
            or (data.get("host") or {}).get("name")
            or entity_arg.get("name")
        )
        entity_type = entity_arg.get("type")
        entity_ref = entity_arg.get("value")

        # AlarmStatusChangedEvent: asıl hedef çoğu zaman 'entity' alanındadır
        if not vm_ref and entity_type == "VirtualMachine" and entity_ref:
            vm_ref = entity_ref
        if not host_ref and entity_type == "HostSystem" and entity_ref:
            host_ref = entity_ref

        severity = self._map_vim_event_severity(
            event_type,
            title,
            {"task_error": data.get("task_error"), "alarm_status": data.get("alarm_status")},
        )
        kind = "vcenter_task" if "task" in (event_type or "").lower() else "vcenter_event"
        if "alarm" in (event_type or "").lower():
            kind = "vcenter_alarm"

        return {
            "id": f"evt-{event_key}",
            "kind": kind,
            "severity": severity,
            "event_key": str(event_key),
            "chain_id": data.get("chainId"),
            "event_type_id": event_type,
            "title": title[:500],
            "user_name": data.get("userName"),
            "host_ref": host_ref,
            "vm_ref": vm_ref,
            "entity_type": entity_type,
            "entity_ref": entity_ref,
            "entity_name": entity_name,
            "timestamp": data.get("createdTime"),
            "change_tag": data.get("changeTag"),
        }

    def _get_vcenter_current_time(self, soap_session, soap_url: str):
        """
        ServiceInstance.CurrentTime() — vCenter'ın kendi saatini döner.

        Backend host saati ile vCenter saati arasında drift olabilir (örn. test/demo
        ortamlarında yıl farkı). Event zaman filtrelemesini vCenter'ın kendi saatine
        göre yapmak, tüm event'lerin yanlışlıkla "eski" sayılıp atlanmasını önler.
        """
        from datetime import datetime, timezone

        body = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:CurrentTime>
      <vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>
    </vim25:CurrentTime>
  </soapenv:Body>
</soapenv:Envelope>"""
        try:
            root = self._soap_post(soap_session, soap_url, body, timeout=15)
            if root is None:
                return None
            for el in root.iter():
                if self._soap_tag(el) == "returnval" and el.text:
                    return datetime.fromisoformat(el.text.replace("Z", "+00:00"))
        except Exception as exc:
            logger.warning("vCenter CurrentTime alınamadı: %s", exc)
        return None

    def _query_vim_events(self, soap_session, soap_url: str, event_manager: str,
                          hours: int = 48, max_events: int = 800,
                          event_type_ids: Optional[List[str]] = None,
                          max_pages: int = 6) -> List[Dict]:
        """
        EventManager.CreateCollectorForEvents + latestPage/GetPreviousPage ile event stream okur.

        Not: QueryEvents(filter.time.beginTime=...) bazı vCenter kurulumlarında
        (özellikle yoğun event DB'lerinde) boş dönebiliyor veya zaman aşımına
        uğruyor. Collector tabanlı yaklaşım VMware'in resmi önerdiği, güvenilir
        yöntemdir: filtresiz collector oluşturulur, sayfalar geriye doğru okunur
        ve `hours` sınırına client tarafında uygulanır.

        `event_type_ids` verilirse EventFilterSpec.type + EventFilterSpec.time.beginTime
        ile sunucu tarafında filtreleme yapılır (örn. sadece VM restart/create/remove
        event'leri) — bu, login/logout gürültüsü olmadan çok daha geniş bir zaman
        penceresini (7-30 gün) az sayfa ile taramayı mümkün kılar.
        NOT: EventFilterSpec alan sırası önemlidir (WSDL: entity, time, ..., eventTypeId).
        """
        from datetime import datetime, timezone, timedelta

        reference_now = self._get_vcenter_current_time(soap_session, soap_url) or datetime.now(timezone.utc)
        cutoff = reference_now - timedelta(hours=hours)
        page_size = min(max(max_events, 100), 1000)

        if event_type_ids:
            begin_time_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
            type_filter_xml = "".join(
                f"<vim25:eventTypeId>{t}</vim25:eventTypeId>" for t in event_type_ids
            )
            filter_xml = (
                "<vim25:filter>"
                f"<vim25:time><vim25:beginTime>{begin_time_str}</vim25:beginTime></vim25:time>"
                f"{type_filter_xml}"
                "</vim25:filter>"
            )
        else:
            filter_xml = "<vim25:filter></vim25:filter>"

        create_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:CreateCollectorForEvents>
      <vim25:_this type="EventManager">{event_manager}</vim25:_this>
      {filter_xml}
    </vim25:CreateCollectorForEvents>
  </soapenv:Body>
</soapenv:Envelope>"""
        root = self._soap_post(soap_session, soap_url, create_body, timeout=60)
        if root is None:
            return []

        collector_ref = None
        for el in root.iter():
            if self._soap_tag(el) == "returnval" and el.text:
                collector_ref = el.text
                break
        if not collector_ref:
            logger.warning("CreateCollectorForEvents: collector referansı alınamadı")
            return []

        try:
            page_size_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:SetCollectorPageSize>
      <vim25:_this type="EventHistoryCollector">{collector_ref}</vim25:_this>
      <vim25:maxCount>{page_size}</vim25:maxCount>
    </vim25:SetCollectorPageSize>
  </soapenv:Body>
</soapenv:Envelope>"""
            self._soap_post(soap_session, soap_url, page_size_body, timeout=20)

            events: List[Dict] = []
            stop = False

            for page_num in range(max_pages):
                if page_num == 0:
                    prop_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>EventHistoryCollector</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>latestPage</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="EventHistoryCollector">{collector_ref}</vim25:obj>
          <vim25:skip>false</vim25:skip>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
                    page_root = self._soap_post(soap_session, soap_url, prop_body, timeout=60)
                else:
                    prev_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:GetPreviousPage>
      <vim25:_this type="EventHistoryCollector">{collector_ref}</vim25:_this>
    </vim25:GetPreviousPage>
  </soapenv:Body>
</soapenv:Envelope>"""
                    page_root = self._soap_post(soap_session, soap_url, prev_body, timeout=60)

                if page_root is None:
                    break

                page_events: List[Dict] = []
                for el in page_root.iter():
                    tag = self._soap_tag(el)
                    if tag not in ("Event",) and "Event" not in tag:
                        continue
                    if tag == "propSet":
                        continue
                    parsed = self._parse_vim_event_element(el)
                    if parsed:
                        page_events.append(parsed)

                if not page_events:
                    break

                for ev in page_events:
                    ts = ev.get("timestamp")
                    if ts:
                        try:
                            ev_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if ev_dt < cutoff:
                                stop = True
                                continue
                        except Exception:
                            pass
                    events.append(ev)

                # Dönen sayfa istenen page_size'dan azsa collector'da başka sayfa
                # kalmamış demektir — GetPreviousPage'i gereksiz çağırmak bazı
                # vCenter sürümlerinde "Unable to resolve WSDL method" SOAP hatası
                # üretebiliyor (tükenmiş collector). Erken çıkış hem hatayı önler
                # hem de gereksiz round-trip'i engeller.
                if len(page_events) < page_size:
                    break

                if stop or len(events) >= max_events:
                    break

            events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
            return events[:max_events]
        finally:
            destroy_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:DestroyCollector>
      <vim25:_this type="EventHistoryCollector">{collector_ref}</vim25:_this>
    </vim25:DestroyCollector>
  </soapenv:Body>
</soapenv:Envelope>"""
            try:
                self._soap_post(soap_session, soap_url, destroy_body, timeout=10)
            except Exception:
                pass

    def _query_triggered_alarms(self, soap_session, soap_url: str,
                                alarm_manager: str, root_folder: str) -> List[Dict]:
        """AlarmManager.GetAlarmState — tetiklenmiş (red/yellow) alarmlar."""
        body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:GetAlarmState>
      <vim25:_this type="AlarmManager">{alarm_manager}</vim25:_this>
      <vim25:entity type="Folder">{root_folder}</vim25:entity>
    </vim25:GetAlarmState>
  </soapenv:Body>
</soapenv:Envelope>"""
        root = self._soap_post(soap_session, soap_url, body, timeout=60)
        if root is None:
            return []

        alarms: List[Dict] = []
        for el in root.iter():
            if self._soap_tag(el) != "returnval":
                continue
            entity_type = entity_val = alarm_val = status = time_val = None
            for child in el:
                tag = self._soap_tag(child)
                if tag == "entity":
                    entity_type = child.get("type")
                    entity_val = child.text
                elif tag == "alarm":
                    alarm_val = child.text
                elif tag == "overallStatus":
                    status = (child.text or "").lower()
                elif tag == "time":
                    time_val = child.text

            if status not in ("red", "yellow"):
                continue

            vm_ref = entity_val if entity_type == "VirtualMachine" else None
            host_ref = entity_val if entity_type == "HostSystem" else None
            alarms.append({
                "id": f"alarm-{alarm_val}-{entity_type}-{entity_val}",
                "kind": "vcenter_alarm",
                "severity": "critical" if status == "red" else "warning",
                "event_key": f"{alarm_val}:{entity_val}",
                "title": f"vCenter alarm ({status}): {entity_type}/{entity_val}",
                "alarm_ref": alarm_val,
                "entity_type": entity_type,
                "entity_ref": entity_val,
                "entity_name": None,
                "vm_ref": vm_ref,
                "host_ref": host_ref,
                "overall_status": status,
                "timestamp": time_val,
            })
        return alarms

    def collect_platform_logs(self, hours: int = 48, max_events: int = 800) -> Dict[str, Any]:
        """
        vCenter'dan event stream, tetiklenmiş alarmlar ve task hatalarını toplar.
        SOAP EventManager + AlarmManager kullanır (REST event API yok).
        """
        from datetime import datetime, timezone

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return {"events": [], "alarms": [], "errors": ["SOAP oturumu açılamadı"]}

        refs = self._get_service_content_refs(soap_session, soap_url)
        errors: List[str] = []

        events: List[Dict] = []
        try:
            events = self._query_vim_events(
                soap_session, soap_url, refs["eventManager"], hours=hours, max_events=max_events,
            )
        except Exception as exc:
            logger.error("QueryEvents error (%s): %s", self.host, exc, exc_info=True)
            errors.append(f"QueryEvents: {exc}")

        alarms: List[Dict] = []
        try:
            alarms = self._query_triggered_alarms(
                soap_session, soap_url, refs["alarmManager"], refs["rootFolder"],
            )
        except Exception as exc:
            logger.error("GetAlarmState error (%s): %s", self.host, exc, exc_info=True)
            errors.append(f"GetAlarmState: {exc}")

        task_events = [e for e in events if e.get("kind") == "vcenter_task"]
        logger.info(
            "vCenter %s: %d event, %d alarm, %d task-event",
            self.host, len(events), len(alarms), len(task_events),
        )
        return {
            "events": events,
            "alarms": alarms,
            "task_events": task_events,
            "errors": errors,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }

    def query_lifecycle_events(
        self,
        event_type_ids: List[str],
        days: int = 7,
        max_events: int = 3000,
        max_pages: int = 30,
    ) -> Dict[str, Any]:
        """
        Belirli event tiplerini (örn. VM restart/create/remove/migrate) geniş bir
        zaman penceresinde (gün bazlı) sorgular. `collect_platform_logs`'un aksine
        server-side type filtresi kullanır — login/logout gürültüsü olmadan 7-30
        günlük tarih aralığını az sayfa ile tarayabilir. Bağımsız login/logout
        döngüsü yürütür (VCenterClient zaten login/logout edilmiş olsa da tekrar
        SOAP oturumu açar — SOAP ve REST oturumları ayrıdır).
        """
        from datetime import datetime, timezone

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            return {"events": [], "errors": ["SOAP oturumu açılamadı"]}

        try:
            refs = self._get_service_content_refs(soap_session, soap_url)
            events = self._query_vim_events(
                soap_session, soap_url, refs["eventManager"],
                hours=days * 24, max_events=max_events,
                event_type_ids=event_type_ids, max_pages=max_pages,
            )
            return {
                "events": events,
                "errors": [],
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "reference_time": None,
            }
        except Exception as exc:
            logger.error("query_lifecycle_events error (%s): %s", self.host, exc, exc_info=True)
            return {"events": [], "errors": [str(exc)]}



    # ── MTV / Forklift kaynak envanteri ───────────────────────────────────────

    def get_datastores(self) -> List[Dict]:
        """Datastore listesi (moref + ad) — MTV StorageMap için."""
        out = []
        for d in self.list_datastores_status() or []:
            moref = d.get("ref") or d.get("moref")
            if not moref:
                continue
            out.append({
                "moref": moref,
                "name": d.get("name") or moref,
                "type": d.get("type"),
                "capacity_gb": d.get("capacity_gb"),
                "free_gb": d.get("free_gb"),
                "accessible": d.get("accessible"),
            })
        return out

    def get_networks(self) -> List[Dict]:
        """Standart + DV port group ağları (moref) — MTV NetworkMap için."""
        import xml.etree.ElementTree as ET

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            # REST fallback
            data = self._api_call("GET", "/vcenter/network") or []
            if isinstance(data, dict):
                data = data.get("value") or []
            return [{"moref": n.get("network"), "name": n.get("name"), "type": n.get("type")}
                    for n in data if n.get("network")]

        root_folder = self._get_root_folder(soap_session, soap_url)
        result: List[Dict] = []

        def _fetch(obj_type: str, paths: List[str], net_type: str):
            path_xml = "".join(f"<vim25:pathSet>{p}</vim25:pathSet>" for p in paths)
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:vim25="urn:vim25"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>{obj_type}</vim25:type>
          <vim25:all>false</vim25:all>
          {path_xml}
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
            <vim25:selectSet><vim25:name>dcToNet</vim25:name></vim25:selectSet>
            <vim25:selectSet><vim25:name>dcToNetFolder</vim25:name></vim25:selectSet>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToNet</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>network</vim25:path>
            <vim25:skip>false</vim25:skip>
          </vim25:selectSet>
          <vim25:selectSet xsi:type="vim25:TraversalSpec">
            <vim25:name>dcToNetFolder</vim25:name>
            <vim25:type>Datacenter</vim25:type>
            <vim25:path>networkFolder</vim25:path>
            <vim25:skip>false</vim25:skip>
            <vim25:selectSet><vim25:name>visitFolders</vim25:name></vim25:selectSet>
          </vim25:selectSet>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
            try:
                resp = soap_session.post(
                    soap_url, data=body,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    verify=self.verify_ssl, timeout=30,
                )
                if resp.status_code != 200:
                    return
                root = ET.fromstring(resp.text)

                def _tag(el):
                    return el.tag.split("}")[-1]

                for rv in root.iter():
                    if _tag(rv) != "returnval":
                        continue
                    obj_el = next((c for c in rv if _tag(c) == "obj"), None)
                    if obj_el is None or not (obj_el.text or "").strip():
                        continue
                    moref = obj_el.text.strip()
                    name = moref
                    for ps in rv:
                        if _tag(ps) != "propSet":
                            continue
                        n_el = next((c for c in ps if _tag(c) == "name"), None)
                        v_el = next((c for c in ps if _tag(c) == "val"), None)
                        if n_el is not None and (n_el.text or "") == "name" and v_el is not None:
                            name = (v_el.text or name).strip()
                    result.append({"moref": moref, "name": name, "type": net_type})
            except Exception as e:
                logger.warning("get_networks %s error: %s", obj_type, e)

        _fetch("Network", ["name"], "network")
        _fetch("DistributedVirtualPortgroup", ["name"], "dvportgroup")
        # de-dupe by moref
        seen = set()
        uniq = []
        for n in result:
            if n["moref"] in seen:
                continue
            seen.add(n["moref"])
            uniq.append(n)
        return uniq

    def get_vm_resource_refs(self, morefs: List[str]) -> Dict:
        """Seçili VM'lerin kullandığı datastore/ağ moref'leri (MTV eşleme)."""
        import xml.etree.ElementTree as ET

        wanted = set(morefs or [])
        if not wanted:
            return {"datastores": [], "networks": [], "per_vm": {}, "warnings": []}

        soap_url = f"https://{self.host}:{self.port}/sdk"
        soap_session = self._soap_login()
        if not soap_session:
            raise RuntimeError("vCenter SOAP oturumu açılamadı")

        ds_map: Dict[str, str] = {}
        net_map: Dict[str, str] = {}
        per_vm: Dict[str, Dict] = {}
        warnings: List[str] = []

        def _tag(el):
            return el.tag.split("}")[-1]

        for moid in wanted:
            body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>
    <vim25:RetrieveProperties>
      <vim25:_this type="PropertyCollector">propertyCollector</vim25:_this>
      <vim25:specSet>
        <vim25:propSet>
          <vim25:type>VirtualMachine</vim25:type>
          <vim25:all>false</vim25:all>
          <vim25:pathSet>name</vim25:pathSet>
          <vim25:pathSet>datastore</vim25:pathSet>
          <vim25:pathSet>network</vim25:pathSet>
          <vim25:pathSet>config.hardware.device</vim25:pathSet>
        </vim25:propSet>
        <vim25:objectSet>
          <vim25:obj type="VirtualMachine">{moid}</vim25:obj>
        </vim25:objectSet>
      </vim25:specSet>
    </vim25:RetrieveProperties>
  </soapenv:Body>
</soapenv:Envelope>"""
            try:
                resp = soap_session.post(
                    soap_url, data=body,
                    headers={"Content-Type": "text/xml; charset=utf-8"},
                    verify=self.verify_ssl, timeout=30,
                )
                if resp.status_code != 200:
                    warnings.append(f"{moid}: SOAP HTTP {resp.status_code}")
                    continue
                root = ET.fromstring(resp.text)
                vm_name = moid
                vm_ds: List[str] = []
                vm_net: List[str] = []
                nic_count = 0
                for rv in root.iter():
                    if _tag(rv) != "returnval":
                        continue
                    for ps in rv:
                        if _tag(ps) != "propSet":
                            continue
                        n_el = next((c for c in ps if _tag(c) == "name"), None)
                        v_el = next((c for c in ps if _tag(c) == "val"), None)
                        if n_el is None or v_el is None:
                            continue
                        pname = n_el.text or ""
                        if pname == "name" and v_el.text:
                            vm_name = v_el.text.strip()
                        elif pname == "datastore":
                            for child in v_el:
                                if _tag(child) in ("ManagedObjectReference", "Datastore") or child.get("type") == "Datastore":
                                    ref = (child.text or "").strip()
                                    if ref:
                                        ds_map.setdefault(ref, ref)
                                        vm_ds.append(ref)
                                # name may be sibling attribute
                                nm = child.get("name")
                                if nm and (child.text or "").strip():
                                    ds_map[child.text.strip()] = nm
                        elif pname == "network":
                            for child in v_el:
                                ref = (child.text or "").strip()
                                if ref:
                                    net_map.setdefault(ref, ref)
                                    vm_net.append(ref)
                        elif pname == "config.hardware.device":
                            for child in v_el:
                                t = child.get("{http://www.w3.org/2001/XMLSchema-instance}type") or child.get("type") or ""
                                local = _tag(child)
                                if "Ethernet" in t or "Ethernet" in local or "VirtualE1000" in t or "VirtualVmxnet" in t:
                                    nic_count += 1
                # Try to resolve datastore names via list
                per_vm[moid] = {
                    "name": vm_name,
                    "datastores": vm_ds,
                    "networks": vm_net,
                    "nic_count": nic_count,
                }
                if nic_count > len(set(vm_net)) and vm_net:
                    warnings.append(
                        f"'{vm_name}': {nic_count} NIC aynı ağa bağlı — Forklift reddedebilir; "
                        f"fazla NIC'i kaldırın veya farklı ağlara alın."
                    )
            except Exception as e:
                warnings.append(f"{moid}: {e}")

        # Enrich datastore/network names from inventory
        try:
            for d in self.get_datastores():
                if d["moref"] in ds_map:
                    ds_map[d["moref"]] = d["name"]
        except Exception:
            pass
        try:
            for n in self.get_networks():
                if n["moref"] in net_map:
                    net_map[n["moref"]] = n["name"]
        except Exception:
            pass

        return {
            "datastores": [{"moref": k, "name": v} for k, v in sorted(ds_map.items(), key=lambda x: x[1] or "")],
            "networks": [{"moref": k, "name": v} for k, v in sorted(net_map.items(), key=lambda x: x[1] or "")],
            "per_vm": per_vm,
            "warnings": warnings,
        }
