"""Esnaf veri merdiveni — ucuz SoT → pahalı SoT; reddetme yok.

Kullanıcı veri istediğinde mümkün olan yolları sırayla deneriz.
Çoklu retry / alternatif hostname denemesi YOK.

Sıra (genel):
  1) DB / son sync cache
  2) Prometheus (varsa)
  3) vCenter QueryPerf / db virt metrik
  4) SSH / WinRM (top, sar, collect, get_*)
"""
from __future__ import annotations

import re
from typing import FrozenSet, List, Optional, Sequence, Tuple

# Anlık / canlı kaynak tüketimi niyeti
_LIVE_RESOURCE_KW = (
    "anlık", "anlik", "canlı kaynak", "canli kaynak",
    "kaynak tüket", "kaynak tuket", "kaynak kullanım", "kaynak kullanim",
    "cpu kullanım", "cpu kullanim", "ram kullanım", "ram kullanim",
    "bellek kullanım", "bellek kullanim", "disk kullanım", "disk kullanim",
    "load average", "yük ortalama", "yuk ortalama",
    "top ", " top", "sar ", " sar", "vmstat", "iostat", "free -",
    "quickstats", "quick stats", "utilization", "kullanım oranı",
)

_VM_RE = re.compile(
    r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])"
    r"|sanal\s*makine|virtual\s*machine",
    re.I,
)

# Merdiven basamakları (retry yok)
LADDER_STEPS: Tuple[str, ...] = (
    "db",
    "prometheus",
    "vcenter_perf",
    "ssh",
)


def is_live_resource_query(message: str) -> bool:
    m = (message or "").lower()
    if not m.strip():
        return False
    return any(k in m for k in _LIVE_RESOURCE_KW)


def wants_guest_os_metrics(message: str) -> bool:
    """Guest OS içi metrik (SSH) de gerekir — yalnız hipervizör yetmez."""
    m = (message or "").lower()
    if not is_live_resource_query(m):
        return False
    # Açık guest/SSH isteği veya genel "sunucu/kaynak" (VM adı + anlık)
    if any(k in m for k in ("ssh", "guest", "top", "sar", "vmstat", "iostat", "df ", "içinden", "icinden")):
        return True
    if any(k in m for k in ("sunucu", "server", "kaynak", "cpu", "ram", "bellek", "yük", "yuk", "load")):
        return True
    return bool(_VM_RE.search(m)) or is_live_resource_query(m)


def ladder_system_addendum(*, has_prometheus: bool = False) -> str:
    """Tool / final prompt ek — esnaf sırası, retry yok."""
    prom_line = (
        "2) Prometheus/node-exporter (varsa PromQL — yoksa ATLA, 'yok' deyip DURMA)\n"
        if has_prometheus
        else "2) Prometheus — bu ortamda yok/boşsa ATLA; bahane etme, sonraki basamağa geç\n"
    )
    return (
        "\n\nESNAF VERİ MERDİVENİ (zorunlu — reddetme yok):\n"
        "Kullanıcı veri istedi: ne yapıp edip getir. 'İznim yok / toplanmadı / Prometheus yok' "
        "ile KAPATMA; sıradaki basamağı dene. Aynı hedefe çoklu retry / alternatif hostname YOK.\n"
        "Sıra (ucuz → pahalı):\n"
        "1) DB / son sync / db_list_vms / db_vm_detail (QuickStats cache)\n"
        f"{prom_line}"
        "3) vCenter: vcenter_perf_query (entity=vm, target=VM adı) veya db metrik alanları\n"
        "4) SSH READ_ONLY: get_* / run_diagnostic / collect (top, sar, vmstat, free, df) — "
        "guest anlık kullanım için asıl SoT çoğu zaman burasıdır\n"
        "Hiçbiri veri vermezse: hangi basamakların denendiğini ve hata özetini yaz.\n"
        "Yeterli veri geldiği basamakta dur; gereksiz pahalı çağrı yapma.\n"
    )


def domains_for_live_resource(
    base_domains: Optional[FrozenSet[str]],
    *,
    include_ssh: bool = True,
) -> FrozenSet[str]:
    """Anlık kaynak sorusunda vcenter + linux (SSH) domain birleşimi."""
    dom = set(base_domains or ())
    dom.add("infra")
    dom.add("vcenter")
    if include_ssh:
        dom.add("linux")
    return frozenset(dom)


def force_virt_linux_modules(modules: Sequence[str]) -> Tuple[str, ...]:
    out: List[str] = []
    for m in ("virt", "linux"):
        if m not in out:
            out.append(m)
    for m in modules:
        if m not in out:
            out.append(m)
    return tuple(out)
