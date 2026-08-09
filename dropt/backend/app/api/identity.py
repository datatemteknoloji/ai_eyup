from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session

from app.api.deps import require_admin
from app.core.database import get_session
from app.models.job import AuditStatus
from app.models.user import User
from app.schemas.identity import AdTestRequest, AdTestResponse, IdentityPublic, IdentityUpdate
from app.services.ad_auth import authenticate_ad, test_ad_bind
from app.services.audit import write_audit
from app.services.identity_store import (
    apply_identity_update,
    get_or_create_identity,
    identity_public,
)
from app.services.kerberos_sso import save_keytab_bytes, test_kerberos_config

router = APIRouter(prefix="/identity", tags=["identity"])


@router.get("", response_model=IdentityPublic)
def get_identity(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> IdentityPublic:
    return identity_public(get_or_create_identity(session))


@router.put("", response_model=IdentityPublic)
def put_identity(
    body: IdentityUpdate,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> IdentityPublic:
    cfg = apply_identity_update(session, body)
    write_audit(
        session,
        action="identity.update",
        status=AuditStatus.success,
        message="Kimlik ayarları güncellendi",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
        after_state={
            "ad_enabled": cfg.ad_enabled,
            "sso_enabled": cfg.sso_enabled,
            "sso_mode": cfg.sso_mode,
            "ad_domain": cfg.ad_domain,
        },
    )
    return identity_public(cfg)


@router.post("/test-ad", response_model=AdTestResponse)
def test_ad(
    body: AdTestRequest,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AdTestResponse:
    cfg = get_or_create_identity(session)
    if body.username and body.password:
        result = authenticate_ad(cfg, body.username, body.password)
        return AdTestResponse(
            ok=result.ok,
            message=result.message,
            role=result.role.value if result.role else None,
            groups=result.groups[:20],
            resolved_host=result.resolved_host or None,
            ldap_url=result.ldap_url or None,
        )
    result = test_ad_bind(cfg)
    if not result.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)
    return AdTestResponse(
        ok=True,
        message=result.message,
        groups=[],
        resolved_host=result.resolved_host or None,
        ldap_url=result.ldap_url or None,
    )


@router.post("/kerberos/keytab", response_model=IdentityPublic)
async def upload_kerberos_keytab(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
    file: UploadFile = File(...),
) -> IdentityPublic:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Boş keytab")
    if len(data) > 2_000_000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Keytab çok büyük")
    path = save_keytab_bytes(data, file.filename or "portal.keytab")
    cfg = get_or_create_identity(session)
    cfg.kerberos_keytab_path = path
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    write_audit(
        session,
        action="identity.kerberos.keytab",
        status=AuditStatus.success,
        message=f"Keytab yüklendi: {path}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role.value,
    )
    return identity_public(cfg)


@router.post("/kerberos/test")
def test_kerberos(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    cfg = get_or_create_identity(session)
    ok, message = test_kerberos_config(cfg)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    return {"ok": True, "message": message}
