"""
Kanıt guard'ı: araç çıktısı varken "canlı sorguda kayıt dönmedi" cevabı
kullanıcıya gitmemeli. Üretimde bu cümle, araç gerçekten veri döndürdüğü
halde görülüyordu ve sorunu yanlış yere yönlendiriyordu.
"""
from app.services.chat_coverage import looks_like_no_data_answer
from app.services.hypervisor_intelligence import (
    _answer_ignores_evidence, _has_tool_evidence, _render_tool_evidence_fallback,
    _tool_evidence_block,
)

EVIDENCE = (
    "vCenter sağlık durumu nedir?\n\n"
    "[CANLI ARAÇ SONUÇLARI — yanıtında bunları esas al]\n"
    '[Sanallaştırma sağlık özeti]\n{"ok": true, "health": {"score": 50, '
    '"label": "Sorunlu"}, "critical_hosts": [{"host": "192.168.1.101", '
    '"mem_pct": 95.5, "overall_status": "red"}]}'
)


def test_evidence_block_extracted_without_header():
    block = _tool_evidence_block(EVIDENCE)
    assert block.startswith("[Sanallaştırma sağlık özeti]")
    assert "192.168.1.101" in block


def test_question_without_evidence_is_not_guarded():
    assert not _has_tool_evidence("vCenter sağlık durumu nedir?")
    assert _tool_evidence_block("vCenter sağlık durumu nedir?") == ""


def test_empty_evidence_block_is_not_guarded():
    assert not _has_tool_evidence(
        "soru\n\n[CANLI ARAÇ SONUÇLARI — yanıtında bunları esas al]\n"
    )


def test_real_evidence_triggers_guard():
    assert _has_tool_evidence(EVIDENCE)


def test_fallback_shows_real_data_instead_of_no_data_sentence():
    out = _render_tool_evidence_fallback(EVIDENCE)
    assert "192.168.1.101" in out
    assert not looks_like_no_data_answer(out)


def test_model_paraphrases_of_no_data_are_detected():
    for text in (
        "Canlı sorguda kayıt dönmedi.",
        "Sorguda vCenter'ın sağlık durumu bilgisi bulunamadı.",
        "Bu konuda canlı veri mevcut değil.",
        "İlgili kayıt bulunamadı.",
        "Sağlık bilgisi yer almıyor.",
        "vCenter sağlık durumu sorgusu sonucunda canlı veri alınamadı.",
        "İlgili bilgi döndürülemedi.",
    ):
        assert looks_like_no_data_answer(text), text


def test_normal_answers_are_not_flagged_as_no_data():
    for text in (
        "192.168.1.101 hostunda RAM %95.5 seviyesinde, sensör durumu red.",
        "3 datastore var; datastore2 %87.9 dolu.",
        "Cluster bulunmadığı için HA yapılandırması yok.",
    ):
        assert not looks_like_no_data_answer(text), text


def test_short_answer_without_any_evidence_value_is_rejected():
    """Kalıp listesi yetmiyor: model her turda yeni bir ret cümlesi uyduruyor.
    İçerik ölçütü — kanıttaki hiçbir sayı cevapta yoksa kanıt kullanılmamıştır."""
    evidence = _tool_evidence_block(EVIDENCE)
    assert _answer_ignores_evidence(
        "vCenter bağlantısı sağlanamadı; sağlık raporu gelmedi.", evidence,
    )


def test_answer_quoting_evidence_values_is_accepted():
    evidence = _tool_evidence_block(EVIDENCE)
    assert not _answer_ignores_evidence(
        "192.168.1.101 hostunda RAM 95.5 seviyesinde, sağlık skoru 50.", evidence,
    )


def test_long_narrative_answers_are_not_second_guessed():
    evidence = _tool_evidence_block(EVIDENCE)
    long_answer = "Ortam değerlendirmesi. " * 40
    assert not _answer_ignores_evidence(long_answer, evidence)


def test_guard_needs_enough_anchors_to_judge():
    assert not _answer_ignores_evidence("veri yok", "sadece metin, iki 12 anchor")


def test_fallback_truncates_long_evidence():
    long_q = EVIDENCE + "x" * 20000
    out = _render_tool_evidence_fallback(long_q, max_chars=500)
    assert "kısaltıldı" in out
    assert len(out) < 1200
