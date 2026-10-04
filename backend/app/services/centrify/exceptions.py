"""Centrify modülü exception hiyerarşisi.

Tüm Centrify hataları CentrifyError'dan türer — ainew genelinde
yakalanıp izole edilir; uygulamanın kalanını etkilemez.
"""
from __future__ import annotations

from enum import Enum


class CentrifyErrorClass(str, Enum):
    """Hata sınıflandırması — retry stratejisini belirler."""
    TRANSIENT = "transient"    # WinRM ağ hatası, timeout → sınırlı retry (max 2)
    PERMANENT = "permanent"    # auth fail, nesne yok, yetki yok → durdur, retry YASAK
    AMBIGUOUS = "ambiguous"    # WinRM timeout ama komut çalışmış olabilir → AD'den oku


class CentrifyError(Exception):
    """Temel Centrify hatası."""
    error_class: CentrifyErrorClass = CentrifyErrorClass.TRANSIENT

    def __init__(self, message: str, *, error_class: CentrifyErrorClass | None = None):
        super().__init__(message)
        if error_class is not None:
            self.error_class = error_class


class CentrifyAuthError(CentrifyError):
    """WinRM / AD kimlik doğrulama hatası — retry YASAK."""
    error_class = CentrifyErrorClass.PERMANENT


class CentrifyConnectionError(CentrifyError):
    """WinRM bağlantı hatası — geçici, sınırlı retry."""
    error_class = CentrifyErrorClass.TRANSIENT


class CentrifyCircuitOpenError(CentrifyError):
    """Circuit breaker açık — tüm işlemler reddedilir."""
    error_class = CentrifyErrorClass.PERMANENT


class CentrifyScriptError(CentrifyError):
    """PowerShell scripti hata döndü."""
    error_class = CentrifyErrorClass.TRANSIENT

    def __init__(self, message: str, *, stderr: str = "", exit_code: int = -1,
                 error_class: CentrifyErrorClass | None = None):
        super().__init__(message, error_class=error_class)
        self.stderr = stderr
        self.exit_code = exit_code


class CentrifyObjectNotFoundError(CentrifyError):
    """İstenen nesne AD'de bulunamadı."""
    error_class = CentrifyErrorClass.PERMANENT


class CentrifyAmbiguousResultError(CentrifyError):
    """İşlem gönderildi ama sonucu belirsiz (timeout sonrası)."""
    error_class = CentrifyErrorClass.AMBIGUOUS
