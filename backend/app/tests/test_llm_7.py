"""Adım 7 — temperature yapılandırması, tool-parse hata ölçümü, kapsam/varlık yokluğu araç sonuçları."""
from __future__ import annotations

import pytest

from app.services import chat_request_metrics as crm
from app.services import llm_chat_policy as lcp
from app.services.agent import llm as agent_llm


# ── temperature ─────────────────────────────────────────────────────────────

def test_temperature_for_defaults_override_and_clamp(monkeypatch):
    vals = {}
    monkeypatch.setattr(lcp, "_setting", lambda k, d: vals.get(k, d))
    assert lcp.temperature_for(answer_turn=False) == 0.1
    assert lcp.temperature_for(answer_turn=True) == 0.2   # A/B sonrası varsayılan
    vals.update({"llm_temperature_tools": 0.05, "llm_temperature_answer": 0.3})
    assert lcp.temperature_for(answer_turn=False) == 0.05
    assert lcp.temperature_for(answer_turn=True) == 0.3
    assert lcp.temperature_for(answer_turn=True, override=0.7) == 0.7       # istek bazlı A/B yalnız cevap turunu etkiler
    assert lcp.temperature_for(answer_turn=False, override=0.7) == 0.05
    assert lcp.temperature_for(answer_turn=True, override=9) == 1.5          # sınır
    vals["llm_temperature_answer"] = "bozuk"
    assert lcp.temperature_for(answer_turn=True) == 0.2


def test_temperature_settings_registered():
    from app.services.runtime_settings import ADVANCED_SCHEMA as S
    for k in ("llm_temperature_tools", "llm_temperature_answer"):
        assert S[k]["type"] == "float" and S[k]["group"] == "llm_chat"
        assert 0 <= S[k]["default"] <= 1.5


class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


def test_turn_temperature_reaches_ollama_payload(monkeypatch):
    seen = []

    def fake(payload, timeout):
        seen.append(payload["options"]["temperature"])
        return _Resp(200, {"message": {"content": "tamam", "tool_calls": []}, "done_reason": "stop"})
    monkeypatch.setattr(agent_llm, "_ollama_chat", fake)
    agent_llm.set_turn_temperature(None)
    agent_llm.chat_with_tools("m", [{"role": "user", "content": "x"}], [])
    agent_llm.set_turn_temperature(0.2)
    agent_llm.chat_with_tools("m", [{"role": "user", "content": "x"}], [])
    agent_llm.set_turn_temperature(None)
    assert seen == [0.1, 0.2]


def test_tool_parse_error_is_recorded_per_turn(monkeypatch):
    calls = {"n": 0}

    def fake(payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(500, {"error": "error parsing tool call: raw='{\"limit\":25\"}'"}, text="error parsing tool call")
        return _Resp(200, {"message": {"content": "cevap", "tool_calls": []}, "done_reason": "stop"})
    monkeypatch.setattr(agent_llm, "_ollama_chat", fake)
    m = crm.start("automic", "x")
    try:
        res = agent_llm.chat_with_tools("m", [{"role": "user", "content": "x"}],
                                        [{"type": "function", "function": {"name": "t", "parameters": {}}}])
        assert res["content"] == "cevap"
        flags = [t.tool_parse_error for t in m.llm_turns]
        assert flags == [True, False]            # hatalı tur işaretli, başarılı yeniden deneme değil
    finally:
        crm.finish(m)


# ── araç sonuçları: kapsam dışı / var olmayan varlık (salt okunur, DEV-FAKE) ──────

def _adb_system():
    from app.services.automic import database as adb_mod
    from app.services.automic.service import resolve_system
    try:
        adb_mod.ensure_schema()
        adb = adb_mod._session_factory()
        system = resolve_system(adb, None)
    except Exception:
        pytest.skip("Automic modül DB okunamıyor")
    if system is None:
        adb.close()
        pytest.skip("Automic sistemi yok")
    return adb, system


def test_search_outside_coverage_says_no_data_not_zero():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        res = q.search_executions(adb, system, t_from="2020-01-01T00:00:00+00:00", t_to="2020-01-02T00:00:00+00:00")
        assert res["total"] == 0 and res["data_available"] is False
        assert "veri yok" in res["summary"].lower() and "DENEMEZ" in res["summary"]
        assert res["coverage"]["records_in_range"] == 0
    finally:
        adb.close()


def test_nonexistent_object_and_agent_return_similar_names():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        r = q.search_executions(adb, system, object_name="JOBS.DWH.SYNK.01", range_="90d")
        assert r["total"] == 0
        hint = r["object_hint"]
        assert hint["exists_in_module_db"] is False
        a = q.agent_summary(adb, system, "LNXGHOST09")
        assert a["ok"] is False and "bulunamadı" in a["error"]
        a2 = q.agent_summary(adb, system, "LNXAPP01")
        assert a2["ok"] is True
        act = q.active_executions(adb, system, agent="LNXGHOST09")
        assert act["matched"] == 0 and "filter_note" in act and act["agent_hint"]["exists_in_module_db"] is False
    finally:
        adb.close()


def test_continuous_coverage_ignores_isolated_old_rows():
    from datetime import datetime, timedelta, timezone
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        end = datetime.now(timezone.utc)
        cov = q.data_coverage(adb, system, list(system.clients or [100, 200, 300]), end - timedelta(days=90), end)
        if cov.get("continuous_since"):
            assert cov["continuous_since"] > cov["data_first_at"]
            assert cov["isolated_records_before_continuous"] >= 1
        assert "range_fully_covered" in cov
    finally:
        adb.close()


def test_get_report_falls_back_to_stored_excerpt_type():
    from sqlalchemy import text
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        row = adb.execute(text(
            "SELECT x.client, x.run_id, x.report_type FROM automic_report_excerpts x WHERE x.system_id = :s "
            "AND x.report_type NOT IN ('REP', '-') AND NOT EXISTS (SELECT 1 FROM automic_report_excerpts y "
            "WHERE y.system_id = x.system_id AND y.run_id = x.run_id AND y.report_type = 'REP') "
            "ORDER BY x.end_time DESC LIMIT 1"), {"s": system.id}).first()
        if not row:
            pytest.skip("REP'siz saklı rapor kırpıntısı yok")
        res = q.get_report(adb, system, int(row[0]), int(row[1]), "REP")
        assert res["ok"] is True and res["report_type"] == row[2] and res["requested_report_type"] == "REP"
    finally:
        adb.close()


def test_language_hint_only_for_english():
    from app.services import llm_chat_policy as lcp
    assert "English" in lcp.language_hint("How many jobs are running right now?")
    assert lcp.language_hint("Dün hangi joblar hata verdi?") == ""
    assert lcp.language_hint("dün hangi joblar patladı, show me the count") == ""
    assert lcp.language_hint("hatalar?") == ""


def test_needs_clarification_and_assumption_hint():
    from app.services import llm_chat_policy as lcp
    assert lcp.needs_clarification("O agent neden yavaş?", False)
    assert lcp.needs_clarification("Şunu tekrar çalıştırsak sorun olur mu?", False)
    assert not lcp.needs_clarification("Şunu tekrar çalıştırsak sorun olur mu?", True)   # geçmiş var
    assert not lcp.needs_clarification("JOBS.CRM.EXTRACT.01 neden hata verdi?", False)  # varlık adı var
    assert not lcp.needs_clarification("Dün hangi işler hata verdi?", False)
    assert "Varsayım" in lcp.ambiguity_hint("Dünkü sorun ne?", False)
    assert lcp.ambiguity_hint("JOBS.A.B dünkü sorun ne?", False) == ""


def test_compact_query_keeps_filters():
    from app.services.automic.chat_support import compact_query
    q = compact_query("automic_search_executions", {"status_class": "failed", "range": "24h", "limit": 25,
                                                    "agent": "", "client": 0, "object_name": "*"})
    assert "status_class=failed" in q and "range=24h" in q
    assert "limit" not in q and "agent" not in q and "object_name" not in q
    assert compact_query(None, {}) == ""


def test_search_gives_latest_record_when_range_empty_and_status_filter_note():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        # aralık veri dışı, ama nesne modül DB'de var → aralık dışındaki en son kayıt verilir
        r = q.search_executions(adb, system, object_name="JOBS.DWH.SYNC.01",
                                t_from="2020-01-01T00:00:00+00:00", t_to="2020-01-02T00:00:00+00:00")
        assert r["total"] == 0
        if r.get("latest_record_any_time"):          # fake veri bu ortamda varsa
            assert r["latest_record_any_time"]["object_name"] == "JOBS.DWH.SYNC.01"
            assert "aralık dışı" in r["summary"]
        # durum filtresi 0 döner ama nesne çalışmışsa filtresiz sayı verilir
        r2 = q.search_executions(adb, system, object_name="JOBS.DWH.TEMIZLIK.03", status_class="failed",
                                 t_from="2026-10-08T00:00:00+03:00", t_to="2026-10-11T00:00:00+03:00")
        if r2["total"] == 0 and r2.get("runs_ignoring_status_filter"):
            assert r2["runs_ignoring_status_filter"]["total"] > 0 and "DENEMEZ" in r2["summary"]
    finally:
        adb.close()


def test_clock_override_is_contextual():
    from datetime import datetime, timezone
    from app.services.automic import clock
    from app.services.automic.queries import parse_range
    clock.set_now(clock.parse_override("2026-10-10T02:40:00+03:00"))
    try:
        s, e = parse_range("24h")
        assert e == datetime(2026, 10, 9, 23, 40, tzinfo=timezone.utc)
    finally:
        clock.set_now(None)
    assert clock.parse_override("bozuk") is None


def test_action_request_answer_only_for_imperatives():
    from app.services import llm_chat_policy as lcp
    for m in ("JOBS.DWH.SYNC.01'i restart et", "JOBP.DWH.GUNSONU workflow'unu iptal et",
              "VARA.DWH.PARAM değişkenini güncelle, değerini 5 yap", "LNXAPP01 agent'ını durdur"):
        a = lcp.action_request_answer(m)
        assert "salt-okunur" in a and "AWI" in a and "yapamam" in a, m
    assert "JOBS.DWH.SYNC.01" in lcp.action_request_answer("JOBS.DWH.SYNC.01'i restart et")
    assert "read-only" in lcp.action_request_answer("restart JOBS.A.B please", english=True)
    for m in ("JOBS.DWH.SYNC.01 en son ne zaman çalıştı?", "Şunu tekrar çalıştırsak sorun olur mu?",
              "Hangi job'lar hata verdi?", "iptal edilen işler", "Dün kaç iş çalıştı"):
        assert lcp.action_request_answer(m) == "", m


def test_time_expression_is_calendar_period():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services import llm_chat_policy as lcp
    now = datetime(2026, 10, 11, 0, 30, tzinfo=ZoneInfo("Europe/Istanbul"))
    h = lcp.time_expression_hint("Geçen yıl hangi job'lar hata verdi?", now)
    assert "from=2025-01-01T00:00:00+03:00" in h and "to=2026-01-01T00:00:00+03:00" in h
    h = lcp.time_expression_hint("3 ay önce en çok hata veren job hangisiydi?", now)
    assert "from=2026-07-01T00:00:00+03:00" in h and "to=2026-08-01T00:00:00+03:00" in h
    assert "2026-09-01" in lcp.time_expression_hint("geçen ay kaç iş çalıştı", now)
    assert lcp.time_expression_hint("son 7 günde kaç iş", now) == ""
    now2 = datetime(2026, 1, 15, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert "2025-12-01" in lcp.time_expression_hint("geçen ay", now2)      # yıl sınırı


def test_unavailable_and_followup_hints():
    from app.services import llm_chat_policy as lcp
    assert "TUTULMAZ" in lcp.unavailable_info_hint("JOBS.X hangi müşteriyi etkiliyor?")
    assert lcp.unavailable_info_hint("Dün kaç iş hata verdi?") == ""
    assert "AYNEN" in lcp.followup_hint("bunlardan en uzun süreni hangisi?", ["automic_search_executions status_class=failed"])
    assert lcp.followup_hint("bunlardan en uzun süreni hangisi?", []) == ""
    assert lcp.followup_hint("Dün kaç iş çalıştı?", ["x"]) == ""


def test_search_returns_both_duration_extremes():
    from app.services.automic import queries as q
    adb, system = _adb_system()
    try:
        r = q.search_executions(adb, system, t_from="2026-10-08T00:00:00+03:00", t_to="2026-10-11T00:00:00+03:00", limit=1)
        if r["total"]:
            assert r["longest_run"]["duration_sec"] >= r["shortest_run"]["duration_sec"]
    finally:
        adb.close()


# ── Adım 7b ──────────────────────────────────────────────────────────────────

def _now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(2026, 10, 11, 0, 30, tzinfo=ZoneInfo("Europe/Istanbul"))


def test_explicit_dates_resolve_to_window():
    w = lcp.resolve_time_window("2025 Aralık ayında JOBS.DWH.SYNC.01 kaç kez çalıştı?", _now())
    assert w["label"] == "Aralık 2025" and w["force"] is True
    assert lcp.forced_window_iso(w) == ("2025-11-30T21:00:00+00:00", "2025-12-31T21:00:00+00:00")
    assert "2026-03-15" in lcp.time_expression_hint("15 Mart'ta ne oldu?", _now())
    assert "from=2026-09-03T00:00:00+03:00" in lcp.time_expression_hint("geçen ayın 3'ü kaç iş çalıştı", _now())
    assert "2030-01-01" in lcp.time_expression_hint("2030 Ocak ayında kaç iş çalıştı?", _now())
    # gelecekteki gün/ay (yıl yok) → geçen yıl
    assert "2025-12-25" in lcp.time_expression_hint("25 Aralık günü ne oldu", _now())
    # geçersiz tarih ve çoklu dönem → pencere yok
    assert lcp.resolve_time_window("31 Şubat", _now()) is None
    assert lcp.resolve_time_window("Aralık 2025 ile Ocak 2026", _now()) is None


def test_explicit_window_not_forced_when_comparing_or_relative():
    w = lcp.resolve_time_window("geçen ay ile bu ayı karşılaştır", _now())
    assert w and w["force"] is False and lcp.forced_window_iso(w) is None
    w = lcp.resolve_time_window("2025 Aralık ve son 7 gün", _now())
    assert w and w["force"] is False


def test_forced_window_overrides_model_dates():
    from app.services.automic import clock
    clock.set_window(("2025-11-30T21:00:00+00:00", "2025-12-31T21:00:00+00:00"))
    try:
        out = clock.apply_window({"range": "24h", "from": "yanlış", "object_name": "X"})
    finally:
        clock.set_window(None)
    assert out["from"].startswith("2025-11-30") and out["to"].startswith("2025-12-31")
    assert "range" not in out and out["object_name"] == "X"
    assert clock.apply_window({"range": "7d"}) == {"range": "7d"}   # pencere yoksa dokunmaz


def test_return_code_note_fixed_text_and_known_codes_at_source():
    from app.services.automic import error_codes as ec
    res = {"ok": True, "items": [{"return_code": 8, "error": "ORA-01653: unable to extend table X in tablespace Y"}]}
    ec.annotate_result(res)
    assert res["return_code_note"] == ("Bu dönüş kodunun anlamı çalıştırılan programa/script'e özgüdür; "
                                       "Automic'te genel bir anlamı yoktur.")
    assert res["known_error_codes"][0]["code"] == "ORA-01653" and "Oracle" in res["known_error_codes"][0]["source"]
    ok = {"ok": True, "items": [{"return_code": 0}]}
    ec.annotate_result(ok)
    assert "return_code_note" not in ok and "known_error_codes" not in ok


def test_known_codes_block_is_labeled_by_code_and_skips_unknown():
    from app.services.automic import error_codes as ec
    blk = ec.known_codes_block([{"content": "ORA\u201101555: snapshot too old; ORA-99999 bilinmiyor; ORA-06512: at line 4"}])
    assert blk.startswith("**Genel bilgi:**") and "ORA-01555" in blk and "ORA-06512" in blk
    assert "ORA-99999" not in blk and "Kaynak: Oracle" in blk
    assert ec.known_codes_block([{"content": "kod yok"}]) == ""


def test_unavailable_info_answers_without_llm_and_without_schema_names():
    import re
    for q in ("JOBS.DWH.SYNC.01 job'ını kim yazdı?", "JOBS.DWH.SYNC.01'in aylık maliyeti ne kadar?",
              "JOBS.DWH.SYNC.01 hangi müşteriyi etkiliyor?", "JOBS.ETL.SYNC.01'in iş sahibi (business owner) kim?"):
        a = lcp.unavailable_info_answer(q)
        assert a.startswith("**Bu bilgi mevcut Automic verisinde yok**"), q
        assert "Şunları gösterebilirim" in a
        assert not re.search(r"\b(?:OH|AH|OT|EH|UC)_\w+", a)
    assert "not available" in lcp.unavailable_info_answer("Who wrote JOBS.DWH.SYNC.01?", english=True)
    # veri isteyen / ilgisiz sorular LLM'e gider
    assert lcp.unavailable_info_answer("JOBS.DWH.SYNC.01 kaç kez çalıştı ve maliyeti ne?") == ""
    assert lcp.unavailable_info_answer("BATCH/OPS kullanıcısı dün kaç iş çalıştırdı?") == ""
    assert lcp.unavailable_info_answer("Hangi job'lar hata verdi?") == ""
