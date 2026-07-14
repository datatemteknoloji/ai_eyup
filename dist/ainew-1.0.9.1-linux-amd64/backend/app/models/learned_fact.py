"""
Sunucular hakkinda SSH/WinRM ile toplanan YAPISAL/SABIT bilgileri (OS, kernel,
disk/mount duzeni, guvenlik yapilandirmasi, donanim vb.) kalici olarak saklar.

ONEMLI: Burada sadece "kolay kolay degismeyen" bilgiler tutulur — anlik CPU/RAM/
disk kullanim yuzdesi, calisan process listesi, log kayitlari gibi degisken
(volatile) veriler ASLA bu tabloya yazilmaz; onlar her zaman canli SSH/WinRM'den
gelir (bkz. app/services/fact_learning.py'deki whitelist).

Boylece AI, "sordukca arastirdikca ortami ogrenen" bir yapiya kavusur: aynı
sunucu icin ayni yapisal bilgi tekrar tekrar SSH ile cekilmek zorunda kalmaz,
ve canli SSH basarisiz/zaman asimina ugrarsa en son bilinen deger (tarihiyle
birlikte, "X gun once dogrulandi" seklinde) dusmemis bir cevap saglar.
"""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class LearnedFact(Base):
    __tablename__ = "learned_facts"
    __table_args__ = (
        UniqueConstraint("server_id", "category", "key", name="uq_learned_fact_server_category_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    server_id = Column(Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True)

    category = Column(String(50), nullable=False, index=True)  # "kernel", "os", "disk", "security", ...
    key = Column(String(200), nullable=False)                  # "kernel_version", "selinux_status", ...
    value = Column(Text, nullable=False)

    # ssh | winrm | manual (admin Bilgi Bankasi ekranindan duzenlerse)
    source = Column(String(20), default="ssh", nullable=False)

    first_learned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_confirmed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    times_confirmed = Column(Integer, default=1, nullable=False)
    # value son onaylamada degisti mi? (ayni kaldiysa times_confirmed artar,
    # degistiyse first_learned_at da guncellenir — "yeniden ogrenildi" sayilir)
    confidence = Column(Float, default=1.0, nullable=False)

    server = relationship("Server")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "first_learned_at": self.first_learned_at.isoformat() if self.first_learned_at else None,
            "last_confirmed_at": self.last_confirmed_at.isoformat() if self.last_confirmed_at else None,
            "times_confirmed": self.times_confirmed,
            "confidence": self.confidence,
        }
