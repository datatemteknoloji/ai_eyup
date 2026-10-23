"""BackupProvider arayüzü — sağlayıcıdan bağımsız.

Ortak tipler ``services.integrations.types`` içindedir (donanım sağlayıcıları da kullanır); burada
geriye dönük uyumluluk için yeniden dışa aktarılır. Bu modülde HTTP çağrısı yoktur.
"""
from __future__ import annotations

from typing import Protocol, Set, runtime_checkable

from app.services.integrations.types import ConnTestResult, ProviderHealth, SyncCursor  # noqa: F401


@runtime_checkable
class BackupProvider(Protocol):
    kind: str

    def test_connection(self) -> ConnTestResult: ...

    def capabilities(self) -> Set[str]: ...

    def sync(self, cursor: SyncCursor) -> SyncCursor: ...

    def health(self) -> ProviderHealth: ...
