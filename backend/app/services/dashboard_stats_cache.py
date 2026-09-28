"""Dashboard sağlık sayaçları — Redis TTL önbellek.

Event/incident COUNT sorguları büyük tabloda pahalı. Scheduler yaklaşık
60 sn'de bir sayar; sayfa açılışı hazır sonucu okur. Kullanıcı incident
veya event üzerinde işlem yapınca nesil artar, bir sonraki okuma yeniden sayar.
Redis yoksa süreç içi sözlük (worker başına) kullanılır.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_GEN_KEY = "ainew:dashstats:gen"
_TTL_SEC = 180
_MEM: dict = {}
_local_gen = 0


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def _generation(r) -> str:
    if r is not None:
        try:
            return str(r.get(_GEN_KEY) or "0")
        except Exception:
            return str(_local_gen)
    return str(_local_gen)


def _cache_key(gen: str, kind: str, platform: Optional[str], extra: str) -> str:
    return f"ainew:dashstats:{gen}:{kind}:{platform or 'all'}:{extra}"


def cache_get(kind: str, platform: Optional[str], extra: str = "") -> Optional[dict]:
    r = _redis()
    key = _cache_key(_generation(r), kind, platform, extra)
    if r is not None:
        try:
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("dashboard stats cache okunamadı: %s", exc)
        return None
    hit = _MEM.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def cache_put(kind: str, platform: Optional[str], extra: str, payload: dict, gen: Optional[str] = None) -> None:
    r = _redis()
    current = _generation(r)
    if gen is not None and gen != current:
        return
    key = _cache_key(current if gen is None else gen, kind, platform, extra)
    if r is not None:
        try:
            r.setex(key, _TTL_SEC, json.dumps(payload, ensure_ascii=False))
            return
        except Exception as exc:
            logger.debug("dashboard stats cache yazılamadı: %s", exc)
    _MEM[key] = (time.monotonic() + _TTL_SEC, payload)


def invalidate_dashboard_stats() -> None:
    """Kullanıcı işlemi sonrası sayaçları düşür. Eski anahtarlar TTL ile silinir."""
    global _local_gen
    _local_gen += 1
    _MEM.clear()
    r = _redis()
    if r is None:
        return
    try:
        r.incr(_GEN_KEY)
    except Exception as exc:
        logger.debug("dashboard stats cache invalidate atlandı: %s", exc)


def get_or_compute(
    kind: str,
    platform: Optional[str],
    extra: str,
    compute: Callable[[], dict],
) -> dict:
    hit = cache_get(kind, platform, extra)
    if hit is not None:
        return hit
    r = _redis()
    gen = _generation(r)
    data = compute()
    cache_put(kind, platform, extra, data, gen=gen)
    return data


def refresh_dashboard_stat_caches() -> None:
    """Ana, Linux, Windows ve sanallaştırma sayaçlarını önceden say."""
    from app.core.database import SessionLocal
    from app.api.events import compute_event_stats
    from app.api.incidents import compute_incident_stats

    db = SessionLocal()
    try:
        r = _redis()
        gen = _generation(r)
        for platform in (None, "linux", "windows", "virt"):
            try:
                events = compute_event_stats(db, platform, False)
                cache_put("events", platform, "0", events, gen=gen)
                incidents = compute_incident_stats(db, platform)
                cache_put("incidents", platform, "", incidents, gen=gen)
            except Exception:
                db.rollback()
                logger.exception("dashboard stats yenilenemedi platform=%s", platform or "all")
            if _generation(r) != gen:
                return
    finally:
        db.close()
