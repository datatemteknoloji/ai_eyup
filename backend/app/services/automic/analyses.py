"""Asenkron uzun Automic analizleri — bulk_job_tracker ile poll."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services import bulk_job_tracker as bjt

logger = logging.getLogger(__name__)

KINDS = {
    "failure_pack": "Hata paketi (çok günlük)",
    "overnight_review": "Gece vardiyası özeti",
    "impact_analysis": "Etki analizi (nesne/agent)",
}


def start_analysis(system_id: int, kind: str, *, range_: str = "7d",
                   object_name: Optional[str] = None, agent: Optional[str] = None,
                   clients: Optional[List[int]] = None) -> Dict[str, Any]:
    if kind not in KINDS:
        return {"ok": False, "error": f"Bilinmeyen analiz: {kind}", "kinds": list(KINDS)}
    title = f"Automic · {KINDS[kind]}"
    if object_name:
        title += f" · {object_name}"
    jid = bjt.create_job(f"automic_{kind}", title, total=4, message="Metrikler toplanıyor…")
    t = threading.Thread(
        target=_run, args=(jid, system_id, kind, range_, object_name, agent, clients),
        name=f"automic-analysis-{jid}", daemon=True,
    )
    t.start()
    return {"ok": True, "job_id": jid, "kind": kind, "title": title}


def get_analysis(job_id: str) -> Optional[Dict[str, Any]]:
    return bjt.get_job(job_id)


def list_analyses(*, active_only: bool = False) -> List[Dict[str, Any]]:
    jobs = bjt.list_jobs(active_only=active_only)
    return [j for j in jobs if str(j.get("kind") or "").startswith("automic_")]


def _run(job_id: str, system_id: int, kind: str, range_: str,
         object_name: Optional[str], agent: Optional[str], clients: Optional[List[int]]) -> None:
    from app.services.automic.database import get_automic_thread_session, ensure_schema
    from app.services.automic.service import resolve_system

    try:
        ensure_schema()
        db = get_automic_thread_session()
        if db is None:
            bjt.finish(job_id, status="error", error="Automic DB yok", message="Başarısız")
            return
        try:
            system = resolve_system(db, system_id)
            if system is None:
                bjt.finish(job_id, status="error", error="Sistem yok", message="Başarısız")
                return
            bjt.tick(job_id, done=1, message="Veri sorgulanıyor…")
            if bjt.is_cancelled(job_id):
                bjt.finish(job_id, status="cancelled", message="İptal edildi")
                return

            from . import queries as q
            from .insight import build_metrics_blob, generate_insight

            pack: Dict[str, Any] = {"kind": kind, "system": system.name, "range": range_}
            if kind == "failure_pack":
                top = q.run_history(db, system, "top_failed_objects",
                                    {"range": range_, "limit": 20, "client": clients[0] if clients and len(clients) == 1 else None})
                sigs = q.run_history(db, system, "error_signatures", {"range": range_, "limit": 20})
                trend = q.run_history(db, system, "failure_trend", {"range": range_})
                pack["top_failed"] = top.get("rows") or []
                pack["signatures"] = sigs.get("rows") or []
                pack["trend"] = trend.get("rows") or []
                bjt.tick(job_id, done=2, message="AI özeti…")
                insight = generate_insight(db, system, range_=range_, clients=clients, force=True)
                pack["insight_markdown"] = insight.get("markdown")
            elif kind == "overnight_review":
                tonight = q.expected_tonight(db, system, clients=clients)
                active = q.active_executions(db, system, clients=clients, limit=100)
                pack["expected_tonight"] = tonight
                pack["active"] = {"total": active.get("total"), "over_p95_count": active.get("over_p95_count"),
                                  "by_state": {}}
                items = active.get("items") or []
                for i in items:
                    st = i.get("state") or "other"
                    pack["active"]["by_state"][st] = pack["active"]["by_state"].get(st, 0) + 1
                bjt.tick(job_id, done=2, message="AI özeti…")
                metrics = build_metrics_blob(db, system, range_="24h", clients=clients)
                metrics["expected_tonight_count"] = len((tonight.get("items") or []))
                insight = generate_insight(db, system, range_="24h", clients=clients, force=True)
                pack["insight_markdown"] = insight.get("markdown")
            else:  # impact_analysis
                if not object_name and not agent:
                    bjt.finish(job_id, status="error", error="object_name veya agent gerekli",
                               message="Başarısız")
                    return
                if object_name:
                    pack["object"] = q.object_summary(db, system, object_name,
                                                     client=clients[0] if clients and len(clients) == 1 else None,
                                                     days=30)
                    try:
                        from .objects import object_usage
                        cl = pack["object"].get("client") or (system.clients or [None])[0]
                        if cl is not None:
                            pack["usage"] = object_usage(db, system, int(cl), object_name)
                    except Exception as exc:
                        pack["usage"] = {"ok": False, "error": str(exc)}
                if agent:
                    pack["agent"] = q.agent_summary(db, system, agent, range_=range_, clients=clients)
                bjt.tick(job_id, done=2, message="AI özeti…")
                insight = generate_insight(db, system, range_=range_, clients=clients, force=True)
                pack["insight_markdown"] = insight.get("markdown")

            bjt.tick(job_id, done=3, message="Sonuç paketleniyor…")
            pack["generated_at"] = datetime.now(timezone.utc).isoformat()
            bjt.finish(job_id, status="done", message="Tamamlandı", result=pack)
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Automic analiz %s", job_id)
        bjt.finish(job_id, status="error", error=str(exc), message="Hata")
