"""
Uygulama ayarları - key-value (envanter sync aralığı vb.)
"""
from sqlalchemy import Column, Integer, String, Text
from app.core.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(128), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=True)
