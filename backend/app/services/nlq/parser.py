"""
NLQ Natural Language → JSON parser (LLM). Never invents host data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from app.services import llm_gateway
from app.services.nlq.schema import ALLOWED_FIELDS, ALLOWED_OPERATORS, DEFAULT_LIMIT

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sen bir Linux operasyon sorgu asistanısın.
Kullanıcının doğal dilde yazdığı soruyu YALNIZCA tanımlı JSON sorgu şemasına dönüştür.
Asla sunucu, hostname, IP, metrik, sayı veya durum uydurma.
Doğrudan SQL veya shell komutu üretme.
Kullanıcı açıkça canlı doğrulama / şimdi doğrula / canlı kontrol et demedikçe live_check=false.
Soru mevcut alanlarla cevaplanamıyorsa intent=unsupported dön.
Belirsizse güvenli ve dar yorum kullan.
Çıktın YALNIZCA geçerli JSON olmalı (markdown yok).

İzinli intent: search_servers | unsupported
İzinli field'lar: {fields}
İzinli operator'lar: {ops}

Şema örneği:
{{
  "intent": "search_servers",
  "filters": [{{"field": "uptime_days", "operator": ">", "value": 200}}],
  "sort": {{"field": "uptime_days", "direction": "desc"}},
  "limit": 100,
  "live_check": false,
  "requested_columns": ["hostname", "ip_address", "environment", "uptime_days", "boot_time", "collection_time", "collection_status"]
}}

environment değerleri: production | staging | development | unknown
service_status için inactive/failed/not_running veya active kullan.
"Son N gün içinde reboot" → last_reboot_date >= N (gün olarak sayı) ve operator ">=".
"Patch tarihi N günden eski" → last_patch_date < N (gün) operator "<".
"Top N disk" → sort disk_usage_percent desc + limit N.
"Veri alınamayan / unreachable" → collection_status = failed veya unreachable; "stale" için collection_time.
""".format(
    fields=", ".join(sorted(ALLOWED_FIELDS)),
    ops=", ".join(sorted(ALLOWED_OPERATORS)),
)

LIVE_HINTS = (
    "canlı", "canli", "şimdi doğrula", "simdi dogrula", "live check", "live verify",
    "doğrula", "dogrula", "şu an kontrol", "su an kontrol",
)


def detect_live_check_phrase(question: str) -> bool:
    q = (question or "").lower()
    return any(h in q for h in LIVE_HINTS)


def _extract_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    # strip markdown fence
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if m:
            text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _heuristic_parse(question: str) -> Optional[dict]:
    """Fallback when LLM unavailable — covers core TR/EN patterns."""
    q = (question or "").lower()
    filters = []
    sort = None
    limit = DEFAULT_LIMIT
    live = detect_live_check_phrase(question)

    m = re.search(r"uptime[^\d]*(\d+)\s*g[uü]n", q) or re.search(r"(\d+)\s*g[uü]nden?\s*(yüksek|fazla|üzerinde|uzerinde|>)", q)
    if "uptime" in q or "çalışma süresi" in q or "calisma suresi" in q:
        num = re.search(r"(\d+)\s*g[uü]n", q)
        if num:
            op = ">" if any(x in q for x in ("yüksek", "fazla", "üzerinde", "uzerinde", "üstünde", ">", "higher", "more than", "over")) else ">"
            filters.append({"field": "uptime_days", "operator": op, "value": int(num.group(1))})
            sort = {"field": "uptime_days", "direction": "desc"}

    m = re.search(r"disk[^\d%]*%?\s*(\d+)", q) or re.search(r"%\s*(\d+).*disk", q)
    if "disk" in q and ("%" in q or "yüzde" in q or "yuzde" in q or "percent" in q or "üzeri" in q or "uzeri" in q):
        num = (
            re.search(r"(\d+)\s*%", q)
            or re.search(r"%\s*(\d+)", q)
            or re.search(r"yüzde\s*(\d+)|yuzde\s*(\d+)", q)
        )
        if num:
            val = int(next(g for g in num.groups() if g is not None))
            filters.append({"field": "disk_usage_percent", "operator": ">", "value": val})
            sort = {"field": "disk_usage_percent", "direction": "desc"}

    if "cpu" in q and ("%" in q or "yüzde" in q or "yuzde" in q or "üzeri" in q or "uzeri" in q):
        num = re.search(r"(\d+)\s*%", q) or re.search(r"%\s*(\d+)", q) or re.search(r"yüzde\s*(\d+)", q)
        if num:
            val = int(next(g for g in num.groups() if g is not None))
            filters.append({"field": "cpu_usage_percent", "operator": ">", "value": val})

    if "reboot" in q or "yeniden başlat" in q or "yeniden baslat" in q:
        num = re.search(r"(\d+)\s*g[uü]n", q)
        days = int(num.group(1)) if num else 30
        filters.append({"field": "last_reboot_date", "operator": ">=", "value": days})

    if "patch" in q or "yama" in q:
        num = re.search(r"(\d+)\s*g[uü]n", q)
        days = int(num.group(1)) if num else 90
        filters.append({"field": "last_patch_date", "operator": "<", "value": days})

    if "ntp" in q or "chrony" in q:
        filters.append({"field": "service_name", "operator": "=", "value": "chronyd"})
        filters.append({"field": "service_status", "operator": "=", "value": "not_running"})

    if "production" in q or "prod" in q or "üretim" in q or "uretim" in q:
        filters.append({"field": "environment", "operator": "=", "value": "production"})

    if "alınamayan" in q or "alinamayan" in q or "unreachable" in q or "erişilemeyen" in q:
        filters.append({"field": "collection_status", "operator": "in", "value": ["failed", "unreachable"]})

    top = re.search(r"(ilk|top)\s*(\d+)", q)
    if top:
        limit = int(top.group(2))
        if "disk" in q:
            sort = {"field": "disk_usage_percent", "direction": "desc"}
            if not any(f["field"] == "disk_usage_percent" for f in filters):
                filters.append({"field": "disk_usage_percent", "operator": "is_not_null", "value": None})

    if not filters and not sort:
        return None

    return {
        "intent": "search_servers",
        "filters": filters,
        "sort": sort,
        "limit": limit,
        "live_check": live,
        "requested_columns": [
            "hostname", "ip_address", "environment", "uptime_days",
            "disk_usage_percent", "cpu_usage_percent", "boot_time",
            "collection_time", "collection_status",
        ],
    }


def parse_question(question: str, *, model: Optional[str] = None) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {"intent": "unsupported", "reason": "Boş soru", "missing_fields": []}

    from app.core.config import settings

    active_model = model or settings.OLLAMA_DEFAULT_MODEL
    prompt = SYSTEM_PROMPT + "\n\nKullanıcı sorusu:\n" + question + "\n\nJSON:"
    raw_text = ""
    try:
        data = llm_gateway.generate_sync(
            model=active_model,
            prompt=prompt,
            options={"temperature": 0.1},
            timeout=60,
        )
        raw_text = (data or {}).get("response") or ""
    except Exception as e:
        logger.warning("NLQ LLM parse failed: %s", e)

    parsed = _extract_json(raw_text)
    if parsed and isinstance(parsed, dict):
        if detect_live_check_phrase(question):
            parsed["live_check"] = True
        return parsed

    heur = _heuristic_parse(question)
    if heur:
        return heur

    return {
        "intent": "unsupported",
        "reason": "Sorgu JSON'a dönüştürülemedi veya mevcut alanlarla eşleşmedi.",
        "missing_fields": [],
    }
