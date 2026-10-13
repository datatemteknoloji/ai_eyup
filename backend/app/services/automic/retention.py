"""Günlük özet + süre tabanlı saklama + kota (watermark) yönetimi.

Kurallar (automic-retention-policy.yaml):
  - Detay silinmeden önce o günün özeti üretilmiş olmalı.
  - Özet işi son 3 günü yeniden hesaplar (geç gelen kayıtlar).
  - Kota: warn → uyarı; prune → quota_eviction_order ile erken temizlik (floor'lara kadar);
    critical → rapor alıntısı alımı durur, meta veri alımı sürer.
  - daily_aggregates / failed_index / audit kota temizliğinde silinmez.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.automic import AutomicCollectorState, AutomicSystem

from .database import database_size_bytes, get_automic_thread_session, timescale_enabled
from .defaults import effective_settings

logger = logging.getLogger(__name__)

_AGG_SQL = text("""
INSERT INTO automic_daily_aggregates AS a (
    system_id, client, day, object_name, object_type, folder,
    run_count, ok_count, failed_count, cancelled_count,
    duration_min, duration_avg, duration_p95, duration_max,
    first_start, last_end, top_error_signature, agents)
WITH g AS (
    SELECT e.system_id, e.client, (e.end_time AT TIME ZONE 'UTC')::date AS day, e.object_name,
           max(e.object_type) AS object_type, max(e.folder) AS folder,
           count(*) AS run_count,
           count(*) FILTER (WHERE e.status_class = 'ok') AS ok_count,
           count(*) FILTER (WHERE e.status_class = 'failed') AS failed_count,
           count(*) FILTER (WHERE e.status_class = 'cancelled') AS cancelled_count,
           min(e.duration_sec) AS dmin, avg(e.duration_sec) AS davg,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY e.duration_sec) AS dp95,
           max(e.duration_sec) AS dmax,
           min(e.start_time) AS first_start, max(e.end_time) AS last_end,
           to_jsonb(array_remove(array_agg(DISTINCT e.agent), NULL)) AS agents
    FROM automic_executions e
    WHERE e.system_id = :sid AND e.end_time >= :d_from AND e.end_time < :d_to
    GROUP BY 1, 2, 3, 4
)
SELECT g.system_id, g.client, g.day, g.object_name, g.object_type, g.folder,
       g.run_count, g.ok_count, g.failed_count, g.cancelled_count,
       g.dmin, g.davg, g.dp95, g.dmax, g.first_start, g.last_end,
       (SELECT f.error_signature FROM automic_failed_index f
         WHERE f.system_id = g.system_id AND f.client = g.client AND f.day = g.day
           AND f.object_name = g.object_name AND f.error_signature IS NOT NULL
         GROUP BY f.error_signature ORDER BY count(*) DESC LIMIT 1),
       g.agents
FROM g
ON CONFLICT (system_id, client, day, object_name) DO UPDATE SET
    object_type = EXCLUDED.object_type, folder = EXCLUDED.folder,
    run_count = EXCLUDED.run_count, ok_count = EXCLUDED.ok_count,
    failed_count = EXCLUDED.failed_count, cancelled_count = EXCLUDED.cancelled_count,
    duration_min = EXCLUDED.duration_min, duration_avg = EXCLUDED.duration_avg,
    duration_p95 = EXCLUDED.duration_p95, duration_max = EXCLUDED.duration_max,
    first_start = EXCLUDED.first_start, last_end = EXCLUDED.last_end,
    top_error_signature = EXCLUDED.top_error_signature, agents = EXCLUDED.agents
""")


def _utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def aggregate_days(db: Session, system_id: int, d_from: date, d_to_excl: date) -> int:
    n = 0
    d = d_from
    while d < d_to_excl:
        db.execute(_AGG_SQL, {"sid": system_id, "d_from": _utc_midnight(d),
                              "d_to": _utc_midnight(d + timedelta(days=1))})
        db.commit()
        n += 1
        d += timedelta(days=1)
    return n


def run_aggregates(db: Session, system_id: int, recompute_days: int = 3) -> int:
    today = datetime.now(timezone.utc).date()
    return aggregate_days(db, system_id, today - timedelta(days=recompute_days - 1), today + timedelta(days=1))


def _ensure_aggregated_before(db: Session, system_id: int, cutoff: datetime) -> None:
    """cutoff'tan eski olup özeti olmayan günleri silmeden önce özetler."""
    rows = db.execute(text("""
        SELECT DISTINCT (end_time AT TIME ZONE 'UTC')::date AS d FROM automic_executions
        WHERE system_id = :sid AND end_time < :cut
        EXCEPT
        SELECT DISTINCT day FROM automic_daily_aggregates WHERE system_id = :sid AND day < :cutd
    """), {"sid": system_id, "cut": cutoff, "cutd": cutoff.date()}).all()
    for (d,) in rows:
        aggregate_days(db, system_id, d, d + timedelta(days=1))


def _delete_older(db: Session, table: str, col: str, system_id: int, cutoff) -> int:
    res = db.execute(text(f"DELETE FROM {table} WHERE system_id = :sid AND {col} < :cut"),
                     {"sid": system_id, "cut": cutoff})
    db.commit()
    return int(res.rowcount or 0)


def _drop_chunks(db: Session, table: str, older_than) -> None:
    try:
        db.execute(text(f"SELECT drop_chunks('{table}', older_than => :c)"), {"c": older_than})
        db.commit()
    except Exception as exc:
        db.rollback()
        note_error("retention._drop_chunks", exc)


_TIME_TABLES = (
    # (tablo, kolon, ayar anahtarı, birim) — executions: activation_time partition
    ("automic_executions", "activation_time", "executions_days", "days"),
    ("automic_report_excerpts", "end_time", "failed_report_excerpts_days", "days"),
    ("automic_failed_index", "day", "failed_index_days", "days"),
    ("automic_daily_aggregates", "day", "daily_aggregates_days", "days"),
)


def _cutoff(table_col: str, days: int):
    now = datetime.now(timezone.utc)
    c = now - timedelta(days=days)
    return c.date() if table_col == "day" else c


def run_retention(db: Session) -> Dict[str, Any]:
    systems = db.query(AutomicSystem).all()
    if not systems:
        return {"deleted": {}}
    ts = timescale_enabled(db)
    deleted: Dict[str, int] = {}
    per_sys = {s.id: effective_settings(s.settings)["retention"] for s in systems}
    for table, col, key, _u in _TIME_TABLES:
        max_days = max(int(r.get(key) or 90) for r in per_sys.values())
        if table == "automic_executions":
            for s in systems:
                # günlük özet hâlâ end_time ile; saklama budaması activation_time
                _ensure_aggregated_before(db, s.id, _cutoff("end_time", int(per_sys[s.id].get(key) or 90)))
        if ts:
            _drop_chunks(db, table, _cutoff(col, max_days))
        for s in systems:
            days = int(per_sys[s.id].get(key) or 90)
            deleted[table] = deleted.get(table, 0) + _delete_older(db, table, col, s.id, _cutoff(col, days))
    for s in systems:
        hours = int(per_sys[s.id].get("report_cache_hours") or 24)
        res = db.execute(text("DELETE FROM automic_report_cache WHERE system_id = :sid AND fetched_at < :c"),
                         {"sid": s.id, "c": datetime.now(timezone.utc) - timedelta(hours=hours)})
        deleted["automic_report_cache"] = deleted.get("automic_report_cache", 0) + int(res.rowcount or 0)
        # silinmiş nesne başlıkları + script sürümleri
        del_days = int(per_sys[s.id].get("object_headers_deleted_days") or 90)
        res = db.execute(text(
            "DELETE FROM automic_object_headers WHERE system_id = :sid AND deleted_at IS NOT NULL "
            "AND deleted_at < :c"),
            {"sid": s.id, "c": datetime.now(timezone.utc) - timedelta(days=del_days)})
        deleted["automic_object_headers"] = deleted.get("automic_object_headers", 0) + int(res.rowcount or 0)
        try:
            from .objects import prune_script_versions
            deleted["automic_object_script_versions"] = deleted.get("automic_object_script_versions", 0) + \
                prune_script_versions(db, s)
        except Exception as exc:
            note_error("retention.run_retention", exc)
    db.execute(text("DELETE FROM automic_collector_runs WHERE started_at < :c"),
               {"c": datetime.now(timezone.utc) - timedelta(days=7)})
    db.commit()
    return {"deleted": deleted}


# ── kota ──────────────────────────────────────────────────────────────────

def layer_sizes(db: Session) -> Dict[str, int]:
    """Tablo katmanı boyutları (byte). Kota widget'ı için."""
    tables = (
        "automic_executions", "automic_report_excerpts", "automic_report_cache",
        "automic_failed_index", "automic_daily_aggregates", "automic_active",
        "automic_object_headers", "automic_object_script_versions", "automic_collector_runs",
    )
    out: Dict[str, int] = {}
    for t in tables:
        try:
            out[t] = int(db.execute(text(f"SELECT pg_total_relation_size('{t}')")).scalar() or 0)
        except Exception:
            db.rollback()
            out[t] = 0
    return out


def quota_status(db: Session) -> Dict[str, Any]:
    systems = db.query(AutomicSystem).all()
    st = effective_settings(systems[0].settings if systems else {})["storage"]
    quota_gb = max(float(effective_settings(s.settings)["storage"]["quota_gb"]) for s in systems) if systems \
        else float(st["quota_gb"])
    used = database_size_bytes(db)
    pct = round(used / (quota_gb * 1024 ** 3) * 100, 2) if quota_gb else 0.0
    level = "ok"
    if pct >= float(st["critical_pct"]):
        level = "critical"
    elif pct >= float(st["prune_pct"]):
        level = "prune"
    elif pct >= float(st["warn_pct"]):
        level = "warn"
    return {"used_bytes": used, "quota_gb": quota_gb, "usage_pct": pct, "level": level,
            "thresholds": {k: st[k] for k in ("warn_pct", "prune_pct", "critical_pct")},
            "layers": layer_sizes(db)}


_EVICTION = (
    # (tablo, kolon, floor gün)
    ("automic_report_cache", "fetched_at", 0),
    ("automic_report_excerpts", "end_time", 30),
    ("automic_executions", "activation_time", 30),
)


def enforce_quota(db: Session) -> Dict[str, Any]:
    q = quota_status(db)
    actions: List[str] = []
    if q["level"] in ("prune", "critical"):
        ts = timescale_enabled(db)
        for table, col, floor in _EVICTION:
            for _ in range(60):
                q = quota_status(db)
                if q["level"] not in ("prune", "critical"):
                    break
                oldest = db.execute(text(f"SELECT min({col}) FROM {table}")).scalar()
                if oldest is None:
                    break
                floor_at = datetime.now(timezone.utc) - timedelta(days=floor)
                cut = min(oldest + timedelta(days=1), floor_at)
                if cut <= oldest:
                    break
                if table == "automic_executions":
                    for s in db.query(AutomicSystem).all():
                        _ensure_aggregated_before(db, s.id, cut)
                if ts and table != "automic_report_cache":
                    _drop_chunks(db, table, cut)
                db.execute(text(f"DELETE FROM {table} WHERE {col} < :c"), {"c": cut})
                db.commit()
                actions.append(f"{table} < {cut:%Y-%m-%d}")
        q = quota_status(db)
    paused = "quota_critical" if q["level"] == "critical" else None
    for st in db.query(AutomicCollectorState).all():
        if st.ingest_paused_reason != paused:
            st.ingest_paused_reason = paused
    db.commit()
    q["actions"] = actions
    return q


def run_maintenance(kind: str = "all") -> Dict[str, Any]:
    """Arka plan girişi: kind = aggregate | retention | quota | all."""
    db = get_automic_thread_session()
    if db is None:
        return {"ok": False}
    out: Dict[str, Any] = {"ok": True}
    try:
        if kind in ("aggregate", "all"):
            out["aggregated"] = {s.id: run_aggregates(db, s.id) for s in db.query(AutomicSystem).all()}
        if kind in ("retention", "all"):
            out["retention"] = run_retention(db)
        if kind in ("quota", "all"):
            out["quota"] = enforce_quota(db)
    except Exception as exc:
        db.rollback()
        logger.exception("Automic bakım (%s) hata", kind)
        out = {"ok": False, "error": str(exc)}
    finally:
        db.close()
    return out


def storage_projection(settings: Dict[str, Any], clients: Optional[int] = None) -> Dict[str, Any]:
    """Sihirbaz için tahmini disk kullanımı (YAML'daki boyut örneği formülü)."""
    p = settings.get("projection") or {}
    r = settings.get("retention") or {}
    s = settings.get("storage") or {}
    daily = float(p.get("daily_exec") or 0)
    fail = float(p.get("failure_rate") or 0.01)
    objs = float(p.get("active_objects_daily") or 0) or max(daily / 20, 1)
    comp = max(1.0, float(p.get("compression_ratio") or 8))
    exc_kb = float(p.get("avg_excerpt_kb") or 15)
    idx_f = float(p.get("index_overhead_factor") or 1.4)
    ex_days = int(r.get("executions_days") or 90)
    comp_after = min(int(r.get("compress_after_days") or 7), ex_days)
    kb = 1000.0
    hot = daily * comp_after * 1 * kb
    cold = daily * (ex_days - comp_after) * 1 * kb / comp
    excerpts = daily * fail * int(r.get("failed_report_excerpts_days") or 90) * exc_kb * kb
    fidx = daily * fail * int(r.get("failed_index_days") or 365) * 0.5 * kb
    agg = objs * int(r.get("daily_aggregates_days") or 730) * 0.3 * kb / comp
    need = idx_f * (hot + cold + excerpts + fidx + agg) + 2e9
    quota = float(s.get("quota_gb") or 0)
    prune = float(s.get("prune_pct") or 85)
    gb = lambda b: round(b / 1e9, 2)  # noqa: E731
    return {
        "executions_hot_gb": gb(hot), "executions_compressed_gb": gb(cold), "report_excerpts_gb": gb(excerpts),
        "failed_index_gb": gb(fidx), "daily_aggregates_gb": gb(agg),
        "estimated_db_gb": gb(need), "quota_gb": quota,
        "min_disk_gb": round(max(quota, gb(need)) * float(s.get("disk_overhead_factor") or 1.5), 1),
        "fits": gb(need) <= quota * prune / 100,
        "prune_threshold_gb": round(quota * prune / 100, 1),
    }
