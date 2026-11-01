"""Güç durumu ham değer taraması — YALNIZ OKUR (SELECT); DB'ye yazmaz.

`servers.vm_power_state` ve `virt_vm_metrics.power_state` farklı ham değerleri + adetleri + her birinin
kanonik sınıfı (`chat_quality.power_state.classify`) + tanınıyor mu. `unknown` sınıfına düşen her değer
ayrıca listelenir ("tanınmayan" = hiçbir kümede yok → WARNING üretir; "açık-durum-yok" = boş/UNKNOWN).

Kullanım (backend konteyneri):
  docker cp scripts/diag_power_state_scan.py server_management_backend:/tmp/
  docker exec -w /app -e PYTHONPATH=/app server_management_backend python /tmp/diag_power_state_scan.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.chat_quality import power_state as ps

SOURCES = [
    ("servers.vm_power_state", "select vm_power_state, count(*) from servers group by 1 order by 2 desc"),
    ("virt_vm_metrics.power_state (tüm geçmiş)",
     "select power_state, count(*) from virt_vm_metrics group by 1 order by 2 desc"),
    ("virt_vm_metrics.power_state (son 1 gün)",
     "select power_state, count(*) from virt_vm_metrics where timestamp > now() - interval '1 day' "
     "group by 1 order by 2 desc"),
]


def scan(db):
    out = []
    for name, sql in SOURCES:
        rows = []
        for raw, n in db.execute(text(sql)).all():
            cls = ps.classify(raw)
            rows.append({
                "raw": raw, "count": int(n), "class": cls,
                "recognized": ps.is_recognized(raw),
            })
        out.append({"source": name, "rows": rows,
                    "total": sum(r["count"] for r in rows),
                    "unknown": [r for r in rows if r["class"] == ps.UNKNOWN],
                    "unrecognized": [r for r in rows if not r["recognized"]]})
    return out


def render(res) -> str:
    L = []
    for s in res:
        L.append(f"### {s['source']}  (toplam {s['total']})")
        L.append("| ham değer | adet | sınıf | tanınıyor |")
        L.append("|---|---:|---|---|")
        for r in s["rows"]:
            L.append(f"| {r['raw']!r} | {r['count']} | {r['class']} | {'evet' if r['recognized'] else '**HAYIR**'} |")
        if s["unrecognized"]:
            L.append(f"**TANINMAYAN değerler:** " + ", ".join(f"{r['raw']!r}:{r['count']}" for r in s["unrecognized"]))
        elif s["unknown"]:
            L.append("`unknown` sınıfı (tanınan 'durum yok' değerleri): "
                     + ", ".join(f"{r['raw']!r}:{r['count']}" for r in s["unknown"]))
        else:
            L.append("`unknown` sınıfına düşen değer yok.")
        L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    db = SessionLocal()
    try:
        res = scan(db)
    finally:
        db.close()
    print(render(res))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
