"""
Modül erişim politikası — SAYFA BAZLI yetkilendirme.

İlke:
- Bir modüle yetki verildiyse, o modülün sayfalarının çağırdığı tüm API'ler çalışır
  ("o sayfadaki her şeyi yapabilir").
- Modül, başka bir modülün sayfasına/API'sine geçiş HAKKI vermez. Bir modülün sayfası
  başka modülün verisini de kullanıyorsa bu açıkça ``GRANTS`` içinde (modül → sayfanın
  kullandığı uç) tanımlanır; listede olmayan hiçbir uç açılmaz.
- Admin / superadmin tümüne erişir.

Yapı:
- ``RULES``: yol öneki → "sahip" modüller (any-of). En uzun önek kazanır.
  ``ANY``: kimliği doğrulanmış herkes (uç noktanın kendi rol kontrolü geçerli).
  ``ADMIN``: yalnız admin. Eşleşmeyen /api/v1 yolu: yalnız admin (fail-closed);
  ``test_every_registered_route_is_classified`` yeni router'ın sınıflandırılmasını zorunlu kılar.
- ``GRANTS``: modül → (yöntemler, uç regex'i). Sayfa-içi çapraz kullanım (örn. Monitoring
  hub'ının Windows/OpenShift/sanallaştırma izleme uçları; sohbet sayfasının envanter özeti).
- ``ROLE_RULES``: yazma / komut çalıştırma uçları için minimum rol.
- ``platform=`` parametreli ortak uçlarda ilgili platform modülü ayrıca aranır.
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
    modules: Tuple[str, ...] = ()           # any-of (sahip modüller)
    mode: str = "modules"                   # modules | any | admin


def _m(prefix: str, *modules: str) -> Rule:
    return Rule(prefix, tuple(modules))


_ANY = lambda p: Rule(p, mode="any")        # noqa: E731
_ADMIN = lambda p: Rule(p, mode="admin")    # noqa: E731

_P = PLATFORM_MODULES

RULES: List[Rule] = [
    # ── Herkes (kimlik doğrulanmış) — uç noktaların kendi rol kontrolü geçerli ──
    _ANY("/auth"), _ANY("/public"), _ANY("/modules"), _ANY("/identity"), _ANY("/security"),
    _ANY("/audit"), _ANY("/platform"), _ANY("/platform-update"), _ANY("/settings"),
    # Yalnız admin sayfalarının kullandığı uçlar (AuditLog, Ayarlar)
    _ADMIN("/tasks"), _ADMIN("/rag"), _ADMIN("/mcp"),

    # ── Sohbet sayfaları (Tüm Altyapı / platform sohbetleri / Agent) ──
    _m("/chat", *_P, "ai_automation", "executive"),
    _m("/chat-turns", *_P, "ai_automation", "executive"),
    _m("/unified-chat", *_P, "ai_automation", "executive"),
    _m("/agent", "ai_automation"),

    # ── Sanallaştırma ──
    _m("/virt-insights", "virtualization"),
    _m("/hypervisors", "virtualization", "integrations"),

    # ── OpenShift ──
    _m("/ocp-insights", "openshift"),
    _m("/openshift", "openshift", "integrations"),

    # ── Exadata ──
    _m("/exadata", "exadata", "integrations"),

    # ── Windows ──
    _m("/windows", "windows"),
    _m("/windows-chat", "windows"),

    # ── Linux ──
    _m("/servers", "linux", "integrations", "knowledge"),
    _m("/packages", "linux"),
    _m("/repos", "linux"),
    _m("/updates", "linux"),
    _m("/snapshots", "linux"),
    _m("/ansible", "linux"),
    _m("/terminal", "linux"),

    # ── Paylaşılan AIOps veri uçları (platform parametresi ayrıca doğrulanır) ──
    _m("/events", *_P),
    _m("/incidents", *_P),
    _m("/anomalies", *_P),
    _m("/baseline", *_P),
    _m("/rca", *_P),
    _m("/alerts", *_P),
    _m("/compare", *_P),
    _m("/platform-reports", *_P),
    _m("/metrics", *_P, "monitoring"),
    _m("/monitoring", *_P, "monitoring"),
    _m("/ops", *_P),
    _m("/ops/executive-summary", "executive"),
    _m("/ops/executive-report", "executive"),
    _m("/ai", *_P),
    _m("/collectors", *_P),

    # ── Level 1 / Centrify ──
    _m("/level1", "level1"),
    _m("/centrify-mgmt", "centrify", "level1", "integrations"),
    _m("/centrify-chat", "centrify", "level1"),

    # ── Entegrasyonlar ──
    _m("/ucmdb", "integrations"),
    _m("/integrations", "integrations"),

    # ── Ayrı atama gerektiren modüller ──
    _m("/knowledge", "knowledge"),
    _m("/applications", "applications"),
    _m("/custom-reports", "custom_reports"),
]

_RULES_BY_LEN = sorted(RULES, key=lambda r: len(r.prefix), reverse=True)


@dataclass(frozen=True)
class Grant:
    """Bir modülün SAYFASININ başka bir alandan kullandığı uç."""
    module: str
    pattern: "re.Pattern[str]"
    methods: Optional[FrozenSet[str]] = None  # None → tüm yöntemler
    why: str = ""


def _g(module: str, regex: str, methods: Optional[Iterable[str]] = None, why: str = "") -> Grant:
    return Grant(module, re.compile(regex), frozenset(methods) if methods else None, why)


_GET = ("GET", "HEAD")

# Platform sohbet / "Tüm Altyapı" sayfaları envanter özeti + pin-fact için sunucu listesini okur
_CHAT_PAGE_MODULES = ("windows", "virtualization", "exadata", "openshift", "ai_automation", "executive")

GRANTS: List[Grant] = [
    # ── Monitoring hub: Linux / Windows / OpenShift / Sanallaştırma / Zabbix / Diğer sekmeleri ──
    _g("monitoring", r"^/windows/monitoring(/.*)?$", why="Monitoring hub › Windows"),
    _g("monitoring", r"^/openshift/monitoring(/.*)?$", why="Monitoring hub › OpenShift"),
    _g("monitoring", r"^/openshift/clusters$", _GET, "Monitoring hub › OpenShift küme seçici"),
    _g("monitoring", r"^/hypervisors/monitoring(/.*)?$", why="Monitoring hub › Sanallaştırma"),
    _g("monitoring", r"^/hypervisors/?$", _GET, "Monitoring hub › Sanallaştırma kaynak listesi"),

    # ── Windows sunucu sayfası hypervisor listesini okur; OpenShift MTV paneli VMware kaynaklarını okur ──
    _g("windows", r"^/hypervisors/?$", _GET, "Windows sunucular › VM/host bilgisi"),
    _g("openshift", r"^/hypervisors/?$", _GET, "OpenShift MTV paneli › VMware kaynakları"),

    # ── Sanallaştırma sayfası VM detay/arama için snapshot ve sunucu uçlarını kullanır ──
    _g("virtualization", r"^/snapshots/server/.*$", why="Hypervisors › VM detay / arama"),

    # ── Sohbet sayfaları: envanter özeti (sunucu / Windows özeti) ve pin-fact sunucu listesi ──
    *[_g(m, r"^/servers(/.*)?$", _GET, "Sohbet sayfası › envanter özeti / pin-fact")
      for m in _CHAT_PAGE_MODULES],
    *[_g(m, r"^/windows/servers/summary$", _GET, "Tüm Altyapı sohbeti › Windows özeti")
      for m in ("ai_automation", "executive")],
]

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
    (frozenset({"POST", "PUT", "DELETE"}), re.compile(r"^/centrify-mgmt/.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/(hypervisors|exadata|openshift|ucmdb)/.*sync.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/(repos)/[^/]+/(sync|cancel-sync|sync-rhsm|sync-metadata)$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/monitoring/prometheus/sync.*$"), "operator"),
    (frozenset({"POST"}), re.compile(r"^/anomalies/run-cycle$"), "operator"),
    # OpenShift › Planlama ve Denetim sayfaları yalnız admin (özet/değişiklik/olay zaman çizelgesi diğer sayfalarca kullanılır)
    (None, re.compile(r"^/ocp-insights/(capacity|reclaim|findings|node-risk|run|baseline)(/.*)?$"), "admin"),
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
    return None


def granted_by(have: Iterable[str], method: str, path: str) -> Optional[Grant]:
    """Kullanıcının modüllerinden biri, bu ucu sayfa-içi kullanım olarak açıyor mu?"""
    p = _strip(path)
    have = set(have)
    m = method.upper()
    for g in GRANTS:
        if g.module not in have:
            continue
        if g.methods is not None and m not in g.methods:
            continue
        if g.pattern.match(p):
            return g
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

    granted = False
    if rule.mode == "admin" and not is_admin:
        return Decision(False, 403, "Bu işlem için en az 'admin' yetkisi gerekli")

    if rule.mode == "modules" and not is_admin:
        if not (set(rule.modules) & have):
            if granted_by(have, method, path) is not None:
                granted = True
            else:
                names = ", ".join(rule.modules)
                return Decision(False, 403, f"Bu alan için modül yetkisi gerekli: {names}")

    # Platform parametresi (ortak AIOps uçları) — yalnız ilgili modüle sahipse
    plat = platform_from(path, query)
    if plat and not is_admin and not granted:
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
