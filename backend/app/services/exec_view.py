"""Kilitli paketin sayfa modeli. Anahtar adları ekrana basılmaz; cümleler burada kurulur.

Demo kart bu modele girmez. GET onu ayrıca ekler.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.exec_health import FORMULA_TR, score_area
from app.services.exec_risks import RULE_TR, rank_findings
from app.services.synthetic_scope import synthetic_hypervisor_ids, synthetic_server_ids

OCP_NOTE = (
    "Bu not küme olaylarından hesaplanıyor. Red Hat'in önerdiği alert tabanlı ölçüm henüz toplanmıyor; "
    "not gerçekte olduğundan kötü görünebilir."
)
SECTION_COUNT = 12
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
Counts = Tuple[int, int]


def _tr_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _tr_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    text_value = f"{float(value):.0f}"
    return f"%{text_value}"


def _tr_gb(value: float) -> str:
    if value >= 1024:
        text = f"{value / 1024:.1f}".replace(".", ",")
        if text.endswith(",0"):
            text = text[:-2]
        return f"{text} TB"
    text = f"{value:.1f}".replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text} GB"


def _safe_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.startswith("ZZ-FAKE") or _IP.search(value):
        return None
    return value


def _fit_assets(pairs: List[Counts], population: int) -> List[Counts]:
    """Popülasyondan fazla olay kimliği tek varlıkta birleşir; eksik varlık temiz sayılır."""
    if population <= 0:
        return []
    ordered = sorted(pairs, key=lambda item: (item[0], item[1]), reverse=True)
    if len(ordered) > population:
        head = ordered[: population - 1]
        rest = ordered[population - 1 :]
        merged = (sum(c for c, _w in rest), sum(w for _c, w in rest))
        ordered = head + [merged]
    if len(ordered) < population:
        ordered = ordered + [(0, 0)] * (population - len(ordered))
    return ordered


def _months(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    if days <= 0:
        return "0"
    months = max(1, int(round(days / 30.0)))
    return str(months)


def _num(facts: List[Dict[str, Any]], section_id: str, key: str) -> Optional[Dict[str, Any]]:
    for report in facts:
        for section in report.get("sections") or []:
            if section.get("id") == section_id:
                return (section.get("numbers") or {}).get(key)
    return None


def _section(facts: List[Dict[str, Any]], section_id: str) -> Optional[Dict[str, Any]]:
    for report in facts:
        for section in report.get("sections") or []:
            if section.get("id") == section_id:
                return section
    return None


def _ready_map(facts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows = []
    for report in facts:
        for item in report.get("data_readiness") or []:
            rows.append({
                "section": item.get("section_id") or "",
                "status": "Ölçüldü" if item.get("status") == "ok" else "Ölçülemedi",
                "missing": item.get("reason") or "",
                "how": item.get("reason") or "",
            })
    return rows


def _sparkline(db: Session, hidden_servers: set) -> List[Dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    try:
        rows = db.execute(text("""
            SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                   CASE
                     WHEN event_type ILIKE '%openshift%' OR COALESCE(source, '') ILIKE '%openshift%' THEN 'OpenShift'
                     WHEN event_type ILIKE '%vcenter%' OR event_type ILIKE '%virt%' OR COALESCE(source, '') ILIKE '%virt%' THEN 'Sanallaştırma'
                     WHEN event_type ILIKE '%windows%' OR COALESCE(source, '') ILIKE '%windows%' THEN 'Windows'
                     ELSE 'Linux'
                   END AS area,
                   CASE WHEN severity IN ('critical', 'emergency') THEN 'kritik' ELSE 'uyarı' END AS sev,
                   COUNT(DISTINCT COALESCE(server_id::text, md5(COALESCE(title, '')))) AS n
            FROM system_events
            WHERE created_at >= :since
              AND severity IN ('critical', 'emergency', 'warning')
              AND (server_id IS NULL OR server_id != ALL(:hidden))
            GROUP BY 1, 2, 3
            ORDER BY 1
        """), {"since": since, "hidden": list(hidden_servers) or [0]}).all()
    except Exception:
        db.rollback()
        return []
    return [{"day": str(r.day), "area": r.area, "severity": r.sev, "count": int(r.n)} for r in rows]


def _capacity_rows(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    section = _section(facts, "b1_virt") or {}
    out = []
    for row in section.get("rows") or []:
        runway = row.get("runway_days") or {}
        early = _months(runway.get("fastest"))
        typical = _months(runway.get("typical"))
        late = _months(runway.get("slowest")) if runway.get("slowest") is not None else None
        out.append({
            "name": "Adsız küme" if (row.get("cluster") or "") in ("", "(küme yok)") else (row.get("cluster") or "Küme"),
            "resource": "bellek",
            "now": _tr_pct(row.get("memory_pct")),
            "cpu": _tr_pct(row.get("cpu_pct")),
            "early": early,
            "typical": typical,
            "late": late or ("12+" if typical else None),
            "low": bool(row.get("low_confidence") or row.get("status") != "ok"),
        })
    out.sort(key=lambda item: int(item["early"] or 99))
    return out


def _server_counts(db: Session) -> Dict[str, int]:
    from app.models.server import Server

    hidden = synthetic_server_ids(db)
    out = {"linux": 0, "linux_agent": 0, "windows": 0, "windows_agent": 0}
    try:
        rows = db.query(
        Server.os_type, Server.node_exporter_running, Server.windows_exporter_running, Server.id,
    ).all()
    except Exception:
        db.rollback()
        return out
    for os_type, linux_agent, windows_agent, sid in rows:
        if sid in hidden:
            continue
        name = (os_type or "").lower()
        if "windows" in name:
            out["windows"] += 1
            if windows_agent:
                out["windows_agent"] += 1
        else:
            out["linux"] += 1
            if linux_agent:
                out["linux_agent"] += 1
    return out


def _virt_population(db: Session, cluster_count: int) -> int:
    syn = list(synthetic_hypervisor_ids(db))
    try:
        params: Dict[str, Any] = {"syn": syn or [0]}
        found = db.execute(text("""
            SELECT count(DISTINCT host_name)
            FROM hypervisor_host_metrics
            WHERE timestamp >= NOW() - INTERVAL '2 days'
              AND host_name IS NOT NULL
              AND hypervisor_id != ALL(:syn)
        """), params).scalar()
    except Exception:
        db.rollback()
        found = 0
    return int(found or 0) or cluster_count


def _event_assets(db: Session) -> Dict[str, Any]:
    """Son 24 saat. Aynı varlık ve olay türü bir kez. Adlar yalnız detay listesine gider."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    hidden = list(synthetic_server_ids(db)) or [0]
    try:
        rows = db.execute(text("""
            SELECT
              CASE
                WHEN event_type ILIKE '%openshift%' OR COALESCE(source, '') ILIKE '%openshift%' THEN 'OpenShift'
                WHEN event_type ILIKE '%vcenter%' OR event_type ILIKE '%virt%'
                  OR COALESCE(source, '') ILIKE '%virt%' OR COALESCE(source, '') ILIKE '%olvm%' THEN 'Sanallaştırma'
                WHEN event_type ILIKE '%windows%' OR COALESCE(source, '') ILIKE '%windows%' THEN 'Windows'
                ELSE 'Linux'
              END AS area,
              COALESCE(server_id::text, md5(COALESCE(title, ''))) AS asset,
              MAX(CASE WHEN severity IN ('critical', 'emergency') THEN 1 ELSE 0 END) AS crit
            FROM system_events
            WHERE created_at >= :since
              AND severity IN ('critical', 'emergency', 'warning')
              AND (server_id IS NULL OR server_id != ALL(:hidden))
            GROUP BY 1, 2, COALESCE(event_type, '')
        """), {"since": since, "hidden": hidden}).all()
    except Exception:
        db.rollback()
        return {"pairs": {}, "named": {}}
    per: Dict[str, Dict[str, List[int]]] = {}
    for area, asset, crit in rows:
        slot = per.setdefault(area, {}).setdefault(str(asset), [0, 0])
        if int(crit or 0):
            slot[0] += 1
        else:
            slot[1] += 1
    ids = [int(asset) for area_assets in per.values() for asset in area_assets if str(asset).isdigit()]
    names: Dict[int, str] = {}
    if ids:
        from app.models.server import Server
        for sid, host, vm in (
            db.query(Server.id, Server.hostname, Server.vm_name).filter(Server.id.in_(ids[:300])).all()
        ):
            label = _safe_name(vm) or _safe_name(host)
            if label:
                names[int(sid)] = label
    named: Dict[str, List[Dict[str, str]]] = {}
    pairs: Dict[str, List[Counts]] = {}
    for area, assets in per.items():
        pairs[area] = [(c, w) for c, w in assets.values()]
        ranked = sorted(assets.items(), key=lambda item: (item[1][0], item[1][1]), reverse=True)
        rows_named = []
        for asset, (crit, warn) in ranked:
            if not str(asset).isdigit() or int(asset) not in names:
                continue
            scored = score_area([(crit, warn)], monitored=True)
            rows_named.append({
                "name": names[int(asset)],
                "status": scored["status"],
                "critical": _tr_int(crit),
                "warning": _tr_int(warn),
                "usage": "—",
            })
            if len(rows_named) >= 10:
                break
        named[area] = rows_named
    return {"pairs": pairs, "named": named}


def _areas(db: Session, facts: List[Dict[str, Any]], series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts = _server_counts(db)
    ocp = _section(facts, "b1_ocp") or {}
    clusters = int(((ocp.get("numbers") or {}).get("clusters") or {}).get("value") or 0)
    nodes = int(((ocp.get("numbers") or {}).get("nodes") or {}).get("value") or 0)
    virt_rows = (_section(facts, "b1_virt") or {}).get("rows") or []
    virt_pop = _virt_population(db, len(virt_rows))
    events = _event_assets(db)
    pairs: Dict[str, List[Counts]] = events["pairs"]
    named: Dict[str, List[Dict[str, str]]] = events["named"]

    def assets_for(name: str, population: int, monitored: bool) -> List[Counts]:
        if not monitored:
            return []
        return _fit_assets(pairs.get(name) or [], population)

    cards = [
        {
            "name": "OpenShift",
            "monitored": clusters > 0 and nodes > 0,
            "population": nodes,
            "metrics_fixed": [
                {"label": "Küme", "value": _tr_int(clusters)},
                {"label": "Node", "value": _tr_int(nodes)},
            ],
            "reason": OCP_NOTE,
            "formula": FORMULA_TR + " " + OCP_NOTE,
            "third": "Açık kritik uyarı",
        },
        {
            "name": "Sanallaştırma",
            "monitored": virt_pop > 0,
            "population": virt_pop,
            "metrics_fixed": [
                {"label": "Küme", "value": _tr_int(len(virt_rows))},
                {"label": "En yüksek bellek", "value": _highest_mem(virt_rows)},
            ],
            "reason": "vCenter ve OLVM kümeleri.",
            "formula": FORMULA_TR,
            "third": "Açık kritik sorun",
        },
        {
            "name": "Linux",
            "monitored": counts["linux"] > 0,
            "population": counts["linux"],
            "metrics_fixed": [
                {"label": "İzlenen sunucu", "value": _tr_int(counts["linux"])},
            ],
            "tail": {"label": "En yüksek bellek", "value": "—"},
            "reason": "Sunucu olayları." if counts["linux"] else "Linux sunucusu yok.",
            "formula": FORMULA_TR,
            "third": "Kritik sorunlu sunucu",
        },
        {
            "name": "Windows",
            "monitored": counts["windows_agent"] > 0,
            "population": counts["windows"] if counts["windows_agent"] else 0,
            "metrics_fixed": [
                {"label": "Sunucu", "value": _tr_int(counts["windows"])},
                {"label": "İzleme", "value": "Var" if counts["windows_agent"] else "Yok"},
            ],
            "reason": "Windows sunucuları izleniyor." if counts["windows_agent"] else "Windows sunucularında izleme ajanı yok.",
            "formula": FORMULA_TR,
            "third": "Ajanı çalışan",
        },
    ]
    built = []
    for card in cards:
        asset_rows = assets_for(card["name"], card["population"], card["monitored"])
        scored = score_area(asset_rows, monitored=card["monitored"])
        points = [item for item in series if item["area"] == card["name"]]
        if card["name"] == "Windows":
            third_value = _tr_int(counts["windows_agent"])
        else:
            third_value = _tr_int(scored["critical_assets"]) if card["monitored"] else "—"
        metrics = card["metrics_fixed"] + [{"label": card["third"], "value": third_value}]
        if card.get("tail"):
            metrics.append(card["tail"])
        reason = card["reason"]
        if card["name"] == "Linux" and scored["critical_assets"]:
            reason = f"Bu ay Linux alanında { _tr_int(scored['critical_assets']) } sunucuda kritik uyarı açık."
        built.append({
            "name": card["name"],
            "status": scored["status"],
            "score": scored["score"],
            "reason": reason,
            "metrics": metrics,
            "series": points,
            "formula": card["formula"],
            "change": "ilk ay",
            "assets": named.get(card["name"]) or [],
        })
    return built


def _highest_mem(rows: List[Dict[str, Any]]) -> str:
    vals = [r.get("memory_pct") for r in rows if r.get("memory_pct") is not None]
    if not vals:
        return "—"
    return _tr_pct(max(vals))


def _kpis(facts: List[Dict[str, Any]], areas: List[Dict[str, Any]], risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    watched = [a for a in areas if a["status"] != "İzleme yok"]
    critical = [a for a in watched if a["status"] == "Kritik"]
    cap = _capacity_rows(facts)
    nearest = next((row for row in cap if row.get("early")), None)
    off = _num(facts, "a2", "powered_off")
    cpu = _num(facts, "a2", "wasted_vcpu")
    ram = _num(facts, "a2", "wasted_ram_gb")
    disk = _num(facts, "a2", "wasted_disk_gb")
    old_critical = sum(1 for row in risks if row.get("severity") == "critical" and int(row.get("age_days") or 0) >= 30)
    reclaim = "—"
    if cpu or ram or disk:
        parts = []
        if cpu:
            parts.append(f"{cpu['display'][0]} vCPU")
        if ram:
            parts.append(f"{ram['display'][0]} GB RAM")
        if disk:
            parts.append(_tr_gb(float(disk.get("value") or 0)))
        reclaim = " · ".join(parts)
    return [
        {"label": "Kritik durumdaki alan", "value": f"{len(critical)} / {len(watched)} alan" if watched else "—", "hint": ""},
        {
            "label": "En yakın kapasite eşiği",
            "value": (
                f"{nearest['name']} · bellek · eşikte"
                if nearest and nearest.get("early") == "0"
                else f"{nearest['name']} · bellek · {nearest['early']}–{nearest['late'] or nearest['early']} ay"
                if nearest and nearest.get("early")
                else "—"
            ),
            "hint": "" if nearest else "geçmiş veri yetersiz",
        },
        {"label": "Geri kazanılabilir kaynak", "value": reclaim if off else "—", "hint": ""},
        {"label": "30 günden uzun açık kritik sorun", "value": _tr_int(old_critical), "hint": ""},
    ]


def _section_ok(facts: List[Dict[str, Any]], section_id: str) -> bool:
    section = _section(facts, section_id)
    return bool(section and section.get("status") == "ok")


def _idle(db: Session, facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    def count(section_id: str, key: str) -> str:
        num = _num(facts, section_id, key)
        if not num or num.get("value") is None:
            return "—"
        return _tr_int(int(num["value"]))

    cpu = _num(facts, "a2", "wasted_vcpu")
    ram = _num(facts, "a2", "wasted_ram_gb")
    disk = _num(facts, "a2", "wasted_disk_gb")
    categories = [
        {
            "name": "Kapalı VM",
            "count": count("a2", "powered_off"),
            "vcpu": cpu["display"][0] if cpu else "—",
            "ram": f"{ram['display'][0]} GB" if ram else "—",
            "disk": _tr_gb(float(disk["value"])) if disk and disk.get("value") is not None else "—",
        },
        {"name": "Atıl VM", "count": count("a2_idle", "idle"), "vcpu": "—", "ram": "—", "disk": "—"},
        {"name": "Aşırı boyutlu", "count": count("a2_oversized", "oversized"), "vcpu": "—", "ram": "—", "disk": "—"},
        {"name": "Eski snapshot", "count": count("a2_snapshots", "snapshots"), "vcpu": "—", "ram": "—", "disk": "—"},
        {"name": "Yetim disk", "count": count("a2_orphan", "orphans"), "vcpu": "—", "ram": "—", "disk": "—"},
    ]
    top: List[Dict[str, str]] = []
    try:
        from app.models.server import Server
        from app.services.chat_quality import power_state as ps

        hidden = synthetic_server_ids(db)
        ranked = []
        for vm in db.query(Server).filter(Server.hypervisor_id.isnot(None)).all():
            if vm.id in hidden or not ps.is_off(vm.vm_power_state):
                continue
            name = _safe_name(vm.vm_name) or _safe_name(vm.hostname)
            if not name:
                continue
            ranked.append((int(vm.vm_disk_gb or 0), name, int(vm.vm_cpu_count or 0), int(vm.vm_memory_mb or 0)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        for disk_gb, name, cpu_n, ram_mb in ranked[:10]:
            top.append({
                "name": name,
                "cluster": "—",
                "category": "Kapalı VM",
                "amount": f"{_tr_int(cpu_n)} vCPU · {_tr_gb(ram_mb / 1024)} RAM · {_tr_gb(float(disk_gb))}",
                "age": "—",
            })
    except Exception:
        db.rollback()
    return {
        "categories": categories,
        "top": top,
        "note": "Bu değerler ayrılmış kaynaktır, gerçek tüketim değildir.",
    }


def _calendar(capacity: List[Dict[str, Any]]) -> Dict[str, Any]:
    bands = []
    items = []
    for row in capacity:
        if not row.get("early"):
            continue
        late = row.get("late") or row["early"]
        bands.append({
            "label": f"{row['name']} bellek",
            "early": int(row["early"]),
            "late": int(str(late).replace("+", "") or row["early"]),
            "missing": False,
        })
        when = "eşikte" if str(row.get("early")) == "0" else f"{row['early']}–{late} ay"
        items.append({
            "when": when,
            "area": row["name"],
            "event": "Bellek eşiği",
            "impact": "Kapasite",
        })
    bands.append({"label": "Destek bitişi", "missing": True})
    bands.append({"label": "Garanti bitişi", "missing": True})
    items.append({"when": "—", "area": "Destek", "event": "veri yok", "impact": "—"})
    items.append({"when": "—", "area": "Garanti", "event": "veri yok", "impact": "—"})
    return {"bands": bands, "items": items}


def _operations(facts: List[Dict[str, Any]]) -> str:
    manual = _num(facts, "a6", "p50_saat")
    auto = _num(facts, "a6", "auto_closed")
    if manual:
        return "Manuel kapanış var. Çözüm süresi ortalaması ana ekranda gösterilmez."
    count = auto["display"][0] if auto else "—"
    return f"Olaylar otomatik kapatılıyor; çözüm süresi ölçülemiyor. Otomatik kapanan: {count}."


def _sources(db: Session) -> List[Dict[str, str]]:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    mid = since + timedelta(days=23)
    hidden = list(synthetic_server_ids(db)) or [0]
    try:
        rows = db.execute(text("""
            SELECT
              CASE
                WHEN event_type ILIKE '%openshift%' OR COALESCE(source, '') ILIKE '%openshift%' THEN 'OpenShift küme olayları'
                WHEN event_type ILIKE '%vcenter%' OR event_type ILIKE '%virt%'
                  OR COALESCE(source, '') ILIKE '%virt%' THEN 'Sanallaştırma küme olayları'
                WHEN event_type ILIKE '%windows%' OR COALESCE(source, '') ILIKE '%windows%' THEN 'Windows sunucu olayları'
                ELSE 'Linux sunucu olayları'
              END AS label,
              COUNT(DISTINCT COALESCE(server_id::text, md5(COALESCE(title, '')))) FILTER (WHERE created_at >= :mid) AS recent,
              COUNT(DISTINCT COALESCE(server_id::text, md5(COALESCE(title, '')))) FILTER (WHERE created_at < :mid) AS older
            FROM system_events
            WHERE created_at >= :since
              AND severity IN ('critical', 'emergency', 'warning')
              AND (server_id IS NULL OR server_id != ALL(:hidden))
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 5
        """), {"since": since, "mid": mid, "hidden": hidden}).all()
    except Exception:
        db.rollback()
        return []
    out = []
    for row in rows:
        recent = int(row.recent or 0)
        older = int(row.older or 0)
        if older == 0:
            trend = "ilk ay"
        elif recent > older:
            trend = "artıyor"
        elif recent < older:
            trend = "azalıyor"
        else:
            trend = "aynı"
        out.append({"label": row.label, "count": _tr_int(recent), "trend": trend})
    return out


def _failover(facts: List[Dict[str, Any]]) -> str:
    section = _section(facts, "b2") or {}
    rows = section.get("rows") or []
    if not rows:
        return "Bir sunucu arızalanırsa kalan kapasite ölçülemedi çünkü küme kapasitesi yok."
    short = [row.get("cluster") or "Küme" for row in rows if (row.get("n_plus_one") == "fail")]
    if short:
        return "Bir sunucu arızalanırsa kalan kapasite yetmeyen küme: " + ", ".join(str(name) for name in short) + "."
    return "Bir sunucu arızalanırsa kalan kapasite yetmeyen küme yok."


def _coverage(
    facts: List[Dict[str, Any]],
    areas: List[Dict[str, Any]],
    capacity: List[Dict[str, Any]],
    summary: Dict[str, str],
) -> Dict[str, Any]:
    rows = [{
        "section": "Özet",
        "status": "Ölçüldü" if summary.get("text") else "Ölçülemedi",
        "missing": "" if summary.get("text") else "Özet cümlesi yok",
        "how": "Şimdi yenile ile paket yeniden üretilir",
    }]
    for area in areas:
        ok = area["status"] not in ("Ölçülemedi", "İzleme yok")
        rows.append({
            "section": area["name"],
            "status": "Ölçüldü" if ok else area["status"],
            "missing": "" if ok else area["reason"],
            "how": "İzleme ajanı veya küme olayı gerekir" if not ok else "",
        })
    rows.extend([
        {
            "section": "Kapasite",
            "status": "Ölçüldü" if capacity else "Ölçülemedi",
            "missing": "" if capacity else "Küme bellek serisi yok",
            "how": "En az 14 günlük bellek ölçümü gerekir",
        },
        {
            "section": "Yatırım",
            "status": "Ölçüldü" if _section_ok(facts, "b2") else "Ölçülemedi",
            "missing": "" if _section_ok(facts, "b2") else "Küme kapasite planı yok",
            "how": "Sanal küme kapasitesi ölçülünce tamamlanır",
        },
        {
            "section": "Takvim",
            "status": "Ölçüldü" if capacity else "Ölçülemedi",
            "missing": "Destek ve garanti kaydı yok",
            "how": "Referans paketi ve gerçek garanti kaydı gerekir",
        },
        {
            "section": "Risk",
            "status": "Ölçüldü",
            "missing": "",
            "how": "",
        },
        {
            "section": "Atıl kaynak",
            "status": "Ölçüldü" if _section_ok(facts, "a2") else "Ölçülemedi",
            "missing": "" if _section_ok(facts, "a2") else "Kapalı sanal makine sayımı yok",
            "how": "Sanal makine envanteri gerekir",
        },
        {
            "section": "Olay",
            "status": "Ölçüldü" if _section(facts, "a6") else "Ölçülemedi",
            "missing": "" if _section(facts, "a6") else "Dönem olayı yok",
            "how": "Kilitli paket olay bölümünü taşır",
        },
        {
            "section": "Veri kapsamı",
            "status": "Ölçüldü",
            "missing": "OpenShift node ve Linux disk tahmini için veri yok",
            "how": "Günlük doluluk serisi birikince tamamlanır",
        },
    ])
    measured = sum(1 for row in rows if row["status"] == "Ölçüldü")
    return {"measured": measured, "total": SECTION_COUNT, "rows": rows[:SECTION_COUNT]}


def build_view(db: Session, facts: List[Dict[str, Any]], summary: Dict[str, str]) -> Dict[str, Any]:
    hidden = synthetic_server_ids(db)
    series = _sparkline(db, hidden)
    areas = _areas(db, facts, series)
    risks = rank_findings(db, synthetic_source_ids=synthetic_hypervisor_ids(db))
    mom = _section(facts, "a1_mom") or {}
    if mom.get("status") == "ok":
        for area in areas:
            area["change"] = "aylık kilit"
    cap = _capacity_rows(facts)
    hosts = _num(facts, "b2", "hosts_needed")
    return {
        "summary": summary,
        "kpis": _kpis(facts, areas, risks),
        "areas": areas,
        "capacity": cap,
        "failover": _failover(facts),
        "investment": {
            "value": (hosts or {}).get("display", ["—"])[0],
            "sentence": "Önümüzdeki 12 ayda ek sunucu ihtiyacı görünmüyor." if hosts and hosts.get("value") == 0 else "Ek sunucu ihtiyacı bu pakette yok.",
        },
        "calendar": _calendar(cap),
        "idle": _idle(db, facts),
        "operations": _operations(facts),
        "sources": _sources(db),
        "risks": [
            {
                "area": row["area"],
                "sentence": row["sentence"],
                "age": _tr_int(int(row["age_days"])),
                "age_days": int(row["age_days"]),
                "action": row["action"],
                "entity": row.get("entity_name"),
            }
            for row in risks
        ],
        "risk_rule": RULE_TR,
        "events": series,
        "coverage": _coverage(facts, areas, cap, summary),
        "openshift_note": OCP_NOTE,
        "formula": FORMULA_TR,
    }


def demo_cards(db: Session) -> List[Dict[str, Any]]:
    """Bayrak açıksa demo sağlayıcı sayıları. Kilitli pakete yazılmaz."""
    from app.services.backup.demo_gate import backup_mode
    from app.services.hw.demo_gate import hw_mode

    cards = []
    if backup_mode(db) == "demo":
        from app.models.backup import BkProtectedObject
        from app.services.backup.demo_gate import active_instances
        ids = [row.id for row in active_instances(db, include_demo=True)]
        count = db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_(ids or [0])).count() if ids else 0
        cards.append({
            "title": "Yedek kapsamı",
            "demo": True,
            "lines": [{"label": "Korunan nesne", "value": _tr_int(count)}],
        })
    else:
        cards.append({"title": "Yedek kapsamı", "demo": False, "lines": [], "status": "Ölçülemedi"})
    if hw_mode(db) == "demo":
        from app.models.hw import HwWarranty
        from app.services.hw.demo_gate import _enabled_rows, is_demo_kind
        ids = [row.id for row in _enabled_rows(db) if is_demo_kind(row.kind)]
        count = db.query(HwWarranty).filter(HwWarranty.instance_id.in_(ids or [0])).count() if ids else 0
        cards.append({
            "title": "Donanım ve garanti",
            "demo": True,
            "lines": [{"label": "Garanti kaydı", "value": _tr_int(count)}],
        })
    else:
        cards.append({"title": "Donanım ve garanti", "demo": False, "lines": [], "status": "Ölçülemedi"})
    if os.getenv("BACKUP_DEMO_ENABLED") or os.getenv("HW_DEMO_ENABLED"):
        return cards
    return cards
