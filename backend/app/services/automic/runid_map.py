"""Zaman aralığı → AH_Idnr (RunID) eşlemesi.

Collector her ingest'te saat başına min/max RunID yazar. Kaynak sorguları
AH_Idnr BETWEEN ile PK üzerinden çalışır; sonuç modül tarafında gerçek zaman
kolonuna göre süzülür. Alt sınır `runid_slack_hours` (varsayılan 24s) ile genişler
(RunID aktivasyon anında atanır; bitiş zamanı daha geç olabilir).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.automic import AutomicRunIdHourMap


def _hour_floor(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def upsert_from_records(db: Session, system_id: int, records: Iterable[Dict[str, Any]]) -> int:
    """Ingest edilen kayıtlardan saatlik min/max RunID güncelle (aktivasyon zamanı öncelikli)."""
    buckets: Dict[datetime, Dict[str, int]] = {}
    for r in records:
        rid = r.get("run_id")
        if rid is None:
            continue
        t = r.get("activation_time") or r.get("start_time") or r.get("end_time")
        if t is None:
            continue
        h = _hour_floor(t if isinstance(t, datetime) else datetime.fromisoformat(str(t)))
        b = buckets.setdefault(h, {"min": int(rid), "max": int(rid), "n": 0})
        b["min"] = min(b["min"], int(rid))
        b["max"] = max(b["max"], int(rid))
        b["n"] += 1
    if not buckets:
        return 0
    rows = [{
        "system_id": system_id, "hour_utc": h,
        "min_run_id": v["min"], "max_run_id": v["max"], "sample_count": v["n"],
    } for h, v in buckets.items()]
    stmt = pg_insert(AutomicRunIdHourMap.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["system_id", "hour_utc"],
        set_={
            "min_run_id": text("LEAST(automic_runid_hour_map.min_run_id, EXCLUDED.min_run_id)"),
            "max_run_id": text("GREATEST(automic_runid_hour_map.max_run_id, EXCLUDED.max_run_id)"),
            "sample_count": text("automic_runid_hour_map.sample_count + EXCLUDED.sample_count"),
        },
    )
    db.execute(stmt)
    return len(rows)


def bounds_for_time_range(
    db: Session, system_id: int, t_from: datetime, t_to: datetime, *, slack_hours: float = 24,
) -> Optional[Tuple[int, int]]:
    """[t_from - slack, t_to) saatleri için (min_run_id, max_run_id+1). Yoksa None."""
    if t_from.tzinfo is None:
        t_from = t_from.replace(tzinfo=timezone.utc)
    if t_to.tzinfo is None:
        t_to = t_to.replace(tzinfo=timezone.utc)
    lo = _hour_floor(t_from - timedelta(hours=float(slack_hours)))
    hi = _hour_floor(t_to) + timedelta(hours=1)
    row = db.execute(text(
        "SELECT MIN(min_run_id), MAX(max_run_id) FROM automic_runid_hour_map "
        "WHERE system_id = :sid AND hour_utc >= :lo AND hour_utc < :hi"
    ), {"sid": system_id, "lo": lo, "hi": hi}).first()
    if not row or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1]) + 1


def global_bounds(db: Session, system_id: int) -> Optional[Tuple[int, int]]:
    row = db.execute(text(
        "SELECT MIN(min_run_id), MAX(max_run_id) FROM automic_runid_hour_map WHERE system_id = :sid"
    ), {"sid": system_id}).first()
    if not row or row[0] is None:
        return None
    return int(row[0]), int(row[1]) + 1


def rebuild_from_executions(db: Session, system_id: int, *, limit_hours: int = 0) -> int:
    """automic_executions'tan saatlik min/max RunID eşlemesini yeniden kur.

    Partition migration / map silinmesi sonrası collector'ın 0 satırda kalmasını önler.
    limit_hours>0 ise yalnız son N saat (aktivasyon) alınır; 0 = tümü.
    Dönüş: yazılan/güncellenen saat kovası sayısı.
    """
    where = "system_id = :sid AND run_id IS NOT NULL"
    params: Dict[str, Any] = {"sid": system_id}
    if limit_hours and limit_hours > 0:
        where += (
            " AND coalesce(activation_time, start_time, end_time) >= "
            "(NOW() - (:h * INTERVAL '1 hour'))"
        )
        params["h"] = int(limit_hours)
    rows = db.execute(text(f"""
        SELECT date_trunc('hour', coalesce(activation_time, start_time, end_time)) AS hour_utc,
               MIN(run_id), MAX(run_id), COUNT(*)::int
        FROM automic_executions
        WHERE {where}
        GROUP BY 1
    """), params).all()
    if not rows:
        return 0
    payload = []
    for h, mn, mx, n in rows:
        if h is None or mn is None:
            continue
        if isinstance(h, datetime) and h.tzinfo is None:
            h = h.replace(tzinfo=timezone.utc)
        payload.append({
            "system_id": system_id, "hour_utc": h,
            "min_run_id": int(mn), "max_run_id": int(mx), "sample_count": int(n),
        })
    if not payload:
        return 0
    stmt = pg_insert(AutomicRunIdHourMap.__table__).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["system_id", "hour_utc"],
        set_={
            "min_run_id": text("LEAST(automic_runid_hour_map.min_run_id, EXCLUDED.min_run_id)"),
            "max_run_id": text("GREATEST(automic_runid_hour_map.max_run_id, EXCLUDED.max_run_id)"),
            "sample_count": text(
                "GREATEST(automic_runid_hour_map.sample_count, EXCLUDED.sample_count)"
            ),
        },
    )
    db.execute(stmt)
    return len(payload)


def bounds_for_children(
    db: Session, system_id: int, parent_run_id: int,
    parent_end_time: Optional[datetime] = None, *, slack_hours: float = 24,
) -> Optional[Tuple[int, int]]:
    """Alt görev / restart için (id_min, id_max).

    Alt sınır = üst çalışmanın AH_Idnr (sonra aktive edilir).
    Üst sınır = bitiş+pay saatlerindeki eşleme max; hâlâ çalışıyorsa eşlemedeki en güncel AH_Idnr.
    """
    id_min = int(parent_run_id)
    if parent_end_time is not None:
        if parent_end_time.tzinfo is None:
            parent_end_time = parent_end_time.replace(tzinfo=timezone.utc)
        t_to = parent_end_time + timedelta(hours=float(slack_hours))
        b = bounds_for_time_range(db, system_id, parent_end_time, t_to, slack_hours=0)
        if b and b[1] > id_min:
            return id_min, b[1]
    gb = global_bounds(db, system_id)
    if gb and gb[1] > id_min:
        return id_min, gb[1]
    # eşleme yok / üst sınır belirsiz — yine de PK alt sınırı ile dar aralık istemeyiz
    return None
