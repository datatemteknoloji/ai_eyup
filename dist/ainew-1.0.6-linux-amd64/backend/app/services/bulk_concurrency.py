"""
Toplu SSH / WinRM / TCP kontrolleri için ortak paralellik ayarları.

Ürün 3000–4000 sunucu ölçeğinde çalışacak şekilde varsayılanlar
yüksektir; ortam değişkeniyle ince ayar yapılabilir.

  BULK_SSH_WORKERS   — AI Ready, credential SSH test, OS refresh (varsayılan 50)
  BULK_TCP_WORKERS   — health checker TCP/ping (varsayılan 100, daha hafif)
"""
from __future__ import annotations

import os
from typing import Optional


DEFAULT_BULK_SSH_WORKERS = 50
DEFAULT_BULK_TCP_WORKERS = 100
_MAX_SSH = 128
_MAX_TCP = 256


def _parse_workers(raw: str, default: int, lo: int, hi: int) -> int:
    raw = (raw or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return max(lo, min(int(raw), hi))
    return default


def bulk_ssh_workers(requested: Optional[int] = None) -> int:
    """SSH / WinRM / AI Ready toplu test için worker sayısı."""
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_SSH))
    return _parse_workers(
        os.environ.get("BULK_SSH_WORKERS", ""),
        DEFAULT_BULK_SSH_WORKERS,
        1,
        _MAX_SSH,
    )


def bulk_tcp_workers(requested: Optional[int] = None) -> int:
    """Hafif TCP health check için worker sayısı."""
    if requested is not None and requested > 0:
        return max(1, min(int(requested), _MAX_TCP))
    return _parse_workers(
        os.environ.get("BULK_TCP_WORKERS", ""),
        DEFAULT_BULK_TCP_WORKERS,
        1,
        _MAX_TCP,
    )
