"""Kapıdan geçmeyen AI metni yayımlanmaz."""
from app.services.exec_commentary import prompt_payload, publish_commentary

FACTS = {
    "report_type": "a1",
    "period": {"start": "2026-10-01", "end": "2026-10-31"},
    "sections": [{
        "id": "a1",
        "title": "Aylık özet",
        "status": "ok",
        "numbers": {"events": {"value": 12, "unit": "adet", "display": ["12", "12 adet"]}},
        "labels": {"risk_1": "esx03"},
        "notes": [],
        "rows": [{"vm": "should-not-be-sent", "cpu": 99}],
    }],
}


def test_prompt_period_drops_the_clock():
    facts = dict(FACTS)
    facts["period"] = {"start": "2026-10-01T00:00:00+00:00", "end": "2026-11-01T00:00:00+00:00"}
    payload = prompt_payload(facts)
    assert payload["period"] == {"start": "2026-10-01", "end": "2026-11-01"}
    assert "00:00:00" not in str(payload)


def test_prompt_has_numbers_and_labels_not_vm_rows():
    payload = prompt_payload(FACTS)
    assert payload["sections"][0]["numbers"]["events"]["display"] == ["12", "12 adet"]
    assert payload["sections"][0]["labels"]["risk_1"] == "esx…"
    assert not any(ch.isdigit() for ch in payload["sections"][0]["labels"]["risk_1"])
    assert "rows" not in payload["sections"][0]
    assert "should-not-be-sent" not in str(payload)


def test_good_text_is_published():
    out = publish_commentary(FACTS, "a1", lambda _p: "Dönemde 12 adet olay var. Öne çıkan esx03.", require_number=True)
    assert out["source"] == "ai"
    assert out["published"].startswith("Dönemde")
    assert out["attempts"] == 1


def test_rejected_text_is_not_published():
    calls = {"n": 0}

    def generate(_prompt: str) -> str:
        calls["n"] += 1
        return "Dönemde 99 adet olay var."

    out = publish_commentary(FACTS, "a1", generate, require_number=True)
    assert calls["n"] == 2
    assert out["published"] is None
    assert out["source"] == "template"
    assert "12" in out["fallback"]
    assert "99" not in out["fallback"]


def test_second_attempt_can_pass():
    calls = {"n": 0}

    def generate(_prompt: str) -> str:
        calls["n"] += 1
        return "99 olay" if calls["n"] == 1 else "12 adet olay, esx03."

    out = publish_commentary(FACTS, "a1", generate, require_number=True)
    assert out["source"] == "ai"
    assert out["attempts"] == 2
    assert "12 adet" in out["published"]
