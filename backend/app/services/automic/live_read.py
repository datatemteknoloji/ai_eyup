"""Canlı kaynak okuma politikası — collector dışı tüm okumaların tek kontrol noktası.

Modlar: off (varsayılan) | windows_only | always
Yalnız risk sınıfı 'düşük' şablonlar canlı çalışabilir.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.models.automic import AutomicCollectorState, AutomicSystem

from . import guard
from .defaults import effective_settings
from .schedule import collection_allowed
from .source.base import SourceError
from .source.factory import build_source

logger = logging.getLogger(__name__)

# Risk raporu (rev 4) — canlıda yalnız "düşük"
LIVE_ALLOWED_TEMPLATES: Set[str] = {
    "execution_by_id",
    "children",
    "restarts",
    "report_types_rh",
    "report_count",
    "report_range",
    "object_script_lines",
    "object_names_by_ids",
    "usage_children",
    # ended_* / usage_by_parent_id_range / object_headers_by_id_range → collector
}

# Kaynak method → zorunlu şablon(lar); hepsi LIVE_ALLOWED olmalı
FN_TEMPLATES: Dict[str, Tuple[str, ...]] = {
    "fetch_execution": ("execution_by_id",),
    "fetch_children": ("children",),
    "fetch_restarts": ("restarts",),
    "list_reports": ("report_types_rh",),  # RT tipi orta risk → canlı yasak
    "fetch_report": ("report_count", "report_range"),
    "fetch_object_script": ("object_script_lines",),
    # Orta/yüksek — kapı reddeder
    "fetch_object_header": ("object_header_by_name",),
    "fetch_active_executions": ("active_executions",),
    "fetch_object_headers": ("object_headers_by_id_range",),
    "fetch_jpp_by_parent_range": ("usage_by_parent_id_range",),
}

_MODES = frozenset({"off", "windows_only", "always"})

_local_lock = threading.Lock()
_local_budget: Dict[str, Deque[float]] = defaultdict(deque)
_local_durations: Dict[int, Deque[float]] = defaultdict(lambda: deque(maxlen=500))
_local_counters: Dict[str, int] = defaultdict(int)


@dataclass
class LiveReadDecision:
    allowed: bool
    reason: str  # ok | policy_off | allow_live_false | outside_window | budget_global | budget_user | template_risk | unknown_fn
    mode: str
    templates: Tuple[str, ...] = ()
    as_of: Optional[str] = None
    message: str = ""


@dataclass
class LiveReadResult:
    ok: bool
    data: Any = None
    data_source: str = "module_db"  # module_db | source_live | denied
    decision: Optional[LiveReadDecision] = None
    elapsed_sec: Optional[float] = None
    row_count: Optional[int] = None
    error: Optional[str] = None
    code: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def live_read_mode(settings: Dict[str, Any]) -> str:
    g = (settings or {}).get("source_guard") or {}
    m = str(g.get("live_read_mode") or "off").strip().lower()
    return m if m in _MODES else "off"


def data_as_of(db: Session, system_id: int) -> Optional[str]:
    st = db.get(AutomicCollectorState, system_id)
    if not st:
        return None
    t = st.active_snapshot_at or st.last_success_at or st.last_run_at
    return t.isoformat() if t else None


def _templates_for(fn_name: str, explicit: Optional[Sequence[str]] = None) -> Tuple[str, ...]:
    if explicit:
        return tuple(explicit)
    return FN_TEMPLATES.get(fn_name, ())


def evaluate(
    system: AutomicSystem,
    fn_name: str,
    *,
    allow_live: Optional[bool] = None,
    user_id: Optional[int] = None,
    templates: Optional[Sequence[str]] = None,
    db: Optional[Session] = None,
) -> LiveReadDecision:
    """allow_live: None=politika varsayılanı; False=asla; True=yalnız politika izin veriyorsa."""
    settings = effective_settings(system.settings)
    mode = live_read_mode(settings)
    tmpls = _templates_for(fn_name, templates)
    as_of = data_as_of(db, system.id) if db is not None else None

    if allow_live is False:
        return LiveReadDecision(
            False, "allow_live_false", mode, tmpls, as_of,
            f"allow_live=false — canlı okuma yapılmadı; veriler {as_of or 'son toplama'} itibarıyla (modül DB).",
        )

    if not tmpls:
        return LiveReadDecision(
            False, "unknown_fn", mode, tmpls, as_of,
            f"Bilinmeyen canlı okuma hedefi '{fn_name}' — reddedildi.",
        )

    risky = [t for t in tmpls if t not in LIVE_ALLOWED_TEMPLATES]
    if risky:
        return LiveReadDecision(
            False, "template_risk", mode, tmpls, as_of,
            f"Şablon(lar) canlı okumada yasak (risk ≠ düşük): {', '.join(risky)}.",
        )

    if mode == "off":
        if allow_live is True:
            return LiveReadDecision(
                False, "policy_off", mode, tmpls, as_of,
                f"Politika gereği canlı okuma kapalı (off); veriler {as_of or 'son toplama'} itibarıyla.",
            )
        return LiveReadDecision(
            False, "policy_off", mode, tmpls, as_of,
            f"Canlı okuma kapalı (off); veriler {as_of or 'son toplama'} itibarıyla.",
        )

    if mode == "windows_only" and not collection_allowed(settings.get("collection") or {}):
        return LiveReadDecision(
            False, "outside_window", mode, tmpls, as_of,
            f"Canlı okuma yalnız toplama penceresinde; şu an kapalı. Veriler {as_of or 'son toplama'} itibarıyla.",
        )

    # allow_live True veya None (politika açık) → bütçe
    g = settings.get("source_guard") or {}
    global_lim = int(g.get("live_budget_per_min") or 10)
    user_lim = int(g.get("live_budget_per_user_per_min") or 3)
    ok_g, ok_u = _budget_check(system.id, user_id, global_lim, user_lim, consume=False)
    if not ok_g:
        return LiveReadDecision(
            False, "budget_global", mode, tmpls, as_of,
            f"Canlı okuma bütçesi aşıldı (global {global_lim}/dk); modül DB kullanıldı. "
            f"Veriler {as_of or 'son toplama'} itibarıyla.",
        )
    if user_id is not None and not ok_u:
        return LiveReadDecision(
            False, "budget_user", mode, tmpls, as_of,
            f"Canlı okuma bütçesi aşıldı (kullanıcı {user_lim}/dk); modül DB kullanıldı. "
            f"Veriler {as_of or 'son toplama'} itibarıyla.",
        )

    return LiveReadDecision(True, "ok", mode, tmpls, as_of, "Canlı okuma izinli.")


def _budget_keys(system_id: int, user_id: Optional[int]) -> Tuple[str, Optional[str]]:
    minute = int(time.time()) // 60
    gkey = f"automic:live:budget:{system_id}:{minute}"
    ukey = f"automic:live:budget:{system_id}:u{user_id}:{minute}" if user_id is not None else None
    return gkey, ukey


def _budget_check(system_id: int, user_id: Optional[int], global_lim: int, user_lim: int,
                  *, consume: bool) -> Tuple[bool, bool]:
    now = time.time()
    gkey, ukey = _budget_keys(system_id, user_id)
    r = get_redis()
    if r is not None:
        try:
            gn = int(r.get(gkey) or 0)
            un = int(r.get(ukey) or 0) if ukey else 0
            ok_g, ok_u = gn < global_lim, (user_id is None or un < user_lim)
            if consume and ok_g and ok_u:
                pipe = r.pipeline()
                pipe.incr(gkey)
                pipe.expire(gkey, 120)
                if ukey:
                    pipe.incr(ukey)
                    pipe.expire(ukey, 120)
                pipe.execute()
            return ok_g, ok_u
        except Exception as _e:
            note_error("live_read._budget_check", _e)
    with _local_lock:
        gq = _local_budget[gkey]
        while gq and gq[0] < now - 60:
            gq.popleft()
        uq = _local_budget[ukey] if ukey else None
        if uq is not None:
            while uq and uq[0] < now - 60:
                uq.popleft()
        ok_g = len(gq) < global_lim
        ok_u = uq is None or len(uq) < user_lim
        if consume and ok_g and ok_u:
            gq.append(now)
            if uq is not None:
                uq.append(now)
        return ok_g, ok_u


def _record_metrics(system_id: int, *, elapsed: float, denied_reason: Optional[str],
                    allowed: bool) -> None:
    r = get_redis()
    minute = int(time.time()) // 60
    if r is not None:
        try:
            if allowed:
                rk = f"automic:live:ok:{system_id}:{minute}"
                r.incr(rk)
                r.expire(rk, 3600)
                dk = f"automic:live:dur:{system_id}"
                r.lpush(dk, f"{elapsed:.4f}")
                r.ltrim(dk, 0, 499)
                r.expire(dk, 86400)
            elif denied_reason:
                rk = f"automic:live:deny:{system_id}:{denied_reason}:{minute}"
                r.incr(rk)
                r.expire(rk, 3600)
                if denied_reason.startswith("budget"):
                    r.incr(f"automic:live:budget_exceed:{system_id}:{minute}")
                    r.expire(f"automic:live:budget_exceed:{system_id}:{minute}", 3600)
            return
        except Exception as _e:
            note_error("live_read._record_metrics", _e)
    with _local_lock:
        if allowed:
            _local_counters[f"ok:{system_id}"] += 1
            _local_durations[system_id].append(elapsed)
        elif denied_reason:
            _local_counters[f"deny:{system_id}:{denied_reason}"] += 1


def _audit_live(system: AutomicSystem, *, user_id: Optional[int], tool: Optional[str],
                fn_name: str, templates: Sequence[str], elapsed: float, row_count: Optional[int],
                decision: LiveReadDecision) -> None:
    try:
        from app.core.database import SessionLocal
        from app.services.audit import record_audit
        db = SessionLocal()
        try:
            actor = None
            if user_id is not None:
                from app.models.user import User
                actor = db.get(User, int(user_id))
            record_audit(
                db, category="automic", action="live_read",
                status="success" if decision.reason == "ok" else "denied",
                actor=actor, summary=f"Automic canlı okuma: {fn_name}",
                target_type="automic_system", target_id=system.id,
                detail={
                    "tool": tool, "fn": fn_name, "templates": list(templates),
                    "reason": decision.reason, "mode": decision.mode,
                    "elapsed_sec": round(elapsed, 3), "row_count": row_count,
                    "as_of": decision.as_of, "user_id": user_id,
                },
            )
        finally:
            db.close()
    except Exception as exc:
        note_error("live_read._audit_live", exc)


def _row_count(data: Any) -> Optional[int]:
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("items", "lines", "rows", "nodes"):
            if isinstance(data.get(k), list):
                return len(data[k])
        return 1
    if hasattr(data, "lines"):
        return len(getattr(data, "lines") or [])
    return 1


def call(
    db: Session,
    system: AutomicSystem,
    fn_name: str,
    *args: Any,
    allow_live: Optional[bool] = None,
    user_id: Optional[int] = None,
    tool: Optional[str] = None,
    templates: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> LiveReadResult:
    """Tek merkezi kapı: politika + risk + bütçe → kaynak çağrısı → audit/metrik."""
    decision = evaluate(
        system, fn_name, allow_live=allow_live, user_id=user_id, templates=templates, db=db,
    )
    if not decision.allowed:
        _record_metrics(system.id, elapsed=0.0, denied_reason=decision.reason, allowed=False)
        _audit_live(system, user_id=user_id, tool=tool, fn_name=fn_name,
                    templates=decision.templates, elapsed=0.0, row_count=None, decision=decision)
        return LiveReadResult(
            ok=False, data_source="denied", decision=decision,
            error=decision.message, code=decision.reason,
            meta={"as_of": decision.as_of, "live_read_mode": decision.mode},
        )

    settings = effective_settings(system.settings)
    g = settings["source_guard"]
    global_lim = int(g.get("live_budget_per_min") or 10)
    user_lim = int(g.get("live_budget_per_user_per_min") or 3)
    _budget_check(system.id, user_id, global_lim, user_lim, consume=True)

    t0 = time.monotonic()
    try:
        with guard.source_slot(system.id, max_sessions=int(g.get("max_sessions") or 2), wait_sec=5):
            with build_source(system) as src:
                src.settings = {
                    **src.settings,
                    "source_guard": {**g, "collector_timeout_sec": g.get("chat_timeout_sec")},
                }
                fn = getattr(src, fn_name)
                data = fn(*args, **kwargs)
        elapsed = time.monotonic() - t0
        rc = _row_count(data)
        guard.record_success(system.id)
        _record_metrics(system.id, elapsed=elapsed, denied_reason=None, allowed=True)
        _audit_live(system, user_id=user_id, tool=tool, fn_name=fn_name,
                    templates=decision.templates, elapsed=elapsed, row_count=rc, decision=decision)
        logger.info(
            "automic_live_read system=%s fn=%s templates=%s elapsed=%.3f rows=%s user=%s tool=%s",
            system.id, fn_name, decision.templates, elapsed, rc, user_id, tool,
        )
        return LiveReadResult(
            ok=True, data=data, data_source="source_live", decision=decision,
            elapsed_sec=elapsed, row_count=rc,
            meta={"as_of": decision.as_of, "live_read_mode": decision.mode},
        )
    except SourceError as exc:
        elapsed = time.monotonic() - t0
        guard.record_failure(
            system.id, threshold=int(g.get("circuit_failures") or 3),
            open_sec=int(g.get("circuit_open_sec") or 300),
        )
        _record_metrics(system.id, elapsed=elapsed, denied_reason="source_error", allowed=False)
        return LiveReadResult(
            ok=False, data_source="denied", decision=decision, elapsed_sec=elapsed,
            error=str(exc), code=getattr(exc, "code", None),
            meta={"as_of": decision.as_of, "live_read_mode": decision.mode},
        )


def metrics_snapshot(system_id: int) -> Dict[str, Any]:
    """Health/monitoring için canlı okuma özeti (son ~60 dk + süre dağılımı)."""
    minute = int(time.time()) // 60
    ok_n = deny_n = budget_n = 0
    durations: List[float] = []
    deny_by: Dict[str, int] = {}
    r = get_redis()
    if r is not None:
        try:
            for m in range(minute - 59, minute + 1):
                ok_n += int(r.get(f"automic:live:ok:{system_id}:{m}") or 0)
                budget_n += int(r.get(f"automic:live:budget_exceed:{system_id}:{m}") or 0)
                for reason in ("policy_off", "allow_live_false", "outside_window", "budget_global",
                               "budget_user", "template_risk", "source_error", "unknown_fn"):
                    v = int(r.get(f"automic:live:deny:{system_id}:{reason}:{m}") or 0)
                    if v:
                        deny_by[reason] = deny_by.get(reason, 0) + v
                        deny_n += v
            raw = r.lrange(f"automic:live:dur:{system_id}", 0, 499) or []
            durations = [float(x) for x in raw]
        except Exception as _e:
            note_error("live_read.metrics_snapshot", _e)
    if not durations and not ok_n:
        with _local_lock:
            ok_n = _local_counters.get(f"ok:{system_id}", 0)
            durations = list(_local_durations.get(system_id) or [])
            for k, v in _local_counters.items():
                if k.startswith(f"deny:{system_id}:"):
                    reason = k.split(":", 2)[-1]
                    deny_by[reason] = deny_by.get(reason, 0) + v
                    deny_n += v
                    if reason.startswith("budget"):
                        budget_n += v
    durations.sort()
    p50 = p95 = None
    if durations:
        p50 = durations[int(0.50 * (len(durations) - 1))]
        p95 = durations[int(0.95 * (len(durations) - 1))]
    return {
        "live_reads_ok_60m": ok_n,
        "live_reads_denied_60m": deny_n,
        "live_budget_exceed_60m": budget_n,
        "live_deny_by_reason": deny_by,
        "live_duration_p50_sec": round(p50, 3) if p50 is not None else None,
        "live_duration_p95_sec": round(p95, 3) if p95 is not None else None,
        "live_duration_samples": len(durations),
    }


def transparency(data_source: str, as_of: Optional[str], *, note: Optional[str] = None) -> Dict[str, Any]:
    return {
        "data_source": data_source,
        "as_of": as_of,
        "freshness_note": note,
    }
