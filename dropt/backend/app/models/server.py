from datetime import UTC, datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class ServerStatus(str, Enum):
    unknown = "unknown"
    ready = "ready"
    unreachable = "unreachable"
    disabled = "disabled"


class Credential(SQLModel, table=True):
    __tablename__ = "credentials"

    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(default="default", max_length=128)
    ssh_username: str = Field(default="dtt-automation", max_length=128)
    encrypted_ssh_password: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TargetServer(SQLModel, table=True):
    __tablename__ = "target_servers"

    id: Optional[int] = Field(default=None, primary_key=True)
    hostname: str = Field(index=True, max_length=255)
    ip: str = Field(index=True, max_length=64)
    port: int = Field(default=22, ge=1, le=65535)
    status: ServerStatus = Field(default=ServerStatus.unknown, index=True)
    tags: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=512)
    last_connection_message: str = Field(default="", max_length=1024)
    ssh_key_installed: bool = Field(default=False)
    os_pretty: str = Field(default="", max_length=255)
    machine_type: str = Field(default="", max_length=32)  # physical | virtual
    virtualization: str = Field(default="", max_length=64)
    credentials_id: Optional[int] = Field(default=None, foreign_key="credentials.id", index=True)
    # ainew Server.ai_ready senkronu — False ise Level 1 işleri force olmadan engellenir
    ainew_ai_ready: Optional[bool] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
