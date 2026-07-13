"""
Altyapı Rapor Motoru — 20 farklı rapor üretir.

Her rapor fonksiyonu:
  - DB'den gerçek veri çeker
  - Yapılandırılmış JSON döner
  - LLM kullanmaz (hızlı + güvenilir)
  - `answer_report_question()` fonksiyonu LLM ile doğal dil özeti ekler

Rapor Tipleri
─────────────────────────────────────────────
executive_summary       Genel sağlık özeti
capacity                CPU/RAM/storage kapasitesi
risk                    Kritik riskler
vm_health               VM başına sağlık skoru
resource_usage          En çok kaynak tahsis edilen VM'ler (tahsisat, gerçek tüketim değil)
security_compliance     Tools, patch, versiyon uyum
consolidation           Boşta/kapalı VM'ler
lifecycle               HW/OS yaşam döngüsü
anomaly                 Anormal davranışlar
forecast                3/6/12 ay kapasite tahmini
sla                     Olay yoğunluğundan tahmini erişilebilirlik
operations              Operasyonel aktivite
performance_bottleneck  Darboğaz tespiti
riskiest_assets         En riskli varlıklar
business_impact         Servis etki analizi
finance                 Maliyet / showback (tahsisat bazlı)

Not: "backup", "dr_readiness" ve "chargeback" raporları kaldırıldı. İlk ikisi
gerçek backup/DR entegrasyonu (Veeam/SRM/vSphere HA verisi) olmadan anlamlı
veri üretemiyordu. "chargeback" ise departman ataması (Business Service Map)
tanımlanmadığı sürece "finance" raporuyla aynı hesabı tek bir "Genel" grubunda
tekrar ediyordu; departman ataması yapıldığında finance raporu zaten yeterli
görünürlüğü sağlıyor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Yardımcı: ESX host metrikleri ────────────────────────────────────────────

def _latest_host_metrics(db: Session) -> List[Dict]:
    rows = db.execute(text("""
        SELECT DISTINCT ON (host_name)
            host_name, hypervisor_id,
            cpu_usage_pct, cpu_usage_mhz, cpu_total_mhz, cpu_cores,
            mem_used_mb, mem_total_mb, mem_usage_pct,
            ds_used_gb, ds_total_gb, ds_usage_pct,
            net_rx_kbps, net_tx_kbps,
            vms_running, vms_total, connection_state, maintenance_mode,
            timestamp
        FROM hypervisor_host_metrics
        ORDER BY host_name, timestamp DESC
    """)).all()
    result = []
    for r in rows:
        result.append({
            "host": r.host_name,
            "hypervisor_id": r.hypervisor_id,
            "cpu_pct": round(r.cpu_usage_pct or 0, 1),
            "cpu_cores": r.cpu_cores or 0,
            "cpu_mhz_used": r.cpu_usage_mhz or 0,
            "cpu_mhz_total": r.cpu_total_mhz or 0,
            "mem_pct": round(r.mem_usage_pct or 0, 1),
            "mem_used_gb": round((r.mem_used_mb or 0) / 1024, 1),
            "mem_total_gb": round((r.mem_total_mb or 0) / 1024, 1),
            "mem_free_gb": round(((r.mem_total_mb or 0) - (r.mem_used_mb or 0)) / 1024, 1),
            "ds_pct": round(r.ds_usage_pct or 0, 1),
            "ds_used_gb": round(r.ds_used_gb or 0, 1),
            "ds_total_gb": round(r.ds_total_gb or 0, 1),
            "ds_free_gb": round((r.ds_total_gb or 0) - (r.ds_used_gb or 0), 1),
            "net_rx_kbps": r.net_rx_kbps or 0,
            "net_tx_kbps": r.net_tx_kbps or 0,
            "vms_running": r.vms_running or 0,
            "vms_total": r.vms_total or 0,
            "state": r.connection_state,
            "maintenance": bool(r.maintenance_mode),
            "last_update": r.timestamp.isoformat() if r.timestamp else None,
        })
    return result


def _get_vms(db: Session) -> List[Dict]:
    from app.models.server import Server
    from app.models.hypervisor import Hypervisor
    vms = db.query(Server).filter(
        or_(
            Server.hypervisor_id.isnot(None),
            Server.server_type == "VIRTUAL",
        )
    ).all()
    hvs = {hv.id: hv.name for hv in db.query(Hypervisor).all()}
    result = []
    for v in vms:
        result.append({
            "id": v.id,
            "name": v.name,
            "ip": v.ip_address or v.vm_guest_ip or "",
            "hypervisor": hvs.get(v.hypervisor_id, "?"),
            "os_type": v.os_type or "",
            "os_version": v.os_version or "",
            "os_release": v.os_release_id or "",
            "cpu_count": v.vm_cpu_count or v.cpu_cores or 0,
            "memory_gb": round((v.vm_memory_mb or 0) / 1024, 1) if v.vm_memory_mb else (v.memory_gb or 0),
            "memory_mb": v.vm_memory_mb or 0,
            "disk_gb": v.vm_disk_gb or 0,
            "power_state": v.vm_power_state or "unknown",
            "tools_status": v.vm_tools_status or "unknown",
            "hw_version": v.vm_hardware_version or "",
            "cluster": v.vm_cluster or "",
            "datastore": v.vm_datastore or "",
            "tier": getattr(v, "tier", "unknown") or "unknown",
            "last_sync": v.vm_last_sync.isoformat() if v.vm_last_sync else None,
            "ai_ready": v.ai_ready,
        })
    return result


def _get_active_events(db: Session, days: int = 7) -> List[Dict]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(text("""
        SELECT e.id, e.server_id, s.name as server_name,
               e.event_type, e.title, e.severity,
               e.created_at, e.occurrence_count
        FROM system_events e
        LEFT JOIN servers s ON e.server_id = s.id
        WHERE e.is_known=false AND e.is_acknowledged=false
          AND e.created_at >= :since
        ORDER BY
          CASE e.severity
            WHEN 'critical' THEN 1 WHEN 'error' THEN 2
            WHEN 'warning' THEN 3 ELSE 4 END,
          e.created_at DESC
        LIMIT 200
    """), {"since": since}).all()
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "server_id": r.server_id,
            "server": r.server_name,
            "type": r.event_type,
            "title": r.title,
            "severity": r.severity,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "occurrences": r.occurrence_count or 1,
        })
    return result


def _get_virt_platform_events(db: Session, days: int = 30) -> List[Dict]:
    """Sanallaştırma platformu olayları (virt_collector / virt_resource kaynaklı)."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(text("""
        SELECT e.id, e.server_id, s.name as server_name,
               e.event_type, e.title, e.severity, e.source,
               e.created_at, e.occurrence_count, e.raw_data
        FROM system_events e
        LEFT JOIN servers s ON e.server_id = s.id
        WHERE e.created_at >= :since
          AND (
            e.source IN ('virt_collector', 'virt_resource', 'vcenter_event', 'vcenter_alarm', 'vcenter_task')
            OR e.event_type IN ('virt_log', 'virt_resource', 'vcenter_event', 'vcenter_alarm', 'vcenter_task')
          )
        ORDER BY e.created_at DESC
        LIMIT 300
    """), {"since": since}).all()
    result = []
    for r in rows:
        raw = r.raw_data or {}
        result.append({
            "id": r.id,
            "server_id": r.server_id,
            "server": r.server_name or raw.get("host_name") or "Platform",
            "type": r.event_type,
            "title": r.title,
            "severity": r.severity,
            "source": r.source,
            "action": raw.get("action"),
            "actor": raw.get("actor"),
            "hypervisor_id": raw.get("hypervisor_id"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "occurrences": r.occurrence_count or 1,
        })
    return result


def _detect_host_metric_anomalies(db: Session) -> List[Dict]:
    """Son 24 saatte baseline'a göre anormal host metrik artışları."""
    rows = db.execute(text("""
        WITH recent AS (
            SELECT host_name,
                   MAX(cpu_usage_pct) AS peak_cpu,
                   MAX(mem_usage_pct) AS peak_mem,
                   MAX(ds_usage_pct) AS peak_ds
            FROM hypervisor_host_metrics
            WHERE timestamp >= NOW() - INTERVAL '24 hours'
            GROUP BY host_name
        ),
        baseline AS (
            SELECT host_name,
                   AVG(cpu_usage_pct) AS avg_cpu,
                   AVG(mem_usage_pct) AS avg_mem,
                   AVG(ds_usage_pct) AS avg_ds
            FROM hypervisor_host_metrics
            WHERE timestamp >= NOW() - INTERVAL '7 days'
            GROUP BY host_name
        )
        SELECT r.host_name,
               r.peak_cpu, b.avg_cpu,
               r.peak_mem, b.avg_mem,
               r.peak_ds, b.avg_ds
        FROM recent r
        JOIN baseline b ON r.host_name = b.host_name
    """)).all()

    anomalies = []
    for r in rows:
        issues = []
        avg_cpu = float(r.avg_cpu or 0)
        avg_mem = float(r.avg_mem or 0)
        avg_ds = float(r.avg_ds or 0)
        peak_cpu = float(r.peak_cpu or 0)
        peak_mem = float(r.peak_mem or 0)
        peak_ds = float(r.peak_ds or 0)

        if avg_cpu >= 5 and peak_cpu >= max(85, avg_cpu * 1.45):
            issues.append(f"CPU spike (%{round(peak_cpu, 1)} vs ort. %{round(avg_cpu, 1)})")
        if avg_mem >= 5 and peak_mem >= max(85, avg_mem * 1.35):
            issues.append(f"RAM spike (%{round(peak_mem, 1)} vs ort. %{round(avg_mem, 1)})")
        if avg_ds >= 5 and peak_ds >= max(80, avg_ds * 1.25):
            issues.append(f"Disk spike (%{round(peak_ds, 1)} vs ort. %{round(avg_ds, 1)})")

        if issues:
            anomalies.append({
                "host": r.host_name,
                "issues": issues,
                "peak_cpu_pct": round(peak_cpu, 1),
                "avg_cpu_pct": round(avg_cpu, 1),
                "peak_mem_pct": round(peak_mem, 1),
                "avg_mem_pct": round(avg_mem, 1),
                "severity": "Kritik" if any("RAM" in i or "CPU" in i for i in issues) else "Uyarı",
            })

    anomalies.sort(key=lambda x: -(len(x["issues"]) * 10 + x["peak_cpu_pct"]))
    return anomalies[:20]


def _report_data_quality(db: Session) -> Dict[str, Any]:
    """Rapor güvenilirliği için envanter ve metrik tazeliği özeti."""
    from app.models.server import Server
    from app.models.hypervisor import Hypervisor

    virtual_servers = db.query(Server).filter(
        or_(
            Server.hypervisor_id.isnot(None),
            Server.server_type == "VIRTUAL",
        )
    ).all()
    total_vms = len(virtual_servers)
    with_hypervisor = sum(1 for v in virtual_servers if v.hypervisor_id)
    with_disk = sum(1 for v in virtual_servers if v.vm_disk_gb)
    with_tools = sum(1 for v in virtual_servers if v.vm_tools_status)
    with_datastore = sum(1 for v in virtual_servers if v.vm_datastore)
    stale_cutoff = datetime.utcnow() - timedelta(hours=24)
    stale_sync = sum(
        1 for v in virtual_servers
        if not v.vm_last_sync or v.vm_last_sync.replace(tzinfo=None) < stale_cutoff
    )

    hosts = _latest_host_metrics(db)
    last_host_metric = None
    for h in hosts:
        ts = h.get("last_update")
        if ts and (last_host_metric is None or ts > last_host_metric):
            last_host_metric = ts

    hypervisors = db.query(Hypervisor).all()
    hv_sync_info = []
    for hv in hypervisors:
        hv_sync_info.append({
            "name": hv.name,
            "type": hv.hypervisor_type.value if hv.hypervisor_type else "",
            "last_sync": hv.last_sync.isoformat() if hv.last_sync else None,
        })

    meta_fields = 4
    meta_score = 0
    if total_vms:
        meta_score = round(
            (
                (with_hypervisor / total_vms)
                + (with_disk / total_vms)
                + (with_tools / total_vms)
                + (with_datastore / total_vms)
            ) / meta_fields * 100,
            1,
        )

    warnings: List[str] = []
    if total_vms == 0:
        warnings.append("Envanterde sanal sunucu yok — hypervisor VM senkronizasyonu çalıştırın.")
    elif with_hypervisor < total_vms * 0.8:
        warnings.append(f"{total_vms - with_hypervisor} VM hypervisor ile eşleşmemiş.")
    if total_vms and with_disk < total_vms * 0.5:
        warnings.append("Disk tahsisat bilgisi eksik — VM detay zenginleştirmesi gerekli.")
    if not hosts:
        warnings.append("Host metrikleri yok — yalnızca VMware ESX metrik senkronu desteklenir.")
    elif stale_sync > total_vms * 0.3 and total_vms:
        warnings.append(f"{stale_sync} VM'in detay senkronu 24 saatten eski.")

    if meta_score >= 80 and hosts and not warnings:
        quality_level = "İyi"
    elif meta_score >= 55 or hosts:
        quality_level = "Orta"
    else:
        quality_level = "Düşük"

    return {
        "vm_total": total_vms,
        "vm_with_hypervisor_pct": round(with_hypervisor / total_vms * 100, 1) if total_vms else 0,
        "vm_metadata_completeness_pct": meta_score,
        "vm_missing_disk_count": total_vms - with_disk,
        "vm_missing_tools_count": total_vms - with_tools,
        "vm_stale_sync_count": stale_sync,
        "host_metrics_hosts": len(hosts),
        "last_host_metric_at": last_host_metric,
        "hypervisor_sync": hv_sync_info,
        "warnings": warnings,
        "quality_level": quality_level,
    }


def _build_executive_recommendations(
    hosts: List[Dict],
    vms: List[Dict],
    events: List[Dict],
    data_quality: Dict[str, Any],
) -> List[str]:
    recs: List[str] = []
    critical_cnt = sum(1 for e in events if e["severity"] in ("critical", "error"))

    if data_quality.get("quality_level") == "Düşük":
        recs.append("Envanter kalitesi düşük — hypervisor VM sync ve detay zenginleştirmesini çalıştırın.")
    if not hosts:
        recs.append("Kapasite/tahmin raporları için ESX host metrik senkronizasyonunu etkinleştirin.")
    if critical_cnt > 0:
        recs.append(f"{critical_cnt} aktif kritik olay var — Virt AIOps olay merkezini inceleyin.")
    high_mem = [h for h in hosts if h["mem_pct"] > 85]
    if high_mem:
        recs.append(f"{len(high_mem)} host bellek baskısı altında — kapasite planlaması yapın.")
    no_tools = [
        v for v in vms
        if v["power_state"] in ("POWERED_ON", "up", "running", "poweredOn")
        and (not v["tools_status"] or "running" not in (v["tools_status"] or "").lower())
    ]
    if no_tools:
        recs.append(f"{len(no_tools)} çalışan VM'de guest tools eksik — güvenlik/uyumluluk riski.")
    powered_off = [v for v in vms if v["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn")]
    if len(powered_off) >= 5:
        recs.append(f"{len(powered_off)} kapalı VM — konsolidasyon raporu ile kaynak geri kazanımı değerlendirin.")
    if not recs:
        recs.append("Kritik bulgu yok — mevcut kapasite ve uyumluluk seviyesi korunuyor.")
    return recs[:8]


# ─────────────────────────────────────────────────────────────────────────────
# RAPOR FONKSİYONLARI
# ─────────────────────────────────────────────────────────────────────────────

def generate_executive_summary(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)
    vms = _get_vms(db)
    events = _get_active_events(db, days=7)

    critical_cnt = sum(1 for e in events if e["severity"] in ("critical", "error"))
    warning_cnt = sum(1 for e in events if e["severity"] == "warning")
    powered_on = [v for v in vms if v["power_state"] in ("POWERED_ON", "up", "running", "poweredOn")]
    powered_off = [v for v in vms if v not in powered_on]

    avg_cpu = round(sum(h["cpu_pct"] for h in hosts) / len(hosts), 1) if hosts else 0
    avg_mem = round(sum(h["mem_pct"] for h in hosts) / len(hosts), 1) if hosts else 0
    avg_ds = round(sum(h["ds_pct"] for h in hosts) / len(hosts), 1) if hosts else 0

    risk_level = "Kritik" if critical_cnt > 5 else ("Yüksek" if critical_cnt > 0 else "Normal")
    data_quality = _report_data_quality(db)
    recommendations = _build_executive_recommendations(hosts, vms, events, data_quality)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "risk_level": risk_level,
        "infrastructure": {
            "host_count": len(hosts),
            "vm_total": len(vms),
            "vm_powered_on": len(powered_on),
            "vm_powered_off": len(powered_off),
        },
        "utilization": {
            "avg_cpu_pct": avg_cpu,
            "avg_mem_pct": avg_mem,
            "avg_storage_pct": avg_ds,
            "highest_cpu_host": max(hosts, key=lambda h: h["cpu_pct"])["host"] if hosts else "-",
            "highest_mem_host": max(hosts, key=lambda h: h["mem_pct"])["host"] if hosts else "-",
        },
        "health": {
            "active_critical_events": critical_cnt,
            "active_warning_events": warning_cnt,
            "hosts_in_maintenance": sum(1 for h in hosts if h["maintenance"]),
            "hosts_disconnected": sum(1 for h in hosts if h["state"] != "connected"),
        },
        "recommendations": recommendations,
        "data_quality": data_quality,
        "hosts_detail": hosts,
    }


def generate_capacity_report(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)

    # 30 günlük trend hesapla
    trend_rows = db.execute(text("""
        SELECT host_name,
               AVG(cpu_usage_pct) as avg_cpu,
               AVG(mem_usage_pct) as avg_mem,
               AVG(ds_usage_pct) as avg_ds,
               MIN(cpu_usage_pct) as min_cpu,
               MAX(cpu_usage_pct) as max_cpu
        FROM hypervisor_host_metrics
        WHERE timestamp >= NOW() - INTERVAL '30 days'
        GROUP BY host_name
    """)).all()
    trend_map = {r.host_name: r for r in trend_rows}

    # 90 günlük büyüme oranı (linear regression basiti)
    growth_rows = db.execute(text("""
        SELECT host_name,
               CORR(EXTRACT(EPOCH FROM timestamp), ds_usage_pct) as ds_corr,
               REGR_SLOPE(ds_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as ds_daily_growth,
               REGR_SLOPE(mem_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as mem_daily_growth,
               REGR_SLOPE(cpu_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as cpu_daily_growth
        FROM hypervisor_host_metrics
        WHERE timestamp >= NOW() - INTERVAL '90 days'
        GROUP BY host_name
    """)).all()
    growth_map = {r.host_name: r for r in growth_rows}

    capacity_items = []
    for h in hosts:
        trend = trend_map.get(h["host"])
        growth = growth_map.get(h["host"])

        ds_daily = (growth.ds_daily_growth or 0) if growth else 0
        mem_daily = (growth.mem_daily_growth or 0) if growth else 0

        # Kaç günde %80 kapasiteye ulaşır?
        days_to_ds_80 = int((80 - h["ds_pct"]) / ds_daily) if ds_daily > 0.001 else None
        days_to_mem_80 = int((80 - h["mem_pct"]) / mem_daily) if mem_daily > 0.001 else None

        status = "Kritik" if h["mem_pct"] > 85 or h["ds_pct"] > 85 else (
            "Uyarı" if h["mem_pct"] > 70 or h["ds_pct"] > 70 else "Normal"
        )

        capacity_items.append({
            "host": h["host"],
            "cpu": {
                "used_pct": h["cpu_pct"],
                "cores": h["cpu_cores"],
                "avg_30d": round(trend.avg_cpu or 0, 1) if trend else None,
                "daily_growth_pct": round(growth.cpu_daily_growth or 0, 4) if growth else 0,
            },
            "memory": {
                "used_pct": h["mem_pct"],
                "used_gb": h["mem_used_gb"],
                "total_gb": h["mem_total_gb"],
                "free_gb": h["mem_free_gb"],
                "avg_30d": round(trend.avg_mem or 0, 1) if trend else None,
                "daily_growth_pct": round(mem_daily, 4),
                "days_to_80pct": days_to_mem_80,
            },
            "storage": {
                "used_pct": h["ds_pct"],
                "used_gb": h["ds_used_gb"],
                "total_gb": h["ds_total_gb"],
                "free_gb": h["ds_free_gb"],
                "avg_30d": round(trend.avg_ds or 0, 1) if trend else None,
                "daily_growth_pct": round(ds_daily, 4),
                "days_to_80pct": days_to_ds_80,
            },
            "status": status,
            "vms_running": h["vms_running"],
            "vms_total": h["vms_total"],
        })

    warnings = []
    for item in capacity_items:
        if item["memory"]["days_to_80pct"] and item["memory"]["days_to_80pct"] < 30:
            warnings.append(f"{item['host']} belleği {item['memory']['days_to_80pct']} gün içinde %80'e ulaşacak")
        if item["storage"]["days_to_80pct"] and item["storage"]["days_to_80pct"] < 30:
            warnings.append(f"{item['host']} diski {item['storage']['days_to_80pct']} gün içinde %80'e ulaşacak")

    # VM bazında disk tahsisatı — datastore varsa datastore, yoksa hypervisor adına göre grupla
    vms = _get_vms(db)
    ds_vm_breakdown: Dict[str, Any] = {}
    for vm in vms:
        ds = (vm.get("datastore") or "").strip()
        # datastore yoksa hypervisor adını kullan (grup kimliği olarak)
        group_key = ds if ds else f"Hypervisor: {vm.get('hypervisor','Bilinmiyor')}"
        if group_key not in ds_vm_breakdown:
            ds_vm_breakdown[group_key] = {"vm_count": 0, "allocated_disk_gb": 0.0, "vms": [], "is_hypervisor_group": not bool(ds)}
        ds_vm_breakdown[group_key]["vm_count"] += 1
        ds_vm_breakdown[group_key]["allocated_disk_gb"] += float(vm.get("disk_gb") or 0)
        ds_vm_breakdown[group_key]["vms"].append({
            "vm": vm["name"],
            "disk_gb": vm.get("disk_gb") or 0,
            "power_state": vm["power_state"],
            "cluster": vm.get("cluster") or "",
        })

    # Sıralı ve top-VM eklendi
    for ds_key in ds_vm_breakdown:
        entry = ds_vm_breakdown[ds_key]
        entry["allocated_disk_gb"] = round(entry["allocated_disk_gb"], 1)
        entry["vms"] = sorted(entry["vms"], key=lambda x: -(x["disk_gb"] or 0))[:20]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "capacity_items": capacity_items,
        "warnings": warnings,
        "datastore_vm_disk": ds_vm_breakdown,
        "overall_status": "Kritik" if any(i["status"] == "Kritik" for i in capacity_items) else (
            "Uyarı" if any(i["status"] == "Uyarı" for i in capacity_items) else "Normal"
        ),
    }


def generate_risk_dashboard(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)
    vms = _get_vms(db)
    events = _get_active_events(db, days=7)

    # Yüksek kullanım riski
    high_cpu_hosts = [h for h in hosts if h["cpu_pct"] > 80]
    high_mem_hosts = [h for h in hosts if h["mem_pct"] > 85]
    high_ds_hosts = [h for h in hosts if h["ds_pct"] > 80]

    # VMware Tools yüklü olmayan powered-on VM'ler
    no_tools_vms = [v for v in vms
                    if v["power_state"] in ("POWERED_ON", "up", "running")
                    and (not v["tools_status"] or "running" not in (v["tools_status"] or "").lower())]

    # Bakım modundaki hostlar
    maintenance_hosts = [h for h in hosts if h["maintenance"]]

    # En çok kritik event olan sunucular
    server_event_counts: Dict[str, int] = {}
    for e in events:
        if e["severity"] in ("critical", "error") and e["server"]:
            server_event_counts[e["server"]] = server_event_counts.get(e["server"], 0) + 1
    top_alarm_servers = sorted(server_event_counts.items(), key=lambda x: -x[1])[:10]

    # Risk skoru (0–100)
    risk_score = min(100, (
        len(high_mem_hosts) * 20 +
        len(high_cpu_hosts) * 10 +
        len(high_ds_hosts) * 15 +
        sum(1 for e in events if e["severity"] in ("critical", "error")) * 2
    ))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "risk_score": risk_score,
        "risk_level": "Kritik" if risk_score > 60 else ("Yüksek" if risk_score > 30 else "Normal"),
        "risks": {
            "high_cpu_hosts": [{"host": h["host"], "cpu_pct": h["cpu_pct"]} for h in high_cpu_hosts],
            "high_memory_hosts": [{"host": h["host"], "mem_pct": h["mem_pct"], "free_gb": h["mem_free_gb"]} for h in high_mem_hosts],
            "high_storage_hosts": [{"host": h["host"], "ds_pct": h["ds_pct"], "free_gb": h["ds_free_gb"]} for h in high_ds_hosts],
            "no_tools_vms": [{"vm": v["name"], "os": v["os_type"]} for v in no_tools_vms[:20]],
            "maintenance_hosts": [h["host"] for h in maintenance_hosts],
            "top_alarm_servers": [{"server": s, "events": c} for s, c in top_alarm_servers],
        },
        "critical_event_count": sum(1 for e in events if e["severity"] in ("critical", "error")),
        "warning_event_count": sum(1 for e in events if e["severity"] == "warning"),
    }


def generate_vm_health_scores(db: Session) -> Dict[str, Any]:
    vms = _get_vms(db)
    events = _get_active_events(db, days=7)

    # Sunucu başına event sayısı
    server_events: Dict[int, List] = {}
    for e in events:
        sid = e.get("server_id")
        if sid:
            server_events.setdefault(sid, []).append(e)

    scored = []
    for vm in vms:
        score = 100
        issues = []

        # Güç durumu
        if vm["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn"):
            score -= 20
            issues.append("VM kapalı")

        # Tools durumu
        tools = (vm["tools_status"] or "").lower()
        if "running" not in tools:
            score -= 15
            issues.append("VMware Tools çalışmıyor")
        elif "old" in tools:
            score -= 5
            issues.append("VMware Tools güncel değil")

        # Aktif event'ler
        vm_evs = server_events.get(vm["id"], [])
        crit = sum(1 for e in vm_evs if e["severity"] in ("critical", "error"))
        warn = sum(1 for e in vm_evs if e["severity"] == "warning")
        score -= min(30, crit * 10 + warn * 3)
        if crit:
            issues.append(f"{crit} kritik olay")
        if warn:
            issues.append(f"{warn} uyarı olayı")

        # HW versiyonu
        hw = vm.get("hw_version", "")
        if hw:
            try:
                ver = int(hw.replace("VMX_", "").replace("vmx-", ""))
                if ver < 14:
                    score -= 10
                    issues.append(f"Eski HW versiyonu ({hw})")
            except Exception:
                pass

        score = max(0, score)
        grade = "A" if score >= 90 else ("B" if score >= 75 else ("C" if score >= 60 else ("D" if score >= 40 else "F")))

        scored.append({
            "vm": vm["name"],
            "id": vm["id"],
            "hypervisor": vm["hypervisor"],
            "score": score,
            "grade": grade,
            "issues": issues,
            "power_state": vm["power_state"],
            "tools_status": vm["tools_status"],
            "tier": vm["tier"],
        })

    scored.sort(key=lambda x: x["score"])

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "total_vms": len(scored),
        "avg_score": round(sum(v["score"] for v in scored) / len(scored), 1) if scored else 0,
        "grade_distribution": {
            g: sum(1 for v in scored if v["grade"] == g)
            for g in ["A", "B", "C", "D", "F"]
        },
        "vm_scores": scored,
        "critical_vms": [v for v in scored if v["grade"] in ("D", "F")],
    }


def generate_resource_usage_report(db: Session) -> Dict[str, Any]:
    vms = _get_vms(db)
    powered_on = [v for v in vms if v["power_state"] in ("POWERED_ON", "up", "running", "poweredOn")]

    top_cpu = sorted(powered_on, key=lambda v: -(v["cpu_count"] or 0))[:10]
    top_ram = sorted(powered_on, key=lambda v: -(v["memory_gb"] or 0))[:10]
    top_disk = sorted(powered_on, key=lambda v: -(v["disk_gb"] or 0))[:10]

    total_allocated_cpu = sum(v["cpu_count"] or 0 for v in powered_on)
    total_allocated_ram = sum(v["memory_gb"] or 0 for v in powered_on)
    total_allocated_disk = sum(v["disk_gb"] or 0 for v in powered_on)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "powered_on_vms": len(powered_on),
            "total_allocated_vcpu": total_allocated_cpu,
            "total_allocated_ram_gb": round(total_allocated_ram, 1),
            "total_allocated_disk_gb": round(total_allocated_disk, 1),
        },
        "top_cpu_consumers": [
            {"vm": v["name"], "vcpu": v["cpu_count"], "hypervisor": v["hypervisor"]}
            for v in top_cpu
        ],
        "top_ram_consumers": [
            {"vm": v["name"], "ram_gb": v["memory_gb"], "hypervisor": v["hypervisor"]}
            for v in top_ram
        ],
        "top_disk_consumers": [
            {"vm": v["name"], "disk_gb": v["disk_gb"], "hypervisor": v["hypervisor"]}
            for v in top_disk
        ],
    }


def generate_security_compliance_report(db: Session) -> Dict[str, Any]:
    vms = _get_vms(db)
    hosts = _latest_host_metrics(db)

    no_tools = [v for v in vms
                if not v["tools_status"] or "running" not in (v["tools_status"] or "").lower()]
    tools_ok = [v for v in vms if v not in no_tools]

    # HW versiyon dağılımı
    hw_versions: Dict[str, int] = {}
    for v in vms:
        hw = v.get("hw_version") or "Bilinmiyor"
        hw_versions[hw] = hw_versions.get(hw, 0) + 1

    # OS dağılımı
    os_dist: Dict[str, int] = {}
    for v in vms:
        os_key = v.get("os_release") or v.get("os_type") or "Bilinmiyor"
        os_dist[os_key] = os_dist.get(os_key, 0) + 1

    powered_on_no_tools = [v for v in no_tools if v["power_state"] in ("POWERED_ON", "up", "running")]

    compliance_score = 100
    issues = []
    if powered_on_no_tools:
        compliance_score -= min(40, len(powered_on_no_tools) * 5)
        issues.append(f"{len(powered_on_no_tools)} çalışan VM'de VMware Tools yüklü değil/çalışmıyor")

    old_hw = [v for v in vms if v.get("hw_version") and
              any(v["hw_version"].endswith(f"_{n}") or f"vmx-{n}" in v["hw_version"].lower()
                  for n in [str(x) for x in range(10, 14)])]
    if old_hw:
        compliance_score -= min(20, len(old_hw) * 3)
        issues.append(f"{len(old_hw)} VM'de eski HW versiyonu (< vmx-14)")

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "compliance_score": max(0, compliance_score),
        "issues": issues,
        "vmware_tools": {
            "compliant_count": len(tools_ok),
            "non_compliant_count": len(no_tools),
            "powered_on_non_compliant": len(powered_on_no_tools),
            "compliance_pct": round(len(tools_ok) / len(vms) * 100, 1) if vms else 0,
            "non_compliant_vms": [{"vm": v["name"], "state": v["power_state"]} for v in powered_on_no_tools[:20]],
        },
        "hw_version_distribution": hw_versions,
        "os_distribution": os_dist,
        "host_count": len(hosts),
    }


def generate_consolidation_report(db: Session) -> Dict[str, Any]:
    vms = _get_vms(db)

    powered_off = [v for v in vms if v["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn")]
    low_cpu = [v for v in vms
               if v["power_state"] in ("POWERED_ON", "up", "running", "poweredOn")
               and (v["cpu_count"] or 0) >= 8]  # Yüksek vCPU ataması

    # Toplam kaynak israfı (kapalı VM'lerin tahsisatı)
    wasted_vcpu = sum(v["cpu_count"] or 0 for v in powered_off)
    wasted_ram = sum(v["memory_gb"] or 0 for v in powered_off)
    wasted_disk = sum(v["disk_gb"] or 0 for v in powered_off)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "powered_off_vms": {
            "count": len(powered_off),
            "wasted_vcpu": wasted_vcpu,
            "wasted_ram_gb": round(wasted_ram, 1),
            "wasted_disk_gb": round(wasted_disk, 1),
            "vms": [{"vm": v["name"], "cpu": v["cpu_count"], "ram_gb": v["memory_gb"], "disk_gb": v["disk_gb"]}
                    for v in powered_off[:30]],
        },
        "oversized_vms": {
            "count": len(low_cpu),
            "vms": [{"vm": v["name"], "cpu": v["cpu_count"], "ram_gb": v["memory_gb"]}
                    for v in sorted(low_cpu, key=lambda x: -(x["cpu_count"] or 0))[:20]],
        },
        "consolidation_potential": {
            "reclaimable_vcpu": wasted_vcpu,
            "reclaimable_ram_gb": round(wasted_ram, 1),
            "reclaimable_disk_gb": round(wasted_disk, 1),
        },
    }


def generate_lifecycle_report(db: Session) -> Dict[str, Any]:
    vms = _get_vms(db)

    hw_age_map = {
        "VMX_20": "2023+", "VMX_19": "2021-2023",
        "VMX_18": "2019-2021", "VMX_17": "2018-2019",
        "VMX_16": "2017-2018", "VMX_15": "2016-2017",
        "VMX_14": "2015-2016",
    }
    old_threshold = 14  # vmx-14 öncesi "eski" sayılır

    hw_dist: Dict[str, List] = {}
    old_hw_vms = []
    unknown_hw_vms = []

    for v in vms:
        hw = v.get("hw_version") or ""
        hw_dist.setdefault(hw or "Bilinmiyor", []).append(v["name"])
        if hw:
            try:
                ver = int(hw.upper().replace("VMX_", "").replace("VMX-", ""))
                if ver < old_threshold:
                    old_hw_vms.append({"vm": v["name"], "hw_version": hw, "era": hw_age_map.get(hw, "Eski")})
            except Exception:
                unknown_hw_vms.append(v["name"])
        else:
            unknown_hw_vms.append(v["name"])

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "hw_version_distribution": {k: len(v) for k, v in hw_dist.items()},
        "old_hw_vms": {
            "count": len(old_hw_vms),
            "threshold": f"vmx-{old_threshold}",
            "vms": old_hw_vms[:30],
        },
        "unknown_hw_vms": len(unknown_hw_vms),
        "total_vms": len(vms),
        "upgrade_needed_pct": round(len(old_hw_vms) / len(vms) * 100, 1) if vms else 0,
    }


def generate_anomaly_report(db: Session) -> Dict[str, Any]:
    events = _get_active_events(db, days=14)
    virt_events = _get_virt_platform_events(db, days=14)
    metric_anomalies = _detect_host_metric_anomalies(db)

    # Sunucu başına olay yoğunluğu
    server_agg: Dict[str, Dict] = {}
    for e in events + virt_events:
        key = e.get("server") or "Bilinmiyor"
        if key not in server_agg:
            server_agg[key] = {"server": key, "critical": 0, "warning": 0, "total": 0, "types": set()}
        server_agg[key]["total"] += 1
        server_agg[key]["types"].add(e.get("type", ""))
        if e["severity"] in ("critical", "error", "emergency"):
            server_agg[key]["critical"] += 1
        elif e["severity"] == "warning":
            server_agg[key]["warning"] += 1

    anomalies = sorted(
        [{"server": v["server"], "critical": v["critical"], "warning": v["warning"],
          "total": v["total"], "event_types": list(v["types"])}
         for v in server_agg.values()],
        key=lambda x: -(x["critical"] * 10 + x["warning"])
    )[:20]

    # Tekrarlayan event tipleri
    type_counts: Dict[str, int] = {}
    for e in events + virt_events:
        t = e.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": 14,
        "total_events": len(events) + len(virt_events),
        "critical_count": sum(
            1 for e in events + virt_events if e["severity"] in ("critical", "error", "emergency")
        ),
        "warning_count": sum(1 for e in events + virt_events if e["severity"] == "warning"),
        "top_anomaly_servers": anomalies,
        "top_event_types": [{"type": t, "count": c} for t, c in top_types],
        "host_metric_anomalies": metric_anomalies,
        "virt_platform_events": len(virt_events),
        "analysis_note": (
            "Olay anomalileri system_events + sanallaştırma platform loglarından; "
            "host metrik anomalileri son 24 saat vs 7 gün ortalamasından türetilir."
        ),
    }


def generate_forecast_report(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)

    # 90 günlük büyüme trendi
    growth_rows = db.execute(text("""
        SELECT host_name,
               REGR_SLOPE(ds_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as ds_daily,
               REGR_SLOPE(mem_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as mem_daily,
               REGR_SLOPE(cpu_usage_pct, EXTRACT(EPOCH FROM timestamp)) * 86400 as cpu_daily
        FROM hypervisor_host_metrics
        WHERE timestamp >= NOW() - INTERVAL '90 days'
        GROUP BY host_name
    """)).all()
    growth_map = {r.host_name: r for r in growth_rows}

    def project(current_pct: float, daily_growth: float, days: int) -> float:
        return round(min(100, current_pct + daily_growth * days), 1)

    forecasts = []
    for h in hosts:
        g = growth_map.get(h["host"])
        if not g:
            continue
        ds_d = g.ds_daily or 0
        mem_d = g.mem_daily or 0
        cpu_d = g.cpu_daily or 0

        forecasts.append({
            "host": h["host"],
            "current": {
                "cpu_pct": h["cpu_pct"],
                "mem_pct": h["mem_pct"],
                "ds_pct": h["ds_pct"],
            },
            "forecast_3m": {
                "cpu_pct": project(h["cpu_pct"], cpu_d, 90),
                "mem_pct": project(h["mem_pct"], mem_d, 90),
                "ds_pct": project(h["ds_pct"], ds_d, 90),
            },
            "forecast_6m": {
                "cpu_pct": project(h["cpu_pct"], cpu_d, 180),
                "mem_pct": project(h["mem_pct"], mem_d, 180),
                "ds_pct": project(h["ds_pct"], ds_d, 180),
            },
            "forecast_12m": {
                "cpu_pct": project(h["cpu_pct"], cpu_d, 365),
                "mem_pct": project(h["mem_pct"], mem_d, 365),
                "ds_pct": project(h["ds_pct"], ds_d, 365),
            },
            "daily_growth": {
                "cpu_pct_per_day": round(cpu_d, 4),
                "mem_pct_per_day": round(mem_d, 4),
                "ds_pct_per_day": round(ds_d, 4),
            },
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "forecasts": forecasts,
        "investment_needed": any(
            f["forecast_6m"]["mem_pct"] > 90 or f["forecast_6m"]["ds_pct"] > 90
            for f in forecasts
        ),
    }


def generate_finance_report(db: Session) -> Dict[str, Any]:
    from app.models.infrastructure_report import CostConfig
    from app.models.infrastructure_report import BusinessServiceMap

    vms = _get_vms(db)
    cost_cfg = db.query(CostConfig).first()
    cpu_rate = cost_cfg.cpu_per_core if cost_cfg else 50.0
    ram_rate = cost_cfg.ram_per_gb if cost_cfg else 20.0
    disk_rate = cost_cfg.storage_per_gb if cost_cfg else 0.5
    currency = cost_cfg.currency if cost_cfg else "TL"

    vm_costs = []
    for v in vms:
        if v["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn"):
            continue
        cost = (
            (v["cpu_count"] or 0) * cpu_rate +
            (v["memory_gb"] or 0) * ram_rate +
            (v["disk_gb"] or 0) * disk_rate
        )
        vm_costs.append({
            "vm": v["name"],
            "hypervisor": v["hypervisor"],
            "vcpu": v["cpu_count"],
            "ram_gb": v["memory_gb"],
            "disk_gb": v["disk_gb"],
            "monthly_cost": round(cost, 2),
        })

    vm_costs.sort(key=lambda x: -x["monthly_cost"])
    total = sum(v["monthly_cost"] for v in vm_costs)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "currency": currency,
        "cost_rates": {
            "cpu_per_core": cpu_rate,
            "ram_per_gb": ram_rate,
            "storage_per_gb": disk_rate,
        },
        "total_monthly_cost": round(total, 2),
        "total_annual_cost": round(total * 12, 2),
        "top_cost_vms": vm_costs[:20],
        "powered_off_savings": round(
            sum((v["cpu_count"] or 0) * cpu_rate + (v["memory_gb"] or 0) * ram_rate
                for v in vms if v["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn")), 2
        ),
        "note": "Maliyet hesabı DB'deki tahsisat bilgisine göre yapılmıştır (gerçek tüketim değil).",
    }


def generate_riskiest_assets(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)
    vms = _get_vms(db)
    events = _get_active_events(db, days=7)

    # Her sunucu için event skoru
    server_scores: Dict[str, int] = {}
    for e in events:
        s = e.get("server") or ""
        pts = 10 if e["severity"] in ("critical", "error") else 3
        server_scores[s] = server_scores.get(s, 0) + pts

    # Host risk skorları
    host_risks = []
    for h in hosts:
        risk = 0
        reasons = []
        if h["mem_pct"] > 90: risk += 30; reasons.append(f"RAM %{h['mem_pct']}")
        elif h["mem_pct"] > 80: risk += 15; reasons.append(f"RAM %{h['mem_pct']}")
        if h["ds_pct"] > 85: risk += 20; reasons.append(f"Disk %{h['ds_pct']}")
        if h["cpu_pct"] > 85: risk += 15; reasons.append(f"CPU %{h['cpu_pct']}")
        if h["maintenance"]: risk += 10; reasons.append("Bakım modu")
        if h["state"] != "connected": risk += 40; reasons.append("Bağlantı sorunu")
        if risk > 0:
            host_risks.append({"host": h["host"], "risk_score": risk, "reasons": reasons})

    # VM risk skorları
    vm_risks = []
    for v in vms:
        risk = server_scores.get(v["name"], 0)
        reasons = []
        if v["power_state"] not in ("POWERED_ON", "up", "running", "poweredOn"):
            pass  # kapalı VM zaten risk değil (konsolidasyon raporunda)
        else:
            tools = (v["tools_status"] or "").lower()
            if "running" not in tools:
                risk += 10; reasons.append("Tools yok")
            if v["tier"] == "production": risk += 5; reasons.append("Production")
        if risk > 0:
            vm_risks.append({
                "vm": v["name"],
                "hypervisor": v["hypervisor"],
                "tier": v["tier"],
                "risk_score": risk,
                "reasons": reasons,
            })

    host_risks.sort(key=lambda x: -x["risk_score"])
    vm_risks.sort(key=lambda x: -x["risk_score"])

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "riskiest_hosts": host_risks[:10],
        "riskiest_vms": vm_risks[:15],
        "total_risky_hosts": len(host_risks),
        "total_risky_vms": len(vm_risks),
    }


def generate_operations_report(db: Session) -> Dict[str, Any]:
    """Son 30 günün operasyonel aktivitesi (system_events + sanallaştırma platform logları)."""
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.execute(text("""
        SELECT
            event_type,
            severity,
            COUNT(*) as cnt,
            COUNT(DISTINCT server_id) as unique_servers
        FROM system_events
        WHERE created_at >= :since
        GROUP BY event_type, severity
        ORDER BY cnt DESC
        LIMIT 30
    """), {"since": since}).all()

    virt_rows = db.execute(text("""
        SELECT
            event_type,
            severity,
            COUNT(*) as cnt
        FROM system_events
        WHERE created_at >= :since
          AND (
            source IN ('virt_collector', 'virt_resource', 'vcenter_event', 'vcenter_alarm', 'vcenter_task')
            OR event_type IN ('virt_log', 'virt_resource', 'vcenter_event', 'vcenter_alarm', 'vcenter_task')
          )
        GROUP BY event_type, severity
        ORDER BY cnt DESC
        LIMIT 20
    """), {"since": since}).all()

    # Günlük trend
    daily = db.execute(text("""
        SELECT DATE_TRUNC('day', created_at)::date as day,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE severity='critical') as critical
        FROM system_events
        WHERE created_at >= :since
        GROUP BY day ORDER BY day DESC
        LIMIT 30
    """), {"since": since}).all()

    virt_platform = _get_virt_platform_events(db, days=30)
    recent_platform_logs = [
        {
            "title": e.get("title"),
            "severity": e.get("severity"),
            "action": e.get("action"),
            "actor": e.get("actor"),
            "host": e.get("server"),
            "created_at": e.get("created_at"),
        }
        for e in virt_platform[:25]
    ]

    breakdown = [
        {"type": r.event_type, "severity": r.severity,
         "count": r.cnt, "unique_servers": r.unique_servers}
        for r in rows
    ]
    virt_breakdown = [
        {"type": r.event_type, "severity": r.severity, "count": r.cnt}
        for r in virt_rows
    ]
    total_events = sum(b["count"] for b in breakdown)
    unique_srv = max((b["unique_servers"] for b in breakdown), default=0)
    virt_total = sum(b["count"] for b in virt_breakdown)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": 30,
        "total_events": total_events,
        "unique_servers": unique_srv,
        "event_breakdown": breakdown,
        "virt_platform": {
            "total_events": virt_total,
            "breakdown": virt_breakdown,
            "recent_logs": recent_platform_logs,
        },
        "daily_trend": [
            {"day": str(d.day), "total": d.total, "critical": d.critical}
            for d in daily
        ],
        "note": (
            "Sanallaştırma platform logları (virt_log / virt_resource) operasyon aktivitesine dahil edildi. "
            "VM oluşturma/silme audit detayları hypervisor API entegrasyonu ile genişletilebilir."
        ),
    }


def generate_performance_bottleneck(db: Session) -> Dict[str, Any]:
    hosts = _latest_host_metrics(db)

    # Son 24 saatin peak değerleri
    peak_rows = db.execute(text("""
        SELECT host_name,
               MAX(cpu_usage_pct) as peak_cpu,
               MAX(mem_usage_pct) as peak_mem,
               MAX(ds_usage_pct) as peak_ds,
               MAX(net_rx_kbps + net_tx_kbps) as peak_net_kbps,
               AVG(cpu_usage_pct) as avg_cpu,
               AVG(mem_usage_pct) as avg_mem
        FROM hypervisor_host_metrics
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        GROUP BY host_name
    """)).all()
    peak_map = {r.host_name: r for r in peak_rows}

    bottlenecks = []
    for h in hosts:
        p = peak_map.get(h["host"])
        issues = []
        if h["mem_pct"] > 85: issues.append(f"Memory pressure (%{h['mem_pct']})")
        if h["cpu_pct"] > 80: issues.append(f"CPU doygun (%{h['cpu_pct']})")
        if h["ds_pct"] > 80: issues.append(f"Datastore dolu (%{h['ds_pct']})")
        if p:
            if (p.peak_net_kbps or 0) > 1_000_000:
                issues.append(f"Network yüksek ({round(p.peak_net_kbps/1024, 0)} Mbps peak)")

        bottlenecks.append({
            "host": h["host"],
            "current_cpu": h["cpu_pct"],
            "current_mem": h["mem_pct"],
            "current_ds": h["ds_pct"],
            "peak_cpu_24h": round(p.peak_cpu, 1) if p else None,
            "peak_mem_24h": round(p.peak_mem, 1) if p else None,
            "peak_net_mbps": round((p.peak_net_kbps or 0) / 1024, 1) if p else None,
            "issues": issues,
            "severity": "Kritik" if any("pressure" in i or "doygun" in i for i in issues) else (
                "Uyarı" if issues else "Normal"
            ),
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "bottlenecks": bottlenecks,
        "critical_count": sum(1 for b in bottlenecks if b["severity"] == "Kritik"),
    }


def generate_sla_report(db: Session) -> Dict[str, Any]:
    """SLA raporu — uptime/downtime eventlerinden türetilir."""
    since = datetime.utcnow() - timedelta(days=30)

    # Status değişim eventleri (uptime proxy)
    rows = db.execute(text("""
        SELECT s.id, s.name, s.status,
               COUNT(e.id) as event_count,
               COUNT(e.id) FILTER (WHERE e.severity IN ('critical','error')) as critical_count
        FROM servers s
        LEFT JOIN system_events e ON e.server_id = s.id
            AND e.created_at >= :since
        WHERE s.hypervisor_id IS NOT NULL
        GROUP BY s.id, s.name, s.status
    """), {"since": since}).all()

    sla_items = []
    for r in rows:
        estimated_uptime = max(0, 100 - (r.critical_count or 0) * 0.5)
        sla_items.append({
            "server": r.name,
            "current_status": r.status or "UNKNOWN",
            "critical_events_30d": r.critical_count or 0,
            "total_events_30d": r.event_count or 0,
            "estimated_uptime_pct": round(min(100, estimated_uptime), 2),
            "sla_met": estimated_uptime >= 99.0,
        })

    met = sum(1 for s in sla_items if s["sla_met"])
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": 30,
        "sla_target_pct": 99.0,
        "servers_meeting_sla": met,
        "servers_missing_sla": len(sla_items) - met,
        "overall_sla_compliance_pct": round(met / len(sla_items) * 100, 1) if sla_items else 100,
        "sla_items": sorted(sla_items, key=lambda x: x["estimated_uptime_pct"])[:30],
        "note": "SLA hesabı olay yoğunluğundan tahmin edilmiştir. Kesin ölçüm için monitoring entegrasyonu gereklidir.",
    }


def generate_business_impact(db: Session) -> Dict[str, Any]:
    from app.models.infrastructure_report import BusinessServiceMap
    from app.models.server import Server

    mappings = db.query(BusinessServiceMap).all()
    if not mappings:
        vms = _get_vms(db)
        prod_vms = [v for v in vms if v["tier"] == "production"]
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "mapped_services": 0,
            "message": "Henüz iş servisi eşleşmesi tanımlanmamış.",
            "high_risk_candidates": [
                {"vm": v["name"], "reason": "Production tier"}
                for v in prod_vms[:10]
            ],
            "setup_instructions": "POST /hypervisors/business-services endpoint'i ile servis eşleşmesi ekleyebilirsiniz.",
        }

    services: Dict[str, List] = {}
    for m in mappings:
        srv = db.query(Server).filter(Server.id == m.server_id).first()
        vm_name = srv.name if srv else f"ID:{m.server_id}"
        services.setdefault(m.service_name, []).append({
            "vm": vm_name,
            "tier": m.service_tier,
            "dept": m.department,
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "mapped_services": len(services),
        "services": [{"service": k, "vms": v, "vm_count": len(v)} for k, v in services.items()],
    }


# ── Ana Dispatch ──────────────────────────────────────────────────────────────

REPORT_REGISTRY: Dict[str, Any] = {
    "executive_summary":       generate_executive_summary,
    "capacity":                generate_capacity_report,
    "risk":                    generate_risk_dashboard,
    "vm_health":               generate_vm_health_scores,
    "resource_usage":          generate_resource_usage_report,
    "security_compliance":     generate_security_compliance_report,
    "consolidation":           generate_consolidation_report,
    "lifecycle":               generate_lifecycle_report,
    "anomaly":                 generate_anomaly_report,
    "forecast":                generate_forecast_report,
    "finance":                 generate_finance_report,
    "riskiest_assets":         generate_riskiest_assets,
    "operations":              generate_operations_report,
    "performance_bottleneck":  generate_performance_bottleneck,
    "sla":                     generate_sla_report,
    "business_impact":         generate_business_impact,
}

REPORT_TITLES: Dict[str, str] = {
    "executive_summary":       "Executive Summary",
    "capacity":                "Kapasite Raporu",
    "risk":                    "Risk Dashboard",
    "vm_health":               "VM Sağlık Skoru",
    "resource_usage":          "Kaynak Tahsis Raporu",
    "security_compliance":     "Güvenlik ve Uyumluluk Raporu",
    "consolidation":           "Konsolidasyon Raporu",
    "lifecycle":               "Yaşam Döngüsü Raporu",
    "anomaly":                 "Anomali Tespit Raporu",
    "forecast":                "Kapasite Tahmin Raporu",
    "finance":                 "Finans / Maliyet Raporu",
    "riskiest_assets":         "En Riskli Varlıklar",
    "operations":              "Operasyon Raporu",
    "performance_bottleneck":  "Performans Darboğaz Raporu",
    "sla":                     "Erişilebilirlik Raporu (Tahmini)",
    "business_impact":         "Business Service Impact",
}


def generate_report(db: Session, report_type: str, save: bool = True) -> Dict[str, Any]:
    """
    Raporu üretir, DB'ye kaydeder ve döner.
    save=False ise sadece üretir, DB'ye yazmaz.
    """
    fn = REPORT_REGISTRY.get(report_type)
    if not fn:
        raise ValueError(f"Bilinmeyen rapor tipi: {report_type}")

    data = fn(db)
    title = REPORT_TITLES.get(report_type, report_type)

    if "data_quality" not in data:
        data["data_quality"] = _report_data_quality(db)

    if save:
        from app.models.infrastructure_report import InfrastructureReport
        report_obj = InfrastructureReport(
            report_type=report_type,
            report_title=title,
            data=data,
            status="ready",
        )
        db.add(report_obj)
        db.commit()
        db.refresh(report_obj)
        data["_report_id"] = report_obj.id
        data["_report_title"] = title

    data["report_type"] = report_type
    return data


def get_latest_report(db: Session, report_type: str) -> Optional[Dict[str, Any]]:
    """DB'den en son kaydedilen raporu getir."""
    from app.models.infrastructure_report import InfrastructureReport
    rpt = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == report_type)
        .order_by(InfrastructureReport.generated_at.desc())
        .first()
    )
    if not rpt:
        return None
    return {**rpt.data, "_report_id": rpt.id, "_report_title": rpt.report_title,
            "_generated_at": rpt.generated_at.isoformat() if rpt.generated_at else None}


def format_report_as_markdown(report_type: str, data: Dict[str, Any]) -> str:
    """Tüm 19 rapor tipi için deterministik Markdown üretir."""
    title = REPORT_TITLES.get(report_type, report_type)
    ts = data.get("generated_at", "")[:16]
    lines: List[str] = [f"# {title}", f"*Oluşturulma: {ts}*", ""]

    # ── Yardımcı iç fonksiyonlar ──────────────────────────────────────────────
    def tbl(headers: List[str], rows: List[List[str]]) -> List[str]:
        sep = ["|" + "|".join("---" for _ in headers) + "|"]
        hdr = ["| " + " | ".join(str(h) for h in headers) + " |"]
        body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
        return hdr + sep + body

    def badge(level: str) -> str:
        m = {"Kritik": "🔴", "Yüksek": "🟠", "Orta": "🟡", "Normal": "🟢", "Düşük": "🟢"}
        return m.get(level, "⚪")

    # ── Executive Summary ────────────────────────────────────────────────────
    if report_type == "executive_summary":
        infra = data.get("infrastructure", {})
        util  = data.get("utilization", {})
        health = data.get("health", {})
        rl = data.get("risk_level", "?")
        lines += [
            f"{badge(rl)} **Risk Seviyesi: {rl}**", "",
            "## Altyapı Özeti",
        ] + tbl(
            ["Metrik", "Değer"],
            [
                ["ESX/KVM Host Sayısı", infra.get("host_count", 0)],
                ["Toplam VM", infra.get("vm_total", 0)],
                ["Çalışan VM", infra.get("vm_powered_on", 0)],
                ["Kapalı VM", infra.get("vm_powered_off", 0)],
                ["Ort. CPU", f"%{util.get('avg_cpu_pct', 0)}"],
                ["Ort. RAM", f"%{util.get('avg_mem_pct', 0)}"],
                ["Ort. Disk", f"%{util.get('avg_storage_pct', 0)}"],
                ["Kritik Olay", health.get("active_critical_events", 0)],
                ["Uyarı Olayı", health.get("active_warning_events", 0)],
            ]
        )
        hosts = data.get("hosts_detail", [])
        if hosts:
            lines += ["", "## Host Detayları"] + tbl(
                ["Host", "CPU%", "RAM%", "Disk%", "VM"],
                [[h["host"], f"%{h.get('cpu_pct',0)}", f"%{h.get('mem_pct',0)}", f"%{h.get('ds_pct',0)}", f"{h.get('vms_running',0)}/{h.get('vms_total',0)}"]
                 for h in hosts]
            )
        recs = data.get("recommendations", [])
        if recs:
            lines += ["", "## Önerilen Aksiyonlar"] + [f"- {r}" for r in recs]

    # ── Kapasite ─────────────────────────────────────────────────────────────
    elif report_type == "capacity":
        items = data.get("capacity_items", [])
        lines += ["## Host Kapasite Durumu"] + tbl(
            ["Host", "CPU%", "RAM%", "Disk%", "Boş RAM (GB)", "Boş Disk (GB)", "VM", "Durum"],
            [[i["host"], f"%{i['cpu']['used_pct']}", f"%{i['memory']['used_pct']}", f"%{i['storage']['used_pct']}",
              i["memory"]["free_gb"], i["storage"]["free_gb"], f"{i['vms_running']}/{i['vms_total']}", i.get("status","")]
             for i in items]
        )
        warns = data.get("warnings", [])
        if warns:
            lines += ["", "## ⚠️ Uyarılar"] + [f"- {w}" for w in warns]
        ds_breakdown = data.get("datastore_vm_disk", {})
        if ds_breakdown:
            lines += ["", "## Datastore Bazında VM Disk Tahsisatı"] + tbl(
                ["Datastore", "VM Sayısı", "Tahsisli Disk (GB)"],
                [[ds, info["vm_count"], info["allocated_disk_gb"]]
                 for ds, info in sorted(ds_breakdown.items(), key=lambda x: -x[1]["allocated_disk_gb"])]
            )
            lines += ["", "## Datastore VM Disk Detayı"]
            for ds, info in sorted(ds_breakdown.items(), key=lambda x: -x[1]["allocated_disk_gb"]):
                lines += [f"### {ds} ({info['vm_count']} VM, {info['allocated_disk_gb']} GB tahsisli)"] + tbl(
                    ["VM", "Disk (GB)", "Güç"],
                    [[v["vm"], v["disk_gb"], v["power_state"]] for v in info["vms"][:15]]
                ) + [""]

    # ── Risk Dashboard ────────────────────────────────────────────────────────
    elif report_type == "risk":
        risks = data.get("risks", {})
        rs = data.get("risk_score", 0)
        rl = data.get("risk_level", "?")
        lines += [
            f"{badge(rl)} **Risk Skoru: {rs}/100 — {rl}**",
            f"- Kritik Olay: **{data.get('critical_event_count', 0)}**",
            f"- Uyarı Olayı: **{data.get('warning_event_count', 0)}**", ""
        ]
        if risks.get("high_cpu_hosts"):
            lines += ["## 🔴 Yüksek CPU Host'lar"] + tbl(
                ["Host", "CPU%"],
                [[h["host"], f"%{h['cpu_pct']}"] for h in risks["high_cpu_hosts"]]
            ) + [""]
        if risks.get("high_memory_hosts"):
            lines += ["## 🔴 Yüksek RAM Host'lar"] + tbl(
                ["Host", "RAM%", "Boş (GB)"],
                [[h["host"], f"%{h['mem_pct']}", h["free_gb"]] for h in risks["high_memory_hosts"]]
            ) + [""]
        if risks.get("high_storage_hosts"):
            lines += ["## 🔴 Yüksek Disk Host'lar"] + tbl(
                ["Host", "Disk%", "Boş (GB)"],
                [[h["host"], f"%{h['ds_pct']}", h["free_gb"]] for h in risks["high_storage_hosts"]]
            ) + [""]
        if risks.get("no_tools_vms"):
            lines += ["## ⚠️ VMware Tools Çalışmayan VM'ler"] + tbl(
                ["VM", "OS"],
                [[v["vm"], v.get("os","?")] for v in risks["no_tools_vms"][:15]]
            ) + [""]
        if risks.get("top_alarm_servers"):
            lines += ["## 🔔 En Çok Alarm Üreten Sunucular"] + tbl(
                ["Sunucu", "Olay Sayısı"],
                [[s["server"], s["events"]] for s in risks["top_alarm_servers"]]
            )

    # ── VM Sağlık Skoru ────────────────────────────────────────────────────────
    elif report_type == "vm_health":
        gdist = data.get("grade_distribution", {})
        lines += [
            f"**Ortalama Sağlık Skoru:** {data.get('avg_score', 0)}/100",
            "",
            "## Not Dağılımı",
        ] + tbl(
            ["Not", "VM Sayısı"],
            [[g, c] for g, c in gdist.items()]
        )
        cvms = data.get("critical_vms", [])
        if cvms:
            lines += ["", "## Kritik VM'ler (D/F Notu)"] + tbl(
                ["VM", "Skor", "Not", "Sorunlar"],
                [[v["vm"], f"{v['score']}/100", v["grade"], ", ".join(v["issues"][:3])] for v in cvms[:20]]
            )

    # ── Kaynak Tahsisi ───────────────────────────────────────────────────────
    elif report_type == "resource_usage":
        s = data.get("summary", {})
        lines += [
            f"**Çalışan VM:** {s.get('powered_on_vms', 0)}",
            f"**Toplam Tahsis CPU:** {s.get('total_allocated_vcpu', 0)} vCPU",
            f"**Toplam Tahsis RAM:** {s.get('total_allocated_ram_gb', 0)} GB",
            f"**Toplam Tahsis Disk:** {s.get('total_allocated_disk_gb', 0)} GB",
            "",
            "*Not: Bu değerler tahsisat (allocation) bazlıdır, gerçek zamanlı kaynak tüketimi değildir.*",
            "",
            "## En Çok CPU Tahsis Edilen VM'ler",
        ] + tbl(
            ["VM", "vCPU", "Hypervisor"],
            [[v["vm"], v["vcpu"], v.get("hypervisor","?")] for v in data.get("top_cpu_consumers", [])]
        ) + ["", "## En Çok RAM Tahsis Edilen VM'ler"] + tbl(
            ["VM", "RAM (GB)", "Hypervisor"],
            [[v["vm"], v["ram_gb"], v.get("hypervisor","?")] for v in data.get("top_ram_consumers", [])]
        ) + ["", "## En Çok Disk Tahsis Edilen VM'ler"] + tbl(
            ["VM", "Disk (GB)", "Hypervisor"],
            [[v["vm"], v["disk_gb"], v.get("hypervisor","?")] for v in data.get("top_disk_consumers", [])]
        )

    # ── Güvenlik & Uyumluluk ──────────────────────────────────────────────────
    elif report_type == "security_compliance":
        comp = data.get("vmware_tools", {})
        score = data.get("compliance_score", 0)
        lines += [
            f"**Uyum Skoru:** {score}/100",
            f"**VMware Tools:** {comp.get('compliant_count', 0)} uyumlu / "
            f"{comp.get('non_compliant_count', 0)} uyumsuz — %{comp.get('compliance_pct', 0)}",
            f"**Çalışan & Tools Yok:** {comp.get('powered_on_non_compliant', 0)} VM", ""
        ]
        issues = data.get("issues", [])
        if issues:
            lines += ["## Tespit Edilen Sorunlar"] + [f"- ⚠️ {i}" for i in issues] + [""]
        noncompliant = comp.get("non_compliant_vms", [])
        if noncompliant:
            lines += ["## VMware Tools Yüklü Olmayan Çalışan VM'ler"] + tbl(
                ["VM", "Güç Durumu"],
                [[v["vm"], v.get("state","?")] for v in noncompliant[:20]]
            ) + [""]
        hw = data.get("hw_version_distribution", {})
        if hw:
            lines += ["## Donanım Versiyon Dağılımı"] + tbl(
                ["HW Versiyon", "VM Sayısı"],
                [[k, v] for k, v in sorted(hw.items(), key=lambda x: -x[1])]
            )

    # ── Konsolidasyon ──────────────────────────────────────────────────────────
    elif report_type == "consolidation":
        poff = data.get("powered_off_vms", {})
        over = data.get("oversized_vms", {})
        pot  = data.get("consolidation_potential", {})
        lines += [
            "## Geri Kazanım Potansiyeli",
        ] + tbl(
            ["Kaynak", "Miktar"],
            [
                ["Kapalı VM", poff.get("count", 0)],
                ["Geri Alınabilir vCPU", pot.get("reclaimable_vcpu", 0)],
                ["Geri Alınabilir RAM", f"{pot.get('reclaimable_ram_gb', 0)} GB"],
                ["Geri Alınabilir Disk", f"{pot.get('reclaimable_disk_gb', 0)} GB"],
                ["Oversized VM (≥8 vCPU)", over.get("count", 0)],
            ]
        )
        if poff.get("vms"):
            lines += ["", "## Kapalı VM Listesi"] + tbl(
                ["VM", "vCPU", "RAM (GB)", "Disk (GB)"],
                [[v["vm"], v["cpu"], v.get("ram_gb","?"), v.get("disk_gb","?")] for v in poff["vms"][:20]]
            )
        if over.get("vms"):
            lines += ["", "## Oversized VM'ler (≥8 vCPU)"] + tbl(
                ["VM", "vCPU", "RAM (GB)"],
                [[v["vm"], v["cpu"], v.get("ram_gb","?")] for v in over["vms"][:15]]
            )

    # ── Yaşam Döngüsü ────────────────────────────────────────────────────────
    elif report_type == "lifecycle":
        old = data.get("old_hw_vms", {})
        lines += [
            f"**Toplam VM:** {data.get('total_vms', 0)}",
            f"**Eski Donanım VM:** {old.get('count', 0)} ({data.get('upgrade_needed_pct', 0)}%)",
            f"**Eşik:** {old.get('threshold','vmx-14')} altı", "",
            "## Donanım Versiyon Dağılımı",
        ] + tbl(
            ["HW Versiyon", "VM Sayısı"],
            [[k, v] for k, v in sorted(data.get("hw_version_distribution", {}).items(), key=lambda x: -x[1])]
        )
        if old.get("vms"):
            lines += ["", "## Güncelleme Gereken VM'ler"] + tbl(
                ["VM", "HW Versiyon", "Dönem"],
                [[v["vm"], v.get("hw_version","?"), v.get("era","?")] for v in old["vms"][:20]]
            )

    # ── Anomali Tespit ────────────────────────────────────────────────────────
    elif report_type == "anomaly":
        lines += [
            f"**İnceleme Periyodu:** {data.get('period_days', 14)} gün",
            f"**Toplam Olay:** {data.get('total_events', 0)}",
            f"**Kritik Olay:** {data.get('critical_count', 0)}",
            f"**Uyarı:** {data.get('warning_count', 0)}", "",
            "## En Çok Anomali Olan Sunucular",
        ] + tbl(
            ["Sunucu", "Kritik", "Uyarı", "Toplam"],
            [[a["server"], a["critical"], a["warning"], a["total"]]
             for a in data.get("top_anomaly_servers", [])[:15]]
        ) + ["", "## En Sık Görülen Olay Tipleri"] + tbl(
            ["Tip", "Adet"],
            [[t["type"], t["count"]] for t in data.get("top_event_types", [])]
        )
        metric_anomalies = data.get("host_metric_anomalies", [])
        if metric_anomalies:
            lines += ["", "## Host Metrik Anomalileri"] + tbl(
                ["Host", "Bulgular", "Peak CPU%", "Peak RAM%"],
                [[a["host"], "; ".join(a.get("issues", [])), a.get("peak_cpu_pct", "-"), a.get("peak_mem_pct", "-")]
                 for a in metric_anomalies[:15]]
            )

    # ── Kapasite Tahmin (Forecast) ────────────────────────────────────────────
    elif report_type == "forecast":
        lines += ["## Kapasite Tahmini (Lineer Trend)"] + tbl(
            ["Host", "CPU Şimdi", "3 Ay", "6 Ay", "12 Ay", "RAM Şimdi", "3 Ay", "6 Ay", "12 Ay"],
            [[f["host"],
              f"%{f['current']['cpu_pct']}", f"%{f['forecast_3m']['cpu_pct']}", f"%{f['forecast_6m']['cpu_pct']}", f"%{f['forecast_12m']['cpu_pct']}",
              f"%{f['current']['mem_pct']}", f"%{f['forecast_3m']['mem_pct']}", f"%{f['forecast_6m']['mem_pct']}", f"%{f['forecast_12m']['mem_pct']}"]
             for f in data.get("forecasts", [])]
        )
        if data.get("investment_needed"):
            lines += ["", "**⚠️ 6 ay içinde kapasite yatırımı gerekebilir.**"]

    # ── Finans / Maliyet ─────────────────────────────────────────────────────
    elif report_type == "finance":
        cur = data.get("currency", "TL")
        lines += [
            f"**Aylık Maliyet:** {data.get('total_monthly_cost', 0):,.0f} {cur}",
            f"**Yıllık Maliyet:** {data.get('total_annual_cost', 0):,.0f} {cur}",
            f"**Kapalı VM Tasarruf:** {data.get('powered_off_savings', 0):,.0f} {cur}/ay", "",
            "## En Maliyetli VM'ler",
        ] + tbl(
            ["VM", "vCPU", "RAM (GB)", "Disk (GB)", f"Aylık ({cur})"],
            [[v["vm"], v["vcpu"], v["ram_gb"], v["disk_gb"], f"{v['monthly_cost']:,.0f}"]
             for v in data.get("top_cost_vms", [])[:15]]
        )

    # ── En Riskli Varlıklar ──────────────────────────────────────────────────
    elif report_type == "riskiest_assets":
        lines += [
            f"**Riskli Host Sayısı:** {data.get('total_risky_hosts', 0)}",
            f"**Riskli VM Sayısı:** {data.get('total_risky_vms', 0)}", "",
            "## En Riskli Host'lar",
        ] + tbl(
            ["Host", "Risk Skoru", "Sebepler"],
            [[h["host"], h.get("risk_score", 0), ", ".join(h.get("reasons", [])[:3])]
             for h in data.get("riskiest_hosts", [])[:10]]
        ) + ["", "## En Riskli VM'ler"] + tbl(
            ["VM", "Risk Skoru", "Sebepler"],
            [[v["vm"], v.get("risk_score", 0), ", ".join(v.get("reasons", [])[:3])]
             for v in data.get("riskiest_vms", [])[:10]]
        )

    # ── Operasyon Raporu ──────────────────────────────────────────────────────
    elif report_type == "operations":
        lines += [
            f"**Periyot:** {data.get('period_days', 30)} gün",
            f"**Toplam Olay:** {data.get('total_events', 0)}",
            f"**Etkilenen Sunucu:** {data.get('unique_servers', 0)}", "",
            "## Olay Tipi / Önem Derecesi Dağılımı",
        ] + tbl(
            ["Tip", "Önem", "Adet", "Etkilenen Sunucu"],
            [[b["type"], b["severity"], b["count"], b["unique_servers"]] for b in data.get("event_breakdown", [])[:15]]
        ) + ["", "## Günlük Trend"] + tbl(
            ["Tarih", "Toplam", "Kritik"],
            [[d["day"], d["total"], d["critical"]] for d in data.get("daily_trend", [])[:10]]
        )
        virt = data.get("virt_platform", {})
        if virt.get("breakdown"):
            lines += ["", "## Sanallaştırma Platform Olayları"] + tbl(
                ["Tip", "Önem", "Adet"],
                [[b["type"], b["severity"], b["count"]] for b in virt["breakdown"][:15]]
            )
        note = data.get("note")
        if note:
            lines += ["", f"*Not: {note}*"]

    # ── Performans Darboğaz ───────────────────────────────────────────────────
    elif report_type == "performance_bottleneck":
        bns = data.get("bottlenecks", [])
        lines += [
            f"**Kritik Darboğaz Sayısı:** {data.get('critical_count', 0)}/{len(bns)}", "",
            "## Host Bazında Darboğaz Durumu",
        ] + tbl(
            ["Host", "CPU%", "Peak CPU (24s)", "RAM%", "Peak RAM (24s)", "Disk%", "Durum", "Sorunlar"],
            [[b["host"], f"%{b.get('current_cpu',0)}", (f"%{b['peak_cpu_24h']}" if b.get('peak_cpu_24h') is not None else "-"),
              f"%{b.get('current_mem',0)}", (f"%{b['peak_mem_24h']}" if b.get('peak_mem_24h') is not None else "-"),
              f"%{b.get('current_ds',0)}", b.get("severity","Normal"), ", ".join(b.get("issues", [])[:2])]
             for b in bns]
        )

    # ── SLA / Erişilebilirlik Raporu ─────────────────────────────────────────
    elif report_type == "sla":
        lines += [
            f"**SLA Hedefi:** %{data.get('sla_target_pct', 99)}",
            f"**Periyot:** {data.get('period_days', 30)} gün",
            f"**SLA Sağlayan Sunucu:** {data.get('servers_meeting_sla', 0)}",
            f"**SLA Tutturamayan Sunucu:** {data.get('servers_missing_sla', 0)}",
            f"**Genel Uyum:** %{data.get('overall_sla_compliance_pct', 100)}", "",
            "## Sunucu Erişilebilirlik Durumu",
        ] + tbl(
            ["Sunucu", "Tahmini Uptime%", "Kritik Olay (30g)", "SLA"],
            [[s.get("server","?"), f"%{s.get('estimated_uptime_pct',0)}", s.get("critical_events_30d",0),
              "✓" if s.get("sla_met") else "✗"]
             for s in data.get("sla_items", [])[:20]]
        )
        note = data.get("note")
        if note:
            lines += ["", f"*Not: {note}*"]

    # ── Business Impact ───────────────────────────────────────────────────────
    elif report_type == "business_impact":
        if data.get("mapped_services", 0) == 0 and data.get("high_risk_candidates") is not None:
            lines += [
                f"**Tanımlı İş Servisi:** 0",
                f"*{data.get('message','')}*",
                "",
                "## Yüksek Risk Adayları (Production Tier, servis eşleşmesi tanımlanmamış)",
            ] + tbl(
                ["VM", "Sebep"],
                [[v.get("vm","?"), v.get("reason","?")] for v in data.get("high_risk_candidates", [])[:15]]
            )
            if data.get("setup_instructions"):
                lines += ["", f"*{data['setup_instructions']}*"]
        else:
            lines += [
                f"**Tanımlı İş Servisi:** {data.get('mapped_services', 0)}", "",
                "## İş Servisi Haritası",
            ] + tbl(
                ["Servis", "VM Sayısı"],
                [[s.get("service","?"), s.get("vm_count",0)] for s in data.get("services", [])[:15]]
            )

    # ── Fallback (veri varsa key-value, yoksa bilgi mesajı) ───────────────────
    else:
        keys = [k for k in data if k not in ("generated_at",) and not k.startswith("_")]
        if keys:
            lines += tbl(["Alan", "Değer"], [[k.replace("_"," ").title(), str(data[k])[:120]] for k in keys[:30]])
        else:
            lines.append("*Bu rapor tipi için henüz veri bulunmuyor.*")

    return "\n".join(lines)
