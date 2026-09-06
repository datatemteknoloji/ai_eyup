"""host_op_lock birim testleri."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.host_op_lock import (
    HostLockError,
    _format_blockers,
    _lock_key,
    acquire_server_locks,
    release_server_locks,
    BlockingJobInfo,
)


def test_format_blockers_tr():
    msg = _format_blockers(
        [
            BlockingJobInfo(
                job_id=42,
                username="ali",
                module="sysctl",
                action="set",
                status="running",
                server_ids=[7],
            )
        ],
        {7: "db01"},
    )
    assert "iş #42" in msg
    assert "ali" in msg
    assert "db01" in msg


def test_acquire_releases_partial_on_conflict(monkeypatch):
    job = SimpleNamespace(id=10, server_ids=[1, 2], created_by_username="a")

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, xx=False, ex=None):
            if nx and key in store:
                return False
            if xx and key not in store:
                return False
            store[key] = value
            return True

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr("app.services.host_op_lock._redis", lambda: FakeRedis())
    monkeypatch.setattr("app.services.host_op_lock.find_blocking_jobs", lambda session, j: [])

    # Pre-lock server 2 as another job
    store[_lock_key(2)] = "99|other"

    session = MagicMock()
    with pytest.raises(HostLockError):
        acquire_server_locks(session, job)  # type: ignore[arg-type]

    # Partial lock on server 1 must be rolled back
    assert _lock_key(1) not in store
    assert store[_lock_key(2)] == "99|other"


def test_acquire_and_release_happy(monkeypatch):
    job = SimpleNamespace(id=5, server_ids=[3], created_by_username="ayse")
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, nx=False, xx=False, ex=None):
            if nx and key in store:
                return False
            store[key] = value
            return True

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr("app.services.host_op_lock._redis", lambda: FakeRedis())
    monkeypatch.setattr("app.services.host_op_lock.find_blocking_jobs", lambda session, j: [])

    held = acquire_server_locks(MagicMock(), job)  # type: ignore[arg-type]
    assert held == [3]
    assert store[_lock_key(3)].startswith("5|")
    release_server_locks(job, held)  # type: ignore[arg-type]
    assert _lock_key(3) not in store
