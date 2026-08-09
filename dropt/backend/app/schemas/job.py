from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.job import AuditStatus, JobRunStatus, JobStatus


class JobCreate(BaseModel):
    module: str = Field(default="local_user")
    action: str
    talep_id: str = Field(min_length=1, max_length=255)
    server_ids: list[int] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class JobRunPublic(BaseModel):
    id: int
    job_id: int
    target_server_id: int
    hostname: str
    ip: str
    status: JobRunStatus
    dry_run: bool
    summary_tr: str
    planned_commands: list[str]
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    stdout: str
    stderr: str
    error_message: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class PreviewPublic(BaseModel):
    id: int
    job_id: int
    summary_tr: str
    risk_notes: str
    planned_commands: list[str]
    host_summaries: list[dict[str, Any]]
    technical_detail: str
    created_at: datetime


class JobPublic(BaseModel):
    id: int
    module: str
    action: str
    status: JobStatus
    talep_id: str
    title: str
    summary_tr: str
    created_by_username: str
    created_by_role: str
    server_ids: list[int]
    hostnames: list[str] = Field(default_factory=list)
    payload: dict[str, Any]
    dry_run: bool
    progress_done: int
    progress_total: int
    error_message: str
    created_at: datetime
    updated_at: datetime
    previewed_at: Optional[datetime]
    applied_at: Optional[datetime]
    finished_at: Optional[datetime]
    preview: Optional[PreviewPublic] = None
    runs: list[JobRunPublic] = Field(default_factory=list)


class JobListResponse(BaseModel):
    items: list[JobPublic]
    total: int
    page: int
    page_size: int


class AuditPublic(BaseModel):
    id: int
    user_id: Optional[int]
    username: str
    role: str
    client_ip: str
    target_server_id: Optional[int]
    hostname: str
    ip: str
    talep_id: str
    job_id: Optional[int]
    action: str
    status: AuditStatus
    message: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    output: str
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditPublic]
    total: int
    page: int
    page_size: int


class LocalUserPublic(BaseModel):
    username: str
    uid: Optional[int] = None
    home: str = ""
    shell: str = ""
    groups: list[str] = Field(default_factory=list)
    status: str = "unknown"
    protected: bool = False
