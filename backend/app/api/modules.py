"""
Modül yönetimi API'si.
GET  /modules/           → tüm modülleri listele
GET  /modules/my         → mevcut kullanıcının modül ID listesi
GET  /modules/users      → tüm kullanıcıların modül atamaları (admin)
GET  /modules/users/{id} → belirli kullanıcının modülleri (admin)
PUT  /modules/users/{id} → kullanıcının modüllerini toplu güncelle (admin)
POST /modules/seed       → varsayılan modülleri oluştur/güncelle (admin)
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user, require_role
from app.models.user import User
from app.models.module import Module, UserModule, DEFAULT_MODULES

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Schemas ───────────────────────────────────────────────────────────────────

class ModuleOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True

    class Config:
        from_attributes = True


class UserModuleAssignment(BaseModel):
    module_ids: List[str]


class UserModuleSummary(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    modules: List[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_admin(user: User) -> bool:
    return user.role in ("admin", "superadmin")


def _get_user_modules(user_id: int, db: Session) -> List[str]:
    rows = db.query(UserModule).filter(UserModule.user_id == user_id).all()
    return [r.module_id for r in rows]


def _ensure_modules_seeded(db: Session):
    """Seed DEFAULT_MODULES if table is empty or new entries added."""
    for m in DEFAULT_MODULES:
        existing = db.query(Module).filter(Module.id == m["id"]).first()
        if not existing:
            db.add(Module(**m))
    db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ModuleOut])
def list_modules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Sistemdeki tüm aktif modülleri listele."""
    _ensure_modules_seeded(db)
    return db.query(Module).filter(Module.is_active == True).order_by(Module.sort_order).all()


@router.get("/my")
def my_modules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mevcut kullanıcının erişebileceği modül ID'lerini döndür."""
    _ensure_modules_seeded(db)
    # Admin tüm modüllere erişir
    if _is_admin(current_user):
        all_ids = [m["id"] for m in DEFAULT_MODULES]
        return {"is_admin": True, "modules": all_ids}

    modules = _get_user_modules(current_user.id, db)
    return {"is_admin": False, "modules": modules}


@router.get("/users", dependencies=[Depends(require_role("admin"))])
def list_user_modules(db: Session = Depends(get_db)) -> List[UserModuleSummary]:
    """Tüm kullanıcıların modül atamalarını listele (admin)."""
    _ensure_modules_seeded(db)
    users = db.query(User).filter(User.is_active == True).order_by(User.username).all()
    result = []
    for u in users:
        if _is_admin(u):
            # Admin tüm modüllere erişir
            mods = [m["id"] for m in DEFAULT_MODULES]
        else:
            mods = _get_user_modules(u.id, db)
        result.append(UserModuleSummary(
            user_id=u.id,
            username=u.username,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            modules=mods,
        ))
    return result


@router.get("/users/{user_id}", dependencies=[Depends(require_role("admin"))])
def get_user_modules(user_id: int, db: Session = Depends(get_db)):
    """Belirli kullanıcının modüllerini getir (admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    if _is_admin(user):
        return {"user_id": user_id, "is_admin": True, "modules": [m["id"] for m in DEFAULT_MODULES]}

    return {"user_id": user_id, "is_admin": False, "modules": _get_user_modules(user_id, db)}


@router.put("/users/{user_id}", dependencies=[Depends(require_role("admin"))])
def set_user_modules(
    user_id: int,
    body: UserModuleAssignment,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kullanıcının modüllerini toplu güncelle — mevcut atamaların tamamı değiştirilir (admin)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    if _is_admin(user):
        raise HTTPException(status_code=400, detail="Admin kullanıcılarının modülleri manuel yönetilemez")

    # Geçerli modül ID'lerini doğrula
    valid_ids = {m["id"] for m in DEFAULT_MODULES}
    invalid = [mid for mid in body.module_ids if mid not in valid_ids]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Geçersiz modül ID'leri: {invalid}")

    # Mevcut atamaları sil
    db.query(UserModule).filter(UserModule.user_id == user_id).delete()

    # Yeni atamaları ekle
    for mid in body.module_ids:
        db.add(UserModule(user_id=user_id, module_id=mid, granted_by=current_user.id))

    db.commit()
    logger.info("Modules updated for user %s by admin %s: %s", user.username, current_user.username, body.module_ids)
    return {"user_id": user_id, "modules": body.module_ids}


@router.post("/seed", dependencies=[Depends(require_role("admin"))])
def seed_modules(db: Session = Depends(get_db)):
    """Varsayılan modülleri oluştur/güncelle (admin)."""
    created, updated = 0, 0
    for m in DEFAULT_MODULES:
        existing = db.query(Module).filter(Module.id == m["id"]).first()
        if existing:
            for k, v in m.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Module(**m))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(DEFAULT_MODULES)}
