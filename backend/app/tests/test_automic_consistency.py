"""Automic: sohbet ↔ altyapı ekranı tutarlılığı, rapor kuyruğu, adım bütçeleri, sessiz hata yasağı.

Geçici bir test sistemi (TEST-CONSIST, source_type=fake) açılır ve her testten sonra TÜM satırları silinir
(canlı DEV-FAKE verisine dokunmaz).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.services.automic.defaults import effective_settings

SYS_NAME = "TEST-CONSIST"


@pytest.fixture()
def adb_sys():
    from app.models.automic import AutomicSystem
    from app.services.automic.database import ensure_schema, get_automic_thread_session

    try:
        ensure_schema()
        adb = get_automic_thread_session()
    except Exception:
        pytest.skip("Automic modül DB yok")
    if adb is None:
        pytest.skip("Automic modül DB yok")
    _purge(adb)
    system = AutomicSystem(
        name=SYS_NAME, is_default=False, enabled=False, source_type="fake",
        connection={"fake_clients": [100]}, clients=[100], settings={},
    )
    adb.add(system)
    adb.commit()
    try:
        yield adb, system
    finally:
        adb.rollback()
        _purge(adb)
        adb.close()


def _purge(adb) -> None:
    row = adb.execute(text("SELECT id FROM automic_systems WHERE name = :n"), {"n": SYS_NAME}).first()
    if not row:
        return
    sid = int(row[0])
    tables = [r[0] for r in adb.execute(text(
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_name = 'system_id' AND table_name <> 'automic_systems'")).all()]
    for t in tables:
        adb.execute(text(f"DELETE FROM {t} WHERE system_id = :s"), {"s": sid})
    adb.execute(text("DELETE FROM automic_systems WHERE id = :s"), {"s": sid})
    adb.commit()


# ── 5) sohbet ↔ ekran tutarlılığı ─────────────────────────────────────────

def _chat_names(answer: str):
    import re
    return set(re.findall(r"`([A-Z0-9.]+)`", answer))


def test_chat_disconnected_list_equals_infrastructure_screen(adb_sys, monkeypatch):
    from app.services.agent.tools import TOOLS
    from app.services.automic import infra as infra_svc
    from app.services.automic.source.fake import FakeSource
    from app.services.automic.template_answers import plan_deterministic, try_template_answer

    adb, system = adb_sys
    src = FakeSource(system.id, {"fake_clients": [100]}, None, effective_settings({}), {})
    infra_svc.sync_infrastructure(adb, system, src)

    # Ekran: altyapı sayfası "kopuk" filtresi = status=disconnected
    screen = {a["name"] for a in infra_svc.list_agents(adb, system, status="disconnected")["agents"]}
    assert screen == {"DBMSS01", "LNXBAT02"}

    # Sohbet: planlayıcı aynı filtreyi seçmeli ("kopuk" ≠ "missing")
    msg = "Kopuk agent'lar hangileri?"
    plan = plan_deterministic(msg)
    assert plan == [("automic_infrastructure", {"aspect": "agents", "status": "disconnected"})]
    assert all(a.get("status") != "missing" for _, a in plan)

    ctx = {"platform": "automic", "automic_system_id": system.id}
    structured = []
    for name, args in plan:
        res = TOOLS[name].direct_handler(None, args, ctx)
        structured.append({"tool": name, "args": args, "result": res})
    answer = try_template_answer(msg, structured)
    assert answer and "Kopuk agent yok" not in answer
    assert _chat_names(answer) == screen
    assert "HOST_Active = 0" in answer and "Son kontrol" in answer

    # Aynı fonksiyon / aynı filtre: "kopuk" takma adı ile "disconnected" aynı sonuç, "missing" boş
    via_alias = {a["name"] for a in infra_svc.list_agents(adb, system, status="kopuk")["agents"]}
    assert via_alias == screen
    assert infra_svc.list_agents(adb, system, status="missing")["agents"] == []

    # Sohbetin yedek planı da aynı filtreyi kullanır
    from app.services.automic.chat_support import plan_fallback
    assert plan_fallback("kopuk agent var mı")[0][1].get("status") == "disconnected"


def test_status_alias_normalization():
    from app.services.automic.infra_status import normalize_status

    assert normalize_status("kopuk") == "disconnected"
    assert normalize_status("bağlı") == "connected"
    assert normalize_status("bilinmiyor") == "unknown"
    assert normalize_status("durdu") == "missing"
    assert normalize_status("") is None
    assert normalize_status("kopuk") != normalize_status("missing")


# ── 1) rapor kuyruğu (backlog) ────────────────────────────────────────────

def _failed(adb, sid, run_id, end, name="JOBS.T.X.01"):
    adb.execute(text(
        "INSERT INTO automic_executions (system_id, client, run_id, activation_time, end_time, object_name, "
        "object_type, status_code, status_class, agent) VALUES (:s, 100, :r, :e, :e, :n, 'JOBS', 1800, 'failed', 'LNXAPP01')"),
        {"s": sid, "r": run_id, "e": end, "n": name})


def test_report_queue_newest_first_and_skips_unavailable(adb_sys):
    from app.services.automic import collector as col

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    # 40 saat önceki (eskiden 24 sa penceresi dışında kalan) + yeni + kesin "alınamadı" + kırpıntılı
    _failed(adb, system.id, 1001, now - timedelta(hours=40))
    _failed(adb, system.id, 1002, now - timedelta(hours=2))
    _failed(adb, system.id, 1003, now - timedelta(hours=30))
    _failed(adb, system.id, 1004, now - timedelta(hours=5))
    _failed(adb, system.id, 1005, now - timedelta(hours=6))
    adb.execute(text(
        "INSERT INTO automic_report_excerpts (system_id, client, run_id, report_type, end_time, content) "
        "VALUES (:s, 100, 1005, 'REP', :e, 'x')"), {"s": system.id, "e": now - timedelta(hours=6)})
    col._mark_attempt(adb, system.id, 100, 1004, now - timedelta(hours=5), status="unavailable", prev_attempts=0,
                      error="kaynakta rapor yok")
    adb.commit()
    q = col._report_queue(adb, system, now - timedelta(days=90), 100, 5, 10)
    assert [r[1] for r in q] == [1002, 1003, 1001]          # en yeniden eskiye; 1004/1005 dışarıda
    depth = col.report_queue_depth(adb, system.id, now - timedelta(days=90))
    assert depth == {"pending": 3, "retrying": 0, "unavailable": 1}


def test_report_queue_backoff_and_final_unavailable(adb_sys):
    from app.services.automic import collector as col

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    _failed(adb, system.id, 2001, now - timedelta(hours=3))
    adb.commit()
    col._mark_attempt(adb, system.id, 100, 2001, now - timedelta(hours=3), status="error", prev_attempts=0, error="geçici")
    adb.commit()
    # son deneme az önce → geri çekilme: kuyrukta yok
    assert col._report_queue(adb, system, now - timedelta(days=1), 10, 5, 10) == []
    adb.execute(text("UPDATE automic_report_attempts SET last_attempt_at = now() - interval '2 hours' "
                     "WHERE system_id = :s AND run_id = 2001"), {"s": system.id})
    adb.commit()
    q = col._report_queue(adb, system, now - timedelta(days=1), 10, 5, 10)
    assert [(r[1], r[3]) for r in q] == [(2001, 1)]
    # deneme hakkı bitince (attempts ≥ max) kuyruktan çıkar
    adb.execute(text("UPDATE automic_report_attempts SET attempts = 5 WHERE system_id = :s AND run_id = 2001"),
                {"s": system.id})
    adb.commit()
    assert col._report_queue(adb, system, now - timedelta(days=1), 10, 5, 10) == []


def test_collect_failed_reports_marks_unavailable_and_fills_backlog(adb_sys):
    from app.services.automic import collector as col
    from app.services.automic.source.fake import FakeSource, run_id_lo_for_minute

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    src = FakeSource(system.id, {"fake_clients": [100]}, None, effective_settings({}), {})
    recs = src.fetch_ended_executions([100], now - timedelta(hours=3), now, limit=100000,
                                      id_min=run_id_lo_for_minute(int((now - timedelta(hours=3)).timestamp() // 60)),
                                      id_max=run_id_lo_for_minute(int(now.timestamp() // 60)) + 10_000)
    failed = [r for r in recs if r.get("status_code") == 1800 or r.get("return_code") not in (None, 0)]
    col._ingest(adb, system, recs, effective_settings({})["status_classes"])
    adb.commit()
    # kaynakta bulunmayan bir RunID (eski)
    _failed(adb, system.id, 123456789, now - timedelta(hours=50))
    adb.commit()
    caps = {"features": {"reports": True}}
    src.capability = caps
    settings = effective_settings({})
    n = col._collect_failed_reports(adb, src, system, settings, time.monotonic() + 120, [])
    assert n > 0
    st = dict(adb.execute(text(
        "SELECT status, count(*) FROM automic_report_attempts WHERE system_id = :s GROUP BY 1"), {"s": system.id}).all())
    assert st.get("done", 0) == n
    assert st.get("unavailable", 0) >= 1          # 123456789: kaynakta yok → "rapor alınamadı"
    # ikinci tur: unavailable bir daha denenmez
    before = adb.execute(text("SELECT attempts FROM automic_report_attempts WHERE system_id=:s AND run_id=123456789"),
                         {"s": system.id}).scalar()
    col._collect_failed_reports(adb, src, system, settings, time.monotonic() + 60, [])
    after = adb.execute(text("SELECT attempts FROM automic_report_attempts WHERE system_id=:s AND run_id=123456789"),
                        {"s": system.id}).scalar()
    assert before == after == 1


# ── 2) adım bütçeleri ─────────────────────────────────────────────────────

def test_step_budget_cuts_and_does_not_starve_next_step():
    from app.services.automic.steps import StepClock

    total = 10.0
    clock = StepClock(total, {"ingest": 0.02, "reports": 0.5}, time.monotonic() + total)
    with clock.step("ingest") as st:
        while time.monotonic() < st.deadline:      # adım kendi deadline'ını gözetir
            time.sleep(0.01)
        st.cut = True
    with clock.step("reports") as st:
        remaining = st.deadline - time.monotonic()
        assert remaining > 3.0                     # önceki adım diğerlerini aç bırakmadı
    m = clock.snapshot()
    assert m["ingest"]["overrun"] is True and m["ingest"]["duration_sec"] < 1.0
    assert m["reports"]["overrun"] is False and m["reports"]["budget_sec"] == 5.0


def test_step_error_is_isolated_but_fatal_source_error_propagates():
    from app.services.automic.errors import error_counters, reset_for_tests
    from app.services.automic.source.base import SourceError
    from app.services.automic.steps import StepClock

    reset_for_tests()
    clock = StepClock(60, None, time.monotonic() + 60)
    with clock.step("users"):
        raise ValueError("kırık")
    with clock.step("infra") as st:
        st.items = 3
    assert clock.snapshot()["users"]["error"].startswith("ValueError")
    assert clock.snapshot()["infra"]["items"] == 3
    assert any(c["component"] == "collector.step.users" for c in error_counters()["components"])
    with pytest.raises(SourceError):
        with clock.step("ingest"):
            raise SourceError("bağlantı koptu", code="connection_lost")


def test_step_state_cursor_and_overrun_totals_persist():
    from app.services.automic.steps import get_step_state, save_step_metrics

    state = SimpleNamespace(step_state={"cursors": {"refresh": {"run_id": 5}}})
    save_step_metrics(state, {"ingest": {"overrun": True, "duration_sec": 1, "budget_sec": 1, "items": 0, "error": None}})
    save_step_metrics(state, {"ingest": {"overrun": True, "duration_sec": 1, "budget_sec": 1, "items": 0, "error": None},
                              "reports": {"overrun": False}})
    ss = get_step_state(state)
    assert ss["cursors"]["refresh"] == {"run_id": 5}      # imleç korunur
    assert ss["overruns"] == {"ingest": 2} and ss["runs"] == 2


# ── 3) durum güncelleme: açık liste, aralık taraması yok ─────────────────

def test_refresh_uses_explicit_ids_not_range_scan(adb_sys):
    from app.services.automic import collector as col
    from app.services.automic.steps import get_step_state

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    for i in range(7):
        adb.execute(text(
            "INSERT INTO automic_executions (system_id, client, run_id, activation_time, end_time, object_name, "
            "object_type, status_code, status_class) VALUES (:s, 100, :r, :e, :e, 'JOBS.T.X.01', 'JOBS', 1550, 'running')"),
            {"s": system.id, "r": 5_000_000 + i * 10_000_000_000, "e": now - timedelta(minutes=60 - i)})
    adb.commit()                                      # RunID'ler arası devasa boşluk → aralık taraması bütçeyi yerdi
    calls = []

    class Src:
        source_type = "fake"

        def fetch_ended_by_runids(self, pairs):
            calls.append(list(pairs))
            return []

        def fetch_ended_by_runid_range(self, *a, **k):          # çağrılmamalı
            raise AssertionError("aralık taraması yapıldı")

    state = col._get_state(adb, system.id)
    settings = effective_settings({"collection": {"refresh_chunk": 3, "refresh_ids_per_run": 5}})
    col._refresh_recent_step(adb, Src(), system, state, settings, [100], time.monotonic() + 30, [])
    assert [len(c) for c in calls] == [3, 2]                   # PK listesi parça parça
    cur = get_step_state(state)["cursors"]["refresh"]
    assert cur["run_id"] == 5_000_000 + 4 * 10_000_000_000     # imleç kalıcı → sonraki tur devam eder
    calls.clear()
    col._refresh_recent_step(adb, Src(), system, state, settings, [100], time.monotonic() + 30, [])
    assert [len(c) for c in calls] == [2]                      # kalan 2 RunID
    assert get_step_state(state)["cursors"]["refresh"] == {}   # geçiş tamam → baştan


def test_refresh_budget_cut_resumes_from_cursor(adb_sys):
    from app.services.automic import collector as col

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    for i in range(6):
        adb.execute(text(
            "INSERT INTO automic_executions (system_id, client, run_id, activation_time, end_time, object_name, "
            "object_type, status_code, status_class) VALUES (:s, 100, :r, :e, :e, 'JOBS.T.X.01', 'JOBS', 1550, 'running')"),
            {"s": system.id, "r": 100 + i, "e": now - timedelta(minutes=50 - i)})
    adb.commit()
    seen = []

    class Src:
        def fetch_ended_by_runids(self, pairs):
            seen.extend(r for _, r in pairs)
            return []

    state = col._get_state(adb, system.id)
    settings = effective_settings({"collection": {"refresh_chunk": 2, "refresh_ids_per_run": 100}})
    # bütçe zaten dolmuş → hiç parça okunmaz, imleç değişmez
    col._refresh_recent_step(adb, Src(), system, state, settings, [100], time.monotonic() - 1, [])
    assert seen == []


# ── eski şema fake temizliği ──────────────────────────────────────────────

def test_cleanup_legacy_fake_runids_only_fake_and_old_scheme(adb_sys):
    from app.services.automic.maintenance import LEGACY_RUNID_MIN, cleanup_legacy_fake_runids
    from app.services.automic.steps import get_step_state

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    _failed(adb, system.id, 9_000_000_000_001, now - timedelta(hours=2))      # eski şema
    _failed(adb, system.id, 298_000_000_000, now - timedelta(hours=2))         # yeni şema
    adb.execute(text(
        "INSERT INTO automic_active (system_id, client, run_id, object_name, status_code, status_class, snapshot_at) "
        "VALUES (:s, 100, 7029863676050, 'JOBS.T.X.01', 1550, 'running', now())"), {"s": system.id})
    adb.commit()
    state = SimpleNamespace(step_state=None)
    out = cleanup_legacy_fake_runids(adb, system, state)
    assert out["executions"] == 1 and out["active"] == 1
    left = [r[0] for r in adb.execute(text("SELECT run_id FROM automic_executions WHERE system_id=:s"), {"s": system.id}).all()]
    assert left == [298_000_000_000] and all(r < LEGACY_RUNID_MIN for r in left)
    assert "resync" in get_step_state(state)["cursors"]
    # gerçek kaynak türü: dokunulmaz
    real = SimpleNamespace(id=system.id, source_type="oracle", name="X")
    _failed(adb, system.id, 9_000_000_000_002, now)
    adb.commit()
    assert cleanup_legacy_fake_runids(adb, real, SimpleNamespace(step_state=None)) == {}
    assert adb.execute(text("SELECT count(*) FROM automic_executions WHERE system_id = :s AND run_id = 9000000000002"),
                       {"s": system.id}).scalar() == 1


def test_fake_active_run_ids_use_single_counter_scheme():
    from app.services.automic.source.fake import FakeSource

    src = FakeSource(1, {"fake_clients": [100, 200, 300]}, None, effective_settings({}), {})
    act = src.fetch_active_executions([100, 200, 300], limit=500)
    assert act and all(a["run_id"] < 10**12 for a in act)
    ids = [(a["client"], a["run_id"]) for a in act]
    assert len(ids) == len(set(ids))
    lo = min(a["run_id"] for a in act) // 10_000
    now_min = int(time.time() // 60)
    assert now_min - 130 <= lo <= now_min             # bitmiş çalışmalarla aynı dakika×10000 ölçeği


# ── 4) sessiz hata yasağı + gerçek rapor kapsamı ──────────────────────────

def test_note_error_counts_and_warns(caplog):
    import logging

    from app.services.automic import errors

    errors.reset_for_tests()
    with caplog.at_level(logging.WARNING, logger="app.services.automic.errors"):
        errors.note_error("unit.test", ValueError("boom"))
        errors.note_error("unit.test", ValueError("boom"))
    assert any("unit.test" in r.message and r.levelno == logging.WARNING for r in caplog.records)
    comp = {c["component"]: c for c in errors.error_counters()["components"]}
    assert comp["unit.test"]["count"] >= 2 and "boom" in comp["unit.test"]["last_msg"]


def test_no_debug_only_or_bare_swallow_in_automic_module():
    """Automic modülünde except bloğu hatayı yalnız debug loglamaz / tamamen yutmaz."""
    import ast
    import glob
    import os

    root = os.path.dirname(os.path.dirname(__file__))
    files = glob.glob(os.path.join(root, "services", "automic", "**", "*.py"), recursive=True)
    files += [os.path.join(root, "api", "automation.py"), os.path.join(root, "services", "agent", "tools_automic.py")]
    offenders = []
    for f in files:
        if f.endswith(os.path.join("automic", "errors.py")):
            continue
        src = open(f, encoding="utf-8").read()
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if any(isinstance(x, ast.Raise) for b in node.body for x in ast.walk(b)):
                continue
            txt = "\n".join(lines[node.lineno - 1: node.end_lineno])
            def _silent(b):
                if isinstance(b, (ast.Pass, ast.Continue)):
                    return True
                return isinstance(b, ast.Return) and (b.value is None or isinstance(b.value, (ast.Constant, ast.List,
                                                                                               ast.Dict, ast.Tuple)))
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
            only_pass = broad and all(_silent(b) for b in node.body)
            dbg = "logger.debug" in txt
            handled = any(k in txt for k in ("note_error", "logger.warning", "logger.error", "logger.exception",
                                             "warnings.append", "_lost("))
            if (only_pass or dbg) and not handled:
                offenders.append(f"{os.path.relpath(f, root)}:{node.lineno}")
    assert not offenders, "sessiz except: " + ", ".join(offenders)


def test_search_executions_has_no_nonexistent_error_signature_column_query(adb_sys):
    """Eski bug: automic_executions.error_signature kolonu yok → imza dağılımı sessizce yutuluyordu."""
    from app.services.automic import queries as q

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    for rid, sig in ((3001, "ORA-12541 TNS:no listener"), (3002, "ORA-12541 TNS:no listener"), (3003, None), (3004, None)):
        _failed(adb, system.id, rid, now - timedelta(hours=1))
        adb.execute(text(
            "INSERT INTO automic_failed_index (system_id, client, run_id, day, object_name, error_signature) "
            "VALUES (:s, 100, :r, :d, 'JOBS.T.X.01', :sg)"), {"s": system.id, "r": rid, "d": now.date(), "sg": sig})
    for rid in (3001, 3002, 3003):
        adb.execute(text(
            "INSERT INTO automic_report_excerpts (system_id, client, run_id, report_type, end_time, content, error_signature) "
            "VALUES (:s, 100, :r, 'REP', :e, 'x', NULL)"), {"s": system.id, "r": rid, "e": now - timedelta(hours=1)})
    adb.commit()
    res = q.search_executions(adb, system, status_class="failed", range_="24h", limit=2)
    assert "unavailable" not in res, res.get("unavailable_note")
    assert res["report_coverage"]["failed_total"] == 4 and res["report_coverage"]["with_report"] == 3
    assert res["report_coverage"]["without_report"] == 1 and res["report_coverage"]["coverage_pct"] == 75.0
    dist = res["error_signature_distribution"]
    assert dist == [{"signature": "ORA-12541 TNS:no listener", "count": 2}]
    # listelenen satırlarda gerçek rapor bilgisi var (alan yokluğu "rapor yok" değildir)
    assert all("report_available" in it for it in res["items"])


def test_search_executions_reports_unavailable_info_instead_of_false_zero(adb_sys, monkeypatch):
    from app.services.automic import queries as q

    adb, system = adb_sys
    now = datetime.now(timezone.utc)
    _failed(adb, system.id, 4001, now - timedelta(hours=1))
    adb.commit()

    def boom(*a, **k):
        raise RuntimeError("sorgu kırıldı")

    monkeypatch.setattr(q, "report_coverage_for", boom)
    res = q.search_executions(adb, system, status_class="failed", range_="24h", limit=5)
    assert "report_coverage" in res["unavailable"]
    assert "bu bilgi alınamadı" in res["unavailable_note"].lower()
    assert "report_coverage" not in res                        # yanlış sıfır/"rapor yok" üretilmez
    from app.services.automic import why_answer as wa
    md = "\n".join(t for _, t in wa.build_blocks([{"tool": "automic_search_executions", "args": {}, "result": res}]))
    assert "Alınamayan bilgi" in md and "rapor yok" not in md.lower().replace("rapor yok\" anlamına", "")


def test_why_answer_uses_real_coverage_not_listed_row_count():
    from app.services.automic import why_answer as wa

    items = [{"run_id": 100 + i, "object_name": "JOBS.A.B.01", "status_class": "failed", "status_code": 1800,
              "return_code": 1, "end_time": "2026-10-12T10:00:00+00:00", "report_available": i < 4} for i in range(25)]
    res = {"ok": True, "items": items, "total": 111, "runs_total": 450, "failed_total": 111, "failure_rate_pct": 24.67,
           "report_coverage": {"failed_total": 111, "with_report": 91, "without_report": 20, "pending_report": 12,
                               "report_unavailable": 8, "coverage_pct": 82.0}}
    md = "\n".join(t for _, t in wa.build_blocks([{"tool": "automic_search_executions", "args": {}, "result": res}]))
    assert "(rapor yok)" not in md
    assert "111 hatalı çalışmanın 91 tanesinde rapor kırpıntısı var (%82)" in md
    assert "12 tanesi henüz toplanmadı" in md and "8 tanesi için kaynakta rapor alınamadı" in md
    assert "11'i hatalı" in md or "111'i hatalı" in md


# ── adım 7i: doğrulayıcı, şablonlar, canlı akış, tutarlılık ───────────────

def test_validator_cuts_all_four_leak_kinds_and_logs_each():
    from app.services.automic.answer_validator import validate_answer

    base = "**Son 24 saatte 12 hatalı çalışma var.**\n"
    cases = {
        "plan_leak": "That's fine. Provide meta.\n",
        "forbidden_instruction": "Sistem/ortam adı sunucu değildir; IP/hostname kullan.\n",
        "tool_syntax": "automic_execution(aspect=detail)\n",
        "code_meaning": "255 genellikle genel hata olarak yorumlanır.\n",
    }
    for rule, bad in cases.items():
        out, iv = validate_answer(base + bad + "Devam eden bilgi burada.\n")
        assert any(i["rule"].startswith(rule) for i in iv), (rule, iv)
        for frag in ("That's fine", "Provide", "sunucu değildir", "IP/hostname", "automic_execution", "aspect=",
                     "255 genellikle", "yorumlan", "()", "; ."):
            assert frag not in out, (rule, frag, out)
        assert "**Son 24 saatte 12 hatalı çalışma var.**" in out and "Devam eden bilgi burada." in out


def test_validator_keeps_legit_return_code_note():
    from app.services.automic.answer_validator import validate_answer

    txt = ("**Dönüş kodu:** Bu dönüş kodunun anlamı çalıştırılan programa/script'e özgüdür; "
           "Automic'te genel bir anlamı yoktur.\n")
    out, iv = validate_answer(txt)
    assert iv == [] and "genel bir anlamı yoktur" in out


def test_debug_inject_texts_are_the_four_requested_strings():
    from app.api.automation import _debug_inject_texts

    assert _debug_inject_texts("plan") == ["That's fine. Provide meta."]
    assert _debug_inject_texts("instruction") == ["Sistem/ortam adı sunucu değildir; IP/hostname kullan."]
    assert _debug_inject_texts("tool") == ["automic_execution(aspect=detail)"]
    assert _debug_inject_texts("code") == ["255 genellikle genel hata olarak yorumlanır."]
    assert len(_debug_inject_texts("all@start")) == 4 and _debug_inject_texts("zzz") == []


def test_evalfilter_drops_ungrounded_cause_bullets_and_logs():
    from app.services.automic.why_answer import EvalFilter

    structured = [{"tool": "automic_execution", "args": {}, "result": {
        "ok": True, "content": "x\nERROR: return code N from step TRANSFORM\n",
        "error_signature": "ERROR: return code N from step TRANSFORM"}}]
    f = EvalFilter(allow_med_high=True)
    f.set_allowed_entities(structured)
    out = f.feed("Olası neden:\n- Agent kopuk olabilir veya kaynak yetersizliği (olası).\n"
                 "- `TRANSFORM` adımı sıfırdan farklı kodla bitmiş olabilir.\nGüven: orta\n") + f.flush()
    assert "TRANSFORM" in out and "kopuk" not in out
    notes = f.take_notes()
    assert any(n["reason"] == "ungrounded_cause" for n in notes)


def test_evalfilter_without_any_evidence_falls_back_to_undetermined():
    from app.services.automic.why_answer import EvalFilter

    f = EvalFilter(allow_med_high=False)
    f.set_allowed_entities([{"tool": "automic_search_executions", "args": {}, "result": {"ok": True}}])
    out = f.feed("Olası neden:\n- Disk dolmuş olabilir.\nGüven: orta\n") + f.flush()
    assert "belirlenemedi" in out and "Disk" not in out


def test_template_no_data_never_says_no_failures():
    from app.services.automic.template_answers import try_template_answer

    res = {"ok": True, "data_available": False, "data_status": "NO_DATA_IN_RANGE", "failed_total": 0,
           "from": "2024-12-31T21:00:00+00:00", "to": "2025-12-31T21:00:00+00:00",
           "partial_coverage_note": "365 günlük aralığın yalnızca 0 gününde veri var (08–12 Ekim).",
           "coverage": {"data_first_at": "2026-10-08T11:08:01+03:00", "data_last_at": "2026-10-12T19:08:22+03:00"}}
    ans = try_template_answer("Geçen yıl hangi job'lar hata verdi?",
                              [{"tool": "automic_search_executions", "args": {}, "result": res}])
    assert "veri yok" in ans and "2025-01-01 – 2025-12-31" in ans
    assert "2026-10-08 – 2026-10-12" in ans and "hatalı çalışma yok" not in ans
    # Eski beklenti: «yalnızca 0 gününde veri var». 0 gün = hiç veri yok; çelişkili
    # okunuyordu. Kapsam bildirimi korunur, ifade «hiçbir gününde veri yok» oldu.
    assert "yalnızca 0 gününde" not in ans
    assert "365 günlük aralığın hiçbir gününde veri yok" in ans


def test_template_count_followup_uses_filtered_numbers():
    from app.services.automic.template_answers import try_template_answer

    res = {"ok": True, "runs_total": 3489, "failed_total": 46, "filtered_total": 46, "total": 46,
           "filtered_by": {"status_class": "failed"}, "universe": {"runs_total": 3489, "failed_total": 46}}
    ans = try_template_answer("peki bunların kaçı LNXAPP01'deydi?",
                              [{"tool": "automic_search_executions", "args": {}, "result": res}], profile="count")
    assert ans.startswith("**46 hatalı çalışma**") and "3489" in ans


def test_last_run_profile_is_deterministic_and_grounded():
    from app.services.automic.answer_profile import classify_question
    from app.services.automic.template_answers import plan_deterministic, try_template_answer

    q = "JOBS.DWH.SYNC.01 en son ne zaman çalıştı?"
    assert classify_question(q) == "lastrun"
    assert classify_question("en son ne zaman çalıştı?") != "lastrun"      # nesne yoksa LLM yolu
    plan = plan_deterministic(q)
    assert plan[0][0] == "automic_search_executions" and plan[0][1]["limit"] == 1
    item = {"object_name": "JOBS.DWH.SYNC.01", "start_time": "2026-10-12T18:56:41+03:00",
            "end_time": "2026-10-12T18:58:48+03:00", "duration_sec": 127, "status_class": "ok",
            "status_code": 1900, "agent": "LNXETL01"}
    ans = try_template_answer(q, [{"tool": "automic_search_executions", "args": plan[0][1],
                                   "result": {"ok": True, "items": [item]}}])
    assert "2026-10-12 18:56:41+03:00" in ans and "2dk 07sn" in ans and "başarıyla tamamlandı" in ans
    assert "`LNXETL01`" in ans and "hata kodu" not in ans


def test_why_classification_covers_sorun_neydi():
    from app.services.automic.answer_profile import classify_question
    from app.services.automic.why_answer import is_why_question

    for q in ("Dünkü sorun neydi?", "dün ne oldu?", "Dün hata neydi?"):
        assert is_why_question(q) and classify_question(q) == "why"


def test_hhmm_uses_local_zone_for_utc_input():
    from app.services.automic.template_answers import _hhmm

    assert _hhmm("2026-10-12T16:18:00+00:00") == "19:18"
    assert _hhmm("2026-10-12T19:18:00+03:00") == "19:18"


def test_stream_chunks_cut_only_on_sentence_boundaries():
    """Canlı akış: kelime/isim ortasından kesilen parçaya doğrulayıcı uygulanıp bozmasın (JOBS.\\nDWH.SYNC01 hatası)."""
    import re
    from app.services.automic.answer_validator import validate_answer

    text = ("**JOBS.DWH.SYNC.01 son çalışması 2026-10-12 18:56:41+03:00'da tamamlandı.**  \n"
            "Son çalışma 2 dk 07 sn sürdü. En çok hata veren joblar: `JOBS.FIN.EXTRACT.01` (28), `JOBS.OPS.LOAD.03` (25).\n")
    boundary = re.compile(r"(?:[.!?]\s|\n)")
    # akıtma simülasyonu: tutulan kuyruk + yalnız sınırda bırakma
    out, hold = "", ""
    for ch in text:
        hold += ch
        cut = 0
        for m in boundary.finditer(hold[:-8] if len(hold) > 8 else ""):
            cut = m.end()
        if cut:
            vis, hold = hold[:cut], hold[cut:]
            core = vis.strip()
            lead, trail = vis[:len(vis) - len(vis.lstrip())], vis[len(vis.rstrip()):]
            cleaned, _ = validate_answer(core)
            out += lead + cleaned.strip() + trail
    cleaned, _ = validate_answer(hold.strip())
    out += hold[:len(hold) - len(hold.lstrip())] + cleaned.strip() + hold[len(hold.rstrip()):]
    for name in ("JOBS.DWH.SYNC.01", "JOBS.FIN.EXTRACT.01", "JOBS.OPS.LOAD.03", "Son çalışma 2 dk 07 sn"):
        assert name in out, (name, out)


def test_quality_detect_lang_ignores_quoted_error_signatures():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
    sys.path.insert(0, "/app/scripts")
    try:
        import automic_quality as aq
    except Exception:
        pytest.skip("scripts/automic_quality.py bu ortamda yok")
    ans = ("**Son 24 saatte 718 hatalı çalışma var.**\nHata imzaları: “No space left on device”, “Permission denied”, "
           "“ORA-12541: TNS:no listener”, “unable to extend table”.\n")
    assert aq.detect_lang(ans) == "tr"
    assert aq.detect_lang("**There were 12 failed runs in the last 24 hours and the cause is the listener.**") == "en"


def test_fake_run_agents_are_all_in_infra_table():
    """Çalışma verisindeki agent adları (yürütme, aktif) altyapı tablosundaki agent'lardan gelir — ayrı havuz yok."""
    from app.services.automic.source.fake import FakeSource

    src = FakeSource(1, {"fake_clients": [100, 200, 300]}, None, effective_settings({}), {})
    infra = {h["name"] for h in src.fetch_hosts()}
    now = datetime.now(timezone.utc)
    from app.services.automic.source.fake import run_id_lo_for_minute
    t0 = now - timedelta(hours=6)
    runs = src.fetch_ended_executions(
        [100, 200, 300], t0, now, limit=200000,
        id_min=run_id_lo_for_minute(int(t0.timestamp() // 60)),
        id_max=run_id_lo_for_minute(int(now.timestamp() // 60)) + 10_000)
    seen = {r["agent"] for r in runs if r.get("agent")} | {a["agent"] for a in
                                                         src.fetch_active_executions([100, 200, 300], limit=500) if a.get("agent")}
    assert seen and seen <= infra, sorted(seen - infra)
    assert len(infra) == 14


def test_turkish_number_suffix_in_universe_summary_and_premise():
    from app.services.automic.tr_grammar import tr_n_si

    assert [tr_n_si(n) for n in (6, 11, 46, 113)] == ["6'sı", "11'i", "46'sı", "113'ü"]
    from app.services.automic import why_answer as wa
    res = {"ok": True, "universe": {"runs_total": 80, "failed_total": 6, "failure_rate_pct": 7.5},
           "runs_total": 80, "failed_total": 6, "failure_rate_pct": 7.5}
    txt = wa.premise_correction("JOBS.A.B.01 hiç hata vermedi mi, hiç hata yok?", [{"tool": "t", "args": {}, "result": res}])
    assert "6'sı hatalı" in txt


def test_validator_collapses_double_negation():
    from app.services.automic.answer_validator import validate_answer

    out, _ = validate_answer("**Kanıt yok yok — rapor var var.**\nDevam.\n")
    assert "yok yok" not in out and "var var" not in out and "Kanıt yok" in out
