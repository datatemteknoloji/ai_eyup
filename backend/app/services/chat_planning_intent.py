"""Cross-platform planlama / migrasyon niyeti (Unified TTFT).

vCenter→OpenShift taşıma, kapasite/kaynak planı gibi sorularda:
- Linux/Windows SSH araçlarını açma (gereksiz tur)
- vCenter + OpenShift + infra domain
- Daha az agentic adım + erken final
- Belirsizse önce seçenek sor; follow-up'ta derinleştir
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

_VCENTER_KW = (
    "vcenter", "vsphere", "esxi", "esx", "vmware", "datastore",
    "sanallaştır", "sanallastir", "hypervisor", "virtual machine", " sanal ",
    "sanal makine", "vmdk", "disk rate", "disk requests",
)
# vm / vms / vmler / vmlerdeki (Türkçe ekler) — yalnız "vm" substring değil
_VM_TOKEN_RE = re.compile(
    r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])",
    re.IGNORECASE,
)

_OCP_KW = (
    "openshift", "ocp", "kubernetes", "k8s", "kubevirt", "mtv", "migration toolkit",
    "namespace", "cluster",
)
_MIGRATE_KW = (
    "taşı", "tasi", "taşıyabilir", "tasinabilir", "taşıma", "tasima",
    "migrate", "migration", "move to", "aktar", "göç", "goc",
)
_PLAN_KW = (
    "planlama", "kaynak plan", "kapasite plan", "capacity plan", "capacity planning",
    "sizing", "boyutlandır", "boyutlandir", "overcommit", "fit eder", "sığar", "sigar",
    "kaynak ihtiyacı", "kaynak ihtiyaci", "ne kadar cpu", "ne kadar ram",
    "kaynak kapasite", "cluster kapasite", "sığar mı", "sigar mi",
)
_DEPTH_KW = (
    "daha kapsamlı", "daha kapsamli", "kapsamlı cevap", "kapsamli cevap",
    "daha detay", "daha ayrıntılı", "daha ayirintili", "detaylı plan", "detayli plan",
    "derinleştir", "derinlestir", "daha derin", "genişlet", "genislet",
    "daha fazla detay", "ayrıntılı", "ayrintili",
)

# Kullanıcı kapsamı netleştirmiş sayılır
_SCOPE_FEASIBILITY = (
    "fizibilite", "fizibilete", "taşınabilir mi", "tasinabilir mi",
    "sadece özet", "sadece ozet", "kısa bakış", "kisa bakis", "kabaca",
    "seçenek 1", "secenek 1", "seçenek1", "secenek1",
)
_SCOPE_DETAILED = (
    "detaylı kaynak", "detayli kaynak", "kaynak planı yap", "kaynak plani yap",
    "vm listesi", "cpu/ram", "sizing yap", "seçenek 2", "secenek 2", "seçenek2", "secenek2",
)
_SCOPE_MTV = (
    "mtv", "migration toolkit", "migration plan", "taşıma planı", "tasima plani",
    "seçenek 3", "secenek 3", "seçenek3", "secenek3",
)

_CLARIFY_TTL = 45 * 60


def message_has_vcenter_intent(message: Optional[str]) -> bool:
    """vCenter/ESXi/VM envanter veya sanallaştırma niyeti (agentic kapısı)."""
    m = (message or "").lower()
    if not m.strip():
        return False
    if any(k in m for k in _VCENTER_KW):
        return True
    if _VM_TOKEN_RE.search(m):
        return True
    return False


def message_has_ocp_intent(message: Optional[str]) -> bool:
    m = (message or "").lower()
    return any(k in m for k in _OCP_KW)


def is_cross_platform_planning(message: Optional[str]) -> bool:
    """vCenter↔OCP taşıma / kapasite / kaynak planı sorusu mu?"""
    m = (message or "").lower()
    if not m:
        return False
    migrate = any(k in m for k in _MIGRATE_KW)
    plan = any(k in m for k in _PLAN_KW)
    vc = message_has_vcenter_intent(m)
    ocp = message_has_ocp_intent(m)
    # Guest/SSH/df + virt envanter soruları MTV planlama değil
    guestish = any(
        k in m for k in (
            "ssh", "guest", "df -", "df -h", "vmdk", "disk adet", "disk boyut",
            "her bir disk", "içinden", "icinden",
        )
    )
    if guestish and not ocp and not migrate:
        return False
    if migrate and (vc or ocp):
        return True
    if plan and (vc or ocp):
        return True
    if vc and ocp and (migrate or plan or "kaynak" in m):
        return True
    return False


def is_depth_followup(message: Optional[str]) -> bool:
    m = (message or "").lower().strip()
    if not m:
        return False
    return any(k in m for k in _DEPTH_KW)


def resolve_planning_scope(message: Optional[str]) -> Optional[str]:
    """Kullanıcı kapsam seçtiyse: feasibility | detailed | mtv."""
    m = (message or "").lower().strip()
    if not m:
        return None
    # Tek başına "1" / "2" / "3" (önceki netleştirme cevabına yanıt)
    if m in ("1", "1.", "①"):
        return "feasibility"
    if m in ("2", "2.", "②"):
        return "detailed"
    if m in ("3", "3.", "③"):
        return "mtv"
    if any(k in m for k in _SCOPE_MTV):
        return "mtv"
    if any(k in m for k in _SCOPE_DETAILED):
        return "detailed"
    if any(k in m for k in _SCOPE_FEASIBILITY):
        return "feasibility"
    return None


def planning_needs_clarification(
    message: Optional[str],
    *,
    is_followup: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
) -> bool:
    """İlk belirsiz planlama sorusunda seçenek sorulsun mu?"""
    if not is_cross_platform_planning(message):
        return False
    if resolve_planning_scope(message):
        return False
    if is_depth_followup(message):
        return False
    # Önceki turda seçenek sorduk; kullanıcı yine belirsiz yazdıysa tekrar sorma —
    # agentic'e bırak (veya scope parse edilecek)
    if clarification_pending and is_followup:
        return False
    # İlk net planlama sorusu (veya follow-up değil)
    if not is_followup:
        return True
    # Follow-up ama episode yok ve pending yok → yine netleştir
    if not has_episode and not clarification_pending:
        return True
    return False


def should_reopen_planning_agentic(
    message: Optional[str],
    *,
    wants_openshift: bool = False,
    has_episode: bool = False,
    clarification_pending: bool = False,
    is_followup: bool = False,
) -> bool:
    """Follow-up / seçim sonrası agentic yeniden açılsın mı?"""
    if resolve_planning_scope(message):
        return True
    # "daha kapsamlı" — önceki tur (episode, netleştirme veya herhangi follow-up)
    if is_depth_followup(message) and (has_episode or clarification_pending or is_followup):
        return True
    if is_cross_platform_planning(message):
        return True
    if wants_openshift or message_has_vcenter_intent(message):
        return True
    return False


def planning_tool_domains(
    message: Optional[str],
    *,
    wants_openshift: bool = False,
    linux_specific: bool = False,
    windows_specific: bool = False,
) -> Optional[FrozenSet[str]]:
    """Unified agentic domain filtresi."""
    vc = message_has_vcenter_intent(message)
    ocp = wants_openshift or message_has_ocp_intent(message)
    planning = is_cross_platform_planning(message) or is_depth_followup(message)
    scope = resolve_planning_scope(message)

    if planning or scope or (vc and ocp):
        return frozenset({"vcenter", "openshift", "infra"})
    if ocp and not linux_specific and not windows_specific and not vc:
        return frozenset({"openshift", "infra"})
    if vc and not linux_specific and not windows_specific and not ocp:
        return frozenset({"vcenter", "infra"})
    return None


def planning_agentic_limits(
    message: Optional[str],
    *,
    depth: bool = False,
) -> Tuple[bool, int, int]:
    """(is_planning, max_steps, stop_after_tools)."""
    scope = resolve_planning_scope(message)
    planning = is_cross_platform_planning(message) or bool(scope) or depth
    if not planning:
        return False, 0, 0
    try:
        from app.services import runtime_settings
        base = int(runtime_settings.get_int("unified_chat_planning_max_tool_steps"))
    except Exception:
        base = 2
    base = max(1, min(base, 6))

    if scope == "mtv" or depth or is_depth_followup(message):
        max_steps = min(4, max(base, 3))
        stop_after = min(3, max_steps)
    elif scope == "detailed":
        max_steps = min(3, max(base, 2))
        stop_after = min(3, max_steps)
    elif scope == "feasibility":
        max_steps = min(2, base)
        stop_after = 1
    else:
        max_steps = base
        stop_after = min(2, max_steps)
    return True, max_steps, stop_after


PLANNING_CLARIFY_OPTIONS: List[Dict[str, str]] = [
    {
        "id": "feasibility",
        "label": "1) Fizibilite özeti",
        "prompt": "Fizibilite: vCenter VM'lerimi OpenShift'e taşıyabilir miyim? Kısa kapasite özeti yeter.",
    },
    {
        "id": "detailed",
        "label": "2) Detaylı kaynak planı",
        "prompt": "Detaylı kaynak planı: vCenter → OpenShift için CPU/RAM/disk sizing ve taşınabilirlik analizi yap.",
    },
    {
        "id": "mtv",
        "label": "3) MTV / taşıma planı",
        "prompt": "MTV odaklı taşıma planı: vCenter'dan OpenShift'e Migration Toolkit yaklaşımı ve adımlar.",
    },
]


def build_planning_clarification() -> Dict[str, Any]:
    """SSE + prompt için netleştirme metni ve seçenekler."""
    lines = [
        "Bu isteği doğru derinlikte yanıtlamak için kapsamı netleştirelim. "
        "Hangisini istersiniz?",
        "",
    ]
    for opt in PLANNING_CLARIFY_OPTIONS:
        lines.append(f"- **{opt['label']}**")
    lines.append("")
    lines.append("_İsterseniz 1 / 2 / 3 yazın veya aşağıdaki seçeneklerden birine tıklayın._")
    return {
        "text": "\n".join(lines),
        "options": list(PLANNING_CLARIFY_OPTIONS),
    }


def _clarify_key(session_id: int, platform: str = "unified") -> str:
    return f"ainew:plan_clarify:{platform}:{int(session_id)}"


def set_planning_clarification_pending(session_id: Optional[int], *, platform: str = "unified") -> None:
    if not session_id:
        return
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if not r:
            return
        r.setex(_clarify_key(session_id, platform), _CLARIFY_TTL, json.dumps({"pending": True}))
    except Exception as e:
        logger.debug("plan clarify set: %s", e)


def clear_planning_clarification_pending(session_id: Optional[int], *, platform: str = "unified") -> None:
    if not session_id:
        return
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if not r:
            return
        r.delete(_clarify_key(session_id, platform))
    except Exception as e:
        logger.debug("plan clarify clear: %s", e)


def has_planning_clarification_pending(session_id: Optional[int], *, platform: str = "unified") -> bool:
    if not session_id:
        return False
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if not r:
            return False
        return bool(r.get(_clarify_key(session_id, platform)))
    except Exception:
        return False


PLANNING_SYSTEM_ADDENDUM = (
    "\n\nMOD — KAPASİTE / MİGRASYON PLANI (hızlı yol):\n"
    "- Amaç: TAŞINABİLİRLİK ve KAYNAK PLANI taslağı.\n"
    "- En fazla 1–2 READ_ONLY araç: ÖNCE infra_overview / db_list_datastores / "
    "db_list_vms / db_list_esx_hosts; stale veya boşsa vcenter_ask veya openshift_ask.\n"
    "- Pod listesi / event dump / SSH komutları YAPMA.\n"
    "- Yeterli özet gelince HEMEN tool_call üretmeden bırak; nihai planı sohbet cevabı "
    "üretecek. Aynı soruyu tekrar tekrar araçlarla derinleştirme.\n"
    "- Linux/Windows SSH get_* araçlarını bu soruda KULLANMA.\n"
)

PLANNING_DEPTH_ADDENDUM = (
    "\n\nMOD — DERİN KAPSAM (kullanıcı daha kapsamlı istedi):\n"
    "- Önceki özeti genişlet: db_* yetersizse vcenter_ask + openshift_ask "
    "(ve gerekirse infra_overview).\n"
    "- Hâlâ pod dump / SSH get_* YAPMA; kapasite ve taşınabilirlik kanıtına odaklan.\n"
    "- 2–3 tool yeterli; sonra tool_call üretmeden bırak.\n"
)
