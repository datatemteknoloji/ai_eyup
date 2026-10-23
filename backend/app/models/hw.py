"""Donanım yönetimi sağlayıcı (Dell OME / HPE OneView / OVGD) verisi — normalize şema.

Tablolar HER kurulumda oluşur ve entegrasyon yokken BOŞ kalır. Uygulama davranışını tablo varlığı değil
``hw`` capability'si belirler (bkz. services/capabilities.py). Hiçbir sütun donanıma yazmak için kullanılmaz;
tümü salt-okunur çekilmiş veridir.

`hw_components` / `hw_utilization` bu sürümde YOK: kaynak alanları doğrulanmadı (docs/plans/hw-api-sources.md).
`hw_log_entries` Faz 3 (iLO/iDRAC ham log) için ayrılmıştır; bu sürümde doldurulmaz.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)

from app.core.database import Base


class HwManager(Base):
    """Bir yönetim noktası: OME örneği, OneView appliance'ı veya OVGD."""
    __tablename__ = "hw_managers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_key = Column(String(255), nullable=False)          # ome | appliance host/id | ovgd
    manager_kind = Column(String(32), nullable=False)           # ome | oneview | ovgd
    name = Column(String(255), nullable=False, default="")
    address = Column(String(255), nullable=True)
    version = Column(String(64), nullable=True)                 # ürün sürümü (okunabildiyse)
    api_version = Column(String(32), nullable=True)             # currentVersion / x-api-version
    support_level = Column(String(16), nullable=False, default="compatible")  # verified | compatible | unsupported
    status = Column(String(32), nullable=False, default="never")  # ok | error | auth_failed | skipped | unsupported | never
    last_error = Column(Text, nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    server_count = Column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("instance_id", "provider_key", name="uq_hw_manager"),)


class HwServer(Base):
    __tablename__ = "hw_servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("hw_managers.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_ref = Column(String(255), nullable=False)          # OME cihaz Id / OneView server-hardware uri-id
    vendor = Column(String(16), nullable=False)                 # dell | hpe
    name = Column(String(255), nullable=False, default="")
    os_hostname = Column(String(255), nullable=True)            # OneView serverName / OME DeviceName
    model = Column(String(255), nullable=True)
    serial = Column(String(64), nullable=True, index=True)      # normalize (service tag / serialNumber)
    uuid = Column(String(64), nullable=True, index=True)
    virtual_serial = Column(String(64), nullable=True, index=True)
    virtual_uuid = Column(String(64), nullable=True, index=True)
    bmc_ip = Column(String(64), nullable=True)
    bmc_type = Column(String(32), nullable=True)                # iDRAC | iLO4 | iLO5 | iLO6 ...
    bmc_version = Column(String(64), nullable=True)
    bios_version = Column(String(128), nullable=True)
    form_factor = Column(String(32), nullable=True)             # blade | rack | unknown (ham değer extra_json'da)
    enclosure_ref = Column(String(255), nullable=True)
    enclosure_name = Column(String(255), nullable=True)
    bay = Column(String(64), nullable=True)
    health = Column(String(16), nullable=False, default="unknown")   # ok | warning | critical | unknown
    raw_status = Column(String(64), nullable=True)
    power_state = Column(String(16), nullable=True)             # on | off | unknown
    connected = Column(Boolean, nullable=True)
    cpu_count = Column(Integer, nullable=True)
    memory_gb = Column(Float, nullable=True)
    web_url = Column(String(512), nullable=True)                # "OneView'da aç / OME'de aç" (yönetim konsolu)
    extra_json = Column(Text, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("instance_id", "provider_ref", name="uq_hw_server"),)


class HwEnclosure(Base):
    __tablename__ = "hw_enclosures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("hw_managers.id", ondelete="SET NULL"), nullable=True)
    provider_ref = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False, default="")
    model = Column(String(255), nullable=True)
    serial = Column(String(64), nullable=True)
    health = Column(String(16), nullable=False, default="unknown")
    bay_count = Column(Integer, nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("instance_id", "provider_ref", name="uq_hw_enclosure"),)


class HwFirmware(Base):
    __tablename__ = "hw_firmware"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="")
    component_type = Column(String(64), nullable=True)
    version = Column(String(128), nullable=True)
    collected_at = Column(DateTime(timezone=True), nullable=True)


class HwAlert(Base):
    __tablename__ = "hw_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    manager_id = Column(Integer, ForeignKey("hw_managers.id", ondelete="SET NULL"), nullable=True)
    provider_ref = Column(String(255), nullable=False)
    server_ref = Column(String(255), nullable=True, index=True)  # hw_servers.provider_ref (varsa)
    entity_name = Column(String(255), nullable=True)
    severity = Column(String(16), nullable=False, default="unknown")   # critical | warning | info | unknown
    state = Column(String(16), nullable=False, default="active")       # active | cleared
    category = Column(String(128), nullable=True)
    message = Column(Text, nullable=True)
    fingerprint = Column(String(64), nullable=False, index=True)        # gruplama: kategori+normalize mesaj
    occurred_at = Column(DateTime(timezone=True), nullable=True, index=True)
    cleared_at = Column(DateTime(timezone=True), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("instance_id", "provider_ref", name="uq_hw_alert"),)


class HwLogEntry(Base):
    """Faz 3 için ayrılmış (iLO/iDRAC ham log). Bu sürümde doldurulmaz."""
    __tablename__ = "hw_log_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    severity = Column(String(16), nullable=True)
    message = Column(Text, nullable=True)


class HwWarranty(Base):
    __tablename__ = "hw_warranty"

    id = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_ref = Column(String(255), nullable=False)
    server_ref = Column(String(255), nullable=True, index=True)   # OME DeviceId
    serial = Column(String(64), nullable=True, index=True)
    service_level = Column(String(255), nullable=True)
    provider_name = Column(String(128), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("instance_id", "provider_ref", name="uq_hw_warranty"),)


class HwHostLink(Base):
    """Donanım kaydı ↔ ainew hedefi (Linux/Windows sunucu veya ESXi host) eşleşmesi."""
    __tablename__ = "hw_host_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hw_server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=False, unique=True)
    target_kind = Column(String(16), nullable=False)               # server | esxi
    target_id = Column(Integer, nullable=False, index=True)
    method = Column(String(32), nullable=False)                    # serial | uuid | virtual_serial | virtual_uuid | hostname
    confidence = Column(String(8), nullable=False)                 # exact | low
    matched_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("target_kind", "target_id", name="uq_hw_link_target"),)
