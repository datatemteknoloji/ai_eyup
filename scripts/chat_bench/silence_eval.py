"""Adım 10 — ilk token öncesi sessizlik ölçümü (progress açık/kapalı).

  cd /dttadvance/app && python3 -m scripts.chat_bench.silence_eval --module all --tag on  --out /tmp/chat-bench/s10
  python3 -m scripts.chat_bench.silence_eval --module all --tag off --progress off   # ayarı geçici kapatır, bitince eski değere döner

Her soru YENİ oturumda bir kez sorulur (veri/araç soruları — cache'e girmez). Çıktı: ilk token süresi, ilk token ÖNCESİ en uzun
olay boşluğu (`max_pre_token_gap_s`), ilerleme olayı sayısı/adımları. Oturumlar sonunda silinir.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import subprocess
import sys
import time

from . import client

Q = {
    "virt": ["En çok CPU kullanan 5 VM hangileri ve neden yüksek olabilir?", "Hangi datastore'lar dolmak üzere ve ne yapılmalı?"],
    "ocp": ["OpenShift'te hangi pod'lar restart etmiş, nedenini yorumla", "OpenShift node'larının durumu nasıl, sorun var mı?"],
    "admin": ["Hangi Linux sunucularında disk doluluğu yüzde 80 üzerinde? Nedenini de yorumla", "En çok CPU kullanan 5 VM hangileri ve neden yüksek olabilir?"],
}


def _setting(key: str, value) -> None:
    code = (
        "from app.core.database import SessionLocal;from app.services import runtime_settings as r;"
        f"d=SessionLocal();r.save_advanced_settings({{'{key}': {value!r}}}, d);d.close();r.invalidate_cache()"
    )
    subprocess.run(["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app", "server_management_backend", "python", "-c", code], check=True, capture_output=True)


def run(mod: str, out: str, tag: str):
    token = client.login()
    rows, sessions = [], []
    for q in Q[mod]:
        r = client.ask(mod, token, q, None, timeout=420)
        if r.get("session_id"):
            sessions.append(r["session_id"])
        rows.append({
            "q": q, "wall_s": r.get("wall_s"), "first_token_s": r.get("first_token_s"),
            "max_pre_token_gap_s": r.get("max_pre_token_gap_s"), "progress_n": r.get("progress_n"),
            "progress_steps": r.get("progress_steps"), "error": r.get("error"), "tools": r.get("tools"),
        })
        print(f"[{mod}/{tag}] ttft={r.get('first_token_s')}s max_pre_token_gap={r.get('max_pre_token_gap_s')}s progress_n={r.get('progress_n')} steps={r.get('progress_steps')} | {q[:50]}", flush=True)
    try:
        token = client.login()
        for sid in sessions:
            client.delete_session(mod, token, sid)
    except Exception:
        pass
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(f"{out}-{tag}-{mod}.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="all")
    ap.add_argument("--tag", default="on")
    ap.add_argument("--out", default="/tmp/chat-bench/s10")
    ap.add_argument("--progress", default="", help="on|off — ayarı geçici değiştirir, bitince varsayılana (on) döner")
    a = ap.parse_args()
    mods = ["virt", "ocp", "admin"] if a.module == "all" else [a.module]
    if a.progress:
        _setting("chat_progress_enabled", a.progress == "on")
        time.sleep(20)
    try:
        for m in mods:
            run(m, a.out, a.tag)
    finally:
        if a.progress:
            _setting("chat_progress_enabled", True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
