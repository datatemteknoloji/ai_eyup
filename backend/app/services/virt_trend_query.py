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
            "net_rx_kbps": ("net_rx_kbps", "KBps", None),
            "net_tx_kbps": ("net_tx_kbps", "KBps", None),
            # Host performans sayaçları (QueryPerf ile toplanır) — "host'un
            # kendisi mi darboğaz" sorusunun ölçülebilir tarafı.
            "cpu_ready_pct": ("cpu_ready_pct", "%", 5.0),
            "mem_balloon_mb": ("mem_balloon_mb", "MB", None),
            "mem_swap_used_mb": ("mem_swap_used_mb", "MB", 1.0),
            "disk_latency_ms": ("disk_latency_ms", "ms", 20.0),
            "disk_device_latency_ms": ("disk_device_latency_ms", "ms", 20.0),
            "disk_read_iops": ("disk_read_iops", "IOPS", None),
            "disk_write_iops": ("disk_write_iops", "IOPS", None),
            "net_dropped_rx": ("net_dropped_rx", "paket", None),
            "net_dropped_tx": ("net_dropped_tx", "paket", None),
        },
    },
    # Cluster: ayrı bir hypertable YOK — host satırları (cluster_name,
    # timestamp) ikilisine indirgenerek türetilir. Cluster kapasite tahmini
    # ("bu cluster'da 3 ay sonra yer kalır mı") bu eksen olmadan hiç
    # cevaplanamıyordu; host bazlı eğim cluster'ın toplamını göstermez.
    "cluster": {
        "table": "hypervisor_host_metrics",
        "key": "cluster_name",
        "labels": (),
        "extra_where": ("cluster_name IS NOT NULL", "cluster_name <> ''"),
        "aggregate": "avg",
        "metrics": {
            # Oranlar cluster ortalaması, kapasiteler toplam olarak indirgenir.
            "cpu_pct": ("cpu_usage_pct", "%", 90.0, "avg"),
            "mem_pct": ("mem_usage_pct", "%", 90.0, "avg"),
            "ds_pct": ("ds_usage_pct", "%", 90.0, "avg"),
            "cpu_total_mhz": ("cpu_total_mhz", "MHz", None, "sum"),
            "mem_total_mb": ("mem_total_mb", "MB", None, "sum"),
            "ds_total_gb": ("ds_total_gb", "GB", None, "sum"),
            "ds_used_gb": ("ds_used_gb", "GB", None, "sum"),
            "vms_running": ("vms_running", "adet", None, "sum"),
            "vms_total": ("vms_total", "adet", None, "sum"),
            "cpu_ready_pct": ("cpu_ready_pct", "%", 5.0, "max"),
            "disk_latency_ms": ("disk_latency_ms", "ms", 20.0, "max"),
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
            "net_rx_kbps": ("net_rx_kbps", "KBps", None),
            "net_tx_kbps": ("net_tx_kbps", "KBps", None),
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
            "read_iops": ("read_iops", "IOPS", None),
            "write_iops": ("write_iops", "IOPS", None),
            "read_latency_ms": ("read_latency_ms", "ms", 20.0),
            "write_latency_ms": ("write_latency_ms", "ms", 20.0),
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
    "cluster": "cluster", "clusters": "cluster", "kume": "cluster",
    "küme": "cluster", "kumeler": "cluster", "kümeler": "cluster",
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
    "network": "net_tx_kbps", "net": "net_tx_kbps", "throughput": "net_tx_kbps",
    "net_rx": "net_rx_kbps", "net_tx": "net_tx_kbps",
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
    return {
        "host": "mem_pct",
        "vm": "cpu_pct",
        "datastore": "usage_pct",
        "cluster": "mem_pct",
    }[entity]


def _round(value: Any, digits: int = 2) -> Optional[float]:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


# Değer filtresinin hangi istatistiğe uygulandığı. Pencere içinde tek bir sayı
# yok: "CPU'su %80 üstü VM'ler" sorusu anlık son değere de, kalıcı yüksek
# kullanımı gösteren p95'e de bakabilir. Varsayılan `last` — kullanıcı "şu an"
# demeden de genelde güncel durumu kastediyor; kalıcılık istendiğinde p95/avg
# seçilir. Serbest metin ASLA kolon adı olarak kullanılmaz (whitelist).
_VALUE_BASES: Dict[str, str] = {
    "last": "last", "son": "last", "current": "last", "anlik": "last",
    "anlık": "last", "guncel": "last", "güncel": "last", "now": "last",
    "avg": "avg", "average": "avg", "ortalama": "avg", "mean": "avg",
    "p95": "p95", "95": "p95", "percentile": "p95", "yuzde95": "p95",
    "max": "max", "peak": "max", "maksimum": "max", "en_yuksek": "max",
    "min": "min", "minimum": "min", "en_dusuk": "min",
}


def _canon_basis(value: Optional[str]) -> str:
    key = (value or "").strip().lower().replace(" ", "_")
    return _VALUE_BASES.get(key, "last")


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _apply_value_filter(
    items: List[Dict[str, Any]],
    basis: str,
    lo: Optional[float],
    hi: Optional[float],
) -> tuple:
    """Eşik filtresini uygular → (kalan satırlar, değeri olmayan eleme sayısı)."""
    if lo is None and hi is None:
        return items, 0
    kept: List[Dict[str, Any]] = []
    unknown = 0
    for item in items:
        value = item.get(basis)
        if value is None:
            unknown += 1
            continue
        if lo is not None and value < lo:
            continue
        if hi is not None and value > hi:
            continue
        kept.append(item)
    return kept, unknown


def _classify_pattern(
    direction: str,
    avg_v: Optional[float],
    max_v: Optional[float],
    last: Optional[float],
    reliable: bool,
) -> Optional[str]:
    """Ani sıçrama (spike) ile sürekli yükseliş/düşüş (sustained trend) ayrımı.

    "Son 24 saatte sürekli artan VM'leri bul, ani spike'lardan ayır" gibi
    sorularda bu yorumu modele bırakmak (yalnız avg/max/last verip) uydurma
    sonuç riski taşır — burada basit ama deterministik bir sınıflandırma
    üretilir; model yalnızca bu etiketi raporlar.

    Dönenler: "sürekli_yükseliş" | "sürekli_düşüş" | "dalgalı_artış" |
    "ani_sıçrama" | "kararlı" | None (güvenilir eğim yoksa).
    """
    if not reliable:
        return None
    rng = (max_v - avg_v) if (max_v is not None and avg_v is not None) else None
    if direction == "azalıyor":
        return "sürekli_düşüş"
    if direction == "artıyor":
        # last, max'a yakınsa (avg→max aralığının >=%60'ı) yükseliş HALA
        # sürüyor; değilse yükselip düşmüş (dalgalı artış) olabilir.
        if rng and rng > 0 and last is not None:
            closeness = (last - avg_v) / rng
            return "sürekli_yükseliş" if closeness >= 0.6 else "dalgalı_artış"
        return "sürekli_yükseliş"
    # Eğim düz ama tepe (max) ortalamadan çok yüksek VE son değer tepeye
    # yakın değil → bir noktada sıçramış, sonra normale dönmüş.
    if (
        rng and avg_v and rng > abs(avg_v) * 0.4 and last is not None
        and (last - avg_v) < rng * 0.4
    ):
        return "ani_sıçrama"
    return "kararlı"


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
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    value_basis: Optional[str] = None,
) -> Dict[str, Any]:
    """Zaman serisinden varlık başına trend + kapasite tükenme tahmini üretir.

    order: worsening (eğime göre en hızlı artan/kötüleşen) | improving |
           highest (son değere göre) | lowest
    threshold: tükenme tahmini eşiği; verilmezse metrik varsayılanı kullanılır
               (ör. doluluk %90, free_gb 0).
    min_value/max_value: DEĞER FİLTRESİ — "CPU'su %80 üzerinde olan VM'ler"
               gibi eşikli sorular için. `order=highest` yalnız top-N verir,
               "eşiği aşanların TÜMÜ" sorusunu cevaplayamaz; eşik kodda sabit
               olan deterministik handler'lar da (ör. %90) tek değere kilitli.
               Filtre `value_basis` istatistiğine uygulanır.
    value_basis: last (varsayılan) | avg | p95 | max | min
    """
    entity = _canon_entity(entity_type)
    spec = _ENTITIES[entity]
    metric_key = _canon_metric(entity, metric) or _default_metric(entity)
    # Metrik tanımı 3'lü (kolon, birim, eşik) veya 4'lü (+ indirgeme fonksiyonu)
    # olabilir. 4. eleman yalnız türetilmiş varlıklarda (cluster) anlamlıdır:
    # oranlar ortalama, kapasiteler toplam, gecikmeler maksimum ile indirgenir.
    _mdef = spec["metrics"][metric_key]
    column, unit, default_threshold = _mdef[0], _mdef[1], _mdef[2]
    reduce_fn = _mdef[3] if len(_mdef) > 3 else spec.get("aggregate")
    if reduce_fn not in (None, "avg", "sum", "max", "min"):
        reduce_fn = "avg"
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
    where.extend(spec.get("extra_where") or ())
    params: Dict[str, Any] = {}
    if hv_id is not None:
        where.append("hypervisor_id = :hv_id")
        params["hv_id"] = hv_id
    if name_filter:
        where.append(f"{spec['key']} ILIKE :name_filter")
        params["name_filter"] = f"%{name_filter.strip()}%"

    # regr_slope(y, x): x = gün cinsinden epoch → eğim "birim/gün".
    if reduce_fn and not spec["labels"]:
        # Türetilmiş varlık (cluster): aynı timestamp'te birden çok host satırı
        # var; eğim hesabından ÖNCE tek değere indirgenmeli, aksi hâlde
        # regr_slope host sayısındaki dalgalanmayı trend sanar.
        src_select = (
            f"SELECT {spec['key']} AS entity_key, timestamp, "
            f"{reduce_fn}({column}) AS value\n"
            f"            FROM {spec['table']}\n"
            f"            WHERE {' AND '.join(where)}\n"
            f"            GROUP BY {spec['key']}, timestamp"
        )
    else:
        src_select = (
            f"SELECT {spec['key']} AS entity_key, timestamp, {column} AS value"
            f"{''.join(f', {c}' for c in spec['labels'])}\n"
            f"            FROM {spec['table']}\n"
            f"            WHERE {' AND '.join(where)}"
        )

    sql = f"""
        WITH src AS (
            {src_select}
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

        # Ani sıçrama (spike) ile sürekli yükseliş (sustained rise) ayrımı —
        # "son 24 saatte sürekli artan VM'leri bul, ani spike'lardan ayır" gibi
        # sorularda bu ayrımı modele bırakmak (yalnızca avg/max/last verip)
        # uydurma yorum riski taşır; burada basit ama deterministik bir
        # sınıflandırma üretilir.
        avg_v = _round(row.get("avg_value"))
        max_v = _round(row.get("max_value"))
        pattern = _classify_pattern(direction, avg_v, max_v, last, reliable)

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
            "pattern": pattern,
            "days_to_threshold": days_to_limit,
            "forecast_note": forecast_note,
            "insufficient_history": not reliable,
        })

    # Değer filtresi: satırlar zaten varlık başına indirgendiği için SQL'e
    # gerek yok (varlık sayısı yüzler mertebesinde) ve kolon adı SQL'e hiç
    # girmiyor. Filtre sıralama/limit'ten ÖNCE uygulanır: aksi hâlde top_n
    # eşiği aşan varlıkları eleyebilir.
    basis = _canon_basis(value_basis)
    lo = _float_or_none(min_value)
    hi = _float_or_none(max_value)
    total_before_filter = len(items)
    items, excluded_unknown = _apply_value_filter(items, basis, lo, hi)

    order_key = (order or "worsening").strip().lower()
    if order_key == "improving":
        items.sort(key=lambda i: (i["slope_per_day"] is None, i["slope_per_day"] or 0))
    elif order_key == "highest":
        items.sort(key=lambda i: (i["last"] is None, -(i["last"] or 0)))
    elif order_key == "lowest":
        items.sort(key=lambda i: (i["last"] is None, i["last"] or 0))
    else:
        items.sort(key=lambda i: (i["slope_per_day"] is None, -(i["slope_per_day"] or 0)))

    filter_desc = None
    if lo is not None or hi is not None:
        bounds = []
        if lo is not None:
            bounds.append(f"≥{_round(lo)}{unit}")
        if hi is not None:
            bounds.append(f"≤{_round(hi)}{unit}")
        filter_desc = f"{metric_key} {basis} {' ve '.join(bounds)}"

    all_short = bool(items) and all(i["insufficient_history"] for i in items)
    note = None
    if not items and filter_desc and total_before_filter:
        # Veri VAR ama eşiği aşan yok — bu geçerli bir cevaptır ("hiçbiri"),
        # "veri yok" ile karıştırılırsa model yanlışlıkla eksik veri bildirir.
        note = (
            f"Son {window_days:g} günde {total_before_filter} {entity} incelendi; "
            f"{filter_desc} koşulunu sağlayan yok. Veri eksikliği DEĞİL, "
            "koşula uyan varlık bulunmadı."
        )
    elif not items:
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
        "matched": len(items),
        "scanned": total_before_filter,
        "value_filter": (
            {
                "basis": basis,
                "min_value": lo,
                "max_value": hi,
                "description": filter_desc,
                "excluded_no_value": excluded_unknown,
            }
            if filter_desc
            else None
        ),
        "items": items[:limit],
        "note": note,
        "hint": (
            "slope_per_day = birim/gün eğim (regr_slope). days_to_threshold = eşiğe "
            "kalan gün. insufficient_history=true ise trend yorumu YAPMA, yalnız "
            "mevcut değeri bildir. pattern: 'sürekli_yükseliş'/'sürekli_düşüş' = "
            "trend devam ediyor (son değer tepeye/dibe yakın); 'ani_sıçrama' = bir "
            "noktada yükselip normale dönmüş (spike, ŞU AN sorun değil); "
            "'dalgalı_artış' = artıyor ama düzensiz; 'kararlı' = anlamlı değişim yok. "
            "'Spike ile sürekli trendi ayır' türü sorularda pattern alanını kullan, "
            "kendi yorumunu üretme."
            + (
                f" value_filter uygulandı: {total_before_filter} varlıktan {len(items)} "
                "tanesi koşulu sağladı; count TÜM eşleşmedir, items ilk top_n satırdır."
                if filter_desc
                else ""
            )
        ),
    }
