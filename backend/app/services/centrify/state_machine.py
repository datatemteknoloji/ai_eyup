"""Centrify operasyon durum makinesi.

Her yazma isteği tek durum makinesinden geçer:
  requested → pending_approval → approved → provisioning
    → written_to_ad → verified → completed

Hata dalları: failed | ambiguous | cancelled | rolled_back
Geçersiz geçişler reddedilir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Geçerli durum geçişleri ───────────────────────────────────

VALID_TRANSITIONS: dict[str, list[str]] = {
    "requested":        ["pending_approval", "cancelled"],
    "pending_approval": ["approved", "cancelled"],
    "approved":         ["provisioning", "cancelled", "completed", "failed"],
    "provisioning":     ["written_to_ad", "failed", "ambiguous"],
    "written_to_ad":    ["verified", "failed", "ambiguous"],
    "verified":         ["completed", "failed"],
    "failed":           ["requested"],       # retry → requested'a geri
    "ambiguous":        ["requested", "completed", "failed"],
    "cancelled":        [],                  # terminal
    "completed":        [],                  # terminal
    "rolled_back":      [],                  # terminal
}

TERMINAL_STATES = {"completed", "cancelled", "rolled_back"}

# Onay gerektiren operasyon tipleri
APPROVAL_REQUIRED_OPS = {
    "create_role", "delete_role", "update_role",
    "create_command", "delete_command", "update_command",
    "create_role_assignment", "delete_role_assignment",
    "clone_role", "overwrite_role",
    "add_command_to_role", "remove_command_from_role",
    "add_user_to_group", "remove_user_from_group",
    "create_computer_role", "delete_computer_role",
}


def can_transition(current: str, target: str) -> bool:
    """Bu geçiş geçerli mi?"""
    allowed = VALID_TRANSITIONS.get(current, [])
    return target in allowed


def transition(operation, target: str, *, actor_id: int | None = None,
               error_message: str | None = None) -> bool:
    """Operasyonun durumunu değiştir. False = geçersiz geçiş.

    operation: CentrifyOperation ORM instance'ı (session'a bağlı olmalı).
    """
    current = operation.status
    if not can_transition(current, target):
        logger.warning(
            "Geçersiz durum geçişi: %s → %s (op #%s, tip: %s)",
            current, target, operation.id, operation.operation_type,
        )
        return False

    now = datetime.now(timezone.utc)
    history = list(operation.status_history or [])
    history.append({
        "from": current,
        "to": target,
        "at": now.isoformat(),
        "actor_id": actor_id,
        "error": error_message,
    })
    operation.status = target
    operation.status_history = history
    operation.updated_at = now
    if error_message:
        operation.error_message = error_message

    return True


def needs_approval(operation_type: str) -> bool:
    """Onay kuyruğu kapalı — işlemler doğrudan uygulanır."""
    return False


def is_terminal(status: str) -> bool:
    """Terminal durumda mı? (değişiklik yapılamaz)"""
    return status in TERMINAL_STATES


def initial_status(operation_type: str) -> str:
    """Yeni operasyonun başlangıç durumu."""
    if needs_approval(operation_type):
        return "pending_approval"
    return "approved"
