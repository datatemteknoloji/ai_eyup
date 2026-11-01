#!/usr/bin/env python3
"""Varlık çözümleyici kapısı — yanlış alarm / yakalama taraması (LLM çağrısı YOK; yalnız DB okur).

Adım 4 kriter 3-4: (a) bench soruları + geçmiş mesajları, (b) zararsız ek soru kümesi, (c) DB'deki gerçek
adlar (tip adı kalıplarıyla), (d) ek ghost kümesi, (e) multi / daraltmalı kümeler.

Kullanım (backend konteyneri içinde):
    docker cp scripts/chat_bench server_management_backend:/tmp/chat_bench_pkg
    docker cp scripts/diag_entity_gate.py server_management_backend:/tmp/diag_entity_gate.py
    docker exec server_management_backend python /tmp/diag_entity_gate.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tmp/chat_bench_pkg/..")


def main() -> int:
    from app.services.chat_quality import entity_gate as eg
    from app.tests import entity_gate_cases as C

    cat = eg._load_catalog()
    print(f"katalog ok={cat.ok} ad={len(cat.names)} çoklu-ad={sorted(cat.dupes)}")
    fails = 0

    # (a) bench soruları
    try:
        sys.path.insert(0, "/tmp")
        import importlib
        qmod = importlib.import_module("chat_bench_pkg.questions") if False else None  # noqa: F841
    except Exception:
        qmod = None
    bench = []
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("bench_questions", "/tmp/chat_bench_pkg/questions.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)  # type: ignore[union-attr]
        for mod, fn in m.BUILDERS.items():
            for s in fn():
                bench.append((mod, s["id"], s["q"], s.get("history") or []))
    except Exception as exc:
        print("bench soruları yüklenemedi:", exc)
    expected_ghost = {"v29", "v30", "v31", "o33", "o34", "a23"}
    expected_multi = {"v14", "v15", "v16", "a08", "a09"}
    hit_ids = {}
    from app.services.chat_quality.action_gate import gate_response as _action
    hist_hits = []
    for mod, id_, q, hist in bench:
        # Üretimde kapı yalnız GÜNCEL mesajı görür (eylem kapısı önce çalışır); geçmiş yalnız bilgi amaçlı.
        if _action(q, platform="unified"):
            continue
        r = eg.resolve(q, cat, allow_virt_list=True)
        if r:
            hit_ids[id_] = (r.kind, r.entity, q)
        for h in hist:
            rh = eg.resolve(h, cat, allow_virt_list=True)
            if rh:
                hist_hits.append((id_, h, rh.kind))
    print(f"\n(a) bench: {len(bench)} soru; tetiklenen {len(hit_ids)}")
    for id_, (k, e, t) in sorted(hit_ids.items()):
        tag = "BEKLENEN" if id_ in expected_ghost | expected_multi else "YANLIŞ ALARM"
        if tag == "YANLIŞ ALARM":
            fails += 1
        print(f"   {id_:4} {k:10} {e[:30]:30} {tag}  «{t[:70]}»")
    print("   (bilgi) geçmiş mesajlarında tetiklenen:", hist_hits)
    missing = (expected_ghost | expected_multi) - set(hit_ids)
    print("   beklenip tetiklenmeyen:", sorted(missing))
    fails += len(missing)

    # (b) zararsız ek
    bad = [(q, eg.resolve(q, cat, allow_virt_list=True)) for q in C.HARMLESS]
    bad = [(q, r) for q, r in bad if r]
    print(f"\n(b) zararsız {len(C.HARMLESS)} soru; yanlış alarm {len(bad)}")
    for q, r in bad:
        print("   !!", q, "→", r.kind, r.entity)
    fails += len(bad)

    # (c) DB'deki gerçek adlar
    real = sorted({cat.display[k] for k in cat.names if k in cat.display})
    c_bad = []
    frames = ("{} VM'i hangi hostta?", "{} cluster'ında kaç host var?", "{} namespace'inde kaç pod var?",
              "{} sunucusunun CPU kullanımı nedir?", "{} host'unun durumu ne?", "{} node'u Ready mi?")
    for name in real:
        for f in frames:
            r = eg.resolve(f.format(name), cat, allow_virt_list=False)
            if r and r.kind == eg.KIND_NOT_FOUND:
                c_bad.append((name, f, r.entity))
    print(f"\n(c) DB adı {len(real)} × {len(frames)} kalıp; yanlış 'bulunamadı' {len(c_bad)}")
    for x in c_bad[:15]:
        print("   !!", x)
    fails += len(c_bad)

    # (d) ghost
    missed = []
    for q, ent in C.GHOST:
        r = eg.resolve(q, cat, allow_virt_list=True)
        if not (r and r.kind == eg.KIND_NOT_FOUND and r.entity == ent):
            missed.append((q, r.kind if r else None))
    rate = 100.0 * (len(C.GHOST) - len(missed)) / len(C.GHOST)
    print(f"\n(d) ghost {len(C.GHOST)} soru; yakalanan {len(C.GHOST) - len(missed)} (%{rate:.0f})")
    for x in missed:
        print("   kaçan:", x)
    if rate < 95:
        fails += 1

    # (e) multi / daraltmalı
    m_missed = [q for q in C.MULTI if not (eg.resolve(q, cat, allow_virt_list=True) or None)
                or eg.resolve(q, cat, allow_virt_list=True).kind != eg.KIND_AMBIGUOUS]
    n_bad = [q for q in C.NARROWED if eg.resolve(q, cat, allow_virt_list=True)]
    n_rbac = [q for q in C.MULTI if eg.resolve(q, cat, allow_virt_list=False)]
    print(f"\n(e) multi {len(C.MULTI)}: kaçan {len(m_missed)} {m_missed}; daraltmalı {len(C.NARROWED)}: yanlış tetik {len(n_bad)} {n_bad};"
          f" yetkisiz bağlamda liste {len(n_rbac)}")
    fails += len(m_missed) + len(n_bad) + len(n_rbac)
    print("\nSONUÇ:", "TEMİZ" if fails == 0 else f"{fails} sorun")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
