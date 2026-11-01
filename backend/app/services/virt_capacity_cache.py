"""Sanallaştırma kapasite yanıtları için kısa ömürlü sunucu önbelleği.

`build_capacity` ve N+1 matrisi büyük envanterde (binlerce VM, onlarca host) saniyeler sürer ve
girdisi (host/VM metrikleri, eşikler) dakikalar içinde değişmez. Aynı istek her sayfa açılışında
yeniden hesaplanmasın diye sonuç Redis'te (yoksa süreç içi sözlükte) TTL ile tutulur.

Geçersiz kılma: eşik/override değişince ve envanter/karar katmanı turu bitince `invalidate()`
nesil sayacını artırır; eski anahtarlar TTL ile kendiliğinden silinir. Redis varsa nesil
sayacı süreçler (uvicorn worker, Celery) arası paylaşılır.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_GEN_KEY = "ainew:virtcap:gen"
# Girdiler (host/VM metrikleri) en sık 15 dk'da, envanter 60 dk'da değişir ve her tur sonunda `invalidate()`
# + `prewarm()` çağrılır; TTL yalnız emniyet ağıdır (kullanıcı sayfayı açtığında soğuk hesap beklemesin).
TTL_SEC = 600
_MEM: Dict[str, Any] = {}
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


def _key(gen: str, kind: str, extra: str) -> str:
    return f"ainew:virtcap:{gen}:{kind}:{extra}"


def _jsonable(payload: Any) -> Any:
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(payload)


def capacity_key(hypervisor_id=None, cluster=None, platform=None) -> str:
    """`/virt-insights/capacity` önbellek anahtarı (API ve `prewarm` aynı biçimi kullanır)."""
    return f"{hypervisor_id}|{cluster or ''}|{platform or ''}"


def get_or_compute(kind: str, extra: str, compute: Callable[[], Any], *, ttl: int = TTL_SEC) -> Any:
    """Önbellekte varsa onu, yoksa `compute()` sonucunu (ve önbelleğe yazarak) döner.

    Hata dönen (`ok=False`) sonuçlar önbelleğe yazılmaz.
    """
    r = _redis()
    gen = _generation(r)
    key = _key(gen, kind, extra)
    if r is not None:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("virt kapasite önbelleği okunamadı: %s", exc)
    else:
        hit = _MEM.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]

    data = compute()
    if isinstance(data, dict) and data.get("ok") is False:
        return data
    try:
        enc = _jsonable(data)
        if _generation(r) != gen:      # hesap sırasında geçersiz kılındı → yazma
            return data
        if r is not None:
            r.setex(key, ttl, json.dumps(enc, ensure_ascii=False))
        else:
            _MEM[key] = (time.monotonic() + ttl, enc)
    except Exception as exc:
        logger.debug("virt kapasite önbelleği yazılamadı: %s", exc)
    return data


def invalidate() -> None:
    """Eşik/envanter değişti → tüm kapasite önbelleğini düşür."""
    global _local_gen
    _local_gen += 1
    _MEM.clear()
    r = _redis()
    if r is None:
        return
    try:
        r.incr(_GEN_KEY)
    except Exception as exc:
        logger.debug("virt kapasite önbelleği invalidate atlandı: %s", exc)


def invalidate_and_prewarm() -> None:
    """Tur sonu: önbelleği düşür ve varsayılan `/capacity` yanıtını hemen yeniden hesapla (hata sessiz)."""
    invalidate()
    try:
        from app.core.database import ThreadSessionLocal
        from app.services.virt_capacity_planner import build_capacity
        db = ThreadSessionLocal()
        try:
            get_or_compute("capacity", capacity_key(), lambda: build_capacity(db))
        finally:
            db.close()
    except Exception as exc:
        logger.debug("virt kapasite önbelleği ön ısıtma atlandı: %s", exc)
