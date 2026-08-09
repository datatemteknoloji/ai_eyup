from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, SQLModel


class JobStatus(str, Enum):
    draft = "draft"
    previewed = "previewed"
    approved = "approved"
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"
    cancelled = "cancelled"


class JobRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class AuditStatus(str, Enum):
    success = "success"
    failed = "failed"
    info = "info"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    module: str = Field(index=True, max_length=64)
    action: str = Field(index=True, max_length=64)
    status: JobStatus = Field(default=JobStatus.draft, index=True)
    talep_id: str = Field(max_length=255, index=True)
    title: str = Field(default="", max_length=255)
    summary_tr: str = Field(default="", max_length=1024)
    created_by_user_id: int = Field(index=True, foreign_key="users.id")
    created_by_username: str = Field(max_length=128)
    created_by_role: str = Field(max_length=32)
    client_ip: str = Field(default="", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    server_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    dry_run: bool = Field(default=True)
    progress_done: int = Field(default=0)
    progress_total: int = Field(default=0)
    celery_task_id: Optional[str] = Field(default=None, max_length=128)
    error_message: str = Field(default="", max_length=1024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previewed_at: Optional[datetime] = Field(default=None)
    applied_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)


class JobRun(SQLModel, table=True):
    __tablename__ = "job_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(index=True, foreign_key="jobs.id")
    target_server_id: int = Field(index=True, foreign_key="target_servers.id")
    hostname: str = Field(default="", max_length=255)
    ip: str = Field(default="", max_length=64)
    status: JobRunStatus = Field(default=JobRunStatus.pending, index=True)
    dry_run: bool = Field(default=True)
    summary_tr: str = Field(default="", max_length=1024)
    planned_commands: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    before_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    stdout: str = Field(default="", sa_column=Column(Text))
    stderr: str = Field(default="", sa_column=Column(Text))
    error_message: str = Field(default="", max_length=1024)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreviewArtifact(SQLModel, table=True):
    __tablename__ = "preview_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(index=True, foreign_key="jobs.id", unique=True)
    summary_tr: str = Field(default="", sa_column=Column(Text))
    risk_notes: str = Field(default="", sa_column=Column(Text))
    planned_commands: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    host_summaries: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    technical_detail: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditLog(SQLModel, table=True):
    """Immutable audit trail — no UPDATE/DELETE via API."""

    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    username: str = Field(default="", max_length=128, index=True)
    role: str = Field(default="", max_length=32)
    client_ip: str = Field(default="", max_length=64)
    target_server_id: Optional[int] = Field(default=None, index=True)
    hostname: str = Field(default="", max_length=255)
    ip: str = Field(default="", max_length=64)
    talep_id: str = Field(default="", max_length=255, index=True)
    job_id: Optional[int] = Field(default=None, index=True)
    action: str = Field(max_length=128, index=True)
    status: AuditStatus = Field(default=AuditStatus.info, index=True)
    message: str = Field(default="", sa_column=Column(Text))
    before_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after_state: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output: str = Field(default="", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
