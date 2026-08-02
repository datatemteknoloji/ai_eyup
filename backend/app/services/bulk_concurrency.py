"""
Toplu SSH / WinRM / TCP kontrolleri için ortak paralellik ayarları.

Öncelik: Ayarlar → Gelişmiş (DB) → BULK_*_WORKERS env → varsayılan.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_BULK_SSH_WORKERS = 25
DEFAULT_BULK_TCP_WORKERS = 100
DEFAULT_LOG_SSH_WORKERS = 32
DEFAULT_WINDOWS_LOG_WORKERS = 20
_MAX_SSH = 128
_MAX_TCP = 256
_MAX_LOG_SSH = 64
_MAX_WINDOWS_LOG = 64


def _parse_workers(raw: str, default: int, lo: int, hi: int) -> int:
    raw = (raw or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return max(lo, min(int(raw), hi))
    return default


def bulk_ssh_workers(requested: Optional[int] = None) -> int:
    """SSH / WinRM / AI Ready toplu test için worker sayısı."""
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_SSH))
    try:
        from app.services.runtime_settings import get_int
        return max(1, min(get_int("bulk_ssh_workers"), _MAX_SSH))
    except Exception:
        return _parse_workers(
            os.environ.get("BULK_SSH_WORKERS", ""),
            DEFAULT_BULK_SSH_WORKERS,
            1,
            _MAX_SSH,
        )


def log_ssh_workers(requested: Optional[int] = None) -> int:
    """Linux journalctl log toplama paralelliği (15k+ ölçek)."""
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_LOG_SSH))
    try:
        from app.services.runtime_settings import get_int
        return max(1, min(get_int("log_ssh_workers"), _MAX_LOG_SSH))
    except Exception:
        return _parse_workers(
            os.environ.get("LOG_SSH_WORKERS", ""),
            DEFAULT_LOG_SSH_WORKERS,
            1,
            _MAX_LOG_SSH,
        )


def windows_log_workers(requested: Optional[int] = None) -> int:
    """Windows Event Log toplama (WinRM) paralelliği — 10k+ ölçek.

    Önceden collect_all_windows_logs sunucuları tek tek, tamamen sıralı işliyordu;
    3000 Windows sunucuda tur saatler sürebiliyordu (interval 900sn'i katbekat aşar).
    """
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_WINDOWS_LOG))
    try:
        from app.services.runtime_settings import get_int
        return max(1, min(get_int("windows_log_workers"), _MAX_WINDOWS_LOG))
    except Exception:
        return _parse_workers(
            os.environ.get("WINDOWS_LOG_WORKERS", ""),
            DEFAULT_WINDOWS_LOG_WORKERS,
            1,
            _MAX_WINDOWS_LOG,
        )


def bulk_tcp_workers(requested: Optional[int] = None) -> int:
    """Hafif TCP health check için worker sayısı."""
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_TCP))
    try:
        from app.services.runtime_settings import get_int
        return max(1, min(get_int("bulk_tcp_workers"), _MAX_TCP))
    except Exception:
        return _parse_workers(
            os.environ.get("BULK_TCP_WORKERS", ""),
            DEFAULT_BULK_TCP_WORKERS,
            1,
            _MAX_TCP,
        )
