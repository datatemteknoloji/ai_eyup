"""
OpenShift Virtualization (KubeVirt) REST API Client

Kimlik doğrulama: API Server URL + Bearer Token (Service Account token).
Kubernetes/OpenShift API sunucusuna doğrudan REST çağrıları yapar — ek SDK
bağımlılığı gerektirmez (mevcut `requests` kütüphanesi ile).
"""
import logging
import time
from typing import Dict, List, Optional, Tuple

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)


class KubeVirtClient:
    """OpenShift Virtualization (KubeVirt) API client — VM envanteri + olay toplama.

    Kimlik doğrulama: Bearer Token DOĞRUDAN verilebilir, ya da `username`+`password`
    verilirse OpenShift OAuth sunucusundan (`oc login -u/-p` ile aynı akış) otomatik
    olarak bir token alınır.
    """

    def __init__(
        self,
        api_url: str,
        token: str = "",
        verify_ssl: bool = False,
        timeout: int = 20,
        username: str = "",
        password: str = "",
    ):
        self.api_url = (api_url or "").strip().rstrip("/")
        if self.api_url and not self.api_url.startswith("http"):
            self.api_url = f"https://{self.api_url}"
        self.username = username or ""
        self.password = password or ""
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.auth_error = ""
        self.token = token or ""

        if not self.token and self.username and self.password:
            self.token, self.auth_error = self._login_with_credentials()

        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _login_with_credentials(self) -> Tuple[str, str]:
        from app.services.openshift.oauth_helper import obtain_oauth_token
        token, error = obtain_oauth_token(
            self.api_url, self.username, self.password, verify_ssl=self.verify_ssl, timeout=self.timeout
        )
        return token or "", error

    def _get(self, path: str, params: Optional[dict] = None, timeout: Optional[int] = None):
        url = f"{self.api_url}{path}"
        return self.session.get(url, params=params, timeout=timeout or self.timeout)

    def test_connection(self) -> Tuple[bool, str]:
        """Bağlantıyı ve token yetkisini test et. Returns (success, detail_message)."""
        if not self.api_url:
            return False, "API Server URL gerekli"
        if not self.token:
            if self.auth_error:
                return False, self.auth_error
            return False, "Bearer Token veya kullanıcı adı/şifre gerekli"
        try:
            r = self._get("/version", timeout=15)
            if r.status_code == 200:
                return True, ""
            # /version bazı kısıtlı RBAC'larda kapalı olabilir — kubevirt CR'ları dene
            r2 = self._get("/apis/kubevirt.io/v1/virtualmachines", params={"limit": 1}, timeout=15)
            if r2.status_code == 200:
                return True, ""
            if r2.status_code == 401:
                return False, "401 Yetkisiz — Token geçersiz veya süresi dolmuş"
            if r2.status_code == 403:
                return False, "403 Erişim reddedildi — Token'ın kubevirt.io VM'lerini okuma yetkisi yok"
            if r2.status_code == 404:
                return False, "KubeVirt API bulunamadı (404) — OpenShift Virtualization operatörü kurulu mu?"
            return False, f"HTTP {r2.status_code}: {(r2.text or '')[:200]}"
        except requests.exceptions.SSLError:
            return False, "SSL hatası — Sertifika doğrulanamadı"
        except requests.exceptions.ConnectTimeout:
            return False, "Bağlantı zaman aşımı — API URL ve port erişilebilir mi?"
        except requests.exceptions.ConnectionError as e:
            logger.error(f"OpenShift Virtualization connection error: {e}")
            return False, "Bağlantı kurulamadı — API URL kontrol edin"
        except Exception as e:
            logger.error(f"OpenShift Virtualization connection test failed: {e}")
            return False, str(e)

    @staticmethod
    def _parse_quantity(val) -> float:
        """Kubernetes resource quantity string'ini (ör. '4', '8Gi', '500m') sayıya çevirir."""
        if val is None:
            return 0.0
        s = str(val).strip()
        if not s:
            return 0.0
        try:
            if s.endswith("Ki"):
                return float(s[:-2]) / (1024 ** 2)
            if s.endswith("Mi"):
                return float(s[:-2]) / 1024
            if s.endswith("Gi"):
                return float(s[:-2])
            if s.endswith("Ti"):
                return float(s[:-2]) * 1024
            if s.endswith("m"):  # milli-cores
                return float(s[:-1]) / 1000
            return float(s)
        except (TypeError, ValueError):
            return 0.0

    def list_vms(self) -> List[Dict]:
        """Tüm namespace'lerdeki VirtualMachine + VirtualMachineInstance kaynaklarını
        oVirt/VMware client'larıyla aynı sözlük şekline dönüştürerek döner."""
        try:
            vm_r = self._get("/apis/kubevirt.io/v1/virtualmachines", params={"limit": 500}, timeout=30)
            if vm_r.status_code != 200:
                logger.error(f"KubeVirt VM listesi hatası: {vm_r.status_code} - {vm_r.text[:200]}")
                return []
            vms = (vm_r.json() or {}).get("items", [])

            # VMI (VirtualMachineInstance) — çalışan VM'lerin canlı durumu (IP, node, guest OS)
            vmi_by_key: Dict[str, dict] = {}
            try:
                vmi_r = self._get("/apis/kubevirt.io/v1/virtualmachineinstances", params={"limit": 500}, timeout=30)
                if vmi_r.status_code == 200:
                    for vmi in (vmi_r.json() or {}).get("items", []):
                        meta = vmi.get("metadata", {})
                        key = f"{meta.get('namespace', '')}/{meta.get('name', '')}"
                        vmi_by_key[key] = vmi
            except Exception as exc:
                logger.debug(f"VMI listesi alınamadı: {exc}")

            inventory = []
            for vm in vms:
                meta = vm.get("metadata", {}) or {}
                namespace = meta.get("namespace", "")
                name = meta.get("name", "Unknown")
                uid = meta.get("uid", "")
                key = f"{namespace}/{name}"
                vmi = vmi_by_key.get(key) or {}

                spec = vm.get("spec", {}) or {}
                template_spec = ((spec.get("template") or {}).get("spec") or {})
                domain = template_spec.get("domain", {}) or {}
                resources = (domain.get("resources") or {}).get("requests", {}) or {}
                cpu_val = domain.get("cpu", {}).get("cores") if isinstance(domain.get("cpu"), dict) else None
                cpu_cores = int(cpu_val) if cpu_val else max(1, round(self._parse_quantity(resources.get("cpu", "1"))))
                memory_gb = round(self._parse_quantity(resources.get("memory", "0")), 1)

                vmi_status = vmi.get("status", {}) or {}
                phase = (vmi_status.get("phase") or vm.get("status", {}).get("printableStatus") or "Unknown")
                node_name = vmi_status.get("nodeName", "")

                ip_address = ""
                for iface in vmi_status.get("interfaces", []) or []:
                    if iface.get("ipAddress"):
                        ip_address = iface["ipAddress"]
                        break

                guest_os = ""
                guest_info = vmi_status.get("guestOSInfo") or {}
                if guest_info:
                    guest_os = guest_info.get("prettyName") or guest_info.get("name") or ""

                status = "ONLINE" if str(phase).lower() in ("running",) else "OFFLINE"

                inventory.append({
                    "name": name,
                    "ip_address": ip_address,
                    "hostname": name,
                    "os_type": guest_os,
                    "cpu_cores": cpu_cores,
                    "memory_gb": memory_gb,
                    "status": status,
                    "vm_id": uid or key,
                    "namespace": namespace,
                    "node_name": node_name,
                    "phase": phase,
                })

            logger.info(f"OpenShift Virtualization {self.api_url}: {len(inventory)} VM senkronize edildi")
            return inventory
        except Exception as e:
            logger.error(f"KubeVirt list_vms error: {e}", exc_info=True)
            return []

    def get_vm_full_details(self, vm_id: str, name: str = "") -> Optional[Dict]:
        """VM'in tüm detaylarını döner — vm_id burada '{namespace}/{name}' anahtarı olarak kullanılır."""
        try:
            namespace, vm_name = (vm_id.split("/", 1) + [""])[:2] if "/" in vm_id else ("", vm_id)
            vm_name = vm_name or name
            if not namespace or not vm_name:
                return None

            vm_r = self._get(f"/apis/kubevirt.io/v1/namespaces/{namespace}/virtualmachines/{vm_name}", timeout=15)
            if vm_r.status_code != 200:
                return None
            vm = vm_r.json()

            vmi_r = self._get(
                f"/apis/kubevirt.io/v1/namespaces/{namespace}/virtualmachineinstances/{vm_name}", timeout=15
            )
            vmi = vmi_r.json() if vmi_r.status_code == 200 else {}
            vmi_status = vmi.get("status", {}) or {}

            spec = vm.get("spec", {}) or {}
            template_spec = ((spec.get("template") or {}).get("spec") or {})
            domain = template_spec.get("domain", {}) or {}
            resources = (domain.get("resources") or {}).get("requests", {}) or {}

            disks = template_spec.get("volumes", []) or []
            disk_names = [d.get("name", "") for d in disks if d.get("name")]

            networks: list = []
            guest_ip = ""
            for iface in vmi_status.get("interfaces", []) or []:
                addr = iface.get("ipAddress", "")
                if addr and not guest_ip:
                    guest_ip = addr
                networks.append({
                    "name": iface.get("name", ""),
                    "mac": iface.get("mac", ""),
                    "ips": [{"address": addr, "version": "v4"}] if addr else [],
                })

            guest_info = vmi_status.get("guestOSInfo") or {}

            return {
                "vm_id": vm_id,
                "vm_name": vm_name,
                "vm_guest_hostname": vmi_status.get("guestOSInfo", {}).get("hostname") or vm_name,
                "vm_guest_ip": guest_ip,
                "vm_cpu_count": max(1, round(self._parse_quantity(resources.get("cpu", "1")))),
                "vm_memory_mb": int(self._parse_quantity(resources.get("memory", "0")) * 1024),
                "vm_disk_gb": 0,
                "vm_power_state": vmi_status.get("phase", "") or "",
                "vm_tools_status": guest_info.get("version", ""),
                "vm_network_info": networks,
                "vm_cluster": "OpenShift Virtualization",
                "vm_datastore": "",
                "vm_hardware_version": "",
                "os_type": guest_info.get("prettyName") or guest_info.get("name") or "",
                "disk_names": disk_names,
                "namespace": namespace,
                "node_name": vmi_status.get("nodeName", ""),
            }
        except Exception as e:
            logger.error(f"KubeVirt get_vm_full_details error: {e}", exc_info=True)
            return None

    def list_events(self, hours: int = 48) -> List[Dict]:
        """KubeVirt/Kubernetes Event API'sinden VM ile ilişkili olayları çeker.

        Node NotReady, VMI CrashLoop, migration hataları gibi Warning/Normal
        tipteki olayları normalize edilmiş sözlük listesi olarak döner.
        """
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events: List[Dict] = []
        try:
            r = self._get("/api/v1/events", params={"limit": 500}, timeout=30)
            if r.status_code != 200:
                logger.warning(f"KubeVirt event listesi alınamadı: {r.status_code}")
                return []
            items = (r.json() or {}).get("items", [])
            for ev in items:
                involved = ev.get("involvedObject", {}) or {}
                kind = involved.get("kind", "")
                if kind not in ("VirtualMachine", "VirtualMachineInstance", "Node", "DataVolume"):
                    continue
                last_ts_raw = ev.get("lastTimestamp") or ev.get("eventTime") or (ev.get("metadata") or {}).get("creationTimestamp")
                try:
                    last_ts = datetime.strptime(last_ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if last_ts_raw else None
                except Exception:
                    last_ts = None
                if last_ts and last_ts < cutoff:
                    continue

                event_type = ev.get("type", "Normal")
                reason = ev.get("reason", "")
                message = ev.get("message", "")
                severity = "critical" if event_type == "Warning" and reason in (
                    "Unhealthy", "FailedScheduling", "SyncFailed", "VMICrashLoop", "NodeNotReady",
                ) else ("warning" if event_type == "Warning" else "info")

                events.append({
                    "title": f"{kind}/{involved.get('name', '')}: {reason}",
                    "description": message,
                    "severity": severity,
                    "source_object": f"{kind}/{involved.get('name', '')}",
                    "namespace": involved.get("namespace", ""),
                    "timestamp": last_ts.isoformat() if last_ts else None,
                    "reason": reason,
                })
        except Exception as e:
            logger.error(f"KubeVirt list_events error: {e}", exc_info=True)
        return events

    def logout(self):
        """Uyum için no-op — token tabanlı oturumlar sunucu tarafında kapatılmaz."""
        try:
            self.session.close()
        except Exception:
            pass
