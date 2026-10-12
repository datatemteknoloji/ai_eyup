"""BackupProvider arayüzü — sağlayıcıdan bağımsız.

Veeam adaptörü Dilim D'de eklenir. Bu modülde HTTP çağrısı yoktur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Protocol, Set, runtime_checkable


@dataclass
class ConnTestResult:
    ok: bool
    api_version: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealth:
    ok: bool
    stale: bool = False
    data_age_sec: Optional[float] = None
    message: str = ""


@dataclass
class SyncCursor:
    """Artımlı senkron imleci (sağlayıcıya özel JSON string taşır)."""
    token: str = ""
    updated_at: Optional[datetime] = None


@runtime_checkable
class BackupProvider(Protocol):
    kind: str

    def test_connection(self) -> ConnTestResult: ...

    def capabilities(self) -> Set[str]: ...

    def sync(self, cursor: SyncCursor) -> SyncCursor: ...

    def health(self) -> ProviderHealth: ...
