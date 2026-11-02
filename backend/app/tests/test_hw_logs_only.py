"""Faz 3c — portalsız (OME/OneView yok) «Donanım Logları» modu: kapı (`has_hw_logs`) + log uçları portalsız çalışır."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.services.hw import bmc_logs as BL
from app.services.hw import host_logs as HL
from app.services.hw import ipmi_inband as IP
from app.tests.test_hw_host_logs import _hv_with_hosts


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _flags(monkeypatch, host=False, ipmi=False, bmc=False):
    monkeypatch.setattr(HL, "enabled", lambda: host)
    monkeypatch.setattr(IP, "enabled", lambda: ipmi)
    monkeypatch.setattr(BL, "enabled", lambda: bmc)


def _client(db, role="admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import hw as hw_api, hw_bmc
    from app.core.auth import get_current_user
    from app.core.database import get_db
    app = FastAPI()
    app.include_router(hw_api.router, prefix="/hw")
    app.include_router(hw_bmc.router, prefix="/hw/bmc")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=1, username="u")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_logs_available_false_when_no_flag_and_no_rows(db, monkeypatch):
    _flags(monkeypatch)
    assert HL.logs_available(db) is False


@pytest.mark.parametrize("which", ["host", "ipmi", "bmc"])
def test_logs_available_true_when_any_flag_on(db, monkeypatch, which):
    _flags(monkeypatch, **{which: True})
    assert HL.logs_available(db) is True


def test_logs_available_true_when_rows_exist_even_if_flags_off(db, monkeypatch):
    _flags(monkeypatch)
    _hv, inv = _hv_with_hosts(db)
    now = datetime.now(timezone.utc)
    HL.ingest_lines(db, "esxi", inv.id, "esxi_sel", [HL.Item(now, "critical", "power", "PSU 2 failed")], now)
    db.commit()
    assert HL.logs_available(db) is True


def test_logs_available_never_raises(db, monkeypatch):
    _flags(monkeypatch)

    class Boom:
        def query(self, *a, **k):
            raise RuntimeError("db yok")

    assert HL.logs_available(Boom()) is False


def test_capabilities_payload_exposes_has_hw_logs(db, monkeypatch):
    from app.services import capabilities as cap
    monkeypatch.setattr(HL, "logs_available", lambda db=None: True)
    assert cap.capabilities_payload()["has_hw_logs"] is True
    monkeypatch.setattr(HL, "logs_available", lambda db=None: False)
    assert cap.capabilities_payload()["has_hw_logs"] is False
    # portal yeteneği log kapısından bağımsız: portal yokken has_hw False kalır
    assert cap.capabilities_payload()["has_hw"] is False


def test_log_overview_works_without_any_portal(db, monkeypatch):
    """Portal (HwManager/instance) YOK; yalnız ESXi logu var → 200, ESXi satırı görünür, portal_alert kapalı."""
    _flags(monkeypatch, host=True)
    _hv, inv = _hv_with_hosts(db)
    now = datetime.now(timezone.utc)
    HL.ingest_lines(db, "esxi", inv.id, "esxi_sel", [HL.Item(now, "critical", "power", "PSU 2 failed")], now)
    db.commit()
    r = _client(db).get("/hw/log-overview")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert [i["source"] for i in j["items"]] == ["esxi_sel"]
    assert j["items"][0]["host_class"] == "esxi"


def test_bmc_overview_works_without_any_portal(db, monkeypatch):
    _flags(monkeypatch, bmc=True)
    r = _client(db).get("/hw/bmc/overview")
    assert r.status_code == 200
    assert r.json().get("ok", True) is not False
