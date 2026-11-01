"""Adım 20 — gerileme taraması: Linux sohbet yönlendirme düzeltmeleri."""
from app.services.chat_path_policy import resolve_live_path
from app.services.linux_chat_intent import is_fleet_inventory_query


def test_testserver_name_is_not_fleet_inventory():
    # «testserver» içindeki «ver» + «sunucu» envanter listesi sanılmamalı
    assert not is_fleet_inventory_query("mtv-testserver sunucusunun cpu kullanımı nedir?")
    assert not is_fleet_inventory_query("mtv-testserver sunucusunun son 3 saatlik cpu grafiği")


def test_real_inventory_questions_still_match():
    for q in (
        "sunucuların hostname ve ip listesini ver",
        "tüm sunucuları listele",
        "ver sunucu listesini",
        "ip adreslerini göster",
        "hangi sunucular kayıtlı",
    ):
        assert is_fleet_inventory_query(q), q


def test_script_bilgi_is_not_ip_inventory():
    assert not is_fleet_inventory_query("backup script bilgi ver")


def _path(msg, **kw):
    return resolve_live_path(
        msg, agentic_enabled=True, wants_fixed_collect=True, has_live_targets=True, **kw
    )


def test_named_server_nedir_is_live():
    p = _path("dttadvance sunucusunun uptime değeri nedir?", has_named_target=True)
    assert p.reason != "knowledge_only" and (p.run_agentic or p.run_fixed_collect)


def test_unnamed_conceptual_nedir_stays_knowledge_only():
    p = _path("uptime nedir?")
    assert p.reason == "knowledge_only" and not p.run_agentic


def test_named_chitchat_stays_chitchat():
    p = _path("merhaba", has_named_target=True)
    assert p.reason == "chitchat"


def test_verifier_block_note_path_does_not_collide_on_kind():
    # Adım 20: note_path(kind, **detail) — detail içinde `kind=` anahtarı TypeError verip turu çökertiyordu
    from app.services.chat_orchestrator import service
    import inspect
    src = inspect.getsource(service._on_violation)
    assert "kind=violation.kind" not in src.replace("violation_kind=violation.kind", "")
    from app.services.chat_quality.trace import TurnTrace
    tr = TurnTrace.__new__(TurnTrace)
    tr.paths = []
    tr.note_path("verifier_block", violation_kind="ungrounded_command", level="block")
    assert tr.paths[0]["kind"] == "verifier_block"


def test_virt_ask_thread_uses_own_session():
    # Adım 20: canlı akış sink'i orkestratör döngüsünü uyandırdığı için iş parçacığı istek Session'ını paylaşmamalı
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("api", "hypervisors.py").read_text()
    i = src.index("def _run_ask():")
    seg = src[i:i + 900]
    assert "ask_hypervisor_question(inner, _tdb" in seg and "ask_hypervisor_question(inner, db," not in seg


class _C:
    def __init__(self, name):
        self.name = name


class _Cl:
    def __init__(self, pods, err=""):
        self._p, self.last_error = pods, err

    def list_pods(self, namespace=None):
        return [dict(p) for p in self._p]


def test_all_clusters_pods_detail_with_namespace():
    from app.services.agent import tools as T
    pods = [{"namespace": "huawei-csi", "name": "p1", "status": "Running", "node_name": "master-0", "restart_count": 0}]
    fac = lambda c: _Cl(pods) if c.name == "real" else _Cl([], "dns")
    r = T._list_ocp_pods_all_clusters([_C("real"), _C("fake")], "huawei-csi", client_factory=fac)
    assert r["pods"] and r["pods"][0]["node_name"] == "master-0" and r["pods"][0]["_cluster"] == "real"
    assert r["unreachable_clusters"][0]["cluster"] == "fake" and r["list_complete"] is False


def test_all_clusters_pods_tsv_when_large_without_namespace():
    from app.services.agent import tools as T
    pods = [{"namespace": "n", "name": f"p{i}", "status": "Running", "node_name": "m", "restart_count": 0} for i in range(130)]
    r = T._list_ocp_pods_all_clusters([_C("real")], None, client_factory=lambda c: _Cl(pods))
    assert "pods" not in r and r["pods_listed"] == 130 and r["pods_tsv"].startswith("cluster\t")


def test_kubevirt_vms_aggregate_across_hypervisors(monkeypatch):
    from app.services.agent import tools as T

    class _H:
        def __init__(self, name):
            self.name = name

    class _K:
        def __init__(self, name):
            self.name = name

        def list_vms(self):
            if self.name == "bad":
                raise RuntimeError("dns")
            return [{"name": "vm1"}] * (5 if self.name == "real" else 0)

    monkeypatch.setattr(T, "_build_kubevirt_client", lambda hv: _K(hv.name))
    r = T._list_kubevirt_vms_all([_H("fake"), _H("real"), _H("bad")])
    assert r["count"] == 5 and r["scope"] == "all_hypervisors"
    assert r["unreachable_hypervisors"][0]["hypervisor"] == "bad"
    assert {p["hypervisor"]: p["count"] for p in r["per_hypervisor"]}["real"] == 5


def test_chart_source_label_hides_internal_table():
    from app.services.chat_charts import _summary_text
    txt = _summary_text(title="x", hours=6, charts=[], sources=["ocp_resource_metrics"], missing=[], notes=[], lead="")
    assert "ocp_resource_metrics" not in txt and "OpenShift" in txt
