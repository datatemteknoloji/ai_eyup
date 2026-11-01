"""Sayfa açılışı raporu hesaplamaz; kilitli satırı okur."""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.models.infrastructure_report import InfrastructureReport
from app.services.exec_snapshot import produce_bundle


def _client(db):
    from app.api import executive_facts

    app = FastAPI()
    app.include_router(executive_facts.router, prefix="/ops")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_get_empty_does_not_build(isolated_db, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sayfa açılışı hesaplamamalı")

    monkeypatch.setattr("app.services.exec_snapshot.build_executive_facts", boom)
    res = _client(isolated_db).get("/ops/executive-facts")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "empty"
    assert body["reports"] == []
    assert body["refreshing"] is False


def test_get_returns_locked_bundle_without_recompute(isolated_db, monkeypatch):
    db = isolated_db
    db.add(InfrastructureReport(
        report_type="executive_bundle",
        report_title="Yönetici raporları",
        status="locked",
        generated_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        data={"locked": True, "period": {"start": "2026-10-01", "end": "2026-11-01"}, "facts": [{"report_type": "a1"}]},
    ))
    db.commit()

    def boom(*_a, **_k):
        raise AssertionError("kilitli rapor yeniden hesaplanmamalı")

    monkeypatch.setattr("app.services.exec_snapshot.build_executive_facts", boom)
    body = _client(db).get("/ops/executive-facts").json()
    assert body["status"] == "ready"
    assert body["reports"][0]["report_type"] == "a1"
    assert body["period"]["start"] == "2026-10-01"


def test_month_roll_locks_previous_bundle_once(isolated_db, monkeypatch):
    db = isolated_db
    db.add(InfrastructureReport(
        report_type="executive_bundle",
        report_title="Yönetici raporları",
        status="locked",
        generated_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        data={
            "locked": True,
            "period": {"start": "2026-09-01T00:00:00+00:00", "end": "2026-10-01T00:00:00+00:00"},
            "facts": [{"report_type": "a1", "sections": [{"id": "a1", "numbers": {"events": {"value": 8}}}]}],
        },
    ))
    db.commit()
    monkeypatch.setattr(
        "app.services.exec_snapshot.build_executive_facts",
        lambda *_a, **_k: [{"report_type": "a1", "sections": []}],
    )
    monkeypatch.setattr(
        "app.services.exec_snapshot.compose_summary",
        lambda *_a, **_k: {"text": "Özet cümlesi.", "source": "template"},
    )
    produce_bundle(isolated_db, now=datetime(2026, 10, 15, tzinfo=timezone.utc))
    produce_bundle(isolated_db, now=datetime(2026, 10, 20, tzinfo=timezone.utc))
    monthly = (
        db.query(InfrastructureReport)
        .filter(InfrastructureReport.report_type == "executive_monthly")
        .all()
    )
    assert len(monthly) == 1
    assert monthly[0].data["period"]["start"].startswith("2026-09-01")
    assert monthly[0].data["facts"][0]["sections"][0]["numbers"]["events"]["value"] == 8


def test_produce_writes_locked_row(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.exec_snapshot.build_executive_facts",
        lambda *_a, **_k: [{"report_type": "a1", "sections": []}],
    )
    monkeypatch.setattr(
        "app.services.exec_snapshot.compose_summary",
        lambda *_a, **_k: {"text": "Özet cümlesi.", "source": "template"},
    )
    row_id = produce_bundle(isolated_db)
    assert row_id
    body = _client(isolated_db).get("/ops/executive-facts").json()
    assert body["reports"][0]["report_type"] == "a1"
    assert body["status"] == "ready"
    assert body["summary"] == "Özet cümlesi."
    assert body["summary_source"] == "template"


def _stub_build(monkeypatch):
    monkeypatch.setattr("app.services.exec_snapshot.build_executive_facts",
                        lambda *_a, **_k: [{"report_type": "a1", "sections": []}])
    monkeypatch.setattr("app.services.exec_snapshot.compose_summary",
                        lambda *_a, **_k: {"text": "x", "source": "template"})


def _advisory_count(db) -> int:
    from sqlalchemy import text
    return db.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")).scalar()


def test_produce_does_not_leak_advisory_lock_across_pool_connections(isolated_db, monkeypatch):
    """Kilit oturum bağlantısında alınıp `rollback()` sonrası başka havuz bağlantısında bırakılmaya çalışılırsa
    kilit sızıyordu (sonraki üretimler None; tam takımda sıra bağımlı hata)."""
    from sqlalchemy import text
    _stub_build(monkeypatch)
    eng = isolated_db.get_bind()
    conns = [eng.connect() for _ in range(3)]
    for c in conns:
        c.execute(text("SELECT 1"))
    for c in conns:
        c.close()                                   # havuzda 3 boşta bağlantı
    ids = [produce_bundle(isolated_db) for _ in range(3)]
    assert all(ids)
    assert _advisory_count(isolated_db) == 0


def test_produce_returns_none_while_another_session_holds_the_lock(isolated_db, monkeypatch):
    from sqlalchemy import text
    from app.services import exec_snapshot as snap
    _stub_build(monkeypatch)
    eng = isolated_db.get_bind()
    other = eng.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        assert other.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": snap._LOCK}).scalar()
        assert produce_bundle(isolated_db) is None          # kilit dolu → üretim yok
    finally:
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": snap._LOCK})
        other.close()
    assert produce_bundle(isolated_db)                       # kilit düşünce üretir
    assert _advisory_count(isolated_db) == 0
