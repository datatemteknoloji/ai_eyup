"""Privilege escalation for non-root automation users.

Global setting automation_user_kind:
  root  → no prefix
  local → sudo -n
  ad    → dzdo -n
"""

from __future__ import annotations

import shlex

from sqlmodel import Session

from app.models.settings import AUTOMATION_USER_KIND_KEY, AppSetting
from app.services.bootstrap import get_automation_username

AutomationUserKind = str  # "root" | "local" | "ad"

VALID_KINDS = frozenset({"root", "local", "ad"})
DEFAULT_KIND = "root"


def normalize_kind(raw: str | None, *, username: str | None = None) -> AutomationUserKind:
    kind = (raw or "").strip().lower()
    user = (username or "").strip()
    if user == "root" or user.lower() == "root":
        return "root"
    if kind in VALID_KINDS:
        if kind != "root" and user == "root":
            return "root"
        return kind
    if user and user != "root":
        # Legacy: username set but kind missing → treat as local (sudo)
        return "local"
    return DEFAULT_KIND


def get_automation_user_kind(session: Session) -> AutomationUserKind:
    row = session.get(AppSetting, AUTOMATION_USER_KIND_KEY)
    username = get_automation_username(session)
    return normalize_kind(row.value if row else None, username=username)


def set_automation_user_kind(session: Session, kind: str, *, username: str | None = None) -> AutomationUserKind:
    user = username if username is not None else get_automation_username(session)
    cleaned = normalize_kind(kind, username=user)
    if cleaned not in VALID_KINDS:
        raise ValueError("Geçersiz otomasyon kullanıcı tipi (root|local|ad)")
    row = session.get(AppSetting, AUTOMATION_USER_KIND_KEY)
    if row is None:
        row = AppSetting(key=AUTOMATION_USER_KIND_KEY, value=cleaned)
    else:
        row.value = cleaned
    session.add(row)
    session.commit()
    session.refresh(row)
    return cleaned


def escalation_prefix(kind: AutomationUserKind) -> str | None:
    if kind == "local":
        return "sudo -n"
    if kind == "ad":
        return "dzdo -n"
    return None


def elevate_command(session: Session, command: str) -> str:
    """Wrap a remote command for privilege escalation when needed."""
    raw = command if command is not None else ""
    cmd = raw.strip()
    if not cmd or cmd.startswith("#"):
        return raw

    kind = get_automation_user_kind(session)
    prefix = escalation_prefix(kind)
    if not prefix:
        return raw

    # Avoid double-wrap
    if cmd.startswith("sudo ") or cmd.startswith("dzdo "):
        return raw

    return f"{prefix} -- bash -lc {shlex.quote(cmd)}"


def elevate_commands(session: Session, commands: list[str] | None) -> list[str]:
    if not commands:
        return []
    return [elevate_command(session, c) for c in commands]
