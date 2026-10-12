"""Kapasite eşik politikası — yalnız varsayılandan farklı değerler saklanır."""
from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class CapacityPolicy(Base):
    __tablename__ = "capacity_policies"

    key = Column(String(40), primary_key=True)
    value = Column(Float, nullable=False)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CapacityPolicyOverride(Base):
    """H.0: instance (cluster='') veya cluster seviyesinde eşik override'ı.

    Çözüm sırası: kod varsayılanı < global (`capacity_policies`) < instance < cluster. Global tabloya dokunulmaz.
    """
    __tablename__ = "capacity_policy_overrides"
    __table_args__ = (UniqueConstraint("hypervisor_id", "cluster", "key", name="uq_cap_policy_override"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    hypervisor_id = Column(Integer, nullable=False, index=True)
    cluster = Column(String(255), nullable=False, default="")     # '' = instance seviyesi
    key = Column(String(40), nullable=False)
    value = Column(Float, nullable=False)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
