"""
Compare Windows — İki zaman diliminin log/event karşılaştırması + LLM analizi.

Kullanım senaryoları:
  1. Sorun öncesi vs. sorun sonrası (baseline vs. incident)
  2. Haftalık karşılaştırma (son 1 saat vs. geçen hafta aynı saat)
  3. Sunucu-sunucu karşılaştırma (server_a vs. server_b, aynı zaman)

Çıktı:
  {
    "window_a": {...stats...},
    "window_b": {...stats...},
    "delta": {...},
    "llm_analysis": {
      "summary": str,
      "key_differences": [str, ...],
      "regression_indicators": [str, ...],
      "recommendations": [str, ...],
      "confidence": str
    },
    "model": str,
    "analyzed_at": str
  }
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from app.core.config import settings, get_active_model
from app.models.event import SystemEvent
from app.services import llm_gateway

logger = logging.getLogger(__name__)

MAX_ROWS_PER_WINDOW = 200


# ── Pencere istatistiği ───────────────────────────────────────────────────────

def _window_stats(
    db: Session,
    server_id: Optional[int],
    since: datetime,
    until: datetime,
    event_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Bir zaman penceresi için istatistik ve temsili log satırlarını toplar."""
    query = db.query(SystemEvent).filter(
        SystemEvent.created_at >= since,
        SystemEvent.created_at <= until,
    )
    if server_id is not None:
        query = query.filter(SystemEvent.server_id == server_id)
    if event_types:
        query = query.filter(SystemEvent.event_type.in_(event_types))

    rows = query.order_by(SystemEvent.created_at.desc()).limit(MAX_ROWS_PER_WINDOW).all()

    severity_counts = Counter(r.severity for r in rows)
    type_counts = Counter(r.event_type for r in rows)
    top_titles = Counter(r.title for r in rows if r.title).most_common(10)

    # Error/critical satırların örnekleri
    critical_samples = [
        {
            "ts": r.created_at.isoformat() if r.created_at else "",
            "severity": r.severity,
            "type": r.event_type,
            "title": r.title,
            "description": (r.description or "")[:200],
        }
        for r in rows
        if r.severity in ("error", "critical")
    ][:20]

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total_events": len(rows),
        "severity_counts": dict(severity_counts),
        "type_counts": dict(type_counts),
        "top_titles": [{"title": t, "count": c} for t, c in top_titles],
        "critical_samples": critical_samples,
        "error_rate": (
            (severity_counts.get("error", 0) + severity_counts.get("critical", 0)) / len(rows)
            if rows else 0.0
        ),
    }


def _delta(a: Dict, b: Dict) -> Dict[str, Any]:
    """İki pencerenin temel metriklerinin farkını hesaplar."""
    def _pct_change(v_a: float, v_b: float) -> Optional[float]:
        if v_a == 0:
            return None if v_b == 0 else 999.0
        return round((v_b - v_a) / v_a * 100, 1)

    total_a = a["total_events"]
    total_b = b["total_events"]
    err_a = a["severity_counts"].get("error", 0) + a["severity_counts"].get("critical", 0)
    err_b = b["severity_counts"].get("error", 0) + b["severity_counts"].get("critical", 0)

    return {
        "total_events_change": total_b - total_a,
        "total_events_pct": _pct_change(total_a, total_b),
        "error_events_change": err_b - err_a,
        "error_events_pct": _pct_change(err_a, err_b),
        "error_rate_change": round(b["error_rate"] - a["error_rate"], 4),
        "new_event_types": list(set(b["type_counts"]) - set(a["type_counts"])),
        "disappeared_event_types": list(set(a["type_counts"]) - set(b["type_counts"])),
    }


# ── LLM prompt ───────────────────────────────────────────────────────────────

def _build_compare_prompt(
    window_a: Dict,
    window_b: Dict,
    delta: Dict,
    label_a: str = "Önceki pencere",
    label_b: str = "Sonraki pencere",
    context: str = "",
) -> str:
    def _fmt_window(w: Dict, label: str) -> str:
        lines = [
            f"{label}: {w['since'][:19]} → {w['until'][:19]}",
            f"  Toplam event: {w['total_events']} | Hata oranı: {w['error_rate']*100:.1f}%",
            f"  Önem dağılımı: {w['severity_counts']}",
            f"  Tip dağılımı: {w['type_counts']}",
        ]
        if w["top_titles"]:
            lines.append("  En sık başlıklar:")
            for item in w["top_titles"][:5]:
                lines.append(f"    - {item['title']} ({item['count']}x)")
        if w["critical_samples"]:
            lines.append("  Kritik/hata örnekleri:")
            for s in w["critical_samples"][:5]:
                lines.append(f"    [{s['ts'][:19]}] [{s['severity'].upper()}] {s['title']}")
                if s["description"]:
                    lines.append(f"      {s['description'][:150]}")
        return "\n".join(lines)

    delta_lines = [
        f"  Event sayısı değişimi: {delta['total_events_change']:+d} "
        f"({delta['total_events_pct']:+.1f}%)" if delta['total_events_pct'] is not None
        else f"  Event sayısı değişimi: {delta['total_events_change']:+d}",
        f"  Hata event değişimi: {delta['error_events_change']:+d}",
        f"  Hata oranı değişimi: {delta['error_rate_change']*100:+.1f}%",
    ]
    if delta["new_event_types"]:
        delta_lines.append(f"  Yeni event tipleri: {', '.join(delta['new_event_types'])}")
    if delta["disappeared_event_types"]:
        delta_lines.append(f"  Kaybolan event tipleri: {', '.join(delta['disappeared_event_types'])}")

    context_section = f"\nEK BAĞLAM:\n{context}\n" if context else ""

    return f"""Sen bir senior Linux/AIOps mühendisisin.
İki zaman diliminin log/event verilerini karşılaştır ve TÜRKÇE analiz yap.
{context_section}
=== {label_a.upper()} ===
{_fmt_window(window_a, label_a)}

=== {label_b.upper()} ===
{_fmt_window(window_b, label_b)}

=== DELTA ===
{chr(10).join(delta_lines)}

Lütfen yalnızca aşağıdaki JSON formatında yanıt ver:
{{
  "summary": "2-3 cümle genel değerlendirme",
  "key_differences": [
    "fark 1",
    "fark 2"
  ],
  "regression_indicators": [
    "regresyon veya kötüleşme göstergesi (varsa)"
  ],
  "recommendations": [
    "öneri 1",
    "öneri 2"
  ],
  "confidence": "high|medium|low"
}}"""


def _parse_llm_response(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    return {
        "summary": raw[:600] if raw else "Analiz alınamadı",
        "key_differences": [],
        "regression_indicators": [],
        "recommendations": [],
        "confidence": "low",
    }


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def compare_windows(
    db: Session,
    server_id_a: Optional[int],
    since_a: datetime,
    until_a: datetime,
    server_id_b: Optional[int],
    since_b: datetime,
    until_b: datetime,
    label_a: str = "Pencere A",
    label_b: str = "Pencere B",
    event_types: Optional[List[str]] = None,
    context: str = "",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    İki pencereyi karşılaştırır ve LLM ile analiz yapar.

    server_id_a == server_id_b → aynı sunucu, farklı zaman dilimleri
    server_id_a != server_id_b → farklı sunucular, aynı (veya farklı) zaman dilimleri

    event_types: None ise tüm tipler; örn. ["log_entry", "metric_anomaly"]
    context: AWR raporu özeti veya başka ek bağlam metni
    """
    window_a = _window_stats(db, server_id_a, since_a, until_a, event_types)
    window_b = _window_stats(db, server_id_b, since_b, until_b, event_types)
    delta = _delta(window_a, window_b)

    active_model = model or get_active_model(db)
    prompt = _build_compare_prompt(window_a, window_b, delta, label_a, label_b, context)

    try:
        data = llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=180)
        if data.get("error"):
            llm_analysis = {"summary": f"AI servisi hatası: {data['error']}", "confidence": "low"}
        else:
            raw = (data.get("response") or "").strip()
            llm_analysis = _parse_llm_response(raw)
    except requests.exceptions.ConnectionError:
        llm_analysis = {"summary": "LLM bağlantı hatası", "confidence": "low"}
    except requests.exceptions.Timeout:
        llm_analysis = {"summary": "LLM zaman aşımı (180s)", "confidence": "low"}
    except Exception as e:
        llm_analysis = {"summary": f"Hata: {str(e)[:200]}", "confidence": "low"}

    return {
        "window_a": window_a,
        "window_b": window_b,
        "delta": delta,
        "llm_analysis": llm_analysis,
        "model": active_model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
