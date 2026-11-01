"""Veritabanı kilit kuyruğu bekçisi (son savunma hattı).

Sorun: uygulama bağlantılarından biri uzun süre «idle in transaction» kalırsa (ör. dış sistemi
beklerken açık okuma işlemi), TimescaleDB retention işi `servers` üzerinde AccessExclusive kilidi ister
ve o işlemin ARKASINDA bekler; sonradan gelen TÜM okumalar da retention'ın arkasına kuyruğa girer →
uygulama «kilitlenir» (5 dk'ya kadar; retention iş zaman aşımına uğrayana dek).

Kök neden kodda giderilir (kısa işlemler: bkz. `background_tasks._run_vm_sync_batch`,
`snapshot_service.search_and_sync_vm_details`, `core.database.release_txn`). Bu bekçi, ileride
başka bir kod yolu aynı hatayı yaparsa kesintinin dakikalarca sürmesini engeller:

  Yalnızca şu koşulların HEPSİ sağlanırsa engelleyen bağlantıyı sonlandırır (`pg_terminate_backend`):
    - engelleyen bağlantı bizim (`ainew-api` / `ainew-thread`) ve «idle in transaction» (sorgu ÇALIŞTIRMIYOR),
    - işlem yaşı >= DB_LOCK_GUARD_XACT_SEC (varsayılan 60 sn),
    - onu bekleyen bir kilit talebi >= DB_LOCK_GUARD_WAIT_SEC (varsayılan 20 sn) beklemiş.
  Okuma işlemi geri alınır; veri değişmez. Çalışan sorgu/yazma asla öldürülmez.

Kapatma: DB_LOCK_GUARD=0. Yük: 10 sn'de bir tek hafif katalog sorgusu (ayrı NullPool bağlantısı).
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_started = False
_stats = {"checks": 0, "terminated": 0, "errors": 0, "last_terminated": ""}

_SQL = """
SELECT b.pid,
       b.application_name,
       b.state,
       EXTRACT(EPOCH FROM (now() - b.xact_start))::int AS xact_age,
       COUNT(DISTINCT w.pid) AS waiters,
       MAX(EXTRACT(EPOCH FROM (now() - w.query_start)))::int AS max_wait,
       left(b.query, 160) AS q
FROM pg_stat_activity w
CROSS JOIN LATERAL unnest(pg_blocking_pids(w.pid)) AS bp(pid)
JOIN pg_stat_activity b ON b.pid = bp.pid
WHERE w.datname = current_database()
  AND w.wait_event_type = 'Lock'
  AND b.pid <> pg_backend_pid()
  AND b.application_name = ANY(:apps)
  AND b.state IN ('idle in transaction', 'idle in transaction (aborted)')
  AND b.wait_event_type IS DISTINCT FROM 'Lock'
  AND b.xact_start < now() - make_interval(secs => :xact)
GROUP BY b.pid, b.application_name, b.state, b.xact_start, b.query
HAVING MAX(EXTRACT(EPOCH FROM (now() - w.query_start))) >= :wait
"""


def enabled() -> bool:
    return (os.getenv("DB_LOCK_GUARD", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def stats() -> dict:
    return dict(_stats)


def _params() -> dict:
    return {
        "apps": ["ainew-api", "ainew-thread"],
        "xact": float(os.getenv("DB_LOCK_GUARD_XACT_SEC", "60")),
        "wait": float(os.getenv("DB_LOCK_GUARD_WAIT_SEC", "20")),
    }


def check_once(conn) -> list:
    """Tek tarama. Sonlandırılan bağlantıların satırlarını döndürür (test edilebilir)."""
    from sqlalchemy import text

    _stats["checks"] += 1
    rows = conn.execute(text(_SQL), _params()).fetchall()
    out = []
    for r in rows:
        pid = int(r[0])
        ok = conn.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid}).scalar()
        _stats["terminated"] += 1 if ok else 0
        _stats["last_terminated"] = f"pid={pid} app={r[1]} xact_age={r[3]}s"
        logger.warning(
            "DB kilit bekçisi: pid=%s app=%s uzun süredir 'idle in transaction' (%ss) ve %s kilit talebini "
            "engelliyor (en uzun bekleme %ss) → bağlantı sonlandırıldı=%s. Son sorgu: %s",
            pid, r[1], r[3], r[4], r[5], bool(ok), (r[6] or "").replace("\n", " "),
        )
        out.append(r)
    return out


def _loop(interval: float) -> None:
    from app.core.database import _thread_engine

    while True:
        time.sleep(interval)
        try:
            with _thread_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                check_once(conn)
        except Exception as e:  # DB geçici erişilemez olabilir; bekçi asla uygulamayı düşürmez
            _stats["errors"] += 1
            logger.debug("DB kilit bekçisi taraması başarısız: %s", e)


def start() -> None:
    global _started
    if _started or not enabled():
        return
    _started = True
    interval = max(5.0, float(os.getenv("DB_LOCK_GUARD_INTERVAL_SEC", "10")))
    t = threading.Thread(target=_loop, args=(interval,), name="db-lock-guard", daemon=True)
    t.start()
    logger.info("DB kilit bekçisi başlatıldı (tarama %ss, işlem>=%ss, bekleme>=%ss)",
                interval, _params()["xact"], _params()["wait"])
