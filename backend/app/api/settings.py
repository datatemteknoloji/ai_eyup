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
        if request.set_ai_ready:
            server.ai_ready = True
        flag_modified(server, "connection_config")
        applied += 1

    db.commit()
    return {
        "success": True,
        "message": f"'{cred.name}' credential {applied} sunucuya uygulandı",
        "applied_count": applied
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
