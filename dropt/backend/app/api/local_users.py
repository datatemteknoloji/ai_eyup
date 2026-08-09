from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.server import TargetServer
from app.models.user import User
from app.modules.local_user import list_local_users
from app.schemas.job import LocalUserPublic

router = APIRouter(prefix="/servers", tags=["local-users"])


@router.get("/{server_id}/local-users", response_model=list[LocalUserPublic])
def get_local_users(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[LocalUserPublic]:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        rows = list_local_users(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sunucudan kullanıcı listesi alınamadı: {exc}",
        ) from exc
    return [LocalUserPublic(**r) for r in rows]
