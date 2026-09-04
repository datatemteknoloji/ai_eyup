"""virt_db_query — yeni datastore/name_filter parametreleri (kapsam daraltma).

Kullanıcı şikayeti: "NVME_DS'de hangi vmler var" sorusu TÜM VM'leri
döndürüyordu çünkü list_vms_db'nin datastore'a göre filtreleme parametresi
YOKTU. Bu testler yeni eklenen gerçek SQL-seviyesi filtreleri doğrular.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_inventory import HypervisorHostInventory
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_datastore import VirtDatastore
from app.services.virt_db_query import list_datastores_db, list_esx_hosts_db, list_vms_db


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Hypervisor.__table__.create(engine)
    Server.__table__.create(engine)
    VirtDatastore.__table__.create(engine)
    HypervisorHostMetric.__table__.create(engine)
    HypervisorHostInventory.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
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


def test_list_vms_db_filters_by_datastore(db_session):
    db_session.add_all([
        Server(name="web01", vm_name="web01", server_type="VIRTUAL", vm_datastore="NVME_DS"),
        Server(name="db02", vm_name="db02", server_type="VIRTUAL", vm_datastore="SATA_DS"),
    ])
    db_session.commit()

    result = list_vms_db(db_session, datastore="NVME_DS")
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["vms"][0]["name"] == "web01"


def test_list_vms_db_filters_by_name(db_session):
    db_session.add_all([
        Server(name="web01", vm_name="web01", server_type="VIRTUAL"),
        Server(name="db02", vm_name="db02", server_type="VIRTUAL"),
    ])
    db_session.commit()

    result = list_vms_db(db_session, name_filter="web01")
    assert result["count"] == 1
    assert result["vms"][0]["name"] == "web01"


def test_list_vms_db_no_filter_returns_all(db_session):
    db_session.add_all([
        Server(name="web01", vm_name="web01", server_type="VIRTUAL", vm_datastore="NVME_DS"),
        Server(name="db02", vm_name="db02", server_type="VIRTUAL", vm_datastore="SATA_DS"),
    ])
    db_session.commit()

    result = list_vms_db(db_session)
    assert result["count"] == 2


def test_list_datastores_db_name_filter(db_session):
    hv = _make_hv(db_session)
    db_session.add_all([
        VirtDatastore(hypervisor_id=hv.id, name="NVME_DS", as_of=datetime.now(timezone.utc)),
        VirtDatastore(hypervisor_id=hv.id, name="SATA_DS", as_of=datetime.now(timezone.utc)),
    ])
    db_session.commit()

    result = list_datastores_db(db_session, name_filter="NVME_DS")
    assert result["count"] == 1
    assert result["datastores"][0]["name"] == "NVME_DS"


def test_list_esx_hosts_db_name_filter(db_session):
    hv = _make_hv(db_session)
    db_session.add_all([
        HypervisorHostMetric(hypervisor_id=hv.id, host_name="esx03"),
        HypervisorHostMetric(hypervisor_id=hv.id, host_name="esx04"),
    ])
    db_session.commit()

    result = list_esx_hosts_db(db_session, name_filter="esx03")
    assert result["count"] == 1
    assert result["hosts"][0]["name"] == "esx03"
