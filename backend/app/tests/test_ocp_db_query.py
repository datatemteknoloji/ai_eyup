"""ocp_db_query unit testleri — sqlite in-memory, yalnızca openshift tabloları.

virt_db_query.py'deki DB-first desenin OpenShift karşılığı: node/proje envanteri
periyodik sync (openshift_sync_service.py) ile dolan openshift_nodes/openshift_projects
tablolarından okunur.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject
from app.services.ocp_db_query import list_ocp_nodes_db, list_ocp_projects_db


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    OpenShiftCluster.__table__.create(engine)
    OpenShiftNode.__table__.create(engine)
    OpenShiftProject.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_cluster(db, *, name="prod-ocp", last_sync=None):
    c = OpenShiftCluster(
        name=name,
        api_url="https://api.example:6443",
        connection_config={"token": "x"},
        status="ONLINE",
        last_sync=last_sync if last_sync is not None else datetime.now(timezone.utc),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_list_ocp_nodes_db_join_and_fresh(db_session):
    c = _make_cluster(db_session)
    db_session.add_all([
        OpenShiftNode(cluster_id=c.id, name="master-0", role="master", status="Ready",
                      cpu_cores=8, memory_gb=32, pod_count=40),
        OpenShiftNode(cluster_id=c.id, name="worker-0", role="worker", status="Ready",
                      cpu_cores=16, memory_gb=64, pod_count=80),
    ])
    db_session.commit()

    result = list_ocp_nodes_db(db_session, cluster="prod-ocp")
    assert result["ok"] is True
    assert result["source"] == "db"
    assert result["count"] == 2
    assert result["stale"] is False
    names = {n["name"] for n in result["nodes"]}
    assert names == {"master-0", "worker-0"}


def test_list_ocp_nodes_db_role_filter(db_session):
    c = _make_cluster(db_session)
    db_session.add_all([
        OpenShiftNode(cluster_id=c.id, name="master-0", role="master", status="Ready"),
        OpenShiftNode(cluster_id=c.id, name="worker-0", role="worker", status="Ready"),
    ])
    db_session.commit()

    result = list_ocp_nodes_db(db_session, cluster="prod-ocp", role="master")
    assert result["count"] == 1
    assert result["nodes"][0]["name"] == "master-0"


def test_list_ocp_nodes_db_stale_when_old_sync(db_session):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    c = _make_cluster(db_session, last_sync=old)
    db_session.add(OpenShiftNode(cluster_id=c.id, name="worker-0", role="worker", status="Ready"))
    db_session.commit()

    result = list_ocp_nodes_db(db_session, cluster="prod-ocp")
    assert result["stale"] is True


def test_list_ocp_nodes_db_no_cluster_defined_returns_error(db_session):
    result = list_ocp_nodes_db(db_session, cluster="anything")
    assert result["ok"] is False
    assert "error" in result


def test_list_ocp_nodes_db_unknown_name_falls_back_to_first_cluster(db_session):
    # agent/tools.py::resolve_openshift_cluster ile aynı davranış — tekli
    # cluster kurulumunda isim yanlış/eksik olsa da çalışmaya devam eder.
    c = _make_cluster(db_session)
    db_session.add(OpenShiftNode(cluster_id=c.id, name="worker-0", role="worker", status="Ready"))
    db_session.commit()

    result = list_ocp_nodes_db(db_session, cluster="typo-name")
    assert result["ok"] is True
    assert result["cluster"] == "prod-ocp"


def test_list_ocp_projects_db_filter(db_session):
    c = _make_cluster(db_session)
    db_session.add_all([
        OpenShiftProject(cluster_id=c.id, name="team-a", pod_count=5, deployment_count=2, route_count=1),
        OpenShiftProject(cluster_id=c.id, name="team-b", pod_count=3, deployment_count=1, route_count=0),
    ])
    db_session.commit()

    result = list_ocp_projects_db(db_session, cluster="prod-ocp", name_filter="team-a")
    assert result["ok"] is True
    assert result["count"] == 1
    assert result["projects"][0]["name"] == "team-a"


def test_list_ocp_projects_db_all(db_session):
    c = _make_cluster(db_session)
    db_session.add(OpenShiftProject(cluster_id=c.id, name="team-a", pod_count=5))
    db_session.commit()

    result = list_ocp_projects_db(db_session)
    assert result["count"] == 1
    assert result["source"] == "db"
