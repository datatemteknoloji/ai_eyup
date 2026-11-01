#!/usr/bin/env python3
"""Sohbet kalite benchmark çalıştırıcı (virt / ocp / admin).

  python scripts/chat_bench/run.py --module virt --set smoke
  python scripts/chat_bench/run.py --module all --set all --tag baseline
  python scripts/chat_bench/run.py --module ocp --set cnt,prem          # kategori
  python scripts/chat_bench/run.py --module ocp --set o01,o02           # kimlik
  python scripts/chat_bench/run.py --list

Çıktı: <out>/<tag>-<module>.json + .md (tam cevap, araçlar, plan, kural sonuçları).
Bench gerçek uç noktaları ve gerçek saati kullanır; oluşturduğu sohbet oturumlarını sonunda siler
(--no-cleanup ile kapatılır). Gizli bilgi soruları yalnız --include-secrets ile çalışır; kaydedilen
cevaplardaki gizli kalıplar [REDACTED-BENCH] ile maskelenir.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chat_bench import client, quality, truth  # noqa: E402
from chat_bench.questions import BUILDERS  # noqa: E402

SPEED = {"simple": 25.0, "medium": 60.0, "analysis": 90.0}
CAT_NAMES = {
    "cnt": "Sayım", "lst": "Liste/top-N", "which": "Hangi X'te", "yn": "Evet/Hayır", "cap": "Kapasite/sağlık",
    "why": "Neden", "prem": "Yanlış öncül", "fup": "Çok turlu", "code": "Kod/durum anlamı", "none": "Veride yok",
    "ghost": "Var olmayan varlık", "time": "Zaman", "multi": "Çoklu örnek/aynı ad", "inj": "Enjeksiyon/eylem",
    "sec": "Gizli bilgi", "route": "Çok modüllü yönlendirme", "cache": "Cache (benzer soru)", "automic": "Automic (Admin)",
    "cmd": "Komut dili (oc)", "chart": "Grafik dürüstlüğü",
}


INFRA_MARKERS = ("Uzak dil modeli şu anda yanıt vermiyor", "ReadTimeout", "Connection refused", "Model yanıt vermedi")


def is_infra(r: Dict[str, Any]) -> bool:
    """LLM/altyapı kaynaklı başarısızlık (ürün kalitesi değil): zaman aşımı, uzak LLM yanıtsız, boş cevap."""
    if "skipped" in r:
        return False
    if r.get("infra_override") is False:   # elle doğrulanmış: tekrarlanabilir ürün hatası
        return False
    ans = r.get("answer") or ""
    err = str(r.get("error") or "")
    if any(m in ans or m in err for m in INFRA_MARKERS):
        return True
    if "timed out" in err or "timeout" in err.lower() or err.startswith("HTTP 5"):
        return True
    return not ans.strip()


def select(specs: List[Dict[str, Any]], what: str, include_secrets: bool) -> List[Dict[str, Any]]:
    what = (what or "all").strip()
    out = []
    for s in specs:
        if s["needs_secret"] and not include_secrets:
            continue
        if what == "all":
            out.append(s)
        elif what == "smoke":
            if s["smoke"]:
                out.append(s)
        else:
            keys = {x.strip() for x in what.split(",") if x.strip()}
            if s["id"] in keys or s["cat"] in keys:
                out.append(s)
    return out


def run_module(module: str, args, T: Dict[str, Any], token: str) -> Dict[str, Any]:
    specs = select(BUILDERS[module](), args.set, args.include_secrets)
    results: List[Dict[str, Any]] = []
    sessions: List[int] = []
    prev: Dict[str, Dict[str, Any]] = {}
    if args.resume:
        try:
            with open(args.resume.format(module=module), encoding="utf-8") as f:
                prev = {r["id"]: r for r in json.load(f).get("results", [])}
        except Exception as e:
            print(f"[{module}] resume okunamadı: {e!r}", flush=True)
    for i, spec in enumerate(specs, 1):
        if spec["id"] in prev and prev[spec["id"]].get("q") == spec["q"] and not is_infra(prev[spec["id"]]):
            results.append({**prev[spec["id"]], "carried": True})
            continue
        try:
            exp = spec["exp"](T) if callable(spec["exp"]) else spec["exp"]
        except (KeyError, IndexError, TypeError) as e:
            results.append({"id": spec["id"], "cat": spec["cat"], "q": spec["q"], "skipped": f"ortam eksik: {e!r}"})
            print(f"[{module} {i}/{len(specs)}] {spec['id']} ATLANDI (ortam eksik: {e!r})", flush=True)
            continue
        sid = None
        for h in spec["history"]:
            r = client.ask(module, token, h, sid, timeout=args.timeout)
            sid = r.get("session_id") or sid
            if sid and sid not in sessions:
                sessions.append(sid)
        res = client.ask(module, token, spec["q"], sid, timeout=args.timeout, now_override=spec.get("now"))
        if res.get("session_id") and res["session_id"] not in sessions:
            sessions.append(res["session_id"])
        ev = quality.evaluate(spec, exp, res, T, speed_limit=SPEED.get(spec["tier"]))
        sec_cat = spec["cat"] == "sec"
        results.append({
            "id": spec["id"], "cat": spec["cat"], "tier": spec["tier"], "q": spec["q"], "history": spec["history"],
            "note": spec.get("note", ""),
            "answer": quality.redact(res["answer"]) if sec_cat else res["answer"],
            "wall_s": res.get("wall_s"), "first_token_s": res.get("first_token_s"),
            "from_cache": res.get("from_cache"), "tools": res.get("tools"),
            "plan": res.get("plan"), "error": res.get("error"), "needs_confirmation": res.get("needs_confirmation"),
            "trace_events": res.get("trace_events"),
            "trace_paths": (res.get("trace") or {}).get("paths"),
            "max_gap_s": res.get("max_gap_s"), "done_gap_s": res.get("done_gap_s"), "tokens_n": res.get("tokens_n"),
            "guard": (res.get("trace") or {}).get("guard"),
            "trace_tool_n": len((res.get("trace") or {}).get("tools") or []),
            "grounding": (res.get("trace") or {}).get("grounding"),
            # Doğrulayıcı bulgularını insan incelemesi ve bozulmuş-cevap testi için araç sonuçlarının kısa görünümü (Adım 7b)
            "trace_tools_brief": ([{"tool": t.get("tool"), "args": t.get("args"),
                                    "result": json.dumps(t.get("result"), ensure_ascii=False, default=str)[:3000]}
                                   for t in ((res.get("trace") or {}).get("tools") or [])]
                                  if ((res.get("trace") or {}).get("tools")) else None),
            **ev,
        })
        results[-1]["infra"] = is_infra(results[-1])
        flag = "GEÇTİ" if ev["passed"] else ("ALTYAPI" if results[-1]["infra"] else "KALDI")
        if ev["passed"] and ev["manual"]:
            flag += "+M"
        print(f"[{module} {i}/{len(specs)}] {spec['id']} {flag} {res.get('wall_s')}s"
              f"{' (cache)' if res.get('from_cache') else ''} {'; '.join(ev['reasons'])[:140]}", flush=True)
    if not args.no_cleanup:
        try:
            token = client.login()   # uzun koşuda JWT süresi dolmuş olabilir
        except Exception:
            pass
        failed = [sid for sid in sessions if not client.delete_session(module, token, sid)]
        if failed:
            print(f"[{module}] UYARI: {len(failed)} oturum silinemedi: {failed[:10]}", flush=True)
    return {"module": module, "results": results, "sessions_created": len(sessions)}


def summarize(mod: Dict[str, Any]) -> Dict[str, Any]:
    allr = [r for r in mod["results"] if "skipped" not in r]
    infra = [r for r in allr if is_infra(r) and not r["passed"]]
    rs = [r for r in allr if r not in infra]
    cats: "OrderedDict[str, Dict[str, int]]" = OrderedDict()
    for r in rs:
        c = cats.setdefault(r["cat"], {"n": 0, "pass": 0})
        c["n"] += 1
        c["pass"] += 1 if r["passed"] else 0
    lat = sorted(r["wall_s"] for r in rs if r.get("wall_s") is not None)
    return {
        "total": len(rs), "passed": sum(1 for r in rs if r["passed"]), "infra": len(infra),
        "infra_ids": [r["id"] for r in infra],
        "skipped": sum(1 for r in mod["results"] if "skipped" in r),
        "manual": sum(1 for r in rs if r.get("manual")),
        "cache_hits": sum(1 for r in rs if r.get("from_cache")),
        "by_cat": cats,
        "p50_s": lat[len(lat) // 2] if lat else None,
        "p95_s": lat[int(len(lat) * 0.95) - 1] if len(lat) >= 2 else (lat[0] if lat else None),
    }


def write_report(mod: Dict[str, Any], tag: str, outdir: str, meta: Dict[str, Any]) -> str:
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, f"{tag}-{mod['module']}")
    sm = summarize(mod)
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "summary": sm, **mod}, f, ensure_ascii=False, indent=1, default=str)
    L: List[str] = [f"# Chat bench — {mod['module']} ({tag})", "",
                    f"- Tarih: {meta['when']} · set: `{meta['set']}` · API: {meta['api']}",
                    f"- **Geçen: {sm['passed']}/{sm['total']}** (altyapı hatası {sm['infra']} hariç: {', '.join(sm['infra_ids']) or '-'}; atlanan {sm['skipped']}, manuel inceleme {sm['manual']}, "
                    f"cache cevabı {sm['cache_hits']}) · p50 {sm['p50_s']}s · p95 {sm['p95_s']}s", "",
                    "## Kategori", "", "| Kategori | Geçen | Toplam |", "|---|---|---|"]
    for c, v in sm["by_cat"].items():
        L.append(f"| {CAT_NAMES.get(c, c)} | {v['pass']} | {v['n']} |")
    L += ["", "## Kalanlar", ""]
    for r in mod["results"]:
        if "skipped" in r or r["passed"] or is_infra(r):
            continue
        ans = (r["answer"] or "").replace("\n", " ")
        L += [f"### {r['id']} [{r['cat']}] {r['q']}",
              f"- Neden: {'; '.join(r['reasons'])}",
              f"- Süre: {r['wall_s']}s · araçlar: {r.get('tools')} · plan: "
              f"{(r.get('plan') or {}).get('reason')}{' · CACHE' if r.get('from_cache') else ''}",
              f"- Cevap: {ans[:700]}{'…' if len(ans) > 700 else ''}", ""]
    L += ["## Manuel inceleme (otomatik kural yetmez)", ""]
    for r in mod["results"]:
        if "skipped" in r or not r.get("manual"):
            continue
        ans = (r["answer"] or "").replace("\n", " ")
        L += [f"- **{r['id']}** {r['q']} — {'GEÇTİ' if r['passed'] else 'KALDI'} — _{r['manual']}_",
              f"  - Cevap: {ans[:500]}{'…' if len(ans) > 500 else ''}"]
    warns = [r for r in mod["results"] if "skipped" not in r and r.get("warnings")]
    if warns:
        L += ["", "## Uyarılar", ""]
        for r in warns:
            L.append(f"- {r['id']}: {'; '.join(r['warnings'])}")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return base


def rescore(module: str, path: str, T: Dict[str, Any]) -> Dict[str, Any]:
    """Sohbete soru sormadan, kayıtlı cevapları güncel kural/gerçek değerlerle yeniden değerlendirir."""
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    specs = {s["id"]: s for s in BUILDERS[module]()}
    out: List[Dict[str, Any]] = []
    for r in old["results"]:
        sp = specs.get(r["id"])
        if "skipped" in r or not sp or sp["q"] != r["q"]:
            out.append(r)
            continue
        try:
            exp = sp["exp"](T) if callable(sp["exp"]) else sp["exp"]
        except (KeyError, IndexError, TypeError):
            out.append(r)
            continue
        ev = quality.evaluate(sp, exp, {"answer": r.get("answer"), "error": r.get("error"), "tools": r.get("tools"),
                                        "plan": r.get("plan"), "wall_s": r.get("wall_s")}, T,
                              speed_limit=SPEED.get(sp["tier"]))
        out.append({**r, **ev})
    return {"module": module, "results": out, "sessions_created": old.get("sessions_created")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="all", help="virt|ocp|admin|all")
    ap.add_argument("--set", default="smoke", help="smoke|all|kategori,kimlik listesi")
    ap.add_argument("--tag", default=datetime.now().strftime("run-%Y%m%d-%H%M"))
    ap.add_argument("--out", default="/tmp/chat-bench")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--include-secrets", action="store_true")
    ap.add_argument("--no-cleanup", action="store_true")
    ap.add_argument("--resume", default="", help="önceki JSON ({module} yer tutucu); yalnız altyapı hatalı soruları yeniden çalıştırır")
    ap.add_argument("--rescore", default="", help="soru sormadan kayıtlı JSON'u yeniden puanla ({module} yer tutucu)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--trace", action="store_true", help="debug_trace bayrağı: iç tur izini kaydet (admin)")
    args = ap.parse_args()

    modules = list(BUILDERS) if args.module == "all" else [m.strip() for m in args.module.split(",")]
    if args.list:
        for m in modules:
            sp = BUILDERS[m]()
            print(f"== {m}: {len(sp)} soru, smoke {sum(1 for s in sp if s['smoke'])}")
            for s in sp:
                print(f"  {s['id']:5} {s['cat']:7} {'S' if s['smoke'] else ' '}{'*' if s['needs_secret'] else ' '} {s['q']}")
        return 0

    client.TRACE = bool(args.trace)
    T = truth.load_truth()
    if args.rescore:
        meta = {"when": datetime.now().isoformat(timespec="seconds"), "set": "rescore", "api": client.api_base()}
        for m in modules:
            mod = rescore(m, args.rescore.format(module=m), T)
            base = write_report(mod, args.tag, args.out, meta)
            sm = summarize(mod)
            print(f"== {m}: {sm['passed']}/{sm['total']} geçti (altyapı {sm['infra']}) · rapor {base}.md")
        return 0
    token = client.login()
    meta = {"when": datetime.now().isoformat(timespec="seconds"), "set": args.set, "api": client.api_base()}
    rc = 0
    for m in modules:
        t0 = time.time()
        mod = run_module(m, args, T, token)
        base = write_report(mod, args.tag, args.out, meta)
        sm = summarize(mod)
        print(f"\n== {m}: {sm['passed']}/{sm['total']} geçti · {round(time.time()-t0)}s · rapor {base}.md", flush=True)
        if sm["passed"] < sm["total"]:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
