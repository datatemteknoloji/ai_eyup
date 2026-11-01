"""VM-sync kilit sorunu (uygulama kilitlenmesi) kök neden + bekçi testleri.

Kök neden: toplu VM sync tek oturumu saatlerce açık tuttu (erişilemeyen ZZ-FAKE vCenter için her sunucuda
10 sn zaman aşımı); TimescaleDB retention'ın AccessExclusive talebi bu işlemin arkasına, tüm okumalar da
retention'ın arkasına kuyruğa girdi.
"""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import create_engine, text

from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401


def _mk_hv(db, name, ip="10.0.0.1"):
    from app.models.hypervisor import Hypervisor, HypervisorType
    hv = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=name, ip_address=ip,
                    connection_config={})
    db.add(hv)
    db.flush()
    return hv


def _mk_vms(db, hv, n):
    from app.models.server import Server
    ids = []
    for i in range(n):
        s = Server(name=f"{hv.name}-vm{i}", hostname=f"{hv.name}-vm{i}", ip_address=f"10.9.{hv.id}.{i + 1}",
                   server_type="VM", os_type="linux", hypervisor_id=hv.id, hypervisor_vm_id=f"vm-{i}")
        db.add(s)
        db.flush()
        ids.append(s.id)
    db.commit()
    return ids


# ── Toplu sync: devre kesici + kısa işlem ────────────────────────────────────

def test_batch_breaker_skips_unreachable_hypervisor(isolated_db, monkeypatch):
    import app.background_tasks as bt
    import app.services.snapshot_service as ss

    bt._VM_SYNC_BACKOFF.clear()
    dead = _mk_hv(isolated_db, "dead", "198.18.0.1")
    live = _mk_hv(isolated_db, "live", "10.0.0.2")
    dead_ids = _mk_vms(isolated_db, dead, 6)
    live_ids = _mk_vms(isolated_db, live, 3)

    calls = []

    def fake(server, db):
        calls.append(server.id)
        if server.hypervisor_id == dead.id:
            return {"found": False, "unreachable": True, "message": "vCenter oturumu açılamadı"}
        return {"found": True, "vm_id": "x"}

    monkeypatch.setattr(ss, "search_and_sync_vm_details", fake)
    bt._run_vm_sync_batch(isolated_db)

    assert sum(1 for c in calls if c in dead_ids) == 2, "ölü hypervisor için yalnız 2 deneme (eşik)"
    assert sum(1 for c in calls if c in live_ids) == 3, "ulaşılabilir hypervisor tam işlenir"
    assert dead.id in bt._VM_SYNC_BACKOFF

    # Geri çekilme süresinde 2. tur: ölü hypervisor'a hiç dokunulmaz
    calls.clear()
    bt._run_vm_sync_batch(isolated_db)
    assert not any(c in dead_ids for c in calls)
    assert sum(1 for c in calls if c in live_ids) == 3
    bt._VM_SYNC_BACKOFF.clear()


def test_batch_closes_transaction_before_loop(isolated_db, monkeypatch):
    """Hedef listesi alındıktan sonra çağıran oturum açık işlemde KALMAZ."""
    import app.background_tasks as bt
    import app.services.snapshot_service as ss

    bt._VM_SYNC_BACKOFF.clear()
    hv = _mk_hv(isolated_db, "hv-a")
    _mk_vms(isolated_db, hv, 2)
    seen = {}

    def fake(server, db):
        seen.setdefault("caller_in_txn", isolated_db.in_transaction())
        return {"found": True, "vm_id": "x"}

    monkeypatch.setattr(ss, "search_and_sync_vm_details", fake)
    bt._run_vm_sync_batch(isolated_db)
    assert seen["caller_in_txn"] is False


def test_search_and_sync_has_no_open_transaction_during_network(isolated_db, monkeypatch):
    """Hypervisor'a ağ çağrısı yapılırken DB işlemi AÇIK OLMAMALI (kök neden)."""
    import app.services.snapshot_service as ss
    from app.models.server import Server

    hv = _mk_hv(isolated_db, "hv-net")
    sid = _mk_vms(isolated_db, hv, 1)[0]
    srv = isolated_db.get(Server, sid)
    obs = {}

    def fake_client(h):
        obs["in_txn"] = isolated_db.in_transaction()
        raise RuntimeError("vCenter oturumu açılamadı")

    monkeypatch.setattr(ss, "get_vm_client", fake_client)
    res = ss.search_and_sync_vm_details(srv, isolated_db)
    assert obs["in_txn"] is False
    assert res["found"] is False and res.get("unreachable") is True


def test_search_and_sync_success_writes_details(isolated_db, monkeypatch):
    import app.services.snapshot_service as ss
    from app.models.server import Server

    hv = _mk_hv(isolated_db, "hv-ok")
    sid = _mk_vms(isolated_db, hv, 1)[0]
    srv = isolated_db.get(Server, sid)

    class C:
        def get_vm_full_details(self, vm_id, name=""):
            return {"vm_name": "renamed", "vm_cpu_count": 4, "vm_power_state": "poweredOn"}

        def logout(self):
            pass

    monkeypatch.setattr(ss, "get_vm_client", lambda h: (C(), "vmware"))
    res = ss.search_and_sync_vm_details(srv, isolated_db)
    assert res["found"] is True
    isolated_db.expire_all()
    fresh = isolated_db.get(Server, sid)
    assert fresh.vm_cpu_count == 4 and fresh.vm_last_sync is not None


# ── DB kilit bekçisi ─────────────────────────────────────────────────────────

def _engine_for(eng, app_name):
    return create_engine(eng.url, connect_args={"application_name": app_name}, pool_size=1, max_overflow=0)


def _run_guard_scenario(_isolated_engine, blocker_app, monkeypatch):
    from app.core import db_lock_guard as g

    monkeypatch.setenv("DB_LOCK_GUARD_XACT_SEC", "0")
    monkeypatch.setenv("DB_LOCK_GUARD_WAIT_SEC", "1")
    with _isolated_engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS _guard_t (id int)"))

    blocker_eng = _engine_for(_isolated_engine, blocker_app)
    waiter_eng = _engine_for(_isolated_engine, "ainew-waiter")
    blocker = blocker_eng.connect()
    blocker.execute(text("SELECT count(*) FROM _guard_t"))  # AccessShare + açık işlem, sonra «idle in transaction»
    box = {}

    def waiter():
        try:
            with waiter_eng.begin() as w:
                w.execute(text("LOCK TABLE _guard_t IN ACCESS EXCLUSIVE MODE"))
            box["ok"] = True
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(2.5)  # bekleme >= 1 sn
    try:
        with _isolated_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            killed = g.check_once(conn)
        t.join(timeout=3)
        done_before_cleanup = dict(box)
        return killed, done_before_cleanup
    finally:
        try:
            blocker.close()
        except Exception:
            pass
        t.join(timeout=5)
        blocker_eng.dispose()
        waiter_eng.dispose()
        with _isolated_engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _guard_t"))


def test_guard_terminates_idle_blocker_of_ours(_isolated_engine, monkeypatch):
    killed, box = _run_guard_scenario(_isolated_engine, "ainew-api", monkeypatch)
    assert len(killed) == 1
    assert box.get("ok") is True, "engel kalkınca bekleyen kilit talebi tamamlanmalı"


def test_guard_never_touches_foreign_connections(_isolated_engine, monkeypatch):
    killed, box = _run_guard_scenario(_isolated_engine, "psql-or-alembic", monkeypatch)
    assert killed == []


def test_guard_sql_is_valid_when_idle(_isolated_engine):
    from app.core import db_lock_guard as g
    with _isolated_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert g.check_once(conn) == []
