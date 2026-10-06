"""
Modül erişim politikası — API yol öneki → gerekli modül(ler).

Amaç: bir kullanıcı yetkisi olmayan modülün hiçbir sayfasına / API'sine
(link, kısa yol, dashboard, doğrudan URL, WebSocket) erişemesin.

Kurallar:
- Admin / superadmin tüm modüllere erişir.
- Kural "any-of": listedeki modüllerden en az birine sahip olmak yeterli.
- ``read_extra``: yalnız GET/HEAD için ek izinli modüller (örn. ``executive`` salt-okunur).
- ``ANY``: kimliği doğrulanmış her kullanıcı (uç noktanın kendi rol kontrolü geçerli).
- ``ADMIN``: yalnız admin.
- En uzun önek eşleşmesi kazanır. Eşleşmeyen /api/v1 yolu → kapalı (yalnız admin);
  bu sayede yeni eklenen router'lar sınıflandırılmadan kullanıcıya açılmaz.
  ``test_module_policy`` her kayıtlı route'un kapsandığını doğrular.

Ek olarak ``ROLE_RULES``: bazı yazma / komut çalıştırma uçları için minimum rol.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

ANY = "*"
ADMIN = "!admin"

# Platform (AIOps) modülleri
PLATFORM_MODULES: Tuple[str, ...] = ("linux", "windows", "virtualization", "exadata", "openshift")

# `platform=` query / path parametresi → modül
PLATFORM_PARAM_TO_MODULE: Dict[str, str] = {
    "linux": "linux",
    "windows": "windows",
    "virt": "virtualization",
    "virtualization": "virtualization",
    "vmware": "virtualization",
    "exadata": "exadata",
    "openshift": "openshift",
    "ocp": "openshift",
}

ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3, "superadmin": 3}


@dataclass(frozen=True)
class Rule:
    prefix: str
    modules: Tuple[str, ...] = ()           # any-of; boş + flag → özel
    read_extra: Tuple[str, ...] = ()        # yalnız GET/HEAD için ek modüller
    mode: str = "modules"                   # modules | any | admin


def _m(prefix: str, *modules: str, read_extra: Iterable[str] = ()) -> Rule:
    return Rule(prefix, tuple(modules), tuple(read_extra))


_ANY = lambda p: Rule(p, mode="any")        # noqa: E731
_ADMIN = lambda p: Rule(p, mode="admin")    # noqa: E731

_P = PLATFORM_MODULES
_ROUTES = "/api/v1"

RULES: List[Rule] = [
    # ── Herkes (kimlik doğrulanmış) — uç noktaların kendi rol kontrolü geçerli ──
    _ANY("/auth"), _ANY("/public"), _ANY("/modules"), _ANY("/identity"), _ANY("/security"),
    _ANY("/audit"), _ANY("/platform"), _ANY("/platform-update"), _ANY("/settings"),
    _ANY("/tasks"), _ANY("/rag"),
    # Sohbet: oturum uçları herkese; platform kapsamı unified-chat içinde modüle göre süzülür
    _m("/chat", *_P, "ai_automation", "executive"),
    _m("/chat-turns", *_P, "ai_automation", "executive"),
    _m("/unified-chat", *_P, "ai_automation", "executive"),

    # ── Sanallaştırma ──
    _m("/virt-insights", "virtualization"),
    _m("/hypervisors", "virtualization", "integrations", read_extra=("executive",)),

    # ── OpenShift ──
    _m("/ocp-insights", "openshift"),
    _m("/openshift", "openshift", "integrations", read_extra=("executive",)),

    # ── Exadata ──
    _m("/exadata", "exadata", "integrations", read_extra=("executive",)),

    # ── Windows ──
    _m("/windows", "windows", read_extra=("executive",)),
    _m("/windows-chat", "windows"),

    # ── Linux ──
    _m("/servers", "linux", "windows", "virtualization", "exadata", "integrations",
       "applications", "knowledge", "ai_automation", "monitoring", "custom_reports",
       read_extra=("executive",)),
    _m("/packages", "linux"),
    _m("/repos", "linux"),
    _m("/updates", "linux"),
    _m("/snapshots", "linux"),
    _m("/ansible", "linux"),
    _m("/terminal", "linux"),

    # ── Paylaşılan AIOps veri uçları (platform parametresi ayrıca doğrulanır) ──
    _m("/events", *_P, "ai_automation", "monitoring", read_extra=("executive",)),
    _m("/incidents", *_P, "ai_automation", "monitoring", read_extra=("executive",)),
    _m("/anomalies", *_P, "ai_automation", "monitoring", read_extra=("executive",)),
    _m("/baseline", *_P, "ai_automation", "monitoring", read_extra=("executive",)),
    _m("/rca", *_P, "ai_automation", "monitoring", read_extra=("executive",)),
    _m("/alerts", *_P, "monitoring", read_extra=("executive",)),
    _m("/compare", *_P, read_extra=("executive",)),
    _m("/platform-reports", *_P, read_extra=("executive",)),
    _m("/metrics", *_P, "monitoring", read_extra=("executive",)),
    _m("/monitoring", *_P, "monitoring", "integrations", read_extra=("executive",)),
    _m("/ops", *_P, read_extra=("executive",)),
    _m("/ops/executive-summary", "executive"),
    _m("/ai", *_P, "ai_automation"),
    _m("/collectors", *_P, "integrations", "ai_automation"),

    # ── AI & Otomasyon ──
    _m("/agent", "ai_automation"),
    _ADMIN("/mcp"),

    # ── Level 1 / Centrify ──
    _m("/level1", "level1", "integrations"),
    _m("/centrify-mgmt", "centrify", "level1", "integrations"),
    _m("/centrify-chat", "centrify", "level1", "integrations"),

    # ── Entegrasyonlar ──
    _m("/ucmdb", "integrations"),
    _m("/integrations", "integrations", "virtualization", "exadata", "openshift"),

    # ── Ayrı atama gerektiren modüller ──
    _m("/knowledge", "knowledge"),
    _m("/applications", "applications"),
    _m("/custom-reports", "custom_reports"),
]

_RULES_BY_LEN = sorted(RULES, key=lambda r: len(r.prefix), reverse=True)

# (yöntemler | None=hepsi, yol regex, minimum rol)
ROLE_RULES: List[Tuple[Optional[FrozenSet[str]], "re.Pattern[str]", str]] = [
    (None, re.compile(r"^/windows/servers/[^/]+/run-ps$"), "admin"),
    (frozenset({"POST"}), re.compile(r"^/windows/adhoc$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/windows/servers/[^/]+/reboot$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/windows/servers/[^/]+/save-credentials$"), "operator"),
    (frozenset({"POST", "DELETE"}), re.compile(r"^/windows/global-credential(/.*)?$"), "admin"),
    (frozenset({"POST"}), re.compile(r"^/ansible/(adhoc|playbook)$"), "operator"),
    (frozenset({"POST", "PUT", "DELETE"}), re.compile(r"^/settings/credentials(/.*)?$"), "admin"),
    (frozenset({"POST"}), re.compile(r"^/servers/[^/]+/credentials$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/events/bulk-delete$"), "operator"),
    (frozenset({"POST", "DELETE"}), re.compile(r"^/rag/runbook/(ingest|ingest-pdf|documents)$"), "operator"),
    (frozenset({"DELETE"}), re.compile(r"^/rag/runbook/documents$"), "admin"),
    (frozenset({"POST", "PUT", "DELETE"}), re.compile(r"^/centrify-mgmt/.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/(hypervisors|exadata|openshift|ucmdb)/.*sync.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/(repos)/[^/]+/(sync|cancel-sync|sync-rhsm|sync-metadata)$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/monitoring/prometheus/sync.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/anomalies/run-cycle$"), "operator"),
]

_PREFIX = "/api/v1"


def _strip(path: str) -> str:
    p = path[len(_PREFIX):] if path.startswith(_PREFIX) else path
    return p or "/"


def find_rule(path: str) -> Optional[Rule]:
    """En uzun öneke sahip kural (path: /api/v1 öneki dahil ya da hariç)."""
    p = _strip(path)
    for r in _RULES_BY_LEN:
        if p == r.prefix or p.startswith(r.prefix + "/"):
            return r
    # nlq router öneksiz tanımlı: /ai/..., /collectors/...
    return None


def platform_from(path: str, query: Dict[str, str]) -> Optional[str]:
    """İstekteki platform bilgisi (query ?platform= veya /platform-reports/{platform}/...)."""
    p = _strip(path)
    if p.startswith("/platform-reports/"):
        seg = p.split("/")[2:3]
        if seg:
            return seg[0]
    v = (query.get("platform") or "").strip().lower()
    return v or None


def min_role_for(method: str, path: str) -> Optional[str]:
    p = _strip(path)
    best: Optional[str] = None
    for methods, rx, role in ROLE_RULES:
        if methods is not None and method.upper() not in methods:
            continue
        if rx.match(p):
            if best is None or ROLE_RANK[role] > ROLE_RANK[best]:
                best = role
    return best


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: int = 200
    detail: str = ""


def decide(
    *,
    role: str,
    modules: Iterable[str],
    method: str,
    path: str,
    query: Optional[Dict[str, str]] = None,
) -> Decision:
    """Bir isteğin izinli olup olmadığına karar verir (saf fonksiyon)."""
    method = method.upper()
    query = query or {}
    is_admin = role in ("admin", "superadmin")
    have = set(modules)

    rule = find_rule(path)
    if rule is None:
        return Decision(True) if is_admin else Decision(
            False, 403, "Bu alan için yetkiniz yok (sınıflandırılmamış uç nokta)"
        )

    if rule.mode == "admin" and not is_admin:
        return Decision(False, 403, "Bu işlem için en az 'admin' yetkisi gerekli")

    if rule.mode == "modules" and not is_admin:
        allowed = set(rule.modules)
        if method in ("GET", "HEAD"):
            allowed |= set(rule.read_extra)
        if not (allowed & have):
            names = ", ".join(rule.modules)
            return Decision(False, 403, f"Bu alan için modül yetkisi gerekli: {names}")

    # Platform parametresi (ortak AIOps uçları) — yalnız ilgili modüle sahipse
    plat = platform_from(path, query)
    if plat and not is_admin:
        need = PLATFORM_PARAM_TO_MODULE.get(plat)
        if need and need not in have:
            return Decision(False, 403, f"Bu alan için '{need}' modül yetkisi gerekli")

    need_role = min_role_for(method, _strip(path))
    if need_role and ROLE_RANK.get(role, 0) < ROLE_RANK[need_role]:
        return Decision(False, 403, f"Bu işlem için en az '{need_role}' yetkisi gerekli")

    return Decision(True)


def can_open_shell(role: str, modules: Iterable[str], module_id: str, min_role: str = "operator") -> bool:
    """WebSocket (terminal / pod exec / VM console) için modül + rol kontrolü."""
    if role in ("admin", "superadmin"):
        return True
    return module_id in set(modules) and ROLE_RANK.get(role, 0) >= ROLE_RANK[min_role]
