"""Opsiyonel yedekleme/DR sağlayıcı çerçevesi.

Kayıtlı ama yapılandırılmamış / disabled sağlayıcının sistem üzerinde sıfır etkisi vardır.
"""
from app.services.backup.protocol import BackupProvider, ConnTestResult, ProviderHealth, SyncCursor
from app.services.backup.registry import list_provider_kinds, get_provider_factory

# Sağlayıcıları kayıt defterine ekler (kayıt ≠ aktif; etki yalnız enabled instance ile)
from app.services.backup import veeam_provider  # noqa: E402,F401

__all__ = [
    "BackupProvider",
    "ConnTestResult",
    "ProviderHealth",
    "SyncCursor",
    "list_provider_kinds",
    "get_provider_factory",
]
