"""Adım 6a — araçta hesaplama: pod gruplu sayım / top-N / erişilemeyen cluster, grafik lideri, olay kesilme notu."""
from types import SimpleNamespace

from app.services.agent import tools as T
from app.services import chat_charts as cc
from app.services import vcenter_vm_lifecycle as lc


class _Client:
    def __init__(self, pods=None, err=None, raise_=None):
        self._pods, self.last_error, self._raise = pods or [], err, raise_

    def list_pods(self, namespace=None):
        if self._raise:
            raise self._raise
        return [dict(p) for p in self._pods]


OVIRT = [
    {"namespace": "a", "name": "p1", "status": "Running", "restart_count": 53813},
    {"namespace": "b", "name": "p2", "status": "CrashLoopBackOff", "reason": "CrashLoopBackOff", "restart_count": 45459},
    {"namespace": "c", "name": "p3", "status": "Running", "restart_count": 0},
    {"namespace": "c", "name": "p4", "status": "Error", "reason": "Error", "restart_count": 0},
    {"namespace": "c", "name": "p5", "status": "Succeeded", "reason": "Completed", "restart_count": 0},
]


def _clusters(*names):
    return [SimpleNamespace(id=i, name=n) for i, n in enumerate(names, 2)]


def _run(clients):
    cl = _clusters(*clients.keys())
    return T._list_ocp_pods_all_clusters(cl, None, client_factory=lambda c: clients[c.name])


def test_all_clusters_unreachable_marked_and_total_from_reachable():
    r = _run({"oVirt": _Client(OVIRT), "ZZ-FAKE-OCP": _Client([], err="Connection error: fake-ocp.invalid")})
    assert r["ok"] and r["scope"] == "all_clusters"
    assert r["reachable_total"] == 5
    assert r["unreachable_clusters"][0]["cluster"] == "ZZ-FAKE-OCP"
    assert "BİLİNMİYOR" in r["unreachable_note"] and "ZZ-FAKE-OCP" in r["unreachable_note"]
    per = {p["cluster"]: p for p in r["per_cluster"]}
    assert per["oVirt"]["reachable"] and per["oVirt"]["count"] == 5
    assert per["ZZ-FAKE-OCP"]["reachable"] is False and per["ZZ-FAKE-OCP"]["count"] is None


def test_all_clusters_reason_breakdown_and_problem_definition():
    r = _run({"oVirt": _Client(OVIRT), "X": _Client(OVIRT[:1])})
    assert r["by_reason"]["CrashLoopBackOff"] == 1 and r["by_reason"]["Error"] == 1
    assert r["by_reason"]["5+ restart (Running)"] == 2
    assert r["problem_count"] == 4
    assert "Hatalı pod tanımı" in r["problem_definition"]
    assert "unreachable_clusters" not in r


def test_all_clusters_exception_is_unreachable():
    r = _run({"oVirt": _Client(OVIRT), "Y": _Client(raise_=RuntimeError("tls"))})
    assert [u["cluster"] for u in r["unreachable_clusters"]] == ["Y"]


def test_all_clusters_none_reachable():
    r = _run({"A": _Client(err="x"), "B": _Client(err="y")})
    assert r["ok"] is False and r["live_connection_failed"]


def test_top_restarts_sorted_with_rank():
    r = _run({"oVirt": _Client(OVIRT), "Z": _Client([{"namespace": "z", "name": "zz", "status": "Running", "restart_count": 60000}])})
    top = r["top_restarts"]
    assert [t["name"] for t in top] == ["zz", "p1", "p2"]
    assert top[0]["rank"] == 1 and top[0]["cluster"] == "Z" and top[0]["restart_count"] == 60000
    assert "rank 1" in r["top_restarts_note"]


def test_top_restarts_excludes_zero():
    assert T._top_restarts([{"name": "a", "restart_count": 0}]) == []


def test_rank_leader_line_highest_and_lowest():
    charts = [{"title": "CPU Kullanımı — x", "unit": "core", "series": [
        {"label": "ns/a — CPU (cores)", "points": [{"v": 0.01}, {"v": 0.03}]},
        {"label": "ns/b — CPU (cores)", "points": [{"v": 0.05}, {"v": 0.04}]},
        {"label": "ns/c — CPU (cores)", "points": []},
    ]}]
    hi = cc.rank_leader_line(charts, "highest", 1)
    assert "En yüksek CPU Kullanımı" in hi and "ns/b — 0.045 core" in hi and "Top-2" in hi
    lo = cc.rank_leader_line(charts, "lowest", 1)
    assert "En düşük" in lo and "ns/a — 0.020 core" in lo
    assert cc.rank_leader_line([], "highest", 1) == ""


def test_summary_text_lead_first():
    t = cc._summary_text(title="T", hours=1, charts=[], sources=[], missing=[], notes=[], lead="**LEAD**")
    assert t.splitlines()[2] == "**LEAD**"


def test_truncation_note(monkeypatch):
    from app.services import hypervisor_intelligence as hi
    lc._TRUNCATED.set([{"hypervisor": "office", "max_events": 3000}])
    note = hi._ev_src_note([], vmware_only=True)
    assert "Sonuç kesildi" in note and "office (ilk 3000 olay)" in note and "toplam bilinmiyor" in note
    assert "Sonuç kesildi" not in hi._ev_src_note([])


def test_fetch_events_records_truncation(monkeypatch):
    hv = SimpleNamespace(name="office")
    monkeypatch.setattr(lc, "_vmware_hypervisors", lambda db: [hv])

    class _VC:
        def query_lifecycle_events(self, types, days=7, max_events=3000):
            return {"events": [{"timestamp": "2026-10-14T10:00:00Z"}] * 2, "errors": [], "truncated": True, "max_events": 2}
    monkeypatch.setattr(lc, "_build_client", lambda h: _VC())

    class _Q:
        def filter(self, *a):
            return self

        def all(self):
            return []

    db = SimpleNamespace(query=lambda *a: _Q())
    lc.pop_truncation()
    out = lc.fetch_events(db, ["VmPoweredOnEvent"], days=1, max_events=2)
    assert out["truncated"] == [{"hypervisor": "office", "max_events": 2}]
    assert lc.pop_truncation() == [{"hypervisor": "office", "max_events": 2}]
    assert lc.pop_truncation() == []
