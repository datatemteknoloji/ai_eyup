"""Kilitli paketin sayfa modeli. Anahtar adları ekrana basılmaz; cümleler burada kurulur.

Demo kart bu modele girmez. GET onu ayrıca ekler.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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


def _tr_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _tr_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    text_value = f"{float(value):.0f}"
    return f"%{text_value}"


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
            "name": row.get("cluster") or "Küme",
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
        rows = db.query(Server.os_type, Server.node_exporter_running, Server.hypervisor_id, Server.id).all()
    except Exception:
        db.rollback()
        return out
    for os_type, agent, _hv, sid in rows:
        if sid in hidden:
            continue
        name = (os_type or "").lower()
        if "windows" in name:
            out["windows"] += 1
        else:
            out["linux"] += 1
            if agent:
                out["linux_agent"] += 1
    return out


def _areas(db: Session, facts: List[Dict[str, Any]], series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counts = _server_counts(db)
    ocp = _section(facts, "b1_ocp") or {}
    clusters = ((ocp.get("numbers") or {}).get("clusters") or {}).get("value") or 0
    nodes = ((ocp.get("numbers") or {}).get("nodes") or {}).get("value") or 0
    virt_rows = (_section(facts, "b1_virt") or {}).get("rows") or []
    cards = [
        {
            "name": "OpenShift",
            "monitored": clusters > 0,
            "assets": [(0, 0)] * max(int(nodes), 0),
            "metrics": [
                {"label": "Küme", "value": _tr_int(int(clusters))},
                {"label": "Node", "value": _tr_int(int(nodes))},
                {"label": "Açık kritik uyarı", "value": "—"},
            ],
            "reason": OCP_NOTE,
            "formula": FORMULA_TR + " " + OCP_NOTE,
        },
        {
            "name": "Sanallaştırma",
            "monitored": len(virt_rows) > 0,
            "assets": [(0, 0)] * max(len(virt_rows), 0) or ([(0, 0)] if virt_rows else []),
            "metrics": [
                {"label": "Küme", "value": _tr_int(len(virt_rows))},
                {"label": "En yüksek bellek", "value": _highest_mem(virt_rows)},
                {"label": "Açık kritik sorun", "value": "—"},
            ],
            "reason": "vCenter ve OLVM kümeleri.",
            "formula": FORMULA_TR,
        },
        {
            "name": "Linux",
            "monitored": counts["linux"] > 0,
            "assets": [(0, 0)] * counts["linux"] if counts["linux"] else [],
            "metrics": [
                {"label": "İzlenen sunucu", "value": _tr_int(counts["linux"])},
                {"label": "Kritik sorunlu sunucu", "value": "0" if counts["linux"] else "—"},
                {"label": "Ajanı çalışan", "value": _tr_int(counts["linux_agent"])},
            ],
            "reason": "Sunucu olayları." if counts["linux"] else "Linux sunucusu yok.",
            "formula": FORMULA_TR,
        },
        {
            "name": "Windows",
            "monitored": False,
            "assets": [],
            "metrics": [
                {"label": "Sunucu", "value": "—"},
                {"label": "İzleme", "value": "Yok"},
                {"label": "Exporter", "value": "Yok"},
            ],
            "reason": "Windows sunucularında izleme ajanı yok.",
            "formula": FORMULA_TR,
        },
    ]
    built = []
    for card in cards:
        scored = score_area(card["assets"], monitored=card["monitored"])
        points = [item for item in series if item["area"] == card["name"]]
        built.append({
            "name": card["name"],
            "status": scored["status"],
            "score": scored["score"],
            "reason": card["reason"] if card["name"] != "OpenShift" or scored["status"] != "İzleme yok" else card["reason"],
            "metrics": card["metrics"],
            "series": points,
            "formula": card["formula"],
            "change": "ilk ay",
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
            parts.append(f"{disk['display'][0]} GB")
        reclaim = " · ".join(parts)
    return [
        {"label": "Kritik durumdaki alan", "value": f"{len(critical)} / {len(watched)} alan" if watched else "—", "hint": ""},
        {
            "label": "En yakın kapasite eşiği",
            "value": f"{nearest['name']} · bellek · {nearest['early']}–{nearest['late'] or nearest['early']} ay" if nearest and nearest.get("early") else "—",
            "hint": "" if nearest else "geçmiş veri yetersiz",
        },
        {"label": "Geri kazanılabilir kaynak", "value": reclaim if off else "—", "hint": ""},
        {"label": "30 günden uzun açık kritik sorun", "value": _tr_int(old_critical), "hint": ""},
    ]


def _coverage(facts: List[Dict[str, Any]], areas: List[Dict[str, Any]]) -> Dict[str, Any]:
    measured_names = []
    for area in areas:
        if area["status"] not in ("Ölçülemedi", "İzleme yok"):
            measured_names.append(area["name"])
    if _section(facts, "a2") and _section(facts, "a2").get("status") == "ok":
        measured_names.append("atıl kaynak")
    if _section(facts, "b2") and (_section(facts, "b2") or {}).get("status") == "ok":
        measured_names.append("yatırım")
    if _capacity_rows(facts):
        measured_names.append("kapasite")
    measured = min(SECTION_COUNT, len(set(measured_names)) or 0)
    rows = []
    for item in _ready_map(facts):
        if item["status"] != "Ölçüldü":
            rows.append({
                "section": item["section"],
                "status": item["status"],
                "missing": item["missing"],
                "how": "Ayrıntı satırı açılınca",
            })
    return {"measured": measured, "total": SECTION_COUNT, "rows": rows[:12]}


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
        "investment": {
            "value": (hosts or {}).get("display", ["—"])[0],
            "sentence": "Önümüzdeki 12 ayda ek sunucu ihtiyacı görünmüyor." if hosts and hosts.get("value") == 0 else "Ek sunucu ihtiyacı bu pakette yok.",
        },
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
        "coverage": _coverage(facts, areas),
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
