#!/usr/bin/env python3
"""Kayıtlı benchmark cevaplarını GÜNCEL kalite kurallarıyla yeniden puanlar (yeni koşu gerekmez).

Kullanım: python scripts/automic_rescore.py /tmp/bench/b7_full.json [--out /tmp/bench/b7_full_rescored.json]
Çıktı: kategori / soru bazında eski → yeni geçme sayıları.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import automic_chat_bench as bench  # noqa: E402
import automic_questions as aq  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    data = json.load(open(args.path, encoding="utf-8"))
    rows = data["rows"]
    old = {id(r): (r.get("quality") or {}).get("verdict") for r in rows}
    new_rows = copy.deepcopy(rows)
    bench.attach_quality(new_rows)
    by_q: "OrderedDict[str, list]" = OrderedDict()
    by_cat: "OrderedDict[str, list]" = OrderedDict()
    for r_old, r_new in zip(rows, new_rows):
        o = old[id(r_old)] == "GEÇTİ"
        n = (r_new.get("quality") or {}).get("verdict") == "GEÇTİ"
        by_q.setdefault(r_new["id"], []).append((o, n, r_new))
        by_cat.setdefault(r_new.get("cat") or "?", []).append((o, n))
    tot_o = sum(o for v in by_q.values() for o, _, _ in v)
    tot_n = sum(n for v in by_q.values() for _, n, _ in v)
    total = sum(len(v) for v in by_q.values())
    print(f"Genel: eski {tot_o}/{total} ({100 * tot_o / total:.1f}%) → güncel kurallarla {tot_n}/{total} ({100 * tot_n / total:.1f}%)")
    print("\nKategori | eski | yeni")
    for cat, v in by_cat.items():
        print(f"{cat} ({aq.CATEGORIES.get(cat, '')}) | {sum(o for o, _ in v)}/{len(v)} | {sum(n for _, n in v)}/{len(v)}")
    print("\nDeğişen sorular | eski | yeni | kalma nedenleri (yeni)")
    for qid, v in by_q.items():
        so, sn = sum(o for o, _, _ in v), sum(n for _, n, _ in v)
        fails = sorted({f.split(":")[0] for _, n, r in v if not n for f in (r.get("quality") or {}).get("failures", [])})
        if so != sn or sn < len(v):
            print(f"{qid} | {so}/{len(v)} | {sn}/{len(v)} | {', '.join(fails)}")
    if args.out:
        data["rows"] = new_rows
        json.dump(data, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
