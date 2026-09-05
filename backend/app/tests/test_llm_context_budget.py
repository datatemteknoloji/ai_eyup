"""llm_context_budget unit tests."""
from app.services.llm_context_budget import (
    estimate_tokens,
    truncate_text_to_token_budget,
)


def test_estimate_tokens():
    assert estimate_tokens("hello") >= 1


def test_truncate_when_over_budget():
    big = "x" * 100000
    out, truncated = truncate_text_to_token_budget(big, 1000)
    assert truncated
    assert len(out) < len(big)
    assert "kısaltıldı" in out


def test_no_truncate_when_under_budget():
    small = "kısa metin"
    out, truncated = truncate_text_to_token_budget(small, 10000)
    assert not truncated
    assert out == small


# ── gateway hard-cap: bütçe ayarı model/gateway limitini asla aşmamalı ───────

def test_input_budget_clamped_by_gateway_hard_cap(monkeypatch):
    import app.services.llm_context_budget as m
    # Admin bütçeyi 128K'ya çıkarmış olsa bile, gateway/model gerçekte 32K ise
    # efektif bütçe 32K'nın (güvenlik payı + rezerv düşülmüş) üstüne çıkmamalı.
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 128000)
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 32768)
    budget = m.get_input_token_budget()
    assert budget == 32768 - 2000 - 4096
    assert budget < 128000


def test_input_budget_grows_when_hard_cap_raised(monkeypatch):
    # Gateway/model gerçekten büyürse (32K → 64K), kod değişmeden bütçe otomatik
    # büyür — "32K'ya sabit kalmayacak" gereksinimi.
    import app.services.llm_context_budget as m
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 128000)
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 65536)
    budget = m.get_input_token_budget()
    assert budget == 65536 - 2000 - 4096


# ── budget_sections: soru/tool sonucu ASLA kesilmez, yalnız context/history ──

def test_budget_sections_no_truncate_when_small():
    from app.services.llm_context_budget import budget_sections
    result = budget_sections(system="sistem", context="küçük context", history="", protected_tail="soru")
    assert result["meta"]["truncated"] is False
    assert result["context"] == "küçük context"


def test_budget_sections_truncates_context_not_tail(monkeypatch):
    import app.services.llm_context_budget as m
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 32768)
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 32768)
    # Gerçek regresyon senaryosu: 62 host / 3720 VM'lik dev bir context dump'ı +
    # ufak bir kullanıcı sorusu. Kesilen SADECE context olmalı; soru asla değil.
    huge_context = "VM verisi satırı. " * 200000
    tail = "Kullanıcı Sorusu: isthol5esxia03 host üzerindeki VM'leri göster\n\nLütfen yanıtını ver:"
    result = m.budget_sections(system="sistem promptu", context=huge_context, history="", protected_tail=tail)
    assert result["meta"]["truncated"] is True
    assert result["meta"]["truncated_section"] in ("context", "context+history")
    assert len(result["context"]) < len(huge_context)
    # Fonksiyon protected_tail'i hiç döndürmüyor/değiştirmiyor — çağıran onu
    # prompt'a olduğu gibi ekler; burada dolaylı kanıt: final_tokens tail'i
    # tam token sayısıyla içeriyor.
    from app.services.llm_context_budget import estimate_tokens
    assert result["meta"]["tail_tokens"] == estimate_tokens(tail)


def test_budget_sections_truncates_history_when_context_alone_not_enough(monkeypatch):
    import app.services.llm_context_budget as m
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 8192)
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 8192)
    result = m.budget_sections(
        system="s" * 100,
        context="c" * 100,
        history="h" * 200000,
        protected_tail="t" * 100,
    )
    assert result["meta"]["truncated"] is True
    assert len(result["history"]) < 200000


def test_budget_sections_never_shrinks_tail_even_when_impossible(monkeypatch):
    # Aşırı durum: system+tail tek başına bütçeyi aşıyor. context/history
    # sıfırlanır ama fonksiyon tail'i KISALTMAZ (sessiz veri kaybı yerine
    # gateway'in kendi limit hatasını vermesi tercih edilir).
    import app.services.llm_context_budget as m
    monkeypatch.setattr(m, "get_context_token_budget", lambda: 100)
    monkeypatch.setattr(m, "get_gateway_hard_cap_tokens", lambda: 100)
    # get_input_token_budget() alt sınırı 2048 token'dır (bkz. max(2048, ...));
    # bu alt sınırı da aşan bir tail ile gerçek "imkansız" senaryoyu test ediyoruz.
    huge_tail = "Kullanıcı Sorusu: " + ("x" * 10000)
    result = m.budget_sections(system="s", context="c" * 5000, history="", protected_tail=huge_tail)
    assert result["context"] == ""
    from app.services.llm_context_budget import estimate_tokens
    assert result["meta"]["tail_tokens"] == estimate_tokens(huge_tail)
