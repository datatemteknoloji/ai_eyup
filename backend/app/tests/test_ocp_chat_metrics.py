"""ocp_chat_metrics — katalog / alias / mode (DB yok)."""
from unittest.mock import MagicMock, patch

from app.services.ocp_chat_metrics import (
    _canon_kind,
    _canon_metric,
    run_ocp_monitoring_query,
)


def test_canon_kind_and_metric():
    assert _canon_kind("nodes") == "node"
    assert _canon_kind("pods") == "pod"
    assert _canon_kind("kubevirt") == "vm"
    assert _canon_metric("node", "cpu") == "cpu_pct"
    assert _canon_metric("node", "bellek") == "memory_pct"
    assert _canon_metric("pod", "cores") == "cpu_used_cores"


def test_catalog_mode_no_cluster():
    db = MagicMock()
    out = run_ocp_monitoring_query(db, list_catalog=True, kind="node")
    assert out["ok"] is True
    assert out["mode"] == "catalog"
    ids = {m["id"] for m in out["metrics"]}
    assert "cpu_pct" in ids and "memory_pct" in ids


def test_series_requires_names():
    db = MagicMock()
    cluster = MagicMock()
    cluster.id = 1
    cluster.name = "ocp-lab"
    with patch("app.services.ocp_chat_metrics._resolve_cluster", return_value=cluster):
        out = run_ocp_monitoring_query(db, mode="series", kind="node")
    assert out["ok"] is False
    assert "names" in (out.get("error") or "").lower()


def test_top_delegates(monkeypatch):
    db = MagicMock()
    cluster = MagicMock()
    cluster.id = 7
    cluster.name = "prod"
    fake = {"ok": True, "mode": "top", "items": [{"name": "w1", "value": 90.0}]}

    monkeypatch.setattr(
        "app.services.ocp_chat_metrics._resolve_cluster",
        lambda *_a, **_k: cluster,
    )
    monkeypatch.setattr(
        "app.services.ocp_chat_metrics.query_top",
        lambda *_a, **_k: fake,
    )
    out = run_ocp_monitoring_query(db, mode="top", kind="node", metric="cpu_pct", top_n=5)
    assert out["items"][0]["name"] == "w1"
