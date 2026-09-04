"""
OpenShift Container Platform REST API Client

Kimlik doğrulama: API Server URL + Bearer Token (Service Account token).
Kubernetes/OpenShift API sunucusuna doğrudan REST çağrıları yapar.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)

# OpenShift'in kendi sistem/altyapı projeleri — envanterde gösterilecek "iş" projelerinden ayrı sayılır
_SYSTEM_NAMESPACE_PREFIXES = ("openshift", "kube-", "default")


class OpenShiftClient:
    """OpenShift Container Platform API client — node/proje/pod/deployment/route envanteri + olay toplama.

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
        # Dinamik çözümleme: DNS → host /etc/hosts (compose extra_hosts yok)
        self._tls_server_hostname: Optional[str] = None
        try:
            from app.services.host_resolve import rewrite_url_host
            rewritten, note, orig_host = rewrite_url_host(self.api_url)
            if rewritten and rewritten != self.api_url:
                logger.info("OpenShift API host resolve: %s", note)
                self.api_url = rewritten
                self._tls_server_hostname = orig_host
            elif note:
                logger.debug("OpenShift API host resolve: %s", note)
        except Exception as e:
            logger.warning("OpenShift API host resolve atlandı: %s", e)

        self.username = username or ""
        self.password = password or ""
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.auth_error = ""
        # Son list_*/get_* çağrısındaki HTTP/bağlantı hatası — boş `[]` sonucu ile
        # "gerçekten boş" durumunu ayırt etmek için. Her çağrının başında temizlenir,
        # hata olursa doldurulur. Çağıran kod (agent/tools.py handler'ları) bunu
        # kontrol ederek "0 node/pod" yerine açık hata döndürebilir.
        self.last_error: str = ""
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
        # IP'ye yazıldıysa sanal host / yönlendirici için orijinal ad
        if self._tls_server_hostname:
            self.session.headers["Host"] = self._tls_server_hostname

    def _login_with_credentials(self) -> Tuple[str, str]:
        from app.services.openshift.oauth_helper import obtain_oauth_token
        token, error = obtain_oauth_token(
            self.api_url, self.username, self.password, verify_ssl=self.verify_ssl, timeout=self.timeout
        )
        return token or "", error

    def _get(self, path: str, params: Optional[dict] = None, timeout: Optional[int] = None):
        return self.session.get(f"{self.api_url}{path}", params=params, timeout=timeout or self.timeout)

    def _patch(
        self,
        path: str,
        body: dict,
        *,
        content_type: str = "application/strategic-merge-patch+json",
        timeout: Optional[int] = None,
    ):
        headers = {**self.session.headers, "Content-Type": content_type}
        return self.session.patch(
            f"{self.api_url}{path}",
            json=body,
            headers=headers,
            timeout=timeout or self.timeout,
        )

    def _post(self, path: str, body: Optional[dict] = None, timeout: Optional[int] = None):
        return self.session.post(
            f"{self.api_url}{path}",
            json=body if body is not None else {},
            timeout=timeout or self.timeout,
        )

    def _delete(self, path: str, timeout: Optional[int] = None):
        return self.session.delete(f"{self.api_url}{path}", timeout=timeout or self.timeout)

    def test_connection(self) -> Tuple[bool, str]:
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
            r2 = self._get("/api/v1/namespaces", params={"limit": 1}, timeout=15)
            if r2.status_code == 200:
                return True, ""
            if r2.status_code == 401:
                return False, "401 Yetkisiz — Token geçersiz veya süresi dolmuş"
            if r2.status_code == 403:
                return False, "403 Erişim reddedildi — Token'ın küme kaynaklarını okuma yetkisi yok"
            return False, f"HTTP {r2.status_code}: {(r2.text or '')[:200]}"
        except requests.exceptions.SSLError:
            return False, "SSL hatası — Sertifika doğrulanamadı"
        except requests.exceptions.ConnectTimeout:
            return False, "Bağlantı zaman aşımı — API URL ve port erişilebilir mi?"
        except requests.exceptions.ConnectionError as e:
            logger.error(f"OpenShift connection error: {e}")
            return False, "Bağlantı kurulamadı — API URL kontrol edin"
        except Exception as e:
            logger.error(f"OpenShift connection test failed: {e}")
            return False, str(e)

    @staticmethod
    def _describe_http_error(r) -> str:
        """HTTP durum koduna göre insan-okunur hata metni (401/403 için özel)."""
        if r.status_code == 401:
            return "401 Yetkisiz — Token geçersiz veya süresi dolmuş"
        if r.status_code == 403:
            return "403 Erişim reddedildi — Token'ın küme kaynaklarını okuma yetkisi yok"
        return f"HTTP {r.status_code}: {(r.text or '')[:200]}"

    def get_version(self) -> str:
        try:
            r = self._get("/version/openshift", timeout=10)
            if r.status_code == 200:
                return (r.json() or {}).get("gitVersion", "")
            r2 = self._get("/version", timeout=10)
            if r2.status_code == 200:
                return (r2.json() or {}).get("gitVersion", "")
        except Exception:
            pass
        return ""

    @staticmethod
    def _parse_quantity(val) -> float:
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
            if s.endswith("n"):  # nanocores
                return float(s[:-1]) / 1_000_000_000
            if s.endswith("m"):  # millicores
                return float(s[:-1]) / 1000
            n = float(s)
            # Suffix yok + büyük sayı → byte (PVC/PV capacity)
            if n >= 1024 * 1024:
                return n / (1024 ** 3)
            return n
        except (TypeError, ValueError):
            return 0.0

    def list_nodes(self) -> List[Dict]:
        """Cluster node'larını (master/worker/infra) döner."""
        self.last_error = ""
        try:
            r = self._get("/api/v1/nodes", params={"limit": 500}, timeout=30)
            if r.status_code != 200:
                self.last_error = self._describe_http_error(r)
                logger.error(f"OpenShift node listesi hatası: {r.status_code} - {r.text[:200]}")
                return []
            nodes = []
            for n in (r.json() or {}).get("items", []):
                meta = n.get("metadata", {}) or {}
                labels = meta.get("labels", {}) or {}
                name = meta.get("name", "")

                role = "worker"
                if any(k.startswith("node-role.kubernetes.io/master") or k.startswith("node-role.kubernetes.io/control-plane") for k in labels):
                    role = "master"
                elif any(k.startswith("node-role.kubernetes.io/infra") for k in labels):
                    role = "infra"

                status_obj = n.get("status", {}) or {}
                conditions = status_obj.get("conditions", []) or []
                ready = next((c for c in conditions if c.get("type") == "Ready"), None)
                node_status = "Ready" if ready and ready.get("status") == "True" else "NotReady"

                capacity = status_obj.get("capacity", {}) or {}
                allocatable = status_obj.get("allocatable", {}) or {}
                node_info = status_obj.get("nodeInfo", {}) or {}
                cpu_cap = self._parse_quantity(capacity.get("cpu"))
                mem_cap = round(self._parse_quantity(capacity.get("memory")), 2)
                cpu_alloc = self._parse_quantity(allocatable.get("cpu")) or cpu_cap
                mem_alloc = round(self._parse_quantity(allocatable.get("memory")), 2) or mem_cap

                internal_ip = ""
                external_ip = ""
                hostname = name
                for addr in status_obj.get("addresses") or []:
                    if not isinstance(addr, dict):
                        continue
                    t, v = addr.get("type"), (addr.get("address") or "").strip()
                    if not v:
                        continue
                    if t == "InternalIP" and not internal_ip:
                        internal_ip = v
                    elif t == "ExternalIP" and not external_ip:
                        external_ip = v
                    elif t == "Hostname" and v:
                        hostname = v

                nodes.append({
                    "name": name,
                    "role": role,
                    "status": node_status,
                    "cpu_cores": cpu_cap,
                    "memory_gb": mem_cap,
                    "cpu_allocatable": cpu_alloc,
                    "memory_allocatable_gb": mem_alloc,
                    "kubelet_version": node_info.get("kubeletVersion", ""),
                    "os_image": node_info.get("osImage", ""),
                    "internal_ip": internal_ip,
                    "external_ip": external_ip,
                    "hostname": hostname,
                    "ip_address": internal_ip or external_ip,
                })
            return nodes
        except Exception as e:
            self.last_error = f"Bağlantı hatası: {e}"
            logger.error(f"OpenShift list_nodes error: {e}", exc_info=True)
            return []

    def list_projects(self) -> List[Dict]:
        """Namespace/proje listesini döner (openshift-* sistem projeleri de dahil, `is_system` ile ayrılır)."""
        self.last_error = ""
        try:
            r = self._get("/api/v1/namespaces", params={"limit": 500}, timeout=30)
            if r.status_code != 200:
                self.last_error = self._describe_http_error(r)
                logger.error(f"OpenShift proje listesi hatası: {r.status_code} - {r.text[:200]}")
                return []
            projects = []
            for ns in (r.json() or {}).get("items", []):
                meta = ns.get("metadata", {}) or {}
                name = meta.get("name", "")
                annotations = meta.get("annotations", {}) or {}
                status = (ns.get("status", {}) or {}).get("phase", "Active")
                projects.append({
                    "name": name,
                    "status": status,
                    "display_name": annotations.get("openshift.io/display-name", ""),
                    "requester": annotations.get("openshift.io/requester", ""),
                    "is_system": name.startswith(_SYSTEM_NAMESPACE_PREFIXES),
                })
            return projects
        except Exception as e:
            self.last_error = f"Bağlantı hatası: {e}"
            logger.error(f"OpenShift list_projects error: {e}", exc_info=True)
            return []

    def list_pods(self, namespace: Optional[str] = None) -> List[Dict]:
        """Pod envanteri — durum, restart sayısı, node adı.

        Kubernetes continue-token ile tüm sayfaları çeker (limit tek başına
        yeterli olmayabilir). Ham containerStatuses dönülmez — AI/tool
        bağlamını şişirir ve 300+ pod'da çıktı kesilip 1-2 pod kalırdı.
        """
        self.last_error = ""
        try:
            path = f"/api/v1/namespaces/{namespace}/pods" if namespace else "/api/v1/pods"
            pods: List[Dict] = []
            continue_token: Optional[str] = None
            for _page in range(50):  # güvenlik üst sınırı
                params: Dict[str, Any] = {"limit": 500}
                if continue_token:
                    params["continue"] = continue_token
                r = self._get(path, params=params, timeout=45)
                if r.status_code != 200:
                    self.last_error = self._describe_http_error(r)
                    logger.error(f"OpenShift pod listesi hatası: {r.status_code} - {r.text[:200]}")
                    break
                body = r.json() or {}
                for p in body.get("items", []) or []:
                    meta = p.get("metadata", {}) or {}
                    status_obj = p.get("status", {}) or {}
                    spec = p.get("spec", {}) or {}
                    container_statuses = status_obj.get("containerStatuses", []) or []
                    ready_count = sum(1 for c in container_statuses if c.get("ready"))
                    total_count = len(container_statuses) or len(spec.get("containers", []) or [])
                    restart_count = sum(int(c.get("restartCount", 0) or 0) for c in container_statuses)
                    wait_reason = None
                    for c in container_statuses:
                        state = c.get("state") or {}
                        waiting = state.get("waiting") or {}
                        if waiting.get("reason"):
                            wait_reason = waiting["reason"]
                            break
                        term = state.get("terminated") or {}
                        if term.get("reason") and term.get("reason") not in ("Completed",):
                            wait_reason = term["reason"]
                            break

                    owners = meta.get("ownerReferences") or []
                    owner_kind = owners[0].get("kind", "") if owners else ""
                    owner_name = owners[0].get("name", "") if owners else ""

                    cpu_req = 0.0
                    mem_req = 0.0
                    for c in (spec.get("containers") or []):
                        req = ((c.get("resources") or {}).get("requests") or {})
                        cpu_req += self._parse_quantity(req.get("cpu"))
                        mem_req += self._parse_quantity(req.get("memory"))

                    phase = status_obj.get("phase", "Unknown")
                    display_status = wait_reason or phase

                    pods.append({
                        "namespace": meta.get("namespace", ""),
                        "name": meta.get("name", ""),
                        "status": display_status,
                        "phase": phase,
                        "reason": wait_reason,
                        "node_name": spec.get("nodeName", ""),
                        "restart_count": restart_count,
                        "ready": f"{ready_count}/{total_count}",
                        "owner_kind": owner_kind,
                        "owner_name": owner_name,
                        "cpu_request": round(cpu_req, 3),
                        "memory_request_gb": round(mem_req, 3),
                        "labels": meta.get("labels") or {},
                    })
                continue_token = (body.get("metadata") or {}).get("continue") or None
                if not continue_token:
                    break
            return pods
        except Exception as e:
            self.last_error = f"Bağlantı hatası: {e}"
            logger.error(f"OpenShift list_pods error: {e}", exc_info=True)
            return []

    def list_deployments(self, namespace: Optional[str] = None) -> List[Dict]:
        try:
            path = f"/apis/apps/v1/namespaces/{namespace}/deployments" if namespace else "/apis/apps/v1/deployments"
            r = self._get(path, params={"limit": 1000}, timeout=30)
            if r.status_code != 200:
                return []
            items = []
            for d in (r.json() or {}).get("items", []):
                meta = d.get("metadata", {}) or {}
                status_obj = d.get("status", {}) or {}
                desired = (d.get("spec", {}) or {}).get("replicas", 0) or 0
                ready = status_obj.get("readyReplicas", 0) or 0
                items.append({
                    "namespace": meta.get("namespace", ""),
                    "name": meta.get("name", ""),
                    "status": "Available" if ready >= desired and desired > 0 else ("Progressing" if desired > 0 else "Scaled to 0"),
                    "ready": f"{ready}/{desired}",
                })
            return items
        except Exception as e:
            logger.error(f"OpenShift list_deployments error: {e}", exc_info=True)
            return []

    def list_routes(self, namespace: Optional[str] = None) -> List[Dict]:
        """OpenShift Route kaynakları (route.openshift.io/v1) — Kubernetes'te karşılığı yok."""
        try:
            path = f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes" if namespace else "/apis/route.openshift.io/v1/routes"
            r = self._get(path, params={"limit": 1000}, timeout=30)
            if r.status_code == 404:
                return []  # Route API mevcut değil (vanilla k8s veya kısıtlı RBAC)
            if r.status_code != 200:
                return []
            items = []
            for rt in (r.json() or {}).get("items", []):
                meta = rt.get("metadata", {}) or {}
                spec = rt.get("spec", {}) or {}
                status_obj = rt.get("status", {}) or {}
                ingress = (status_obj.get("ingress") or [{}])[0]
                conditions = ingress.get("conditions", []) or []
                admitted = any(c.get("type") == "Admitted" and c.get("status") == "True" for c in conditions)
                to = spec.get("to") or {}
                items.append({
                    "namespace": meta.get("namespace", ""),
                    "name": meta.get("name", ""),
                    "host": spec.get("host", ""),
                    "status": "Admitted" if admitted else "Pending",
                    "to_service": to.get("name", "") if to.get("kind") == "Service" else to.get("name", ""),
                })
            return items
        except Exception as e:
            logger.error(f"OpenShift list_routes error: {e}", exc_info=True)
            return []

    def list_services(self, namespace: Optional[str] = None) -> List[Dict]:
        """Service envanteri — topology (Route → Service → Pod) için."""
        try:
            path = f"/api/v1/namespaces/{namespace}/services" if namespace else "/api/v1/services"
            r = self._get(path, params={"limit": 1000}, timeout=30)
            if r.status_code != 200:
                return []
            items = []
            for svc in (r.json() or {}).get("items", []) or []:
                meta = svc.get("metadata", {}) or {}
                spec = svc.get("spec", {}) or {}
                ports = spec.get("ports") or []
                port_str = ",".join(
                    f"{p.get('port')}/{p.get('protocol', 'TCP')}" for p in ports[:4]
                )
                items.append({
                    "namespace": meta.get("namespace", ""),
                    "name": meta.get("name", ""),
                    "status": spec.get("type", "ClusterIP"),
                    "selector": spec.get("selector") or {},
                    "ports": port_str,
                    "cluster_ip": spec.get("clusterIP", ""),
                })
            return items
        except Exception as e:
            logger.error(f"OpenShift list_services error: {e}", exc_info=True)
            return []

    def get_project_topology(self, namespace: str) -> Dict[str, Any]:
        """Seçili proje için Route → Service → Deployment/owner → Pod → Node ilişkisi."""
        ns = (namespace or "").strip()
        if not ns:
            return {"project": "", "nodes": [], "edges": [], "summary": {}}

        routes = self.list_routes(ns)
        services = self.list_services(ns)
        deployments = self.list_deployments(ns)
        pods = self.list_pods(ns)

        graph_nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []
        seen: set = set()

        def add_node(nid: str, kind: str, name: str, **extra):
            if nid in seen:
                return
            seen.add(nid)
            graph_nodes.append({"id": nid, "kind": kind, "name": name, **extra})

        for rt in routes:
            rid = f"route/{rt['name']}"
            add_node(rid, "route", rt["name"], status=rt.get("status"), host=rt.get("host"))
            svc = rt.get("to_service") or ""
            if svc:
                sid = f"service/{svc}"
                add_node(sid, "service", svc, status="Service")
                edges.append({"from": rid, "to": sid, "rel": "routes-to"})

        for svc in services:
            sid = f"service/{svc['name']}"
            add_node(sid, "service", svc["name"], status=svc.get("status"), ports=svc.get("ports"))
            sel = svc.get("selector") or {}
            if sel:
                for pod in pods:
                    labels = pod.get("labels") or {}
                    if all(labels.get(k) == v for k, v in sel.items()):
                        pid = f"pod/{pod['name']}"
                        add_node(
                            pid, "pod", pod["name"],
                            status=pod.get("status"), node_name=pod.get("node_name"),
                            ready=pod.get("ready"), restart_count=pod.get("restart_count"),
                        )
                        edges.append({"from": sid, "to": pid, "rel": "selects"})
                        if pod.get("node_name"):
                            nid = f"node/{pod['node_name']}"
                            add_node(nid, "node", pod["node_name"], status="")
                            edges.append({"from": pid, "to": nid, "rel": "runs-on"})

        for d in deployments:
            did = f"deployment/{d['name']}"
            add_node(did, "deployment", d["name"], status=d.get("status"), ready=d.get("ready"))
            for pod in pods:
                if pod.get("owner_kind") in ("ReplicaSet", "Deployment") and (
                    (pod.get("owner_name") or "").startswith(d["name"]) or pod.get("owner_name") == d["name"]
                ):
                    pid = f"pod/{pod['name']}"
                    add_node(
                        pid, "pod", pod["name"],
                        status=pod.get("status"), node_name=pod.get("node_name"),
                        ready=pod.get("ready"), restart_count=pod.get("restart_count"),
                    )
                    edges.append({"from": did, "to": pid, "rel": "owns"})
                    if pod.get("node_name"):
                        nid = f"node/{pod['node_name']}"
                        add_node(nid, "node", pod["node_name"], status="")
                        edges.append({"from": pid, "to": nid, "rel": "runs-on"})

        # Orphan pods (no edge yet)
        for pod in pods:
            pid = f"pod/{pod['name']}"
            if pid not in seen:
                add_node(
                    pid, "pod", pod["name"],
                    status=pod.get("status"), node_name=pod.get("node_name"),
                    ready=pod.get("ready"), restart_count=pod.get("restart_count"),
                )
                if pod.get("node_name"):
                    nid = f"node/{pod['node_name']}"
                    add_node(nid, "node", pod["node_name"], status="")
                    edges.append({"from": pid, "to": nid, "rel": "runs-on"})

        return {
            "project": ns,
            "nodes": graph_nodes,
            "edges": edges,
            "summary": {
                "routes": len(routes),
                "services": len(services),
                "deployments": len(deployments),
                "pods": len(pods),
            },
        }

    def list_events(self, hours: int = 48) -> List[Dict]:
        """Türetilmiş alarm mantığı: Node NotReady, CrashLoopBackOff, OOMKilled, PVC sorunları, Deployment ilerleme sorunu."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events: List[Dict] = []
        self.last_error = ""

        try:
            r = self._get("/api/v1/events", params={"limit": 500}, timeout=30)
            if r.status_code != 200:
                self.last_error = self._describe_http_error(r)
            if r.status_code == 200:
                for ev in (r.json() or {}).get("items", []):
                    involved = ev.get("involvedObject", {}) or {}
                    kind = involved.get("kind", "")
                    event_type = ev.get("type", "Normal")
                    reason = ev.get("reason", "")
                    if event_type != "Warning":
                        continue
                    last_ts_raw = ev.get("lastTimestamp") or ev.get("eventTime") or (ev.get("metadata") or {}).get("creationTimestamp")
                    try:
                        last_ts = datetime.strptime(last_ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if last_ts_raw else None
                    except Exception:
                        last_ts = None
                    if last_ts and last_ts < cutoff:
                        continue

                    severity = "critical" if reason in (
                        "Failed", "FailedScheduling", "BackOff", "Unhealthy", "OOMKilling",
                        "NodeNotReady", "FailedMount", "FailedAttachVolume",
                    ) else "warning"

                    events.append({
                        "title": f"{kind}/{involved.get('name', '')}: {reason}",
                        "description": ev.get("message", ""),
                        "severity": severity,
                        "source_object": f"{kind}/{involved.get('name', '')}",
                        "namespace": involved.get("namespace", ""),
                        "timestamp": last_ts.isoformat() if last_ts else None,
                        "reason": reason,
                    })
        except Exception as e:
            self.last_error = f"Bağlantı hatası: {e}"
            logger.error(f"OpenShift list_events error: {e}", exc_info=True)

        # Türetilmiş: CrashLoopBackOff / yüksek restart (list_pods reason alanından)
        try:
            for pod in self.list_pods():
                reason = pod.get("reason") or ""
                restarts = int(pod.get("restart_count") or 0)
                if reason == "CrashLoopBackOff" or (pod.get("status") or "") == "CrashLoopBackOff":
                    events.append({
                        "title": f"Pod/{pod['name']}: CrashLoopBackOff",
                        "description": reason,
                        "severity": "critical",
                        "source_object": f"Pod/{pod['name']}",
                        "namespace": pod.get("namespace", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": "CrashLoopBackOff",
                    })
                elif restarts >= 5:
                    events.append({
                        "title": f"Pod/{pod['name']}: Yüksek restart sayısı ({restarts})",
                        "description": f"Pod {restarts} kez yeniden başladı",
                        "severity": "warning",
                        "source_object": f"Pod/{pod['name']}",
                        "namespace": pod.get("namespace", ""),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": "HighRestartCount",
                    })
        except Exception as e:
            logger.debug(f"OpenShift derived pod events skipped: {e}")

        return events

    def logout(self):
        try:
            self.session.close()
        except Exception:
            pass
