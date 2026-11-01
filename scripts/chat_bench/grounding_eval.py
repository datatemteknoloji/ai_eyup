#!/usr/bin/env python3
"""Adım 7b ölçümü: bench kayıtlarındaki doğrulayıcı (gölge) bulgularını özetler ve gerçek cevaplardan türetilmiş
bozulmuş cevaplarla yakalama oranını ölçer.

Kullanım (docker içinde `app.services.chat_quality.grounding` gerekir):
  python3 scripts/chat_bench/grounding_eval.py --tags s7-r1,s7-r2,s7-r3 --out /tmp/chat-bench/s7-grounding
Çıktı: `<out>.json` (sayılar) + `<out>-findings.md` (her bulgu: soru, sınıf, metin, bağlam — insan incelemesi için).
Bozulmuş cevap testi için kayıtta `trace_tools_brief` (araç sonucu ≤3000 karakter) gerekir; kesilmiş sonuçlar atlanır.
"""
import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict

MODS = ("admin", "virt", "ocp")


def load(tag, mod, base):
    p = os.path.join(base, f"{tag}-{mod}.json")
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8")).get("results", [])


def summarize(records):
    cls_findings = Counter()
    cls_answers = Counter()
    ms = []
    skipped = Counter()
    total = scored = 0
    flagged = []
    for r in records:
        g = r.get("grounding")
        total += 1
        if not g:
            skipped["no_grounding"] += 1
            continue
        if g.get("skipped"):
            skipped[g["skipped"]] += 1
            continue
        scored += 1
        ms.append(g.get("ms") or 0.0)
        seen = set()
        for f in g.get("findings") or []:
            cls_findings[f["class"]] += 1
            seen.add(f["class"])
        for c, n in (g.get("counts") or {}).items():
            pass
        for c in seen:
            cls_answers[c] += 1
        if g.get("findings"):
            flagged.append(r)
    ms.sort()

    def pct(p):
        return round(ms[min(len(ms) - 1, int(len(ms) * p))], 1) if ms else 0.0
    return {
        "answers_total": total, "answers_scored": scored, "skipped": dict(skipped),
        "findings_by_class": dict(cls_findings), "answers_flagged_by_class": dict(cls_answers),
        "answers_flagged": len(flagged), "ms_p50": pct(0.5), "ms_p95": pct(0.95), "ms_max": ms[-1] if ms else 0.0,
    }, flagged


def corrupt_eval(records, seed=7):
    """Gerçek, bulgusuz cevaplardan bozulmuş sürümler üret; doğrulayıcının yakalama oranını ölç."""
    sys.path.insert(0, "/app")
    from app.services.chat_quality import grounding as g
    rnd = random.Random(seed)
    stats = defaultdict(lambda: [0, 0])      # sınıf → [yakalanan, denenen]
    n_base = 0
    base_clean = 0
    for r in records:
        gr = r.get("grounding")
        brief = r.get("trace_tools_brief") or []
        ans = r.get("answer") or ""
        if not gr or gr.get("skipped") or not brief or not ans:
            continue
        tools = []
        ok = True
        for t in brief:
            res = t.get("result")
            if isinstance(res, str) and len(res) >= 2990:
                ok = False
                break
            try:
                res = json.loads(res) if isinstance(res, str) else res
            except Exception:
                pass
            tools.append((t.get("tool"), t.get("args"), res))
        if not ok or not tools:
            continue
        kw = dict(user_message=r.get("q") or "", history_text=" ".join(r.get("history") or []), tools=tools, paths=[], platform="unified")
        base = g.verify(ans, **kw)
        n_base += 1
        if base["findings"]:
            continue                          # bulgusu olmayan temiz cevaplardan türet
        base_clean += 1
        variants = []
        # yalnız bağımsız, doğrulayıcının «anlamlı sayı» saydığı değerler (tarih/ad/IP/gruplu sayı parçası DEĞİL)
        meaningful = {v for v, _ in g.answer_numbers(ans)}
        nums = [(m.start(), m.group(0)) for m in re.finditer(
            r"(?<!\d )(?<![\w.,\-\u2011\u2013:/#])\d{2,6}(?:[.,]\d+)?(?![\w.,\-\u2011\u2013:/]\d)(?!\w)(?! \d{3}\b)", ans)
            if g.parse_number(m.group(0)) in meaningful]
        if nums:
            a, tok = rnd.choice(nums)
            val = g.parse_number(tok)
            wrong = str(int(val) + rnd.randint(137, 913))
            variants.append(("ungrounded_number", ans[:a] + wrong + ans[a + len(tok):]))
        variants.append(("ungrounded_entity", ans + f"\n\n**{rnd.choice(['cache-prod-77', 'mail-gw-03', 'ftp-old-09', 'ldap-dc-02'])}** de kapalı görünüyor."))
        variants.append(("ungrounded_command", ans + f"\n\n```\n{rnd.choice(['vmware-vim-cmd vmsvc/getallvms', 'esxcli system version get', 'govc ls /dc1', 'pvesh get /nodes'])}\n```"))
        variants.append(("internal_term", ans + f"\n\nVeri {rnd.choice(['db_list_vms', 'list_ocp_pods', 'infra_report'])} ile alındı."))
        variants.append(("source_label", f"## Liste (kaynak: {rnd.choice(['db_list_vms', 'vcenter_ask'])})\n\n" + ans))
        for cls, text in variants:
            res = g.verify(text, **kw)
            stats[cls][1] += 1
            if cls in {f["class"] for f in res["findings"]}:
                stats[cls][0] += 1
    return {"base_answers": n_base, "clean_base": base_clean,
            "capture": {c: {"caught": a, "tried": b, "rate": round(a / b, 3) if b else None} for c, (a, b) in stats.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", required=True)
    ap.add_argument("--base", default="/tmp/chat-bench")
    ap.add_argument("--out", default="/tmp/chat-bench/s7-grounding")
    ap.add_argument("--no-corrupt", action="store_true")
    a = ap.parse_args()
    recs = []
    for tag in a.tags.split(","):
        for m in MODS:
            for r in load(tag.strip(), m, a.base):
                r["_tag"], r["_mod"] = tag.strip(), m
                recs.append(r)
    summ, flagged = summarize(recs)
    out = {"summary": summ}
    if not a.no_corrupt:
        out["corrupt"] = corrupt_eval(recs)
    json.dump(out, open(a.out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    with open(a.out + "-findings.md", "w", encoding="utf-8") as fh:
        fh.write("# Doğrulayıcı bulguları (gölge) — insan incelemesi için\n\n")
        for r in flagged:
            fh.write(f"## {r['_tag']}/{r['_mod']} {r['id']} — {r['q']}\n\n")
            fh.write(f"Araçlar: {r.get('tools')} · yol: {[p.get('handler') or p.get('path') for p in (r.get('trace_paths') or [])]}\n\n")
            for f in r["grounding"]["findings"]:
                fh.write(f"- **{f['class']}** `{f['text']}` — {f.get('detail', '')}\n")
            fh.write(f"\n> {(r.get('answer') or '')[:600].replace(chr(10), ' ')}\n\n")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
