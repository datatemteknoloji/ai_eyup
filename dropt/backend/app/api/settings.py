from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlmodel import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import get_settings
from app.core.database import get_session
from app.models.user import User
from app.schemas.settings import (
    AdminSettings,
    AdminSettingsUpdate,
    MailSettingsPublic,
    PublicSettings,
)
from app.services import assistant_settings as aset
from app.services import backup as backup_svc
from app.services.audit import write_audit
from app.services.bootstrap import (
    automation_password_is_set,
    get_app_name,
    get_automation_username,
    get_smtp_host,
    get_smtp_test_mail,
    set_app_name,
    set_automation_password,
    set_automation_username,
    set_smtp_host,
    set_smtp_test_mail,
)
from app.services.identity_store import get_or_create_identity
from app.services.privilege import get_automation_user_kind, set_automation_user_kind

router = APIRouter(prefix="/settings", tags=["settings"])


def _admin_settings(session: Session) -> AdminSettings:
    return AdminSettings(
        app_name=get_app_name(session),
        version=get_settings().app_version,
        automation_username=get_automation_username(session),
        automation_user_kind=get_automation_user_kind(session),
        automation_password_set=automation_password_is_set(session),
        admin_terminal_user="root",
        smtp_host=get_smtp_host(session),
        smtp_test_mail=get_smtp_test_mail(session),
        assistant_enabled=aset.is_assistant_enabled(session),
        assistant_ollama_mode=aset.get_assistant_ollama_mode(session),
        assistant_gateway_url=aset.get_assistant_gateway_url(session),
        assistant_gateway_api_key_set=aset.gateway_api_key_is_set(session),
        assistant_direct_host=aset.get_assistant_direct_host(session),
        assistant_direct_port=aset.get_assistant_direct_port(session),
        assistant_model=aset.get_assistant_model(session),
    )


@router.get("/public", response_model=PublicSettings)
def public_settings(session: Session = Depends(get_session)) -> PublicSettings:
    cfg = get_or_create_identity(session)
    return PublicSettings(
        app_name=get_app_name(session),
        version=get_settings().app_version,
        sso_enabled=bool(cfg.sso_enabled),
        ad_enabled=bool(cfg.ad_enabled),
        sso_mode=(cfg.sso_mode or "kerberos"),
        assistant_enabled=aset.is_assistant_enabled(session),
    )


@router.get("/mail", response_model=MailSettingsPublic)
def get_mail_settings(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> MailSettingsPublic:
    return MailSettingsPublic(
        smtp_host=get_smtp_host(session),
        smtp_test_mail=get_smtp_test_mail(session),
    )


@router.get("", response_model=AdminSettings)
def get_settings_admin(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AdminSettings:
    return _admin_settings(session)


@router.patch("", response_model=AdminSettings)
def update_settings_admin(
    body: AdminSettingsUpdate,
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AdminSettings:
    try:
        if body.app_name is not None:
            set_app_name(session, body.app_name)
        if body.automation_username is not None:
            set_automation_username(session, body.automation_username)
        if body.automation_user_kind is not None:
            set_automation_user_kind(
                session,
                body.automation_user_kind,
                username=get_automation_username(session),
            )
        if body.automation_password is not None and body.automation_password.strip():
            set_automation_password(session, body.automation_password)
        if body.smtp_host is not None:
            set_smtp_host(session, body.smtp_host)
        if body.smtp_test_mail is not None:
            set_smtp_test_mail(session, body.smtp_test_mail)
        if body.assistant_enabled is not None:
            aset.set_assistant_enabled(session, body.assistant_enabled)
        if body.assistant_ollama_mode is not None:
            aset.set_assistant_ollama_mode(session, body.assistant_ollama_mode)
        if body.assistant_gateway_url is not None:
            aset.set_assistant_gateway_url(session, body.assistant_gateway_url)
        if body.assistant_gateway_api_key is not None:
            aset.set_assistant_gateway_api_key(session, body.assistant_gateway_api_key)
        if body.assistant_direct_host is not None:
            aset.set_assistant_direct_host(session, body.assistant_direct_host)
        if body.assistant_direct_port is not None:
            aset.set_assistant_direct_port(session, body.assistant_direct_port)
        if body.assistant_model is not None:
            aset.set_assistant_model(session, body.assistant_model)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _admin_settings(session)


@router.get("/backup/settings")
def export_settings_backup(
    include_secrets: bool = Query(False, description="Secret key'leri de dahil et"),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    from app.models.job import AuditStatus

    payload = backup_svc.export_settings_payload(session, include_secrets=include_secrets)
    write_audit(
        session,
        action="settings.backup.export",
        status=AuditStatus.success,
        message=f"settings export include_secrets={include_secrets}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        after_state={
            "redacted_keys": payload.get("redacted_keys"),
            "count": len(payload.get("settings") or {}),
        },
    )
    return payload


@router.post("/backup/settings")
def import_settings_backup(
    body: dict,
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    from app.models.job import AuditStatus

    try:
        result = backup_svc.import_settings_payload(session, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    write_audit(
        session,
        action="settings.backup.import",
        status=AuditStatus.success,
        message="settings import",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        after_state=result,
    )
    return {"ok": True, **result}


@router.get("/backup/database")
def export_database_backup(
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Response:
    from app.models.job import AuditStatus

    try:
        data = backup_svc.dump_database_sql_gz()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    name = backup_svc.dump_filename()
    write_audit(
        session,
        action="settings.backup.db_export",
        status=AuditStatus.success,
        message=f"database dump {name}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        after_state={"bytes": len(data)},
    )
    return Response(
        content=data,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/backup/database")
async def import_database_backup(
    confirm: bool = Query(False, description="true olmalı — yıkıcı işlem"),
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    from app.models.job import AuditStatus

    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm=true gerekli (veritabanı üzerine yazılır)",
        )
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Boş dosya")
    if len(blob) > 512 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dosya çok büyük (max 512MB)")
    try:
        out = backup_svc.restore_database_sql_gz(blob)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    write_audit(
        session,
        action="settings.backup.db_import",
        status=AuditStatus.success,
        message=f"database restore filename={file.filename}",
        user_id=admin.id,
        username=admin.username,
        role=admin.role,
        after_state={"bytes": len(blob)},
    )
    return {"ok": True, "detail": "Restore tamamlandı — API oturumlarını yenileyin", "log_tail": out[:500]}
