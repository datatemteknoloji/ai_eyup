"""Sentetik kapsam: işaretle, silme, gerçek kaydı yönetici kümesine alma."""
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.integration_instance import IntegrationInstance
from app.models.openshift import OpenShiftCluster
from app.models.server import Server
from app.services.synthetic_scope import (
    inventory, mark, synthetic_hypervisor_ids, synthetic_integration_ids, synthetic_server_ids,
)


def test_fake_seed_and_demo_kind_are_synthetic_real_is_not(isolated_db):
    db = isolated_db
    fake = Hypervisor(
        name="ZZ-FAKE-vCenter", hypervisor_type=HypervisorType.VMWARE,
        hostname="fake.invalid", ip_address="198.18.0.1", connection_config={},
        meta_data={"fake_seed": True},
    )
    real = Hypervisor(
        name="office", hypervisor_type=HypervisorType.VMWARE,
        hostname="vc.example", ip_address="10.0.0.8", connection_config={},
        meta_data={},
    )
    db.add_all([fake, real])
    db.flush()
    db.add(Server(name="zz-vm-1", hypervisor_id=fake.id, connection_config={}))
    db.add(Server(name="office-vm", hypervisor_id=real.id, connection_config={}))
    db.add(OpenShiftCluster(name="ZZ-FAKE-OCP", api_url="https://fake", connection_config={}, meta_data={"fake_seed": True}))
    db.add(OpenShiftCluster(name="oVirt", api_url="https://real", connection_config={}, meta_data={}))
    db.add(IntegrationInstance(category="backup", kind="veeam_demo", label="Veeam DEMO", endpoint="demo", enabled=True))
    db.add(IntegrationInstance(category="backup", kind="veeam_vbr", label="Veeam", endpoint="https://veeam", enabled=True))
    db.commit()

    hv_ids = synthetic_hypervisor_ids(db)
    assert fake.id in hv_ids and real.id not in hv_ids
    srv = synthetic_server_ids(db, hv_ids)
    names = {n for (n,) in db.query(Server.name).filter(Server.id.in_(srv)).all()}
    assert names == {"zz-vm-1"}
    kinds = {r.kind for r in db.query(IntegrationInstance).filter(IntegrationInstance.id.in_(synthetic_integration_ids(db))).all()}
    assert kinds == {"veeam_demo"}

    stamped = mark(db)
    assert stamped["hypervisors"] == 1 and stamped["integrations"] == 1
    db.refresh(fake)
    assert fake.meta_data.get("synthetic") is True and fake.meta_data.get("fake_seed") is True
    db.refresh(real)
    assert not (real.meta_data or {}).get("synthetic")
    assert db.query(Hypervisor).count() == 2

    again = mark(db)
    assert again == {"hypervisors": 0, "clusters": 0, "integrations": 0}
    tables = {r["table"] for r in inventory(db)}
    assert {"hypervisors", "openshift_clusters", "integration_instances", "servers"} <= tables
