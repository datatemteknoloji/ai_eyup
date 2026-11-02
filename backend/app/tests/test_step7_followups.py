"""Adım 7 sonrası: DB işlemi bırakma, error_state_count, v11 kapsamı, bayat node, bench truth kuralı."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.database import release_txn
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality import count_extra as cx
from app.services.chat_quality import ocp_pod_stats as ps
from app.services.chat_quality.count_scope import HV, Scope, ScopeCatalog

_BACKEND = Path(__file__).resolve().parents[2]  # .../backend (konteynerde /app, CI'da repo/backend)


def _src(rel: str) -> str:
    """Kaynak dosyayı çalışma dizininden bağımsız oku (CI'da cwd repo kökü)."""
    return (_BACKEND / rel).read_text(encoding="utf-8")


# ── release_txn ──────────────────────────────────────────────────────────────────

class _FakeDB:
    def __init__(self, in_tx=True, boom=False):
        self.in_tx, self.boom, self.commits, self.rollbacks = in_tx, boom, 0, 0

    def in_transaction(self):
        return self.in_tx

    def commit(self):
        if self.boom:
            raise RuntimeError("x")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_release_txn_commits_open_transaction():
    db = _FakeDB()
    assert release_txn(db) is True and db.commits == 1


def test_release_txn_noop_without_transaction_or_db():
    db = _FakeDB(in_tx=False)
    assert release_txn(db) is False and db.commits == 0
    assert release_txn(None) is False


def test_release_txn_swallows_errors_and_rolls_back():
    db = _FakeDB(boom=True)
    assert release_txn(db) is False and db.rollbacks == 1


@pytest.mark.parametrize("path", ["app/api/unified_chat.py", "app/api/chat.py", "app/api/windows_chat.py"])
def test_chat_pipelines_release_txn_before_llm_stream(path):
    src = _src(path)
    i = src.index("release_txn(db)")
    assert 'yield _sse({"phase": "answering"})' in src[i:i + 400]


def test_run_turn_releases_txn_in_loop():
    src = _src("app/services/chat_orchestrator/service.py")
    assert "release_txn(db)" in src and "_last_release" in src


def test_engines_have_application_names():
    from app.core import database
    assert database.engine.dialect.name == "postgresql"
    src = _src("app/core/database.py")
    assert "ainew-api" in src and "ainew-thread" in src


# ── error_state_count ───────────────────────────────────────────────────────────

PODS = (
    [{"status": "Error", "reason": "", "restart_count": 0}] * 10
    + [{"status": "Running", "reason": "CrashLoopBackOff", "restart_count": 9}] * 2
    + [{"status": "Pending", "reason": "RunContainerError", "restart_count": 0}] * 1
    + [{"status": "Running", "reason": "", "restart_count": 7}] * 92       # restart ≥5: problem ama error_state DEĞİL
    + [{"status": "Pending", "reason": "", "restart_count": 0}] * 2
    + [{"status": "Running", "reason": "", "restart_count": 0}] * 50
)


def test_error_state_count_is_narrow():
    s = ps.summarize(PODS)
    assert s["error_state_count"] == 13
    assert s["error_state_breakdown"] == {"Error": 10, "CrashLoopBackOff": 2, "RunContainerError": 1}
    assert s["problem_count"] == 10 + 2 + 1 + 92 + 2     # geniş tanım ayrı kalır
    assert "error_state_count" in s["error_state_definition"] and "problem_count" in s["error_state_definition"]


@pytest.mark.parametrize("st,rs,want", [
    ("Error", "", "Error"), ("Running", "CrashLoopBackOff", "CrashLoopBackOff"),
    ("crashloopbackoff", "", "CrashLoopBackOff"), ("Pending", "RunContainerError", "RunContainerError"),
    ("Running", "", None), ("Pending", "", None), ("Succeeded", "Completed", None), ("ImagePullBackOff", "", None),
])
def test_error_state_of(st, rs, want):
    assert ps.error_state_of(st, rs) == want


class _Cl:
    def __init__(self, pods, err=""):
        self.pods, self.last_error = pods, err

    def list_pods(self, namespace=None):
        return [dict(p) for p in self.pods]


def test_all_clusters_tool_exposes_error_state_count():
    from app.services.agent import tools
    cls = [SimpleNamespace(name="oVirt"), SimpleNamespace(name="B")]
    data = {"oVirt": PODS, "B": [{"status": "Error", "reason": "", "restart_count": 0}] * 4}
    res = tools._list_ocp_pods_all_clusters(cls, None, client_factory=lambda c: _Cl(data[c.name]))
    assert res["error_state_count"] == 17
    per = {p["cluster"]: p for p in res["per_cluster"]}
    assert per["oVirt"]["error_state_count"] == 13 and per["B"]["error_state_count"] == 4
    assert res["problem_count"] > res["error_state_count"]


def test_tool_description_points_to_error_state_count():
    from app.services.agent import tools
    assert "error_state_count" in tools.TOOLS["list_ocp_pods"].description


def test_error_state_n_helper():
    from app.services.agent import tools
    assert tools._error_state_n(PODS) == 13


def test_error_state_fields_flagged_as_internal_terms():
    from app.services.chat_quality import grounding
    r = grounding.verify("oVirt için `error_state_count` değeri 13.", user_message="hatalı pod sayısı?",
                         tools=[("list_ocp_pods", {}, {"ok": True, "count": 3})], paths=[], platform="unified")
    assert [f for f in r["findings"] if f["class"] == "internal_term" and f["text"] == "error_state_count"]


# ── v11: kapalı VM listesi kapsamı ──────────────────────────────────────────────

def _cat():
    return ScopeCatalog(hypervisors=[HV(1, "office", "VMWARE"), HV(2, "Datatem OLVM", "KVM")], ok=True)


@pytest.fixture
def cat_override():
    old = cr._cat_override
    cr._cat_override = _cat()
    yield
    cr._cat_override = old


def _vms():
    out = []
    for i in range(19):
        out.append({"name": f"o-{i}", "hypervisor_id": 1, "power_state": "poweredOff", "datastore": "ds", "memory_gb": 1, "cluster": ""})
    for i in range(14):
        out.append({"name": f"on-{i}", "hypervisor_id": 1, "power_state": "poweredOn", "datastore": "ds", "memory_gb": 1, "cluster": ""})
    for i in range(10):
        out.append({"name": f"k-{i}", "hypervisor_id": 2, "power_state": "poweredOff", "datastore": "ds", "memory_gb": 1, "cluster": ""})
    return out


def test_powered_off_list_scoped_to_hypervisor(monkeypatch, cat_override):
    from app.services import hypervisor_intelligence as hi
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: _vms())
    t = hi.h_powered_off_count(None, "office vCenter'daki kapalı VM'leri listele")
    assert "**19** VM kapalı" in t and "toplam 33" in t and "Kapsam: office" in t
    assert "o-0" in t and "k-0" not in t


def test_powered_off_list_unscoped_keeps_fleet(monkeypatch, cat_override):
    from app.services import hypervisor_intelligence as hi
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: _vms())
    t = hi.h_powered_off_count(None, "kapalı VM'leri listele")
    assert "**29** VM kapalı" in t and "Kapsam:" not in t and "İlk 30" not in t


def test_powered_off_list_caps_with_note(monkeypatch, cat_override):
    from app.services import hypervisor_intelligence as hi
    many = [{"name": f"v{i}", "hypervisor_id": 2, "power_state": "poweredOff", "datastore": "d", "memory_gb": 1, "cluster": ""} for i in range(45)]
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: many)
    t = hi.h_powered_off_count(None, "Datatem OLVM'de kapalı VM'leri listele")
    assert "**45** VM" in t and "İlk 30 VM gösteriliyor (45 kapalı VM var)" in t


# ── bayat node ───────────────────────────────────────────────────────────────────

def _ocp_cat():
    return ScopeCatalog(ocp_clusters=[(1, "oVirt"), (2, "ZZ-FAKE-OCP")], ok=True)


def _plan():
    return cr.Plan(kind="count", topic="node", domain="ocp")


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
SYNCS = {1: NOW - timedelta(minutes=2), 2: NOW - timedelta(days=3)}


def test_split_ocp_fresh_uses_pod_threshold(monkeypatch):
    monkeypatch.setattr(cx, "fetch_cluster_syncs", lambda db: SYNCS)
    monkeypatch.setattr(cx, "_now", lambda: NOW)
    monkeypatch.setattr(cx, "ocp_stale_threshold_sec", lambda: 1800)
    fresh, stale, _, thr = cr.split_ocp_fresh(None, {1: 3, 2: 15})
    assert fresh == {1: 3} and stale == [2] and thr == 1800


def test_node_total_excludes_stale_cluster_and_notes_it():
    cat = _ocp_cat()
    txt = cr.render_ocp_nodes(_plan(), cat, {1: 3, 2: 15}, "Toplam node", "Node", NOW, {1: 3}, [2], SYNCS, 1800)
    assert txt.startswith("**Toplam node: 3**")
    assert "Güncel olmayan cluster (toplama katılmadı; sonuç bilinmiyor)" in txt
    assert "ZZ-FAKE-OCP" in txt and "eski kayıt 15 node" in txt and "30 dk'dan eski" in txt


def test_node_all_stale_is_unknown():
    cat = _ocp_cat()
    txt = cr.render_ocp_nodes(_plan(), cat, {2: 15}, "Toplam node", "Node", NOW, {}, [2], SYNCS, 1800)
    assert "güncel sayı bilinmiyor" in txt and "eski kayıt 15 node" in txt


def test_node_all_fresh_unchanged():
    cat = _ocp_cat()
    a = cr.render_ocp_nodes(_plan(), cat, {1: 3}, "Toplam node", "Node", NOW, {1: 3}, [], SYNCS, 1800)
    b = cr.render_ocp(_plan(), cat, {1: 3}, "Toplam node", "Node", NOW)
    assert a == b


def test_compare_nodes_drops_stale(monkeypatch):
    monkeypatch.setattr(cx, "fetch_cluster_syncs", lambda db: SYNCS)
    monkeypatch.setattr(cx, "_now", lambda: NOW)
    monkeypatch.setattr(cx, "ocp_stale_threshold_sec", lambda: 1800)
    monkeypatch.setattr(cr, "fetch_ocp_counts", lambda db, table, scope, cat: {1: 3, 2: 15})
    monkeypatch.setattr(cr, "fetch_ocp_last_sync", lambda db, ids: NOW)
    plan = cr.Plan(kind="compare", topic="node", domain="ocp", by="hypervisor")
    txt = cr.answer(plan, _ocp_cat(), None)
    assert "En çok node: oVirt — 3" in txt and "Güncel olmayan cluster" in txt and "eski kayıt 15 node" in txt


def test_count_nodes_answer_path(monkeypatch):
    monkeypatch.setattr(cx, "fetch_cluster_syncs", lambda db: SYNCS)
    monkeypatch.setattr(cx, "_now", lambda: NOW)
    monkeypatch.setattr(cx, "ocp_stale_threshold_sec", lambda: 1800)
    monkeypatch.setattr(cr, "fetch_ocp_counts", lambda db, table, scope, cat: {1: 3, 2: 15})
    monkeypatch.setattr(cr, "fetch_ocp_last_sync", lambda db, ids: NOW)
    txt = cr.answer(_plan(), _ocp_cat(), None)
    assert "**Toplam node: 3**" in txt and "ZZ-FAKE-OCP" in txt


@pytest.mark.parametrize("path", ["app/api/unified_chat.py", "app/api/chat.py",
                                  "app/api/windows_chat.py", "app/api/hypervisors.py"])
def test_request_session_released_after_attach_and_stream(path):
    src = _src(path)
    # Adım 11: çağrı event döngüsünü bloklamamak için `_stream_resp = await attach_and_stream_async(...)`
    i = src.index("_stream_resp = await attach_and_stream_async(") if "_stream_resp = await attach_and_stream_async(" in src else src.index("_stream_resp = attach_and_stream(")
    j = src.index("return _stream_resp", i)
    assert "release_txn(db, keep_loaded=True)" in src[i:j]


def test_sse_endpoints_release_request_session():
    for path, marker in (("app/api/chat_turns.py", "async def turn_events"),
                         ("app/api/platform_status.py", "async def platform_container_logs_stream")):
        src = _src(path)
        body = src[src.index(marker):]
        assert "release_txn(db, keep_loaded=True)" in body[:1500]


def test_llm_gateway_release_hook_runs_before_call_and_unbinds():
    from app.services import llm_gateway as gw
    calls = []
    tok = gw.bind_release_hook(lambda: calls.append(1))
    gw._before_llm_call()
    gw.unbind_release_hook(tok)
    gw._before_llm_call()
    assert calls == [1]


def test_llm_gateway_entrypoints_call_hook_and_hook_errors_are_swallowed():
    from app.services import llm_gateway as gw
    src = _src("app/services/llm_gateway.py")
    assert src.count("    _before_llm_call()\n") == 5
    tok = gw.bind_release_hook(lambda: 1 / 0)
    try:
        gw._before_llm_call()
    finally:
        gw.unbind_release_hook(tok)


def test_release_txn_keep_loaded_disables_expire_on_commit():
    db = _FakeDB(in_tx=True)
    db.expire_on_commit = True
    assert release_txn(db, keep_loaded=True) is True
    assert db.expire_on_commit is False
