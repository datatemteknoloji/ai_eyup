"""Dilim E — yedeğe bağlı ek deterministik analizler.

Yalnız ``backup`` capability varken çağrılır. Tüm rakamlar bk_* tablolarından
hesaplanır; LLM rakam üretmez, RTO tahmin EDİLMEZ.

Doğrulanmamış Veeam alanlarına dayanılmaz (bkz. veeam_api_ref.py belirsizlik listesi):
* Değişmezlik (immutability): F.1'de şema okundu, alan YOK → daima ``not_measurable`` (bk.repo.immutability).
* Şifreleme / CBT (F.1): Get All Jobs alanlarından; eksik/yetkisiz → ``not_measurable``.
* 3-2-1: yalnız "copy" tipi iş varlığı denetlenir (harici/immutable kopya doğrulanmaz).
* Değişim oranı: oturum ``transferredSize`` (doc) toplamı — iş bazlı, VM bazlı değil.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.backup import (
    BkJob, BkProtectedObject, BkRepository, BkRestoreTest, BkSession,
)
from app.services.backup import rpo_engine as eng
from app.services.backup.veeam_api_ref import REVISIONS
from app.services.findings.registry import (
    ISO_BACKUP, RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS,
)
from app.services.findings.store import FindingDraft

SPIKE_FACTOR = 2.0          # son oturum aktarımı > 2× önceki medyan
OVERRUN_FACTOR = 1.5        # son oturum süresi > 1.5× önceki medyan
MIN_HISTORY = 5             # trend için gerekli önceki oturum sayısı
HISTORY_DAYS = 30


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ok(res: Optional[str]) -> bool:
    return (res or "").lower() in ("success", "warning")


def _job_ids(db: Session, *, include_demo: bool = False) -> Dict[int, BkJob]:
    ids = [i.id for i in eng.backup_instances(db, include_demo=include_demo)]
    return {j.id: j for j in db.query(BkJob).filter(BkJob.instance_id.in_(ids or [-1])).all()}


# ── Madde 9/E: iş trendleri (değişim oranı sıçraması, pencere aşımı) ──────────

def job_trend_findings(db: Session, *, now: Optional[datetime] = None) -> List[FindingDraft]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=HISTORY_DAYS)
    out: List[FindingDraft] = []
    for j in _job_ids(db, include_demo=True).values():
        if not j.enabled:
            continue
        ss = (db.query(BkSession).filter(BkSession.job_id == j.id, BkSession.started_at >= since)
              .order_by(BkSession.started_at.asc()).all())
        ss = [s for s in ss if _ok(s.result) and s.ended_at is not None and s.started_at is not None]
        ref = f"job:{j.instance_id}:{j.provider_job_id}"
        if len(ss) < MIN_HISTORY + 1:
            for cid in ("bk.job.change_rate_spike", "bk.job.window_overrun"):
                out.append(FindingDraft(cid, "job", ref, j.name, RESULT_NOT_MEASURABLE,
                                        detail=f"Trend için en az {MIN_HISTORY + 1} başarılı oturum gerekli (var: {len(ss)})"))
            continue
        last, prev = ss[-1], ss[-1 - MIN_HISTORY - 20:-1]
        tr = [s.transferred_bytes for s in prev if s.transferred_bytes]
        if last.transferred_bytes and len(tr) >= MIN_HISTORY:
            med = statistics.median(tr)
            ratio = last.transferred_bytes / med if med else None
            out.append(FindingDraft(
                "bk.job.change_rate_spike", "job", ref, j.name,
                RESULT_FAIL if (ratio and ratio >= SPIKE_FACTOR) else RESULT_PASS,
                evidence={"last_gb": round(last.transferred_bytes / 1024 ** 3, 2), "median_gb": round(med / 1024 ** 3, 2),
                          "ratio": round(ratio, 2) if ratio else None, "factor": SPIKE_FACTOR},
                detail=f"Son aktarım medyanın {ratio:.1f}× katı" if ratio else ""))
        else:
            out.append(FindingDraft("bk.job.change_rate_spike", "job", ref, j.name, RESULT_NOT_MEASURABLE,
                                    detail="Aktarım boyutu verisi yok"))
        dur = [(s.ended_at - s.started_at).total_seconds() for s in prev]
        d_last = (last.ended_at - last.started_at).total_seconds()
        dmed = statistics.median(dur) if dur else 0
        ratio_d = d_last / dmed if dmed else None
        out.append(FindingDraft(
            "bk.job.window_overrun", "job", ref, j.name,
            RESULT_FAIL if (ratio_d and ratio_d >= OVERRUN_FACTOR) else RESULT_PASS,
            evidence={"last_min": round(d_last / 60, 1), "median_min": round(dmed / 60, 1),
                      "ratio": round(ratio_d, 2) if ratio_d else None, "factor": OVERRUN_FACTOR},
            detail=f"Son süre medyanın {ratio_d:.1f}× katı" if ratio_d else ""))
    return out


# ── F.1: iş yapılandırması kuralları (şifreleme / CBT) + depo değişmezliği (daima ölçülemedi) ──

def _vbr_type(j: BkJob) -> str:
    try:
        return str((json.loads(j.meta_json or "{}")).get("vbr_type") or "")
    except ValueError:
        return ""


def _cfg_unavailable(j: BkJob) -> Optional[str]:
    st = j.config_state
    if st == "forbidden":
        return "ölçülemedi (yetki): GET /api/v1/jobs bu hesapla okunamadı"
    if st == "error":
        return "ölçülemedi: iş yapılandırması okunamadı"
    if st is None:
        return "ölçülemedi: iş yapılandırması henüz okunmadı"
    return None


def job_config_findings(db: Session) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    for j in _job_ids(db, include_demo=True).values():
        ref = f"job:{j.instance_id}:{j.provider_job_id}"
        if not j.enabled:
            for cid in ("bk.job.encryption_off", "bk.job.cbt_off"):
                out.append(FindingDraft(cid, "job", ref, j.name, RESULT_NOT_APPLICABLE, detail="İş devre dışı"))
            continue
        why = _cfg_unavailable(j)
        # şifreleme — backup/copy/replica işleri için ortak alan; yoksa ölçülemedi
        if why or j.encryption_enabled is None:
            out.append(FindingDraft("bk.job.encryption_off", "job", ref, j.name, RESULT_NOT_MEASURABLE,
                                    detail=why or "Yanıtta şifreleme alanı yok"))
        else:
            out.append(FindingDraft("bk.job.encryption_off", "job", ref, j.name,
                                    RESULT_PASS if j.encryption_enabled else RESULT_FAIL,
                                    evidence={"encryption_enabled": j.encryption_enabled}))
        # CBT — yalnız VMware yedek işleri
        if _vbr_type(j) != "VSphereBackup":
            out.append(FindingDraft("bk.job.cbt_off", "job", ref, j.name, RESULT_NOT_APPLICABLE,
                                    detail="CBT yalnız VMware (VSphereBackup) işleri için uygulanır"))
        elif why or j.cbt_enabled is None:
            out.append(FindingDraft("bk.job.cbt_off", "job", ref, j.name, RESULT_NOT_MEASURABLE,
                                    detail=why or "Yanıtta CBT alanı yok"))
        else:
            out.append(FindingDraft("bk.job.cbt_off", "job", ref, j.name,
                                    RESULT_PASS if j.cbt_enabled else RESULT_FAIL,
                                    evidence={"cbt_enabled": j.cbt_enabled}))
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    for r in db.query(BkRepository).filter(BkRepository.instance_id.in_(ids or [-1])).all():
        out.append(FindingDraft("bk.repo.immutability", "repository", f"repo:{r.instance_id}:{r.provider_repo_id}", r.name,
                                RESULT_NOT_MEASURABLE, evidence={"repo_type": r.repo_type},
                                detail="Doğrulanamaz: REST yanıt şemasında değişmezlik alanı yok "
                                       f"(depo türü: {r.repo_type or 'bilinmiyor'})"))
    return out


# ── Madde 12: RTO doğrulanmamış / 3-2-1 kopya / API revizyonu ────────────────

def last_restore_test(db: Session, protected_object_ids: List[int]) -> Optional[BkRestoreTest]:
    if not protected_object_ids:
        return None
    return (db.query(BkRestoreTest).filter(BkRestoreTest.protected_object_id.in_(protected_object_ids))
            .order_by(BkRestoreTest.tested_at.desc()).first())


def policy_findings(db: Session, *, now: Optional[datetime] = None,
                    vms: Optional[List[Dict[str, Any]]] = None) -> List[FindingDraft]:
    now = now or datetime.now(timezone.utc)
    out: List[FindingDraft] = []
    insts = eng.backup_instances(db, include_demo=True)
    # RTO doğrulanmamış: hedef RTO var + restore testi yok
    objs_by_vm: Dict[int, List[int]] = {}
    for o in db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_([i.id for i in insts] or [-1]),
                                                 BkProtectedObject.match_confidence.in_(("exact", "high"))).all():
        if o.matched_vm_id is not None:
            objs_by_vm.setdefault(o.matched_vm_id, []).append(o.id)
    for r in eng.vm_protection(db, now=now, vms=vms, include_demo=True):
        if r["state"] != "protected":
            continue
        vref = f"vm:{r['ref']}" if r.get("ref") else f"vm:srv-{r['server_id']}"
        rto = r.get("target_rto_min")
        if not rto:
            res, det, ev = RESULT_NOT_APPLICABLE, "Hedef RTO tanımlı değil", {}
        else:
            t = last_restore_test(db, objs_by_vm.get(r["server_id"], []))
            if t is None or t.tested_at is None:
                res, det, ev = RESULT_FAIL, "Hedef RTO var ama kayıtlı geri yükleme testi yok (RTO tahmin edilmez)", {"target_rto_min": rto}
            else:
                age = (now - _aware(t.tested_at)).days
                res = RESULT_FAIL if age > 180 else RESULT_PASS
                det = f"Son geri yükleme testi {age} gün önce"
                ev = {"target_rto_min": rto, "tested_at": t.tested_at.isoformat(), "duration_sec": t.duration_sec}
        out.append(FindingDraft("bk.vm.rto_unverified", "vm", vref, str(r["name"]), res, cluster_name=r.get("cluster"),
                                evidence=ev, detail=det, stale=bool(r["stale"])))
    # 3-2-1 (yalnız copy işi varlığı)
    jobs = list(_job_ids(db).values())
    has_copy = any(j.job_type == "copy" and j.enabled for j in jobs)
    for i in insts:
        out.append(FindingDraft(
            "bk.copy.missing", "provider", f"instance:{i.id}", i.label or f"{i.kind}#{i.id}",
            RESULT_PASS if has_copy else RESULT_FAIL,
            evidence={"copy_jobs": sum(1 for j in jobs if j.job_type == "copy"), "verified": "yalnız iş varlığı"},
            detail="" if has_copy else "Etkin 'copy' tipi iş yok (3-2-1 ikinci kopya kanıtı eksik)"))
        try:
            rev = (json.loads(i.meta_json or "{}") or {}).get("api_revision")
        except ValueError:
            rev = None
        if i.kind == "veeam_vbr" and rev in REVISIONS:
            dep = REVISIONS[rev][0] != "supported"
            out.append(FindingDraft(
                "bk.provider.api_revision_deprecated", "provider", f"instance:{i.id}", i.label or f"{i.kind}#{i.id}",
                RESULT_FAIL if dep else RESULT_PASS,
                evidence={"api_revision": rev, "status": REVISIONS[rev][0], "vbr_build": REVISIONS[rev][1]},
                detail=f"REST revizyonu {rev} Veeam dokümanında '{REVISIONS[rev][0]}' (VBR {REVISIONS[rev][1]})"))
    return out


def extra_findings(db: Session, *, now: Optional[datetime] = None) -> List[FindingDraft]:
    return job_trend_findings(db, now=now) + job_config_findings(db) + policy_findings(db, now=now)


def _encryption_item(jobs: Dict[int, BkJob]) -> Dict[str, Any]:
    act = [j for j in jobs.values() if j.enabled and j.job_type == "backup"]
    meas = [j for j in act if j.encryption_enabled is not None and j.config_state == "ok"]
    off = [j for j in meas if j.encryption_enabled is False]
    st = "ölçülemedi" if not meas else ("eksik" if off else "ok")
    note = "İş düzeyi şifreleme (storageData.encryption.isEnabled); depo/donanım şifrelemesi okunmaz."
    if act and len(meas) < len(act):
        note += f" {len(act) - len(meas)} iş için alan okunamadı (ölçülemedi)."
    return {"control": "ISO27001:A.8.13", "item": "Yedek işlerinde şifreleme", "status": st,
            "value": f"{len(meas) - len(off)}/{len(meas)}" if meas else None, "note": note}


# ── Madde 12: ISO 27001 A.8.13 kanıtı ───────────────────────────────────────

def evidence(db: Session, *, now: Optional[datetime] = None, days: int = 30) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    from app.services.backup.demo_gate import BANNER_TR, backup_mode
    if backup_mode(db) == "demo":
        # F.0: DEMO veriden ISO A.8.13 kanıtı ÜRETİLMEZ (denetim belgesi gerçek veriye dayanmalı).
        return {"generated_at": now.isoformat(), "window_days": days, "items": [], "jobs": [], "demo": True,
                "blocked": True, "blocked_reason": f"{BANNER_TR}: ISO 27001 A.8.13 kanıtı demo veriden üretilmez.",
                "not_checked": []}
    since = now - timedelta(days=days)
    jobs = _job_ids(db)
    rows = []
    tot = ok = 0
    for j in sorted(jobs.values(), key=lambda x: x.name or ""):
        ss = db.query(BkSession).filter(BkSession.job_id == j.id, BkSession.started_at >= since).all()
        done = [s for s in ss if s.result]
        n_ok = sum(1 for s in done if _ok(s.result))
        tot += len(done)
        ok += n_ok
        rows.append({"job": j.name, "type": j.job_type, "enabled": j.enabled, "sessions": len(done),
                     "success_pct": round(100 * n_ok / len(done), 1) if done else None,
                     "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                     "last_result": j.last_result})
    prot = eng.vm_protection(db, now=now)
    on = [r for r in prot if r["powered_on"]]
    covered = [r for r in on if r["state"] == "protected"]
    last_test = db.query(BkRestoreTest).order_by(BkRestoreTest.tested_at.desc()).first()
    tested = last_test.tested_at.isoformat() if last_test and last_test.tested_at else None
    items = [
        {"control": "ISO27001:A.8.13", "item": "Yedekleme işleri tanımlı ve etkin",
         "status": "ok" if any(j.enabled for j in jobs.values()) else "eksik", "value": len(jobs)},
        {"control": "ISO27001:A.8.13", "item": f"Son {days} gün oturum başarı oranı",
         "status": ("ok" if tot and ok / tot >= 0.95 else "eksik") if tot else "ölçülemedi",
         "value": f"%{round(100 * ok / tot, 1)}" if tot else None},
        {"control": "ISO27001:A.8.13", "item": "Açık VM'lerin yedek kapsamı",
         "status": "ok" if on and len(covered) == len(on) else ("eksik" if on else "ölçülemedi"),
         "value": f"{len(covered)}/{len(on)}"},
        {"control": "ISO27001:A.8.13", "item": "Geri yükleme testi kaydı",
         "status": "ok" if tested else "eksik", "value": tested,
         "note": "ainew geri yükleme testi yapmaz/okumaz; kayıt yoksa 'eksik' raporlanır."},
        {"control": "ISO27001:A.8.13", "item": "İkinci kopya (copy işi)",
         "status": "ok" if any(j.job_type == "copy" and j.enabled for j in jobs.values()) else "eksik",
         "value": sum(1 for j in jobs.values() if j.job_type == "copy")},
        _encryption_item(jobs),
    ]
    return {"generated_at": now.isoformat(), "window_days": days, "items": items, "jobs": rows,
            "demo": False, "blocked": False,
            "not_checked": ["Değişmezlik (immutability) — REST şemasında alan yok (doğrulanamaz)",
                            "VBR yapılandırma yedeği",
                            "Depo/donanım düzeyi şifreleme (yalnız iş düzeyi şifreleme okunur)"]}


# ── Madde 10: drift ↔ yedek hatası korelasyonu ──────────────────────────────

def failure_after_change(db: Session, *, now: Optional[datetime] = None, hours: int = 72) -> List[Dict[str, Any]]:
    from app.models.server import Server
    from app.services.virt_incident_timeline import _config_changes
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    jobs = _job_ids(db, include_demo=True)
    out: List[Dict[str, Any]] = []
    for j in jobs.values():
        bad = (db.query(BkSession).filter(BkSession.job_id == j.id, BkSession.started_at >= since)
               .order_by(BkSession.started_at.asc()).all())
        bad = [s for s in bad if (s.result or "").lower() == "failed"]
        if not bad:
            continue
        first = _aware(bad[0].started_at)
        vm_ids = {o.matched_vm_id for o in db.query(BkProtectedObject).filter(
            BkProtectedObject.instance_id == j.instance_id, BkProtectedObject.job_provider_id == j.provider_job_id,
            BkProtectedObject.match_confidence.in_(("exact", "high"))).all() if o.matched_vm_id}
        names: Set[str] = set()
        clusters: Set[str] = set()
        for s in db.query(Server).filter(Server.id.in_(list(vm_ids) or [-1])).all():
            names.update(x for x in (s.vm_name, s.name) if x)
            if s.vm_cluster:
                clusters.add(s.vm_cluster)
        ch = [c for c in _config_changes(db, first - timedelta(hours=hours), first, names, set()) if c["entity"] in names]
        if ch:
            out.append({"job": j.name, "first_failed_at": first.isoformat(), "message": (bad[0].message or "")[:300],
                        "changes": ch[:10],
                        "note": "Zamansal korelasyon; kök neden kesin değildir. Değişiklik zamanı toplama turuna bağlıdır."})
    return out


# ── Madde 13: zaman çizelgesi öğeleri ──────────────────────────────────────

def timeline_items(db: Session, start: datetime, end: datetime, server_ids: Set[int]) -> List[Dict[str, Any]]:
    """Penceredeki yedek oturumları (VM'e eşleşen işler). Capability yoksa boş."""
    from app.services.capabilities import get_capabilities
    if not server_ids or "backup" not in get_capabilities():
        return []
    ids = [i.id for i in eng.backup_instances(db)]
    pairs = {(o.instance_id, o.job_provider_id): o.matched_vm_id for o in db.query(BkProtectedObject).filter(
        BkProtectedObject.instance_id.in_(ids or [-1]), BkProtectedObject.matched_vm_id.in_(list(server_ids)),
        BkProtectedObject.match_confidence.in_(("exact", "high")), BkProtectedObject.job_provider_id.isnot(None)).all()}
    if not pairs:
        return []
    out: List[Dict[str, Any]] = []
    for j in db.query(BkJob).filter(BkJob.instance_id.in_(ids)).all():
        if (j.instance_id, j.provider_job_id) not in pairs:
            continue
        for s in db.query(BkSession).filter(BkSession.job_id == j.id, BkSession.started_at <= end).all():
            st, en = _aware(s.started_at), _aware(s.ended_at) or end
            if st is None or en < start:
                continue
            failed = (s.result or "").lower() == "failed"
            out.append({"t": st.isoformat(), "kind": "backup_session", "source": "backup",
                        "entity": j.name, "title": f"Yedek oturumu: {j.name} ({s.result or 'çalışıyor'})",
                        "detail": (s.message or "")[:300], "severity": "high" if failed else "info",
                        "tags": ["backup"],
                        "note": "Yedek oturumu VM snapshot oluşturma/commit (stun) ile eş zamanlı olabilir; zamansal örtüşmedir, nedensellik kanıtı değil."})
    return out


# ── Kapasite what-if: depo boyutu ───────────────────────────────────────────

def repo_whatif(db: Session, *, add_vms: int = 0, avg_vm_gb: Optional[float] = None,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """Yeni VM eklenirse depo doluluğu. VM başına tahmin = mevcut kullanılan / korunan nesne sayısı
    (kullanıcı ``avg_vm_gb`` verirse o). Bu bir doğrusal projeksiyondur; sıkıştırma/dedupe/saklama etkisi modellenmez."""
    ids = [i.id for i in eng.backup_instances(db, include_demo=True)]
    repos = db.query(BkRepository).filter(BkRepository.instance_id.in_(ids or [-1])).all()
    cap = sum(r.capacity_bytes or 0 for r in repos)
    free = sum(r.free_bytes or 0 for r in repos if r.free_bytes is not None)
    n_obj = db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_(ids or [-1])).count()
    used = cap - free if cap else 0
    per_vm = (avg_vm_gb * 1024 ** 3) if avg_vm_gb else (used / n_obj if n_obj else None)
    if not cap or per_vm is None:
        return {"ok": False, "reason": "Depo kapasitesi veya korunan nesne verisi yok", "assumptions": []}
    after_used = used + per_vm * max(0, add_vms)
    pct_before, pct_after = 100 * used / cap, 100 * after_used / cap
    return {"ok": True, "add_vms": add_vms, "per_vm_gb": round(per_vm / 1024 ** 3, 1),
            "used_pct_before": round(pct_before, 1), "used_pct_after": round(pct_after, 1),
            "fits_below_warn": pct_after < eng.REPO_WARN_PCT, "warn_pct": eng.REPO_WARN_PCT,
            "assumptions": ["Doğrusal projeksiyon; saklama politikası, sıkıştırma ve tekilleştirme modellenmez.",
                            "Tüm depolar toplanır (iş→depo eşlemesi yok)."]}
