"""Gerçek değer (ground truth) — yalnızca SALT-OKUNUR SELECT; uygulama verisine yazmaz.

Sohbet cevaplarındaki sayı/varlık iddiaları bu değerlerle karşılaştırılır. Veri DB'den çalışma anında
okunur (sabit sayı yok); böylece ortam değişse de bench doğru kalır.
"""
from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Set

DB_CONTAINER = "server_management_db"

POWER_ON = {"poweredon", "powered_on", "running", "up", "on", "active"}
POWER_OFF = {"poweredoff", "powered_off", "stopped", "shutoff", "shut off", "down", "off", "halted"}
POD_ERR_STATES = {
    "crashloopbackoff", "error", "runcontainererror", "imagepullbackoff", "errimagepull",
    "createcontainererror", "oomkilled", "failed", "evicted", "containercannotrun",
}


def sql(query: str) -> List[List[str]]:
    """psql ile salt-okunur sorgu; satır = sütun listesi. Hata → []."""
    cmd = [
        "docker", "exec", "-i", DB_CONTAINER, "psql", "-U", "postgres", "-d", "server_management",
        "-t", "-A", "-F", "\x1f", "-c", query,
    ]
    low = query.strip().lower()
    if not low.startswith("select") and not low.startswith("with"):
        raise ValueError("truth.sql yalnızca SELECT/WITH çalıştırır")
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=60)
    except Exception:
        return []
    return [ln.split("\x1f") for ln in out.splitlines() if ln.strip()]


def _fresh_counts(inner: str, stale_sec: int) -> Dict[int, int]:
    """`inner` (h, n, ts) satırlarını hypervisor başına en yeni ts'e göre süzer; hypervisor → taze satır sayısı."""
    rows = sql(
        f"with l as ({inner}), m as (select h, max(ts) mx from l group by h) "
        f"select l.h, count(*) from l join m on m.h = l.h "
        f"where l.ts is not null and extract(epoch from (m.mx - l.ts)) <= {int(stale_sec)} group by 1"
    )
    return {int(h): int(n) for h, n in rows}


# Canlı (salt-okunur GET) pod sayımı: backend konteynerinde çalışır; hiçbir şey yazmaz/silmez.
_LIVE_PODS = r"""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.models.openshift import OpenShiftCluster
from app.services.openshift.cluster_ops import client_from_cluster
from app.services.openshift.fake_cluster import is_fake
ERR = %(err)r
out = {}
db = SessionLocal()
try:
    for c in db.query(OpenShiftCluster).order_by(OpenShiftCluster.id).all():
        if is_fake(c):
            out[c.name] = {"fake": True}
            continue
        cl = client_from_cluster(c)
        try:
            cl.last_error = ""
            pods = cl.list_pods()
            if cl.last_error:
                out[c.name] = {"error": cl.last_error[:120]}
                continue
            st = [str(p.get("status") or "").strip().lower() for p in pods]
            out[c.name] = {"total": len(pods), "err": sum(1 for x in st if x in ERR), "crash": sum(1 for x in st if x == "crashloopbackoff")}
        finally:
            try:
                cl.logout()
            except Exception:
                pass
finally:
    db.close()
print(json.dumps(out))
"""


# Bayat cluster: ürün (count_rules) son senkronu 3 × `openshift_sync_interval_sec`'ten eski cluster'ı toplama KATMAZ
# («sonuç bilinmiyor» satırı). Bench doğrusu da aynı kuralı kullanır (o17, o01, a01/a03/a10/a26: toplamlar yalnız taze cluster'lar).
_FRESH = r"""
import json, sys
sys.path.insert(0, "/app")
from app.core.database import SessionLocal
from app.services.chat_quality import count_extra as cx
db = SessionLocal()
try:
    thr = cx.ocp_stale_threshold_sec()
    syncs = cx.fetch_cluster_syncs(db)
    from app.models.openshift import OpenShiftCluster
    cl = {c.id: c.name for c in db.query(OpenShiftCluster).all()}
    fresh, stale = cx.split_clusters(syncs, list(cl), cx._now(), thr)
    print(json.dumps({"fresh": [cl[i] for i in fresh], "stale": [cl[i] for i in stale], "threshold_sec": thr}))
finally:
    db.rollback()
    db.close()
"""


def ocp_freshness(container: str = "server_management_backend") -> Dict[str, Any]:
    """{"fresh": [ad…], "stale": [ad…]}; alınamazsa {} (çağıran hepsini taze sayar = eski davranış)."""
    import json as _json
    try:
        out = subprocess.check_output(
            ["docker", "exec", "-i", "-w", "/app", "-e", "PYTHONPATH=/app", container, "python", "-"],
            input=_FRESH, text=True, stderr=subprocess.DEVNULL, timeout=60)
        return _json.loads(out.strip().splitlines()[-1])
    except Exception:
        return {}


def live_pod_counts(container: str = "server_management_backend") -> Dict[str, Dict[str, Any]]:
    """Gerçek cluster'lar için canlı pod sayıları; alınamazsa {} (çağıran `manual` yazar)."""
    import json as _json
    code = _LIVE_PODS % {"err": sorted(POD_ERR_STATES)}
    try:
        out = subprocess.check_output(
            ["docker", "exec", "-i", "-w", "/app", "-e", "PYTHONPATH=/app", container, "python", "-"],
            input=code, text=True, stderr=subprocess.DEVNULL, timeout=120)
        return _json.loads(out.strip().splitlines()[-1])
    except Exception:
        return {}


def power_class(state: str) -> str:
    s = (state or "").strip().lower()
    if s in POWER_ON:
        return "on"
    if s in POWER_OFF:
        return "off"
    return "other"


def load_truth() -> Dict[str, Any]:
    T: Dict[str, Any] = {}

    # --- Sanallaştırma ---
    hv = {r[1]: int(r[0]) for r in sql("select id,name from hypervisors")}
    hv_type = {int(r[0]): r[1] for r in sql("select id,hypervisor_type::text from hypervisors")}
    T["hv_id"] = hv
    T["hv_type"] = hv_type
    T["hv_count"] = len(hv)
    vm_rows = sql(
        "select hypervisor_id, vm_power_state, count(*) from servers "
        "where hypervisor_id is not null group by 1,2"
    )
    by_hv: Dict[int, Dict[str, int]] = {}
    for hid, st, n in vm_rows:
        d = by_hv.setdefault(int(hid), {"on": 0, "off": 0, "other": 0, "total": 0})
        c = power_class(st)
        d[c] += int(n)
        d["total"] += int(n)
    T["vm_by_hv"] = by_hv
    T["vm_total"] = sum(d["total"] for d in by_hv.values())
    T["vm_on_total"] = sum(d["on"] for d in by_hv.values())
    T["vm_off_total"] = sum(d["off"] for d in by_hv.values())
    T["vm_other_total"] = sum(d["other"] for d in by_hv.values())
    T["vm_names_by_hv_power"] = {}
    for hid, nm, st in sql("select hypervisor_id, name, vm_power_state from servers where hypervisor_id is not null"):
        T["vm_names_by_hv_power"].setdefault((int(hid), power_class(st)), []).append(nm)
    # Host/datastore/cluster doğrusu = sohbetteki sayım kuralıyla AYNI tanım (Adım 5b): host başına son metrik satırı /
    # datastore-cluster `as_of`, kendi hypervisor'ının en yeni satırından 2 × 900 sn (esx_metric_interval_sec) geride olanlar
    # BAYAT sayılır ve toplama girmez. (Eski `hypervisor_host_inventory` sayımı bayat/çift adlı hostları ayıramıyordu.)
    stale_sec = 1800
    host_fresh = _fresh_counts(
        "select distinct on (hypervisor_id, host_name) hypervisor_id h, host_name n, timestamp ts "
        "from hypervisor_host_metrics order by hypervisor_id, host_name, timestamp desc", stale_sec)
    T["hosts_fresh_by_hv"] = host_fresh
    T["vmware_hosts"] = sum(n for h, n in host_fresh.items() if hv_type.get(h) == "VMWARE")
    T["hosts_inventory_vmware"] = int(
        (sql("select count(*) from hypervisor_host_inventory i join hypervisors h on h.id=i.hypervisor_id "
             "where h.hypervisor_type::text='VMWARE'") or [["0"]])[0][0]
    )
    T["virt_clusters"] = sum(_fresh_counts("select hypervisor_id h, name n, as_of ts from virt_clusters", stale_sec).values())
    ds_by_hv = _fresh_counts("select hypervisor_id h, name n, as_of ts from virt_datastores", stale_sec)
    T["datastores_by_hv"] = ds_by_hv
    T["datastores"] = sum(ds_by_hv.values())
    # En eski olay kaydı (zaman penceresi «saklama dışı» şablonunun beklenen tarihi)
    ev = sql("select to_char(min(created_at) at time zone 'Europe/Istanbul', 'YYYY-MM-DD HH24:MI') from system_events")
    T["events_earliest"] = ev[0][0] if ev and ev[0] and ev[0][0] else ""
    # Aynı adlı VM birden çok hypervisor'da
    dup = sql(
        "select name, string_agg(hypervisor_id::text || ':' || coalesce(vm_power_state,'?'), ',') from servers "
        "where hypervisor_id is not null group by name having count(distinct hypervisor_id) > 1"
    )
    T["dup_vm"] = {r[0]: r[1].split(",") for r in dup}

    # --- OpenShift ---
    cl = {r[1]: int(r[0]) for r in sql("select id,name from openshift_clusters")}
    T["ocp_cluster_id"] = cl
    T["ocp_clusters"] = len(cl)
    T["ocp_nodes"] = {n: int((sql(f"select count(*) from openshift_nodes where cluster_id={i}") or [["0"]])[0][0])
                      for n, i in cl.items()}
    fr = ocp_freshness()
    stale_names = set(fr.get("stale") or [])
    T["ocp_stale_clusters"] = sorted(stale_names)
    T["ocp_nodes_total"] = sum(n for c, n in T["ocp_nodes"].items() if c not in stale_names)
    T["ocp_projects"] = {n: int((sql(f"select count(*) from openshift_projects where cluster_id={i}") or [["0"]])[0][0])
                         for n, i in cl.items()}
    # Pod doğrusu: gerçek cluster için CANLI (bayat DB satırları pod sayısını şişiriyordu: DB 787 ↔ canlı 331);
    # sahte cluster için DB (canlı karşılığı yok). Canlı alınamazsa `ocp_pods_src = "db-unreliable"` (soru `manual` olur).
    live = live_pod_counts()
    pods: Dict[str, int] = {}
    errs: Dict[str, int] = {}
    crash: Dict[str, int] = {}
    src = "live"
    for name, i in cl.items():
        lv = live.get(name)
        if lv and "total" in lv:
            pods[name], errs[name], crash[name] = lv["total"], lv["err"], lv["crash"]
        elif lv and lv.get("fake"):
            pods[name] = int((sql(f"select count(*) from openshift_workloads where cluster_id={i} and kind='pod'") or [["0"]])[0][0])
            e = c = 0
            for st, n in sql(f"select status,count(*) from openshift_workloads where cluster_id={i} and kind='pod' group by 1"):
                if st.strip().lower() in POD_ERR_STATES:
                    e += int(n)
                if st.strip().lower() == "crashloopbackoff":
                    c += int(n)
            errs[name], crash[name] = e, c
        else:
            src = "db-unreliable"
            pods[name] = int((sql(f"select count(*) from openshift_workloads where cluster_id={i} and kind='pod'") or [["0"]])[0][0])
            errs[name] = crash[name] = 0
    T["ocp_pods_src"] = src
    T["ocp_pods"] = pods
    T["ocp_pods_total"] = sum(n for c, n in pods.items() if c not in stale_names)
    T["ocp_err_pods"] = errs
    T["ocp_err_pods_total"] = sum(errs.values())
    T["ocp_crash_pods"] = crash
    T["ocp_top_restart"] = [r[0] for r in sql(
        "select name from openshift_workloads where kind='pod' order by restart_count desc limit 3")]
    T["ocp_top_ns_by_cluster"] = {}
    for n, i in cl.items():
        r = sql(f"select name from openshift_projects where cluster_id={i} order by pod_count desc limit 1")
        if r:
            T["ocp_top_ns_by_cluster"][n] = r[0][0]
    T["ocp_huawei_nodes"] = sorted({r[0] for r in sql(
        "select node_name from openshift_workloads where kind='pod' and project='huawei-csi' and node_name is not null")})
    T["ocp_master_nodes"] = [r[0] for r in sql(
        "select name from openshift_nodes where role ilike '%master%' and cluster_id in "
        "(select id from openshift_clusters where name not ilike 'zz-fake%')")]

    # --- Linux sunucu örneği (Admin) ---
    T["servers"] = {r[0]: r[1:] for r in sql(
        "select name, coalesce(ip_address,''), coalesce(os_type,'') from servers "
        "where name in ('dttadvance','rhel94-test')")}

    # --- Donanım (Dell OME / HPE OneView; DEMO dahil) — salt-okunur SELECT, tek sağlayıcı ailesi ---
    def _n(q):
        r = sql(q)
        return int(r[0][0]) if r and r[0] and r[0][0] not in ("", None) else 0
    T["hw_total"] = _n("select count(*) from hw_servers")
    T["hw_dell"] = _n("select count(*) from hw_servers where vendor='dell'")
    T["hw_hpe"] = _n("select count(*) from hw_servers where vendor='hpe'")
    T["hw_crit"] = _n("select count(*) from hw_servers where health='critical'")
    T["hw_warn"] = _n("select count(*) from hw_servers where health='warning'")
    T["hw_dell_crit"] = _n("select count(*) from hw_servers where vendor='dell' and health='critical'")
    T["hw_hpe_warn"] = _n("select count(*) from hw_servers where vendor='hpe' and health='warning'")
    T["hw_crit_names"] = [r[0] for r in sql("select name from hw_servers where health='critical' order by name")]
    T["hw_health"] = {r[0]: r[1] for r in sql("select name, health from hw_servers")}
    T["hw_first_encl"] = (sql("select enclosure_name from hw_servers where enclosure_name is not null "
                              "group by 1 order by 1 limit 1") or [[""]])[0][0]
    T["hw_encl_blades"] = _n(f"select count(*) from hw_servers where enclosure_name='{T['hw_first_encl']}'") if T["hw_first_encl"] else 0
    wsql = ("select count(distinct s.id) from hw_servers s join hw_warranty w on w.instance_id=s.instance_id "
            "and (w.server_ref=s.provider_ref or (w.serial is not null and w.serial=s.serial)) where {c}")
    T["hw_w_expired"] = _n(wsql.format(c="w.end_date < now()"))
    T["hw_w_exp90"] = _n(wsql.format(c="w.end_date >= now() and w.end_date < now() + interval '90 days'"))
    T["hw_alert_crit"] = _n("select count(*) from hw_alerts where severity='critical' and state='active'")
    T["hw_alert_warn"] = _n("select count(*) from hw_alerts where severity='warning' and state='active'")
    T["hw_demo_on"] = _n("select count(*) from integration_instances where kind='hw_demo'") > 0

    # --- Evren (varlık adı) ---
    uni: Set[str] = set()
    for q in (
        "select name from servers", "select vm_name from servers", "select hostname from servers",
        "select vm_guest_hostname from servers", "select name from hypervisors",
        "select host_name from hypervisor_host_inventory", "select name from virt_clusters",
        "select name from virt_datastores", "select name from openshift_clusters",
        "select name from openshift_nodes", "select name from openshift_projects",
        "select name from openshift_workloads",
        "select name from hw_servers", "select name from hw_enclosures",
    ):
        for r in sql(q):
            if r and r[0]:
                uni.add(r[0].strip().lower())
    T["universe"] = uni
    return T
