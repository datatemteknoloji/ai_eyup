"""Adım 7g — KPI evren, sızıntı, by_object, top5 birleşik oran, object_host, engine PWP,
takvim haftası, zaman ifadesi, genel bilgi filtresi, TR ek, profil."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Europe/Istanbul")


def test_leak_guard_blocks_bare_star_planning():
    from app.services.automic.chat_support import AnswerLeakGuard, looks_like_planning_leak

    leak = ('**" Provide bold sentence with list? Should list job names? '
            "Probably list distinct object names... Let's craft.\"**\n\n"
            "**Dün gece 12 hatalı çalışma oldu.**\n")
    assert looks_like_planning_leak(leak)
    g = AnswerLeakGuard()
    out = "".join(g.feed(leak[i:i + 7]) for i in range(0, len(leak), 7)) + g.flush()
    out = g.clean_full(out)
    assert "Provide bold" not in out
    assert "Let's craft" not in out
    assert "Dün gece" in out or out.strip().startswith("**Dün")


def test_leak_guard_does_not_fast_release_incomplete_bold():
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard()
    # Kapanmamış ** — henüz akıtma
    assert g.feed("**Provide ") == ""
    assert not g.released


def test_week_calendar_monday_inclusive():
    """2026-10-12 Pazartesi: bu hafta=12–18, geçen hafta=5–11."""
    from app.services.llm_chat_policy import resolve_time_window

    now = datetime(2026, 10, 12, 15, 0, tzinfo=IST)
    tw = resolve_time_window("geçen hafta kaç hatalı çalışma oldu?", now)
    assert tw is not None
    assert tw["start"].date().isoformat() == "2026-10-05"
    assert tw["end"].date().isoformat() == "2026-10-12"  # exclusive → 11 dahil
    tw2 = resolve_time_window("bu hafta ne oldu?", now)
    assert tw2["start"].date().isoformat() == "2026-10-12"
    assert tw2["end"].date().isoformat() == "2026-10-19"


@pytest.mark.parametrize("dow,date", [
    (0, "2026-10-12"),  # Pazartesi
    (1, "2026-10-13"),
    (2, "2026-10-14"),
    (3, "2026-10-15"),
    (4, "2026-10-16"),
    (5, "2026-10-17"),
    (6, "2026-10-18"),  # Pazar
])
def test_week_calendar_every_weekday(dow, date):
    from app.services.llm_chat_policy import resolve_time_window

    y, m, d = map(int, date.split("-"))
    now = datetime(y, m, d, 12, 0, tzinfo=IST)
    assert now.weekday() == dow
    week0 = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dow)
    prev0 = week0 - timedelta(days=7)
    tw = resolve_time_window("geçen hafta", now)
    assert tw["start"].date() == prev0.date()
    assert tw["end"].date() == week0.date()
    twb = resolve_time_window("bu hafta", now)
    assert twb["start"].date() == week0.date()
    assert twb["end"].date() == (week0 + timedelta(days=7)).date()


def test_tr_si_suffix():
    from app.services.automic.tr_grammar import tr_n_si

    assert tr_n_si(16) == "16'sı"
    assert tr_n_si(28) == "28'i"
    assert tr_n_si(11) == "11'i"
    assert tr_n_si(100) == "100'ü"


def test_action_offer_by_entity():
    from app.services.automic.tr_grammar import action_offer_tr

    assert "agent" in action_offer_tr("LNXPROD01'i restart et", "LNXPROD01").lower() or "durumunu" in action_offer_tr(
        "LNXPROD01'i restart et", "LNXPROD01")
    assert "çalışmalarını" in action_offer_tr("JOBS.DWH.SYNC.01'i restart et", "JOBS.DWH.SYNC.01")


def test_known_codes_only_visible():
    from app.services.automic.error_codes import known_codes_block

    structured = [{"tool": "x", "result": {
        "ok": True,
        "error_signature": "ORA-00054 resource busy",
        "items": [{"error_signature": "ORA-00001 unique"}],
    }}]
    # Cevapta yalnız ORA-00054
    blk = known_codes_block(structured, answer_text="Hata imzası: ORA-00054 görüldü.")
    assert "ORA-00054" in blk
    assert "ORA-00001" not in blk


def test_answer_profile_yesno_collapses_table():
    from app.services.automic.answer_profile import classify_question, filter_components

    assert classify_question("Dün hata var mıydı?") == "yesno"
    comps = [
        {"type": "kpi_row", "items": []},
        {"type": "table", "title": "Çalışmalar", "rows": list(range(20)), "total": 20},
        {"type": "chart", "kind": "line"},
    ]
    out = filter_components("yesno", comps)
    assert not any(c.get("type") == "chart" for c in out)
    assert not any(c.get("type") == "table" and not c.get("collapsed") for c in out)


def test_components_kpi_from_universe():
    from app.services.automic.components import _from_search

    res = {
        "universe": {"runs_total": 72553, "ok_total": 70000, "failed_total": 1010, "cancelled_total": 1543},
        "runs_total": 72553, "failed_total": 1010, "ok_total": 70000, "cancelled_total": 1543,
        "filtered_total": 1010, "filtered_by": {"status_class": "failed"},
        "total": 1010, "counts": {"failed": 1010, "ok": 0},
        "items": [{"run_id": 1, "object_name": "JOBS.A", "status_class": "failed"}],
        "system_id": 1,
        "by_object": [{"object_name": "JOBS.A", "failed_count": 5, "runs_count": 10,
                       "failure_rate_pct": 50.0, "last_failed_at": None}],
    }
    comps = _from_search(res)
    kpi = next(c for c in comps if c["type"] == "kpi_row")
    by_label = {i["label"]: i["value"] for i in kpi["items"]}
    assert by_label["Toplam"] == 72553
    assert by_label["Başarılı"] == 70000
    assert by_label["Hatalı"] == 1010
    titles = [c.get("title") for c in comps if c.get("type") == "table"]
    assert any("1.010" in (t or "") or "1010" in (t or "").replace(".", "") for t in titles)


def test_engine_summary_active_pwp_single(monkeypatch):
    """Fake topoloji özeti: aktif PWP yalnız 10.10.0.11."""
    from app.services.automic import infra as infra_mod

    class _P:
        def __init__(self, name, pt, ip, status="connected"):
            self.name, self.process_type, self.ip = name, pt, ip
            self.port = 2217
            self.node = None
            self.status = status
            self.last_life_sign = None
            self.connection_count = 1
            self.pwp_connected = 1
            self.rest_endpoint = None
            self.missing_since = None

    procs = [
        _P("PWP001", "PWP", "10.10.0.11"),
        _P("WP001", "WP", "10.10.0.11"),
        _P("WP002", "WP", "10.10.0.11"),
        _P("CP001", "CP", "10.10.0.11"),
        _P("WP003", "WP", "10.10.0.12"),
        _P("WP004", "WP", "10.10.0.12", status="missing"),
        _P("CP002", "CP", "10.10.0.12"),
        _P("JCP001", "JCP", "10.10.0.12"),
        _P("REST001", "REST", "10.10.0.12"),
        _P("JWP001", "JWP", "10.10.0.12"),
    ]

    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return procs

    class _DB:
        def query(self, *a):
            return _Q()

        def get(self, *a):
            return None

    class _Sys:
        id = 1
        name = "DEV-FAKE"
        settings = {}

    monkeypatch.setattr(infra_mod, "load_overrides", lambda *a, **k: {})
    monkeypatch.setattr(infra_mod, "effective_settings", lambda *a, **k: {"ae_version": "24"})
    monkeypatch.setattr(infra_mod, "_mask_settings", lambda *a, **k: {})
    monkeypatch.setattr(infra_mod, "resolve_hostname",
                        lambda **k: {"hostname": None, "source": "ip_only", "source_label": "IP"})
    monkeypatch.setattr(infra_mod, "status_label_tr", lambda s: s or "?")

    out = infra_mod.list_engine_servers(_DB(), _Sys())
    assert out["active_pwp_count"] == 1
    assert out["active_pwp"][0]["ip"] == "10.10.0.11"
    assert "10.10.0.11" in out["summary_tr"] and "PWP aktif" in out["summary_tr"]
    # CP002 PWP gibi anılmamalı
    assert "CP002" not in (out.get("active_pwp") or [{}])[0].get("name", "")
