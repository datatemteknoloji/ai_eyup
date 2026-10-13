"""Automic altyapı senkronu: agents, agent groups, engine processes, snapshots."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.automic import (
    AutomicActiveExecution,
    AutomicAgent,
    AutomicAgentGroup,
    AutomicAgentGroupMember,
    AutomicAwiServer,
    AutomicCollectorState,
    AutomicDailyAggregate,
    AutomicEngineProcess,
    AutomicExecution,
    AutomicInfraDailySummary,
    AutomicInfraStatusSnapshot,
    AutomicSystem,
)
from app.services.automic.defaults import effective_settings
from app.services.automic.hostname_resolve import load_overrides, resolve_hostname
from app.services.automic.infra_status import (
    STATUS_MISSING,
    compute_agent_status,
    compute_engine_status,
    mqsrv_type_label,
    normalize_status,
    status_label_tr,
    thresholds,
)
from app.services.automic.masking import mask_text
from app.services.automic.small_tables import SMALL_REF_TABLES, check_row_count
from app.services.automic.source.base import SourceError
from app.services.automic.teams import resolve_team_for_object

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def sync_infrastructure(
    db: Session, system: AutomicSystem, src, *,
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """HOST + MQSRV + OHG/OHGF tam okuma (küçük tablo istisnası)."""
    settings = settings or effective_settings(system.settings)
    gcfg = settings.get("source_guard") or {}
    if not gcfg.get("infra_sync_enabled", True):
        return {"ok": True, "skipped": "infra_sync_disabled"}

    fetch_hosts = getattr(src, "fetch_hosts", None)
    fetch_mqsrv = getattr(src, "fetch_mqsrv", None)
    fetch_groups = getattr(src, "fetch_agent_groups", None)
    if not callable(fetch_hosts) or not callable(fetch_mqsrv):
        return {"ok": False, "skipped": "infra_fetch_missing"}

    warnings: List[str] = []
    disabled: Set[str] = set()

    # Satır sayısı kontrolü
    count_fn = getattr(src, "count_table", None)
    for tbl in sorted(SMALL_REF_TABLES):
        if not callable(count_fn):
            break
        try:
            n = int(count_fn(tbl) or 0)
        except SourceError as exc:
            warnings.append(f"{tbl} count: {exc}")
            continue
        ok, warn = check_row_count(tbl, n, settings)
        if warn:
            warnings.append(warn)
        if not ok:
            disabled.add(tbl)

    hosts: List[Dict[str, Any]] = []
    mqsrv: List[Dict[str, Any]] = []
    groups: List[Dict[str, Any]] = []
    members: List[Dict[str, Any]] = []

    if "HOST" not in disabled:
        try:
            hosts = list(fetch_hosts() or [])
        except SourceError as exc:
            warnings.append(f"HOST: {exc}")
    if "MQSRV" not in disabled:
        try:
            mqsrv = list(fetch_mqsrv() or [])
        except SourceError as exc:
            warnings.append(f"MQSRV: {exc}")
    if callable(fetch_groups) and "OHG" not in disabled and "OHGF" not in disabled:
        try:
            gres = fetch_groups() or {}
            groups = list(gres.get("groups") or [])
            members = list(gres.get("members") or [])
        except SourceError as exc:
            warnings.append(f"OHG/OHGF: {exc}")

    # Kaynak saat referansı: tüm MQSRV LastUpdate max
    source_now = None
    for row in mqsrv:
        lu = _aware(row.get("last_update") or row.get("last_life_sign"))
        if lu and (source_now is None or lu > source_now):
            source_now = lu

    life_by_name: Dict[str, datetime] = {}
    for row in mqsrv:
        if int(row.get("mqsrv_type") or row.get("type") or 0) != 8:
            continue
        nm = (row.get("name") or "").strip()
        lu = _aware(row.get("last_update") or row.get("last_life_sign"))
        if nm and lu:
            prev = life_by_name.get(nm)
            if prev is None or lu > prev:
                life_by_name[nm] = lu

    wall = _now()
    agent_names_seen: Set[str] = set()
    agents_upserted = 0
    for h in hosts:
        name = (h.get("name") or "").strip()
        if not name:
            continue
        agent_names_seen.add(name)
        life = life_by_name.get(name) or _aware(h.get("last_life_sign"))
        status, rule = compute_agent_status(
            host_active=h.get("host_active") if h.get("host_active") is not None else h.get("active"),
            last_life_sign=life,
            source_now=source_now,
            synced_at=wall,
            wall_now=wall,
            settings=settings,
        )
        row = db.get(AutomicAgent, {"system_id": system.id, "name": name})
        if row is None:
            row = AutomicAgent(system_id=system.id, name=name, first_seen=wall)
            db.add(row)
        row.client = h.get("client")
        row.oh_idnr = h.get("oh_idnr") or h.get("object_id")
        row.ip = (h.get("ip") or None)
        row.hostname_automic = (h.get("hostname") or h.get("hostname_automic") or None)
        row.port = h.get("port")
        row.os = h.get("os") or h.get("software")
        row.hardware = h.get("hardware")
        row.platform = h.get("platform")
        row.version = h.get("version")
        row.host_active = h.get("host_active") if h.get("host_active") is not None else h.get("active")
        row.roles = h.get("roles")
        row.last_life_sign = life
        row.status = status
        row.status_rule = rule
        row.missing_since = None
        row.synced_at = wall
        row.last_seen = wall
        agents_upserted += 1

    # Kaybolan agent'lar
    existing_agents = db.query(AutomicAgent).filter(AutomicAgent.system_id == system.id).all()
    for a in existing_agents:
        if a.name in agent_names_seen:
            continue
        if a.missing_since is None:
            a.missing_since = wall
        a.status = STATUS_MISSING
        a.status_rule = "missing_from_source"
        a.synced_at = wall

    # Engine processes (Type ≠ 8)
    eng_seen: Set[str] = set()
    eng_upserted = 0
    for m in mqsrv:
        tcode = int(m.get("mqsrv_type") or m.get("type") or 0)
        if tcode == 8:
            continue
        name = (m.get("name") or "").strip()
        if not name:
            continue
        eng_seen.add(name)
        life = _aware(m.get("last_update") or m.get("last_life_sign"))
        status, rule = compute_engine_status(
            last_life_sign=life, source_now=source_now, synced_at=wall,
            wall_now=wall, settings=settings,
        )
        row = db.get(AutomicEngineProcess, {"system_id": system.id, "name": name})
        if row is None:
            row = AutomicEngineProcess(
                system_id=system.id, name=name, process_type=mqsrv_type_label(tcode),
                mqsrv_type=tcode, first_seen=wall,
            )
            db.add(row)
        row.process_type = mqsrv_type_label(tcode)
        row.mqsrv_type = tcode
        row.ip = m.get("ip")
        row.port = m.get("port")
        row.rest_endpoint = m.get("rest_endpoint")
        row.connection_count = m.get("connection_count") or m.get("conn_cnt")
        row.pwp_connected = m.get("pwp_connected")
        row.last_life_sign = life
        row.status = status
        row.status_rule = rule
        row.missing_since = None
        row.synced_at = wall
        row.last_seen = wall
        # node: IP → hostname resolve (Automic HOST_HostName yok MQSRV'de)
        ov = load_overrides(db, system.id)
        resolved = resolve_hostname(ip=row.ip, overrides=ov, settings=settings)
        # REST endpoint hostname önerisi
        if not resolved.get("hostname") or resolved.get("source") == "ip_only":
            ep = row.rest_endpoint or ""
            if "://" in ep:
                try:
                    hostpart = ep.split("://", 1)[1].split("/", 1)[0]
                    hostpart = hostpart.split(":")[0]
                    if hostpart and not hostpart.replace(".", "").isdigit():
                        row.node = hostpart
                    else:
                        row.node = resolved.get("hostname")
                except Exception:
                    row.node = resolved.get("hostname")
            else:
                row.node = resolved.get("hostname")
        else:
            row.node = resolved.get("hostname")
        eng_upserted += 1

    for e in db.query(AutomicEngineProcess).filter(AutomicEngineProcess.system_id == system.id).all():
        if e.name in eng_seen:
            continue
        if e.missing_since is None:
            e.missing_since = wall
        e.status = STATUS_MISSING
        e.status_rule = "missing_from_source"
        e.synced_at = wall

    # Agent groups
    grp_seen: Set[str] = set()
    for g in groups:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        grp_seen.add(name)
        row = db.get(AutomicAgentGroup, {"system_id": system.id, "name": name})
        if row is None:
            row = AutomicAgentGroup(system_id=system.id, name=name)
            db.add(row)
        row.client = g.get("client")
        row.oh_idnr = g.get("oh_idnr") or g.get("object_id")
        row.platform = g.get("platform")
        row.mode = g.get("mode")
        row.synced_at = wall
        row.missing_since = None

    for g in db.query(AutomicAgentGroup).filter(AutomicAgentGroup.system_id == system.id).all():
        if g.name not in grp_seen and grp_seen:
            if g.missing_since is None:
                g.missing_since = wall

    if members:
        db.execute(text(
            "DELETE FROM automic_agent_group_members WHERE system_id = :sid"
        ), {"sid": system.id})
        for m in members:
            gn = (m.get("group_name") or "").strip()
            an = (m.get("agent_name") or "").strip()
            if not gn or not an:
                continue
            db.add(AutomicAgentGroupMember(
                system_id=system.id, group_name=gn, agent_name=an, synced_at=wall,
            ))

    # Snapshots (aralık kontrolü)
    thr = thresholds(settings)
    state = db.get(AutomicCollectorState, system.id)
    if state is None:
        state = AutomicCollectorState(system_id=system.id)
        db.add(state)
    take_snap = True
    if state.infra_synced_at:
        last = _aware(state.infra_synced_at)
        if last and (wall - last) < timedelta(minutes=max(1, thr["snapshot_interval_min"] - 1)):
            # Her senkron status günceller; snapshot aralığı ayarlanabilir — yine de yaz
            pass
    _write_snapshots(db, system.id, wall)

    state.infra_synced_at = wall
    state.infra_source_now = source_now
    state.infra_warning = "; ".join(warnings) if warnings else None
    db.commit()

    return {
        "ok": True,
        "agents": agents_upserted,
        "engine_processes": eng_upserted,
        "groups": len(grp_seen),
        "members": len(members),
        "source_now": source_now.isoformat() if source_now else None,
        "warnings": warnings,
        "disabled_tables": sorted(disabled),
    }


def _write_snapshots(db: Session, system_id: int, wall: datetime) -> None:
    for a in db.query(AutomicAgent).filter(AutomicAgent.system_id == system_id).all():
        db.merge(AutomicInfraStatusSnapshot(
            system_id=system_id, kind="agent", name=a.name, snapshot_at=wall,
            status=a.status, host_active=a.host_active, last_life_sign=a.last_life_sign,
            ip=a.ip, detail={"rule": a.status_rule},
        ))
    for e in db.query(AutomicEngineProcess).filter(AutomicEngineProcess.system_id == system_id).all():
        db.merge(AutomicInfraStatusSnapshot(
            system_id=system_id, kind="engine", name=e.name, snapshot_at=wall,
            status=e.status, last_life_sign=e.last_life_sign, ip=e.ip,
            detail={"type": e.process_type, "rule": e.status_rule},
        ))


def rollup_infra_daily(db: Session, system_id: int, day: Optional[date] = None) -> int:
    day = day or (_now().date() - timedelta(days=1))
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    rows = db.query(AutomicInfraStatusSnapshot).filter(
        AutomicInfraStatusSnapshot.system_id == system_id,
        AutomicInfraStatusSnapshot.snapshot_at >= start,
        AutomicInfraStatusSnapshot.snapshot_at < end,
    ).all()
    buckets: Dict[Tuple[str, str], Dict[str, int]] = {}
    for r in rows:
        k = (r.kind, r.name)
        b = buckets.setdefault(k, {"samples": 0, "connected": 0, "disconnected": 0, "unknown": 0, "missing": 0})
        b["samples"] += 1
        st = r.status or "unknown"
        if st in b:
            b[st] += 1
        elif st == "connected":
            b["connected"] += 1
        else:
            b["unknown"] += 1
    n = 0
    for (kind, name), b in buckets.items():
        samples = b["samples"] or 1
        known = b["connected"] + b["disconnected"]
        uptime = (100.0 * b["connected"] / known) if known else None
        db.merge(AutomicInfraDailySummary(
            system_id=system_id, kind=kind, name=name, day=day,
            samples=b["samples"], connected_samples=b["connected"],
            disconnected_samples=b["disconnected"], unknown_samples=b["unknown"],
            missing_samples=b["missing"], approx_uptime_pct=uptime,
        ))
        n += 1
    if n:
        db.commit()
    return n


def _mask_settings(system: AutomicSystem) -> Dict[str, Any]:
    return effective_settings(system.settings).get("masking") or {}


def _apply_mask(val: Optional[str], kind: str, settings: Dict[str, Any]) -> Optional[str]:
    if val is None:
        return None
    m = settings or {}
    cfg = {"mask_ip": bool(m.get("mask_ip")), "mask_hostname": bool(m.get("mask_hostname"))}
    if kind == "ip" and cfg["mask_ip"]:
        return mask_text(val, cfg)
    if kind == "hostname" and cfg["mask_hostname"]:
        return mask_text(val, cfg)
    return val


def list_agents(db: Session, system: AutomicSystem, *,
                status: Optional[str] = None, platform: Optional[str] = None,
                team: Optional[str] = None, group: Optional[str] = None,
                missing_hostname: bool = False) -> Dict[str, Any]:
    settings = effective_settings(system.settings)
    q = db.query(AutomicAgent).filter(AutomicAgent.system_id == system.id)
    status = normalize_status(status)
    if status:
        q = q.filter(AutomicAgent.status == status)
    if platform:
        q = q.filter(AutomicAgent.platform == platform)
    agents = q.all()
    ov = load_overrides(db, system.id)
    mask = _mask_settings(system)
    state = db.get(AutomicCollectorState, system.id)
    group_members: Dict[str, List[str]] = {}
    if group:
        mems = db.query(AutomicAgentGroupMember).filter(
            AutomicAgentGroupMember.system_id == system.id,
            AutomicAgentGroupMember.group_name == group,
        ).all()
        allowed = {m.agent_name for m in mems}
        agents = [a for a in agents if a.name in allowed]
    else:
        for m in db.query(AutomicAgentGroupMember).filter(
            AutomicAgentGroupMember.system_id == system.id
        ).all():
            group_members.setdefault(m.agent_name, []).append(m.group_name)

    # 24h stats
    since = _now() - timedelta(hours=24)
    stats_rows = db.execute(text(
        "SELECT agent, COUNT(*), "
        "SUM(CASE WHEN status_class='failed' THEN 1 ELSE 0 END) "
        "FROM automic_executions WHERE system_id=:sid AND end_time>=:since AND agent IS NOT NULL "
        "GROUP BY agent"
    ), {"sid": system.id, "since": since}).all()
    stats = {r[0]: {"runs_24h": int(r[1]), "failed_24h": int(r[2] or 0)} for r in stats_rows}

    out = []
    for a in agents:
        rh = resolve_hostname(
            agent_name=a.name, ip=a.ip, hostname_automic=a.hostname_automic,
            overrides=ov, settings=settings,
        )
        if missing_hostname:
            # hostname yok veya yalnız IP
            if rh.get("hostname") and rh.get("source") not in (None, "ip_only"):
                continue
        item = {
            "name": a.name,
            "ip": _apply_mask(a.ip, "ip", mask),
            "hostname": _apply_mask(rh.get("hostname"), "hostname", mask),
            "hostname_source": rh.get("source"),
            "hostname_source_label": rh.get("source_label"),
            "os": a.os,
            "platform": a.platform,
            "version": a.version,
            "status": a.status,
            "status_label": status_label_tr(a.status),
            "status_rule": a.status_rule,
            "last_life_sign": a.last_life_sign.isoformat() if a.last_life_sign else None,
            "missing_since": a.missing_since.isoformat() if a.missing_since else None,
            "synced_at": a.synced_at.isoformat() if a.synced_at else None,
            "groups": group_members.get(a.name, []),
            "runs_24h": (stats.get(a.name) or {}).get("runs_24h", 0),
            "failed_24h": (stats.get(a.name) or {}).get("failed_24h", 0),
            "roles": a.roles,
        }
        out.append(item)

    # kopuk / missing üstte
    order = {"disconnected": 0, "missing": 1, "unknown": 2, "connected": 3}
    out.sort(key=lambda x: (order.get(x["status"], 9), x["name"]))

    if team:
        # ekip filtresi — agent'ın son işlerindeki ekipler
        filtered = []
        for item in out:
            teams = _agent_teams(db, system, item["name"])
            item["teams"] = teams
            if team in teams or (team == "unassigned" and not teams):
                filtered.append(item)
        out = filtered
    else:
        for item in out:
            item["teams"] = _agent_teams(db, system, item["name"])

    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "agents": out,
        "synced_at": state.infra_synced_at.isoformat() if state and state.infra_synced_at else None,
        "source_now": state.infra_source_now.isoformat() if state and state.infra_source_now else None,
        "infra_warning": state.infra_warning if state else None,
        "note": "Durum bilgisi anlık değil; son kontrol zamanına aittir.",
        "ae_version": settings.get("ae_version"),
        "ae_version_note": "kurulumda girilen",
    }


def _agent_teams(db: Session, system: AutomicSystem, agent: str, limit: int = 20) -> List[str]:
    rows = db.execute(text(
        "SELECT DISTINCT object_name, client FROM automic_executions "
        "WHERE system_id=:sid AND agent=:ag ORDER BY object_name LIMIT :lim"
    ), {"sid": system.id, "ag": agent, "lim": limit}).all()
    teams: Set[str] = set()
    for object_name, client in rows:
        r = resolve_team_for_object(db, system.id, int(client), object_name)
        if r.get("team"):
            teams.add(r["team"])
    return sorted(teams)


def agent_detail(db: Session, system: AutomicSystem, name: str) -> Dict[str, Any]:
    from app.services.automic.queries import agent_summary
    from app.services.automic.infra_status import rule_label_tr

    a = db.get(AutomicAgent, {"system_id": system.id, "name": name})
    settings = effective_settings(system.settings)
    mask = _mask_settings(system)
    ov = load_overrides(db, system.id)
    state = db.get(AutomicCollectorState, system.id)
    summary = agent_summary(db, system, name, range_="7d")
    summary_24 = agent_summary(db, system, name, range_="24h")

    if a is None:
        return {
            "ok": False, "error": "Agent bulunamadı (altyapı senkronu yapılmamış olabilir)",
            "agent": name, "activity": summary,
        }

    rh = resolve_hostname(
        agent_name=a.name, ip=a.ip, hostname_automic=a.hostname_automic,
        overrides=ov, settings=settings,
    )
    groups = [
        m.group_name for m in db.query(AutomicAgentGroupMember).filter(
            AutomicAgentGroupMember.system_id == system.id,
            AutomicAgentGroupMember.agent_name == name,
        ).all()
    ]
    # 30g timeline
    since = _now() - timedelta(days=30)
    snaps = (
        db.query(AutomicInfraStatusSnapshot)
        .filter(
            AutomicInfraStatusSnapshot.system_id == system.id,
            AutomicInfraStatusSnapshot.kind == "agent",
            AutomicInfraStatusSnapshot.name == name,
            AutomicInfraStatusSnapshot.snapshot_at >= since,
        )
        .order_by(AutomicInfraStatusSnapshot.snapshot_at.asc())
        .limit(2000)
        .all()
    )
    timeline = [
        {"at": s.snapshot_at.isoformat(), "status": s.status}
        for s in snaps
    ]
    connected = sum(1 for s in snaps if s.status == "connected")
    known = sum(1 for s in snaps if s.status in ("connected", "disconnected"))
    uptime = round(100.0 * connected / known, 1) if known else None
    thr = thresholds(settings)

    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "identity": {
            "name": a.name,
            "hostname": _apply_mask(rh.get("hostname"), "hostname", mask),
            "hostname_source": rh.get("source"),
            "hostname_source_label": rh.get("source_label"),
            "hostname_automic": _apply_mask(a.hostname_automic, "hostname", mask),
            "hostname_manual": rh.get("manual_hostname"),
            "hostname_mismatch": bool(
                rh.get("manual_hostname") and a.hostname_automic
                and rh["manual_hostname"] != a.hostname_automic
            ),
            "ip": _apply_mask(a.ip, "ip", mask),
            "os": a.os,
            "platform": a.platform,
            "hardware": a.hardware,
            "version": a.version,
            "port": a.port,
            "roles": a.roles,
        },
        "status": {
            "value": a.status,
            "label": status_label_tr(a.status),
            "rule": a.status_rule,
            "rule_label": rule_label_tr(a.status_rule or ""),
            "last_life_sign": a.last_life_sign.isoformat() if a.last_life_sign else None,
            "host_active": a.host_active,
            "missing_since": a.missing_since.isoformat() if a.missing_since else None,
            "synced_at": a.synced_at.isoformat() if a.synced_at else None,
            "source_now": state.infra_source_now.isoformat() if state and state.infra_source_now else None,
            "approx_uptime_pct": uptime,
            "uptime_note": f"yaklaşık — toplama aralığı: {thr['snapshot_interval_min']} dk",
            "timeline_30d": timeline,
        },
        "workload": {
            "active_now": (summary.get("stats") or {}).get("active_now"),
            "stats_24h": (summary_24.get("stats") or {}),
            "stats_7d": (summary.get("stats") or {}),
            "top_failed": [
                o for o in (summary.get("top_objects") or []) if o.get("failed")
            ][:10],
            "recent_runs": summary.get("recent_runs") or [],
            "active": summary.get("active") or [],
        },
        "context": {
            "groups": groups,
            "teams": _agent_teams(db, system, name, limit=50),
        },
        "note": "Durum bilgisi anlık değil; son kontrol zamanına aittir. Kaynak: Automic DB HOST + MQSRV (Type=8).",
        "ae_version": settings.get("ae_version"),
        "ae_version_note": "kurulumda girilen",
    }


def list_engine_servers(db: Session, system: AutomicSystem) -> Dict[str, Any]:
    settings = effective_settings(system.settings)
    mask = _mask_settings(system)
    ov = load_overrides(db, system.id)
    state = db.get(AutomicCollectorState, system.id)
    procs = db.query(AutomicEngineProcess).filter(
        AutomicEngineProcess.system_id == system.id
    ).all()
    by_ip: Dict[str, List[Dict[str, Any]]] = {}
    for p in procs:
        key = p.ip or p.node or "(bilinmeyen)"
        rh = resolve_hostname(ip=p.ip, overrides=ov, settings=settings)
        node = p.node or rh.get("hostname")
        by_ip.setdefault(key, []).append({
            "name": p.name,
            "process_type": p.process_type,
            "ip": _apply_mask(p.ip, "ip", mask),
            "port": p.port,
            "node": _apply_mask(node, "hostname", mask),
            "hostname_source": rh.get("source_label"),
            "status": p.status,
            "status_label": status_label_tr(p.status),
            "last_life_sign": p.last_life_sign.isoformat() if p.last_life_sign else None,
            "connection_count": p.connection_count,
            "pwp_connected": p.pwp_connected,
            "rest_endpoint": p.rest_endpoint,
            "missing_since": p.missing_since.isoformat() if p.missing_since else None,
            "is_pwp": p.process_type == "PWP" and p.status == "connected",
        })
    servers = []
    for ip, plist in by_ip.items():
        plist.sort(key=lambda x: (0 if x["process_type"] == "PWP" else 1, x["name"]))
        node = plist[0].get("node")
        servers.append({
            "ip": _apply_mask(ip if ip != "(bilinmeyen)" else None, "ip", mask) or ip,
            "node": node,
            "processes": plist,
            "has_active_pwp": any(x.get("is_pwp") for x in plist),
        })
    servers.sort(key=lambda s: (0 if s["has_active_pwp"] else 1, s.get("ip") or ""))
    # Tip bazında özet + aktif PWP tek ve açık
    active_pwp: List[Dict[str, Any]] = []
    server_summaries: List[Dict[str, Any]] = []
    for s in servers:
        counts: Dict[str, int] = {}
        for p in s.get("processes") or []:
            pt = p.get("process_type") or "?"
            counts[pt] = counts.get(pt, 0) + 1
            if p.get("is_pwp"):
                active_pwp.append({
                    "name": p.get("name"), "ip": s.get("ip"), "node": s.get("node"),
                })
        s["type_counts"] = counts
        bits = []
        if s.get("has_active_pwp"):
            bits.append("PWP aktif")
        for pt in ("WP", "CP", "JWP", "JCP", "REST", "PWP"):
            if counts.get(pt):
                bits.append(f"{counts[pt]} {pt}")
        # JCP/REST birleşik etiket
        if counts.get("JCP") or counts.get("REST"):
            pass  # zaten sayıldı
        s["summary_bits"] = bits
        server_summaries.append({
            "ip": s.get("ip"), "node": s.get("node"),
            "has_active_pwp": s.get("has_active_pwp"), "type_counts": counts, "bits": bits,
        })
    lines = [f"Engine {len(servers)} sunucuda:"]
    for s in servers:
        bits = ", ".join(s.get("summary_bits") or [])
        ip = s.get("ip") or "?"
        node = s.get("node")
        # Hostname yoksa veya IP ile aynıysa tekrarlama
        if node and str(node) != str(ip) and not str(node).startswith(str(ip)):
            label = f"{ip} ({node})"
        else:
            label = str(ip)
        lines.append(f"- {label}" + (f": {bits}" if bits else ""))
    if len(active_pwp) == 1:
        ap = active_pwp[0]
        lines.append(f"Aktif PWP tek: {ap.get('name')} @ {ap.get('ip')}.")
    elif len(active_pwp) == 0:
        lines.append("Aktif (connected) PWP yok.")
    else:
        lines.append("Aktif PWP: " + ", ".join(f"{a['name']}@{a['ip']}" for a in active_pwp) + ".")
    # Kopuk process'ler
    disconnected = []
    for s in servers:
        for p in s.get("processes") or []:
            st = (p.get("status") or "").lower()
            lab = (p.get("status_label") or "").lower()
            if st in ("missing", "disconnected") or lab in ("kopuk", "kayıp", "kayip"):
                disconnected.append(f"{s.get('ip')}'de {p.get('name')} kopuk")
    if disconnected:
        lines.append("; ".join(disconnected) + ".")
    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "servers": servers,
        "active_pwp": active_pwp,
        "active_pwp_count": len(active_pwp),
        "disconnected_processes": disconnected,
        "server_summaries": server_summaries,
        "summary_tr": " ".join(lines),
        "synced_at": state.infra_synced_at.isoformat() if state and state.infra_synced_at else None,
        "source_now": state.infra_source_now.isoformat() if state and state.infra_source_now else None,
        "ae_version": settings.get("ae_version"),
        "ae_version_note": "kurulumda girilen",
        "note": "Durum bilgisi anlık değil; son kontrol zamanına aittir. Kaynak: Automic DB MQSRV.",
    }


def engine_server_detail(db: Session, system: AutomicSystem, ip: str) -> Dict[str, Any]:
    overview = list_engine_servers(db, system)
    server = None
    for s in overview.get("servers") or []:
        if s.get("ip") == ip or (s.get("processes") and any(p.get("ip") == ip for p in s["processes"])):
            server = s
            break
    if not server:
        return {"ok": False, "error": "Engine sunucusu bulunamadı", "ip": ip}
    # PWP geçiş geçmişi
    since = _now() - timedelta(days=30)
    pwp_names = [p["name"] for p in server["processes"] if p["process_type"] == "PWP"]
    history = []
    if pwp_names:
        snaps = db.query(AutomicInfraStatusSnapshot).filter(
            AutomicInfraStatusSnapshot.system_id == system.id,
            AutomicInfraStatusSnapshot.kind == "engine",
            AutomicInfraStatusSnapshot.name.in_(pwp_names),
            AutomicInfraStatusSnapshot.snapshot_at >= since,
        ).order_by(AutomicInfraStatusSnapshot.snapshot_at.asc()).limit(500).all()
        history = [
            {"at": s.snapshot_at.isoformat(), "name": s.name, "status": s.status,
             "ip": (s.detail or {}).get("ip") if isinstance(s.detail, dict) else s.ip}
            for s in snaps
        ]
    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "server": server,
        "pwp_history": history,
        "synced_at": overview.get("synced_at"),
        "ae_version": overview.get("ae_version"),
        "ae_version_note": "kurulumda girilen",
        "note": overview.get("note"),
    }


def infrastructure_overview(db: Session, system: AutomicSystem) -> Dict[str, Any]:
    agents = list_agents(db, system)
    engines = list_engine_servers(db, system)
    awi = [
        {
            "id": a.id, "name": a.name, "url": a.url,
            "last_status": a.last_status, "last_check_at": a.last_check_at.isoformat() if a.last_check_at else None,
            "last_http_code": a.last_http_code, "last_error": a.last_error,
        }
        for a in db.query(AutomicAwiServer).filter(
            AutomicAwiServer.system_id == system.id, AutomicAwiServer.enabled.is_(True)
        ).all()
    ]
    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "engines": engines,
        "agents": agents,
        "awi_servers": awi,
        "synced_at": agents.get("synced_at"),
        "note": "Durum bilgisi anlık değil; son kontrol zamanına aittir.",
    }


def enrich_execution_infra(db: Session, system: AutomicSystem, ex: Any) -> Dict[str, Any]:
    """Job detayına agent/ekip alanları."""
    settings = effective_settings(system.settings)
    mask = _mask_settings(system)
    agent = getattr(ex, "agent", None)
    agent_group = getattr(ex, "agent_group", None)
    agent_assigned = getattr(ex, "agent_assigned", None) or agent_group or agent
    actual = agent
    # Grup adı agent kolonundaysa ayır
    if agent and not agent_group:
        grp = db.get(AutomicAgentGroup, {"system_id": system.id, "name": agent})
        if grp:
            agent_assigned = agent
            actual = None
    ag_row = db.get(AutomicAgent, {"system_id": system.id, "name": actual}) if actual else None
    ov = load_overrides(db, system.id)
    rh = resolve_hostname(
        agent_name=actual, ip=ag_row.ip if ag_row else None,
        hostname_automic=ag_row.hostname_automic if ag_row else None,
        overrides=ov, settings=settings,
    ) if actual else {}
    team = resolve_team_for_object(
        db, system.id, int(ex.client), ex.object_name,
    )
    return {
        "agent_assigned": agent_assigned,
        "agent_group": agent_group,
        "agent_actual": actual,
        "agent_status": ag_row.status if ag_row else None,
        "agent_status_label": status_label_tr(ag_row.status) if ag_row else None,
        "agent_synced_at": ag_row.synced_at.isoformat() if ag_row and ag_row.synced_at else None,
        "server_hostname": _apply_mask(rh.get("hostname"), "hostname", mask) if rh else None,
        "server_hostname_source": rh.get("source_label") if rh else None,
        "server_ip": _apply_mask(ag_row.ip, "ip", mask) if ag_row else None,
        "team": team.get("team"),
        "team_rule": team.get("rule_type"),
        "team_rule_label": team.get("rule_label"),
    }
