"""
Global Credential Model
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from app.core.database import Base


class GlobalCredential(Base):
    __tablename__ = "global_credentials"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    username = Column(String(255), nullable=False)
    password = Column(String(512))
    private_key = Column(Text)
    sudo_password = Column(String(512))
    port = Column(Integer, default=22)
    is_default = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
