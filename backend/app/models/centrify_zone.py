"""Centrify Zone Management ORM modelleri.

Bu modeller ayrı Centrify DB'de (:5434) yaşar — ainew ana DB'yle karıştırılmaz.
CentrifyBase kullanır; ainew Base'den ayrı.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import relationship

from app.services.centrify.database import CentrifyBase


class CentrifyZone(CentrifyBase):
    """Zone ağaç yapısı."""
    __tablename__ = "centrify_zones"

    id = Column(Integer, primary_key=True)
    ad_guid = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    ad_dn = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    zone_type = Column(String(50), nullable=False)  # hierarchical | classic
    parent_zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=True)
    description = Column(Text)
    management_state = Column(String(50), nullable=False, default="imported_readonly")
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    children = relationship("CentrifyZone", backref="parent", remote_side=[id], lazy="select")
    roles = relationship("CentrifyRole", back_populates="zone", lazy="select")
    commands = relationship("CentrifyCommand", back_populates="zone", lazy="select")
    computers = relationship("CentrifyComputer", back_populates="zone", lazy="select")
    computer_roles = relationship("CentrifyComputerRole", back_populates="zone", lazy="select")
    role_assignments = relationship("CentrifyRoleAssignment", back_populates="zone", lazy="select")
    unix_profiles = relationship("CentrifyUnixProfile", back_populates="zone", lazy="select")


class CentrifyComputer(CentrifyBase):
    """Zone üyesi sunucu."""
    __tablename__ = "centrify_computers"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    ad_guid = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    ad_dn = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    fqdn = Column(Text)
    os_type = Column(String(50))
    agent_version = Column(Text)
    ainew_server_id = Column(Integer)  # soft ref — FK yok
    management_state = Column(String(50), nullable=False, default="imported_readonly")
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="computers")


class CentrifyRole(CentrifyBase):
    """Zone role tanımı."""
    __tablename__ = "centrify_roles"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    ad_guid = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    ad_dn = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    is_system_role = Column(Boolean, default=False)
    management_state = Column(String(50), nullable=False, default="imported_readonly")

    # ── General tab alanları ──────────────────────────────────
    allow_local_accounts = Column(Boolean, default=False)
    available_times = Column(JSONB)  # zaman kısıtlamaları

    # ── System Rights tab alanları ────────────────────────────
    # UNIX rights
    password_login_allowed = Column(Boolean, default=False)
    sso_login_allowed = Column(Boolean, default=False)
    ad_disabled_sudo_cron = Column(Boolean, default=False)
    non_restricted_shell = Column(Boolean, default=False)
    user_visible = Column(Boolean, default=True)
    # Windows rights
    console_login_allowed = Column(Boolean, default=False)
    remote_login_allowed = Column(Boolean, default=False)
    powershell_remote_allowed = Column(Boolean, default=False)
    # Rescue rights
    rescue_login_allowed = Column(Boolean, default=False)

    # ── Authentication tab ────────────────────────────────────
    require_mfa = Column(Boolean, default=False)

    # ── Audit tab ─────────────────────────────────────────────
    audit_level = Column(String(30), default="if_possible")  # none | if_possible | required

    # ── Custom Attributes tab ─────────────────────────────────
    custom_attributes = Column(JSONB)  # [{name, value}, ...]

    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="roles")
    role_commands = relationship("CentrifyRoleCommand", back_populates="role", lazy="select")
    assignments = relationship("CentrifyRoleAssignment", back_populates="role", lazy="select")


class CentrifyCommand(CentrifyBase):
    """Komut/Right tanımı."""
    __tablename__ = "centrify_commands"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    ad_guid = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    ad_dn = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    command_path = Column(Text)
    match_type = Column(String(50))  # exact | glob | regex
    run_as_user = Column(Text, default="root")
    run_as_group = Column(Text)
    auth_type = Column(String(50), default="password")  # password | none | mfa
    description = Column(Text)
    management_state = Column(String(50), nullable=False, default="imported_readonly")
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="commands")
    role_commands = relationship("CentrifyRoleCommand", back_populates="command", lazy="select")


class CentrifyRoleCommand(CentrifyBase):
    """Role ↔ Command ilişki tablosu."""
    __tablename__ = "centrify_role_commands"

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("centrify_roles.id"), nullable=False)
    command_id = Column(Integer, ForeignKey("centrify_commands.id"), nullable=False)

    __table_args__ = (UniqueConstraint("role_id", "command_id"),)

    role = relationship("CentrifyRole", back_populates="role_commands")
    command = relationship("CentrifyCommand", back_populates="role_commands")


class CentrifyComputerRole(CentrifyBase):
    """Computer Role tanımı."""
    __tablename__ = "centrify_computer_roles"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    ad_guid = Column(PG_UUID(as_uuid=True), nullable=False, unique=True)
    ad_dn = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    management_state = Column(String(50), nullable=False, default="imported_readonly")
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="computer_roles")
    members = relationship("CentrifyComputerRoleMember", back_populates="computer_role", lazy="select")


class CentrifyComputerRoleMember(CentrifyBase):
    """Computer ↔ Computer Role ilişki tablosu."""
    __tablename__ = "centrify_computer_role_members"

    id = Column(Integer, primary_key=True)
    computer_id = Column(Integer, ForeignKey("centrify_computers.id"), nullable=False)
    computer_role_id = Column(Integer, ForeignKey("centrify_computer_roles.id"), nullable=False)

    __table_args__ = (UniqueConstraint("computer_id", "computer_role_id"),)

    computer = relationship("CentrifyComputer")
    computer_role = relationship("CentrifyComputerRole", back_populates="members")


class CentrifyRoleAssignment(CentrifyBase):
    """Role Assignment — kullanıcı/grup → role ataması.

    scope_type='zone' → tüm zone genelinde (computer_id=NULL)
    scope_type='computer' → sadece belirli computer (computer_id dolu)
    """
    __tablename__ = "centrify_role_assignments"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    computer_id = Column(Integer, ForeignKey("centrify_computers.id"), nullable=True)
    ad_guid = Column(PG_UUID(as_uuid=True))
    ad_dn = Column(Text)
    role_id = Column(Integer, ForeignKey("centrify_roles.id"), nullable=False)
    assignee_type = Column(String(50), nullable=False)  # user | group | computer_role
    assignee_dn = Column(Text, nullable=False)
    assignee_name = Column(Text, nullable=False)
    scope_type = Column(String(50), nullable=False, default="zone")  # zone | computer
    scope_dn = Column(Text)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    management_state = Column(String(50), nullable=False, default="imported_readonly")
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    last_seen_in_ad = Column(DateTime(timezone=True))
    deleted_in_ad = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="role_assignments")
    role = relationship("CentrifyRole", back_populates="assignments")
    computer = relationship("CentrifyComputer")


class CentrifyUnixProfile(CentrifyBase):
    """UNIX profil verisi."""
    __tablename__ = "centrify_unix_profiles"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    user_dn = Column(Text, nullable=False)
    user_name = Column(Text, nullable=False)
    uid = Column(Integer)
    gid = Column(Integer)
    home_dir = Column(Text)
    shell = Column(Text)
    gecos = Column(Text)
    enabled = Column(Boolean, default=True)
    source_hash = Column(Text)
    last_synced_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone = relationship("CentrifyZone", back_populates="unix_profiles")


# ── Operasyonel tablolar ──────────────────────────────────────────

class CentrifyOperation(CentrifyBase):
    """Yazma istekleri kuyruğu (outbox + saga)."""
    __tablename__ = "centrify_operations"

    id = Column(Integer, primary_key=True)
    correlation_id = Column(PG_UUID(as_uuid=True), nullable=False)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"))
    operation_type = Column(Text, nullable=False)
    desired_state = Column(JSONB, nullable=False)
    observed_state = Column(JSONB)
    status = Column(String(50), nullable=False, default="requested")
    status_history = Column(JSONB, default=[])
    saga_id = Column(PG_UUID(as_uuid=True))
    saga_step = Column(Integer, default=0)
    saga_total = Column(Integer, default=1)
    requested_by = Column(Integer, nullable=False)
    requested_by_name = Column(Text, nullable=False)
    approved_by = Column(Integer)
    approved_by_name = Column(Text)
    reason = Column(Text, nullable=False)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CentrifyAuditLog(CentrifyBase):
    """Append-only audit log — UPDATE/DELETE yasak."""
    __tablename__ = "centrify_audit_log"

    id = Column(Integer, primary_key=True)
    correlation_id = Column(PG_UUID(as_uuid=True), nullable=False)
    operation_id = Column(Integer, ForeignKey("centrify_operations.id"))
    actor_user_id = Column(Integer, nullable=False)
    actor_username = Column(Text, nullable=False)
    target_type = Column(Text, nullable=False)
    target_ad_guid = Column(PG_UUID(as_uuid=True))
    target_name = Column(Text)
    action = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    details = Column(JSONB)
    approved_by_id = Column(Integer)
    approved_by_name = Column(Text)
    result = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CentrifyDriftEvent(CentrifyBase):
    """Drift tespit kayıtları."""
    __tablename__ = "centrify_drift_events"

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, ForeignKey("centrify_zones.id"), nullable=False)
    object_type = Column(Text, nullable=False)
    object_ad_guid = Column(PG_UUID(as_uuid=True), nullable=False)
    object_name = Column(Text, nullable=False)
    expected_hash = Column(Text)
    actual_hash = Column(Text)
    drift_details = Column(JSONB)
    resolved = Column(Boolean, default=False)
    resolved_by = Column(Integer)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))


class CentrifyCommandTemplate(CentrifyBase):
    """Öntanımlı komut şablonları — sık kullanılan komut kalıpları."""
    __tablename__ = "centrify_command_templates"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    category = Column(String(100), nullable=False, default="Genel")
    command_path = Column(Text, nullable=False)
    match_type = Column(String(50), nullable=False, default="glob")
    run_as_user = Column(Text, default="root")
    run_as_group = Column(Text, default="")
    auth_type = Column(String(50), default="password")
    description = Column(Text)
    risk_level = Column(String(20), nullable=False, default="medium")  # low | medium | high | critical
    is_builtin = Column(Boolean, default=False)
    enabled = Column(Boolean, default=True)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CentrifyCommandWhitelist(CentrifyBase):
    """Komut path beyaz listesi — yalnızca eşleşen path'ler oluşturulabilir."""
    __tablename__ = "centrify_command_whitelist"

    id = Column(Integer, primary_key=True)
    pattern = Column(Text, nullable=False, unique=True)
    pattern_type = Column(String(20), nullable=False, default="glob")  # glob | regex | prefix
    description = Column(Text)
    category = Column(String(100), default="Genel")
    risk_level = Column(String(20), nullable=False, default="medium")
    max_run_as = Column(Text, default="root")
    requires_auth = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CentrifyIntegrationConfig(CentrifyBase):
    """Centrify entegrasyon ayarları."""
    __tablename__ = "centrify_integration_config"

    id = Column(Integer, primary_key=True)
    label = Column(Text, nullable=False, default="Varsayılan")
    winrm_host = Column(Text, nullable=False)
    winrm_port = Column(Integer, default=5985)
    winrm_https = Column(Boolean, default=False)
    service_account = Column(Text, nullable=False)
    password_enc = Column(Text, nullable=False)
    sync_interval_minutes = Column(Integer, default=30)
    sync_enabled = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
