"""Collector doğruluk: durum yenileme yardımcıları, reorg boşluğu, mutabakat.

AE ürün sürümü: kaynak tablodan otomatik okunmaz (şemada kolon yok); kurulumda elle girilir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.automic import AutomicDataGap, AutomicReconcileReport, AutomicSystem

from . import runid_map
from .source.base import SourceError

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stale_collection_warning(state, *, threshold_hours: float) -> Optional[str]:
    """Son başarılı toplama eşiği aştıysa kritik uyarı metni."""
    last = getattr(state, "last_success_at", None)
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_h = (_now() - last).total_seconds() / 3600.0
    if age_h < float(threshold_hours):
        return None
    return (
        f"KRİTİK: Son başarılı toplama {age_h:.1f} saat önce "
        f"(eşik {float(threshold_hours):g} saat) — veri boşluğu riski"
    )


def ingest_stall_warning(
    db: Session, system_id: int, state, src, *, zero_ticks: int = 6,
) -> Optional[str]:
    """N tur boyunca 0 yeni satır yazıldıysa ve kaynakta yeni veri varken kritik uyarı.

    ``last_success_at`` her turda güncellenir; bu yüzden yalnız ona bakmak sessiz
    veri kaybını gizler. Collector run geçmişi + watermark / kaynak ucu kullanılır.
    """
    n = max(2, int(zero_ticks or 6))
    rows = db.execute(text(
        "SELECT rows, started_at FROM automic_collector_runs "
        "WHERE system_id = :sid AND kind IN ('incremental', 'manual') "
        "ORDER BY started_at DESC LIMIT :n"
    ), {"sid": int(system_id), "n": n}).all()
    if len(rows) < n:
        return None
    if any(int(r[0] or 0) > 0 for r in rows):
        return None
    wm = getattr(state, "watermark", None)
    source_newer = False
    probe = getattr(src, "source_has_ended_after", None)
    if callable(probe) and wm is not None:
        try:
            source_newer = bool(probe(wm))
        except Exception:
            source_newer = False
    if not source_newer and wm is not None:
        if wm.tzinfo is None:
            wm = wm.replace(tzinfo=timezone.utc)
        # Kaynak probe yoksa: watermark > 2× interval gerideyse ve last_success taze ise şüpheli
        last_ok = getattr(state, "last_success_at", None)
        if last_ok is not None:
            if last_ok.tzinfo is None:
                last_ok = last_ok.replace(tzinfo=timezone.utc)
            if (_now() - last_ok) < timedelta(hours=2) and (_now() - wm) > timedelta(hours=2):
                source_newer = True
    if not source_newer:
        return None
    return (
        f"KRİTİK: Son {n} toplama turunda hiç yeni kayıt yazılmadı "
        f"(last_rows=0) ancak kaynakta watermark sonrası veri var — "
        f"RunID eşlemesi / tarama tavanı kontrol edin (sessiz veri kaybı)"
    )


def data_freshness_fields(db: Session, system_id: int, state) -> Dict[str, Any]:
    """UI/API: son yeni kayıt zamanı + son tur yazılan satır + stall özeti."""
    last_new = db.execute(text(
        "SELECT max(end_time) FROM automic_executions WHERE system_id = :sid"
    ), {"sid": int(system_id)}).scalar()
    zero_streak = 0
    for (nrows,) in db.execute(text(
        "SELECT rows FROM automic_collector_runs "
        "WHERE system_id = :sid AND kind IN ('incremental', 'manual') "
        "ORDER BY started_at DESC LIMIT 30"
    ), {"sid": int(system_id)}):
        if int(nrows or 0) > 0:
            break
        zero_streak += 1
    return {
        "last_new_record_at": last_new.isoformat() if last_new else None,
        "last_ingest_rows": int(getattr(state, "last_rows", 0) or 0) if state else 0,
        "zero_ingest_streak": zero_streak,
        "watermark": state.watermark.isoformat() if state and state.watermark else None,
    }


def record_data_gap(
    db: Session, system_id: int, *, id_min: int, id_max: int,
    reason: str = "reorg", detail: Optional[str] = None,
    client: Optional[int] = None,
) -> None:
    """Açık (resolved_at NULL) aynı aralık varsa tekrar yazma."""
    exists = db.execute(text(
        "SELECT id FROM automic_data_gaps WHERE system_id = :sid AND id_min = :lo AND id_max = :hi "
        "AND resolved_at IS NULL LIMIT 1"
    ), {"sid": system_id, "lo": int(id_min), "hi": int(id_max)}).first()
    if exists:
        return
    db.add(AutomicDataGap(
        system_id=system_id, client=client, id_min=int(id_min), id_max=int(id_max),
        reason=reason[:64], detail=(detail or "")[:2000], detected_at=_now(),
    ))


def list_open_gaps(db: Session, system_id: int, *, limit: int = 20) -> List[Dict[str, Any]]:
    rows = db.execute(text(
        "SELECT id, client, id_min, id_max, reason, detail, detected_at FROM automic_data_gaps "
        "WHERE system_id = :sid AND resolved_at IS NULL ORDER BY detected_at DESC LIMIT :lim"
    ), {"sid": system_id, "lim": limit}).all()
    return [{
        "id": r[0], "client": r[1], "id_min": int(r[2]), "id_max": int(r[3]),
        "reason": r[4], "detail": r[5],
        "detected_at": r[6].isoformat() if r[6] else None,
        "label": "kayıp veri",
    } for r in rows]


def bump_run_id_watermarks(state, rows: List[Dict[str, Any]]) -> None:
    """(Eski) Ingest edilen satırlardan client → max AH_Idnr.

    Kayıp-veri alarmı için tercih edilen yol ``bump_scanned_runid_ceiling`` —
    uzun süredir çalışmayan client'larda max-found yanlış alarm üretir.
    """
    if not rows:
        return
    wm = dict(getattr(state, "run_id_watermark_by_client", None) or {})
    for r in rows:
        c = r.get("client")
        rid = r.get("run_id")
        if c is None or rid is None:
            continue
        key = str(int(c))
        rid_i = int(rid)
        prev = wm.get(key)
        if prev is None or rid_i > int(prev):
            wm[key] = rid_i
    state.run_id_watermark_by_client = wm


def bump_scanned_runid_ceiling(
    state, clients: List[int], scanned_id_hi: int,
) -> None:
    """Client watermark = tarama aralığının üst sınırı (exclusive end).

    Bulunan max RunID yerine collector'ın taradığı PK tavanını kullanır;
    uzun süredir çalışmayan client yanlış kayıp alarmı üretmez.
    """
    try:
        hi = int(scanned_id_hi)
    except (TypeError, ValueError):
        return
    if hi <= 0:
        return
    wm = dict(getattr(state, "run_id_watermark_by_client", None) or {})
    for c in clients or []:
        key = str(int(c))
        prev = wm.get(key)
        if prev is None or hi > int(prev):
            wm[key] = hi
    state.run_id_watermark_by_client = wm


def client_runid_watermarks(
    db: Session, system_id: int, state, clients: List[int],
) -> Dict[int, int]:
    """Client → son okunan/yazılan max AH_Idnr (state + modül DB MAX)."""
    out: Dict[int, int] = {}
    stored = getattr(state, "run_id_watermark_by_client", None) or {}
    for c in clients:
        key = str(int(c))
        if key in stored and stored[key] is not None:
            out[int(c)] = int(stored[key])
    if not clients:
        return out
    rows = db.execute(text(
        "SELECT client, MAX(run_id) FROM automic_executions "
        "WHERE system_id = :sid AND client = ANY(:cl) GROUP BY client"
    ), {"sid": system_id, "cl": list(clients)}).all()
    for c, mx in rows:
        if mx is None:
            continue
        c_i, mx_i = int(c), int(mx)
        out[c_i] = max(out.get(c_i, mx_i), mx_i)
    return out


def detect_reorg_gaps(
    db: Session, system: AutomicSystem, src, state, clients: List[int],
) -> Tuple[int, List[str]]:
    """Kaynak MIN(AH_Idnr) > min(client RunID watermark) ise kayıp; aksi halde normal reorg.

    - Normal reorg (MIN yükselir ama watermark'ın altında/eşit): alarm yok, bilgi logu.
    - Gerçek kayıp (MIN > watermark): aralık (watermark, kaynak_min) → gaps + kritik uyarı.
    RunID dizisindeki boşluklar kayıp sayılmaz.
    """
    min_fn = getattr(src, "min_run_id", None)
    if not callable(min_fn):
        return 0, []
    try:
        src_min = min_fn()
    except TypeError:
        # Eski imza min_run_id(client) — kullanma
        return 0, []
    except SourceError as exc:
        return 0, [f"reorg min_run_id: {exc}"]
    if src_min is None:
        return 0, []
    src_min = int(src_min)
    now = _now()

    wms = client_runid_watermarks(db, system.id, state, clients)
    if not wms:
        logger.info(
            "Automic reorg bilgi [%s] kaynak_min=%s watermark=yok at=%s",
            system.name, src_min, now.isoformat(),
        )
        return 0, []

    watermark = min(wms.values())
    if src_min > watermark:
        # Kayıp aralığı (watermark, kaynak_min) — yarım açık [watermark, kaynak_min) kaydı
        record_data_gap(
            db, system.id, id_min=watermark, id_max=src_min, client=None,
            reason="reorg",
            detail=(
                f"Kaynak MIN AH_Idnr {src_min} > watermark {watermark}; "
                f"kayıp aralık ({watermark}, {src_min})"
            ),
        )
        warn = (
            f"KRİTİK: Kayıp veri (reorg) — kaynak MIN={src_min} > watermark={watermark}; "
            f"aralık ({watermark}, {src_min})"
        )
        logger.warning("Automic [%s] %s", system.name, warn)
        return 1, [warn]

    logger.info(
        "Automic reorg normal [%s] kaynak_min=%s watermark=%s at=%s",
        system.name, src_min, watermark, now.isoformat(),
    )
    return 0, []


def reconcile_hourly(
    db: Session, system: AutomicSystem, src, clients: List[int],
    *, days: int = 2, diff_pct_threshold: float = 1.0,
) -> Dict[str, Any]:
    """Son N gün saat bazında kaynak COUNT (PK) ↔ modül COUNT karşılaştır."""
    count_fn = getattr(src, "count_ended_by_id_range", None)
    if not callable(count_fn):
        return {"ok": False, "skipped": "count_unavailable"}
    end = _now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=max(1, int(days)))
    warnings: List[str] = []
    hours_checked = 0
    max_diff = 0.0
    cur = start
    while cur < end:
        nxt = cur + timedelta(hours=1)
        bounds = runid_map.bounds_for_time_range(
            db, system.id, cur, nxt, slack_hours=0)
        if bounds is None:
            cur = nxt
            continue
        lo, hi = bounds
        try:
            src_n = int(count_fn(clients, lo, hi) or 0)
        except SourceError as exc:
            warnings.append(f"mutabakat sayım {cur.isoformat()}: {exc}")
            cur = nxt
            continue
        mod_n = int(db.execute(text(
            "SELECT count(*) FROM automic_executions WHERE system_id = :sid "
            "AND client = ANY(:cl) AND end_time >= :t0 AND end_time < :t1"
        ), {"sid": system.id, "cl": list(clients), "t0": cur, "t1": nxt}).scalar() or 0)
        base = max(src_n, mod_n, 1)
        diff = abs(src_n - mod_n) * 100.0 / base
        max_diff = max(max_diff, diff)
        stmt = pg_insert(AutomicReconcileReport.__table__).values([{
            "system_id": system.id, "hour_utc": cur,
            "source_count": src_n, "module_count": mod_n,
            "diff_pct": round(diff, 3), "id_min": lo, "id_max": hi,
            "created_at": _now(),
        }])
        stmt = stmt.on_conflict_do_update(
            index_elements=["system_id", "hour_utc"],
            set_={
                "source_count": stmt.excluded.source_count,
                "module_count": stmt.excluded.module_count,
                "diff_pct": stmt.excluded.diff_pct,
                "id_min": stmt.excluded.id_min,
                "id_max": stmt.excluded.id_max,
                "created_at": stmt.excluded.created_at,
            },
        )
        db.execute(stmt)
        hours_checked += 1
        if diff >= float(diff_pct_threshold) and max(src_n, mod_n) >= 10:
            warnings.append(
                f"Mutabakat: {cur.isoformat()} kaynak={src_n} modül={mod_n} "
                f"fark=%{diff:.1f} (eşik %{float(diff_pct_threshold):g})"
            )
        cur = nxt
    return {
        "ok": True, "hours_checked": hours_checked, "max_diff_pct": round(max_diff, 2),
        "warnings": warnings[:10],
    }


def recent_reconcile_summary(db: Session, system_id: int, *, limit: int = 10) -> Dict[str, Any]:
    rows = db.execute(text(
        "SELECT hour_utc, source_count, module_count, diff_pct, id_min, id_max "
        "FROM automic_reconcile_reports WHERE system_id = :sid "
        "ORDER BY hour_utc DESC LIMIT :lim"
    ), {"sid": system_id, "lim": limit}).all()
    items = [{
        "hour_utc": r[0].isoformat() if r[0] else None,
        "source_count": int(r[1]), "module_count": int(r[2]),
        "diff_pct": float(r[3] or 0), "id_min": r[4], "id_max": r[5],
    } for r in rows]
    worst = max((i["diff_pct"] for i in items), default=0.0)
    return {"items": items, "max_diff_pct": worst}
