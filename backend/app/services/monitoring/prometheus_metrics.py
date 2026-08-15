"""
Prometheus Metrics Service - Tüm metrikleri çekmek ve AI'a context sağlamak için
"""
import asyncio
import httpx
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
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
_METRIC_STOPWORDS = {
    "cpu", "ram", "disk", "load", "net", "node", "job", "http", "https", "all",
    "memory", "bellek", "swap", "network", "trafik", "traffic", "usage",
    "kullanım", "kullanim", "metrik", "metrics", "preset", "prometheus",
    "kaynak", "detay", "sunucu", "sunucular", "host", "server",
}

_FAMILY_KEYWORDS = {
    "cpu": ("cpu",),
    "memory": ("ram", "memory", "bellek", "swap"),
    "disk": ("disk",),
    "network": ("network", "ağ", "ag", "trafik", "traffic", "bandwidth", "rx", "tx"),
    "load": ("load", "yük", "yuk"),
}
_ALL_PRESET_FAMILIES = ("cpu", "memory", "disk", "load", "network")
_PRESET_COLS = {
    "cpu": [("cpu", "CPU%")],
    "memory": [("memory", "RAM%"), ("mem_avail", "MemAvail")],
    "disk": [("disk", "Disk/%"), ("disk_read", "DiskRead"), ("disk_write", "DiskWrite")],
    "load": [("load", "Load1")],
    "network": [("net_rx", "RX"), ("net_tx", "TX")],
}
_FAMILY_EXTRA_COLS = {
    "cpu": [
        ("cpu_user", "user%"),
        ("cpu_system", "sys%"),
        ("cpu_iowait", "iowait%"),
        ("cpu_steal", "steal%"),
        ("cpu_softirq", "softirq%"),
    ],
    "memory": [
        ("mem_total", "MemTotal"),
        ("mem_cached", "Cached"),
        ("mem_buffers", "Buffers"),
        ("swap_pct", "Swap%"),
    ],
    "load": [("load5", "Load5"), ("load15", "Load15")],
}
_ALL_NODE_PREFIXES = {
    "cpu": ("node_cpu_",),
    "memory": ("node_memory_",),
    "disk": ("node_filesystem_", "node_disk_"),
    "network": ("node_network_",),
    "load": ("node_load",),
}


def chat_metric_col_keys(families, *, depth: str) -> List[Tuple[str, str]]:
    keys: List[Tuple[str, str]] = []
    for fam in _ALL_PRESET_FAMILIES:
        if fam not in families:
            continue
        keys.extend(_PRESET_COLS.get(fam) or [])
        if depth in ("family", "all_node"):
            keys.extend(_FAMILY_EXTRA_COLS.get(fam) or [])
    return keys


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
    """Kullanıcı metnindeki hostname/FQDN/IP/önek → scrape'deki gerçek instance.

    `oprbigdata` → oprbigdata3/5/13… (kısa ad öneki, min 5 karakter).
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
        if short in _METRIC_STOPWORDS:
            continue
        if _word_in_text(ml, short):
            _add(inst)

    tokens = [t.lower() for t in _HOST_TOKEN_RE.findall(message)]
    for tok in tokens:
        if tok in _METRIC_STOPWORDS or len(tok) < 5:
            continue
        for inst in up_map.keys():
            host = inst.rsplit(":", 1)[0].lower()
            short = host.split(".")[0]
            if short.startswith(tok) or host.startswith(tok):
                _add(inst)

    if not found:
        for tok in tokens:
            if tok in _METRIC_STOPWORDS:
                continue
            inst, _up = match_prometheus_instance(
                up_map, hostname=tok, name=tok, ip=tok if _IPV4_RE.fullmatch(tok) else None,
            )
            _add(inst)

    return found


def parse_prom_chat_intent(message: str) -> Dict[str, Any]:
    """Soru → aileler + derinlik (preset | family | all_node)."""
    ml = (message or "").lower()
    families = {fam for fam, kws in _FAMILY_KEYWORDS.items() if any(k in ml for k in kws)}
    all_node = any(
        k in ml
        for k in (
            "en detay", "en kapsam", "kapsamlı", "kapsamli", "tüm metrik", "tum metrik",
            "bütün metrik", "butun metrik", "ham metrik", "her metrik", "tüm node",
            "tum node", "node_*", "node_exporter tüm",
        )
    )
    family_detail = (not all_node) and any(
        k in ml for k in ("detay", "ayrıntı", "ayrinti", "iowait", "mount", "iops", "inode")
    )
    general = any(
        k in ml
        for k in ("kaynak", "performans", "genel kullanım", "genel kaynak", "resource")
    )
    if all_node:
        depth = "all_node"
        if not families:
            families = set(_ALL_PRESET_FAMILIES)
    elif family_detail:
        depth = "family"
        if not families:
            families = set(_ALL_PRESET_FAMILIES)
    elif families and not general:
        depth = "preset"
    else:
        depth = "preset"
        families = set(_ALL_PRESET_FAMILIES)
    return {"families": families, "depth": depth}


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
        "mem_avail": f'node_memory_MemAvailable_bytes{{{selector}}}',
        "disk_read": (
            f'sum by (instance) (rate(node_disk_read_bytes_total{{{selector}}}[5m]))'
        ),
        "disk_write": (
            f'sum by (instance) (rate(node_disk_written_bytes_total{{{selector}}}[5m]))'
        ),
    }


def linux_family_detail_queries(selector: str) -> Dict[str, Dict[str, str]]:
    """Aile detayı (cpu user/system/iowait, bellek/swap, disk mount + IO)."""
    cpu_mode = (
        lambda mode: f'avg by (instance) (rate(node_cpu_seconds_total{{mode="{mode}",{selector}}}[5m])) * 100'
    )
    return {
        "cpu": {
            "cpu_user": cpu_mode("user"),
            "cpu_system": cpu_mode("system"),
            "cpu_iowait": cpu_mode("iowait"),
            "cpu_steal": cpu_mode("steal"),
            "cpu_softirq": cpu_mode("softirq"),
        },
        "memory": {
            "mem_total": f'node_memory_MemTotal_bytes{{{selector}}}',
            "mem_cached": f'node_memory_Cached_bytes{{{selector}}}',
            "mem_buffers": f'node_memory_Buffers_bytes{{{selector}}}',
            "swap_pct": (
                f'(1 - node_memory_SwapFree_bytes{{{selector}}} '
                f'/ (node_memory_SwapTotal_bytes{{{selector}}} + 1)) * 100'
            ),
        },
        "disk": {
            "disk_mount_pct": (
                f'(1 - (node_filesystem_avail_bytes{{fstype!~"tmpfs|devtmpfs|squashfs|overlay",{selector}}} '
                f'/ node_filesystem_size_bytes{{fstype!~"tmpfs|devtmpfs|squashfs|overlay",{selector}}})) * 100'
            ),
        },
        "network": {},
        "load": {
            "load5": f'node_load5{{{selector}}}',
            "load15": f'node_load15{{{selector}}}',
        },
    }


def join_series_by_instance(
    columns: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """Kolon adı → [{instance, value}] listelerini instance satırında birleştir."""
    rows: Dict[str, Dict[str, Any]] = {}
    for col, series in (columns or {}).items():
        for item in series or []:
            inst = item.get("instance") or "?"
            rows.setdefault(inst, {})[col] = item.get("value")
            if item.get("mountpoint"):
                rows[inst].setdefault("_mounts", {})[str(item.get("mountpoint"))] = item.get("value")
    return rows


def format_joined_metric_table(
    rows: Dict[str, Dict[str, Any]],
    col_keys: List[tuple],
    *,
    max_rows: int = 80,
    sort_key: str = "cpu",
) -> str:
    """Markdown tablo; boş hücre scrape yok demek değildir."""
    if not rows:
        return ""
    items = list(rows.items())
    items.sort(key=lambda kv: float(kv[1].get(sort_key) or -1), reverse=True)
    truncated = max(0, len(items) - max_rows)
    items = items[:max_rows]
    headers = ["instance"] + [h for _k, h in col_keys]
    lines = [
        "KURAL: Tek tablo, instance JOIN. Boş hücre = bu seride anlık değer yok; "
        "node-exporter/scrape yok uydurma. Ayrı CPU ve RAM listelerini birleştirme.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for inst, row in items:
        cells = [inst]
        for key, _h in col_keys:
            val = row.get(key)
            if val is None:
                cells.append("")
            elif key in ("net_rx", "net_tx", "disk_read", "disk_write", "mem_avail", "mem_total",
                         "mem_cached", "mem_buffers"):
                cells.append(PrometheusMetricsService._fmt_rate_bps(float(val)) if key in (
                    "net_rx", "net_tx", "disk_read", "disk_write"
                ) else _fmt_bytes(float(val)))
            elif key.startswith("load"):
                cells.append(f"{float(val):.2f}")
            else:
                cells.append(f"{float(val):.1f}")
        lines.append("| " + " | ".join(cells) + " |")
    if truncated:
        lines.append(f"\n(Toplam {truncated + max_rows} instance; ilk {max_rows} {sort_key} azalan.)")
    return "\n".join(lines) + "\n"


def _fmt_bytes(n: float) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GiB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.0f} MiB"
    return f"{n:.0f} B"


def format_disk_mount_table(
    rows: Dict[str, Dict[str, Any]],
    *,
    max_lines: int = 80,
) -> str:
    """Aile detayı: mountpoint JOIN (kök dışı volume'lar)."""
    lines = [
        "Disk mount kullanımı (%). Boş satır = o mount bu anlık sorguda yok.",
        "",
        "| instance | mountpoint | % |",
        "| --- | --- | --- |",
    ]
    n = 0
    for inst, row in sorted(rows.items(), key=lambda kv: kv[0]):
        mounts = row.get("_mounts") or {}
        for mp, val in sorted(
            mounts.items(),
            key=lambda x: -float(x[1] or 0),
        ):
            try:
                pct = f"{float(val):.1f}"
            except (TypeError, ValueError):
                pct = ""
            lines.append(f"| {inst} | {mp} | {pct} |")
            n += 1
            if n >= max_lines:
                lines.append(f"\n(Mount listesi kesildi; ilk {max_lines}.)")
                return "\n".join(lines) + "\n"
    return ("\n".join(lines) + "\n") if n else ""


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
    
    def _instant_series(
        self,
        data: Optional[Dict[str, Any]],
        extra_labels: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        extra_labels = extra_labels or []
        if not data or data.get("status") != "success":
            return []
        out: List[Dict[str, Any]] = []
        for r in (data.get("data") or {}).get("result") or []:
            try:
                metric = r.get("metric") or {}
                inst = metric.get("instance") or "?"
                row: Dict[str, Any] = {
                    "instance": inst,
                    "value": float(r["value"][1]),
                }
                if metric.get("__name__"):
                    row["__name__"] = metric.get("__name__")
                for lab in extra_labels:
                    row[lab] = metric.get(lab) or ""
                out.append(row)
            except (KeyError, TypeError, ValueError, IndexError):
                continue
        return out

    async def _query_columns(
        self,
        queries: Dict[str, str],
        extra_labels: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        extra_labels = extra_labels or {}
        if not queries:
            return {}
        keys = list(queries.keys())
        results = await asyncio.gather(
            *[self.query_metric(queries[k]) for k in keys],
            return_exceptions=True,
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for k, res in zip(keys, results):
            if isinstance(res, Exception):
                logger.debug("PromQL kolon hatası %s: %s", k, res)
                out[k] = []
            else:
                out[k] = self._instant_series(res, extra_labels=extra_labels.get(k))
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
        """Canlı Metrikler preset'leri: CPU/RAM/disk/load/RX/TX + avail/IO, instance bazlı."""
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
                "mem_avail": "mem_avail",
                "disk_read": "disk_read",
                "disk_write": "disk_write",
            }
            columns = await self._query_columns({qk: queries[qk] for qk in key_map})
            for qk, mk in key_map.items():
                metrics[mk] = columns.get(qk) or []
        except Exception as e:
            logger.error(f"Sunucu metrikleri hatası: {e}")
        return metrics

    async def get_metrics_context_for_ai(self, message: str) -> str:
        """AI context: instance JOIN tablosu (preset / aile detayı / node_*)."""
        ml = (message or "").lower()
        want_uptime = any(
            kw in ml for kw in ("uptime", "çalışma süresi", "calisma suresi", "boot", "restart")
        )
        intent = parse_prom_chat_intent(message)
        families = intent["families"]
        depth = intent["depth"]

        up_map = get_node_exporter_up_map()
        named = resolve_prometheus_instances_from_message(message, up_map)
        selector = linux_promql_selector(named or None)

        parts: List[str] = []
        if named:
            parts.append(
                "Prometheus Node Exporter — scrape instance etiketi birebir "
                f"({len(named)} host). Kısa ad öneki (örn. oprbigdata → oprbigdata3/5/…). "
                "Tek tablo, instance JOIN."
            )
        else:
            parts.append(
                "Prometheus filo (tüm node-exporter instance). Tek tablo JOIN; "
                "ayrı CPU/RAM sıralamalarını birleştirme. Boş hücre = bu seride anlık değer yok."
            )

        try:
            preset_q = linux_live_preset_queries(selector)
            queries: Dict[str, str] = {}
            extra_labels: Dict[str, List[str]] = {}
            col_keys = chat_metric_col_keys(families, depth=depth)
            for key, _h in col_keys:
                if key in preset_q:
                    queries[key] = preset_q[key]
            if depth in ("family", "all_node"):
                fam_q = linux_family_detail_queries(selector)
                for fam in families:
                    for key, q in (fam_q.get(fam) or {}).items():
                        queries[key] = q
                        if key == "disk_mount_pct":
                            extra_labels[key] = ["mountpoint"]
            columns = await self._query_columns(queries, extra_labels)
            joined = join_series_by_instance(columns)
            if named:
                rows = {inst: dict(joined.get(inst) or {}) for inst in named}
                for inst, data in joined.items():
                    if inst not in rows:
                        rows[inst] = data
            else:
                rows = joined
            table = format_joined_metric_table(
                rows,
                col_keys,
                max_rows=80 if named else 80,
                sort_key=col_keys[0][0] if col_keys else "cpu",
            )
            if table:
                parts.append(table)
            if depth in ("family", "all_node") and "disk" in families:
                mounts = format_disk_mount_table(rows)
                if mounts:
                    parts.append(mounts)
        except Exception as e:
            logger.error(f"Prometheus chat JOIN hatası: {e}")

        if depth == "all_node":
            try:
                parts.append(await self._all_node_context(selector, families, named))
            except Exception as e:
                logger.debug("all_node context: %s", e)

        if want_uptime:
            parts.append(await self._uptime_context(named or None))

        return "\n".join(p for p in parts if p)

    async def _all_node_context(
        self,
        selector: str,
        families,
        named: Optional[List[str]],
    ) -> str:
        """Ham node_* — filo için yalnızca isim; named host'ta örnek seri (kapalı)."""
        prefixes: List[str] = []
        for fam in families or _ALL_PRESET_FAMILIES:
            prefixes.extend(_ALL_NODE_PREFIXES.get(fam) or ())
        if not prefixes:
            prefixes = ["node_"]

        names = await self.get_node_exporter_metrics()
        filtered = [
            n for n in names
            if any(n.startswith(p) for p in prefixes)
        ]
        filtered = filtered[:80]
        lines = [
            "Ham node_* (Canlı Metrikler raw grubu). Filo geneli binlerce seri dump edilmez.",
            "İsimler:",
            ", ".join(filtered) if filtered else "(isim alınamadı)",
        ]
        if not named or len(named) > 12:
            if named and len(named) > 12:
                lines.append(
                    f"{len(named)} host seçili — ham seri dump yok (isim listesi). "
                    "Daha az host veya aile detayı sorun."
                )
            else:
                lines.append(
                    "Belirli hostname yazınca bu aile için örnek seriler de gelir."
                )
            return "\n".join(lines) + "\n"

        alts = "|".join(re.escape(p.rstrip("_")) + ".*" for p in prefixes)
        query = f'{{__name__=~"{alts}",{selector}}}'
        data = await self.query_metric(query)
        series = self._instant_series(data, extra_labels=["mode", "device", "mountpoint"])
        if not series:
            return "\n".join(lines) + "\n"

        lines.append("")
        lines.append("| instance | metrik | etiket | değer |")
        lines.append("| --- | --- | --- | --- |")
        seen: Dict[tuple, int] = {}
        shown = 0
        for item in series:
            name = item.get("__name__") or "?"
            inst = item.get("instance") or "?"
            key = (inst, name)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 3:
                continue
            tags = []
            for lab in ("mode", "device", "mountpoint"):
                if item.get(lab):
                    tags.append(f"{lab}={item[lab]}")
            try:
                val = f"{float(item['value']):.4g}"
            except (TypeError, ValueError, KeyError):
                val = ""
            lines.append(f"| {inst} | {name} | {','.join(tags)} | {val} |")
            shown += 1
            if shown >= 80:
                lines.append("(örnek seri kesildi; max 80)")
                break
        return "\n".join(lines) + "\n"

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
