"""Kapasite eşik politikası — yalnız varsayılandan farklı değerler saklanır."""
from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.sql import func

from app.core.database import Base


class CapacityPolicy(Base):
    __tablename__ = "capacity_policies"

    key = Column(String(40), primary_key=True)
    value = Column(Float, nullable=False)
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
