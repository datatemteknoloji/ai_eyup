"""Adım 11 — SystemEvent tekilleştirme: tüm satırları ORM nesnesi olarak yükleme YOK (GIL/SSE gecikmesi kök nedeni)."""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.event import SystemEvent
from app.services import event_dedupe, ovirt_event_collector, vcenter_event_collector, virt_log_collector
from app.services import openshift_virt_event_collector as ocpv
from app.services.event_dedupe import ExternalKeyIndex, find_existing_event


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    SystemEvent.__table__.create(eng)
    S = sessionmaker(bind=eng)
    s = S()
    yield s, eng
    s.close()


def _ev(source, key, days_ago=0, **kw):
    ts = datetime.utcnow() - timedelta(days=days_ago)
    return SystemEvent(event_type="vcenter_event", source=source, title="t", raw_data={"external_key": key},
                       created_at=ts, last_seen=ts, occurrence_count=1, **kw)


def test_find_existing_basic(db):
    s, _ = db
    s.add_all([_ev("vcenter_event", "hv1-a"), _ev("vcenter_event", "hv1-b")]); s.commit()
    assert find_existing_event(s, "vcenter_event", "hv1-a").raw_data["external_key"] == "hv1-a"
    assert find_existing_event(s, "vcenter_event", "hv1-zzz") is None


def test_find_existing_source_scoped(db):
    s, _ = db
    s.add(_ev("vcenter_task", "hv1-a")); s.commit()
    assert find_existing_event(s, "vcenter_event", "hv1-a") is None
    assert find_existing_event(s, "vcenter_task", "hv1-a") is not None


def test_find_existing_window_7_days(db):
    s, _ = db
    s.add(_ev("vcenter_event", "old", days_ago=9)); s.commit()
    assert find_existing_event(s, "vcenter_event", "old") is None
    idx = ExternalKeyIndex(s)
    assert idx.find("vcenter_event", "old") is None


def test_index_finds_and_returns_orm_row(db):
    s, _ = db
    s.add_all([_ev("vcenter_event", f"k{i}") for i in range(5)]); s.commit()
    idx = ExternalKeyIndex(s)
    r = idx.find("vcenter_event", "k3")
    assert isinstance(r, SystemEvent) and r.raw_data["external_key"] == "k3"
    assert idx.find("vcenter_event", "nope") is None


def test_index_first_match_on_duplicates(db):
    s, _ = db
    a, b = _ev("vcenter_event", "dup"), _ev("vcenter_event", "dup")
    s.add_all([a, b]); s.commit()
    assert ExternalKeyIndex(s).find("vcenter_event", "dup").id == min(a.id, b.id)
    assert find_existing_event(s, "vcenter_event", "dup").id == min(a.id, b.id)


def test_index_add_covers_same_batch_duplicates(db):
    s, _ = db
    idx = ExternalKeyIndex(s)
    new = _ev("vcenter_event", "fresh")
    s.add(new)
    idx.add("vcenter_event", "fresh", new)
    assert idx.find("vcenter_event", "fresh") is new


def test_index_loads_once_per_source(db):
    s, eng = db
    s.add_all([_ev("vcenter_event", f"k{i}") for i in range(20)]); s.commit()
    n = {"q": 0}

    @event.listens_for(eng, "before_cursor_execute")
    def _count(conn, cur, stmt, params, ctx, many):
        if "system_events" in stmt:
            n["q"] += 1

    idx = ExternalKeyIndex(s)
    for i in range(20):
        idx.find("vcenter_event", f"k{i}")
    # 1 yükleme + 20 satır getirme (db.get) — olay başına tam tablo taraması YOK
    assert n["q"] <= 1 + 20


def test_find_without_index_selects_one_row_not_all(db):
    s, eng = db
    s.add_all([_ev("vcenter_event", f"k{i}") for i in range(50)]); s.commit()
    seen = []

    @event.listens_for(eng, "before_cursor_execute")
    def _grab(conn, cur, stmt, params, ctx, many):
        seen.append(stmt)

    find_existing_event(s, "vcenter_event", "k7")
    sql = " ".join(seen).lower()
    assert "external_key" in sql or "json_extract" in sql  # anahtar filtresi SQL tarafında
    assert "limit" in sql


def _hv():
    return SimpleNamespace(id=1, name="vc1")


def test_vcenter_upsert_duplicate_returns_false_and_new_adds(db, monkeypatch):
    s, _ = db
    monkeypatch.setattr(vcenter_event_collector, "_enrich_item_refs", lambda i: i)
    monkeypatch.setattr(vcenter_event_collector, "_resolve_server_id", lambda *a, **k: None)
    monkeypatch.setattr(vcenter_event_collector, "_backfill_existing_event", lambda *a, **k: None)
    monkeypatch.setattr(vcenter_event_collector, "_build_raw_data",
                        lambda hv, item, et, ek: {"external_key": ek})
    now = datetime.utcnow()
    idx = ExternalKeyIndex(s)
    item = {"id": "evt-1", "title": "x"}
    assert vcenter_event_collector._upsert_vcenter_event(s, _hv(), item, "vcenter_event", "vcenter_event", now, idx) is True
    # aynı turda tekrar: kopya sayılır (eski davranış: autoflush ile bekleyen satır bulunurdu)
    assert vcenter_event_collector._upsert_vcenter_event(s, _hv(), item, "vcenter_event", "vcenter_event", now, idx) is False
    s.commit()
    # yeni sync (indexsiz, SQL araması): kayıtlı → False
    assert vcenter_event_collector._upsert_vcenter_event(s, _hv(), item, "vcenter_event", "vcenter_event", now) is False
    assert s.query(SystemEvent).count() == 1


def test_vcenter_upsert_backfill_called_on_existing(db, monkeypatch):
    s, _ = db
    s.add(_ev("vcenter_event", "hv1-evt-9")); s.commit()
    monkeypatch.setattr(vcenter_event_collector, "_enrich_item_refs", lambda i: i)
    called = []
    monkeypatch.setattr(vcenter_event_collector, "_backfill_existing_event", lambda *a, **k: called.append(a[0].id))
    ok = vcenter_event_collector._upsert_vcenter_event(
        s, _hv(), {"id": "evt-9"}, "vcenter_event", "vcenter_event", datetime.utcnow(), ExternalKeyIndex(s))
    assert ok is False and len(called) == 1


def test_ovirt_upsert_replay_is_not_a_recurrence(db, monkeypatch):
    # Adım 11 → yaşam döngüsü düzeltmesi: aynı oVirt olay id'si akış penceresinde yeniden görünür; sayaç şişmez.
    s, _ = db
    s.add(SystemEvent(event_type="ovirt_event", source="ovirt_event", title="t",
                      raw_data={"external_key": "ovirt-hv1-e1"}, occurrence_count=1,
                      created_at=datetime.utcnow())); s.commit()
    ok = ovirt_event_collector._upsert(s, SimpleNamespace(id=1, name="o"), {"id": "e1"}, datetime.utcnow(), ExternalKeyIndex(s))
    assert ok is False
    assert s.query(SystemEvent).one().occurrence_count == 1


def test_ocpv_upsert_updates_severity(db):
    s, _ = db
    key = "hv1-vm1-Started-2026"
    s.add(SystemEvent(event_type="openshift_virt_event", source="openshift_virt_event", title="t", severity="info",
                      raw_data={"external_key": key}, occurrence_count=1, created_at=datetime.utcnow())); s.commit()
    item = {"source_object": "vm1", "reason": "Started", "timestamp": "2026", "severity": "warning"}
    ok = ocpv._upsert_openshift_virt_event(s, SimpleNamespace(id=1, name="x"), item, datetime.utcnow(), ExternalKeyIndex(s))
    assert ok is False
    row = s.query(SystemEvent).one()
    assert row.severity == "warning" and row.occurrence_count == 1   # replay = tekrar değil


def test_virt_log_upsert_sql_side(db):
    s, _ = db
    s.add(SystemEvent(event_type="virt_log", source="virt_collector", title="t", severity="info",
                      raw_data={"external_key": "L1"}, occurrence_count=1, created_at=datetime.utcnow())); s.commit()
    ok = virt_log_collector._upsert_virt_event(s, {"id": "L1", "severity": "warning"}, "virt_log", datetime.utcnow())
    assert ok is False
    assert s.query(SystemEvent).one().occurrence_count == 1           # platform günlüğü replay'i tekrar sayılmaz
    ok2 = virt_log_collector._upsert_virt_event(s, {"id": "L2", "title": "yeni", "source": "x"}, "virt_log", datetime.utcnow())
    assert ok2 is True and s.query(SystemEvent).count() == 2


@pytest.mark.parametrize("mod,fn", [
    (vcenter_event_collector, "_upsert_vcenter_event"),
    (ovirt_event_collector, "_upsert"),
    (ocpv, "_upsert_openshift_virt_event"),
    (virt_log_collector, "_upsert_virt_event"),
])
def test_no_mass_orm_load_in_upsert(mod, fn):
    src = inspect.getsource(getattr(mod, fn))
    assert "existing_rows" not in src and ".all()" not in src


def test_sync_functions_pass_index():
    assert "ExternalKeyIndex(db)" in inspect.getsource(vcenter_event_collector.sync_vcenter_events_for_hypervisor)
    assert "ExternalKeyIndex(db)" in inspect.getsource(vcenter_event_collector.sync_vcenter_lifecycle_events)
    assert "ExternalKeyIndex(db)" in inspect.getsource(ovirt_event_collector.sync_ovirt_events_for_hypervisor)
    assert "ExternalKeyIndex(db)" in inspect.getsource(ocpv.sync_openshift_virt_events_for_hypervisor)


def test_dedupe_module_has_no_llm_or_http():
    src = inspect.getsource(event_dedupe)
    assert "requests" not in src and "llm" not in src.lower().replace("llm_", "x")


# ── Adım 11: senkron işleri event döngüsünden çıkarma (kaynak kancaları) ───────────────

def _src(path):
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    return (root / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["api/unified_chat.py", "api/chat.py", "api/windows_chat.py", "api/hypervisors.py"])
def test_attach_and_stream_offloaded_to_chat_executor(path):
    src = _src(path)
    assert "_stream_resp = await attach_and_stream_async(" in src
    assert "_stream_resp = attach_and_stream(" not in src


def test_http_bridge_async_wrapper_passes_loop_and_uses_chat_executor():
    src = _src("services/chat_orchestrator/http_bridge.py")
    assert "async def attach_and_stream_async" in src
    assert "run_chat_io(attach_and_stream, loop=asyncio.get_running_loop()" in src
    assert "loop=loop," in src          # create_turn'e iletilir
    svc = _src("services/chat_orchestrator/service.py")
    assert "loop.call_soon_threadsafe(_spawn_turn, loop, turn.id)" in svc


def test_spawn_turn_from_worker_thread_runs_on_loop(monkeypatch):
    """Regresyon: create_turn iş parçacığında çağrılınca run_turn ESKİDEN hiç başlamıyordu (get_running_loop RuntimeError)."""
    import asyncio, threading
    from app.services.chat_orchestrator import service as svc
    ran = []

    async def fake_run_turn(tid):
        ran.append((tid, threading.current_thread() is threading.main_thread()))

    monkeypatch.setattr(svc, "run_turn", fake_run_turn)

    async def main():
        loop = asyncio.get_running_loop()
        t = threading.Thread(target=lambda: loop.call_soon_threadsafe(svc._spawn_turn, loop, "T1"))
        t.start(); t.join()
        await asyncio.sleep(0.1)

    asyncio.run(main())
    assert ran == [("T1", True)]


def test_unified_route_and_plan_sources_offloaded():
    src = _src("api/unified_chat.py")
    assert "await run_chat_io(\n                    route_unified," in src
    assert src.count("await run_chat_io(\n                            plan_sources,") == 2
    assert "_route = route_unified(" not in src and "_plan = plan_sources(" not in src


def test_windows_plan_sources_offloaded():
    assert _src("api/windows_chat.py").count("await run_chat_io(plan_sources,") == 2


def test_ocp_live_handler_end_of_turn_plan_xread_and_gate_offloaded():
    assert "await run_chat_io(_openshift_ask_handler" in _src("api/chat.py")
    svc = _src("services/chat_orchestrator/service.py")
    assert "await chat_run_io(plan_sources, row.message" in svc
    assert "await chat_run_io(_timed_read)" in svc
    # Adım 13: kapı bekleme `asyncio.sleep` ile (iş parçacığı tutmaz); her yoklama kısa `run_chat_io` çağrısı
    assert "await ai_gate.acquire(turn_id, message=_gate_msg)" in svc
    gate_src = _src("services/chat_orchestrator/ai_gate.py")
    assert "time.sleep(" not in gate_src and "await asyncio.sleep(" in gate_src


def test_rag_search_and_background_enqueue_offloaded():
    assert "await run_chat_io(\n        hybrid_search_collection," in _src("services/rag_service.py")
    bg = _src("background_tasks.py")
    assert "await asyncio.to_thread(enqueue_fleet_job, task_name)" in bg
    assert "\n                        qa_cache.invalidate_all()" not in bg


def test_chat_executor_is_separate_from_default_and_copies_context():
    import asyncio, contextvars, threading
    from app.core import chat_executor as ce
    cv = contextvars.ContextVar("cv_test", default="x")

    async def main():
        cv.set("hello")
        return await ce.run_chat_io(lambda: (cv.get(), threading.current_thread().name))

    val, name = asyncio.run(main())
    assert val == "hello"            # bağlam kopyalanır (trace_scope vb. çalışsın)
    assert name.startswith("chat_io")  # varsayılan yürütücü DEĞİL
    assert ce.CHAT_IO_WORKERS >= 32


def test_chat_executor_not_blocked_by_saturated_default_executor():
    import asyncio, time
    from concurrent.futures import ThreadPoolExecutor
    from app.core import chat_executor as ce

    async def main():
        small = ThreadPoolExecutor(max_workers=2)
        asyncio.get_running_loop().set_default_executor(small)
        for _ in range(2):
            asyncio.get_running_loop().run_in_executor(None, time.sleep, 1.5)   # varsayılan havuzu doldur
        t0 = time.perf_counter()
        await ce.run_chat_io(lambda: 1)
        return time.perf_counter() - t0

    assert asyncio.run(main()) < 0.5


def test_automic_untouched_by_step11():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for p in list((root / "services" / "automic").glob("*.py")) + [root / "api" / "automation.py"]:
        assert "Adım 11" not in p.read_text(encoding="utf-8")


# ── loop_watchdog ──────────────────────────────────────────────────────────────

def test_loop_watchdog_disabled_by_env(monkeypatch):
    from app.core import loop_watchdog as lw
    monkeypatch.setenv("LOOP_WATCHDOG", "0")
    assert lw.enabled() is False
    monkeypatch.setenv("LOOP_WATCHDOG", "1")
    assert lw.enabled() is True


def test_loop_watchdog_stats_shape_and_hot_threads():
    from app.core import loop_watchdog as lw
    st = lw.stats()
    assert set(st) == {"max_stall_s", "stalls"}
    lw._sample_thread_cpu(); lw._sample_thread_cpu()
    assert isinstance(lw._hot_threads(), str)
    assert "iş parçacığı" in lw._thread_summary()


def test_loop_watchdog_detects_blocked_loop(caplog):
    import asyncio, logging, threading, time
    from app.core import loop_watchdog as lw
    lw._started = False
    caplog.set_level(logging.WARNING)

    async def main():
        lw.start(asyncio.get_running_loop())
        await asyncio.sleep(0.6)
        time.sleep(2.2)            # döngüyü blokla
        await asyncio.sleep(0.8)

    asyncio.run(main())
    assert any("LoopWatchdog" in r.getMessage() and "tıkalı" in r.getMessage() for r in caplog.records)
    lw._started = False


def test_no_data_answer_retry_llm_offloaded():
    src = _src("api/unified_chat.py")
    assert "await run_chat_io(\n                            maybe_fix_no_data_answer," in src
    assert "_fixed, _ev_reason = maybe_fix_no_data_answer(" not in src


def test_virt_resource_condition_refreshes_last_seen(db):
    """Kaynak izleyici koşul-tabanlı: koşul sürdükçe last_seen/occurrence yenilenir (olay açık kalır)."""
    s, _ = db
    old = datetime.utcnow() - timedelta(hours=3)
    s.add(SystemEvent(event_type="virt_resource", source="virt_resource", title="t", severity="warning",
                      raw_data={"external_key": "R1"}, occurrence_count=1, last_seen=old, created_at=old)); s.commit()
    now = datetime.utcnow()
    ok = virt_log_collector._upsert_virt_event(s, {"id": "R1", "severity": "warning", "source": "resource_monitor"},
                                               "virt_resource", now)
    assert ok is False
    row = s.query(SystemEvent).one()
    assert row.occurrence_count == 2 and row.last_seen >= old + timedelta(hours=2)
