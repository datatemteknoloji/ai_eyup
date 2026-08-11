"""Chat canlı filo hedefleme politikası (Plan 2 Dalga 1 — TTFT).

Seçim/isim yokken tüm AI-ready filoya SSH/WinRM açmayı keser.
Açık filo/karşılaştır isteklerinde cap'li örneklem kullanır.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

# Kullanıcı açıkça filo taraması istediğinde cap'li örneklem açılır
# (geniş keyword seti: chat_full_scan_policy.wants_full_fleet)

UNSELECTED_LIVE_HINT = (
    "NOT: Canlı SSH/WinRM taraması için hedef seçilmedi. "
    "Filo genelinde anlık kullanım için Hedef menüsünden sunucu seçin, "
    "soruya sunucu adını/IP yazın, veya 'tüm sunucular / bütün liste / filo' deyin "
    "(varsayılan cap; 'tüm filo' + onay ile tek soruda hard max). Envanter "
    "(CPU çekirdek/RAM GB) aşağıda DB'den gelir; Prometheus metrikleri varsa onlar kullanılabilir."
)

FLEET_SAMPLE_HINT = (
    "NOT: Filo taraması istendi — canlı bağlantı üst sınır ile sınırlandı. "
    "Belirli sunucu için Hedef menüsünden seçin veya adını yazın. "
    "Tüm filo için 'tüm sunucular' deyip onaylayın."
)


def message_wants_fleet_scan(message: Optional[str]) -> bool:
    try:
        from app.services.chat_full_scan_policy import wants_full_fleet
        if wants_full_fleet(message):
            return True
    except Exception:
        pass
    m = (message or "").lower()
    if not m:
        return False
    extras = (
        "karşılaştır", "karsilastir", "compare", "side by side", "yan yana",
        "filo", "fleet",
    )
    return any(k in m for k in extras)


def get_chat_ssh_fleet_cap(default: int = 64) -> int:
    try:
        from app.services.chat_full_scan_policy import (
            effective_fleet_cap,
            is_full_scan_request,
        )
        if is_full_scan_request():
            return effective_fleet_cap(default)
        from app.services import runtime_settings
        n = int(runtime_settings.get_int("chat_ssh_fleet_cap"))
        return max(1, min(n, 512))
    except Exception:
        return default


def apply_live_collect_policy(
    candidates: Sequence[Any],
    *,
    message: str,
    has_explicit_selection: bool,
    mentioned: Optional[Sequence[Any]] = None,
) -> Tuple[List[Any], Optional[str], bool]:
    """Canlı SSH/WinRM hedeflerini belirle.

    Returns:
        live_targets: collect için sunucu listesi (cap uygulanmış olabilir)
        note: prompt'a eklenecek uyarı (veya None)
        allow_live: False ise canlı collect atlanmalı
    """
    mentioned = list(mentioned or [])
    candidates = list(candidates or [])
    cap = get_chat_ssh_fleet_cap()

    if mentioned:
        from app.services.linux_info_collector import cap_servers_for_ssh
        picked, note = cap_servers_for_ssh(mentioned, message, cap=cap)
        return picked, note, True

    if has_explicit_selection and candidates:
        from app.services.linux_info_collector import cap_servers_for_ssh
        picked, note = cap_servers_for_ssh(candidates, message, cap=cap)
        return picked, note, True

    if message_wants_fleet_scan(message) and candidates:
        from app.services.linux_info_collector import cap_servers_for_ssh
        picked, note = cap_servers_for_ssh(candidates, message, cap=cap)
        if note is None and len(candidates) > len(picked):
            note = FLEET_SAMPLE_HINT + f" ({len(picked)}/{len(candidates)})"
        elif note is None:
            note = FLEET_SAMPLE_HINT
        return picked, note, True

    # Seçim yok, filo isteği yok → canlı collect yok (TTFT)
    return [], UNSELECTED_LIVE_HINT if candidates else None, False


def inventory_lines_for_prompt(servers: Sequence[Any], *, limit: int = 40) -> str:
    """DB envanter özeti (canlı collect olmadan prompt'a)."""
    if not servers:
        return ""
    try:
        from app.services.chat_full_scan_policy import effective_fleet_cap, is_full_scan_request
        if is_full_scan_request():
            limit = max(limit, effective_fleet_cap())
    except Exception:
        pass
    lines = []
    for s in list(servers)[:limit]:
        name = getattr(s, "name", None) or "?"
        ip = getattr(s, "ip_address", None) or "-"
        os_info = getattr(s, "os_version", None) or getattr(s, "os_type", None) or "?"
        status = getattr(s, "status", None) or "?"
        cpu = getattr(s, "cpu_cores", None)
        mem = getattr(s, "memory_gb", None)
        extra = []
        if cpu is not None:
            extra.append(f"CPU={cpu} core")
        if mem is not None:
            extra.append(f"RAM={mem}GB")
        extra_str = (", " + ", ".join(extra)) if extra else ""
        lines.append(f"- {name} ({ip}): OS={os_info}, Durum={status}{extra_str}")
    more = len(servers) - limit
    head = f"AI Ready envanter ({len(servers)} sunucu"
    if more > 0:
        head += f", ilk {limit} gösteriliyor"
    head += " — DB, canlı tarama değil):\n"
    return head + "\n".join(lines)
