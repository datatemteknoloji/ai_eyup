"""Sayı kapısı: display ile birebir, label rakamı sayı değil, A1 sayısız metin yok."""
from app.services.number_gate import check_text

FACTS = {
    "sections": [{
        "id": "a1",
        "numbers": {
            "findings": {"value": 12, "unit": "adet", "display": ["12", "12 adet"]},
            "cpu": {"value": 72.4, "unit": "%", "display": ["72,4", "%72,4", "%72,4"]},
            "period": {"value": "2026-10-01", "unit": "date", "display": ["2026-10-01"]},
        },
        "labels": {"host": "esx03", "site": "Edirne, bay 9"},
    }, {
        "id": "b1",
        "numbers": {"days": {"value": 14, "unit": "gün", "display": ["14", "14 gün"]}},
        "labels": {},
    }],
}


def test_exact_display_and_label_digits_pass():
    text = "Edirne, bay 9 üzerindeki esx03 için 12 adet bulgu var. Dönem 2026-10-01, doluluk %72,4."
    result = check_text(text, FACTS, section_id="a1", require_number=True)
    assert result["ok"] is True
    assert "03" not in result["found"]
    assert "9" not in result["found"]


def test_invented_number_rejected():
    result = check_text("13 adet bulgu var.", FACTS, section_id="a1", require_number=True)
    assert result["ok"] is False
    assert "13" in result["rejected"] or "13 adet" in result["rejected"]


def test_wrong_rounding_and_foreign_form_rejected():
    assert check_text("Doluluk 72.", FACTS, section_id="a1")["ok"] is False
    assert check_text("Doluluk 72.4.", FACTS, section_id="a1")["ok"] is False
    assert check_text("Doluluk %72.", FACTS, section_id="a1")["ok"] is False


def test_date_not_in_facts_rejected():
    result = check_text("Dönem 2026-11-01.", FACTS, section_id="a1")
    assert result["ok"] is False
    assert "2026-11-01" in result["rejected"]


def test_a1_numberless_text_rejected_other_section_passes():
    prose = "Bakım penceresi uygun, ek yorum yok."
    assert check_text(prose, FACTS, section_id="a1", require_number=True)["ok"] is False
    assert check_text(prose, FACTS, section_id="b1", require_number=False)["ok"] is True


def test_allowed_duration_passes():
    assert check_text("Örnek 14 gün.", FACTS, section_id="b1")["ok"] is True


def test_compact_and_split_period_are_labels():
    facts = {
        "period": {"start": "2026-10-01", "end": "2026-11-01"},
        "sections": FACTS["sections"],
    }
    text = "Dönem 20261001, 01/10/2026, 01.10.2026. Yıl 2026. Bulgu 12 adet."
    assert check_text(text, facts, section_id="a1", require_number=True)["ok"] is True
    assert check_text("Ay 10 gün 01.", facts, section_id="a1")["ok"] is False


def test_period_timestamp_is_masked_and_bare_zero_is_not():
    facts = {
        "period": {"start": "2026-10-01T00:00:00+00:00", "end": "2026-11-01T00:00:00+00:00"},
        "sections": FACTS["sections"],
    }
    copied = "Dönem 2026-10-01T00:00:00+00:00 ile 2026-11-01 arasında 12 adet."
    assert check_text(copied, facts, section_id="a1", require_number=True)["ok"] is True
    assert check_text("Tam 00 olay.", facts, section_id="a1")["ok"] is False


def test_thousands_separator_matches_the_integer_display():
    facts = {"sections": [{"id": "a1", "numbers": {"events": {"display": ["533816", "533816 adet"]}}, "labels": {}}]}
    assert check_text("Dönemde 533.816 olay ve 533,816 adet.", facts, section_id="a1")["ok"] is True
    assert check_text("Doluluk 72.4.", FACTS, section_id="a1")["ok"] is False


def test_sibling_display_passes_only_for_the_whole_report():
    text = "Özette 12 adet, kapasitede 14 gün."
    assert check_text(text, FACTS, section_id="a1")["ok"] is False
    assert check_text(text, FACTS, section_id="a1", all_sections=True)["ok"] is True
