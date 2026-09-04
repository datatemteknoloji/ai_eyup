"""Özel Rapor motoru — sohbet-tabanlı keşif + deterministik dondurma.

Tasarım (hibrit A+B):
  1) `resolve_report_query()` — kullanıcı doğal dilde bir soru yazar (chat gibi).
     Mevcut agentic READ_ONLY tool-loop'u (`unified_tool_chat.run_read_only_tool_loop`)
     ile soru çözülür; o turda çağrılan HER tool (isim + args + ham sonuç) aday
     olarak döner. LLM burada sadece HANGİ aracı hangi argümanla çağıracağına karar
     verir — render tamamen bu modülün deterministik `render_tool_result()` fonksiyonuyla
     yapılır (LLM'in serbest metnine güvenilmez).
  2) Kullanıcı sonuçtan memnunsa bir adayı seçip başlık verir → `CustomReportDefinition`
     olarak kaydedilir (bkz. app.api.custom_reports).
  3) Sonraki her çalıştırmada `execute_definition()` YALNIZCA o aracı, O ARGÜMANLARLA
     yeniden çalıştırır — LLM'e HİÇ gidilmez. Tam tekrarlanabilir, düşük hata payı.

Kapsam kısıtı: yalnızca sunucudan bağımsız (READ_ONLY + direct_handler) araçlar
"dondurulabilir" (db_list_vms, db_list_datastores, db_list_esx_hosts, db_virt_alarms,
db_list_critical_events, db_virt_cross_match, db_list_ocp_nodes, db_list_ocp_projects,
vcenter_snapshot_summary, vcenter_list_vm_snapshots, vcenter_live_alarms,
vcenter_live_tasks, vcenter_perf_query, openshift_ask, list_ocp_pods, list_ocp_events,
list_kubevirt_vms, infra_overview, cross_entity_match, vcenter_ask, db_vm_detail, ...).
Belirli bir sunucuya SSH ile bağlanan atomik tanı komutları (get_system_summary vb.)
bu modülün kapsamı dışındadır — onlar tekil sunucu tanısı içindir, fleet raporu değil.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.chat_output_directives import (
    OutputDirective,
    render_rows_as_brief,
    render_rows_as_json,
)

logger = logging.getLogger(__name__)


def coerce_directive(value: Optional[str]) -> OutputDirective:
    if isinstance(value, OutputDirective):
        return value
    if not value:
        return OutputDirective.NONE
    try:
        return OutputDirective(str(value).strip().lower())
    except Exception:
        return OutputDirective.NONE


def is_capturable_tool(name: str) -> bool:
    """Bu tool bir Özel Rapor olarak dondurulabilir mi (sunucudan bağımsız, READ_ONLY)."""
    try:
        from app.services.agent.tools import get_tool
        from app.services.agent.policy import RiskLevel
    except Exception:
        return False
    tool = get_tool(name)
    return bool(tool and tool.risk_level == RiskLevel.READ_ONLY and tool.direct_handler)


# ── Genel (kind'a bağımsız) tool-sonucu → markdown/json/brief render ────────

_LIST_KEYS_PRIORITY = (
    "vms", "hosts", "esx_hosts", "datastores", "alarms", "events", "nodes",
    "projects", "pods", "snapshots", "tasks", "clusters", "workloads",
    "matches", "items", "results", "rows", "records", "metrics",
)

_META_KEYS = ("as_of", "count", "total_count", "total_count_in_window", "stale", "source", "cluster")


def _find_row_list(result: Dict[str, Any]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    for key in _LIST_KEYS_PRIORITY:
        val = result.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return key, val
    for key, val in result.items():
        if isinstance(val, list) and val and isinstance(val[0], dict):
            return key, val
    return None, []


def _rows_to_markdown_table(rows: List[Dict[str, Any]], *, max_rows: int = 200) -> str:
    if not rows:
        return "_Sonuç bulunamadı (0 kayıt)._"
    cols: List[str] = []
    for r in rows[:max_rows]:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    if len(cols) > 12:
        cols = cols[:12]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows[:max_rows]:
        vals = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            vals.append("" if v is None else str(v))
        lines.append("| " + " | ".join(vals) + " |")
    note = ""
    if len(rows) > max_rows:
        note = f"\n\n_...{len(rows) - max_rows} satır daha (toplam {len(rows)})._"
    return "\n".join(lines) + note


def render_tool_result(
    result: Any,
    directive: OutputDirective = OutputDirective.NONE,
    *,
    max_rows: int = 300,
) -> str:
    """Herhangi bir READ_ONLY tool sonucunu kind'a bağımsız, deterministik şekilde
    render eder — /table (varsayılan), /json, /brief komutlarına uyar."""
    if not isinstance(result, dict):
        return f"```json\n{json.dumps(result, ensure_ascii=False, default=str, indent=2)}\n```"

    if result.get("ok") is False:
        err = result.get("error") or result.get("hint") or "Bilinmeyen hata"
        return f"⚠️ Sorgu hata döndürdü: {err}"

    key, rows = _find_row_list(result)
    meta = {k: result.get(k) for k in _META_KEYS if k in result}

    if directive == OutputDirective.JSON:
        if rows:
            return render_rows_as_json(rows, meta=meta)
        return f"```json\n{json.dumps(result, ensure_ascii=False, default=str, indent=2)}\n```"

    if directive == OutputDirective.BRIEF:
        if rows:
            return render_rows_as_brief(rows, subject=key or "Sonuç")
        n = meta.get("count") or meta.get("total_count") or "?"
        return f"Toplam {n} kayıt döndü."

    if rows:
        header = ""
        if meta:
            info = ", ".join(f"{k}={v}" for k, v in meta.items())
            header = f"_{info}_\n\n"
        return header + _rows_to_markdown_table(rows, max_rows=max_rows)

    return f"```json\n{json.dumps(result, ensure_ascii=False, default=str, indent=2)}\n```"


# ── Keşif adımı: doğal dil soru → aday tool çağrıları ───────────────────────

def resolve_report_query(
    db: Session,
    *,
    question: str,
    platform: str,
    output_directive: Optional[str] = None,
    model: Optional[str] = None,
    max_steps: int = 6,
) -> Dict[str, Any]:
    """Doğal dil soruyu agentic READ_ONLY tool-loop ile çözer.

    Bu turda çağrılan HER tool'u (isim + args + ham sonuç + render önizleme +
    "capturable" bayrağı) aday listesi olarak döner. Kaydetme işlemi burada
    YAPILMAZ — kullanıcı adaylardan birini seçtiğinde `app.api.custom_reports`
    `POST /custom-reports/` ile kaydeder.
    """
    from app.core.config import get_active_model
    from app.services.agent.tools import domains_for_platform, get_tool
    from app.services.unified_tool_chat import run_read_only_tool_loop

    q = (question or "").strip()
    if not q:
        return {"ok": False, "error": "Soru boş olamaz."}

    mdl = model or get_active_model(db)
    plat = (platform or "unified").strip().lower()
    domains = domains_for_platform(plat)
    directive = coerce_directive(output_directive)

    tool_calls_seen: List[Dict[str, Any]] = []
    final: Dict[str, Any] = {}
    try:
        gen = run_read_only_tool_loop(
            db, mdl, q, "", "",
            max_steps=max_steps,
            domains=domains,
            platform=plat,
            output_directive=directive,
        )
        for ev in gen:
            et = ev.get("type")
            if et == "tool_call":
                tool_calls_seen.append({
                    "tool": ev.get("tool"),
                    "args": ev.get("args") or {},
                    "label": ev.get("label") or ev.get("tool"),
                })
            elif et == "final":
                final = ev
            elif et in ("skipped", "error"):
                return {
                    "ok": False,
                    "error": ev.get("reason") or ev.get("detail") or "Sorgu çözümlenemedi.",
                }
    except Exception as e:
        logger.exception("resolve_report_query patladı: %s", e)
        return {"ok": False, "error": str(e)}

    structured = final.get("structured_results") or []
    if not structured:
        return {
            "ok": True,
            "question": q,
            "platform": plat,
            "output_directive": directive.value,
            "model": mdl,
            "candidates": [],
            "note": (
                "Bu soru için hiçbir READ_ONLY tool çağrılmadı — model doğrudan genel "
                "bilgiyle cevapladı ya da soru mevcut araçlarla eşleşmedi. Özel rapor "
                "olarak dondurulacak somut bir sorgu bulunamadı."
            ),
        }

    # virt_inventory_contract zaten alan/filtre-duyarlı özel bir render üretmiş
    # olabilir (deterministic_answer) — varsa SON çağrılan uygun tool için onu
    # önizleme olarak tercih et (genel render'dan daha kaliteli); diğerleri için
    # genel `render_tool_result` fallback kullanılır.
    det_answer = final.get("deterministic_answer")

    # structured_results sırayla — aynı (tool,args) çağrısına ait label'ı
    # tool_calls_seen'den eşleştir (index bazlı, tekrarları da doğru sırayla eşler).
    used_idx: set = set()
    candidates: List[Dict[str, Any]] = []
    for i_sr, sr in enumerate(structured):
        name = sr.get("tool")
        args = sr.get("args") or {}
        result = sr.get("result")
        label = name
        for i, tc in enumerate(tool_calls_seen):
            if i in used_idx:
                continue
            if tc.get("tool") == name and tc.get("args") == args:
                label = tc.get("label") or name
                used_idx.add(i)
                break
        tool_obj = get_tool(name) if name else None
        ok = not (isinstance(result, dict) and result.get("ok") is False)
        preview = render_tool_result(result, directive)
        if det_answer and i_sr == len(structured) - 1:
            # deterministic_answer, structured_results'taki SON tool çağrısına
            # (virt envanter prefetch/loop'un ürettiği asıl SoT çağrısı) karşılık gelir.
            preview = det_answer
        candidates.append({
            "tool": name,
            "args": args,
            "label": label,
            "capturable": bool(is_capturable_tool(name)) if name else False,
            "ok": ok,
            "preview": preview,
            "domains": sorted(tool_obj.domains) if tool_obj else [],
        })

    return {
        "ok": True,
        "question": q,
        "platform": plat,
        "output_directive": directive.value,
        "model": mdl,
        "tools_used": final.get("tools_used") or [],
        "candidates": candidates,
    }


# Dondurulmuş çağrı bir virt envanter tool'uysa (db_list_vms/db_list_datastores/
# db_list_esx_hosts), yeniden çalıştırırken de aynı özel/alan-duyarlı formatter'ı
# kullan (chat'te görülenle birebir aynı kalite) — diğer tüm tool'lar için genel
# `render_tool_result` fallback yeterli ve kind'a bağımsızdır.
_KIND_BY_TOOL = {
    "db_list_datastores": "datastore",
    "db_list_esx_hosts": "esx_host",
}


def _render_via_inventory_contract(tool_name: str, args: Dict[str, Any], raw: Any, directive: "OutputDirective") -> Optional[str]:
    try:
        from app.services.virt_inventory_contract import materialize_from_tool_results, KIND_VM_DISK, KIND_VM_LIST
    except Exception:
        return None
    kind = _KIND_BY_TOOL.get(tool_name)
    if tool_name == "db_list_vms":
        kind = KIND_VM_DISK if args.get("include_disks") else KIND_VM_LIST
    if not kind:
        return None
    try:
        return materialize_from_tool_results(
            kind, [{"tool": tool_name, "result": raw}],
            fields=args.get("fields"), directive=directive,
        )
    except Exception:
        return None


# ── Dondurulmuş tanımı deterministik yeniden çalıştırma ─────────────────────

def execute_definition(db: Session, definition: Any) -> Dict[str, Any]:
    """Kayıtlı bir CustomReportDefinition'ı YENİDEN çalıştırır — LLM YOK, tamamen
    deterministik: kaydedilen (tool_name, tool_args) birebir tekrar çağrılır."""
    from app.services.agent.tools import get_tool
    from app.services.agent.policy import RiskLevel

    name = definition.tool_name
    tool = get_tool(name)
    if not tool:
        return {"ok": False, "error": f"Araç bulunamadı (kaldırılmış olabilir): {name}"}
    if tool.risk_level != RiskLevel.READ_ONLY or not tool.direct_handler:
        return {
            "ok": False,
            "error": "Bu araç özel rapor için desteklenmiyor (READ_ONLY + sunucudan bağımsız olmalı).",
        }

    args = dict(definition.tool_args or {})
    ctx = {"platform": definition.platform or "unified"}
    try:
        raw = tool.execute(db, args, ctx)
    except Exception as e:
        logger.exception("Özel rapor çalıştırma hatası (id=%s): %s", getattr(definition, "id", "?"), e)
        return {"ok": False, "error": str(e)}

    directive = coerce_directive(definition.output_directive)
    ok = not (isinstance(raw, dict) and raw.get("ok") is False)
    rendered = None
    if ok:
        rendered = _render_via_inventory_contract(name, args, raw, directive)
    if not rendered:
        rendered = render_tool_result(raw, directive)
    return {"ok": ok, "raw": raw, "rendered": rendered, "error": (raw.get("error") if isinstance(raw, dict) and not ok else None)}
