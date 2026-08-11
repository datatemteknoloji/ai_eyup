"""Virt sohbet — VM liste limiti (ContextVar) + tam envanter onayı (paylaşılan politika).

Keyword / onay / Redis pending → `chat_full_scan_policy`.
VM liste kesimi → bu modüldeki ContextVar + runtime_settings virt_chat_vm_list_*.
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

from app.services.chat_full_scan_policy import (  # noqa: F401
    is_confirm_message,
    is_decline_message,
    wants_full_fleet,
    wants_full_inventory,
    resolve_full_scan_turn,
    get_full_scan_pending,
    set_full_scan_pending,
    clear_full_scan_pending,
    build_full_fleet_clarification,
)

_request_vm_limit: ContextVar[Optional[int]] = ContextVar("virt_vm_list_limit", default=None)
_request_full_scan: ContextVar[bool] = ContextVar("virt_full_scan", default=False)


def get_default_vm_list_limit() -> int:
    try:
        from app.services import runtime_settings as rts
        return int(rts.get_int("virt_chat_vm_list_limit"))
    except Exception:
        return 50


def get_hard_max_vm_list_limit() -> int:
    try:
        from app.services import runtime_settings as rts
        return int(rts.get_int("virt_chat_vm_list_hard_max"))
    except Exception:
        return 5000


def set_request_vm_list_limit(limit: Optional[int], *, full_scan: bool = False) -> Token:
    _request_full_scan.set(bool(full_scan))
    return _request_vm_limit.set(limit)


def reset_request_vm_list_limit(token: Token) -> None:
    try:
        _request_vm_limit.reset(token)
    except Exception:
        _request_vm_limit.set(None)
    _request_full_scan.set(False)


def effective_vm_list_limit() -> int:
    override = _request_vm_limit.get()
    if override is not None and int(override) > 0:
        return int(override)
    return get_default_vm_list_limit()


def is_full_scan_request() -> bool:
    if bool(_request_full_scan.get()):
        return True
    try:
        from app.services.chat_full_scan_policy import is_full_scan_request as _shared
        return _shared()
    except Exception:
        return False


def build_full_scan_clarification(*, vm_count: int, default_limit: Optional[int] = None) -> str:
    return build_full_fleet_clarification(
        item_count=vm_count,
        default_cap=default_limit if default_limit is not None else get_default_vm_list_limit(),
        kind="VM",
    )


def count_virt_vms(db) -> int:
    from app.services.chat_full_scan_policy import count_fleet_candidates
    return count_fleet_candidates(db, platform="virt")
