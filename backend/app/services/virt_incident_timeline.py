"""Olay zaman çizelgesi + kök neden adayları (sanallaştırma).

Bir incident (veya host / VM / datastore + zaman) için pencere içindeki
kanıtları tek eksende toplar:
  • SystemEvent (vCenter/OLVM/OCP olayları, alarm)
  • host / VM / datastore metrik eşik aşımları (TimescaleDB)
  • host bağlantı kopması, bakım modu, HA yeniden başlatma olayları
  • yapılandırma değişiklikleri (virt_config_snapshots)
  • Zabbix problemleri (sanallaştırma bağlı Zabbix kaynağı varsa)
Adaylar deterministik kurallarla sıralanır; her aday kanıt maddeleri ve
doğrulama adımları taşır. LLM yalnız anlatır, sıralamayı değiştirmez.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

TH = {"cpu_ready_pct": 5.0, "host_cpu_pct": 85.0, "host_mem_pct": 92.0, "disk_latency_ms": 20.0,
      "ds_latency_ms": 20.0, "balloon_mb": 1.0, "swapped_mb": 1.0}
HA_RE = re.compile(r"(vsphere ha|ha restart|restarted .* on host|failover|isolation|fenc|highly available|"
                   r"ha agent|yeniden başlat)", re.I)
DISCONNECT_RE = re.compile(r"(not responding|disconnected|connection lost|lost connectivity|bağlantı kop|"
                           r"non.?responsive|unreachable)", re.I)
STORAGE_RE = re.compile(r"(apd|pdl|all paths down|path .* down|lost access to volume|datastore|latency|"
                        r"storage|lun|multipath)", re.I)
NET_RE = re.compile(r"(uplink|link down|network redundancy|vmnic|nic .* down|packet)", re.I)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _aware(dt).isoformat() if dt else None


def _parse_at(at: Optional[str]) -> datetime:
    if not at:
        return datetime.now(timezone.utc)
    try:
        return _aware(datetime.fromisoformat(str(at).replace("Z", "+00:00")))
    except ValueError:
        return datetime.now(timezone.utc)


def _events(db: Session, start: datetime, end: datetime, names: Set[str], server_ids: Set[int],
            hv_ids: Set[int]) -> List[Dict[str, Any]]:
    from app.models.event import SystemEvent
    rows = (db.query(SystemEvent).filter(SystemEvent.created_at >= start, SystemEvent.created_at <= end)
            .order_by(SystemEvent.created_at).limit(3000).all())
    low = {n.lower() for n in names if n}
    out = []
    for e in rows:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        txt = f"{e.title or ''} {e.description or ''}"
        host = str(rd.get("host_name") or rd.get("host") or "")
        hit = (e.server_id in server_ids) or (host.lower() in low) or any(n in txt.lower() for n in low)
        if not hit:
            continue
        if hv_ids and rd.get("hypervisor_id") not in hv_ids and str(rd.get("hypervisor_id")) not in {str(i) for i in hv_ids} \
                and e.server_id not in server_ids and host.lower() not in low:
            continue
        out.append({
            "t": _iso(e.created_at), "kind": "event", "source": e.source or "event",
            "entity": host or rd.get("vm_name") or "", "title": (e.title or "")[:300],
            "detail": (e.description or "")[:500], "severity": e.severity,
            "tags": [t for t, rx in (("ha", HA_RE), ("disconnect", DISCONNECT_RE), ("storage", STORAGE_RE),
                                     ("network", NET_RE)) if rx.search(txt)],
            "ref": {"event_id": e.id},
        })
    return out


def _host_series(db: Session, start: datetime, end: datetime, hosts: Sequence[str]) -> List[Dict[str, Any]]:
    if not hosts:
        return []
    rows = db.execute(text("""
        SELECT timestamp, hypervisor_id, host_name, cpu_usage_pct, mem_usage_pct, cpu_ready_pct,
               disk_latency_ms, disk_device_latency_ms, mem_balloon_mb, mem_swap_used_mb,
               net_dropped_rx, net_dropped_tx, connection_state, maintenance_mode, vms_running
          FROM hypervisor_host_metrics
         WHERE host_name = ANY(:h) AND timestamp BETWEEN :s AND :e
         ORDER BY host_name, timestamp
    """), {"h": list(hosts), "s": start, "e": end}).mappings().all()
    items: List[Dict[str, Any]] = []
    by_host: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_host[r["host_name"]].append(dict(r))
    for host, series in by_host.items():
        prev_conn = None
        prev_vms = None
        flagged: Set[str] = set()
        for r in series:
            t = _iso(r["timestamp"])
            conn = str(r.get("connection_state") or "")
            if prev_conn is not None and conn != prev_conn:
                items.append({"t": t, "kind": "host_state", "source": "metrics", "entity": host,
                              "title": f"{host}: bağlantı {prev_conn} → {conn}",
                              "severity": "critical" if conn != "connected" else "info",
                              "tags": ["disconnect"] if conn != "connected" else ["reconnect"]})
            prev_conn = conn
            vr = r.get("vms_running")
            if prev_vms is not None and vr is not None and prev_vms - vr >= 3:
                items.append({"t": t, "kind": "host_state", "source": "metrics", "entity": host,
                              "title": f"{host}: çalışan VM {prev_vms} → {vr}", "severity": "high",
                              "tags": ["vm_drop"]})
            prev_vms = vr if vr is not None else prev_vms
            for key, label, unit, thr, tag in (
                ("cpu_ready_pct", "CPU ready", "%", TH["cpu_ready_pct"], "cpu"),
                ("cpu_usage_pct", "CPU", "%", TH["host_cpu_pct"], "cpu"),
                ("mem_usage_pct", "Memory", "%", TH["host_mem_pct"], "memory"),
                ("disk_latency_ms", "Disk latency", " ms", TH["disk_latency_ms"], "storage"),
                ("mem_swap_used_mb", "Swap", " MB", TH["swapped_mb"], "memory"),
            ):
                v = r.get(key)
                if v is None:
                    continue
                if float(v) > thr and key not in flagged:
                    flagged.add(key)
                    peak = max(float(x.get(key) or 0) for x in series)
                    items.append({"t": t, "kind": "metric", "source": "metrics", "entity": host,
                                  "title": f"{host}: {label} eşik üstü ({float(v):.1f}{unit}, tepe {peak:.1f}{unit})",
                                  "severity": "high" if peak > thr * 2 else "medium", "tags": [tag],
                                  "value": float(v), "peak": peak, "metric": key})
    return items


def _vm_series(db: Session, start: datetime, end: datetime, vms: Sequence[str]) -> List[Dict[str, Any]]:
    if not vms:
        return []
    rows = db.execute(text("""
        SELECT vm_name, host_name,
               max(cpu_usage_pct) AS cpu, max(cpu_ready_pct) AS ready, max(disk_latency_ms) AS lat,
               max(balloon_mb) AS balloon, max(swapped_mb) AS swapped,
               max(COALESCE(net_dropped_rx,0)+COALESCE(net_dropped_tx,0)) AS dropped,
               min(timestamp) AS first_t,
               array_agg(DISTINCT host_name) AS hosts
          FROM virt_vm_metrics
         WHERE vm_name = ANY(:v) AND timestamp BETWEEN :s AND :e
         GROUP BY vm_name, host_name
    """), {"v": list(vms), "s": start, "e": end}).mappings().all()
    items = []
    hosts_seen: Dict[str, Set[str]] = defaultdict(set)
    for r in rows:
        hosts_seen[r["vm_name"]].add(r["host_name"])
        t = _iso(r["first_t"])
        for key, label, unit, thr, tag in (
            ("ready", "CPU ready", "%", TH["cpu_ready_pct"], "cpu"),
            ("lat", "Disk latency", " ms", TH["disk_latency_ms"], "storage"),
            ("balloon", "Balloon", " MB", TH["balloon_mb"], "memory"),
            ("swapped", "Swapped", " MB", TH["swapped_mb"], "memory"),
            ("dropped", "Paket kaybı", "", 1.0, "network"),
        ):
            v = r.get(key)
            if v is not None and float(v) > thr:
                items.append({"t": t, "kind": "vm_metric", "source": "metrics", "entity": r["vm_name"],
                              "title": f"{r['vm_name']}: {label} tepe {float(v):.1f}{unit} ({r['host_name']})",
                              "severity": "medium", "tags": [tag], "peak": float(v), "metric": key})
    for vm, hs in hosts_seen.items():
        if len(hs) > 1:
            items.append({"t": _iso(start), "kind": "vm_move", "source": "metrics", "entity": vm,
                          "title": f"{vm}: pencerede host değişti ({', '.join(sorted(h for h in hs if h))})",
                          "severity": "info", "tags": ["vmotion_or_restart"]})
    return items


def _ds_series(db: Session, start: datetime, end: datetime, datastores: Sequence[str]) -> List[Dict[str, Any]]:
    if not datastores:
        return []
    rows = db.execute(text("""
        SELECT name, max(GREATEST(COALESCE(read_latency_ms,0), COALESCE(write_latency_ms,0))) AS lat,
               max(usage_pct) AS usage, bool_or(accessible = false) AS inacc, min(timestamp) AS t
          FROM virt_datastore_metrics
         WHERE name = ANY(:d) AND timestamp BETWEEN :s AND :e
         GROUP BY name
    """), {"d": list(datastores), "s": start, "e": end}).mappings().all()
    out = []
    for r in rows:
        if r["inacc"]:
            out.append({"t": _iso(r["t"]), "kind": "datastore", "source": "metrics", "entity": r["name"],
                        "title": f"{r['name']}: erişilemez durumda görüldü", "severity": "critical",
                        "tags": ["storage"]})
        if r["lat"] is not None and float(r["lat"]) > TH["ds_latency_ms"]:
            out.append({"t": _iso(r["t"]), "kind": "datastore", "source": "metrics", "entity": r["name"],
                        "title": f"{r['name']}: latency tepe {float(r['lat']):.1f} ms", "severity": "high",
                        "tags": ["storage"], "peak": float(r["lat"])})
        if r["usage"] is not None and float(r["usage"]) >= 95:
            out.append({"t": _iso(r["t"]), "kind": "datastore", "source": "metrics", "entity": r["name"],
                        "title": f"{r['name']}: doluluk %{float(r['usage']):.0f}", "severity": "high",
                        "tags": ["storage", "full"]})
    return out


def _config_changes(db: Session, start: datetime, end: datetime, names: Set[str],
                    clusters: Set[str]) -> List[Dict[str, Any]]:
    from app.models.infra_finding import VirtConfigSnapshot
    from app.services.virt_config_drift import diff_configs
    rows = (db.query(VirtConfigSnapshot)
            .filter(VirtConfigSnapshot.captured_at >= start, VirtConfigSnapshot.captured_at <= end,
                    VirtConfigSnapshot.platform.in_(("vmware", "olvm", "ocp_virt"))).all())
    out = []
    for s in rows:
        if s.entity_name not in names and s.cluster_name not in clusters and s.entity_name not in clusters:
            continue
        prev = (db.query(VirtConfigSnapshot)
                .filter(VirtConfigSnapshot.platform == s.platform, VirtConfigSnapshot.source_id == s.source_id,
                        VirtConfigSnapshot.entity_kind == s.entity_kind, VirtConfigSnapshot.entity_ref == s.entity_ref,
                        VirtConfigSnapshot.captured_at < s.captured_at)
                .order_by(VirtConfigSnapshot.captured_at.desc()).first())
        if prev is None:
            continue
        diff = diff_configs((prev.payload or {}).get("config") or {}, (s.payload or {}).get("config") or {})
        if not diff:
            continue
        out.append({"t": _iso(s.captured_at), "kind": "config_change", "source": "config_snapshot",
                    "entity": s.entity_name, "title": f"{s.entity_kind} {s.entity_name}: {len(diff)} yapılandırma değişikliği",
                    "detail": "; ".join(f"{d['path']}: {d['old']} → {d['new']}" for d in diff[:5])[:500],
                    "severity": "medium", "tags": ["config"],
                    "note": "Değişiklik toplama turunda algılandı; gerçek zaman bir önceki turdan sonradır."})
    return out


def _zabbix(db: Session, start: datetime, end: datetime, names: Set[str]) -> Dict[str, Any]:
    try:
        from app.services.monitoring_sources import load_sources_from_db
        from app.services.zabbix_client import client_from_source
    except Exception:
        return {"used": False, "items": []}
    items: List[Dict[str, Any]] = []
    used = False
    for src in load_sources_from_db(db):
        if src.collector_type != "zabbix" or src.binding not in ("virtualization", "none"):
            continue
        try:
            cli = client_from_source(src)
            hostids = []
            for n in list(names)[:20]:
                for h in cli.hosts(search=n, limit=5):
                    hostids.append(h.get("hostid"))
            if not hostids:
                continue
            used = True
            rows = cli.call("event.get", {
                "output": ["eventid", "clock", "name", "severity", "value"],
                "hostids": hostids, "time_from": int(start.timestamp()), "time_till": int(end.timestamp()),
                "source": 0, "object": 0, "value": 1, "sortfield": ["clock"], "limit": 200,
                "selectHosts": ["name"],
            }) or []
            for r in rows:
                hn = ", ".join(h.get("name") for h in r.get("hosts") or [] if isinstance(h, dict))
                items.append({"t": datetime.fromtimestamp(int(r.get("clock") or 0), tz=timezone.utc).isoformat(),
                              "kind": "zabbix", "source": f"zabbix:{src.label}", "entity": hn,
                              "title": str(r.get("name") or "")[:300],
                              "severity": {"5": "critical", "4": "high", "3": "medium"}.get(str(r.get("severity")), "low"),
                              "tags": [t for t, rx in (("storage", STORAGE_RE), ("network", NET_RE),
                                                       ("disconnect", DISCONNECT_RE)) if rx.search(str(r.get("name")))]})
        except Exception as exc:
            logger.info("Zabbix zaman çizelgesi (%s): %s", src.label, exc)
    return {"used": used, "items": items}


def _rank(items: List[Dict[str, Any]], bottleneck: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    tags = defaultdict(list)
    for i, it in enumerate(items):
        for t in it.get("tags") or []:
            tags[t].append(i)
    layers = defaultdict(int)
    for b in (bottleneck or {}).get("items") or []:
        for f in b.get("findings") or []:
            if f.get("severity") in ("high", "medium"):
                layers[(f.get("layer"), f.get("resource"))] += 1
    cands: List[Dict[str, Any]] = []

    def add(key, title, score, ev, verify):
        cands.append({"id": key, "title": title, "confidence": round(min(score, 0.95), 2),
                      "confidence_label": "yüksek" if score >= 0.7 else ("orta" if score >= 0.4 else "düşük"),
                      "evidence": [items[i]["title"] for i in ev[:8]], "evidence_idx": ev[:20],
                      "verify": verify})

    if tags["disconnect"] or tags["vm_drop"]:
        ha = tags["ha"]
        add("host_failure", "Host bağlantı kaybı / arıza" + (" ve HA yeniden başlatma" if ha else ""),
            0.55 + 0.2 * bool(ha) + 0.1 * bool(tags["vm_drop"]),
            tags["disconnect"] + tags["vm_drop"] + ha,
            ["Host'un yönetim ağı ve donanım loglarını (iDRAC/iLO) kontrol edin",
             "vCenter/Manager olaylarında HA yeniden başlatılan VM listesini doğrulayın",
             "Aynı anda başka host'larda bağlantı kopması var mı (ağ/izolasyon)"])
    st = tags["storage"]
    if st or layers[("datastore", "disk")] or layers[("host", "disk")]:
        n_vm = layers[("datastore", "disk")] + layers[("host", "disk")]
        add("storage_latency", "Depolama gecikmesi / erişim sorunu",
            0.35 + 0.08 * min(len(st), 5) + 0.05 * min(n_vm, 4),
            st, ["Etkilenen datastore'u kullanan diğer VM'lerde aynı anda latency var mı",
                 "Array / SAN switch loglarında aynı zaman diliminde olay arayın",
                 "Host multipath durumunu (dead path) kontrol edin"])
    cpu = tags["cpu"]
    if cpu or layers[("host", "cpu")]:
        add("cpu_contention", "Host CPU çekişmesi (ready yüksek)",
            0.3 + 0.1 * min(len(cpu), 4) + 0.1 * min(layers[("host", "cpu")], 3),
            cpu, ["Aynı host'taki VM'lerin CPU ready değerlerini karşılaştırın",
                  "DRS önerilerini ve host CPU doygunluğunu inceleyin",
                  "Yüksek vCPU'lu atıl VM'leri küçültmeyi değerlendirin"])
    mem = tags["memory"]
    if mem or layers[("host", "memory")]:
        add("memory_pressure", "Host Memory baskısı (balloon/swap)",
            0.35 + 0.1 * min(len(mem), 4), mem,
            ["Host'ta balloon/swap/compression değerlerini kontrol edin",
             "Memory overcommit oranını ve reservation'ları inceleyin"])
    net = tags["network"]
    if net:
        add("network", "Ağ / uplink sorunu", 0.3 + 0.1 * min(len(net), 4), net,
            ["Host uplink durumu ve vSwitch teaming ayarlarını kontrol edin",
             "Fiziksel switch port loglarına bakın"])
    cfg = [i for i in tags["config"] if _aware(datetime.fromisoformat(items[i]["t"])) <= at]
    if cfg:
        add("config_change", "Olaydan önce yapılandırma değişikliği", 0.3 + 0.1 * min(len(cfg), 3), cfg,
            ["Değişikliği yapan kişiyi/değişiklik kaydını doğrulayın (vCenter Tasks / audit)",
             "Değişikliği geri almanın etkisini değerlendirin"])
    if layers[("vm", "cpu")] and not cpu:
        add("vm_own_load", "VM'in kendi yükü (host normal)", 0.35, [],
            ["Guest içinde süreç bazlı CPU kullanımını inceleyin", "vCPU sayısının yeterliliğini değerlendirin"])
    cands.sort(key=lambda c: -c["confidence"])
    return cands


def build_timeline(db: Session, *, host: Optional[str] = None, vm: Optional[str] = None,
                   datastore: Optional[str] = None, at: Optional[str] = None, before_min: int = 120,
                   after_min: int = 60, hosts: Optional[List[str]] = None, vms: Optional[List[str]] = None,
                   datastores: Optional[List[str]] = None, server_ids: Optional[List[int]] = None,
                   hv_ids: Optional[List[int]] = None, at_dt: Optional[datetime] = None) -> Dict[str, Any]:
    from app.models.server import Server
    from app.services.virt_diagnostics import correlate_window
    t0 = _aware(at_dt) if at_dt else _parse_at(at)
    before_min = max(5, min(int(before_min or 120), 24 * 60))
    after_min = max(0, min(int(after_min or 60), 24 * 60))
    start, end = t0 - timedelta(minutes=before_min), t0 + timedelta(minutes=after_min)
    H: Set[str] = set(hosts or []) | ({host} if host else set())
    V: Set[str] = set(vms or []) | ({vm} if vm else set())
    D: Set[str] = set(datastores or []) | ({datastore} if datastore else set())
    S: Set[int] = set(server_ids or [])
    HV: Set[int] = set(hv_ids or [])
    clusters: Set[str] = set()
    for v in list(V):
        s = db.query(Server).filter((Server.vm_name == v) | (Server.name == v)).first()
        if s:
            S.add(s.id)
            if s.vm_host_name:
                H.add(s.vm_host_name)
            if s.vm_datastore:
                D.add(s.vm_datastore)
            if s.vm_cluster:
                clusters.add(s.vm_cluster)
            if s.hypervisor_id:
                HV.add(s.hypervisor_id)
    names = H | V | D
    items: List[Dict[str, Any]] = []
    items += _events(db, start, end, names, S, HV)
    items += _host_series(db, start, end, sorted(H))
    items += _vm_series(db, start, end, sorted(V))
    items += _ds_series(db, start, end, sorted(D))
    items += _config_changes(db, start, end, names, clusters)
    zb = _zabbix(db, start, end, H | V)
    items += zb["items"]
    items.sort(key=lambda x: x.get("t") or "")
    bottleneck = correlate_window(db, start=start, end=end, vm_names=sorted(V) or None,
                                  host_names=sorted(H) or None, limit=20) if (V or H) else {}
    cands = _rank(items, bottleneck, t0)
    return {
        "ok": True,
        "window": {"at": t0.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
                   "before_min": before_min, "after_min": after_min},
        "scope": {"hosts": sorted(H), "vms": sorted(V), "datastores": sorted(D), "clusters": sorted(clusters)},
        "items": items[:500],
        "candidates": cands,
        "bottleneck": bottleneck.get("items") if isinstance(bottleneck, dict) else None,
        "sources": {"events": True, "metrics": True, "config_snapshots": True, "zabbix": zb["used"]},
        "notes": ["Adaylar kanıt sayısı ve şiddetine göre deterministik sıralanır; kesin kök neden değildir.",
                  "Metrik çözünürlüğü toplama aralığına bağlıdır (ESX metrik ~15 dk)."],
    }


def build_incident_timeline(db: Session, *, incident_id: int, before_min: int = 120,
                            after_min: int = 60) -> Dict[str, Any]:
    from app.models.event import Incident, SystemEvent
    from app.models.server import Server
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        return {"ok": False, "not_found": True, "error": "Olay bulunamadı"}
    sids = [int(x) for x in (inc.affected_servers or []) if str(x).isdigit()]
    hosts: Set[str] = set()
    vms: Set[str] = set()
    ds: Set[str] = set()
    hv_ids: Set[int] = set()
    for s in db.query(Server).filter(Server.id.in_(sids)).all() if sids else []:
        if s.hypervisor_id:
            vms.add(s.vm_name or s.name)
            hv_ids.add(s.hypervisor_id)
            if s.vm_host_name:
                hosts.add(s.vm_host_name)
            if s.vm_datastore:
                ds.add(s.vm_datastore)
    ev_ids = [int(x) for x in (inc.related_events or []) if str(x).isdigit()]
    for e in db.query(SystemEvent).filter(SystemEvent.id.in_(ev_ids)).all() if ev_ids else []:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if rd.get("host_name"):
            hosts.add(str(rd["host_name"]))
        if rd.get("vm_name"):
            vms.add(str(rd["vm_name"]))
        if rd.get("datastore"):
            ds.add(str(rd["datastore"]))
        if rd.get("hypervisor_id"):
            try:
                hv_ids.add(int(rd["hypervisor_id"]))
            except (TypeError, ValueError):
                pass
    if not (hosts or vms or ds):
        return {"ok": True, "applicable": False, "incident_id": inc.id,
                "note": "Olayda sanallaştırma varlığı (VM/host/datastore) yok — zaman çizelgesi uygulanmaz."}
    res = build_timeline(db, hosts=sorted(hosts), vms=sorted(vms), datastores=sorted(ds), server_ids=sids,
                         hv_ids=sorted(hv_ids), at_dt=inc.created_at, before_min=before_min, after_min=after_min)
    res.update({"incident_id": inc.id, "incident_title": inc.title, "applicable": True})
    return res
