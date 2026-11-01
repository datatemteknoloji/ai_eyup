"""RAG modül kapsamı (Adım 8R/R2): sohbetin modülüne göre runbook aramasını daraltır.

Kural: satır `metadata.module` ∈ kapsam, `general` veya etiketsiz (kullanıcı yüklemesi) → aranır; başka modülün
belgesi gelmez. `None` = kısıtsız (admin / modül belirsiz). Boş küme = yalnız `general`/etiketsiz.
Yalnız `runbook` koleksiyonu filtrelenir (incidents/knowledge_facts/metric_descriptions modül etiketi taşımaz — K4).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Set

# sohbet platformu / yönlendirici modülü → RAG modül etiketleri
_ROUTE_TO_RAG = {
    "linux": {"linux"},
    "exadata": {"exadata", "linux"},
    "windows": {"windows"},
    "virt": {"virtualization"},
    "virtualization": {"virtualization"},
    "openshift": {"openshift"},
    "ocp": {"openshift"},
    "automic": {"automic"},
}
# Plan/araç `domains` adları
_DOMAIN_TO_RAG = {
    "linux": {"linux"},
    "exadata": {"exadata", "linux"},
    "windows": {"windows"},
    "vcenter": {"virtualization"},
    "virt": {"virtualization"},
    "virtualization": {"virtualization"},
    "openshift": {"openshift"},
}


def _map(names: Iterable[str], table: dict) -> Set[str]:
    out: Set[str] = set()
    for n in names or ():
        out |= table.get(str(n).strip().lower(), set())
    return out


def modules_for_platform(platform: Optional[str]) -> Optional[Set[str]]:
    """Tek platformlu sohbet (Linux/Windows/OCP/Exadata/Sanallaştırma). Bilinmeyen platform → None (kısıtsız)."""
    p = (platform or "").strip().lower()
    return set(_ROUTE_TO_RAG[p]) if p in _ROUTE_TO_RAG else None


def modules_for_route(route_modules: Optional[Iterable[str]], allowed: Any = None) -> Optional[Set[str]]:
    """Unified/Admin: yönlendirici modülleri ∩ kullanıcının izinli modülleri (RBAC). `allowed=None` → kısıtsız kullanıcı."""
    routed = _map(route_modules or (), _ROUTE_TO_RAG)
    if allowed is None:
        return routed or None
    base = _map(allowed, _ROUTE_TO_RAG)
    return (routed & base) if routed else base


def modules_for_domains(domains: Optional[Iterable[str]], platform: Optional[str] = None) -> Optional[Set[str]]:
    """Araç döngüsü (`knowledge_search`): sohbet platformu tek modülse onu; yoksa domain'lerden; belirsiz → None."""
    plat = modules_for_platform(platform)
    if plat is not None:
        return plat
    dom = _map(domains or (), _DOMAIN_TO_RAG)
    return dom or None
