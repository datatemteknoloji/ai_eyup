from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.server import TargetServer
from app.models.user import User
from app.modules.hostname import read_hostname_state

router = APIRouter(prefix="/servers", tags=["hostname"])


class HostnameState(BaseModel):
    short_name: str = ""
    domain: str = ""
    fqdn: str = ""
    hosts_preview: str = ""
    warnings: list[str] = Field(default_factory=list)
    ip: str = ""


@router.get("/{server_id}/hostname", response_model=HostnameState)
def get_hostname_state(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HostnameState:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        state = read_hostname_state(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Hostname okunamadı: {exc}",
        ) from exc
    return HostnameState(**state)
