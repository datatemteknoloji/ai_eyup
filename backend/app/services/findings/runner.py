"""Karar katmanı turu: topla → snapshot → değerlendir → bulguları kalıcılaştır.

Fleet job (`fleet.virt_insights`) her `virt_insights_interval_sec` saniyede bir
çalıştırır; datastore dosya taraması `virt_insights_file_scan_hours` aralıkla
yapılır (ağır olduğu için). Bir platformun toplayıcısı hata verirse yalnız
DB'den hesaplanabilen kategoriler (kapasite) güncellenir; diğer bulgular
korunur (yanlışlıkla "çözüldü" görünmez).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.infra_finding import InfraCheckRun, VirtDatastoreFile
from app.services import virt_insights_data as vd
from app.services.findings import store
from app.services.findings.registry import CHECKS

logger = logging.getLogger(__name__)

HEALTH_CATS = ("health", "hardware", "compliance")


def _setting_int(key: str, default: int) -> int:
    try:
        from app.services.runtime_settings import get_int
        return int(get_int(key))
    except Exception:
        return default


def _file_scan_due(db: Session, platform: str, source_id: int) -> bool:
    hours = _setting_int("virt_insights_file_scan_hours", 24)
    last = (db.query(func.max(InfraCheckRun.finished_at))
            .filter(InfraCheckRun.platform == platform, InfraCheckRun.source_id == source_id,
                    InfraCheckRun.status.in_(("ok", "partial")),
                    InfraCheckRun.stats["file_scan"].as_string() == "true")
            .scalar())
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(hours=max(1, hours))


def _collect(db: Session, platform: str, hv, file_scan: bool) -> Dict[str, Any]:
    if platform == "vmware":
        from app.services.findings.collectors import vmware
        return vmware.collect(hv, file_scan=file_scan)
    if platform == "olvm":
        from app.services.findings.collectors import olvm
        return olvm.collect(hv, file_scan=file_scan)
    if platform == "ocp_virt":
        from app.services.findings.collectors import ocp_virt
        return ocp_virt.collect(db, hv, file_scan=file_scan)
    return {"ok": False, "error": f"desteklenmeyen platform {platform}"}


def _save_snapshots(db: Session, platform: str, hv_id: int, col: Dict[str, Any], now: datetime) -> Dict:
    since: Dict = {}
    for c in col.get("clusters") or []:
        cfg = dict(c.get("config") or {})
        if c.get("host_names") is not None:
            cfg["hosts"] = c["host_names"]
        if c.get("datastore_refs") is not None:
            cfg["datastore_refs"] = sorted(c["datastore_refs"])
        store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="cluster",
                                   entity_ref=str(c["name"]), entity_name=c["name"], cluster_name=c["name"],
                                   config=cfg, state=c.get("state"), now=now)
    for h in col.get("hosts") or []:
        snap = store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="host",
                                          entity_ref=str(h["ref"]), entity_name=h["name"],
                                          cluster_name=h.get("cluster"), config=h.get("config"),
                                          state=h.get("state"), now=now)
        since[("host", str(h["ref"]))] = {
            k: store.state_since(snap, k) for k in (h.get("state") or {}) if not k.startswith("_")
        }
    for d in col.get("datastores") or []:
        store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="datastore",
                                   entity_ref=str(d["ref"]), entity_name=d["name"], cluster_name=None,
                                   config=d.get("config"), state=d.get("state"), now=now)
    if platform == "ocp_virt":
        for v in col.get("vms") or []:
            store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="vm",
                                       entity_ref=str(v["ref"]), entity_name=v["ref"],
                                       cluster_name=(col.get("platform") or {}).get("cluster_name"),
                                       config=v.get("config"), state=None, now=now)
        if col.get("platform"):
            p = col["platform"]
            store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="platform",
                                       entity_ref="platform", entity_name=p.get("cluster_name") or "platform",
                                       cluster_name=p.get("cluster_name"),
                                       config={"default_eviction": p.get("default_eviction"),
                                               "hco_version": (p.get("hco") or {}).get("version")},
                                       state={"hco_available": (p.get("hco") or {}).get("available")}, now=now)
    if col.get("about"):
        store.save_config_snapshot(db, platform=platform, source_id=hv_id, entity_kind="platform",
                                   entity_ref="manager", entity_name=str(col["about"].get("fullName")
                                                                         or col["about"].get("name") or "manager"),
                                   cluster_name=None, config=col["about"], state=None, now=now)
    return since


def _to_dt(v: Any) -> Optional[datetime]:
    if v is None or isinstance(v, datetime):
        return v
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _save_files(db: Session, platform: str, hv_id: int, files: List[Dict[str, Any]], now: datetime) -> int:
    db.query(VirtDatastoreFile).filter(VirtDatastoreFile.platform == platform,
                                       VirtDatastoreFile.source_id == hv_id).delete(synchronize_session=False)
    for f in files:
        db.add(VirtDatastoreFile(
            platform=platform, source_id=hv_id, kind=f["kind"], datastore=f.get("datastore"),
            path=str(f["path"])[:1024], name=(f.get("name") or "")[:512], size_gb=f.get("size_gb"),
            modified_at=_to_dt(f.get("modified_at")), owner_vm=(f.get("owner_vm") or None),
            attached=f.get("attached"), extra=f.get("extra") or {}, as_of=now,
        ))
    db.flush()
    return len(files)


def run_for_hypervisor(db: Session, hv, *, file_scan: Optional[bool] = None,
                       capacity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from app.services import virt_config_drift, virt_health_checks, virt_reclaim, virt_reference_checks
    platform = vd.platform_of(hv)
    if not platform:
        return {"skipped": True}
    now = store.utcnow()
    do_scan = _file_scan_due(db, platform, hv.id) if file_scan is None else bool(file_scan)
    run = InfraCheckRun(platform=platform, source_id=hv.id, source_name=hv.name, kind="full",
                        status="running", started_at=now, stats={})
    db.add(run)
    db.commit()
    stats: Dict[str, Any] = {"file_scan": do_scan}
    errors: List[str] = []
    try:
        col = _collect(db, platform, hv, do_scan)
        if not col.get("ok"):
            errors.append(col.get("error") or "toplama başarısız")
        else:
            since = _save_snapshots(db, platform, hv.id, col, now)
            if col.get("unsupported_paths"):
                stats["unsupported_paths"] = col["unsupported_paths"][:50]
            hw = virt_health_checks.hardware_context(db, hv.id) if platform in ("vmware", "olvm") else {}
            drafts = virt_health_checks.evaluate(platform, col, since=since, hw=hw)
            r = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                       categories=HEALTH_CATS, drafts=drafts, run_id=run.id, now=now)
            stats["health"] = {**virt_health_checks.summarize(drafts), **r}

            vm_cluster = {}
            for a in vd.vm_allocations(db, [hv.id]):
                vm_cluster[a["name"]] = a.get("cluster")
            rdrafts = virt_reclaim.reclaim_findings(platform, col, vm_cluster)
            files = col.get("files")
            scope = ["reclaim.vm.snapshot_age"]
            if files is not None:
                stats["files"] = _save_files(db, platform, hv.id, files, now)
                stats["file_scan_detail"] = {k: v for k, v in (col.get("file_scan") or {}).items() if k != "files"}
                scope += ["reclaim.file.orphan_disk", "reclaim.file.unused_iso"]
            elif do_scan:
                stats["file_scan_error"] = (col.get("file_scan") or {}).get("error")
            r = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                       categories=("reclaim",), drafts=rdrafts, run_id=run.id, now=now,
                                       resolve_checks=scope)
            stats["reclaim"] = r

            ddrafts = virt_config_drift.drift_findings(db, platform, hv.id)
            stats["drift"] = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                                    categories=("drift",), drafts=ddrafts, run_id=run.id, now=now)

            vdrafts = virt_reference_checks.vuln_findings(db, platform, col)
            if vdrafts is not None:
                stats["vuln"] = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                                       categories=("vuln",), drafts=vdrafts, run_id=run.id, now=now)
            kdrafts = virt_reference_checks.known_issue_findings(db, platform, hv.id, col)
            if kdrafts is not None:
                stats["known_issue"] = store.persist_findings(
                    db, platform=platform, source_id=hv.id, source_name=hv.name,
                    categories=("known_issue",), drafts=kdrafts, run_id=run.id, now=now)
            udrafts = virt_reference_checks.upgrade_findings(
                platform, col, virt_reference_checks.get_ref(db, "upgrade_matrix"))
            stats["upgrade"] = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                                      categories=("upgrade",), drafts=udrafts, run_id=run.id, now=now)
        # Kapasite DB'den hesaplanır — toplayıcı başarısız olsa da güncellenir
        if capacity is not None:
            from app.services.virt_capacity_planner import capacity_findings
            cdrafts = capacity_findings(capacity).get((platform, hv.id), [])
            stats["capacity"] = store.persist_findings(db, platform=platform, source_id=hv.id, source_name=hv.name,
                                                       categories=("capacity",), drafts=cdrafts, run_id=run.id, now=now)
        run.status = "ok" if not errors else ("partial" if capacity is not None else "error")
        run.error = "; ".join(errors)[:2000] or None
    except Exception as exc:
        logger.exception("virt_insights turu hata (%s)", hv.name)
        db.rollback()
        run = db.query(InfraCheckRun).get(run.id) or run
        run.status = "error"
        run.error = str(exc)[:2000]
    run.stats = stats
    run.finished_at = store.utcnow()
    db.add(run)
    db.commit()
    return {"hypervisor": hv.name, "platform": platform, "status": run.status, "error": run.error, "stats": stats}


def run_cycle(db: Session, *, hypervisor_id: Optional[int] = None, platform: Optional[str] = None,
              file_scan: Optional[bool] = None, include_ocp: bool = True) -> Dict[str, Any]:
    from app.services.virt_capacity_planner import build_capacity
    hvs = vd.virt_hypervisors(db, platform=platform if platform != "ocp" else None, hypervisor_id=hypervisor_id)
    if platform == "ocp":
        hvs = []
    try:
        capacity = build_capacity(db, hypervisor_id=hypervisor_id, platform=platform if platform != "ocp" else None)
    except Exception as exc:
        logger.exception("kapasite hesabı başarısız")
        db.rollback()
        capacity = None
    results = [run_for_hypervisor(db, hv, file_scan=file_scan, capacity=capacity) for hv in hvs]
    if include_ocp and not hypervisor_id and platform in (None, "ocp"):
        try:
            from app.services.ocp_insights import run_ocp_cycle
            results.extend(run_ocp_cycle(db))
        except Exception as exc:
            logger.exception("OCP insights turu başarısız")
            db.rollback()
            results.append({"platform": "ocp", "status": "error", "error": str(exc)})
    return {"ok": True, "runs": results, "checks": len(CHECKS)}
