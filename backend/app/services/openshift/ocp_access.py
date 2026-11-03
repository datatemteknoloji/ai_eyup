"""
OpenShift Access / RBAC — Users, Groups, Roles, Bindings.

OKUMA: bu modül (liste/detay/etkin yetki/risk/izin matrisi) — openshift modül yetkilileri.
YAZMA: `ocp_access_write.py` (YALNIZ oluşturma; düzenleme/silme/kullanıcı yönetimi yok; Admin).
Sohbet aracı `ocp_access_query` yalnız bu modülü kullanır → READ-ONLY kalır.

API yolları:
  user.openshift.io/v1 — users, groups, identities
  rbac.authorization.k8s.io/v1 — roles, clusterroles, rolebindings, clusterrolebindings
  authorization.k8s.io/v1 — SelfSubjectAccessReview
  config.openshift.io/v1 — OAuth identity providers (opsiyonel)
"""
from __future__ import annotations

import logging
import threading
import time
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


_PAGE = 500
_MAX_ITEMS = 20000


def _get_all(
    client: OpenShiftClient,
    path: str,
    *,
    cap: int = _MAX_ITEMS,
    page: int = _PAGE,
) -> Tuple[List[Dict], Optional[str], bool]:
    """Kubernetes `continue` token ile tüm sayfaları oku → (items, error, truncated).

    İlk sayfa hatası → ([], error, False). Sonraki sayfa hatası → kısmi liste + truncated=True.
    """
    items: List[Dict] = []
    token = ""
    truncated = False
    for page_no in range(1000):
        params: Dict[str, Any] = {"limit": page}
        if token:
            params["continue"] = token
        body, err = _get(client, path, params=params)
        if err:
            if page_no == 0:
                return [], err, False
            return items, err, True
        items.extend(_items(body))
        token = ((body or {}).get("metadata") or {}).get("continue") or ""
        if len(items) >= cap:
            truncated = bool(token) or len(items) > cap
            items = items[:cap]
            break
        if not token:
            break
    return items, None, truncated


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
    raw_items, err, source_truncated = _get_all(client, path)
    if err and not raw_items:
        return {"ok": False, "items": [], "error": err, "kind": kind, "namespace": namespace or ""}
    summarizer = _SUMMARIZERS[kind]
    items = [summarizer(o) for o in raw_items]
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
    total = len(items)
    truncated = source_truncated
    if len(items) > limit:
        items = items[:limit]
        truncated = True
    return {
        "ok": True,
        "kind": kind,
        "namespace": namespace or "",
        "items": items,
        "count": len(items),
        "total": total,
        "truncated": truncated,
        **({"partial_error": err} if err else {}),
    }


def get_access(
    client: OpenShiftClient,
    kind: str,
    name: str,
    *,
    namespace: Optional[str] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    """Tek nesne özeti. `raw` (ham nesne) yalnız include_raw=True (API: Admin) — sohbet aracı vermez."""
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
    out: Dict[str, Any] = {"ok": True, "kind": kind, "item": summary}
    if include_raw:
        out["raw"] = _clean_raw(body)
    return out


def _clean_raw(obj: Dict) -> Dict:
    """YAML görünümü için gürültüyü (managedFields) at; sır değeri taşıyan alan zaten yok."""
    out = dict(obj or {})
    md = dict(out.get("metadata") or {})
    md.pop("managedFields", None)
    out["metadata"] = md
    return out


def raw_yaml(client: OpenShiftClient, kind: str, name: str, *, namespace: Optional[str] = None) -> Dict[str, Any]:
    """Nesnenin YAML metni (Admin). Secret/SA token değeri içermez (yalnız RBAC/kimlik nesneleri)."""
    import yaml as _yaml
    res = get_access(client, kind, name, namespace=namespace, include_raw=True)
    if not res.get("ok"):
        return res
    raw = res["raw"]
    if (kind or "").lower() == "serviceaccounts":
        # Token Secret'larına yalnız ad ile referans var; yine de gizli alanları at.
        raw = {k: v for k, v in raw.items() if k not in ("secrets", "imagePullSecrets")}
    return {"ok": True, "kind": res["kind"], "yaml": _yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)}


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


# ── Anlık görüntü (snapshot) + kısa ömürlü önbellek ──────────────────────────
# Overview / risk / etkin yetki aynı 7 listeyi kullanır; her istekte yeniden çekmek
# yüzlerce HTTP çağrısı demek. 60 sn önbellek + oluşturma sonrası geçersiz kılma.

SNAPSHOT_TTL_S = 60
_SNAP_KINDS = ("users", "groups", "clusterroles", "clusterrolebindings", "roles", "rolebindings", "serviceaccounts")
_SNAP_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_SNAP_LOCK = threading.Lock()


def invalidate_snapshot(cache_key: Optional[str] = None) -> None:
    with _SNAP_LOCK:
        if cache_key is None:
            _SNAP_CACHE.clear()
        else:
            _SNAP_CACHE.pop(cache_key, None)


def _snap_error(snap: Dict[str, Any]) -> str:
    errs = list(dict.fromkeys(str(v) for v in (snap.get("errors") or {}).values()))
    return "RBAC binding'leri okunamadı: " + (errs[0][:300] if errs else "bilinmeyen hata")


def load_snapshot(client: OpenShiftClient, cache_key: Optional[str] = None, *, force: bool = False) -> Dict[str, Any]:
    """{kind: [özet...]} + errors + truncated + fetched_at. cache_key (ör. cluster_id) verilirse önbellekli."""
    now = time.time()
    if cache_key and not force:
        with _SNAP_LOCK:
            hit = _SNAP_CACHE.get(cache_key)
        if hit and now - hit[0] < SNAPSHOT_TTL_S:
            return hit[1]
    snap: Dict[str, Any] = {"errors": {}, "truncated": {}, "fetched_at": now}
    for kind in _SNAP_KINDS:
        out = list_access(client, kind, limit=_MAX_ITEMS)
        if out.get("ok"):
            snap[kind] = out.get("items") or []
            if out.get("truncated"):
                snap["truncated"][kind] = True
        else:
            snap[kind] = None  # None = okunamadı (boş liste ≠ erişim yok)
            snap["errors"][kind] = out.get("error") or "hata"
    if cache_key:
        with _SNAP_LOCK:
            _SNAP_CACHE[cache_key] = (now, snap)
    return snap


# ── İzin matrisi ─────────────────────────────────────────────────────────────

STD_VERBS = ["get", "list", "watch", "create", "update", "patch", "delete", "deletecollection"]


def permission_matrix(rules: Sequence[Dict]) -> Dict[str, Any]:
    """Role kurallarını (özet biçimi: verbs/api_groups/resources…) kaynak × fiil matrisine aç.

    '*' fiil → tüm standart fiiller + all_verbs. resourceNames olan kural kaynak satırına
    `resource_names` olarak işlenir (kısıtlı yetki). non-resource URL'ler ayrı listelenir.
    """
    rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    nonres: List[Dict[str, Any]] = []
    wildcard_verbs = False
    wildcard_resources = False
    for r in rules or []:
        verbs = set(r.get("verbs") or [])
        if "*" in verbs:
            wildcard_verbs = True
        expanded = set(STD_VERBS) | verbs if "*" in verbs else verbs
        urls = r.get("non_resource_urls") or []
        if urls:
            nonres.append({"urls": list(urls), "verbs": sorted(expanded)})
        resources = r.get("resources") or []
        groups = r.get("api_groups") or [""]
        if "*" in resources:
            wildcard_resources = True
        for g in groups:
            for res in resources:
                row = rows.setdefault((g, res), {
                    "api_group": g, "resource": res, "verbs": set(), "resource_names": set(), "restricted": True,
                })
                row["verbs"] |= expanded
                names = r.get("resource_names") or []
                if names:
                    row["resource_names"] |= set(names)
                else:
                    row["restricted"] = False
    out_rows = []
    for (g, res), row in sorted(rows.items(), key=lambda kv: (kv[0][1] != "*", kv[0][0], kv[0][1])):
        out_rows.append({
            "api_group": g,
            "resource": res,
            "verbs": sorted(row["verbs"]),
            "all_verbs": "*" in row["verbs"],
            "resource_names": sorted(row["resource_names"]),
            "restricted": bool(row["restricted"]),
        })
    return {
        "columns": STD_VERBS,
        "rows": out_rows,
        "non_resource": nonres,
        "wildcard_verbs": wildcard_verbs,
        "wildcard_resources": wildcard_resources,
        "full_access": wildcard_verbs and wildcard_resources,
    }


def role_matrix(client: OpenShiftClient, kind: str, name: str, *, namespace: Optional[str] = None) -> Dict[str, Any]:
    kind = (kind or "").lower()
    if kind not in ("roles", "clusterroles"):
        return {"ok": False, "error": "kind: roles|clusterroles"}
    res = get_access(client, kind, name, namespace=namespace)
    if not res.get("ok"):
        return res
    item = res["item"]
    return {"ok": True, "item": item, "matrix": permission_matrix(item.get("rules") or [])}


# ── Etkin yetki (kullanıcı/grup/SA) ──────────────────────────────────────────

def _implicit_groups(kind: str, name: str, namespace: str) -> List[str]:
    if kind == "user":
        return ["system:authenticated", "system:authenticated:oauth"]
    if kind == "serviceaccount":
        out = ["system:serviceaccounts", "system:authenticated"]
        if namespace:
            out.append(f"system:serviceaccounts:{namespace}")
        return out
    return []


def _index_roles(snap: Dict[str, Any]) -> Tuple[Dict[str, Dict], Dict[Tuple[str, str], Dict]]:
    cr = {r["name"]: r for r in (snap.get("clusterroles") or [])}
    nr = {(r["namespace"], r["name"]): r for r in (snap.get("roles") or [])}
    return cr, nr


def _resolve_role(binding: Dict, cr: Dict, nr: Dict) -> Optional[Dict]:
    ref = binding.get("role_ref") or {}
    if ref.get("kind") == "ClusterRole":
        return cr.get(ref.get("name"))
    return nr.get((binding.get("namespace") or "", ref.get("name")))


def effective_permissions(
    client: OpenShiftClient,
    *,
    subject_kind: str,
    subject_name: str,
    subject_namespace: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Özne için: doğrudan + grup üyeliği üzerinden gelen tüm binding'ler ve birleşik izin matrisleri."""
    sk = (subject_kind or "User").strip()
    sn = (subject_name or "").strip()
    sns = (subject_namespace or "").strip()
    if not sn:
        return {"ok": False, "error": "subject_name zorunlu"}
    snap = load_snapshot(client, cache_key)
    if snap.get("clusterrolebindings") is None and snap.get("rolebindings") is None:
        return {"ok": False, "error": _snap_error(snap)}
    kl = sk.lower()
    groups: List[str] = []
    if kl == "user" and snap.get("groups"):
        groups = [g["name"] for g in snap["groups"] if sn in (g.get("users") or [])]
    groups = sorted(set(groups) | set(_implicit_groups(kl, sn, sns)))
    cr, nr = _index_roles(snap)

    def _via(sub: Dict) -> Optional[str]:
        sk2, n2, ns2 = (sub.get("kind") or "").lower(), sub.get("name") or "", sub.get("namespace") or ""
        if sk2 == kl and n2.lower() == sn.lower() and (kl != "serviceaccount" or ns2 == sns):
            return "direct"
        if sk2 == "group" and n2 in groups and kl != "group":
            return f"group:{n2}"
        if kl == "group" and sk2 == "group" and n2 == sn:
            return "direct"
        return None

    grants: List[Dict[str, Any]] = []
    cluster_rules: List[Dict] = []
    ns_rules: Dict[str, List[Dict]] = {}
    missing: List[str] = []
    for b in (snap.get("clusterrolebindings") or []) + (snap.get("rolebindings") or []):
        via = None
        for sub in b.get("subjects") or []:
            via = _via(sub)
            if via:
                break
        if not via:
            continue
        role = _resolve_role(b, cr, nr)
        ref = b.get("role_ref") or {}
        scope = "cluster" if b["kind"] == "ClusterRoleBinding" else "namespace"
        grants.append({
            "binding_kind": b["kind"], "binding": b["name"], "namespace": b.get("namespace") or "",
            "scope": scope, "via": via, "role_kind": ref.get("kind"), "role": ref.get("name"),
            "role_found": role is not None, "rule_count": (role or {}).get("rule_count", 0),
        })
        if role is None:
            missing.append(f"{ref.get('kind')}/{ref.get('name')}")
            continue
        if scope == "cluster":
            cluster_rules.extend(role.get("rules") or [])
        else:
            ns_rules.setdefault(b.get("namespace") or "", []).extend(role.get("rules") or [])
    cluster_matrix = permission_matrix(cluster_rules)
    ns_out = {ns: permission_matrix(rs) for ns, rs in sorted(ns_rules.items())[:100]}
    is_cluster_admin = any(
        g["scope"] == "cluster" and g["role"] == "cluster-admin" for g in grants
    ) or cluster_matrix["full_access"]
    return {
        "ok": True,
        "subject": {"kind": sk, "name": sn, "namespace": sns},
        "groups": groups,
        "member_groups": [g for g in groups if not g.startswith("system:")],
        "grants": grants,
        "grant_count": len(grants),
        "cluster_matrix": cluster_matrix,
        "namespace_matrices": ns_out,
        "is_cluster_admin": is_cluster_admin,
        "missing_roles": sorted(set(missing)),
        "errors": snap.get("errors") or {},
    }


# ── Risk paneli ──────────────────────────────────────────────────────────────

BUILTIN_ROLES = {"cluster-admin", "admin", "edit", "view", "basic-user", "self-provisioner", "cluster-reader"}
_CRITICAL_ROLES = {"cluster-admin"}
_BROAD_ROLES = {"cluster-admin", "admin", "edit"}
_BROAD_GROUPS = {"system:authenticated", "system:unauthenticated", "system:authenticated:oauth"}


def _is_builtin(role: Dict) -> bool:
    n = role.get("name") or ""
    if n.startswith("system:") or n in BUILTIN_ROLES:
        return True
    labels = role.get("labels") or {}
    return "kubernetes.io/bootstrapping" in labels or "openshift.io/bootstrapping" in labels


def _role_is_wildcard(role: Dict) -> str:
    """'full' (verbs=* ve resources=*), 'verbs' (yalnız verbs=*), '' (yok)."""
    full = False
    verbs_only = False
    for r in role.get("rules") or []:
        if "*" in (r.get("verbs") or []):
            if "*" in (r.get("resources") or []):
                full = True
            else:
                verbs_only = True
    return "full" if full else ("verbs" if verbs_only else "")


def compute_risks(snap: Dict[str, Any], *, cap: int = 200) -> Dict[str, Any]:
    cr, nr = _index_roles(snap)
    users = {u["name"] for u in (snap.get("users") or [])} if snap.get("users") is not None else None
    groups = {g["name"] for g in (snap.get("groups") or [])} if snap.get("groups") is not None else None
    sas = (
        {(s["namespace"], s["name"]) for s in (snap.get("serviceaccounts") or [])}
        if snap.get("serviceaccounts") is not None else None
    )
    group_members = {g["name"]: g.get("users") or [] for g in (snap.get("groups") or [])}

    holders: List[Dict] = []
    dangerous: List[Dict] = []
    orphans: List[Dict] = []
    bindings = (snap.get("clusterrolebindings") or []) + (snap.get("rolebindings") or [])
    for b in bindings:
        ref = b.get("role_ref") or {}
        role = _resolve_role(b, cr, nr)
        base = {
            "binding_kind": b["kind"], "binding": b["name"], "namespace": b.get("namespace") or "",
            "role_kind": ref.get("kind"), "role": ref.get("name"),
        }
        if role is None and (ref.get("kind") == "ClusterRole" and snap.get("clusterroles") is not None
                             or ref.get("kind") == "Role" and snap.get("roles") is not None):
            orphans.append({**base, "type": "missing_role", "severity": "warning",
                            "subject": "", "message": f"Başvurulan {ref.get('kind')} '{ref.get('name')}' bulunamadı"})
        is_ca = ref.get("name") in _CRITICAL_ROLES and ref.get("kind") == "ClusterRole"
        wild = _role_is_wildcard(role) if role else ""
        for s in b.get("subjects") or []:
            sname, skind, sns = s.get("name") or "", (s.get("kind") or ""), s.get("namespace") or ""
            is_system = sname.startswith("system:")
            subj = {"subject_kind": skind, "subject": sname, "subject_namespace": sns}
            if is_ca and b["kind"] == "ClusterRoleBinding" and not is_system:
                item = {**base, **subj, "severity": "critical", "type": "cluster_admin_holder"}
                if skind == "Group":
                    item["member_count"] = len(group_members.get(sname, []))
                    item["members"] = group_members.get(sname, [])[:20]
                holders.append(item)
            if sname in _BROAD_GROUPS and skind == "Group" and (ref.get("name") in _BROAD_ROLES or wild):
                dangerous.append({**base, **subj, "severity": "critical", "type": "broad_group_grant",
                                  "message": f"'{sname}' grubuna '{ref.get('name')}' verilmiş — kimlik doğrulanan herkes etkilenir"})
            # yetim özneler
            if is_system:
                continue
            miss = ""
            if skind == "User" and users is not None and sname not in users:
                miss = "Kullanıcı nesnesi yok (hiç giriş yapmamış veya silinmiş olabilir)"
            elif skind == "Group" and groups is not None and sname not in groups:
                miss = "Grup nesnesi yok"
            elif skind == "ServiceAccount" and sas is not None and (sns, sname) not in sas:
                miss = "ServiceAccount yok"
            if miss:
                orphans.append({**base, **subj, "type": "missing_subject", "severity": "info", "message": miss})

    wildcard_roles: List[Dict] = []
    for kind, key in (("ClusterRole", "clusterroles"), ("Role", "roles")):
        for r in snap.get(key) or []:
            w = _role_is_wildcard(r)
            if w:
                wildcard_roles.append({
                    "role_kind": kind, "role": r["name"], "namespace": r.get("namespace") or "",
                    "wildcard": w, "builtin": _is_builtin(r),
                    "severity": ("info" if _is_builtin(r) else ("critical" if w == "full" else "warning")),
                })
    return {
        "ok": True,
        "summary": {
            "cluster_admin_holders": len(holders),
            "wildcard_roles": len([w for w in wildcard_roles if not w["builtin"]]),
            "wildcard_roles_builtin": len([w for w in wildcard_roles if w["builtin"]]),
            "broad_group_grants": len(dangerous),
            "orphan_bindings": len([o for o in orphans if o["type"] == "missing_role"]),
            "orphan_subjects": len([o for o in orphans if o["type"] == "missing_subject"]),
        },
        "cluster_admin_holders": holders[:cap],
        "wildcard_roles": wildcard_roles[:cap],
        "broad_group_grants": dangerous[:cap],
        "orphans": orphans[:cap],
        "errors": snap.get("errors") or {},
        "fetched_at": snap.get("fetched_at"),
    }


def access_risks(client: OpenShiftClient, cache_key: Optional[str] = None) -> Dict[str, Any]:
    snap = load_snapshot(client, cache_key)
    if snap.get("clusterrolebindings") is None and snap.get("rolebindings") is None:
        return {"ok": False, "error": _snap_error(snap)}
    return compute_risks(snap)


def access_overview(client: OpenShiftClient, cache_key: Optional[str] = None, *, admin: bool = False) -> Dict[str, Any]:
    """KPI sayıları + OAuth providers + yetki teşhisi (önbellekli snapshot).

    admin=False → IdP yalnız ad/tür (mapping/token ayrıntısı Admin'e özel).
    """
    snap = load_snapshot(client, cache_key)
    counts: Dict[str, Any] = {}
    for kind in ("users", "groups", "clusterroles", "clusterrolebindings", "roles", "rolebindings", "serviceaccounts"):
        counts[kind] = None if snap.get(kind) is None else len(snap[kind])
    # Identity sayısı snapshot'ta yok (nadiren gerekli, büyük olabilir) → ucuz tek sayfa değil, tam okuma
    ident = list_access(client, "identities", limit=_MAX_ITEMS)
    counts["identities"] = ident.get("count") if ident.get("ok") else None
    errors = dict(snap.get("errors") or {})
    if not ident.get("ok"):
        errors["identities"] = ident.get("error") or "hata"

    idp = identity_providers(client)
    providers = idp.get("providers") if idp.get("ok") else []
    if not admin:
        providers = [{"name": p.get("name"), "type": p.get("type")} for p in providers]
    can_list_users = self_can_i(client, verb="list", resource="users", api_group="user.openshift.io")
    can_list_crb = self_can_i(client, verb="list", resource="clusterrolebindings", api_group="rbac.authorization.k8s.io")

    risk_summary = None
    if snap.get("clusterrolebindings") is not None:
        risk_summary = compute_risks(snap, cap=0)["summary"]
    return {
        "ok": True,
        "counts": counts,
        "errors": errors,
        "truncated": snap.get("truncated") or {},
        "identity_providers": providers,
        "identity_providers_error": None if idp.get("ok") else idp.get("error"),
        "token_can": {
            "list_users": can_list_users.get("allowed"),
            "list_clusterrolebindings": can_list_crb.get("allowed"),
        },
        "risk_summary": risk_summary,
        "fetched_at": snap.get("fetched_at"),
        "footnote": (
            "Okuma: openshift modül yetkilileri. Oluşturma (RoleBinding / ClusterRoleBinding / Role / "
            "ClusterRole) yalnız Admin; düzenleme, silme ve kullanıcı/grup yönetimi bu ekranda yoktur."
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
