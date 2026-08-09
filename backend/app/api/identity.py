"""Kimlik doğrulama / AD ayarları + sync."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import client_ip, require_role
from app.core.database import get_db
from app.models.user import User
from app.services import ad_auth, ad_sync
from app.services.audit import record_audit
from app.services.identity_store import (
    apply_identity_update,
    get_or_create_identity,
    identity_public,
)
from fastapi import Request

router = APIRouter()


class IdentityUpdate(BaseModel):
    ad_enabled: Optional[bool] = None
    ad_host: Optional[str] = None
    ad_port: Optional[int] = None
    ad_use_ssl: Optional[bool] = None
    ad_tls_verify: Optional[bool] = None
    ad_ca_cert_pem: Optional[str] = None
    ad_clear_ca: Optional[bool] = None
    ad_domain: Optional[str] = None
    ad_base_dn: Optional[str] = None
    ad_bind_dn: Optional[str] = None
    ad_bind_password: Optional[str] = None
    ad_user_filter: Optional[str] = None
    ad_admin_group: Optional[str] = None
    ad_operator_group: Optional[str] = None
    ad_viewer_group: Optional[str] = None
    ad_jit_enabled: Optional[bool] = None
    sso_enabled: Optional[bool] = None
    sso_mode: Optional[str] = None
    sso_issuer: Optional[str] = None
    sso_client_id: Optional[str] = None
    sso_client_secret: Optional[str] = None
    sso_redirect_uri: Optional[str] = None
    sso_scopes: Optional[str] = None
    sso_admin_group: Optional[str] = None
    sso_operator_group: Optional[str] = None
    sso_viewer_group: Optional[str] = None
    sso_frontend_redirect: Optional[str] = None


class AdTestRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


@router.get("")
def get_identity(db: Session = Depends(get_db), _admin: User = Depends(require_role("admin"))):
    cfg = get_or_create_identity(db)
    return identity_public(cfg)


@router.put("")
def put_identity(
    body: IdentityUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    cfg = get_or_create_identity(db)
    apply_identity_update(db, cfg, body.model_dump(exclude_unset=True))
    record_audit(
        db, category="auth", action="identity.update", actor=admin,
        summary="Kimlik ayarları güncellendi", ip_address=client_ip(request),
    )
    return identity_public(cfg)


@router.post("/test-ad")
def test_ad(
    body: AdTestRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
):
    cfg = get_or_create_identity(db)
    if body.username and body.password:
        r = ad_auth.authenticate_ad(cfg, body.username, body.password)
    else:
        r = ad_auth.test_ad_bind(cfg)
    return {
        "ok": r.ok,
        "message": r.message,
        "role": r.role,
        "groups": r.groups,
        "resolved_host": r.resolved_host,
        "ldap_url": r.ldap_url,
    }


@router.post("/sync-ad")
def sync_ad(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    cfg = get_or_create_identity(db)
    try:
        result = ad_sync.sync_ad_users(db, cfg)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit(
        db, category="auth", action="identity.sync_ad", actor=admin,
        summary=(
            f"AD sync: scanned={result.get('scanned')} created={result.get('created')} "
            f"updated={result.get('updated')}"
        ),
        ip_address=client_ip(request),
    )
    return result
