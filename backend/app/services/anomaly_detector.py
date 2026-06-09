"""
Anomaly Detection - Z-score + IQR + Threshold temelli anomali tespiti.
TimescaleDB'deki metric_data'yi analiz eder.
"""
import logging
import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.server import Server
from app.models.metric import MetricData

logger = logging.getLogger(__name__)


# Anomali tespiti icin kritik metrikler ve esikleri
# z_threshold: kaç sigma sapma olunca alarm üretilir
#   - 3.0 = %99.7 normal dağılım (her 370 ölçümde 1 alarm — gürültülü)
#   - 3.5 = %99.95 (her 4.400 ölçümde 1 — dengeli)  ← yeni default
#   - 4.0 = %99.994 (her 15.800 ölçümde 1 — hassas ortamlar)
# min_history: eşik devreye girmeden önce gereken minimum veri noktası
ANOMALY_CONFIG = {
    "cpu_usage_percent":         {"warning": 85.0, "critical": 95.0, "z_threshold": 3.5, "min_history": 20},
    "cpu_iowait_percent":        {"warning": 25.0, "critical": 50.0, "z_threshold": 3.5, "min_history": 20},
    "cpu_steal_percent":         {"warning": 8.0,  "critical": 20.0, "z_threshold": 3.5, "min_history": 20},
    "memory_usage_percent":      {"warning": 88.0, "critical": 96.0, "z_threshold": 3.5, "min_history": 20},
    "swap_usage_percent":        {"warning": 60.0, "critical": 85.0, "z_threshold": 3.5, "min_history": 10},
    "disk_root_usage_percent":   {"warning": 82.0, "critical": 92.0, "z_threshold": 3.5, "min_history": 10},
    "disk_io_utilization_percent":{"warning": 85.0,"critical": 96.0, "z_threshold": 3.5, "min_history": 20},
    "load1":                     {"warning": None, "critical": None, "z_threshold": 3.5, "min_history": 20},
    "procs_blocked":             {"warning": 10.0, "critical": 30.0, "z_threshold": 3.5, "min_history": 10},
    "network_rx_errors_per_sec": {"warning": 5.0,  "critical": 20.0, "z_threshold": 3.5, "min_history": 10},
    "network_tx_errors_per_sec": {"warning": 5.0,  "critical": 20.0, "z_threshold": 3.5, "min_history": 10},
    "network_rx_drops_per_sec":  {"warning": 5.0,  "critical": 20.0, "z_threshold": 3.5, "min_history": 10},
    "network_tx_drops_per_sec":  {"warning": 5.0,  "critical": 20.0, "z_threshold": 3.5, "min_history": 10},
    "context_switches_per_sec":  {"warning": None, "critical": None, "z_threshold": 4.0, "min_history": 30},
}


def _zscore(values: List[float], current: float) -> Optional[float]:
    if len(values) < 5:
        return None
    try:
        mean = statistics.mean(values)
        stdev = statistics.stdev(values)
        if stdev < 1e-9:
            return 0.0
        return (current - mean) / stdev
    except Exception:
        return None


def _iqr_outlier(values: List[float], current: float) -> bool:
    if len(values) < 8:
        return False
    try:
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[3 * n // 4]
        iqr = q3 - q1
        upper = q3 + 1.5 * iqr
        return current > upper
    except Exception:
        return False


def _severity(value: float, cfg: Dict[str, Any], z: Optional[float]) -> str:
    crit = cfg.get("critical")
    warn = cfg.get("warning")
    z_thresh = cfg.get("z_threshold", 3.0)

    # 1) Mutlak eşik kontrolü (en güvenilir sinyal)
    if crit is not None and value >= crit:
        return "critical"
    if warn is not None and value >= warn:
        return "warning"

    # 2) Z-score: yalnızca POZİTİF sapma (değer YÜKSELDİ) anlamlıdır.
    #    Tüm metriklerimiz "yüksek = kötü" olduğundan değerin düşmesi anomali değildir.
    #    Ayrıca düşük mutlak değerli istatistiksel spike'ları ele (örn. CPU %2.77).
    if z is not None and z >= z_thresh:
        floor = (warn * 0.5) if warn is not None else None
        if floor is None or value >= floor:
            return "warning" if z < z_thresh + 3 else "critical"
    return "info"


def detect_anomalies_for_server(
    db: Session,
    server: Server,
    lookback_minutes: int = 60,
    history_minutes: int = 1440,  # 24 saat gecmis
) -> List[Dict[str, Any]]:
    """Bir sunucu icin anomali tespiti yapar."""
    anomalies = []
    now = datetime.utcnow()
    lookback_start = now - timedelta(minutes=lookback_minutes)
    history_start = now - timedelta(minutes=history_minutes)

    for metric_name, base_cfg in ANOMALY_CONFIG.items():
        try:
            cfg = dict(base_cfg)
            # load1 çekirdek sayısına göre dinamik eşik (load == cores → %100 doluluk)
            if metric_name == "load1" and getattr(server, "cpu_cores", None):
                cores = max(1, int(server.cpu_cores))
                cfg["warning"] = cores * 1.0
                cfg["critical"] = cores * 2.0
            # Son N dakikanin ortalamasini al (mevcut deger)
            recent = db.query(MetricData).filter(
                MetricData.server_id == server.id,
                MetricData.metric_name == metric_name,
                MetricData.timestamp >= lookback_start,
            ).order_by(MetricData.timestamp.desc()).limit(cfg["min_history"]).all()

            if not recent:
                continue

            current_value = statistics.mean([r.value for r in recent])

            # Gecmis verileri al (baseline)
            history = db.query(MetricData.value).filter(
                MetricData.server_id == server.id,
                MetricData.metric_name == metric_name,
                MetricData.timestamp >= history_start,
                MetricData.timestamp < lookback_start,
            ).all()
            history_values = [h[0] for h in history]

            if len(history_values) < cfg["min_history"]:
                # Gecmis yetersiz, sadece esik kontrolu yap
                z = None
            else:
                z = _zscore(history_values, current_value)

            severity = _severity(current_value, cfg, z)
            is_iqr_outlier = _iqr_outlier(history_values, current_value) if history_values else False

            # Yalnızca aksiyon alınabilir (warning/critical) anomalileri raporla.
            # IQR aykırılık bilgisi payload'da tutulur ama tek başına tetiklemez.
            if severity in ("warning", "critical"):
                mean_val = statistics.mean(history_values) if history_values else None
                stdev_val = statistics.stdev(history_values) if len(history_values) >= 2 else None

                anomalies.append({
                    "server_id": server.id,
                    "server_name": server.name,
                    "ip_address": server.ip_address,
                    "metric_name": metric_name,
                    "current_value": round(current_value, 4),
                    "mean_value": round(mean_val, 4) if mean_val is not None else None,
                    "stdev_value": round(stdev_val, 4) if stdev_val is not None else None,
                    "z_score": round(z, 2) if z is not None else None,
                    "is_iqr_outlier": is_iqr_outlier,
                    "severity": severity,
                    "threshold_warning": cfg.get("warning"),
                    "threshold_critical": cfg.get("critical"),
                    "detected_at": now.isoformat(),
                    "message": _build_message(metric_name, current_value, severity, z, cfg),
                })
        except Exception as e:
            logger.debug(f"Anomaly check error {metric_name}/{server.name}: {e}")

    return anomalies


def _build_message(metric: str, value: float, severity: str, z: Optional[float], cfg: Dict) -> str:
    metric_labels = {
        "cpu_usage_percent": "CPU kullanimi",
        "cpu_iowait_percent": "CPU IO wait",
        "cpu_steal_percent": "CPU steal",
        "memory_usage_percent": "Bellek kullanimi",
        "swap_usage_percent": "Swap kullanimi",
        "disk_root_usage_percent": "Disk (/) kullanimi",
        "disk_io_utilization_percent": "Disk IO kullanimi",
        "load1": "Sistem yuku (load1)",
        "procs_blocked": "Bloke proses sayisi",
        "network_rx_errors_per_sec": "Network RX hata/sn",
        "network_tx_errors_per_sec": "Network TX hata/sn",
        "network_rx_drops_per_sec": "Network RX drop/sn",
        "network_tx_drops_per_sec": "Network TX drop/sn",
        "context_switches_per_sec": "Context switch/sn",
    }
    label = metric_labels.get(metric, metric)
    unit = "%" if "percent" in metric else ("/sn" if "per_sec" in metric else "")
    sev_label = "🔴 KRITIK" if severity == "critical" else "🟡 UYARI"
    msg = f"{sev_label}: {label} yuksek: {value:.2f}{unit}"
    if z is not None:
        msg += f" (Z-score: {z:.1f})"
    if cfg.get("critical") and value >= cfg["critical"]:
        msg += f" — Esik: {cfg['critical']}{unit}"
    elif cfg.get("warning") and value >= cfg["warning"]:
        msg += f" — Esik: {cfg['warning']}{unit}"
    return msg


def detect_all_anomalies(db: Session) -> List[Dict[str, Any]]:
    """Tum ONLINE AI-ready sunuculari tara."""
    servers = db.query(Server).filter(
        Server.ai_ready == True,
        Server.status == "ONLINE"
    ).all()

    all_anomalies = []
    for srv in servers:
        try:
            anomalies = detect_anomalies_for_server(db, srv)
            all_anomalies.extend(anomalies)
        except Exception as e:
            logger.error(f"Anomaly detection failed {srv.name}: {e}")

    if all_anomalies:
        logger.warning(f"Anomaly detection: {len(all_anomalies)} anomali tespit edildi")
    else:
        logger.info("Anomaly detection: anomali yok")

    return all_anomalies
