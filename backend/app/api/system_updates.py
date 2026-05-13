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
from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.models.repository import RepoSource
from app.services.system_update_service import check_available_updates, run_system_update_plan

logger = logging.getLogger(__name__)
router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sysupdate")


class CheckRequest(BaseModel):
    server_ids:  List[int]
    update_type: str = "all"

class PlanCreateRequest(BaseModel):
    name:                  str
    update_type:           str
    server_ids:            List[int]
    distro_filter:         Optional[str] = None
    repo_id:               Optional[int] = None
    # Yetkili kullanıcı override
    override_username:      Optional[str] = None
    override_password:      Optional[str] = None
    override_sudo_password: Optional[str] = None
    # Yetki yükseltme yöntemi
    priv_method:            Optional[str] = "sudo"  # sudo | dzdo | su | pbrun | direct

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
        "has_override_creds": bool(plan.override_username),
        "override_username":  plan.override_username or None,
        "priv_method":        plan.priv_method or "sudo",
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
        }
        for s in filtered
    ]


# ─── Güncelleme kontrolü ──────────────────────────────────────────────────────

@router.post("/check")
def check_updates(req: CheckRequest, db: Session = Depends(get_db)):
    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    global_cred = _get_global_cred(db)
    results = {}

    def _check_one(srv):
        pkgs = check_available_updates(srv, req.update_type, global_cred)
        return str(srv.id), {
            "server_name": srv.name, "server_ip": srv.ip_address, "packages": pkgs,
            "count": len([p for p in pkgs if "error" not in p]),
            "security_count": len([p for p in pkgs if p.get("is_security")]),
            "kernel_count":   len([p for p in pkgs if p.get("is_kernel")]),
        }

    with ThreadPoolExecutor(max_workers=5) as pool:
        from concurrent.futures import as_completed
        futures = {pool.submit(_check_one, s): s for s in servers}
        for f in as_completed(futures):
            sid, data = f.result()
            results[sid] = data
    return results


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
            from app.core.config import settings
            summary_lines = [f"- {v['server_name']}: {v['os']} → {v['repo_display']} ({v['confidence']} güven)"
                             for v in suggestions.values()]
            prompt = f"""Linux sistem yöneticisi olarak aşağıdaki sunucu-repo eşleştirmelerini kısaca değerlendir (Türkçe, 3-4 cümle):
{chr(10).join(summary_lines)}
Eşleşmeyenler: {len(unmatched)} sunucu
Güncelleme öncesi dikkat edilmesi gerekenleri belirt."""
            r = http_requests.post(
                f"{settings.OLLAMA_URL}/api/generate",
                json={"model": "qwen2.5:latest", "prompt": prompt, "stream": False},
                timeout=60,
            )
            if r.status_code == 200:
                ai_comment = r.json().get("response", "")
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
def create_plan(req: PlanCreateRequest, db: Session = Depends(get_db)):
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
def delete_plan(plan_id: int, db: Session = Depends(get_db)):
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
def analyze_plan(plan_id: int, db: Session = Depends(get_db)):
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
        from app.core.config import settings
        r = http_requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": "qwen2.5:latest", "prompt": prompt, "stream": False},
            timeout=120,
        )
        analysis = r.json().get("response", "AI yanıt vermedi") if r.status_code == 200 \
                   else f"AI servisine ulaşılamadı (HTTP {r.status_code})"
    except Exception as e:
        analysis = f"AI analizi yapılamadı: {e}"

    plan.ai_analysis = analysis
    plan.status      = "ai_done"
    db.commit()

    return {"analysis": analysis, "packages_checked": {k: len(v) for k, v in all_packages.items()}}


# ─── Çalıştır ─────────────────────────────────────────────────────────────────

@router.post("/plans/{plan_id}/run")
def run_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan bulunamadı")
    if plan.status == "running":
        raise HTTPException(400, "Plan zaten çalışıyor")
    plan.status = "running"
    db.commit()
    _executor.submit(run_system_update_plan, plan_id)
    return {"ok": True, "status": "running"}


# ─── İş listesi ───────────────────────────────────────────────────────────────

@router.get("/plans/{plan_id}/jobs")
def list_jobs(plan_id: int, db: Session = Depends(get_db)):
    jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
    result = []
    for j in jobs:
        srv = db.query(Server).filter_by(id=j.server_id).first()
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
        })
    return result
