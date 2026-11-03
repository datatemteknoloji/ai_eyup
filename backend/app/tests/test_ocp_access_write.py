"""OpenShift Access/RBAC — YALNIZ oluşturma (Admin), okuma sertleştirmeleri. Ağa ÇIKMAZ (sahte client)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.openshift import ocp_access as OA
from app.services.openshift import ocp_access_write as W


def _resp(status: int, body: dict | None = None, text: str = ""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    r.text = text
    return r


# ── doğrulama / manifest ─────────────────────────────────────────────────────

def test_build_rolebinding_manifest_has_labels_and_audit_annotations():
    m = W.build_manifest("RoleBinding", {
        "name": "dev-view", "namespace": "dev",
        "role_ref": {"kind": "ClusterRole", "name": "view"},
        "subjects": [{"kind": "User", "name": "alice"}, {"kind": "ServiceAccount", "name": "ci", "namespace": "dev"}],
        "description": "dev ekibi",
    }, actor="admin1")
    assert m["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "ainew"
    assert m["metadata"]["annotations"]["ainew.io/created-by"] == "admin1"
    assert m["metadata"]["annotations"]["ainew.io/description"] == "dev ekibi"
    assert m["roleRef"] == {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "view"}
    assert m["subjects"][0] == {"kind": "User", "name": "alice", "apiGroup": "rbac.authorization.k8s.io"}
    assert m["subjects"][1] == {"kind": "ServiceAccount", "name": "ci", "namespace": "dev"}  # SA: apiGroup yok


@pytest.mark.parametrize("kind,spec,msg", [
    ("RoleBinding", {"name": "x", "role_ref": {"kind": "Role", "name": "r"}, "subjects": [{"kind": "User", "name": "a"}]}, "namespace"),
    ("ClusterRoleBinding", {"name": "x", "role_ref": {"kind": "Role", "name": "r"}, "subjects": [{"kind": "User", "name": "a"}]}, "ClusterRole"),
    ("RoleBinding", {"name": "Büyük_Ad", "namespace": "d", "role_ref": {"kind": "Role", "name": "r"}, "subjects": [{"kind": "User", "name": "a"}]}, "geçersiz"),
    ("RoleBinding", {"name": "x", "namespace": "d", "role_ref": {"kind": "Role", "name": "r"}, "subjects": []}, "özne"),
    ("RoleBinding", {"name": "x", "namespace": "d", "role_ref": {"kind": "Role", "name": "r"}, "subjects": [{"kind": "ServiceAccount", "name": "s"}]}, "namespace"),
    ("Role", {"name": "x", "namespace": "d", "rules": []}, "kural"),
    ("Role", {"name": "x", "namespace": "d", "rules": [{"verbs": ["get"], "resources": ["pods"], "nonResourceURLs": ["/healthz"]}]}, "nonResourceURLs"),
    ("Role", {"name": "x", "namespace": "d", "rules": [{"verbs": ["frobnicate"], "resources": ["pods"]}]}, "bilinmeyen fiil"),
    ("Deployment", {"name": "x"}, "Desteklenmeyen"),
])
def test_validation_rejects(kind, spec, msg):
    with pytest.raises(W.AccessWriteError) as ei:
        W.build_manifest(kind, spec)
    assert msg.lower() in ei.value.message.lower()


def test_role_rules_default_core_group_and_clusterrole_nonresource():
    m = W.build_manifest("Role", {"name": "r", "namespace": "d", "rules": [{"verbs": ["get", "list"], "resources": ["pods"]}]})
    assert m["rules"][0]["apiGroups"] == [""]
    cm = W.build_manifest("ClusterRole", {"name": "r", "rules": [{"verbs": ["get"], "nonResourceURLs": ["/healthz"]}]})
    assert cm["rules"][0] == {"verbs": ["get"], "nonResourceURLs": ["/healthz"]}


def test_yaml_mode_strips_smuggled_metadata_and_rejects_foreign_kinds():
    text = """
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pod-reader
  labels: {evil: "1"}
  finalizers: [x]
  ownerReferences: [{name: a}]
rules:
- apiGroups: [""]
  resources: [pods]
  verbs: [get, list]
"""
    kind, spec, ignored = W.spec_from_yaml(text)
    assert kind == "ClusterRole" and spec["name"] == "pod-reader"
    assert any("labels" in w for w in ignored) and any("finalizers" in w for w in ignored)
    m = W.build_manifest(kind, spec)
    assert m["metadata"]["labels"] == {"app.kubernetes.io/managed-by": "ainew"}
    assert "finalizers" not in m["metadata"] and "ownerReferences" not in m["metadata"]
    with pytest.raises(W.AccessWriteError):
        W.spec_from_yaml("apiVersion: v1\nkind: Secret\nmetadata: {name: x}\n")
    with pytest.raises(W.AccessWriteError):
        W.spec_from_yaml("kind: Role\n---\nkind: Role\n")
    with pytest.raises(W.AccessWriteError) as ei:
        W.spec_from_yaml("kind: ClusterRole\nmetadata: {name: a}\naggregationRule: {clusterRoleSelectors: []}\n")
    assert "aggregationRule" in ei.value.message


# ── uyarılar ─────────────────────────────────────────────────────────────────

def _binding(role, kind="ClusterRoleBinding", subj=None):
    return W.build_manifest(kind, {
        "name": "b", "namespace": "d", "role_ref": {"kind": "ClusterRole", "name": role},
        "subjects": subj or [{"kind": "User", "name": "alice"}],
    })


def test_warnings_cluster_admin_and_broad_groups_are_critical():
    w = W.analyze_warnings(_binding("cluster-admin"))
    assert any(x["code"] == "cluster_admin_global" and x["level"] == "critical" for x in w)
    assert W.requires_name_confirmation(w)
    w2 = W.analyze_warnings(_binding("view", subj=[{"kind": "Group", "name": "system:authenticated"}]))
    assert any(x["code"] == "broad_group" for x in w2) and W.requires_name_confirmation(w2)
    w3 = W.analyze_warnings(_binding("view"))
    assert not W.requires_name_confirmation(w3)


def test_warnings_role_rules():
    m = W.build_manifest("ClusterRole", {"name": "r", "rules": [
        {"verbs": ["*"], "resources": ["*"], "apiGroups": ["*"]},
        {"verbs": ["get", "list"], "resources": ["secrets"]},
        {"verbs": ["escalate", "bind"], "resources": ["clusterroles"], "apiGroups": ["rbac.authorization.k8s.io"]},
        {"verbs": ["create"], "resources": ["pods/exec"]},
    ]})
    codes = {x["code"] for x in W.analyze_warnings(m)}
    assert {"wildcard_all", "secrets_read", "privilege_verbs", "pod_exec"} <= codes


def test_equivalent_delete_is_informational_text_only():
    m = _binding("view", kind="RoleBinding")
    assert W.equivalent_delete_command(m) == "oc delete rolebinding b -n d"
    assert W.equivalent_delete_command(W.build_manifest("ClusterRole", {"name": "r", "rules": [{"verbs": ["get"], "resources": ["pods"]}]})) == "oc delete clusterrole r"


# ── cluster'a gönderme ───────────────────────────────────────────────────────

class FakeCluster:
    """_post'u kaydeder; ad bazlı 409 / 403 simülasyonu."""

    def __init__(self, existing=(), forbid_escalation=False, can_create=True):
        self.posts = []
        self.existing = set(existing)
        self.forbid_escalation = forbid_escalation
        self.can_create = can_create

    def _post(self, path, body=None, timeout=None):
        self.posts.append((path, body))
        if "selfsubjectaccessreviews" in path:
            return _resp(201, {"status": {"allowed": self.can_create, "reason": "" if self.can_create else "no"}})
        name = body["metadata"]["name"]
        if name in self.existing:
            return _resp(409, {"message": "already exists"})
        if self.forbid_escalation:
            return _resp(403, {"message": "user is attempting to grant RBAC permissions not currently held"})
        return _resp(201, body)

    def _get(self, *a, **k):  # pragma: no cover - kullanılmaz
        return _resp(404)

    def _describe_http_error(self, r):
        return f"HTTP {r.status_code}"


FORM = dict(mode="form", kind="RoleBinding", spec={
    "name": "dev-view", "namespace": "dev",
    "role_ref": {"kind": "ClusterRole", "name": "view"},
    "subjects": [{"kind": "User", "name": "alice"}],
})


def test_preview_uses_dry_run_and_never_persists():
    c = FakeCluster()
    out = W.preview(c, **FORM)
    assert out["ok"] and out["dry_run"]["ok"]
    assert [p for p, _ in c.posts] == ["/apis/rbac.authorization.k8s.io/v1/namespaces/dev/rolebindings?dryRun=All"]
    assert "oc delete rolebinding dev-view -n dev" in out["equivalent_delete"]


def test_create_runs_dry_run_first_then_real_post_and_invalidates_cache():
    c = FakeCluster()
    OA._SNAP_CACHE["c1"] = (1e18, {"x": 1})
    out = W.create(c, cache_key="c1", **FORM)
    assert out["created"]
    paths = [p for p, _ in c.posts]
    assert paths == ["/apis/rbac.authorization.k8s.io/v1/namespaces/dev/rolebindings?dryRun=All",
                     "/apis/rbac.authorization.k8s.io/v1/namespaces/dev/rolebindings"]
    assert "c1" not in OA._SNAP_CACHE


def test_create_409_has_turkish_message_and_no_real_post():
    c = FakeCluster(existing={"dev-view"})
    with pytest.raises(W.AccessWriteError) as ei:
        W.create(c, **FORM)
    assert ei.value.status == 409 and "zaten var" in ei.value.message
    assert all("dryRun=All" in p for p, _ in c.posts)  # gerçek POST gitmedi


def test_create_escalation_403_is_explained():
    c = FakeCluster(forbid_escalation=True)
    with pytest.raises(W.AccessWriteError) as ei:
        W.create(c, **FORM)
    assert "yükseltme" in ei.value.message.lower()


def test_critical_requires_exact_name_confirmation():
    c = FakeCluster()
    kw = dict(mode="form", kind="ClusterRoleBinding", spec={
        "name": "ops-admin", "role_ref": {"kind": "ClusterRole", "name": "cluster-admin"},
        "subjects": [{"kind": "Group", "name": "ops"}],
    })
    with pytest.raises(W.AccessWriteError) as ei:
        W.create(c, **kw)
    assert ei.value.code == "confirm_required" and not c.posts
    with pytest.raises(W.AccessWriteError):
        W.create(c, confirm_name="yanlis", **kw)
    assert not c.posts
    assert W.create(c, confirm_name="ops-admin", **kw)["created"]


def test_copy_from_existing_role_prefills_rules():
    c = MagicMock()
    c._get.return_value = _resp(200, {
        "metadata": {"name": "view"},
        "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]},
                  {"nonResourceURLs": ["/healthz"], "verbs": ["get"]}],
    })
    prep = W.prepare(c, mode="form", kind="ClusterRole", spec={"name": "my-view"}, copy_from={"kind": "ClusterRole", "name": "view"})
    rules = prep["manifest"]["rules"]
    assert rules[0]["resources"] == ["pods"] and rules[1]["nonResourceURLs"] == ["/healthz"]
    prep2 = W.prepare(c, mode="form", kind="Role", spec={"name": "my-view", "namespace": "d"}, copy_from={"kind": "ClusterRole", "name": "view"})
    assert len(prep2["manifest"]["rules"]) == 1  # Role'da nonResourceURLs atıldı


def test_capabilities_per_kind():
    out = W.capabilities(FakeCluster(can_create=False))
    assert set(out) == set(W.KINDS) and not any(v["allowed"] for v in out.values()) and out["Role"]["reason"]
    assert all(v["allowed"] for v in W.capabilities(FakeCluster()).values())


def test_no_write_helpers_beyond_create():
    """Düzenleme/silme yüzeyi olmamalı: modül _delete/_patch/PUT çağırmaz."""
    import inspect
    src = inspect.getsource(W)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("#", '"', "'")))
    assert "client._delete" not in code and "client._patch" not in code and ".put(" not in code


# ── okuma sertleştirmeleri ───────────────────────────────────────────────────

def test_list_access_follows_continue_tokens():
    pages = [
        _resp(200, {"metadata": {"continue": "T1"}, "items": [{"metadata": {"name": f"u{i}"}} for i in range(3)]}),
        _resp(200, {"metadata": {}, "items": [{"metadata": {"name": f"u{i}"}} for i in range(3, 5)]}),
    ]
    c = MagicMock()
    c._get.side_effect = pages
    out = OA.list_access(c, "users", limit=100)
    assert out["count"] == 5 and out["total"] == 5 and not out["truncated"]
    assert c._get.call_args_list[1].kwargs["params"]["continue"] == "T1"


def test_get_access_hides_raw_unless_requested_and_yaml_drops_managed_fields():
    c = MagicMock()
    c._get.return_value = _resp(200, {"metadata": {"name": "r", "managedFields": [{"x": 1}]}, "rules": []})
    assert "raw" not in OA.get_access(c, "clusterroles", "r")
    out = OA.raw_yaml(c, "clusterroles", "r")
    assert out["ok"] and "managedFields" not in out["yaml"]


def test_permission_matrix_expands_wildcard_and_resource_names():
    m = OA.permission_matrix([
        {"verbs": ["*"], "api_groups": ["*"], "resources": ["*"], "resource_names": [], "non_resource_urls": []},
        {"verbs": ["get"], "api_groups": [""], "resources": ["configmaps"], "resource_names": ["cm1"], "non_resource_urls": []},
    ])
    assert m["full_access"] and m["wildcard_verbs"]
    star = next(r for r in m["rows"] if r["resource"] == "*")
    assert set(OA.STD_VERBS) <= set(star["verbs"]) and star["all_verbs"]
    cm = next(r for r in m["rows"] if r["resource"] == "configmaps")
    assert cm["restricted"] and cm["resource_names"] == ["cm1"]


def _snap():
    def role(name, rules, ns=""):
        return {"name": name, "namespace": ns, "kind": "ClusterRole" if not ns else "Role", "rules": rules,
                "rule_count": len(rules), "labels": {}}

    def b(kind, name, ref_kind, ref, subjects, ns=""):
        return {"kind": kind, "name": name, "namespace": ns, "role_ref": {"kind": ref_kind, "name": ref},
                "subjects": [{"kind": k, "name": n, "namespace": sns, "key": f"{k}:{n}"} for k, n, sns in subjects]}
    star = [{"verbs": ["*"], "api_groups": ["*"], "resources": ["*"], "resource_names": [], "non_resource_urls": []}]
    rd = [{"verbs": ["get", "list"], "api_groups": [""], "resources": ["pods"], "resource_names": [], "non_resource_urls": []}]
    return {
        "errors": {}, "truncated": {}, "fetched_at": 1,
        "users": [{"name": "alice"}, {"name": "bob"}],
        "groups": [{"name": "ops", "users": ["alice"]}],
        "serviceaccounts": [{"name": "ci", "namespace": "dev"}],
        "clusterroles": [role("cluster-admin", star), role("pod-reader", rd), role("custom-all", star)],
        "roles": [role("local", rd, "dev")],
        "clusterrolebindings": [
            b("ClusterRoleBinding", "ops-admin", "ClusterRole", "cluster-admin", [("Group", "ops", "")]),
            b("ClusterRoleBinding", "ghost", "ClusterRole", "cluster-admin", [("User", "ghost", "")]),
            b("ClusterRoleBinding", "broken", "ClusterRole", "nope", [("User", "bob", "")]),
            b("ClusterRoleBinding", "everyone", "ClusterRole", "cluster-admin", [("Group", "system:authenticated", "")]),
        ],
        "rolebindings": [
            b("RoleBinding", "dev-read", "ClusterRole", "pod-reader", [("User", "alice", ""), ("ServiceAccount", "gone", "dev")], "dev"),
            b("RoleBinding", "local-b", "Role", "local", [("ServiceAccount", "ci", "dev")], "dev"),
        ],
    }


def test_compute_risks():
    r = OA.compute_risks(_snap())
    holders = {(h["subject"]) for h in r["cluster_admin_holders"]}
    assert holders == {"ops", "ghost"}                       # system:authenticated holder listesinde değil
    assert next(h for h in r["cluster_admin_holders"] if h["subject"] == "ops")["member_count"] == 1
    assert [d["subject"] for d in r["broad_group_grants"]] == ["system:authenticated"]
    wild = {w["role"]: w for w in r["wildcard_roles"]}
    assert wild["cluster-admin"]["builtin"] and not wild["custom-all"]["builtin"]
    assert wild["custom-all"]["severity"] == "critical"
    types = {(o["type"], o["subject"] or o["role"]) for o in r["orphans"]}
    assert ("missing_role", "nope") in types
    assert ("missing_subject", "ghost") in types and ("missing_subject", "gone") in types
    assert r["summary"]["cluster_admin_holders"] == 2


def test_effective_permissions_includes_group_membership(monkeypatch):
    monkeypatch.setattr(OA, "load_snapshot", lambda client, cache_key=None, force=False: _snap())
    out = OA.effective_permissions(MagicMock(), subject_kind="User", subject_name="alice")
    assert "ops" in out["member_groups"]
    assert out["is_cluster_admin"]                           # ops grubu → cluster-admin
    vias = {(g["binding"], g["via"]) for g in out["grants"]}
    assert ("ops-admin", "group:ops") in vias and ("dev-read", "direct") in vias
    assert "dev" in out["namespace_matrices"]
    bob = OA.effective_permissions(MagicMock(), subject_kind="User", subject_name="bob")
    # «everyone» binding'i system:authenticated'a cluster-admin veriyor → her kullanıcı dolaylı admin
    assert bob["is_cluster_admin"] and "ClusterRole/nope" in bob["missing_roles"]
    assert any(g["via"] == "group:system:authenticated" and g["role"] == "cluster-admin" for g in bob["grants"])
    sa = OA.effective_permissions(MagicMock(), subject_kind="ServiceAccount", subject_name="ci", subject_namespace="dev")
    assert sa["grants"] and sa["grants"][0]["binding"] in {"local-b", "everyone"}


def test_snapshot_cache_and_invalidate(monkeypatch):
    calls = {"n": 0}

    def fake_list(client, kind, **kw):
        calls["n"] += 1
        return {"ok": True, "items": []}
    monkeypatch.setattr(OA, "list_access", fake_list)
    OA.invalidate_snapshot()
    OA.load_snapshot(MagicMock(), "k")
    n1 = calls["n"]
    OA.load_snapshot(MagicMock(), "k")
    assert calls["n"] == n1                                  # önbellekten
    OA.invalidate_snapshot("k")
    OA.load_snapshot(MagicMock(), "k")
    assert calls["n"] == 2 * n1


# ── API: rol kapısı ──────────────────────────────────────────────────────────

def _api(role, fake=None, monkeypatch=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import openshift as api
    from app.core.auth import get_current_user
    app = FastAPI()
    app.include_router(api.router, prefix="/openshift")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=role, id=1, username="u")
    fake = fake or FakeCluster()
    fake.logout = lambda: None
    monkeypatch.setattr(api, "_access_client", lambda cid, db: (SimpleNamespace(id=cid, name="c"), fake))
    monkeypatch.setattr(api, "record_audit", lambda *a, **k: AUDITS.append(k))
    from app.core.database import get_db
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app), fake


AUDITS: list = []
CREATE_BODY = {"mode": "form", "kind": "RoleBinding", "spec": FORM["spec"]}


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_write_endpoints_are_admin_only(role, monkeypatch):
    cl, fake = _api(role, monkeypatch=monkeypatch)
    assert cl.post("/openshift/clusters/1/access/create", json=CREATE_BODY).status_code == 403
    assert cl.post("/openshift/clusters/1/access/create/preview", json=CREATE_BODY).status_code == 403
    assert cl.get("/openshift/clusters/1/access/yaml", params={"kind": "clusterroles", "name": "x"}).status_code == 403
    assert cl.get("/openshift/clusters/1/access/identity-providers").status_code == 403
    assert not fake.posts


def test_capabilities_non_admin_makes_no_cluster_call(monkeypatch):
    cl, fake = _api("operator", monkeypatch=monkeypatch)
    j = cl.get("/openshift/clusters/1/access/capabilities").json()
    assert j["can_write"] is False and j["is_admin"] is False and j["reason"] and not fake.posts


def test_admin_create_audits_with_yaml_and_failure_is_audited(monkeypatch):
    AUDITS.clear()
    cl, fake = _api("admin", monkeypatch=monkeypatch)
    r = cl.post("/openshift/clusters/1/access/create", json=CREATE_BODY)
    assert r.status_code == 200 and r.json()["created"]
    ok = [a for a in AUDITS if a["status"] == "success"]
    assert ok and "kind: RoleBinding" in ok[0]["detail"]["yaml"] and ok[0]["action"] == "access.create"
    assert "managed-by" in ok[0]["detail"]["yaml"]
    # 409
    AUDITS.clear()
    cl2, _ = _api("admin", fake=FakeCluster(existing={"dev-view"}), monkeypatch=monkeypatch)
    r2 = cl2.post("/openshift/clusters/1/access/create", json=CREATE_BODY)
    assert r2.status_code == 409 and "zaten var" in r2.json()["detail"]
    assert AUDITS and AUDITS[0]["status"] == "failed"


def test_admin_create_rejects_unsupported_kind(monkeypatch):
    cl, fake = _api("admin", monkeypatch=monkeypatch)
    r = cl.post("/openshift/clusters/1/access/create", json={"mode": "form", "kind": "Secret", "spec": {"name": "x"}})
    assert r.status_code == 400 and not fake.posts


def test_no_delete_or_put_routes_under_access():
    from app.api import openshift as api
    for route in api.router.routes:
        path = getattr(route, "path", "")
        if "/access" in path:
            assert not ({"DELETE", "PUT", "PATCH"} & set(route.methods or [])), path
