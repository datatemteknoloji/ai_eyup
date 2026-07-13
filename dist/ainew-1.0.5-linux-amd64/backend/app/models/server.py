"""
Server Model
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Server(Base):
    """Server model"""
    __tablename__ = "servers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    hostname = Column(String(255))
    ip_address = Column(String(45), index=True)
    status = Column(String(50), default="unknown")
    os_type       = Column(String(50))
    os_version    = Column(String(255))   # PRETTY_NAME
    os_release_id = Column(String(50))    # ID: "rhel"|"ol"|"rocky"|"ubuntu"
    os_version_id = Column(String(20))    # VERSION_ID: "9.5"|"8.10"|"22.04"
    kernel_version= Column(String(100))   # uname -r
    server_type   = Column(String(50))
    cpu_cores = Column(Integer, default=0)
    memory_gb = Column(Integer, default=0)
    ai_ready = Column(Boolean, default=False, index=True)
    tier = Column(String(20), default="unknown", index=True)  # production | staging | development | unknown
    connection_config = Column(JSON, default=dict)
    
    # Hypervisor iliskisi
    hypervisor_id = Column(Integer, ForeignKey("hypervisors.id", ondelete="SET NULL"), nullable=True, index=True)
    hypervisor_vm_id = Column(String(255), nullable=True)

    # ── VM Detayları (hypervisor'dan senkronize edilir) ───────────────────────
    vm_name           = Column(String(255), nullable=True)        # Hypervisorde görünen VM adı
    vm_guest_hostname = Column(String(255), nullable=True)        # Guest OS hostname (VMware Tools / oVirt guest agent)
    vm_guest_ip       = Column(String(45),  nullable=True)        # Guest OS primary IP (management IP'den farklı olabilir)
    vm_cpu_count      = Column(Integer,     nullable=True)        # vCPU sayısı
    vm_memory_mb      = Column(Integer,     nullable=True)        # Tahsis edilen RAM (MB)
    vm_disk_gb        = Column(Integer,     nullable=True)        # Toplam disk (GB, tüm disk'ler)
    vm_power_state    = Column(String(30),  nullable=True)        # poweredOn / poweredOff / up / down / suspended
    vm_tools_status   = Column(String(50),  nullable=True)        # guestToolsRunning / toolsNotInstalled vb.
    vm_network_info   = Column(JSON,        nullable=True)        # [{adapter, mac, ips:[...]}] listesi
    vm_cluster        = Column(String(255), nullable=True)        # Hangi cluster / datacenter
    vm_datastore      = Column(String(255), nullable=True)        # Birincil datastore / storage domain adı
    vm_hardware_version = Column(String(50), nullable=True)       # vmx-19 / v4 vb.
    vm_last_sync      = Column(DateTime(timezone=True), nullable=True)  # Son hypervisor sync zamanı

    # Node Exporter durum cache (background task 5dk'da bir gunceller)
    node_exporter_installed = Column(Boolean, default=False)
    node_exporter_running = Column(Boolean, default=False)
    node_exporter_last_check = Column(DateTime(timezone=True), nullable=True)

    # Windows Exporter durum cache (node_exporter'ın Windows eşleniği — background task senkronlar)
    windows_exporter_installed = Column(Boolean, default=False)
    windows_exporter_running = Column(Boolean, default=False)
    windows_exporter_last_check = Column(DateTime(timezone=True), nullable=True)

    # Windows Update / Defender durum cache — auto-onboarding periyodik WinRM ile toplar
    # (raporların hızlı/senkron çalışması için canlı WinRM sorgusu YAPILMAZ, bu cache okunur)
    win_updates_pending = Column(Integer, nullable=True)
    win_updates_critical = Column(Integer, nullable=True)
    win_updates_last_checked = Column(DateTime(timezone=True), nullable=True)
    win_reboot_pending = Column(Boolean, default=False)
    win_defender_enabled = Column(Boolean, nullable=True)
    win_defender_up_to_date = Column(Boolean, nullable=True)

    # Linux güvenlik denetim cache — auto-onboarding periyodik SSH ile toplar
    linux_firewall_active = Column(Boolean, nullable=True)
    linux_selinux_status = Column(String(20), nullable=True)   # Enforcing | Permissive | Disabled | N/A
    linux_failed_logins_24h = Column(Integer, nullable=True)
    linux_security_last_check = Column(DateTime(timezone=True), nullable=True)

    # Uygulama/servis keşfi (Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.) —
    # background task periyodik SSH/WinRM ile tarar, sonuçlar discovered_applications
    # tablosuna yazılır (bkz. app/services/app_discovery.py). Bu alan sadece
    # "en son ne zaman tarandı" bilgisini tutar (rescan aralığını belirlemek için).
    app_discovery_last_scan = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    hypervisor = relationship("Hypervisor", back_populates="servers")
    events = relationship("SystemEvent", back_populates="server", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="server", cascade="all, delete-orphan")
