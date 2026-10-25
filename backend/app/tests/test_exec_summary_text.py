"""Özet yer tutucudan basılır. Rakam yazan model şablona düşer."""
from app.services.exec_summary_text import compose_summary

FACTS = [{
    "report_type": "a2",
    "sections": [{
        "id": "a2",
        "numbers": {
            "powered_off": {"value": 29, "display": ["29", "29 VM"]},
            "wasted_vcpu": {"value": 126, "display": ["126", "126 vCPU"]},
            "wasted_ram_gb": {"value": 403.4, "display": ["403,4", "403,4 GB"]},
            "wasted_disk_gb": {"value": 5848, "display": ["5848", "5848 GB"]},
        },
    }],
}, {
    "report_type": "b2",
    "sections": [{
        "id": "b2",
        "numbers": {"hosts_needed": {"value": 0, "display": ["0", "0 host"]}},
    }],
}]


def test_placeholder_is_filled_and_passes_the_gate():
    out = compose_summary(
        FACTS,
        lambda _p: "Kapalı durumda {powered_off} VM, {wasted_vcpu} vCPU ve {wasted_ram_gb} GB RAM ayırıyor.",
    )
    assert out["source"] == "ai"
    assert out["text"] == "Kapalı durumda 29 VM, 126 vCPU ve 403,4 GB RAM ayırıyor."
    assert "{" not in out["text"]


def test_invented_digit_falls_back_to_a_sentence():
    out = compose_summary(FACTS, lambda _p: "Toplam 99 VM var.")
    assert out["source"] == "template"
    assert "29" in out["text"]
    assert "99" not in out["text"]
    assert "ek sunucu ihtiyacı görünmüyor" in out["text"]
