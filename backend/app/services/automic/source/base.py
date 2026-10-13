"""Ortak veri kaynağı arayüzü.

Collector, araçlar ve monitoring yalnızca bu arayüzü bilir; verinin hangi
kaynaktan (Oracle / MSSQL / PostgreSQL / REST) geldiğini bilmez.
Tüm zamanlar timezone-aware UTC datetime olarak döner.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

#
# Alanlar mantıksaldır; Oracle profilinde resmi AE kolonlarına eşlenir (bkz. sql/oracle/ae-24.yaml).
# `user` ve `folder` doğrudan kolon değildir: adaptör `user_id` (AH_USR_Idnr → OH_Name) ve
# `object_id` (OFS home klasörü → OH_Name) üzerinden çözer.
EXECUTION_FIELDS = (
    "client", "run_id", "parent_run_id", "top_run_id", "restart_ref_run_id",
    "object_id", "object_name", "object_type", "status_code",
    "activation_time", "start_time", "end_time",
    "agent", "agent_group", "platform", "queue", "user_id", "return_code",
    "run_time_sec", "ert_sec",
)

ACTIVE_FIELDS = (
    "client", "run_id", "parent_run_id", "top_run_id", "object_id", "object_name", "object_type",
    "status_code", "activation_time", "start_time", "agent", "agent_group", "platform", "queue",
    "user_id", "run_time_sec", "ert_sec", "ert_end_time", "ert_calc", "signal", "mrt_sec", "srt_sec",
)

OBJECT_HEADER_FIELDS = (
    "object_id", "client", "object_name", "object_type", "title",
    "created_at", "created_user_id", "modified_at", "modified_user_id", "ert_sec",
    "archive1", "archive2",
)

HOST_FIELDS = (
    "oh_idnr", "hardware", "os", "sw_version", "platform", "ip", "port",
    "host_active", "version", "roles", "hostname",
)
MQSRV_FIELDS = (
    "name", "mqsrv_type", "ip", "port", "last_update", "start_time",
    "rest_endpoint", "connection_count", "pwp_connected", "system_name",
)
OHG_FIELDS = ("oh_idnr", "platform", "mode")
OHGF_FIELDS = ("oh_idnr", "line_no", "filter_type", "agent_name")

# USER senkron (OH OType=USER) — delete_flag dahil; USR tablosu yok
USER_HEADER_FIELDS = (
    "object_id", "client", "object_name", "object_type", "modified_at", "delete_flag",
)

SOURCE_TYPES = ("db_oracle", "db_mssql", "db_postgres", "rest", "hybrid")
IMPLEMENTED_SOURCE_TYPES = ("db_oracle",)


class SourceError(Exception):
    """Kaynak hatası — kullanıcıya gösterilebilir Türkçe mesaj taşır."""

    def __init__(self, message: str, *, code: str = "source_error", retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class ConnectionResult:
    ok: bool
    message: str
    db_version: Optional[str] = None
    driver_mode: Optional[str] = None
    latency_ms: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "message": self.message, "db_version": self.db_version,
            "driver_mode": self.driver_mode, "latency_ms": self.latency_ms,
            "warnings": self.warnings, "details": self.details,
        }


@dataclass
class Freshness:
    lag_sec: Optional[float]
    method: str
    latest_at: Optional[datetime] = None


@dataclass
class ReportText:
    report_type: str
    lines: List[str]
    total_lines: int
    truncated: bool


class AutomicSource(ABC):
    """Bir AE sistemine salt okunur erişim."""

    source_type: str = ""

    def __init__(self, system_id: int, connection: Dict[str, Any], secret: Optional[str],
                 settings: Dict[str, Any], capability: Optional[Dict[str, Any]] = None):
        self.system_id = system_id
        self.connection = connection or {}
        self.secret = secret
        self.settings = settings or {}
        self.capability = capability or {}

    def close(self) -> None:  # pragma: no cover - adaptöre göre
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def supports(self, feature: str) -> bool:
        feats = (self.capability or {}).get("features") or {}
        val = feats.get(feature)
        return bool(val) and val not in ("unavailable", "none")

    @abstractmethod
    def test_connection(self) -> ConnectionResult: ...

    @abstractmethod
    def discover(self) -> Dict[str, Any]:
        """Yetenek matrisi (CapabilityMatrix) üretir."""

    @abstractmethod
    def source_freshness(self) -> Freshness: ...

    @abstractmethod
    def fetch_ended_executions(self, clients: List[int], t_from: datetime, t_to: datetime,
                               *, limit: int) -> List[Dict[str, Any]]: ...

    def fetch_ended_by_runids(self, pairs: List[Tuple[int, int]]) -> List[Dict[str, Any]]:
        """Açık (client, run_id) listesi — PK nokta sorgusu (min..max aralık TARAMAZ). Durum güncelleme adımı kullanır."""
        fn = getattr(self, "fetch_ended_by_runid_range", None)
        out: List[Dict[str, Any]] = []
        if not callable(fn):
            return out
        for client, rid in pairs:
            out.extend(fn([int(client)], int(rid), int(rid) + 1, limit=2))
        return out

    @abstractmethod
    def fetch_active_executions(self, clients: List[int], *, limit: int) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def fetch_execution(self, client: int, run_id: int) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def fetch_children(self, client: int, run_id: int, *, limit: int,
                       id_min: Optional[int] = None, id_max: Optional[int] = None) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def fetch_restarts(self, client: int, run_id: int, *, limit: int,
                       id_min: Optional[int] = None, id_max: Optional[int] = None) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def list_reports(self, client: int, run_id: int) -> List[str]: ...

    @abstractmethod
    def fetch_report(self, client: int, run_id: int, report_type: str, *,
                     head: int, tail: int, max_scan_lines: int) -> ReportText: ...

    def fetch_object_header(self, client: int, object_name: str) -> Optional[Dict[str, Any]]:
        """OH satırı; yoksa None. Varsayılan: yetenek yok."""
        raise SourceError("Nesne başlıkları bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def fetch_object_headers(self, clients: List[int], *, since: Optional[datetime] = None,
                             limit: int = 5000) -> List[Dict[str, Any]]:
        raise SourceError("Nesne başlıkları bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def find_users(self, pattern: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Kullanıcı ADI (OH_Name, OH_OType = USER) desenine uyan kullanıcılar → [{user_id, name, client}]."""
        raise SourceError("Kullanıcı arama bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def fetch_runs_by_users(self, user_ids: List[int], clients: List[int], t_from: datetime,
                            t_to: datetime, *, limit: int) -> List[Dict[str, Any]]:
        """Verilen kullanıcı id'lerinin (AH_USR_Idnr) biten çalışmaları, yeniden eskiye."""
        raise SourceError("Kullanıcıya göre çalışma arama bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def fetch_object_script(self, object_id: int, *, max_lines: int = 20000) -> List[str]:
        """OT satırları (sıralı metin satırları)."""
        raise SourceError("Nesne script'i bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def fetch_jpp_by_parent_range(self, id_min: int, id_max: int, *, limit: int
                                  ) -> List[Dict[str, Any]]:
        """JPP satırları — ebeveyn OH_Idnr PK aralığı. Varsayılan: yetenek yok."""
        raise SourceError("Usage/bağımlılık (JPP) bu kaynakta kullanılamıyor.",
                          code="capability_missing", retryable=False)

    def fetch_object_usage(self, client: int, object_name: str, *, depth: int = 1
                           ) -> Dict[str, Any]:
        """Canlı usage kaldırıldı — modül DB / JPP senkron kullanın."""
        raise SourceError(
            "Kaynakta canlı usage (isim) sorgusu kaldırıldı; modül DB kullanın.",
            code="capability_removed", retryable=False,
        )
