"""
OpenShift Access / RBAC — YALNIZ OLUŞTURMA (Admin).

Kapsam (bilinçli olarak dar):
  RoleBinding, ClusterRoleBinding, Role, ClusterRole  → CREATE
  Düzenleme (PUT/PATCH), silme (DELETE), kullanıcı/grup/identity yönetimi → YOK.
  Sohbet aracı (`ocp_access_query`) bu modülü ASLA çağırmaz (READ-ONLY).

Güvenlik katmanları:
  1. Girdi doğrulama (DNS-1123 ad, fiil/kaynak biçimi, boyut sınırları); YAML modu da aynı
     doğrulayıcıdan geçer ve yalnız {ad, namespace, roleRef, subjects, rules} alanlarını alır
     (labels/annotations/ownerReferences/finalizers vb. YOK SAYILIR → uyarı).
  2. `dryRun=All` ile sunucu tarafı ön izleme (admission + RBAC escalation kontrolü).
  3. Riskli içerik uyarıları (cluster-admin, wildcard, secrets, escalate/bind/impersonate,
     system:authenticated) — kritik olanlarda nesne adını yazarak onay şart (sunucu da doğrular).
  4. `app.kubernetes.io/managed-by: ainew` etiketi + `ainew.io/created-by` notu.
  5. Gerçek oluşturma öncesi dryRun yeniden çalışır; 409 → Türkçe «zaten var».
  6. Silme komutu yalnız BİLGİ amaçlı gösterilir; hiçbir koşulda çalıştırılmaz.
Token/Secret değeri hiçbir yerde okunmaz, loglanmaz.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.services.openshift import ocp_access
from app.services.openshift.ocp_access import AUTHZ_API, RBAC_API
from app.services.openshift.ocp_client import OpenShiftClient

logger = logging.getLogger(__name__)

MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "ainew"
CREATED_BY_ANNOTATION = "ainew.io/created-by"
CREATED_AT_ANNOTATION = "ainew.io/created-at"
DESCRIPTION_ANNOTATION = "ainew.io/description"

RBAC_GROUP = "rbac.authorization.k8s.io"
KINDS = ("RoleBinding", "ClusterRoleBinding", "Role", "ClusterRole")
_KIND_ALIASES = {k.lower(): k for k in KINDS}
_KIND_ALIASES.update({"rolebindings": "RoleBinding", "clusterrolebindings": "ClusterRoleBinding",
                      "roles": "Role", "clusterroles": "ClusterRole"})
_NAMESPACED = {"RoleBinding": True, "Role": True, "ClusterRoleBinding": False, "ClusterRole": False}
_PLURAL = {"RoleBinding": "rolebindings", "ClusterRoleBinding": "clusterrolebindings",
           "Role": "roles", "ClusterRole": "clusterroles"}

MAX_SUBJECTS = 50
MAX_RULES = 100
MAX_LIST_ITEMS = 100

_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$")
_LABEL_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_VERB_RE = re.compile(r"^(\*|[a-z]+)$")
_TOKEN_RE = re.compile(r"^(\*|[A-Za-z0-9][A-Za-z0-9._/:-]*)$")  # kaynak / apiGroup / resourceName
_API_GROUP_RE = re.compile(r"^(\*|[a-z0-9]([-a-z0-9.]*[a-z0-9])?)?$")
_RESOURCE_RE = re.compile(r"^(\*|[a-z0-9]([-a-z0-9.]*[a-z0-9])?(/[a-z0-9*]([-a-z0-9.*]*[a-z0-9*])?)?)$")
_URL_RE = re.compile(r"^(\*|/[A-Za-z0-9._~/*-]*)$")

KNOWN_VERBS = {
    "get", "list", "watch", "create", "update", "patch", "delete", "deletecollection",
    "impersonate", "bind", "escalate", "approve", "sign", "use", "proxy", "*",
}


class AccessWriteError(Exception):
    """Doğrulama / iş kuralı hatası → API 400/409 (Türkçe mesaj)."""

    def __init__(self, message: str, *, status: int = 400, code: str = "invalid") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def normalize_kind(kind: str) -> str:
    k = _KIND_ALIASES.get((kind or "").strip().lower())
    if not k:
        raise AccessWriteError(f"Desteklenmeyen tür: {kind!r}. Yalnız {', '.join(KINDS)} oluşturulabilir.")
    return k


def _check_name(name: Any, what: str = "Ad") -> str:
    n = str(name or "").strip()
    if not n:
        raise AccessWriteError(f"{what} zorunlu")
    if len(n) > 253 or not _NAME_RE.match(n):
        raise AccessWriteError(
            f"{what} geçersiz: «{n}» — küçük harf, rakam, '-' ve '.' kullanın (en fazla 253 karakter)."
        )
    return n


def _check_ns(ns: Any) -> str:
    n = str(ns or "").strip()
    if not n:
        raise AccessWriteError("namespace zorunlu")
    if len(n) > 63 or not _LABEL_RE.match(n):
        raise AccessWriteError(f"namespace geçersiz: «{n}»")
    return n


def _str_list(val: Any, what: str, pattern: re.Pattern, *, allow_empty_item: bool = False) -> List[str]:
    if val is None:
        return []
    if isinstance(val, str):
        val = [val]
    if not isinstance(val, (list, tuple)):
        raise AccessWriteError(f"{what} liste olmalı")
    out: List[str] = []
    for v in val:
        s = "" if v is None else str(v).strip()
        if not s and not allow_empty_item:
            continue
        if len(s) > 253 or not pattern.match(s):
            raise AccessWriteError(f"{what} geçersiz değer: «{s}»")
        if s not in out:
            out.append(s)
    if len(out) > MAX_LIST_ITEMS:
        raise AccessWriteError(f"{what} en fazla {MAX_LIST_ITEMS} öğe olabilir")
    return out


# ── Doğrulama / manifest üretimi ─────────────────────────────────────────────

def normalize_rules(rules: Any, *, cluster: bool) -> List[Dict[str, Any]]:
    if not isinstance(rules, (list, tuple)) or not rules:
        raise AccessWriteError("En az bir kural (rule) gerekli")
    if len(rules) > MAX_RULES:
        raise AccessWriteError(f"En fazla {MAX_RULES} kural eklenebilir")
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict):
            raise AccessWriteError(f"Kural {i}: nesne olmalı")
        # Hem k8s (apiGroups) hem özet (api_groups) biçimini kabul et
        def pick(*keys: str) -> Any:
            for k in keys:
                if k in r:
                    return r[k]
            return None
        verbs = _str_list(pick("verbs"), f"Kural {i} verbs", _VERB_RE)
        if not verbs:
            raise AccessWriteError(f"Kural {i}: en az bir fiil (verb) gerekli")
        bad = [v for v in verbs if v not in KNOWN_VERBS]
        if bad:
            raise AccessWriteError(f"Kural {i}: bilinmeyen fiil {bad}. Geçerli: {', '.join(sorted(KNOWN_VERBS))}")
        resources = _str_list(pick("resources"), f"Kural {i} resources", _RESOURCE_RE)
        groups = _str_list(pick("apiGroups", "api_groups"), f"Kural {i} apiGroups", _API_GROUP_RE, allow_empty_item=True)
        names = _str_list(pick("resourceNames", "resource_names"), f"Kural {i} resourceNames", _TOKEN_RE)
        urls = _str_list(pick("nonResourceURLs", "non_resource_urls"), f"Kural {i} nonResourceURLs", _URL_RE)
        if urls and not cluster:
            raise AccessWriteError(f"Kural {i}: nonResourceURLs yalnız ClusterRole'da kullanılabilir")
        if urls and (resources or names):
            raise AccessWriteError(f"Kural {i}: nonResourceURLs ile resources/resourceNames birlikte kullanılamaz")
        if not urls and not resources:
            raise AccessWriteError(f"Kural {i}: resources (veya nonResourceURLs) gerekli")
        rule: Dict[str, Any] = {"verbs": verbs}
        if urls:
            rule["nonResourceURLs"] = urls
        else:
            # apiGroups verilmezse core ("") grubu varsay (boş liste k8s'te hiçbir grup demektir)
            rule["apiGroups"] = groups or [""]
            rule["resources"] = resources
            if names:
                rule["resourceNames"] = names
        out.append(rule)
    return out


def normalize_subjects(subjects: Any) -> List[Dict[str, str]]:
    if not isinstance(subjects, (list, tuple)) or not subjects:
        raise AccessWriteError("En az bir özne (kullanıcı/grup/ServiceAccount) gerekli")
    if len(subjects) > MAX_SUBJECTS:
        raise AccessWriteError(f"En fazla {MAX_SUBJECTS} özne eklenebilir")
    out: List[Dict[str, str]] = []
    seen = set()
    for i, s in enumerate(subjects, 1):
        if not isinstance(s, dict):
            raise AccessWriteError(f"Özne {i}: nesne olmalı")
        kind = str(s.get("kind") or "").strip()
        kmap = {"user": "User", "group": "Group", "serviceaccount": "ServiceAccount"}
        kind = kmap.get(kind.lower(), "")
        if not kind:
            raise AccessWriteError(f"Özne {i}: kind User | Group | ServiceAccount olmalı")
        name = str(s.get("name") or "").strip()
        if not name:
            raise AccessWriteError(f"Özne {i}: ad zorunlu")
        if len(name) > 253 or any(c in name for c in " \t\n\r\"'`$;|&<>\\"):
            raise AccessWriteError(f"Özne {i}: ad geçersiz karakter içeriyor")
        entry: Dict[str, str] = {"kind": kind, "name": name}
        if kind == "ServiceAccount":
            entry["namespace"] = _check_ns(s.get("namespace"))
        else:
            entry["apiGroup"] = RBAC_GROUP
        key = (kind, name, entry.get("namespace", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def build_manifest(
    kind: str,
    spec: Dict[str, Any],
    *,
    actor: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Doğrulanmış k8s manifesti üret. `spec`: name, namespace?, role_ref?, subjects?, rules?, description?"""
    kind = normalize_kind(kind)
    if not isinstance(spec, dict):
        raise AccessWriteError("spec nesne olmalı")
    name = _check_name(spec.get("name"))
    namespaced = _NAMESPACED[kind]
    md: Dict[str, Any] = {"name": name}
    if namespaced:
        md["namespace"] = _check_ns(spec.get("namespace"))
    now = now or datetime.now(timezone.utc)
    md["labels"] = {MANAGED_BY_LABEL: MANAGED_BY_VALUE}
    ann = {CREATED_AT_ANNOTATION: now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if actor:
        ann[CREATED_BY_ANNOTATION] = str(actor)[:100]
    desc = str(spec.get("description") or "").strip()
    if desc:
        ann[DESCRIPTION_ANNOTATION] = desc[:500]
    md["annotations"] = ann
    manifest: Dict[str, Any] = {"apiVersion": f"{RBAC_GROUP}/v1", "kind": kind, "metadata": md}

    if kind in ("RoleBinding", "ClusterRoleBinding"):
        ref = spec.get("role_ref") or spec.get("roleRef") or {}
        ref_kind = str(ref.get("kind") or ("ClusterRole" if kind == "ClusterRoleBinding" else "")).strip()
        ref_kind = {"role": "Role", "clusterrole": "ClusterRole"}.get(ref_kind.lower(), "")
        if not ref_kind:
            raise AccessWriteError("roleRef.kind Role veya ClusterRole olmalı")
        if kind == "ClusterRoleBinding" and ref_kind != "ClusterRole":
            raise AccessWriteError("ClusterRoleBinding yalnız ClusterRole'a bağlanabilir")
        ref_name = str(ref.get("name") or "").strip()
        if not ref_name:
            raise AccessWriteError("roleRef.name zorunlu")
        if len(ref_name) > 253 or any(c in ref_name for c in " \t\n\r\"'`$;|&<>\\"):
            raise AccessWriteError("roleRef.name geçersiz karakter içeriyor")
        manifest["roleRef"] = {"apiGroup": RBAC_GROUP, "kind": ref_kind, "name": ref_name}
        manifest["subjects"] = normalize_subjects(spec.get("subjects"))
    else:
        manifest["rules"] = normalize_rules(spec.get("rules"), cluster=(kind == "ClusterRole"))
    return manifest


_ALLOWED_TOP = {"apiVersion", "kind", "metadata", "roleRef", "subjects", "rules"}
_ALLOWED_META = {"name", "namespace"}
_STRIPPED_META = {"labels", "annotations", "ownerReferences", "finalizers", "generateName", "uid",
                  "resourceVersion", "creationTimestamp", "managedFields", "selfLink", "generation"}


def spec_from_yaml(text: str) -> Tuple[str, Dict[str, Any], List[str]]:
    """YAML → (kind, spec, ignored_warnings). Tek doküman, yalnız desteklenen 4 tür."""
    if not (text or "").strip():
        raise AccessWriteError("YAML boş")
    if len(text) > 200_000:
        raise AccessWriteError("YAML çok büyük (en fazla 200 KB)")
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.YAMLError as e:
        raise AccessWriteError(f"YAML okunamadı: {str(e)[:200]}") from e
    if len(docs) != 1:
        raise AccessWriteError("YAML tek bir nesne içermeli (birden fazla doküman desteklenmez)")
    doc = docs[0]
    if not isinstance(doc, dict):
        raise AccessWriteError("YAML bir nesne (map) olmalı")
    kind = normalize_kind(str(doc.get("kind") or ""))
    api = str(doc.get("apiVersion") or "")
    if api and api != f"{RBAC_GROUP}/v1":
        raise AccessWriteError(f"apiVersion {RBAC_GROUP}/v1 olmalı (gelen: {api})")
    warnings: List[str] = []
    for k in doc:
        if k not in _ALLOWED_TOP:
            if k == "aggregationRule":
                raise AccessWriteError("aggregationRule desteklenmiyor")
            warnings.append(f"Yok sayıldı: {k}")
    md = doc.get("metadata") or {}
    if not isinstance(md, dict):
        raise AccessWriteError("metadata nesne olmalı")
    for k in md:
        if k in _STRIPPED_META:
            warnings.append(f"metadata.{k} yok sayıldı (ainew kendi etiket/notlarını ekler)")
        elif k not in _ALLOWED_META:
            warnings.append(f"metadata.{k} yok sayıldı")
    spec: Dict[str, Any] = {"name": md.get("name"), "namespace": md.get("namespace")}
    if kind in ("RoleBinding", "ClusterRoleBinding"):
        spec["role_ref"] = doc.get("roleRef") or {}
        spec["subjects"] = doc.get("subjects")
    else:
        spec["rules"] = doc.get("rules")
    return kind, spec, warnings


# ── Uyarılar (riskli içerik) ─────────────────────────────────────────────────

def analyze_warnings(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    """{level: critical|warning|info, code, message}. critical → ad yazarak onay şart."""
    out: List[Dict[str, str]] = []

    def add(level: str, code: str, msg: str) -> None:
        out.append({"level": level, "code": code, "message": msg})

    kind = manifest.get("kind")
    if kind in ("RoleBinding", "ClusterRoleBinding"):
        ref = manifest.get("roleRef") or {}
        rname = ref.get("name")
        if rname == "cluster-admin" and ref.get("kind") == "ClusterRole":
            if kind == "ClusterRoleBinding":
                add("critical", "cluster_admin_global",
                    "cluster-admin tüm cluster üzerinde TAM yetki verir (her kaynak, her namespace).")
            else:
                add("critical", "cluster_admin_ns",
                    "cluster-admin bu namespace'te tam yetki verir (namespace içinde sınırsız).")
        elif rname in ("admin", "edit") and ref.get("kind") == "ClusterRole":
            scope = "tüm cluster" if kind == "ClusterRoleBinding" else "bu namespace"
            add("warning", "broad_role", f"'{rname}' rolü {scope} için geniş yazma yetkisi verir.")
        for s in manifest.get("subjects") or []:
            if s.get("kind") == "Group" and s.get("name") in ("system:authenticated", "system:unauthenticated",
                                                             "system:authenticated:oauth"):
                add("critical", "broad_group",
                    f"'{s['name']}' tüm kimlik doğrulanan/anonim istemcileri kapsar — "
                    "bu role herkes sahip olur.")
            if s.get("kind") == "ServiceAccount" and s.get("name") == "default":
                add("warning", "default_sa",
                    "default ServiceAccount'a yetki vermek, namespace'teki tüm pod'lara bu yetkiyi verir.")
        if kind == "ClusterRoleBinding" and rname not in ("cluster-admin",):
            add("info", "cluster_scope", "ClusterRoleBinding cluster genelinde geçerlidir; namespace kısıtı olmaz.")
    else:
        for i, r in enumerate(manifest.get("rules") or [], 1):
            verbs, res, groups = r.get("verbs") or [], r.get("resources") or [], r.get("apiGroups") or []
            if "*" in verbs and "*" in res:
                add("critical", "wildcard_all", f"Kural {i}: tüm kaynaklarda tüm fiiller (wildcard) — cluster-admin eşdeğeri.")
            elif "*" in verbs:
                add("warning", "wildcard_verbs", f"Kural {i}: tüm fiiller (*) — okuma/yazma/silme dahil.")
            elif "*" in res:
                add("warning", "wildcard_resources", f"Kural {i}: tüm kaynaklar (*).")
            if "*" in groups and "*" not in res:
                add("warning", "wildcard_groups", f"Kural {i}: tüm API grupları (*).")
            esc = [v for v in verbs if v in ("escalate", "bind", "impersonate")]
            if esc:
                add("critical", "privilege_verbs",
                    f"Kural {i}: {', '.join(esc)} fiilleri yetki yükseltmeye izin verir.")
            if "secrets" in res and any(v in verbs for v in ("get", "list", "watch", "*")):
                add("warning", "secrets_read",
                    f"Kural {i}: Secret okuma — token/parola/sertifika içeriğine erişim sağlar.")
            if ("pods/exec" in res or "pods/attach" in res) and any(v in verbs for v in ("create", "*")):
                add("warning", "pod_exec", f"Kural {i}: pod içinde komut çalıştırma (exec/attach).")
            if any(g in ("rbac.authorization.k8s.io",) for g in groups) and any(
                x in res for x in ("clusterrolebindings", "rolebindings", "clusterroles", "roles", "*")
            ) and any(v in verbs for v in ("create", "update", "patch", "*")):
                add("warning", "rbac_write", f"Kural {i}: RBAC nesnelerini değiştirme yetkisi.")
    # tekilleştir
    seen, uniq = set(), []
    for w in out:
        k = (w["code"], w["message"])
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq


def requires_name_confirmation(warnings: List[Dict[str, str]]) -> bool:
    return any(w["level"] == "critical" for w in warnings)


def equivalent_delete_command(manifest: Dict[str, Any]) -> str:
    """BİLGİ amaçlı — ainew bu komutu ASLA çalıştırmaz."""
    kind = manifest["kind"].lower()
    md = manifest["metadata"]
    cmd = f"oc delete {kind} {md['name']}"
    if md.get("namespace"):
        cmd += f" -n {md['namespace']}"
    return cmd


def manifest_yaml(manifest: Dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)


# ── Cluster'a gönderme ───────────────────────────────────────────────────────

def _create_path(manifest: Dict[str, Any], *, dry_run: bool) -> str:
    kind = manifest["kind"]
    md = manifest["metadata"]
    plural = _PLURAL[kind]
    if _NAMESPACED[kind]:
        path = f"{RBAC_API}/namespaces/{md['namespace']}/{plural}"
    else:
        path = f"{RBAC_API}/{plural}"
    return path + ("?dryRun=All" if dry_run else "")


def _status_message(r: Any) -> str:
    try:
        body = r.json() or {}
        return str(body.get("message") or "")[:400]
    except Exception:
        return (getattr(r, "text", "") or "")[:300]


def interpret_response(r: Any, manifest: Dict[str, Any]) -> Tuple[bool, str, str]:
    """(ok, code, Türkçe mesaj)."""
    kind, md = manifest["kind"], manifest["metadata"]
    where = f" ({md['namespace']} namespace'inde)" if md.get("namespace") else ""
    if r.status_code in (200, 201, 202):
        return True, "ok", ""
    detail = _status_message(r)
    if r.status_code == 409:
        return False, "exists", f"Aynı isimde {kind} zaten var: «{md['name']}»{where}. Başka bir ad seçin."
    if r.status_code == 403:
        low = detail.lower()
        if "escalat" in low or "attempting to grant" in low or "cannot bind" in low or "not currently held" in low:
            return False, "escalation", (
                "Yetki yükseltme engeli: ainew'in cluster token'ı bu role/kurala sahip olmadığı için onu başkasına "
                f"veremez (Kubernetes privilege-escalation koruması). Ayrıntı: {detail}"
            )
        return False, "forbidden", f"Cluster token'ının {kind} oluşturma yetkisi yok. Ayrıntı: {detail}"
    if r.status_code == 401:
        return False, "unauthorized", "Cluster token'ı geçersiz veya süresi dolmuş (401)."
    if r.status_code in (400, 422):
        return False, "invalid", f"Cluster nesneyi reddetti: {detail}"
    if r.status_code == 404:
        return False, "not_found", f"Hedef bulunamadı (namespace yok olabilir): {detail}"
    return False, "error", f"HTTP {r.status_code}: {detail}"


def submit(client: OpenShiftClient, manifest: Dict[str, Any], *, dry_run: bool) -> Dict[str, Any]:
    try:
        r = client._post(_create_path(manifest, dry_run=dry_run), body=manifest, timeout=30)
    except Exception as e:  # ağ hatası
        return {"ok": False, "code": "network", "message": f"Cluster'a ulaşılamadı: {str(e)[:200]}"}
    ok, code, msg = interpret_response(r, manifest)
    return {"ok": ok, "code": code, "message": msg, "http_status": r.status_code}


def prepare(
    client: Optional[OpenShiftClient],
    *,
    mode: str,
    kind: Optional[str] = None,
    spec: Optional[Dict[str, Any]] = None,
    yaml_text: Optional[str] = None,
    copy_from: Optional[Dict[str, Any]] = None,
    actor: str = "",
) -> Dict[str, Any]:
    """Girdiyi doğrula → manifest + uyarılar + YAML (cluster'a dokunmaz; copy_from hariç okuma)."""
    ignored: List[str] = []
    if (mode or "form").lower() == "yaml":
        kind, spec, ignored = spec_from_yaml(yaml_text or "")
    else:
        kind = normalize_kind(kind or "")
        spec = dict(spec or {})
    if copy_from and kind in ("Role", "ClusterRole"):
        if client is None:
            raise AccessWriteError("Kaynak rol okunamadı (cluster istemcisi yok)")
        src_kind = (copy_from.get("kind") or "").lower()
        if src_kind not in ("role", "clusterrole", "roles", "clusterroles"):
            raise AccessWriteError("copy_from.kind Role veya ClusterRole olmalı")
        plural = "roles" if src_kind.startswith("role") else "clusterroles"
        src = ocp_access.get_access(client, plural, str(copy_from.get("name") or ""),
                                    namespace=copy_from.get("namespace"))
        if not src.get("ok"):
            raise AccessWriteError(f"Kaynak rol okunamadı: {src.get('error')}")
        copied = [
            {"verbs": r["verbs"], "apiGroups": r["api_groups"], "resources": r["resources"],
             "resourceNames": r["resource_names"], "nonResourceURLs": r["non_resource_urls"]}
            for r in (src["item"].get("rules") or [])
        ]
        if kind == "Role":  # nonResourceURLs Role'da geçersiz
            copied = [c for c in copied if not c["nonResourceURLs"]]
        spec["rules"] = copied + list(spec.get("rules") or [])
        if not spec.get("description"):
            spec["description"] = f"{copy_from.get('name')} rolünden kopyalandı"
    manifest = build_manifest(kind, spec, actor=actor)
    warnings = analyze_warnings(manifest)
    return {
        "manifest": manifest,
        "yaml": manifest_yaml(manifest),
        "warnings": warnings,
        "requires_name_confirmation": requires_name_confirmation(warnings),
        "ignored": ignored,
        "equivalent_delete": equivalent_delete_command(manifest),
        "equivalent_delete_note": "Yalnız bilgi — ainew bu komutu çalıştırmaz; silme işlemini kendiniz oc/konsol ile yapın.",
    }


def preview(client: OpenShiftClient, **kw: Any) -> Dict[str, Any]:
    """Doğrula + sunucu tarafı dryRun=All. Hiçbir şey kalıcı olmaz."""
    prep = prepare(client, **kw)
    dry = submit(client, prep["manifest"], dry_run=True)
    return {"ok": dry["ok"], "dry_run": dry, **prep}


def create(client: OpenShiftClient, *, confirm_name: Optional[str] = None, cache_key: Optional[str] = None, **kw: Any) -> Dict[str, Any]:
    """Doğrula → (kritikse ad onayı) → dryRun → gerçek POST. Düzenleme/silme yok."""
    prep = prepare(client, **kw)
    manifest = prep["manifest"]
    if prep["requires_name_confirmation"]:
        if (confirm_name or "").strip() != manifest["metadata"]["name"]:
            raise AccessWriteError(
                "Bu nesne yüksek risk içeriyor. Onay için nesnenin adını "
                f"(«{manifest['metadata']['name']}») aynen yazmalısınız.",
                status=400, code="confirm_required",
            )
    dry = submit(client, manifest, dry_run=True)
    if not dry["ok"]:
        raise AccessWriteError(dry["message"], status=409 if dry["code"] == "exists" else 400, code=dry["code"])
    real = submit(client, manifest, dry_run=False)
    if not real["ok"]:
        raise AccessWriteError(real["message"], status=409 if real["code"] == "exists" else 400, code=real["code"])
    ocp_access.invalidate_snapshot(cache_key)
    return {"ok": True, "created": True, **prep}


# ── Yetenek kontrolü (token create yapabilir mi?) ────────────────────────────

def capabilities(client: OpenShiftClient) -> Dict[str, Any]:
    """ainew cluster token'ı her tür için `create` yetkisine sahip mi (SelfSubjectAccessReview)."""
    out: Dict[str, Any] = {}
    for kind in KINDS:
        res = ocp_access.self_can_i(client, verb="create", resource=_PLURAL[kind], api_group=RBAC_GROUP)
        allowed = bool(res.get("allowed")) if res.get("ok") else False
        reason = ""
        if not res.get("ok"):
            reason = res.get("error") or "Yetki sorgulanamadı"
        elif not allowed:
            reason = res.get("reason") or f"Cluster token'ının {kind} oluşturma yetkisi yok (create {_PLURAL[kind]})"
        out[kind] = {"allowed": allowed, "reason": reason}
    return out
