"""Darboğaz teşhisi — "VM mi yavaş, host mu yavaş?" (deterministik).

Neden ayrı bir katman: envanter ve trend araçları "ne oldu" sorusunu
cevaplıyor ("CPU %95", "gecikme 40 ms"), ama operatörün sorduğu şey genelde
"NEDEN ve KİM suçlu" oluyor. Bu çıkarımı modele bırakmak iki hataya yol
açıyor: (1) tek metriğe bakıp yanlış katmanı suçlamak ("CPU %95 → VM'e vCPU
ekle" — oysa host doygun ve ready %20), (2) sayı uydurmak.

Kural motoru VM ve HOST zaman serisini AYNI pencerede yan yana koyar ve
vSphere performans analizinin standart ayrım kurallarını uygular:

  * VM CPU ready yüksek + host CPU doygun   → HOST CPU çekişmesi (VM'e vCPU
    eklemek durumu KÖTÜLEŞTİRİR)
  * VM CPU ready yüksek + host CPU rahat    → VM'de fazla vCPU / co-stop
  * VM balloon/swap > 0 veya host mem yüksek→ HOST bellek baskısı
  * VM disk gecikmesi yüksek + host/DS de   → DEPOLAMA katmanı
  * VM disk gecikmesi yüksek + host rahat   → VM'e özel (guest/queue)
  * VM CPU yüksek + ready düşük             → VM'in KENDİ iş yükü (normal)

Her bulgu, kararı üreten SAYILARI da taşır; model yalnız Türkçeye çevirir.
Eşikler VMware'in yaygın kabul gören sınırlarıdır ve tek yerde tanımlıdır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Eşikler tek kaynak: kural metinleri ve çıktı notları buradan okur.
TH = {
    "cpu_ready_pct": 5.0,        # >%5 → CPU çekişmesi (VMware önerisi <%5)
    "cpu_costop_ms": 200.0,      # SMP çekişmesi
    "host_cpu_pct": 80.0,        # host doygunluk sınırı
    "host_mem_pct": 90.0,
    "vm_cpu_pct": 90.0,
    "disk_latency_ms": 20.0,     # >20 ms → depolama darboğazı
    "balloon_mb": 1.0,
    "swapped_mb": 1.0,
    "net_dropped": 1.0,
}

_VM_SQL = """
    SELECT hypervisor_id, vm_name,
           max(host_name)  AS host_name,
           max(cluster_name) AS cluster_name,
           max(datastore)  AS datastore,
           count(*)        AS samples,
           avg(cpu_usage_pct)  AS cpu_avg,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage_pct)  AS cpu_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY mem_usage_pct)  AS mem_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_ready_pct)  AS ready_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_costop_ms)  AS costop_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_latency_ms) AS dlat_p95,
           max(balloon_mb) AS balloon_max,
           max(swapped_mb) AS swapped_max,
           max(net_dropped_rx + net_dropped_tx) AS dropped_max,
           max(num_cpu)    AS num_cpu
    FROM virt_vm_metrics
    WHERE timestamp >= now() - (:hours * interval '1 hour')
      AND vm_name ILIKE :vm
    GROUP BY hypervisor_id, vm_name
    ORDER BY ready_p95 DESC NULLS LAST
    LIMIT :limit
"""

_HOST_SQL = """
    SELECT host_name, hypervisor_id,
           max(cluster_name) AS cluster_name,
           count(*)          AS samples,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_usage_pct) AS cpu_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY mem_usage_pct) AS mem_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY ds_usage_pct)  AS ds_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY cpu_ready_pct) AS ready_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_latency_ms) AS dlat_p95,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY disk_device_latency_ms) AS devlat_p95,
           max(mem_swap_used_mb) AS swap_max,
           max(mem_balloon_mb)   AS balloon_max,
           max(net_dropped_rx + net_dropped_tx) AS dropped_max,
           max(vms_running)  AS vms_running,
           max(cpu_threads)  AS cpu_threads
    FROM hypervisor_host_metrics
    WHERE timestamp >= now() - (:hours * interval '1 hour')
      AND host_name ILIKE :host
    GROUP BY hypervisor_id, host_name
    LIMIT 50
"""


def _f(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _gt(value: Optional[float], limit: float) -> bool:
    return value is not None and value > limit


def _classify_row(vm: Dict[str, Any], host: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Tek VM için katman kararı. host None ise yalnız VM kanıtı kullanılır."""
    findings: List[Dict[str, Any]] = []
    host = host or {}

    ready = vm.get("ready_p95")
    costop = vm.get("costop_p95")
    host_cpu = host.get("cpu_p95")
    host_mem = host.get("mem_p95")
    host_dlat = host.get("dlat_p95") or host.get("devlat_p95")

    # ── CPU ──────────────────────────────────────────────────────────────────
    if _gt(ready, TH["cpu_ready_pct"]):
        if _gt(host_cpu, TH["host_cpu_pct"]):
            findings.append({
                "layer": "host",
                "resource": "cpu",
                "severity": "high",
                "verdict": (
                    "Host CPU çekişmesi: VM CPU beklemede (ready) ve host CPU doygun."
                ),
                "action": (
                    "VM'e vCPU EKLEMEYİN — çekişmeyi artırır. VM'i daha rahat bir "
                    "host'a taşıyın veya host üzerindeki yoğunluğu azaltın."
                ),
                "evidence": {
                    "vm_cpu_ready_p95": ready, "host_cpu_p95": host_cpu,
                    "esik_ready_pct": TH["cpu_ready_pct"], "esik_host_cpu_pct": TH["host_cpu_pct"],
                },
            })
        else:
            findings.append({
                "layer": "vm",
                "resource": "cpu",
                "severity": "medium",
                "verdict": (
                    "VM tarafı CPU çekişmesi: ready yüksek ama host CPU rahat — "
                    "büyük olasılıkla VM'e gereğinden fazla vCPU verilmiş "
                    "(zamanlama/co-stop maliyeti)."
                ),
                "action": "vCPU sayısını düşürerek zamanlama maliyetini azaltın.",
                "evidence": {
                    "vm_cpu_ready_p95": ready, "host_cpu_p95": host_cpu,
                    "vm_cpu_costop_p95": costop, "vcpu": vm.get("num_cpu"),
                },
            })
    elif _gt(costop, TH["cpu_costop_ms"]):
        findings.append({
            "layer": "vm", "resource": "cpu", "severity": "medium",
            "verdict": "SMP çekişmesi: co-stop yüksek, vCPU'lar birbirini bekliyor.",
            "action": "vCPU sayısını azaltın veya NUMA hizalamasını gözden geçirin.",
            "evidence": {"vm_cpu_costop_p95": costop, "vcpu": vm.get("num_cpu")},
        })
    elif _gt(vm.get("cpu_p95"), TH["vm_cpu_pct"]):
        findings.append({
            "layer": "guest", "resource": "cpu", "severity": "medium",
            "verdict": (
                "VM'in KENDİ iş yükü CPU'yu doyuruyor (ready düşük — altyapı "
                "kaynağı bekletmiyor)."
            ),
            "action": "Uygulama tarafını inceleyin; gerekiyorsa vCPU ekleyin.",
            "evidence": {"vm_cpu_p95": vm.get("cpu_p95"), "vm_cpu_ready_p95": ready},
        })

    # ── Bellek ───────────────────────────────────────────────────────────────
    if _gt(vm.get("swapped_max"), TH["swapped_mb"]) or _gt(vm.get("balloon_max"), TH["balloon_mb"]):
        layer = "host" if _gt(host_mem, TH["host_mem_pct"]) else "vm"
        findings.append({
            "layer": layer, "resource": "memory", "severity": "high",
            "verdict": (
                "Bellek baskısı: VM balloon/swap görüyor"
                + (" ve host belleği doygun." if layer == "host" else ".")
            ),
            "action": (
                "Host üzerindeki bellek taahhüdünü düşürün (VM taşıyın / RAM ekleyin)."
                if layer == "host"
                else "VM'in bellek ayırma (reservation/limit) ayarlarını kontrol edin."
            ),
            "evidence": {
                "vm_balloon_mb_max": vm.get("balloon_max"),
                "vm_swapped_mb_max": vm.get("swapped_max"),
                "host_mem_p95": host_mem,
            },
        })

    # ── Depolama ─────────────────────────────────────────────────────────────
    if _gt(vm.get("dlat_p95"), TH["disk_latency_ms"]):
        layer = "datastore" if _gt(host_dlat, TH["disk_latency_ms"]) else "vm"
        findings.append({
            "layer": layer, "resource": "storage", "severity": "high",
            "verdict": (
                "Depolama gecikmesi eşik üstü; host/datastore seviyesinde de yüksek "
                "→ paylaşımlı depolama katmanı darboğaz."
                if layer == "datastore"
                else "Depolama gecikmesi bu VM'e özgü; host seviyesinde gecikme normal."
            ),
            "action": (
                "Datastore/LUN yoğunluğunu ve çoklu yol (multipathing) durumunu inceleyin."
                if layer == "datastore"
                else "VM'in disk kuyruğu, snapshot zinciri ve guest I/O desenini inceleyin."
            ),
            "evidence": {
                "vm_disk_latency_p95_ms": vm.get("dlat_p95"),
                "host_disk_latency_p95_ms": host_dlat,
                "esik_ms": TH["disk_latency_ms"],
                "datastore": vm.get("datastore"),
            },
        })

    # ── Ağ ───────────────────────────────────────────────────────────────────
    if _gt(vm.get("dropped_max"), TH["net_dropped"]):
        layer = "host" if _gt(host.get("dropped_max"), TH["net_dropped"]) else "vm"
        findings.append({
            "layer": layer, "resource": "network", "severity": "medium",
            "verdict": "Paket kaybı var" + (" — host uplink tarafında da görülüyor." if layer == "host" else "."),
            "action": (
                "Host uplink/vSwitch yoğunluğunu ve NIC durumunu inceleyin."
                if layer == "host" else "vNIC tipi ve guest sürücüsünü kontrol edin."
            ),
            "evidence": {
                "vm_dropped_max": vm.get("dropped_max"),
                "host_dropped_max": host.get("dropped_max"),
            },
        })

    if not findings:
        findings.append({
            "layer": "none", "resource": "-", "severity": "none",
            "verdict": "Ölçülen pencerede darboğaz kanıtı yok (tüm göstergeler eşik altında).",
            "action": "-",
            "evidence": {
                "vm_cpu_p95": vm.get("cpu_p95"), "vm_cpu_ready_p95": ready,
                "vm_disk_latency_p95_ms": vm.get("dlat_p95"), "host_cpu_p95": host_cpu,
            },
        })

    order = {"high": 0, "medium": 1, "none": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 3))
    return {
        "vm": vm.get("vm_name"),
        "host": vm.get("host_name"),
        "cluster": vm.get("cluster_name"),
        "datastore": vm.get("datastore"),
        "samples": vm.get("samples"),
        "host_samples": host.get("samples"),
        "primary_layer": findings[0]["layer"],
        "findings": findings,
    }


def classify_bottleneck(
    db: Session,
    *,
    vm_name: Optional[str] = None,
    host_name: Optional[str] = None,
    hours: float = 24,
    limit: int = 10,
) -> Dict[str, Any]:
    """VM/host zaman serisinden darboğaz katmanını sınıflandırır.

    vm_name verilirse o VM(ler), yoksa host_name'deki VM'ler incelenir. İkisi
    de yoksa ready süresi en yüksek VM'ler seçilir (fleet taraması).
    """
    window = max(0.25, min(float(hours or 24), 720.0))
    top = max(1, min(int(limit or 10), 50))
    vm_like = f"%{vm_name.strip()}%" if vm_name else "%"

    try:
        vm_rows = [
            dict(r._mapping)
            for r in db.execute(text(_VM_SQL), {"hours": window, "vm": vm_like, "limit": top})
        ]
    except Exception as e:
        logger.error("classify_bottleneck VM sorgusu: %s", e, exc_info=True)
        return {"ok": False, "error": f"VM zaman serisi okunamadı: {e}"}

    if host_name:
        needle = host_name.strip().lower()
        vm_rows = [r for r in vm_rows if needle in str(r.get("host_name") or "").lower()]

    if not vm_rows:
        return {
            "ok": True,
            "window_hours": window,
            "items": [],
            "note": (
                "Belirtilen kapsamda son {h} saatte VM metriği bulunamadı "
                "(VM adı yanlış olabilir veya metrik sync henüz çalışmamıştır)."
            ).format(h=window),
        }

    host_names = {str(r.get("host_name") or "").strip() for r in vm_rows}
    host_names.discard("")
    hosts: Dict[str, Dict[str, Any]] = {}
    for hn in host_names:
        try:
            rows = [
                dict(r._mapping)
                for r in db.execute(text(_HOST_SQL), {"hours": window, "host": hn})
            ]
        except Exception as e:
            logger.warning("classify_bottleneck host sorgusu (%s): %s", hn, e)
            rows = []
        for row in rows:
            key = f"{row.get('hypervisor_id')}|{str(row.get('host_name') or '').strip().lower()}"
            hosts[key] = {
                k: (_f(v) if k not in ("host_name", "cluster_name") else v)
                for k, v in row.items()
            }

    items = []
    for raw in vm_rows:
        vm = {
            k: (_f(v) if k not in ("vm_name", "host_name", "cluster_name", "datastore") else v)
            for k, v in raw.items()
        }
        host_key = f"{raw.get('hypervisor_id')}|{str(raw.get('host_name') or '').strip().lower()}"
        host = hosts.get(host_key)
        items.append(_classify_row(vm, host))

    host_only = not vm_rows and host_name
    return {
        "ok": True,
        "window_hours": window,
        "thresholds": dict(TH),
        "items": items,
        "methodology": (
            "Her VM için p95 değerleri hesaplanır ve AYNI pencerede çalıştığı "
            "host'un p95 değerleriyle karşılaştırılır. Katman kararı tek metrikle "
            "değil, VM+host çiftinin birlikte aşıp aşmadığına göre verilir "
            "(ör. ready>%5 VE host CPU>%80 → host çekişmesi; ready>%5 ama host "
            "CPU<%80 → VM'de fazla vCPU). Eşikler: "
            f"ready %{TH['cpu_ready_pct']}, host CPU %{TH['host_cpu_pct']}, "
            f"host RAM %{TH['host_mem_pct']}, disk gecikmesi {TH['disk_latency_ms']} ms."
        ),
        "scope": {"vm_name": vm_name, "host_name": host_name, "host_only": host_only},
    }
