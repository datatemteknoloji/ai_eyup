"""virt_entity_resolver unit testleri — sqlite in-memory.

Genel kural testi: mesajdan datastore/VM/host/cluster adı çıkarımı TAHMİN
değil, DB'deki GERÇEK isimlerle karşılaştırma ile yapılır. Bu mekanizma
datastore'a özel değildir — herhangi bir isimlendirilmiş varlık için aynı
şekilde çalışır (kullanıcının "farklı bir senaryoda olabilirdi" uyarısı).
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.hypervisor_metric import HypervisorHostMetric
from app.models.server import Server
from app.models.virt_datastore import VirtDatastore
from app.services import virt_entity_resolver as resolver


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Hypervisor.__table__.create(engine)
    Server.__table__.create(engine)
    VirtDatastore.__table__.create(engine)
    HypervisorHostMetric.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # her testte taze önbellek — modüller arası TTL cache sızmasın
    resolver._cache.clear()
    try:
        yield session
    finally:
        session.close()


def _make_hv(db, name="Office"):
    hv = Hypervisor(
        name=name,
        hypervisor_type=HypervisorType.VMWARE,
        hostname="vcenter.example",
        ip_address="10.0.0.1",
        connection_config={},
    )
    db.add(hv)
    db.commit()
    db.refresh(hv)
    return hv


def _add_vm(db, *, name, cluster=None, datastore=None):
    db.add(Server(
        name=name, vm_name=name, server_type="VIRTUAL",
        vm_cluster=cluster, vm_datastore=datastore,
    ))


def _add_datastore(db, hv, *, name):
    db.add(VirtDatastore(
        hypervisor_id=hv.id, name=name, as_of=datetime.now(timezone.utc),
    ))


def _add_host(db, hv, *, host_name):
    db.add(HypervisorHostMetric(hypervisor_id=hv.id, host_name=host_name))


def test_extract_datastore_name(db_session):
    hv = _make_hv(db_session)
    _add_datastore(db_session, hv, name="NVME_DS")
    _add_datastore(db_session, hv, name="SATA_DS")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "NVME_DS bu datastorede hangi vmlere ait diskler bulunuyor?")
    assert out == {"datastore": "NVME_DS"}


def test_extract_is_case_insensitive(db_session):
    hv = _make_hv(db_session)
    _add_datastore(db_session, hv, name="NVME_DS")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "nvme_ds datastore'unda ne var?")
    assert out.get("datastore") == "NVME_DS"


def test_extract_vm_name(db_session):
    _add_vm(db_session, name="web01")
    _add_vm(db_session, name="db02")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "web01 vm'inin diskleri neler?")
    assert out == {"vm_name": "web01"}


def test_extract_host_name(db_session):
    hv = _make_hv(db_session)
    _add_host(db_session, hv, host_name="esx03.local")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "esx03.local host'undaki VM'ler hangileri?")
    assert out == {"host_name": "esx03.local"}


def test_extract_cluster_name(db_session):
    _add_vm(db_session, name="app01", cluster="ProdCluster")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "ProdCluster kümesindeki VM'leri listele")
    assert out == {"cluster": "ProdCluster"}


def test_extract_no_match_returns_empty(db_session):
    _add_vm(db_session, name="web01")
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "genel olarak kaç VM var?")
    assert out == {}


def test_extract_prefers_longest_and_respects_word_boundary(db_session):
    hv = _make_hv(db_session)
    _add_datastore(db_session, hv, name="DS10")
    _add_datastore(db_session, hv, name="DS100")
    db_session.commit()

    # "DS100" mesajda geçiyor — "DS10" da bir substring olmasına rağmen kelime
    # sınırı (word-boundary) sayesinde YANLIŞ eşleşmez; en uzun/gerçek eşleşme seçilir.
    out = resolver.extract_entity_filters(db_session, "DS100 datastore'unda hangi vmler var?")
    assert out.get("datastore") == "DS100"


def test_extract_multiple_entities_at_once(db_session):
    hv = _make_hv(db_session)
    _add_datastore(db_session, hv, name="NVME_DS")
    _add_vm(db_session, name="ProdCluster-app01", cluster="ProdCluster")
    db_session.commit()

    out = resolver.extract_entity_filters(
        db_session, "ProdCluster kümesindeki NVME_DS datastore'undaki vmler",
    )
    assert out.get("datastore") == "NVME_DS"
    assert out.get("cluster") == "ProdCluster"


def test_extract_ignores_short_names(db_session):
    _add_vm(db_session, name="vm")  # 2 karakter — _MIN_NAME_LEN altı, dikkate alınmaz
    db_session.commit()

    out = resolver.extract_entity_filters(db_session, "vm listesi göster")
    assert out == {}
