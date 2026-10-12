"""Dilim C — Madde 14 snapshot_remove ön kontrol."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.backup.snapshot_guard import (
    backup_window_active,
    check_snapshot_remove,
    snapshot_looks_like_backup,
)


def test_backup_named_snapshot_blocked_without_provider(monkeypatch):
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.get_capabilities",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.backup_window_active",
        lambda db, now=None: False,
    )
    r = check_snapshot_remove(
        db=SimpleNamespace(),  # type: ignore[arg-type]
        snapshots=[{"name": "VEEAM BACKUP TEMPORARY SNAPSHOT", "ref": "snap-1"}],
        vm_name="vm1",
    )
    assert r["ok"] is False
    assert r["reason"] == "backup_named_snapshot"


def test_normal_snapshot_allowed(monkeypatch):
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.get_capabilities",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.backup_window_active",
        lambda db, now=None: False,
    )
    r = check_snapshot_remove(
        db=SimpleNamespace(),
        snapshots=[{"name": "before-patch", "ref": "snap-2"}],
        vm_name="vm1",
    )
    assert r["ok"] is True


def test_backup_window_blocks(monkeypatch):
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.get_capabilities",
        lambda: frozenset(),
    )
    monkeypatch.setattr(
        "app.services.backup.snapshot_guard.backup_window_active",
        lambda db, now=None: True,
    )
    r = check_snapshot_remove(
        db=SimpleNamespace(),
        snapshots=[{"name": "manual", "ref": "snap-3"}],
        vm_name="vm1",
    )
    assert r["ok"] is False
    assert r["reason"] == "backup_window"


def test_name_patterns():
    assert snapshot_looks_like_backup("Veeam Replica")
    assert not snapshot_looks_like_backup("weekly-clean")
