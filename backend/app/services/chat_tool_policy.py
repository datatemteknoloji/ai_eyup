"""Chat tool politikası — DB-first (özellikle virt / vCenter).

İlk fazda db_* öncelikli; stale/boş veya faz dolunca canlı vCenter açılır.
Esnaf merdiveni: domain'de linux/windows varsa SSH/WinRM basamağı serbest
(Prometheus yok diye reddetme).
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
    "db_virt_cross_match",
})

# L3 — canlı API (DB yetersizse)
LIVE_VCENTER_TOOLS: FrozenSet[str] = frozenset({
    "vcenter_ask",
    "vcenter_live_alarms",
    "vcenter_live_tasks",
    "vcenter_perf_query",
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
    for key in ("vms", "datastores", "hosts", "alarms", "rows"):
        if key in result and isinstance(result.get(key), list) and len(result[key]) == 0:
            return True
    if result.get("count") == 0 and any(
        k in result for k in ("vms", "datastores", "hosts", "alarms", "rows")
    ):
        return True
    return False


def tool_blocked_in_db_first_phase(
    name: str,
    *,
    domains: Optional[frozenset] = None,
) -> Optional[str]:
    """Faz-1'de yasaklı tool çağrısı için model mesajı.

    vcenter_perf_query istisna: Monitor Disk Rate/Requests DB'de yok;
    READ-ONLY QueryPerf faz-1'de de serbest (mutate değil).
    domains içinde linux/windows varsa SSH/WinRM esnaf merdiveninde serbest.
    """
    if name in DB_FIRST_TOOLS:
        return None
    if name == "vcenter_perf_query":
        return None
    if name in LIVE_VCENTER_TOOLS:
        return (
            f"'{name}' henüz kapalı (DB-first fazı). Önce db_list_vms / "
            "db_list_datastores / db_list_esx_hosts / db_virt_alarms / "
            "db_virt_cross_match / db_vm_detail çağır. "
            "Anlık Disk Rate/CPU için vcenter_perf_query kullanılabilir. "
            "Diğer canlı araçlar sonraki adımda açılır."
        )
    if name.startswith(SSH_DIAG_PREFIXES) or name.startswith("win_"):
        dom = domains or frozenset()
        if name.startswith("win_") and "windows" in dom:
            return None
        if (not name.startswith("win_")) and "linux" in dom:
            return None  # esnaf: SSH basamağı açık
        return (
            f"'{name}' sanallaştırma/DB-first kapsamında değil "
            "(SSH/WinRM kapalı). DB veya vCenter araçlarını kullan."
        )
    return None


DB_FIRST_SYSTEM_ADDENDUM = (
    "\n\nDB-FIRST POLİTİKA (zorunlu):\n"
    "- İlk adımlarda öncelik: db_list_vms, db_vm_detail, db_list_datastores, "
    "db_list_esx_hosts, db_virt_alarms, db_virt_cross_match, infra_overview.\n"
    "- Domain'de linux varsa SSH get_* / run_diagnostic SERBEST (esnaf merdiveni basamak 4); "
    "Prometheus yoksa guest anlık metrik için SSH kullan — 'iznim yok' deme.\n"
    "- VM disk adet/boyut: db_list_vms (disk_gb, disk_count, disks[]) — tek çağrı; "
    "27× db_vm_detail yapma. disk_gb dolu satıra 'toplanmadı' YAZMA.\n"
    "- Kullanıcı özellik listesi verdiyse fields=[...] geç (ESXi/VM/datastore); "
    "disk_gb/disk_count yine korunur.\n"
    "- Birden fazla SoT'u (host+VM+datastore+alarm) eşleştirmek için "
    "db_virt_cross_match(join_on=host|datastore|entity) kullan — elle birleştirme.\n"
    "- Monitor Disk Rate / Disk Requests / canlı CPU-disk-net için "
    "vcenter_perf_query. metrics=[disk_rate] veya [disk_requests,cpu]; yalnız istenen metrikler.\n"
    "- vcenter_ask / vcenter_live_* yalnız DB stale/boş/hata SONRASI "
    "(sistem 'canlı araçlar açıldı' derse). Hepsi READ-ONLY; write/mutate yok.\n"
    "- Cevabında as_of / stale / SoT etiketini kısaca belirt.\n"
)
