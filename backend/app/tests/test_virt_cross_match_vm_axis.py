"""cross_match_virt_db — VM ekseni (join_on="vm").

Neden gerekli: host ekseni VM'leri yalnız ad listesi (`vms`) olarak veriyordu,
bu yüzden "CPU'su yüksek VM'ler hangi hostta ve host'un RAM'i ne durumda"
sorusu iki ayrı tool çağrısı + modelin elle eşleştirmesi demekti. VM ekseninde
VM'in kendi yükü ile host'unun yükü aynı satırda döner.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_datastore import VirtDatastore
from app.services import virt_db_query
from app.services.virt_db_query import cross_match_virt_db


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Hypervisor.__table__.create(engine)
    Server.__table__.create(engine)
    VirtDatastore.__table__.create(engine)
    HypervisorHostMetric.__table__.create(engine)
    HypervisorHostInventory.__table__.create(engine)
    SystemEvent.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded(db_session):
    hv = Hypervisor(
        name="Office", hypervisor_type=HypervisorType.VMWARE,
        hostname="vcenter.example", ip_address="10.0.0.1", connection_config={},
    )
    db_session.add(hv)
    db_session.commit()
    db_session.refresh(hv)

    db_session.add_all([
        HypervisorHostMetric(
            hypervisor_id=hv.id, host_name="esx01",
            cpu_usage_pct=35.0, mem_usage_pct=91.0, connection_state="connected",
            vms_total=12,
        ),
        HypervisorHostMetric(
            hypervisor_id=hv.id, host_name="esx02",
            cpu_usage_pct=10.0, mem_usage_pct=22.0, connection_state="connected",
        ),
        VirtDatastore(
            hypervisor_id=hv.id, name="NVME_DS", usage_pct=87.0, free_gb=120.0,
            as_of=datetime.now(timezone.utc),
        ),
        Server(
            name="web01", vm_name="web01", server_type="VIRTUAL",
            hypervisor_id=hv.id, vm_host_name="esx01", vm_datastore="NVME_DS",
            vm_cpu_count=4, vm_memory_mb=8192, vm_power_state="POWERED_ON",
        ),
        Server(
            name="idle01", vm_name="idle01", server_type="VIRTUAL",
            hypervisor_id=hv.id, vm_host_name="esx02", vm_datastore="NVME_DS",
            vm_cpu_count=2, vm_memory_mb=4096, vm_power_state="POWERED_ON",
        ),
    ])
    db_session.commit()
    return db_session


@pytest.fixture()
def with_vm_metrics(monkeypatch):
    """virt_vm_metrics Postgres hypertable'ı — SQLite'ta yok, sonucu taklit et."""
    monkeypatch.setattr(
        virt_db_query, "_latest_vm_utilization",
        lambda db, **kw: {
            "web01": {
                "vm_name": "web01", "cpu_usage_pct": 88.0, "mem_usage_pct": 61.0,
                "cpu_ready_pct": 4.2, "timestamp": datetime(2026, 9, 9, tzinfo=timezone.utc),
            },
            "idle01": {
                "vm_name": "idle01", "cpu_usage_pct": 3.0, "mem_usage_pct": 12.0,
                "cpu_ready_pct": 0.1, "timestamp": datetime(2026, 9, 9, tzinfo=timezone.utc),
            },
        },
    )


def test_vm_axis_emits_one_row_per_vm(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="vm")
    assert res["ok"] is True
    assert res["join_on"] == "vm"
    assert {r["vm"] for r in res["rows"]} == {"web01", "idle01"}
    assert all(r["match_axis"] == "vm" for r in res["rows"] if "match_axis" in r)


def test_vm_axis_carries_both_layers(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="vm", vm_name="web01")
    assert res["count"] == 1
    row = res["rows"][0]
    # VM'in kendi yükü ile host'un yükü ayrı alanlarda — karışmamalı
    assert row["vm_cpu_pct"] == 88.0
    assert row["vm_mem_pct"] == 61.0
    assert row["host"] == "esx01"
    assert row["host_mem_pct"] == 91.0
    assert row["host_cpu_pct"] == 35.0
    # host'un kaç VM barındırdığı — "CPU Ready yüksek VM'lerin host'unda kaç
    # VM var" gibi sorular için (contention şüphesi).
    assert row["host_vm_count"] == 12
    # bağlı depolama da aynı satırda
    assert row["datastore"] == "NVME_DS"
    assert row["ds_usage_pct"] == 87.0


def test_min_cpu_filters_on_vm_not_host(seeded, with_vm_metrics):
    """idle01 %90 RAM'li bir hostta değil ama kendi CPU'su düşük → elenmeli."""
    res = cross_match_virt_db(seeded, join_on="vm", min_cpu_pct=80)
    assert [r["vm"] for r in res["rows"]] == ["web01"]
    assert res["matched"] == 1
    assert res["scanned"] == 2
    assert res["filters"] == {"vm_cpu_pct": 80.0}


def test_min_mem_filter_can_return_empty_without_error(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="vm", min_mem_pct=99)
    assert res["ok"] is True
    assert res["rows"] == []
    assert res["scanned"] == 2


def test_vm_axis_default_fields_are_vm_centric(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="vm")
    for expected in ("vm", "vm_cpu_pct", "host", "host_mem_pct", "datastore"):
        assert expected in res["fields"]


def test_vm_axis_explicit_fields_projection(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="vm", fields=["vm", "host", "vm_ready_pct"])
    assert res["fields"] == ["vm", "host", "vm_ready_pct"]
    assert res["rows"][0].keys() <= {"vm", "host", "vm_ready_pct"}


def test_vm_axis_survives_missing_metric_table(seeded):
    """Hypertable yoksa (SQLite / yeni kurulum) envanter tarafı yine dönmeli."""
    res = cross_match_virt_db(seeded, join_on="vm")
    assert res["ok"] is True
    assert {r["vm"] for r in res["rows"]} == {"web01", "idle01"}
    assert all(r["vm_cpu_pct"] is None for r in res["rows"])


def test_host_axis_unchanged(seeded, with_vm_metrics):
    res = cross_match_virt_db(seeded, join_on="host")
    assert res["join_on"] == "host"
    assert {r["host"] for r in res["rows"]} == {"esx01", "esx02"}
    assert "match_key" in res["fields"]


def test_unknown_axis_falls_back_to_host(seeded, with_vm_metrics):
    assert cross_match_virt_db(seeded, join_on="uydurma")["join_on"] == "host"
    assert cross_match_virt_db(seeded, join_on="VMs")["join_on"] == "vm"
