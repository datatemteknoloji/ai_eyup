"""Yanıt kapsamı (sistem, zaman aralığı, kayıt sayısı, kaynak, güncellik) — araç sonuçlarından, deterministik.

LLM'e yazdırılmaz: arayüzdeki "Sorgu detayı" altlığı bu alanları gösterir. Böylece sayı/tarih uydurma
riski olmaz ve yanıt metni teknik ayrıntıyla kalabalıklaşmaz.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DB_SOURCES = {"module_db", "executions", "daily_aggregates", "executions_pattern", "db"}
_LIVE_SOURCES = {"source", "source_live"}


def _iso_min_max(vals: List[str]) -> tuple:
    vals = [v for v in vals if isinstance(v, str) and v]
    return (min(vals), max(vals)) if vals else (None, None)


def _fmt_local(iso: Optional[str], tz_name: str) -> Optional[str]:
    """UTC/offset ISO → kullanıcı TZ'sinde görünen yerel ISO (+offset)."""
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz_name or "Europe/Istanbul")).isoformat(timespec="seconds")
    except Exception:
        return iso


def build_scope(structured: List[Dict[str, Any]], tools_used: Optional[List[str]] = None, *,
                system_name: Optional[str] = None, system_id: Optional[int] = None,
                default_clients: Optional[List[int]] = None,
                status: Optional[Dict[str, Any]] = None, fallback: bool = False,
                tz_name: str = "Europe/Istanbul") -> Dict[str, Any]:
    froms: List[str] = []
    tos: List[str] = []
    clients: Optional[List[int]] = None
    record_count: Optional[int] = None
    sources = set()
    partial = False
    retention_limited = False
    for sr in structured or []:
        res = sr.get("result")
        if not isinstance(res, dict) or res.get("ok") is False:
            continue
        for key in ("from", "window_from"):
            if isinstance(res.get(key), str):
                froms.append(res[key])
        for key in ("to", "window_to"):
            if isinstance(res.get(key), str):
                tos.append(res[key])
        if clients is None and isinstance(res.get("clients"), list) and res["clients"]:
            clients = [int(c) for c in res["clients"] if isinstance(c, (int, float))]
        if record_count is None and isinstance(res.get("total"), int) and (sr.get("tool") or "") in (
                "automic_search_executions", "automic_active"):
            record_count = res["total"]
        ds = res.get("data_source")
        if ds in _LIVE_SOURCES:
            sources.add("source")
        elif ds in _DB_SOURCES or ds is None:
            sources.add("db")
        if res.get("truncated") or res.get("live_error"):
            partial = True
        if ds == "daily_aggregates":
            retention_limited = True
    if sources == {"source"}:
        data_source = "source"
    elif sources == {"db", "source"}:
        data_source = "mixed"
    else:
        data_source = "db"
    t_from, _ = _iso_min_max(froms)
    _, t_to = _iso_min_max(tos)
    # Altbilgi: kullanıcı saat diliminde göster (UTC→yerel kayması olmasın)
    t_from_l = _fmt_local(t_from, tz_name)
    t_to_l = _fmt_local(t_to, tz_name)
    scope: Dict[str, Any] = {
        "system": system_name, "system_id": system_id,
        "clients": clients or list(default_clients or []),
        "time_from": t_from_l or t_from, "time_to": t_to_l or t_to,
        "time_from_utc": t_from, "time_to_utc": t_to,
        "timezone": tz_name,
        "data_source": data_source, "record_count": record_count,
        "partial": partial, "retention_limited": retention_limited,
        "tools": list(dict.fromkeys(tools_used or [])),
    }
    if fallback:
        scope["fallback_tools"] = True
    if status:
        scope["source_lag_sec"] = status.get("source_lag_sec")
        scope["last_collection_at"] = status.get("last_success_at") or status.get("last_run_at")
    return scope


def scope_for_answer(system_id: int, structured: List[Dict[str, Any]], tools_used: Optional[List[str]],
                     *, fallback: bool = False, tz_name: str = "Europe/Istanbul") -> Dict[str, Any]:
    """Kendi modül-DB oturumunu açıp sistem durumunu da ekler (thread executor'da çağrılır)."""
    from . import database as adb_mod
    from .service import resolve_system, system_status

    status = None
    name = None
    clients: List[int] = []
    try:
        adb_mod.ensure_schema()
        adb = adb_mod._session_factory()
        try:
            system = resolve_system(adb, system_id)
            if system is not None:
                name, clients = system.name, list(system.clients or [])
                status = system_status(adb, system)
        finally:
            adb.close()
    except Exception as exc:  # kapsam eksik kalsa da yanıt akışı bozulmasın
        note_error("scope.scope_for_answer", exc)
    return build_scope(structured, tools_used, system_name=name, system_id=system_id,
                       default_clients=clients, status=status, fallback=fallback, tz_name=tz_name)


def stub_meta(scope: Dict[str, Any]) -> Dict[str, Any]:
    """LLM meta bloğu üretmediyse altlık yine görünsün diye asgari meta."""
    return {"intent": "general_info", "severity": "info", "confidence": None, "scope": scope,
            "entities": [], "follow_ups": []}
