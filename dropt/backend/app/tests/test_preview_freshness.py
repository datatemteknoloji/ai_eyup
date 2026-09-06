"""preview_freshness birim testleri."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.base import HostPlan
from app.services.preview_freshness import (
    StalePreviewError,
    fingerprint_state,
    normalize_commands,
    revalidate_job_preview,
)


def test_normalize_commands_skips_comments():
    assert normalize_commands(["  # note", "lvextend -L +1G", "", "#x", "mkfs.xfs /dev/x"]) == [
        "lvextend -L +1G",
        "mkfs.xfs /dev/x",
    ]


def test_fingerprint_ignores_volatile():
    a = fingerprint_state({"vg_free_g": 10, "timestamp": "t1", "mount": "/data"})
    b = fingerprint_state({"vg_free_g": 10, "timestamp": "t2", "mount": "/data"})
    assert a == b
    c = fingerprint_state({"vg_free_g": 9, "mount": "/data"})
    assert a != c


def test_revalidate_detects_command_drift(monkeypatch):
    job = SimpleNamespace(id=1, module="filesystem", action="extend", server_ids=[7], payload={})
    run = SimpleNamespace(
        target_server_id=7,
        hostname="db01",
        status=SimpleNamespace(value="pending"),
        planned_commands=["lvextend -L +1G /dev/vg/lv"],
        before_state={"vg_free_g": 10, "mount": "/data"},
    )
    # Make status comparable to JobRunStatus.skipped
    from app.models.job import JobRunStatus

    run.status = JobRunStatus.pending

    session = MagicMock()
    session.exec.return_value.all.side_effect = [
        [SimpleNamespace(id=7, hostname="db01", ip="1.1.1.1")],  # servers
        [run],  # runs
    ]

    fresh = HostPlan(
        server_id=7,
        hostname="db01",
        ip="1.1.1.1",
        ok=True,
        summary_tr="x",
        planned_commands=["lvextend -L +5G /dev/vg/lv"],  # changed size
        before_state={"vg_free_g": 10, "mount": "/data"},
    )

    class FakeMod:
        def build_plans(self, session, action, servers, payload):
            return [fresh]

    monkeypatch.setattr("app.services.preview_freshness.get_module", lambda name: FakeMod())

    # session.exec used twice with different queries — simplify by custom side_effect
    servers = [SimpleNamespace(id=7, hostname="db01", ip="1.1.1.1")]
    calls = {"n": 0}

    def _exec(stmt):
        calls["n"] += 1
        m = MagicMock()
        if calls["n"] == 1:
            m.all.return_value = servers
        else:
            m.all.return_value = [run]
        return m

    session.exec.side_effect = _exec

    with pytest.raises(StalePreviewError) as ei:
        revalidate_job_preview(session, job)  # type: ignore[arg-type]
    assert "komutlar değişmiş" in str(ei.value)


def test_revalidate_detects_state_drift(monkeypatch):
    from app.models.job import JobRunStatus

    job = SimpleNamespace(id=2, module="network", action="change_ip", server_ids=[3], payload={})
    run = SimpleNamespace(
        target_server_id=3,
        hostname="app01",
        status=JobRunStatus.pending,
        planned_commands=["nmcli con mod eth0 ipv4.addresses 10.0.0.5/24"],
        before_state={"ip": "10.0.0.5", "iface": "eth0"},
    )
    fresh = HostPlan(
        server_id=3,
        hostname="app01",
        ip="10.0.0.1",
        ok=True,
        summary_tr="x",
        planned_commands=["nmcli con mod eth0 ipv4.addresses 10.0.0.5/24"],
        before_state={"ip": "10.0.0.9", "iface": "eth0"},  # live IP changed
    )

    class FakeMod:
        def build_plans(self, session, action, servers, payload):
            return [fresh]

    monkeypatch.setattr("app.services.preview_freshness.get_module", lambda name: FakeMod())
    session = MagicMock()
    calls = {"n": 0}

    def _exec(stmt):
        calls["n"] += 1
        m = MagicMock()
        m.all.return_value = (
            [SimpleNamespace(id=3, hostname="app01", ip="10.0.0.1")] if calls["n"] == 1 else [run]
        )
        return m

    session.exec.side_effect = _exec

    with pytest.raises(StalePreviewError) as ei:
        revalidate_job_preview(session, job)  # type: ignore[arg-type]
    assert "durumu önizlemeden" in str(ei.value)


def test_revalidate_ok_when_same(monkeypatch):
    from app.models.job import JobRunStatus

    job = SimpleNamespace(id=3, module="log_collect", action="package", server_ids=[1], payload={})
    state = {"template": "journal", "hours": 1}
    cmds = ["journalctl --since '-1h'"]
    run = SimpleNamespace(
        target_server_id=1,
        hostname="h",
        status=JobRunStatus.pending,
        planned_commands=cmds,
        before_state=state,
    )
    fresh = HostPlan(
        server_id=1, hostname="h", ip="1.1.1.1", ok=True, summary_tr="ok",
        planned_commands=list(cmds), before_state=dict(state),
    )

    class FakeMod:
        def build_plans(self, *a, **k):
            return [fresh]

    monkeypatch.setattr("app.services.preview_freshness.get_module", lambda name: FakeMod())
    session = MagicMock()
    calls = {"n": 0}

    def _exec(stmt):
        calls["n"] += 1
        m = MagicMock()
        m.all.return_value = (
            [SimpleNamespace(id=1, hostname="h", ip="1.1.1.1")] if calls["n"] == 1 else [run]
        )
        return m

    session.exec.side_effect = _exec
    out = revalidate_job_preview(session, job)  # type: ignore[arg-type]
    assert 1 in out
