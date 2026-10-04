"""Centrify Zone Management REST API — Faz 0 (spike).

Bu router yüklenemezse ainew çalışmaya devam eder — import hatası
ana app'i çökertmez.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/centrify-mgmt", tags=["centrify"])

# Router yüklendiğinde tabloları oluşturmayı dene (DB yoksa sessizce geç)
try:
    from app.services.centrify.database import create_centrify_tables
    create_centrify_tables()
except Exception as _init_err:
    logger.warning("Centrify tabloları oluşturulamadı (ilk başlatma bekleniyor): %s", _init_err)

# Mevcut tabloya yeni sütunları ekle (idempotent ALTER TABLE)
try:
    from app.services.centrify.database import get_centrify_thread_session as _gs
    _db = _gs()
    if _db:
        _new_cols = {
            "centrify_roles": [
                ("allow_local_accounts", "BOOLEAN DEFAULT FALSE"),
                ("available_times", "JSONB"),
                ("password_login_allowed", "BOOLEAN DEFAULT FALSE"),
                ("sso_login_allowed", "BOOLEAN DEFAULT FALSE"),
                ("ad_disabled_sudo_cron", "BOOLEAN DEFAULT FALSE"),
                ("non_restricted_shell", "BOOLEAN DEFAULT FALSE"),
                ("user_visible", "BOOLEAN DEFAULT TRUE"),
                ("console_login_allowed", "BOOLEAN DEFAULT FALSE"),
                ("remote_login_allowed", "BOOLEAN DEFAULT FALSE"),
                ("powershell_remote_allowed", "BOOLEAN DEFAULT FALSE"),
                ("rescue_login_allowed", "BOOLEAN DEFAULT FALSE"),
                ("require_mfa", "BOOLEAN DEFAULT FALSE"),
                ("audit_level", "VARCHAR(30) DEFAULT 'if_possible'"),
                ("custom_attributes", "JSONB"),
            ],
            "centrify_role_assignments": [
                ("computer_id", "INTEGER REFERENCES centrify_computers(id)"),
            ],
        }
        for _tbl, _cols in _new_cols.items():
            for _col, _typ in _cols:
                try:
                    _db.execute(__import__("sqlalchemy").text(
                        f"ALTER TABLE {_tbl} ADD COLUMN IF NOT EXISTS {_col} {_typ}"
                    ))
                except Exception:
                    pass
        _db.commit()
        _db.close()
        logger.info("Centrify role/assignment sütun migrasyonu tamamlandı")
except Exception as _mig_err:
    logger.warning("Centrify sütun migrasyonu atlandı: %s", _mig_err)

# ── Pydantic şemaları ─────────────────────────────────────────


class CentrifyConfigIn(BaseModel):
    winrm_host: str = Field(..., min_length=1, description="Windows sunucu IP/hostname")
    winrm_port: int = Field(5985, ge=1, le=65535)
    winrm_https: bool = False
    service_account: str = Field(..., min_length=1, description="sAMAccountName (örn: service_centrify)")
    password: str = Field(..., min_length=1)
    sync_interval_minutes: int = Field(30, ge=5, le=1440)
    label: str = "Varsayılan"


class CentrifyConfigOut(BaseModel):
    id: int
    label: str
    winrm_host: str
    winrm_port: int
    winrm_https: bool
    service_account: str
    sync_interval_minutes: int
    sync_enabled: bool
    enabled: bool


class ConnectionTestOut(BaseModel):
    connected: bool
    winrm_ok: bool = False
    adedit_found: bool = False
    adedit_version: str = ""
    zone_count: int = 0
    latency_ms: int = 0
    error: str = ""


class CircuitStatusOut(BaseModel):
    open: bool
    fail_count: int
    ttl_seconds: Optional[int] = None
    redis_available: bool = True


class ZoneOut(BaseModel):
    id: int
    ad_guid: str
    ad_dn: str
    name: str
    zone_type: str
    parent_zone_id: Optional[int] = None
    description: Optional[str] = None
    management_state: str


class RoleOut(BaseModel):
    id: int
    ad_guid: str
    name: str
    description: Optional[str] = None
    is_system_role: bool = False
    management_state: str
    command_count: int = 0
    zone_name: Optional[str] = None
    zone_dn: Optional[str] = None
    # General
    allow_local_accounts: bool = False
    # System Rights — UNIX
    password_login_allowed: bool = False
    sso_login_allowed: bool = False
    ad_disabled_sudo_cron: bool = False
    non_restricted_shell: bool = False
    user_visible: bool = True
    # System Rights — Windows
    console_login_allowed: bool = False
    remote_login_allowed: bool = False
    powershell_remote_allowed: bool = False
    # System Rights — Rescue
    rescue_login_allowed: bool = False
    # Authentication
    require_mfa: bool = False
    # Audit
    audit_level: str = "if_possible"
    # Custom Attributes
    custom_attributes: Optional[list] = None


class CommandOut(BaseModel):
    id: int
    ad_guid: str
    name: str
    command_path: Optional[str] = None
    match_type: Optional[str] = None
    run_as_user: Optional[str] = None
    auth_type: Optional[str] = None
    description: Optional[str] = None
    management_state: str


class OperationIn(BaseModel):
    operation_type: str = Field(..., description="create_role_assignment, delete_role, vb.")
    zone_id: Optional[int] = None
    desired_state: dict = Field(..., description="Hedef durum verisi")
    reason: str = Field(..., min_length=3, description="Zorunlu gerekçe")


class ApproveIn(BaseModel):
    pass


class RejectIn(BaseModel):
    reason: str = Field("", description="Red gerekçesi")


class CloneRoleIn(BaseModel):
    source_role_id: int
    target_zone_id: int
    new_name: str = Field(..., min_length=1)
    copy_commands: bool = True
    reason: str = Field(..., min_length=3)


class OverwriteRoleIn(BaseModel):
    source_role_id: int
    target_role_id: int
    reason: str = Field(..., min_length=3)


class CommandCreateIn(BaseModel):
    zone_id: int
    name: str = Field(..., min_length=1, max_length=200)
    command_path: str = Field(..., min_length=1)
    match_type: str = Field("glob", pattern="^(exact|glob|regex)$")
    run_as_user: str = Field("root")
    run_as_group: str = Field("")
    auth_type: str = Field("password", pattern="^(password|none|mfa)$")
    description: str = Field("")
    from_template_id: Optional[int] = None
    reason: str = Field(..., min_length=3)


class CommandToRoleIn(BaseModel):
    zone_id: int
    role_name: str
    command_name: str
    reason: str = Field(..., min_length=3)


class CommandDeleteIn(BaseModel):
    zone_id: int
    command_name: str
    reason: str = Field(..., min_length=3)


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1)
    category: str = Field("Genel")
    command_path: str = Field(..., min_length=1)
    match_type: str = Field("glob", pattern="^(exact|glob|regex)$")
    run_as_user: str = Field("root")
    run_as_group: str = Field("")
    auth_type: str = Field("password", pattern="^(password|none|mfa)$")
    description: str = Field("")
    risk_level: str = Field("medium", pattern="^(low|medium|high|critical)$")


class WhitelistIn(BaseModel):
    pattern: str = Field(..., min_length=1)
    pattern_type: str = Field("glob", pattern="^(glob|regex|prefix)$")
    description: str = Field("")
    category: str = Field("Genel")
    risk_level: str = Field("medium", pattern="^(low|medium|high|critical)$")
    max_run_as: str = Field("root")
    requires_auth: bool = True


# ── Yardımcılar ───────────────────────────────────────────────


def _get_adapter():
    """Aktif entegrasyon ayarından WinRM adaptörü oluştur."""
    try:
        from app.services.centrify.database import get_centrify_thread_session
        from app.models.centrify_zone import CentrifyIntegrationConfig

        db = get_centrify_thread_session()
        if db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Centrify DB erişilemiyor",
            )
        try:
            config = db.query(CentrifyIntegrationConfig).filter_by(enabled=True).first()
        finally:
            db.close()

        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Centrify entegrasyonu yapılandırılmamış",
            )

        from app.services.centrify.winrm_adapter import WinRMCentrifyAdapter
        return WinRMCentrifyAdapter.from_config({
            "winrm_host": config.winrm_host,
            "winrm_port": config.winrm_port,
            "winrm_https": config.winrm_https,
            "service_account": config.service_account,
            "password_enc": config.password_enc,
            "timeout": 60,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Centrify adaptör oluşturma hatası: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Centrify adaptör hatası: {exc}",
        )


# ── Bağlantı testi (yapılandırma sırasında) ──────────────────


@router.post("/config/test-connection", response_model=ConnectionTestOut)
async def test_connection(body: CentrifyConfigIn):
    """WinRM bağlantı testi — yapılandırma sırasında kullanılır."""
    from app.services.centrify.winrm_adapter import WinRMCentrifyAdapter
    adapter = WinRMCentrifyAdapter(
        host=body.winrm_host,
        username=body.service_account,
        password=body.password,
        port=body.winrm_port,
        use_https=body.winrm_https,
    )
    result = adapter.test_connection()
    return ConnectionTestOut(
        connected=result.connected,
        winrm_ok=result.winrm_ok,
        adedit_found=result.adedit_found,
        adedit_version=result.adedit_version,
        zone_count=result.zone_count,
        latency_ms=result.latency_ms,
        error=result.error,
    )


# ── Yapılandırma CRUD ────────────────────────────────────────


@router.put("/config", response_model=CentrifyConfigOut)
async def save_config(body: CentrifyConfigIn):
    """Centrify entegrasyon ayarlarını kaydet/güncelle."""
    from app.services.centrify.database import get_centrify_thread_session, create_centrify_tables
    from app.models.centrify_zone import CentrifyIntegrationConfig
    from app.core.encryption import encrypt_secret

    create_centrify_tables()
    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        existing = db.query(CentrifyIntegrationConfig).first()
        if existing:
            existing.winrm_host = body.winrm_host
            existing.winrm_port = body.winrm_port
            existing.winrm_https = body.winrm_https
            existing.service_account = body.service_account
            existing.password_enc = encrypt_secret(body.password)
            existing.sync_interval_minutes = body.sync_interval_minutes
            existing.label = body.label
            existing.enabled = True
            db.commit()
            db.refresh(existing)
            cfg = existing
        else:
            cfg = CentrifyIntegrationConfig(
                winrm_host=body.winrm_host,
                winrm_port=body.winrm_port,
                winrm_https=body.winrm_https,
                service_account=body.service_account,
                password_enc=encrypt_secret(body.password),
                sync_interval_minutes=body.sync_interval_minutes,
                label=body.label,
                enabled=True,
            )
            db.add(cfg)
            db.commit()
            db.refresh(cfg)
        return CentrifyConfigOut(
            id=cfg.id,
            label=cfg.label,
            winrm_host=cfg.winrm_host,
            winrm_port=cfg.winrm_port,
            winrm_https=cfg.winrm_https,
            service_account=cfg.service_account,
            sync_interval_minutes=cfg.sync_interval_minutes,
            sync_enabled=cfg.sync_enabled,
            enabled=cfg.enabled,
        )
    finally:
        db.close()


@router.get("/config", response_model=Optional[CentrifyConfigOut])
async def get_config():
    """Mevcut entegrasyon ayarını getir."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyIntegrationConfig

    db = get_centrify_thread_session()
    if db is None:
        return None
    try:
        cfg = db.query(CentrifyIntegrationConfig).filter_by(enabled=True).first()
        if cfg is None:
            return None
        return CentrifyConfigOut(
            id=cfg.id,
            label=cfg.label,
            winrm_host=cfg.winrm_host,
            winrm_port=cfg.winrm_port,
            winrm_https=cfg.winrm_https,
            service_account=cfg.service_account,
            sync_interval_minutes=cfg.sync_interval_minutes,
            sync_enabled=cfg.sync_enabled,
            enabled=cfg.enabled,
        )
    except Exception:
        return None
    finally:
        db.close()


# ── Circuit breaker ──────────────────────────────────────────


@router.get("/circuit-status", response_model=CircuitStatusOut)
async def circuit_status():
    """Circuit breaker durumunu getir."""
    from app.services.centrify.circuit_breaker import get_circuit_status
    return CircuitStatusOut(**get_circuit_status())


@router.post("/config/reset-circuit")
async def reset_circuit():
    """Circuit breaker'ı resetle (admin işlemi)."""
    from app.services.centrify.circuit_breaker import reset_circuit as do_reset
    ok = do_reset(actor="admin_api")
    if not ok:
        raise HTTPException(status_code=500, detail="Circuit reset başarısız")
    return {"ok": True, "message": "Circuit breaker resetlendi"}


# ── Salt okunur — zone, role, command listeleri ──────────────


@router.get("/zones")
async def list_zones():
    """Zone listesini DB'den getir."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        zones = db.query(CentrifyZone).filter_by(deleted_in_ad=False).all()
        return [
            ZoneOut(
                id=z.id,
                ad_guid=str(z.ad_guid),
                ad_dn=z.ad_dn,
                name=z.name,
                zone_type=z.zone_type,
                parent_zone_id=z.parent_zone_id,
                description=z.description,
                management_state=z.management_state,
            )
            for z in zones
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/roles")
async def list_roles(zone_id: int, include_parents: bool = False):
    """Zone içindeki rolleri DB'den getir. include_parents=true ise parent zone rollerini de ekler."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRole, CentrifyZone

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        zone_ids = [zone_id]
        if include_parents:
            cur = db.query(CentrifyZone).filter_by(id=zone_id).first()
            while cur and cur.parent_zone_id:
                zone_ids.append(cur.parent_zone_id)
                cur = db.query(CentrifyZone).filter_by(id=cur.parent_zone_id).first()

        roles = db.query(CentrifyRole).filter(
            CentrifyRole.zone_id.in_(zone_ids),
            CentrifyRole.deleted_in_ad.is_(False),
        ).all()

        zone_cache: dict[int, CentrifyZone] = {}
        def _zone(zid: int) -> CentrifyZone | None:
            if zid not in zone_cache:
                zone_cache[zid] = db.query(CentrifyZone).filter_by(id=zid).first()
            return zone_cache[zid]

        return [
            RoleOut(
                id=r.id,
                ad_guid=str(r.ad_guid),
                name=r.name,
                description=r.description,
                is_system_role=r.is_system_role or False,
                management_state=r.management_state,
                command_count=len(r.role_commands) if r.role_commands else 0,
                zone_name=(_zone(r.zone_id).name if _zone(r.zone_id) else None),
                zone_dn=(_zone(r.zone_id).ad_dn if _zone(r.zone_id) else None),
                allow_local_accounts=r.allow_local_accounts or False,
                password_login_allowed=r.password_login_allowed or False,
                sso_login_allowed=r.sso_login_allowed or False,
                ad_disabled_sudo_cron=r.ad_disabled_sudo_cron or False,
                non_restricted_shell=r.non_restricted_shell or False,
                user_visible=r.user_visible if r.user_visible is not None else True,
                console_login_allowed=r.console_login_allowed or False,
                remote_login_allowed=r.remote_login_allowed or False,
                powershell_remote_allowed=r.powershell_remote_allowed or False,
                rescue_login_allowed=r.rescue_login_allowed or False,
                require_mfa=r.require_mfa or False,
                audit_level=r.audit_level or "if_possible",
                custom_attributes=r.custom_attributes,
            )
            for r in roles
        ]
    finally:
        db.close()


@router.get("/zones/{zone_id}/commands")
async def list_commands(zone_id: int):
    """Zone içindeki komutları DB'den getir."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommand

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        cmds = db.query(CentrifyCommand).filter_by(zone_id=zone_id, deleted_in_ad=False).all()
        return [
            CommandOut(
                id=c.id,
                ad_guid=str(c.ad_guid),
                name=c.name,
                command_path=c.command_path,
                match_type=c.match_type,
                run_as_user=c.run_as_user,
                auth_type=c.auth_type,
                description=c.description,
                management_state=c.management_state,
            )
            for c in cmds
        ]
    finally:
        db.close()


@router.get("/zones/{zone_id}")
async def get_zone(zone_id: int):
    """Zone detay."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        z = db.query(CentrifyZone).filter_by(id=zone_id, deleted_in_ad=False).first()
        if z is None:
            raise HTTPException(status_code=404, detail="Zone bulunamadı")
        return ZoneOut(
            id=z.id, ad_guid=str(z.ad_guid), ad_dn=z.ad_dn, name=z.name,
            zone_type=z.zone_type, parent_zone_id=z.parent_zone_id,
            description=z.description, management_state=z.management_state,
        )
    finally:
        db.close()


@router.get("/zones/{zone_id}/children")
async def list_zone_children(zone_id: int):
    """Alt zone'lar."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        children = db.query(CentrifyZone).filter_by(parent_zone_id=zone_id, deleted_in_ad=False).all()
        return [
            ZoneOut(id=z.id, ad_guid=str(z.ad_guid), ad_dn=z.ad_dn, name=z.name,
                    zone_type=z.zone_type, parent_zone_id=z.parent_zone_id,
                    description=z.description, management_state=z.management_state)
            for z in children
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/role-assignments")
async def list_role_assignments(zone_id: int):
    """Zone-level role assignment'lar (computer_id IS NULL)."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRoleAssignment

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyRoleAssignment).filter(
            CentrifyRoleAssignment.zone_id == zone_id,
            CentrifyRoleAssignment.deleted_in_ad.is_(False),
            CentrifyRoleAssignment.computer_id.is_(None),
        ).all()
        return [
            {
                "id": a.id, "ad_guid": str(a.ad_guid) if a.ad_guid else None,
                "role_id": a.role_id, "assignee_type": a.assignee_type,
                "assignee_name": a.assignee_name, "assignee_dn": a.assignee_dn,
                "scope_type": a.scope_type, "computer_id": a.computer_id,
                "scope_dn": a.scope_dn,
                "start_time": a.start_time.isoformat() if a.start_time else None,
                "end_time": a.end_time.isoformat() if a.end_time else None,
                "management_state": a.management_state,
            }
            for a in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/computers/{computer_id}/role-assignments")
async def list_computer_role_assignments(zone_id: int, computer_id: int):
    """Belirli bir computer'a ait role assignment'lar (scope_type='computer')."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRoleAssignment

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyRoleAssignment).filter_by(
            zone_id=zone_id, computer_id=computer_id, deleted_in_ad=False,
        ).all()
        return [
            {
                "id": a.id, "ad_guid": str(a.ad_guid) if a.ad_guid else None,
                "role_id": a.role_id, "assignee_type": a.assignee_type,
                "assignee_name": a.assignee_name, "assignee_dn": a.assignee_dn,
                "scope_type": a.scope_type, "computer_id": a.computer_id,
                "scope_dn": a.scope_dn,
                "start_time": a.start_time.isoformat() if a.start_time else None,
                "end_time": a.end_time.isoformat() if a.end_time else None,
                "management_state": a.management_state,
            }
            for a in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/computer-roles")
async def list_computer_roles(zone_id: int):
    """Zone içindeki computer role'ler."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyComputerRole

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyComputerRole).filter_by(zone_id=zone_id, deleted_in_ad=False).all()
        return [
            {
                "id": cr.id, "ad_guid": str(cr.ad_guid), "name": cr.name,
                "description": cr.description, "management_state": cr.management_state,
            }
            for cr in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/computers")
async def list_computers(zone_id: int):
    """Zone üyesi sunucular."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyComputer

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyComputer).filter_by(zone_id=zone_id, deleted_in_ad=False).all()
        return [
            {
                "id": c.id, "ad_guid": str(c.ad_guid), "name": c.name,
                "fqdn": c.fqdn, "os_type": c.os_type, "agent_version": c.agent_version,
                "ainew_server_id": c.ainew_server_id, "management_state": c.management_state,
            }
            for c in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/zones/{zone_id}/unix-profiles")
async def list_unix_profiles(zone_id: int):
    """Zone UNIX profilleri."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyUnixProfile

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyUnixProfile).filter_by(zone_id=zone_id).all()
        return [
            {
                "id": p.id, "user_dn": p.user_dn, "user_name": p.user_name,
                "uid": p.uid, "gid": p.gid, "home_dir": p.home_dir,
                "shell": p.shell, "gecos": p.gecos, "enabled": p.enabled,
            }
            for p in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/roles/{role_id}")
async def get_role_detail(role_id: int):
    """Rol detay — bağlı komutlarıyla birlikte."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRole

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        r = db.query(CentrifyRole).filter_by(id=role_id).first()
        if r is None:
            raise HTTPException(status_code=404, detail="Rol bulunamadı")
        commands = []
        for rc in (r.role_commands or []):
            c = rc.command
            if c and not c.deleted_in_ad:
                commands.append({
                    "id": c.id, "name": c.name, "command_path": c.command_path,
                    "match_type": c.match_type, "run_as_user": c.run_as_user,
                    "auth_type": c.auth_type, "description": c.description,
                })
        return {
            "id": r.id, "ad_guid": str(r.ad_guid), "name": r.name,
            "description": r.description, "is_system_role": r.is_system_role or False,
            "management_state": r.management_state, "zone_id": r.zone_id,
            "commands": commands, "command_count": len(commands),
            "allow_local_accounts": r.allow_local_accounts or False,
            "password_login_allowed": r.password_login_allowed or False,
            "sso_login_allowed": r.sso_login_allowed or False,
            "ad_disabled_sudo_cron": r.ad_disabled_sudo_cron or False,
            "non_restricted_shell": r.non_restricted_shell or False,
            "user_visible": r.user_visible if r.user_visible is not None else True,
            "console_login_allowed": r.console_login_allowed or False,
            "remote_login_allowed": r.remote_login_allowed or False,
            "powershell_remote_allowed": r.powershell_remote_allowed or False,
            "rescue_login_allowed": r.rescue_login_allowed or False,
            "require_mfa": r.require_mfa or False,
            "audit_level": r.audit_level or "if_possible",
            "custom_attributes": r.custom_attributes,
        }
    finally:
        db.close()


@router.get("/zones/{zone_id}/drift")
async def list_drift_events(zone_id: int):
    """Zone drift event'leri."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyDriftEvent

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = (
            db.query(CentrifyDriftEvent)
            .filter_by(zone_id=zone_id, resolved=False)
            .order_by(CentrifyDriftEvent.detected_at.desc())
            .limit(100)
            .all()
        )
        return [
            {
                "id": d.id, "object_type": d.object_type, "object_name": d.object_name,
                "drift_details": d.drift_details, "detected_at": d.detected_at.isoformat() if d.detected_at else None,
            }
            for d in items
        ]
    except Exception:
        return []
    finally:
        db.close()


# ── Deterministik sorgular (AI + UI) ─────────────────────────


@router.get("/query/effective-access")
async def query_effective_access(user: str, computer: str):
    """Kullanıcı+sunucu için etkili komut zinciri (parent miras yok)."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import resolve_effective_access

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return resolve_effective_access(db, user=user, computer=computer)
    finally:
        db.close()


@router.get("/query/diagnose-login")
async def query_diagnose_login(user: str, computer: str):
    """Sabit sırayla login teşhisi."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import diagnose_login_failure

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return diagnose_login_failure(db, user=user, computer=computer)
    finally:
        db.close()


@router.get("/query/expiring-assignments")
async def query_expiring_assignments(days: int = 30, limit: int = 50):
    """N gün içinde süresi dolacak atamalar."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_expiring_assignments

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return find_expiring_assignments(db, days=days, limit=limit)
    finally:
        db.close()


@router.get("/query/similar-roles")
async def query_similar_roles(role: str = "", commands: str = "", zone_id: Optional[int] = None, limit: int = 10):
    """Benzer roller (komut kümesi Jaccard). commands=virgülle ayrılmış taslak komut adları."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_similar_roles

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        cmd_list = [c.strip() for c in (commands or "").split(",") if c.strip()] or None
        return find_similar_roles(db, role=role, commands=cmd_list, zone_id=zone_id, limit=limit)
    finally:
        db.close()


@router.get("/query/similar-commands")
async def query_similar_commands(command: str = "", path: str = "", zone_id: Optional[int] = None, limit: int = 15):
    """Benzer komutlar (path/ad örtüşmesi)."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import find_similar_commands

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return find_similar_commands(db, command=command, path=path, zone_id=zone_id, limit=limit)
    finally:
        db.close()


@router.get("/query/explain-role")
async def query_explain_role(role: str, zone_id: Optional[int] = None):
    """Rol amacı: açıklama + komutlar + login + benzerler."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import explain_role

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return explain_role(db, role=role, zone_id=zone_id)
    finally:
        db.close()


@router.get("/query/explain-command")
async def query_explain_command(command: str, zone_id: Optional[int] = None):
    """Komut amacı: path + açıklama + kullanan roller + benzerler."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.query_service import explain_command

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(503, "Centrify DB erişilemiyor")
    try:
        return explain_command(db, command=command, zone_id=zone_id)
    finally:
        db.close()


# ── Sync ────────────────────────────────────────────────────


@router.get("/sync/status")
async def sync_status():
    """Son senkronizasyon durumu."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone

    db = get_centrify_thread_session()
    if db is None:
        return {"synced": False, "zone_count": 0, "last_synced_at": None}
    try:
        zones = db.query(CentrifyZone).filter_by(deleted_in_ad=False).all()
        last_sync = None
        for z in zones:
            if z.last_synced_at and (last_sync is None or z.last_synced_at > last_sync):
                last_sync = z.last_synced_at
        return {
            "synced": len(zones) > 0,
            "zone_count": len(zones),
            "last_synced_at": last_sync.isoformat() if last_sync else None,
        }
    except Exception:
        return {"synced": False, "zone_count": 0, "last_synced_at": None}
    finally:
        db.close()


@router.post("/sync/trigger")
async def trigger_sync():
    """WinRM ile zone verilerini çekip DB'ye yaz."""
    adapter = _get_adapter()
    from app.services.centrify.sync_service import run_full_sync
    result = run_full_sync(adapter)
    return result


# ── Operasyonlar (yazma kuyruğu) ────────────────────────────


def _extract_user(request) -> tuple[int, str]:
    """Request Authorization header'ından user id ve username çıkar."""
    from app.core.security import decode_access_token
    from app.core.database import SessionLocal
    try:
        token = (request.headers.get("authorization") or "").replace("Bearer ", "")
        payload = decode_access_token(token)
        user_id = payload.get("user_id") or payload.get("sub")
        if user_id:
            from app.models.user import User
            db = SessionLocal()
            try:
                user = db.query(User).filter_by(id=int(user_id)).first()
                if user:
                    return user.id, user.username
            finally:
                db.close()
    except Exception:
        pass
    return 0, "system"


@router.post("/operations")
async def create_operation(body: OperationIn, request: Request):
    """Yeni yazma operasyonu oluştur."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.provisioning_service import create_operation as svc_create

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        result = svc_create(
            db,
            operation_type=body.operation_type,
            zone_id=body.zone_id,
            desired_state=body.desired_state,
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


@router.get("/operations")
async def list_operations(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """Operasyon listesi."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyOperation

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        q = db.query(CentrifyOperation).order_by(CentrifyOperation.created_at.desc())
        if status:
            q = q.filter_by(status=status)
        ops = q.offset(offset).limit(limit).all()
        return [
            {
                "id": op.id,
                "correlation_id": str(op.correlation_id),
                "operation_type": op.operation_type,
                "status": op.status,
                "zone_id": op.zone_id,
                "desired_state": op.desired_state,
                "requested_by_name": op.requested_by_name,
                "approved_by_name": op.approved_by_name,
                "reason": op.reason,
                "error_message": op.error_message,
                "retry_count": op.retry_count,
                "created_at": op.created_at.isoformat() if op.created_at else None,
                "updated_at": op.updated_at.isoformat() if op.updated_at else None,
            }
            for op in ops
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.get("/operations/{operation_id}")
async def get_operation(operation_id: int):
    """Operasyon detay + durum geçmişi."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyOperation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        op = db.query(CentrifyOperation).filter_by(id=operation_id).first()
        if op is None:
            raise HTTPException(status_code=404, detail="Operasyon bulunamadı")
        return {
            "id": op.id,
            "correlation_id": str(op.correlation_id),
            "operation_type": op.operation_type,
            "status": op.status,
            "status_history": op.status_history,
            "zone_id": op.zone_id,
            "desired_state": op.desired_state,
            "observed_state": op.observed_state,
            "requested_by": op.requested_by,
            "requested_by_name": op.requested_by_name,
            "approved_by": op.approved_by,
            "approved_by_name": op.approved_by_name,
            "reason": op.reason,
            "error_message": op.error_message,
            "retry_count": op.retry_count,
            "max_retries": op.max_retries,
            "created_at": op.created_at.isoformat() if op.created_at else None,
            "updated_at": op.updated_at.isoformat() if op.updated_at else None,
        }
    finally:
        db.close()


@router.post("/operations/{operation_id}/approve")
async def approve_operation(operation_id: int, request: Request):
    """Operasyonu onayla. Dört göz: kendi isteğini kendi onaylayamaz."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.provisioning_service import approve_operation as svc_approve

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        result = svc_approve(db, operation_id, approved_by=user_id, approved_by_name=username)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Onay başarısız"))
        return result
    finally:
        db.close()


@router.post("/operations/{operation_id}/reject")
async def reject_operation(operation_id: int, body: RejectIn, request: Request):
    """Operasyonu reddet."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.provisioning_service import reject_operation as svc_reject

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        result = svc_reject(db, operation_id, rejected_by=user_id, rejected_by_name=username, reject_reason=body.reason)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Red başarısız"))
        return result
    finally:
        db.close()


@router.post("/operations/{operation_id}/cancel")
async def cancel_operation(operation_id: int, request: Request):
    """Operasyonu iptal et."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.provisioning_service import cancel_operation as svc_cancel

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        result = svc_cancel(db, operation_id, cancelled_by=user_id, cancelled_by_name=username)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "İptal başarısız"))
        return result
    finally:
        db.close()


@router.post("/operations/{operation_id}/retry")
async def retry_operation(operation_id: int, request: Request):
    """Başarısız operasyonu yeniden kuyruğa al."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.services.centrify.provisioning_service import retry_operation as svc_retry

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        result = svc_retry(db, operation_id, retried_by=user_id, retried_by_name=username)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Yeniden deneme başarısız"))
        return result
    finally:
        db.close()


# ── Rol diff / clone / overwrite ─────────────────────────────


@router.get("/roles/{role_id}/diff/{other_id}")
async def diff_roles(role_id: int, other_id: int):
    """İki rolün komutlarını karşılaştır — clone/overwrite öncesi önizleme."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRole

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        r1 = db.query(CentrifyRole).filter_by(id=role_id).first()
        r2 = db.query(CentrifyRole).filter_by(id=other_id).first()
        if not r1 or not r2:
            raise HTTPException(status_code=404, detail="Rol bulunamadı")

        def _cmds(role):
            cmds = {}
            for rc in (role.role_commands or []):
                c = rc.command
                if c and not c.deleted_in_ad:
                    cmds[c.name] = {
                        "id": c.id, "name": c.name, "command_path": c.command_path,
                        "match_type": c.match_type, "run_as_user": c.run_as_user,
                        "auth_type": c.auth_type,
                    }
            return cmds

        cmds1 = _cmds(r1)
        cmds2 = _cmds(r2)
        all_names = set(cmds1.keys()) | set(cmds2.keys())

        added, removed, unchanged = [], [], []
        for name in sorted(all_names):
            in1 = name in cmds1
            in2 = name in cmds2
            if in1 and in2:
                unchanged.append(cmds1[name])
            elif in1 and not in2:
                removed.append(cmds1[name])
            else:
                added.append(cmds2[name])

        # Etkilenen atamalar (hedef roldeki)
        assignment_count = len([a for a in (r1.assignments or []) if not a.deleted_in_ad])

        return {
            "role_a": {"id": r1.id, "name": r1.name, "zone_id": r1.zone_id, "command_count": len(cmds1)},
            "role_b": {"id": r2.id, "name": r2.name, "zone_id": r2.zone_id, "command_count": len(cmds2)},
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
            "affected_assignments": assignment_count,
        }
    finally:
        db.close()


@router.post("/roles/clone")
async def clone_role(body: CloneRoleIn, request: Request):
    """Rolü komutlarıyla birlikte kopyala — operasyon oluşturur."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRole, CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        src = db.query(CentrifyRole).filter_by(id=body.source_role_id).first()
        dst_zone = db.query(CentrifyZone).filter_by(id=body.target_zone_id).first()
        if not src:
            raise HTTPException(status_code=404, detail="Kaynak rol bulunamadı")
        if not dst_zone:
            raise HTTPException(status_code=404, detail="Hedef zone bulunamadı")

        # Aynı zone'da aynı isimde rol var mı?
        existing = db.query(CentrifyRole).filter_by(zone_id=body.target_zone_id, name=body.new_name, deleted_in_ad=False).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Hedef zone'da '{body.new_name}' adında rol zaten var")

        src_zone = db.query(CentrifyZone).filter_by(id=src.zone_id).first()

        result = create_operation(
            db,
            operation_type="clone_role",
            zone_id=body.target_zone_id,
            desired_state={
                "src_zone_dn": src_zone.ad_dn if src_zone else "",
                "src_role_name": src.name,
                "dst_zone_dn": dst_zone.ad_dn,
                "dst_role_name": body.new_name,
                "name": body.new_name,
                "copy_commands": body.copy_commands,
                "source_description": src.description,
            },
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


@router.post("/roles/overwrite")
async def overwrite_role(body: OverwriteRoleIn, request: Request):
    """Hedef rolün komutlarını kaynak rolünkilerle üzerine yaz — operasyon oluşturur."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyRole, CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        src = db.query(CentrifyRole).filter_by(id=body.source_role_id).first()
        dst = db.query(CentrifyRole).filter_by(id=body.target_role_id).first()
        if not src:
            raise HTTPException(status_code=404, detail="Kaynak rol bulunamadı")
        if not dst:
            raise HTTPException(status_code=404, detail="Hedef rol bulunamadı")

        src_zone = db.query(CentrifyZone).filter_by(id=src.zone_id).first()
        dst_zone = db.query(CentrifyZone).filter_by(id=dst.zone_id).first()

        result = create_operation(
            db,
            operation_type="overwrite_role",
            zone_id=dst.zone_id,
            desired_state={
                "src_zone_dn": src_zone.ad_dn if src_zone else "",
                "src_role_name": src.name,
                "dst_zone_dn": dst_zone.ad_dn if dst_zone else "",
                "dst_role_name": dst.name,
                "name": f"{dst.name} (overwrite from {src.name})",
            },
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


# ── Komut CRUD ────────────────────────────────────────────────


def _validate_whitelist(db, command_path: str) -> tuple[bool, str]:
    """Komut path'inin beyaz listeyle eşleşip eşleşmediğini kontrol et."""
    from app.models.centrify_zone import CentrifyCommandWhitelist
    import fnmatch
    import re

    entries = db.query(CentrifyCommandWhitelist).filter_by(enabled=True).all()
    if not entries:
        return True, ""  # Beyaz liste boşsa her şeye izin ver

    for entry in entries:
        if entry.pattern_type == "prefix":
            if command_path.startswith(entry.pattern):
                return True, ""
        elif entry.pattern_type == "glob":
            if fnmatch.fnmatch(command_path, entry.pattern):
                return True, ""
        elif entry.pattern_type == "regex":
            try:
                if re.match(entry.pattern, command_path):
                    return True, ""
            except re.error:
                continue
    return False, f"Komut path'i beyaz listede eşleşme bulamadı: {command_path}"


@router.post("/commands")
async def create_command(body: CommandCreateIn, request: Request):
    """Yeni komut oluştur — beyaz liste kontrolü + zorunlu onay."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        zone = db.query(CentrifyZone).filter_by(id=body.zone_id, deleted_in_ad=False).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone bulunamadı")

        allowed, msg = _validate_whitelist(db, body.command_path)
        if not allowed:
            raise HTTPException(status_code=403, detail=msg)

        result = create_operation(
            db,
            operation_type="create_command",
            zone_id=body.zone_id,
            desired_state={
                "zone_dn": zone.ad_dn,
                "name": body.name,
                "command_path": body.command_path,
                "match_type": body.match_type,
                "run_as_user": body.run_as_user,
                "run_as_group": body.run_as_group,
                "auth_type": body.auth_type,
                "description": body.description,
                "from_template_id": body.from_template_id,
            },
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


@router.post("/commands/delete")
async def delete_command(body: CommandDeleteIn, request: Request):
    """Komut silme isteği — zorunlu onay."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        zone = db.query(CentrifyZone).filter_by(id=body.zone_id, deleted_in_ad=False).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone bulunamadı")

        result = create_operation(
            db,
            operation_type="delete_command",
            zone_id=body.zone_id,
            desired_state={"zone_dn": zone.ad_dn, "name": body.command_name},
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


@router.post("/commands/add-to-role")
async def add_command_to_role(body: CommandToRoleIn, request: Request):
    """Komut → role bağla — zorunlu onay."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        zone = db.query(CentrifyZone).filter_by(id=body.zone_id, deleted_in_ad=False).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone bulunamadı")

        result = create_operation(
            db,
            operation_type="add_command_to_role",
            zone_id=body.zone_id,
            desired_state={
                "zone_dn": zone.ad_dn,
                "role_name": body.role_name,
                "command_name": body.command_name,
                "name": f"{body.command_name} → {body.role_name}",
            },
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


@router.post("/commands/remove-from-role")
async def remove_command_from_role(body: CommandToRoleIn, request: Request):
    """Komut → rolden kaldır — zorunlu onay."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone
    from app.services.centrify.provisioning_service import create_operation

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        zone = db.query(CentrifyZone).filter_by(id=body.zone_id, deleted_in_ad=False).first()
        if not zone:
            raise HTTPException(status_code=404, detail="Zone bulunamadı")

        result = create_operation(
            db,
            operation_type="remove_command_from_role",
            zone_id=body.zone_id,
            desired_state={
                "zone_dn": zone.ad_dn,
                "role_name": body.role_name,
                "command_name": body.command_name,
                "name": f"{body.command_name} ✕ {body.role_name}",
            },
            reason=body.reason,
            requested_by=user_id,
            requested_by_name=username,
        )
        return result
    finally:
        db.close()


# ── Komut şablonları ─────────────────────────────────────────


BUILTIN_TEMPLATES = [
    {"name": "Service Restart", "category": "Servis Yönetimi", "command_path": "/usr/bin/systemctl restart *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Systemd servis restart", "risk_level": "medium"},
    {"name": "Service Status", "category": "Servis Yönetimi", "command_path": "/usr/bin/systemctl status *", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Systemd servis durumu", "risk_level": "low"},
    {"name": "Service Stop", "category": "Servis Yönetimi", "command_path": "/usr/bin/systemctl stop *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Systemd servis durdur", "risk_level": "high"},
    {"name": "Log Tail", "category": "Log Görüntüleme", "command_path": "/usr/bin/tail -f /var/log/*", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Log takip (tail)", "risk_level": "low"},
    {"name": "Journal View", "category": "Log Görüntüleme", "command_path": "/usr/bin/journalctl *", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Systemd journal görüntüleme", "risk_level": "low"},
    {"name": "Disk Usage", "category": "Disk", "command_path": "/usr/bin/df *", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Disk kullanımı", "risk_level": "low"},
    {"name": "Process List", "category": "Sistem", "command_path": "/usr/bin/ps *", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Süreç listesi", "risk_level": "low"},
    {"name": "Network Status", "category": "Ağ", "command_path": "/usr/sbin/ss *", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Soket durumu", "risk_level": "low"},
    {"name": "User Add", "category": "Kullanıcı Yönetimi", "command_path": "/usr/sbin/useradd *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Kullanıcı ekleme", "risk_level": "high"},
    {"name": "Password Change", "category": "Kullanıcı Yönetimi", "command_path": "/usr/bin/passwd *", "match_type": "glob", "run_as_user": "root", "auth_type": "mfa", "description": "Parola değiştirme", "risk_level": "critical"},
    {"name": "Mount", "category": "Disk", "command_path": "/usr/bin/mount *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Disk bağlama", "risk_level": "high"},
    {"name": "Cron Edit", "category": "Zamanlama", "command_path": "/usr/bin/crontab *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Cron düzenleme", "risk_level": "medium"},
    {"name": "Package Install", "category": "Paket Yönetimi", "command_path": "/usr/bin/dnf install *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "DNF paket kurulumu", "risk_level": "high"},
    {"name": "Package Update", "category": "Paket Yönetimi", "command_path": "/usr/bin/dnf update *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "DNF paket güncelleme", "risk_level": "medium"},
    {"name": "Firewall Rule", "category": "Güvenlik", "command_path": "/usr/bin/firewall-cmd *", "match_type": "glob", "run_as_user": "root", "auth_type": "mfa", "description": "Firewall kuralı", "risk_level": "critical"},
    {"name": "Docker Container", "category": "Konteyner", "command_path": "/usr/bin/docker *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Docker yönetimi", "risk_level": "high"},
    {"name": "File Read", "category": "Dosya", "command_path": "/usr/bin/cat /etc/*", "match_type": "glob", "run_as_user": "root", "auth_type": "none", "description": "Konfigürasyon dosyası okuma", "risk_level": "low"},
    {"name": "Vi Editor", "category": "Dosya", "command_path": "/usr/bin/vi *", "match_type": "glob", "run_as_user": "root", "auth_type": "password", "description": "Vi metin düzenleyici", "risk_level": "medium"},
]


@router.get("/command-templates")
async def list_command_templates():
    """Komut şablonlarını listele (builtin + custom)."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandTemplate

    db = get_centrify_thread_session()
    if db is None:
        return BUILTIN_TEMPLATES

    try:
        custom = db.query(CentrifyCommandTemplate).filter_by(enabled=True).all()
        result = []
        for t in BUILTIN_TEMPLATES:
            result.append({**t, "is_builtin": True, "id": None, "enabled": True})

        for t in custom:
            result.append({
                "id": t.id, "name": t.name, "category": t.category,
                "command_path": t.command_path, "match_type": t.match_type,
                "run_as_user": t.run_as_user, "run_as_group": t.run_as_group or "",
                "auth_type": t.auth_type, "description": t.description or "",
                "risk_level": t.risk_level, "is_builtin": t.is_builtin or False,
                "enabled": t.enabled,
            })
        return result
    except Exception:
        return [{**t, "is_builtin": True, "id": None, "enabled": True} for t in BUILTIN_TEMPLATES]
    finally:
        db.close()


@router.post("/command-templates")
async def create_command_template(body: TemplateIn, request: Request):
    """Özel komut şablonu oluştur."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandTemplate

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        existing = db.query(CentrifyCommandTemplate).filter_by(name=body.name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"'{body.name}' adında şablon zaten var")

        tpl = CentrifyCommandTemplate(
            name=body.name, category=body.category,
            command_path=body.command_path, match_type=body.match_type,
            run_as_user=body.run_as_user, run_as_group=body.run_as_group,
            auth_type=body.auth_type, description=body.description,
            risk_level=body.risk_level, is_builtin=False,
            created_by=username,
        )
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
        return {"id": tpl.id, "name": tpl.name, "message": "Şablon oluşturuldu"}
    finally:
        db.close()


@router.delete("/command-templates/{template_id}")
async def delete_command_template(template_id: int):
    """Özel şablon sil (builtin silinemez)."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandTemplate

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        tpl = db.query(CentrifyCommandTemplate).filter_by(id=template_id).first()
        if not tpl:
            raise HTTPException(status_code=404, detail="Şablon bulunamadı")
        if tpl.is_builtin:
            raise HTTPException(status_code=403, detail="Yerleşik şablonlar silinemez")
        db.delete(tpl)
        db.commit()
        return {"ok": True, "message": "Şablon silindi"}
    finally:
        db.close()


# ── Beyaz liste ──────────────────────────────────────────────


@router.get("/command-whitelist")
async def list_command_whitelist():
    """Komut beyaz listesi."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandWhitelist

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = db.query(CentrifyCommandWhitelist).order_by(CentrifyCommandWhitelist.category).all()
        return [
            {
                "id": w.id, "pattern": w.pattern, "pattern_type": w.pattern_type,
                "description": w.description, "category": w.category,
                "risk_level": w.risk_level, "max_run_as": w.max_run_as,
                "requires_auth": w.requires_auth, "enabled": w.enabled,
            }
            for w in items
        ]
    except Exception:
        return []
    finally:
        db.close()


@router.post("/command-whitelist")
async def add_whitelist_entry(body: WhitelistIn, request: Request):
    """Beyaz listeye yeni kalıp ekle."""
    user_id, username = _extract_user(request)

    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandWhitelist

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        existing = db.query(CentrifyCommandWhitelist).filter_by(pattern=body.pattern).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Bu kalıp zaten beyaz listede: {body.pattern}")

        entry = CentrifyCommandWhitelist(
            pattern=body.pattern, pattern_type=body.pattern_type,
            description=body.description, category=body.category,
            risk_level=body.risk_level, max_run_as=body.max_run_as,
            requires_auth=body.requires_auth, created_by=username,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return {"id": entry.id, "pattern": entry.pattern, "message": "Beyaz listeye eklendi"}
    finally:
        db.close()


@router.delete("/command-whitelist/{entry_id}")
async def delete_whitelist_entry(entry_id: int):
    """Beyaz listeden kalıp kaldır."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyCommandWhitelist

    db = get_centrify_thread_session()
    if db is None:
        raise HTTPException(status_code=503, detail="Centrify DB erişilemiyor")
    try:
        entry = db.query(CentrifyCommandWhitelist).filter_by(id=entry_id).first()
        if not entry:
            raise HTTPException(status_code=404, detail="Beyaz liste kaydı bulunamadı")
        db.delete(entry)
        db.commit()
        return {"ok": True, "message": "Beyaz listeden kaldırıldı"}
    finally:
        db.close()


@router.post("/command-whitelist/validate")
async def validate_command_path(body: dict):
    """Komut path'inin beyaz listeyle eşleşip eşleşmediğini kontrol et."""
    path = body.get("command_path", "")
    if not path:
        raise HTTPException(status_code=400, detail="command_path gerekli")

    from app.services.centrify.database import get_centrify_thread_session
    db = get_centrify_thread_session()
    if db is None:
        return {"allowed": True, "reason": "Beyaz liste kontrolü yapılamadı"}
    try:
        allowed, msg = _validate_whitelist(db, path)
        return {"allowed": allowed, "reason": msg if not allowed else "Eşleşme bulundu"}
    finally:
        db.close()


# ── Health / Monitoring ───────────────────────────────────────


@router.get("/health")
async def centrify_health():
    """Centrify modülü sağlık kontrolü — monitoring ve alert için."""
    from app.services.centrify.database import get_centrify_thread_session, centrify_db_available
    from app.services.centrify.circuit_breaker import get_circuit_status

    result = {
        "module": "centrify",
        "status": "healthy",
        "checks": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 1. DB kontrolü
    db_ok = centrify_db_available()
    result["checks"]["database"] = {"ok": db_ok, "detail": "Centrify DB (:5434) erişilebilir" if db_ok else "Centrify DB erişilemiyor"}
    if not db_ok:
        result["status"] = "degraded"

    # 2. Circuit breaker
    cb = get_circuit_status()
    result["checks"]["circuit_breaker"] = {
        "ok": not cb.get("open", False),
        "open": cb.get("open", False),
        "fail_count": cb.get("fail_count", 0),
        "ttl_seconds": cb.get("ttl_seconds"),
    }
    if cb.get("open"):
        result["status"] = "critical"

    # 3. Config var mı
    if db_ok:
        db = get_centrify_thread_session()
        if db:
            try:
                from app.models.centrify_zone import CentrifyIntegrationConfig, CentrifyZone, CentrifyOperation
                cfg = db.query(CentrifyIntegrationConfig).filter_by(enabled=True).first()
                result["checks"]["config"] = {"ok": cfg is not None, "detail": f"WinRM: {cfg.winrm_host}:{cfg.winrm_port}" if cfg else "Yapılandırma yok"}

                # 4. Zone sayısı
                zone_count = db.query(CentrifyZone).filter_by(deleted_in_ad=False).count()
                result["checks"]["zones"] = {"ok": zone_count > 0, "count": zone_count}

                # 5. Senkronizasyon yaşı
                from sqlalchemy import func as sqlfunc
                last_sync = db.query(sqlfunc.max(CentrifyZone.last_synced_at)).scalar()
                if last_sync:
                    age_minutes = (datetime.now(timezone.utc) - last_sync.replace(tzinfo=timezone.utc)).total_seconds() / 60
                    sync_ok = age_minutes < 60
                    result["checks"]["sync_age"] = {"ok": sync_ok, "minutes_ago": round(age_minutes, 1), "detail": "Senkronizasyon güncel" if sync_ok else "Senkronizasyon 1 saatten eski"}
                    if not sync_ok and result["status"] == "healthy":
                        result["status"] = "warning"
                else:
                    result["checks"]["sync_age"] = {"ok": False, "detail": "Henüz senkronizasyon yapılmamış"}

                # 6. Bekleyen operasyonlar
                pending = db.query(CentrifyOperation).filter(CentrifyOperation.status.in_(["pending_approval"])).count()
                failed = db.query(CentrifyOperation).filter_by(status="failed").count()
                result["checks"]["operations"] = {"pending_approval": pending, "failed": failed, "alert": failed > 0}
                if failed > 5 and result["status"] == "healthy":
                    result["status"] = "warning"
            finally:
                db.close()

    return result


@router.get("/metrics")
async def centrify_metrics():
    """Prometheus text format metrikleri."""
    from app.services.centrify.database import get_centrify_thread_session, centrify_db_available
    from app.services.centrify.circuit_breaker import get_circuit_status

    lines = ["# HELP centrify_up Centrify modülü çalışıyor mu", "# TYPE centrify_up gauge"]

    db_ok = centrify_db_available()
    lines.append(f'centrify_up{{component="database"}} {1 if db_ok else 0}')

    cb = get_circuit_status()
    lines.append(f'centrify_circuit_open {1 if cb.get("open") else 0}')
    lines.append(f'centrify_auth_fail_count {cb.get("fail_count", 0)}')

    if db_ok:
        db = get_centrify_thread_session()
        if db:
            try:
                from app.models.centrify_zone import CentrifyZone, CentrifyRole, CentrifyCommand, CentrifyOperation
                lines.append(f'centrify_zone_count {db.query(CentrifyZone).filter_by(deleted_in_ad=False).count()}')
                lines.append(f'centrify_role_count {db.query(CentrifyRole).filter_by(deleted_in_ad=False).count()}')
                lines.append(f'centrify_command_count {db.query(CentrifyCommand).filter_by(deleted_in_ad=False).count()}')
                lines.append(f'centrify_operations_pending {db.query(CentrifyOperation).filter_by(status="pending_approval").count()}')
                lines.append(f'centrify_operations_failed {db.query(CentrifyOperation).filter_by(status="failed").count()}')
                lines.append(f'centrify_operations_completed {db.query(CentrifyOperation).filter_by(status="completed").count()}')
            finally:
                db.close()

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


# ── Global arama ─────────────────────────────────────────────


@router.get("/search")
async def global_search(q: str = "", limit: int = 50):
    """Tüm zone'larda sunucu, kullanıcı ve zone arama."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyZone, CentrifyComputer, CentrifyUnixProfile

    if not q or len(q) < 2:
        return {"computers": [], "users": [], "zones": []}

    db = get_centrify_thread_session()
    if db is None:
        return {"computers": [], "users": [], "zones": []}

    pattern = f"%{q}%"
    try:
        # Zone'ları ara
        zones = (
            db.query(CentrifyZone)
            .filter(CentrifyZone.deleted_in_ad.is_(False), CentrifyZone.name.ilike(pattern))
            .limit(limit)
            .all()
        )

        # Bilgisayarları ara (isim veya FQDN)
        computers = (
            db.query(CentrifyComputer)
            .filter(
                CentrifyComputer.deleted_in_ad.is_(False),
                (CentrifyComputer.name.ilike(pattern) | CentrifyComputer.fqdn.ilike(pattern)),
            )
            .limit(limit)
            .all()
        )

        # Kullanıcıları ara
        users = (
            db.query(CentrifyUnixProfile)
            .filter(CentrifyUnixProfile.user_name.ilike(pattern))
            .limit(limit)
            .all()
        )

        # Zone id → zone bilgisi haritası (yol hesabı için)
        zone_map: dict[int, dict] = {}
        all_zones = db.query(CentrifyZone).filter_by(deleted_in_ad=False).all()
        for z in all_zones:
            zone_map[z.id] = {"id": z.id, "name": z.name, "parent_zone_id": z.parent_zone_id}

        def _zone_path(zone_id: int) -> str:
            parts: list[str] = []
            cur = zone_id
            seen: set[int] = set()
            while cur and cur not in seen:
                seen.add(cur)
                zi = zone_map.get(cur)
                if not zi:
                    break
                parts.append(zi["name"])
                cur = zi["parent_zone_id"]
            parts.reverse()
            return " → ".join(parts)

        return {
            "zones": [
                {"id": z.id, "name": z.name, "zone_type": z.zone_type, "path": _zone_path(z.id)}
                for z in zones
            ],
            "computers": [
                {
                    "id": c.id, "name": c.name, "fqdn": c.fqdn,
                    "os_type": c.os_type, "agent_version": c.agent_version,
                    "zone_id": c.zone_id, "zone_path": _zone_path(c.zone_id),
                }
                for c in computers
            ],
            "users": [
                {
                    "id": p.id, "user_name": p.user_name, "uid": p.uid,
                    "home_dir": p.home_dir, "shell": p.shell,
                    "zone_id": p.zone_id, "zone_path": _zone_path(p.zone_id),
                }
                for p in users
            ],
        }
    except Exception:
        return {"computers": [], "users": [], "zones": []}
    finally:
        db.close()


# ── Demo seed ─────────────────────────────────────────────────


@router.post("/demo/seed")
async def seed_demo_data():
    """Demo verisi oluştur — gerçekçi zone/role/command/assignment/audit."""
    from app.services.centrify.demo_seed import seed_demo_data as do_seed
    return do_seed()


@router.delete("/demo/seed")
async def clear_demo_data():
    """Demo verisini temizle."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import (
        CentrifyDriftEvent, CentrifyAuditLog, CentrifyOperation,
        CentrifyComputerRoleMember, CentrifyComputerRole,
        CentrifyRoleCommand, CentrifyRoleAssignment,
        CentrifyUnixProfile, CentrifyComputer,
        CentrifyCommand, CentrifyRole, CentrifyZone,
    )
    db = get_centrify_thread_session()
    if db is None:
        return {"ok": False, "error": "Centrify DB erişilemiyor"}
    try:
        for model in [CentrifyDriftEvent, CentrifyAuditLog, CentrifyOperation,
                      CentrifyComputerRoleMember, CentrifyComputerRole,
                      CentrifyRoleCommand, CentrifyRoleAssignment,
                      CentrifyUnixProfile, CentrifyComputer,
                      CentrifyCommand, CentrifyRole, CentrifyZone]:
            db.query(model).delete()
        db.commit()
        return {"ok": True, "message": "Tüm demo verisi silindi"}
    except Exception as exc:
        db.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


# ── Audit log ────────────────────────────────────────────────


@router.get("/audit")
async def list_audit_log(limit: int = 100, offset: int = 0):
    """Audit log listesi."""
    from app.services.centrify.database import get_centrify_thread_session
    from app.models.centrify_zone import CentrifyAuditLog

    db = get_centrify_thread_session()
    if db is None:
        return []
    try:
        items = (
            db.query(CentrifyAuditLog)
            .order_by(CentrifyAuditLog.created_at.desc())
            .offset(offset).limit(limit).all()
        )
        return [
            {
                "id": a.id,
                "correlation_id": str(a.correlation_id),
                "operation_id": a.operation_id,
                "actor_username": a.actor_username,
                "target_type": a.target_type,
                "target_name": a.target_name,
                "action": a.action,
                "reason": a.reason,
                "result": a.result,
                "approved_by_name": a.approved_by_name,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in items
        ]
    except Exception:
        return []
    finally:
        db.close()
