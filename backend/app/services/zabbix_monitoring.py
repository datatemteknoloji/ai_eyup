"""Zabbix monitoring service — overview, hosts, series, problems, coverage, chat query.

Timescale’e yazmaz; canlı Zabbix API (READ-ONLY).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.services.monitoring_sources import (
    MonitoringSource,
    load_sources_from_db,
    load_sources_runtime,
    list_custom,
    match_custom_label,
    resolve,
)
from app.services.zabbix_client import ZabbixClient, ZabbixError, client_from_source
from app.services.zabbix_metric_map import (
    CATALOG,
    catalog,
    default_chart_metrics,
    families,
    get_metric,
    match_item_to_metrics,
    pick_best_item,
    resolve_metric_id,
)

logger = logging.getLogger(__name__)


def _zabbix_sources(db=None) -> List[MonitoringSource]:
    sources = load_sources_from_db(db) if db is not None else load_sources_runtime()
    return [s for s in list_custom(sources) if s.collector_type == "zabbix"]


def resolve_zabbix_source(
    db=None,
    source_id: Optional[str] = None,
    question: Optional[str] = None,
) -> tuple[Optional[MonitoringSource], Optional[str]]:
    sources = _zabbix_sources(db)
    if not sources:
        return None, "Zabbix Other kaynağı yok (Ayarlar → Monitoring)"

    if source_id:
        sid = source_id[7:] if source_id.startswith("custom:") else source_id
        all_src = load_sources_from_db(db) if db is not None else load_sources_runtime()
        src = resolve(all_src, source_id=sid)
        if src and src.binding == "none" and src.collector_type == "zabbix":
            return src, None
        return None, f"Zabbix kaynağı bulunamadı: {source_id}"

    if question:
        all_src = load_sources_from_db(db) if db is not None else load_sources_runtime()
        hits = [s for s in match_custom_label(question, all_src) if s.collector_type == "zabbix"]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, "Birden fazla Zabbix label eşleşti: " + ", ".join(s.label for s in hits)

    if len(sources) == 1:
        return sources[0], None
    labels = [s.label for s in sources]
    return None, (
        "Birden fazla Zabbix kaynağı var; mesajda label’ın tamamını yazın "
        f"veya source_id verin. Mevcut: {labels}"
    )


def _client(src: MonitoringSource) -> ZabbixClient:
    return client_from_source(src)


def list_sources(db=None) -> List[Dict[str, Any]]:
    return [s.public_dict() for s in _zabbix_sources(db)]


def overview(source_id: Optional[str] = None, db=None) -> Dict[str, Any]:
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err, "configured": False, "source_kind": "zabbix"}
    try:
        client = _client(src)
        ver = client.version()
        hosts = client.hosts(limit=500)
        enabled = [h for h in hosts if str(h.get("status")) == "0"]
        problems = []
        try:
            problems = client.problems(limit=20)
        except ZabbixError as e:
            logger.warning("zabbix problems: %s", e)

        # Sample lastvalues for default metrics on first few hosts
        sample_hosts = enabled[:12]
        hostids = [str(h["hostid"]) for h in sample_hosts if h.get("hostid")]
        items = client.items_for_hosts(hostids, limit=2000) if hostids else []
        by_host: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            by_host.setdefault(str(it.get("hostid")), []).append(it)

        top_cpu: List[Dict[str, Any]] = []
        top_mem: List[Dict[str, Any]] = []
        host_by_id = {str(h["hostid"]): h for h in sample_hosts}
        for hid, hitems in by_host.items():
            h = host_by_id.get(hid) or {}
            name = h.get("name") or h.get("host") or hid
            for mid, bucket in (("cpu_util", top_cpu), ("mem_used_pct", top_mem)):
                mdef = get_metric(mid)
                if not mdef:
                    continue
                best = pick_best_item(hitems, mdef)
                if not best:
                    continue
                try:
                    val = float(best.get("lastvalue"))
                    val = mdef.transform_value(val, str(best.get("key_") or ""))
                except Exception:
                    continue
                bucket.append({
                    "hostid": hid,
                    "host": name,
                    "metric_id": mid,
                    "value": val,
                    "unit": mdef.unit,
                    "item_key": best.get("key_"),
                })
        top_cpu.sort(key=lambda x: x["value"], reverse=True)
        top_mem.sort(key=lambda x: x["value"], reverse=True)

        def _avg(rows: List[Dict[str, Any]]) -> Optional[float]:
            if not rows:
                return None
            return round(sum(float(r["value"]) for r in rows) / len(rows), 1)

        norm_problems = _normalize_problems(problems)
        sev_counts = {"disaster": 0, "high": 0, "average": 0, "warning": 0, "info": 0, "not_classified": 0}
        for p in norm_problems:
            try:
                sev = int(p.get("severity") if p.get("severity") is not None else 0)
            except Exception:
                sev = 0
            # Zabbix: 0 not classified … 5 disaster
            key = {
                5: "disaster", 4: "high", 3: "average", 2: "warning", 1: "info", 0: "not_classified",
            }.get(sev, "not_classified")
            sev_counts[key] = sev_counts.get(key, 0) + 1

        return {
            "ok": True,
            "configured": True,
            "source_kind": "zabbix",
            "source": src.public_dict(),
            "zabbix_version": ver,
            "hosts_total": len(hosts),
            "hosts_enabled": len(enabled),
            "problems_count": len(problems),
            "problems": norm_problems[:10],
            "severity_counts": sev_counts,
            "critical_count": sev_counts["disaster"] + sev_counts["high"],
            "avg_cpu": _avg(top_cpu),
            "avg_mem": _avg(top_mem),
            "top_cpu": top_cpu[:8],
            "top_mem": top_mem[:8],
            "catalog_size": len(CATALOG),
            "default_metrics": default_chart_metrics(),
        }
    except ZabbixError as e:
        return {
            "ok": False,
            "configured": True,
            "error": str(e),
            "source": src.public_dict(),
            "source_kind": "zabbix",
        }


def list_hosts(
    source_id: Optional[str] = None,
    *,
    search: str = "",
    groupid: Optional[str] = None,
    limit: int = 100,
    db=None,
) -> Dict[str, Any]:
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err, "hosts": []}
    try:
        client = _client(src)
        groups = client.hostgroups(limit=200)
        groupids = [groupid] if groupid else None
        hosts = client.hosts(groupids=groupids, search=search, limit=limit)
        out = []
        for h in hosts:
            ifaces = h.get("interfaces") or []
            main_ip = ""
            for iface in ifaces:
                if str(iface.get("main")) == "1" or not main_ip:
                    main_ip = iface.get("ip") or iface.get("dns") or ""
            out.append({
                "hostid": str(h.get("hostid")),
                "host": h.get("host"),
                "name": h.get("name") or h.get("host"),
                "status": h.get("status"),
                "available": h.get("available"),
                "ip": main_ip,
                "groups": [
                    {"groupid": str(g.get("groupid")), "name": g.get("name")}
                    for g in (h.get("groups") or [])
                ],
            })
        return {
            "ok": True,
            "hosts": out,
            "groups": [{"groupid": str(g.get("groupid")), "name": g.get("name")} for g in groups],
            "source": src.public_dict(),
            "source_kind": "zabbix",
        }
    except ZabbixError as e:
        return {"ok": False, "error": str(e), "hosts": []}


def list_problems(
    source_id: Optional[str] = None,
    *,
    hostid: Optional[str] = None,
    limit: int = 50,
    db=None,
) -> Dict[str, Any]:
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err, "problems": []}
    try:
        client = _client(src)
        hostids = [hostid] if hostid else None
        rows = client.problems(hostids=hostids, limit=limit)
        return {
            "ok": True,
            "problems": _normalize_problems(rows),
            "source": src.public_dict(),
            "source_kind": "zabbix",
        }
    except ZabbixError as e:
        return {"ok": False, "error": str(e), "problems": []}


def _normalize_problems(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for p in rows:
        hosts = p.get("hosts") or []
        host_names = [h.get("name") or h.get("host") for h in hosts]
        out.append({
            "eventid": str(p.get("eventid") or ""),
            "name": p.get("name") or "",
            "severity": p.get("severity"),
            "clock": p.get("clock"),
            "acknowledged": p.get("acknowledged"),
            "hosts": host_names,
        })
    return out


def coverage(
    source_id: Optional[str] = None,
    *,
    hostid: Optional[str] = None,
    sample_hosts: int = 5,
    db=None,
) -> Dict[str, Any]:
    """Catalog metric_id → Zabbix item eşleşme durumu."""
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err}
    try:
        client = _client(src)
        if hostid:
            hosts = client.hosts(limit=1, search="")
            # fetch specific
            all_h = client.hosts(limit=500)
            hosts = [h for h in all_h if str(h.get("hostid")) == str(hostid)]
        else:
            hosts = client.hosts(limit=sample_hosts)
        hostids = [str(h["hostid"]) for h in hosts if h.get("hostid")]
        items = client.items_for_hosts(hostids, limit=5000) if hostids else []
        by_host: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            by_host.setdefault(str(it.get("hostid")), []).append(it)

        mapped = []
        unmapped = []
        for mdef in CATALOG:
            found_any = False
            examples = []
            for h in hosts:
                hid = str(h.get("hostid"))
                best = pick_best_item(by_host.get(hid) or [], mdef)
                if best:
                    found_any = True
                    raw_lv = best.get("lastvalue")
                    try:
                        disp = mdef.transform_value(float(raw_lv), str(best.get("key_") or ""))
                    except Exception:
                        disp = raw_lv
                    examples.append({
                        "host": h.get("name") or h.get("host"),
                        "key": best.get("key_"),
                        "itemid": best.get("itemid"),
                        "lastvalue": disp,
                    })
            row = {
                "metric_id": mdef.id,
                "title": mdef.title,
                "family": mdef.family,
                "mapped": found_any,
                "examples": examples[:3],
            }
            (mapped if found_any else unmapped).append(row)

        # Unmapped raw keys sample (not in catalog)
        orphan_keys = []
        seen = set()
        for it in items:
            key = str(it.get("key_") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            if not match_item_to_metrics(key):
                orphan_keys.append(key)
            if len(orphan_keys) >= 40:
                break

        return {
            "ok": True,
            "source": src.public_dict(),
            "hosts_sampled": len(hosts),
            "catalog_total": len(CATALOG),
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "mapped": mapped,
            "unmapped": unmapped,
            "orphan_item_keys_sample": orphan_keys,
            "source_kind": "zabbix",
        }
    except ZabbixError as e:
        return {"ok": False, "error": str(e)}


def series(
    metric_id: str,
    *,
    source_id: Optional[str] = None,
    hostids: Optional[List[str]] = None,
    host_search: str = "",
    range_sec: int = 900,
    top_n: int = 8,
    db=None,
) -> Dict[str, Any]:
    mid = resolve_metric_id(metric_id) or (metric_id or "").strip()
    mdef = get_metric(mid)
    if not mdef:
        return {
            "ok": False,
            "error": f"Bilinmeyen metric_id: {metric_id}. catalog modunu kullanın.",
            "series": [],
        }
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err, "series": []}
    try:
        client = _client(src)
        if hostids:
            all_h = client.hosts(limit=500)
            idset = set(str(x) for x in hostids)
            # Seçim sırasını koru
            by_id = {str(h.get("hostid")): h for h in all_h}
            hosts = [by_id[i] for i in hostids if i in by_id]
        else:
            # Overview Top-N: mümkün olduğunca çok host tara, sonra lastvalue ile sırala
            hosts = client.hosts(search=host_search, limit=500)
        hids = [str(h["hostid"]) for h in hosts if h.get("hostid")]
        items = client.items_for_hosts(hids, limit=8000) if hids else []
        by_host: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            by_host.setdefault(str(it.get("hostid")), []).append(it)

        picked: List[tuple] = []
        for h in hosts:
            hid = str(h.get("hostid"))
            best = pick_best_item(by_host.get(hid) or [], mdef)
            if not best:
                continue
            try:
                lv = float(best.get("lastvalue") or 0)
                lv = mdef.transform_value(lv, str(best.get("key_") or ""))
            except Exception:
                lv = 0.0
            picked.append((lv, h, best))
        if hostids:
            # Çoklu seçimde sıralamayı lastvalue ile değil seçim listesiyle tut; yine de limit
            picked = picked[: max(top_n, len(hostids))]
        else:
            picked.sort(key=lambda x: x[0], reverse=True)
            picked = picked[:top_n]

        now = int(time.time())
        time_from = now - int(range_sec)
        series_out: List[Dict[str, Any]] = []
        for _, h, item in picked:
            try:
                vt = int(item.get("value_type") or 0)
            except Exception:
                vt = 0
            item_key = str(item.get("key_") or "")
            hist = client.history(
                [str(item["itemid"])],
                value_type=vt,
                time_from=time_from,
                time_till=now,
            )
            points = []
            for row in hist:
                try:
                    raw = float(row["value"])
                    points.append({
                        "t": int(row["clock"]),
                        "v": mdef.transform_value(raw, item_key),
                    })
                except Exception:
                    continue
            name = h.get("name") or h.get("host") or str(h.get("hostid"))
            series_out.append({
                "name": name,
                "hostid": str(h.get("hostid")),
                "metric_id": mdef.id,
                "item_key": item.get("key_"),
                "itemid": str(item.get("itemid")),
                "unit": mdef.unit or item.get("units") or "",
                "points": points,
            })

        return {
            "ok": True,
            "metric_id": mdef.id,
            "title": mdef.title,
            "unit": mdef.unit,
            "range_sec": range_sec,
            "series": series_out,
            "source": src.public_dict(),
            "source_kind": "zabbix",
            "note": None if series_out else "Seçilen host’larda bu metric için item bulunamadı (coverage’a bakın).",
        }
    except ZabbixError as e:
        return {"ok": False, "error": str(e), "series": []}


def host_last_values(
    hostid: str,
    *,
    source_id: Optional[str] = None,
    metric_ids: Optional[List[str]] = None,
    db=None,
) -> Dict[str, Any]:
    src, err = resolve_zabbix_source(db, source_id)
    if not src:
        return {"ok": False, "error": err}
    mids = metric_ids or default_chart_metrics()
    try:
        client = _client(src)
        items = client.items_for_hosts([str(hostid)], limit=2000)
        values = []
        for mid in mids:
            mdef = get_metric(mid)
            if not mdef:
                continue
            best = pick_best_item(items, mdef)
            if not best:
                values.append({"metric_id": mid, "mapped": False})
                continue
            try:
                val = float(best.get("lastvalue"))
                val = mdef.transform_value(val, str(best.get("key_") or ""))
            except Exception:
                val = best.get("lastvalue")
            values.append({
                "metric_id": mid,
                "title": mdef.title,
                "unit": mdef.unit,
                "mapped": True,
                "value": val,
                "item_key": best.get("key_"),
                "lastclock": best.get("lastclock"),
            })
        return {"ok": True, "hostid": str(hostid), "values": values, "source_kind": "zabbix"}
    except ZabbixError as e:
        return {"ok": False, "error": str(e)}


def run_zabbix_query(
    *,
    mode: str = "overview",
    source_id: Optional[str] = None,
    metric_id: Optional[str] = None,
    hostid: Optional[str] = None,
    hostids: Optional[List[str]] = None,
    host: Optional[str] = None,
    groupid: Optional[str] = None,
    search: str = "",
    range_sec: int = 900,
    top_n: int = 8,
    question: Optional[str] = None,
    family: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Chat / API handler."""
    mode = (mode or "overview").strip().lower()

    # Infer metric from question
    if not metric_id and question:
        metric_id = resolve_metric_id(question)

    if mode in ("templates", "families"):
        return {"ok": True, "families": families(), "source_kind": "zabbix"}
    if mode == "catalog":
        return {
            "ok": True,
            "catalog": catalog(family),
            "family": family or "all",
            "source_kind": "zabbix",
        }
    if mode == "list_sources":
        return {"ok": True, "sources": list_sources(db), "source_kind": "zabbix"}
    if mode == "hosts":
        return list_hosts(source_id, search=search or (host or ""), groupid=groupid, db=db)
    if mode == "problems":
        return list_problems(source_id, hostid=hostid, db=db)
    if mode == "coverage":
        return coverage(source_id, hostid=hostid, db=db)
    if mode == "host_values" and hostid:
        return host_last_values(hostid, source_id=source_id, db=db)
    if mode == "series" and metric_id:
        ids = hostids
        if hostid:
            ids = [hostid]
        return series(
            metric_id,
            source_id=source_id,
            hostids=ids,
            host_search=host or search or "",
            range_sec=range_sec,
            top_n=top_n,
            db=db,
        )
    if mode == "top" and metric_id:
        return series(
            metric_id,
            source_id=source_id,
            host_search=host or search or "",
            range_sec=range_sec,
            top_n=top_n,
            db=db,
        )

    out = overview(source_id, db=db)
    if question:
        out["question"] = question
        out["hint"] = (
            "İpucu: mode=catalog|hosts|problems|coverage|series|top; "
            "series için metric_id (cpu_util, mem_used_pct, fs_used_pct, …). "
            "Mesajda Zabbix kaynak label’ının tamamı geçmeli."
        )
    return out
