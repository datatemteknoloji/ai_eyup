"""Runtime ayarları — tüm uvicorn worker'lara Redis pub/sub ile bildirim."""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

CHANNEL = "ainew:settings_reload"
_listener_started = False
_lock = threading.Lock()


def reload_runtime_settings_from_db() -> None:
    """AppSettings → settings nesnesi (startup ile aynı mantık)."""
    try:
        from app.core.database import SessionLocal
        from app.models.app_settings import AppSettings
        from app.core.config import settings as cfg
        import os

        db = SessionLocal()
        try:
            rows = {r.key: r.value for r in db.query(AppSettings).all()}
        finally:
            db.close()

        if rows.get("remote_llm_enabled") is not None:
            cfg.REMOTE_LLM_ENABLED = rows["remote_llm_enabled"].lower() == "true"
            os.environ["REMOTE_LLM_ENABLED"] = "true" if cfg.REMOTE_LLM_ENABLED else "false"
        if rows.get("remote_llm_url"):
            cfg.REMOTE_LLM_URL = rows["remote_llm_url"]
            os.environ["REMOTE_LLM_URL"] = rows["remote_llm_url"]
        if rows.get("remote_llm_model"):
            cfg.REMOTE_LLM_MODEL = rows["remote_llm_model"]
            os.environ["REMOTE_LLM_MODEL"] = rows["remote_llm_model"]
        if rows.get("remote_llm_api_key"):
            from app.core.encryption import decrypt_secret
            plain = decrypt_secret(rows["remote_llm_api_key"])
            cfg.REMOTE_LLM_API_KEY = plain
            os.environ["REMOTE_LLM_API_KEY"] = plain
        if rows.get("remote_llm_virtual_key") is not None:
            from app.core.encryption import decrypt_secret as dec_vk
            raw = rows["remote_llm_virtual_key"] or ""
            plain_vk = dec_vk(raw) if raw else ""
            cfg.REMOTE_LLM_VIRTUAL_KEY = plain_vk
            os.environ["REMOTE_LLM_VIRTUAL_KEY"] = plain_vk
        if rows.get("remote_llm_verify_ssl") is not None:
            cfg.REMOTE_LLM_VERIFY_SSL = rows["remote_llm_verify_ssl"].lower() == "true"
        if rows.get("remote_llm_ca_bundle") is not None:
            cfg.REMOTE_LLM_CA_BUNDLE = rows["remote_llm_ca_bundle"]

        from app.services.runtime_settings import invalidate_cache
        invalidate_cache()
        logger.info("Worker runtime settings yenilendi (Redis broadcast)")
    except Exception as e:
        logger.warning("Worker settings reload başarısız: %s", e)


def broadcast_settings_reload() -> bool:
    """Ayar kaydı sonrası diğer worker'lara bildir."""
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is None:
            return False
        r.publish(CHANNEL, "reload")
        return True
    except Exception as e:
        logger.debug("settings broadcast atlandı: %s", e)
        return False


def _listen_once() -> None:
    """Tek bir pubsub oturumu — hata/timeout'ta çağırana döner."""
    from app.core.redis_client import get_redis, reset_redis_client

    r = get_redis(force_retry=True)
    if r is None:
        raise RuntimeError("Redis erişilemiyor")
    pubsub = r.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe(CHANNEL)
        logger.info("Settings reload listener dinlemede")
        while True:
            # timeout'lu okuma: Redis sessizken de döngü canlı kalır
            msg = pubsub.get_message(timeout=30.0)
            if msg is None:
                continue
            if msg.get("type") != "message":
                continue
            reload_runtime_settings_from_db()
    finally:
        try:
            pubsub.close()
        except Exception:
            pass
        # Bozulmuş bağlantı bir sonraki turda yeniden kurulsun
        try:
            reset_redis_client()
        except Exception:
            pass


def _listener_supervisor() -> None:
    """Redis kesintisinde listener'ı kendi kendine yeniden kurar.

    Eski davranışta `pubsub.listen()` bir TimeoutError'da thread'i sessizce
    bitiriyordu; o worker bir daha ayar değişikliği duymuyordu (uzak LLM
    ayarları dahil).
    """
    import time

    delay = 2.0
    while True:
        try:
            _listen_once()
            delay = 2.0
        except Exception as e:
            logger.warning("Settings listener koptu, %.0f sn sonra yeniden: %s", delay, e)
            time.sleep(delay)
            delay = min(delay * 2, 60.0)


def start_settings_reload_listener() -> None:
    global _listener_started
    with _lock:
        if _listener_started:
            return
        try:
            t = threading.Thread(
                target=_listener_supervisor, daemon=True, name="settings-reload",
            )
            t.start()
            _listener_started = True
            logger.info("Settings reload listener başlatıldı (otomatik yeniden bağlanır)")
        except Exception as e:
            logger.debug("Settings listener başlatılamadı: %s", e)
