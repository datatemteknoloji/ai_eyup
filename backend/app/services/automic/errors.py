"""Automic modülü hata kaydı: sessiz yutma yasağı.

`note_error(component, exc)` — her yutulan istisna için:
  * en az WARNING log (bileşen başına 60 sn'de bir; aradaki tekrarlar sayılır),
  * kalıcı hata sayacı (Redis hash `automic:err:count`, yedek: süreç içi sözlük) + son hata zamanı/metni.
Sayaçlar health ekranına (`error_counters()`) gider; kullanıcı cevabını etkileyen sorgu hataları ayrıca
çağıranın `unavailable` listesine eklenir ("bu bilgi alınamadı"; yanlış sıfır / "rapor yok" yazılmaz).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("app.services.automic.errors")

_LOCK = threading.Lock()
_LOCAL_COUNT: Dict[str, int] = {}
_LOCAL_LAST: Dict[str, Dict[str, Any]] = {}
_LAST_LOG_AT: Dict[str, float] = {}
_SUPPRESSED: Dict[str, int] = {}
_LOG_INTERVAL_SEC = 60.0
import os as _os


def _keys() -> tuple:
    """pytest altında ayrı anahtarlar: test koşusu canlı hata sayaçlarını ezmesin/kirletmesin."""
    pfx = "automic:err_test" if _os.environ.get("PYTEST_CURRENT_TEST") else "automic:err"
    return pfx + ":count", pfx + ":last"


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def note_error(component: str, exc: Optional[BaseException] = None, *, detail: str = "") -> None:
    """Yutulan hatayı kaydet (WARNING + sayaç). Kendisi asla istisna fırlatmaz."""
    try:
        comp = (component or "unknown")[:80]
        msg = (f"{type(exc).__name__}: {exc}" if exc is not None else detail or "hata")[:300]
        if detail and exc is not None:
            msg = f"{detail} — {msg}"[:300]
        now = time.monotonic()
        with _LOCK:
            _LOCAL_COUNT[comp] = _LOCAL_COUNT.get(comp, 0) + 1
            _LOCAL_LAST[comp] = {"at": datetime.now(timezone.utc).isoformat(), "msg": msg}
            last = _LAST_LOG_AT.get(comp, 0.0)
            do_log = now - last >= _LOG_INTERVAL_SEC
            if do_log:
                _LAST_LOG_AT[comp] = now
                suppressed = _SUPPRESSED.pop(comp, 0)
            else:
                _SUPPRESSED[comp] = _SUPPRESSED.get(comp, 0) + 1
                suppressed = 0
        if do_log:
            logger.warning("[automic-error] %s: %s%s", comp, msg,
                           f" (+{suppressed} tekrar)" if suppressed else "")
        r = _redis()
        if r is not None:
            try:
                r.hincrby(_keys()[0], comp, 1)
                r.hset(_keys()[1], comp, f"{datetime.now(timezone.utc).isoformat()}|{msg}")
            except Exception:
                pass
    except Exception:  # pragma: no cover - kayıt hatası asla çağıranı bozmaz
        pass


def error_counters() -> Dict[str, Any]:
    """Health için: {total, components:[{component,count,last_at,last_msg}] (çoktan aza)}."""
    counts: Dict[str, int] = {}
    last: Dict[str, Dict[str, Any]] = {}
    r = _redis()
    if r is not None:
        try:
            for k, v in (r.hgetall(_keys()[0]) or {}).items():
                k = k.decode() if isinstance(k, bytes) else k
                counts[k] = int(v)
            for k, v in (r.hgetall(_keys()[1]) or {}).items():
                k = k.decode() if isinstance(k, bytes) else k
                v = v.decode() if isinstance(v, bytes) else v
                at, _, m = str(v).partition("|")
                last[k] = {"at": at, "msg": m}
        except Exception:
            counts, last = {}, {}
    if not counts:
        with _LOCK:
            counts, last = dict(_LOCAL_COUNT), dict(_LOCAL_LAST)
    comps = [
        {"component": k, "count": int(c), "last_at": (last.get(k) or {}).get("at"),
         "last_msg": (last.get(k) or {}).get("msg")}
        for k, c in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return {"total": sum(c["count"] for c in comps), "components": comps[:30]}


def reset_for_tests() -> None:
    with _LOCK:
        _LOCAL_COUNT.clear()
        _LOCAL_LAST.clear()
        _LAST_LOG_AT.clear()
        _SUPPRESSED.clear()
