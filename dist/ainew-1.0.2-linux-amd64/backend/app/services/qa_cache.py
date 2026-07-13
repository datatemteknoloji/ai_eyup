"""
Soru-Cevap önbelleği (Redis tabanlı).

Amaç: Aynı (veya normalize edildiğinde aynı) soru tekrar sorulduğunda AI
asistanın LLM'i tekrar "düşündürmesini" ya da deterministik katmanın aynı
DB/vCenter sorgusunu tekrar çalıştırmasını engellemek — sistem sorulan
soruları "öğrenip" hatırlar:

  - İlk kez sorulan bir soru normal şekilde hesaplanır ve kısa süreliğine
    (BASE_TTL) önbelleğe alınır.
  - Aynı soru tekrar sorulduğunda önbellekten anında (latency ~0ms) döner.
  - Bir soru belirli bir eşiğin üzerinde tekrar sorulursa (WARM/HOT), önbellek
    süresi otomatik uzatılır — sık sorulan sorular daha uzun süre "hatırlanır".

Altyapı verisi arka planda periyodik olarak senkronize edildiğinde
(virt log / inventory / VM sync) `invalidate_all()` çağrılarak önbellek
temizlenir, böylece bayat veri sunma riski en aza indirilir.

Redis'e erişilemezse önbellek sessizce devre dışı kalır; fonksiyonellik
bozulmaz, sadece hızlanma faydası kaybolur.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "hv_qa_cache:v1:"
_HIT_PREFIX = "hv_qa_hits:v1:"

_BASE_TTL_SECONDS = 5 * 60        # ilk cevap: 5 dk hatırla
_WARM_TTL_SECONDS = 15 * 60       # 3+ kez sorulmuşsa: 15 dk (log sync periyoduyla uyumlu)
_HOT_TTL_SECONDS = 60 * 60        # 10+ kez sorulmuşsa: 1 saat
_WARM_HIT_THRESHOLD = 3
_HOT_HIT_THRESHOLD = 10

_redis_client = None
_redis_unavailable = False


def _get_redis():
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        client.ping()
        _redis_client = client
        return client
    except Exception as exc:
        logger.warning("[QACache] Redis kullanılamıyor, önbellek devre dışı: %s", exc)
        _redis_unavailable = True
        return None


_PUNCT_TABLE = str.maketrans("", "", "?!.,;:'\"()[]{}")


def _normalize(question: str) -> str:
    q = (question or "").strip()
    # Türkçe büyük 'İ' -> 'i' (str.lower() 'İ'yi iki karaktere çevirip eşleşmeyi kırar)
    q = q.replace("İ", "i").replace("I", "ı").lower()
    q = q.translate(_PUNCT_TABLE)
    return " ".join(q.split())


def _cache_key(question: str, model: Optional[str] = None) -> str:
    raw = f"{_normalize(question)}|{model or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_cached_answer(question: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Önbellekte varsa cevabı döndürür (hit sayacını artırıp gerekirse TTL uzatır)."""
    r = _get_redis()
    if not r or not question:
        return None
    key = _cache_key(question, model)
    try:
        raw = r.get(_KEY_PREFIX + key)
        if not raw:
            return None
        data = json.loads(raw)
        hits = r.incr(_HIT_PREFIX + key)
        if hits >= _HOT_HIT_THRESHOLD:
            r.expire(_KEY_PREFIX + key, _HOT_TTL_SECONDS)
            r.expire(_HIT_PREFIX + key, _HOT_TTL_SECONDS)
        elif hits >= _WARM_HIT_THRESHOLD:
            r.expire(_KEY_PREFIX + key, _WARM_TTL_SECONDS)
            r.expire(_HIT_PREFIX + key, _WARM_TTL_SECONDS)
        data["_cache_hits"] = hits
        return data
    except Exception as exc:
        logger.warning("[QACache] okuma hatası: %s", exc)
        return None


def set_cached_answer(question: str, result: Dict[str, Any], model: Optional[str] = None) -> None:
    """Hesaplanan cevabı önbelleğe yazar (varsayılan TTL ile)."""
    r = _get_redis()
    if not r or not question:
        return
    key = _cache_key(question, model)
    try:
        payload = json.dumps(result, default=str, ensure_ascii=False)
        r.set(_KEY_PREFIX + key, payload, ex=_BASE_TTL_SECONDS)
        r.setnx(_HIT_PREFIX + key, 0)
        r.expire(_HIT_PREFIX + key, _BASE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("[QACache] yazma hatası: %s", exc)


def invalidate_all() -> int:
    """Altyapı verisi tazelendiğinde (sync sonrası) tüm önbelleği temizler."""
    r = _get_redis()
    if not r:
        return 0
    try:
        keys = list(r.scan_iter(f"{_KEY_PREFIX}*")) + list(r.scan_iter(f"{_HIT_PREFIX}*"))
        if keys:
            r.delete(*keys)
        return len(keys)
    except Exception as exc:
        logger.warning("[QACache] temizleme hatası: %s", exc)
        return 0
