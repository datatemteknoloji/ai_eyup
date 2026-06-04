"""
Kimlik doğrulama API — login, profil ve kullanıcı yönetimi (admin).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import client_ip, get_current_user, require_role
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.services.audit import record_audit

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "operator"


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChangeRequest(BaseModel):
    new_password: str


def _user_dict(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    ip = client_ip(request)
    if not user or not user.is_active or not verify_password(req.password, user.hashed_password):
        record_audit(db, category="auth", action="auth.login", status="failure",
                     actor=req.username, summary=f"Başarısız giriş: {req.username}",
                     ip_address=ip)
        raise HTTPException(status_code=401, detail="Kullanıcı adı veya parola hatalı")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(user.username, extra={"uid": user.id, "role": user.role})
    record_audit(db, category="auth", action="auth.login", status="success",
                 actor=user, summary=f"Giriş yapıldı: {user.username}", ip_address=ip)
    return {"access_token": token, "token_type": "bearer", "user": _user_dict(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_dict(user)


@router.post("/change-password")
def change_own_password(req: PasswordChangeRequest, request: Request,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    if len(req.new_password or "") < 4:
        raise HTTPException(status_code=400, detail="Parola en az 4 karakter olmalı")
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    record_audit(db, category="auth", action="auth.change_password", actor=user,
                 summary="Kendi parolasını değiştirdi", ip_address=client_ip(request))
    return {"success": True}


# ── Kullanıcı yönetimi (admin) ──────────────────────────────────────────────
@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    rows = db.query(User).order_by(User.id.asc()).all()
    return {"users": [_user_dict(u) for u in rows]}


@router.post("/users")
def create_user(req: CreateUserRequest, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    if req.role not in ("admin", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="Geçersiz rol")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten var")
    u = User(
        username=req.username,
        email=req.email,
        full_name=req.full_name,
        role=req.role,
        hashed_password=hash_password(req.password),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    record_audit(db, category="auth", action="auth.create_user", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Kullanıcı oluşturuldu: {u.username} ({u.role})",
                 ip_address=client_ip(request))
    return _user_dict(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, req: UpdateUserRequest, request: Request,
                db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if req.role is not None:
        if req.role not in ("admin", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="Geçersiz rol")
        u.role = req.role
    if req.full_name is not None:
        u.full_name = req.full_name
    if req.email is not None:
        u.email = req.email
    if req.is_active is not None:
        u.is_active = req.is_active
    db.commit()
    record_audit(db, category="auth", action="auth.update_user", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Kullanıcı güncellendi: {u.username}",
                 ip_address=client_ip(request))
    return _user_dict(u)


@router.post("/users/{user_id}/password")
def admin_set_password(user_id: int, req: PasswordChangeRequest, request: Request,
                       db: Session = Depends(get_db),
                       admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    u.hashed_password = hash_password(req.new_password)
    db.commit()
    record_audit(db, category="auth", action="auth.reset_password", actor=admin,
                 target_type="user", target_id=u.id,
                 summary=f"Parola sıfırlandı: {u.username}",
                 ip_address=client_ip(request))
    return {"success": True}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_role("admin"))):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
    if u.id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz")
    if u.role == "admin" and db.query(User).filter(User.role == "admin").count() <= 1:
        raise HTTPException(status_code=400, detail="Son admin hesabı silinemez")
    uname = u.username
    db.delete(u)
    db.commit()
    record_audit(db, category="auth", action="auth.delete_user", actor=admin,
                 target_type="user", target_id=user_id,
                 summary=f"Kullanıcı silindi: {uname}", ip_address=client_ip(request))
    return {"success": True}
