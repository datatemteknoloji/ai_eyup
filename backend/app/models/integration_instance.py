"""Yeni nesil entegrasyon instance'ları (category: backup, ileride bmc, …).

Centrify / Automic / hypervisor kartları bu tabloya TAŞINMAZ — kendi
modellerinde kalır. Yalnız Dilim B+ sonrası eklenen sağlayıcılar burayı kullanır.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class IntegrationInstance(Base):
    __tablename__ = "integration_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # backup | bmc | … — eski hub kartlarıyla karışmasın diye zorunlu
    category = Column(String(64), nullable=False, index=True)
    kind = Column(String(64), nullable=False, index=True)  # veeam_vbr | veeam_demo | …
    label = Column(String(255), nullable=False, default="")
    endpoint = Column(String(512), nullable=False, default="")
    # encrypt_secret ile mühürlü JSON / parola — write_credential DEĞİL
    credential_ref = Column(Text, nullable=True)
    verify_ssl = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=False, index=True)
    sync_interval_sec = Column(Integer, nullable=False, default=3600)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(64), nullable=True)  # ok | error | auth_failed | never
    last_error = Column(Text, nullable=True)
    meta_json = Column(Text, nullable=True)  # sürüm, cursor özeti vb.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
