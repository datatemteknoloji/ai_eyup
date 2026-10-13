"""Toplu yerleşim: çoklu profil, anti-affinity, HA/CPU kontrolü, cluster bağımsızlığı."""
from __future__ import annotations

import pytest

from app.services import capacity_policy
from app.services import virt_bulk_placement as vbp
from app.tests.test_capacity_v2 import _seed


@pytest.fixture(autouse=True)
def _thr():
    capacity_policy.activate(values={})
    yield
    capacity_policy.activate(values={})


def P(name, vcpu=2, mem=16, disk=0, count=1, group=None):
    return {"name": name, "vcpu": vcpu, "memory_gb": mem, "disk_gb": disk, "count": count, "group": group}


def _hosts(*free):
    return [{"name": f"h{i + 1}", "ref": f"r{i + 1}", "cores": 32.0, "free_gb": float(f)} for i, f in enumerate(free)]


def test_normalize_validates():
    with pytest.raises(ValueError):
        vbp.normalize_profiles([])
    with pytest.raises(ValueError):
        vbp.normalize_profiles([P("a"), P("a")])
    with pytest.raises(ValueError):
        vbp.normalize_profiles([P("")])
    with pytest.raises(ValueError):
        vbp.normalize_profiles([P("a", vcpu=0)])
    assert vbp.normalize_profiles([P("a", group="  ")])[0]["group"] is None


def test_expand_names_and_multi_profile_placement():
    vms = vbp.expand(vbp.normalize_profiles([P("web", mem=16, count=3), P("db", mem=64)]))
    assert [v["vm"] for v in vms] == ["web-1", "web-2", "web-3", "db"]
    r = vbp.place_bulk(_hosts(100, 100), vms, None, 15)
    assert not r["unplaced"] and len(r["plan"]) == 4
    assert next(p for p in r["plan"] if p["vm"] == "db")["host"] == "h1"          # en büyük VM ilk, en boş host (ada göre)


def test_anti_affinity_spreads_group_across_hosts():
    vms = vbp.expand(vbp.normalize_profiles([P("db", mem=8, count=3, group="g1")]))
    r = vbp.place_bulk(_hosts(500, 10, 10), vms, None, 15)
    assert sorted(p["host"] for p in r["plan"]) == ["h1", "h2", "h3"]               # h1 çok boş olsa da tek host'a yığılmaz


def test_anti_affinity_insufficient_hosts_is_reported():
    vms = vbp.expand(vbp.normalize_profiles([P("db", mem=8, count=3, group="g1")]))
    r = vbp.place_bulk(_hosts(500, 500), vms, None, 15)
    assert len(r["plan"]) == 2 and [u["reason"] for u in r["unplaced"]] == ["anti_affinity"]


def test_group_spans_profiles_and_ungrouped_may_share_hosts():
    vms = vbp.expand(vbp.normalize_profiles([P("a", mem=8, group="g"), P("b", mem=8, group="g"), P("c", mem=8, count=2)]))
    r = vbp.place_bulk(_hosts(500, 500), vms, None, 15)
    h = {p["vm"]: p["host"] for p in r["plan"]}
    assert h["a"] != h["b"] and not r["unplaced"]


def test_reasons_memory_fragmentation_datastore():
    vms = vbp.expand(vbp.normalize_profiles([P("big", mem=60)]))
    assert vbp.place_bulk(_hosts(40, 40), vms, None, 15)["unplaced"][0]["reason"] == "fragmentation"
    assert vbp.place_bulk(_hosts(10, 10), vms, None, 15)["unplaced"][0]["reason"] == "memory"
    assert vbp.place_bulk([], vms, None, 15)["unplaced"][0]["reason"] == "no_host"
    d = vbp.expand(vbp.normalize_profiles([P("x", mem=1, disk=100)]))
    ds = [{"name": "DS", "free_gb": 500, "capacity_gb": 1000, "accessible": True, "host_refs": {"r2"}}]
    r = vbp.place_bulk(_hosts(500, 5), d, ds, 15)
    assert r["plan"][0]["host"] == "h2" and r["plan"][0]["datastore"] == "DS"        # yalnız h2 DS'e erişir (h2 boş: 5 GB ≥ 1)
    ds2 = [{**ds[0], "free_gb": 50}]
    assert vbp.place_bulk(_hosts(500, 5), d, ds2, 15)["unplaced"][0]["reason"] == "datastore"


def test_bulk_place_end_to_end_per_cluster_and_cpu(isolated_db):
    db = isolated_db
    _seed(db, "vc01", [("e1", "host-1", 256, 20, "A"), ("e2", "host-2", 256, 20, "A"), ("e3", "host-3", 256, 20, "A")])
    _seed(db, "vc02", [("f1", "host-1", 256, 20, "B")])
    res = vbp.bulk_place(db, profiles=[P("web", vcpu=4, mem=16, count=4), P("db", vcpu=8, mem=64, count=3, group="dbs")])
    by = {r["cluster"]: r for r in res["results"]}
    assert by["A"]["fits"] and by["A"]["placed"] == 7 and by["A"]["status"] in ("ok", "warn")
    assert sorted(p["host"] for p in by["A"]["plan"] if p["profile"] == "db") == ["e1", "e2", "e3"]
    assert sum(h["vms"] for h in by["A"]["by_host"]) == 7 and by["A"]["plan"][0]["path"]
    assert by["B"]["fits"] is False and "anti_affinity" in by["B"]["limiting"]       # tek host: grup yayılamaz
    assert by["B"]["placed"] + by["B"]["unplaced_count"] == 7
    assert res["results"][0]["cluster"] == "A"                                        # sığanlar önce
    assert by["A"]["cpu"]["p95_demand_cores"] is not None


def test_cpu_fail_makes_cluster_not_fit(isolated_db):
    db = isolated_db
    _seed(db, "vc01", [("e1", "host-1", 1024, 20, "A"), ("e2", "host-2", 1024, 20, "A")])
    # Memory bol; ama 200 vCPU × %50 varsayım = 100 çekirdek talebi > etkin çekirdek (32)
    res = vbp.bulk_place(db, profiles=[P("cpu", vcpu=100, mem=1, count=2)], cpu_util_assumption=0.5)
    r = res["results"][0]
    assert r["cpu"]["verdict"] == "fail" and r["fits"] is False and "cpu" in r["limiting"]
