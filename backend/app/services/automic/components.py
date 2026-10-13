"""Araç sonuçlarından (structured_results) UI bileşenleri — LLM çizmez, backend üretir.

Bileşen tipleri: kpi_row, table, chart, workflow_tree, log_excerpt, notice.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

from typing import Any, Dict, List, Optional

_MAX_ROWS = 200

_EXEC_COLS = [
    {"key": "end_time", "label": "Bitiş", "type": "datetime"},
    {"key": "object_name", "label": "Nesne", "type": "object"},
    {"key": "object_type", "label": "Tip"},
    # Tek Durum sütunu: sınıf metni + kod (StatusBadge); ayrı status_code yok → "1800 1800" tekrarı olmaz
    {"key": "status_class", "label": "Durum", "type": "status"},
    {"key": "duration_sec", "label": "Süre", "type": "duration"},
    {"key": "agent", "label": "Agent", "type": "agent"},
    {"key": "client", "label": "Client"},
    {"key": "run_id", "label": "RunID", "type": "run"},
]


def _exec_table(title: str, items: List[Dict[str, Any]], system_id: Any, *, total: Optional[int] = None) -> Dict[str, Any]:
    return {"type": "table", "title": title, "system_id": system_id, "columns": _EXEC_COLS,
            "rows": items[:_MAX_ROWS], "total": total if total is not None else len(items)}


def _tool_error_notice(res: Dict[str, Any]) -> Optional[str]:
    code = str(res.get("code") or "")
    err = str(res.get("error") or "")
    low = err.lower()
    if code == "run_id_missing" or "run_id gerekli" in low:
        return ("Çalışma kimliği (RunID) bulunamadı; önce ilgili işin son hatalı "
                "çalışmasını arayın.")
    return None


def _from_search(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    """KPI'lar filtresiz evren (universe); tablo başlığı filtreyi belirtir."""
    uni = res.get("universe") if isinstance(res.get("universe"), dict) else {}
    # Filtresiz toplamlar — status_class=failed iken counts.ok=0 tuzağına düşme
    runs = uni.get("runs_total")
    if runs is None and res.get("runs_total") is not None:
        runs = res.get("runs_total")
    if runs is None:
        runs = res.get("total", 0)
    ok = uni.get("ok_total")
    if ok is None:
        ok = (res.get("counts") or {}).get("ok", 0)
    failed = uni.get("failed_total")
    if failed is None:
        failed = (res.get("counts") or {}).get("failed", 0)
    canc = uni.get("cancelled_total")
    if canc is None:
        canc = (res.get("counts") or {}).get("cancelled", 0)
    out = [{"type": "kpi_row", "items": [
        {"label": "Toplam", "value": int(runs or 0)},
        {"label": "Başarılı", "value": int(ok or 0), "tone": "ok"},
        {"label": "Hatalı", "value": int(failed or 0), "tone": "critical"},
        {"label": "İptal", "value": int(canc or 0), "tone": "warning"},
    ]}]
    if res.get("data_source") == "source_live":
        out.insert(0, {"type": "notice", "tone": "info",
                       "text": f"Kullanıcı '{res.get('user_query')}' kaynakta (OH USER → AH_USR_Idnr) canlı arandı: "
                               + ", ".join(u.get("name") or "?" for u in (res.get("source_users") or [])[:5])})
    hint = res.get("hint")
    if hint and not res.get("items"):
        known = ", ".join(u["user"] for u in (hint.get("known_users") or [])[:8])
        out.insert(0, {"type": "notice", "tone": "warning",
                       "text": hint.get("message", "") + (f" Bilinen kullanıcılar: {known}" if known else "")})
    # Job bazında özet (üstte) — failed_count sıralı
    by_obj = res.get("by_object") or []
    n_distinct = int(res.get("distinct_failed_objects") or len(by_obj))
    if by_obj and n_distinct > 1:
        shown = len(by_obj)
        title = (
            f"Hata veren job'lar ({shown} / {n_distinct} farklı"
            + (f" · {int(failed or 0)} hatalı çalışma" if failed else "") + ")"
        )
        out.append({
            "type": "table", "title": title,
            "system_id": res.get("system_id"),
            "columns": [
                {"key": "object_name", "label": "Job", "type": "object"},
                {"key": "failed_count", "label": "Hatalı"},
                {"key": "runs_count", "label": "Toplam çalışma"},
                {"key": "failure_rate_pct", "label": "Hata %", "format": "pct"},
                {"key": "last_failed_at", "label": "Son hata", "type": "datetime"},
            ],
            "rows": by_obj[:10],
            "total": n_distinct,
            "collapsed": False,
        })
    if res.get("items"):
        filt = (res.get("filtered_by") or {}).get("status_class")
        listed = int(res.get("filtered_total") if res.get("filtered_total") is not None else res.get("total") or 0)
        if filt and runs:
            title = f"Hatalı çalışmalar ({listed:,} / {int(runs):,})".replace(",", ".")
        elif filt:
            title = f"Hatalı çalışmalar ({listed})"
        else:
            title = "Çalışmalar"
        tbl = _exec_table(title, res["items"], res.get("system_id"), total=listed)
        # 10+ satır veya job özeti varsa varsayılan kapalı
        if listed > 10 or by_obj:
            tbl["collapsed"] = True
        out.append(tbl)
    return out


def _from_execution(args: Dict[str, Any], res: Dict[str, Any]) -> List[Dict[str, Any]]:
    aspect = (args.get("aspect") or "detail").lower()
    sid = res.get("system_id")
    if aspect == "detail" and res.get("execution"):
        e = res["execution"]
        items = [
            {"label": "Durum", "value": f"{e.get('status_class')} ({e.get('status_code')})",
             "tone": "critical" if e.get("status_class") == "failed" else "ok"},
            {"label": "Süre", "value": e.get("duration_sec"), "format": "duration"},
            {"label": "Agent", "value": e.get("agent") or "—"},
            {"label": "Dönüş kodu", "value": e.get("return_code")},
        ]
        out = [{"type": "kpi_row", "items": items}]
        if res.get("error_signature"):
            out.append({"type": "notice", "tone": "critical", "text": res["error_signature"]})
        return out
    if aspect == "children" and res.get("items"):
        return [{"type": "workflow_tree", "system_id": sid, "parent_run_id": res.get("parent_run_id"),
                 "nodes": [{k: i.get(k) for k in ("run_id", "object_name", "object_type", "status_class",
                                                  "status_code", "start_time", "end_time", "duration_sec",
                                                  "agent", "client")} for i in res["items"][:_MAX_ROWS]]}]
    if aspect == "report" and res.get("content"):
        return [{"type": "log_excerpt", "title": f"Rapor {res.get('report_type')}",
                 "source": res.get("data_source"), "truncated": res.get("truncated"),
                 "total_lines": res.get("total_lines"), "content": res["content"][:64000]}]
    if aspect == "restarts" and res.get("restarts"):
        return [{"type": "table", "title": "Restart zinciri", "system_id": sid, "columns": [
            {"key": "run_id", "label": "RunID", "type": "run"},
            {"key": "status_class", "label": "Sınıf", "type": "status"},
            {"key": "end_time", "label": "Bitiş", "type": "datetime"}], "rows": res["restarts"]}]
    return []


def _from_active(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [{"type": "kpi_row", "items": [
        {"label": "Aktif", "value": res.get("total", 0)},
        {"label": "p95 üstü", "value": len(res.get("over_p95") or []), "tone": "warning"},
    ]}]
    if res.get("items"):
        out.append({"type": "table", "title": "Aktif işler", "system_id": res.get("system_id"), "columns": [
            {"key": "object_name", "label": "Nesne", "type": "object"},
            {"key": "state", "label": "Durum"},
            {"key": "status_code", "label": "Kod"},
            {"key": "start_time", "label": "Başlangıç", "type": "datetime"},
            {"key": "running_sec", "label": "Çalışma süresi", "type": "duration"},
            {"key": "p95_duration_sec", "label": "p95", "type": "duration"},
            {"key": "agent", "label": "Agent", "type": "agent"},
            {"key": "run_id", "label": "RunID", "type": "run"},
            {"key": "client", "label": "Client"}], "rows": res["items"][:_MAX_ROWS]})
    return out


def _from_object(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    s = res.get("stats") or {}
    out = [{"type": "kpi_row", "items": [
        {"label": "Çalışma", "value": s.get("runs")},
        {"label": "Hata oranı", "value": s.get("failure_rate_pct"), "format": "pct",
         "tone": "critical" if (s.get("failure_rate_pct") or 0) > 5 else "ok"},
        {"label": "Ort. süre", "value": s.get("avg_duration_sec"), "format": "duration"},
        {"label": "p95", "value": s.get("p95_duration_sec"), "format": "duration"},
    ]}]
    if res.get("recent_runs"):
        out.append(_exec_table(f"{res.get('object_name')} — son çalışmalar", res["recent_runs"], res.get("system_id")))
    return out


_CHARTS = {
    "failure_trend": ("line", "bucket", [("failed", "Hatalı"), ("total", "Toplam")]),
    "volume": ("stacked_bar", "bucket", [("ok", "Başarılı"), ("failed", "Hatalı"), ("cancelled", "İptal")]),
    "duration_trend": ("line", "bucket", [("avg_sec", "Ortalama"), ("p95_sec", "p95"), ("max_sec", "Maks")]),
    "top_failed_objects": ("hbar", "object_name", [("failed", "Hatalı")]),
    "slowest_objects": ("hbar", "object_name", [("p95_sec", "p95 (sn)")]),
    "agent_activity": ("hbar", "agent", [("runs", "Çalışma"), ("failed", "Hatalı")]),
}


def _from_period_compare(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys = [("label", "Dönem"), ("total", "Toplam"), ("failed", "Hatalı"), ("ok", "Başarılı"),
            ("cancelled", "İptal"), ("failure_rate_pct", "Hata %"),
            ("first_record_at", "İlk kayıt"), ("last_record_at", "Son kayıt")]
    flat = [{k: r.get(k) for k, _ in keys} for r in res.get("rows") or []]
    out: List[Dict[str, Any]] = []
    msg = res.get("note") or res.get("comparison_warning")
    if msg:
        out.append({"type": "notice", "tone": "warning", "text": str(msg)})
    out.append({"type": "table", "title": res.get("label"), "system_id": res.get("system_id"),
                "columns": [{"key": k, "label": lbl} for k, lbl in keys], "rows": flat})
    return out


def _from_history(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    if res.get("template_id") == "period_compare":
        return _from_period_compare(res)
    rows = res.get("rows") or []
    if not rows:
        return [{"type": "notice", "tone": "info", "text": f"{res.get('label')}: veri yok"}]
    tid = res.get("template_id")
    out: List[Dict[str, Any]] = []
    if tid in _CHARTS:
        kind, x, series = _CHARTS[tid]
        if tid == "top_failed_objects" and not any(int(r.get("failed") or 0) for r in rows):
            pass
        else:
            out.append({"type": "chart", "kind": kind, "title": res.get("label"), "x": x,
                        "series": [{"key": k, "label": lbl} for k, lbl in series], "data": rows[:_MAX_ROWS]})
    cols = [{"key": k, "label": k} for k in rows[0].keys()]
    for c in cols:
        if c["key"] == "object_name":
            c["type"] = "object"
        elif c["key"] == "run_id":
            c["type"] = "run"
        elif c["key"] == "agent":
            c["type"] = "agent"
    out.append({"type": "table", "title": res.get("label"), "system_id": res.get("system_id"),
                "columns": cols, "rows": rows[:_MAX_ROWS]})
    return out


def build_components(structured_results: List[Dict[str, Any]],
                     *, message: Optional[str] = None) -> List[Dict[str, Any]]:
    comps: List[Dict[str, Any]] = []
    search_kpi_done = False
    # object_host / engines — altyapı bileşeni
    for sr in structured_results or []:
        tool = sr.get("tool") or ""
        res = sr.get("result")
        args = sr.get("args") or {}
        if not isinstance(res, dict) or not tool.startswith("automic_"):
            continue
        if res.get("ok") is False:
            note = _tool_error_notice(res)
            if note:
                comps.append({"type": "notice", "tone": "warning", "text": note})
            continue
        try:
            if tool == "automic_search_executions":
                part = _from_search(res)
                if search_kpi_done:
                    part = [p for p in part if p.get("type") != "kpi_row"]
                else:
                    search_kpi_done = True
                comps += part
            elif tool == "automic_execution":
                comps += _from_execution(args, res)
            elif tool == "automic_active":
                comps += _from_active(res)
            elif tool == "automic_object":
                if (args.get("aspect") or "").lower() == "usage" and res.get("nodes"):
                    comps.append({"type": "dependency_graph", "title": f"Usage · {res.get('object_name')}",
                                  "system_id": res.get("system_id"),
                                  "nodes": res.get("nodes") or [], "edges": res.get("edges") or []})
                else:
                    comps += _from_object(res)
            elif tool == "automic_history":
                comps += _from_history(res)
            elif tool == "automic_infrastructure":
                aspect = (args.get("aspect") or "").lower()
                if aspect == "object_host" and res.get("agents"):
                    comps.append({
                        "type": "table", "title": f"{res.get('object_name')} — agent'lar",
                        "system_id": res.get("system_id"),
                        "columns": [
                            {"key": "agent", "label": "Agent", "type": "agent"},
                            {"key": "runs_count", "label": "Çalışma"},
                            {"key": "hostname", "label": "Hostname"},
                            {"key": "ip", "label": "IP"},
                            {"key": "status_label", "label": "Durum"},
                            {"key": "synced_at", "label": "Son kontrol", "type": "datetime"},
                        ],
                        "rows": (res.get("agents") or [])[:_MAX_ROWS],
                        "total": res.get("distinct_agents"),
                    })
                elif aspect in ("engines", "overview") and res.get("servers"):
                    # Düz process satırları
                    flat = []
                    for s in res.get("servers") or []:
                        for p in s.get("processes") or []:
                            flat.append({
                                "ip": s.get("ip"), "node": s.get("node"),
                                "name": p.get("name"), "process_type": p.get("process_type"),
                                "status_label": p.get("status_label"), "is_pwp": p.get("is_pwp"),
                            })
                    if flat:
                        comps.append({
                            "type": "table", "title": "Engine sunucuları",
                            "system_id": res.get("system_id"),
                            "columns": [
                                {"key": "ip", "label": "IP"},
                                {"key": "node", "label": "Hostname"},
                                {"key": "name", "label": "Process"},
                                {"key": "process_type", "label": "Tip"},
                                {"key": "status_label", "label": "Durum"},
                            ],
                            "rows": flat[:_MAX_ROWS],
                        })
                    if res.get("summary_tr"):
                        comps.insert(0, {"type": "notice", "tone": "info", "text": res["summary_tr"]})
        except Exception as _e:
            note_error("components.build_components", _e)
            continue
    from app.services.automic.answer_profile import classify_question, filter_components
    profile = classify_question(message or "")
    return filter_components(profile, comps[:12], structured_results)
