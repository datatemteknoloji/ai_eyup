"""OpenShift / KubeVirt alan projeksiyonu — bilgi kirliliği önlemi.

Kullanıcı ne sordıysa yalnız onu döndür. Tam `get_vm_full_details` dump'ı
LLM bağlamına ve cevaba girmez; fields/question ile daraltılır.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

# Kimlik — her zaman korunur (hangi VM olduğu belli olsun)
_IDENTITY = ("name", "namespace")

# Belirsiz "VM bilgisi / özet" isteklerinde varsayılan kısa özet
DEFAULT_BRIEF_FIELDS: tuple = (
    "name",
    "namespace",
    "phase",
    "cpu_cores",
    "memory_gb",
    "ip_address",
    "node_name",
    "guest_os",
)

# Kullanıcı/alias → canonical alan (get_vm_full_details anahtarları)
FIELD_ALIASES: Dict[str, tuple] = {
    "name": ("name", "vm_name", "vm"),
    "namespace": ("namespace", "ns", "project", "proje"),
    "uid": ("uid",),
    "phase": ("phase", "status", "durum", "power", "printable_status", "runnable"),
    "run_strategy": ("run_strategy", "runstrategy", "run strategy"),
    "cpu_cores": ("cpu_cores", "cpu", "vcpu", "cores"),
    "cpu_sockets": ("cpu_sockets", "sockets"),
    "cpu_threads": ("cpu_threads", "threads"),
    "cpu_model": ("cpu_model",),
    "memory_gb": ("memory_gb", "memory", "ram", "bellek", "memory_mb"),
    "ip_address": ("ip_address", "ip", "guest_ip"),
    "node_name": ("node_name", "node", "worker", "host"),
    "guest_os": ("guest_os", "os", "işletim", "isletim"),
    "hostname": ("hostname", "guest_hostname"),
    "machine_type": ("machine_type", "machine"),
    "architecture": ("architecture", "arch", "amd64", "arm64"),
    "firmware": ("firmware", "bios", "uefi", "bootloader"),
    "labels": ("labels", "label", "etiket"),
    "annotations": ("annotations", "annotation"),
    "disks": ("disks", "disk", "pvc", "volume", "datavolume", "depolama"),
    "nics": ("nics", "nic", "interface", "network", "mac", "ağ", "ag"),
    "node_selector": ("node_selector", "nodeselector", "node selector"),
    "affinity": ("affinity", "anti-affinity", "antiaffinity"),
    "tolerations": ("tolerations", "toleration", "taint"),
    "dedicated_cpu_placement": ("dedicated_cpu_placement", "dedicated cpu", "cpu pinning", "pinning"),
    "cpu_numa": ("cpu_numa", "numa"),
    "hugepages": ("hugepages", "huge pages", "hugepage"),
    "eviction_strategy": ("eviction_strategy", "eviction"),
    "owner_references": ("owner_references", "owner"),
    "vmi_conditions": ("vmi_conditions", "conditions", "koşul", "kosul"),
    "boot_order": ("boot_order", "boot"),
    "launcher_pod": ("launcher_pod", "virt-launcher", "pod"),
    "created": ("created", "creation", "oluşturulma", "olusturulma"),
}

# Canonical → detail dict'teki gerçek anahtar(lar); birden fazlaysa hepsi alınır
_CANONICAL_KEYS: Dict[str, tuple] = {
    "name": ("name", "vm_name"),
    "namespace": ("namespace",),
    "uid": ("uid",),
    "phase": ("phase", "runnable"),
    "run_strategy": ("run_strategy",),
    "cpu_cores": ("cpu_cores",),
    "cpu_sockets": ("cpu_sockets",),
    "cpu_threads": ("cpu_threads",),
    "cpu_model": ("cpu_model",),
    "memory_gb": ("memory_gb", "memory_mb"),
    "ip_address": ("ip_address",),
    "node_name": ("node_name",),
    "guest_os": ("guest_os",),
    "hostname": ("hostname",),
    "machine_type": ("machine_type",),
    "architecture": ("architecture",),
    "firmware": ("firmware",),
    "labels": ("labels",),
    "annotations": ("annotations",),
    "disks": ("disks", "disk_names"),
    "nics": ("nics",),
    "node_selector": ("node_selector",),
    "affinity": ("affinity",),
    "tolerations": ("tolerations",),
    "dedicated_cpu_placement": ("dedicated_cpu_placement",),
    "cpu_numa": ("cpu_numa",),
    "hugepages": ("hugepages",),
    "eviction_strategy": ("eviction_strategy",),
    "owner_references": ("owner_references",),
    "vmi_conditions": ("vmi_conditions",),
    "boot_order": ("boot_order",),
    "launcher_pod": ("launcher_pod",),
    "created": ("created",),
}


def normalize_fields(fields: Optional[Sequence[str]]) -> List[str]:
    """Alias listesini canonical alanlara çevir; bilinmeyenleri at."""
    if not fields:
        return list(DEFAULT_BRIEF_FIELDS)
    out: List[str] = []
    alias_map: Dict[str, str] = {}
    for canon, aliases in FIELD_ALIASES.items():
        for a in aliases:
            alias_map[a.lower()] = canon
    for raw in fields:
        key = (raw or "").strip().lower()
        if not key:
            continue
        canon = alias_map.get(key) or (key if key in FIELD_ALIASES else None)
        if canon and canon not in out:
            out.append(canon)
    return out or list(DEFAULT_BRIEF_FIELDS)


def detect_requested_kubevirt_fields(message: str) -> List[str]:
    """Mesajdan istenen KubeVirt VM alanlarını çıkar.

    Belirli bir alan belirtilmemişse DEFAULT_BRIEF_FIELDS döner
    (50 özellik dump'ı değil, kısa özet).
    """
    m = (message or "").lower()
    if not m.strip():
        return list(DEFAULT_BRIEF_FIELDS)

    def has(*keywords: str) -> bool:
        return any(k in m for k in keywords)

    def has_token(*tokens: str) -> bool:
        return any(re.search(r"(?<![a-z0-9_])" + re.escape(t), m) for t in tokens)

    if has(
        "sadece isim", "sadece ad", "yalnız isim", "yalnızca isim",
        "yalniz isim", "isim yeterli", "adı yeterli",
    ):
        return ["name", "namespace"]

    # Açık "hepsi / tam detay / full" → tüm bilinen alanlar
    if has("tam detay", "full detail", "tüm alan", "tum alan", "hepsini ver", "tüm özellik", "tum ozellik"):
        return list(FIELD_ALIASES.keys())

    fields: List[str] = ["name", "namespace"]
    specific = False

    if has("runstrategy", "run strategy", "run_strategy", "rerunonfailure", "always", "halted"):
        fields.append("run_strategy"); specific = True
    if has("firmware", "bios", "uefi", "bootloader"):
        fields.append("firmware"); specific = True
    if has("pinning", "dedicated cpu", "dedicatedcpu", "cpu pin"):
        fields.append("dedicated_cpu_placement"); specific = True
    if has_token("numa") or has("cpu_numa"):
        fields.append("cpu_numa"); specific = True
    if has("hugepage", "huge page"):
        fields.append("hugepages"); specific = True
    if has("affinity", "anti-affinity", "antiaffinity"):
        fields.append("affinity"); specific = True
    if has("toleration", "taint"):
        fields.append("tolerations"); specific = True
    if has("node selector", "nodeselector", "node_selector"):
        fields.append("node_selector"); specific = True
    if has("eviction"):
        fields.append("eviction_strategy"); specific = True
    if has("annotation"):
        fields.append("annotations"); specific = True
    if has("label", "etiket") and not has("node selector"):
        fields.append("labels"); specific = True
    if has("owner", "sahip"):
        fields.append("owner_references"); specific = True
    if has("condition", "koşul", "kosul"):
        fields.append("vmi_conditions"); specific = True
    if has("disk", "pvc", "datavolume", "volume", "depolama"):
        fields.append("disks"); specific = True
    if has("nic", "interface", "mac", "ağ", "ag ", " network"):
        fields.append("nics"); specific = True
    if has_token("ip", "adres"):
        fields.append("ip_address"); specific = True
    if has_token("cpu") or has("vcpu", "işlemci", "islemci", "çekirdek", "cekirdek"):
        fields += ["cpu_cores", "cpu_sockets", "cpu_threads"]; specific = True
    if has("ram", "memory", "bellek"):
        fields.append("memory_gb"); specific = True
    if has("machine type", "machine_type", "q35"):
        fields.append("machine_type"); specific = True
    if has("architecture", "mimari", "amd64", "arm64"):
        fields.append("architecture"); specific = True
    if has("phase", "durum", "status", "çalışıyor", "calisiyor", "running"):
        fields.append("phase"); specific = True
    if has("node", "worker", "hangi host", "hangi node"):
        fields.append("node_name"); specific = True
    if has("işletim", "isletim", "guest os", "os type"):
        fields.append("guest_os"); specific = True
    if has("boot order", "boot_order"):
        fields.append("boot_order"); specific = True
    if has("launcher", "virt-launcher"):
        fields.append("launcher_pod"); specific = True
    if has_token("uid"):
        fields.append("uid"); specific = True

    if specific:
        return list(dict.fromkeys(fields))
    return list(DEFAULT_BRIEF_FIELDS)


def project_kubevirt_vm(
    detail: Dict[str, Any],
    fields: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """detail'den yalnız istenen alanları çıkar; kimlik alanları her zaman kalır."""
    if not isinstance(detail, dict):
        return {}
    canon = normalize_fields(fields)
    for ident in _IDENTITY:
        if ident not in canon:
            canon = [ident, *canon]
    out: Dict[str, Any] = {}
    for c in canon:
        keys = _CANONICAL_KEYS.get(c) or (c,)
        for k in keys:
            if k in detail:
                out[k] = detail[k]
    out["_fields_returned"] = [c for c in canon]
    out["_note"] = (
        "Yalnız istenen alanlar döndü (bilgi kirliliği önlemi). "
        "Daha fazla alan için fields=[...] veya soruda alanı belirt."
    )
    return out
