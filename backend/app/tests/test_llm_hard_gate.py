"""Son kapı (hard gate) — gateway'e model penceresini aşan payload gitmesin.

Gerçek olay: bütçe 32K'ya ayarlıyken modele ~35.8K token'lık istek gitti ve
gateway "context length exceeded" döndü. Sebep, bütçelemenin yalnızca BAGLAM
bölümüne uygulanıp system/kurallar/geçmiş/soru toplamının sayılmamasıydı.
Bu testler hem toplam-payload kapısını hem de tahmin kalibrasyonunu doğrular.
"""
import app.services.llm_context_budget as m


def _cap_32k(monkeypatch):
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 32768)
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 32768)


# ── enforce_prompt_budget ───────────────────────────────────────────────────

def test_prompt_gate_noop_when_within_limit(monkeypatch):
    _cap_32k(monkeypatch)
    prompt = "kısa bir soru"
    out, meta = m.enforce_prompt_budget(prompt, system="sistem")
    assert out == prompt
    assert meta["truncated"] is False


def test_prompt_gate_truncates_over_hard_cap(monkeypatch):
    _cap_32k(monkeypatch)
    # ~35K token'lık prompt (gerçek olaydaki büyüklük)
    prompt = "HEAD-KURALLAR\n" + ("x" * 120000) + "\nKULLANICI SORUSU: disk doluyor mu?"
    out, meta = m.enforce_prompt_budget(prompt, system="s" * 400, label="test")

    assert meta["truncated"] is True
    assert meta["final_tokens"] <= meta["limit"]
    assert meta["limit"] <= 32768
    # Baş (kurallar) ve son (soru) korunur — kesilen orta bölümdür.
    assert out.startswith("HEAD-KURALLAR")
    assert out.endswith("disk doluyor mu?")
    assert "kırpıldı" in out


def test_prompt_gate_limit_follows_hard_cap(monkeypatch):
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 131072)
    assert m.get_payload_hard_limit() > 100000


# ── enforce_messages_budget ────────────────────────────────────────────────

def test_messages_gate_noop_when_small(monkeypatch):
    _cap_32k(monkeypatch)
    msgs = [
        {"role": "system", "content": "sistem"},
        {"role": "user", "content": "merhaba"},
    ]
    out, meta = m.enforce_messages_budget(msgs)
    assert out == msgs
    assert meta["truncated"] is False


def test_messages_gate_shrinks_tool_output_first(monkeypatch):
    _cap_32k(monkeypatch)
    msgs = [
        {"role": "system", "content": "sistem promptu"},
        {"role": "user", "content": "eski soru"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function"}]},
        {"role": "tool", "content": "T" * 200000},  # devasa tool çıktısı
        {"role": "user", "content": "SON SORU: hangi sunucu riskli?"},
    ]
    out, meta = m.enforce_messages_budget(msgs, label="test")

    assert meta["truncated"] is True
    assert meta["final_tokens"] <= meta["limit"]
    # Mesaj sayısı korunur (tool_calls ↔ tool eşleşmesi bozulmamalı)
    assert len(out) == len(msgs)
    assert out[2]["tool_calls"] == msgs[2]["tool_calls"]
    # Küçültülen tool çıktısıdır; system ve son kullanıcı sorusu dokunulmadan kalır.
    assert len(out[3]["content"]) < len(msgs[3]["content"])
    assert out[0]["content"] == "sistem promptu"
    assert out[4]["content"] == "SON SORU: hangi sunucu riskli?"


def test_messages_gate_does_not_mutate_input(monkeypatch):
    _cap_32k(monkeypatch)
    msgs = [{"role": "user", "content": "U" * 200000}]
    original = msgs[0]["content"]
    out, meta = m.enforce_messages_budget(msgs)
    assert msgs[0]["content"] == original
    assert len(out[0]["content"]) < len(original)


# ── kalibrasyon: gerçek usage.prompt_tokens ile char/token oranı ────────────

def _reset_cal():
    m._cal_state.update({"ratio": None, "samples": 0, "last_observed": None})


def test_default_ratio_is_conservative():
    _reset_cal()
    assert m.chars_per_token() == m._CHARS_PER_TOKEN_EST
    assert m.calibration_snapshot()["calibrated"] is False


def test_calibration_converges_to_observed_ratio():
    _reset_cal()
    # Gateway 40.000 karakter için 10.000 prompt token bildirdi → 4.0 char/token
    for _ in range(6):
        m.record_actual_usage(40000, 10000)
    snap = m.calibration_snapshot()
    assert snap["calibrated"] is True
    assert 3.6 <= snap["chars_per_token"] <= 4.0  # %5 muhafazakâr pay ile
    _reset_cal()


def test_calibration_ignores_absurd_and_short_samples():
    _reset_cal()
    m.record_actual_usage(100, 5)          # çok kısa prompt → örnekleme yok
    m.record_actual_usage(100000, 5)       # 20000 char/token → aralık dışı
    m.record_actual_usage(100000, 100000)  # 1.0 char/token → aralık dışı
    assert m.calibration_snapshot()["samples"] == 0
    assert m.chars_per_token() == m._CHARS_PER_TOKEN_EST
    _reset_cal()


def test_gateway_feeds_calibration_from_real_usage():
    """Gateway, uzak yanıttaki usage.prompt_tokens ile tahmini kalibre eder."""
    from app.services import llm_gateway as g

    _reset_cal()
    msgs = [{"role": "user", "content": "x" * 30000}]
    for _ in range(4):
        g._note_prompt_tokens(g._payload_chars(msgs), {"usage": {"prompt_tokens": 10000}})
    snap = m.calibration_snapshot()
    assert snap["samples"] == 4
    assert snap["last_observed"] == 3.0
    assert 2.7 <= snap["chars_per_token"] <= 3.0
    _reset_cal()


def test_estimate_tokens_uses_calibrated_ratio():
    _reset_cal()
    text = "a" * 10000
    before = m.estimate_tokens(text)
    for _ in range(4):
        m.record_actual_usage(40000, 20000)  # 2.0 char/token (kötümser tokenizer)
    after = m.estimate_tokens(text)
    assert after > before  # daha fazla token tahmini → daha erken kırpma
    _reset_cal()
