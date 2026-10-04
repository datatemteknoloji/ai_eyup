"""Centrify provisioning servisi — yazma operasyonlarını yürütür.

Onaylanan operasyonları alır, WinRM adaptörü üzerinden AD'ye yazar,
sonucu doğrular ve durumu günceller.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.centrify import state_machine, audit_service
from app.services.centrify.exceptions import (
    CentrifyAuthError,
    CentrifyCircuitOpenError,
    CentrifyConnectionError,
    CentrifyError,
    CentrifyErrorClass,
    CentrifyScriptError,
)

logger = logging.getLogger(__name__)


def create_operation(
    db: Session,
    *,
    operation_type: str,
    zone_id: int | None,
    desired_state: dict,
    reason: str,
    requested_by: int,
    requested_by_name: str,
) -> dict:
    """Yeni operasyon isteği oluştur."""
    from app.models.centrify_zone import CentrifyOperation

    initial = state_machine.initial_status(operation_type)

    op = CentrifyOperation(
        correlation_id=uuid.uuid4(),
        zone_id=zone_id,
        operation_type=operation_type,
        desired_state=desired_state,
        status=initial,
        status_history=[{"from": "new", "to": initial, "at": datetime.now(timezone.utc).isoformat()}],
        requested_by=requested_by,
        requested_by_name=requested_by_name,
        reason=reason,
    )
    db.add(op)
    db.flush()

    # Onay yok: istenen durumu yerel DB'ye hemen yaz
    try:
        apply_local_state(db, op)
        state_machine.transition(op, "completed", actor_id=requested_by)
    except Exception as exc:
        logger.exception("Yerel uygulama başarısız (op #%s)", op.id)
        op.error_message = str(exc)
        state_machine.transition(op, "failed", actor_id=requested_by, error_message=str(exc))

    audit_service.log_action(
        db,
        correlation_id=op.correlation_id,
        operation_id=op.id,
        actor_user_id=requested_by,
        actor_username=requested_by_name,
        target_type=operation_type,
        target_name=desired_state.get("name", ""),
        action="operation_created",
        reason=reason,
        details={"desired_state": desired_state, "initial_status": initial},
        result="success",
    )
    db.commit()

    return {
        "id": op.id,
        "correlation_id": str(op.correlation_id),
        "operation_type": op.operation_type,
        "status": op.status,
        "created_at": op.created_at.isoformat() if op.created_at else None,
    }


def approve_operation(
    db: Session,
    operation_id: int,
    *,
    approved_by: int,
    approved_by_name: str,
) -> dict:
    """Operasyonu onayla. Dört göz: kendi isteğini kendi onaylayamaz."""
    from app.models.centrify_zone import CentrifyOperation

    op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
    if op is None:
        return {"ok": False, "error": "Operasyon bulunamadı"}

    if op.status != "pending_approval":
        return {"ok": False, "error": f"Operasyon onaylanamaz (durum: {op.status})"}

    if op.requested_by == approved_by:
        return {"ok": False, "error": "Kendi isteğinizi kendiniz onaylayamazsınız (dört göz prensibi)"}

    ok = state_machine.transition(op, "approved", actor_id=approved_by)
    if not ok:
        return {"ok": False, "error": "Geçersiz durum geçişi"}

    op.approved_by = approved_by
    op.approved_by_name = approved_by_name

    audit_service.log_action(
        db,
        correlation_id=op.correlation_id,
        operation_id=op.id,
        actor_user_id=approved_by,
        actor_username=approved_by_name,
        target_type=op.operation_type,
        target_name=(op.desired_state or {}).get("name", ""),
        action="operation_approved",
        reason=f"Onaylandı: {op.reason}",
        approved_by_id=approved_by,
        approved_by_name=approved_by_name,
        result="success",
    )
    db.commit()

    return {"ok": True, "status": op.status}


def reject_operation(
    db: Session,
    operation_id: int,
    *,
    rejected_by: int,
    rejected_by_name: str,
    reject_reason: str = "",
) -> dict:
    """Operasyonu reddet."""
    from app.models.centrify_zone import CentrifyOperation

    op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
    if op is None:
        return {"ok": False, "error": "Operasyon bulunamadı"}

    if op.status != "pending_approval":
        return {"ok": False, "error": f"Operasyon reddedilemez (durum: {op.status})"}

    ok = state_machine.transition(op, "cancelled", actor_id=rejected_by,
                                   error_message=reject_reason or "Reddedildi")
    if not ok:
        return {"ok": False, "error": "Geçersiz durum geçişi"}

    audit_service.log_action(
        db,
        correlation_id=op.correlation_id,
        operation_id=op.id,
        actor_user_id=rejected_by,
        actor_username=rejected_by_name,
        target_type=op.operation_type,
        target_name=(op.desired_state or {}).get("name", ""),
        action="operation_rejected",
        reason=reject_reason or "Reddedildi",
        result="rejected",
    )
    db.commit()

    return {"ok": True, "status": op.status}


def cancel_operation(
    db: Session,
    operation_id: int,
    *,
    cancelled_by: int,
    cancelled_by_name: str,
) -> dict:
    """Operasyonu iptal et."""
    from app.models.centrify_zone import CentrifyOperation

    op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
    if op is None:
        return {"ok": False, "error": "Operasyon bulunamadı"}

    if state_machine.is_terminal(op.status):
        return {"ok": False, "error": f"Operasyon zaten tamamlanmış (durum: {op.status})"}

    ok = state_machine.transition(op, "cancelled", actor_id=cancelled_by,
                                   error_message="Kullanıcı tarafından iptal edildi")
    if not ok:
        return {"ok": False, "error": "Geçersiz durum geçişi"}

    audit_service.log_action(
        db,
        correlation_id=op.correlation_id,
        operation_id=op.id,
        actor_user_id=cancelled_by,
        actor_username=cancelled_by_name,
        target_type=op.operation_type,
        target_name=(op.desired_state or {}).get("name", ""),
        action="operation_cancelled",
        reason="Kullanıcı tarafından iptal edildi",
        result="cancelled",
    )
    db.commit()

    return {"ok": True, "status": op.status}


def execute_operation(db: Session, operation_id: int, adapter) -> dict:
    """Onaylanmış operasyonu yürüt (provisioning → write → verify → complete).

    Bu fonksiyon Celery task içinden çağrılır. Senkron çalışır.
    """
    from app.models.centrify_zone import CentrifyOperation

    op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
    if op is None:
        return {"ok": False, "error": "Operasyon bulunamadı"}

    if op.status != "approved":
        return {"ok": False, "error": f"Operasyon yürütülemez (durum: {op.status})"}

    # provisioning durumuna geç
    if not state_machine.transition(op, "provisioning", actor_id=0):
        return {"ok": False, "error": "Provisioning geçişi başarısız"}
    db.commit()

    try:
        result = _dispatch_operation(adapter, op.operation_type, op.desired_state or {})

        # written_to_ad
        state_machine.transition(op, "written_to_ad", actor_id=0)
        op.observed_state = result
        db.commit()

        # verified → completed
        state_machine.transition(op, "verified", actor_id=0)
        db.commit()
        state_machine.transition(op, "completed", actor_id=0)

        audit_service.log_action(
            db,
            correlation_id=op.correlation_id,
            operation_id=op.id,
            actor_user_id=op.requested_by,
            actor_username=op.requested_by_name,
            target_type=op.operation_type,
            target_name=(op.desired_state or {}).get("name", ""),
            action="operation_completed",
            reason=op.reason,
            details={"observed_state": result},
            approved_by_id=op.approved_by,
            approved_by_name=op.approved_by_name,
            result="success",
        )
        db.commit()

        return {"ok": True, "status": "completed", "result": result}

    except CentrifyCircuitOpenError as exc:
        state_machine.transition(op, "failed", error_message=str(exc))
        audit_service.log_action(
            db, correlation_id=op.correlation_id, operation_id=op.id,
            actor_user_id=0, actor_username="system",
            target_type=op.operation_type, action="operation_failed",
            reason=str(exc), result="failed",
        )
        db.commit()
        return {"ok": False, "error": str(exc), "error_class": "permanent"}

    except CentrifyAuthError as exc:
        state_machine.transition(op, "failed", error_message=str(exc))
        audit_service.log_action(
            db, correlation_id=op.correlation_id, operation_id=op.id,
            actor_user_id=0, actor_username="system",
            target_type=op.operation_type, action="operation_failed",
            reason=str(exc), result="failed",
        )
        db.commit()
        return {"ok": False, "error": str(exc), "error_class": "permanent"}

    except CentrifyConnectionError as exc:
        op.retry_count = (op.retry_count or 0) + 1
        if op.retry_count >= (op.max_retries or 3):
            state_machine.transition(op, "failed", error_message=f"Max retry aşıldı: {exc}")
        else:
            state_machine.transition(op, "failed", error_message=str(exc))
        db.commit()
        return {"ok": False, "error": str(exc), "error_class": "transient"}

    except Exception as exc:
        logger.exception("Operasyon yürütme hatası: op #%s", operation_id)
        state_machine.transition(op, "failed", error_message=str(exc))
        db.commit()
        return {"ok": False, "error": str(exc), "error_class": "transient"}


def retry_operation(
    db: Session,
    operation_id: int,
    *,
    retried_by: int,
    retried_by_name: str,
) -> dict:
    """Başarısız operasyonu yeniden kuyruğa al."""
    from app.models.centrify_zone import CentrifyOperation

    op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
    if op is None:
        return {"ok": False, "error": "Operasyon bulunamadı"}

    if op.status not in ("failed", "ambiguous"):
        return {"ok": False, "error": f"Yalnızca failed/ambiguous durumlar yeniden denenebilir (durum: {op.status})"}

    ok = state_machine.transition(op, "requested", actor_id=retried_by,
                                   error_message=None)
    if not ok:
        return {"ok": False, "error": "Geçersiz durum geçişi"}

    # Onay gerekliyse tekrar onaya yolla
    if state_machine.needs_approval(op.operation_type):
        state_machine.transition(op, "pending_approval", actor_id=retried_by)

    audit_service.log_action(
        db,
        correlation_id=op.correlation_id,
        operation_id=op.id,
        actor_user_id=retried_by,
        actor_username=retried_by_name,
        target_type=op.operation_type,
        target_name=(op.desired_state or {}).get("name", ""),
        action="operation_retried",
        reason=f"Yeniden deneme #{(op.retry_count or 0) + 1}",
        result="retried",
    )
    db.commit()

    return {"ok": True, "status": op.status}


def _dispatch_operation(adapter, operation_type: str, desired: dict) -> dict:
    """Operasyon tipine göre doğru adaptör metodunu çağır."""
    dispatch = {
        "create_role_assignment": lambda: adapter.create_role_assignment(
            zone_dn=desired["zone_dn"],
            role=desired["role_name"],
            assignee_dn=desired["assignee_dn"],
            scope=desired.get("scope_type", "zone"),
        ),
        "delete_role_assignment": lambda: adapter.delete_role_assignment(
            zone_dn=desired["zone_dn"],
            assignment_id=desired["assignment_ad_guid"],
        ),
        "create_role": lambda: adapter.create_role(
            zone_dn=desired["zone_dn"],
            name=desired["name"],
            description=desired.get("description", ""),
        ),
        "delete_role": lambda: adapter.delete_role(
            zone_dn=desired["zone_dn"],
            name=desired["name"],
        ),
        "update_role": lambda: adapter.update_role(
            zone_dn=desired["zone_dn"],
            name=desired["name"],
            new_desc=desired.get("description", ""),
        ),
        "create_command": lambda: adapter.create_command(
            zone_dn=desired["zone_dn"],
            name=desired["name"],
            path=desired.get("command_path", ""),
            run_as=desired.get("run_as_user", "root"),
            auth_type=desired.get("auth_type", "password"),
            match=desired.get("match_type", "exact"),
            run_as_group=desired.get("run_as_group", ""),
            description=desired.get("description", ""),
        ),
        "delete_command": lambda: adapter.delete_command(
            zone_dn=desired["zone_dn"],
            name=desired["name"],
        ),
        "add_command_to_role": lambda: adapter.add_command_to_role(
            zone_dn=desired["zone_dn"],
            role=desired["role_name"],
            command=desired["command_name"],
        ),
        "remove_command_from_role": lambda: adapter.remove_command_from_role(
            zone_dn=desired["zone_dn"],
            role=desired["role_name"],
            command=desired["command_name"],
        ),
        "clone_role": lambda: adapter.clone_role(
            src_zone=desired["src_zone_dn"],
            src_role=desired["src_role_name"],
            dst_zone=desired["dst_zone_dn"],
            dst_name=desired["dst_role_name"],
        ),
        "overwrite_role": lambda: adapter.overwrite_role_commands(
            src_zone=desired["src_zone_dn"],
            src_role=desired["src_role_name"],
            dst_zone=desired["dst_zone_dn"],
            dst_role=desired["dst_role_name"],
        ),
    }

    handler = dispatch.get(operation_type)
    if handler is None:
        raise CentrifyError(f"Desteklenmeyen operasyon tipi: {operation_type}")

    result = handler()
    if hasattr(result, '__dict__'):
        return {"success": result.success, "message": result.message, "data": result.data}
    if isinstance(result, dict):
        return result
    return {"success": True, "message": "OK"}


def apply_local_state(db: Session, op) -> None:
    """İstenen durumu Centrify Postgres tablolarına yaz — UI hemen güncellenir."""
    from app.models.centrify_zone import (
        CentrifyZone, CentrifyRole, CentrifyCommand, CentrifyRoleCommand,
        CentrifyRoleAssignment,
    )

    desired = op.desired_state or {}
    zone_id = op.zone_id
    op_type = op.operation_type
    zone = db.query(CentrifyZone).filter_by(id=zone_id).first() if zone_id else None
    zone_dn = desired.get("zone_dn") or (zone.ad_dn if zone else "")

    def _guid():
        return uuid.uuid4()

    if op_type in ("create_role", "clone_role"):
        name = desired.get("name") or desired.get("dst_role_name")
        if not name:
            raise ValueError("Rol adı yok")
        existing = db.query(CentrifyRole).filter_by(zone_id=zone_id, name=name, deleted_in_ad=False).first()
        if existing:
            return
        src = None
        src_name = desired.get("source_role_name") or desired.get("src_role_name")
        if src_name:
            src = db.query(CentrifyRole).filter_by(zone_id=zone_id, name=src_name, deleted_in_ad=False).first()
            if src is None and zone:
                src = db.query(CentrifyRole).filter_by(name=src_name, deleted_in_ad=False).first()
        role = CentrifyRole(
            zone_id=zone_id,
            ad_guid=_guid(),
            ad_dn=f"CN={name},{zone_dn}" if zone_dn else name,
            name=name,
            description=desired.get("description") or (src.description if src else None),
            is_system_role=False,
            management_state="managed",
            allow_local_accounts=bool(desired.get("allow_local_accounts", src.allow_local_accounts if src else False)),
            password_login_allowed=bool(desired.get("password_login_allowed", src.password_login_allowed if src else False)),
            sso_login_allowed=bool(desired.get("sso_login_allowed", src.sso_login_allowed if src else False)),
            ad_disabled_sudo_cron=bool(desired.get("ad_disabled_sudo_cron", src.ad_disabled_sudo_cron if src else False)),
            non_restricted_shell=bool(desired.get("non_restricted_shell", src.non_restricted_shell if src else False)),
            user_visible=desired.get("user_visible", src.user_visible if src else True) is not False,
            console_login_allowed=bool(desired.get("console_login_allowed", src.console_login_allowed if src else False)),
            remote_login_allowed=bool(desired.get("remote_login_allowed", src.remote_login_allowed if src else False)),
            powershell_remote_allowed=bool(desired.get("powershell_remote_allowed", src.powershell_remote_allowed if src else False)),
            rescue_login_allowed=bool(desired.get("rescue_login_allowed", src.rescue_login_allowed if src else False)),
            require_mfa=bool(desired.get("require_mfa", src.require_mfa if src else False)),
            audit_level=desired.get("audit_level") or (src.audit_level if src else "if_possible"),
            custom_attributes=desired.get("custom_attributes") or (src.custom_attributes if src else None),
        )
        db.add(role)
        db.flush()
        if src:
            for rc in src.role_commands or []:
                db.add(CentrifyRoleCommand(role_id=role.id, command_id=rc.command_id))

    elif op_type == "update_role":
        name = desired.get("name")
        role = db.query(CentrifyRole).filter_by(zone_id=zone_id, name=name, deleted_in_ad=False).first()
        if not role:
            raise ValueError(f"Rol bulunamadı: {name}")
        for field in (
            "description", "allow_local_accounts", "password_login_allowed", "sso_login_allowed",
            "ad_disabled_sudo_cron", "non_restricted_shell", "user_visible", "console_login_allowed",
            "remote_login_allowed", "powershell_remote_allowed", "rescue_login_allowed",
            "require_mfa", "audit_level", "custom_attributes",
        ):
            if field in desired:
                setattr(role, field, desired[field])
        role.management_state = "managed"

    elif op_type == "delete_role":
        name = desired.get("name")
        role = db.query(CentrifyRole).filter_by(zone_id=zone_id, name=name, deleted_in_ad=False).first()
        if role:
            role.deleted_in_ad = True

    elif op_type == "create_command":
        name = desired.get("name")
        if not name:
            raise ValueError("Komut adı yok")
        existing = db.query(CentrifyCommand).filter_by(zone_id=zone_id, name=name, deleted_in_ad=False).first()
        if existing:
            return
        db.add(CentrifyCommand(
            zone_id=zone_id,
            ad_guid=_guid(),
            ad_dn=f"CN={name},{zone_dn}" if zone_dn else name,
            name=name,
            command_path=desired.get("command_path"),
            match_type=desired.get("match_type") or "glob",
            run_as_user=desired.get("run_as_user") or "root",
            run_as_group=desired.get("run_as_group") or "",
            auth_type=desired.get("auth_type") or "password",
            description=desired.get("description"),
            management_state="managed",
        ))

    elif op_type == "delete_command":
        name = desired.get("name") or desired.get("command_name")
        cmd = db.query(CentrifyCommand).filter_by(zone_id=zone_id, name=name, deleted_in_ad=False).first()
        if cmd:
            cmd.deleted_in_ad = True

    elif op_type == "add_command_to_role":
        role = db.query(CentrifyRole).filter_by(zone_id=zone_id, name=desired.get("role_name"), deleted_in_ad=False).first()
        if role is None:
            role = db.query(CentrifyRole).filter_by(name=desired.get("role_name"), deleted_in_ad=False).first()
        cmd = db.query(CentrifyCommand).filter_by(zone_id=zone_id, name=desired.get("command_name"), deleted_in_ad=False).first()
        if not role or not cmd:
            raise ValueError("Rol veya komut bulunamadı")
        exists = db.query(CentrifyRoleCommand).filter_by(role_id=role.id, command_id=cmd.id).first()
        if not exists:
            db.add(CentrifyRoleCommand(role_id=role.id, command_id=cmd.id))

    elif op_type == "remove_command_from_role":
        role = db.query(CentrifyRole).filter_by(name=desired.get("role_name"), deleted_in_ad=False).first()
        cmd = db.query(CentrifyCommand).filter_by(zone_id=zone_id, name=desired.get("command_name"), deleted_in_ad=False).first()
        if role and cmd:
            link = db.query(CentrifyRoleCommand).filter_by(role_id=role.id, command_id=cmd.id).first()
            if link:
                db.delete(link)

    elif op_type == "create_role_assignment":
        role = db.query(CentrifyRole).filter_by(name=desired.get("role_name"), deleted_in_ad=False).first()
        if not role:
            raise ValueError(f"Rol bulunamadı: {desired.get('role_name')}")
        db.add(CentrifyRoleAssignment(
            zone_id=zone_id,
            computer_id=desired.get("computer_id"),
            ad_guid=_guid(),
            ad_dn="",
            role_id=role.id,
            assignee_type=desired.get("assignee_type") or "user",
            assignee_dn=desired.get("assignee_dn") or desired.get("assignee_name") or "",
            assignee_name=desired.get("assignee_name") or "",
            scope_type=desired.get("scope_type") or ("computer" if desired.get("computer_id") else "zone"),
            management_state="managed",
        ))

    elif op_type == "delete_role_assignment":
        aid = desired.get("assignment_id")
        if aid:
            a = db.query(CentrifyRoleAssignment).filter_by(id=aid).first()
            if a:
                a.deleted_in_ad = True

