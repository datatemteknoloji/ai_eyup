"""Chat tool politikası — DB-first (özellikle virt / vCenter).

İlk fazda yalnızca DATABASE tool'ları (db_*) modele sunulur; sonuç stale/boş
ise veya faz adımı dolunca canlı vCenter tool'ları açılır. Virt kapsamında
Linux SSH araçları zaten domain filtresiyle kapalıdır; politika ek olarak
yanlış canlı çağrıları faz-1'de reddeder.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Set

# L1 — ucuz DB
DB_FIRST_TOOLS: FrozenSet[str] = frozenset({
    "infra_overview",
    "db_list_vms",
    "db_vm_detail",
    "db_list_datastores",
    "db_list_esx_hosts",
    "db_virt_alarms",
})

# L3 — canlı API (DB yetersizse)
LIVE_VCENTER_TOOLS: FrozenSet[str] = frozenset({
    "vcenter_ask",
    "vcenter_live_alarms",
    "vcenter_live_tasks",
})

# Virt sohbetinde asla (SSH / Linux teşhis)
SSH_DIAG_PREFIXES = ("get_", "run_diagnostic", "read_service", "list_free", "lvm_")

# İlk faz: en fazla bu kadar LLM adımı yalnız DB tool şeması
DB_FIRST_MAX_STEPS = 2


def should_use_db_first(
    *,
    platform: Optional[str],
    domains: Optional[frozenset],
) -> bool:
    """Virt sohbeti veya domain'de vcenter varsa DB-first uygula."""
    plat = (platform or "").strip().lower()
    if plat in ("virt", "hypervisor", "virtualization"):
        return True
    if domains is not None and "vcenter" in domains:
        return True
    return False


def filter_tool_specs(
    specs: List[Dict[str, Any]],
    allowed: Set[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in specs:
        fn = (s.get("function") or {}) if isinstance(s, dict) else {}
        name = fn.get("name") or ""
        if name in allowed:
            out.append(s)
    return out


def db_first_phase_allowed_names(all_spec_names: Set[str]) -> Set[str]:
    """Faz-1: DB tool'ları ∩ mevcut şema."""
    return set(DB_FIRST_TOOLS) & all_spec_names


def live_unlocked_allowed_names(all_spec_names: Set[str]) -> Set[str]:
    """Faz-2+: DB + canlı vCenter (+ OCP virt tool'ları domain'deyse)."""
    base = set(DB_FIRST_TOOLS) | set(LIVE_VCENTER_TOOLS)
    # KubeVirt / OCP live — virt domain'de kalabilir
    base |= {"list_kubevirt_vms", "openshift_ask", "list_ocp_pods", "list_ocp_events"}
    return base & all_spec_names


def result_needs_live_escalation(tool_name: str, result: Any) -> bool:
    """DB tool çıktısı yetersizse canlı faza geç."""
    if tool_name not in DB_FIRST_TOOLS:
        return False
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return True
    if result.get("stale") is True:
        return True
    # Liste boş
    for key in ("vms", "datastores", "hosts", "alarms"):
        if key in result and isinstance(result.get(key), list) and len(result[key]) == 0:
            return True
    if result.get("count") == 0 and any(
        k in result for k in ("vms", "datastores", "hosts", "alarms")
    ):
        return True
    return False


def tool_blocked_in_db_first_phase(name: str) -> Optional[str]:
    """Faz-1'de yasaklı tool çağrısı için model mesajı."""
    if name in DB_FIRST_TOOLS:
        return None
    if name in LIVE_VCENTER_TOOLS:
        return (
            f"'{name}' henüz kapalı (DB-first fazı). Önce db_list_vms / "
            "db_list_datastores / db_list_esx_hosts / db_virt_alarms / db_vm_detail "
            "çağır. Sonuç stale veya boşsa canlı araçlar sonraki adımda açılır."
        )
    if name.startswith(SSH_DIAG_PREFIXES) or name.startswith("win_"):
        return (
            f"'{name}' sanallaştırma/DB-first kapsamında değil "
            "(SSH/WinRM kapalı). DB veya vCenter araçlarını kullan."
        )
    return None


DB_FIRST_SYSTEM_ADDENDUM = (
    "\n\nDB-FIRST POLİTİKA (zorunlu):\n"
    "- İlk adımlarda YALNIZCA db_list_vms, db_vm_detail, db_list_datastores, "
    "db_list_esx_hosts, db_virt_alarms, infra_overview kullan.\n"
    "- vcenter_ask / vcenter_live_* araçları yalnızca DB sonucu stale=true, "
    "boş liste veya hata döndükten SONRA (sistem 'canlı araçlar açıldı' derse) kullan.\n"
    "- Linux SSH get_* / run_diagnostic bu kapsamda YASAK.\n"
    "- Cevabında as_of / stale bilgisini kısaca belirt.\n"
)
