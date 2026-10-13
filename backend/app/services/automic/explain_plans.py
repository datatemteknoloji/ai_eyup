"""Kaynak SQL şablonları için plan kontrolü (salt okunur).

Yöntem: şablonu temkinli küçük aralıkla bir kez SELECT ile çalıştır →
oturumun prev_sql_id'si üzerinden V$SQL_PLAN oku.
Yazma gerektiren plan araçları kullanılmaz — sql_guard + READ ONLY oturumdan geçer.

  python -m app.services.automic.explain_plans --system-id 1

Planda TABLE ACCESS FULL veya INDEX FAST FULL SCAN → şablon "riskli".
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RISKY = re.compile(
    r"TABLE ACCESS\s+FULL|INDEX\s+FAST\s+FULL\s+SCAN",
    re.IGNORECASE,
)

# Temkinli örnek bind — dar aralık / düşük limit
_SAMPLE = {
    "ended_executions": {"clients_bind": ":c0", "limit": 5, "binds": {"c0": 100, "id_min": 1, "id_max": 50}},
    "latest_run_id": {"limit": 1, "binds": {"client": 100}},
    # client filtresi yok — beklenen plan: INDEX FULL SCAN (MIN/MAX)
    "min_run_id": {"limit": 1, "binds": {}},
    "count_ended_by_id_range": {
        "clients_bind": ":c0", "limit": 1,
        "binds": {"c0": 100, "id_min": 1, "id_max": 50},
    },
    "execution_by_id": {"fields": True, "limit": 1, "binds": {"client": 100, "run_id": 1}},
    "children": {"fields": True, "limit": 5,
                 "binds": {"client": 100, "run_id": 1, "id_min": 1, "id_max": 50}},
    "restarts": {"fields": True, "limit": 5,
                 "binds": {"client": 100, "run_id": 1, "ref_id": 1, "id_min": 1, "id_max": 50}},
    "active_executions": {"clients_bind": ":c0", "limit": 5, "binds": {"c0": 100}},
    "report_types_rh": {"limit": 5, "binds": {"run_id": 1}},
    "report_types_rt": {"limit": 5, "binds": {"run_id": 1}},
    "report_count": {"limit": 1, "binds": {"run_id": 1, "rtype": "REP"}},
    "report_range": {"fields": True, "limit": 5,
                     "binds": {"run_id": 1, "rtype": "REP", "head_to": 5, "tail_from": 0}},
    "object_header_by_name": {"fields": True, "limit": 1, "binds": {"client": 100, "name": "JOBS.X"}},
    "object_headers_by_id_range": {"clients_bind": ":c0", "fields": True, "limit": 5,
                                  "binds": {"c0": 100, "id_min": 1, "id_max": 50}},
    "object_names_by_ids": {"ids_bind": ":i0", "fields": True, "limit": 5, "binds": {"i0": 1}},
    "folder_links_by_objects": {"ids_bind": ":i0", "limit": 5, "binds": {"i0": 1}},
    "object_script_lines": {"limit": 5, "binds": {"object_id": 1}},
    "usage_children": {"limit": 5, "binds": {"parent_id": 1}},
    "usage_by_parent_id_range": {"limit": 5, "binds": {"id_min": 1, "id_max": 50}},
    "table_row_count": {"limit": 1, "binds": {}},
    "hosts_all": {"fields": True, "limit": 5, "binds": {}},
    "mqsrv_all": {"fields": True, "limit": 5, "binds": {}},
    "ohg_all": {"fields": True, "limit": 5, "binds": {}},
    "ohgf_all": {"fields": True, "limit": 5, "binds": {}},
}


def _logical_for(query: str) -> str:
    if query.startswith("report_"):
        return "report_headers" if query.endswith("_rh") else "report_text"
    if query.startswith("object_script"):
        return "object_scripts"
    if query.startswith("object_") or query == "folder_links_by_objects":
        return "folders" if "folder" in query else "object_headers"
    if query.startswith("usage_"):
        return "object_usage"
    if query == "active_executions":
        return "active"
    if query in ("hosts_all", "table_row_count"):
        return "hosts"
    if query == "mqsrv_all":
        return "mqsrv"
    if query == "ohg_all":
        return "agent_groups"
    if query == "ohgf_all":
        return "agent_group_filters"
    return "executions"


def explain_system(system_id: int) -> Dict[str, Any]:
    from app.models.automic import AutomicSystem
    from app.services.automic.database import get_automic_thread_session
    from app.services.automic.source import templates
    from app.services.automic.source.base import (
        EXECUTION_FIELDS, HOST_FIELDS, MQSRV_FIELDS, OBJECT_HEADER_FIELDS,
        OHG_FIELDS, OHGF_FIELDS, SourceError,
    )
    from app.services.automic.source.factory import build_source
    from app.services.automic.small_tables import risk_report_entries

    db = get_automic_thread_session()
    if db is None:
        return {"ok": False, "error": "Automic modül DB yok"}
    try:
        system = db.get(AutomicSystem, system_id)
        if not system:
            return {"ok": False, "error": "Sistem bulunamadı"}
        results: List[Dict[str, Any]] = []
        with build_source(system) as src:
            if not hasattr(src, "_profile") or not hasattr(src, "_query"):
                return {"ok": False, "error": "Oracle dışı kaynak — plan kontrolü yok"}
            prof = src._profile
            mapping = src._mapping or {}
            for qname, _spec in (prof.get("queries") or {}).items():
                sample = _SAMPLE.get(qname) or {"limit": 5, "binds": {}}
                logical = _logical_for(qname)
                tmap = mapping.get(logical) or {}
                if not tmap.get("available"):
                    results.append({"query": qname, "status": "skipped", "reason": f"{logical} unavailable"})
                    continue
                try:
                    fields = None
                    if sample.get("fields"):
                        if logical == "hosts":
                            fields = list(HOST_FIELDS)
                        elif logical == "mqsrv":
                            fields = list(MQSRV_FIELDS)
                        elif logical == "agent_groups":
                            fields = list(OHG_FIELDS)
                        elif logical == "agent_group_filters":
                            fields = list(OHGF_FIELDS)
                        elif "object" in logical:
                            fields = list(OBJECT_HEADER_FIELDS)
                        else:
                            fields = list(EXECUTION_FIELDS)
                    sql = templates.render(
                        prof, qname, schema=src._schema, table_map=tmap,
                        fields=fields, clients_bind=sample.get("clients_bind"),
                        ids_bind=sample.get("ids_bind"), limit=min(5, int(sample.get("limit") or 5)),
                    )
                except Exception as exc:
                    results.append({"query": qname, "status": "render_error", "error": str(exc)})
                    continue
                entry: Dict[str, Any] = {
                    "query": qname, "sql": sql[:500], "status": "ok", "risky": False, "plan": "",
                }
                try:
                    plan_text = _plan_via_vsql(src, sql, sample.get("binds") or {}, qname)
                    entry["plan"] = plan_text
                    if _RISKY.search(plan_text or ""):
                        entry["risky"] = True
                        entry["status"] = "riskli"
                except SourceError as exc:
                    entry["status"] = "plan_failed"
                    entry["error"] = str(exc)
                    entry["note"] = (
                        "V$SQL / V$SQL_PLAN SELECT yetkisi veya oturum sql_id bulunamadı. "
                        "DBA: automic-source-dba-grants.md (V_$SQL, V_$SQL_PLAN)."
                    )
                results.append(entry)
        risky = [r for r in results if r.get("risky")]
        from app.services.automic.defaults import effective_settings
        return {
            "ok": True, "system_id": system_id, "system": system.name,
            "at": datetime.now(timezone.utc).isoformat(),
            "method": "probe_select_then_v$sql_plan",
            "templates": results, "risky_count": len(risky),
            "risky": [r["query"] for r in risky],
            "small_ref_tables": risk_report_entries(effective_settings(system.settings)),
        }
    finally:
        db.close()


def _plan_via_vsql(src, sql: str, binds: Dict[str, Any], query_name: str) -> str:
    """Probe SELECT → aynı oturumda prev_sql_id → V$SQL_PLAN (hepsi sql_guard + READ ONLY)."""
    from app.services.automic.source.base import SourceError
    from app.services.automic.source.sql_guard import UnsafeSqlError, assert_read_only

    sql_prev = (
        "SELECT prev_sql_id, prev_child_number FROM v$session "
        "WHERE sid = SYS_CONTEXT('USERENV', 'SID') FETCH FIRST 1 ROWS ONLY"
    )
    sql_plan = (
        "SELECT id, operation, options, object_name, cost, cardinality "
        "FROM v$sql_plan WHERE sql_id = :sql_id AND child_number = :ch "
        "ORDER BY id FETCH FIRST 200 ROWS ONLY"
    )
    sql_plan_any = (
        "SELECT id, operation, options, object_name, cost, cardinality "
        "FROM v$sql_plan WHERE sql_id = :sql_id "
        "ORDER BY id FETCH FIRST 200 ROWS ONLY"
    )
    try:
        assert_read_only(sql)
        assert_read_only(sql_prev)
        assert_read_only(sql_plan)
        assert_read_only(sql_plan_any)
    except UnsafeSqlError as exc:
        raise SourceError(f"Plan SQL guard: {exc}", code="plan_failed", retryable=False) from exc

    conn = src._connect()
    src._ensure_read_only(conn)
    conn.call_timeout = src._timeout_ms("chat")
    with conn.cursor() as cur:
        try:
            cur.execute(sql, binds or {})
            cur.fetchmany(5)
        except Exception as exc:
            # Boş sonuç / ORA-… — yine de sql_id yakalamayı dene
            note_error("explain_plans._plan_via_vsql", exc)
        cur.execute(sql_prev)
        row = cur.fetchone()
        if not row or not row[0]:
            raise SourceError(
                "prev_sql_id alınamadı (V$SESSION yetkisi?).",
                code="plan_failed", retryable=False,
            )
        sql_id, child = str(row[0]), int(row[1] or 0)
        cur.execute(sql_plan, {"sql_id": sql_id, "ch": child})
        plan_rows = cur.fetchmany(200)
        if not plan_rows:
            cur.execute(sql_plan_any, {"sql_id": sql_id})
            plan_rows = cur.fetchmany(200)
    if not plan_rows:
        raise SourceError(
            f"V$SQL_PLAN boş (sql_id={sql_id}). GRANT SELECT ON SYS.V_$SQL_PLAN gerekir.",
            code="plan_failed", retryable=False,
        )
    lines = []
    for prow in plan_rows:
        _id, op, opt, obj, cost, card = (list(prow) + [None] * 6)[:6]
        lines.append(f"{_id} {op or ''} {opt or ''} {obj or ''} cost={cost} card={card}".strip())
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Automic kaynak şablon plan kontrolü (V$SQL_PLAN)")
    p.add_argument("--system-id", type=int, required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    out = explain_system(args.system_id)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        if not out.get("ok"):
            print("HATA:", out.get("error"), file=sys.stderr)
            return 1
        print(f"Sistem {out['system']} — {out['risky_count']} riskli şablon ({out.get('method')})")
        for t in out.get("templates") or []:
            flag = "RISKLI" if t.get("risky") else t.get("status")
            print(f"  [{flag}] {t.get('query')}")
            if t.get("error"):
                print(f"    {t['error']}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
