"""OpenShift olay zaman çizelgesi: sır maskeleme ve deterministik aday sıralaması."""
from types import SimpleNamespace

from app.services.ocp_incident_timeline import _OBJ_RE, _candidates, _mask


def test_mask_hides_secrets_and_truncates():
    assert "hunter2" not in _mask("login failed password=hunter2 for user")
    assert "abc123" not in _mask("Authorization: Bearer abc123")
    assert len(_mask("x" * 1000)) == 300


def test_object_regex():
    m = _OBJ_RE.match("Pod/web-1")
    assert m and m.group(1) == "Pod" and m.group(2) == "web-1"
    assert _OBJ_RE.match("garbage") is None


def _live(**kw):
    base = {"pods": [], "events": [], "logs": [], "nodes": []}
    base.update(kw)
    return base


def test_oom_candidate_ranks_first():
    live = _live(pods=[{"containers": [{"name": "app", "restarts": 5, "waiting": "CrashLoopBackOff",
                                        "last_reason": "OOMKilled", "last_exit": 137}]}])
    c = _candidates(None, 1, [], live, [])
    assert c[0]["id"] == "oom" and c[0]["verify"]
    assert {x["id"] for x in c} >= {"oom", "app_crash"}


def test_no_evidence_no_candidates():
    assert _candidates(None, 1, [], _live(), []) == []


def test_node_and_operator_candidates_use_findings():
    fs = [SimpleNamespace(check_id="ocp.node.condition", result="fail", entity_name="w1", title="t",
                          evidence={"detail": "NotReady"}),
          SimpleNamespace(check_id="ocp.operator.health", result="fail", entity_name="etcd", title="t", evidence={})]
    c = _candidates(None, 1, [], _live(nodes=["w1"]), fs)
    assert [x["id"] for x in c] == ["node", "operator"]
    assert not _candidates(None, 1, [], _live(nodes=["other"]), fs[:1])
