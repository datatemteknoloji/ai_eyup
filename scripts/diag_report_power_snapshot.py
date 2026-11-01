"""Adım 5d — rapor/KPI güç durumu önce/sonra görüntüsü (YALNIZ OKUR; save=False, DB'ye yazmaz).

report_engine rapor tiplerini üretir, güç durumuna duyarlı alanları (powered_on/off sayıları vb.) ve
tüm JSON'un sha özetini kaydeder; ayrıca dashboard/KPI fonksiyonlarını çağırır.
  python /tmp/diag_report_power_snapshot.py --out /tmp/report-before.json
  python /tmp/diag_report_power_snapshot.py --compare /tmp/report-before.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re

from app.core.database import SessionLocal

_POWER_KEY = re.compile(r"power|running|vm_on|vm_off|on_vm|off_vm|savings|wasted|idle|reclaim", re.I)


def _walk(o, path="", acc=None):
    acc = {} if acc is None else acc
    if isinstance(o, dict):
        for k, v in o.items():
            _walk(v, f"{path}.{k}" if path else str(k), acc)
    elif isinstance(o, list):
        acc[path + "#len"] = len(o)
    else:
        if _POWER_KEY.search(path) and isinstance(o, (int, float, str)):
            acc[path] = o
    return acc


def snapshot() -> dict:
    from app.services import report_engine as re_

    db = SessionLocal()
    out = {}
    try:
        for rt in re_.REPORT_REGISTRY:
            try:
                data = re_.REPORT_REGISTRY[rt](db)
                body = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
                body = re.sub(r'"(generated_at|as_of|timestamp)": "[^"]*"', "", body)
                out[f"report:{rt}"] = {
                    "sha": hashlib.sha256(body.encode()).hexdigest()[:16],
                    "power_fields": {k: v for k, v in _walk(data).items()},
                }
            except Exception as e:  # noqa: BLE001
                out[f"report:{rt}"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
        for name, mod, fn in (
            ("kpi:hypervisors_stats", "app.api.hypervisors", None),
        ):
            pass
        # KPI/dashboard: GERÇEK fonksiyonlar çağrılır (yalnız DB okur) — önce/sonra aynı çağrılarla
        import asyncio

        def _kpi(label, fn):
            try:
                out[label] = _walk(fn())
            except Exception as e:  # noqa: BLE001
                out[label] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}

        from app.services import virt_monitoring as vm
        from app.services import virt_ops_center as voc
        from app.api import hypervisors as hv_api
        from app.api import ops_center as oc_api

        _kpi("kpi:virt_monitoring.build_overview", lambda: vm.build_overview(db))
        _kpi("kpi:hypervisors.get_quick_stats (vms_powered_on)", lambda: asyncio.run(hv_api.get_quick_stats(db)))
        _kpi("kpi:ops_center.executive_summary", lambda: asyncio.run(oc_api.executive_summary(db)))
        _kpi("kpi:virt_ops_center.build_virt_command_center", lambda: voc.build_virt_command_center(db))
        # openshift_virt_host_metrics.sync DB'ye yazar → çağrılmaz; ifade (eski ↔ yeni) servers satırlarıyla hesaplanır
        from sqlalchemy import text

        from app.services.chat_quality import power_state as ps

        rows = db.execute(text(
            "select h.name hv, s.status, s.vm_power_state from servers s join hypervisors h on h.id = s.hypervisor_id "
            "where h.hypervisor_type::text = 'OPENSHIFT_VIRT'")).all()
        per = {}
        for r in rows:
            d = per.setdefault(r.hv, {"vm_total": 0, "running_old_expr('on' in ps)": 0, "running_canonical": 0})
            d["vm_total"] += 1
            if (r.status or "").upper() == "ONLINE" or "on" in (r.vm_power_state or "").lower():
                d["running_old_expr('on' in ps)"] += 1
            if (r.status or "").upper() == "ONLINE" or ps.is_on(r.vm_power_state):
                d["running_canonical"] += 1
        for hv, d in per.items():
            for k, v in d.items():
                out[f"calc:openshift_virt_host_metrics:{hv}:{k}"] = v
        for raw_sql, label in (
            ("select count(*) from servers where hypervisor_id is not null and vm_power_state in ('POWERED_ON','up','running','poweredOn')", "sql-replica:hypervisors.py (old IN list)"),
            ("select count(*) from servers where hypervisor_id is not null and vm_power_state ilike '%on%'", "sql-replica:virt_monitoring.py (old ilike %on%)"),
            ("select count(*) from servers where hypervisor_id is not null and lower(vm_power_state) in ('poweredon','up','running')", "sql-replica:ops_center.py (old lower IN)"),
        ):
            out[label] = db.execute(text(raw_sql)).scalar()
    finally:
        db.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--compare")
    a = ap.parse_args()
    cur = snapshot()
    if a.out:
        json.dump(cur, open(a.out, "w"), ensure_ascii=False, indent=1, sort_keys=True, default=str)
        print(f"{len(cur)} kayıt → {a.out}")
    if a.compare:
        old = json.load(open(a.compare))
        for k in sorted(set(old) | set(cur)):
            if json.dumps(old.get(k), sort_keys=True, default=str) != json.dumps(cur.get(k), sort_keys=True, default=str):
                o, n = old.get(k), cur.get(k)
                if isinstance(o, dict) and isinstance(n, dict) and "power_fields" in o and "power_fields" in n:
                    for f in sorted(set(o["power_fields"]) | set(n["power_fields"])):
                        if o["power_fields"].get(f) != n["power_fields"].get(f):
                            print(f"FARK {k} :: {f}: {o['power_fields'].get(f)} -> {n['power_fields'].get(f)}")
                else:
                    print(f"FARK {k}: {o} -> {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
