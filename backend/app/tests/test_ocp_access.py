"""OpenShift Access / RBAC — unit tests (mocked HTTP)."""
from unittest.mock import MagicMock, patch

from app.services.openshift.ocp_access import (
    KIND_PATHS,
    _subject_key,
    _summarize_binding,
    _summarize_group,
    _summarize_user,
    list_access,
    run_access_query,
    subject_bindings,
)


def _resp(status: int, body: dict):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    return r


def test_kind_paths_cover_expected():
    expected = {
        "users", "groups", "identities", "roles", "clusterroles",
        "rolebindings", "clusterrolebindings", "serviceaccounts",
    }
    assert set(KIND_PATHS) == expected


def test_summarize_user_group_binding():
    u = _summarize_user({
        "metadata": {"name": "alice", "uid": "u1"},
        "fullName": "Alice A",
        "identities": ["htpasswd:alice"],
        "groups": [],
    })
    assert u["name"] == "alice" and u["full_name"] == "Alice A"
    g = _summarize_group({
        "metadata": {"name": "admins"},
        "users": ["alice", "bob"],
    })
    assert g["user_count"] == 2
    b = _summarize_binding({
        "metadata": {"name": "admins-crb"},
        "roleRef": {"kind": "ClusterRole", "name": "cluster-admin", "apiGroup": "rbac.authorization.k8s.io"},
        "subjects": [{"kind": "User", "name": "alice"}],
    }, cluster=True)
    assert b["kind"] == "ClusterRoleBinding"
    assert b["subjects"][0]["key"] == "user:alice"
    assert _subject_key({"kind": "ServiceAccount", "namespace": "ns", "name": "runner"}) == "sa:ns/runner"


def test_list_access_filters_and_403():
    client = MagicMock()
    client._get.return_value = _resp(200, {
        "items": [
            {"metadata": {"name": "alice"}, "identities": [], "groups": []},
            {"metadata": {"name": "bob"}, "identities": [], "groups": []},
        ],
    })
    out = list_access(client, "users", q="ali", limit=50)
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["items"][0]["name"] == "alice"

    client._get.return_value = _resp(403, {})
    denied = list_access(client, "users")
    assert denied["ok"] is False
    assert "403" in (denied.get("error") or "")


def test_list_access_invalid_kind():
    out = list_access(MagicMock(), "widgets")
    assert out["ok"] is False


def test_subject_bindings_matches_user():
    client = MagicMock()

    def fake_get(path, params=None, timeout=None):
        if path.endswith("/rolebindings"):
            return _resp(200, {
                "items": [{
                    "metadata": {"name": "edit-alice", "namespace": "shop"},
                    "roleRef": {"kind": "ClusterRole", "name": "edit"},
                    "subjects": [{"kind": "User", "name": "alice"}],
                }],
            })
        if path.endswith("/clusterrolebindings"):
            return _resp(200, {
                "items": [{
                    "metadata": {"name": "view-all"},
                    "roleRef": {"kind": "ClusterRole", "name": "view"},
                    "subjects": [{"kind": "Group", "name": "devs"}],
                }],
            })
        return _resp(404, {})

    client._get.side_effect = fake_get
    out = subject_bindings(client, subject_kind="User", subject_name="alice")
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["bindings"][0]["name"] == "edit-alice"
    assert out["bindings"][0]["kind"] == "RoleBinding"


def test_run_access_query_modes():
    client = MagicMock()
    with patch("app.services.openshift.ocp_access.access_overview", return_value={"ok": True, "counts": {}}) as ov:
        assert run_access_query(client, mode="overview")["ok"] is True
        ov.assert_called_once()
    with patch("app.services.openshift.ocp_access.list_access", return_value={"ok": True, "items": []}) as li:
        run_access_query(client, mode="list", kind="groups", q="x")
        li.assert_called_once()
    with patch("app.services.openshift.ocp_access.identity_providers", return_value={"ok": True}) as idp:
        run_access_query(client, mode="idp")
        idp.assert_called_once()
    bad = run_access_query(client, mode="mutate")
    assert bad["ok"] is False


def test_tool_registered():
    from app.services.agent.tools import TOOLS, domains_for_platform
    assert "ocp_access_query" in TOOLS
    tool = TOOLS["ocp_access_query"]
    assert "openshift" in (tool.domains or set())
    specs = {s["function"]["name"] for s in __import__(
        "app.services.agent.tools", fromlist=["tool_specs_read_only"]
    ).tool_specs_read_only(domains_for_platform("openshift"))}
    assert "ocp_access_query" in specs
