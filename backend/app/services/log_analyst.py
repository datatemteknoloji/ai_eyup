"""
Log Analyst — DB'deki log/olay satırlarını okuyarak AI destekli Kök Neden Analizi yapar.

Desteklenen event_type:
  - log_entry, metric_anomaly  → Linux OS journal / ilgili log_entry
  - virt_log, virt_resource, vcenter_event, vcenter_alarm, vcenter_task
       → aynı host/pencere içindeki sanallaştırma olayları + alarmın kendi payload'u
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from app.core.config import get_active_model
from app.models.event import SystemEvent
from app.services import llm_gateway

logger = logging.getLogger(__name__)

MAX_LOG_ROWS = 150
TIME_WINDOW_MINUTES = 30
VIRT_EVENT_TYPES = (
    "virt_log",
    "virt_resource",
    "vcenter_event",
    "vcenter_alarm",
    "vcenter_task",
)
OS_EVENT_TYPES = ("log_entry", "metric_anomaly")
SUPPORTED_EVENT_TYPES = OS_EVENT_TYPES + VIRT_EVENT_TYPES

MUTATING_KEYWORDS = (
    "systemctl", "service", "restart", "reboot", "shutdown",
    "rm ", "kill", "pkill", "halt", "poweroff", "mkfs", "fdisk",
    "power off", "destroy", "unregister", "delete vm",
)


def _row_dict(r: SystemEvent) -> Dict[str, Any]:
    raw = r.raw_data or {}
    return {
        "ts": r.created_at.isoformat() if r.created_at else "",
        "severity": r.severity or "info",
        "title": r.title,
        "description": (r.description or "")[:400],
        "category": raw.get("category", ""),
        "event_type": r.event_type,
        "host_name": raw.get("host_name") or raw.get("entity") or "",
        "action": raw.get("action") or "",
    }


def log_query(
    db: Session,
    event: SystemEvent,
    max_rows: int = MAX_LOG_ROWS,
) -> List[Dict[str, Any]]:
    et = (event.event_type or "").strip()
    anchor = event.last_seen or event.created_at or datetime.utcnow()
    since = anchor - timedelta(minutes=TIME_WINDOW_MINUTES)
    until = anchor + timedelta(minutes=TIME_WINDOW_MINUTES)

    if et in OS_EVENT_TYPES:
        if not event.server_id:
            return []
        rows = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.server_id == event.server_id,
                SystemEvent.event_type == "log_entry",
                SystemEvent.created_at >= since,
                SystemEvent.created_at <= until,
            )
            .order_by(SystemEvent.created_at.desc())
            .limit(max_rows)
            .all()
        )
        return [_row_dict(r) for r in rows]

    if et in VIRT_EVENT_TYPES:
        raw = event.raw_data or {}
        host = (
            raw.get("host_name")
            or raw.get("entity")
            or raw.get("vm_name")
            or raw.get("object_name")
            or ""
        )
        hv_id = raw.get("hypervisor_id")
        if not host and event.title:
            m = re.search(r"entity\s+(\S+)", event.title, re.I)
            if m:
                host = m.group(1).rstrip(".")

        candidates = (
            db.query(SystemEvent)
            .filter(
                SystemEvent.event_type.in_(VIRT_EVENT_TYPES),
                SystemEvent.created_at >= since,
                SystemEvent.created_at <= until,
            )
            .order_by(SystemEvent.created_at.desc())
            .limit(max_rows * 3)
            .all()
        )

        def _match(r: SystemEvent) -> bool:
            if r.id == event.id:
                return True
            rr = r.raw_data or {}
            if hv_id and rr.get("hypervisor_id") == hv_id:
                return True
            if host:
                blob = " ".join(
                    str(x or "")
                    for x in (
                        r.title,
                        r.description,
                        rr.get("host_name"),
                        rr.get("entity"),
                        rr.get("vm_name"),
                        rr.get("object_name"),
                    )
                ).lower()
                if host.lower() in blob:
                    return True
            if event.title and r.title and event.title[:40] == r.title[:40]:
                return True
            return False

        matched = [r for r in candidates if _match(r)]
        if not any(r.id == event.id for r in matched):
            matched.insert(0, event)
        return [_row_dict(r) for r in matched[:max_rows]]

    return []


def _build_prompt(event: SystemEvent, log_lines: List[Dict]) -> str:
    is_virt = (event.event_type or "") in VIRT_EVENT_TYPES
    persona = (
        "Sen bir VMware/oVirt sanallaştırma ve AIOps uzmanısın."
        if is_virt
        else "Sen bir Linux sistem yöneticisi ve AIOps uzmanısın."
    )
    ctx_label = "SANALLAŞTIRMA / PLATFORM OLAYLARI" if is_virt else "LOG SATIRLARI"
    raw = event.raw_data or {}
    extra = ""
    if is_virt:
        extra = (
            f"\n  Host/Entity : {raw.get('host_name') or raw.get('entity') or '-'}"
            f"\n  Aksiyon     : {raw.get('action') or '-'}"
            f"\n  Kategori    : {raw.get('category') or '-'}"
            f"\n  Platform    : {raw.get('platform_label') or raw.get('platform') or 'virt'}"
        )

    lines_text = "\n".join(
        f"[{(l.get('ts') or '')[:19]}] [{(l.get('event_type') or 'log').upper()}] "
        f"[{(l.get('severity') or 'info').upper()}] {l.get('title') or ''}"
        + (f" — {(l.get('description') or '')[:200]}" if l.get("description") else "")
        for l in log_lines
    )
    empty_hint = (
        "(yakın zaman penceresinde ek olay bulunamadı — aşağıdaki EVENT satırını temel al)"
        if is_virt
        else "(log satırı bulunamadı)"
    )
    return f"""{persona}
Aşağıdaki event ve bağlam satırları için TÜRKÇE kök neden analizi yap.
Kısa, net ve uygulanabilir yanıt ver. Uydurma; veride yoksa "veri yetersiz" de.

EVENT:
  Tür: {event.event_type}
  Önem: {event.severity}
  Başlık: {event.title}
  Açıklama: {(event.description or 'Yok')[:400]}{extra}

SON {len(log_lines)} {ctx_label} (son {TIME_WINDOW_MINUTES} dakika, en yeni önce):
{lines_text or empty_hint}

Lütfen aşağıdaki JSON formatında yanıt ver (başka bir şey yazma):
{{
  "root_cause": "Tek cümle kök neden",
  "impact": "Hangi VM/host/servis etkileniyor",
  "recommendations": [
    "adım 1 — somut kontrol veya aksiyon",
    "adım 2"
  ],
  "confidence": "high|medium|low"
}}"""


def _parse_response(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    return {
        "root_cause": raw[:500] if raw else "Analiz alınamadı",
        "impact": "",
        "recommendations": [],
        "confidence": "low",
    }


def _requires_approval(recommendations: List[str]) -> bool:
    text = " ".join(recommendations).lower()
    return any(kw in text for kw in MUTATING_KEYWORDS)


def analyze_event_logs(
    db: Session,
    event_id: int,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        return {"error": "Event bulunamadı"}

    log_lines = log_query(db, event)
    et = (event.event_type or "").strip()

    if et not in SUPPORTED_EVENT_TYPES:
        return {
            "root_cause": f"Bu event tipi ({et or '?'}) için otomatik kök neden analizi henüz desteklenmiyor.",
            "impact": "",
            "recommendations": [
                "AI Sohbet sekmesinden alarm metnini yapıştırıp sorabilirsiniz",
                "İlgili platform loglarını manuel kontrol edin",
            ],
            "confidence": "low",
            "log_lines_used": 0,
            "model": "",
            "requires_approval": False,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    if not log_lines and et in VIRT_EVENT_TYPES:
        log_lines = [_row_dict(event)]

    if not log_lines and et == "metric_anomaly":
        return {
            "root_cause": "Bu metrik anomalisi için yakın zamanda log satırı bulunamadı.",
            "impact": "",
            "recommendations": ["journalctl -u <servis> --since '30 min ago' ile manuel kontrol edin"],
            "confidence": "low",
            "log_lines_used": 0,
            "model": "",
            "requires_approval": False,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    if not log_lines and et == "log_entry":
        log_lines = [_row_dict(event)]

    active_model = model or get_active_model(db)
    prompt = _build_prompt(event, log_lines)

    try:
        data = llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=120)
        if data.get("error"):
            logger.warning(f"[LogAnalyst] LLM hatası (event #{event_id}): {data['error']}")
            return {"error": f"AI servisi yanıt vermedi: {data['error']}"}

        raw_text = (data.get("response") or "").strip()
        if not raw_text:
            return {"error": "AI servisi boş yanıt döndürdü"}

        parsed = _parse_response(raw_text)
        recommendations = parsed.get("recommendations") or []

        result = {
            "root_cause": parsed.get("root_cause", ""),
            "impact": parsed.get("impact", ""),
            "recommendations": recommendations,
            "confidence": parsed.get("confidence", "low"),
            "log_lines_used": len(log_lines),
            "model": active_model,
            "requires_approval": _requires_approval(recommendations),
            "analyzed_at": datetime.utcnow().isoformat(),
        }
        logger.info(
            f"[LogAnalyst] Tamamlandı: event #{event_id} type={et} | "
            f"{len(log_lines)} satır | model={active_model}"
        )
        return result

    except requests.exceptions.ConnectionError:
        return {"error": "AI servisi bağlantı hatası — Ollama çalışıyor mu?"}
    except requests.exceptions.Timeout:
        return {"error": "AI servisi zaman aşımı (120s)"}
    except Exception as e:
        logger.exception(f"[LogAnalyst] Beklenmeyen hata (event #{event_id})")
        return {"error": str(e)}
