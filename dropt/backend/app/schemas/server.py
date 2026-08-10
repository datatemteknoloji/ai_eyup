from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.server import ServerStatus


class ServerCreate(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    ip: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=512)
    port: int = Field(default=22, ge=1, le=65535)
    tags: str = Field(default="", max_length=512)
    description: str = Field(default="", max_length=512)

    @field_validator("hostname", "ip", "tags", "description")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class ServerUpdate(BaseModel):
    hostname: Optional[str] = Field(default=None, min_length=1, max_length=255)
    ip: Optional[str] = Field(default=None, min_length=3, max_length=64)
    password: Optional[str] = Field(default=None, min_length=1, max_length=512)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    status: Optional[ServerStatus] = None
    tags: Optional[str] = Field(default=None, max_length=512)
    description: Optional[str] = Field(default=None, max_length=512)
    test_connection: bool = True

    @field_validator("hostname", "ip", "tags", "description")
    @classmethod
    def strip_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return v.strip()


class ServerPublic(BaseModel):
    id: int
    hostname: str
    ip: str
    port: int
    status: ServerStatus
    tags: str
    description: str
    username: str
    has_password: bool
    ssh_key_installed: bool
    os_pretty: str = ""
    machine_type: str = ""
    virtualization: str = ""
    last_connection_message: str
    connection_ok: Optional[bool] = None
    ainew_ai_ready: Optional[bool] = None
    created_at: datetime
    updated_at: datetime


class ServerListResponse(BaseModel):
    items: list[ServerPublic]
    total: int
    page: int
    page_size: int


class ServerImportRowResult(BaseModel):
    hostname: str
    ip: str
    status: str
    message: str = ""
    server_id: int | None = None


class ServerImportParseResponse(BaseModel):
    rows: list[dict[str, str]]
    total: int


class ServerImportRowRequest(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    ip: str = Field(min_length=3, max_length=64)

    @field_validator("hostname", "ip")
    @classmethod
    def strip_row(cls, v: str) -> str:
        return v.strip()


class ServerImportResponse(BaseModel):
    ok: bool
    total_rows: int
    created: int
    ready: int
    unreachable: int
    skipped: int
    items: list[ServerImportRowResult]
