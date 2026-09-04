"""Çok kaynaklı sohbet yanıtlarında katman etiketleme — tek doğruluk kaynağı.

Amaç: Linux/Windows/Prometheus/vCenter/OpenShift/RAG gibi farklı SoT'lardan
gelen metin bloklarının chat.py / windows_chat.py / unified_chat.py içinde
HER YERDE aynı başlıkla etiketlenmesi (kopyala-yapıştır metin sürüklenmesin).

Mevcut metinler kasıtlı olarak DEĞİŞTİRİLMEDİ (persona addendum'larda birebir
alıntılanıyorlar, bkz. unified_chat.py) — yalnızca tek fonksiyona taşındı.
Yeni katman anahtarları (ör. openshift_db) ileride eklenecek entegrasyonlar
için hazır bırakıldı.
"""
from __future__ import annotations

from typing import Optional

# key -> görüntülenen başlık (mevcut metinlerle birebir aynı, geriye dönük uyumlu)
LAYER_LABELS = {
    "linux_ssh": "LINUX SUNUCULARDAN ALINAN GERCEK VERILER (SSH)",
    "windows_winrm": "WINDOWS SUNUCULARDAN ALINAN GERCEK VERILER (WinRM)",
    "ssh": "SUNUCULARDAN ALINAN GERCEK VERILER (SSH)",
    "ssh_agentic": "SUNUCULARDAN ALINAN GERCEK VERILER (SSH, agentic fallback)",
    "winrm": "SUNUCULARDAN ALINAN GERCEK VERILER (WinRM)",
    "prometheus": "PROMETHEUS CANLI METRIKLER",
    "db_virt": "VCENTER/ESXI ENVANTERI (DATABASE)",
    "vcenter_live": "VCENTER CANLI SORGU (SOAP/API)",
    "openshift_db": "OPENSHIFT NODE/PROJE ENVANTERI (DATABASE)",
    "openshift_live": "OPENSHIFT CANLI SORGU (API)",
    "rag_runbook": "RUNBOOK",
    "rag_incidents": "BENZER OLAYLAR",
    "rag_metrics": "METRIK ACIKLAMALARI",
    "rag_knowledge": "BILGI BANKASI / RAG",
}


def layer_header(key: str) -> str:
    """Katman anahtarına karşılık gelen (Türkçe, mevcut konvansiyonla uyumlu) başlık."""
    return LAYER_LABELS.get(key, key.upper())


def wrap_layer(key: str, body: str, *, suffix: Optional[str] = None) -> str:
    """'BAŞLIK:\\nmetin' bloğu üretir — chat.py/windows_chat.py/unified_chat.py'de

    context_parts.append(...) çağrılarının tek noktadan beslendiği yardımcı.
    body boşsa "" döner (çağıran taraf zaten `if body:` ile koruyor).
    """
    text = (body or "").strip()
    if not text:
        return ""
    header = layer_header(key) + (f" {suffix}" if suffix else "")
    return f"{header}:\n{text}"
