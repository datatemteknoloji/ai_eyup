"""Yapılandırma ve en iyi uygulama denetimi (deterministik kurallar).

Girdi: findings/collectors çıktısı (vCenter / OLVM Manager / kube API) + DB.
Çıktı: FindingDraft listesi — her kontrol pass / fail / not_measurable döner.
"not_measurable" bilinçli bir sonuçtur: yönetim API'si o bilgiyi vermiyorsa
(ör. OLVM host NTP) bunu "sorun yok" diye göstermek yanıltıcı olur.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.findings.store import FindingDraft

LONG_MAINTENANCE_DAYS = 7
OVERCOMMIT_PCT = 150.0
HW_EVENT_RE = re.compile(
    r"(hardware|sensor|ecc|memory error|dimm|psu|power supply|fan|temperature|raid|disk fail|"
    r"hba|nic down|link down|ipmi|bmc|ilo|idrac|machine check|mce|pci)",
    re.I,
)

Since = Dict[Tuple[str, str], Dict[str, datetime]]


def _days_since(since: Since, kind: str, ref: str, key: str) -> Optional[int]:
    dt = (since.get((kind, ref)) or {}).get(key)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).days


# ── VMware ───────────────────────────────────────────────────────────────────

def _vmware(col: Dict[str, Any], since: Since, hw: Dict[str, Any]) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    hosts = col.get("hosts") or []
    by_cluster: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in hosts:
        by_cluster[h.get("cluster") or ""].append(h)
    host_name = {h["ref"]: h["name"] for h in hosts}

    for c in col.get("clusters") or []:
        cfg, name = c["config"], c["name"]
        ref = f"cluster:{name}"
        ha = cfg.get("ha_enabled")
        out.append(FindingDraft("vmw.cluster.ha_enabled", "cluster", ref, name,
                                "not_measurable" if ha is None else ("pass" if ha else "fail"),
                                evidence={"ha_enabled": ha}, cluster_name=name))
        if ha:
            ac = cfg.get("admission_control_enabled")
            out.append(FindingDraft("vmw.cluster.admission_control", "cluster", ref, name,
                                    "not_measurable" if ac is None else ("pass" if ac else "fail"),
                                    evidence={"enabled": ac, "policy": cfg.get("admission_policy")},
                                    cluster_name=name))
            hm = str(cfg.get("host_monitoring") or "").lower()
            out.append(FindingDraft("vmw.cluster.host_monitoring", "cluster", ref, name,
                                    "not_measurable" if not hm else ("pass" if hm == "enabled" else "fail"),
                                    evidence={"host_monitoring": hm}, cluster_name=name))
            iso = cfg.get("isolation_addresses") or []
            out.append(FindingDraft("vmw.cluster.isolation_address", "cluster", ref, name,
                                    "pass" if iso else "fail", evidence={"addresses": iso},
                                    detail="Varsayılan gateway kullanılıyor" if not iso else ", ".join(iso),
                                    cluster_name=name))
        drs = cfg.get("drs_enabled")
        out.append(FindingDraft("vmw.cluster.drs_enabled", "cluster", ref, name,
                                "not_measurable" if drs is None else ("pass" if drs else "fail"),
                                evidence={"drs_enabled": drs}, cluster_name=name))
        if drs:
            beh = str(cfg.get("drs_behavior") or "")
            out.append(FindingDraft("vmw.cluster.drs_automation", "cluster", ref, name,
                                    "fail" if beh == "manual" else "pass", evidence={"behavior": beh},
                                    detail=beh, cluster_name=name))

        members = [h for h in by_cluster.get(name, []) if h["state"].get("connection") == "connected"]
        if len(members) >= 2:
            vers = {h["name"]: f"{h['config'].get('version')} ({h['config'].get('build')})" for h in members}
            distinct = sorted(set(vers.values()))
            out.append(FindingDraft("vmw.cluster.version_consistency", "cluster", ref, name,
                                    "fail" if len(distinct) > 1 else "pass",
                                    evidence={"versions": vers}, detail=" / ".join(distinct), cluster_name=name))
            ntp_sets = {h["name"]: ",".join(h["config"].get("ntp_servers") or []) for h in members}
            nonempty = {v for v in ntp_sets.values() if v}
            out.append(FindingDraft("vmw.cluster.ntp_consistency", "cluster", ref, name,
                                    "fail" if len(nonempty) > 1 else "pass",
                                    evidence={"ntp": ntp_sets}, cluster_name=name))
            lun_pol: Dict[str, Dict[str, str]] = defaultdict(dict)
            for h in members:
                for lun in h["config"].get("luns") or []:
                    if lun.get("san") and lun.get("policy"):
                        lun_pol[str(lun["id"])][h["name"]] = lun["policy"]
            mixed = {lid: p for lid, p in lun_pol.items() if len(set(p.values())) > 1}
            out.append(FindingDraft("vmw.cluster.path_policy_consistency", "cluster", ref, name,
                                    "fail" if mixed else "pass",
                                    evidence={"mixed_luns": dict(list(mixed.items())[:20]), "count": len(mixed)},
                                    detail=f"{len(mixed)} LUN" if mixed else "", cluster_name=name))

        # Paylaşımlı datastore cluster'ın tüm bağlı hostlarında mount edilmiş mi
        member_refs = {h["ref"] for h in members}
        for ds in col.get("datastores") or []:
            if not ds["config"].get("multiple_host_access"):
                continue
            mounted = set(ds["config"].get("mounted_hosts") or [])
            inter = mounted & member_refs
            if not inter or len(member_refs) < 2:
                continue
            missing = sorted(host_name.get(r, r) for r in member_refs - mounted)
            out.append(FindingDraft("vmw.datastore.cluster_visibility", "datastore",
                                    f"datastore:{ds['ref']}@{name}", f"{ds['name']} @ {name}",
                                    "fail" if missing else "pass",
                                    evidence={"missing_hosts": missing, "mounted": len(inter),
                                              "cluster_hosts": len(member_refs)},
                                    detail=("Eksik: " + ", ".join(missing)) if missing else "", cluster_name=name))

    for h in hosts:
        cfg, st, name, cl = h["config"], h["state"], h["name"], h.get("cluster")
        ref = f"host:{h['ref']}"
        conn = st.get("connection")
        out.append(FindingDraft("vmw.host.connection", "host", ref, name,
                                "pass" if conn == "connected" else "fail", evidence={"connection": conn},
                                detail=str(conn), cluster_name=cl))
        if st.get("maintenance"):
            d = _days_since(since, "host", h["ref"], "maintenance")
            out.append(FindingDraft("vmw.host.long_maintenance", "host", ref, name,
                                    "fail" if d is not None and d >= LONG_MAINTENANCE_DAYS else "pass",
                                    evidence={"days": d}, detail=f"≥ {d} gün" if d is not None else "",
                                    cluster_name=cl))
        else:
            out.append(FindingDraft("vmw.host.long_maintenance", "host", ref, name, "pass", cluster_name=cl))
        if conn != "connected":
            continue
        ntp = cfg.get("ntp_servers") or []
        out.append(FindingDraft("vmw.host.ntp_configured", "host", ref, name, "pass" if ntp else "fail",
                                evidence={"servers": ntp}, detail=", ".join(ntp), cluster_name=cl))
        if ntp:
            run = st.get("ntpd_running")
            out.append(FindingDraft("vmw.host.ntp_running", "host", ref, name,
                                    "not_measurable" if run is None else ("pass" if run else "fail"),
                                    evidence={"running": run, "policy": cfg.get("ntp_policy")}, cluster_name=cl))
        dns = cfg.get("dns_servers") or []
        out.append(FindingDraft("vmw.host.dns_configured", "host", ref, name, "pass" if dns else "fail",
                                evidence={"servers": dns}, cluster_name=cl))
        vm_nics = cfg.get("vmotion_vmknics") or []
        out.append(FindingDraft("vmw.host.vmotion_vmknic", "host", ref, name, "pass" if vm_nics else "fail",
                                evidence={"vmknics": vm_nics}, cluster_name=cl))
        single = [
            {"switch": s.get("name"), "kind": s.get("kind"), "uplinks": s.get("uplinks")}
            for s in cfg.get("vswitches") or []
            if (s.get("kind") == "distributed" or (s.get("portgroups") or 0) > 0) and len(s.get("uplinks") or []) < 2
        ]
        out.append(FindingDraft("vmw.host.uplink_redundancy", "host", ref, name, "fail" if single else "pass",
                                evidence={"switches": single},
                                detail=", ".join(f"{s['switch']} ({len(s['uplinks'] or [])})" for s in single),
                                cluster_name=cl))
        luns = cfg.get("luns") or []
        san = [x for x in luns if x.get("san")]
        weak = [x for x in san if (x.get("alive_paths") or 0) < 2]
        out.append(FindingDraft("vmw.host.storage_path_redundancy", "host", ref, name,
                                "fail" if weak else ("pass" if san else "not_measurable"),
                                evidence={"luns": weak[:30], "san_luns": len(san)},
                                detail=f"{len(weak)}/{len(san)} LUN tek/ölü yollu" if weak else
                                ("" if san else "SAN LUN yok (yerel/NFS/vSAN)"),
                                cluster_name=cl))
        # Denetim
        ssh = st.get("ssh_running")
        out.append(FindingDraft("cmp.host.ssh_disabled", "host", ref, name,
                                "not_measurable" if ssh is None else ("fail" if ssh else "pass"),
                                evidence={"running": ssh, "policy": cfg.get("ssh_policy")}, cluster_name=cl))
        sh = st.get("shell_running")
        out.append(FindingDraft("cmp.host.shell_disabled", "host", ref, name,
                                "not_measurable" if sh is None else ("fail" if sh else "pass"),
                                evidence={"running": sh, "policy": cfg.get("shell_policy")}, cluster_name=cl))
        lm = cfg.get("lockdown_mode")
        out.append(FindingDraft("cmp.host.lockdown_mode", "host", ref, name,
                                "not_measurable" if not lm else ("fail" if lm == "lockdownDisabled" else "pass"),
                                evidence={"mode": lm}, detail=str(lm or ""), cluster_name=cl))
        syslog = (col.get("syslog") or {})
        if h["ref"] in syslog:
            v = syslog.get(h["ref"]) or ""
            out.append(FindingDraft("cmp.host.syslog_remote", "host", ref, name, "pass" if v.strip() else "fail",
                                    evidence={"logHost": v}, detail=v, cluster_name=cl))
        else:
            out.append(FindingDraft("cmp.host.syslog_remote", "host", ref, name, "not_measurable",
                                    detail="OptionManager okunamadı", cluster_name=cl))
        # Donanım
        out.extend(_hardware_host("vmware", h, cl, hw))

    for ds in col.get("datastores") or []:
        st = ds["state"]
        ref = f"datastore:{ds['ref']}"
        acc = st.get("accessible")
        out.append(FindingDraft("vmw.datastore.accessible", "datastore", ref, ds["name"],
                                "pass" if acc else "fail", evidence={"inaccessible_mounts":
                                                                     [host_name.get(x, x) for x in st.get("inaccessible_mounts") or []]}))
        cap, free, unc = st.get("capacity_gb"), st.get("free_gb"), st.get("uncommitted_gb")
        if cap:
            prov = 100.0 * ((cap - (free or 0)) + (unc or 0)) / cap
            out.append(FindingDraft("vmw.datastore.overcommit", "datastore", ref, ds["name"],
                                    "fail" if prov > OVERCOMMIT_PCT else "pass",
                                    evidence={"provisioned_pct": round(prov, 1), "capacity_gb": cap,
                                              "uncommitted_gb": unc}, detail=f"Provisioned %{prov:.0f}"))
    return out


def _hardware_host(platform: str, h: Dict[str, Any], cl: Optional[str], hw: Dict[str, Any]) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    name, ref = h["name"], f"host:{h['ref']}"
    m = (hw.get("metrics") or {}).get(name) or {}
    inv = (hw.get("inventory") or {}).get(name) or {}
    status = str(m.get("overall_status") or h["state"].get("overall_status") or "").lower()
    if platform == "vmware":
        bad = int(m.get("sensor_bad_count") or 0)
        sensors = [s for s in (inv.get("health_sensors") or []) if isinstance(s, dict)
                   and str(s.get("status") or s.get("health") or "").lower() in ("yellow", "red", "warning", "critical")]
        out.append(FindingDraft("hw.host.sensor_alarm", "host", ref, name, "fail" if bad or sensors else "pass",
                                evidence={"bad_count": bad, "sensors": sensors[:20],
                                          "vendor": h["config"].get("vendor"), "model": h["config"].get("model"),
                                          "bios": h["config"].get("bios")},
                                detail=", ".join(str(s.get("name")) for s in sensors[:5]), cluster_name=cl))
        issues = [i for i in (inv.get("config_issues") or []) if i]
        out.append(FindingDraft("hw.host.config_issue", "host", ref, name, "fail" if issues else "pass",
                                evidence={"issues": issues[:20]},
                                detail="; ".join(str(i.get("message") if isinstance(i, dict) else i)[:120] for i in issues[:3]),
                                cluster_name=cl))
    if status:
        out.append(FindingDraft("hw.host.overall_status", "host", ref, name,
                                "fail" if status in ("red", "yellow") else "pass", evidence={"status": status},
                                detail=status, cluster_name=cl, severity="high" if status == "red" else None))
    ev = (hw.get("events") or {}).get(name) or []
    out.append(FindingDraft("hw.host.event_pattern", "host", ref, name, "fail" if len(ev) >= 3 else "pass",
                            evidence={"count": len(ev), "events": ev[:10]},
                            detail=f"14 günde {len(ev)} donanım olayı" if ev else "", cluster_name=cl))
    return out


# ── OLVM ─────────────────────────────────────────────────────────────────────

def _olvm(col: Dict[str, Any], since: Since, hw: Dict[str, Any]) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    hosts = col.get("hosts") or []
    by_cluster: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in hosts:
        by_cluster[h.get("cluster") or ""].append(h)
    for c in col.get("clusters") or []:
        cfg, name = c["config"], c["name"]
        ref = f"cluster:{name}"
        fe = cfg.get("fencing_enabled")
        out.append(FindingDraft("olvm.cluster.fencing_policy", "cluster", ref, name,
                                "not_measurable" if fe is None else ("pass" if fe else "fail"),
                                evidence={k: cfg.get(k) for k in ("fencing_enabled", "skip_if_sd_active",
                                                                  "skip_if_connectivity_broken")},
                                cluster_name=name))
        hr = cfg.get("ha_reservation")
        out.append(FindingDraft("olvm.cluster.ha_reservation", "cluster", ref, name,
                                "not_measurable" if hr is None else ("pass" if hr else "fail"),
                                evidence={"ha_reservation": hr}, cluster_name=name))
        out.append(FindingDraft("olvm.cluster.scheduling_policy", "cluster", ref, name, "pass",
                                evidence={"policy": cfg.get("scheduling_policy"),
                                          "properties": cfg.get("scheduling_properties"),
                                          "memory_overcommit_pct": cfg.get("memory_overcommit_pct")},
                                detail=str(cfg.get("scheduling_policy") or ""), cluster_name=name))
        members = [h for h in by_cluster.get(name, []) if h["state"].get("status") == "up"]
        if len(members) >= 2:
            vers = {h["name"]: h["config"].get("version") for h in members}
            distinct = sorted({str(v) for v in vers.values() if v})
            out.append(FindingDraft("olvm.cluster.version_consistency", "cluster", ref, name,
                                    "fail" if len(distinct) > 1 else "pass", evidence={"versions": vers},
                                    detail=" / ".join(distinct), cluster_name=name))
    for h in hosts:
        cfg, st, name, cl = h["config"], h["state"], h["name"], h.get("cluster")
        ref = f"host:{h['ref']}"
        status = st.get("status") or ""
        out.append(FindingDraft("olvm.host.status", "host", ref, name,
                                "pass" if status in ("up", "maintenance") else "fail",
                                evidence={"status": status, "external_status": st.get("external_status")},
                                detail=status, cluster_name=cl))
        if st.get("maintenance"):
            d = _days_since(since, "host", h["ref"], "maintenance")
            out.append(FindingDraft("olvm.host.long_maintenance", "host", ref, name,
                                    "fail" if d is not None and d >= LONG_MAINTENANCE_DAYS else "pass",
                                    evidence={"days": d}, cluster_name=cl))
        else:
            out.append(FindingDraft("olvm.host.long_maintenance", "host", ref, name, "pass", cluster_name=cl))
        pm = cfg.get("power_management_enabled")
        out.append(FindingDraft("olvm.host.power_management", "host", ref, name,
                                "not_measurable" if pm is None else ("pass" if pm else "fail"),
                                evidence={"enabled": pm, "kdump_detection": cfg.get("power_management_kdump")},
                                cluster_name=cl))
        out.append(FindingDraft("olvm.host.ntp", "host", ref, name, "not_measurable",
                                detail="Manager API host NTP bilgisini vermez", cluster_name=cl))
        out.append(FindingDraft("olvm.host.multipath", "host", ref, name, "not_measurable",
                                detail="Manager API yol sayısını vermez", cluster_name=cl))
        out.extend(_hardware_host("olvm", h, cl, hw))
    for ds in col.get("datastores") or []:
        st = ds["state"].get("status") or ""
        ok = st in ("active", "up", "ok", "unattached", "")
        out.append(FindingDraft("olvm.storage.status", "datastore", f"datastore:{ds['ref']}", ds["name"],
                                "pass" if ok else "fail",
                                evidence={"status": st, "external_status": ds["state"].get("external_status"),
                                          "type": ds["config"].get("type")}, detail=st,
                                severity="medium" if st == "maintenance" else None))
    out.append(FindingDraft("cmp.platform.time_source", "platform", "platform", "OLVM Manager", "not_measurable",
                            detail="Saat kaynağı API'de yok — host chrony kanıtı manuel eklenmeli"))
    return out


# ── OpenShift Virtualization ─────────────────────────────────────────────────

_EVICT_OK = ("LiveMigrate", "LiveMigrateIfPossible", "External")


def _ocp_virt(col: Dict[str, Any]) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    plat = col.get("platform") or {}
    cname = plat.get("cluster_name")
    hco = plat.get("hco")
    if hco is None:
        out.append(FindingDraft("ocpv.platform.hco_health", "platform", "platform:hco", "HyperConverged",
                                "not_measurable", detail="HyperConverged CR okunamadı (RBAC)", cluster_name=cname))
    else:
        bad = hco.get("available") == "False" or hco.get("degraded") == "True"
        out.append(FindingDraft("ocpv.platform.hco_health", "platform", "platform:hco", hco.get("name") or "HyperConverged",
                                "fail" if bad else "pass", evidence=hco, detail=str(hco.get("message") or "")[:200],
                                cluster_name=cname))
    default = plat.get("default_eviction")
    for vm in col.get("vms") or []:
        cfg, st = vm["config"], vm["state"]
        ref = f"vm:{vm['ref']}"
        rs = cfg.get("run_strategy")
        eff = cfg.get("eviction_strategy") or default
        if rs not in ("Halted",):
            out.append(FindingDraft("ocpv.vm.eviction_strategy", "vm", ref, vm["ref"],
                                    "pass" if eff in _EVICT_OK else "fail",
                                    evidence={"vm": cfg.get("eviction_strategy"), "cluster_default": default,
                                              "effective": eff}, detail=str(eff or "tanımsız"), cluster_name=cname))
        lm = st.get("live_migratable")
        if lm is not None and vm.get("power") == "poweredOn":
            out.append(FindingDraft("ocpv.vm.live_migratable", "vm", ref, vm["ref"],
                                    "fail" if lm == "False" else "pass",
                                    evidence={"reason": st.get("live_migratable_reason"),
                                              "message": st.get("live_migratable_message")},
                                    detail=str(st.get("live_migratable_reason") or ""), cluster_name=cname))
        out.append(FindingDraft("ocpv.vm.run_strategy", "vm", ref, vm["ref"],
                                "fail" if rs == "Manual" else "pass", evidence={"run_strategy": rs},
                                detail=str(rs), cluster_name=cname))
    out.append(FindingDraft("cmp.platform.time_source", "platform", "platform", "OpenShift", "not_measurable",
                            detail="Node chrony yapılandırması MachineConfig ile kanıtlanmalı", cluster_name=cname))
    return out


# ── Ortak giriş ──────────────────────────────────────────────────────────────

def hardware_context(db: Session, hv_id: int) -> Dict[str, Any]:
    from app.models.event import SystemEvent
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.services import virt_insights_data as vd
    metrics = {m["host_name"]: m for m in vd.latest_hosts(db, [hv_id])}
    inv = {}
    for i in db.query(HypervisorHostInventory).filter(HypervisorHostInventory.hypervisor_id == hv_id).all():
        inv[i.host_name] = {"health_sensors": i.health_sensors or [], "config_issues": i.config_issues or []}
    events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    since = datetime.now(timezone.utc) - timedelta(days=14)
    rows = (db.query(SystemEvent).filter(SystemEvent.created_at >= since)
            .order_by(SystemEvent.created_at.desc()).limit(5000).all())
    for e in rows:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if rd.get("hypervisor_id") not in (hv_id, str(hv_id)):
            continue
        txt = f"{e.title or ''} {e.description or ''}"
        if not HW_EVENT_RE.search(txt):
            continue
        host = rd.get("host_name") or rd.get("host") or ""
        if host:
            events[host].append({"title": (e.title or "")[:200], "at": e.created_at.isoformat() if e.created_at else None,
                                 "severity": e.severity, "count": e.occurrence_count})
    return {"metrics": metrics, "inventory": inv, "events": events}


def evaluate(platform: str, collected: Dict[str, Any], *, since: Optional[Since] = None,
             hw: Optional[Dict[str, Any]] = None) -> List[FindingDraft]:
    since = since or {}
    hw = hw or {}
    if platform == "vmware":
        return _vmware(collected, since, hw)
    if platform == "olvm":
        return _olvm(collected, since, hw)
    if platform == "ocp_virt":
        return _ocp_virt(collected)
    return []


def summarize(drafts: List[FindingDraft]) -> Dict[str, int]:
    c = Counter(d.result for d in drafts)
    return {"pass": c.get("pass", 0), "fail": c.get("fail", 0), "not_measurable": c.get("not_measurable", 0)}
