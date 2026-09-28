"""
OpenShift Access / RBAC — Users, Groups, Roles, Bindings (READ-ONLY).

API yolları:
  user.openshift.io/v1 — users, groups, identities
  rbac.authorization.k8s.io/v1 — roles, clusterroles, rolebindings, clusterrolebindings
  authorization.k8s.io/v1 — SelfSubjectAccessReview
  config.openshift.io/v1 — OAuth identity providers (opsiyonel)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.openshift.ocp_client import OpenShiftClient

logger = logging.getLogger(__name__)

USER_API = "/apis/user.openshift.io/v1"
RBAC_API = "/apis/rbac.authorization.k8s.io/v1"
AUTHZ_API = "/apis/authorization.k8s.io/v1"
CONFIG_API = "/apis/config.openshift.io/v1"

KIND_PATHS = {
    "users": (f"{USER_API}/users", False),
    "groups": (f"{USER_API}/groups", False),
    "identities": (f"{USER_API}/identities", False),
    "clusterroles": (f"{RBAC_API}/clusterroles", False),
    "clusterrolebindings": (f"{RBAC_API}/clusterrolebindings", False),
    "roles": (f"{RBAC_API}/roles", True),  # namespaced list-all via /roles
    "rolebindings": (f"{RBAC_API}/rolebindings", True),
    "serviceaccounts": ("/api/v1/serviceaccounts", True),
}


def _get(
    client: OpenShiftClient,
    path: str,
    params: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> Tuple[Optional[Dict], Optional[str]]:
    """(body, error). 403/404 → error metni."""
    try:
        r = client._get(path, params=params, timeout=timeout or 30)
        if r.status_code == 200:
            return (r.json() or {}), None
        if r.status_code == 403:
            return None, f"403 — bu kaynak için yetki yok ({path})"
        if r.status_code == 404:
            return None, f"404 — kaynak yok veya API kurulu değil ({path})"
        return None, client._describe_http_error(r)
    except Exception as e:
        return None, str(e)


def _items(body: Optional[Dict]) -> List[Dict]:
    if not body:
        return []
    return list(body.get("items") or [])


def _meta(obj: Dict) -> Dict[str, Any]:
    md = obj.get("metadata") or {}
    return {
        "name": md.get("name") or "",
        "namespace": md.get("namespace") or "",
        "uid": md.get("uid") or "",
        "created": md.get("creationTimestamp") or "",
        "labels": md.get("labels") or {},
        "annotations": md.get("annotations") or {},
    }


def _summarize_user(obj: Dict) -> Dict[str, Any]:
    m = _meta(obj)
    return {
        **m,
        "kind": "User",
        "full_name": obj.get("fullName") or "",
        "identities": list(obj.get("identities") or []),
        "groups": list(obj.get("groups") or []),  # often empty; membership on Group
    }


def _summarize_group(obj: Dict) -> Dict[str, Any]:
    m = _meta(obj)
    users = list(obj.get("users") or [])
    return {
        **m,
        "kind": "Group",
        "users": users,
        "user_count": len(users),
    }


def _summarize_identity(obj: Dict) -> Dict[str, Any]:
    m = _meta(obj)
    user = obj.get("user") or {}
    return {
        **m,
        "kind": "Identity",
        "provider_name": obj.get("providerName") or "",
        "provider_user_name": obj.get("providerUserName") or "",
        "user_name": user.get("name") or "",
        "user_uid": user.get("uid") or "",
    }


def _rule_summary(rules: Sequence[Dict]) -> List[Dict[str, Any]]:
    out = []
    for rule in rules or []:
        out.append({
            "verbs": list(rule.get("verbs") or []),
            "api_groups": list(rule.get("apiGroups") or []),
            "resources": list(rule.get("resources") or []),
            "resource_names": list(rule.get("resourceNames") or []),
            "non_resource_urls": list(rule.get("nonResourceURLs") or []),
        })
    return out


def _summarize_role(obj: Dict, *, cluster: bool) -> Dict[str, Any]:
    m = _meta(obj)
    rules = _rule_summary(obj.get("rules") or [])
    return {
        **m,
        "kind": "ClusterRole" if cluster else "Role",
        "rule_count": len(rules),
        "rules": rules,
        "aggregation": (obj.get("aggregationRule") or None),
    }


def _subject_key(s: Dict) -> str:
    kind = (s.get("kind") or "").lower()
    ns = s.get("namespace") or ""
    name = s.get("name") or ""
    if kind == "serviceaccount" and ns:
        return f"sa:{ns}/{name}"
    if kind == "group":
        return f"group:{name}"
    if kind == "user":
        return f"user:{name}"
    return f"{kind}:{ns}/{name}".strip(":")


def _summarize_binding(obj: Dict, *, cluster: bool) -> Dict[str, Any]:
    m = _meta(obj)
    role_ref = obj.get("roleRef") or {}
    subjects = []
    for s in obj.get("subjects") or []:
        subjects.append({
            "kind": s.get("kind") or "",
            "name": s.get("name") or "",
            "namespace": s.get("namespace") or "",
            "api_group": s.get("apiGroup") or "",
            "key": _subject_key(s),
        })
    return {
        **m,
        "kind": "ClusterRoleBinding" if cluster else "RoleBinding",
        "role_ref": {
            "kind": role_ref.get("kind") or "",
            "name": role_ref.get("name") or "",
            "api_group": role_ref.get("apiGroup") or "",
        },
        "subjects": subjects,
        "subject_count": len(subjects),
    }


def _summarize_sa(obj: Dict) -> Dict[str, Any]:
    m = _meta(obj)
    secrets = obj.get("secrets") or []
    return {
        **m,
        "kind": "ServiceAccount",
        "secret_count": len(secrets),
        "automount": obj.get("automountServiceAccountToken"),
    }


_SUMMARIZERS = {
    "users": lambda o: _summarize_user(o),
    "groups": lambda o: _summarize_group(o),
    "identities": lambda o: _summarize_identity(o),
    "roles": lambda o: _summarize_role(o, cluster=False),
    "clusterroles": lambda o: _summarize_role(o, cluster=True),
    "rolebindings": lambda o: _summarize_binding(o, cluster=False),
    "clusterrolebindings": lambda o: _summarize_binding(o, cluster=True),
    "serviceaccounts": lambda o: _summarize_sa(o),
}


def list_access(
    client: OpenShiftClient,
    kind: str,
    *,
    namespace: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """kind: users|groups|identities|roles|clusterroles|rolebindings|clusterrolebindings|serviceaccounts"""
    kind = (kind or "").strip().lower()
    if kind not in KIND_PATHS:
        return {"ok": False, "items": [], "error": f"Geçersiz kind: {kind}"}
    base, namespaced = KIND_PATHS[kind]
    path = base
    if namespaced and namespace:
        if kind == "serviceaccounts":
            path = f"/api/v1/namespaces/{namespace}/serviceaccounts"
        else:
            path = f"{RBAC_API}/namespaces/{namespace}/{kind}"
    body, err = _get(client, path, params={"limit": min(max(limit, 1), 2000)})
    if err:
        return {"ok": False, "items": [], "error": err, "kind": kind, "namespace": namespace or ""}
    summarizer = _SUMMARIZERS[kind]
    items = [summarizer(o) for o in _items(body)]
    needle = (q or "").strip().lower()
    if needle:
        def _match(it: Dict) -> bool:
            blob = " ".join(
                str(it.get(k) or "")
                for k in ("name", "namespace", "full_name", "provider_name", "user_name")
            ).lower()
            if needle in blob:
                return True
            for s in it.get("subjects") or []:
                if needle in (s.get("name") or "").lower() or needle in (s.get("key") or "").lower():
                    return True
            for u in it.get("users") or []:
                if needle in str(u).lower():
                    return True
            role = (it.get("role_ref") or {}).get("name") or ""
            if needle in role.lower():
                return True
            return False
        items = [it for it in items if _match(it)]
    # Stable sort
    items.sort(key=lambda x: (x.get("namespace") or "", x.get("name") or ""))
    truncated = False
    if len(items) > limit:
        items = items[:limit]
        truncated = True
    return {
        "ok": True,
        "kind": kind,
        "namespace": namespace or "",
        "items": items,
        "count": len(items),
        "truncated": truncated,
    }


def get_access(
    client: OpenShiftClient,
    kind: str,
    name: str,
    *,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    kind = (kind or "").strip().lower()
    name = (name or "").strip()
    if kind not in KIND_PATHS or not name:
        return {"ok": False, "error": "kind ve name zorunlu"}
    base, namespaced = KIND_PATHS[kind]
    if namespaced:
        if not namespace:
            return {"ok": False, "error": f"{kind} için namespace zorunlu"}
        if kind == "serviceaccounts":
            path = f"/api/v1/namespaces/{namespace}/serviceaccounts/{name}"
        else:
            path = f"{RBAC_API}/namespaces/{namespace}/{kind}/{name}"
    else:
        path = f"{base}/{name}"
    body, err = _get(client, path)
    if err or not body:
        return {"ok": False, "error": err or "bulunamadı", "kind": kind, "name": name}
    summary = _SUMMARIZERS[kind](body)
    return {
        "ok": True,
        "kind": kind,
        "item": summary,
        "raw": body,
    }


def subject_bindings(
    client: OpenShiftClient,
    *,
    subject_kind: str,
    subject_name: str,
    subject_namespace: Optional[str] = None,
    namespace: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """User/Group/ServiceAccount için RoleBinding + ClusterRoleBinding eşleşmeleri."""
    sk = (subject_kind or "User").strip()
    sn = (subject_name or "").strip()
    if not sn:
        return {"ok": False, "error": "subject_name zorunlu", "bindings": []}
    target_key = _subject_key({
        "kind": sk,
        "name": sn,
        "namespace": subject_namespace or "",
    })
    # Also match bare name for User/Group
    alt_keys = {target_key, f"{sk.lower()}:{sn}"}

    crb = list_access(client, "clusterrolebindings", limit=2000)
    rb = list_access(client, "rolebindings", namespace=namespace, limit=2000)
    errors = []
    if not crb.get("ok"):
        errors.append(f"clusterrolebindings: {crb.get('error')}")
    if not rb.get("ok"):
        errors.append(f"rolebindings: {rb.get('error')}")

    hits = []
    for item in (crb.get("items") or []) + (rb.get("items") or []):
        for s in item.get("subjects") or []:
            key = s.get("key") or ""
            name_ok = (s.get("name") or "").lower() == sn.lower()
            kind_ok = (s.get("kind") or "").lower() == sk.lower()
            ns_ok = True
            if sk.lower() == "serviceaccount" and subject_namespace:
                ns_ok = (s.get("namespace") or "") == subject_namespace
            if key in alt_keys or (name_ok and kind_ok and ns_ok):
                hits.append(item)
                break

    hits.sort(key=lambda x: (x.get("kind") or "", x.get("namespace") or "", x.get("name") or ""))
    return {
        "ok": True,
        "subject": {
            "kind": sk,
            "name": sn,
            "namespace": subject_namespace or "",
            "key": target_key,
        },
        "bindings": hits[:limit],
        "count": min(len(hits), limit),
        "total": len(hits),
        "truncated": len(hits) > limit,
        "errors": errors,
    }


def group_members(client: OpenShiftClient, name: str) -> Dict[str, Any]:
    detail = get_access(client, "groups", name)
    if not detail.get("ok"):
        return detail
    item = detail["item"]
    return {
        "ok": True,
        "group": item.get("name"),
        "users": item.get("users") or [],
        "user_count": item.get("user_count") or 0,
        "item": item,
    }


def self_can_i(
    client: OpenShiftClient,
    *,
    verb: str,
    resource: str,
    api_group: str = "",
    namespace: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """SelfSubjectAccessReview — kayıtlı token ne yapabilir?"""
    body = {
        "apiVersion": "authorization.k8s.io/v1",
        "kind": "SelfSubjectAccessReview",
        "spec": {
            "resourceAttributes": {
                "verb": verb,
                "resource": resource,
                "group": api_group or "",
            }
        },
    }
    ra = body["spec"]["resourceAttributes"]
    if namespace:
        ra["namespace"] = namespace
    if name:
        ra["name"] = name
    try:
        r = client._post(f"{AUTHZ_API}/selfsubjectaccessreviews", body=body, timeout=15)
        if r.status_code not in (200, 201):
            return {"ok": False, "allowed": False, "error": client._describe_http_error(r)}
        data = r.json() or {}
        status = data.get("status") or {}
        return {
            "ok": True,
            "allowed": bool(status.get("allowed")),
            "denied": bool(status.get("denied")),
            "reason": status.get("reason") or "",
            "evaluation_error": status.get("evaluationError") or "",
            "request": ra,
        }
    except Exception as e:
        return {"ok": False, "allowed": False, "error": str(e)}


def identity_providers(client: OpenShiftClient) -> Dict[str, Any]:
    """OAuth cluster config — identity providers (okuma)."""
    body, err = _get(client, f"{CONFIG_API}/oauths/cluster")
    if err or not body:
        return {"ok": False, "providers": [], "error": err or "OAuth config okunamadı"}
    spec = body.get("spec") or {}
    providers = []
    for p in spec.get("identityProviders") or []:
        providers.append({
            "name": p.get("name") or "",
            "type": p.get("type") or "",
            "mapping_method": p.get("mappingMethod") or "",
            "challenge": p.get("challenge"),
            "login": p.get("login"),
        })
    return {
        "ok": True,
        "providers": providers,
        "count": len(providers),
        "token_config": spec.get("tokenConfig") or {},
    }


def access_overview(client: OpenShiftClient) -> Dict[str, Any]:
    """KPI sayıları + OAuth providers + yetki teşhisi."""
    counts: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for kind in ("users", "groups", "clusterroles", "clusterrolebindings", "identities"):
        out = list_access(client, kind, limit=5000)
        if out.get("ok"):
            counts[kind] = out.get("count") or 0
        else:
            counts[kind] = None
            errors[kind] = out.get("error") or "hata"
    # Namespaced aggregates (tüm NS) — pahalı olabilir; limit ile
    for kind in ("roles", "rolebindings", "serviceaccounts"):
        out = list_access(client, kind, limit=5000)
        if out.get("ok"):
            counts[kind] = out.get("count") or 0
        else:
            counts[kind] = None
            errors[kind] = out.get("error") or "hata"

    idp = identity_providers(client)
    can_list_users = self_can_i(client, verb="list", resource="users", api_group="user.openshift.io")
    can_list_crb = self_can_i(client, verb="list", resource="clusterrolebindings", api_group="rbac.authorization.k8s.io")

    return {
        "ok": True,
        "counts": counts,
        "errors": errors,
        "identity_providers": idp.get("providers") if idp.get("ok") else [],
        "identity_providers_error": None if idp.get("ok") else idp.get("error"),
        "token_can": {
            "list_users": can_list_users.get("allowed"),
            "list_clusterrolebindings": can_list_crb.get("allowed"),
        },
        "footnote": (
            "READ-ONLY görünüm. Kullanıcı/group/role/binding oluşturma-silme "
            "bu sürümde yok — oc veya konsol kullanın."
        ),
    }


def run_access_query(
    client: OpenShiftClient,
    *,
    mode: str = "overview",
    kind: Optional[str] = None,
    name: Optional[str] = None,
    namespace: Optional[str] = None,
    q: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_name: Optional[str] = None,
    subject_namespace: Optional[str] = None,
    verb: Optional[str] = None,
    resource: Optional[str] = None,
    api_group: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Chat / API birleşik giriş."""
    mode = (mode or "overview").strip().lower()
    if mode == "overview":
        return access_overview(client)
    if mode == "list":
        return list_access(client, kind or "users", namespace=namespace, q=q, limit=limit)
    if mode == "get":
        return get_access(client, kind or "users", name or "", namespace=namespace)
    if mode in ("subject", "who", "bindings_for"):
        return subject_bindings(
            client,
            subject_kind=subject_kind or "User",
            subject_name=subject_name or name or "",
            subject_namespace=subject_namespace,
            namespace=namespace,
            limit=limit,
        )
    if mode in ("group_members", "members"):
        return group_members(client, name or subject_name or "")
    if mode in ("can_i", "self_can_i"):
        return self_can_i(
            client,
            verb=verb or "get",
            resource=resource or "pods",
            api_group=api_group or "",
            namespace=namespace,
            name=name,
        )
    if mode in ("identity_providers", "oauth", "idp"):
        return identity_providers(client)
    return {
        "ok": False,
        "error": (
            "mode: overview|list|get|subject|group_members|can_i|identity_providers"
        ),
    }
