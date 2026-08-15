"""
Prometheus Metrics Service - Tüm metrikleri çekmek ve AI'a context sağlamak için
"""
import httpx
import logging
import re
from typing import Dict, List, Optional, Any
from app.core.config import settings, promql_job_matcher

logger = logging.getLogger(__name__)


def node_exporter_up_for_server(
    server_ip: Optional[str],
    hostname: Optional[str],
    name: Optional[str] = None,
) -> bool:
    """Prometheus'tan bu sunucuda node-exporter'ın up olup olmadığını kontrol et (sync)."""
    if not server_ip and not hostname and not name:
        return False
    try:
        up_map = get_node_exporter_up_map()
        _inst, is_up = match_prometheus_instance(
            up_map, ip=server_ip, hostname=hostname, name=name,
        )
        return bool(is_up)
    except Exception as e:
        logger.debug(f"Prometheus node_exporter up check hatası: {e}")
    return False


def get_node_exporter_up_map() -> Dict[str, str]:
    """Prometheus up{job=...} sonuçlarını instance -> '0'|'1' map olarak döner."""
    result_map: Dict[str, str] = {}
    try:
        job = promql_job_matcher(kind="linux")
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": f'up{{{job}}}'},
            )
            if resp.status_code != 200:
                return result_map
            data = resp.json()
            if data.get("status") != "success":
                return result_map
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if instance and value and len(value) >= 2:
                    result_map[instance] = str(value[1])
    except Exception as e:
        logger.debug(f"Prometheus up map hatası: {e}")
    return result_map


def _hostname_candidates(*values: Optional[str]) -> List[str]:
    """Tekilleştirilmiş hostname / kısa ad adayları (lowercase)."""
    out: List[str] = []
    seen = set()
    for v in values:
        c = (v or "").strip().lower()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
        short = c.split(".")[0]
        if short and short not in seen:
            seen.add(short)
            out.append(short)
    return out


def _match_hostname_in_up_map(
    up_map: Dict[str, str], candidates: List[str],
) -> tuple[Optional[str], bool]:
    """Kısa ad ↔ FQDN: oprkbarcdbt → oprkbarcdbt.kfs.local:9100."""
    if not up_map or not candidates:
        return None, False
    for cand in candidates:
        short = cand.split(".")[0]
        for inst, val in up_map.items():
            host_part = inst.rsplit(":", 1)[0].lower()
            host_short = host_part.split(".")[0]
            # Tam eşitlik veya kısa ad + domain eki
            if (
                host_part == cand
                or host_part == short
                or host_part.startswith(cand + ".")
                or host_part.startswith(short + ".")
                or host_short == short
                or host_short == cand
            ):
                return inst, val == "1"
    return None, False


def match_prometheus_instance(
    up_map: Dict[str, str],
    *,
    ip: Optional[str] = None,
    hostname: Optional[str] = None,
    name: Optional[str] = None,
) -> tuple[Optional[str], bool]:
    """Sunucuyu Prometheus instance etiketiyle eşleştir.

    Merkezi/harici Prometheus'ta instance çoğu zaman hostname:9100 veya
    FQDN:9100 olur (oprkbarcdbt.sys.yapikredi.com.tr:9100). IP:9100 yedektir.
    Returns: (matched_instance, is_up)
    """
    if not up_map:
        return None, False

    ip = (ip or "").strip()
    hostname = (hostname or "").strip()
    name = (name or "").strip()

    # 1) Hostname / name önce (kısa ad → FQDN)
    matched, is_up = _match_hostname_in_up_map(
        up_map, _hostname_candidates(hostname, name),
    )
    if matched:
        return matched, is_up

    # 2) IP:9100 yedek
    if ip:
        exact = f"{ip}:9100"
        if exact in up_map:
            return exact, up_map[exact] == "1"
        for inst, val in up_map.items():
            if inst.startswith(ip + ":"):
                return inst, val == "1"

    return None, False


_HOST_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,80}")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _escape_promql_label(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _promql_regex_literal(value: str) -> str:
    """PromQL =~ alternation için özel karakterleri karakter sınıfına al."""
    special = "^.$*+?{}[]|()\\"
    return "".join(f"[{c}]" if c in special else c for c in (value or ""))


def _word_in_text(text: str, token: str) -> bool:
    """Hostname kısa adı mesajda geçiyor mu (Türkçe ek / noktalama toleranslı)."""
    if not text or not token or len(token) < 3:
        return False
    return re.search(
        r"(?<![a-z0-9])" + re.escape(token.lower()) + r"(?![a-z0-9])",
        text.lower(),
    ) is not None


def resolve_prometheus_instances_from_message(
    message: str,
    up_map: Dict[str, str],
) -> List[str]:
    """Kullanıcı metnindeki hostname/FQDN/IP → Prometheus'taki gerçek instance etiketi.

    Scrape FQDN:9100 veya kısa-ad:9100 olabilir; uydurulmaz, up map'ten okunur.
    """
    if not (message or "").strip() or not up_map:
        return []
    ml = message.lower()
    found: List[str] = []
    seen = set()

    def _add(inst: Optional[str]) -> None:
        if inst and inst not in seen:
            seen.add(inst)
            found.append(inst)

    for ip in _IPV4_RE.findall(message):
        inst, _up = match_prometheus_instance(up_map, ip=ip)
        _add(inst)

    for inst in up_map.keys():
        host = inst.rsplit(":", 1)[0].lower()
        short = host.split(".")[0]
        if host and host in ml:
            _add(inst)
            continue
        if short in {"cpu", "ram", "disk", "load", "net", "node", "job", "http", "all"}:
            continue
        if _word_in_text(ml, short):
            _add(inst)

    if not found:
        for tok in _HOST_TOKEN_RE.findall(message):
            if tok.lower() in ("cpu", "ram", "disk", "http", "https"):
                continue
            inst, _up = match_prometheus_instance(
                up_map, hostname=tok, name=tok, ip=tok if _IPV4_RE.fullmatch(tok) else None,
            )
            _add(inst)

    return found


def linux_promql_selector(instances: Optional[List[str]] = None) -> str:
    """Canlı Metrikler ile aynı: job matcher + varsa birebir instance etiketi."""
    job = promql_job_matcher(kind="linux")
    insts = [i for i in (instances or []) if i]
    if not insts:
        return job
    if len(insts) == 1:
        return f'{job},instance="{_escape_promql_label(insts[0])}"'
    alts = "|".join(_promql_regex_literal(i) for i in insts)
    return f'{job},instance=~"{alts}"'


def linux_live_preset_queries(selector: str) -> Dict[str, str]:
    """Canlı Metrikler preset PromQL (instance bazlı)."""
    return {
        "cpu": (
            f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle",{selector}}}[5m])) * 100)'
        ),
        "memory": (
            f'(1 - (node_memory_MemAvailable_bytes{{{selector}}} '
            f'/ node_memory_MemTotal_bytes{{{selector}}})) * 100'
        ),
        "disk": (
            f'(1 - (node_filesystem_avail_bytes{{mountpoint="/",{selector}}} '
            f'/ node_filesystem_size_bytes{{mountpoint="/",{selector}}})) * 100'
        ),
        "load": f'node_load1{{{selector}}}',
        "net_rx": (
            f'sum by (instance) (rate(node_network_receive_bytes_total{{device!~"lo",{selector}}}[5m]))'
        ),
        "net_tx": (
            f'sum by (instance) (rate(node_network_transmit_bytes_total{{device!~"lo",{selector}}}[5m]))'
        ),
    }


def sync_node_exporter_running_from_prometheus(db) -> Dict[str, int]:
    """DB'deki node_exporter_running bayrağını Prometheus up durumuna göre günceller."""
    from app.models.server import Server

    up_map = get_node_exporter_up_map()
    updated = cleared = promoted = 0

    servers = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    for server in servers:
        _inst, prom_up = match_prometheus_instance(
            up_map,
            ip=server.ip_address,
            hostname=server.hostname,
            name=server.name,
        )

        if prom_up:
            changed = False
            if not server.node_exporter_installed:
                server.node_exporter_installed = True
                changed = True
            if not server.node_exporter_running:
                server.node_exporter_running = True
                changed = True
            if changed:
                promoted += 1
                updated += 1
            continue

        # Prometheus'tan veri yok — kurulu sayılan ama çalışmıyor olarak işaretle
        if server.node_exporter_installed and server.node_exporter_running:
            server.node_exporter_running = False
            cleared += 1
            updated += 1

    if updated:
        db.commit()

    return {
        "updated": updated,
        "promoted": promoted,
        "cleared": cleared,
        "live": sum(1 for v in up_map.values() if v == "1"),
        "targets": len(up_map),
    }


# ── Windows Exporter (node_exporter'ın Windows eşleniği, port 9182) ─────────

WINDOWS_EXPORTER_PORT = 9182
WINDOWS_EXPORTER_JOB = "windows-exporter"  # varsayılan; runtime'da settings.PROMETHEUS_WINDOWS_JOBS kullanılır


def get_windows_exporter_up_map() -> Dict[str, str]:
    """Prometheus up{job=windows...} sonuçlarını instance -> '0'|'1' map olarak döner."""
    result_map: Dict[str, str] = {}
    try:
        job = promql_job_matcher(kind="windows")
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": f'up{{{job}}}'},
            )
            if resp.status_code != 200:
                return result_map
            data = resp.json()
            if data.get("status") != "success":
                return result_map
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if instance and value and len(value) >= 2:
                    result_map[instance] = str(value[1])
    except Exception as e:
        logger.debug(f"Prometheus windows-exporter up map hatası: {e}")
    return result_map


def windows_exporter_up_for_server(server_ip: Optional[str], hostname: Optional[str]) -> bool:
    """Prometheus'tan bu sunucuda windows_exporter'ın up olup olmadığını kontrol et (sync)."""
    if not server_ip and not hostname:
        return False
    up_map = get_windows_exporter_up_map()
    if server_ip:
        instance = f"{server_ip}:{WINDOWS_EXPORTER_PORT}"
        if up_map.get(instance) == "1":
            return True
    if hostname:
        for inst, val in up_map.items():
            if val == "1" and (inst.startswith(hostname) or hostname in inst):
                return True
    return False


def sync_windows_exporter_running_from_prometheus(db) -> Dict[str, int]:
    """DB'deki windows_exporter_running bayrağını Prometheus up durumuna göre günceller."""
    from app.models.server import Server

    up_map = get_windows_exporter_up_map()
    updated = cleared = promoted = 0

    servers = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    for server in servers:
        instance = f"{server.ip_address.strip()}:{WINDOWS_EXPORTER_PORT}"
        prom_up = up_map.get(instance) == "1"

        if prom_up:
            changed = False
            if not server.windows_exporter_installed:
                server.windows_exporter_installed = True
                changed = True
            if not server.windows_exporter_running:
                server.windows_exporter_running = True
                changed = True
            if changed:
                promoted += 1
                updated += 1
            continue

        if server.windows_exporter_installed and server.windows_exporter_running:
            server.windows_exporter_running = False
            cleared += 1
            updated += 1

    if updated:
        db.commit()

    return {
        "updated": updated,
        "promoted": promoted,
        "cleared": cleared,
        "live": sum(1 for v in up_map.values() if v == "1"),
        "targets": len(up_map),
    }


def sync_windows_exporter_targets_from_db(db, reload: bool = True) -> Dict[str, Any]:
    """
    DB'deki kurulu Windows sunuculardan windows_exporter Prometheus target dosyasını
    yeniden oluşturur (node_exporter'daki sync_node_exporter_targets_from_db eşleniği).
    """
    from app.models.server import Server
    from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager

    eligible = db.query(Server).filter(
        Server.windows_exporter_installed == True,  # noqa: E712
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    by_instance: Dict[str, object] = {}
    duplicate_names: List[str] = []

    for server in eligible:
        instance = f"{server.ip_address.strip()}:{WINDOWS_EXPORTER_PORT}"
        if instance in by_instance:
            prev = by_instance[instance]
            winner = _pick_canonical_monitoring_server([prev, server])
            loser = server if winner is prev else prev
            duplicate_names.append(getattr(loser, "name", "?"))
            by_instance[instance] = winner
        else:
            by_instance[instance] = server

    new_targets = []
    for instance, server in sorted(by_instance.items(), key=lambda x: (x[1].name or "").lower()):
        new_targets.append({
            "targets": [instance],
            "labels": {
                "server_id": str(server.id),
                "server_name": server.name,
                "job": WINDOWS_EXPORTER_JOB,
            },
        })

    tm = PrometheusTargetManager(_windows_targets_file_path())
    old_targets = tm.load_targets()
    old_instances = {
        t.get("targets", [])[0]
        for t in old_targets
        if t.get("targets")
    }
    new_instances = set(by_instance.keys())

    tm.rebuild_targets(new_targets)

    stats = {
        "targets_before": len(old_targets),
        "targets_after": len(new_targets),
        "servers_eligible": len(eligible),
        "unique_instances": len(new_targets),
        "removed_orphans": len(old_instances - new_instances),
        "added": len(new_instances - old_instances),
        "duplicate_servers_skipped": duplicate_names,
        "reloaded": False,
    }

    if reload:
        stats["reloaded"] = tm.reload_prometheus_sync()

    logger.info(
        "Windows exporter target sync: %s -> %s hedef (%s yetim kaldırıldı)",
        stats["targets_before"],
        stats["targets_after"],
        stats["removed_orphans"],
    )
    return stats


def _windows_targets_file_path() -> str:
    import os
    if os.path.exists("/prometheus/targets"):
        return "/prometheus/targets/windows_exporter_targets.json"
    if os.path.exists("/etc/prometheus/targets"):
        return "/etc/prometheus/targets/windows_exporter_targets.json"
    return "/prometheus/targets/windows_exporter_targets.json"


def _pick_canonical_monitoring_server(servers: list):
    """Aynı IP için tek kayıt: hypervisor bağlı olan, yoksa en yüksek id."""
    def score(s):
        return (1 if getattr(s, "hypervisor_id", None) else 0, s.id or 0)
    return max(servers, key=score)


def sync_node_exporter_targets_from_db(db, reload: bool = True) -> Dict[str, Any]:
    """
    DB'deki kurulu ONLINE sunuculardan Prometheus target dosyasını yeniden oluşturur.
    Silinen sunucuların hedefleri kaldırılır; ad/IP değişiklikleri etiketlere yansır.
    Aynı IP'de birden fazla kayıt varsa tek hedef kalır (hypervisor kaydı öncelikli).
    """
    from app.models.server import Server
    from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager

    eligible = db.query(Server).filter(
        Server.node_exporter_installed == True,  # noqa: E712
        Server.status == "ONLINE",
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).all()

    by_instance: Dict[str, object] = {}
    duplicate_names: List[str] = []

    for server in eligible:
        instance = f"{server.ip_address.strip()}:9100"
        if instance in by_instance:
            prev = by_instance[instance]
            winner = _pick_canonical_monitoring_server([prev, server])
            loser = server if winner is prev else prev
            duplicate_names.append(getattr(loser, "name", "?"))
            by_instance[instance] = winner
        else:
            by_instance[instance] = server

    new_targets = []
    for instance, server in sorted(by_instance.items(), key=lambda x: x[1].name.lower()):
        new_targets.append({
            "targets": [instance],
            "labels": {
                "server_id": str(server.id),
                "server_name": server.name,
                "job": "node-exporter",
            },
        })

    tm = PrometheusTargetManager()
    old_targets = tm.load_targets()
    old_instances = {
        t.get("targets", [])[0]
        for t in old_targets
        if t.get("targets")
    }
    new_instances = set(by_instance.keys())

    tm.rebuild_targets(new_targets)

    stats = {
        "targets_before": len(old_targets),
        "targets_after": len(new_targets),
        "servers_eligible": len(eligible),
        "unique_instances": len(new_targets),
        "removed_orphans": len(old_instances - new_instances),
        "added": len(new_instances - old_instances),
        "duplicate_servers_skipped": duplicate_names,
        "reloaded": False,
    }

    if reload:
        stats["reloaded"] = tm.reload_prometheus_sync()

    logger.info(
        "Prometheus target sync: %s -> %s hedef (%s yetim kaldırıldı)",
        stats["targets_before"],
        stats["targets_after"],
        stats["removed_orphans"],
    )
    return stats


class PrometheusMetricsService:
    """Prometheus metriklerini çekmek ve analiz etmek için servis"""
    
    def __init__(self, prometheus_url: Optional[str] = None):
        self.prometheus_url = prometheus_url or settings.PROMETHEUS_URL
    
    async def get_available_metrics(self) -> List[str]:
        """Mevcut tüm metrikleri listele"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.prometheus_url}/api/v1/label/__name__/values")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data.get("data", [])
        except Exception as e:
            logger.error(f"Metrik listesi alınamadı: {e}")
        return []
    
    async def get_node_exporter_metrics(self) -> List[str]:
        """Node Exporter metriklerini filtrele"""
        all_metrics = await self.get_available_metrics()
        return [m for m in all_metrics if m.startswith("node_")]
    
    async def query_metric(self, query: str) -> Optional[Dict[str, Any]]:
        """Prometheus query çalıştır"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.prometheus_url}/api/v1/query",
                    params={"query": query}
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"Query hatası: {e}")
        return None
    
    def _instant_series(self, data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not data or data.get("status") != "success":
            return []
        out: List[Dict[str, Any]] = []
        for r in (data.get("data") or {}).get("result") or []:
            try:
                inst = (r.get("metric") or {}).get("instance") or "?"
                out.append({"instance": inst, "value": float(r["value"][1])})
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        return out

    @staticmethod
    def _top(items: List[Dict[str, Any]], n: int = 12) -> List[Dict[str, Any]]:
        return sorted(items, key=lambda x: float(x.get("value") or 0), reverse=True)[:n]

    @staticmethod
    def _fmt_rate_bps(bps: float) -> str:
        if bps >= 1024 * 1024:
            return f"{bps / 1024 / 1024:.2f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{bps:.0f} B/s"

    async def get_system_overview(self) -> Dict[str, Any]:
        """Filo ortalaması (tek sayı). Instance bazlı değerler get_server_metrics'te."""
        overview = {
            "cpu": {},
            "memory": {},
            "disk": {},
            "network": {},
            "load": {}
        }
        job = promql_job_matcher(kind="linux")
        try:
            cpu_query = (
                f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle",{job}}}[5m])) * 100)'
            )
            cpu_data = await self.query_metric(cpu_query)
            series = self._instant_series(cpu_data)
            if series:
                overview["cpu"]["average"] = series[0]["value"]

            memory_query = (
                f'(1 - (avg(node_memory_MemAvailable_bytes{{{job}}}) '
                f'/ avg(node_memory_MemTotal_bytes{{{job}}}))) * 100'
            )
            memory_data = await self.query_metric(memory_query)
            series = self._instant_series(memory_data)
            if series:
                overview["memory"]["usage_percent"] = series[0]["value"]

            disk_query = (
                f'(1 - (avg(node_filesystem_avail_bytes{{mountpoint="/",{job}}}) '
                f'/ avg(node_filesystem_size_bytes{{mountpoint="/",{job}}}))) * 100'
            )
            disk_data = await self.query_metric(disk_query)
            series = self._instant_series(disk_data)
            if series:
                overview["disk"]["usage_percent"] = series[0]["value"]

            load_query = f'avg(node_load1{{{job}}})'
            load_data = await self.query_metric(load_query)
            series = self._instant_series(load_data)
            if series:
                overview["load"]["1min"] = series[0]["value"]
        except Exception as e:
            logger.error(f"Sistem overview hatası: {e}")

        return overview

    async def get_server_metrics(
        self,
        server_ip: Optional[str] = None,
        *,
        instances: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Canlı Metrikler preset'leri: CPU/RAM/disk/load/RX/TX, instance bazlı."""
        metrics: Dict[str, Any] = {}
        resolved = [i for i in (instances or []) if i]
        try:
            if not resolved and server_ip:
                up_map = get_node_exporter_up_map()
                inst, _up = match_prometheus_instance(
                    up_map, ip=server_ip, hostname=server_ip, name=server_ip,
                )
                if inst:
                    resolved = [inst]
            selector = linux_promql_selector(resolved or None)
            queries = linux_live_preset_queries(selector)
            key_map = {
                "cpu": "cpu_usage",
                "memory": "memory_usage",
                "disk": "disk_usage",
                "load": "load1",
                "net_rx": "network_rx",
                "net_tx": "network_tx",
            }
            for qk, mk in key_map.items():
                data = await self.query_metric(queries[qk])
                metrics[mk] = self._instant_series(data)
        except Exception as e:
            logger.error(f"Sunucu metrikleri hatası: {e}")
        return metrics

    async def get_metrics_context_for_ai(self, message: str) -> str:
        """AI için metrik context — scrape etiketini uydurmadan, preset PromQL."""
        context = ""
        ml = (message or "").lower()
        want_uptime = any(
            kw in ml for kw in ("uptime", "çalışma süresi", "calisma suresi", "boot", "restart")
        )

        up_map = get_node_exporter_up_map()
        named = resolve_prometheus_instances_from_message(message, up_map)

        if named:
            context += (
                "\n📈 Prometheus Node Exporter (instance etiketi scrape'den birebir; "
                "FQDN veya hostname hangisiyse o):\n"
            )
            try:
                metrics = await self.get_server_metrics(instances=named)
                by_host: Dict[str, Dict[str, Optional[float]]] = {
                    inst: {} for inst in named
                }
                for key, field in (
                    ("cpu_usage", "cpu"),
                    ("memory_usage", "mem"),
                    ("disk_usage", "disk"),
                    ("load1", "load"),
                    ("network_rx", "rx"),
                    ("network_tx", "tx"),
                ):
                    for item in metrics.get(key) or []:
                        inst = item.get("instance") or "?"
                        by_host.setdefault(inst, {})[field] = item.get("value")
                for inst in named:
                    row = by_host.get(inst) or {}
                    context += f"  {inst}\n"
                    if row.get("cpu") is not None:
                        context += f"    CPU: {row['cpu']:.1f}%\n"
                    if row.get("mem") is not None:
                        context += f"    RAM: {row['mem']:.1f}%\n"
                    if row.get("disk") is not None:
                        context += f"    Disk (/): {row['disk']:.1f}%\n"
                    if row.get("load") is not None:
                        context += f"    Load1: {row['load']:.2f}\n"
                    if row.get("rx") is not None:
                        context += f"    Net RX: {self._fmt_rate_bps(row['rx'])}\n"
                    if row.get("tx") is not None:
                        context += f"    Net TX: {self._fmt_rate_bps(row['tx'])}\n"
                    if not row:
                        context += "    (bu instance için seri yok)\n"
            except Exception:
                pass
            if want_uptime:
                context += await self._uptime_context(named)
            return context

        try:
            overview = await self.get_system_overview()
            context += (
                "\n📊 Filo ortalaması (tüm instance'ların avg'i — tek sunucu değil):\n"
            )
            if overview.get("cpu", {}).get("average") is not None:
                context += f"  - Ortalama CPU: {overview['cpu']['average']:.2f}%\n"
            if overview.get("memory", {}).get("usage_percent") is not None:
                context += f"  - Ortalama RAM: {overview['memory']['usage_percent']:.2f}%\n"
            if overview.get("disk", {}).get("usage_percent") is not None:
                context += f"  - Ortalama Disk (/): {overview['disk']['usage_percent']:.2f}%\n"
            if overview.get("load", {}).get("1min") is not None:
                context += f"  - Load Average (1 dk): {overview['load']['1min']:.2f}\n"
        except Exception:
            pass

        try:
            metrics = await self.get_server_metrics()
            context += (
                "\n📈 Sunucu bazlı (Prometheus instance etiketi, değere göre yüksekten düşüğe):\n"
            )
            if metrics.get("cpu_usage"):
                context += "  CPU:\n"
                for item in self._top(metrics["cpu_usage"]):
                    context += f"    {item['instance']}: {item['value']:.1f}%\n"
            if metrics.get("memory_usage"):
                context += "  RAM:\n"
                for item in self._top(metrics["memory_usage"]):
                    context += f"    {item['instance']}: {item['value']:.1f}%\n"
            if metrics.get("disk_usage"):
                context += "  Disk (/):\n"
                for item in self._top(metrics["disk_usage"]):
                    context += f"    {item['instance']}: {item['value']:.1f}%\n"
            if metrics.get("load1"):
                context += "  Load1:\n"
                for item in self._top(metrics["load1"]):
                    context += f"    {item['instance']}: {item['value']:.2f}\n"
            if metrics.get("network_rx"):
                context += "  Network RX:\n"
                for item in self._top(metrics["network_rx"]):
                    context += f"    {item['instance']}: {self._fmt_rate_bps(item['value'])}\n"
            if metrics.get("network_tx"):
                context += "  Network TX:\n"
                for item in self._top(metrics["network_tx"]):
                    context += f"    {item['instance']}: {self._fmt_rate_bps(item['value'])}\n"
        except Exception:
            pass

        if want_uptime:
            context += await self._uptime_context(None)
        return context

    async def _uptime_context(self, instances: Optional[List[str]]) -> str:
        try:
            from datetime import datetime as _dt
            sel = linux_promql_selector(instances)
            data = await self.query_metric(f"node_boot_time_seconds{{{sel}}}")
            series = self._instant_series(data)
            if not series:
                return ""
            lines = ["\n⏱️ Uptime:"]
            now = _dt.now().timestamp()
            for item in series[:12]:
                days = (now - item["value"]) / 86400
                lines.append(f"  {item['instance']}: {days:.1f} gün")
            return "\n".join(lines) + "\n"
        except Exception:
            return ""
