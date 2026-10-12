"""Yedekleme RPO motoru — deterministik (LLM rakam üretmez; RTO tahmin EDİLMEZ).

Girdi: ``bk_*`` tabloları (sağlayıcı senkronu) + ainew VM envanteri + ``BkRpoPolicy``.
Çıktı: VM başına koruma/RPO durumu ve ``FindingDraft`` listesi.

Kurallar:
* Korumasız / RPO kararında yalnız exact|high eşleşmeler kullanılır; low → ölçülemedi.
* Hedef RPO tanımlı değilse ``bk.vm.rpo_breach`` → not_applicable (skora girmez).
* Sağlayıcı verisi bayatsa (son başarılı senkron > 2×aralık) VM sonuçları
  not_measurable + ``stale=True`` — bayat veriyle "ihlal" iddia edilmez.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.backup import BkJob, BkProtectedObject, BkRepository, BkRpoPolicy, BkSession
from app.models.integration_instance import IntegrationInstance
from app.services.backup.demo_gate import is_demo_kind
from app.services.backup.matching import CONF_LOW, TRUSTED
from app.services.backup.sync import data_age_sec, provider_stale
from app.services.findings.registry import (
    ISO_BACKUP, ISO_CAPACITY, RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS,
)
from app.services.findings.store import FindingDraft

REPO_WARN_PCT = 85.0
REPO_CRIT_PCT = 95.0
JOB_FAIL_WINDOW_H = 24
SCOPE_KINDS = ("vm", "cluster", "all")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _vms(db: Session) -> List[Dict[str, Any]]:
    from app.services import virt_insights_data as vd
    hvs = vd.virt_hypervisors(db, platform="vmware")
    return vd.vm_allocations(db, [h.id for h in hvs])


def resolve_target(policies: List[BkRpoPolicy], vm: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Öncelik: vm > cluster > all. → (rpo_min, rto_min, policy_id)."""
    def pick(kind: str, ref: str) -> Optional[BkRpoPolicy]:
        for p in policies:
            if p.scope_kind == kind and (kind == "all" or (p.scope_ref or "").lower() == (ref or "").lower()):
                return p
        return None
    for kind, ref in (("vm", str(vm.get("name") or "")), ("cluster", str(vm.get("cluster") or "")), ("all", "")):
        p = pick(kind, ref)
        if p is not None and (p.target_rpo_min or p.target_rto_min):
            return (int(p.target_rpo_min) if p.target_rpo_min else None), (int(p.target_rto_min) if p.target_rto_min else None), p.id
    return None, None, None


def backup_instances(db: Session, *, include_demo: bool = False) -> List[IntegrationInstance]:
    """Etkin yedek instance'ları. Varsayılan YALNIZ gerçek sağlayıcılar; DEMO ancak
    ``include_demo=True`` (Yedekleme ekranı / bulgu üreticisi) + açık bayrak + gerçek sağlayıcı yokken
    döner (bkz. ``demo_gate``)."""
    from app.services.backup.demo_gate import active_instances
    return active_instances(db, include_demo=include_demo)


def vm_protection(db: Session, *, now: Optional[datetime] = None,
                  vms: Optional[List[Dict[str, Any]]] = None, include_demo: bool = False) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    insts = {i.id: i for i in backup_instances(db, include_demo=include_demo)}
    if not insts:
        return []
    vms = vms if vms is not None else _vms(db)
    policies = db.query(BkRpoPolicy).all()
    objs = db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_(list(insts))).all()
    by_vm: Dict[int, List[BkProtectedObject]] = {}
    low_by_vm: Dict[int, List[BkProtectedObject]] = {}
    for o in objs:
        if o.matched_vm_id is None:
            continue
        (by_vm if o.match_confidence in TRUSTED else low_by_vm if o.match_confidence == CONF_LOW else {}) \
            .setdefault(o.matched_vm_id, []).append(o)
    stale_any = any(provider_stale(i, now) for i in insts.values())
    out: List[Dict[str, Any]] = []
    for v in vms:
        sid = v["id"]
        trusted, low = by_vm.get(sid, []), low_by_vm.get(sid, [])
        last = max((_aware(o.last_restore_point_at) for o in trusted if o.last_restore_point_at), default=None)
        rpo_t, rto_t, pol = resolve_target(policies, v)
        age_min = round((now - last).total_seconds() / 60.0, 1) if last else None
        if trusted:
            state = "protected"
        elif low:
            state = "low_match"
        else:
            state = "unprotected"
        if state == "protected":
            if rpo_t is None:
                rpo_state = "no_target"
            elif age_min is None:
                rpo_state = "breach"   # nesne var ama pencerede hiç restore point yok
            else:
                rpo_state = "breach" if age_min > rpo_t else "ok"
        else:
            rpo_state = "n/a"
        out.append({
            "server_id": sid, "name": v.get("name"), "cluster": v.get("cluster"), "ref": v.get("ref"),
            "powered_on": bool(v.get("powered_on")), "state": state,
            "match_confidence": (trusted[0].match_confidence if trusted else (low[0].match_confidence if low else "none")),
            "last_restore_point_at": last.isoformat() if last else None, "rpo_age_min": age_min,
            "target_rpo_min": rpo_t, "target_rto_min": rto_t, "policy_id": pol, "rpo_state": rpo_state,
            "stale": stale_any,
            "job_provider_ids": sorted({o.job_provider_id for o in trusted if o.job_provider_id}),
        })
    return out


def summary(db: Session, *, now: Optional[datetime] = None, include_demo: bool = False) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    insts = backup_instances(db, include_demo=include_demo)
    rows = vm_protection(db, now=now, include_demo=include_demo)
    on = [r for r in rows if r["powered_on"] and r["state"] != "low_match"]
    prot = [r for r in on if r["state"] == "protected"]
    jobs = db.query(BkJob).filter(BkJob.instance_id.in_([i.id for i in insts] or [-1])).all()
    repos = db.query(BkRepository).filter(BkRepository.instance_id.in_([i.id for i in insts] or [-1])).all()
    return {
        "providers": [{
            "id": i.id, "label": i.label, "kind": i.kind, "demo": is_demo_kind(i.kind),
            "last_sync_at": i.last_sync_at.isoformat() if i.last_sync_at else None,
            "last_status": i.last_status, "last_error": i.last_error,
            "stale": provider_stale(i, now), "data_age_sec": data_age_sec(i, now),
        } for i in insts],
        "vms_total": len(rows), "powered_on": len(on), "protected": len(prot),
        "unprotected": len([r for r in on if r["state"] == "unprotected"]),
        "low_match": len([r for r in rows if r["state"] == "low_match"]),
        "protected_pct": round(100.0 * len(prot) / len(on), 1) if on else None,
        "rpo_ok": len([r for r in prot if r["rpo_state"] == "ok"]),
        "rpo_breach": len([r for r in prot if r["rpo_state"] == "breach"]),
        "rpo_no_target": len([r for r in prot if r["rpo_state"] == "no_target"]),
        "demo_active": any(is_demo_kind(i.kind) for i in insts),
        "jobs": len(jobs), "jobs_failed": len([j for j in jobs if j.last_result == "Failed"]),
        "repositories": len(repos),
    }


def repo_used_pct(r: BkRepository) -> Optional[float]:
    """1 − free/capacity (usedSpaceGB kullanılmaz: api_ref #3)."""
    if not r.capacity_bytes or r.free_bytes is None:
        return None
    return round(100.0 * (1 - r.free_bytes / r.capacity_bytes), 1)


def backup_findings(db: Session, *, now: Optional[datetime] = None,
                    vms: Optional[List[Dict[str, Any]]] = None) -> List[FindingDraft]:
    """Etkin kümenin (gerçek VEYA — bayrakla — demo; asla karışık) bulguları."""
    now = now or datetime.now(timezone.utc)
    insts = {i.id: i for i in backup_instances(db, include_demo=True)}
    if not insts:
        return []
    out: List[FindingDraft] = []
    stale_any = any(provider_stale(i, now) for i in insts.values())
    age = min((data_age_sec(i, now) or 0.0 for i in insts.values()), default=None)

    for i in insts.values():
        ref = f"instance:{i.id}"
        failed = (i.last_status or "") in ("error", "auth_failed")
        out.append(FindingDraft(
            "bk.provider.sync_failed", "provider", ref, i.label or f"{i.kind}#{i.id}",
            RESULT_FAIL if failed else RESULT_PASS,
            evidence={"status": i.last_status, "error": (i.last_error or "")[:300], "demo": is_demo_kind(i.kind)},
            detail=(i.last_error or "")[:300]))
        if i.last_sync_at is not None:
            st = provider_stale(i, now)
            out.append(FindingDraft(
                "bk.provider.stale", "provider", ref, i.label or f"{i.kind}#{i.id}",
                RESULT_FAIL if st else RESULT_PASS,
                evidence={"last_sync_at": i.last_sync_at.isoformat(), "interval_sec": i.sync_interval_sec},
                detail=f"Veri yaşı {int(data_age_sec(i, now) or 0)} sn", data_age_sec=data_age_sec(i, now)))

    for r in vm_protection(db, now=now, vms=vms, include_demo=True):
        vref = f"vm:{r['ref']}" if r.get("ref") else f"vm:srv-{r['server_id']}"
        common = dict(entity_kind="vm", entity_ref=vref, entity_name=str(r["name"]), cluster_name=r.get("cluster"),
                      stale=bool(r["stale"]), data_age_sec=age if r["stale"] else None)
        if r["state"] == "low_match":
            if r["powered_on"]:
                out.append(FindingDraft("bk.vm.unprotected", common["entity_kind"], vref, common["entity_name"],
                                        RESULT_NOT_MEASURABLE, cluster_name=common["cluster_name"],
                                        detail="Düşük güvenli ad eşleşmesi — eşleşmeyi doğrulayın",
                                        evidence={"match": r["match_confidence"]}))
            continue
        if r["powered_on"]:
            res = RESULT_NOT_MEASURABLE if r["stale"] else (RESULT_PASS if r["state"] == "protected" else RESULT_FAIL)
            out.append(FindingDraft("bk.vm.unprotected", common["entity_kind"], vref, common["entity_name"], res,
                                    cluster_name=common["cluster_name"], stale=common["stale"],
                                    data_age_sec=common["data_age_sec"],
                                    evidence={"match": r["match_confidence"]},
                                    detail="Yedek koruma kaydı yok" if r["state"] != "protected" else ""))
        if r["state"] != "protected":
            continue
        if r["rpo_state"] == "no_target":
            res, sev = RESULT_NOT_APPLICABLE, None
        elif r["stale"]:
            res, sev = RESULT_NOT_MEASURABLE, None
        else:
            res = RESULT_FAIL if r["rpo_state"] == "breach" else RESULT_PASS
            tgt, a = r["target_rpo_min"], r["rpo_age_min"]
            sev = "critical" if (res == RESULT_FAIL and a is not None and tgt and a > 3 * tgt) else None
        out.append(FindingDraft(
            "bk.vm.rpo_breach", "vm", vref, common["entity_name"], res, cluster_name=common["cluster_name"],
            stale=common["stale"], data_age_sec=common["data_age_sec"], severity=sev,
            evidence={"last_restore_point_at": r["last_restore_point_at"], "rpo_age_min": r["rpo_age_min"],
                      "target_rpo_min": r["target_rpo_min"], "policy_id": r["policy_id"]},
            detail=("Hedef RPO tanımlı değil" if r["rpo_state"] == "no_target" else
                    f"Son nokta {r['rpo_age_min']} dk önce; hedef {r['target_rpo_min']} dk")))

    # İşler
    since = now - timedelta(hours=JOB_FAIL_WINDOW_H)
    for j in db.query(BkJob).filter(BkJob.instance_id.in_(list(insts))).all():
        ref = f"job:{j.instance_id}:{j.provider_job_id}"
        last = (db.query(BkSession).filter(BkSession.job_id == j.id).order_by(BkSession.started_at.desc()).first())
        last_failed = bool(last and last.result == "Failed" and (_aware(last.started_at) or since) >= since)
        if not j.enabled:
            res = RESULT_NOT_APPLICABLE
        elif j.last_result == "Failed" or last_failed:
            res = RESULT_FAIL
        elif j.last_result in (None, "None") and j.last_run_at is None:
            res = RESULT_NOT_MEASURABLE
        else:
            res = RESULT_PASS
        out.append(FindingDraft(
            "bk.job.failed_recent", "job", ref, j.name, res, stale=stale_any, data_age_sec=age if stale_any else None,
            evidence={"last_result": j.last_result, "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                      "message": (last.message if last else None), "type": j.job_type},
            detail=(last.message or "")[:300] if (last and res == RESULT_FAIL) else ""))

    # Depolar
    for r in db.query(BkRepository).filter(BkRepository.instance_id.in_(list(insts))).all():
        ref = f"repo:{r.instance_id}:{r.provider_repo_id}"
        pct = repo_used_pct(r)
        if r.is_online is False:
            res, sev, det = RESULT_FAIL, "critical", "Depo çevrimdışı"
        elif pct is None:
            res, sev, det = RESULT_NOT_MEASURABLE, None, "Kapasite bilgisi yok"
        else:
            res = RESULT_FAIL if pct >= REPO_WARN_PCT else RESULT_PASS
            sev = "critical" if pct >= REPO_CRIT_PCT else None
            det = f"Doluluk %{pct} (eşik %{REPO_WARN_PCT:.0f})"
        out.append(FindingDraft("bk.repo.capacity", "repository", ref, r.name, res, severity=sev,
                                stale=stale_any, data_age_sec=age if stale_any else None,
                                evidence={"used_pct": pct, "threshold_pct": REPO_WARN_PCT, "online": r.is_online},
                                detail=det, refs=[ISO_BACKUP, ISO_CAPACITY]))
    from app.services.backup import extras
    out += extras.extra_findings(db, now=now)
    return out


def persist_backup_findings(db: Session, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Capability varken bulguları yazar; yoksa önceki backup bulgularını çözer (etkisiz hale getirir).

    Gerçek sağlayıcı bulguları ``platform="backup"``; DEMO bulguları (yalnız açık bayrakla) ayrı
    ``platform="backup_demo"`` altında yazılır ve varsayılan bulgu sorgularından dışlanır (F.0).
    Mod değişince (bayrak kapandı / gerçek sağlayıcı eklendi) diğer taraftaki aktif bulgular çözülür."""
    from app.services.backup.demo_gate import DEMO_CAPABILITY, DEMO_PLATFORM, backup_mode
    from app.services.capabilities import get_capabilities
    from app.services.findings import store
    caps = get_capabilities(force_refresh=True)
    mode = backup_mode(db)
    have = "backup" in caps and mode == "real"
    have_demo = DEMO_CAPABILITY in caps and mode == "demo"
    drafts = backup_findings(db, now=now) if (have or have_demo) else []
    r = store.persist_findings(db, platform="backup", source_id=None, source_name="backup",
                               categories=("backup",), drafts=drafts if have else [], now=now)
    rd = store.persist_findings(db, platform=DEMO_PLATFORM, source_id=None, source_name="backup (DEMO)",
                                categories=("backup",), drafts=drafts if have_demo else [], now=now)
    db.commit()
    return {"capability": have, "demo": have_demo, **r, "demo_upserted": rd["upserted"], "demo_resolved": rd["resolved"]}
