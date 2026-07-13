"""
ESX host donanım kimliği ve ağ envanteri.

hypervisor_host_metrics (TimescaleDB) sadece 15 dk'da bir değişen kapasite
metriklerini tutar; bu tablo ise nadiren değişen envanter bilgisini
(donanım marka/model, fiziksel NIC, vSwitch, port group/VLAN, VMkernel NIC,
DNS) host başına TEK satırda tutar — sync her çalıştığında upsert edilir.
"""
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class HypervisorHostInventory(Base):
    __tablename__ = "hypervisor_host_inventory"

    id = Column(Integer, primary_key=True, index=True)
    hypervisor_id = Column(
        Integer, ForeignKey("hypervisors.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    host_ref  = Column(String(64), nullable=False)   # vCenter MOR (örn. host-12)
    host_name = Column(String(255), nullable=False)

    # ── Donanım kimliği ──────────────────────────────────────────────────────
    vendor    = Column(String(128))    # örn. Dell Inc., HPE, Cisco
    model     = Column(String(128))    # örn. PowerEdge R740
    uuid      = Column(String(64))
    cpu_model = Column(String(128))

    # ── Ağ envanteri (JSON) ──────────────────────────────────────────────────
    pnics      = Column(JSON, default=list)   # [{device, mac, link_speed_mb, full_duplex, mtu}]
    vswitches  = Column(JSON, default=list)   # [{name, num_ports, pnics:[...], portgroups:[...]}]
    portgroups = Column(JSON, default=list)   # [{name, vlan_id, vswitch_name}]
    vnics      = Column(JSON, default=list)   # [{device, portgroup, mtu, ip_address, subnet_mask, dhcp}]
    dns        = Column(JSON, default=dict)   # {host_name, domain_name, dhcp, servers:[...]}

    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    hypervisor = relationship("Hypervisor")

    __table_args__ = (
        UniqueConstraint("hypervisor_id", "host_ref", name="uq_hv_host_inventory"),
    )
