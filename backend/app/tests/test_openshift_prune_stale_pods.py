"""İş-1 — OpenShift senkronu: bayat pod temizliği (yalnız TAM+BAŞARILI listelemede, cluster bazında).

İzole geçici DB (isolated_db.py); canlı veriye dokunmaz.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.models.openshift import OpenShiftCluster, OpenShiftNode, OpenShiftProject, OpenShiftWorkload
from app.services import openshift_sync_service as svc
from app.services.openshift.ocp_client import OpenShiftClient as OCPClient


@pytest.fixture()
def db(isolated_db):
    from app.core.database import Base
    eng = isolated_db.get_bind()
    Base.metadata.create_all(eng, tables=[OpenShiftCluster.__table__, OpenShiftWorkload.__table__,
                                              OpenShiftProject.__table__, OpenShiftNode.__table__])
    for t in (OpenShiftWorkload, OpenShiftProject, OpenShiftNode):
        isolated_db.execute(t.__table__.delete())
    isolated_db.execute(OpenShiftWorkload.__table__.delete())
    isolated_db.execute(OpenShiftCluster.__table__.delete())
    isolated_db.commit()
    return isolated_db


def _cluster(db, name="c1", meta=None):
    c = OpenShiftCluster(name=name, api_url="https://x.invalid", connection_config={}, meta_data=meta)
    db.add(c)
    db.commit()
    return c


def _pods(db, cluster, names, ns="ns1", kind="pod"):
    for n in names:
        db.add(OpenShiftWorkload(cluster_id=cluster.id, project=ns, kind=kind, name=n, status="Running"))
    db.commit()


def _names(db, cluster, kind="pod"):
    rows = db.query(OpenShiftWorkload).filter_by(cluster_id=cluster.id, kind=kind).all()
    return sorted(r.name for r in rows)


def _prune(db, c, seen, **kw):
    kw.setdefault("list_complete", True)
    kw.setdefault("had_errors", False)
    res = svc.prune_stale_pods(db, c, {("ns1", n) for n in seen}, **kw)
    db.commit()
    return res


def test_full_list_deletes_only_stale(db):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "c", "d"])
    r = _prune(db, c, ["a", "b", "c"])
    assert r["deleted"] == 1 and r["reason"] == "ok"
    assert _names(db, c) == ["a", "b", "c"]


def test_incomplete_list_deletes_nothing(db):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "c", "d"])
    r = _prune(db, c, ["a"], list_complete=False)
    assert r["deleted"] == 0 and r["reason"] == "list_incomplete"
    assert len(_names(db, c)) == 4


def test_sync_errors_delete_nothing(db):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "c", "d"])
    r = _prune(db, c, ["a", "b", "c"], had_errors=True)
    assert r["deleted"] == 0 and r["reason"] == "sync_errors"
    assert len(_names(db, c)) == 4


def test_empty_list_deletes_nothing(db):
    c = _cluster(db)
    _pods(db, c, ["a", "b"])
    r = _prune(db, c, [])
    assert r["deleted"] == 0 and r["reason"] == "empty_list"
    assert len(_names(db, c)) == 2


def test_other_cluster_untouched(db):
    c1, c2 = _cluster(db, "c1"), _cluster(db, "c2")
    _pods(db, c1, ["a", "b", "x"])
    _pods(db, c2, ["a", "b", "x"])           # aynı adlar, başka cluster
    r = _prune(db, c1, ["a", "b"])
    assert r["deleted"] == 1
    assert _names(db, c1) == ["a", "b"]
    assert _names(db, c2) == ["a", "b", "x"]


def test_fake_cluster_skipped(db):
    c = _cluster(db, "ZZ-FAKE-OCP", meta={"fake_seed": True})
    _pods(db, c, ["a", "b", "c"])
    r = _prune(db, c, ["a"])
    assert r["deleted"] == 0 and r["reason"] == "fake_cluster"
    assert len(_names(db, c)) == 3


def test_only_pod_kind_deleted(db):
    c = _cluster(db)
    _pods(db, c, ["a", "gone"])
    _pods(db, c, ["dep1", "dep2"], kind="deployment")
    _pods(db, c, ["svc1"], kind="service")
    r = _prune(db, c, ["a"])
    assert r["deleted"] == 1
    assert _names(db, c, "deployment") == ["dep1", "dep2"]
    assert _names(db, c, "service") == ["svc1"]


def test_same_name_other_namespace_distinguished(db):
    c = _cluster(db)
    _pods(db, c, ["p"], ns="ns1")
    _pods(db, c, ["p"], ns="ns2")
    res = svc.prune_stale_pods(db, c, {("ns1", "p")}, list_complete=True, had_errors=False)
    db.commit()
    assert res["deleted"] == 1
    rows = db.query(OpenShiftWorkload).filter_by(cluster_id=c.id, kind="pod").all()
    assert [(r.project, r.name) for r in rows] == [("ns1", "p")]


def test_dry_run_does_not_write(db):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "c", "d"])
    r = _prune(db, c, ["a", "b", "c"], dry_run=True)
    assert r["stale"] == 1 and r["deleted"] == 0 and r["dry_run"] is True
    assert len(_names(db, c)) == 4


def test_mass_delete_guard(db):
    c = _cluster(db)
    names = [f"p{i}" for i in range(100)]
    _pods(db, c, names)
    r = _prune(db, c, names[:30])                  # 70 bayat / 100 > %50 ve > 20 → otomatik silme yok
    assert r["deleted"] == 0 and r["reason"] == "too_large"
    assert len(_names(db, c)) == 100
    r2 = _prune(db, c, names[:60])                 # 40 bayat / 100 ≤ %50 → siler
    assert r2["deleted"] == 40


def test_rows_created_after_sync_start_not_deleted(db):
    c = _cluster(db)
    _pods(db, c, ["a", "late"])
    started = datetime.now(timezone.utc) - timedelta(hours=1)    # 'late' senkron başlangıcından SONRA oluşmuş sayılır
    r = _prune(db, c, ["a"], sync_started_at=started)
    assert r["deleted"] == 0
    assert len(_names(db, c)) == 2


def test_setting_off_disables(db, monkeypatch):
    from app.services import runtime_settings as rs
    real = rs.get_bool
    monkeypatch.setattr(rs, "get_bool", lambda k: False if k == "openshift_sync_prune_enabled" else real(k))
    c = _cluster(db)
    _pods(db, c, ["a", "b"])
    r = _prune(db, c, ["a"])
    assert r["deleted"] == 0 and r["reason"] == "disabled"


def test_setting_default_on():
    from app.services import runtime_settings as rs
    assert rs.ADVANCED_SCHEMA["openshift_sync_prune_enabled"]["default"] is True


# ---- istemci: tam-liste işareti -------------------------------------------------------------

def _client_with(responses):
    cl = OCPClient.__new__(OCPClient)
    cl.last_error = ""
    cl.pods_complete = False
    it = iter(responses)
    cl._get = lambda path, params=None, timeout=None: next(it)
    cl._describe_http_error = lambda r: f"HTTP {r.status_code}"
    cl._parse_quantity = lambda v: 0.0
    return cl


def _resp(code, items=(), cont=None):
    r = MagicMock()
    r.status_code = code
    r.text = ""
    r.json.return_value = {"items": list(items), "metadata": {"continue": cont} if cont else {}}
    return r


def _item(name):
    return {"metadata": {"namespace": "ns1", "name": name}, "status": {"phase": "Running"}, "spec": {}}


def test_list_pods_complete_flag():
    cl = _client_with([_resp(200, [_item("a")], cont="t1"), _resp(200, [_item("b")])])
    pods = cl.list_pods()
    assert [p["name"] for p in pods] == ["a", "b"] and cl.pods_complete is True and cl.last_error == ""


def test_list_pods_http_error_midway_is_incomplete():
    cl = _client_with([_resp(200, [_item("a")], cont="t1"), _resp(500)])
    pods = cl.list_pods()
    assert [p["name"] for p in pods] == ["a"]           # kısmi liste dönüyor (eski davranış)…
    assert cl.pods_complete is False and cl.last_error  # …ama TAM değil
    assert cl.last_error


def test_list_pods_exception_is_incomplete():
    cl = _client_with([])

    def boom(*a, **k):
        raise TimeoutError("zaman aşımı")
    cl._get = boom
    assert cl.list_pods() == [] and cl.pods_complete is False and "zaman" in cl.last_error


def test_list_pods_page_cap_is_incomplete():
    cl = _client_with([_resp(200, [_item(f"p{i}")], cont=f"t{i}") for i in range(60)])
    cl.list_pods()
    assert cl.pods_complete is False                   # 50 sayfa sınırına takıldı → kısmi


# ---- senkron entegrasyonu --------------------------------------------------------------------

class _FakeClient:
    def __init__(self, pods, complete=True, last_error="", connect_ok=True):
        self._pods, self.pods_complete, self.last_error, self._ok = pods, complete, last_error, connect_ok

    def test_connection(self):
        return (self._ok, "" if self._ok else "bağlanamadı")

    def list_nodes(self): return []
    def list_projects(self): return [{"name": "ns1"}]
    def list_pods(self): return self._pods
    def list_deployments(self): return []
    def list_routes(self): return []
    def list_services(self): return []
    def get_version(self): return "4.18"
    def logout(self): pass


def _run_sync(db, monkeypatch, c, client):
    import app.services.openshift.cluster_ops as ops
    monkeypatch.setattr(ops, "client_from_cluster", lambda cl: client)
    monkeypatch.setattr("app.services.openshift_virt_inventory.sync_kubevirt_vms_into_servers",
                        lambda *a, **k: {"skipped": True, "total_vms": 0, "synced_count": 0, "errors": []})
    monkeypatch.setattr("app.services.openshift_virt_host_metrics.sync_openshift_virt_host_metrics",
                        lambda *a, **k: {"hosts": 0})
    r = svc.sync_openshift_cluster(db, c)
    db.commit()
    return r


def _live(*names):
    return [{"namespace": "ns1", "name": n, "status": "Running", "node_name": "n1", "restart_count": 0, "ready": "1/1"} for n in names]


def test_sync_full_success_prunes(db, monkeypatch):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "old1", "old2"])
    r = _run_sync(db, monkeypatch, c, _FakeClient(_live("a", "b")))
    assert r["pods_pruned"] == 2 and _names(db, c) == ["a", "b"]


def test_sync_failed_connection_keeps_everything(db, monkeypatch):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "old1", "old2"])
    _run_sync(db, monkeypatch, c, _FakeClient([], connect_ok=False))
    assert len(_names(db, c)) == 4


def test_sync_partial_list_keeps_everything(db, monkeypatch):
    c = _cluster(db)
    _pods(db, c, ["a", "b", "old1", "old2"])
    r = _run_sync(db, monkeypatch, c, _FakeClient(_live("a"), complete=False, last_error="HTTP 500"))
    assert r["pods_pruned"] == 0 and len(_names(db, c)) == 4 + 0 and "a" in _names(db, c)
