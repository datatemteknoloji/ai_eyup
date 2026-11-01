"""Adım 13 (k) — eşzamanlılık yük bench'i: N aynı anda soru (her biri YENİ oturum) → tamamlanma/hata/kapı bekleme/TTFT/toplam süre.

  cd /dttadvance/app && python3 -m scripts.chat_bench.concurrency_eval --module admin --n 1,3,6,12 --out /tmp/chat-bench/s13
  python3 -m scripts.chat_bench.concurrency_eval --n 6 --gate 3          # kapı sınırını bu koşu için geçici ayarla (bitince eski değer)

Notlar
- Tek admin hesabı kullanıldığı için `chat_user_max_active_turns` koşu boyunca 0'a (kapalı) alınır ve BİTİNCE eski değerine döner;
  kullanıcı limiti ayrıca `--user-limit-check` ile (aynı kullanıcıdan 3 eşzamanlı → 3.'ncü 429) doğrulanır.
- Her soru cache'e girmesin diye farklı sorulur (modül başına havuz + sıra no). Oturumlar sonunda silinir.
- Kapı bekleme süresi `debug_trace` içindeki `paths[kind=gate].wait_ms` alanından okunur (admin hesabı).
- «İlk başarısız N»: hata/zaman aşımı oluşan en küçük N (yoksa «yok»).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import subprocess
import sys
import threading
import time
import urllib.request

from . import client

_M = ["disk doluluğu yüzde 70 üzerinde", "bellek kullanımı yüzde 85 üzerinde", "CPU kullanımı yüzde 60 üzerinde",
      "swap kullanımı yüzde 30 üzerinde", "disk doluluğu yüzde 90 üzerinde", "bellek kullanımı yüzde 70 üzerinde",
      "CPU kullanımı yüzde 80 üzerinde", "load average 2 üzerinde", "disk doluluğu yüzde 60 üzerinde",
      "bellek kullanımı yüzde 95 üzerinde", "CPU kullanımı yüzde 40 üzerinde", "swap kullanımı yüzde 10 üzerinde"]
# «Hangi Linux sunucularında … ? Nedenini de yorumla» → yorum istendiği için envanter/QA erken çıkışına DÜŞMEZ,
# ajan yoluna (LLM çok adımlı) gider: kapıyı ve LLM semaforunu gerçekten yükler. (Düz «En çok CPU… hangileri?» envanter tablosuyla LLM'siz biter.)
POOL = {
    "admin": [f"Hangi Linux sunucularında {m}? Nedenini de yorumla" for m in _M],
    "virt": [q + " Nedenini yorumla ve öneri ver." for q in [
        "En çok CPU kullanan 5 VM hangileri?",
        "Hangi datastore'lar dolmak üzere?",
        "En çok bellek kullanan 5 VM hangisi?",
        "Kapalı durumdaki VM'ler hangileri?",
        "Snapshot'ı olan VM'ler hangileri?",
        "Hangi ESXi host'ları en yüklü?",
        "En büyük diskli 5 VM hangisi?",
        "Hangi VM'ler uzun süredir açık?",
        "Cluster bazında VM dağılımı nasıl?",
        "Düşük kaynak kullanan boşta VM'ler hangileri?",
        "Datastore doluluk oranlarını sırala",
        "CPU overcommit riski olan host var mı?",
    ]],
}


def _py(code: str) -> str:
    r = subprocess.run(
        ["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app", "server_management_backend", "python", "-c", code],
        check=True, capture_output=True, text=True,
    )
    return r.stdout.strip()


def _get_setting(key: str):
    out = _py(
        "import json;from app.services import runtime_settings as r;"
        f"print(json.dumps(r.get_setting({key!r})))"
    )
    return json.loads(out.splitlines()[-1])


def _set_setting(key: str, value) -> None:
    _py(
        "from app.core.database import SessionLocal;from app.services import runtime_settings as r;"
        f"d=SessionLocal();r.save_advanced_settings({{{key!r}: {value!r}}}, d);d.close();r.invalidate_cache()"
    )


def _pct(vals, p):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round(p / 100.0 * (len(vals) - 1)))))
    return round(vals[k], 1)


def _gate_wait_ms(r):
    for p in ((r.get("trace") or {}).get("paths") or []):
        if p.get("kind") == "gate":
            return p.get("wait_ms"), p.get("lane")
    return None, None


def _metrics() -> dict:
    try:
        with urllib.request.urlopen(client.api_base().replace("/api/v1", "") + "/metrics/chat-gate", timeout=10) as r:
            txt = r.read().decode()
    except Exception:
        return {}
    out = {}
    for ln in txt.splitlines():
        if ln.startswith("#") or " " not in ln:
            continue
        k, v = ln.rsplit(" ", 1)
        try:
            out[k] = float(v)
        except ValueError:
            pass
    return out


def run_n(mod: str, n: int, token: str, base_idx: int, timeout: int):
    pool = POOL[mod]
    results = [None] * n
    barrier = threading.Barrier(n)

    def worker(i):
        q = pool[(base_idx + i) % len(pool)]
        barrier.wait()
        results[i] = (q, client.ask(mod, token, q, None, timeout=timeout))

    ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    t0 = time.perf_counter()
    for t in ths:
        t.start()
    peak_q = 0
    while any(t.is_alive() for t in ths):
        m = _metrics()
        peak_q = max(peak_q, int(m.get("ainew_chat_gate_queue_len", 0)))
        time.sleep(1.0)
    for t in ths:
        t.join()
    wall = round(time.perf_counter() - t0, 1)
    rows, sessions = [], []
    for q, r in results:
        w_ms, lane = _gate_wait_ms(r)
        if r.get("session_id"):
            sessions.append(r["session_id"])
        rows.append({
            "q": q, "error": r.get("error"), "wall_s": r.get("wall_s"), "ttft_s": r.get("first_token_s"),
            "gate_wait_s": round(w_ms / 1000.0, 1) if w_ms is not None else None, "lane": lane,
            "answer_chars": len(r.get("answer") or ""),
        })
    return rows, wall, peak_q, sessions


def summarize(n: int, rows, wall, peak_q):
    ok = [r for r in rows if not r["error"] and r["answer_chars"] > 0]
    errs = [r["error"] or "boş cevap" for r in rows if r["error"] or r["answer_chars"] == 0]
    return {
        "n": n, "completed": len(ok), "errors": len(errs), "error_kinds": sorted(set(errs)),
        "gate_wait_p50_s": _pct([r["gate_wait_s"] for r in ok], 50), "gate_wait_p95_s": _pct([r["gate_wait_s"] for r in ok], 95),
        "ttft_p50_s": _pct([r["ttft_s"] for r in ok], 50), "ttft_p95_s": _pct([r["ttft_s"] for r in ok], 95),
        "total_p50_s": _pct([r["wall_s"] for r in ok], 50), "total_p95_s": _pct([r["wall_s"] for r in ok], 95),
        "batch_wall_s": wall, "peak_queue": peak_q,
    }


def user_limit_check(token: str) -> dict:
    """Aynı kullanıcıdan 3 eşzamanlı tur: limit=2 ise 3. istek HTTP 429 + Türkçe mesaj almalı."""
    import urllib.error

    outs = []

    def one(i):
        req = urllib.request.Request(
            client.api_base() + "/unified-chat/stream",
            data=json.dumps({"message": POOL["admin"][i]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            first = resp.readline()
            outs.append(("ok", first[:60].decode(errors="replace"), resp))
        except urllib.error.HTTPError as e:
            outs.append((e.code, e.read().decode(errors="replace")[:200], None))

    ths = []
    for i in range(3):
        t = threading.Thread(target=one, args=(i,), daemon=True)
        t.start()
        ths.append(t)
        time.sleep(0.4)
    for t in ths:
        t.join(timeout=30)
    for _s, _b, resp in outs:           # açık akışları kapat (turlar sunucuda iptal olmaz, kendi bitecek)
        try:
            resp and resp.close()
        except Exception:
            pass
    return {"results": [(a, b) for a, b, _ in outs]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="admin", choices=sorted(POOL))
    ap.add_argument("--n", default="1,3,6,12")
    ap.add_argument("--out", default="/tmp/chat-bench/s13")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--gate", type=int, default=0, help="chat_ai_max_concurrent'ı bu koşu için geçici ayarla (0=dokunma)")
    ap.add_argument("--user-limit-check", action="store_true")
    a = ap.parse_args()

    ns = [int(x) for x in a.n.split(",") if x.strip()]
    restore = {}
    try:
        restore["chat_user_max_active_turns"] = _get_setting("chat_user_max_active_turns")
        if a.gate:
            restore["chat_ai_max_concurrent"] = _get_setting("chat_ai_max_concurrent")
            _set_setting("chat_ai_max_concurrent", a.gate)
        if not a.user_limit_check:
            _set_setting("chat_user_max_active_turns", 0)
        time.sleep(12)   # 2 worker'ın ayar önbelleği
        token = client.login()
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)

        if a.user_limit_check:
            res = user_limit_check(token)
            print("[user-limit]", res, flush=True)
            with open(f"{a.out}-userlimit.json", "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=1)
            return 0

        summary, first_fail, base = [], None, 0
        gate_val = _get_setting("chat_ai_max_concurrent")
        llm_val = _get_setting("llm_max_concurrent")
        for n in ns:
            token = client.login()
            rows, wall, peak_q, sessions = run_n(a.module, n, token, base, a.timeout)
            base += n
            s = summarize(n, rows, wall, peak_q)
            summary.append(s)
            if s["errors"] and first_fail is None:
                first_fail = n
            print(f"[N={n}] ok={s['completed']}/{n} err={s['errors']} gate_wait p50/p95={s['gate_wait_p50_s']}/{s['gate_wait_p95_s']}s "
                  f"ttft p50/p95={s['ttft_p50_s']}/{s['ttft_p95_s']}s total p50/p95={s['total_p50_s']}/{s['total_p95_s']}s "
                  f"batch={wall}s peak_queue={peak_q} {s['error_kinds']}", flush=True)
            with open(f"{a.out}-{a.module}-n{n}.json", "w", encoding="utf-8") as f:
                json.dump({"summary": s, "rows": rows}, f, ensure_ascii=False, indent=1)
            try:
                token = client.login()
                for sid in sessions:
                    client.delete_session(a.module, token, sid)
            except Exception:
                pass
            time.sleep(3)
        print(json.dumps({"gate": gate_val, "llm_max_concurrent": llm_val, "first_failing_n": first_fail or "yok",
                          "summary": summary}, ensure_ascii=False, indent=1))
        with open(f"{a.out}-{a.module}-summary.json", "w", encoding="utf-8") as f:
            json.dump({"gate": gate_val, "llm": llm_val, "first_failing_n": first_fail, "summary": summary}, f, ensure_ascii=False, indent=1)
    finally:
        for k, v in restore.items():
            try:
                _set_setting(k, v)
            except Exception as e:  # geri yükleme başarısızsa kullanıcıya açıkça söyle
                print(f"!! {k} eski değere ({v!r}) döndürülemedi: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    client.TRACE = True
    sys.exit(main())
