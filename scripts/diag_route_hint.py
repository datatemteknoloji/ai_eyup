#!/usr/bin/env python3
"""Route-hint teşhisi: çeşitli sorularla hint LLM'ini çağırır, HAM çıktıyı kaydeder.

Adım 3 / Parça 2C: "hint'in uygulandığı tüm sorular aynı linux+vcenter planını veriyor" bulgusunu
(şablondaki örnek yanıtı kopyalama şüphesi) ölçmek için. Uygulamadaki çağrıyla aynı istem/limitler
kullanılır (`route_llm_hint` içindeki aynı fonksiyonlar); fark: `skip_if_busy=False` (teşhis sırasıdır).

Kullanım (backend konteyneri içinde):
    docker cp scripts/diag_route_hint.py server_management_backend:/tmp/diag_route_hint.py
    docker exec server_management_backend python /tmp/diag_route_hint.py --tag before [--extra]

Çıktı: /tmp/hint-diag-<tag>.json + stdout özeti. Her soru ~1 sn; toplam ≤ 17 LLM çağrısı.
Uygulama verisine yazmaz (yalnız LLM çağrısı + llm_activity kaydı).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter

sys.path.insert(0, "/app")

# (grup, soru) — 12 çeşitli soru: 4 Windows, 3 virt, 2 openshift, 1 exadata, 2 linux
QUESTIONS = [
    ("windows", "Winserver01 çalışıyor mu?"),
    ("windows", "IIS servisi neden durdu, Windows event log'larında ne var?"),
    ("windows", "Active Directory domain controller replikasyon sorunu var mı?"),
    ("windows", "Windows sunucuda C: diski ne kadar dolu?"),
    ("virt", "Hangi ESXi host'ta CPU yükü yüksek?"),
    ("virt", "Snapshot'ı olan VM'ler hangileri?"),
    ("virt", "Datastore doluluk oranı kritik olanları listele"),
    ("openshift", "CrashLoopBackOff durumundaki pod'lar hangileri?"),
    ("openshift", "Cluster node'larının durumu nasıl?"),
    ("exadata", "Exadata cell disk durumu ve smart scan performansı nasıl?"),
    ("linux", "Linux sunucuda load average neden yüksek?"),
    ("linux", "systemd'de failed olan servisler var mı?"),
]
# Canlı bench'te gözlenen hint'li sorular (a14 ayrıca yukarıda)
EXTRA = [
    ("bench:a16", "Şu an kaç iş çalışıyor?"),
    ("bench:a22", "Şirketin aylık altyapı maliyeti ne kadar?"),
    ("bench:a25", "OpenShift'te hiç sorunlu pod yok, değil mi?"),
    ("bench:a27", "Bunların hepsi Ready mi?"),
]


def _prompt_for(rh, message, plan):
    fn = getattr(rh, "build_hint_prompt", None)
    if fn:
        return fn(message, plan)
    prompt = rh._USER_TMPL.format(
        question=(message or "")[:800],
        modules=list(plan.modules or ()),
        reason=plan.reason,
        conf=float(plan.confidence or 0),
    )
    return rh._SYSTEM, prompt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="run")
    ap.add_argument("--extra", action="store_true", help="bench'te görülen 4 ek soru")
    args = ap.parse_args()

    from app.services import route_llm_hint as rh
    from app.services.llm_gateway import active_model_label, generate_sync, resolve_model_for_tier
    from app.services.module_orchestrator import plan_modules

    # Uygulama süreçleri OLLAMA_DEFAULT_MODEL'i DB'deki aktif modele eşitler; bu betik ayrı süreçtir,
    # eşitlemeden hint .env varsayılanına (llama3.2:3b) giderdi ve sunucuda yanlış modeli yüklerdi.
    active_model_label()
    model, _tier = resolve_model_for_tier("fast", None)
    num_predict, think = rh._hint_limits()
    qs = QUESTIONS + (EXTRA if args.extra else [])
    print(f"model={model} num_predict={num_predict} think={think} sorular={len(qs)}")

    rows = []
    for grp, q in qs:
        plan = plan_modules(q)
        system, prompt = _prompt_for(rh, q, plan)
        t0 = time.perf_counter()
        data = generate_sync(
            model=model,
            prompt=prompt,
            system=system,
            options={"temperature": 0.0, "num_predict": num_predict},
            think=think,
            timeout=rh._timeout_sec(),
            best_effort=True,
        )
        dur = time.perf_counter() - t0
        raw = (data.get("response") or "").strip()
        hinted = rh.parse_hinted_modules(raw) if raw else ()
        merged = rh.merge_route_hint(plan, hinted, q) if hinted else plan
        rows.append({
            "group": grp, "q": q,
            "kw_modules": list(plan.modules or ()), "kw_reason": plan.reason,
            "kw_conf": float(plan.confidence or 0),
            "would_ask": rh.should_ask_route_hint(plan),
            "raw": raw[:300], "hinted": list(hinted),
            "merged_modules": list(merged.modules or ()), "merged_reason": merged.reason,
            "duration_s": round(dur, 2),
            "error": str(data.get("error") or "")[:120] or None,
            "done_reason": data.get("done_reason"),
            "eval_count": data.get("eval_count"),
        })
        r = rows[-1]
        print(f"[{grp:9}] {q[:52]:52} kw={r['kw_modules']}/{r['kw_conf']:.2f} ask={r['would_ask']!s:5} "
              f"→ hint={r['hinted']} merged={r['merged_modules']} {r['duration_s']}s"
              + (f" ERR={r['error']}" if r["error"] else ""))

    distinct_raw = Counter(tuple(r["hinted"]) for r in rows)
    print("\nFarklı hint çıktısı sayısı:", len(distinct_raw), dict(distinct_raw))
    win = [r for r in rows if r["group"] == "windows"]
    print("Windows sorularında hint'te 'windows' geçen:", sum("windows" in r["hinted"] for r in win), "/", len(win))
    out = f"/tmp/hint-diag-{args.tag}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"model": model, "num_predict": num_predict, "think": think, "rows": rows}, fh,
                  ensure_ascii=False, indent=1)
    print("kaydedildi:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
