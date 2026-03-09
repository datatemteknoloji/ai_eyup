"""
Settings API - Global Credentials CRUD + Apply to Servers
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.models.credential import GlobalCredential
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────

class CredentialCreate(BaseModel):
    name: str
    username: str
    password: str = ""
    private_key: str = ""
    sudo_password: str = ""
    port: int = 22

class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None
    sudo_password: Optional[str] = None
    port: Optional[int] = None

class CredentialResponse(BaseModel):
    id: int
    name: str
    username: str
    port: int
    has_password: bool
    has_private_key: bool
    is_default: bool

class ApplyCredentialRequest(BaseModel):
    server_ids: Optional[List[int]] = None
    set_ai_ready: bool = True


def _cred_to_response(c: GlobalCredential) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "username": c.username,
        "port": c.port,
        "has_password": bool(c.password),
        "has_private_key": bool(c.private_key),
        "is_default": c.is_default
    }


# ─── CRUD ─────────────────────────────────────────────

@router.get("/credentials/", response_model=List[CredentialResponse])
async def list_credentials(db: Session = Depends(get_db)):
    """Tüm global credential'ları listele"""
    creds = db.query(GlobalCredential).order_by(GlobalCredential.is_default.desc(), GlobalCredential.name).all()
    return [_cred_to_response(c) for c in creds]


@router.post("/credentials/", response_model=CredentialResponse, status_code=201)
async def create_credential(data: CredentialCreate, db: Session = Depends(get_db)):
    """Yeni global credential oluştur"""
    existing = db.query(GlobalCredential).filter(GlobalCredential.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{data.name}' adında credential zaten var")

    is_first = db.query(GlobalCredential).count() == 0
    cred = GlobalCredential(
        name=data.name,
        username=data.username,
        password=data.password or None,
        private_key=data.private_key or None,
        sudo_password=data.sudo_password or None,
        port=data.port,
        is_default=is_first
    )
    db.add(cred)
    db.commit()
    db.refresh(cred)
    return _cred_to_response(cred)


@router.get("/credentials/{credential_id}", response_model=CredentialResponse)
async def get_credential(credential_id: int, db: Session = Depends(get_db)):
    """Tek credential getir"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    return _cred_to_response(cred)


@router.put("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(credential_id: int, data: CredentialUpdate, db: Session = Depends(get_db)):
    """Global credential güncelle"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")

    if data.name is not None:
        cred.name = data.name
    if data.username is not None:
        cred.username = data.username
    if data.password is not None and data.password != "":
        cred.password = data.password
    if data.private_key is not None:
        cred.private_key = data.private_key
    if data.sudo_password is not None:
        cred.sudo_password = data.sudo_password
    if data.port is not None:
        cred.port = data.port

    db.commit()
    db.refresh(cred)
    return _cred_to_response(cred)


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: int, db: Session = Depends(get_db)):
    """Global credential sil"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    db.delete(cred)
    db.commit()


@router.post("/credentials/{credential_id}/set-default")
async def set_default_credential(credential_id: int, db: Session = Depends(get_db)):
    """Bir credential'ı varsayılan olarak ayarla"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")
    db.query(GlobalCredential).update({GlobalCredential.is_default: False})
    cred.is_default = True
    db.commit()
    return {"success": True, "message": f"'{cred.name}' varsayılan credential olarak ayarlandı"}


@router.post("/credentials/{credential_id}/apply")
async def apply_credential_to_servers(credential_id: int, request: ApplyCredentialRequest, db: Session = Depends(get_db)):
    """Global credential'ı sunuculara uygula"""
    cred = db.query(GlobalCredential).filter(GlobalCredential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential bulunamadı")

    if request.server_ids:
        servers = db.query(Server).filter(Server.id.in_(request.server_ids)).all()
    else:
        servers = db.query(Server).all()

    if not servers:
        raise HTTPException(status_code=404, detail="Hiç sunucu bulunamadı")

    applied = 0
    failed = []
    for server in servers:
        if not server.connection_config:
            server.connection_config = {}
        server.connection_config["username"] = cred.username
        if cred.password:
            server.connection_config["password"] = cred.password
        if cred.private_key:
            server.connection_config["private_key"] = cred.private_key
        if cred.sudo_password:
            server.connection_config["sudo_password"] = cred.sudo_password
        server.connection_config["port"] = cred.port
        flag_modified(server, "connection_config")
        
        # ai_ready: SSH test et, başarılıysa true (SADECE IP adresi olanlarda)
        if request.set_ai_ready:
            # IP adresi yoksa ai_ready = False
            if not server.ip_address or not server.ip_address.strip():
                logger.debug(f"SSH test atlandı (IP yok): {server.name}")
                server.ai_ready = False
                failed.append(f"{server.name} (IP yok)")
            else:
                try:
                    from app.services.ssh_manager import SSHManager
                    ssh = SSHManager(
                        host=server.ip_address.strip(),
                        username=cred.username,
                        password=cred.password if cred.password else None,
                        private_key=cred.private_key if cred.private_key else None,
                        port=cred.port
                    )
                    ssh.connect()
                    ssh.close()
                    server.ai_ready = True
                except Exception as e:
                    logger.debug(f"SSH test failed for {server.name}: {e}")
                    server.ai_ready = False
                    failed.append(server.name)
        applied += 1

    db.commit()
    msg = f"'{cred.name}' credential {applied} sunucuya uygulandı"
    if failed:
        msg += f". SSH bağlantı başarısız ({len(failed)}): {', '.join(failed[:5])}"
        if len(failed) > 5:
            msg += f" ve {len(failed)-5} diğer"
    return {
        "success": True,
        "message": msg,
        "applied_count": applied,
        "ai_ready_count": applied - len(failed),
        "failed_ssh": failed[:20]
    }


@router.post("/credentials/test-all-ssh")
async def test_all_servers_ssh(db: Session = Depends(get_db)):
    """Tüm sunucularda SSH test et, ai_ready durumunu güncelle ve SSH key dağıt"""
    servers = db.query(Server).all()
    if not servers:
        raise HTTPException(status_code=404, detail="Hiç sunucu bulunamadı")
    
    successful = []
    failed = []
    skipped = []
    key_deployed = []
    
    for server in servers:
        # IP yoksa skip
        if not server.ip_address or not server.ip_address.strip():
            logger.debug(f"SSH test atlandı (IP yok): {server.name}")
            server.ai_ready = False
            skipped.append(server.name)
            continue
        
        # connection_config yoksa skip
        if not server.connection_config or not server.connection_config.get("username"):
            logger.debug(f"SSH test atlandı (credential yok): {server.name}")
            server.ai_ready = False
            skipped.append(server.name)
            continue
        
        # SSH test
        try:
            from app.services.ssh_manager import SSHManager
            ssh = SSHManager(
                host=server.ip_address.strip(),
                username=server.connection_config.get("username"),
                password=server.connection_config.get("password"),
                private_key=server.connection_config.get("private_key"),
                port=server.connection_config.get("port", 22)
            )
            ssh.connect()
            
            # SSH bağlantı başarılı - key deployment dene
            try:
                # Eğer private key varsa, public key'i oluştur ve sunucuya dağıt
                if server.connection_config.get("private_key"):
                    from app.services.ssh_key_deployer import SSHKeyDeployer
                    deployer = SSHKeyDeployer()
                    deploy_result = deployer.deploy_public_key(
                        ssh_manager=ssh,
                        private_key=server.connection_config.get("private_key")
                    )
                    if deploy_result.get("success"):
                        key_deployed.append(server.name)
                        logger.info(f"SSH public key deployed to {server.name}")
            except Exception as key_error:
                logger.warning(f"SSH key deployment failed for {server.name}: {key_error}")
            
            ssh.close()
            server.ai_ready = True
            successful.append(server.name)
            logger.info(f"✅ SSH test başarılı: {server.name}")
        except Exception as e:
            logger.debug(f"SSH test failed for {server.name}: {e}")
            server.ai_ready = False
            failed.append(server.name)
    
    db.commit()
    
    msg = f"SSH Test tamamlandı. Başarılı: {len(successful)}, Başarısız: {len(failed)}, Atlandı: {len(skipped)}"
    if key_deployed:
        msg += f"\n\n🔑 SSH Key dağıtıldı ({len(key_deployed)}): {', '.join(key_deployed[:10])}"
        if len(key_deployed) > 10:
            msg += f" ve {len(key_deployed)-10} diğer"
    if failed:
        msg += f"\n\nBaşarısız: {', '.join(failed[:10])}"
        if len(failed) > 10:
            msg += f" ve {len(failed)-10} diğer"
    if skipped:
        msg += f"\n\nAtlandı (IP/credential yok): {', '.join(skipped[:10])}"
        if len(skipped) > 10:
            msg += f" ve {len(skipped)-10} diğer"
    
    return {
        "success": True,
        "message": msg,
        "successful": len(successful),
        "failed": len(failed),
        "skipped": len(skipped),
        "key_deployed": len(key_deployed),
        "successful_servers": successful[:20],
        "failed_servers": failed[:20],
        "skipped_servers": skipped[:20],
        "key_deployed_servers": key_deployed[:20]
    }


# ─── General Settings ────────────────────────────────

@router.get("/")
async def get_settings(db: Session = Depends(get_db)):
    """Genel ayarları getir"""
    from app.core.config import settings
    default_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    return {
        "ollama_url": settings.OLLAMA_URL,
        "ollama_model": settings.OLLAMA_DEFAULT_MODEL,
        "prometheus_url": settings.PROMETHEUS_URL,
        "default_credential": _cred_to_response(default_cred) if default_cred else None
    }
