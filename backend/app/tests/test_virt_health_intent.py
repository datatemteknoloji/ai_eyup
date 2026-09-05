"""
Genel sağlık/durum sorularının deterministik handler'a yönlenmesi.

Üretimde "vCenter'ın sağlık durumu nedir?" hiçbir QA kuralına uymuyordu; model
araç çağırmadan "canlı veri mevcut değil" cevabı üretiyordu. Bu testler aynı
anlama gelen doğal ifadelerin sağlık handler'ına gitmesini, host'a özel veya
başka konudaki soruların ise BU handler'a KAÇMAMASINI güvenceye alır.
"""
import re

import pytest

from app.services.hypervisor_intelligence import (
    QA_RULES, _normalize_virt_question, h_virt_health_overview,
)


def _matched_handler(question: str):
    q = _normalize_virt_question(question)
    for pattern, handler in QA_RULES:
        if re.search(pattern, q, re.IGNORECASE):
            return handler
    return None


@pytest.mark.parametrize("question", [
    "vCenter'ın sağlık durumu nedir?",
    "vcenter'ın sağlım durumu nedir?",          # yaygın yazım hatası
    "vCenter sağlıklı mı?",
    "vCenter'ın durumu nasıl?",
    "Ortamda problem var mı?",
    "Bir sorun görüyor musun?",
    "Yönetici olarak bilmem gereken bir şey var mı?",
    "vCenter ortamımın genel sağlık durumunu değerlendir",
    "ortamın genel risk seviyesini değerlendir",
    "sistemin durumu ne?",
])
def test_general_health_questions_route_to_health_handler(question):
    assert _matched_handler(question) is h_virt_health_overview


@pytest.mark.parametrize("question", [
    "Hangi ESXi hostlarda problem var ve VM'lere etkisi nedir?",
    "kaç VM var?",
    "Kapasite raporu göster",
    "datastore doluluk durumu",
    "snapshot boyutu ne kadar?",
    "192.168.1.101 üzerindeki VM'leri listele",
])
def test_specific_questions_do_not_hijack_health_handler(question):
    assert _matched_handler(question) is not h_virt_health_overview
