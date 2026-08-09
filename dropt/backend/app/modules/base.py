from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlmodel import Session

from app.models.server import TargetServer


@dataclass
class HostPlan:
    server_id: int
    hostname: str
    ip: str
    ok: bool
    summary_tr: str
    planned_commands: list[str] = field(default_factory=list)
    before_state: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    risk_notes: str = ""


class JobModule(Protocol):
    ACTION_TITLES: dict[str, str]

    def build_plans(
        self, session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]
    ) -> list[HostPlan]: ...

    def apply_plan(
        self,
        session: Session,
        server: TargetServer,
        action: str,
        payload: dict[str, Any],
        plan: HostPlan,
        *,
        job_id: int,
    ) -> tuple[bool, dict[str, Any], str, str]: ...

    def job_summary(self, action: str, payload: dict[str, Any]) -> str: ...
