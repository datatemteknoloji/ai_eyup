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


def test_produce_writes_locked_row(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.exec_snapshot.build_executive_facts",
        lambda *_a, **_k: [{"report_type": "a1", "sections": []}],
    )
    row_id = produce_bundle(isolated_db)
    assert row_id
    body = _client(isolated_db).get("/ops/executive-facts").json()
    assert body["reports"][0]["report_type"] == "a1"
    assert body["status"] == "ready"
