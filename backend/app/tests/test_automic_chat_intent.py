"""Automic sohbet niyet kapısı — meta araç/bileşen üretmez."""
from __future__ import annotations

import pytest

from app.services.automic.chat_support import (
    classify_chat_intent,
    deterministic_identity_answer,
    needs_fallback,
    plan_fallback,
)
from app.services.automic.components import build_components


META_QS = [
    "merhaba",
    "sen kimsin",
    "hangi modelsin",
    "sen hangi modelsin",
    "ne yapabilirsin",
    "teşekkürler",
    "verileri nereden alıyorsun",
    "nasıl çalışıyorsun",
]

DATA_QS = [
    "dün gece hata veren job'lar",
    "JOBS.DWH.SYNC.01 neden hata verdi",
    "hangi job'lar hata verdi?",
]


@pytest.mark.parametrize("msg", META_QS)
def test_meta_intent(msg):
    assert classify_chat_intent(msg) == "meta"


@pytest.mark.parametrize("msg", DATA_QS)
def test_data_intent(msg):
    assert classify_chat_intent(msg) == "data"


def test_meta_zero_tools_and_components():
    """Meta sorularda yedek plan çağrılmamalı; boş structured → sıfır bileşen."""
    for msg in META_QS:
        assert classify_chat_intent(msg) == "meta"
        # Bilinçli: plan_fallback meta için çağrılmaz; çağrılsaydı varsayılan hata planı gelirdi
        comps = build_components([])
        assert comps == []


def test_data_still_gets_fallback_plan():
    plan = plan_fallback("dün gece hata veren job'lar")
    assert plan[0][1].get("template_id") == "top_failed_objects"
    assert needs_fallback("", []) is True


def test_identity_answer_contains_model_and_system():
    txt = deterministic_identity_answer(
        app_name="ainew",
        model="gpt-oss:20b",
        llm_deployment="internal",
        system_name="DEV-FAKE",
        source_label="fake — SAHTE (salt okunur)",
        last_collection="2026-10-10T03:41:18+00:00",
    )
    assert "gpt-oss:20b" in txt
    assert "DEV-FAKE" in txt
    assert "Dolap" not in txt
    assert "Türkiye" not in txt
    assert "ainew" in txt
    assert "```ainew-meta" in txt
