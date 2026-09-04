"""chat_path_policy.is_knowledge_only / resolve_live_path — chat_intent entegrasyonu.

Bağlam: virt sohbetinde düzeltilen "kavramsal soru → yanlışlıkla envanter/canlı
tarama tetiklenmesi" hatası, Linux/Windows/Unified'ın da kullandığı paylaşılan
resolve_live_path() üzerinden bu üç platforma da yayılıyor.
"""
from app.services.chat_path_policy import is_knowledge_only, resolve_live_path


TROUBLESHOOTING_METHOD_Q = (
    "Bir VM'de uygulama zaman zaman yavaşlıyor. CPU %30, RAM %50, disk latency 5 ms. "
    "Ancak kullanıcılar 10–20 saniyelik gecikmeler yaşıyor. "
    "Hangi metrikleri ve hangi katmanları incelersin?"
)


def test_troubleshooting_methodology_question_is_knowledge_only():
    """'incelersin' / 'yavaşlıyor' _LIVE_BLOCK_KEYWORDS'te değil ama _KNOWLEDGE_HINTS'te de
    yok — chat_intent CONCEPTUAL sınıflandırması olmadan bu False dönerdi."""
    assert is_knowledge_only(TROUBLESHOOTING_METHOD_Q) is True


def test_generic_hangi_katman_question_is_knowledge_only():
    # "neden" kelimesi _LIVE_BLOCK_KEYWORDS içinde — chat_intent override etmeli.
    q = "Bir sunucu neden yavaşlar, hangi katmanlara bakılır?"
    assert is_knowledge_only(q) is True


def test_real_live_diagnosis_request_is_not_knowledge_only():
    # "kök neden" -> is_deep_live_query zaten canlı gerektirir (chat_intent'ten önce).
    assert is_knowledge_only("web01 sunucusunda kök neden analizi yap, CPU çok yüksek") is False


def test_explicit_fleet_check_not_knowledge_only():
    assert is_knowledge_only("sunucularımızı kontrol et, hangi servisler down?") is False


def test_plain_conceptual_definition_question_is_knowledge_only():
    assert is_knowledge_only("Load average nedir, nasıl yorumlanır?") is True


def test_resolve_live_path_skips_collect_and_agentic_for_conceptual_question():
    decision = resolve_live_path(
        TROUBLESHOOTING_METHOD_Q,
        agentic_enabled=True,
        wants_fixed_collect=True,
        has_live_targets=True,
    )
    assert decision.run_fixed_collect is False
    assert decision.run_agentic is False
    assert decision.reason == "knowledge_only"


def test_resolve_live_path_still_runs_agentic_for_live_fleet_question():
    decision = resolve_live_path(
        "sunucularımızı kontrol et, hangi servisler down?",
        agentic_enabled=True,
        wants_fixed_collect=True,
        has_live_targets=True,
    )
    assert decision.run_fixed_collect is False  # XOR: agentic açıkken collect atlanır
    assert decision.run_agentic is True
