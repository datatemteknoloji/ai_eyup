"""Adım 5 / Teşhis T2 — QA_RULES golden kaydı (LLM YOK, yalnız salt-okunur DB okuması).

Her soru için `try_deterministic_answer` hangi handler'a düştü ve çıktı özeti (sha256 + uzunluk).
Kural değişikliği (Adım 5b) mevcut kuralları bozmadı mı → `--compare` ile önceki kayıtla karşılaştırılır.

Kullanım (backend konteyneri içinde, PYTHONPATH=/app):
  python /tmp/diag_qa_golden.py --out /tmp/golden-before.json
  python /tmp/diag_qa_golden.py --compare /tmp/golden-before.json

Bench soruları `scripts/chat_bench/questions.py` konteynerde yoksa yalnız EK_SORULAR kullanılır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

EK_SORULAR = [
    # sayım / envanter
    "Kaç tane kapalı VM var?", "Kaç adet kapalı VM var?", "Kaç tane VM var?", "Kaç VM var?", "Toplam kaç VM var?",
    "office vCenter'da kaç VM var?", "oVirt (OpenShift Virt) üzerinde kaç VM var?", "ZZ-FAKE-OpenShift'te kaç VM çalışıyor?",
    "kaç çalışan VM var", "kaç esxi host var", "Kaç datastore var?", "Kaç cluster var?", "OpenShift'te kaç pod var?",
    "VM'leri listele", "kapalı VM'leri listele", "Datastore durumu nedir?", "datastore doluluk oranı",
    "hangi host'ta kaç VM var", "envanter özeti", "ortam özeti",
    # zaman
    "Dün kaç VM yeniden başladı?", "Son 7 günde restart edilen VM'ler", "son 24 saatte kritik alarmlar",
    "geçen hafta restart edilen VM sayısı", "bu ay oluşan alarmlar", "VM restart raporu", "son 30 günde silinen VM'ler",
    "son 1 yılda açılmayan VM'ler", "dün oluşan kritik alarmlar",
    # tek VM / konum
    "dttadvance VM'i hangi hypervisor üzerinde çalışıyor?", "dttadvance VM'inin CPU kullanımı nedir", "datatemengine hangi hostta?",
    # diğer aileler
    "ortam genel sağlık değerlendirmesi", "VMware tools kurulu olmayan VM'ler", "disconnect olan host var mı",
    "en fazla boş belleğe sahip host", "N+1 kapasite", "snapshot'ı olan VM'ler", "en eski snapshot",
    "HA ve DRS durumu", "cluster hiyerarşisi", "kaç GB RAM var", "kaç core var", "kaç disk var", "kaç snapshot var",
]


def _bench_questions():
    out = []
    try:
        sys.path.insert(0, "/tmp/chat_bench_src")
        from scripts.chat_bench import questions as Q  # type: ignore
        for fn in (Q.virt_questions, Q.ocp_questions, Q.admin_questions):
            for s in fn():
                out.append(getattr(s, "q", None) or s["q"])
    except Exception:
        pass
    return out


_LIVE_MARKERS = ("vcenter_vm_lifecycle", "fetch_live", "_get_live_", "vcenter_client", "vcenter_vm_performance", "virt_fleet_perf", "queryperf")


def _is_live(hi, handler_name: str) -> bool:
    import inspect

    fn = getattr(hi, handler_name, None)
    if fn is None:
        return False
    try:
        src = inspect.getsource(fn).lower()
    except Exception:
        return False
    return any(m in src for m in _LIVE_MARKERS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--compare")
    a = ap.parse_args()

    from app.core.database import SessionLocal

    import os
    _alt = os.environ.get("GOLDEN_HI_PATH")  # eski kodla (yedek dosya) koşmak için: veri kayması ↔ kod farkını ayırır
    if _alt:
        import importlib.util
        import sys as _sys

        spec = importlib.util.spec_from_file_location("app.services.hypervisor_intelligence", _alt)
        mod = importlib.util.module_from_spec(spec)
        _sys.modules["app.services.hypervisor_intelligence"] = mod
        spec.loader.exec_module(mod)
    from app.services import hypervisor_intelligence as hi

    qs = list(dict.fromkeys(_bench_questions() + EK_SORULAR))
    db = SessionLocal()
    res = {}
    try:
        for q in qs:
            n = hi._normalize_virt_question(q)
            handler = None
            for p, h in hi.QA_RULES:
                if re.search(p, n, re.I):
                    handler = h.__name__
                    break
            if handler and _is_live(hi, handler):
                # Canlı vCenter/WinRM sorgusu yapan handler çalıştırılmaz (yavaş + çıktı değişken): yalnız yönlendirme kaydı
                res[q] = {"first_pattern_handler": handler, "answered": None, "len": 0, "sha": "LIVE-SKIPPED"}
                continue
            try:
                ans = hi.try_deterministic_answer(db, q)
            except Exception as e:  # noqa: BLE001
                ans = f"ERR:{type(e).__name__}"
            body = re.sub(r"as_of[^\n]*", "", ans or "")
            res[q] = {
                "first_pattern_handler": handler,
                "answered": bool(ans),
                "len": len(body),
                "sha": hashlib.sha256(body.encode()).hexdigest()[:16],
            }
    finally:
        db.close()

    if a.out:
        json.dump(res, open(a.out, "w"), ensure_ascii=False, indent=1, sort_keys=True)
        print(f"{len(res)} soru kaydedildi → {a.out}; yanıtlanan {sum(1 for v in res.values() if v['answered'])}")
    if a.compare:
        old = json.load(open(a.compare))
        diff = [q for q in res if q in old and (res[q]["sha"] != old[q]["sha"] or res[q]["first_pattern_handler"] != old[q]["first_pattern_handler"])]
        print(f"karşılaştırma: {len(old)} eski / {len(res)} yeni; fark {len(diff)}")
        for q in diff:
            print("  FARK:", q, old[q], "->", res[q])
        return 1 if diff else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
