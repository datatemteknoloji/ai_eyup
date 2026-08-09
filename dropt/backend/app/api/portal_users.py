from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, func, select

from app.api.deps import require_admin
from app.core.database import get_session
from app.core.security import hash_password
from app.models.job import AuditStatus
from app.models.user import AuthSource, User, UserRole
from app.schemas.portal_user import (
    PortalUserCreate,
    PortalUserListResponse,
    PortalUserPublic,
    PortalUserUpdate,
)
from app.services.ad_sync import sync_ad_users
from app.services.audit import write_audit
from app.services.identity_store import get_or_create_identity
from app.services.user_ids import next_local_id

router = APIRouter(prefix="/portal-users", tags=["portal-users"])


def _public(u: User) -> PortalUserPublic:
    return PortalUserPublic(
        id=u.id,  # type: ignore[arg-type]
        username=u.username,
        role=u.role,
        auth_source=u.auth_source,
        is_active=u.is_active,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
    )


def _count_active_admins(session: Session) -> int:
    return session.exec(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.admin)
        .where(User.is_active == True)  # noqa: E712
    ).one()


@router.get("", response_model=PortalUserListResponse)
def list_portal_users(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> PortalUserListResponse:
    rows = session.exec(select(User).order_by(col(User.username))).all()
    return PortalUserListResponse(items=[_public(u) for u in rows], total=len(rows))


@router.post("/sync-ad")
def sync_ad_portal_users(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    cfg = get_or_create_identity(session)
    try:
        result = sync_ad_users(session, cfg)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    write_audit(
        session,
        action="portal_user.sync_ad",
        status=AuditStatus.success,
        message=f"AD sync: scanned={result['scanned']} created={result['created']} updated={result['updated']}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        after_state=result,
    )
    return result


@router.post("", response_model=PortalUserPublic, status_code=status.HTTP_201_CREATED)
def create_portal_user(
    body: PortalUserCreate,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> PortalUserPublic:
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kullanıcı adı gerekli")
    if body.role == UserRole.none:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local kullanıcı none olamaz")
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Kullanıcı adı zaten var")

    try:
        new_id = next_local_id(session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user = User(
        id=new_id,
        username=username,
        password_hash=hash_password(body.password),
        role=body.role,
        auth_source=AuthSource.local,
        is_active=body.is_active,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    write_audit(
        session,
        action="portal_user.create",
        status=AuditStatus.success,
        message=f"Local kullanıcı oluşturuldu: {username} ({body.role.value})",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        after_state={"username": username, "role": body.role.value, "id": new_id},
    )
    return _public(user)


@router.patch("/{user_id}", response_model=PortalUserPublic)
def update_portal_user(
    user_id: int,
    body: PortalUserUpdate,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> PortalUserPublic:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı")

    before = {"role": user.role.value, "is_active": user.is_active}
    data = body.model_dump(exclude_unset=True)

    if "role" in data and data["role"] is not None:
        new_role = data["role"]
        if user.auth_source == AuthSource.local and new_role == UserRole.none:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local kullanıcı none olamaz")
        if user.role == UserRole.admin and new_role != UserRole.admin and _count_active_admins(session) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Son aktif Admin'in rolü değiştirilemez",
            )
        user.role = new_role
        if new_role == UserRole.none:
            user.is_active = False
        elif not user.is_active and new_role in {UserRole.admin, UserRole.operator}:
            user.is_active = True

    if "is_active" in data and data["is_active"] is not None:
        if user.is_active and not data["is_active"]:
            if user.id == admin.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kendi hesabınızı pasifleştiremezsiniz")
            if user.role == UserRole.admin and _count_active_admins(session) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Son aktif Admin pasifleştirilemez",
                )
        user.is_active = data["is_active"]

    if "password" in data and data["password"]:
        if user.auth_source != AuthSource.local:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Yalnız Local hesapların şifresi buradan değişir",
            )
        user.password_hash = hash_password(data["password"])

    session.add(user)
    session.commit()
    session.refresh(user)
    write_audit(
        session,
        action="portal_user.update",
        status=AuditStatus.success,
        message=f"Portal kullanıcı güncellendi: {user.username}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        before_state=before,
        after_state={"role": user.role.value, "is_active": user.is_active},
    )
    return _public(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portal_user(
    user_id: int,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kendi hesabınızı silemezsiniz")
    if user.role == UserRole.admin and user.is_active and _count_active_admins(session) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Son aktif Admin silinemez")

    username = user.username
    session.delete(user)
    session.commit()
    write_audit(
        session,
        action="portal_user.delete",
        status=AuditStatus.success,
        message=f"Portal kullanıcı silindi: {username}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        before_state={"username": username},
    )
