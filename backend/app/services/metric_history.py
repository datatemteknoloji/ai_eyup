"""
Chat/Agent için node_exporter (TimescaleDB metric_data) zaman serisi grafik desteği.

Kullanıcı "son 2 saatlik disk ve network utilizasyonunu göster" gibi bir mesaj
yazdığında bunu algılar (detect_chart_request), ilgili metrik geçmişini
TimescaleDB'den çeker (fetch_chart_data) ve chat/agent'ın hem kısa metin özeti
hem de frontend'in Recharts ile çizebileceği yapılandırılmış veriyi
(ChatMessage.meta.charts) üretmesini sağlar (build_chart_response).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.metric import MetricData
from app.models.server import Server

# ── Metrik grupları: kullanıcı kelimesi -> (metric_name, etiket, birim) listesi ──
# Aynı birimdeki (%, B/s, sayı) metrikler tek grafikte, farklı birimler ayrı
# grafikte gösterilir (bkz. build_chart_response gruplama mantığı).
METRIC_GROUPS: Dict[str, List[tuple]] = {
    "cpu": [("cpu_usage_percent", "CPU Kullanımı", "%")],
    "memory": [("memory_usage_percent", "RAM Kullanımı", "%")],
    "disk": [("disk_root_usage_percent", "Disk Kullanımı (/)", "%")],
    "network": [
        ("network_rx_bytes_per_sec", "Network RX", "B/s"),
        ("network_tx_bytes_per_sec", "Network TX", "B/s"),
    ],
    "load": [
        ("load1", "Load (1dk)", ""),
        ("load5", "Load (5dk)", ""),
        ("load15", "Load (15dk)", ""),
    ],
    "disk_io": [
        ("disk_read_bytes_per_sec", "Disk Okuma", "B/s"),
        ("disk_write_bytes_per_sec", "Disk Yazma", "B/s"),
    ],
    "iops": [
        ("disk_read_iops", "Disk Okuma IOPS", "IOPS"),
        ("disk_write_iops", "Disk Yazma IOPS", "IOPS"),
    ],
    "swap": [("swap_usage_percent", "Swap Kullanımı", "%")],
}

_GROUP_KEYWORDS: Dict[str, List[str]] = {
    "iops": ["iops", "ıops", "disk iops"],
    "disk_io": ["disk io", "diskio", "disk i/o", "disk okuma", "disk yazma"],
    "cpu": ["cpu", "işlemci", "islemci"],
    "memory": ["ram", "bellek", "memory", "hafıza", "hafiza"],
    "disk": ["disk"],
    "network": ["network", "ağ", "ag ", "trafik", "traffic", "bandwidth", "bant genişliği"],
    "load": ["load average", "load avg", " load", "yük ortalama", "yük değeri"],
    "swap": ["swap"],
}

# "son 2 saat", "2 saatlik", "son 30 dakika", "1 günlük", "1 aylık" gibi ifadeleri yakalar.
_DURATION_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(saat|saatlik|dakika|dakikalık|dk|gün|günlük|gun|hafta|haftalık|ay|aylık|aylik)",
    re.IGNORECASE,
)

_UNIT_TO_HOURS = {
    "saat": 1.0, "saatlik": 1.0,
    "dakika": 1 / 60, "dakikalık": 1 / 60, "dk": 1 / 60,
    "gün": 24.0, "günlük": 24.0, "gun": 24.0,
    "hafta": 168.0, "haftalık": 168.0,
    "ay": 720.0, "aylık": 720.0, "aylik": 720.0,
}

# Canlı veriler artık (Prometheus + TimescaleDB) 30 gün saklanıyor — üst sınır da
# buna paralel 30 güne (720 saat) çıkarıldı; öncesinde 7 günle sınırlıydı ve veri
# aslında mevcut olsa bile "1 aylık grafik" gibi istekler kesiliyordu.
MAX_HOURS = 720  # 30 gün üst sınır
MAX_POINTS_PER_SERIES = 180  # frontend/LLM için makul üst sınır


def detect_chart_request(message: str) -> Optional[Dict[str, Any]]:
    """
    Mesajda hem bir zaman aralığı (son N saat/dakika/gün) HEM DE en az bir
    metrik grubu (cpu/ram/disk/network/load) geçiyorsa grafik isteği olarak
    yorumlar. İkisi birden yoksa None döner (normal metin akışına düşer) —
    böylece süre belirtmeyen sıradan "cpu kullanımını göster" gibi sorular
    grafiğe değil mevcut metin/Prometheus özetine gider.
    """
    ml = (message or "").lower()

    dur_match = _DURATION_RE.search(ml)
    if not dur_match:
        return None
    amount = float(dur_match.group(1).replace(",", "."))
    unit = dur_match.group(2).lower()
    hours = amount * _UNIT_TO_HOURS.get(unit, 1.0)
    hours = max(0.25, min(hours, MAX_HOURS))

    groups: List[str] = []
    for group, keywords in _GROUP_KEYWORDS.items():
        if any(kw in ml for kw in keywords) and group not in groups:
            groups.append(group)
    if not groups:
        return None

    return {"hours": hours, "groups": groups}


def _downsample(points: List[Dict[str, Any]], max_points: int) -> List[Dict[str, Any]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    out = []
    i = 0.0
    while int(i) < len(points):
        out.append(points[int(i)])
        i += step
    return out


def fetch_chart_data(db: Session, server: Server, hours: float, groups: List[str]) -> List[Dict[str, Any]]:
    """
    Her grup için tek bir "chart" sözlüğü döner:
      {"title", "unit", "series": [{"metric_name", "label", "points": [{"t","v"}]}]}
    Aynı birime sahip metrikler (örn. network RX+TX, B/s) aynı grafikte toplanır.
    """
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    charts: List[Dict[str, Any]] = []

    for group in groups:
        specs = METRIC_GROUPS.get(group)
        if not specs:
            continue
        series = []
        unit = specs[0][2]
        for metric_name, label, _unit in specs:
            rows = (
                db.query(MetricData.timestamp, MetricData.value)
                .filter(
                    MetricData.server_id == server.id,
                    MetricData.metric_name == metric_name,
                    MetricData.timestamp >= start_time,
                )
                .order_by(MetricData.timestamp)
                .all()
            )
            if not rows:
                continue
            points = [{"t": ts.isoformat(), "v": round(float(val), 3)} for ts, val in rows]
            points = _downsample(points, MAX_POINTS_PER_SERIES)
            series.append({"metric_name": metric_name, "label": label, "points": points})

        if series:
            charts.append({
                "group": group,
                "title": _group_title(group, hours),
                "unit": unit,
                "series": series,
            })

    return charts


def _format_duration_label(hours: float) -> str:
    if hours < 1:
        return f"{int(round(hours * 60))} dakika"
    if hours >= 24 and hours % 24 == 0:
        days = int(hours / 24)
        return f"{days} gün" if days > 1 else "1 gün"
    if hours >= 24:
        return f"{hours / 24:g} gün"
    return f"{hours:g} saat"


def _group_title(group: str, hours: float) -> str:
    names = {
        "cpu": "CPU Kullanımı", "memory": "RAM Kullanımı", "disk": "Disk Kullanımı",
        "network": "Network Trafiği", "load": "Load Average", "disk_io": "Disk I/O",
        "iops": "Disk IOPS", "swap": "Swap Kullanımı",
    }
    return f"{names.get(group, group)} — Son {_format_duration_label(hours)}"


def _fmt_bytes_per_sec(v: float) -> str:
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if abs(v) < 1024:
            return f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB/s"


def _series_stats_text(label: str, unit: str, points: List[Dict[str, Any]]) -> str:
    if not points:
        return f"- **{label}**: veri yok"
    values = [p["v"] for p in points]
    avg, mn, mx = sum(values) / len(values), min(values), max(values)
    if unit == "B/s":
        return f"- **{label}**: ort. {_fmt_bytes_per_sec(avg)}, min {_fmt_bytes_per_sec(mn)}, maks {_fmt_bytes_per_sec(mx)}"
    suffix = f" {unit}" if unit else ""
    return f"- **{label}**: ort. {avg:.1f}{suffix}, min {mn:.1f}{suffix}, maks {mx:.1f}{suffix}"


def build_chart_response(db: Session, server: Server, hours: float, groups: List[str]) -> Optional[Dict[str, Any]]:
    """Chat/agent'ın tek çağrıda kullanacağı üst seviye fonksiyon: metin özeti + grafik verisi."""
    charts = fetch_chart_data(db, server, hours, groups)
    if not charts:
        return None

    hours_label = _format_duration_label(hours)
    lines = [f"### {server.name} — Son {hours_label} Metrik Özeti\n"]
    for chart in charts:
        lines.append(f"**{chart['title'].split(' — ')[0]}**")
        for s in chart["series"]:
            lines.append(_series_stats_text(s["label"], chart["unit"], s["points"]))
        lines.append("")
    lines.append("_Detaylı grafik aşağıda gösteriliyor._")

    return {
        "summary_text": "\n".join(lines),
        "charts": [
            {
                "type": "timeseries",
                "title": c["title"],
                "unit": c["unit"],
                "server_id": server.id,
                "server_name": server.name,
                "series": c["series"],
            }
            for c in charts
        ],
    }
