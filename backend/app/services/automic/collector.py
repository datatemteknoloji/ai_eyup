"""Automic collector — biten çalışmalar (watermark + overlap), aktif anlık görüntü,
hatalı rapor alıntıları, hatalı indeks, backfill.

Tek giriş: run_collect(system_id). Zamanlayıcı: tick() (background_tasks her dakika).
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.models.automic import (
    AutomicActiveExecution,
    AutomicCollectorRun,
    AutomicCollectorState,
    AutomicExecution,
    AutomicFailedIndex,
    AutomicReportAttempt,
    AutomicReportExcerpt,
    AutomicSystem,
)

from . import guard, runid_map
from .classify import classify_status
from .database import get_automic_thread_session
from .defaults import effective_settings
from .excerpt import build_excerpt, error_signature
from .masking import mask_text
from .schedule import collection_allowed, in_heavy_window
from .source.base import AutomicSource, SourceError
from .source.factory import build_source
from .errors import note_error
from .maintenance import cleanup_legacy_fake_runids
from .steps import FATAL_CODES, StepClock

logger = logging.getLogger(__name__)

# PK dışı güncellenen kolonlar (activation_time PK — değişmez)
_EXEC_COLS = (
    "end_time", "parent_run_id", "top_run_id", "restart_ref_run_id", "object_name", "object_type",
    "folder", "status_code", "status_class", "start_time", "duration_sec",
    "agent", "agent_group", "agent_assigned", "platform", "queue", "user", "user_idnr", "user_name_at_run",
    "return_code", "run_time_sec", "ert_sec",
)
_MAX_FAILED_REPORTS_PER_RUN = 600
_UPSERT_BATCH = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trunc(v: Optional[str], n: int) -> Optional[str]:
    return v[:n] if isinstance(v, str) else v


def _int_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _exec_row(system_id: int, rec: Dict[str, Any], status_classes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if rec.get("run_id") is None or rec.get("end_time") is None or rec.get("client") is None:
        return None
    st, en = rec.get("start_time"), rec.get("end_time")
    act = rec.get("activation_time") or st or en
    if act is None:
        return None
    dur = (en - st).total_seconds() if st and en and en >= st else None
    return {
        "system_id": system_id,
        "client": int(rec["client"]),
        "run_id": int(rec["run_id"]),
        "activation_time": act,
        "end_time": en,
        "parent_run_id": rec.get("parent_run_id"),
        "top_run_id": rec.get("top_run_id"),
        "restart_ref_run_id": rec.get("restart_ref_run_id"),
        "object_name": _trunc(rec.get("object_name") or "?", 200),
        "object_type": _trunc(rec.get("object_type"), 16),
        "folder": _trunc(rec.get("folder"), 400),
        "status_code": rec.get("status_code"),
        "status_class": classify_status(rec.get("status_code"), status_classes),
        "start_time": st,
        "duration_sec": dur,
        "agent": _trunc(rec.get("agent"), 200),
        "agent_group": _trunc(rec.get("agent_group"), 200),
        "agent_assigned": _trunc(rec.get("agent_assigned") or rec.get("agent_group") or rec.get("agent"), 200),
        "platform": _trunc(rec.get("platform"), 32),
        "queue": _trunc(rec.get("queue"), 200),
        "user": _trunc(rec.get("user") or rec.get("user_name_at_run"), 200),
        "user_idnr": _int_or_none(rec.get("user_idnr") if rec.get("user_idnr") is not None else rec.get("user_id")),
        "user_name_at_run": _trunc(rec.get("user_name_at_run") or rec.get("user"), 200),
        "return_code": rec.get("return_code"),
        "run_time_sec": rec.get("run_time_sec"),
        "ert_sec": rec.get("ert_sec"),
    }


def _upsert_executions(db: Session, rows: List[Dict[str, Any]]) -> None:
    """Upsert anahtarı (system_id, client, run_id, activation_time) — aktivasyon sabit, sil+ekle yok."""
    if not rows:
        return
    for i in range(0, len(rows), _UPSERT_BATCH):
        chunk = rows[i:i + _UPSERT_BATCH]
        stmt = pg_insert(AutomicExecution.__table__).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["system_id", "client", "run_id", "activation_time"],
            set_={c: stmt.excluded[c] for c in _EXEC_COLS},
        )
        db.execute(stmt)


def _upsert_failed_index(db: Session, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    vals = [{
        "system_id": r["system_id"], "client": r["client"], "run_id": r["run_id"],
        "day": r["end_time"].date(), "object_name": r["object_name"], "object_type": r["object_type"],
        "agent": r["agent"], "status_code": r["status_code"], "return_code": r["return_code"],
    } for r in rows]
    for i in range(0, len(vals), _UPSERT_BATCH):
        stmt = pg_insert(AutomicFailedIndex.__table__).values(vals[i:i + _UPSERT_BATCH])
        db.execute(stmt.on_conflict_do_nothing())


def _get_state(db: Session, system_id: int) -> AutomicCollectorState:
    st = db.get(AutomicCollectorState, system_id)
    if st is None:
        st = AutomicCollectorState(system_id=system_id)
        db.add(st)
        db.flush()
    return st


def _collect_lock(system_id: int, ttl: int) -> Tuple[bool, Optional[str]]:
    r = get_redis()
    if r is None:
        return True, None
    key = f"automic:{system_id}:collect_lock"
    try:
        token = str(time.time())
        if r.set(key, token, nx=True, ex=ttl):
            return True, token
        return False, None
    except Exception as _exc:
        note_error("collector.silent_157", _exc)
        return True, None


def _release_lock(system_id: int, token: Optional[str]) -> None:
    if not token:
        return
    r = get_redis()
    if r is None:
        return
    key = f"automic:{system_id}:collect_lock"
    try:
        if r.get(key) == token:
            r.delete(key)
    except Exception as _e:
        note_error("collector._release_lock", _e)


# ── biten çalışmalar (RunID / PK aralığı) ──────────────────────────────────

def _source_latest_run_id(src: AutomicSource, clients: List[int],
                          warnings: List[str]) -> Optional[int]:
    highs: List[int] = []
    for c in clients:
        try:
            fn = getattr(src, "latest_run_id", None)
            h = fn(c) if callable(fn) else None
            if h is not None:
                highs.append(int(h))
        except SourceError as exc:
            warnings.append(f"latest_run_id client={c}: {exc}")
    return max(highs) if highs else None


def _bootstrap_runid_bounds(src: AutomicSource, clients: List[int], chunk: int,
                            warnings: List[str],
                            t_from: Optional[datetime] = None,
                            t_to: Optional[datetime] = None) -> Optional[Tuple[int, int]]:
    """Eşleme yoksa: kaynak zaman→RunID (varsa) veya latest_run_id ile dar uç dilim."""
    suggest = getattr(src, "runid_bounds_for_time", None)
    if callable(suggest) and t_from is not None and t_to is not None:
        try:
            sb = suggest(t_from, t_to)
            if sb and sb[1] > sb[0]:
                return int(sb[0]), int(sb[1])
        except Exception as exc:
            warnings.append(f"runid_bounds_for_time: {exc}")
    hi = _source_latest_run_id(src, clients, warnings)
    if hi is None:
        return None
    return max(1, int(hi) + 1 - max(1, chunk)), int(hi) + 1


def _resolve_fetch_bounds(db: Session, src: AutomicSource, system_id: int,
                          clients: List[int], t_from: datetime, t_to: datetime,
                          guard_cfg: Dict[str, Any], warnings: List[str],
                          ) -> Optional[Tuple[int, int]]:
    """Map + kaynak tavanı + (fake) zaman→RunID. Map tavanı kaynak latest'ın altında kalırsa genişletilir."""
    max_rows = int(guard_cfg.get("max_rows_per_slice") or 500)
    slack = float(guard_cfg.get("runid_slack_hours") or 24)
    if runid_map.global_bounds(db, system_id) is None:
        n = runid_map.rebuild_from_executions(db, system_id)
        if n:
            warnings.append(f"RunID eşlemesi boştu; automic_executions'tan {n} saat yeniden kuruldu")
            db.commit()
    bounds = runid_map.bounds_for_time_range(db, system_id, t_from, t_to, slack_hours=slack)
    suggest = getattr(src, "runid_bounds_for_time", None)
    src_bounds = None
    if callable(suggest):
        try:
            src_bounds = suggest(t_from, t_to)
        except Exception as exc:
            warnings.append(f"runid_bounds_for_time: {exc}")
    if src_bounds and src_bounds[1] > src_bounds[0]:
        # Kaynak zaman→RunID biliniyorsa (DEV-FAKE) eşleme tavanını YOK SAY:
        # eski/zehirli map max_run_id (ör. 9e12) taramayı sonsuza uzatırdı.
        bounds = (int(src_bounds[0]), int(src_bounds[1]))
    elif bounds is None:
        bounds = _bootstrap_runid_bounds(src, clients, max_rows, warnings, t_from, t_to)
        if bounds is None:
            warnings.append("RunID eşlemesi yok ve bootstrap başarısız — kaynak taraması atlandı")
            return None
        warnings.append(f"RunID eşlemesi boş; bootstrap PK aralığı {bounds[0]}–{bounds[1]}")
    latest = _source_latest_run_id(src, clients, warnings)
    if latest is not None and bounds[1] <= int(latest):
        bounds = (bounds[0], int(latest) + 1)
    # Eşlemede kaynak latest'tan çok büyük tavan (zehirli RunID) varsa kes
    if latest is not None and bounds[1] > int(latest) + 1:
        # Map tavanı kaynak ucundan büyükse (fake dışı): yine de latest+1 ile sınırla
        # yalnız map_min ≤ latest ise (aksi halde boş aralık)
        if bounds[0] <= int(latest):
            bounds = (bounds[0], int(latest) + 1)
    return bounds


def _fetch_range(db: Session, src: AutomicSource, system_id: int, clients: List[int],
                 t_from: datetime, t_to: datetime, guard_cfg: Dict[str, Any],
                 deadline: float, warnings: List[str]):
    """Zaman aralığını RunID eşlemesiyle PK dilimlerine çevirir. Yields (wm_hint, records, id_hi)."""
    max_rows = int(guard_cfg.get("max_rows_per_slice") or 500)
    # Fake kaynak dakika başına 10k ID üretir; dilim = 1 dakika (boş 500'lük tarama felaketini önler)
    if getattr(src, "source_type", None) == "fake":
        max_rows = max(max_rows, 10_000)
    bounds = _resolve_fetch_bounds(db, src, system_id, clients, t_from, t_to, guard_cfg, warnings)
    if bounds is None:
        return
    id_min, id_max = bounds
    cur = id_min
    while cur < id_max and time.monotonic() < deadline:
        end = min(cur + max_rows, id_max)
        try:
            recs = src.fetch_ended_executions(
                clients, t_from, t_to, limit=max_rows, id_min=cur, id_max=end)
        except SourceError as exc:
            if exc.code in ("slow_query", "template_disabled"):
                warnings.append(str(exc))
                return
            if exc.code in ("snapshot_too_old", "call_timeout") and max_rows > 50:
                max_rows = max(50, max_rows // 2)
                warnings.append(f"{exc.code}: parça {max_rows} satıra indirildi")
                continue
            raise
        ends = [r["end_time"] for r in recs if r.get("end_time")]
        wm_hint = max(ends) if ends else t_from
        yield wm_hint, recs, end
        cur = end
        # Catch-up: dolu dilimde watermark ilerlesin; bütçe bitmeden sonraki dilime geç
        if recs and len(recs) > max_rows:
            # limit+1 taşması — aynı dilimi küçültmeden devam (üst katman limit keser)
            pass


def _ingest(db: Session, system: AutomicSystem, recs: List[Dict[str, Any]],
            status_classes: Dict[str, Any],
            warnings: Optional[List[str]] = None,
            state: Optional[AutomicCollectorState] = None) -> Tuple[int, int]:
    rows = [r for r in (_exec_row(system.id, x, status_classes) for x in recs) if r]
    if not rows:
        return 0, 0
    # aynı (client, run_id, activation_time) tekrarlarını tekilleştir
    uniq = {(r["client"], r["run_id"], r["activation_time"]): r for r in rows}
    rows = list(uniq.values())
    _upsert_executions(db, rows)
    failed = [r for r in rows if r["status_class"] == "failed"]
    _upsert_failed_index(db, failed)
    try:
        runid_map.upsert_from_records(db, system.id, recs)
    except Exception as exc:
        logger.warning("RunID eşleme güncellenemedi: %s", exc)
        if warnings is not None:
            msg = f"RunID eşleme güncellenemedi: {exc}"
            if msg not in warnings:
                warnings.append(msg)
    # RunID watermark: tarama tavanı (_fetch_range / _refresh_recent_step);
    # bulunan max RunID kullanılmaz (boş client yanlış kayıp alarmı).
    if warnings is not None:
        from .users import effective_mismatch_threshold, mismatch_warning
        # Tur başına bir kez (catch-up'ta her dilimde logger.warning saniyeleri yer)
        if not any(w.startswith("AH_USR_Idnr") for w in warnings):
            msg = mismatch_warning(recs, threshold=effective_mismatch_threshold(system))
            if msg:
                warnings.append(msg)
                logger.warning("Automic [%s] %s", system.name, msg)
    return len(rows), len(failed)


def _persist_source_settings(db: Session, system: AutomicSystem, src: AutomicSource) -> None:
    """Yavaş şablon listesini sistem ayarına yaz."""
    if not getattr(src, "_templates_disabled_dirty", False):
        return
    settings = dict(system.settings or {})
    sg = dict(settings.get("source_guard") or {})
    src_sg = (src.settings or {}).get("source_guard") or {}
    if src_sg.get("disabled_templates"):
        sg["disabled_templates"] = list(src_sg["disabled_templates"])
    if src_sg.get("_slow_events"):
        sg["_slow_events"] = list(src_sg["_slow_events"])[-20:]
    settings["source_guard"] = sg
    system.settings = settings
    db.commit()
    src._templates_disabled_dirty = False


# ── hatalı rapor alıntıları (backlog kuyruğu) ─────────────────────────────

def _report_queue(db: Session, system: AutomicSystem, since: datetime, limit: int,
                  max_attempts: int, backoff_min: float) -> List[Tuple[int, int, datetime, int]]:
    """Raporu henüz alınmamış hatalı çalışmalar: saklama süresi içinde, EN YENİDEN ESKİYE.

    Dışlananlar: kırpıntısı olan, 'unavailable' (rapor alınamadı → bir daha denenmez) ve geri çekilme süresi dolmamış
    'error' kayıtları. Dönüş: (client, run_id, end_time, attempts).
    """
    rows = db.execute(text(
        "SELECT e.client, e.run_id, e.end_time, coalesce(a.attempts, 0) "
        "FROM automic_executions e "
        "LEFT JOIN automic_report_attempts a ON a.system_id = e.system_id AND a.client = e.client AND a.run_id = e.run_id "
        "WHERE e.system_id = :sid AND e.status_class = 'failed' AND e.end_time >= :since "
        "AND NOT EXISTS (SELECT 1 FROM automic_report_excerpts r WHERE r.system_id = e.system_id "
        "                AND r.client = e.client AND r.run_id = e.run_id) "
        "AND (a.run_id IS NULL OR (a.status = 'error' AND a.attempts < :maxa AND a.last_attempt_at IS NOT NULL "
        "     AND a.last_attempt_at < now() - (least(360.0, :bo * power(2, greatest(a.attempts - 1, 0))) * interval '1 minute'))) "
        "ORDER BY e.end_time DESC LIMIT :lim"
    ), {"sid": system.id, "since": since, "maxa": int(max_attempts), "bo": float(backoff_min), "lim": int(limit)}).all()
    return [(int(c), int(r), t, int(n)) for c, r, t, n in rows]


def report_queue_depth(db: Session, system_id: int, since: datetime) -> Dict[str, int]:
    """Kuyruk metrikleri: bekleyen (hiç denenmemiş), yeniden denenecek (error), rapor alınamadı (unavailable)."""
    row = db.execute(text(
        "SELECT "
        "count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM automic_report_excerpts r WHERE r.system_id = e.system_id "
        "   AND r.client = e.client AND r.run_id = e.run_id) AND a.run_id IS NULL), "
        "count(*) FILTER (WHERE a.status = 'error'), "
        "count(*) FILTER (WHERE a.status = 'unavailable') "
        "FROM automic_executions e LEFT JOIN automic_report_attempts a "
        "ON a.system_id = e.system_id AND a.client = e.client AND a.run_id = e.run_id "
        "WHERE e.system_id = :sid AND e.status_class = 'failed' AND e.end_time >= :since"
    ), {"sid": system_id, "since": since}).first()
    return {"pending": int(row[0] or 0), "retrying": int(row[1] or 0), "unavailable": int(row[2] or 0)}


def _mark_attempt(db: Session, system_id: int, client: int, run_id: int, end_time: datetime, *,
                  status: str, prev_attempts: int, error: Optional[str] = None) -> None:
    stmt = pg_insert(AutomicReportAttempt.__table__).values(
        system_id=system_id, client=client, run_id=run_id, end_time=end_time,
        attempts=prev_attempts + 1, last_attempt_at=_now(), status=status, last_error=(error or None) and error[:300],
    )
    db.execute(stmt.on_conflict_do_update(
        index_elements=["system_id", "client", "run_id"],
        set_={"attempts": stmt.excluded.attempts, "last_attempt_at": stmt.excluded.last_attempt_at,
              "status": stmt.excluded.status, "last_error": stmt.excluded.last_error,
              "end_time": stmt.excluded.end_time}))


def _collect_failed_reports(db: Session, src: AutomicSource, system: AutomicSystem,
                            settings: Dict[str, Any], deadline: float, warnings: List[str]) -> int:
    """Rapor kuyruğunu işle (en yeniden eskiye). Kaynakta rapor yoksa 'rapor alınamadı' işaretlenir ve bir daha denenmez."""
    if not src.supports("reports"):
        return 0
    exc_cfg = settings.get("excerpt") or {}
    masking = settings.get("masking") or {}
    ret_days = float((settings.get("retention") or {}).get("failed_report_excerpts_days") or 90)
    since = _now() - timedelta(days=ret_days)
    max_per = int(exc_cfg.get("max_reports_per_execution") or 3)
    wanted = [t for t in exc_cfg.get("report_types") or [] if t]
    head = int(exc_cfg.get("head_lines") or 50)
    tail = int(exc_cfg.get("tail_lines") or 200)
    max_attempts = int(exc_cfg.get("max_attempts") or 5)
    backoff = float(exc_cfg.get("retry_backoff_min") or 10)
    batch = min(_MAX_FAILED_REPORTS_PER_RUN, int(exc_cfg.get("queue_batch") or 600))

    pending = _report_queue(db, system, since, batch, max_attempts, backoff)
    done = 0
    for client, run_id, end_time, prev in pending:
        if time.monotonic() >= deadline:
            break
        try:
            types = src.list_reports(client, run_id)
            if wanted:
                types = [t for t in types if t in wanted]
            types = types[:max_per]
            if not types:
                # Kaynakta rapor yok → "rapor alınamadı"; sonsuza dek denenmez
                _mark_attempt(db, system.id, client, run_id, end_time, status="unavailable", prev_attempts=prev,
                              error="kaynakta rapor yok")
                continue
            sig_for_index = None
            for rt in types:
                rep = src.fetch_report(client, run_id, rt, head=head, tail=tail, max_scan_lines=5000)
                masked_lines = mask_text("\n".join(rep.lines), masking).splitlines()
                text_, trunc = build_excerpt(masked_lines, exc_cfg)
                sig = error_signature(masked_lines, exc_cfg.get("patterns") or [])
                sig_for_index = sig_for_index or sig
                db.execute(pg_insert(AutomicReportExcerpt.__table__).values(
                    system_id=system.id, client=client, run_id=run_id, report_type=rt[:16],
                    end_time=end_time, content=text_, total_lines=rep.total_lines,
                    truncated=trunc or rep.truncated, error_signature=sig,
                    size_bytes=len(text_.encode("utf-8")),
                ).on_conflict_do_nothing())
            if sig_for_index:
                db.query(AutomicFailedIndex).filter(
                    AutomicFailedIndex.system_id == system.id,
                    AutomicFailedIndex.client == client,
                    AutomicFailedIndex.run_id == run_id,
                    AutomicFailedIndex.day == end_time.date(),
                ).update({"error_signature": sig_for_index[:300]}, synchronize_session=False)
            _mark_attempt(db, system.id, client, run_id, end_time, status="done", prev_attempts=prev)
            done += 1
            if done % 25 == 0:
                db.commit()
        except SourceError as exc:
            if exc.code in ("circuit_open", "connection_lost", "auth_failed", "no_listener", "connect_failed"):
                db.commit()
                raise
            db.rollback()
            final = prev + 1 >= max_attempts
            try:
                _mark_attempt(db, system.id, client, run_id, end_time,
                              status="unavailable" if final else "error", prev_attempts=prev, error=str(exc))
                db.commit()
            except Exception as exc2:
                note_error("collector.report_mark_attempt", exc2)
                db.rollback()
            warnings.append(f"Rapor alınamadı ({client}/{run_id}): {exc}")
    db.commit()
    return done


# ── aktif anlık görüntü ───────────────────────────────────────────────────

def _snapshot_active(db: Session, src: AutomicSource, system: AutomicSystem, clients: List[int],
                     *, limit: int = 500) -> int:
    if not src.supports("active"):
        return 0
    recs = src.fetch_active_executions(clients, limit=max(1, int(limit)))
    now = _now()
    db.execute(delete(AutomicActiveExecution).where(AutomicActiveExecution.system_id == system.id))
    rows = []
    seen = set()
    for r in recs:
        if r.get("run_id") is None or r.get("client") is None:
            continue
        k = (int(r["client"]), int(r["run_id"]))
        if k in seen:
            continue
        seen.add(k)
        rows.append({
            "system_id": system.id, "client": k[0], "run_id": k[1],
            "parent_run_id": r.get("parent_run_id"),
            "object_name": _trunc(r.get("object_name") or "?", 200),
            "object_type": _trunc(r.get("object_type"), 16),
            "status_code": r.get("status_code"), "status_class": "active",
            "activation_time": r.get("activation_time"), "start_time": r.get("start_time"),
            "agent": _trunc(r.get("agent"), 200),
            "agent_group": _trunc(r.get("agent_group"), 200),
            "agent_assigned": _trunc(r.get("agent_assigned") or r.get("agent_group") or r.get("agent"), 200),
            "snapshot_at": now,
            "top_run_id": r.get("top_run_id"), "folder": _trunc(r.get("folder"), 400),
            "platform": _trunc(r.get("platform"), 32), "queue": _trunc(r.get("queue"), 200),
            "user": _trunc(r.get("user") or r.get("user_name_at_run"), 200),
            "user_idnr": _int_or_none(
                r.get("user_idnr") if r.get("user_idnr") is not None else r.get("user_id")),
            "user_name_at_run": _trunc(r.get("user_name_at_run") or r.get("user"), 200),
            "run_time_sec": r.get("run_time_sec"),
            "ert_sec": r.get("ert_sec"), "ert_end_time": r.get("ert_end_time"),
            "ert_calc": r.get("ert_calc"), "signal": r.get("signal"),
            "mrt_sec": r.get("mrt_sec"), "srt_sec": r.get("srt_sec"),
        })
    for i in range(0, len(rows), _UPSERT_BATCH):
        db.execute(pg_insert(AutomicActiveExecution.__table__).values(rows[i:i + _UPSERT_BATCH]))
    return len(rows)


# ── ana tur ───────────────────────────────────────────────────────────────

def run_collect(system_id: int, *, manual: bool = False, db: Optional[Session] = None) -> Dict[str, Any]:
    own = db is None
    db = db or get_automic_thread_session()
    if db is None:
        return {"ok": False, "error": "Automic DB erişilemiyor"}
    try:
        return _run_collect(db, system_id, manual=manual)
    finally:
        if own:
            db.close()


def _run_collect(db: Session, system_id: int, *, manual: bool) -> Dict[str, Any]:
    system = db.get(AutomicSystem, system_id)
    if system is None:
        return {"ok": False, "error": "Sistem bulunamadı"}
    if not system.enabled and not manual:
        return {"ok": False, "skipped": "disabled"}
    clients = [int(c) for c in (system.clients or [])]
    if not clients:
        return {"ok": False, "skipped": "no_clients", "error": "İzlenecek client seçilmemiş"}
    settings = effective_settings(system.settings)
    coll = settings["collection"]
    gcfg = settings["source_guard"]
    if not manual and not collection_allowed(coll):
        return {"ok": True, "skipped": "outside_window"}

    budget_sec = max(60, int(float(coll.get("max_run_minutes") or 10) * 60))
    ok_lock, token = _collect_lock(system.id, budget_sec + 120)
    if not ok_lock:
        return {"ok": False, "skipped": "running", "error": "Bu sistem için toplama zaten çalışıyor"}

    started = _now()
    t0 = time.monotonic()
    deadline = t0 + budget_sec
    state = _get_state(db, system.id)
    state.last_run_at = started
    db.commit()
    warnings: List[str] = []
    rows = failed = reports = 0
    active_n = 0
    step_metrics: Dict[str, Any] = {}
    error: Optional[str] = None
    try:
        with guard.source_slot(system.id, max_sessions=int(gcfg.get("max_sessions") or 2)):
            with build_source(system) as src:
                clock = StepClock(budget_sec, coll.get("step_budget_pct"), deadline, on_error=db.rollback)
                # tazelik
                fr = src.source_freshness()
                state.source_lag_sec = fr.lag_sec
                state.source_lag_method = fr.method
                state.source_latest_at = fr.latest_at
                db.commit()

                # Bakım: eski şema fake kayıtları (yalnız source_type=fake; idempotent)
                try:
                    cleanup_legacy_fake_runids(db, system, state)
                except Exception as exc:
                    db.rollback()
                    note_error("collector.maintenance", exc)

                upper = _now()
                if fr.latest_at:
                    upper = min(upper, fr.latest_at)
                elif fr.lag_sec:
                    upper = upper - timedelta(seconds=fr.lag_sec)

                overlap = timedelta(minutes=float(coll.get("overlap_min") or 15))
                if state.watermark is None:
                    state.watermark = upper - timedelta(hours=1)
                    if int(coll.get("backfill_days") or 0) > 0 and not state.backfill_done:
                        state.backfill_from = state.watermark
                        state.backfill_cursor = state.watermark
                t_from = state.watermark - overlap
                from .integrity import bump_scanned_runid_ceiling

                # 1) Yeni kayıtlar — imleç: watermark (her dilimden sonra commit)
                with clock.step("ingest") as st:
                    for wm_hint, recs, id_hi in _fetch_range(
                            db, src, system.id, clients, t_from, upper, gcfg, st.deadline, warnings):
                        n, nf = _ingest(db, system, recs, settings["status_classes"], warnings, state=state)
                        rows += n
                        failed += nf
                        st.items += n
                        bump_scanned_runid_ceiling(state, clients, id_hi)
                        if wm_hint and wm_hint > (state.watermark or wm_hint):
                            state.watermark = wm_hint
                        db.commit()
                    st.cut = time.monotonic() >= st.deadline
                    _persist_source_settings(db, system, src)

                # 2) Aktif anlık görüntü
                with clock.step("active") as st:
                    try:
                        active_lim = int(gcfg.get("max_rows_per_slice") or 500)
                        active_n = _snapshot_active(db, src, system, clients, limit=active_lim)
                        st.items = active_n
                        state.active_snapshot_at = _now()
                        db.commit()
                    except SourceError as exc:
                        if exc.code in FATAL_CODES:
                            raise
                        db.rollback()
                        warnings.append(f"Aktif çalışmalar alınamadı: {exc}")

                # 3) Rapor kuyruğu (backlog: raporu alınmamış hatalı çalışmalar, en yeniden eskiye)
                with clock.step("reports") as st:
                    if state.ingest_paused_reason:
                        warnings.append(f"Rapor alıntıları duraklatıldı: {state.ingest_paused_reason}")
                    else:
                        reports = _collect_failed_reports(db, src, system, settings, st.deadline, warnings)
                        st.items = reports
                        st.cut = time.monotonic() >= st.deadline

                # 4) Durum güncelleme (açık RunID listesi, PK sorgusu, kalıcı imleç)
                with clock.step("refresh") as st:
                    st.items = _refresh_recent_step(db, src, system, state, settings, clients, st.deadline, warnings)
                    st.cut = time.monotonic() >= st.deadline
                with clock.step("resync") as st:
                    st.items = _resync_step(db, src, system, state, settings, clients, st.deadline, warnings)
                    st.cut = time.monotonic() >= st.deadline
                with clock.step("users") as st:
                    _users_sync_step(db, src, system, state, settings, clients, st.deadline, warnings)
                with clock.step("infra") as st:
                    _infra_sync_step(db, src, system, state, settings, st.deadline, warnings)
                with clock.step("gap") as st:
                    _gap_and_stale_step(db, src, system, state, settings, clients, warnings)
                with clock.step("jpp") as st:
                    _jpp_sync_step(db, src, system, state, settings, st.deadline, warnings)
                with clock.step("script") as st:
                    _script_sync_step(db, src, system, state, settings, st.deadline, warnings)
                with clock.step("reconcile") as st:
                    _reconcile_step(db, src, system, state, settings, clients, st.deadline, warnings)
                with clock.step("backfill") as st:
                    _backfill_step(db, src, system, state, settings, clients, st.deadline, warnings)
                _persist_source_settings(db, system, src)
                step_metrics = clock.snapshot()
        guard.record_success(system.id)
        state.last_success_at = _now()
        state.last_error = "; ".join(warnings[:3]) or None
    except SourceError as exc:
        db.rollback()
        error = str(exc)
        opened = guard.record_failure(system.id, threshold=int(gcfg.get("circuit_failures") or 3),
                                      open_sec=int(gcfg.get("circuit_open_sec") or 300)) \
            if exc.code not in ("busy", "circuit_open") else False
        if opened:
            error += " — devre açıldı"
        state = _get_state(db, system.id)
        state.last_error = error
        logger.warning("Automic collect [%s] hata: %s", system.name, error)
    except Exception as exc:
        db.rollback()
        error = f"Beklenmeyen hata: {exc}"
        state = _get_state(db, system.id)
        state.last_error = error[:1000]
        logger.exception("Automic collect [%s] beklenmeyen hata", system.name)
    finally:
        _release_lock(system.id, token)

    dur = round(time.monotonic() - t0, 2)
    interval = float(coll.get("interval_min") or 10)
    state.last_rows = rows
    state.last_duration_sec = dur
    state.next_run_at = _now() + timedelta(minutes=interval)
    db.add(AutomicCollectorRun(
        system_id=system.id, kind="manual" if manual else "incremental", started_at=started,
        duration_sec=dur, rows=rows, failed_rows=failed, reports=reports,
        source_lag_sec=state.source_lag_sec, error=error, step_metrics=step_metrics or None,
    ))
    if step_metrics:
        from .steps import save_step_metrics
        save_step_metrics(state, step_metrics)
    db.commit()
    return {
        "ok": error is None, "rows": rows, "failed": failed, "reports": reports, "active": active_n,
        "duration_sec": dur, "watermark": state.watermark.isoformat() if state.watermark else None,
        "source_lag_sec": state.source_lag_sec, "warnings": warnings, "error": error,
    }


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _refresh_recent_step(db: Session, src: AutomicSource, system: AutomicSystem,
                         state: AutomicCollectorState, settings: Dict[str, Any],
                         clients: List[int], deadline: float, warnings: List[str]) -> int:
    """Durum güncelleme: min..max RunID aralığını TARAMAZ.

    Güncellenecek RunID'ler açık liste (client, run_id): son N saatte durumu kesinleşmemiş olanlar + son
    `refresh_recent_min` dk'da bitenler (geç gelen durum/zaman/user_idnr güncellemeleri). Liste PK nokta sorgusuyla,
    `refresh_chunk` parçalarıyla okunur; imleç (end_time, run_id) kalıcıdır — bütçe bitince sonraki tur kaldığı yerden devam eder.
    """
    from .steps import get_step_state
    coll = settings["collection"]
    hours = float(coll.get("refresh_hours") or 24)
    fetch = getattr(src, "fetch_ended_by_runids", None)
    if hours <= 0 or not callable(fetch):
        return 0
    per_run = int(coll.get("refresh_ids_per_run") or 400)
    chunk = max(1, int(coll.get("refresh_chunk") or 50))
    recent_min = float(coll.get("refresh_recent_min") or 30)
    ss = get_step_state(state)
    cur = dict(ss["cursors"].get("refresh") or {})
    now = _now()
    since = now - timedelta(hours=hours)
    cur_end = _parse_iso(cur.get("end_time")) or since
    if cur_end < since:
        cur_end = since
    cur_run = int(cur.get("run_id") or 0)
    rows = db.execute(text(
        "SELECT client, run_id, end_time FROM automic_executions "
        "WHERE system_id = :sid AND end_time >= :since "
        "AND (end_time > :ce OR (end_time = :ce AND run_id > :cr)) "
        "AND (status_class NOT IN ('ok', 'failed', 'cancelled') OR end_time >= :recent) "
        "ORDER BY end_time ASC, run_id ASC LIMIT :lim"
    ), {"sid": system.id, "since": since, "ce": cur_end, "cr": cur_run,
        "recent": now - timedelta(minutes=recent_min), "lim": per_run}).all()
    from .integrity import bump_scanned_runid_ceiling  # noqa: F401  (tarama tavanı artık yalnız ana alımda ilerler)
    refreshed = 0
    last = None
    for i in range(0, len(rows), chunk):
        if time.monotonic() >= deadline:
            break
        part = rows[i:i + chunk]
        pairs = [(int(c), int(r)) for c, r, _ in part]
        try:
            recs = fetch(pairs)
        except SourceError as exc:
            if exc.code in ("circuit_open", "connection_lost", "auth_failed", "no_listener", "connect_failed"):
                raise
            warnings.append(f"Yeniden okuma: {exc}")
            break
        if recs:
            n, _ = _ingest(db, system, recs, settings["status_classes"], warnings, state=state)
            refreshed += n
        last = part[-1]
        cur = {"end_time": last[2].isoformat(), "run_id": int(last[1])}
        ss = get_step_state(state)
        ss["cursors"]["refresh"] = cur
        state.step_state = ss
        db.commit()
    if last is not None and len(rows) < per_run and last is rows[-1]:
        # Geçiş tamamlandı → bir sonraki tur baştan (son N saat) başlar
        ss = get_step_state(state)
        ss["cursors"]["refresh"] = {}
        state.step_state = ss
        db.commit()
    elif last is None and not rows:
        ss = get_step_state(state)
        if ss["cursors"].get("refresh"):
            ss["cursors"]["refresh"] = {}
            state.step_state = ss
            db.commit()
    if refreshed:
        logger.info("Automic refresh [%s] ids=%s güncellendi=%s", system.name, len(rows), refreshed)
    return refreshed


def _resync_step(db: Session, src: AutomicSource, system: AutomicSystem,
                 state: AutomicCollectorState, settings: Dict[str, Any],
                 clients: List[int], deadline: float, warnings: List[str]) -> int:
    """Bakım sonrası zaman penceresini kaynaktan yeniden oku (kalıcı imleç: step_state.cursors.resync)."""
    from .steps import get_step_state
    ss = get_step_state(state)
    rs = ss["cursors"].get("resync")
    if not rs:
        return 0
    start, end = _parse_iso(rs.get("cursor") or rs.get("from")), _parse_iso(rs.get("to"))
    if not start or not end or start >= end:
        ss["cursors"].pop("resync", None)
        state.step_state = ss
        db.commit()
        return 0
    gcfg = settings["source_guard"]
    total = 0
    cursor = start
    # Dilimler dar zaman pencereleriyle okunur; imleç her dilimden sonra ilerler
    step = timedelta(hours=1)
    while cursor < end and time.monotonic() < deadline:
        win_end = min(cursor + step, end)
        for _wm, recs, _hi in _fetch_range(db, src, system.id, clients, cursor, win_end, gcfg, deadline, warnings):
            n, _ = _ingest(db, system, recs, settings["status_classes"], warnings, state=state)
            total += n
            db.commit()
        if time.monotonic() >= deadline:
            break
        cursor = win_end
        ss = get_step_state(state)
        ss["cursors"]["resync"] = {**rs, "cursor": cursor.isoformat()}
        state.step_state = ss
        db.commit()
    ss = get_step_state(state)
    if cursor >= end:
        ss["cursors"].pop("resync", None)
        logger.warning("Automic [%s] resync tamamlandı (%s → %s)", system.name, start.isoformat(), end.isoformat())
    state.step_state = ss
    db.commit()
    return total


def _gap_and_stale_step(db: Session, src: AutomicSource, system: AutomicSystem,
                        state: AutomicCollectorState, settings: Dict[str, Any],
                        clients: List[int], warnings: List[str]) -> None:
    from .integrity import (
        detect_reorg_gaps, ingest_stall_warning, stale_collection_warning,
    )

    coll = settings["collection"]
    msg = stale_collection_warning(state, threshold_hours=float(coll.get("stale_warn_hours") or 6))
    if msg and msg not in warnings:
        warnings.append(msg)
    stall = ingest_stall_warning(
        db, system.id, state, src,
        zero_ticks=int(coll.get("zero_ingest_warn_ticks") or 6),
    )
    if stall and stall not in warnings:
        warnings.append(stall)
    # Kaynak MIN > RunID watermark → kayıp; MIN yükselmesi tek başına normal reorg
    try:
        n, gap_warns = detect_reorg_gaps(db, system, src, state, clients)
        for w in gap_warns:
            if w not in warnings:
                warnings.append(w)
        db.commit()
    except Exception as exc:
        note_error("collector._gap_and_stale_step", exc)


def _reconcile_step(db: Session, src: AutomicSource, system: AutomicSystem,
                    state: AutomicCollectorState, settings: Dict[str, Any],
                    clients: List[int], deadline: float, warnings: List[str]) -> None:
    """Günde bir (ağır pencere) son 2 gün saatlik mutabakat."""
    from .integrity import reconcile_hourly

    coll = settings["collection"]
    if not in_heavy_window(coll) or time.monotonic() >= deadline - 30:
        return
    last = state.reconcile_at
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last and (_now() - last) < timedelta(hours=20):
        return
    try:
        res = reconcile_hourly(
            db, system, src, clients,
            days=int(coll.get("reconcile_days") or 2),
            diff_pct_threshold=float(coll.get("reconcile_diff_pct") or 1.0),
        )
        state.reconcile_at = _now()
        db.commit()
        for w in res.get("warnings") or []:
            if w not in warnings:
                warnings.append(w)
        logger.info(
            "Automic mutabakat [%s] hours=%s max_diff=%s",
            system.name, res.get("hours_checked"), res.get("max_diff_pct"),
        )
    except Exception as exc:
        db.rollback()
        warnings.append(f"Mutabakat: {exc}")


def _infra_sync_step(db: Session, src: AutomicSource, system: AutomicSystem, state: AutomicCollectorState,
                     settings: Dict[str, Any], deadline: float, warnings: List[str]) -> None:
    """HOST / MQSRV / OHG — küçük referans tablo senkronu."""
    from .infra import sync_infrastructure
    from .teams import seed_demo_rules

    gcfg = settings["source_guard"]
    if not gcfg.get("infra_sync_enabled", True):
        return
    if time.monotonic() >= deadline - 10:
        return
    if not (src.supports("agents") or src.supports("infrastructure")
            or callable(getattr(src, "fetch_hosts", None))):
        return
    try:
        res = sync_infrastructure(db, system, src, settings=settings)
        if res.get("warnings"):
            for w in res["warnings"]:
                if w not in warnings:
                    warnings.append(w)
        if res.get("ok") and (system.source_type == "fake" or fake_mode_check()):
            seed_demo_rules(db, system.id)
        logger.info(
            "Automic infra sync [%s] agents=%s engine=%s groups=%s",
            system.name, res.get("agents"), res.get("engine_processes"), res.get("groups"),
        )
    except Exception as exc:
        db.rollback()
        warnings.append(f"Altyapı senkron: {exc}")


def fake_mode_check() -> bool:
    try:
        from .source.factory import fake_mode_enabled
        return fake_mode_enabled()
    except Exception as _exc:
        note_error("collector.silent_917", _exc)
        return False


def _users_sync_step(db: Session, src: AutomicSource, system: AutomicSystem, state: AutomicCollectorState,
                     settings: Dict[str, Any], clients: List[int], deadline: float,
                     warnings: List[str]) -> None:
    """OH USER → automic_users (USR okunmaz); OH_Idnr PK parçaları (min..max)."""
    from .users import sync_users_chunk

    gcfg = settings["source_guard"]
    if not gcfg.get("user_sync_enabled", True):
        return
    if time.monotonic() >= deadline - 15:
        return
    if not src.supports("objects"):
        return
    bounds_fn = getattr(src, "user_object_id_bounds", None)
    try:
        bounds = bounds_fn(clients) if callable(bounds_fn) else None
    except SourceError as exc:
        warnings.append(f"USER senkron bounds: {exc}")
        return
    if not bounds:
        row = db.execute(text(
            "SELECT MIN(user_idnr), MAX(user_idnr) FROM automic_users WHERE system_id = :sid"
        ), {"sid": system.id}).first()
        if row and row[0] is not None:
            bounds = (int(row[0]), int(row[1]))
    if not bounds:
        return
    lo, hi = int(bounds[0]), int(bounds[1])
    chunk = max(50, int(gcfg.get("user_chunk_rows") or 2000))
    cursor = int(state.users_oh_id_cursor or 0)
    if cursor < lo:
        cursor = lo
    if cursor > hi:
        state.users_oh_id_cursor = 0
        state.users_synced_at = _now()
        db.commit()
        return
    id_min, id_max = cursor, min(cursor + chunk, hi + 1)
    try:
        res = sync_users_chunk(db, system, src, id_min=id_min, id_max=id_max, limit=chunk + 50)
        state.users_oh_id_cursor = id_max
        if id_max > hi:
            state.users_oh_id_cursor = 0
            state.users_synced_at = _now()
        db.commit()
        logger.info(
            "Automic USER sync [%s] oh_id=[%s,%s) upserted=%s unchanged=%s",
            system.name, id_min, id_max, res.get("upserted"), res.get("unchanged"),
        )
        if res.get("error"):
            warnings.append(f"USER senkron: {res['error']}")
    except SourceError as exc:
        db.rollback()
        warnings.append(f"USER senkron: {exc}")


def _jpp_sync_step(db: Session, src: AutomicSource, system: AutomicSystem, state: AutomicCollectorState,
                   settings: Dict[str, Any], deadline: float, warnings: List[str]) -> None:
    """JPP → modül DB: OH_Idnr PK parçaları, varsayılan gecelik ağır pencere."""
    from .objects import sync_jpp_chunk

    gcfg = settings["source_guard"]
    coll = settings["collection"]
    if not gcfg.get("jpp_sync_enabled", True):
        return
    if not in_heavy_window(coll) or time.monotonic() >= deadline - 30:
        return
    if not src.supports("usage_graph"):
        return
    max_oid = db.execute(
        text("SELECT MAX(object_id) FROM automic_object_headers WHERE system_id = :sid"),
        {"sid": system.id},
    ).scalar()
    if max_oid is None:
        return
    cautious = bool(gcfg.get("cautious_mode", True))
    chunk = int(gcfg.get("jpp_chunk_rows") or gcfg.get("backfill_chunk_rows") or 500)
    if not cautious:
        chunk = int(gcfg.get("backfill_chunk_rows_normal") or chunk)
    chunk = max(50, chunk)
    cursor = int(state.jpp_oh_id_cursor or 0)
    if cursor > int(max_oid):
        state.jpp_oh_id_cursor = 0
        state.jpp_synced_at = _now()
        db.commit()
        return
    id_min, id_max = cursor, cursor + chunk
    try:
        res = sync_jpp_chunk(db, system, src, id_min=id_min, id_max=id_max, limit=chunk + 50)
        state.jpp_oh_id_cursor = id_max
        if id_max > int(max_oid):
            state.jpp_oh_id_cursor = 0
            state.jpp_synced_at = _now()
        db.commit()
        logger.info(
            "Automic JPP sync [%s] oh_id=[%s,%s) upserted=%s",
            system.name, id_min, id_max, res.get("upserted"),
        )
    except SourceError as exc:
        db.rollback()
        warnings.append(f"JPP senkron: {exc}")
    pause = float(gcfg.get("backfill_pause_sec") or 0)
    if pause > 0:
        time.sleep(min(pause, 5))


def _script_sync_step(db: Session, src: AutomicSource, system: AutomicSystem, state: AutomicCollectorState,
                      settings: Dict[str, Any], deadline: float, warnings: List[str]) -> None:
    """OT script → modül DB: OH_Idnr PK aralığı + OH_ModDate değişenler; ağır pencere."""
    from .objects import sync_scripts_chunk

    gcfg = settings["source_guard"]
    coll = settings["collection"]
    if not gcfg.get("script_sync_enabled", True):
        return
    if not in_heavy_window(coll) or time.monotonic() >= deadline - 30:
        return
    if not src.supports("versions"):
        return
    max_oid = db.execute(
        text("SELECT MAX(object_id) FROM automic_object_headers WHERE system_id = :sid"),
        {"sid": system.id},
    ).scalar()
    if max_oid is None:
        return
    chunk = int(gcfg.get("jpp_chunk_rows") or gcfg.get("backfill_chunk_rows") or 500)
    chunk = max(50, chunk)
    max_obj = int(gcfg.get("script_chunk_objects") or 20)
    cursor = int(state.script_oh_id_cursor or 0)
    if cursor > int(max_oid):
        state.script_oh_id_cursor = 0
        state.script_synced_at = _now()
        db.commit()
        return
    id_min, id_max = cursor, cursor + chunk
    try:
        res = sync_scripts_chunk(
            db, system, src, id_min=id_min, id_max=id_max, max_objects=max_obj)
        state.script_oh_id_cursor = id_max
        if id_max > int(max_oid):
            state.script_oh_id_cursor = 0
            state.script_synced_at = _now()
        db.commit()
        logger.info(
            "Automic OT script sync [%s] oh_id=[%s,%s) upserted=%s",
            system.name, id_min, id_max, res.get("upserted"),
        )
    except SourceError as exc:
        db.rollback()
        warnings.append(f"Script senkron: {exc}")


def _backfill_step(db: Session, src: AutomicSource, system: AutomicSystem, state: AutomicCollectorState,
                   settings: Dict[str, Any], clients: List[int], deadline: float, warnings: List[str]) -> None:
    """AH_Idnr parçalarıyla geri yükleme — yalnız ağır pencere; kaldığı yerden devam."""
    coll = settings["collection"]
    gcfg = settings["source_guard"]
    days = int(coll.get("backfill_days") or 0)
    if days <= 0 or state.backfill_done:
        return
    if not in_heavy_window(coll) or time.monotonic() >= deadline - 30:
        return
    cautious = bool(gcfg.get("cautious_mode", True))
    chunk = int(gcfg.get("backfill_chunk_rows") if cautious else gcfg.get("backfill_chunk_rows_normal") or 500)
    chunk = max(50, chunk)
    pause = float(gcfg.get("backfill_pause_sec") or 2)
    cursor = state.backfill_run_id_cursor
    if cursor is None:
        bounds = _bootstrap_runid_bounds(src, clients, chunk, warnings)
        if bounds is None:
            warnings.append("Backfill: RunID üst sınırı alınamadı")
            return
        cursor = bounds[1]
        state.backfill_run_id_cursor = cursor
        db.commit()
    gb = runid_map.global_bounds(db, system.id)
    # Yaklaşık alt sınır: eşlemedeki min veya (üst - days*tahmini); bilinmiyorsa 1
    floor_id = int(gb[0]) if gb else 1
    fn = getattr(src, "fetch_ended_by_runid_range", None)
    while cursor > floor_id and time.monotonic() < deadline - 30:
        lo = max(floor_id, int(cursor) - chunk)
        try:
            if callable(fn):
                recs = fn(clients, lo, int(cursor), limit=chunk)
            else:
                recs = src.fetch_ended_executions(
                    clients, _now() - timedelta(days=days), _now(),
                    limit=chunk, id_min=lo, id_max=int(cursor))
        except SourceError as exc:
            warnings.append(f"Backfill durdu: {exc}")
            break
        _ingest(db, system, recs, settings["status_classes"], state=state)
        cursor = lo
        state.backfill_run_id_cursor = cursor
        db.commit()
        if pause > 0:
            time.sleep(min(pause, 30))
    if cursor <= floor_id:
        state.backfill_done = True
        db.commit()


# ── zamanlayıcı ───────────────────────────────────────────────────────────

def due_systems(db: Session) -> List[int]:
    now = _now()
    ids = []
    for s in db.query(AutomicSystem).filter(AutomicSystem.enabled.is_(True)).all():
        st = db.get(AutomicCollectorState, s.id)
        if st is None or st.next_run_at is None or st.next_run_at <= now:
            ids.append(s.id)
    return ids


def tick() -> Dict[str, Any]:
    """Zamanı gelen sistemleri sırayla toplar (scheduler thread'inde çağrılır)."""
    db = get_automic_thread_session()
    if db is None:
        return {"ok": False}
    try:
        ids = due_systems(db)
    finally:
        db.close()
    results = {}
    for sid in ids:
        results[sid] = run_collect(sid)
    return {"ok": True, "systems": results}


def collector_runs_summary(db: Session, system_id: int, hours: int = 24) -> Dict[str, Any]:
    since = _now() - timedelta(hours=hours)
    q = db.query(
        func.count(AutomicCollectorRun.id),
        func.count(AutomicCollectorRun.error),
        func.coalesce(func.sum(AutomicCollectorRun.rows), 0),
        func.avg(AutomicCollectorRun.duration_sec),
    ).filter(AutomicCollectorRun.system_id == system_id, AutomicCollectorRun.started_at >= since).one()
    return {"runs": int(q[0] or 0), "errors": int(q[1] or 0), "rows": int(q[2] or 0),
            "avg_duration_sec": round(float(q[3] or 0), 2)}
