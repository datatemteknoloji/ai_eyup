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
from app.models.module import Module, UserModule, DEFAULT_MODULES, REMOVED_MODULE_IDS

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
    _cleanup_removed_modules(db)


def _cleanup_removed_modules(db: Session):
    """Kaldırılan modülleri (ör. 'aiops') veritabanından temizle.

    Etkilenen kullanıcılara, kapsadığı içeriği zaten sağlayan yerine geçen
    modülü ('linux') ata, sonra Module satırını sil — UserModule kayıtları
    FK CASCADE ile otomatik silinir.
    """
    if not REMOVED_MODULE_IDS:
        return
    existing_removed = db.query(Module).filter(Module.id.in_(REMOVED_MODULE_IDS)).all()
    if not existing_removed:
        return
    affected_user_ids = {
        r.user_id for r in db.query(UserModule).filter(UserModule.module_id.in_(REMOVED_MODULE_IDS)).all()
    }
    for uid in affected_user_ids:
        has_linux = db.query(UserModule).filter(
            UserModule.user_id == uid, UserModule.module_id == "linux"
        ).first()
        if not has_linux:
            db.add(UserModule(user_id=uid, module_id="linux"))
    for mod in existing_removed:
        db.delete(mod)
    db.commit()
    if affected_user_ids:
        logger.info("Kaldırılan modüller temizlendi (%s); %s kullanıcıya 'linux' atandı",
                     REMOVED_MODULE_IDS, len(affected_user_ids))


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

    previous = _get_user_modules(user_id, db)

    # Mevcut atamaları sil
    db.query(UserModule).filter(UserModule.user_id == user_id).delete()

    # Yeni atamaları ekle
    for mid in body.module_ids:
        db.add(UserModule(user_id=user_id, module_id=mid, granted_by=current_user.id))

    db.commit()
    logger.info("Modules updated for user %s by admin %s: %s", user.username, current_user.username, body.module_ids)

    from app.services.audit import record_audit
    record_audit(
        db,
        category="auth",
        action="auth.update_user_modules",
        status="success",
        actor=current_user,
        target_type="user",
        target_id=user_id,
        summary=f"{current_user.username}, {user.username} kullanıcısının modüllerini güncelledi: {', '.join(body.module_ids) or '—'}",
        detail={"before": previous, "after": body.module_ids},
    )

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
    _cleanup_removed_modules(db)
    return {"created": created, "updated": updated, "total": len(DEFAULT_MODULES)}
