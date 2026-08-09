"""
Windows live metrics — WinRM fan-out arka planda; API yalnızca cache okur.
Wave 6: Redis paylaşımlı cache (multi-worker); bellek L1 fallback.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_LOCK = threading.Lock()
_REFRESHING = False
_TTL_SEC = 45.0
_REDIS_KEY = "ainew:win_live_metrics"
_REDIS_REFRESH_KEY = "ainew:win_live_metrics:refreshing"
GLOBAL_WINRM_KEY = "global_winrm_credential"


def _redis_get_payload() -> Optional[Dict[str, Any]]:
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is None:
            return None
        raw = r.get(_REDIS_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict) or "payload" not in data:
            return None
        return data
    except Exception:
        return None


def _redis_set_payload(payload: Dict[str, Any]) -> None:
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is None:
            return
        r.setex(
            _REDIS_KEY,
            int(_TTL_SEC * 4),
            json.dumps({"payload": payload, "ts": time.time()}, ensure_ascii=False, default=str),
        )
    except Exception:
        pass


def _redis_refreshing(val: Optional[bool] = None) -> bool:
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if r is None:
            return False
        if val is None:
            return bool(r.exists(_REDIS_REFRESH_KEY))
        if val:
            r.setex(_REDIS_REFRESH_KEY, 120, "1")
        else:
            r.delete(_REDIS_REFRESH_KEY)
        return bool(val)
    except Exception:
        return False


def cache_age_sec() -> Optional[float]:
    remote = _redis_get_payload()
    if remote:
        return max(0.0, time.time() - float(remote.get("ts") or 0))
    with _LOCK:
        if _CACHE["data"] is None:
            return None
        return max(0.0, time.monotonic() - float(_CACHE["ts"] or 0))


def get_cached_payload() -> Optional[Dict[str, Any]]:
    remote = _redis_get_payload()
    if remote and isinstance(remote.get("payload"), dict):
        out = dict(remote["payload"])
        age = max(0.0, time.time() - float(remote.get("ts") or 0))
        out["age_sec"] = int(age)
        out["refreshing"] = _redis_refreshing() or bool(_REFRESHING)
        out["stale"] = age > _TTL_SEC
        return out
    with _LOCK:
        data = _CACHE["data"]
        if data is None:
            return None
        age = time.monotonic() - float(_CACHE["ts"] or 0)
        out = dict(data)
        out["age_sec"] = int(age)
        out["refreshing"] = bool(_REFRESHING) or _redis_refreshing()
        out["stale"] = age > _TTL_SEC
        return out


def _set_refreshing(val: bool) -> None:
    global _REFRESHING
    with _LOCK:
        _REFRESHING = val
    _redis_refreshing(val)


def _get_global_winrm(db) -> Optional[Dict[str, Any]]:
    from app.core.encryption import decrypt_secret
    from app.models.app_settings import AppSettings

    row = db.query(AppSettings).filter(AppSettings.key == GLOBAL_WINRM_KEY).first()
    if not row or not row.value:
        return None
    try:
        data = json.loads(row.value)
        if data.get("password"):
            data["password"] = decrypt_secret(data["password"])
        return data
    except Exception:
        return None


def collect_and_store(db) -> Dict[str, Any]:
    """WinRM fan-out — yalnızca arka plan / explicit refresh."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.models.server import Server
    from app.services.bulk_concurrency import bulk_ssh_workers
    from app.services.platform_scope import is_windows_server
    from app.services.windows.winrm_client import WinRMClient
    from app.services.windows.windows_info_collector import WindowsInfoCollector

    servers = [s for s in db.query(Server).all() if is_windows_server(s)]
    ready = [s for s in servers if s.ai_ready]
    not_ready = [s for s in servers if not s.ai_ready]
    gcred = _get_global_winrm(db)

    def _client_for(server: Server):
        client = WinRMClient.from_server(server)
        if client:
            return client
        if not gcred:
            return None
        host = server.ip_address or server.hostname
        if not host:
            return None
        return WinRMClient(
            host=host,
            username=gcred["username"],
            password=gcred["password"],
            port=gcred.get("port", 5985),
            use_https=gcred.get("use_https", False),
        )

    def _fetch_one(server: Server):
        client = _client_for(server)
        if not client:
            return server.id, {"error": "WinRM kimlik bilgisi yok"}
        collector = WindowsInfoCollector(client)
        return server.id, collector.get_performance()

    perf_by_id: Dict[int, Dict[str, Any]] = {}
    if ready:
        with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="winrm-live-metrics") as pool:
            futures = {pool.submit(_fetch_one, s): s for s in ready}
            for fut in as_completed(futures):
                try:
                    sid, perf = fut.result()
                    perf_by_id[sid] = perf
                except Exception as exc:  # noqa: BLE001
                    srv = futures[fut]
                    perf_by_id[srv.id] = {"error": str(exc)}

    results = []
    for s in ready:
        perf = perf_by_id.get(s.id, {})
        results.append({
            "id": s.id,
            "name": s.name or s.hostname or f"#{s.id}",
            "ip_address": s.ip_address,
            "status": s.status,
            "ai_ready": True,
            "cpu_pct": perf.get("cpu_pct"),
            "mem_used_pct": perf.get("mem_used_pct"),
            "mem_total_gb": perf.get("mem_total_gb"),
            "mem_free_gb": perf.get("mem_free_gb"),
            "disks": perf.get("disks") or [],
            "uptime_days": perf.get("uptime_days"),
            "last_boot": perf.get("last_boot"),
            "error": perf.get("error"),
        })
    for s in not_ready:
        results.append({
            "id": s.id,
            "name": s.name or s.hostname or f"#{s.id}",
            "ip_address": s.ip_address,
            "status": s.status,
            "ai_ready": False,
            "cpu_pct": None, "mem_used_pct": None, "mem_total_gb": None, "mem_free_gb": None,
            "disks": [], "uptime_days": None, "last_boot": None,
            "error": "AI Ready değil — WinRM bağlantısı kurulamadı",
        })

    results.sort(key=lambda r: (0 if r["ai_ready"] else 1, r["name"] or ""))
    successful = [r for r in results if r["ai_ready"] and r["cpu_pct"] is not None]
    payload = {
        "servers": results,
        "total": len(results),
        "online": len(successful),
        "avg_cpu_pct": round(sum(r["cpu_pct"] for r in successful) / len(successful), 1) if successful else None,
        "avg_mem_pct": round(sum(r["mem_used_pct"] for r in successful) / len(successful), 1) if successful else None,
    }
    with _LOCK:
        _CACHE["data"] = payload
        _CACHE["ts"] = time.monotonic()
    _redis_set_payload(payload)
    return payload


def refresh_async() -> bool:
    """Arka plan thread'de toplama. Zaten çalışıyorsa False."""
    global _REFRESHING
    with _LOCK:
        if _REFRESHING:
            return False
        _REFRESHING = True

    def _run():
        from app.core.database import ThreadSessionLocal
        db = ThreadSessionLocal()
        try:
            collect_and_store(db)
            logger.info("Windows live-metrics cache yenilendi")
        except Exception:
            logger.exception("Windows live-metrics refresh failed")
        finally:
            db.close()
            _set_refreshing(False)

    threading.Thread(target=_run, daemon=True, name="win-live-metrics-refresh").start()
    return True


def refresh_if_stale(max_age_sec: float = _TTL_SEC) -> None:
    age = cache_age_sec()
    if age is None or age >= max_age_sec:
        refresh_async()
