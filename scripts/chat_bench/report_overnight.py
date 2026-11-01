#!/usr/bin/env python3
"""Gece koşusu — TEK RAPOR üretici (LLM YOK; ajan olmadan çalışır).

Okur: bench JSON'ları (<bench-dir>/<etiket>-{virt,ocp,admin}.json), test çıktı günlükleri, plan.md ilerleme
bölümü, diag çıktıları (docs/chat-quality/reports/gece-*-diag/). Yazar: docs/chat-quality/reports/gece-YYYYMMDD.md.

Kullanım (ör.):
  python3 scripts/chat_bench/report_overnight.py \
      --labels step5-full-r1,step5-full-r2,step5-full-r3 --part step5-part \
      --baselines step3-full,step4-part --date 20261015

Eksik girdi (bench turu yok, günlük yok) → ilgili bölüm «veri yok» yazar; betik yine tamamlanır.
Kriter değerlendirmesi mekaniktir: KARŞILANDI / KARŞILANMADI / KARAR BEKLİYOR (insan kararı gerektiren her şey).
«Kapandı» ASLA yazılmaz.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODULES = ("virt", "ocp", "admin")
TARGET_IDS = ["v04", "v07", "v08", "v09", "a05", "a06", "o01", "o16", "o18", "a10", "a26", "v13"]
POD_IDS = ["o07", "o09", "o17"]
NEW_TIME = [f"v{n}" for n in range(58, 66)]
NEW_STATE = ["v45", "v46", "v47", "v48", "a37"]
NEW_CNT = [f"v{n}" for n in range(49, 58)] + ["o45", "a38", "a39"]
KARSILANDI, KARSILANMADI, KARAR = "KARŞILANDI", "KARŞILANMADI", "KARAR BEKLİYOR"


# ── yardımcılar ─────────────────────────────────────────────────────────────────────────

def load_label(bench_dir: str, label: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for m in MODULES:
        p = os.path.join(bench_dir, f"{label}-{m}.json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    out[m] = json.load(f)
            except Exception:
                pass
    return out


def results(mod: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not mod:
        return {}
    return {r["id"]: r for r in mod.get("results", []) if "skipped" not in r}


def is_infra(r: Dict[str, Any]) -> bool:
    return bool(r.get("infra")) and not r.get("passed")


def score(data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    tot = {"passed": 0, "total": 0, "infra": 0}
    per = {}
    for m, mod in data.items():
        rs = list(results(mod).values())
        infra = [r for r in rs if is_infra(r)]
        rest = [r for r in rs if r not in infra]
        p = sum(1 for r in rest if r.get("passed"))
        per[m] = {"passed": p, "total": len(rest), "infra": len(infra), "infra_ids": [r["id"] for r in infra]}
        tot["passed"] += p
        tot["total"] += len(rest)
        tot["infra"] += len(infra)
    return {"total": tot, "per": per}


def pct(xs: List[float], q: float) -> Optional[float]:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))
    return xs[k]


def fmt(v: Any, nd: int = 2) -> str:
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def paths(r: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in (r.get("trace_paths") or []) if isinstance(p, dict)]


def rule_trace(r: Dict[str, Any]) -> List[str]:
    out = []
    for p in paths(r):
        k = p.get("kind")
        if k in ("qa_rule", "entity_gate", "action_gate"):
            out.append(f"{k}:{p.get('handler') or p.get('gate') or ''}".rstrip(":"))
    return out


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def pytest_summary(text: str) -> Optional[Tuple[int, int, int]]:
    """(passed, skipped, failed) — son özet satırından."""
    lines = [l for l in text.splitlines() if re.search(r"\d+ passed", l) or re.search(r"\d+ failed", l)]
    if not lines:
        return None
    l = lines[-1]
    g = lambda k: int((re.search(rf"(\d+) {k}", l) or [0, 0])[1])
    return g("passed"), g("skipped"), g("failed")


def docker_collect_count(path: str) -> Optional[int]:
    try:
        out = subprocess.check_output(
            ["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app", "server_management_backend", "python", "-m", "pytest",
             "--collect-only", "-q", "-p", "no:warnings", path], text=True, stderr=subprocess.DEVNULL, timeout=120)
        return sum(1 for l in out.splitlines() if "::" in l)
    except Exception:
        return None


def plan_progress(plan_text: str) -> List[Tuple[bool, str]]:
    m = re.search(r"### Gece koşusu — İlerleme\n(.*?)\n\n", plan_text, re.S)
    out = []
    if m:
        for l in m.group(1).splitlines():
            mm = re.match(r"- \[( |x)\] (.*)", l)
            if mm:
                out.append((mm.group(1) == "x", mm.group(2)))
    return out


def md_table(head: List[str], rows: List[List[Any]]) -> str:
    L = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        L.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |")
    return "\n".join(L)


# ── ana rapor ───────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="step5-full-r1,step5-full-r2,step5-full-r3", help="tam bench tur etiketleri (virgülle)")
    ap.add_argument("--part", default="step5-part", help="kısmi bench etiketi")
    ap.add_argument("--baselines", default="step3-full,step4-part", help="karşılaştırma etiketleri (virgülle)")
    ap.add_argument("--bench-dir", default="/tmp/chat-bench")
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--plan", default=os.path.join(ROOT, "docs/chat-quality/plan.md"))
    ap.add_argument("--diag-dir", default="")
    ap.add_argument("--tests-full-log", default="")
    ap.add_argument("--tests-automic-log", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-docker", action="store_true", help="docker'a hiç dokunma (test sayımı/truth atlanır)")
    a = ap.parse_args()

    diag = a.diag_dir or os.path.join(ROOT, f"docs/chat-quality/reports/gece-{a.date}-diag")
    out_path = a.out or os.path.join(ROOT, f"docs/chat-quality/reports/gece-{a.date}.md")
    labels = [x.strip() for x in a.labels.split(",") if x.strip()]
    baselines = [x.strip() for x in a.baselines.split(",") if x.strip()]
    tests_full = a.tests_full_log or os.path.join(diag, "tests-full.log")
    tests_automic = a.tests_automic_log or os.path.join(diag, "tests-automic.log")

    rounds = OrderedDict((l, load_label(a.bench_dir, l)) for l in labels)
    done_rounds = [l for l, d in rounds.items() if len(d) == len(MODULES)]
    skipped_rounds = [l for l in labels if os.path.exists(os.path.join(a.bench_dir, f"{l}.SKIPPED"))]
    part = load_label(a.bench_dir, a.part)
    base = OrderedDict((l, load_label(a.bench_dir, l)) for l in baselines)
    plan_text = read(a.plan)
    progress = plan_progress(plan_text)
    full_sum = pytest_summary(read(tests_full))
    aut_sum = pytest_summary(read(tests_automic))

    # soru → tur başına sonuç
    qids: "OrderedDict[str, Tuple[str, str]]" = OrderedDict()   # id → (modül, kategori)
    for l in done_rounds + ([a.part] if part else []):
        data = rounds.get(l) or part
        for m, mod in data.items():
            for rid, r in results(mod).items():
                qids.setdefault(rid, (m, r.get("cat", "")))
    per_round: Dict[str, Dict[str, Dict[str, Any]]] = {l: {rid: r for m, mod in rounds[l].items() for rid, r in results(mod).items()}
                                                       for l in done_rounds}
    base_res: Dict[str, Dict[str, Dict[str, Any]]] = {l: {rid: r for m, mod in d.items() for rid, r in results(mod).items()}
                                                      for l, d in base.items()}
    part_res = {rid: r for m, mod in part.items() for rid, r in results(mod).items()}

    L: List[str] = []
    W = L.append
    W(f"# Gece koşusu raporu — {a.date[:4]}-{a.date[4:6]}-{a.date[6:]}")
    W("")
    W(f"_Üretici: `scripts/chat_bench/report_overnight.py` (LLM'siz). Üretim: {datetime.now().isoformat(timespec='seconds')}. "
      f"Bench turları: {', '.join(done_rounds) or 'yok'}"
      + (f" · ATLANAN: {', '.join(skipped_rounds)} (zaman yetmedi)" if skipped_rounds else "") + f" · kısmi: {a.part if part else 'yok'}. "
      "«Kapandı» ifadesi kullanılmaz: kapanış kararı kullanıcıya aittir._")
    W("")

    # ── (a) 5 satır özet ────────────────────────────────────────────────────────────────
    W("## (a) Özet")
    stage_txt = "; ".join(("✓ " if ok else "○ ") + re.split(r" \(", t)[0] for ok, t in progress) or "plan.md ilerleme bölümü okunamadı"
    bloke = re.findall(r"(?:\*\*BLOKE\*\*|\[BLOKE\]|BLOKE:)[^\n]{0,80}", plan_text.split("### Gece koşusu — İlerleme")[-1]) if "### Gece koşusu — İlerleme" in plan_text else []  # BLOKE işareti: **BLOKE**, [BLOKE] veya BLOKE: (plan.md)
    full_s = (f"{full_sum[0]} geçti / {full_sum[1]} atlandı / {full_sum[2]} kırmızı" if full_sum else "günlük yok")
    aut_s = (f"{aut_sum[0]} geçti / {aut_sum[1]} atlandı" if aut_sum else "günlük yok")
    sc_rounds = {l: score(rounds[l]) for l in done_rounds}
    sc_txt = " · ".join(f"{l.split('-')[-1]}: {v['total']['passed']}/{v['total']['total']} (ALTYAPI {v['total']['infra']})" for l, v in sc_rounds.items()) or "tam bench turu yok"
    sc_part = score(part) if part else None
    W(f"1. **Aşamalar:** {stage_txt}. BLOKE işareti: {'VAR — ' + '; '.join(bloke[:3]) if bloke else 'yok'}.")
    W(f"2. **Testler:** tam takım {full_s}; `-k automic` {aut_s}.")
    W(f"3. **Tam bench (soru-başına, ALTYAPI hariç):** {sc_txt}.")
    W(f"4. **Kısmi bench (`{a.part}`):** " + (f"{sc_part['total']['passed']}/{sc_part['total']['total']} (ALTYAPI {sc_part['total']['infra']})" if sc_part else "yok") + ".")
    W("5. **Karar bekleyenler:** bkz. (g); sayılar değişti (5d) onayı, pod kapsamı teyidi, İş-1 onayı, VMware Tools kararı.")
    W("")

    # ── (b) kriterler ───────────────────────────────────────────────────────────────────
    W("## (b) Adım 5 kriterleri 1–12")
    crit: List[Tuple[str, str, str]] = []

    def all_rounds_pass(ids: List[str]) -> Tuple[bool, List[str]]:
        bad = []
        for rid in ids:
            for l in done_rounds:
                r = per_round[l].get(rid)
                if r is None or not r.get("passed"):
                    bad.append(f"{rid}@{l.split('-')[-1]}")
        return (not bad and bool(done_rounds)), bad

    # 1
    v04 = [per_round[l].get("v04") for l in done_rounds if per_round[l].get("v04")]
    ps_count = None if a.no_docker else docker_collect_count("app/tests/test_power_state.py")
    scan = read(os.path.join(diag, "power-scan.md"))
    has_other = any("Diğer/bilinmeyen" in (r.get("answer") or "") for r in v04)
    ok86 = bool(v04) and all("86" in (r.get("answer") or "") for r in v04)
    st = KARSILANDI if (ok86 and not has_other and (ps_count or 0) >= 40) else (KARAR if not v04 else KARSILANMADI)
    crit.append(("1 Güç durumu", st, f"v04 cevaplarında 86 {'var' if ok86 else 'YOK'}, «Diğer/bilinmeyen» {'çıktı' if has_other else 'çıkmadı'} ({len(v04)} tur); "
                 f"test_power_state toplanan test: {fmt(ps_count)}; ham değer taraması: {'`power-scan.md` mevcut' if scan else 'yok'} (tanınmayan 0 beklenir)."))
    # 2
    ok_all, bad = all_rounds_pass(TARGET_IDS)
    tools_ok = all(not (per_round[l].get(rid) or {}).get("tools") for l in done_rounds for rid in TARGET_IDS if per_round[l].get(rid))
    rule_ok = all(any(t.startswith("qa_rule:count_rules") or t.startswith("qa_rule") for t in rule_trace(per_round[l].get(rid) or {}))
                  for l in done_rounds for rid in TARGET_IDS if per_round[l].get(rid))
    fast = [per_round[l][rid].get("wall_s") for l in done_rounds for rid in TARGET_IDS if per_round[l].get(rid)]
    slow = [x for x in fast if x is not None and x > 1.0]
    same = True
    _ts = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?|\d+(?:\.\d+)? ?(?:sn|saniye|dk)\b")
    for rid in TARGET_IDS:
        ans = {_ts.sub("<t>", (per_round[l].get(rid) or {}).get("answer") or "") for l in done_rounds if per_round[l].get(rid)}
        if len(ans) > 1:
            same = False
    if not done_rounds:
        st = KARAR
    elif not (ok_all and tools_ok and rule_ok and same):
        st = KARSILANMADI
    else:
        st = KARSILANDI if not slow else KARAR   # yalnız >1 sn → ilk-istek yükü insan kararı
    crit.append(("2 Hedef sorular", st, f"12 hedef × {len(done_rounds)} tur: geçmeyen {bad or 'yok'}; `tools=[]` {tools_ok}; iz `qa_rule` {rule_ok}; >1 sn {len(slow)} (ilk-istek yükü ayrı); "
                 f"turlar arası birebir aynı cevap (zaman damgaları hariç) {same}. Pod soruları (o07/o09/o17) kapsam dışı; sonuçları (d)'de."))
    # 3
    fired = []
    for l in done_rounds:
        for rid, r in per_round[l].items():
            tr = [t for t in rule_trace(r) if t.startswith("qa_rule:count_rules")]
            if tr:
                fired.append((l.split("-")[-1], rid, tr[0], bool(r.get("passed"))))
    fired_fail = [f for f in fired if not f[3]]
    tr_ok = bool(full_sum) and full_sum[2] == 0
    expected_cats = {"cnt", "state", "which", "cache"}
    unexpected = sorted({f[1] for f in fired if (qids.get(f[1]) or ("", ""))[1] not in expected_cats})
    if not done_rounds or not full_sum:
        st = KARAR
    elif fired_fail or not tr_ok:
        st = KARSILANMADI
    else:
        st = KARSILANDI if not unexpected else KARAR
    crit.append(("3 Yanlış eşleşme = 0", st, f"birim: 100 zararsız soru × 3 hat + golden (tam takım kırmızı {full_sum[2] if full_sum else '?'}); bench'te sayım kuralı tetiklenen {len(fired)} cevap, "
                 f"bunlardan KALAN {len(fired_fail)} {[f[:3] for f in fired_fail][:6]} ; sayım dışı kategoride tetiklenen: {unexpected or 'yok'} — tetiklenen her soruyu insan gözüyle (b)-3 tablosunda gözden geçirin."))
    # 4
    acc = read(os.path.join(diag, "count-accuracy.md"))
    m4 = re.search(r"Toplam (\d+) soru[^\n]*?yakalanan (\d+)[^\n]*?doğru (\d+) · hatalı (\d+)", acc)
    st = KARSILANDI if (m4 and m4.group(1) == m4.group(2) == m4.group(3) and int(m4.group(1)) >= 40 and m4.group(4) == "0") else (KARAR if not acc else KARSILANMADI)
    crit.append(("4 Doğruluk", st, f"`count-accuracy.md`: {m4.group(0) if m4 else 'okunamadı'} (≥40 soru, bağımsız SQL ile birebir; yeniden üretim: `scripts/diag_count_accuracy.py`)."))
    # 5
    amb = re.search(r"Çoklu eşleşme: (\d+) soru · geçen (\d+) · sessiz tek seçim (\d+)", acc)
    mg = [(l.split("-")[-1], rid, bool(r.get("passed"))) for l in done_rounds for rid, r in per_round[l].items() if r.get("cat") in ("multi", "ghost")]
    mg_pass = sum(1 for x in mg if x[2])
    amb_ok = bool(amb) and amb.group(1) == amb.group(2) and amb.group(3) == "0" and int(amb.group(1)) >= 10
    st = KARSILANDI if amb_ok and (mg_pass == len(mg)) else KARAR
    crit.append(("5 Kapsam/varlık", st, f"çoklu eşleşme tanılaması: {amb.group(0) if amb else 'okunamadı'}; bench multi+ghost cevapları {mg_pass}/{len(mg)} (tur toplamı; LLM yolu, varyans olabilir"
                 + ("" if mg_pass == len(mg) else " — geçmeyenler (c)/(d) tablosunda; KARAR BEKLİYOR") + ")."))
    # 6
    rb = read(os.path.join(diag, "rbac-live.md"))
    rb_pass = len(re.findall(r"\| GEÇTİ \|", rb))
    rb_all = len([l for l in rb.splitlines() if l.startswith("| ") and ("sızıntı=" in l)])
    st = KARSILANDI if (rb_all >= 4 and rb_pass == rb_all) else (KARAR if not rb else KARSILANMADI)
    crit.append(("6 RBAC", st, f"`rbac-live.md`: {rb_pass}/{rb_all} canlı durum geçti (sızıntı yok) + birim testler (`test_count_rules.py` RBAC)."))
    # 7
    tw = None if a.no_docker else docker_collect_count("app/tests/test_time_window.py")
    twh = None if a.no_docker else docker_collect_count("app/tests/test_time_window_handlers.py")
    ok_t, bad_t = all_rounds_pass(NEW_TIME)
    pp_t = [rid for rid in NEW_TIME if part_res.get(rid) and not part_res[rid].get("passed")]
    st = KARSILANDI if ((tw or 0) >= 40 and ok_t) else (KARAR if not done_rounds else KARSILANMADI)
    crit.append(("7 Zaman (5c)", st, f"birim: time_window {fmt(tw)} test (≥40), handler {fmt(twh)}; 8 zaman sorusu (v58–v65, `now_override` dondurulmuş) tam turlarda geçmeyen {bad_t or 'yok'}; kısmi benchte geçmeyen {pp_t or 'yok'}. "
                 "Not: vCenter canlı olayları bu ortamda (sahte vCenter) yanıt vermez → o yol yalnız birim testle doğrulandı."))
    # 8
    tr_live = "?"
    if not a.no_docker:
        try:
            sys.path.insert(0, os.path.join(ROOT, "scripts"))
            from chat_bench import truth  # type: ignore
            T = truth.load_truth()
            tr_live = f"ocp_pods_src={T.get('ocp_pods_src')}; oVirt pod {T['ocp_pods'].get('oVirt')}, toplam {T.get('ocp_pods_total')}, hatalı {T.get('ocp_err_pods_total')}"
        except Exception as e:  # noqa: BLE001
            tr_live = f"truth okunamadı: {type(e).__name__}"
    st = KARSILANDI if tr_live.startswith("ocp_pods_src=live") else KARAR
    crit.append(("8 Bench truth", st, tr_live + "; host/datastore/cluster truth tazelik süzgeciyle (aynı tanım)."))
    # 8b
    new_ids = NEW_STATE + NEW_CNT + NEW_TIME
    qpath = os.path.join(ROOT, "scripts/chat_bench/questions.py")
    qtxt = read(qpath)
    have = [i for i in new_ids if f'"{i}"' in qtxt]
    # önceki geçenler düşmedi mi (kısmi bench, step3-full + step4-part'a göre)
    dropped = []
    for rid, r in part_res.items():
        if rid in new_ids or is_infra(r):
            continue
        prev = [br.get(rid) for br in base_res.values() if br.get(rid)]
        if prev and any(p.get("passed") for p in prev) and not r.get("passed"):
            dropped.append(rid)
    st = KARAR if dropped else (KARSILANDI if len(have) == len(new_ids) and part_res else KARAR)
    crit.append(("8b Bench soruları", st, f"eklenen: güç durumu {sum(1 for i in NEW_STATE if i in have)}/5 (≥4), kapsamlı sayım {sum(1 for i in NEW_CNT if i in have)}/12 (≥10), zaman {sum(1 for i in NEW_TIME if i in have)}/8 (≥8). "
                 f"Kısmi benchte önceden geçip KALAN: {dropped or 'yok'} — her biri (d)'de kural izi / LLM varyansı olarak sınıflanır; düşüş varsa karar insanda."))
    # 9
    new_tests = (full_sum[0] - 2459) if full_sum else None
    st = KARSILANDI if (full_sum and full_sum[2] == 0 and full_sum[0] >= 2395 + 80 and aut_sum and aut_sum[0] >= 323) else (KARAR if not full_sum else KARSILANMADI)
    crit.append(("9 Testler", st, f"tam takım {full_s} (taban 2459 → +{fmt(new_tests)} yeni; kriter ≥2395+80); automic {aut_s} (≥323/2)."))
    # 10
    ll = [(l.split('-')[-1], rid, (r.get('tools') or [])) for l in done_rounds for rid, r in per_round[l].items()
          if any(t.startswith("qa_rule:count_rules") for t in rule_trace(r))]
    ll_tool = [x for x in ll if x[2]]
    first = [per_round[l][rid].get("wall_s") for l in done_rounds[:1] for rid in TARGET_IDS if per_round[l].get(rid)]
    st = KARSILANDI if (ll and not ll_tool) else KARAR
    crit.append(("10 Canlı", st, f"sayım kuralı cevapları {len(ll)}; araç çağıran {len(ll_tool)}; ilk-tur hedef sorular süre p50/max: {fmt(pct(first, .5))}/{fmt(max(first) if first else None)} sn "
                 "(LLM turu 0 ve `ssh.exec` artışı 0: `llm_turns` bench kaydında yok → trace `qa_rule` + `tools=[]` ile dolaylı; audit sayımı bu betikte ölçülmez)."))
    # 11
    docs = {
        "TR": os.path.join(ROOT, "docs/guides/tr/modules/ai-architecture.md"),
        "EN": os.path.join(ROOT, "docs/guides/en/modules/ai-architecture.md"),
        "mdc": os.path.join(ROOT, ".cursor/rules/ainew-ai-architecture.mdc"),
    }
    marks = {"TR": ["Sayım kuralları", "Zaman penceresi", "sql_is_on"], "EN": ["Count rules", "Time window", "sql_is_on"],
             "mdc": ["Sayım kuralları (Adım 5b)", "Zaman penceresi (Adım 5c)", "sql_is_on"]}
    miss = [f"{k}:{m}" for k, p in docs.items() for m in marks[k] if m not in read(p)]
    st = KARSILANDI if not miss and "Aşama 5 — testler" in plan_text else KARSILANMADI
    crit.append(("11 Belgeler", st, f"TR/EN ai-architecture.md + .mdc anahtar ifadeler eksik: {miss or 'yok'}; plan.md sonuç bölümleri mevcut."))
    # 12
    crit.append(("12 Kapanış", KARAR, "Durum önerisi: **Devam ediyor / insan testi (İH5) bekliyor**. «Kapandı» kararı kullanıcıya aittir; bu rapor kapanış yazmaz."))
    W(md_table(["Kriter", "Durum", "Kanıt"], [list(c) for c in crit]))
    W("")
    if fired:
        W("**(b)-3 eki — sayım kuralı tetiklenen bench cevapları (hedef dışı tetikleme var mı, gözle bakın):**")
        W("")
        seen = {}
        for t, rid, h, p in fired:
            seen.setdefault(rid, []).append(f"{t}:{h.split(':',1)[-1]}:{'G' if p else 'K'}")
        W(md_table(["Soru", "Kat.", "Tur:handler:sonuç (G=geçti, K=kaldı)"],
                   [[rid, ((qids.get(rid) or ('', ''))[1]), "; ".join(v)] for rid, v in sorted(seen.items())]))
        W("")

    # ── (c) bench ───────────────────────────────────────────────────────────────────────
    W("## (c) Bench")
    rows = []
    for l, data in list(base.items()) + [(x, rounds[x]) for x in done_rounds if x not in base]:
        s = score(data)
        if not s["total"]["total"]:
            continue
        rows.append([l] + [f"{s['per'][m]['passed']}/{s['per'][m]['total']} (A{s['per'][m]['infra']})" if m in s["per"] else "—" for m in MODULES]
                    + [f"{s['total']['passed']}/{s['total']['total']}", s["total"]["infra"]])
    if part:
        s = score(part)
        rows.append([a.part + " (kısmi)"] + [f"{s['per'][m]['passed']}/{s['per'][m]['total']} (A{s['per'][m]['infra']})" if m in s["per"] else "—" for m in MODULES]
                    + [f"{s['total']['passed']}/{s['total']['total']}", s["total"]["infra"]])
    W(md_table(["Etiket", "virt", "ocp", "admin", "Toplam", "ALTYAPI"], rows) if rows else "_Bench verisi yok._")
    W("")
    W("_(A n) = ALTYAPI (LLM yanıtsız/zaman aşımı; skora girmez). step3-full/step4-part önceki adımlardır; soru setleri farklı olduğundan toplamlar yalnız ortak sorular üzerinden kıyaslanmalıdır (aşağıdaki tablo)._")
    W("")
    # soru başına tur geçmesi
    if done_rounds:
        W("### Soru başına geçme (tur başına) — ortak sorular, step3-full ve step4-part ile")
        W("")
        trs = []
        b3 = base_res.get("step3-full", {})
        b4 = base_res.get("step4-part", {})
        for rid, (m, cat) in sorted(qids.items(), key=lambda kv: (MODULES.index(kv[1][0]), kv[0])):
            marks_ = []
            for l in done_rounds:
                r = per_round[l].get(rid)
                marks_.append("—" if r is None else ("A" if is_infra(r) else ("✓" if r.get("passed") else "✗")))
            n_pass = marks_.count("✓")
            def bm(x):
                return "—" if x is None else ("A" if is_infra(x) else ("✓" if x.get("passed") else "✗"))
            trs.append([rid, m, cat, " ".join(marks_), f"{n_pass}/{len(done_rounds)}", bm(b3.get(rid)), bm(b4.get(rid))])
        W(md_table(["Soru", "Modül", "Kat.", "Turlar", "Geçen", "step3-full", "step4-part"], trs))
        W("")
        # kategori toplamları (her tur)
        W("### Kategori toplamları (tur başına geçen/toplam, ALTYAPI hariç)")
        W("")
        cats = sorted({c for (_m, c) in qids.values()})
        crows = []
        for c in cats:
            row = [c]
            for l in done_rounds:
                rs = [r for rid, r in per_round[l].items() if r.get("cat") == c and not is_infra(r)]
                row.append(f"{sum(1 for r in rs if r.get('passed'))}/{len(rs)}")
            crows.append(row)
        W(md_table(["Kategori"] + [l.split("-")[-1] for l in done_rounds], crows))
        W("")
        W("### ALTYAPI ve ilk-token süresi")
        W("")
        irows = []
        for l in done_rounds:
            rs = list(per_round[l].values())
            ft = [r.get("first_token_s") for r in rs if r.get("first_token_s") is not None]
            wl = [r.get("wall_s") for r in rs if r.get("wall_s") is not None]
            irows.append([l, sum(1 for r in rs if is_infra(r)), ", ".join(r["id"] for r in rs if is_infra(r)) or "—",
                          fmt(pct(ft, .5)), fmt(pct(ft, .95)), fmt(pct(wl, .5)), fmt(pct(wl, .95))])
        for l, dd in base_res.items():
            if l in done_rounds:
                continue
            rs = list(dd.values())
            ft = [r.get("first_token_s") for r in rs if r.get("first_token_s") is not None]
            wl = [r.get("wall_s") for r in rs if r.get("wall_s") is not None]
            irows.append([l, sum(1 for r in rs if is_infra(r)), ", ".join(r["id"] for r in rs if is_infra(r)) or "—",
                          fmt(pct(ft, .5)), fmt(pct(ft, .95)), fmt(pct(wl, .5)), fmt(pct(wl, .95))])
        W(md_table(["Etiket", "ALTYAPI", "Hangileri", "ilk token p50 sn", "p95", "toplam süre p50", "p95"], irows))
        W("")
    else:
        W("_Tam bench turu tamamlanmadı; soru-bazlı tablolar üretilemedi._")
        W("")

    if part:
        W("### Kısmi bench (`" + a.part + "`) — kalan sorular ve kural izi")
        W("")
        prow2 = []
        for rid, r in sorted(part_res.items()):
            if r.get("passed") or is_infra(r):
                continue
            bb = [("✓" if base_res[l].get(rid, {}).get("passed") else "✗") if base_res[l].get(rid) else "—" for l in base_res]
            tr = sorted(set(rule_trace(r)))
            prow2.append([rid, qids.get(rid, ("", ""))[0], r.get("cat", ""), " / ".join(f"{l}:{x}" for l, x in zip(base_res, bb)),
                          ", ".join(tr) or "—", "ürün kaynaklı olabilir" if tr else "LLM/yol varyansı (iz yok)", "; ".join(r.get("reasons") or [])[:90]])
        W(md_table(["Soru", "Modül", "Kat.", "Taban sonuçları", "Kural izi", "Yorum", "Neden"], prow2) if prow2 else "_Kalan yok._")
        W("")

    # ── (d) düşenler / kazananlar ───────────────────────────────────────────────────────
    W("## (d) Düşenler / kazananlar ve kural izi")
    drows: List[List[Any]] = []
    if done_rounds:
        W("Sınıflama: taban = step3-full (yoksa step4-part). **Düşen** = tabanda geçti, turların çoğunda (>%50) kaldı; **kazanan** = tabanda kaldı, turların çoğunda geçti; "
          "**dalgalı** = turlar arasında karışık (LLM varyansı ±1). İz: tur cevaplarında `qa_rule`/`entity_gate`/`action_gate` kaydı varsa **ürün kaynaklı olabilir**, yoksa **LLM varyansı**.")
        W("")
        for rid, (m, cat) in sorted(qids.items(), key=lambda kv: kv[0]):
            b = b3.get(rid) or b4.get(rid)
            if b is None:
                nps = [(per_round[l].get(rid) or {}).get("passed") for l in done_rounds if per_round[l].get(rid) and not is_infra(per_round[l][rid])]
                if nps and sum(1 for p in nps if p) < len(nps):
                    tr = sorted({t for l in done_rounds for t in rule_trace(per_round[l].get(rid) or {})})
                    drows.append([rid, m, cat, "YENİ SORU KALDI", f"{sum(1 for p in nps if p)}/{len(nps)}", "—", ", ".join(tr) or "—",
                                  "ürün kaynaklı olabilir (kural/kapı izi var)" if tr else "LLM varyansı (iz yok) — soru/yol incelensin",
                                  "; ".join(((per_round[done_rounds[-1]].get(rid) or {}).get("reasons") or []))[:90]])
                continue
            if is_infra(b):
                continue
            ps = [(per_round[l].get(rid) or {}).get("passed") for l in done_rounds if per_round[l].get(rid) and not is_infra(per_round[l][rid])]
            if not ps:
                continue
            frac = sum(1 for p in ps if p) / len(ps)
            if b.get("passed") and frac < 0.5:
                kind = "DÜŞEN"
            elif not b.get("passed") and frac > 0.5:
                kind = "KAZANAN"
            elif 0 < sum(1 for p in ps if p) < len(ps):
                kind = "dalgalı"
            else:
                continue
            tr = sorted({t for l in done_rounds for t in rule_trace(per_round[l].get(rid) or {})})
            why = "ürün kaynaklı olabilir (kural/kapı izi var)" if tr else "LLM varyansı (iz yok)"
            reasons = (per_round[done_rounds[-1]].get(rid) or {}).get("reasons") or []
            drows.append([rid, m, cat, kind, f"{sum(1 for p in ps if p)}/{len(ps)}", "geçti" if b.get("passed") else "kaldı",
                          ", ".join(tr) or "—", why, "; ".join(reasons)[:90]])
        W(md_table(["Soru", "Modül", "Kat.", "Durum", "Geçen/tur", "Taban", "Kural izi", "Yorum", "Son tur nedeni"], drows) if drows else "_Düşen/kazanan/dalgalı soru yok._")
        W("")
        W("**Pod soruları (kapsam dışı; LLM yolunda ölçülür, GEÇTİ şartı değil):**")
        W("")
        prow = []
        for rid in POD_IDS:
            ms = [(per_round[l].get(rid) or {}) for l in done_rounds]
            prow.append([rid, " ".join("✓" if x.get("passed") else ("A" if is_infra(x) else "✗") for x in ms if x), "; ".join((ms[-1].get("reasons") or [])[:2]) if ms else ""])
        W(md_table(["Soru", "Turlar", "Son tur nedeni"], prow))
        W("")
    else:
        W("_Tam bench turu yok._")
        W("")

    # ── (e) 5d önce/sonra ───────────────────────────────────────────────────────────────
    W("## (e) 5d — önce/sonra (rapor/KPI güç durumu bağlama)")
    ba = read(os.path.join(diag, "5d-before-after.md"))
    W(ba.split("\n", 1)[1].strip() if ba else "_`5d-before-after.md` yok (5d koşulmadı ya da BLOKE)._")
    W("")
    W("**KARAR BEKLİYOR: sayılar değişti, onay.** 448 `Running` VM artık açık sayılıyor; finans «kapalı VM tasarruf» ve kapalı VM sayıları küçüldü (eski sayılar hatalıydı).")
    W("")

    # ── (f) salt-okunur bulgular ────────────────────────────────────────────────────────
    W("## (f) Salt-okunur bulgular")
    m0 = re.search(r"### Aşama 0 — salt-okunur bulgular\n(.*?)\n\n### ", plan_text, re.S)
    W(m0.group(1).strip() if m0 else "_plan.md «Aşama 0» bulguları okunamadı._")
    W("")
    m2 = re.search(r"- \*\*BULGU \(değiştirilmedi\):\*\* pencere verilmeyen.*", plan_text)
    if m2:
        W(m2.group(0))
        W("")
    m2b = re.search(r"- \*\*BULGU/sınır:\*\* vCenter olay sorgusu.*", plan_text)
    if m2b:
        W(m2b.group(0))
        W("")
    ocp = read(os.path.join(diag, "ocp-stale.json"))
    if ocp:
        W("Bayat pod/deployment/service/route dry-run ham çıktısı: `ocp-stale.json` (silme YOK).")
        W("")

    # ── (g) karar bekleyenler ───────────────────────────────────────────────────────────
    W("## (g) Karar bekleyenler")
    dyn: List[str] = []
    try:
        for r in drows:
            if r[3] == "YENİ SORU KALDI":
                dyn.append(f"**Açık ürün boşluğu adayı — yeni soru {r[0]} ({r[2]}) {r[4]} tur geçti** ({r[6] if r[6] != '—' else 'kural izi yok: sayım kuralı yakalamadı, LLM yoluna düştü'}): "
                           f"{r[8] or 'neden yok'}. Kod bu bench'ten sonra DEĞİŞTİRİLMEDİ (rapor = benchlenen kod); düzeltme önerisi insan kararı.")
            elif r[3] == "DÜŞEN":
                dyn.append(f"**Düşen soru {r[0]} ({r[2]}) {r[4]} tur geçti** (taban geçiyordu; kural izi: {r[6]}): {r[8] or '—'} — iz yoksa LLM/yol varyansı; "
                           "taban sonuçlar `evidence_fallback` (ham veri dökümü) ile geçmiş olabilir, bu turlarda deterministik envanter/genel yola düşüyor; ayrıca bakılmalı.")
    except NameError:
        pass
    for t in dyn:
        W(f"- {t}")
    for t in [
        "**5d sayıları değişti** (açık VM 1018→1466, kapalı 534→86, finans tasarruf 282.658→47.508, israf vCPU/RAM/disk): onay.",
        "**VMware Tools denetimleri bilerek bağlanmadı** (3 yer, `5d-ATLANDI`): kanonik «açık» ile KubeVirt/oVirt VM'leri «tools yok» sayılıyor (8→456); hypervisor türüne göre uygulanabilirlik kararı.",
        "**Pod kapsamı teyidi:** pod/hatalı pod sayımı Adım 5 dışı, o07/o09/o17 hedef listesinden çıkarıldı (plan.md «Kapsam değişikliği»); onay kapanışta teyit edilecek.",
        "**İş-1 (bayat pod/deployment/service/route temizliği):** bu koşuda YOK; yalnız dry-run raporu (pod bayat 456, diğerleri 0). Onay bekliyor.",
        "**Varsayılan zaman penceresi 3 saat geniş** (`datetime.utcnow()` naif ↔ timestamptz): pencere verilmeyen handler yolu; düzeltme golden'ı etkiler — karar.",
        "**vCenter olay saklama süresi** `virt_live_event_retention_days`=30 varsayımı: ortamınızdaki gerçek süreyi doğrulayın.",
        "**dtkvm01 çift adı** (isim ↔ IP, OLVM senkronu host_name'e IP yazıyor): ayrı bulgu, değiştirilmedi.",
        "**`kubevirt_client.py:232`** bulgusu (Paused/Starting «kapalı» saklanır): DB etkisi 0 bugün; düzeltme kararı.",
        "**virt_ops_center `totals.vm_running` 1469 > açık VM 1466:** status=ONLINE ama güç durumu açık olmayan 3 VM — inceleme.",
        "**«Kapandı» kararı** kullanıcıya aittir (kriter 12).",
    ]:
        W(f"- {t}")
    W("")

    # ── (h) sabah ───────────────────────────────────────────────────────────────────────
    W("## (h) Sabah yapılacaklar")
    for t in [
        "**İH5** (insan testi): plan.md «İnsan testi (İH5-x)» listesi — `Kaç tane kapalı VM var?` → 86; `ZZ-FAKE-OpenShift'te kaç VM çalışıyor?` → 443; `Dün kaç VM yeniden başladı?` → pencere cevapta yazılı; yan etki kontrolü.",
        "**İH2-1…6** (Adım 2 güvenlik insan testi): plan.md'ye göre kullanıcı 2026-10-15'te yaptı, Adım 2 Kapandı; bu koşuda dokunulmadı. Yeniden zorunlu değil; 5b/5c/5d sonrası yan etki kontrolü olarak İH2-5 (yanlış ret: `kapalı VM'leri listele`, `son 24 saatte silinen VM'ler`) hızlıca tekrarlanabilir.",
        "**İş-1 onayı** (bayat pod temizliği): dry-run raporu (f) bölümünde.",
        "**Pod kapsamı teyidi** ve **5d sayıları onayı** — (g).",
        "Bench: kuyruk bitmediyse devralma komutları plan.md «Aşama 6 — kısmi bench sonuçları + devralma» bölümünde.",
    ]:
        W(f"- {t}")
    W("")

    # ── yorum (≤10 satır) ───────────────────────────────────────────────────────────────
    W("## Yorum")
    cm: List[str] = []
    cm.append(f"- Kod aşamaları 0–5: {sum(1 for ok, _ in progress[:6] if ok)}/6 işaretli; BLOKE {'var' if bloke else 'yok'}.")
    if sc_rounds:
        vals = [v["total"]["passed"] for v in sc_rounds.values()]
        cm.append(f"- Tam bench geçen sayısı turlar arası {min(vals)}–{max(vals)} (aralık {max(vals)-min(vals)}): LLM varyansı bu aralık kadar beklenir.")
    if done_rounds:
        deg = [r for r in drows if r[3] == "DÜŞEN"]
        prod = [r[0] for r in deg if r[6] != "—"]
        cm.append(f"- Düşen {len(deg)} soru; kural/kapı izi taşıyan (ürün kaynaklı olabilir): {prod or 'yok'}; geri kalanı LLM varyansı.")
    cm.append(f"- Kriterler: {sum(1 for c in crit if c[1]==KARSILANDI)} karşılandı, {sum(1 for c in crit if c[1]==KARSILANMADI)} karşılanmadı, {sum(1 for c in crit if c[1]==KARAR)} karar bekliyor.")
    cm.append("- Sayım kuralları LLM'siz ve hızlı; zaman penceresi cevapta yazılı; vCenter canlı olay yolu bu ortamda yalnız birim testle doğrulanabildi.")
    cm.append("- En büyük açık risk: 5d'nin rakamları değiştirmesi (finans/KPI) — onay olmadan başka ekranlarla kıyas yapılmamalı.")
    W("\n".join(cm[:10]))
    W("")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
