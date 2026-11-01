"""Sayım kuralı doğruluk taraması — salt-okunur. ≥40 soru: cevaptaki BAŞLIK sayısı, kural koduna bağlı
OLMAYAN bağımsız SQL ile hesaplanan değerle birebir aynı mı + kapsam etiketi doğru mu.

  docker cp scripts/diag_count_accuracy.py server_management_backend:/tmp/
  docker exec -w /app -e PYTHONPATH=/app server_management_backend python /tmp/diag_count_accuracy.py [--json out.json]

Bayatlık süzgeci (host/datastore/cluster): bir satır, kendi hypervisor'ının en yeni satırından
2 × esx_metric_interval_sec (varsayılan 1800 sn) geride ise sayılmaz — burada AYRI yazılmış SQL ile.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality import power_state as ps

STALE = 1800


def q1(db, sql, **p):
    return db.execute(text(sql), p).scalar()


def hv_id(db, name):
    return int(q1(db, "select id from hypervisors where name=:n", n=name))


def vm_cnt(db, hv_ids=None, state="all", cluster=None):
    sql = "select vm_power_state from servers where hypervisor_id is not null"
    p = {}
    if hv_ids is not None:
        sql += " and hypervisor_id = any(:h)"; p["h"] = hv_ids
    if cluster:
        sql += " and lower(vm_cluster)=:c"; p["c"] = cluster.lower()
    raws = [r[0] for r in db.execute(text(sql), p).all()]
    s = ps.summarize(raws)
    return s["total"] if state == "all" else s[state]


def fresh_cnt(db, table, tscol, namecol, hv_ids=None, distinct_host=False):
    p = {}
    where = "1=1"
    if hv_ids is not None:
        where = "hypervisor_id = any(:h)"; p["h"] = hv_ids
    if distinct_host:
        rows = db.execute(text(f"select hypervisor_id, host_name, max(timestamp) from hypervisor_host_metrics where {where} group by 1,2"), p).all()
    else:
        rows = db.execute(text(f"select hypervisor_id, {namecol}, {tscol} from {table} where {where}"), p).all()
    newest = {}
    for h, _, t in rows:
        if t is not None and (h not in newest or t > newest[h]):
            newest[h] = t
    return sum(1 for h, _, t in rows if t is not None and (newest[h] - t).total_seconds() <= STALE)


def ocp(db, table, cid=None):
    sql = f"select count(*) from {table}" + (" where cluster_id=:c" if cid else "")
    return int(q1(db, sql, **({"c": cid} if cid else {})))


def build_cases(db):
    OFF, OCPV, OLVM, FV, FO = (hv_id(db, n) for n in ("office", "oVirt (OpenShift Virt)", "Datatem OLVM", "ZZ-FAKE-vCenter", "ZZ-FAKE-OpenShift"))
    vmw = [OFF, FV]
    oc2 = int(q1(db, "select id from openshift_clusters where name='oVirt'"))
    oc3 = int(q1(db, "select id from openshift_clusters where name='ZZ-FAKE-OCP'"))
    C = []  # (platform, soru, beklenen sayı, etiket alt dizesi veya None)

    def add(plat, q, exp, label=None):
        C.append((plat, q, exp, label))

    # VM toplam / durum / kapsam (TR + EN, tane/adet, çekimli)
    tot, on, off = vm_cnt(db), vm_cnt(db, state="on"), vm_cnt(db, state="off")
    for plat in ("virt", "unified"):
        add(plat, "Kaç VM var?", tot, "tüm platformlar")
        add(plat, "Kaç tane VM var?", tot)
        add(plat, "Kaç adet VM var?", tot)
        add(plat, "Toplam kaç VM var?", tot)
        add(plat, "VM sayısı kaç?", tot)
        add(plat, "Kaç sanal makine var?", tot)
        add(plat, "Kaç tane kapalı VM var?", off, "tüm platformlar")
        add(plat, "Kaç VM kapalı?", off)
        add(plat, "Kaç VM çalışıyor?", on)
        add(plat, "Kaç adet açık VM var?", on)
    add("virt", "How many VMs are there?", tot)
    add("virt", "How many VMs are powered off?", off)
    add("virt", "How many VMs are running?", on)
    add("virt", "Number of VMs?", tot)
    add("virt", "office vCenter'da kaç VM var?", vm_cnt(db, [OFF]), "office")
    add("virt", "office'te kaç VM kapalı?", vm_cnt(db, [OFF], "off"), "office")
    add("virt", "office vCenter'da kaç VM çalışıyor?", vm_cnt(db, [OFF], "on"), "office")
    add("virt", "Datatem OLVM üzerinde kaç VM çalışıyor?", vm_cnt(db, [OLVM], "on"), "Datatem OLVM")
    add("virt", "Datatem OLVM'de kaç VM kapalı?", vm_cnt(db, [OLVM], "off"), "Datatem OLVM")
    add("virt", "Datatem OLVM'de kaç VM var?", vm_cnt(db, [OLVM]), "Datatem OLVM")
    add("virt", "ZZ-FAKE-vCenter'da kaç VM var?", vm_cnt(db, [FV]), "ZZ-FAKE-vCenter")
    add("virt", "ZZ-FAKE-OpenShift'te kaç VM çalışıyor?", vm_cnt(db, [FO], "on"), "ZZ-FAKE-OpenShift")
    add("virt", "ZZ-FAKE-OpenShift'te kaç VM kapalı?", vm_cnt(db, [FO], "off"), "ZZ-FAKE-OpenShift")
    add("virt", "oVirt (OpenShift Virt) üzerinde kaç VM var?", vm_cnt(db, [OCPV]), "oVirt (OpenShift Virt)")
    add("virt", "OLVM'de kaç VM var?", vm_cnt(db, [OLVM]), "KVM / OLVM")
    add("virt", "VMware'de kaç VM var?", vm_cnt(db, vmw), "VMware vCenter")
    add("virt", "OpenShift'te kaç VM var?", vm_cnt(db, [OCPV, FO]), "OpenShift Virtualization")
    add("virt", "FAKE-Cluster-1 cluster'ında kaç VM var?", vm_cnt(db, cluster="FAKE-Cluster-1"), "FAKE-Cluster-1")
    # host / datastore / cluster / hypervisor
    add("virt", "Kaç ESXi hostum var?", fresh_cnt(db, None, None, None, vmw, distinct_host=True), "VMware vCenter")
    add("virt", "Kaç host var?", fresh_cnt(db, None, None, None, None, distinct_host=True), "tüm platformlar")
    add("virt", "Datatem OLVM'de kaç host var?", fresh_cnt(db, None, None, None, [OLVM], distinct_host=True), "Datatem OLVM")
    add("virt", "Kaç datastore var?", fresh_cnt(db, "virt_datastores", "as_of", "name"), "tüm platformlar")
    add("virt", "Kaç tane datastore var?", fresh_cnt(db, "virt_datastores", "as_of", "name"))
    add("virt", "office vCenter'da kaç datastore var?", fresh_cnt(db, "virt_datastores", "as_of", "name", [OFF]), "office")
    add("virt", "Datatem OLVM'de kaç datastore var?", fresh_cnt(db, "virt_datastores", "as_of", "name", [OLVM]), "Datatem OLVM")
    add("virt", "Kaç cluster var?", fresh_cnt(db, "virt_clusters", "as_of", "name"), "tüm platformlar")
    add("virt", "Kaç hypervisor var?", int(q1(db, "select count(*) from hypervisors")), "tüm platformlar")
    # OpenShift
    add("unified", "OpenShift'te kaç node var?", ocp(db, "openshift_nodes"), "tüm OpenShift")
    add("unified", "OpenShift clusterlarında toplam kaç node var?", ocp(db, "openshift_nodes"), "tüm OpenShift")
    add("openshift", "oVirt cluster'ında kaç node var?", ocp(db, "openshift_nodes", oc2), "oVirt")
    add("openshift", "ZZ-FAKE-OCP cluster'ında kaç node var?", ocp(db, "openshift_nodes", oc3), "ZZ-FAKE-OCP")
    add("unified", "OpenShift'te kaç proje var?", ocp(db, "openshift_projects"), "tüm OpenShift")
    add("unified", "OpenShift'te kaç namespace var?", ocp(db, "openshift_projects"), "tüm OpenShift")
    add("openshift", "oVirt cluster'ında kaç proje (namespace) var?", ocp(db, "openshift_projects", oc2), "oVirt")
    add("openshift", "ZZ-FAKE-OCP'de kaç proje var?", ocp(db, "openshift_projects", oc3), "ZZ-FAKE-OCP")
    add("openshift", "Kaç node var?", ocp(db, "openshift_nodes"), "tüm OpenShift")
    add("unified", "Kaç OpenShift cluster'ı kayıtlı?", int(q1(db, "select count(*) from openshift_clusters")), "tüm OpenShift")
    return C


def headline_number(ans: str):
    m = re.match(r"\*\*[^*\n]*?:\s*(\d+)\*\*", ans or "")
    return int(m.group(1)) if m else None


AMBIG = [  # kapsam sözcüğü ≥2 kayıtla eşleşir → tüm eşleşenler kırılımda görünmeli (sessiz tek seçim yok)
    ("virt", "ZZ-FAKE'te kaç VM var?", ["ZZ-FAKE-vCenter", "ZZ-FAKE-OpenShift"]),
    ("virt", "ZZ-FAKE'te kaç VM kapalı?", ["ZZ-FAKE-vCenter", "ZZ-FAKE-OpenShift"]),
    ("virt", "OpenShift'te kaç VM var?", ["oVirt (OpenShift Virt)", "ZZ-FAKE-OpenShift"]),
    ("virt", "OpenShift'te kaç VM çalışıyor?", ["oVirt (OpenShift Virt)", "ZZ-FAKE-OpenShift"]),
    ("virt", "VMware'de kaç VM var?", ["office", "ZZ-FAKE-vCenter"]),
    ("virt", "vCenter'larda kaç VM var?", ["office", "ZZ-FAKE-vCenter"]),
    ("virt", "Kaç ESXi hostum var?", ["office", "ZZ-FAKE-vCenter"]),
    ("virt", "Kaç tane ESXi var?", ["office", "ZZ-FAKE-vCenter"]),
    ("virt", "ZZ-FAKE'te kaç datastore var?", ["ZZ-FAKE-vCenter"]),
    ("unified", "Kaç node var?", ["oVirt", "ZZ-FAKE-OCP"]),
    ("unified", "OpenShift'te kaç proje var?", ["oVirt", "ZZ-FAKE-OCP"]),
    ("unified", "Kaç cluster var?", ["oVirt", "ZZ-FAKE-OCP", "Datatem OLVM"]),
]


def ambiguity_check():
    rows, bad = [], 0
    for plat, q, must in AMBIG:
        ans = cr.count_response(q, platform=plat, allowed_modules=None) or ""
        miss = [m for m in must if m not in ans]
        ok = bool(ans) and not miss
        bad += 0 if ok else 1
        rows.append((plat, q, must, miss, ok))
    return rows, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    db = SessionLocal()
    rows, bad = [], 0
    try:
        cases = build_cases(db)
        for plat, q, exp, label in cases:
            ans = cr.count_response(q, platform=plat, allowed_modules=None)
            got = headline_number(ans) if ans else None
            lab_ok = True if not label else (label in (ans or ""))
            ok = ans is not None and got == exp and lab_ok
            bad += 0 if ok else 1
            rows.append({"platform": plat, "q": q, "expected": exp, "got": got, "label_ok": lab_ok,
                         "captured": ans is not None, "ok": ok})
    finally:
        db.close()
    n = len(rows)
    cap = sum(1 for r in rows if r["captured"])
    print(f"| platform | soru | beklenen (bağımsız SQL) | cevap | etiket | sonuç |\n|---|---|---:|---:|---|---|")
    for r in rows:
        print(f"| {r['platform']} | {r['q']} | {r['expected']} | {r['got']} | {'ok' if r['label_ok'] else 'YANLIŞ'} | {'GEÇTİ' if r['ok'] else 'KALDI'} |")
    print(f"\nToplam {n} soru · yakalanan {cap} ({round(100*cap/n)}%) · doğru {n-bad} · hatalı {bad}")
    arows, abad = ambiguity_check()
    print("\n### Çoklu eşleşme (kapsam sözcüğü ≥2 kayıt): tüm kayıtlar kırılımda\n")
    print("| platform | soru | cevapta olması gerekenler | eksik | sonuç |\n|---|---|---|---|---|")
    for plat, q, must, miss, ok in arows:
        print(f"| {plat} | {q} | {', '.join(must)} | {', '.join(miss) or '-'} | {'GEÇTİ' if ok else 'KALDI'} |")
    print(f"\nÇoklu eşleşme: {len(arows)} soru · geçen {len(arows)-abad} · sessiz tek seçim {abad}")
    bad += abad
    if a.json:
        json.dump({"rows": rows, "n": n, "captured": cap, "wrong": bad}, open(a.json, "w"), ensure_ascii=False, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
