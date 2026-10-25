"""Beş yönetici raporu: sentetik dışarıda, ay-ay yalnız kilitli görüntü, yığın p95 dışı."""
import socket
from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import Incident, SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.infrastructure_report import InfrastructureReport
from app.models.server import Server
from app.services.exec_facts import REQUIRED_FS_METRICS, build_executive_facts


def _period():
    end = datetime(2026, 11, 1, tzinfo=timezone.utc)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return start, end


def _by_type(facts):
    return {item["report_type"]: item for item in facts}


def test_synthetic_vm_is_outside_idle_and_events_and_no_money(isolated_db, monkeypatch):
    db = isolated_db
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    fake = Hypervisor(
        name="ZZ-FAKE-vCenter", hypervisor_type=HypervisorType.VMWARE,
        hostname="fake.invalid", ip_address="198.18.0.8", connection_config={},
        meta_data={"synthetic": True},
    )
    real = Hypervisor(
        name="office", hypervisor_type=HypervisorType.VMWARE,
        hostname="vc.example", ip_address="10.1.0.8", connection_config={},
        meta_data={},
    )
    db.add_all([fake, real])
    db.flush()
    db.add(Server(
        name="fake-off", hypervisor_id=fake.id, connection_config={},
        vm_power_state="poweredOff", vm_cpu_count=8, vm_memory_mb=8192, vm_disk_gb=100,
    ))
    db.add(Server(
        name="real-off", hypervisor_id=real.id, connection_config={},
        vm_power_state="poweredOff", vm_cpu_count=2, vm_memory_mb=2048, vm_disk_gb=40,
    ))
    start, end = _period()
    db.add(SystemEvent(
        server_id=None, event_type="cpu_high", severity="critical", title="esx03 doluluk",
        created_at=start + timedelta(days=1), raw_data={"hypervisor_id": fake.id},
    ))
    db.add(SystemEvent(
        server_id=None, event_type="cpu_high", severity="warning", title="office-esx",
        created_at=start + timedelta(days=2), raw_data={"hypervisor_id": real.id},
    ))
    closed = start + timedelta(days=3)
    same = closed.replace(microsecond=0)
    db.add(Incident(title="tek", severity="warning", status="resolved", source="manual", created_at=closed - timedelta(hours=5), resolved_at=same))
    db.add(Incident(title="yigin-1", severity="warning", status="resolved", source="manual", created_at=closed - timedelta(hours=1), resolved_at=same + timedelta(hours=1)))
    db.add(Incident(title="yigin-2", severity="warning", status="resolved", source="manual", created_at=closed - timedelta(hours=9), resolved_at=same + timedelta(hours=1, microseconds=200000)))
    db.commit()

    facts = _by_type(build_executive_facts(db, start, end))
    a2 = facts["a2"]["sections"][0]
    assert a2["numbers"]["powered_off"]["value"] == 1
    assert a2["numbers"]["wasted_vcpu"]["value"] == 2
    assert any("para gösterilmez" in n for n in a2["notes"])
    assert facts["a2"]["sections"][1]["status"] == "unmeasured"
    a1 = next(s for s in facts["a1"]["sections"] if s["id"] == "a1")
    assert a1["numbers"]["events"]["value"] == 1
    assert a1["labels"]["risk_1"] == "office-esx"
    mom = next(s for s in facts["a1"]["sections"] if s["id"] == "a1_mom")
    assert mom["status"] == "unmeasured"
    a6 = facts["a6"]["sections"][0]
    assert a6["numbers"]["bulk_closed"]["value"] == 2
    assert a6["numbers"]["auto_closed"]["value"] == 0
    assert a6["numbers"]["p50_saat"]["value"] == 5.0
    assert a6["numbers"]["tail_count"]["value"] == 0
    assert not any("ayırt edilemiyor" in n for n in a6["notes"])
    linux = next(s for s in facts["b1"]["sections"] if s["id"] == "b1_linux")
    assert linux["status"] == "unmeasured"
    assert all(name in linux["notes"][0] for name in REQUIRED_FS_METRICS)
    assert next(s for s in facts["b1"]["sections"] if s["id"] == "b1_ocp")["status"] == "unmeasured"
    assert "mean" not in str(a6["numbers"])


def test_month_delta_comes_only_from_locked_snapshots(isolated_db):
    db = isolated_db
    start, end = _period()
    older = datetime(2026, 9, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def locked(when, count):
        db.add(InfrastructureReport(
            report_type="executive_monthly",
            report_title="a1",
            status="locked",
            generated_at=when,
            summary=None,
            data={"locked": True, "facts": {"sections": [{
                "id": "a1",
                "numbers": {"events": {"value": count, "display": [str(count)]}},
            }]}},
        ))

    locked(older, 10)
    locked(newer, 4)
    db.add(SystemEvent(
        event_type="cpu_high", severity="critical", title="canli",
        created_at=start + timedelta(days=1), raw_data={},
    ))
    db.commit()
    facts = _by_type(build_executive_facts(db, start, end))
    mom = next(s for s in facts["a1"]["sections"] if s["id"] == "a1_mom")
    assert mom["status"] == "ok"
    assert mom["numbers"]["delta"]["value"] == -6
    assert mom["numbers"]["newer"]["value"] == 4


def test_duration_ignores_automatic_timeout_and_counts_it(isolated_db):
    db = isolated_db
    start, end = _period()
    closed = start + timedelta(days=2)
    db.add(Incident(
        title="elle", severity="warning", status="resolved", source="manual",
        resolution="Kullanıcı kapattı",
        created_at=closed - timedelta(hours=10), resolved_at=closed,
    ))
    db.add(Incident(
        title="zaman", severity="warning", status="resolved", source="auto_vcenter_event",
        resolution="Otomatik kapatıldı: 24 saattir yeni olay/tekrar yok.",
        created_at=closed - timedelta(hours=1), resolved_at=closed + timedelta(hours=2),
    ))
    db.add(Incident(
        title="uzun", severity="critical", status="resolved", source="rule",
        resolution="Kural kapattı",
        created_at=closed - timedelta(hours=40), resolved_at=closed + timedelta(seconds=5),
    ))
    db.commit()
    facts = _by_type(build_executive_facts(db, start, end))
    a6 = facts["a6"]["sections"][0]
    assert a6["numbers"]["auto_closed"]["value"] == 1
    assert a6["status"] == "ok"
    assert a6["numbers"]["p50_saat"]["value"] == 25.0
    assert a6["numbers"]["tail_count"]["value"] == 1
    assert a6["numbers"]["tail_longest_saat"]["value"] == 40.0
    assert not any("ayırt edilemiyor" in n for n in a6["notes"])


def test_unknown_close_keeps_the_distinguishing_note(isolated_db):
    db = isolated_db
    start, end = _period()
    closed = start + timedelta(days=1)
    db.add(Incident(
        title="belirsiz", severity="warning", status="resolved",
        created_at=closed - timedelta(hours=4), resolved_at=closed,
    ))
    db.commit()
    a6 = _by_type(build_executive_facts(db, start, end))["a6"]["sections"][0]
    assert any(n == "kapanış türü ayırt edilemiyor; süreler otomatik kapanışları içerebilir" for n in a6["notes"])
    assert a6["numbers"]["p50_saat"]["value"] == 4.0


def test_openshift_card_count_excludes_synthetic_cluster(isolated_db):
    from app.models.openshift import OpenShiftCluster, OpenShiftNode

    db = isolated_db
    fake = OpenShiftCluster(name="ZZ-FAKE-OCP", api_url="https://fake.invalid:6443", connection_config={}, meta_data={"synthetic": True})
    real = OpenShiftCluster(name="oVirt", api_url="https://192.168.1.241:6443", connection_config={}, version="v1.34.6", meta_data={})
    db.add_all([fake, real])
    db.flush()
    db.add(OpenShiftNode(cluster_id=real.id, name="master-0"))
    db.add(OpenShiftNode(cluster_id=fake.id, name="fake-node"))
    db.commit()
    start, end = _period()
    ocp = next(s for s in _by_type(build_executive_facts(db, start, end))["b1"]["sections"] if s["id"] == "b1_ocp")
    assert ocp["numbers"]["clusters"]["value"] == 1
    assert ocp["numbers"]["nodes"]["value"] == 1
    assert ocp["labels"]["clusters"] == "oVirt"
    assert ocp["labels"]["kind"] == "OpenShift cluster"
