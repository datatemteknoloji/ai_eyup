"""Centrify DEMO veri uçları: varsayılan kapalı + yalnız admin (RBAC politikası ve uç bağımlılıkları)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.module_policy import min_role_for
from app.services.centrify import demo_gate


def _client(role: str) -> TestClient:
    from app.api import centrify_mgmt
    app = FastAPI()
    app.include_router(centrify_mgmt.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=1, username="t")
    return TestClient(app)


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_policy_requires_admin_for_demo_seed(method):
    assert min_role_for(method, "/api/v1/centrify-mgmt/demo/seed") == "admin"
    assert min_role_for("POST", "/api/v1/centrify-mgmt/zones") == "operator"      # diğer yazma uçları değişmedi


def test_flag_default_off(monkeypatch):
    monkeypatch.delenv(demo_gate.ENV_FLAG, raising=False)
    assert demo_gate.demo_enabled() is False


@pytest.mark.parametrize("method", ["post", "delete"])
def test_disabled_by_default_even_for_admin(monkeypatch, method):
    monkeypatch.delenv(demo_gate.ENV_FLAG, raising=False)
    r = getattr(_client("admin"), method)("/centrify-mgmt/demo/seed")
    assert r.status_code == 404 and "kapalı" in r.json()["detail"]


@pytest.mark.parametrize("method", ["post", "delete"])
def test_enabled_but_non_admin_forbidden(monkeypatch, method):
    monkeypatch.setenv(demo_gate.ENV_FLAG, "true")
    r = getattr(_client("operator"), method)("/centrify-mgmt/demo/seed")
    assert r.status_code == 403


def test_enabled_admin_can_seed(monkeypatch):
    monkeypatch.setenv(demo_gate.ENV_FLAG, "true")
    import app.services.centrify.demo_seed as ds
    monkeypatch.setattr(ds, "seed_demo_data", lambda: {"ok": True})
    r = _client("admin").post("/centrify-mgmt/demo/seed")
    assert r.status_code == 200 and r.json() == {"ok": True}
