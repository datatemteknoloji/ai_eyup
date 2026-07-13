"""
Sunucularda otomatik olarak tespit edilen uygulama/servisleri (Oracle DB,
PostgreSQL, MySQL/MariaDB, MSSQL, Nginx/Apache/IIS, Tomcat, Redis, MongoDB,
Kafka, Docker/Kubernetes vb.) kalıcı olarak saklar.

Akış (bkz. app/services/app_discovery.py):
  1. Periyodik arka plan görevi (veya manuel "Yeniden Tara") her sunucuda SSH/WinRM
     ile port/process/servis/paket taraması yapar ve bilinen imzalarla (fingerprint)
     eşleştirir.
  2. Eşleşen her uygulama bu tabloya upsert edilir: ilk görüldüğünde yeni satır,
     tekrar görüldüğünde last_seen_at/times_confirmed güncellenir.
  3. Bir taramada artık görülmeyen (önceden kayıtlı) uygulamalar silinmez, "stopped"
     durumuna çekilir — böylece geçmiş görülebilir, veri kaybı olmaz.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class DiscoveredApplication(Base):
    __tablename__ = "discovered_applications"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_discovered_app_server_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(120), nullable=False, index=True)      # "PostgreSQL", "Nginx", "Oracle Database", ...
    category = Column(String(40), nullable=False, index=True)   # database | webserver | appserver | cache |
                                                                   # messaging | container_platform | other
    version = Column(String(120), nullable=True)
    port = Column(Integer, nullable=True)
    process_or_service = Column(String(200), nullable=True)      # process/servis adı (evidence icin)
    detection_method = Column(String(30), nullable=True)         # process | service | port | package | registry
    evidence = Column(Text, nullable=True)                       # ham cikti kirintisi (debug/citation)

    status = Column(String(20), default="running", nullable=False)  # running | stopped
    source = Column(String(20), default="ssh", nullable=False)      # ssh | winrm | manual

    first_detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    times_confirmed = Column(Integer, default=1, nullable=False)

    server = relationship("Server")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "port": self.port,
            "process_or_service": self.process_or_service,
            "detection_method": self.detection_method,
            "evidence": self.evidence,
            "status": self.status,
            "source": self.source,
            "first_detected_at": self.first_detected_at.isoformat() if self.first_detected_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "times_confirmed": self.times_confirmed,
        }
