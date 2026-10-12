"""Tüm sohbet akışlarının sistem prompt'una eklenen ortak kurallar (Dilim T)."""
from __future__ import annotations

# Değişmez kural: sayılar deterministiktir, LLM yalnız anlatır. Metin unified_tool_chat.SYSTEM_PROMPT ile aynıdır.
NUMBER_RULE_TR = (
    "SAYI KURALI: Sayı, oran, tarih, RPO/RTO, tahmin, yerleşim veya senaryo sonucunu SEN "
    "hesaplama/türetme; yalnızca araç sonucunda veya BAĞLAM'da yazılı değeri aynen aktar. "
    "Araç sonucunda/BAĞLAM'da olmayan bir değeri söyleme — 'veri yok' de. Araç sonucuna "
    "dayanmayan genel bilgi veriyorsan bunu açıkça 'genel bilgi' diye belirt."
)
