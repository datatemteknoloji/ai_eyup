"""
Sohbet kapsama telemetrisi — "cevaplanamayan soru" kaydı.

Model bir ortam sorusuna hiç araç çağırmadan "buna ilişkin canlı veri mevcut
değil" dediğinde bunu sessizce kaybetmek yerine kaydediyoruz: hangi soru
kalıplarının araç yüzeyinde karşılığı olmadığı ölçülebilir hale gelir ve yeni
tool/veri kaynağı ihtiyacı tahminle değil veriyle belirlenir.

Kayıt `app_settings` içinde tek bir JSON satırında tutulur (ayrı tablo/migration
gerektirmez); imza başına sayaç + son 200 farklı soru saklanır.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SETTINGS_KEY = "chat_coverage_misses"
_MAX_ENTRIES = 200

# Model gerçekten araç çağırmadığı halde "veri yok" diyen cevap kalıpları
_NO_DATA_PATTERNS = (
    r"canl[ıi]\s+veri\s+mevcut\s+de[ğg]il",
    r"canl[ıi]\s+sorguda\s+kay[ıi]t\s+d[öo]nmedi",
    r"(?:veri|bilgi|kay[ıi]t|sonu[çc])(?:si|s[ıi]|ler[ıi])?\s+bulunamad[ıi]",
    r"(?:veri|bilgi|kay[ıi]t)(?:si|s[ıi]|ler[ıi])?\s+(?:mevcut\s+de[ğg]il|yer\s+alm[ıi]yor|bulunmamaktad[ıi]r)",
    r"(?:veri|bilgi|sonu[çc])(?:si|s[ıi]|ler[ıi])?\s+(?:al[ıi]namad[ıi]|d[öo]nd[üu]r[üu]lemedi)",
    r"eri[şs]imim\s+yok",
    r"bu\s+bilgiye\s+ula[şs]am",
    r"senkronize\s+edilmiyor",
    r"toplanm(?:ı|i)yor",
)
_NO_DATA_RE = re.compile("|".join(_NO_DATA_PATTERNS), re.IGNORECASE)


def looks_like_no_data_answer(text: Optional[str]) -> bool:
    """Cevap 'veri yok' kalıbı içeriyor mu (kanıtsız reddetme tespiti)."""
    if not text:
        return False
    return bool(_NO_DATA_RE.search(text))


def question_signature(question: str) -> str:
    """Soruyu normalize edip kısa imza üretir (sayı/isim farkları birleşsin)."""
    norm = re.sub(r"\d+", "#", (question or "").strip().lower())
    norm = re.sub(r"[^\w\s#]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def record_coverage_miss(
    db: Session,
    *,
    question: str,
    platform: Optional[str] = None,
    reason: str = "no_tool_called",
    tools_used: Optional[List[str]] = None,
    intent: Optional[str] = None,
) -> None:
    """Kapsama boşluğunu kaydeder. Hata durumunda sohbeti ASLA bozmaz."""
    try:
        from app.models.app_settings import AppSettings

        sig = question_signature(question)
        now = datetime.now(timezone.utc).isoformat()

        row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
        store: Dict[str, Any] = {}
        if row and row.value:
            import json
            try:
                store = json.loads(row.value) if isinstance(row.value, str) else dict(row.value)
            except Exception:
                store = {}

        entry = store.get(sig) or {
            "question": (question or "")[:300],
            "first_seen": now,
            "hits": 0,
        }
        entry["hits"] = int(entry.get("hits") or 0) + 1
        entry["last_seen"] = now
        entry["platform"] = platform or entry.get("platform")
        entry["reason"] = reason
        entry["intent"] = intent or entry.get("intent")
        entry["tools_used"] = tools_used or []
        store[sig] = entry

        if len(store) > _MAX_ENTRIES:
            # En az isabet eden ve en eski kayıtları düşür
            ordered = sorted(
                store.items(),
                key=lambda kv: (kv[1].get("hits") or 0, kv[1].get("last_seen") or ""),
                reverse=True,
            )
            store = dict(ordered[:_MAX_ENTRIES])

        import json
        payload = json.dumps(store, ensure_ascii=False)
        if row is None:
            db.add(AppSettings(key=SETTINGS_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        logger.info(
            "[CoverageMiss] platform=%s reason=%s hits=%s q=%r",
            platform, reason, entry["hits"], (question or "")[:120],
        )
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug("Kapsama telemetrisi yazılamadı: %s", exc)


def coverage_miss_summary(db: Session, limit: int = 50) -> Dict[str, Any]:
    """En sık kaçırılan sorular — yeni tool/veri kaynağı önceliklendirmesi için."""
    try:
        import json
        from app.models.app_settings import AppSettings

        row = db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()
        if not row or not row.value:
            return {"ok": True, "count": 0, "misses": []}
        store = json.loads(row.value) if isinstance(row.value, str) else dict(row.value)
        items = sorted(
            (
                {"signature": k, **v}
                for k, v in store.items() if isinstance(v, dict)
            ),
            key=lambda e: (e.get("hits") or 0),
            reverse=True,
        )
        return {"ok": True, "count": len(items), "misses": items[: max(1, limit)]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
