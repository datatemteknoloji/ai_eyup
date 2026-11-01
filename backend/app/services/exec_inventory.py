"""Yönetici sayfası envanter modeli: Ortam → Küme → Host. Kilitli pakete yazılır.

Sayfadaki her ortam/küme/host/depolama/dikkat kartı bu modelden türer. Okuma yolu burası tek yerdir;
`exec_view.build_view` yalnız birleştirir. Sentetik kayıt (ZZ-FAKE) hiçbir alana girmez. Sayfa açılışta
hesaplamaz: `exec_snapshot.produce_bundle` üretir, GET kilitli veriyi aynen döner.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone  # noqa: F401
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.exec_format import _IP, _safe_name, _tr_gb, _tr_int, _tr_pct
from app.services.host_freshness import fresh_hosts
from app.services.synthetic_scope import synthetic_cluster_ids, synthetic_hypervisor_ids, synthetic_server_ids

NO_CLUSTER = "Kümesiz"          # küme kaydı olmayan (bağımsız) host'ların grubu
_HOST_LIMIT = 20                # kümedeki ağaçta gösterilen en çok host
_TREE_CLUSTER_LIMIT = 12        # ortam başına ağaçtaki en çok küme


def _pct(value: Any) -> Optional[float]:
    """Yönetici ekranında kullanım %100'ü aşmaz (OpenShift istek/limit oranı yönetici için anlamsızdır)."""
    if value is None:
        return None
    return round(max(0.0, min(float(value), 100.0)), 1)


def _avg(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def host_label(name: Optional[str], kind: str) -> str:
    """Ana ekranda IP adı tek başına görünmez: «ESXi host (192.168.1.101)». Ad varsa olduğu gibi kalır."""
    raw = (name or "").strip()
    if not raw:
        return "Adsız host"
    if _IP.fullmatch(raw):
        prefix = {"VMware": "ESXi host", "OLVM": "KVM host", "OpenShift": "Node"}.get(kind, "Host")
        return f"{prefix} ({raw})"
    return raw

_KIND = {
    "vmware": "VMware",
    "kvm": "OLVM",
    "openshift_virt": "OpenShift",
    "proxmox": "Proxmox",
    "hyperv": "Hyper-V",
    "xen": "Xen",
}
_CARD_ACTION = {
    "OpenShift": "İlgili node ve küme olayını giderin.",
    "Sanallaştırma": "İlgili host, küme ve depolama alanını kontrol edin.",
    "Linux": "İlgili sunucudaki açık uyarıyı giderin.",
    "Windows": "İzleme ajanını ve açık uyarıyı ilgili sunucuda giderin.",
}
_FIX = {
    "hardware": "Sensörü ve fiziksel bileşeni kontrol edin; gerekirse üretici kaydı açın.",
    "health": "Host bağlantısını ve servis durumunu kontrol edin.",
    "capacity": "Doluluk için kaynak ekleyin veya yükü başka kümeye alın.",
    "compliance": "Eksik yapılandırmayı ilgili hostta tamamlayın.",
    "reclaim": "Kullanılmayan kaynağı planlı pencerede geri alın.",
}
_SEV_RANK = {"critical": 3, "high": 2, "medium": 1}


def _kind_label(raw: Any) -> str:
    key = (raw.value if hasattr(raw, "value") else str(raw or "")).lower()
    return _KIND.get(key, "Diğer")


def _open_findings(db: Session) -> List[Any]:
    from app.models.infra_finding import InfraFinding

    hidden_hv = synthetic_hypervisor_ids(db)
    hidden_clusters = synthetic_cluster_ids(db)
    try:
        rows = (
            db.query(InfraFinding)
            .filter(
                InfraFinding.active.is_(True),
                InfraFinding.result == "fail",
                InfraFinding.category != "backup",
                InfraFinding.severity.in_(("critical", "high", "medium")),
            )
            .limit(200)
            .all()
        )
    except Exception:
        db.rollback()
        return []
    kept = []
    for row in rows:
        platform = row.platform or ""
        source = int(row.source_id) if row.source_id is not None else None
        if source is not None and platform in ("vmware", "olvm", "ocp_virt") and source in hidden_hv:
            continue
        if source is not None and platform == "ocp" and source in hidden_clusters:
            continue
        if (row.entity_name or "").startswith("ZZ-FAKE") or (row.source_name or "").startswith("ZZ-FAKE"):
            continue
        if (row.evidence or {}).get("demo") or "demo" in (row.source_name or "").lower():
            continue
        kept.append(row)
    return kept


def _finding_action(row: Any) -> str:
    from app.services.exec_risks import _plain

    text_value = _plain(row.recommendation) or _plain(row.title)
    if text_value and text_value != (_plain(row.title) or ""):
        return text_value
    return _FIX.get(row.category or "", "İlgili kaydı planlı pencerede giderin.")


def _finding_problem(row: Any) -> str:
    from app.services.exec_risks import _plain

    title = _plain(row.title) or ("Donanım bulgusu" if row.category == "hardware" else "Açık bulgu")
    if row.category == "hardware" and not title.lower().startswith("donanım"):
        return f"Donanım: {title}"
    return title


def _stamp_issues(db: Session, areas: List[Dict[str, Any]]) -> None:
    from app.services.exec_risks import _AREAS

    grouped: Dict[str, List[Dict[str, str]]] = {}
    ranked = []
    for row in _open_findings(db):
        area = _AREAS.get(row.platform or "")
        if not area:
            continue
        ranked.append((
            _SEV_RANK.get((row.severity or "").lower(), 0),
            1 if row.category == "hardware" else 0,
            area,
            _finding_problem(row),
            _finding_action(row),
        ))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _sev, _hw, area, problem, action in ranked:
        bucket = grouped.setdefault(area, [])
        if len(bucket) >= 3 or any(item["problem"] == problem for item in bucket):
            continue
        bucket.append({"problem": problem, "action": action})
    for area in areas:
        rows = list(grouped.get(area["name"]) or [])
        if not rows:
            action = _CARD_ACTION.get(area["name"], "İlgili kaydı giderin.")
            rows = [{"problem": line, "action": action} for line in (area.get("events") or [])[:3]]
        area["issues"] = rows[:3]


def build_inventory(db: Session) -> Dict[str, Any]:
    """Güncel envanter. Sentetik kayıt girmez. Depolama host toplamı olarak toplanmaz."""
    from app.models.hypervisor import Hypervisor
    from app.models.openshift import OpenShiftCluster, OpenShiftNode
    from app.models.server import Server
    from app.models.virt_datastore import VirtDatastore
    from app.services.synthetic_scope import name_is_synthetic

    empty: Dict[str, Any] = {
        "physical": "0",
        "virtual": "0",
        "platforms": [],
        "environments": [],
        "clusters": [],
        "datastores": [],
        "hosts": [],
        "reclaim": [],
    }
    try:
        hidden_hv = synthetic_hypervisor_ids(db)
        hidden_servers = synthetic_server_ids(db)
        hidden_clusters = synthetic_cluster_ids(db)
        hypervisors = [hv for hv in db.query(Hypervisor).all() if hv.id not in hidden_hv and not name_is_synthetic(hv.name)]
        hv_by_id = {hv.id: hv for hv in hypervisors}
        syn = list(hidden_hv) or [0]
        latest = db.execute(text("""
            SELECT DISTINCT ON (hypervisor_id, host_name)
              hypervisor_id, host_name, host_ref, timestamp, cluster_name, cpu_usage_pct, mem_usage_pct,
              vms_total, sensor_bad_count, overall_status
            FROM hypervisor_host_metrics
            WHERE timestamp >= NOW() - INTERVAL '2 days'
              AND host_name IS NOT NULL
              AND hypervisor_id != ALL(:syn)
            ORDER BY hypervisor_id, host_name, timestamp DESC
        """), {"syn": syn}).all()
        latest = fresh_hosts(latest)     # yeniden adlandırılan host'un iki adı tek host olur (host_ref)
    except Exception:
        db.rollback()
        return empty

    grouped: Dict[Tuple[int, str], List[Any]] = {}
    for row in latest:
        if name_is_synthetic(row.host_name):
            continue
        cluster = (row.cluster_name or "").strip() or NO_CLUSTER
        grouped.setdefault((int(row.hypervisor_id), cluster), []).append(row)

    servers = []
    try:
        servers = db.query(Server).all()
    except Exception:
        db.rollback()
        servers = []
    vm_by_hv: Dict[int, int] = {}
    physical = 0
    virtual = 0
    for vm in servers:
        if vm.id in hidden_servers or name_is_synthetic(getattr(vm, "name", None)):
            continue
        if vm.hypervisor_id and int(vm.hypervisor_id) in hidden_hv:
            continue
        if vm.hypervisor_id:
            virtual += 1
            vm_by_hv[int(vm.hypervisor_id)] = vm_by_hv.get(int(vm.hypervisor_id), 0) + 1
        else:
            physical += 1

    environments: List[Dict[str, Any]] = []
    clusters: List[Dict[str, Any]] = []
    for hv in hypervisors:
        kind = _kind_label(hv.hypervisor_type)
        env_name = hv.name or "Adsız ortam"
        own = [(key, rows) for key, rows in grouped.items() if key[0] == hv.id]
        host_n = sum(len(rows) for _key, rows in own)
        vm_n = vm_by_hv.get(hv.id, 0)
        if vm_n == 0:
            vm_n = sum(int(item.vms_total or 0) for _key, rows in own for item in rows)
        env = {
            "name": env_name,
            "kind": kind,
            "clusters": max(len(own), 1 if host_n else 0),
            "hosts": host_n,
            "vms": vm_n,
            "cpu": _avg([_pct(item.cpu_usage_pct) for _key, rows in own for item in rows]),
            "memory": _avg([_pct(item.mem_usage_pct) for _key, rows in own for item in rows]),
            "problem": "",
            "action": "",
            "status": "Normal",
            "tree": [],
        }
        environments.append(env)
        for (_hv_id, cluster), rows in own:
            entry = {
                "name": cluster,
                "environment": env_name,
                "kind": kind,
                "hosts": len(rows),
                "vms": vm_by_hv.get(hv.id, 0) if len(own) == 1 else sum(int(item.vms_total or 0) for item in rows),
                "cpu": _avg([_pct(item.cpu_usage_pct) for item in rows]) or 0,
                "memory": _avg([_pct(item.mem_usage_pct) for item in rows]) or 0,
                "host_list": sorted(
                    (
                        {
                            "name": host_label(item.host_name, kind),
                            "cpu": _pct(item.cpu_usage_pct),
                            "memory": _pct(item.mem_usage_pct),
                            "problem": bool(item.sensor_bad_count and int(item.sensor_bad_count) > 0),
                        }
                        for item in rows
                    ),
                    key=lambda h: (h["problem"], h["memory"] or 0),
                    reverse=True,
                )[:_HOST_LIMIT],
            }
            clusters.append(entry)
            env["tree"].append(entry)

    try:
        for cluster in db.query(OpenShiftCluster).all():
            if cluster.id in hidden_clusters or name_is_synthetic(cluster.name):
                continue
            nodes = db.query(OpenShiftNode).filter(OpenShiftNode.cluster_id == cluster.id).all()
            if not nodes and any(env["name"] == cluster.name for env in environments):
                continue
            cpu_now = _avg([_pct(node.cpu_usage_pct) for node in nodes])
            mem_now = _avg([_pct(node.memory_usage_pct) for node in nodes])
            node_list = sorted(
                (
                    {
                        "name": host_label(node.name, "OpenShift"),
                        "cpu": _pct(node.cpu_usage_pct),
                        "memory": _pct(node.memory_usage_pct),
                        "problem": (node.status or "").lower() != "ready",
                    }
                    for node in nodes
                    if not name_is_synthetic(node.name)
                ),
                key=lambda h: (h["problem"], h["memory"] or 0),
                reverse=True,
            )[:_HOST_LIMIT]
            same = next((item for item in clusters if item["name"] == cluster.name), None)
            if same is None:
                env = {
                    "name": cluster.name,
                    "kind": "OpenShift",
                    "clusters": 1,
                    "hosts": len(nodes),
                    "vms": 0,
                    "cpu": cpu_now,
                    "memory": mem_now,
                    "problem": "",
                    "action": "",
                    "status": "Normal",
                    "tree": [],
                }
                environments.append(env)
                same = {
                    "name": cluster.name,
                    "environment": cluster.name,
                    "kind": "OpenShift",
                    "hosts": len(nodes),
                    "vms": 0,
                    "cpu": cpu_now or 0,
                    "memory": mem_now or 0,
                    "host_list": node_list,
                }
                clusters.append(same)
                env["tree"].append(same)
            else:
                if cpu_now is not None:
                    same["cpu"] = cpu_now
                if mem_now is not None:
                    same["memory"] = mem_now
                env = next((item for item in environments if item["name"] == same["environment"]), None)
                if env is not None:
                    if cpu_now is not None:
                        env["cpu"] = cpu_now
                    if mem_now is not None:
                        env["memory"] = mem_now
            for node in nodes:
                ready = (node.status or "").lower() == "ready"
                if ready or name_is_synthetic(node.name):
                    continue
                same.setdefault("_down", []).append(node.name)
    except Exception:
        db.rollback()

    stores: List[Dict[str, Any]] = []
    try:
        for ds in db.query(VirtDatastore).all():
            if ds.hypervisor_id not in hv_by_id:
                continue
            if name_is_synthetic(ds.name) or (ds.name or "").startswith("FAKE-"):
                continue
            if ds.usage_pct is None:
                continue
            stores.append({
                "name": ds.name,
                "environment": hv_by_id[ds.hypervisor_id].name,
                "usage": round(float(ds.usage_pct), 1),
                "usageLabel": _tr_pct(float(ds.usage_pct)),
                "free": _tr_gb(float(ds.free_gb or 0)),
            })
    except Exception:
        db.rollback()
    stores.sort(key=lambda item: item["usage"], reverse=True)
    for env in environments:
        mine = [store for store in stores if store["environment"] == env["name"]]
        env["storage"] = mine[0]["usage"] if mine else None
        env["storage_name"] = mine[0]["name"] if mine else None
    stores = stores[:10]

    hosts: List[Dict[str, Any]] = []
    seen = set()

    def add_host(item: Dict[str, Any]) -> None:
        key = (item["host"], item["problem"])
        if key in seen or not item["host"]:
            return
        seen.add(key)
        hosts.append(item)

    for row in _open_findings(db):
        if row.entity_kind not in ("host", "node"):
            continue
        hv = hv_by_id.get(int(row.source_id)) if row.source_id is not None else None
        if hv is not None:
            environment = hv.name
            kind = _kind_label(hv.hypervisor_type)
        else:
            environment = _safe_name(row.source_name) or "Adsız ortam"
            kind = "OpenShift" if row.platform == "ocp" else "Diğer"
        add_host({
            "host": host_label(row.entity_name, kind),
            "problem": _finding_problem(row),
            "action": _finding_action(row),
            "cluster": (row.cluster_name or "").strip() or NO_CLUSTER,
            "environment": environment,
            "kind": kind,
            "hardware": row.category == "hardware",
            "severity": (row.severity or "medium").lower(),
        })
    for (hv_id, cluster), rows in grouped.items():
        hv = hv_by_id.get(hv_id)
        if hv is None:
            continue
        for item in rows:
            if not item.sensor_bad_count or int(item.sensor_bad_count) <= 0:
                continue
            label = host_label(item.host_name, _kind_label(hv.hypervisor_type))
            if any(host["host"] == label and host["hardware"] for host in hosts):
                continue
            add_host({
                "host": label,
                "problem": f"Donanım: {_tr_int(int(item.sensor_bad_count))} sensör normal değil",
                "action": _FIX["hardware"],
                "cluster": cluster,
                "environment": hv.name,
                "kind": _kind_label(hv.hypervisor_type),
                "hardware": True,
                "severity": "high",
            })
    for cluster in clusters:
        for node_name in cluster.pop("_down", []):
            add_host({
                "host": host_label(node_name, "OpenShift"),
                "problem": "Node hazır değil",
                "action": "Node durumunu ve kubelet kaydını kontrol edin.",
                "cluster": cluster["name"],
                "environment": cluster["environment"],
                "kind": "OpenShift",
                "hardware": False,
                "severity": "high",
            })
    hosts.sort(key=lambda item: (item["hardware"], _SEV_RANK.get(item["severity"], 0)), reverse=True)
    for item in hosts:
        item.pop("severity", None)
    primary: List[Dict[str, Any]] = []
    rest: List[Dict[str, Any]] = []
    seen_host = set()
    for item in hosts:
        if item["host"] in seen_host:
            rest.append(item)
        else:
            seen_host.add(item["host"])
            primary.append(item)
    hosts = (primary + rest)[:10]

    for env in environments:
        match = next((host for host in hosts if host["environment"] == env["name"] and host["hardware"]), None)
        other = next((host for host in hosts if host["environment"] == env["name"]), None)
        full = next((store for store in stores if store["environment"] == env["name"] and store["usage"] >= 85), None)
        if match:
            env["problem"] = match["problem"]
            env["action"] = match["action"]
            env["status"] = "Kritik"
        elif full and full["usage"] >= 90:
            env["problem"] = f"Depolama {full['name']} doluluk {full['usageLabel']}"
            env["action"] = "Eski imaj ve kullanılmayan diski temizleyin veya kapasite ekleyin."
            env["status"] = "Kritik" if full["usage"] >= 95 else "Dikkat"
        elif other:
            env["problem"] = other["problem"]
            env["action"] = other["action"]
            env["status"] = "Dikkat"
        elif full:
            env["problem"] = f"Depolama {full['name']} doluluk {full['usageLabel']}"
            env["action"] = "Eski imaj ve kullanılmayan diski temizleyin veya kapasite ekleyin."
            env["status"] = "Dikkat"

    for env in environments:
        env["tree"] = sorted(env.get("tree") or [], key=lambda item: (item["memory"], item["cpu"]), reverse=True)[:_TREE_CLUSTER_LIMIT]
    clusters.sort(key=lambda item: (item["memory"], item["cpu"]), reverse=True)
    clusters = [{k: v for k, v in item.items() if k != "host_list"} for item in clusters[:10]]

    platforms: Dict[str, Dict[str, int]] = {}
    for env in environments:
        slot = platforms.setdefault(env["kind"], {"name": env["kind"], "environments": 0, "clusters": 0, "hosts": 0, "vms": 0})
        slot["environments"] += 1
        slot["clusters"] += int(env["clusters"])
        slot["hosts"] += int(env["hosts"])
        slot["vms"] += int(env["vms"])

    reclaim: List[Dict[str, Any]] = []
    try:
        from app.services.chat_quality import power_state as ps

        buckets: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for vm in servers:
            if vm.id in hidden_servers or not vm.hypervisor_id or int(vm.hypervisor_id) not in hv_by_id:
                continue
            if not ps.is_off(vm.vm_power_state):
                continue
            env_name = hv_by_id[int(vm.hypervisor_id)].name
            cluster = (vm.vm_cluster or "").strip() or NO_CLUSTER
            slot = buckets.setdefault((env_name, cluster), {"environment": env_name, "cluster": cluster, "count": 0, "vcpu": 0, "ram": 0.0, "disk": 0.0})
            slot["count"] += 1
            slot["vcpu"] += int(vm.vm_cpu_count or 0)
            slot["ram"] += float(vm.vm_memory_mb or 0) / 1024.0
            slot["disk"] += float(vm.vm_disk_gb or 0)
        ranked_reclaim = sorted(buckets.values(), key=lambda item: (item["disk"], item["vcpu"]), reverse=True)[:5]
        for slot in ranked_reclaim:
            reclaim.append({
                "environment": slot["environment"],
                "cluster": slot["cluster"],
                "count": _tr_int(slot["count"]),
                "vcpu": slot["vcpu"],
                "ram": _tr_gb(slot["ram"]),
                "disk": _tr_gb(slot["disk"]),
            })
    except Exception:
        db.rollback()

    return {
        "physical": _tr_int(physical),
        "virtual": _tr_int(virtual),
        "platforms": list(platforms.values()),
        "environments": environments,
        "clusters": clusters,
        "datastores": stores,
        "hosts": hosts,
        "reclaim": reclaim,
    }


def landscape_summary(land: Dict[str, Any]) -> str:
    """Şablon özet: üç cümle. Ortam sayıları · fiziksel/sanal sunucu · en büyük ortamlar. Sorun/çözüm yok."""
    envs = land.get("environments") or []
    if not envs:
        return ""
    counts: Dict[str, int] = {}
    for env in envs:
        kind = str(env.get("kind") or "Diğer")
        counts[kind] = counts.get(kind, 0) + 1
    bits = ", ".join(f"{kind} {_tr_int(count)}" for kind, count in counts.items())
    first = f"{_tr_int(len(envs))} ortam var: {bits}."
    second = f"Fiziksel sunucu {land.get('physical') or '0'}, sanal sunucu {land.get('virtual') or '0'}."
    ranked = sorted(envs, key=lambda e: (int(e.get("vms") or 0), int(e.get("hosts") or 0)), reverse=True)[:3]
    parts = [
        f"{e.get('name')} ({e.get('kind')}) {_tr_int(int(e.get('clusters') or 0))} küme, "
        f"{_tr_int(int(e.get('hosts') or 0))} host, {_tr_int(int(e.get('vms') or 0))} sanal makine"
        for e in ranked
    ]
    third = "En büyük ortamlar: " + "; ".join(parts) + "."
    return " ".join([first, second, third])


def template_from_view(facts: List[Dict[str, Any]], view: Dict[str, Any]) -> str:
    from app.services.exec_summary_text import bindings, template_sentences

    text = landscape_summary((view or {}).get("landscape") or {})
    if not text:
        text = template_sentences(bindings(facts or []))
    return text


def build_attention(hosts: List[Dict[str, Any]], risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """«Dikkat gerektirenler»: host sorunları + öncelikli riskler, VARLIK başına tek satır.

    Aynı host'un birden çok sorunu «+N bulgu» olur. Risk satırı bir host adıyla eşleşirse o host'a eklenir;
    eşleşmezse kendi satırı olur. Donanım sorunu önce, sonra en uzun süredir açık olan gelir. İlk 10 döner.
    """
    items: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    def key_of(name: str) -> str:
        raw = (name or "").strip().lower()
        match = re.search(r"\(((?:\d{1,3}\.){3}\d{1,3})\)$", raw)
        return match.group(1) if match else raw

    for row in hosts:
        key = key_of(row.get("host") or "")
        if not key:
            continue
        if key in items:
            items[key]["extra"] += 1
            items[key]["hardware"] = items[key]["hardware"] or bool(row.get("hardware"))
            continue
        items[key] = {
            "title": row.get("host"),
            "problem": row.get("problem") or "",
            "action": row.get("action") or "",
            "environment": row.get("environment") or "",
            "kind": row.get("kind") or "",
            "cluster": row.get("cluster") or "",
            "hardware": bool(row.get("hardware")),
            "extra": 0,
            "age_days": 0,
            "area": "",
        }
        order.append(key)
    for risk in risks:
        entity = (risk.get("entity") or risk.get("entity_name") or "").strip()
        key = key_of(entity)
        age = int(risk.get("age_days") or 0)
        if key and key in items:
            if (risk.get("sentence") or "") != items[key]["problem"]:
                items[key]["extra"] += 1
            items[key]["age_days"] = max(items[key]["age_days"], age)
            items[key]["area"] = items[key]["area"] or risk.get("area") or ""
            continue
        own = key or key_of(f"{risk.get('area')}|{risk.get('sentence')}")
        if own in items:
            items[own]["extra"] += 1
            continue
        items[own] = {
            "title": host_label(entity, "") if entity else (risk.get("area") or "Genel"),
            "problem": risk.get("sentence") or "",
            "action": risk.get("action") or "",
            "environment": "",
            "kind": "",
            "cluster": "",
            "hardware": False,
            "extra": 0,
            "age_days": age,
            "area": risk.get("area") or "",
        }
        order.append(own)
    ranked = sorted((items[k] for k in order), key=lambda r: (r["hardware"], r["age_days"], r["extra"]), reverse=True)
    return ranked[:10]
