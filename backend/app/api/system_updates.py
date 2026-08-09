"""
Sistem Güncelleme API
POST /updates/check            → Mevcut güncellemeleri kontrol et
POST /updates/suggest-repo     → OS/release bazlı repo önerisi + AI
POST /updates/plans            → Plan oluştur
GET  /updates/plans            → Plan listesi
GET  /updates/plans/{id}       → Plan detayı
POST /updates/plans/{id}/analyze → AI ön analiz
POST /updates/plans/{id}/run   → Planı çalıştır
DELETE /updates/plans/{id}     → Planı sil
GET  /updates/plans/{id}/jobs  → İş listesi
GET  /updates/servers          → Distro filtreli sunucu listesi
"""
import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, require_role
from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
from app.models.app_settings import AppSettings
from app.models.user import User
from app.services.audit import record_audit


def _get_active_model(db: Session) -> str:
    """Ayarlarda seçili modeli döner; yoksa config default'unu kullanır."""
    from app.core.config import settings
    row = db.query(AppSettings).filter_by(key="ollama_active_model").first()
    return (row.value if row and row.value else None) or settings.OLLAMA_DEFAULT_MODEL
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.models.repository import RepoSource
from app.services.system_update_service import (
    check_available_updates,
    _get_management_ip,
    run_system_update_plan,
    recover_stuck_system_update_plans,
    cancel_system_update_plan,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sysupdate")


class CheckRequest(BaseModel):
    server_ids:  List[int]
    update_type: str = "all"
    repo_id:     Optional[int] = None
    override_username:      Optional[str] = None
    override_password:      Optional[str] = None
    override_sudo_password: Optional[str] = None
    priv_method:            Optional[str] = "sudo"

class PlanCreateRequest(BaseModel):
    name:                  str
    update_type:           str          # security | kernel | all | custom
    server_ids:            List[int]
    distro_filter:         Optional[str] = None
    repo_id:               Optional[int] = None
    custom_packages:       Optional[List[str]] = None  # custom modda seçilen paketler
    # Yetkili kullanıcı override
    override_username:      Optional[str] = None
    override_password:      Optional[str] = None
    override_sudo_password: Optional[str] = None
    # Yetki yükseltme yöntemi
    priv_method:            Optional[str] = "sudo"  # sudo | dzdo | direct
    # VM snapshot
    snapshot_mode:          Optional[str] = "skip"   # take | skip
    snapshot_retention:     Optional[str] = "1w"     # 1d | 1w | 1m | indefinite

class SuggestRepoRequest(BaseModel):
    server_ids: List[int]


def _plan_summary(plan: SystemUpdatePlan) -> dict:
    return {
        "id": plan.id, "name": plan.name, "update_type": plan.update_type,
        "distro_filter": plan.distro_filter, "repo_id": plan.repo_id,
        "status": plan.status, "total_servers": plan.total_servers,
        "completed_servers": plan.completed_servers,
        "ai_analysis": plan.ai_analysis, "ai_summary": plan.ai_summary,
        "server_ids": plan.server_ids or [],
        "has_override_creds":  bool(plan.override_username),
        "override_username":   plan.override_username or None,
        "priv_method":         plan.priv_method or "sudo",
        "custom_packages":     plan.custom_packages or [],
        "snapshot_mode":       plan.snapshot_mode or "skip",
        "snapshot_retention":  plan.snapshot_retention or "1w",
        "created_at":   plan.created_at.isoformat()  if plan.created_at   else None,
        "started_at":   plan.started_at.isoformat()  if plan.started_at   else None,
        "completed_at": plan.completed_at.isoformat() if plan.completed_at else None,
    }


def _get_global_cred(db):
    return db.query(GlobalCredential).filter_by(is_default=True).first() \
           or db.query(GlobalCredential).first()


# ─── Sunucu listesi (distro filtreli) ─────────────────────────────────────────

@router.get("/servers")
def list_servers_for_update(distro: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Distro filtresine göre sunucuları listeler.
    OS bilgisi henüz toplanmamış sunucular için os_version (PRETTY_NAME) alanına da bakar.
    Hiç eşleşme yoksa tüm IP'li sunucuları döner.
    """
    # Distro → aranacak string eşlemeleri
    DISTRO_PATTERNS: dict = {
        "rhel":   ["rhel", "red hat", "redhat"],
        "oel":    ["ol", "oel", "oracle"],
        "rocky":  ["rocky"],
        "ubuntu": ["ubuntu"],
        "debian": ["debian"],
        "all":    [],
    }

    # Reboot gereken sunucu ID'leri
    reboot_ids = {
        j.server_id for j in db.query(SystemUpdateJob)
        .filter(SystemUpdateJob.reboot_required == True,
                SystemUpdateJob.rebooted == False,
                SystemUpdateJob.status.in_(["completed", "partial"]))
        .all()
    }

    servers_all = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
    ).order_by(Server.name).all()

    if not distro or distro not in DISTRO_PATTERNS:
        filtered = servers_all
    else:
        patterns = DISTRO_PATTERNS[distro]
        matched = []
        unmatched_noinfo = []

        for s in servers_all:
            # OS bilgisi olan sunucularda eşleşme ara
            searchable = " ".join([
                (s.os_release_id or "").lower(),
                (s.os_type or "").lower(),
                (s.os_version or "").lower(),
            ])
            if any(p in searchable for p in patterns):
                matched.append(s)
            elif not s.os_release_id and not s.os_version:
                # OS bilgisi hiç yok → bu sefer de göster ama işaretle
                unmatched_noinfo.append(s)

        # Eşleşen varsa onları, yoksa OS bilgisi olmayan herkesi göster
        filtered = matched if matched else unmatched_noinfo

    return [
        {
            "id":             s.id,
            "name":           s.name,
            "ip":             s.ip_address,
            "os_type":        s.os_type or "",
            "os_release_id":  s.os_release_id or "",
            "os_version_id":  s.os_version_id or "",
            "os_version":     s.os_version or "",
            "kernel_version": s.kernel_version or "",
            "status":         s.status,
            "has_os_info":    bool(s.os_release_id or s.os_version),
            "reboot_required": s.id in reboot_ids,
            "hypervisor_id":  s.hypervisor_id,
            "hypervisor_vm_id": s.hypervisor_vm_id or "",
            "can_snapshot":   bool(s.hypervisor_id and s.hypervisor_vm_id),
        }
        for s in filtered
    ]


# ─── Güncelleme kontrolü ──────────────────────────────────────────────────────

@router.post("/check")
def check_updates(req: CheckRequest, db: Session = Depends(get_db)):
    """
    Sunucularda güncelleme kontrolü — arka plan job.
    Dönüş: ``{ job_id, status }``; sonuç job.result içinde (GET /servers/bulk-jobs/{id}).
    """
    import threading

    from app.core.database import ThreadSessionLocal
    from app.services import bulk_job_tracker as jobs

    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    if not servers:
        return {"job_id": None, "status": "done", "results": {}}

    ids = [s.id for s in servers]
    job_id = jobs.create_job(
        "sysupdate_check",
        "Sistem güncelleme kontrolü",
        total=len(ids),
        message="SSH kontrol başlıyor...",
    )

    # Capture request fields for background thread
    update_type = req.update_type
    repo_id = req.repo_id
    override_username = req.override_username
    override_password = req.override_password
    override_sudo_password = req.override_sudo_password
    priv_method = req.priv_method or "sudo"

    def _run():
        from concurrent.futures import ThreadPoolExecutor, as_completed

        thread_db = ThreadSessionLocal()
        try:
            srv_list = thread_db.query(Server).filter(Server.id.in_(ids)).all()
            global_cred = _get_global_cred(thread_db)
            repo_content = None
            repo_name = None
            if repo_id:
                repo = thread_db.query(RepoSource).filter_by(id=repo_id).first()
                if repo:
                    from app.services.repo_sync_service import generate_repo_file
                    repo_content = generate_repo_file(repo, _get_management_ip(), 8000)
                    repo_name = repo.name

            results = {}

            def _check_one(srv):
                pkgs = check_available_updates(
                    srv,
                    update_type,
                    global_cred,
                    repo_file_content=repo_content,
                    repo_name=repo_name,
                    override_username=override_username,
                    override_password=override_password,
                    override_sudo_password=override_sudo_password,
                    priv_method=priv_method,
                )
                return str(srv.id), {
                    "server_name": srv.name, "server_ip": srv.ip_address, "packages": pkgs,
                    "count": len([p for p in pkgs if "error" not in p]),
                    "security_count": len([p for p in pkgs if p.get("is_security")]),
                    "kernel_count":   len([p for p in pkgs if p.get("is_kernel")]),
                }

            done = 0
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(_check_one, s): s for s in srv_list}
                for f in as_completed(futures):
                    sid, data = f.result()
                    results[sid] = data
                    done += 1
                    jobs.tick(
                        job_id,
                        done=done,
                        total=len(srv_list),
                        message=f"Kontrol {done}/{len(srv_list)}",
                    )

            jobs.finish(
                job_id,
                status="done",
                message=f"{len(results)} sunucu kontrol edildi",
                result=results,
            )
        except Exception as exc:
            logger.exception("sysupdate check failed")
            jobs.finish(job_id, status="error", message=str(exc), error=str(exc))
        finally:
            thread_db.close()

    threading.Thread(target=_run, daemon=True, name=f"sysupdate-check-{job_id}").start()
    return {"job_id": job_id, "status": "running", "queued": len(ids)}


# ─── AI Repo Önerisi ──────────────────────────────────────────────────────────

@router.post("/suggest-repo")
def suggest_repo_for_servers(req: SuggestRepoRequest, db: Session = Depends(get_db)):
    """
    Sunucuların os_release_id + os_version_id bilgisine göre en uygun
    yerel repoyu önerir. AI ile ek açıklama üretir.
    """
    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    repos   = db.query(RepoSource).filter(
        RepoSource.sync_status.in_(["synced", "partial"])
    ).all()

    RELEASE_TO_TYPE = {
        "rhel": "rhel", "ol": "oel", "rocky": "rocky",
        "almalinux": "alma", "centos": "centos",
        "ubuntu": "ubuntu", "debian": "debian",
    }

    suggestions = {}
    unmatched   = []
    no_os_info  = []

    for srv in servers:
        if not srv.os_release_id and not srv.os_version_id:
            no_os_info.append({"id": srv.id, "name": srv.name,
                               "reason": "OS bilgisi yok — 'OS Bilgisini Yenile' butonunu kullanın"})
            continue

        repo_type  = RELEASE_TO_TYPE.get((srv.os_release_id or "").lower(),
                                          (srv.os_release_id or "").lower())
        major_ver  = (srv.os_version_id or "").split(".")[0] if srv.os_version_id else None

        best_repo  = None
        best_score = 0
        for repo in repos:
            if repo.repo_type != repo_type:
                continue
            score = 1
            if major_ver and (repo.os_version or "").startswith(major_ver):
                score += 2
            if srv.os_version_id and repo.os_version == srv.os_version_id:
                score += 3
            if "baseos" in repo.name.lower():
                score += 1
            if score > best_score:
                best_score = score; best_repo = repo

        if best_repo:
            suggestions[str(srv.id)] = {
                "server_name":  srv.name,
                "os":           f"{(srv.os_release_id or '').upper()} {srv.os_version_id or ''}",
                "kernel":       srv.kernel_version or "",
                "repo_id":      best_repo.id,
                "repo_name":    best_repo.name,
                "repo_display": best_repo.display_name,
                "score":        best_score,
                "confidence":   "yüksek" if best_score >= 5 else ("orta" if best_score >= 3 else "düşük"),
            }
        else:
            unmatched.append({
                "id": srv.id, "name": srv.name,
                "os": f"{srv.os_release_id} {srv.os_version_id}",
                "reason": f"{repo_type.upper()} için senkronize repo bulunamadı",
            })

    # AI ek açıklaması
    ai_comment = None
    if suggestions:
        try:
            from app.services import llm_gateway
            summary_lines = [f"- {v['server_name']}: {v['os']} → {v['repo_display']} ({v['confidence']} güven)"
                             for v in suggestions.values()]
            prompt = f"""Linux sistem yöneticisi olarak aşağıdaki sunucu-repo eşleştirmelerini kısaca değerlendir (Türkçe, 3-4 cümle):
{chr(10).join(summary_lines)}
Eşleşmeyenler: {len(unmatched)} sunucu
Güncelleme öncesi dikkat edilmesi gerekenleri belirt."""
            data = llm_gateway.generate_sync(model=_get_active_model(db), prompt=prompt, timeout=60)
            if not data.get("error"):
                ai_comment = data.get("response", "")
        except Exception:
            pass

    return {
        "suggestions": suggestions,
        "unmatched": unmatched,
        "no_os_info": no_os_info,
        "ai_comment": ai_comment,
    }


# ─── Plan CRUD ────────────────────────────────────────────────────────────────

@router.get("/plans")
def list_plans(limit: int = 50, db: Session = Depends(get_db)):
    plans = db.query(SystemUpdatePlan).order_by(SystemUpdatePlan.created_at.desc()).limit(limit).all()
    return [_plan_summary(p) for p in plans]


@router.post("/plans")
def create_plan(req: PlanCreateRequest, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    if not servers:
        raise HTTPException(400, "Sunucu bulunamadı")
    plan = SystemUpdatePlan(
        name=req.name, update_type=req.update_type,
        distro_filter=req.distro_filter, repo_id=req.repo_id,
        server_ids=req.server_ids, total_servers=len(servers),
        completed_servers=0, status="draft",
        override_username=req.override_username or None,
        override_password=req.override_password or None,
        override_sudo_password=req.override_sudo_password or None,
        priv_method=req.priv_method or "sudo",
        custom_packages=req.custom_packages or [],
        snapshot_mode=req.snapshot_mode or "skip",
        snapshot_retention=req.snapshot_retention or "1w",

    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    for srv in servers:
        db.add(SystemUpdateJob(plan_id=plan.id, server_id=srv.id))
    db.commit()
    return _plan_summary(plan)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")
    return _plan_summary(plan)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")
    if plan.status == "running":
        raise HTTPException(400, "Çalışan plan silinemez")
    db.delete(plan)
    db.commit()
    return {"ok": True}


# ─── AI Ön Analiz ─────────────────────────────────────────────────────────────

@router.post("/plans/{plan_id}/analyze")
def analyze_plan(plan_id: int, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")

    plan.status = "ai_analyzing"
    db.commit()

    servers     = db.query(Server).filter(Server.id.in_(plan.server_ids or [])).all()
    global_cred = _get_global_cred(db)

    all_packages = {}
    for srv in servers[:5]:
        pkgs = check_available_updates(srv, plan.update_type, global_cred)
        all_packages[srv.name] = pkgs[:30]
        job = db.query(SystemUpdateJob).filter_by(plan_id=plan_id, server_id=srv.id).first()
        if job:
            job.packages_to_update = pkgs
    db.commit()

    has_kernel = any(p.get("is_kernel") for pkgs in all_packages.values() for p in pkgs)
    srv_os_info = "\n".join(
        f"- {s.name}: {(s.os_release_id or '?').upper()} {s.os_version_id or ''} | kernel: {s.kernel_version or '?'}"
        for s in servers
    )
    pkg_summary = "\n".join(
        f"- {n}: {len(pkgs)} paket → {', '.join(p.get('name','?') for p in pkgs[:10])}..."
        for n, pkgs in all_packages.items() if pkgs
    )

    prompt = f"""Kıdemli Linux sistem yöneticisi olarak aşağıdaki güncelleme planını analiz et:

Plan: {plan.name} | Tip: {plan.update_type}
Sunucu sayısı: {len(servers)}

Sunucu OS/Kernel bilgileri:
{srv_os_info}

Güncellenecek paketler (örnek):
{pkg_summary if pkg_summary else '(henüz kontrol edilmedi)'}
Kernel güncellemesi: {'VAR' if has_kernel else 'YOK'}

Türkçe, madde madde analiz yap:
1. Risk değerlendirmesi
2. {'Kernel güncellemesi var → reboot gerekecek. Dikkat edilmesi gerekenler?' if has_kernel else 'Kernel güncellemesi yok.'}
3. Önerilen güncelleme sırası
4. Güncelleme öncesi alınacak önlemler
5. Tahmini süre"""

    try:
        from app.services import llm_gateway
        data = llm_gateway.generate_sync(model=_get_active_model(db), prompt=prompt, timeout=120)
        analysis = data.get("response", "AI yanıt vermedi") if not data.get("error") \
                   else f"AI servisine ulaşılamadı: {data['error']}"
    except Exception as e:
        analysis = f"AI analizi yapılamadı: {e}"

    plan.ai_analysis = analysis
    plan.status      = "ai_done"
    db.commit()

    return {"analysis": analysis, "packages_checked": {k: len(v) for k, v in all_packages.items()}}


# ─── Çalıştır ─────────────────────────────────────────────────────────────────

@router.get("/server-history/{server_id}")
def get_server_update_history(server_id: int, db: Session = Depends(get_db)):
    """Sunucunun güncelleme geçmişi: son güncelleme tarihi, güncellenen paketler, reboot durumu."""
    jobs = (
        db.query(SystemUpdateJob)
        .filter_by(server_id=server_id)
        .order_by(SystemUpdateJob.id.desc())
        .limit(5)
        .all()
    )
    history = []
    for j in jobs:
        plan = db.query(SystemUpdatePlan).filter_by(id=j.plan_id).first()
        history.append({
            "job_id":          j.id,
            "plan_id":         j.plan_id,
            "plan_name":       plan.name if plan else "?",
            "update_type":     plan.update_type if plan else "?",
            "status":          j.status,
            "packages_updated":len(j.packages_updated or []),
            "reboot_required": j.reboot_required,
            "rebooted":        j.rebooted,
            "started_at":      j.started_at.isoformat() if j.started_at else None,
            "completed_at":    j.completed_at.isoformat() if j.completed_at else None,
        })
    # Reboot bekleyen job var mı?
    pending_reboot = any(
        j.reboot_required and not j.rebooted
        for j in jobs if j.status in ("completed", "partial")
    )
    return {"history": history, "pending_reboot": pending_reboot}


@router.post("/reboot-servers")
def reboot_servers(server_ids: List[int], db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    """
    Seçili sunucuları SSH ile yeniden başlatır.
    Güvenlik için önce 'shutdown -r +1' ile 1 dakika sonra reboot planlar.
    """
    from app.models.credential import GlobalCredential
    from app.services.system_update_service import _resolve_creds, _make_client, _run
    from concurrent.futures import ThreadPoolExecutor, as_completed

    servers = db.query(Server).filter(Server.id.in_(server_ids)).all()
    gc = _get_global_cred(db)

    results = {}

    def _reboot_one(srv):
        try:
            creds = _resolve_creds(srv, gc)
            sudo  = creds.get("sudo_password")
            client = _make_client(creds)
            # 1 dakika sonra reboot (kullanıcı iptal edebilir)
            code, out, err = _run(client, "shutdown -r +1 'Sistem güncellemesi sonrası yeniden başlatma'",
                                  sudo_pass=sudo, timeout=15)
            client.close()
            return str(srv.id), {"success": code == 0, "server_name": srv.name,
                                  "message": "1 dakika sonra yeniden başlatılacak" if code == 0 else err[:200]}
        except Exception as exc:
            return str(srv.id), {"success": False, "server_name": srv.name, "message": str(exc)}

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_reboot_one, s): s for s in servers}
        for f in as_completed(futures):
            sid, result = f.result()
            results[sid] = result

    # rebooted flag'ini güncelle
    for srv in servers:
        if results.get(str(srv.id), {}).get("success"):
            last_job = (db.query(SystemUpdateJob)
                        .filter_by(server_id=srv.id, reboot_required=True, rebooted=False)
                        .order_by(SystemUpdateJob.id.desc()).first())
            if last_job:
                last_job.rebooted = True
    db.commit()

    return {"results": results}


@router.post("/cancel-reboot")
def cancel_reboot(server_ids: List[int], db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    """Planlanmış reboot'u iptal eder (shutdown -c)."""
    from app.services.system_update_service import _resolve_creds, _make_client, _run
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.models.credential import GlobalCredential

    servers = db.query(Server).filter(Server.id.in_(server_ids)).all()
    gc = _get_global_cred(db)
    results = {}

    def _cancel_one(srv):
        try:
            creds = _resolve_creds(srv, gc)
            client = _make_client(creds)
            code, out, err = _run(client, "shutdown -c 'Reboot iptal edildi'",
                                  sudo_pass=creds.get("sudo_password"), timeout=10)
            client.close()
            return str(srv.id), {"success": code == 0, "server_name": srv.name}
        except Exception as exc:
            return str(srv.id), {"success": False, "server_name": srv.name, "message": str(exc)}

    with ThreadPoolExecutor(max_workers=10) as pool:
        for f in as_completed({pool.submit(_cancel_one, s): s for s in servers}):
            sid, res = f.result()
            results[sid] = res

    return {"results": results}


@router.post("/plans/{plan_id}/jobs/{job_id}/rerun")
def rerun_job(plan_id: int, job_id: int, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    """
    Tamamlanmış (başarılı veya başarısız) bir job'u orijinal parametrelerle yeniden çalıştırır.
    """
    from app.models.credential import GlobalCredential
    from app.models.repository import RepoSource
    from app.services.repo_sync_service import generate_repo_file
    from app.services.system_update_service import _get_management_ip
    from datetime import datetime, timezone
    import threading

    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    job  = db.query(SystemUpdateJob).filter_by(id=job_id, plan_id=plan_id).first()
    if not plan or not job:
        raise HTTPException(404, "Plan veya iş bulunamadı")
    if job.status == "running":
        raise HTTPException(400, "İş zaten çalışıyor")

    srv = db.query(Server).filter_by(id=job.server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")

    # Job'u sıfırla
    job.status           = "running"
    job.started_at       = datetime.now(timezone.utc)
    job.completed_at     = None
    job.log              = f"[YENIDEN ÇALIŞTIRILDI] {datetime.now(timezone.utc).strftime('%H:%M:%S')}\n"
    job.packages_updated = []
    job.reboot_required  = False
    db.commit()

    # Thread için snapshot
    server_id   = srv.id
    plan_type   = plan.update_type
    plan_repo   = plan.repo_id
    over_user   = plan.override_username
    over_pass   = plan.override_password
    over_sudo   = plan.override_sudo_password
    priv_method = plan.priv_method or "sudo"
    custom_pkgs = list(plan.custom_packages or [])

    def _do_rerun():
        from app.services.system_update_service import apply_updates_to_server
        from app.core.database import ThreadSessionLocal
        from app.models.repository import RepoSource
        from app.services.repo_sync_service import generate_repo_file
        from datetime import datetime, timezone
        _db = ThreadSessionLocal()
        try:
            _srv = _db.query(Server).filter_by(id=server_id).first()
            _gc  = _db.query(GlobalCredential).filter_by(is_default=True).first() \
                   or _db.query(GlobalCredential).first()
            _repo_name = None; _repo_content = None
            if plan_repo:
                _repo = _db.query(RepoSource).filter_by(id=plan_repo).first()
                if _repo:
                    _repo_content = generate_repo_file(_repo, _get_management_ip(), 8000)
                    _repo_name = _repo.name
            result = apply_updates_to_server(
                _srv, plan_type, _gc, _repo_content, _repo_name,
                override_username=over_user, override_password=over_pass,
                override_sudo_password=over_sudo, priv_method=priv_method,
                custom_packages=custom_pkgs, job_id=job_id,
            )
            j = _db.query(SystemUpdateJob).filter_by(id=job_id).first()
            if j:
                j.status           = result["status"]
                j.packages_updated = result.get("packages_updated", [])
                j.reboot_required  = result.get("reboot_required", False)
                j.completed_at     = datetime.now(timezone.utc)
                _db.commit()
        except Exception as exc:
            logger.error(f"rerun #{job_id}: {exc}", exc_info=True)
            j = _db.query(SystemUpdateJob).filter_by(id=job_id).first()
            if j:
                j.status = "failed"
                j.log    = (j.log or "") + f"\n[HATA] {exc}"
                _db.commit()
        finally:
            _db.close()

    threading.Thread(target=_do_rerun, daemon=True, name=f"rerun-{job_id}").start()
    return {"ok": True, "message": f"İş #{job_id} yeniden başlatıldı"}


@router.post("/plans/{plan_id}/rerun-failed")
def rerun_failed_jobs(plan_id: int, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    """
    Bir plandaki başarısız/iptal edilmiş tüm job'ları yeniden başlatır.
    Plan durumunu 'running' olarak günceller.
    """
    from datetime import datetime, timezone

    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")
    if plan.status == "running":
        raise HTTPException(400, "Plan zaten çalışıyor")

    all_jobs = db.query(SystemUpdateJob).filter(SystemUpdateJob.plan_id == plan_id).all()

    # Hâlâ çalışan job'lar varsa — sadece plan durumunu düzelt, yeni thread açma
    running_jobs = [j for j in all_jobs if j.status == "running"]
    failed_jobs  = [j for j in all_jobs if j.status in ("failed", "cancelled", "error")]

    if not failed_jobs and not running_jobs:
        raise HTTPException(400, "Yeniden başlatılacak başarısız iş bulunamadı")

    if not failed_jobs and running_jobs:
        # Plan zaten devam ediyor, sadece durumu güncelle
        plan.status = "running"
        plan.completed_at = None
        db.commit()
        return {"ok": True, "restarted": 0,
                "message": f"{len(running_jobs)} iş zaten çalışıyor, plan durumu güncellendi"}

    # Plan + job durumlarını sıfırla
    plan.status = "running"
    plan.completed_at = None
    for job in failed_jobs:
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.completed_at = None
        job.log = f"[TEKRAR BAŞLATILDI] {datetime.now(timezone.utc).strftime('%H:%M:%S')}\n"
        job.packages_updated = []
        job.reboot_required = False
    db.commit()

    # Her job için ayrı thread başlat
    for job in failed_jobs:
        job_id    = job.id
        server_id = job.server_id
        plan_type = plan.update_type
        plan_repo = plan.repo_id
        over_user = plan.override_username
        over_pass = plan.override_password
        over_sudo = plan.override_sudo_password
        priv_method   = plan.priv_method or "sudo"
        custom_pkgs   = list(plan.custom_packages or [])

        def _do_rerun(jid=job_id, sid=server_id):
            from app.services.system_update_service import apply_updates_to_server
            from app.core.database import ThreadSessionLocal
            from app.models.repository import RepoSource
            from app.services.repo_sync_service import generate_repo_file
            from app.services.system_update_service import _get_management_ip
            _db = ThreadSessionLocal()
            try:
                _srv  = _db.query(Server).filter_by(id=sid).first()
                _gc   = _db.query(GlobalCredential).filter_by(is_default=True).first() \
                        or _db.query(GlobalCredential).first()
                _repo_name = None; _repo_content = None
                if plan_repo:
                    _repo = _db.query(RepoSource).filter_by(id=plan_repo).first()
                    if _repo:
                        _repo_content = generate_repo_file(_repo, _get_management_ip(), 8000)
                        _repo_name = _repo.name
                result = apply_updates_to_server(
                    _srv, plan_type, _gc, _repo_content, _repo_name,
                    override_username=over_user, override_password=over_pass,
                    override_sudo_password=over_sudo, priv_method=priv_method,
                    custom_packages=custom_pkgs, job_id=jid,
                )
                j = _db.query(SystemUpdateJob).filter_by(id=jid).first()
                if j:
                    j.status           = result["status"]
                    j.packages_updated = result.get("packages_updated", [])
                    j.reboot_required  = result.get("reboot_required", False)
                    j.completed_at     = datetime.now(timezone.utc)
                    _db.commit()
                # Plan durumunu güncelle
                _check_and_finalize_plan(_db, plan_id)
            except Exception as exc:
                logger.error(f"rerun-failed job #{jid}: {exc}", exc_info=True)
                j = _db.query(SystemUpdateJob).filter_by(id=jid).first()
                if j:
                    j.status = "failed"
                    j.log = (j.log or "") + f"\n[HATA] {exc}"
                    _db.commit()
                _check_and_finalize_plan(_db, plan_id)
            finally:
                _db.close()

        threading.Thread(target=_do_rerun, daemon=True,
                         name=f"rerun-failed-{job_id}").start()

    return {
        "ok": True,
        "restarted": len(failed_jobs),
        "message": f"{len(failed_jobs)} başarısız iş yeniden başlatıldı",
    }


def _check_and_finalize_plan(db, plan_id: int) -> None:
    """Tüm job'lar bittiyse plan durumunu günceller."""
    from datetime import datetime, timezone
    try:
        jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
        if not jobs:
            return
        statuses = {j.status for j in jobs}
        if statuses & {"running", "pending"}:
            return  # Hâlâ devam eden var
        plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
        if not plan or plan.status not in ("running",):
            return
        if all(j.status == "completed" for j in jobs):
            plan.status = "completed"
        elif any(j.status == "completed" for j in jobs):
            plan.status = "partial"
        else:
            plan.status = "failed"
        plan.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        logger.debug(f"_check_and_finalize_plan: {e}")


@router.post("/plans/{plan_id}/jobs/{job_id}/fetch-packages")
def fetch_updated_packages(plan_id: int, job_id: int, db: Session = Depends(get_db)):
    """Tamamlanmış job için dnf history üzerinden güncellenen paket listesini çeker."""
    from app.services.system_update_service import _resolve_creds, _make_client
    job = db.query(SystemUpdateJob).filter_by(id=job_id, plan_id=plan_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    if job.packages_updated:
        return {"packages": job.packages_updated, "count": len(job.packages_updated)}

    srv = db.query(Server).filter_by(id=job.server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")

    gc = _get_global_cred(db)
    creds = _resolve_creds(srv, gc)
    try:
        client = _make_client(creds)
        _, out, _ = client.exec_command(
            "dnf history info last 2>/dev/null | grep -E '^ *Upgrade|^ *Install' | awk '{print $2}' | head -200",
            timeout=15, get_pty=False
        )
        text = out.read().decode("utf-8", errors="replace")
        out.channel.recv_exit_status()
        client.close()

        pkgs = []
        seen = set()
        for line in text.splitlines():
            name = line.strip().rsplit(".", 1)[0] if "." in line.strip() else line.strip()
            if name and name not in seen and not name.startswith("#"):
                seen.add(name)
                pkgs.append({"name": name, "version": ""})

        if pkgs:
            job.packages_updated = pkgs
            db.commit()

        return {"packages": pkgs, "count": len(pkgs)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/plans/{plan_id}/jobs/{job_id}/retry-with-fix")
def retry_job_with_fix(plan_id: int, job_id: int, db: Session = Depends(get_db)):
    """
    Başarısız job'ı AI önerilen flag'lerle yeniden çalıştırır.
    Hata içeriğine göre otomatik flag seçer:
    - "cannot install both" / "obsoletes" → --allowerasing
    - "skip-broken" önerisi → --skip-broken
    - "nobest" önerisi → --nobest
    """
    from app.models.credential import GlobalCredential
    from app.models.repository import RepoSource
    from app.services.repo_sync_service import generate_repo_file
    from app.services.system_update_service import (
        _resolve_creds, _make_client, _run_streaming, _detect_pkg_manager,
        _get_management_ip, _write_job_log,
    )
    import threading

    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    job  = db.query(SystemUpdateJob).filter_by(id=job_id, plan_id=plan_id).first()
    if not plan or not job:
        raise HTTPException(404, "Plan veya iş bulunamadı")
    if job.status == "running":
        raise HTTPException(400, "İş zaten çalışıyor")

    srv = db.query(Server).filter_by(id=job.server_id).first()
    if not srv:
        raise HTTPException(404, "Sunucu bulunamadı")

    # Hata log'undan uygulanacak fix'i belirle
    log_text = job.log or ""
    extra_flags = ""
    fix_desc    = "Standart parametrelerle"

    if "cannot install both" in log_text or "obsoletes" in log_text:
        extra_flags = "--allowerasing"
        fix_desc    = "--allowerasing (çakışan paketleri değiştir)"
    elif "skip-broken" in log_text or "broken" in log_text.lower():
        extra_flags = "--skip-broken --nobest"
        fix_desc    = "--skip-broken --nobest (sorunlu paketleri atla)"
    elif "no match" in log_text.lower() or "not found" in log_text.lower():
        extra_flags = "--skip-unavailable"
        fix_desc    = "--skip-unavailable (bulunamayan paketleri atla)"
    else:
        extra_flags = "--nobest --skip-broken"
        fix_desc    = "--nobest --skip-broken (genel hata kurtarma)"

    global_cred = _get_global_cred(db)

    # Repo bilgisi
    repo_name = None
    repo_file_content = None
    if plan.repo_id:
        repo = db.query(RepoSource).filter_by(id=plan.repo_id).first()
        if repo:
            repo_file_content = generate_repo_file(repo, _get_management_ip(), 8000)
            repo_name = repo.name

    # Job'u running yap
    from datetime import datetime, timezone
    job.status     = "running"
    job.started_at = datetime.now(timezone.utc)
    job.log        = f"[FIX] {fix_desc} ile yeniden deneniyor...\n"
    db.commit()

    # Thread için snapshot al (detached object hatası önle)
    server_id_snap  = srv.id
    plan_type_snap  = plan.update_type
    plan_repo_snap  = plan.repo_id
    plan_over_user  = plan.override_username
    plan_over_pass  = plan.override_password
    plan_over_sudo  = plan.override_sudo_password
    plan_priv_snap  = plan.priv_method or "sudo"
    plan_pkgs_snap  = list(plan.custom_packages or [])

    def _run_fix():
        from app.services.system_update_service import apply_updates_to_server
        from app.core.database import ThreadSessionLocal
        from app.models.repository import RepoSource
        from app.services.repo_sync_service import generate_repo_file
        from datetime import datetime, timezone
        _db = ThreadSessionLocal()
        try:
            _srv  = _db.query(Server).filter_by(id=server_id_snap).first()
            _gc   = _db.query(GlobalCredential).filter_by(is_default=True).first() \
                    or _db.query(GlobalCredential).first()
            _repo_name = None; _repo_content = None
            if plan_repo_snap:
                _repo = _db.query(RepoSource).filter_by(id=plan_repo_snap).first()
                if _repo:
                    from app.services.system_update_service import _get_management_ip
                    _repo_content = generate_repo_file(_repo, _get_management_ip(), 8000)
                    _repo_name = _repo.name
            result = apply_updates_to_server(
                _srv, plan_type_snap, _gc,
                _repo_content, _repo_name,
                override_username=plan_over_user,
                override_password=plan_over_pass,
                override_sudo_password=plan_over_sudo,
                priv_method=plan_priv_snap,
                custom_packages=plan_pkgs_snap,
                job_id=job_id,
                extra_flags=extra_flags,
            )
            j = _db.query(SystemUpdateJob).filter_by(id=job_id).first()
            if j:
                j.status           = result["status"]
                j.packages_updated = result.get("packages_updated", [])
                j.reboot_required  = result.get("reboot_required", False)
                j.completed_at     = datetime.now(timezone.utc)
                _db.commit()
        except Exception as exc:
            logger.error(f"retry_with_fix #{job_id}: {exc}", exc_info=True)
            j = _db.query(SystemUpdateJob).filter_by(id=job_id).first()
            if j:
                j.status = "failed"
                j.log    = (j.log or "") + f"\n[RETRY HATA] {exc}"
                _db.commit()
        finally:
            _db.close()

    threading.Thread(target=_run_fix, daemon=True, name=f"retry-{job_id}").start()
    return {"ok": True, "fix": fix_desc, "extra_flags": extra_flags}


@router.post("/plans/{plan_id}/jobs/{job_id}/analyze-error")
def analyze_job_error(plan_id: int, job_id: int, db: Session = Depends(get_db)):
    """Başarısız job'ın hata logunu AI ile analiz eder ve çözüm önerir."""
    from app.core.config import settings
    job  = db.query(SystemUpdateJob).filter_by(id=job_id, plan_id=plan_id).first()
    if not job:
        raise HTTPException(404, "İş bulunamadı")
    if job.status != "failed":
        raise HTTPException(400, "Sadece başarısız işler analiz edilebilir")
    if not job.log:
        raise HTTPException(400, "Log kaydı yok")

    srv = db.query(Server).filter_by(id=job.server_id).first()
    srv_name = srv.name if srv else f"Server #{job.server_id}"
    os_info  = f"{(srv.os_release_id or '').upper()} {srv.os_version_id or ''}" if srv else ""

    # Log'un hata kısmını al
    log_tail = "\n".join(job.log.splitlines()[-40:])

    prompt = f"""Bir Linux sistem güncellemesi sırasında hata oluştu. Türkçe analiz yap:

Sunucu: {srv_name} {os_info}
Güncelleme tipi: {db.query(SystemUpdatePlan).filter_by(id=plan_id).first().update_type if db.query(SystemUpdatePlan).filter_by(id=plan_id).first() else '?'}

Hata logu (son 40 satır):
{log_tail}

Lütfen şunları açıkla:
1. **Hatanın sebebi nedir?**
2. **Çözüm önerisi:** Hangi komut/adım ile düzeltilebilir?
3. **Risk:** Bu hatayı yok sayarsak ne olur?

Kısa ve pratik ol."""

    try:
        from app.services import llm_gateway
        active_model = _get_active_model(db)
        data = llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=90)
        analysis = data.get("response", "AI yanıt vermedi") if not data.get("error") \
                   else f"AI servisine ulaşılamadı: {data['error']}"
    except Exception as e:
        analysis = f"AI analizi yapılamadı: {e}"

    return {"analysis": analysis, "job_id": job_id, "server_name": srv_name}


@router.post("/plans/{plan_id}/run")
def run_plan(plan_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")
    if plan.status == "running":
        raise HTTPException(400, "Plan zaten çalışıyor — iptal edip yeniden deneyin")
    plan.status = "running"
    plan.completed_at = None
    db.commit()
    record_audit(db, category="system_update", action="system_update.run", actor=user,
                 target_type="plan", target_id=plan_id,
                 summary=f"Güncelleme planı başlatıldı: {plan.name}"
                         f" ({plan.total_servers} sunucu)")
    _executor.submit(run_system_update_plan, plan_id)
    return {"ok": True, "status": "running"}


@router.post("/plans/{plan_id}/cancel")
def cancel_plan(plan_id: int, db: Session = Depends(get_db), _=Depends(require_role("operator"))):
    """Takılı veya çalışan planı iptal eder."""
    result = cancel_system_update_plan(plan_id, db)
    if not result.get("ok"):
        raise HTTPException(400, result.get("message", "İptal edilemedi"))
    return result


@router.post("/recover-stuck")
def recover_stuck_plans(db: Session = Depends(get_db), max_minutes: int = 30):
    """Takılı kalan güncelleme job/planlarını temizler."""
    return recover_stuck_system_update_plans(db, max_minutes=max_minutes)


# ─── İş listesi ───────────────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/jobs")
def list_jobs(plan_id: int, db: Session = Depends(get_db)):
    from app.models.vm_snapshot import VMSnapshot
    jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
    result = []
    for j in jobs:
        srv = db.query(Server).filter_by(id=j.server_id).first()
        snap = (
            db.query(VMSnapshot)
            .filter_by(plan_id=plan_id, server_id=j.server_id)
            .order_by(VMSnapshot.created_at.desc())
            .first()
        )
        snap_info = None
        if snap:
            snap_info = {
                "status": snap.status,
                "snapshot_name": snap.snapshot_name,
                "error_message": snap.error_message,
            }
        result.append({
            "id": j.id, "server_id": j.server_id,
            "server_name": srv.name if srv else "?",
            "server_ip":   srv.ip_address if srv else "?",
            "os_type":     (srv.os_release_id or srv.os_type or "") if srv else "?",
            "os_version":  (srv.os_version_id or "") if srv else "?",
            "status": j.status,
            "packages_to_update": j.packages_to_update or [],
            "packages_updated":   j.packages_updated or [],
            "reboot_required": j.reboot_required,
            "log":          j.log,
            "started_at":   j.started_at.isoformat()  if j.started_at  else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "snapshot": snap_info,
        })
    return result
