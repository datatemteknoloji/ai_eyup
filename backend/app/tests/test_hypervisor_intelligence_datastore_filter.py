"""hypervisor_intelligence.py — QA_RULES datastore handler'larının isim
filtresi testleri.

Regresyon konusu: "NVME_DS datastorede hangi vmlere ait diskler var?" sorusu
QA_RULES'daki `datastore.*hangi\\s*vm` kalıbıyla eşleşip h_datastore_vm_map'e
düşüyordu; bu handler `question` parametresini kullanmadığı için TÜM
datastore'ları (bilgi kirliliği) döndürüyordu. Bu dosya hem düşük seviye
`_datastore_vm_disk_summary` (saf fonksiyon) hem de gerçek DB üzerinden
`_extract_datastore_filter` + üç ana handler'ın (`h_datastore_vm_map`,
`h_datastore_by_disk`, `h_datastore_status`) artık isim varsa kapsamı
daralttığını doğrular.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.models.virt_datastore import VirtDatastore
from app.services import hypervisor_intelligence as hvi
from app.services import virt_entity_resolver


def _vm(name, datastore, disk_gb=10, power="POWERED_ON"):
    return {
        "name": name, "datastore": datastore, "disk_gb": disk_gb,
        "power_state": power, "cpu_count": 2, "memory_gb": 4.0,
        "hypervisor": "Office",
    }


# ── _datastore_vm_disk_summary (saf fonksiyon — DB gerekmiyor) ──────────────

def test_summary_no_filter_returns_all_datastores():
    vms = [_vm("web01", "NVME_DS"), _vm("db02", "datastore2")]
    out = hvi._datastore_vm_disk_summary(vms, [], live_datastores=[])
    assert "NVME_DS" in out
    assert "datastore2" in out


def test_summary_with_filter_scopes_to_single_datastore():
    vms = [_vm("web01", "NVME_DS"), _vm("db02", "datastore2"), _vm("db03", "datastore2")]
    out = hvi._datastore_vm_disk_summary(vms, [], live_datastores=[], datastore_filter="NVME_DS")
    assert "NVME_DS" in out
    assert "web01" in out
    # Filtre uygulanan datastore DIŞINDAKİLER hiç görünmemeli — regresyonun ta kendisi.
    assert "datastore2" not in out
    assert "db02" not in out
    assert "db03" not in out


def test_summary_filter_is_case_insensitive_substring():
    vms = [_vm("web01", "NVME_DS")]
    out = hvi._datastore_vm_disk_summary(vms, [], live_datastores=[], datastore_filter="nvme_ds")
    assert "web01" in out


def test_summary_filter_also_scopes_live_datastore_capacity():
    vms = [_vm("web01", "NVME_DS"), _vm("db02", "datastore2")]
    live = [
        {"name": "NVME_DS", "capacity_gb": 2980, "used_gb": 958, "free_gb": 2022, "usage_pct": 32.1},
        {"name": "datastore2", "capacity_gb": 2794, "used_gb": 2454, "free_gb": 340, "usage_pct": 87.8},
    ]
    out = hvi._datastore_vm_disk_summary(vms, [], live_datastores=live, datastore_filter="NVME_DS")
    assert "2980" in out
    assert "2794" not in out


def test_summary_filter_no_match_returns_empty():
    vms = [_vm("web01", "NVME_DS")]
    out = hvi._datastore_vm_disk_summary(vms, [], live_datastores=[], datastore_filter="does-not-exist")
    assert out == ""


# ── _extract_datastore_filter + üst düzey handler'lar (gerçek DB, sqlite) ───

@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Hypervisor.__table__.create(engine)
    Server.__table__.create(engine)
    VirtDatastore.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    virt_entity_resolver._cache.clear()
    try:
        yield session
    finally:
        session.close()


def _make_hv(db, name="Office"):
    hv = Hypervisor(
        name=name, hypervisor_type=HypervisorType.VMWARE,
        hostname="vcenter.example", ip_address="10.0.0.1", connection_config={},
    )
    db.add(hv)
    db.commit()
    db.refresh(hv)
    return hv


def _add_vm(db, *, name, datastore=None, disk_gb=10):
    db.add(Server(
        name=name, vm_name=name, server_type="VIRTUAL",
        vm_datastore=datastore, vm_disk_gb=disk_gb,
    ))


def _add_ds(db, hv, *, name):
    db.add(VirtDatastore(hypervisor_id=hv.id, name=name, as_of=datetime.now(timezone.utc)))


def test_extract_datastore_filter_finds_real_name(db_session):
    hv = _make_hv(db_session)
    _add_ds(db_session, hv, name="NVME_DS")
    _add_ds(db_session, hv, name="datastore2")
    db_session.commit()

    assert hvi._extract_datastore_filter(db_session, "NVME_DS datastorede hangi vmlere ait diskler var?") == "NVME_DS"
    # Regresyonun ikinci varyasyonu: literal "datastore" kelimesi hiç geçmeden de çalışmalı.
    assert hvi._extract_datastore_filter(db_session, "NVME_DS burada hangi vmlere ait diskler mevcut?") == "NVME_DS"


def test_extract_datastore_filter_none_when_no_name_mentioned(db_session):
    hv = _make_hv(db_session)
    _add_ds(db_session, hv, name="NVME_DS")
    db_session.commit()

    assert hvi._extract_datastore_filter(db_session, "hangi datastorede hangi vmler var?") is None


def test_h_datastore_vm_map_scopes_when_name_given(db_session):
    hv = _make_hv(db_session)
    _add_ds(db_session, hv, name="NVME_DS")
    _add_ds(db_session, hv, name="datastore2")
    _add_vm(db_session, name="web01", datastore="NVME_DS", disk_gb=120)
    _add_vm(db_session, name="db02", datastore="datastore2", disk_gb=500)
    db_session.commit()

    out = hvi.h_datastore_vm_map(db_session, "NVME_DS datastorede hangi vmlere ait diskler var?")
    assert "NVME_DS" in out
    assert "web01" in out
    assert "datastore2" not in out
    assert "db02" not in out
    assert "filtre: **NVME_DS**" in out


def test_h_datastore_vm_map_shows_all_when_no_name_given(db_session):
    hv = _make_hv(db_session)
    _add_ds(db_session, hv, name="NVME_DS")
    _add_ds(db_session, hv, name="datastore2")
    _add_vm(db_session, name="web01", datastore="NVME_DS", disk_gb=120)
    _add_vm(db_session, name="db02", datastore="datastore2", disk_gb=500)
    db_session.commit()

    out = hvi.h_datastore_vm_map(db_session, "hangi datastorede hangi vmler var?")
    assert "NVME_DS" in out
    assert "datastore2" in out
    assert "web01" in out
    assert "db02" in out


def test_h_datastore_by_disk_scopes_when_name_given(db_session):
    hv = _make_hv(db_session)
    _add_ds(db_session, hv, name="NVME_DS")
    _add_vm(db_session, name="web01", datastore="NVME_DS", disk_gb=120)
    _add_vm(db_session, name="db02", datastore="datastore2", disk_gb=500)
    db_session.commit()

    out = hvi.h_datastore_by_disk(db_session, "NVME_DS'de kapasite ne kadar?")
    assert "NVME_DS" in out
    assert "datastore2" not in out
    assert "filtre: **NVME_DS**" in out
