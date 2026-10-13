#!/usr/bin/env python3
"""Automic sohbet performans benchmark — 10 sabit soru × 2 çalıştırma (fake veri).

Kullanım:
  python scripts/automic_chat_bench.py
  API=http://127.0.0.1:8000 USER=admin PASS=... python scripts/automic_chat_bench.py

Çıktı: markdown tablo + JSON özet (stdout / --out).

Adım 7/7f: `--set core|adv|all|smoke|a,b,k` (smoke = kategoriden 1'er), `--repeat N`,
`--temperature X`, `--load-test`, dinamik e-öncül (gerçek DB sayımından yanlış iddia).

Adım 6c: her çalıştırmada TAM cevap metni, kullanılan araçlar (args + sonuç özeti + tam araç izi) ve otomatik kalite
kontrolü (scripts/automic_quality.py → GEÇTİ/KALDI + neden) kaydedilir; çalıştırmalar arası karşılaştırılabilir.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import automic_questions as aq

QUESTIONS: List[Tuple[str, str]] = [(x["tier"], x["q"]) for x in aq.CORE]   # çekirdek 10 (geriye uyum)
SPEC_BY_ID: Dict[str, Dict[str, Any]] = {x["id"]: x for x in aq.ALL + aq.WHY + aq.INFRA}


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _psql_count(sql: str) -> tuple[int, int]:
    """automic_db üzerinde (failed, total) sayımı. Hata → (0, 0)."""
    cmd = [
        "docker", "exec", "-i", "automic_db",
        "psql", "-U", "automic", "-d", "automic", "-t", "-A", "-c", sql,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=30).strip()
        parts = (out.split("|") + ["0", "0"])[:2]
        return int(parts[0] or 0), int(parts[1] or 0)
    except Exception:
        return 0, 0


def _window_bounds(kind: str, now: datetime) -> tuple[datetime, datetime, str]:
    tz = now.tzinfo or ZoneInfo("Europe/Istanbul")
    today0 = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "yesterday":
        a, b = today0 - timedelta(days=1), today0
        return a, b, "dün"
    if kind == "this_week":
        week0 = today0 - timedelta(days=today0.weekday())
        return week0, week0 + timedelta(days=7), "bu hafta"
    if kind == "7d":
        return today0 - timedelta(days=7), today0 + timedelta(days=1), "son 7 günde"
    # 30d
    return today0 - timedelta(days=30), today0 + timedelta(days=1), "son 30 günde"


def enrich_dynamic_premises(specs: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """e kategorisi: gerçek failed/total oku → kesin farklı iddia ile soruyu yeniden yaz."""
    now = now or datetime.now(ZoneInfo("Europe/Istanbul"))
    out: List[Dict[str, Any]] = []
    for spec in specs:
        s = dict(spec)
        s["params"] = dict(spec.get("params") or {})
        p = s["params"]
        if not (s.get("cat") == "e" and p.get("dynamic")):
            out.append(s)
            continue
        obj = p.get("object") or "JOBS.DWH.SYNC.01"
        a, b, label = _window_bounds(p.get("window") or "yesterday", now)
        a_utc, b_utc = a.astimezone(timezone.utc), b.astimezone(timezone.utc)
        sql = (
            "SELECT count(*) FILTER (WHERE status_class='failed'), count(*) "
            "FROM automic_executions WHERE object_name = "
            f"'{obj}' AND end_time >= '{a_utc.isoformat()}' AND end_time < '{b_utc.isoformat()}'"
        )
        failed, total = _psql_count(sql)
        rate = round(100.0 * failed / total, 1) if total else 0.0
        p["actual_failed"] = failed
        p["actual_total"] = total
        p["actual_rate"] = rate
        kind = p.get("kind") or "failed_count"
        if kind == "failed_count":
            claim = failed + 17 if failed < 1000 else max(0, failed - 11)
            if claim == failed:
                claim = failed + 3
            p["claimed_n"] = claim
            s["q"] = f"{obj} {label} neden {claim} kez hata verdi?"
        elif kind == "all_failed":
            if total > 0 and failed >= total:
                # gerçekten hepsi hatalıysa "hiç hata yok" iddiası kur
                s["q"] = f"{obj} {label} hiç hata vermedi değil mi?"
                p["claimed_n"] = 0
                p["claim_none"] = True
            else:
                s["q"] = f"{obj} {label} hep başarısız olmuş, neden?"
                p["claimed_n"] = total
                p["claim_all"] = True
        else:  # failure_rate
            claim_rate = 50 if abs(rate - 50) > 5 else (90 if rate < 50 else 5)
            p["claimed_rate"] = claim_rate
            s["q"] = f"{obj}'nin hata oranı %{claim_rate} çıkmış, bunun nedeni ne?"
        out.append(s)
        print(f"  [dynamic e] {s['id']}: actual failed={failed}/{total} (%{rate}) → {s['q']}", flush=True)
    return out


def _load_pass_from_dotenv() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ADMIN_DEFAULT_PASSWORD="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def login(api: str, user: str, password: str) -> str:
    req = urllib.request.Request(
        f"{api}/api/v1/auth/login",
        data=json.dumps({"username": user, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["access_token"]


def stream_chat(api: str, token: str, message: str, timeout: int = 600, priority: str = "",
                think: str = "", session_id: Optional[int] = None,
                temperature: Optional[float] = None, now: str = "") -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{api}/api/v1/automation/chat/stream",
        data=json.dumps({
            "message": message,
            "timezone": "Europe/Istanbul",
            "language": "Türkçe",
            "debug_trace": True,
            **({"priority": priority} if priority else {}),
            **({"now_override": now} if now else {}),
            **({"session_id": session_id} if session_id else {}),
            **({"temperature_answer": temperature} if temperature is not None else {}),
            **({"think_sticky": think == "sticky"} if think in ("sticky", "split") else {}),
        }).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    asked_at = datetime.now(timezone.utc).isoformat()
    request_id = None
    perf_summary = None
    session_out = None
    sse_error = None
    answer = ""
    first_token_ms = None
    first_components_ms = None
    progress: List[Dict[str, Any]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                d = json.loads(line[5:].strip())
            except Exception:
                continue
            if d.get("request_id"):
                request_id = d.get("request_id")
            if d.get("session_id"):
                session_out = d.get("session_id")
            if d.get("error"):
                sse_error = d.get("error")
            if d.get("type") == "perf":
                request_id = d.get("request_id") or request_id
                perf_summary = d.get("perf")
            if d.get("type") == "progress":
                progress.append({"t_ms": round((time.perf_counter() - t0) * 1000, 1), "step": d.get("step"),
                                 "text": d.get("text"), "count": d.get("count")})
            if d.get("type") == "components" and first_components_ms is None:
                first_components_ms = (time.perf_counter() - t0) * 1000
            if d.get("token"):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t0) * 1000
                answer += d.get("token") or ""
    wall_ms = (time.perf_counter() - t0) * 1000
    return {
        "wall_ms": round(wall_ms, 1),
        "asked_at": asked_at,
        "session_id": session_out,
        "sse_error": sse_error,
        "request_id": request_id,
        "perf_summary": perf_summary,
        "answer_chars": len(answer),
        "answer": answer,
        "first_token_client_ms": round(first_token_ms, 1) if first_token_ms is not None else None,
        "first_components_ms": round(first_components_ms, 1) if first_components_ms is not None else None,
        "progress_events": progress,
        "first_progress_client_ms": progress[0]["t_ms"] if progress else None,
    }


def fetch_detail(api: str, token: str, request_id: str) -> Optional[Dict[str, Any]]:
    if not request_id:
        return None
    req = urllib.request.Request(
        f"{api}/api/v1/settings/chat-request-metrics/{request_id}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            return body.get("item")
    except Exception:
        # automic modül endpoint'i
        req2 = urllib.request.Request(
            f"{api}/api/v1/automation/chat/metrics/{request_id}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req2, timeout=30) as resp:
                body = json.loads(resp.read())
                return body.get("item")
        except Exception:
            return None


def _tool_summary(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in trace or []:
        res: Any = None
        try:
            res = json.loads(t.get("result_json") or "null")
        except Exception:
            pass
        item: Dict[str, Any] = {"tool": t.get("tool"), "args": {k: v for k, v in (t.get("args") or {}).items() if v not in (None, "", 0, [])}}
        if isinstance(res, dict):
            for k in ("ok", "total", "count", "template_id", "comparison_possible", "from", "to", "error"):
                if k in res:
                    item[k] = res[k]
            for k in ("items", "rows"):
                if isinstance(res.get(k), list):
                    item[f"{k}_n"] = len(res[k])
            cov = res.get("coverage")
            if isinstance(cov, dict):
                item["coverage"] = {k: cov.get(k) for k in ("data_first_at", "data_last_at", "records_in_range", "range_fully_covered", "note") if k in cov}
            if res.get("note"):
                item["note"] = res.get("note")
            if isinstance(res.get("deltas"), dict):
                item["deltas"] = res["deltas"]
        out.append(item)
    return out


def row_from_detail(q: str, tier: str, run: int, wall: Dict[str, Any], detail: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # SSE perf (aynı worker) öncelikli; Redis/detail yedek
    sse = wall.get("perf_summary") if isinstance(wall.get("perf_summary"), dict) else {}
    turns = (detail or {}).get("llm_turns") or sse.get("llm_turns_detail") or []
    tools = (detail or {}).get("tools") or sse.get("tools") or []
    prompt_tok = max((int(t.get("prompt_eval_count") or 0) for t in turns), default=0)
    eval_tok = sum(int(t.get("eval_count") or 0) for t in turns)
    reason_tok = sum(int(t.get("thinking_tokens_est") or 0) for t in turns)
    prompt_ms = sum(float(t.get("prompt_eval_duration_ms") or 0) for t in turns)
    eval_ms = sum(float(t.get("eval_duration_ms") or 0) for t in turns)
    tool_ms = sum(float(t.get("duration_ms") or 0) for t in tools)
    empty = sum(1 for t in turns if t.get("empty_turn"))
    if not empty and sse.get("empty_turns") is not None and not turns:
        empty = int(sse.get("empty_turns") or 0)
    who = sorted({t.get("triggered_by") or "?" for t in tools}) or ["—"]
    n_turns = len(turns) if turns else int(sse.get("llm_turns") or 0)
    return {
        "tier": tier,
        "question": q,
        "run": run,
        "total_ms": (detail or {}).get("total_ms") or sse.get("total_ms") or wall.get("wall_ms"),
        "wall_ms": wall.get("wall_ms"),
        "asked_at": wall.get("asked_at"),
        "llm_turns": n_turns,
        "empty_turns": empty,
        "prompt_tokens_max": prompt_tok,
        "eval_tokens": eval_tok,
        "reasoning_tokens_est": reason_tok,
        "prompt_eval_ms": round(prompt_ms, 1),
        "eval_ms": round(eval_ms, 1),
        "tool_ms": round(tool_ms, 1),
        "tools_by": "+".join(who),
        "rag_ms": (detail or {}).get("rag_ms") or sse.get("rag_ms") or 0,
        "intent": (detail or {}).get("intent") or sse.get("intent"),
        "request_id": wall.get("request_id"),
        "request_params": (detail or {}).get("request_params") or sse.get("request_params"),
        "token_sections": [
            t.get("token_sections") for t in turns if t.get("token_sections")
        ],
        "prompt_variable_fields": (
            (detail or {}).get("prompt_variable_fields")
            or sse.get("prompt_variable_fields")
        ),
        "tools": tools,
        "tool_parse_errors": sum(1 for t in turns if t.get("tool_parse_error")),
        # Adım 6b/6c
        "answer": wall.get("answer"),
        "answer_chars": wall.get("answer_chars"),
        "tool_trace": ((wall.get("perf_summary") or {}).get("tool_trace")) or [],
        "tool_summary": _tool_summary(((wall.get("perf_summary") or {}).get("tool_trace")) or []),
        "progress_events": wall.get("progress_events") or [],
        "first_progress_ms": wall.get("first_progress_client_ms"),
        "sched_wait_ms_total": (detail or {}).get("sched_wait_ms_total", sse.get("sched_wait_ms_total")),
        "phase_ms": (detail or {}).get("phase_ms") or sse.get("phase_ms"),
        "first_token_client_ms": wall.get("first_token_client_ms"),
        "first_visible_token_ms": (detail or {}).get("first_visible_token_ms") or sse.get("first_visible_token_ms"),
        "queue_ms_total": (detail or {}).get("queue_ms_total", sse.get("queue_ms_total")),
        "unaccounted_ms": (detail or {}).get("unaccounted_ms", sse.get("unaccounted_ms")),
        "final_turn_reason": (detail or {}).get("final_turn_reason") or sse.get("final_turn_reason"),
        "concurrent_llm": (detail or {}).get("concurrent_llm") or sse.get("concurrent_llm") or [],
        "tool_llm_payloads": (detail or {}).get("tool_llm_payloads") or sse.get("tool_llm_payloads") or [],
        "turns_detail": [
            {
                "purpose": t.get("purpose"), "think": t.get("think"), "num_predict": t.get("num_predict"),
                "done_reason": t.get("done_reason"), "streamed": t.get("streamed"),
                "prompt_eval_count": t.get("prompt_eval_count"),
                "prompt_eval_ms": t.get("prompt_eval_duration_ms"),
                "eval_count": t.get("eval_count"), "eval_ms": t.get("eval_duration_ms"),
                "thinking_tokens_est": t.get("thinking_tokens_est"),
                "thinking_chars": t.get("thinking_chars"), "content_chars": t.get("content_chars"),
                "content_head": t.get("content_head"), "leak_suspect": t.get("leak_suspect"),
                "empty_turn": t.get("empty_turn"), "empty_reason": t.get("empty_reason"),
                "tool_parse_error": bool(t.get("tool_parse_error")),
                "temperature": t.get("temperature"),
                "queue_ms": t.get("queue_ms"), "wall_ms": t.get("wall_ms"),
                "ctx_ratio_est": t.get("ctx_ratio_est"), "retry_note": t.get("retry_note"),
                "prefix_hash": t.get("prefix_hash"), "tools_hash": t.get("tools_hash"),
            }
            for t in turns
        ],
    }


def attach_quality(rows: List[Dict[str, Any]]) -> None:
    from automic_quality import check_answer
    for r in rows:
        if r.get("error"):
            r["quality"] = {"verdict": "KALDI", "checks": [], "failures": [f"istek hatası: {r['error']}"],
                            "manual_review": False, "manual_reasons": []}
            continue
        spec = SPEC_BY_ID.get(r.get("id") or "")
        if spec and r.get("question") and spec.get("q") != r["question"]:
            # Dinamik öncül (e kategorisi) soruyu yeniden yazar: kontroller GÖNDERİLEN soruyla çalışmalı
            # ("Belirttiğiniz 18 değil" — kullanıcının kendi sayısı kanıtsız sayılmaz)
            spec = {**spec, "q": r["question"]}
        r["quality"] = check_answer(
            r["question"], r.get("answer") or "", r.get("tool_trace") or [], asked_at=r.get("asked_at"),
            spec=spec if spec and spec.get("cat") != "0" else None,
            prior_trace=r.get("prior_trace") or None, prior_answers=r.get("prior_answers") or None)


def quality_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| Soru | Çalıştırma | Kalite | Kalma nedeni |", "|---|---|---|---|"]
    for r in rows:
        q = r.get("quality") or {}
        qs = r["question"].replace("|", "/")
        why = "; ".join(q.get("failures") or []).replace("|", "/").replace("\n", " ")
        lines.append(f"| {qs[:60]} | {r['run']} | {q.get('verdict', '—')} | {why[:300]} |")
    n_fail = sum(1 for r in rows if (r.get("quality") or {}).get("verdict") != "GEÇTİ")
    lines.append("")
    lines.append(f"**Kalite özeti:** {len(rows) - n_fail}/{len(rows)} GEÇTİ, {n_fail} KALDI.")
    return "\n".join(lines)


def md_table(rows: List[Dict[str, Any]]) -> str:
    lines = [
        "| Soru | Çalıştırma | Toplam süre | LLM tur | Boş tur | Prompt token (max tur) | Üretilen token | Reasoning token | Prompt işleme süresi (toplam) | Üretim süresi (toplam) | Araç süresi | Araçları kim seçti | RAG süresi |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        q = r["question"].replace("|", "/")
        if len(q) > 48:
            q = q[:45] + "…"
        lines.append(
            f"| {q} | {r['run']} | {r['total_ms']} ms | {r['llm_turns']} | {r['empty_turns']} | "
            f"{r['prompt_tokens_max']} | {r['eval_tokens']} | {r['reasoning_tokens_est']} | "
            f"{r['prompt_eval_ms']} ms | {r['eval_ms']} ms | {r['tool_ms']} ms | "
            f"{r['tools_by']} | {r['rag_ms']} ms |"
        )
    return "\n".join(lines)


def analyze(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "Veri yok."
    avg = lambda key: sum(float(r.get(key) or 0) for r in rows) / len(rows)
    parts = [
        f"Ortalama toplam: {avg('total_ms'):.0f} ms",
        f"prompt_eval: {avg('prompt_eval_ms'):.0f} ms",
        f"üretim: {avg('eval_ms'):.0f} ms",
        f"araç: {avg('tool_ms'):.0f} ms",
        f"RAG: {avg('rag_ms'):.0f} ms",
        f"LLM tur: {avg('llm_turns'):.1f}",
    ]
    # En büyük pay
    buckets = {
        "prompt_işleme": avg("prompt_eval_ms"),
        "üretim": avg("eval_ms"),
        "araç": avg("tool_ms"),
        "RAG": avg("rag_ms"),
    }
    top = max(buckets, key=buckets.get)
    # 1. vs 2. çalıştırma prompt
    r1 = [r for r in rows if r["run"] == 1]
    r2 = [r for r in rows if r["run"] == 2]
    p1 = sum(float(r["prompt_eval_ms"] or 0) for r in r1) / max(1, len(r1))
    p2 = sum(float(r["prompt_eval_ms"] or 0) for r in r2) / max(1, len(r2))
    cache_note = (
        f"2. çalıştırmada ort. prompt_eval {p1:.0f}→{p2:.0f} ms "
        f"({'düştü — prefix cache olası' if p2 < p1 * 0.9 else 'belirgin düşüş yok / cache etkisiz veya model zaten warm'})"
    )
    # Basit sorularda fallback
    simple_fb = [
        r for r in rows
        if r["tier"] == "simple" and "fallback" in (r.get("tools_by") or "")
    ]
    # Token dağılımı
    sec_keys = ("system", "rag", "tool_results", "history", "tool_definitions", "user")
    sec_sum = {k: 0.0 for k in sec_keys}
    sec_n = 0
    for r in rows:
        for s in r.get("token_sections") or []:
            if not isinstance(s, dict):
                continue
            sec_n += 1
            for k in sec_keys:
                sec_sum[k] += float(s.get(k) or 0)
    sec_avg = {k: round(sec_sum[k] / max(1, sec_n), 0) for k in sec_keys}

    # Parametre raporu (ilk dolu)
    params = next((r.get("request_params") for r in rows if r.get("request_params")), {}) or {}
    var_fields = next((r.get("prompt_variable_fields") for r in rows if r.get("prompt_variable_fields")), []) or []

    lines = [
        "## Yorum",
        f"- Süre payı: " + ", ".join(parts) + f". En büyük ölçülen kova: **{top}** ({buckets[top]:.0f} ms).",
        f"- {cache_note}.",
        f"- Basit sorularda yedek plan: {len(simple_fb)}/{len([r for r in rows if r['tier']=='simple'])} çalıştırma.",
        f"- Bölüm bazında ort. token tahmini (tur başına): {sec_avg}.",
        "",
        "## İstek parametreleri (değiştirilmedi — rapor)",
        f"- temperature: {params.get('temperature')}",
        f"- think/reasoning: {params.get('think_reasoning')}",
        f"- num_predict: {params.get('num_predict')}",
        f"- stream (tool loop): {params.get('stream')}; final_stream: {params.get('final_stream')}",
        f"- tools_count: {params.get('tools_count')}; tools_defs_tokens_est: {params.get('tools_defs_tokens_est')}",
        f"- num_ctx: {params.get('num_ctx')}; keep_alive: {params.get('keep_alive')}",
        "",
        "## Sistem prompt değişken alanlar (prefix cache)",
    ]
    for vf in var_fields:
        lines.append(
            f"- `{vf.get('name')}` @ {vf.get('location')} (offset {vf.get('char_offset')}): "
            f"{vf.get('prefix_cache_safe')}"
        )
    return "\n".join(lines)


def _avg(vals):
    vals = [float(v) for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _verdicts(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "—"
    v = [((r.get("quality") or {}).get("verdict") or "—") for r in rows]
    star = "*" if any((r.get("quality") or {}).get("mode") == "answer_only" for r in rows) else ""
    return "/".join(("G" if x == "GEÇTİ" else ("K" if x == "KALDI" else "—")) + star for x in v)


def compare_table(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> str:
    """Soru bazında (2 çalıştırma ortalaması) önce/sonra karşılaştırma tablosu."""
    def group(rows):
        g: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            g.setdefault(r["question"], []).append(r)
        return g
    gb, ga = group(before), group(after)
    lines = [
        "| Soru | Önce (sn) | Sonra (sn) | LLM tur önce/sonra | Üretilen token önce/sonra | Reasoning önce/sonra | Max prompt token önce/sonra | Kuyruk süresi | İlk görünür token (sn) | İlk ilerleme olayı (sn) | Kalite (önce→sonra) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for q in [x[1] for x in QUESTIONS]:
        b, a = gb.get(q, []), ga.get(q, [])
        if not a:
            continue
        qs = q.replace("|", "/")
        qs = qs if len(qs) <= 46 else qs[:43] + "…"
        f = lambda rows, k: _avg([r.get(k) for r in rows])
        tb, ta = f(b, "total_ms") / 1000, f(a, "total_ms") / 1000
        ftt = _avg([(r.get("first_visible_token_ms") or r.get("first_token_client_ms")) for r in a]) / 1000
        lines.append(
            f"| {qs} | {tb:.1f} | {ta:.1f} | {f(b,'llm_turns'):.1f} / {f(a,'llm_turns'):.1f} | "
            f"{f(b,'eval_tokens'):.0f} / {f(a,'eval_tokens'):.0f} | "
            f"{f(b,'reasoning_tokens_est'):.0f} / {f(a,'reasoning_tokens_est'):.0f} | "
            f"{max([r.get('prompt_tokens_max') or 0 for r in b] or [0])} / "
            f"{max([r.get('prompt_tokens_max') or 0 for r in a] or [0])} | "
            f"{f(a,'queue_ms_total')/1000:.1f} sn | {ftt:.1f} | {f(a,'first_progress_ms')/1000:.2f} | "
            f"{_verdicts(b)} → {_verdicts(a)} |"
        )
    return "\n".join(lines)


def _pct(vals: List[float], q: float) -> float:
    v = sorted(float(x) for x in vals if x is not None)
    if not v:
        return 0.0
    idx = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[idx]


def _passed(r: Dict[str, Any]) -> bool:
    return (r.get("quality") or {}).get("verdict") == "GEÇTİ"


def _speed_ok(r: Dict[str, Any]) -> bool:
    lim = aq.SPEED_LIMIT_SEC.get(r.get("tier") or "simple", 40.0)
    t = r.get("total_ms")
    return t is not None and float(t) / 1000.0 <= lim


# Varsayılan: saati dondur (admin+debug_trace `now_override`) — tekrarlanabilir ölçüm.
# Veri güncel olduğunda `--now real` ile gerçek saat (now_override yok).
# core: kapsamın bitişine yakın; adv: "Oct 11 gece yarısı sonrası" (dün = 10 Ekim).
NOW_FROZEN = {"0": "2026-10-10T02:40:00+03:00", "_": "2026-10-11T00:30:00+03:00"}
NOW_MODE = "frozen"      # frozen | real | <ISO>


def now_for(spec: Dict[str, Any]) -> str:
    if NOW_MODE == "real":
        return ""
    if NOW_MODE != "frozen":
        return NOW_MODE
    return NOW_FROZEN.get(str(spec.get("cat")), NOW_FROZEN["_"])


def run_spec(api: str, token: str, spec: Dict[str, Any], run: int, *, priority: str = "", think: str = "",
             temperature: Optional[float] = None) -> Dict[str, Any]:
    """Tek soru (çok turluysa önce history mesajları aynı oturumda). Satır = SON turun ölçümü."""
    sid: Optional[int] = None
    prior_trace: List[Dict[str, Any]] = []
    prior_answers: List[str] = []
    for hmsg in spec.get("history") or []:
        w = stream_chat(api, token, hmsg, priority=priority, think=think, session_id=sid, temperature=temperature, now=now_for(spec))
        sid = w.get("session_id") or sid
        prior_answers.append(w.get("answer") or "")
        prior_trace += ((w.get("perf_summary") or {}).get("tool_trace")) or []
    wall = stream_chat(api, token, spec["q"], priority=priority, think=think, session_id=sid, temperature=temperature, now=now_for(spec))
    detail = fetch_detail(api, token, wall.get("request_id") or "")
    row = row_from_detail(spec["q"], spec["tier"], run, wall, detail)
    _now = now_for(spec)
    if _now:       # kalite kontrolü ("dün" penceresi) dondurulmuş saate göre yapılır
        row["asked_at_real"] = row.get("asked_at")
        row["asked_at"] = _now
    row.update({"id": spec["id"], "cat": spec["cat"], "temperature_arg": temperature,
                "prior_trace": prior_trace, "prior_answers": prior_answers,
                "sse_error": wall.get("sse_error")})
    return row


# ── raporlar ──────────────────────────────────────────────────────────────

def category_table(rows: List[Dict[str, Any]], n: int) -> str:
    lines = [f"| Kategori | Soru sayısı | Geçme oranı (N={n}) | Tipik hata | Örnek kalan cevap |", "|---|---|---|---|---|"]
    for cat, name in aq.CATEGORIES.items():
        rr = [r for r in rows if r.get("cat") == cat]
        if not rr:
            continue
        nq = len({r["id"] for r in rr})
        ok = sum(1 for r in rr if _passed(r))
        failed = [r for r in rr if not _passed(r)]
        from collections import Counter
        c = Counter()
        for r in failed:
            for f in (r.get("quality") or {}).get("failures") or []:
                c[f.split(":")[0]] += 1
        typical = ", ".join(f"{k} ×{v}" for k, v in c.most_common(3)) or "—"
        sample = "—"
        if failed:
            a = (failed[0].get("answer") or "").replace("\n", " ").replace("|", "/")
            sample = f"[{failed[0]['id']}] " + (a[:160] + "…" if len(a) > 160 else a)
        lines.append(f"| {cat}) {name} | {nq} | {ok}/{len(rr)} (%{100 * ok / len(rr):.0f}) | {typical} | {sample} |")
    return "\n".join(lines)


def question_pass_table(rows: List[Dict[str, Any]]) -> str:
    lines = ["| Id | Soru | Geçme | Ort. süre (sn) | p95 (sn) | Hız hedefi | Kalma nedenleri (özet) |", "|---|---|---|---|---|---|---|"]
    order = [x["id"] for x in aq.ALL + aq.WHY]
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r.get("id") or r["question"], []).append(r)
    for qid in order:
        rr = by.get(qid)
        if not rr:
            continue
        ok = sum(1 for r in rr if _passed(r))
        ts = [float(r["total_ms"]) / 1000 for r in rr if r.get("total_ms")]
        sp = sum(1 for r in rr if _speed_ok(r))
        from collections import Counter
        c = Counter()
        for r in rr:
            for f in (r.get("quality") or {}).get("failures") or []:
                c[f.split(":")[0]] += 1
        why = ", ".join(f"{k}×{v}" for k, v in c.most_common(3)) or "—"
        q = rr[0]["question"].replace("|", "/")
        lines.append(f"| {qid} | {q[:58]} | {ok}/{len(rr)} | {sum(ts) / max(1, len(ts)):.1f} | {_pct(ts, .95):.1f} | {sp}/{len(rr)} | {why} |")
    return "\n".join(lines)


def overall_stats(rows: List[Dict[str, Any]]) -> str:
    ok = sum(1 for r in rows if _passed(r))
    ts = [float(r["total_ms"]) / 1000 for r in rows if r.get("total_ms")]
    lines = [f"- Genel geçme oranı: **{ok}/{len(rows)} (%{100 * ok / max(1, len(rows)):.1f})**",
             f"- Süre: ortalama {sum(ts) / max(1, len(ts)):.1f} sn, p95 {_pct(ts, .95):.1f} sn, maks {max(ts or [0]):.1f} sn"]
    for tier in ("simple", "medium", "analysis"):
        rr = [r for r in rows if r.get("tier") == tier and r.get("total_ms")]
        if rr:
            tt = [float(r["total_ms"]) / 1000 for r in rr]
            sp = sum(1 for r in rr if _speed_ok(r))
            lines.append(f"  - {tier} (hedef ≤ {aq.SPEED_LIMIT_SEC[tier]:.0f} sn): ort {sum(tt) / len(tt):.1f}, p95 {_pct(tt, .95):.1f}, hedef içinde {sp}/{len(rr)}")
    err = [r for r in rows if r.get("error") or (r.get("sse_error"))]
    lines.append(f"- İstek hatası / SSE hatası / zaman aşımı: {len(err)}")
    return "\n".join(lines)


def manual_table(rows: List[Dict[str, Any]]) -> str:
    items = [r for r in rows if (r.get("quality") or {}).get("manual_review")]
    if not items:
        return "Manuel inceleme işaretli cevap yok."
    # soru başına en çok 2 örnek (tüm N tekrar listelenmez)
    seen: Dict[str, int] = {}
    lines = ["| Id | Çalıştırma | Otomatik karar | Neden manuel | Cevap (ilk 220 kr) |", "|---|---|---|---|---|"]
    for r in items:
        k = r.get("id") or r["question"]
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 2:
            continue
        a = (r.get("answer") or "").replace("\n", " ").replace("|", "/")
        why = "; ".join((r["quality"].get("manual_reasons") or [])).replace("|", "/")
        lines.append(f"| {k} | {r['run']} | {r['quality']['verdict']} | {why[:140]} | {a[:220]} |")
    lines.append("")
    lines.append(f"Toplam manuel işaretli cevap: {len(items)} / {len(rows)} (tabloda soru başına ilk 2 örnek).")
    return "\n".join(lines)


def parse_error_report(rows: List[Dict[str, Any]]) -> str:
    """Ollama 'error parsing tool call' (HTTP 500) oranı: LLM turu başına; soru kategorisi / think seviyesi / tur amacı kırılımı."""
    from collections import defaultdict
    tot = bad = 0
    by_cat: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    by_think: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    by_purpose: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    by_q: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        for t in r.get("turns_detail") or []:
            tot += 1
            e = 1 if t.get("tool_parse_error") else 0
            bad += e
            for d, k in ((by_cat, r.get("cat")), (by_think, str(t.get("think") or "yok")),
                         (by_purpose, str(t.get("purpose") or "?")), (by_q, r.get("id") or "?")):
                d[k][0] += 1
                d[k][1] += e
    if not tot:
        return "LLM tur verisi yok."
    f = lambda d: ", ".join(f"{k}: {v[1]}/{v[0]} (%{100 * v[1] / v[0]:.1f})" for k, v in sorted(d.items(), key=lambda kv: -kv[1][1] / max(1, kv[1][0])))
    worst = {k: v for k, v in by_q.items() if v[1]}
    lines = [f"- Toplam LLM turu: {tot}; parse hatalı tur: **{bad} (%{100 * bad / tot:.2f})**",
             f"- Tur amacına göre: {f(by_purpose)}",
             f"- think seviyesine göre: {f(by_think)}",
             f"- Soru kategorisine göre: {f(by_cat)}",
             f"- Hata gören sorular: {f(worst) if worst else '—'}"]
    reqs = sum(1 for r in rows if r.get("tool_parse_errors"))
    lines.append(f"- En az bir parse hatası gören istek: {reqs}/{len(rows)} (%{100 * reqs / max(1, len(rows)):.1f})")
    return "\n".join(lines)


def temp_report(rows: List[Dict[str, Any]]) -> str:
    by: Dict[str, set] = {}
    for r in rows:
        for t in r.get("turns_detail") or []:
            if t.get("temperature") is not None:
                by.setdefault(t.get("purpose") or "?", set()).add(t["temperature"])
    parts = "; ".join(f"{k}: {sorted(v)}" for k, v in sorted(by.items())) or "veri yok (eski kayıt)"
    return (f"- tur başına gönderilen temperature (purpose → değerler): {parts}; "
            f"istek bazlı override (--temperature): {next((r.get('temperature_arg') for r in rows if r.get('temperature_arg') is not None), '—')}")


def run_load_test(api: str, token: str, n_chat: int, question: str, bg_question: str, timeout: int = 600) -> Dict[str, Any]:
    """n_chat eşzamanlı kullanıcı sohbeti + 1 arka plan sınıfı iş (priority=background) AYNI ANDA başlar."""
    import threading
    results: List[Dict[str, Any]] = []
    lock = threading.Lock()
    t0 = time.perf_counter()

    def worker(label: str, q: str, prio: str, delay: float) -> None:
        time.sleep(delay)
        start = time.perf_counter() - t0
        rec: Dict[str, Any] = {"label": label, "priority": prio or "chat", "start_s": round(start, 2), "question": q}
        try:
            w = stream_chat(api, token, q, priority=prio, timeout=timeout, now=now_for({"cat": "0"}))
            detail = fetch_detail(api, token, w.get("request_id") or "")
            row = row_from_detail(q, "simple", 1, w, detail)
            rec.update({"wall_s": round((w.get("wall_ms") or 0) / 1000, 1), "sched_wait_s": round(float(row.get("sched_wait_ms_total") or 0) / 1000, 2),
                        "queue_s": round(float(row.get("queue_ms_total") or 0) / 1000, 2),
                        "first_progress_ms": row.get("first_progress_ms"), "first_token_s": round(float(w.get("first_token_client_ms") or 0) / 1000, 1),
                        "answer_chars": w.get("answer_chars"), "error": w.get("sse_error"), "request_id": w.get("request_id")})
        except Exception as e:
            rec.update({"error": f"{type(e).__name__}: {e}"})
        with lock:
            results.append(rec)

    th = [threading.Thread(target=worker, args=("bg", bg_question, "background", 0.0))]
    th += [threading.Thread(target=worker, args=(f"chat{i + 1}", question, "", 1.0 + 0.3 * i)) for i in range(n_chat)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    results.sort(key=lambda r: r["label"])
    return {"results": results, "total_s": round(time.perf_counter() - t0, 1)}


def load_report(lt: Dict[str, Any]) -> str:
    lines = ["| İş | Sınıf | Başlangıç (sn) | Süre (sn) | Semafor kuyruk bekleme (sn) | İlk ilerleme (ms) | İlk token (sn) | Hata |", "|---|---|---|---|---|---|---|---|"]
    for r in lt["results"]:
        lines.append(f"| {r['label']} | {r['priority']} | {r['start_s']} | {r.get('wall_s', '—')} | {r.get('sched_wait_s', '—')} | "
                     f"{r.get('first_progress_ms', '—')} | {r.get('first_token_s', '—')} | {r.get('error') or '—'} |")
    chats = [r for r in lt["results"] if r["label"].startswith("chat")]
    bg = next((r for r in lt["results"] if r["label"] == "bg"), {})
    lines.append("")
    lines.append(f"- Toplam süre: {lt['total_s']} sn; sohbet kuyruk bekleme (sn): " + ", ".join(str(c.get('sched_wait_s')) for c in chats))
    lines.append(f"- Arka plan işi: süre {bg.get('wall_s')} sn, kuyruk bekleme {bg.get('sched_wait_s')} sn (sohbetler önce işlenmeli → arka plan gecikir)")
    errs = [r for r in lt["results"] if r.get("error")]
    lines.append(f"- Zaman aşımı / hata: {len(errs)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=_env("API", "http://127.0.0.1:8000"))
    ap.add_argument("--user", default=_env("USER", "admin"))
    ap.add_argument("--password", default=_env("PASS") or _load_pass_from_dotenv())
    ap.add_argument("--out", default="")
    ap.add_argument("--repeat", "--runs", dest="runs", type=int, default=5, help="Her soru kaç kez (varsayılan 5)")
    ap.add_argument("--set", dest="qset", default="core",
                    help="core | adv | all | smoke | kategori harfleri (a,b,k) | soru id")
    ap.add_argument("--compare", default="", help="Önceki benchmark JSON (önce/sonra tablosu)")
    ap.add_argument("--now", default="frozen", help="frozen (varsayılan, tekrarlanabilir) | real | ISO zaman")
    ap.add_argument("--ids", default="", help="Virgülle ayrılmış soru id'leri (ör. d2,k3)")
    ap.add_argument("--only", default="", help="Soru metninde geçen alt dize ile filtrele")
    ap.add_argument("--temperature", type=float, default=None, help="Cevap turu temperature (admin+debug override); boş = ayarlardaki varsayılan")
    ap.add_argument("--think", default="", choices=["", "sticky", "split"],
                    help="think A/B: split = araç seçimi low + cevap seviyesi; sticky = tüm turlar cevap seviyesi")
    ap.add_argument("--priority", default="", help="LLM semafor sınıfı: background → arka plan önceliği")
    ap.add_argument("--load-test", action="store_true", help="3 eşzamanlı sohbet + 1 arka plan işi (semafor)")
    ap.add_argument("--load-chats", type=int, default=3)
    args = ap.parse_args()
    global NOW_MODE
    NOW_MODE = args.now
    if not args.password:
        print("PASSWORD gerekli (PASS veya .env ADMIN_DEFAULT_PASSWORD)", file=sys.stderr)
        return 2
    api = args.api.rstrip("/")
    try:
        token = login(api, args.user, args.password)
    except Exception as e:
        print(f"Login başarısız: {e}", file=sys.stderr)
        return 1

    if args.load_test:
        lt = run_load_test(api, token, args.load_chats, "Şu an kaç iş çalışıyor?",
                           "En çok hata veren 5 job ve ortak noktaları")
        rep = "# Semafor yük testi\n\n" + load_report(lt) + "\n"
        print(rep)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump({"load_test": lt, "markdown": rep}, f, ensure_ascii=False, indent=2)
            with open(args.out.rsplit(".", 1)[0] + ".md", "w", encoding="utf-8") as f:
                f.write(rep)
        return 0

    specs = aq.select(args.qset)
    # e kategorisi dinamik öncül (gerçek DB sayımı)
    if any(s.get("cat") == "e" and (s.get("params") or {}).get("dynamic") for s in specs):
        specs = enrich_dynamic_premises(specs)
    rows: List[Dict[str, Any]] = []
    # tekrarları soru bazında döngüle (aynı sorunun N tekrarı ardışık → prefix cache / sıcaklık etkisi karışmaz)
    for spec in specs:
        if args.ids and spec["id"] not in {x.strip() for x in args.ids.split(",")}:
            continue
        if args.only and args.only.lower() not in spec["q"].lower():
            continue
        for run in range(1, max(1, args.runs) + 1):
            print(f"[{spec['id']}/{spec['tier']}] run={run}: {spec['q']}", flush=True)
            try:
                row = run_spec(api, token, spec, run, priority=args.priority, think=args.think, temperature=args.temperature)
            except urllib.error.HTTPError as e:
                print(f"  HTTP {e.code}: {e.read()[:300]}", file=sys.stderr)
                rows.append({"id": spec["id"], "cat": spec["cat"], "tier": spec["tier"], "question": spec["q"], "run": run,
                             "total_ms": None, "llm_turns": 0, "empty_turns": 0, "prompt_tokens_max": 0,
                             "eval_tokens": 0, "reasoning_tokens_est": 0, "prompt_eval_ms": 0, "eval_ms": 0,
                             "tool_ms": 0, "tools_by": "error", "rag_ms": 0, "error": str(e.code)})
                continue
            except Exception as e:   # zaman aşımı / bağlantı
                print(f"  HATA {type(e).__name__}: {e}", file=sys.stderr)
                rows.append({"id": spec["id"], "cat": spec["cat"], "tier": spec["tier"], "question": spec["q"], "run": run,
                             "total_ms": None, "llm_turns": 0, "empty_turns": 0, "prompt_tokens_max": 0,
                             "eval_tokens": 0, "reasoning_tokens_est": 0, "prompt_eval_ms": 0, "eval_ms": 0,
                             "tool_ms": 0, "tools_by": "error", "rag_ms": 0, "error": f"{type(e).__name__}: {e}"})
                continue
            rows.append(row)
            attach_quality([row])
            q = row.get("quality") or {}
            print(f"  total={row['total_ms']}ms turns={row['llm_turns']} parse_err={row.get('tool_parse_errors')} "
                  f"tools={row['tools_by']} quality={q.get('verdict')}"
                  f"{' [MANUEL]' if q.get('manual_review') else ''}"
                  f"{'  ← ' + '; '.join(q.get('failures') or [])[:200] if q.get('verdict') != 'GEÇTİ' else ''}", flush=True)
            if args.out:   # artımlı kayıt: uzun koşular yarıda kesilirse veri kaybolmasın
                with open(args.out + ".partial", "w", encoding="utf-8") as f:
                    json.dump({"rows": rows}, f, ensure_ascii=False)

    attach_quality(rows)
    n = max(1, args.runs)
    report = ["# Automic chat benchmark", "", f"Küme: `{args.qset}`, tekrar N={n}, temperature override: {args.temperature}, saat: {args.now}", "",
              "## Genel", "", overall_stats(rows), "", "## Kategori tablosu", "", category_table(rows, n), "",
              "## Soru bazında geçme oranı", "", question_pass_table(rows), "",
              "## Manuel inceleme listesi", "", manual_table(rows), "",
              "## Tool-call parse hataları (Ollama 500)", "", parse_error_report(rows), "",
              "## Sıcaklık", "", temp_report(rows), ""]
    core_rows = [r for r in rows if r.get("cat") == "0"]
    if core_rows:
        report += ["## Çekirdek 10 — süre / kalite", "", md_table(core_rows), "", quality_table(core_rows), "", analyze(core_rows), ""]
    else:
        report += ["## Kalan cevaplar (ayrıntı)", "", quality_table([r for r in rows if not _passed(r)]), ""]
    report_s = "\n".join(report)
    if args.compare and os.path.isfile(args.compare):
        with open(args.compare, encoding="utf-8") as f:
            before_rows = json.load(f).get("rows") or []
        for _r in before_rows:
            if not _r.get("quality") and _r.get("answer"):
                from automic_quality import check_answer as _ca
                _tt = _r.get("tool_trace") or []
                _r["quality"] = _ca(_r["question"], _r.get("answer") or "", _tt, answer_only=not _tt)
        report_s += "\n## Önce / Sonra\n\n" + compare_table(before_rows, core_rows or rows) + "\n"
    print("\n" + report_s)
    out = {"rows": rows, "markdown": report_s}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        md_path = args.out.rsplit(".", 1)[0] + ".md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_s)
        print(f"Wrote {args.out} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
