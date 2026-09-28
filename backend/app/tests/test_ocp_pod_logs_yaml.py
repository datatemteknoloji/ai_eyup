"""ocp_pod_logs / ocp_resource_yaml — READ_ONLY chat tools."""
from unittest.mock import MagicMock, patch

from app.services.agent.policy import RiskLevel
from app.services.agent.tools import (
    TOOLS,
    _ocp_pod_logs_handler,
    _ocp_resource_yaml_handler,
    domains_for_platform,
    tool_specs_read_only,
)


def test_tools_registered_read_only():
    for name in ("ocp_pod_logs", "ocp_resource_yaml"):
        assert name in TOOLS
        assert TOOLS[name].risk_level == RiskLevel.READ_ONLY
        assert "openshift" in (TOOLS[name].domains or set())
    names = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("openshift"))}
    assert "ocp_pod_logs" in names and "ocp_resource_yaml" in names
    # Mutating tools must not appear in chat specs
    assert "restart_service" not in names


def test_pod_logs_requires_ns_pod():
    db = MagicMock()
    assert _ocp_pod_logs_handler(db, {}, {})["ok"] is False
    assert "zorunlu" in (_ocp_pod_logs_handler(db, {"namespace": "a"}, {})["error"] or "")


def test_pod_logs_handler_ok():
    cluster = MagicMock()
    cluster.name = "lab"
    db = MagicMock()
    with patch("app.services.agent.tools.resolve_openshift_cluster", return_value=cluster), \
         patch("app.services.agent.tools._build_ocp_client") as build, \
         patch("app.services.openshift.cluster_ops.pod_logs") as logs:
        client = MagicMock()
        build.return_value = client
        logs.return_value = {"ok": True, "logs": "line1\n", "error": None}
        out = _ocp_pod_logs_handler(
            db, {"namespace": "shop", "pod": "api-0", "tail": 50}, {},
        )
        assert out["ok"] is True
        assert out["cluster"] == "lab"
        logs.assert_called_once()
        client.logout.assert_called_once()


def test_resource_yaml_handler_alias_and_truncate_hint():
    cluster = MagicMock()
    cluster.name = "lab"
    db = MagicMock()
    with patch("app.services.agent.tools.resolve_openshift_cluster", return_value=cluster), \
         patch("app.services.agent.tools._build_ocp_client") as build, \
         patch("app.services.openshift.cluster_ops.get_resource_yaml") as gy:
        client = MagicMock()
        build.return_value = client
        gy.return_value = {"ok": True, "yaml": "apiVersion: v1\n", "error": None}
        out = _ocp_resource_yaml_handler(
            db, {"kind": "pod", "name": "api-0", "namespace": "shop"}, {},
        )
        assert out["ok"] is True
        assert out["kind"] == "pods"
        gy.assert_called_once()
        assert gy.call_args[0][1] == "pods"
        assert "READ-ONLY" in (out.get("footnote") or "")
