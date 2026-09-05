"""
"<varlık> durumu nedir / sağlıklı mı" soruları KAVRAMSAL değildir.

Bu sorular "nedir" grameri yüzünden CONCEPTUAL sınıfına düşüyordu; kavramsal
dal envanteri ve araç kanıtını prompt'a hiç koymadığı için model dürüstçe
"canlı veri dönmedi" cevabı veriyordu — kullanıcının bildirdiği asıl şikâyet.
Gerçek tanım soruları ise kavramsal kalmalı.
"""
import pytest

from app.services.chat_intent import ChatIntentKind, classify_chat_intent


@pytest.mark.parametrize("question", [
    "vCenter'ın sağlık durumu nedir?",
    "vCenter sağlıklı mı?",
    "ortamda problem var mı?",
    "cluster durumu nedir?",
    "hangi hostlarda sorun var?",
    "datastore'larda risk var mı?",
    "ESXi host performans durumu nasıl?",
])
def test_environment_state_questions_are_not_conceptual(question):
    assert classify_chat_intent(question).kind is not ChatIntentKind.CONCEPTUAL


@pytest.mark.parametrize("question", [
    "snapshot nedir?",
    "vMotion ile Storage vMotion farkı nedir?",
    "bir VM yavaşlıyorsa hangi metriklere bakarsın?",
])
def test_real_definition_questions_stay_conceptual(question):
    assert classify_chat_intent(question).kind in (
        ChatIntentKind.CONCEPTUAL, ChatIntentKind.MIXED,
    )


def test_definition_question_without_state_word_is_not_treated_as_inventory():
    # "DRS nasıl çalışır?" — Türkçe ek yüzünden eğitim regexine takılmıyor;
    # yine de envanter/canlı sorgusu SAYILMAMALI (boşuna araç çağrısı olmasın).
    assert classify_chat_intent("DRS nasıl çalışır?").kind in (
        ChatIntentKind.CONCEPTUAL, ChatIntentKind.GENERAL,
    )


def test_measurable_attribute_rule_still_applies():
    intent = classify_chat_intent("snapshotların boyutları nedir?")
    assert intent.kind is not ChatIntentKind.CONCEPTUAL
