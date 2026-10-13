"""Tek seferlik/idempotent bakım: eski şema SAHTE (fake) kayıtların temizliği.

Eski DEV-FAKE üretici child/restart/aktif RunID'lerini ayrı bir ofsetle (7e12/8e12/9e12 tabanlı) üretiyordu; gerçek AE tek artan
sayaç kullanır. Bu kayıtlar RunID eşlemesini ve yeniden okuma aralığını zehirliyordu. YALNIZ `source_type == "fake"` sistemlerde:
run_id ≥ 1e12 olan çalışma/aktif/hata indeksi/rapor/kuyruk satırları silinir, RunID eşlemesi yeniden kurulur, sahte kaynak
yeni şemayla aynı zaman penceresini yeniden üretsin diye `resync` imleci eklenir. Uygulama (gerçek kaynak) verisine dokunmaz.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from .errors import note_error
from .steps import get_step_state

logger = logging.getLogger(__name__)

LEGACY_RUNID_MIN = 1_000_000_000_000


def cleanup_legacy_fake_runids(db: Session, system: Any, state: Any) -> Dict[str, Any]:
    if getattr(system, "source_type", None) != "fake":
        return {}
    sid = system.id
    p = {"sid": sid, "lim": LEGACY_RUNID_MIN}
    n_exec = int(db.execute(text(
        "SELECT count(*) FROM automic_executions WHERE system_id = :sid AND run_id >= :lim"), p).scalar() or 0)
    n_act = int(db.execute(text(
        "SELECT count(*) FROM automic_active WHERE system_id = :sid AND run_id >= :lim"), p).scalar() or 0)
    n_map = int(db.execute(text(
        "SELECT count(*) FROM automic_runid_hour_map WHERE system_id = :sid AND (max_run_id >= :lim OR min_run_id >= :lim)"),
        p).scalar() or 0)
    if not (n_exec or n_act or n_map):
        return {}
    span = db.execute(text(
        "SELECT min(end_time), max(end_time) FROM automic_executions WHERE system_id = :sid AND run_id >= :lim"), p).first()
    out: Dict[str, Any] = {"executions": n_exec, "active": n_act, "runid_map_hours": n_map}
    for tbl in ("automic_executions", "automic_active", "automic_failed_index",
                "automic_report_excerpts", "automic_report_attempts", "automic_report_cache"):
        try:
            db.execute(text(f"DELETE FROM {tbl} WHERE system_id = :sid AND run_id >= :lim"), p)
        except Exception as exc:
            note_error(f"maintenance.cleanup.{tbl}", exc)
            db.rollback()
            return {**out, "error": f"{tbl}: {exc}"}
    db.execute(text("DELETE FROM automic_runid_hour_map WHERE system_id = :sid AND (max_run_id >= :lim OR min_run_id >= :lim)"), p)
    db.commit()
    from . import runid_map
    try:
        out["runid_map_rebuilt"] = runid_map.rebuild_from_executions(db, sid)
        db.commit()
    except Exception as exc:
        note_error("maintenance.runid_map_rebuild", exc)
        db.rollback()
    if span and span[0] is not None:
        # Silinen child/restart satırlarını yeni şemayla yeniden üret: yalnız etkilenen zaman penceresi
        ss = get_step_state(state)
        cur = ss["cursors"]
        start = span[0] - timedelta(minutes=5)
        end = span[1] + timedelta(minutes=5)
        cur["resync"] = {"from": start.isoformat(), "to": end.isoformat(), "cursor": start.isoformat()}
        state.step_state = ss
        db.commit()
        out["resync_window"] = [start.isoformat(), end.isoformat()]
    logger.warning("Automic [%s] eski şema fake RunID kayıtları temizlendi: %s", system.name, out)
    return out
