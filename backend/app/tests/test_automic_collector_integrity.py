"""Collector doğruluk: idempotent upsert, stale uyarı, eski kullanıcı, maskeleme, reorg."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.automic.integrity import (
    bump_scanned_runid_ceiling,
    detect_reorg_gaps,
    stale_collection_warning,
)
from app.services.automic.masking import mask_text
from app.services.automic.users import LEGACY_USER_TAG, format_user_display


def test_stale_collection_warning():
    now = datetime.now(timezone.utc)
    st = SimpleNamespace(last_success_at=now - timedelta(hours=7))
    msg = stale_collection_warning(st, threshold_hours=6)
    assert msg and "KRİTİK" in msg
    st2 = SimpleNamespace(last_success_at=now - timedelta(hours=2))
    assert stale_collection_warning(st2, threshold_hours=6) is None


def test_legacy_user_display_label():
    assert LEGACY_USER_TAG in (format_user_display(user_name_at_run="BATCH/OPS", found=False) or "")
    assert "BATCH/OPS" in (format_user_display(user_name_at_run="BATCH/OPS", found=False) or "")
    assert format_user_display(user_idnr=7, found=False) == "bilinmeyen kullanıcı (ID: 7)"
    assert format_user_display(
        user_idnr=7, name="BATCH", department="OPS", found=True,
    ) == "BATCH/OPS"


@pytest.mark.parametrize("raw,leak", [
    ("sqlplus batch/HiddenPass@DWHPRD @/opt/run.sql", "HiddenPass"),
    ("connect app/Secret99@ORCL", "Secret99"),
    ('"connect app/Secret99"', "Secret99"),
    ("jdbc:oracle:thin:@h:1521/X;password=p4ssWord", "p4ssWord"),
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghi", "eyJhbGci"),
    ("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghi", "eyJhbGci"),
    ("mysqldump -pMySecretPass db", "MySecretPass"),
    ("tool --password=xyzSECRET", "xyzSECRET"),
    ("export PASSWORD=EnvSecret99", "EnvSecret99"),
    ("DSN=x;PWD=ConnPwd123;UID=u", "ConnPwd123"),
])
def test_masking_automic_report_patterns(raw, leak):
    out = mask_text(raw, {"country_pack": "none", "mask_ip": False})
    assert leak not in out
    assert "BATCH/OPS" in mask_text(f"{raw} user BATCH/OPS", {"country_pack": "none", "mask_ip": False})


def test_bump_scanned_ceiling_covers_idle_client():
    """Tarama tavanı idle client'ı da ilerletir; max-found kullanılmaz."""
    state = SimpleNamespace(run_id_watermark_by_client={})
    # Client 200 hiç satır üretmedi; yine de taranan üst sınır yazılır
    bump_scanned_runid_ceiling(state, [100, 200], 100_000)
    assert state.run_id_watermark_by_client["100"] == 100_000
    assert state.run_id_watermark_by_client["200"] == 100_000
    # Daha düşük tavan geri almaz
    bump_scanned_runid_ceiling(state, [100], 50_000)
    assert state.run_id_watermark_by_client["100"] == 100_000


def test_idle_client_no_false_loss_with_scanned_ceiling(monkeypatch):
    """Uzun süredir çalışmayan client: tarama tavanı > kaynak MIN → alarm yok."""
    from app.services.automic import integrity as integ

    system = SimpleNamespace(id=1, name="T")
    state = SimpleNamespace(run_id_watermark_by_client={})
    bump_scanned_runid_ceiling(state, [100, 200], 100_000)
    # Eski davranış: max-found=40k olsaydı src_min=50k alarm verirdi
    src = SimpleNamespace(min_run_id=lambda: 50_000)
    monkeypatch.setattr(
        integ, "client_runid_watermarks",
        lambda *a, **k: {100: 100_000, 200: 100_000},
    )
    n, warns = integ.detect_reorg_gaps(SimpleNamespace(), system, src, state, [100, 200])
    assert n == 0 and warns == []


def test_normal_reorg_no_alarm_when_source_min_below_watermark(monkeypatch):
    """Kaynak MIN yükseliyor ama watermark'ın altında → alarm yok."""
    from app.services.automic import integrity as integ

    system = SimpleNamespace(id=1, name="T")
    state = SimpleNamespace(run_id_watermark_by_client={"100": 90_000, "200": 85_000})
    src = SimpleNamespace(min_run_id=lambda: 50_000)
    monkeypatch.setattr(integ, "client_runid_watermarks", lambda *a, **k: {100: 90_000, 200: 85_000})
    n, warns = integ.detect_reorg_gaps(SimpleNamespace(), system, src, state, [100, 200])
    assert n == 0 and warns == []


def test_real_loss_when_source_min_above_watermark(monkeypatch):
    """Kaynak MIN > min(client watermark) → aralık kaydedilir, kritik uyarı."""
    from app.models.automic import AutomicDataGap
    from app.services.automic import integrity as integ
    from app.services.automic.database import ensure_schema, get_automic_thread_session
    from app.services.automic.service import resolve_system

    try:
        ensure_schema()
        adb = get_automic_thread_session()
    except Exception:
        pytest.skip("Automic modül DB yok")
    if adb is None:
        pytest.skip("Automic modül DB yok")
    try:
        system = resolve_system(adb, None)
        if system is None:
            pytest.skip("sistem yok")
        clients = [int(c) for c in (system.clients or [100])]
        state = SimpleNamespace(run_id_watermark_by_client={str(c): 40_000 for c in clients})
        src = SimpleNamespace(min_run_id=lambda: 50_000)
        monkeypatch.setattr(
            integ, "client_runid_watermarks",
            lambda *a, **k: {c: 40_000 for c in clients},
        )
        adb.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM automic_data_gaps WHERE system_id=:s AND reason='reorg'"
            ),
            {"s": system.id},
        )
        adb.commit()
        n, warns = integ.detect_reorg_gaps(adb, system, src, state, clients)
        adb.commit()
        assert n == 1
        assert any("KRİTİK" in w for w in warns)
        assert any("50000" in w for w in warns)
        assert any("40000" in w for w in warns)
        gap = adb.query(AutomicDataGap).filter_by(
            system_id=system.id, id_min=40_000, id_max=50_000).first()
        assert gap is not None and gap.reason == "reorg"
        assert "50000" in (gap.detail or "") and "40000" in (gap.detail or "")
        n2, _ = integ.detect_reorg_gaps(adb, system, src, state, clients)
        assert n2 == 1
        assert adb.query(AutomicDataGap).filter_by(
            system_id=system.id, id_min=40_000, id_max=50_000, resolved_at=None).count() == 1
    finally:
        # Test kaydı canlı modül DB'de açık "KRİTİK kayıp veri" bırakmasın (health ekranını kirletiyordu)
        try:
            adb.rollback()
            _sid = getattr(locals().get("system"), "id", None)
            if _sid is not None:
                adb.execute(__import__("sqlalchemy").text(
                    "DELETE FROM automic_data_gaps WHERE system_id=:s AND reason='reorg' "
                    "AND id_min=40000 AND id_max=50000"), {"s": _sid})
                adb.commit()
        except Exception:
            adb.rollback()
        adb.close()


def test_min_run_id_sql_has_no_client_filter():
    from app.services.automic.source import templates
    from app.tests.test_automic_official_schema import _full_mapping

    prof, mapping = _full_mapping()
    sql = templates.render(
        prof, "min_run_id", schema="UC4",
        table_map=mapping["executions"], limit=1,
    )
    assert "MIN(" in sql.upper()
    assert ":client" not in sql
    body = sql.upper().split("FETCH")[0]
    assert "WHERE" not in body


def test_idempotent_upsert_same_range_twice():
    """Aynı (client, run_id, activation_time) iki kez → tek satır; end_time güncellenir."""
    from app.models.automic import AutomicExecution
    from app.services.automic import collector as col
    from app.services.automic.database import ensure_schema, get_automic_thread_session
    from app.services.automic.service import resolve_system

    try:
        ensure_schema()
        adb = get_automic_thread_session()
    except Exception:
        pytest.skip("Automic modül DB yok")
    if adb is None:
        pytest.skip("Automic modül DB yok")
    try:
        system = resolve_system(adb, None)
        if system is None or system.source_type != "fake":
            pytest.skip("DEV-FAKE yok")
        sid = system.id
        client = int((system.clients or [100])[0])
        rid = 9_876_543_210
        act = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
        row = {
            "system_id": sid, "client": client, "run_id": rid,
            "activation_time": act, "end_time": t1,
            "object_name": "JOBS.TEST.IDEM.01", "object_type": "JOBS",
            "status_code": 1900, "status_class": "ok",
            "parent_run_id": None, "top_run_id": rid, "restart_ref_run_id": None,
            "folder": None, "start_time": t1,
            "duration_sec": 1.0, "agent": None, "platform": None, "queue": None,
            "user": "BATCH/OPS", "user_idnr": 7001, "user_name_at_run": "BATCH/OPS",
            "return_code": 0, "run_time_sec": 1, "ert_sec": 1,
        }
        adb.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM automic_executions WHERE system_id=:s AND client=:c AND run_id=:r"
            ),
            {"s": sid, "c": client, "r": rid},
        )
        adb.commit()
        col._upsert_executions(adb, [row])
        adb.commit()
        col._upsert_executions(adb, [dict(row)])
        adb.commit()
        n1 = adb.query(AutomicExecution).filter_by(
            system_id=sid, client=client, run_id=rid).count()
        assert n1 == 1
        col._upsert_executions(adb, [dict(row, end_time=t2, status_code=1800, status_class="failed")])
        adb.commit()
        rows = adb.query(AutomicExecution).filter_by(
            system_id=sid, client=client, run_id=rid).all()
        assert len(rows) == 1
        et = rows[0].end_time
        if et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)
        else:
            et = et.astimezone(timezone.utc)
        assert et == t2
        assert rows[0].status_class == "failed"
    finally:
        adb.close()


def test_executions_partitioned_by_activation_time():
    from sqlalchemy import text

    from app.services.automic.database import ensure_schema, get_automic_thread_session

    try:
        ensure_schema(force=True)
        adb = get_automic_thread_session()
    except Exception:
        pytest.skip("Automic modül DB yok")
    if adb is None:
        pytest.skip("Automic modül DB yok")
    try:
        dim = adb.execute(text(
            "SELECT column_name FROM timescaledb_information.dimensions "
            "WHERE hypertable_name='automic_executions' LIMIT 1"
        )).scalar()
        if dim is None:
            pytest.skip("Timescale yok")
        assert dim == "activation_time"
        pk = [r[0] for r in adb.execute(text(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = 'automic_executions'::regclass AND i.indisprimary "
            "ORDER BY array_position(i.indkey, a.attnum)"
        )).all()]
        assert pk == ["system_id", "client", "run_id", "activation_time"]
    finally:
        adb.close()


def test_count_ended_template_and_ae_default():
    from app.services.automic.defaults import DEFAULT_SETTINGS
    from app.services.automic.source import templates
    from app.tests.test_automic_official_schema import _full_mapping

    assert DEFAULT_SETTINGS.get("ae_version") == "24.4"
    prof, mapping = _full_mapping()
    sql = templates.render(
        prof, "count_ended_by_id_range", schema="UC4",
        table_map=mapping["executions"], clients_bind=":c0", limit=1,
    )
    assert "COUNT(*)" in sql.upper() and ":id_min" in sql and ":id_max" in sql
    sql_min = templates.render(
        prof, "min_run_id", schema="UC4",
        table_map=mapping["executions"], limit=1,
    )
    assert "MIN(" in sql_min.upper() and "WHERE" not in sql_min.upper().split("FETCH")[0]


def test_fake_run_id_scale_aligned():
    """latest_run_id / üretim / zaman→RunID aynı ölçekte (×10000); aksi collector 0 satır kilitler."""
    from app.services.automic.source.fake import (
        FakeSource, _RUN_ID_PER_MINUTE, run_id_hi_for_minute, run_id_lo_for_minute,
    )

    assert _RUN_ID_PER_MINUTE == 10_000
    src = FakeSource(system_id=1, connection={"fake_clients": [100]}, secret="", settings={})
    now = datetime.now(timezone.utc)
    minute = int(now.timestamp() // 60)
    latest = src.latest_run_id(100)
    assert run_id_lo_for_minute(minute) <= latest < run_id_hi_for_minute(minute)
    # Eski hatalı ×1000 tavanı yeni RunID'lerin altında kalır
    broken_hi = minute * 1000 + 999
    assert latest > broken_hi
    t_from = now - timedelta(minutes=30)
    bounds = src.runid_bounds_for_time(t_from, now)
    assert bounds and bounds[1] > bounds[0]
    items = src._minute_items(100, minute - 10)
    if items:
        assert bounds[0] <= items[0]["run_id"] < run_id_hi_for_minute(minute)
    # Yanlış (×1000) dilimde satır yok; doğru dilimde (zaman penceresi içinde) olabilir
    lag_to = now - timedelta(minutes=5)
    empty = src.fetch_ended_executions(
        [100], t_from, lag_to, limit=50,
        id_min=broken_hi - 500, id_max=broken_hi + 1,
    )
    assert empty == []
    lo, hi = bounds
    got = src.fetch_ended_executions([100], t_from, lag_to, limit=50, id_min=lo, id_max=hi)
    assert isinstance(got, list)


def test_ingest_stall_warning_zero_ticks(monkeypatch):
    from app.services.automic import integrity as integ

    now = datetime.now(timezone.utc)
    state = SimpleNamespace(
        watermark=now - timedelta(days=2),
        last_success_at=now - timedelta(minutes=5),
        last_rows=0,
    )
    runs = [(0, now - timedelta(minutes=i * 10)) for i in range(6)]

    class _R:
        def all(self):
            return runs

    class _DB:
        def execute(self, *a, **k):
            return _R()

    src = SimpleNamespace(source_has_ended_after=lambda after: True)
    msg = integ.ingest_stall_warning(_DB(), 1, state, src, zero_ticks=6)
    assert msg and "KRİTİK" in msg and "yeni kayıt yazılmadı" in msg

    runs_ok = [(3, now)] + runs[1:]
    class _R2:
        def all(self):
            return runs_ok
    class _DB2:
        def execute(self, *a, **k):
            return _R2()
    assert integ.ingest_stall_warning(_DB2(), 1, state, src, zero_ticks=6) is None


def test_resolve_fetch_bounds_extends_with_source_latest(monkeypatch):
    """Map tavanı kaynak latest'ın altındaysa id_max genişler (sessiz stall önlemi)."""
    from app.services.automic import collector as col
    from app.services.automic import runid_map

    monkeypatch.setattr(runid_map, "global_bounds", lambda *a, **k: (1_000, 2_000))
    monkeypatch.setattr(runid_map, "rebuild_from_executions", lambda *a, **k: 0)
    monkeypatch.setattr(
        runid_map, "bounds_for_time_range", lambda *a, **k: (1_000, 2_000),
    )
    src = SimpleNamespace(
        source_type="fake",
        latest_run_id=lambda c: 50_000,
        runid_bounds_for_time=lambda a, b: (40_000, 51_000),
    )
    warnings: list = []
    now = datetime.now(timezone.utc)
    bounds = col._resolve_fetch_bounds(
        SimpleNamespace(), src, 1, [100], now - timedelta(hours=1), now,
        {"max_rows_per_slice": 500, "runid_slack_hours": 24}, warnings,
    )
    assert bounds is not None
    assert bounds[0] == 40_000
    assert bounds[1] >= 50_001
