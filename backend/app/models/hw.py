"""Donanım yönetimi sağlayıcı (Dell OME / HPE OneView / OVGD) verisi — normalize şema.

Tablolar HER kurulumda oluşur ve entegrasyon yokken BOŞ kalır. Uygulama davranışını tablo varlığı değil
``hw`` capability'si belirler (bkz. services/capabilities.py). Hiçbir sütun donanıma yazmak için kullanılmaz;
tümü salt-okunur çekilmiş veridir.

`hw_components` / `hw_utilization` bu sürümde YOK: kaynak alanları doğrulanmadı (docs/plans/hw-api-sources.md).
`hw_log_entries` Faz 3a (host kaynaklı donanım logları: ESXi SEL/vmkernel, Linux/Windows) ile dolar; iLO/iDRAC ham logu (Faz 3b) YOK.
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
    status = Column(String(16), nullable=True)                  # OME InventoryInfo.Status: Installed | Available (önceki/yedek)
    component_id = Column(String(64), nullable=True)            # OME InventoryInfo.ComponentId
    location = Column(String(255), nullable=True)               # HPE componentLocation
    collected_at = Column(DateTime(timezone=True), nullable=True)


class HwFirmwareReference(Base):
    """Referans (doğrulanmış) sunucu: aynı modeldeki sunucular firmware sürümlerini buna göre kıyaslar. Yalnız ainew'e yazılır.

    scope=model: (vendor, model) için TÜM sunucular. scope=chassis: yalnız bu şasideki (`enclosure_id`) AYNI model sunucular;
    şasi referansı model referansını geçersiz kılar (şasi > model)."""
    __tablename__ = "hw_firmware_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(8), nullable=False)                   # model | chassis
    vendor = Column(String(16), nullable=False)
    model = Column(String(255), nullable=False)                 # küçük harfe çevrilmiş karşılaştırma anahtarı değil; ham model
    enclosure_id = Column(Integer, ForeignKey("hw_enclosures.id", ondelete="CASCADE"), nullable=True, index=True)
    reference_server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    set_by = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HwFirmwareAccept(Base):
    """«Kabul edildi»: bu sunucunun bu bileşeni bilinçli olarak referanstan düşük bırakıldı. YALNIZ `accepted_version`
    sunucudaki güncel sürümle AYNI olduğu sürece geçerli (sürüm değişince otomatik düşer)."""
    __tablename__ = "hw_firmware_accepts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    component_key = Column(String(400), nullable=False)
    accepted_version = Column(String(128), nullable=False)
    note = Column(String(500), nullable=True)
    accepted_by = Column(String(128), nullable=True)
    accepted_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("server_id", "component_key", name="uq_hw_fw_accept"),)


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
    """Host kaynaklı donanım kaydı (Faz 3a): ESXi SEL / vmkernel, Linux journal, Windows WHEA.

    iLO/iDRAC'e DOĞRUDAN bağlanılmaz (Faz 3b). Hedef `target_kind`/`target_id` ile (HwHostLink ile aynı anlam:
    server | esxi) bulunur; `server_id` (hw_servers) yalnız gelecekteki sağlayıcı kaynaklı kayıtlar için opsiyoneldir.
    Tekilleştirme `(target_kind, target_id, source, event_key)`; tekrar → `occurrences` ve `last_seen_at`.
    """
    __tablename__ = "hw_log_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    server_id = Column(Integer, ForeignKey("hw_servers.id", ondelete="CASCADE"), nullable=True, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=True)
    severity = Column(String(16), nullable=True)                # critical | warning | info
    message = Column(Text, nullable=True)
    target_kind = Column(String(16), nullable=True)             # server | esxi
    target_id = Column(Integer, nullable=True)                  # servers.id | hypervisor_host_inventory.id
    source = Column(String(24), nullable=True)                  # esxi_sel | esxi_vmkernel | linux_journal | windows_event
    category = Column(String(32), nullable=True)                # memory | cpu | storage | power | thermal | pcie | platform
    event_key = Column(String(64), nullable=True)               # normalize mesajın özeti (tekilleştirme)
    occurrences = Column(Integer, nullable=False, default=1, server_default="1")
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    __table_args__ = (
        UniqueConstraint("target_kind", "target_id", "source", "event_key", name="uq_hw_log_target_event"),
    )


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


class HwBmcProfile(Base):
    """Faz 3b — BMC (iLO/iDRAC) kimlik profili. Parola `encrypt_secret` ile `credential_ref` içinde; hiçbir yanıtta dönmez.

    scope: global (tek) | vendor (dell|hpe) | instance (portal entegrasyonu) | host (host'a özel; `HwBmcEndpoint.profile_id`).
    Çözümleme önceliği: host > instance > vendor > global (bkz. services/hw/bmc_creds.py). Başarısızlıkta zincirleme YOK.
    """
    __tablename__ = "hw_bmc_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, default="")
    scope = Column(String(16), nullable=False, default="host")      # global | vendor | instance | host
    vendor = Column(String(16), nullable=True)                      # dell | hpe (scope=vendor)
    instance_id = Column(Integer, ForeignKey("integration_instances.id", ondelete="CASCADE"), nullable=True, index=True)
    credential_ref = Column(Text, nullable=True)                    # encrypt_secret(json {username, password})
    verify_tls = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)


class HwBmcEndpoint(Base):
    """Faz 3b — BMC adresi + durum. Hedef: `server` (Linux sayfası) | `hw` (portal kaydı; hw_servers.id).

    ip_source önceliği: manual > portal > discovered. `auth_halted`: kimlik reddedilince True; yalnız başarılı
    «Bağlantıyı test et» kaldırır (hesap kilitlenmesin).
    """
    __tablename__ = "hw_bmc_endpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_kind = Column(String(16), nullable=False)                # server | hw
    target_id = Column(Integer, nullable=False)
    bmc_ip = Column(String(64), nullable=True)
    ip_source = Column(String(16), nullable=False, default="manual")  # manual | portal | discovered
    vendor = Column(String(16), nullable=True)                      # dell | hpe | other
    profile_id = Column(Integer, ForeignKey("hw_bmc_profiles.id", ondelete="SET NULL"), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    status = Column(String(24), nullable=False, default="never")    # never|ok|unreachable|auth_failed|unsupported|no_cred|no_ip
    last_error = Column(Text, nullable=True)
    auth_halted = Column(Boolean, nullable=False, default=False, server_default="false")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_ok_at = Column(DateTime(timezone=True), nullable=True)
    # in-band ipmitool durumu: ok | no_ipmitool | no_device | no_sudo | error | None
    ipmi_status = Column(String(24), nullable=True)
    ipmi_run_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("target_kind", "target_id", name="uq_hw_bmc_target"),)
