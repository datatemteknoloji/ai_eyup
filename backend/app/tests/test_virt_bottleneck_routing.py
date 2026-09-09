"""'Neden yavaş' sorularının teşhis handler'ına gitmesi (QA_RULES sırası).

Bu sorular eskiden `h_cpu_ready` gibi TEK sayaç listeleyen kurallara düşüyordu;
operatör "ready %12" görüyor ama suçlunun VM mi host mu olduğunu öğrenemiyordu.
Kural sırası bozulursa (teşhis kuralı cpu_ready'nin altına kayarsa) bu regresyon
sessizce geri gelir — burada sıra sabitlenir.
"""
import re

import pytest

from app.services.hypervisor_intelligence import (
    QA_RULES, _normalize_virt_question, h_bottleneck_diagnose, h_cpu_ready,
)


def _route(question: str):
    q = _normalize_virt_question(question)
    for pattern, handler in QA_RULES:
        if re.search(pattern, q, re.IGNORECASE):
            return getattr(handler, "__name__", "?")
    return None


@pytest.mark.parametrize("question", [
    "app01 vm'i neden yavaş?",
    "Bu VM niye bu kadar yavaş çalışıyor?",
    "Yavaşlık sebebi ne olabilir",
    "Sorun VM'de mi host'ta mı?",
    "Ortamda darboğaz var mı",
    "bottleneck nerede",
    "kaynak çekişmesi yaşayan vm'ler hangileri",
    "hangi vm'ler kaynak bekliyor",
    "bu vm'e vcpu ekleyelim mi",
    "db01 için CPU contention durumu ne",
])
def test_slowness_questions_route_to_diagnosis(question):
    assert _route(question) == h_bottleneck_diagnose.__name__


@pytest.mark.parametrize("question", [
    "CPU ready değerlerini göster",
    "ready time listesi",
])
def test_plain_counter_questions_still_go_to_cpu_ready(question):
    """Salt sayaç isteği teşhis motoruna kaçmamalı — kullanıcı liste istiyor."""
    assert _route(question) == h_cpu_ready.__name__


def test_diagnosis_rule_precedes_cpu_ready_rule():
    names = [getattr(h, "__name__", "") for _, h in QA_RULES]
    assert names.index(h_bottleneck_diagnose.__name__) < names.index(h_cpu_ready.__name__)


def test_health_questions_are_not_hijacked_by_diagnosis():
    """'Sorun var mı' genel sağlık sorusu; teşhis kuralı bunu yutmamalı."""
    assert _route("ortamda problem var mı") == "h_virt_health_overview"
    assert _route("vcenter sağlıklı mı") == "h_virt_health_overview"
