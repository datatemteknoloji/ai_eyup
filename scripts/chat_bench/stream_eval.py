"""Adım 14 — canlı akış ölçümü: bir soruyu SSE olay zaman çizelgesiyle sorar.

Kullanım:
  python -m scripts.chat_bench.stream_eval --q "Hangi job'lar hata verdi?" [--target admin] [--n 1]

Çıktı (tur başına): ilk olay / ilk `thinking` / ilk araç / ilk token (sn), cevap tokenlarının yayıldığı süre,
cevap içi en uzun boşluk, token sayısı, düşünme karakteri, kaç `replace_answer`.
Kriter (plan.md Adım 14): cevap tokenları ≥ ~1 sn'ye yayılmalı (tek patlama değil); düşünme açıkken ilk görünür
içerik (thinking ya da token) ilk araç aşamasından önce gelmeli.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

from scripts.chat_bench import client


def run(target: str, message: str, timeout: int = 420) -> dict:
    spec = client.TARGETS[target]
    token = client.login()
    req = urllib.request.Request(
        client.api_base() + spec["path"],
        data=json.dumps(spec["body"](message, None)).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST",
    )
    t0 = time.perf_counter()
    ev = {"first_event": None, "first_thinking": None, "first_tool": None, "first_token": None, "last_token": None,
          "tokens": 0, "thinking_chars": 0, "thinking_events": 0, "replace": 0, "max_token_gap": 0.0, "answer": ""}
    last = None
    sid = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    d = json.loads(line[5:].strip())
                except Exception:
                    continue
                now = time.perf_counter() - t0
                if ev["first_event"] is None:
                    ev["first_event"] = round(now, 2)
                sid = d.get("session_id") or sid
                if d.get("type") == "thinking" and d.get("text"):
                    ev["thinking_events"] += 1
                    ev["thinking_chars"] += len(d["text"])
                    ev["first_thinking"] = ev["first_thinking"] if ev["first_thinking"] is not None else round(now, 2)
                if d.get("type") == "tool_call" and ev["first_tool"] is None:
                    ev["first_tool"] = round(now, 2)
                if d.get("replace_answer"):
                    ev["replace"] += 1
                    ev["answer"] = ""
                if d.get("token"):
                    ev["tokens"] += 1
                    if ev["first_token"] is None:
                        ev["first_token"] = round(now, 2)
                    if last is not None:
                        ev["max_token_gap"] = max(ev["max_token_gap"], round(now - last, 2))
                    last = now
                    ev["last_token"] = round(now, 2)
                    ev["answer"] += d["token"]
    except urllib.error.HTTPError as e:
        ev["error"] = f"HTTP {e.code}"
    ev["total"] = round(time.perf_counter() - t0, 2)
    if ev["first_token"] is not None and ev["last_token"] is not None:
        ev["answer_spread_s"] = round(ev["last_token"] - ev["first_token"], 2)
    if sid:
        try:
            client.delete_session(target, token, sid)
        except Exception:
            pass
    return ev


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True)
    ap.add_argument("--target", default="admin")
    ap.add_argument("--n", type=int, default=1)
    a = ap.parse_args()
    for i in range(a.n):
        r = run(a.target, a.q)
        ans = r.pop("answer")
        print(json.dumps(r, ensure_ascii=False))
        print("   cevap:", ans[:200].replace("\n", " "))


if __name__ == "__main__":
    main()
