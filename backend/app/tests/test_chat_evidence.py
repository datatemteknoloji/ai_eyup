"""Unified + ortak kanıt guard — virt ile aynı karar, final stream paritesi."""
from app.services.chat_coverage import looks_like_no_data_answer
from app.services.chat_evidence import (
    answer_ignores_evidence,
    collect_unified_live_evidence,
    has_meaningful_evidence,
    maybe_fix_no_data_answer,
    needs_evidence_retry,
    render_raw_evidence_fallback,
    retry_answer_is_usable,
)

EVIDENCE = (
    '[Sanallaştırma sağlık özeti]\n{"ok": true, "health": {"score": 50, '
    '"label": "Sorunlu"}, "critical_hosts": [{"host": "192.168.1.101", '
    '"mem_pct": 95.5, "overall_status": "red"}]}'
)


def test_collect_ignores_short_and_rag_sized_noise():
    assert collect_unified_live_evidence(tool_text="ok", linux_ctx="x") == ""
    big = EVIDENCE + " " * 20
    got = collect_unified_live_evidence(tool_text=big, linux_ctx="kısa")
    assert "192.168.1.101" in got
    assert "kısa" not in got


def test_needs_retry_when_no_data_phrase_and_evidence():
    assert has_meaningful_evidence(EVIDENCE)
    assert needs_evidence_retry("Bu konuda canlı veri mevcut değil.", EVIDENCE)


def test_no_retry_without_evidence():
    assert not needs_evidence_retry("Bu konuda canlı veri mevcut değil.", "")
    assert not needs_evidence_retry("Bu konuda canlı veri mevcut değil.", "kısa")


def test_retry_usable_vs_second_no_data():
    good = "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."
    assert retry_answer_is_usable(good, EVIDENCE)
    assert not retry_answer_is_usable("Canlı veri mevcut değil.", EVIDENCE)
    assert not retry_answer_is_usable("", EVIDENCE)


def test_maybe_fix_uses_retry_when_model_recovers():
    def _gen(**kwargs):
        return {"response": "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."}

    out, reason = maybe_fix_no_data_answer(
        answer="Bu konuda canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="BAGLAM:\n" + EVIDENCE,
        model="test",
        generate_sync=_gen,
    )
    assert reason == "retry"
    assert "192.168.1.101" in out
    assert not looks_like_no_data_answer(out)


def test_maybe_fix_falls_back_when_retry_still_no_data():
    def _gen(**kwargs):
        return {"response": "Hâlâ canlı veri mevcut değil."}

    out, reason = maybe_fix_no_data_answer(
        answer="Bu konuda canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=_gen,
    )
    assert reason == "fallback"
    assert "192.168.1.101" in out
    assert not looks_like_no_data_answer(out)


def test_maybe_fix_falls_back_when_generate_raises():
    def _gen(**kwargs):
        raise RuntimeError("llm down")

    out, reason = maybe_fix_no_data_answer(
        answer="Canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=_gen,
    )
    assert reason == "fallback"
    assert "192.168.1.101" in out


def test_maybe_fix_noop_when_answer_uses_evidence():
    good = "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."
    out, reason = maybe_fix_no_data_answer(
        answer=good,
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=lambda **k: {"response": "should not run"},
    )
    assert reason == ""
    assert out == good


def test_fallback_truncates():
    out = render_raw_evidence_fallback(EVIDENCE + "x" * 20000, max_chars=500)
    assert "kısaltıldı" in out
    assert len(out) < 1200


def test_ignore_heuristic_matches_virt_guard():
    assert answer_ignores_evidence(
        "vCenter bağlantısı sağlanamadı; sağlık raporu gelmedi.", EVIDENCE,
    )
    assert not answer_ignores_evidence(
        "192.168.1.101 hostunda RAM 95.5 seviyesinde, sağlık skoru 50.", EVIDENCE,
    )
