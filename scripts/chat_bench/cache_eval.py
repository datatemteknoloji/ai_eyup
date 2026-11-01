"""Adım 9 — önbellek ölçümü: kavramsal tekrar (isabet oranı + HIT/MISS süresi) ve benzer-varlık çiftleri (yanlış isabet = 0).

  cd /dttadvance/app && python3 -m scripts.chat_bench.cache_eval --module admin --rounds 1 --out /tmp/chat-bench/s9-cache
  (module: virt|ocp|admin|all)

Kavramsal sorular iki kez sorulur (her biri YENİ oturumda): 1. = MISS (veya önceki turdan HIT), 2. = HIT beklenir.
Çiftler: ikinci sorunun from_cache=true olması YANLIŞ İSABET sayılır (veri/varlık soruları hiç önbelleğe girmemeli).
Uygulama verisine dokunmaz; yalnız normal sohbet çağrıları yapar (bench oturumları sonunda silinir).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time

from . import client

CONCEPT = {
    "virt": [
        "vMotion nedir ve nasıl çalışır?",
        "VMware snapshot nedir ve ne işe yarar?",
        "Thin provisioning ile thick provisioning farkı nedir?",
        "vSphere HA nasıl çalışır?",
        "Snapshot'ı uzun süre tutmak neden sorun olur?",
        "Datastore nedir?",
        "Memory ballooning nedir ve nasıl çalışır?",
    ],
    "ocp": [
        "Kubernetes'te Pod nedir?",
        "OpenShift'te Route ile Ingress farkı nedir?",
        "CrashLoopBackOff ne demek?",
        "Taint ve toleration nasıl çalışır?",
        "PersistentVolumeClaim nedir ve ne işe yarar?",
        "Requests ile limits farkı nedir?",
        "DaemonSet nedir?",
    ],
    "admin": [
        "Linux'ta load average ne anlama gelir?",
        "RAID 5 nedir ve nasıl çalışır?",
        "systemd nedir ve ne işe yarar?",
        "TCP ile UDP arasındaki fark nedir?",
        "Swap alanı nedir ve ne zaman kullanılır?",
        "Windows'ta Event Viewer nedir?",
        "Cron nedir ve nasıl çalışır?",
    ],
}
PAIRS = {
    "virt": [
        ("office vCenter'da kaç VM var mı?", "ZZ-FAKE-vCenter'da kaç VM var?"),
        ("Kaç VM açık?", "Kaç VM kapalı?"),
        ("ZZ-FAKE-OpenShift'te kaç VM kapalı?", "office vCenter'da kaç VM kapalı?"),
    ],
    "ocp": [
        ("OpenShift'te kaç node var?", "OpenShift'te kaç pod var?"),
        ("OpenShift'te kaç namespace var?", "ZZ-FAKE-OpenShift'te kaç namespace var?"),
    ],
    "admin": [
        ("Kaç Linux sunucusu var?", "Kaç Windows sunucusu var?"),
        ("Kaç VM var?", "Kaç sunucu var?"),
        ("Kaç sunucu açık?", "Kaç sunucu kapalı?"),
        ("Kaç sunucu çalışıyor?", "Kaç sunucu çalışmıyor?"),
    ],
}


def _ask(mod, token, q, sessions):
    r = client.ask(mod, token, q, None, timeout=420)
    if r.get("session_id"):
        sessions.append(r["session_id"])
    return r


def run(mod, rounds, out, pairs=True):
    token = client.login()
    sessions = []
    res = {"module": mod, "rounds": []}
    for rd in range(1, rounds + 1):
        row = {"round": rd, "concept": [], "pairs": []}
        for q in CONCEPT[mod]:
            a = _ask(mod, token, q, sessions)
            b = _ask(mod, token, q, sessions)
            row["concept"].append({
                "q": q, "first_cache": bool(a.get("from_cache")), "first_s": a.get("wall_s"),
                "second_cache": bool(b.get("from_cache")), "second_s": b.get("wall_s"),
                "same_answer": (a.get("answer") or "").strip() == (b.get("answer") or "").strip(),
                "err": a.get("error") or b.get("error"),
            })
            c = row["concept"][-1]
            print(f"[{mod} r{rd}] {q[:46]:46} 1:{'HIT' if c['first_cache'] else 'MISS'} {c['first_s']}s  2:{'HIT' if c['second_cache'] else 'MISS'} {c['second_s']}s", flush=True)
        for q1, q2 in (PAIRS[mod] if pairs else []):
            a = _ask(mod, token, q1, sessions)
            b = _ask(mod, token, q2, sessions)
            row["pairs"].append({
                "q1": q1, "q2": q2, "q1_cache": bool(a.get("from_cache")), "q2_cache": bool(b.get("from_cache")),
                "wrong_hit": bool(b.get("from_cache")), "a1": (a.get("answer") or "")[:160], "a2": (b.get("answer") or "")[:160],
            })
            p = row["pairs"][-1]
            print(f"[{mod} r{rd}] PAIR wrong_hit={p['wrong_hit']} | {q1[:34]} -> {q2[:34]}", flush=True)
        res["rounds"].append(row)
    try:
        token = client.login()
        for sid in sessions:
            client.delete_session(mod, token, sid)
    except Exception as e:
        print("temizlik uyarı:", e, flush=True)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(f"{out}-{mod}.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


def summarize(res):
    hit2 = miss1 = hit1 = n = wrong = pairs = 0
    t_hit, t_miss = [], []
    for rd in res["rounds"]:
        for c in rd["concept"]:
            n += 1
            hit1 += c["first_cache"]
            hit2 += c["second_cache"]
            (t_hit if c["second_cache"] else t_miss).append(c["second_s"] or 0)
            if not c["first_cache"]:
                t_miss.append(c["first_s"] or 0)
        for p in rd["pairs"]:
            pairs += 1
            wrong += p["wrong_hit"]
    return {
        "module": res["module"], "concept_asks": n, "second_hit_rate": round(hit2 / n, 2) if n else None,
        "first_hit_rate": round(hit1 / n, 2) if n else None,
        "hit_p50_s": round(st.median(t_hit), 2) if t_hit else None,
        "miss_p50_s": round(st.median(t_miss), 2) if t_miss else None,
        "pairs": pairs, "wrong_hits": wrong,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="all")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--out", default="/tmp/chat-bench/s9-cache")
    ap.add_argument("--skip-pairs", action="store_true", help="yalnız kavramsal tekrar (yüksüz HIT süresi ölçümü)")
    a = ap.parse_args()
    mods = ["virt", "ocp", "admin"] if a.module == "all" else [a.module]
    for m in mods:
        print(json.dumps(summarize(run(m, a.rounds, a.out, pairs=not a.skip_pairs)), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
