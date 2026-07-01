"""
Platform modülleri ve kullanıcı-modül atamaları.
Admin: tüm modüllere erişim (bypass).
Operator/viewer: sadece atanan modüller.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class Module(Base):
    __tablename__ = "modules"

    id = Column(String(64), primary_key=True)          # 'linux', 'windows', …
    name = Column(String(128), nullable=False)
    description = Column(String(512), nullable=True)
    icon = Column(String(64), nullable=True)            # lucide icon adı
    color = Column(String(32), nullable=True)           # tailwind renk
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class UserModule(Base):
    __tablename__ = "user_modules"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    module_id = Column(String(64), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "module_id", name="uq_user_module"),)


# ── Varsayılan modüller ───────────────────────────────────────────────────────

DEFAULT_MODULES = [
    {"id": "linux",          "name": "Linux Yönetimi",   "description": "Linux sunucu yönetimi, paket/yama, repo, Ansible",
     "icon": "Server",   "color": "green",   "sort_order": 1},
    {"id": "windows",        "name": "Windows Yönetimi", "description": "WinRM bağlantısı, Event Log, Windows Update",
     "icon": "Shield",   "color": "blue",    "sort_order": 2},
    {"id": "virtualization", "name": "Sanallaştırma",    "description": "Hypervisor yönetimi, altyapı analizi (VMware, Proxmox, Hyper-V)",
     "icon": "Cloud",    "color": "indigo",  "sort_order": 3},
    {"id": "aiops",          "name": "AIOps",            "description": "Komuta Merkezi, Events, Incidents, Anomaly Detection, RCA, Baseline",
     "icon": "Brain",    "color": "purple",  "sort_order": 4},
    {"id": "ai_automation",  "name": "AI & Otomasyon",   "description": "AI Chat, AI Agent (çoklu platform otomasyonu)",
     "icon": "Bot",      "color": "cyan",    "sort_order": 5},
    {"id": "integrations",   "name": "Entegrasyonlar",   "description": "UCMDB statik import ve dış kaynak entegrasyonları",
     "icon": "FileUp",   "color": "orange",  "sort_order": 6},
    {"id": "level1",         "name": "İşletim Level 1",  "description": "Disk, ASM, LVM, servis, kullanıcı runbook'ları",
     "icon": "Wrench",   "color": "teal",    "sort_order": 7},
]
