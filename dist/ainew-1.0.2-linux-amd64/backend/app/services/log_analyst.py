"""
Log Analyst — DB'deki log satırlarını okuyarak AI destekli Kök Neden Analizi yapar.

Akış:
  SystemEvent (event_id) → log_query → ilgili log satırları (log_entry tipi)
  → Ollama prompt → yapılandırılmış yanıt (kök neden + öneriler)

Tasarım kararları:
  - DB-first: SSH re-collect yok; log satırları zaten SystemEvent tablosunda
  - Local-only: Ollama kullanılır, loglar dışarı çıkmaz
  - Token cap: max 150 satır / ~8000 token (local model context penceresi)
  - event_type="log_entry" için tam analiz;
    "metric_anomaly" için aynı zaman penceresindeki log_entry'ler;
    diğer tipler için "log bağlamı yok" yanıtı
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from app.core.config import settings, get_active_model
from app.models.event import SystemEvent
from app.services import llm_gateway

logger = logging.getLogger(__name__)

MAX_LOG_ROWS = 150
TIME_WINDOW_MINUTES = 30
MUTATING_KEYWORDS = (
    "systemctl", "service", "restart", "reboot", "shutdown",
    "rm ", "kill", "pkill", "halt", "poweroff", "mkfs", "fdisk",
)


# ── 1) Log Query ─────────────────────────────────────────────────────────────

def log_query(
    db: Session,
    event: SystemEvent,
    max_rows: int = MAX_LOG_ROWS,
) -> List[Dict[str, Any]]:
    """
    Bir event'e ait log_entry satırlarını DB'den çeker.

    - event_type="log_entry"   → event'in server_id + ±TIME_WINDOW_MINUTES
    - event_type="metric_anomaly" → aynı penceredeki log_entry satırları
    - diğer                    → boş liste (caller "log bağlamı yok" döner)
    """
    if not event.server_id:
        return []

    if event.event_type not in ("log_entry", "metric_anomaly"):
        return []

    anchor = event.last_seen or event.created_at or datetime.utcnow()
    since = anchor - timedelta(minutes=TIME_WINDOW_MINUTES)
    until = anchor + timedelta(minutes=TIME_WINDOW_MINUTES)

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

    return [
        {
            "ts": r.created_at.isoformat() if r.created_at else "",
            "severity": r.severity,
            "title": r.title,
            "description": (r.description or "")[:400],
            "category": (r.raw_data or {}).get("category", ""),
        }
        for r in rows
    ]


# ── 2) Ollama Analizi ─────────────────────────────────────────────────────────

def _build_prompt(event: SystemEvent, log_lines: List[Dict]) -> str:
    lines_text = "\n".join(
        f"[{l['ts'][:19]}] [{l['severity'].upper()}] {l['title']}"
        + (f" — {l['description'][:200]}" if l["description"] else "")
        for l in log_lines
    )
    return f"""Sen bir Linux sistem yöneticisi ve AIOps uzmanısın.
Aşağıdaki event ve log satırları için TÜRKÇE kök neden analizi yap.
Kısa, net ve uygulanabilir yanıt ver.

EVENT:
  Tür: {event.event_type}
  Önem: {event.severity}
  Başlık: {event.title}
  Açıklama: {(event.description or 'Yok')[:300]}

SON {len(log_lines)} LOG SATIRI (son {TIME_WINDOW_MINUTES} dakika, en yeni önce):
{lines_text or '(log satırı bulunamadı)'}

Lütfen aşağıdaki JSON formatında yanıt ver (başka bir şey yazma):
{{
  "root_cause": "Tek cümle kök neden",
  "impact": "Hangi servis/sistem etkileniyor",
  "recommendations": [
    "adım 1 — somut komut veya aksiyon",
    "adım 2"
  ],
  "confidence": "high|medium|low"
}}"""


def _parse_response(raw: str) -> Dict[str, Any]:
    """LLM yanıtından JSON çıkarmaya çalışır; başarısızsa serbest metin döner."""
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


# ── 3) Ana fonksiyon ─────────────────────────────────────────────────────────

def analyze_event_logs(
    db: Session,
    event_id: int,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Bir event için log tabanlı AI kök neden analizi yapar.

    Dönüş:
      {
        "root_cause": str,
        "impact": str,
        "recommendations": [str, ...],
        "confidence": "high|medium|low",
        "log_lines_used": int,
        "model": str,
        "requires_approval": bool,
        "analyzed_at": str,
      }
    veya hata durumunda:
      {"error": str}
    """
    event = db.query(SystemEvent).filter(SystemEvent.id == event_id).first()
    if not event:
        return {"error": "Event bulunamadı"}

    log_lines = log_query(db, event)

    if event.event_type not in ("log_entry", "metric_anomaly"):
        return {
            "root_cause": "Bu event tipi için log bağlamı yok.",
            "impact": "",
            "recommendations": [],
            "confidence": "low",
            "log_lines_used": 0,
            "model": "",
            "requires_approval": False,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    if not log_lines and event.event_type == "metric_anomaly":
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
            f"[LogAnalyst] Tamamlandı: event #{event_id} | "
            f"{len(log_lines)} satır | model={active_model} | "
            f"confidence={result['confidence']}"
        )
        return result

    except requests.exceptions.ConnectionError:
        logger.warning("[LogAnalyst] Ollama'ya bağlanılamadı")
        return {"error": "AI servisi bağlantı hatası — Ollama çalışıyor mu?"}
    except requests.exceptions.Timeout:
        logger.warning(f"[LogAnalyst] Ollama timeout (event #{event_id})")
        return {"error": "AI servisi zaman aşımı (120s)"}
    except Exception as e:
        logger.error(f"[LogAnalyst] Beklenmeyen hata (event #{event_id}): {e}")
        return {"error": f"Analiz hatası: {str(e)[:200]}"}
