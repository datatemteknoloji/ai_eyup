"""Sistem yönetimi yardımcıları: keşif, durum, varsayılan sistem, prompt bağlamı."""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.automic import AutomicCollectorState, AutomicSystem

from . import guard
from .classify import failed_rule_text
from .defaults import effective_settings
from .source.base import SourceError
from .source.factory import build_source, fake_mode_enabled

logger = logging.getLogger(__name__)


def list_systems(db: Session, *, enabled_only: bool = False) -> List[AutomicSystem]:
    q = db.query(AutomicSystem)
    if enabled_only:
        q = q.filter(AutomicSystem.enabled.is_(True))
    return q.order_by(AutomicSystem.is_default.desc(), AutomicSystem.name).all()


def resolve_system(db: Session, system: Optional[Any]) -> Optional[AutomicSystem]:
    """id, ad veya None (varsayılan) → AutomicSystem."""
    if system not in (None, ""):
        try:
            s = db.get(AutomicSystem, int(system))
            if s:
                return s
        except (TypeError, ValueError) as _e:
            note_error("service.resolve_system", _e)
        s = db.query(AutomicSystem).filter(AutomicSystem.name.ilike(str(system))).first()
        if s:
            return s
        return None
    systems = list_systems(db, enabled_only=True)
    return systems[0] if systems else None


def run_discovery(db: Session, system: AutomicSystem) -> Dict[str, Any]:
    with build_source(system) as src:
        cap = src.discover()
    system.capability = cap
    system.capability_at = datetime.now(timezone.utc)
    # AE ürün sürümü kaynak tablodan otomatik okunmaz — kurulumda elle girilir
    db.commit()
    # OH başlık senkronu (yetenek varsa; hata keşfi bozmaz)
    try:
        feats = (cap.get("features") or {})
        if feats.get("objects") and feats.get("objects") != "unavailable":
            from .objects import sync_object_headers
            sync_object_headers(db, system, limit=5000)
    except Exception as exc:
        logger.info("Automic OH sync [%s]: %s", system.name, exc)
    return cap


def _profile_outdated(system: AutomicSystem) -> bool:
    """Kayıtlı keşif eski SQL profil sürümüyle yapıldıysa (kolon eşlemesi değişti) yeniden keşif gerekir."""
    if system.source_type != "db_oracle":
        return False
    cap = system.capability or {}
    try:
        from .source import templates
        cur = templates.load_profile("oracle", cap.get("profile") or "ae-24").get("rev")
    except Exception as _exc:
        note_error("service.silent_72", _exc)
        return False
    return bool(cur) and cap.get("profile_rev") != cur


def run_daily_discovery(db: Session) -> Dict[int, str]:
    out = {}
    for s in list_systems(db, enabled_only=True):
        if s.capability_at and (datetime.now(timezone.utc) - s.capability_at).total_seconds() < 20 * 3600 \
                and not _profile_outdated(s):
            continue
        try:
            run_discovery(db, s)
            out[s.id] = "ok"
        except SourceError as exc:
            db.rollback()
            out[s.id] = str(exc)
            logger.warning("Automic keşif [%s]: %s", s.name, exc)
    return out


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def system_public(s: AutomicSystem, *, include_capability: bool = False) -> Dict[str, Any]:
    from .source_role import source_info_public

    conn = dict(s.connection or {})
    conn.pop("password", None)
    out = {
        "id": s.id, "name": s.name, "is_default": s.is_default, "enabled": s.enabled,
        "source_type": s.source_type, "connection": conn, "has_secret": bool(s.secret_enc),
        "clients": s.clients or [], "settings": effective_settings(s.settings),
        "capability_at": _iso(s.capability_at),
        "capability_summary": capability_summary(s.capability),
        "source_info": source_info_public(s.settings),
        "created_at": _iso(s.created_at), "updated_at": _iso(s.updated_at),
    }
    if include_capability:
        out["capability"] = s.capability
    return out


def capability_summary(cap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cap:
        return None
    role = cap.get("database_role")
    known = cap.get("role_known")
    if known is None:
        known = role is not None
    return {
        "engine": cap.get("engine"), "db_version": cap.get("db_version"), "driver_mode": cap.get("driver_mode"),
        "schema": cap.get("schema"), "database_role": role,
        "database_role_display": role if known and role else "bilinmiyor",
        "open_mode": cap.get("open_mode"),
        "timestamps": cap.get("timestamps"), "features": cap.get("features"),
        "read_only_ok": (cap.get("privileges") or {}).get("read_only_ok"),
        "warnings": (cap.get("warnings") or []) + (cap.get("index_warnings") or []),
        "clients_seen": cap.get("clients_seen") or [],
    }


def system_status(db: Session, s: AutomicSystem) -> Dict[str, Any]:
    from .source_role import source_info_public

    st = db.get(AutomicCollectorState, s.id)
    settings = effective_settings(s.settings)
    info = source_info_public(s.settings)
    cap_sum = capability_summary(s.capability) or {}
    role_display = (
        (info or {}).get("last_role_display")
        or cap_sum.get("database_role_display")
        or "bilinmiyor"
    )
    from .integrity import data_freshness_fields, ingest_stall_warning

    fresh = data_freshness_fields(db, s.id, st) if st else {
        "last_new_record_at": None, "last_ingest_rows": 0, "zero_ingest_streak": 0, "watermark": None,
    }
    stall = None
    if st:
        # Uyarı metni için hafif src stub (probe yok → watermark/success heuristic)
        stall = ingest_stall_warning(
            db, s.id, st, src=None,
            zero_ticks=int((settings.get("collection") or {}).get("zero_ingest_warn_ticks") or 6),
        )
    return {
        "system_id": s.id, "name": s.name, "enabled": s.enabled,
        "fake": fake_mode_enabled() or s.source_type == "fake",
        "clients": s.clients or [],
        "source_label": f"{s.name} · {(s.connection or {}).get('host') or (s.connection or {}).get('dsn') or s.source_type}",
        "watermark": _iso(st.watermark) if st else None,
        "last_run_at": _iso(st.last_run_at) if st else None,
        "last_success_at": _iso(st.last_success_at) if st else None,
        "next_run_at": _iso(st.next_run_at) if st else None,
        "last_error": st.last_error if st else None,
        "last_rows": st.last_rows if st else 0,
        "last_duration_sec": st.last_duration_sec if st else None,
        "source_lag_sec": st.source_lag_sec if st else None,
        "source_lag_method": st.source_lag_method if st else None,
        "active_snapshot_at": _iso(st.active_snapshot_at) if st else None,
        "ingest_paused_reason": st.ingest_paused_reason if st else None,
        "backfill_done": st.backfill_done if st else None,
        "circuit_open_sec": guard.circuit_open_remaining(s.id),
        "interval_min": settings["collection"]["interval_min"],
        "failed_rule": failed_rule_text(settings["status_classes"]),
        "capability_at": _iso(s.capability_at),
        "features": (s.capability or {}).get("features") or {},
        "source_info": info,
        "database_role": (info or {}).get("last_database_role") or (s.capability or {}).get("database_role"),
        "database_role_display": role_display,
        "role_drift": bool((info or {}).get("role_drift")),
        "role_drift_message": (info or {}).get("role_drift_message"),
        "live_read_mode": (settings.get("source_guard") or {}).get("live_read_mode") or "off",
        "live_read_metrics": _live_metrics(s.id),
        "last_new_record_at": fresh.get("last_new_record_at"),
        "last_ingest_rows": fresh.get("last_ingest_rows"),
        "zero_ingest_streak": fresh.get("zero_ingest_streak"),
        "ingest_stall_warning": stall,
        **_health_extras(db, s, st, settings),
    }


def _health_extras(db: Session, s: AutomicSystem, st: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Health: rapor kapsamı (hatalı çalışmaların yüzde kaçında rapor var), adım süreleri/bütçe aşımı, hata sayaçları."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text as _t
    from .errors import error_counters, note_error
    from .queries import report_coverage_for
    from .collector import report_queue_depth
    out: Dict[str, Any] = {"report_coverage": None, "report_queue": None, "step_metrics": None,
                           "step_overruns_24h": None, "error_counters": error_counters()}
    now = datetime.now(timezone.utc)
    try:
        days = int((settings.get("retention") or {}).get("failed_report_excerpts_days") or 90)
        cov = report_coverage_for(
            db, s.id, "system_id = :sid AND status_class = 'failed' AND end_time >= :t0",
            {"sid": s.id, "t0": now - timedelta(days=7)})
        cov.pop("_signatures", None)
        cov["window_days"] = 7
        out["report_coverage"] = cov
        out["report_queue"] = report_queue_depth(db, s.id, now - timedelta(days=days))
    except Exception as exc:
        note_error("service.health.report_coverage", exc)
        try:
            db.rollback()
        except Exception as rexc:
            note_error("service.health.rollback", rexc)
        out["report_coverage"] = {"unavailable": True, "note_tr": "Rapor kapsamı alınamadı (sorgu hatası)."}
    try:
        ss = dict(getattr(st, "step_state", None) or {}) if st else {}
        out["step_metrics"] = {
            "last": ss.get("last") or {}, "overruns_total": ss.get("overruns") or {},
            "runs": ss.get("runs") or 0, "last_at": ss.get("last_at"),
            "cursors": ss.get("cursors") or {},
        }
        rows = db.execute(_t(
            "SELECT k, count(*) FROM automic_collector_runs r, jsonb_each(r.step_metrics) AS e(k, v) "
            "WHERE r.system_id = :sid AND r.started_at >= :t0 AND r.step_metrics IS NOT NULL "
            "AND (e.v->>'overrun')::boolean GROUP BY k"), {"sid": s.id, "t0": now - timedelta(hours=24)}).all()
        out["step_overruns_24h"] = {k: int(c) for k, c in rows}
    except Exception as exc:
        note_error("service.health.step_metrics", exc)
        try:
            db.rollback()
        except Exception as rexc:
            note_error("service.health.rollback", rexc)
    return out


def _live_metrics(system_id: int) -> Dict[str, Any]:
    from .live_read import metrics_snapshot
    return metrics_snapshot(system_id)
