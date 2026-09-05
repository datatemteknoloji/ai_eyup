"""
Sanallaştırma zaman serisi trend / tahmin motoru (DB, deterministik).

Neden ayrı bir motor: "son 7 günde kötüleşen VM'ler", "datastore ne zaman
dolar", "30 günlük sağlık trendi" gibi sorularda aritmetiği modele bırakmak
uydurma sayı üretiyor. Burada eğim (regr_slope) ve tükenme tahmini SQL'de
hesaplanır; model yalnızca yorumlar.

vCenter'ın kendi rollup'ı (QueryPerf + lookback_hours) her ortamda yoktur:
doğrudan ESXi host'a bağlanıldığında yalnız realtime (20 sn) sağlanır,
tarihsel interval (5 dk / 30 dk / 2 sa / 1 gün) YOKTUR. Bu motor
`hypervisor_host_metrics` / `virt_vm_metrics` / `virt_datastore_metrics`
üzerinden çalıştığı için o ortamlarda da trend sorularını yanıtlar.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor

logger = logging.getLogger(__name__)

# Varlık → (tablo, kimlik kolonu, ek etiket kolonları, metrik whitelist)
# Kolon adları SQL'e string olarak girdiği için whitelist ZORUNLU.
_ENTITIES: Dict[str, Dict[str, Any]] = {
    "host": {
        "table": "hypervisor_host_metrics",
        "key": "host_name",
        "labels": ("cluster_name", "connection_state", "overall_status"),
        "metrics": {
            "cpu_pct": ("cpu_usage_pct", "%", 90.0),
            "mem_pct": ("mem_usage_pct", "%", 90.0),
            "ds_pct": ("ds_usage_pct", "%", 90.0),
            "vms_running": ("vms_running", "adet", None),
            "net_rx_kbps": ("net_rx_kbps", "kbps", None),
            "net_tx_kbps": ("net_tx_kbps", "kbps", None),
        },
    },
    "vm": {
        "table": "virt_vm_metrics",
        "key": "vm_name",
        "labels": ("host_name", "cluster_name", "datastore", "power_state"),
        "metrics": {
            "cpu_pct": ("cpu_usage_pct", "%", 90.0),
            "mem_pct": ("mem_usage_pct", "%", 90.0),
            "cpu_ready_pct": ("cpu_ready_pct", "%", 5.0),
            "cpu_costop_ms": ("cpu_costop_ms", "ms", None),
            "disk_latency_ms": ("disk_latency_ms", "ms", 20.0),
            "disk_read_iops": ("disk_read_iops", "IOPS", None),
            "disk_write_iops": ("disk_write_iops", "IOPS", None),
            "balloon_mb": ("balloon_mb", "MB", None),
            "swapped_mb": ("swapped_mb", "MB", None),
            "net_dropped_rx": ("net_dropped_rx", "paket", None),
            "net_dropped_tx": ("net_dropped_tx", "paket", None),
            "guest_disk_pct": ("guest_disk_pct", "%", 90.0),
            "snapshot_count": ("snapshot_count", "adet", None),
        },
    },
    "datastore": {
        "table": "virt_datastore_metrics",
        "key": "name",
        "labels": ("ds_type",),
        "metrics": {
            "usage_pct": ("usage_pct", "%", 90.0),
            "free_gb": ("free_gb", "GB", 0.0),
            "used_gb": ("used_gb", "GB", None),
            "uncommitted_gb": ("uncommitted_gb", "GB", None),
        },
    },
}

# Kullanıcı/model eşanlamlıları → kanonik varlık
_ENTITY_ALIASES = {
    "host": "host", "hosts": "host", "esx": "host", "esxi": "host",
    "hypervisor": "host", "sunucu": "host",
    "vm": "vm", "vms": "vm", "virtualmachine": "vm", "sanal": "vm",
    "datastore": "datastore", "datastores": "datastore", "ds": "datastore",
    "storage": "datastore", "depolama": "datastore",
}

# Metrik eşanlamlıları (varlıktan bağımsız kaba eşleme)
_METRIC_ALIASES = {
    "cpu": "cpu_pct", "cpu_usage": "cpu_pct", "cpu_usage_pct": "cpu_pct",
    "mem": "mem_pct", "memory": "mem_pct", "ram": "mem_pct",
    "mem_usage_pct": "mem_pct", "bellek": "mem_pct",
    "disk": "ds_pct", "datastore_pct": "ds_pct", "doluluk": "usage_pct",
    "usage": "usage_pct", "kullanim": "usage_pct", "free": "free_gb",
    "bos": "free_gb", "latency": "disk_latency_ms", "gecikme": "disk_latency_ms",
    "ready": "cpu_ready_pct", "cpu_ready": "cpu_ready_pct",
    "balloon": "balloon_mb", "swap": "swapped_mb",
}


def _canon_entity(value: Optional[str]) -> str:
    key = (value or "host").strip().lower()
    return _ENTITY_ALIASES.get(key, key if key in _ENTITIES else "host")


def _canon_metric(entity: str, value: Optional[str]) -> Optional[str]:
    metrics = _ENTITIES[entity]["metrics"]
    key = (value or "").strip().lower().replace(" ", "_").replace("%", "_pct")
    if not key:
        return None
    if key in metrics:
        return key
    alias = _METRIC_ALIASES.get(key)
    if alias in metrics:
        return alias
    # "cpu_usage_percent" gibi serbest yazımlar için gevşek eşleşme
    for canon in metrics:
        if canon.split("_")[0] in key:
            return canon
    return None


def _default_metric(entity: str) -> str:
    return {"host": "mem_pct", "vm": "cpu_pct", "datastore": "usage_pct"}[entity]


def _round(value: Any, digits: int = 2) -> Optional[float]:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def run_metric_trend(
    db: Session,
    *,
    entity_type: str = "host",
    metric: Optional[str] = None,
    name_filter: Optional[str] = None,
    hypervisor: Optional[str] = None,
    days: float = 7,
    top_n: int = 10,
    order: str = "worsening",
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """Zaman serisinden varlık başına trend + kapasite tükenme tahmini üretir.

    order: worsening (eğime göre en hızlı artan/kötüleşen) | improving |
           highest (son değere göre) | lowest
    threshold: tükenme tahmini eşiği; verilmezse metrik varsayılanı kullanılır
               (ör. doluluk %90, free_gb 0).
    """
    entity = _canon_entity(entity_type)
    spec = _ENTITIES[entity]
    metric_key = _canon_metric(entity, metric) or _default_metric(entity)
    column, unit, default_threshold = spec["metrics"][metric_key]
    limit = max(1, min(int(top_n or 10), 50))
    window_days = max(0.05, min(float(days or 7), 400.0))

    hv_id: Optional[int] = None
    if hypervisor:
        hv = (
            db.query(Hypervisor)
            .filter(Hypervisor.name.ilike(f"%{hypervisor.strip()}%"))
            .first()
        )
        if hv:
            hv_id = hv.id

    label_cols = "".join(f", max({c}::text) AS {c}" for c in spec["labels"])
    where = [f"timestamp >= now() - interval '{window_days} days'", f"{column} IS NOT NULL"]
    params: Dict[str, Any] = {}
    if hv_id is not None:
        where.append("hypervisor_id = :hv_id")
        params["hv_id"] = hv_id
    if name_filter:
        where.append(f"{spec['key']} ILIKE :name_filter")
        params["name_filter"] = f"%{name_filter.strip()}%"

    # regr_slope(y, x): x = gün cinsinden epoch → eğim "birim/gün".
    sql = f"""
        WITH src AS (
            SELECT {spec['key']} AS entity_key, timestamp, {column} AS value
                   {''.join(f', {c}' for c in spec['labels'])}
            FROM {spec['table']}
            WHERE {' AND '.join(where)}
        ),
        agg AS (
            SELECT entity_key,
                   count(*)                                  AS samples,
                   min(timestamp)                            AS first_ts,
                   max(timestamp)                            AS last_ts,
                   avg(value)                                AS avg_value,
                   min(value)                                AS min_value,
                   max(value)                                AS max_value,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95_value,
                   regr_slope(value, extract(epoch FROM timestamp) / 86400.0) AS slope_per_day
                   {label_cols}
            FROM src GROUP BY entity_key
        ),
        edges AS (
            SELECT DISTINCT ON (entity_key) entity_key, value AS last_value
            FROM src ORDER BY entity_key, timestamp DESC
        ),
        firsts AS (
            SELECT DISTINCT ON (entity_key) entity_key, value AS first_value
            FROM src ORDER BY entity_key, timestamp ASC
        )
        SELECT agg.*, edges.last_value, firsts.first_value
        FROM agg JOIN edges USING (entity_key) JOIN firsts USING (entity_key)
    """
    rows = [dict(r._mapping) for r in db.execute(text(sql), params)]

    limit_value = default_threshold if threshold is None else float(threshold)
    # free_gb'de "tükenme" aşağı yönlüdür; diğerlerinde yukarı.
    descending_metric = metric_key in ("free_gb",)

    items: List[Dict[str, Any]] = []
    for row in rows:
        slope = _round(row.get("slope_per_day"), 4)
        last = _round(row.get("last_value"))
        first = _round(row.get("first_value"))
        samples = int(row.get("samples") or 0)
        span_days = None
        if row.get("first_ts") and row.get("last_ts"):
            span_days = _round(
                (row["last_ts"] - row["first_ts"]).total_seconds() / 86400.0, 3
            )

        # 3 örneğin veya ~2 saatlik pencerenin altında eğim gürültüdür.
        reliable = samples >= 3 and (span_days or 0) >= 0.08
        if not reliable:
            slope = None

        direction = "sabit"
        if slope is not None:
            noise = 0.5 if unit == "%" else max(abs(_round(row.get("avg_value")) or 1) * 0.02, 0.01)
            if slope > noise:
                direction = "artıyor"
            elif slope < -noise:
                direction = "azalıyor"

        days_to_limit = None
        forecast_note = None
        if slope and last is not None and limit_value is not None:
            gap = (last - limit_value) if descending_metric else (limit_value - last)
            moving = (-slope) if descending_metric else slope
            if moving > 0 and gap > 0:
                days_to_limit = _round(gap / moving, 1)
            elif gap <= 0:
                forecast_note = f"eşik ({limit_value}{unit}) zaten aşıldı"

        items.append({
            "name": row.get("entity_key"),
            **{c: row.get(c) for c in spec["labels"]},
            "samples": samples,
            "window_days": span_days,
            "first": first,
            "last": last,
            "delta": _round((last - first) if (last is not None and first is not None) else None),
            "avg": _round(row.get("avg_value")),
            "min": _round(row.get("min_value")),
            "max": _round(row.get("max_value")),
            "p95": _round(row.get("p95_value")),
            "slope_per_day": slope,
            "trend": direction,
            "days_to_threshold": days_to_limit,
            "forecast_note": forecast_note,
            "insufficient_history": not reliable,
        })

    order_key = (order or "worsening").strip().lower()
    if order_key == "improving":
        items.sort(key=lambda i: (i["slope_per_day"] is None, i["slope_per_day"] or 0))
    elif order_key == "highest":
        items.sort(key=lambda i: (i["last"] is None, -(i["last"] or 0)))
    elif order_key == "lowest":
        items.sort(key=lambda i: (i["last"] is None, i["last"] or 0))
    else:
        items.sort(key=lambda i: (i["slope_per_day"] is None, -(i["slope_per_day"] or 0)))

    all_short = bool(items) and all(i["insufficient_history"] for i in items)
    note = None
    if not items:
        note = (
            f"{spec['table']} tablosunda son {window_days:g} günde {metric_key} verisi yok. "
            "Bu tablo her metrik sync turunda dolar; yeni kurulumda birikmesi zaman alır."
        )
    elif all_short:
        note = (
            "Kayıtlı geçmiş henüz trend hesaplamaya yetmiyor (varlık başına <3 örnek "
            "veya çok kısa pencere). Mevcut değerler doğrudur, eğim/tahmin verilmedi."
        )

    return {
        "ok": True,
        "source": f"db:{spec['table']}",
        "entity_type": entity,
        "metric": metric_key,
        "column": column,
        "unit": unit,
        "requested_days": window_days,
        "threshold": limit_value,
        "order": order_key,
        "count": len(items),
        "items": items[:limit],
        "note": note,
        "hint": (
            "slope_per_day = birim/gün eğim (regr_slope). days_to_threshold = eşiğe "
            "kalan gün. insufficient_history=true ise trend yorumu YAPMA, yalnız "
            "mevcut değeri bildir."
        ),
    }
