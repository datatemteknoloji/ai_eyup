from app.services.capacity_overview import _pct, _physical_for


def test_pct_is_clamped_and_none_safe():
    assert _pct(50, 200) == 25.0
    assert _pct(300, 200) == 100.0
    assert _pct(None, 100) is None
    assert _pct(10, 0) is None


def test_physical_uses_mhz_when_reported():
    hosts = [
        {"cpu_cores": 16, "cpu_total_mhz": 40000, "cpu_usage_mhz": 10000, "mem_total_mb": 1024 * 100, "mem_used_mb": 1024 * 50},
        {"cpu_cores": 16, "cpu_total_mhz": 40000, "cpu_usage_mhz": 30000, "mem_total_mb": 1024 * 100, "mem_used_mb": 1024 * 50},
    ]
    row = _physical_for(1, hosts, {"total_gb": 1000.0, "used_gb": 250.0, "count": 2})
    assert row["cpu_cores"] == 32 and row["cpu_total_ghz"] == 80.0 and row["cpu_pct"] == 50.0
    assert row["mem_total_gb"] == 200.0 and row["mem_pct"] == 50.0
    assert row["storage_pct"] == 25.0 and row["datastores"] == 2


def test_physical_without_mhz_uses_core_weighted_pct_and_no_storage():
    hosts = [
        {"cpu_cores": 8, "cpu_usage_pct": 100.0, "mem_total_mb": 1024, "mem_used_mb": 512},
        {"cpu_cores": 8, "cpu_usage_pct": 0.0, "mem_total_mb": 1024, "mem_used_mb": 512},
    ]
    row = _physical_for(2, hosts, None)
    assert row["cpu_total_ghz"] is None and row["cpu_pct"] == 50.0
    assert row["storage_total_gb"] is None and row["storage_pct"] is None


def test_inventory_sources_count_online_offline_attention_per_environment(isolated_db):
    from app.models.server import Server
    from app.services.capacity_overview import inventory_by_source
    db = isolated_db
    for i, st in enumerate(["ONLINE", "ONLINE", "OFFLINE", "WARNING", "CRITICAL", "unknown"]):
        db.add(Server(name=f"vm{i}", ip_address=f"10.0.0.{i + 1}", server_type="VIRTUAL", os_type="linux",
                      hypervisor_id=None, status=st, cpu_cores=2, memory_gb=4))
    db.add(Server(name="w1", ip_address="10.0.1.1", server_type="PHYSICAL", os_type="Windows Server", status="ONLINE",
                  cpu_cores=4, memory_gb=8))
    db.commit()
    inv = inventory_by_source(db, {})
    by = {s["key"]: s for s in inv["sources"]}
    lin, win = by["free:linux"], by["free:windows"]
    assert (lin["servers"], lin["online"], lin["offline"], lin["attention"]) == (6, 2, 1, 2)   # 'unknown' hiçbirine girmez
    assert (win["servers"], win["online"], win["offline"], win["attention"]) == (1, 1, 0, 0)
    assert (inv["total"]["online"], inv["total"]["offline"], inv["total"]["attention"]) == (3, 1, 2)
