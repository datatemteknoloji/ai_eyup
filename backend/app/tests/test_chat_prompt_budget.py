"""Chat prompt'ları TOPLAM olarak model penceresine sığmalı.

Regresyon: eskiden yalnızca BAGLAM bölümü bütçelenirdi (context'e tek başına
tüm input bütçesi verilirdi); persona + kurallar + geçmiş + soru üstüne
eklendiğinde toplam 32K sınırını aşıp gateway'den "context length exceeded"
alınıyordu. Artık üç chat yolu da `budget_sections` üzerinden geçiyor.
"""
import pytest

import app.services.llm_context_budget as b


@pytest.fixture(autouse=True)
def _cap_32k(monkeypatch):
    monkeypatch.setattr(b, "get_gateway_hard_cap_tokens", lambda: 32768)
    monkeypatch.setattr(b, "get_context_token_budget", lambda: 32768)


# Bölüm başlıkları ("BAGLAM:\n" vb.) bütçe dışıdır — küçük pay bırakılır.
_HEADER_SLACK = 200


def _limit() -> int:
    return b.get_input_token_budget() + _HEADER_SLACK


def test_unified_prompt_fits_and_keeps_question():
    from app.api.unified_chat import _build_prompt

    prompt = _build_prompt(
        "disk doluyor mu?",
        "ENVANTER DUMP " + "X" * 400000,   # ~130K token'lık bağlam
        "TOPLAMA: 5 sunucu",
        "ONCEKI: " + "H" * 60000,
        None,
    )
    assert b.estimate_tokens(prompt) <= _limit()
    assert "KULLANICI SORUSU: disk doluyor mu?" in prompt
    assert prompt.rstrip().endswith("YANIT (Markdown, Türkçe):")


def test_windows_prompt_fits_and_keeps_question():
    from app.api.windows_chat import _build_prompt

    prompt = _build_prompt(
        "hangi sunucuda yama eksik?",
        "WINRM DUMP " + "X" * 400000,
        True,
        3,
        ["WIN-A", "WIN-B"],
        "ONCEKI: " + "H" * 60000,
        None,
    )
    assert b.estimate_tokens(prompt) <= _limit()
    assert "KULLANICI SORUSU: hangi sunucuda yama eksik?" in prompt
    assert prompt.rstrip().endswith("YANIT (Markdown, Turkce):")


def test_linux_prompt_fits_and_keeps_question():
    from app.api.chat import _build_prompt

    prompt = _build_prompt(
        "load average neden yüksek?",
        "SSH DUMP " + "X" * 400000,
        True,
        2,
        False,
        ["srv1", "srv2"],
        "ONCEKI: " + "H" * 60000,
        "linux",
        None,
    )
    assert b.estimate_tokens(prompt) <= _limit()
    assert "KULLANICI SORUSU: load average neden yüksek?" in prompt
    assert prompt.rstrip().endswith("YANIT (Markdown, Turkce):")


def test_small_context_is_not_truncated():
    from app.api.unified_chat import _build_prompt

    prompt = _build_prompt("kaç sunucu var?", "Sunucu sayısı: 12", "", "", None)
    assert "Sunucu sayısı: 12" in prompt
    assert "context kısaltıldı" not in prompt


def test_unified_diagram_directive_still_asks_turkish():
    from app.api.unified_chat import _build_prompt
    from app.services.chat_output_directives import OutputDirective

    prompt = _build_prompt(
        "tüm mimariyi göster",
        "Sunucu sayısı: 12",
        "",
        "",
        OutputDirective.DIAGRAM,
    )
    assert prompt.rstrip().endswith("YANIT (Markdown, Türkçe):")
    assert "What it shows" in prompt
    assert "Ne gösteriyor" in prompt
