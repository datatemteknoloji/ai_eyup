"""Sağlayıcıdan gelen normalize veri (sağlayıcıdan bağımsız). Bu modülde I/O yoktur."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

PART_INVENTORY = "inventory"
PART_ALERTS = "alerts"
PART_WARRANTY = "warranty"
ALL_PARTS = (PART_INVENTORY, PART_ALERTS, PART_WARRANTY)


@dataclass
class ManagerRec:
    key: str                         # ome | appliance host/id | ovgd
    kind: str                        # ome | oneview | ovgd
    name: str = ""
    address: Optional[str] = None
    version: Optional[str] = None
    api_version: Optional[str] = None
    support_level: str = "compatible"
    status: str = "ok"               # ok | error | auth_failed | skipped | unsupported
    error: Optional[str] = None
    server_count: Optional[int] = None


@dataclass
class ServerRec:
    provider_ref: str
    vendor: str                      # dell | hpe
    name: str = ""
    manager_key: Optional[str] = None
    os_hostname: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    uuid: Optional[str] = None
    virtual_serial: Optional[str] = None
    virtual_uuid: Optional[str] = None
    bmc_ip: Optional[str] = None
    bmc_type: Optional[str] = None
    bmc_version: Optional[str] = None
    bios_version: Optional[str] = None
    form_factor: Optional[str] = None
    enclosure_ref: Optional[str] = None
    enclosure_name: Optional[str] = None
    bay: Optional[str] = None
    health: str = "unknown"
    raw_status: Optional[str] = None
    power_state: Optional[str] = None
    connected: Optional[bool] = None
    cpu_count: Optional[int] = None
    memory_gb: Optional[float] = None
    web_url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnclosureRec:
    provider_ref: str
    name: str = ""
    manager_key: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    health: str = "unknown"
    bay_count: Optional[int] = None


@dataclass
class AlertRec:
    provider_ref: str
    severity: str                    # critical | warning | info | unknown
    message: str = ""
    category: Optional[str] = None
    server_ref: Optional[str] = None  # ServerRec.provider_ref (biliniyorsa)
    entity_name: Optional[str] = None
    manager_key: Optional[str] = None
    state: str = "active"            # active | cleared
    occurred_at: Optional[datetime] = None
    cleared_at: Optional[datetime] = None
    type_id: Optional[str] = None    # OME AlertMessageId / OneView alertTypeID (gruplama anahtarı)


@dataclass
class WarrantyRec:
    provider_ref: str
    server_ref: Optional[str] = None
    serial: Optional[str] = None
    service_level: Optional[str] = None
    provider_name: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class FirmwareRec:
    server_ref: str
    name: str = ""
    component_type: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None           # Installed | Available
    component_id: Optional[str] = None
    location: Optional[str] = None         # HPE: componentLocation (aynı adlı bileşenleri ayırır)


@dataclass
class HwSnapshot:
    parts: Set[str] = field(default_factory=set)         # gerçekten toplanan bölümler
    managers: List[ManagerRec] = field(default_factory=list)
    servers: List[ServerRec] = field(default_factory=list)
    enclosures: List[EnclosureRec] = field(default_factory=list)
    alerts: List[AlertRec] = field(default_factory=list)
    warranties: List[WarrantyRec] = field(default_factory=list)
    firmware: List[FirmwareRec] = field(default_factory=list)
    firmware_cursors: Dict[str, int] = field(default_factory=dict)     # yönetim noktası → sonraki turun başlangıç sırası
    firmware_progress: Dict[str, Dict[str, int]] = field(default_factory=dict)   # yönetim noktası → {"read": n, "total": m}
    warnings: List[str] = field(default_factory=list)
    not_measurable: List[str] = field(default_factory=list)   # "alan: neden" (kartta gösterilir)
    complete_managers: Set[str] = field(default_factory=set)  # envanteri TAM okunabilen yönetim noktaları
