"""chat_output_directives — /table, /json, /brief komut ayıklama testleri."""
from app.services.chat_output_directives import (
    OutputDirective,
    directive_system_addendum,
    extract_output_directive,
    render_rows_as_brief,
    render_rows_as_json,
)


def test_no_directive_returns_none_and_unchanged_message():
    msg, d = extract_output_directive("NVME_DS'de hangi vmler var?")
    assert d == OutputDirective.NONE
    assert msg == "NVME_DS'de hangi vmler var?"


def test_table_directive_extracted_and_stripped():
    msg, d = extract_output_directive("tüm vmleri /table göster")
    assert d == OutputDirective.TABLE
    assert "/table" not in msg
    assert "tüm vmleri" in msg and "göster" in msg


def test_json_directive():
    msg, d = extract_output_directive("/json datastore listesi")
    assert d == OutputDirective.JSON
    assert "/json" not in msg


def test_brief_directive_and_turkish_alias():
    msg, d = extract_output_directive("bu sunucunun durumu nedir /brief")
    assert d == OutputDirective.BRIEF
    msg2, d2 = extract_output_directive("/kısa özetle durumu")
    assert d2 == OutputDirective.BRIEF


def test_directive_case_insensitive_and_anywhere_in_message():
    msg, d = extract_output_directive("/TABLE tüm vmler")
    assert d == OutputDirective.TABLE


def test_no_false_positive_on_similar_words():
    # "/tablomsu" gibi bir kelime YANLIŞLIKLA /table olarak algılanmamalı.
    msg, d = extract_output_directive("/tablomsu bir görünüm istiyorum")
    assert d == OutputDirective.NONE
    assert "/tablomsu" in msg  # dokunulmadı


def test_multiple_directives_json_wins_over_table():
    msg, d = extract_output_directive("/table /json ver")
    assert d == OutputDirective.JSON
    assert "/table" not in msg and "/json" not in msg


def test_multiple_directives_table_wins_over_brief():
    msg, d = extract_output_directive("/brief /table ver")
    assert d == OutputDirective.TABLE


def test_directive_system_addendum_none_is_empty():
    assert directive_system_addendum(OutputDirective.NONE) == ""
    assert directive_system_addendum(None) == ""


def test_directive_system_addendum_mentions_command():
    assert "/table" in directive_system_addendum(OutputDirective.TABLE)
    assert "/json" in directive_system_addendum(OutputDirective.JSON)
    assert "brief" in directive_system_addendum(OutputDirective.BRIEF).lower() or "2-3" in directive_system_addendum(OutputDirective.BRIEF)


def test_render_rows_as_json_valid_json_block():
    import json as _json
    out = render_rows_as_json([{"name": "web01"}, {"name": "db02"}], meta={"kaynak": "db_list_vms"})
    assert out.startswith("```json")
    assert out.endswith("```")
    body = out[len("```json\n"):-len("\n```")]
    parsed = _json.loads(body)
    assert parsed["count"] == 2
    assert parsed["kaynak"] == "db_list_vms"
    assert parsed["items"][0]["name"] == "web01"


def test_render_rows_as_brief_lists_sample_and_total():
    rows = [{"name": f"vm{i}"} for i in range(9)]
    out = render_rows_as_brief(rows, subject="NVME_DS VM listesi")
    assert "toplam 9 kayıt" in out
    assert "vm0" in out
    assert "4 diğeri" in out  # 9 - 5 gösterilen = 4


def test_render_rows_as_brief_empty():
    out = render_rows_as_brief([], subject="NVME_DS VM listesi")
    assert "bulunamadı" in out


def test_render_rows_as_brief_extra_sentence():
    rows = [{"name": "web01"}]
    out = render_rows_as_brief(rows, subject="VM listesi", extra="Toplam disk: 120 GB.")
    assert "Toplam disk: 120 GB." in out
