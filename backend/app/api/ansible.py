"""
Ansible/AWX API - Toplu komut, playbook çalıştırma
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.server import Server
from app.services.ansible_service import AnsibleService
from app.services.awx_client import AWXClient
import os

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────

class AdHocCommandRequest(BaseModel):
    server_ids: List[int]
    module: str = "shell"  # shell, command, yum, apt, copy, ...
    args: str  # "uptime" veya "name=vim state=present"
    become: bool = False  # sudo ile çalıştır mı


class PlaybookRequest(BaseModel):
    server_ids: List[int]
    playbook_content: str  # YAML içeriği


class AWXJobLaunchRequest(BaseModel):
    template_id: int
    server_ids: Optional[List[int]] = None  # AWX inventory'den seçmek için limit
    extra_vars: Optional[dict] = None
    inventory_id: Optional[int] = None


# ─── Ad-Hoc Komut (Ansible) ───────────────────────────

@router.post("/adhoc")
async def run_adhoc_command(req: AdHocCommandRequest, db: Session = Depends(get_db)):
    """
    Seçili sunucularda Ansible ad-hoc komut çalıştır.
    SADECE IP ADRESI OLAN sunuculara bağlanır (hostname ile değil).
    Önce sunucunun kendi connection_config kullanılır, yoksa Global Credential.
    Örnekler:
    - module=shell, args="uptime"
    - module=yum, args="name=vim state=present", become=true
    """
    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    if not servers:
        raise HTTPException(status_code=404, detail="Hiç sunucu bulunamadı")
    
    # IP adresi olmayan sunucuları filtrele
    servers_with_ip = [s for s in servers if s.ip_address and s.ip_address.strip()]
    servers_without_ip = [s for s in servers if not (s.ip_address and s.ip_address.strip())]
    
    if not servers_with_ip:
        raise HTTPException(
            status_code=400, 
            detail=f"Seçili sunucuların hiçbirinde IP adresi yok. IP adresi ekleyin: {', '.join(s.name for s in servers_without_ip[:5])}"
        )
    
    result = AnsibleService.run_ad_hoc_command(
        servers=servers_with_ip,
        module=req.module,
        args=req.args,
        become=req.become,
        db=db
    )
    
    # Mesajı güncelle: IP olmayan sunucuları bildir
    msg = f"{len(servers_with_ip)} sunucuda '{req.module}' çalıştırıldı"
    if servers_without_ip:
        msg += f". ATLANMIŞ ({len(servers_without_ip)}): {', '.join(s.name for s in servers_without_ip[:5])}"
        if len(servers_without_ip) > 5:
            msg += f" ve {len(servers_without_ip)-5} diğer"
    
    return {
        "success": result["success"],
        "message": msg,
        "results": result.get("results", {}),
        "failed": result.get("failed", []),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "skipped": [s.name for s in servers_without_ip]
    }


@router.post("/ping")
async def ansible_ping_servers(server_ids: List[int], db: Session = Depends(get_db)):
    """Ansible ping modülü ile SSH check (Global Credential kullanılır)"""
    servers = db.query(Server).filter(Server.id.in_(server_ids)).all()
    if not servers:
        raise HTTPException(status_code=404, detail="Hiç sunucu bulunamadı")
    
    reachable = AnsibleService.ping_servers(servers, db)
    
    return {
        "success": True,
        "total": len(servers),
        "reachable": sum(1 for v in reachable.values() if v),
        "results": reachable
    }


@router.post("/playbook")
async def run_playbook(req: PlaybookRequest, db: Session = Depends(get_db)):
    """
    Seçili sunucularda Ansible playbook (YAML) çalıştır.
    YAML içeriği geçici bir dosyaya yazılır ve ansible-playbook komutu çalıştırılır.
    """
    servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
    if not servers:
        raise HTTPException(status_code=404, detail="Hiç sunucu bulunamadı")
    
    # IP adresi olmayan sunucuları filtrele
    servers_with_ip = [s for s in servers if s.ip_address and s.ip_address.strip()]
    servers_without_ip = [s for s in servers if not (s.ip_address and s.ip_address.strip())]
    
    if not servers_with_ip:
        raise HTTPException(
            status_code=400, 
            detail=f"Seçili sunucuların hiçbirinde IP adresi yok. IP adresi ekleyin: {', '.join(s.name for s in servers_without_ip[:5])}"
        )
    
    result = AnsibleService.run_playbook(
        servers=servers_with_ip,
        playbook_content=req.playbook_content,
        db=db
    )
    
    # Mesajı güncelle: IP olmayan sunucuları bildir
    msg = f"Playbook {len(servers_with_ip)} sunucuda çalıştırıldı"
    if servers_without_ip:
        msg += f". ATLANMIŞ ({len(servers_without_ip)}): {', '.join(s.name for s in servers_without_ip[:5])}"
        if len(servers_without_ip) > 5:
            msg += f" ve {len(servers_without_ip)-5} diğer"
    
    return {
        "success": result["success"],
        "message": msg,
        "results": result.get("results", {}),
        "failed": result.get("failed", []),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "skipped": [s.name for s in servers_without_ip]
    }


# ─── AWX Job Template ──────────────────────────────────

def _get_awx_client() -> Optional[AWXClient]:
    """AWX client oluştur (env'den config)"""
    awx_url = os.getenv("AWX_URL")
    awx_user = os.getenv("AWX_USERNAME")
    awx_pass = os.getenv("AWX_PASSWORD")
    
    if not (awx_url and awx_user and awx_pass):
        return None
    
    return AWXClient(
        base_url=awx_url,
        username=awx_user,
        password=awx_pass,
        verify_ssl=os.getenv("AWX_VERIFY_SSL", "true").lower() == "true"
    )


@router.get("/awx/templates")
async def list_awx_job_templates():
    """AWX'teki job template listesi"""
    client = _get_awx_client()
    if not client:
        raise HTTPException(status_code=503, detail="AWX yapılandırılmamış (AWX_URL, AWX_USERNAME, AWX_PASSWORD)")
    
    templates = client.list_job_templates()
    return {
        "success": True,
        "templates": [
            {"id": t["id"], "name": t["name"], "description": t.get("description", "")}
            for t in templates
        ]
    }


@router.post("/awx/launch")
async def launch_awx_job(req: AWXJobLaunchRequest, db: Session = Depends(get_db)):
    """
    AWX job template çalıştır.
    server_ids belirtilirse: limit parametresi ile hostları sınırla.
    """
    client = _get_awx_client()
    if not client:
        raise HTTPException(status_code=503, detail="AWX yapılandırılmamış")
    
    limit = None
    if req.server_ids:
        servers = db.query(Server).filter(Server.id.in_(req.server_ids)).all()
        limit = ",".join(s.name for s in servers)
    
    result = client.launch_job_template(
        template_id=req.template_id,
        inventory_id=req.inventory_id,
        extra_vars=req.extra_vars,
        limit=limit
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "AWX job başlatılamadı"))
    
    return {
        "success": True,
        "job_id": result["job_id"],
        "status": result["status"],
        "message": f"AWX job #{result['job_id']} başlatıldı"
    }


@router.get("/awx/job/{job_id}")
async def get_awx_job_status(job_id: int):
    """AWX job durumu sorgula"""
    client = _get_awx_client()
    if not client:
        raise HTTPException(status_code=503, detail="AWX yapılandırılmamış")
    
    status = client.get_job_status(job_id)
    return {
        "success": True,
        "job": status
    }


@router.get("/awx/job/{job_id}/stdout")
async def get_awx_job_output(job_id: int):
    """AWX job çıktısı (stdout)"""
    client = _get_awx_client()
    if not client:
        raise HTTPException(status_code=503, detail="AWX yapılandırılmamış")
    
    stdout = client.get_job_stdout(job_id)
    return {
        "success": True,
        "job_id": job_id,
        "stdout": stdout
    }


@router.post("/awx/job/{job_id}/cancel")
async def cancel_awx_job(job_id: int):
    """Çalışan AWX job'ı iptal et"""
    client = _get_awx_client()
    if not client:
        raise HTTPException(status_code=503, detail="AWX yapılandırılmamış")
    
    result = client.cancel_job(job_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Job iptal edilemedi"))
    
    return {
        "success": True,
        "message": f"Job #{job_id} iptal edildi"
    }
