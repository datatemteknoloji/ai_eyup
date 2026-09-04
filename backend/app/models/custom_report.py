"""
Özel Rapor Tanımı (Custom Report Definition)
=============================================

Kullanıcı chat/keşif akışında (bkz. `app.services.custom_report_engine`) bir
soruyu READ_ONLY agentic tool-loop ile çözer, sonuçtan memnun kalırsa o turda
çağrılan TAM (tool_name, tool_args) çiftini burada "dondurur". Sonraki her
çalıştırmada LLM'e HİÇ gidilmez — aynı araç aynı argümanlarla yeniden
çalıştırılır (deterministik, tekrarlanabilir, düşük hata payı).

Yetki: bu özelliği KULLANMA (oluşturma/çalıştırma/silme) yetkisi `custom_reports`
modülüne bağlıdır (bkz. app.models.module.DEFAULT_MODULES). Varsayılan olarak
sadece admin'de vardır; Kullanıcı Yönetimi sayfasından diğer kullanıcılara da
atanabilir (mevcut modül atama mekanizmasıyla aynı).
"""
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
)
from sqlalchemy.sql import func

from app.core.database import Base


class CustomReportDefinition(Base):
    __tablename__ = "custom_report_definitions"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Hangi sohbet/tool kapsamı: linux | windows | virt | openshift | exadata | unified
    platform = Column(String(32), nullable=False, index=True)

    # Dondurulan çağrı — kayıttan sonra HER çalıştırmada birebir aynı kullanılır.
    tool_name = Column(String(128), nullable=False)
    tool_args = Column(JSON, nullable=False, default=dict)

    # Kullanıcının /table, /json, /brief seçimi (chat_output_directives.OutputDirective)
    output_directive = Column(String(16), nullable=True, default="table")

    # Denetim/izlenebilirlik: raporun hangi doğal-dil sorudan doğduğu
    source_question = Column(Text, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True, nullable=False)

    # Son çalıştırma önbelleği — liste ekranında LLM/tool'a gitmeden hızlı önizleme.
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_ok = Column(Boolean, nullable=True)
    last_rendered = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)
