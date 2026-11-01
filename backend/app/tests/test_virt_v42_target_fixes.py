"""Hedef ortam analizinden çıkan düzeltmeler (v42):
IP çakışmasıyla VM kaybı, datastore kural önemi, uplink kuralı, kapasite önbelleği, baseline kaldırma.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services import inventory_sync_service as iss
from app.services.findings.registry import RESULT_FAIL, RESULT_PASS
from app.services.virt_health_checks import _datastore_accessible, _vmware


# ── 1) IP çakışması: eşleştirilebilir IP + başka VM'e ait kayıt ─────────────────

def test_is_matchable_ip_rejects_link_local_loopback_and_empty():
    for bad in (None, "", "  ", "169.254.10.5", "127.0.0.1", "0.0.0.0", "fe80::1", "224.0.0.1"):
        assert iss.is_matchable_ip(bad) is False, bad
    for good in ("10.1.2.3", "192.168.0.10", "2001:db8::1"):
        assert iss.is_matchable_ip(good) is True, good
    assert iss.is_matchable_ip("not-an-ip") is True   # çözümlenemeyen metin: eski davranış (eşleştir)


def test_belongs_to_other_vm():
    assert iss._belongs_to_other_vm(SimpleNamespace(hypervisor_vm_id="vm-1"), "vm-2") is True
    assert iss._belongs_to_other_vm(SimpleNamespace(hypervisor_vm_id="vm-2"), "vm-2") is False
    assert iss._belongs_to_other_vm(SimpleNamespace(hypervisor_vm_id=None), "vm-2") is False
    assert iss._belongs_to_other_vm(SimpleNamespace(hypervisor_vm_id=""), "vm-2") is False


class _SeqDB:
    """query().filter().first() → vm_id araması; .all() çağrıları sırayla IP, ad sonuçlarını döner."""

    def __init__(self, by_vm_id=None, by_ip=(), by_name=()):
        self._first = by_vm_id
        self._all = [list(by_ip), list(by_name)]

    def query(self, *_):
        return self

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all.pop(0) if self._all else []


def _srv(vm_id, hv=1):
    return SimpleNamespace(hypervisor_id=hv, hypervisor_vm_id=vm_id)


def test_find_existing_server_does_not_steal_other_vm_by_shared_ip():
    """Aynı IP'yi paylaşan iki VM: ikinci VM, birincinin kaydını (farklı hypervisor_vm_id) devralmamalı."""
    other = _srv("vm-1")
    vm = {"name": "b", "vm_id": "vm-2", "ip_address": "10.0.0.5"}
    assert iss._find_existing_server(_SeqDB(by_ip=[other], by_name=[other]), 1, vm) is None


def test_find_existing_server_adopts_same_name_and_ip_when_vm_id_format_changed():
    """KubeVirt UID → namespace/ad: aynı hypervisor + aynı ad + aynı IP = aynı VM."""
    old = SimpleNamespace(hypervisor_id=1, hypervisor_vm_id="uid-123", name="a", ip_address="10.0.0.5")
    vm = {"name": "a", "vm_id": "ns/a", "ip_address": "10.0.0.5"}
    assert iss._find_existing_server(_SeqDB(by_ip=[old]), 1, vm) is old
    other_name = SimpleNamespace(hypervisor_id=1, hypervisor_vm_id="uid-9", name="zzz", ip_address="10.0.0.5")
    assert iss._find_existing_server(_SeqDB(by_ip=[other_name], by_name=[]), 1, vm) is None


def test_find_existing_server_still_adopts_unbound_record_by_ip_then_name():
    free = _srv(None)
    vm = {"name": "a", "vm_id": "vm-2", "ip_address": "10.0.0.5"}
    assert iss._find_existing_server(_SeqDB(by_ip=[free]), 1, vm) is free
    assert iss._find_existing_server(_SeqDB(by_name=[free]), 1, vm) is free


def test_find_existing_server_ignores_link_local_ip_but_prefers_vm_id():
    free = _srv(None)
    vm = {"name": "a", "vm_id": "vm-2", "ip_address": "169.254.1.1"}
    db = _SeqDB(by_ip=[], by_name=[])
    assert iss._find_existing_server(db, 1, vm) is None
    assert len(db._all) == 1          # yalnız bir all() sorgusu (ad); IP sorgusu yapılmadı
    exact = _srv("vm-2")
    assert iss._find_existing_server(_SeqDB(by_vm_id=exact), 1, vm) is exact


# ── 2) datastore kuralı ────────────────────────────────────────────────────────

def _ds(accessible, mounted, ds_type="VMFS", inacc=(), cap=1000.0, free=1000.0):
    return {"ref": "ds-1", "name": "ds1",
            "config": {"type": ds_type, "mounted_hosts": list(mounted)},
            "state": {"accessible": accessible, "capacity_gb": cap, "free_gb": free,
                      "inaccessible_mounts": list(inacc)}}


def test_datastore_accessible_pass():
    d = _datastore_accessible(_ds(True, ["h1"]), "datastore:ds-1", {})
    assert d.result == RESULT_PASS


def test_datastore_unmounted_is_low_and_flags_empty():
    d = _datastore_accessible(_ds(False, [], free=999.0), "datastore:ds-1", {})
    assert d.result == RESULT_FAIL and d.severity == "low"
    assert d.evidence["scenario"] == "unmounted"
    assert "boş görünüyor" in d.detail


def test_datastore_nfs_all_mounts_down_is_medium():
    d = _datastore_accessible(_ds(False, ["h1", "h2"], "NFS", inacc=["h1", "h2"]), "datastore:ds-1",
                              {"h1": "esx1", "h2": "esx2"})
    assert d.severity == "medium" and d.evidence["scenario"] == "nfs_unreachable"
    assert d.evidence["inaccessible_mounts"] == ["esx1", "esx2"]


def test_datastore_san_partial_stays_default_critical():
    d = _datastore_accessible(_ds(False, ["h1", "h2"], "VMFS", inacc=["h1"]), "datastore:ds-1", {"h1": "esx1"})
    assert d.severity is None            # katalog varsayılanı (critical) devreye girer
    assert d.evidence["scenario"] == "inaccessible"
    assert d.detail == "1/2 host'ta erişilemiyor"


# ── 3) uplink kuralı ──────────────────────────────────────────────────────────

def _host(vswitches):
    return {"ref": "h1", "name": "esx1", "cluster": "c1",
            "state": {"connection": "connected", "maintenance": False},
            "config": {"vswitches": vswitches, "ntp_servers": ["x"]}}


def _uplink(vsw):
    out = _vmware({"hosts": [_host(vsw)], "clusters": [], "datastores": []}, {}, {})
    return next(d for d in out if d.check_id == "vmw.host.uplink_redundancy")


def test_uplink_isolated_standard_switch_is_not_a_failure():
    d = _uplink([{"name": "vSwitch0", "kind": "standard", "uplinks": [], "portgroups": 2}])
    assert d.result == RESULT_PASS
    assert d.evidence["isolated_switches"][0]["switch"] == "vSwitch0"


def test_uplink_single_uplink_fails_with_readable_detail():
    d = _uplink([{"name": "vSwitch1", "kind": "standard", "uplinks": ["vmnic0"], "portgroups": 1}])
    assert d.result == RESULT_FAIL and d.detail == "vSwitch1 (1 uplink)"


def test_uplink_distributed_without_uplink_fails_and_empty_switch_ignored():
    d = _uplink([{"name": "dvs", "kind": "distributed", "uplinks": [], "portgroups": None},
                 {"name": "vSwitchEmpty", "kind": "standard", "uplinks": ["a"], "portgroups": 0}])
    assert d.result == RESULT_FAIL and [s["switch"] for s in d.evidence["switches"]] == ["dvs"]


# ── 4) kapasite önbelleği ─────────────────────────────────────────────────────

def test_capacity_cache_hit_invalidate_and_not_ok_not_cached(monkeypatch):
    from app.services import virt_capacity_cache as vcc
    monkeypatch.setattr(vcc, "_redis", lambda: None, raising=False)
    vcc.invalidate()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"ok": True, "v": calls["n"]}

    a = vcc.get_or_compute("capacity", "k1", compute)
    b = vcc.get_or_compute("capacity", "k1", compute)
    assert a == b and calls["n"] == 1
    vcc.invalidate()
    c = vcc.get_or_compute("capacity", "k1", compute)
    assert c["v"] == 2

    bad = {"n": 0}

    def compute_bad():
        bad["n"] += 1
        return {"ok": False}

    vcc.get_or_compute("capacity", "k2", compute_bad)
    vcc.get_or_compute("capacity", "k2", compute_bad)
    assert bad["n"] == 2


# ── 5) baseline kaldırma ──────────────────────────────────────────────────────

def test_clear_baseline_only_touches_baseline_rows():
    from app.services import virt_config_drift as d

    seen = {}

    class _Q:
        def filter(self, *a, **k):
            seen["filters"] = seen.get("filters", 0) + 1
            return self

        def update(self, values, synchronize_session=None):
            seen["values"] = values
            return 3

    class _DB:
        def query(self, *_):
            return _Q()

        def flush(self):
            seen["flushed"] = True

    n = d.clear_baseline(_DB(), platform="vmware", source_id=1, entity_kind="host", entity_ref="host:h1")
    assert n == 3 and seen["flushed"]
    vals = {getattr(k, "key", k): v for k, v in seen["values"].items()}
    assert vals == {"is_baseline": False, "baseline_by": None, "baseline_at": None}
    assert seen["filters"] >= 4   # is_baseline + platform + source + kind + ref


# ── 6) anomali taraması: tz-aware zaman damgası ───────────────────────────────

def test_detect_all_anomalies_handles_timezone_aware_metric_timestamps(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock
    from app.services import anomaly_detector as ad

    srv = SimpleNamespace(id=1, name="s1", cpu_cores=2)
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = [
        [srv],                                                               # sunucular
        [(1, next(iter(ad.ANOMALY_CONFIG)), datetime.now(timezone.utc) - timedelta(minutes=5), 1.0),
         (1, next(iter(ad.ANOMALY_CONFIG)), datetime.now(timezone.utc) - timedelta(hours=5), 2.0)],
    ]
    seen = {}

    def fake_detect(_db, server, **kw):
        seen["pre"] = kw["_preloaded"]
        return []

    monkeypatch.setattr(ad, "detect_anomalies_for_server", fake_detect)
    assert ad.detect_all_anomalies(db) == []          # eskiden TypeError (naive/aware)
    bucket = next(iter(seen["pre"].values()))
    assert len(bucket["recent"]) == 1 and len(bucket["history"]) == 1


# ── 7) kapasite: with_reclaim ─────────────────────────────────────────────────

def test_build_capacity_skips_reclaim_rollup_when_disabled(monkeypatch):
    from unittest.mock import MagicMock
    from app.services import virt_capacity_planner as vcp

    calls = {"n": 0}
    monkeypatch.setattr(vcp, "_reclaim_by_cluster", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})
    monkeypatch.setattr(vcp.capacity_policy, "activate", lambda *a, **k: None)
    for fn in ("virt_hypervisors", "latest_hosts", "vm_allocations", "host_p95"):
        monkeypatch.setattr(vcp.vd, fn, lambda *a, **k: [])
    monkeypatch.setattr(vcp.vd, "virt_cluster_rows", lambda *a, **k: {})
    monkeypatch.setattr(vcp, "_datastores", lambda *a, **k: [])
    db = MagicMock()
    vcp.build_capacity(db, with_forecast=False)
    assert calls["n"] == 1
    vcp.build_capacity(db, with_forecast=False, with_reclaim=False)
    assert calls["n"] == 1                              # ikinci çağrıda hesaplanmadı


def test_scenario_callers_do_not_request_reclaim():
    import inspect
    from app.services import virt_bulk_placement, virt_capacity_planner as vcp, virt_reclaim_sim
    from app.services.capacity import nested
    for fn in (vcp.simulate, vcp._hf_context, vcp.move_scenario, virt_bulk_placement.bulk_place,
               virt_reclaim_sim.reclaim_sim, nested):
        assert "with_reclaim=False" in inspect.getsource(fn)


# ── 8) learned_facts toplu upsert + commit kontrolü ───────────────────────────

def _fact_server():
    return SimpleNamespace(id=5, name="vm", hypervisor_id=1, server_type="VIRTUAL", hypervisor=SimpleNamespace(name="vc"),
                           os_type="rhel", vm_power_state="poweredOn", vm_tools_status=None, vm_datastore="ds",
                           vm_cluster="c", vm_guest_hostname=None, vm_guest_ip=None, vm_hardware_version=None,
                           cpu_cores=2, memory_gb=4, vm_disk_gb=None, ip_address="10.0.0.1", hostname="vm")


def test_virt_facts_use_single_select_and_respect_commit_flag():
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from app.services.fact_learning import extract_and_store_virt_facts

    same = SimpleNamespace(category="virt_os", key="virt.os_type", value="rhel", times_confirmed=3,
                           last_confirmed_at=None, first_learned_at=None, source="x")
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [same]
    n = extract_and_store_virt_facts(db, _fact_server(), commit=False)
    assert db.query.call_count == 1                     # eskiden fact başına bir SELECT (~14)
    assert n == 9 and same.times_confirmed == 4 and same.source == "virt_sync"
    db.commit.assert_not_called()
    db.begin_nested.assert_called_once()
    assert db.add.call_count == n - 1                   # biri mevcut (güncellendi), kalanı yeni

    db2 = MagicMock()
    db2.query.return_value.filter.return_value.all.return_value = []
    extract_and_store_virt_facts(db2, _fact_server())
    db2.commit.assert_called_once()                     # varsayılan davranış korunur


def test_virt_facts_failure_with_commit_false_does_not_roll_back_callers_work():
    from unittest.mock import MagicMock
    from app.services.fact_learning import extract_and_store_virt_facts
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = RuntimeError("boom")
    assert extract_and_store_virt_facts(db, _fact_server(), commit=False) == 0
    db.rollback.assert_not_called()


# ── 9) upsert: bulunan kayıt yeniden sorgulanmaz ──────────────────────────────

def test_upsert_uses_passed_existing_without_lookup(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(iss, "_find_existing_server",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("tekrar sorgulandı")))
    db = MagicMock()
    created = []
    db.add.side_effect = lambda o: created.append(o) or setattr(o, "id", 9)
    vm = {"name": "n", "hostname": "n", "vm_id": "vm-9", "ip_address": "10.1.1.1", "os_type": "rhel",
          "cpu_cores": 1, "memory_gb": 1, "power_state": "poweredOn"}
    assert iss._upsert_vm_record(db, SimpleNamespace(id=1), vm, None, client=None, existing=None) is True
    assert created and created[0].hypervisor_vm_id == "vm-9"


# ── 10) paralel hypervisor sync ───────────────────────────────────────────────

def test_sync_all_hypervisors_runs_in_parallel_and_survives_one_failure(monkeypatch):
    import threading, time
    from unittest.mock import MagicMock

    hvs = [SimpleNamespace(id=i, name=f"hv{i}") for i in (1, 2, 3)]
    db = MagicMock()
    db.query.return_value.all.return_value = hvs

    class _S:
        def get(self, _m, hid):
            return next(h for h in hvs if h.id == hid)
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    import app.core.database as dbm
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _S())
    threads = set()

    def fake_sync(session, hv, **k):
        threads.add(threading.current_thread().name)
        time.sleep(0.3)
        if hv.id == 2:
            raise RuntimeError("bağlantı yok")
        return {"synced_count": 1, "total_vms": 5, "enriched_count": 0, "errors": []}

    monkeypatch.setattr(iss, "sync_hypervisor_vms", fake_sync)
    t0 = time.time()
    res = iss.sync_all_hypervisors(db)
    assert time.time() - t0 < 0.8                       # sıralı olsaydı ≥ 0.9 sn
    assert [r["name"] for r in res["hypervisors"]] == ["hv1", "hv2", "hv3"]   # sıra korunur
    assert res["total_synced"] == 2 and res["success"] is False
    assert res["hypervisors"][1]["errors"] == ["bağlantı yok"]
    assert len(threads) >= 2


# ── 11) fact onayı sıklık sınırı ──────────────────────────────────────────────

def _fact(value="rhel", ago_min=None, source="virt_sync", times=3):
    from datetime import datetime, timedelta, timezone
    last = None if ago_min is None else datetime.now(timezone.utc) - timedelta(minutes=ago_min)
    return SimpleNamespace(value=value, last_confirmed_at=last, first_learned_at=last, times_confirmed=times, source=source)


def test_confirm_fact_is_throttled_but_value_change_and_source_change_write_immediately():
    from datetime import datetime, timezone
    from app.services.fact_learning import _confirm_or_update_fact as f
    now = datetime.now(timezone.utc)
    fresh = _fact(ago_min=5)
    assert f(fresh, "rhel", now, "virt_sync") is False and fresh.times_confirmed == 3   # 5 dk önce onaylandı: yazma yok
    old = _fact(ago_min=90)
    assert f(old, "rhel", now, "virt_sync") is True and old.times_confirmed == 4
    never = _fact(ago_min=None)
    assert f(never, "rhel", now, "virt_sync") is True
    changed = _fact(value="windows", ago_min=1)
    assert f(changed, "rhel", now, "virt_sync") is True and changed.value == "rhel" and changed.times_confirmed == 1
    other_src = _fact(ago_min=1, source="chat_tool")
    assert f(other_src, "rhel", now, "virt_sync") is True and other_src.source == "virt_sync"
    naive = _fact(ago_min=None)
    from datetime import timedelta
    naive.last_confirmed_at = (now - timedelta(minutes=5)).replace(tzinfo=None)
    assert f(naive, "rhel", now, "virt_sync") is False        # tz'siz damga UTC sayılır, hata vermez


def test_virt_facts_steady_state_writes_nothing_and_does_not_commit():
    from unittest.mock import MagicMock
    from app.services.fact_learning import extract_and_store_virt_facts, VIRT_STABLE_SERVER_FIELDS
    srv = _fact_server()
    rows = []
    for attr, cat in VIRT_STABLE_SERVER_FIELDS.items():
        v = getattr(srv, attr, None)
        if v not in (None, ""):
            rows.append(SimpleNamespace(category=cat, key=f"virt.{attr}", value=str(v), last_confirmed_at=None,
                                        first_learned_at=None, times_confirmed=1, source="virt_sync"))
    from datetime import datetime, timedelta, timezone
    recent = datetime.now(timezone.utc) - timedelta(minutes=3)
    for r in rows:
        r.last_confirmed_at = recent
    rows.append(SimpleNamespace(category="virt_cluster", key="virt.hypervisor_name", value="vc",
                                last_confirmed_at=recent, first_learned_at=recent, times_confirmed=1, source="virt_sync"))
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    assert extract_and_store_virt_facts(db, srv) == 0
    db.commit.assert_not_called()
    db.add.assert_not_called()


# ── 12) datastore fact'leri toplu ─────────────────────────────────────────────

def test_store_live_datastore_facts_uses_batched_selects():
    from unittest.mock import MagicMock
    from app.services.fact_learning import store_live_datastore_facts

    servers = [SimpleNamespace(id=i, vm_datastore="DS1") for i in range(1, 6)] + [SimpleNamespace(id=99, vm_datastore="OTHER")]
    db = MagicMock()
    db.query.return_value.filter.return_value.all.side_effect = [servers, []]     # sunucular, mevcut fact yok
    ds = [{"name": "DS1", "usage_pct": 40.0, "free_gb": 10.0, "capacity_gb": 20.0, "accessible": True}]
    n = store_live_datastore_facts(db, ds)
    assert n == 25 and db.add.call_count == 25                 # 5 sunucu × 5 fact
    assert db.query.call_count == 2                            # eskiden 1 + 25 SELECT
    db.commit.assert_called_once()


# ── 13) kapasite önbelleği: anahtar + ön ısıtma ───────────────────────────────

def test_capacity_key_matches_api_and_prewarm_populates_cache(monkeypatch):
    from app.services import virt_capacity_cache as vcc
    from app.services import virt_capacity_planner as vcp
    import app.core.database as dbm
    import inspect
    from app.api import virt_insights as api

    assert vcc.capacity_key() == "None||" and vcc.capacity_key(3, "c", "vmware") == "3|c|vmware"
    assert "capacity_key(hypervisor_id, cluster, platform)" in inspect.getsource(api.capacity)

    monkeypatch.setattr(vcc, "_redis", lambda: None)
    closed = {"n": 0}
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: SimpleNamespace(close=lambda: closed.__setitem__("n", 1)))
    calls = {"n": 0}
    monkeypatch.setattr(vcp, "build_capacity", lambda db, **k: calls.__setitem__("n", calls["n"] + 1) or {"ok": True, "v": 1})
    vcc.invalidate_and_prewarm()
    assert calls["n"] == 1 and closed["n"] == 1
    out = vcc.get_or_compute("capacity", vcc.capacity_key(), lambda: (_ for _ in ()).throw(AssertionError("soğuk")))
    assert out == {"ok": True, "v": 1}                         # ilk kullanıcı isteği önbellekten


def test_prewarm_failure_is_silent(monkeypatch):
    from app.services import virt_capacity_cache as vcc
    import app.core.database as dbm
    monkeypatch.setattr(vcc, "_redis", lambda: None)
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("db yok")))
    vcc.invalidate_and_prewarm()                               # fırlatmaz


def test_jobs_prewarm_after_metric_inventory_and_insights_rounds():
    import inspect
    from app.services import fleet_jobs
    for fn in (fleet_jobs.run_esx_metric_sync, fleet_jobs.run_inventory_sync, fleet_jobs.run_virt_insights):
        assert "invalidate_and_prewarm()" in inspect.getsource(fn)
