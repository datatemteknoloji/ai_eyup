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
        try:
            from app.services.host_resolve import rewrite_url_host
            rewritten, note, orig = rewrite_url_host(self.api_url)
            if rewritten and rewritten != self.api_url:
                logger.info("KubeVirt API host resolve: %s", note)
                self.api_url = rewritten
                self._tls_server_hostname = orig
            else:
                self._tls_server_hostname = None
        except Exception as e:
            logger.debug("KubeVirt host resolve skip: %s", e)
            self._tls_server_hostname = None

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
        if getattr(self, "_tls_server_hostname", None):
            self.session.headers["Host"] = self._tls_server_hostname

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
        """Kubernetes resource quantity → GiB (bellek/disk) veya core (cpu m/n).

        Suffix'siz büyük sayılar (ör. PVC capacity `34144990004`) byte kabul edilir.
        """
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
            n = float(s)
            # Suffix yok: CPU core (<1000) veya storage byte (>= 1Mi ham)
            if n >= 1024 * 1024:
                return n / (1024 ** 3)
            return n
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _vmi_primary_ip(vmi_status: dict) -> str:
        """VMI status.interfaces → tercih edilen IPv4 (ipAddress veya ipAddresses[])."""
        def _ok(addr: str) -> bool:
            a = (addr or "").strip()
            if not a or ":" in a:  # IPv6 atla (liste sade kalsın)
                return False
            if a.startswith("127.") or a.startswith("169.254."):
                return False
            return True

        candidates: list[str] = []
        for iface in (vmi_status or {}).get("interfaces") or []:
            if not isinstance(iface, dict):
                continue
            one = iface.get("ipAddress") or ""
            if _ok(one):
                candidates.append(one.strip())
            for raw in iface.get("ipAddresses") or []:
                if isinstance(raw, str) and _ok(raw):
                    candidates.append(raw.strip())
                elif isinstance(raw, dict):
                    ip = raw.get("ip") or raw.get("address") or ""
                    if _ok(ip):
                        candidates.append(ip.strip())
        # Pod network genelde 10.x; ilk geçerli yeterli
        return candidates[0] if candidates else ""

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
                mem_raw = resources.get("memory") or (domain.get("memory") or {}).get("guest")
                memory_gb = round(self._parse_quantity(mem_raw), 1) if mem_raw else 0.0

                vmi_status = vmi.get("status", {}) or {}
                phase = (vmi_status.get("phase") or vm.get("status", {}).get("printableStatus") or "Unknown")
                node_name = vmi_status.get("nodeName", "")

                ip_address = self._vmi_primary_ip(vmi_status)

                guest_os = ""
                guest_info = vmi_status.get("guestOSInfo") or {}
                if guest_info:
                    guest_os = guest_info.get("prettyName") or guest_info.get("name") or ""

                status = "ONLINE" if str(phase).lower() in ("running",) else "OFFLINE"
                printable = (vm.get("status") or {}).get("printableStatus") or phase
                # Atlas uyumlu alanlar (power_state / cpu_count / memory_mb)
                power_state = "poweredOn" if str(phase).lower() == "running" else "poweredOff"
                memory_mb = int(round(memory_gb * 1024)) if memory_gb else 0

                inventory.append({
                    "name": name,
                    "ip_address": ip_address,
                    "hostname": (guest_info.get("hostname") if guest_info else None) or name,
                    "os_type": guest_os,
                    "guest_os": guest_os,
                    "cpu_cores": cpu_cores,
                    "cpu_count": cpu_cores,
                    "memory_gb": memory_gb,
                    "memory_mb": memory_mb,
                    "status": status,
                    "power_state": power_state,
                    "vm_id": uid or key,
                    "moref": key,
                    "namespace": namespace,
                    "node_name": node_name,
                    "node": node_name,
                    "host": node_name,
                    "phase": phase,
                    "printable_status": printable,
                    "usage": None,
                })

            # Canlı kullanım — tek toplu metrics çağrısı (virt-launcher pod'ları)
            usage_by_vm: Dict[str, dict] = {}
            try:
                m_r = self._get("/apis/metrics.k8s.io/v1beta1/pods", params={"limit": "5000"}, timeout=20)
                if m_r.status_code == 200:
                    for m in (m_r.json() or {}).get("items") or []:
                        md = m.get("metadata") or {}
                        pod_name = md.get("name") or ""
                        pod_ns = md.get("namespace") or ""
                        if not pod_name.startswith("virt-launcher-"):
                            continue
                        # virt-launcher-<vm>-<hash>
                        vm_name = pod_name[len("virt-launcher-"):].rsplit("-", 1)[0]
                        conts = m.get("containers") or []
                        cpu_m = 0
                        mem_mb = 0
                        for x in conts:
                            u = (x.get("usage") or {})
                            cpu_raw = u.get("cpu") or "0"
                            # "123n" / "45m" / "1"
                            try:
                                s = str(cpu_raw)
                                if s.endswith("n"):
                                    cpu_m += max(0, int(int(s[:-1]) / 1_000_000))
                                elif s.endswith("u"):
                                    cpu_m += max(0, int(int(s[:-1]) / 1000))
                                elif s.endswith("m"):
                                    cpu_m += int(s[:-1] or 0)
                                else:
                                    cpu_m += int(float(s) * 1000)
                            except Exception:
                                pass
                            mem_raw = u.get("memory")
                            if mem_raw:
                                # bytes-ish → MiB via existing helper (GiB scale) * 1024
                                try:
                                    mem_mb += int(round(self._parse_quantity(mem_raw) * 1024))
                                except Exception:
                                    pass
                        usage_by_vm[f"{pod_ns}/{vm_name}"] = {
                            "cpu_millicores": cpu_m,
                            "memory_mb": mem_mb,
                        }
            except Exception as exc:
                logger.debug("KubeVirt metrics skip: %s", exc)

            for row in inventory:
                u = usage_by_vm.get(row["moref"])
                if u:
                    row["usage"] = u

            logger.info(f"OpenShift Virtualization {self.api_url}: {len(inventory)} VM senkronize edildi")
            return inventory
        except Exception as e:
            logger.error(f"KubeVirt list_vms error: {e}", exc_info=True)
            return []

    def _lookup_pvc(self, namespace: str, claim_name: str) -> Optional[Dict]:
        """PVC özeti + bağlı PV adı."""
        if not namespace or not claim_name:
            return None
        try:
            r = self._get(f"/api/v1/namespaces/{namespace}/persistentvolumeclaims/{claim_name}", timeout=10)
            if r.status_code != 200:
                return {"name": claim_name, "namespace": namespace, "error": f"HTTP {r.status_code}"}
            pvc = r.json() or {}
            meta = pvc.get("metadata") or {}
            spec = pvc.get("spec") or {}
            status = pvc.get("status") or {}
            cap = (status.get("capacity") or {}).get("storage") or (spec.get("resources") or {}).get("requests", {}).get("storage")
            return {
                "name": meta.get("name") or claim_name,
                "namespace": meta.get("namespace") or namespace,
                "phase": status.get("phase") or "",
                "storage_class": spec.get("storageClassName") or "",
                "access_modes": spec.get("accessModes") or [],
                "capacity_gb": round(self._parse_quantity(cap), 2) if cap else None,
                "volume_name": spec.get("volumeName") or status.get("volumeName") or "",
            }
        except Exception as exc:
            logger.debug("PVC lookup %s/%s: %s", namespace, claim_name, exc)
            return {"name": claim_name, "namespace": namespace, "error": str(exc)[:120]}

    def _lookup_pv(self, pv_name: str) -> Optional[Dict]:
        if not pv_name:
            return None
        try:
            r = self._get(f"/api/v1/persistentvolumes/{pv_name}", timeout=10)
            if r.status_code != 200:
                return {"name": pv_name, "error": f"HTTP {r.status_code}"}
            pv = r.json() or {}
            meta = pv.get("metadata") or {}
            spec = pv.get("spec") or {}
            status = pv.get("status") or {}
            claim_ref = spec.get("claimRef") or {}
            cap = (spec.get("capacity") or {}).get("storage")
            return {
                "name": meta.get("name") or pv_name,
                "phase": status.get("phase") or "",
                "storage_class": spec.get("storageClassName") or "",
                "reclaim": spec.get("persistentVolumeReclaimPolicy") or "",
                "access_modes": spec.get("accessModes") or [],
                "capacity_gb": round(self._parse_quantity(cap), 2) if cap else None,
                "claim": f"{claim_ref.get('namespace', '')}/{claim_ref.get('name', '')}".strip("/") or None,
            }
        except Exception as exc:
            logger.debug("PV lookup %s: %s", pv_name, exc)
            return {"name": pv_name, "error": str(exc)[:120]}

    def get_vm_full_details(self, vm_id: str, name: str = "") -> Optional[Dict]:
        """VM detayı — proje, worker node, disk→PVC→PV, NIC, guest OS, launcher pod."""
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
            cpu_val = domain.get("cpu", {}).get("cores") if isinstance(domain.get("cpu"), dict) else None
            cpu_cores = int(cpu_val) if cpu_val else max(1, round(self._parse_quantity(resources.get("cpu", "1"))))
            mem_raw = resources.get("memory") or (domain.get("memory") or {}).get("guest")
            memory_gb = round(self._parse_quantity(mem_raw), 2) if mem_raw else 0.0
            memory_mb = int(memory_gb * 1024)

            # domain.devices.disks → bus; volumes → PVC / DataVolume / containerDisk
            disk_meta = {}
            for d in ((domain.get("devices") or {}).get("disks") or []):
                if d.get("name"):
                    disk_meta[d["name"]] = {
                        "bus": ((d.get("disk") or d.get("cdrom") or d.get("lun") or {}).get("bus")) or "",
                        "boot_order": d.get("bootOrder"),
                    }

            disks_out: List[Dict] = []
            disk_names: List[str] = []
            total_disk_gb = 0.0
            for vol in (template_spec.get("volumes") or []):
                vname = vol.get("name") or ""
                if not vname:
                    continue
                disk_names.append(vname)
                entry: Dict = {
                    "name": vname,
                    "bus": (disk_meta.get(vname) or {}).get("bus") or "",
                    "boot_order": (disk_meta.get(vname) or {}).get("boot_order"),
                    "source": None,
                    "claim": None,
                    "pvc": None,
                    "pv": None,
                    "size_gb": None,
                }
                if vol.get("persistentVolumeClaim"):
                    claim = (vol["persistentVolumeClaim"] or {}).get("claimName") or ""
                    entry["source"] = "persistentVolumeClaim"
                    entry["claim"] = claim
                    pvc = self._lookup_pvc(namespace, claim)
                    entry["pvc"] = pvc
                    if pvc and pvc.get("volume_name"):
                        entry["pv"] = self._lookup_pv(pvc["volume_name"])
                    if pvc and pvc.get("capacity_gb") is not None:
                        entry["size_gb"] = pvc["capacity_gb"]
                        total_disk_gb += float(pvc["capacity_gb"] or 0)
                elif vol.get("dataVolume"):
                    dv_name = (vol["dataVolume"] or {}).get("name") or ""
                    entry["source"] = "dataVolume"
                    entry["claim"] = dv_name
                    # CDI DataVolume genelde aynı adlı PVC oluşturur
                    pvc = self._lookup_pvc(namespace, dv_name)
                    entry["pvc"] = pvc
                    if pvc and pvc.get("volume_name"):
                        entry["pv"] = self._lookup_pv(pvc["volume_name"])
                    if pvc and pvc.get("capacity_gb") is not None:
                        entry["size_gb"] = pvc["capacity_gb"]
                        total_disk_gb += float(pvc["capacity_gb"] or 0)
                elif vol.get("containerDisk"):
                    entry["source"] = "containerDisk"
                    entry["image"] = (vol["containerDisk"] or {}).get("image") or ""
                elif vol.get("cloudInitNoCloud") or vol.get("cloudInitConfigDrive"):
                    entry["source"] = "cloudInit"
                else:
                    entry["source"] = next(iter(k for k in vol.keys() if k != "name"), "unknown")
                disks_out.append(entry)

            # NIC: template networks + canlı VMI interfaces
            net_spec = {n.get("name"): n for n in (template_spec.get("networks") or []) if n.get("name")}
            networks: list = []
            guest_ip = self._vmi_primary_ip(vmi_status)
            for iface in vmi_status.get("interfaces") or []:
                addrs = []
                if iface.get("ipAddress"):
                    addrs.append(iface["ipAddress"])
                for raw in iface.get("ipAddresses") or []:
                    if isinstance(raw, str):
                        addrs.append(raw)
                    elif isinstance(raw, dict):
                        addrs.append(raw.get("ip") or raw.get("address") or "")
                addrs = [a for a in addrs if a]
                addr = next((a for a in addrs if ":" not in a), addrs[0] if addrs else "")
                nname = iface.get("name", "")
                nspec = net_spec.get(nname) or {}
                binding = "pod" if nspec.get("pod") is not None else ("multus" if nspec.get("multus") else "")
                networks.append({
                    "name": nname,
                    "mac": iface.get("mac", ""),
                    "ip_address": addr,
                    "binding": binding,
                    "model": iface.get("interfaceName") or "",
                    "ips": [{"address": a, "version": "v6" if ":" in a else "v4"} for a in addrs],
                })
            if not networks:
                for nname, nspec in net_spec.items():
                    binding = "pod" if nspec.get("pod") is not None else ("multus" if nspec.get("multus") else "")
                    networks.append({
                        "name": nname, "mac": "", "ip_address": "", "binding": binding,
                        "model": "", "ips": [],
                    })

            guest_info = vmi_status.get("guestOSInfo") or {}
            phase = vmi_status.get("phase") or (vm.get("status") or {}).get("printableStatus") or ""
            machine_type = (domain.get("machine") or {}).get("type") or ""

            # ── Zengin spec alanları (scheduling / CPU-bellek yerleşimi / firmware) ──
            meta_full = vm.get("metadata") or {}
            annotations = meta_full.get("annotations") or {}
            run_strategy = spec.get("runStrategy") or (
                "Always" if spec.get("running") else "Halted" if "running" in spec else ""
            )
            cpu_spec = domain.get("cpu") or {}
            mem_spec = domain.get("memory") or {}
            firmware = domain.get("firmware") or {}
            architecture = template_spec.get("architecture") or ""

            launcher = ""
            try:
                pods_r = self._get(
                    f"/api/v1/namespaces/{namespace}/pods",
                    params={"labelSelector": f"kubevirt.io/domain={vm_name}"},
                    timeout=10,
                )
                if pods_r.status_code == 200:
                    for p in (pods_r.json() or {}).get("items") or []:
                        pname = (p.get("metadata") or {}).get("name") or ""
                        if "virt-launcher" in pname:
                            launcher = pname
                            break
            except Exception:
                pass

            runnable = bool(spec.get("running")) if "running" in spec else None
            if runnable is None:
                runnable = str((vm.get("status") or {}).get("printableStatus") or "").lower() in (
                    "running", "starting", "migrating",
                )

            return {
                # Virt inventory uyumu
                "vm_id": f"{namespace}/{vm_name}",
                "vm_name": vm_name,
                "vm_guest_hostname": guest_info.get("hostname") or vm_name,
                "vm_guest_ip": guest_ip,
                "vm_cpu_count": cpu_cores,
                "vm_memory_mb": memory_mb,
                "vm_disk_gb": round(total_disk_gb, 2),
                "vm_power_state": phase,
                "vm_tools_status": guest_info.get("version", ""),
                "vm_network_info": networks,
                "vm_cluster": "OpenShift Virtualization",
                "vm_datastore": "",
                "vm_hardware_version": machine_type,
                "os_type": guest_info.get("prettyName") or guest_info.get("name") or "",
                "disk_names": disk_names,
                "namespace": namespace,
                "node_name": vmi_status.get("nodeName", ""),
                # OpenShift AIOPS zengin alanlar
                "name": vm_name,
                "phase": phase,
                "runnable": runnable,
                "cpu_cores": cpu_cores,
                "memory_gb": memory_gb,
                "memory_mb": memory_mb,
                "ip_address": guest_ip,
                "guest_os": guest_info.get("prettyName") or guest_info.get("name") or "",
                "hostname": guest_info.get("hostname") or vm_name,
                "machine_type": machine_type,
                "launcher_pod": launcher,
                "disks": disks_out,
                "nics": networks,
                "created": (vm.get("metadata") or {}).get("creationTimestamp"),
                "labels": (vm.get("metadata") or {}).get("labels") or {},
                # ── Ek zengin alanlar (scheduling / yerleşim / firmware / yaşam döngüsü) ──
                "uid": meta_full.get("uid") or "",
                "annotations": annotations,
                "owner_references": meta_full.get("ownerReferences") or [],
                "run_strategy": run_strategy,
                "architecture": architecture,
                "firmware": {
                    "uuid": firmware.get("uuid") or "",
                    "bootloader": firmware.get("bootloader") or {},
                    "serial": firmware.get("serial") or "",
                },
                "node_selector": template_spec.get("nodeSelector") or {},
                "affinity": template_spec.get("affinity") or {},
                "tolerations": template_spec.get("tolerations") or [],
                "eviction_strategy": template_spec.get("evictionStrategy") or spec.get("evictionStrategy") or "",
                "dedicated_cpu_placement": bool(cpu_spec.get("dedicatedCpuPlacement")),
                "cpu_numa": cpu_spec.get("numa") or {},
                "cpu_model": cpu_spec.get("model") or "",
                "cpu_sockets": cpu_spec.get("sockets"),
                "cpu_threads": cpu_spec.get("threads"),
                "hugepages": (mem_spec.get("hugepages") or {}).get("pageSize") or "",
                "boot_order": [
                    {"name": d.get("name"), "boot_order": d.get("boot_order")}
                    for d in disks_out if d.get("boot_order")
                ],
                "vmi_conditions": vmi_status.get("conditions") or [],
                "qemu_libvirt_note": (
                    "KubeVirt API QEMU/libvirt domain durumunu doğrudan sunmaz "
                    "(virt-launcher pod içindeki libvirtd internal state'idir)."
                ),
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
