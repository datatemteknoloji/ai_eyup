"""Linux × virt I/O korelasyonu — kural, join, data_status."""
from types import SimpleNamespace

from app.services.chat_data_status import NOT_QUERIED, PARTIAL, SUCCESS, SUCCESS_EMPTY
from app.services.cross_domain_diagnostics import (
    classify_io_pair,
    correlate_linux_virt_io,
    _proven_join,
)
from app.services.agent.tools import domains_for_platform, tool_specs_read_only


def test_both_high_is_correlated_storage():
    finding = classify_io_pair(35.0, 40.0)
    assert finding["correlated"] is True
    assert finding["layer"] == "storage"
    assert finding["severity"] == "high"


def test_guest_high_virt_normal_is_not_correlated():
    finding = classify_io_pair(40.0, 5.0)
    assert finding["correlated"] is False
    assert finding["layer"] == "guest"


def test_virt_high_guest_normal_is_hypervisor():
    finding = classify_io_pair(4.0, 45.0)
    assert finding["correlated"] is False
    assert finding["layer"] == "hypervisor"


def test_missing_metrics_never_correlate():
    assert classify_io_pair(None, None)["correlated"] is False
    assert classify_io_pair(40.0, None)["correlated"] is False
    assert classify_io_pair(None, 40.0)["correlated"] is False


def test_empty_name_is_not_queried():
    out = correlate_linux_virt_io(SimpleNamespace(), name="")
    assert out["ok"] is False
    assert out["data_status"] == NOT_QUERIED


def test_no_rows_is_success_empty(monkeypatch):
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics.resolve_linux_virt_pair",
        lambda db, name: {"ok": True, "join": None, "linux": None, "virt_vm": None},
    )
    out = correlate_linux_virt_io(SimpleNamespace(), name="ghost")
    assert out["data_status"] == SUCCESS_EMPTY
    assert "korelasyon yok" in out["note"]


def test_both_sides_without_join_skips_metrics(monkeypatch):
    called = {"guest": 0, "vm": 0}

    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics.resolve_linux_virt_pair",
        lambda db, name: {
            "ok": True,
            "join": None,
            "linux": {"id": 1, "name": "lnx"},
            "virt_vm": {"id": 2, "vm_name": "other"},
        },
    )

    def _guest(*_a, **_k):
        called["guest"] += 1
        return {"value": 99, "samples": 3, "source": "metric_data"}

    def _vm(*_a, **_k):
        called["vm"] += 1
        return {"value": 99, "samples": 3, "source": "virt_vm_metrics"}

    monkeypatch.setattr("app.services.cross_domain_diagnostics._guest_iowait", _guest)
    monkeypatch.setattr("app.services.cross_domain_diagnostics._vm_disk_latency", _vm)

    out = correlate_linux_virt_io(SimpleNamespace(), name="lnx")
    assert out["data_status"] == PARTIAL
    assert called == {"guest": 0, "vm": 0}
    assert "birleştirilmedi" in out["note"]


def test_joined_pair_returns_success(monkeypatch):
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics.resolve_linux_virt_pair",
        lambda db, name: {
            "ok": True,
            "join": "same_row",
            "linux": {"id": 7, "name": "web01"},
            "virt_vm": {"id": 7, "vm_name": "web01"},
        },
    )
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics._guest_iowait",
        lambda *_a, **_k: {"value": 32.0, "samples": 10, "source": "metric_data"},
    )
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics._vm_disk_latency",
        lambda *_a, **_k: {"value": 28.0, "samples": 8, "source": "virt_vm_metrics"},
    )
    out = correlate_linux_virt_io(SimpleNamespace(), name="web01")
    assert out["data_status"] == SUCCESS
    assert out["correlated"] is True
    assert out["guest_iowait_p95"] == 32.0
    assert out["vm_disk_latency_p95_ms"] == 28.0


def test_joined_but_one_metric_is_partial(monkeypatch):
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics.resolve_linux_virt_pair",
        lambda db, name: {
            "ok": True,
            "join": "name",
            "linux": {"id": 3, "name": "db01"},
            "virt_vm": {"id": 9, "vm_name": "db01"},
        },
    )
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics._guest_iowait",
        lambda *_a, **_k: {"value": 41.0, "samples": 4, "source": "metric_data"},
    )
    monkeypatch.setattr(
        "app.services.cross_domain_diagnostics._vm_disk_latency",
        lambda *_a, **_k: {"value": None, "samples": 0, "source": None},
    )
    out = correlate_linux_virt_io(SimpleNamespace(), name="db01")
    assert out["data_status"] == PARTIAL
    assert out["correlated"] is False
    assert out["layer"] == "guest_only"


def test_proven_join_requires_shared_key():
    a = SimpleNamespace(
        id=1, name="web01", vm_name="web01", vm_guest_hostname="web01",
        ip_address="10.0.0.1", vm_guest_ip=None, hypervisor_id=4,
    )
    b = SimpleNamespace(
        id=2, name="other", vm_name="other", vm_guest_hostname="other",
        ip_address="10.0.0.9", vm_guest_ip=None, hypervisor_id=4,
    )
    assert _proven_join(a, a) == "same_row"
    assert _proven_join(a, b) is None
    b.vm_name = "web01"
    assert _proven_join(a, b) == "hypervisor_id"


def test_tool_visible_on_linux_and_virt_not_windows():
    linux = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("linux"))}
    virt = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("virt"))}
    win = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("windows"))}
    ocp = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("openshift"))}
    assert "linux_virt_io_correlate" in linux
    assert "linux_virt_io_correlate" in virt
    assert "linux_virt_io_correlate" not in win
    assert "linux_virt_io_correlate" not in ocp
