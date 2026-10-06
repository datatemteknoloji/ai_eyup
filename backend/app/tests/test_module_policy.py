"""Modül izolasyonu: yetkisi olmayan modülün hiçbir API'sine erişilemez."""
import pytest

from app.core import module_policy as mp
from app.core.module_policy import decide, find_rule, min_role_for

EXEMPT = ("/api/v1/auth/", "/api/v1/public/")


def _d(role="operator", modules=(), method="GET", path="/api/v1/servers/", query=None):
    return decide(role=role, modules=modules, method=method, path=path, query=query or {})


# ── Kapsam: her kayıtlı route bir kurala bağlı olmalı ────────────────────────
def test_every_registered_route_is_classified():
    from app.main import app

    missing = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/v1/") or path.startswith(EXEMPT):
            continue
        if find_rule(path) is None:
            missing.append(path)
    assert not missing, f"Modül politikasında sınıflandırılmamış route'lar: {sorted(set(missing))[:20]}"


# ── Admin ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/api/v1/openshift/clusters", "/api/v1/windows/servers/1/run-ps", "/api/v1/mcp/tools",
    "/api/v1/hypervisors/", "/api/v1/centrify-mgmt/zones", "/api/v1/knowledge/",
])
def test_admin_bypass(path):
    assert _d(role="admin", path=path, method="POST").allowed


# ── Yetkisiz modül → 403 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("modules,path", [
    (("level1",), "/api/v1/openshift/clusters"),
    (("level1",), "/api/v1/hypervisors/"),
    (("level1",), "/api/v1/windows/servers"),
    (("level1",), "/api/v1/exadata/racks"),
    (("level1",), "/api/v1/servers/"),
    (("level1",), "/api/v1/ansible/adhoc"),
    (("level1",), "/api/v1/events/"),
    (("level1",), "/api/v1/ops/command-center"),
    (("level1",), "/api/v1/integrations/summary"),
    (("linux",), "/api/v1/openshift/clusters"),
    (("linux",), "/api/v1/windows/servers"),
    (("linux",), "/api/v1/hypervisors/"),
    (("linux",), "/api/v1/virt-insights/summary"),
    (("linux",), "/api/v1/ocp-insights/summary"),
    (("linux",), "/api/v1/centrify-mgmt/zones"),
    (("linux",), "/api/v1/knowledge/"),
    (("windows",), "/api/v1/ansible/playbook"),
    (("windows",), "/api/v1/terminal/ws/1"),
    (("virtualization",), "/api/v1/openshift/clusters"),
    (("virtualization",), "/api/v1/windows/servers"),
    (("openshift",), "/api/v1/hypervisors/"),
    (("openshift",), "/api/v1/exadata/racks"),
    (("exadata",), "/api/v1/openshift/nodes"),
    (("monitoring",), "/api/v1/openshift/clusters"),
    (("monitoring",), "/api/v1/hypervisors/"),
    (("applications",), "/api/v1/windows/servers"),
    (("ai_automation",), "/api/v1/openshift/clusters"),
    (("ai_automation",), "/api/v1/windows/servers"),
    ((), "/api/v1/servers/"),
    ((), "/api/v1/events/"),
    ((), "/api/v1/ops/summary"),
    ((), "/api/v1/unified-chat/stream"),
])
def test_missing_module_is_denied(modules, path):
    d = _d(modules=modules, path=path)
    assert not d.allowed and d.status == 403


# ── Yetkili modül → izin ─────────────────────────────────────────────────────
@pytest.mark.parametrize("modules,path", [
    (("openshift",), "/api/v1/openshift/clusters"),
    (("openshift",), "/api/v1/ocp-insights/summary"),
    (("virtualization",), "/api/v1/hypervisors/"),
    (("virtualization",), "/api/v1/virt-insights/summary"),
    (("windows",), "/api/v1/windows/servers"),
    (("linux",), "/api/v1/servers/"),
    (("linux",), "/api/v1/updates/plans"),
    (("exadata",), "/api/v1/exadata/racks"),
    (("level1",), "/api/v1/level1/linux-servers"),
    (("level1",), "/api/v1/centrify-mgmt/zones"),
    (("integrations",), "/api/v1/ucmdb/connection"),
    (("integrations",), "/api/v1/hypervisors/"),
    (("monitoring",), "/api/v1/monitoring/zabbix/sources"),
    (("knowledge",), "/api/v1/knowledge/"),
    (("applications",), "/api/v1/applications/"),
    (("custom_reports",), "/api/v1/custom-reports/"),
    (("ai_automation",), "/api/v1/unified-chat/sessions"),
    (("linux",), "/api/v1/events/"),
    (("windows",), "/api/v1/incidents/"),
    ((), "/api/v1/modules/my"),
    ((), "/api/v1/settings/"),
])
def test_assigned_module_is_allowed(modules, path):
    assert _d(modules=modules, path=path).allowed


def test_executive_is_read_only_on_platform_data():
    assert _d(modules=("executive",), path="/api/v1/ops/executive-summary").allowed
    assert _d(modules=("executive",), path="/api/v1/hypervisors/").allowed
    assert not _d(modules=("executive",), path="/api/v1/hypervisors/sync-all-vms", method="POST").allowed
    assert not _d(modules=("executive",), path="/api/v1/ansible/adhoc", method="POST").allowed
    assert not _d(modules=("linux",), path="/api/v1/ops/executive-summary").allowed


# ── Platform parametresi ─────────────────────────────────────────────────────
def test_platform_param_requires_module():
    assert not _d(modules=("linux",), path="/api/v1/events/", query={"platform": "openshift"}).allowed
    assert not _d(modules=("linux",), path="/api/v1/incidents/stats", query={"platform": "virt"}).allowed
    assert _d(modules=("linux",), path="/api/v1/events/", query={"platform": "linux"}).allowed
    assert _d(modules=("virtualization",), path="/api/v1/ops/summary", query={"platform": "virt"}).allowed


def test_platform_reports_path_param():
    assert not _d(modules=("linux",), path="/api/v1/platform-reports/openshift/catalog").allowed
    assert _d(modules=("openshift",), path="/api/v1/platform-reports/openshift/catalog").allowed


# ── Rol tabanlı yazma / komut çalıştırma ─────────────────────────────────────
def test_run_ps_requires_admin_even_with_module():
    p = "/api/v1/windows/servers/3/run-ps"
    assert not _d(role="operator", modules=("windows",), path=p, method="POST").allowed
    assert _d(role="admin", modules=(), path=p, method="POST").allowed


def test_exec_endpoints_need_operator():
    for p in ("/api/v1/windows/adhoc", "/api/v1/windows/servers/1/reboot"):
        assert not _d(role="viewer", modules=("windows",), path=p, method="POST").allowed
        assert _d(role="operator", modules=("windows",), path=p, method="POST").allowed
    assert not _d(role="viewer", modules=("linux",), path="/api/v1/ansible/adhoc", method="POST").allowed
    assert _d(role="operator", modules=("linux",), path="/api/v1/ansible/adhoc", method="POST").allowed


def test_credentials_writes_admin_only():
    for m in ("POST", "PUT", "DELETE"):
        assert not _d(role="operator", modules=("linux",), path="/api/v1/settings/credentials/1", method=m).allowed
    assert _d(role="operator", modules=("linux",), path="/api/v1/settings/credentials/", method="GET").allowed


def test_mcp_admin_only():
    assert not _d(role="operator", modules=("ai_automation", "linux"), path="/api/v1/mcp/call-tool", method="POST").allowed
    assert not _d(role="operator", modules=("ai_automation",), path="/api/v1/mcp/tools").allowed


def test_min_role_for_no_rule():
    assert min_role_for("GET", "/servers/") is None


def test_unclassified_path_is_admin_only():
    assert not _d(role="operator", modules=("linux",), path="/api/v1/brand-new-router/x").allowed
    assert _d(role="admin", path="/api/v1/brand-new-router/x").allowed


# ── WebSocket yardımcısı ─────────────────────────────────────────────────────
class _U:
    def __init__(self, role): self.role = role; self.id = 1


def test_can_open_shell(monkeypatch):
    from app.core import auth

    monkeypatch.setattr(auth, "user_has_module", lambda u, m, db: m == "linux")
    assert auth.can_open_shell(_U("operator"), None, "linux", "operator")
    assert not auth.can_open_shell(_U("viewer"), None, "linux", "operator")
    assert not auth.can_open_shell(_U("operator"), None, "openshift", "operator")


# ── Unified chat süzgeci ─────────────────────────────────────────────────────
def test_chat_route_denied_modules():
    from app.api.unified_chat import _route_denied_modules
    from app.services.unified_intent_router import UnifiedRoute

    def r(**kw):
        base = dict(mode="live", domains=frozenset({"infra"}), need_rag=True, need_live=True,
                    complexity="normal", confidence=0.9, reason="t")
        base.update(kw)
        return UnifiedRoute(**base)

    assert _route_denied_modules(r(modules=("openshift",)), {"linux"}) == ["openshift"]
    assert _route_denied_modules(r(modules=("virt", "linux")), {"linux"}) == ["virt"]
    assert _route_denied_modules(r(modules=("linux",)), {"linux"}) == []
    assert _route_denied_modules(r(modules=("openshift",)), None) == []
    assert _route_denied_modules(r(mode="knowledge", modules=()), set()) == []
    assert _route_denied_modules(r(wants_openshift=True), {"windows"}) == ["openshift"]


# ── Middleware entegrasyonu ──────────────────────────────────────────────────
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.core import principal
    from app.core.security import create_access_token
    from app.main import app

    state = {"role": "operator", "modules": frozenset(), "active": True}

    def fake(payload):
        if not state["active"]:
            return None
        return principal.Principal(424242, "pol_test", state["role"], frozenset(state["modules"]))

    monkeypatch.setattr(principal, "principal_from_payload", fake)
    tok = create_access_token("pol_test", extra={"uid": 424242}, expires_minutes=5)
    c = TestClient(app, headers={"Authorization": f"Bearer {tok}"}, raise_server_exceptions=False)
    c.state = state
    return c


def test_middleware_blocks_other_module(client):
    client.state["modules"] = frozenset({"level1"})
    for path in ("/api/v1/openshift/clusters", "/api/v1/hypervisors/", "/api/v1/servers/",
                 "/api/v1/windows/servers", "/api/v1/exadata/racks", "/api/v1/events/",
                 "/api/v1/ops/executive-summary", "/api/v1/mcp/tools", "/api/v1/settings/credentials/"):
        r = client.get(path) if path != "/api/v1/settings/credentials/" else client.post(path, json={})
        assert r.status_code == 403, (path, r.status_code, r.text[:120])


def test_middleware_allows_own_module(client):
    client.state["modules"] = frozenset({"openshift"})
    r = client.get("/api/v1/openshift/clusters")
    assert r.status_code != 403


def test_middleware_inactive_user_rejected(client):
    client.state["active"] = False
    assert client.get("/api/v1/openshift/clusters").status_code == 401


def test_middleware_unknown_path_is_404_not_403(client):
    client.state["modules"] = frozenset({"level1"})
    assert client.get("/api/v1/definitely-not-a-route").status_code == 404


def test_middleware_no_token_401():
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/v1/openshift/clusters").status_code == 401
