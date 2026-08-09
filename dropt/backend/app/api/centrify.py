from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.database import get_session
from app.models.centrify import CentrifyCredential
from app.models.user import User
from app.services import centrify_store as store

router = APIRouter(prefix="/settings/centrify", tags=["centrify"])


class CentrifyCredentialIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=255)
    password: Optional[str] = Field(default=None, max_length=512)
    label: str = Field(default="", max_length=128)
    enabled: bool = True


@router.get("")
def list_centrify(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {"credentials": [store.credential_public(r) for r in store.list_credentials(session)]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_centrify(
    body: CentrifyCredentialIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    domain = body.domain.strip().lower()
    username = body.username.strip()
    if not domain or not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "username ve domain zorunlu")
    if store.find_row_by_domain(session, domain):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu domain zaten kayıtlı: {domain}")
    if not (body.password or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password zorunlu")
    row = CentrifyCredential(
        label=(body.label or domain).strip(),
        username=username,
        domain=domain,
        password_enc=store.encrypt_password(body.password.strip()),
        enabled=body.enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.credential_public(row)


@router.put("/{cred_id}")
def update_centrify(
    cred_id: int,
    body: CentrifyCredentialIn,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = session.get(CentrifyCredential, cred_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kayıt yok")
    domain = body.domain.strip().lower()
    other = store.find_row_by_domain(session, domain)
    if other and other.id != row.id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Bu domain zaten kayıtlı: {domain}")
    row.label = (body.label or domain).strip()
    row.username = body.username.strip()
    row.domain = domain
    row.enabled = body.enabled
    if body.password is not None and body.password.strip():
        row.password_enc = store.encrypt_password(body.password.strip())
    session.add(row)
    session.commit()
    session.refresh(row)
    return store.credential_public(row)


@router.delete("/{cred_id}")
def delete_centrify(
    cred_id: int,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    row = session.get(CentrifyCredential, cred_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kayıt yok")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
