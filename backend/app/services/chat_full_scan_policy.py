"""Chat platformları için ortak “tam filo / tüm liste” politikası.

- Geniş keyword’ler: tüm filo, tüm sunucular, bütün liste, all servers, …
- Varsayılan cap: `chat_ssh_fleet_cap` (veya virt için VM list limit)
- “Tam kapsam” + aday sayısı > cap → uyarı → onay
- Onay yalnızca **o sorunun** cevabında hard_max; ContextVar ile istek bitince sıfırlanır
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CLARIFY_TTL = 15 * 60
_request_fleet_cap: ContextVar[Optional[int]] = ContextVar("chat_fleet_cap_override", default=None)
_request_full_scan: ContextVar[bool] = ContextVar("chat_full_fleet_scan", default=False)

_mem_lock = threading.Lock()
_mem_pending: Dict[str, Dict[str, Any]] = {}

# Onay / red (satırın tamamı)
_CONFIRM_PATTERNS = re.compile(
    r"^\s*(evet|onay|onayl[ıi]yorum|kabul|devam|tamam(\s*devam)?|"
    r"yes|ok|okay|proceed|confirm(ed)?|do\s*it)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_DECLINE_PATTERNS = re.compile(
    r"^\s*(hay[ıi]r|iptal|vazge[cç]|istemiyorum|no|cancel|abort)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

# “Tüm X / bütün Y / hepsi / limitsiz …” — platform-agnostik
_FULL_FLEET_PATTERNS = re.compile(
    r"("
    # TR — tüm / bütün + hedef
    r"t[uü]m\s*(filo|liste|envanter|kay[ıi]t|host|sunucu|server|linux|windows|"
    r"vm|sanal(\s*makine)?|makine|pod|namespace|cluster|node|esx|hypervisor)"
    r"|b[uü]t[uü]n\s*(filo|liste|envanter|kay[ıi]t|host|sunucu|server|linux|windows|"
    r"vm|sanal(\s*makine)?|makine|pod|namespace|cluster|node)"
    r"|t[uü]m\s*filodaki|filodaki\s*hepsi|filo\s*geneli|filo\s*tarama"
    r"|her\s*(bir\s*)?(sunucu|host|server|vm|pod|node|makine)"
    r"|komple\s*(liste|envanter|filo|tarama|rapor)"
    r"|hepsini\s*(listele|ver|g[oö]ster|getir|yaz|tara|kontrol)"
    r"|hepsinde|hepsine|hepsi\s*i[cç]in|t[uü]m[uü]nde|t[uü]m[uü]n[uü]"
    r"|limit\s*olmadan|limitsiz|s?ınırs[ıi]z|cap\s*olmadan"
    r"|eksiksiz\s*(liste|envanter|filo)|tam\s*(liste|envanter|filo|kapsam)"
    # EN
    r"|all\s*(servers?|hosts?|vms?|nodes?|pods?|namespaces?|clusters?|inventory|fleet|machines?)"
    r"|every\s*(server|host|vm|node|pod|machine)"
    r"|entire\s*(fleet|inventory|estate|list)"
    r"|whole\s*(fleet|inventory|list)"
    r"|full\s*(fleet|inventory|scan|list)"
    r"|without\s*(a\s*)?limit|no\s*limit|uncapped"
    r"|scan\s*(the\s*)?(whole|entire|full)\s*(fleet|inventory)"
    r")",
    re.IGNORECASE,
)


def wants_full_fleet(question: str) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    return bool(_FULL_FLEET_PATTERNS.search(q))


# Geriye dönük alias (virt)
wants_full_inventory = wants_full_fleet


def is_confirm_message(question: str) -> bool:
    return bool(_CONFIRM_PATTERNS.match((question or "").strip()))


def is_decline_message(question: str) -> bool:
    return bool(_DECLINE_PATTERNS.match((question or "").strip()))


def get_default_fleet_cap() -> int:
    try:
        from app.services import runtime_settings as rts
        return max(1, min(int(rts.get_int("chat_ssh_fleet_cap")), 512))
    except Exception:
        return 64


def get_hard_max_fleet_cap() -> int:
    try:
        from app.services import runtime_settings as rts
        return max(50, min(int(rts.get_int("chat_fleet_hard_max")), 20000))
    except Exception:
        return 5000


def set_request_fleet_cap(limit: Optional[int], *, full_scan: bool = False) -> Token:
    _request_full_scan.set(bool(full_scan))
    return _request_fleet_cap.set(limit)


def reset_request_fleet_cap(token: Token) -> None:
    try:
        _request_fleet_cap.reset(token)
    except Exception:
        _request_fleet_cap.set(None)
    _request_full_scan.set(False)


def effective_fleet_cap(default: Optional[int] = None) -> int:
    override = _request_fleet_cap.get()
    if override is not None and int(override) > 0:
        return max(1, min(int(override), 20000))
    base = get_default_fleet_cap() if default is None else int(default)
    return max(1, min(base, 512))


def is_full_scan_request() -> bool:
    return bool(_request_full_scan.get())


def _key(session_id: int, platform: str) -> str:
    return f"ainew:full_fleet:{platform}:{int(session_id)}"


def set_full_scan_pending(
    session_id: Optional[int],
    *,
    question: str,
    item_count: int,
    platform: str = "linux",
    kind: str = "sunucu",
) -> None:
    if not session_id:
        return
    payload = {
        "question": question,
        "item_count": int(item_count),
        "default_cap": get_default_fleet_cap(),
        "kind": kind,
        "platform": platform,
        "ts": time.time(),
    }
    raw = json.dumps(payload, ensure_ascii=False)
    k = _key(session_id, platform)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r:
            r.setex(k, _CLARIFY_TTL, raw)
            return
    except Exception as e:
        logger.debug("full_fleet redis set: %s", e)
    with _mem_lock:
        _mem_pending[k] = {**payload, "_exp": time.time() + _CLARIFY_TTL}


def get_full_scan_pending(
    session_id: Optional[int], *, platform: str = "linux"
) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    k = _key(session_id, platform)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r:
            raw = r.get(k)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                return json.loads(raw)
    except Exception as e:
        logger.debug("full_fleet redis get: %s", e)
    with _mem_lock:
        item = _mem_pending.get(k)
        if not item:
            return None
        if float(item.get("_exp") or 0) < time.time():
            _mem_pending.pop(k, None)
            return None
        return {kk: vv for kk, vv in item.items() if not kk.startswith("_")}


def clear_full_scan_pending(session_id: Optional[int], *, platform: str = "linux") -> None:
    if not session_id:
        return
    k = _key(session_id, platform)
    try:
        from app.core.redis_client import get_redis
        r = get_redis()
        if r:
            r.delete(k)
    except Exception as e:
        logger.debug("full_fleet redis del: %s", e)
    with _mem_lock:
        _mem_pending.pop(k, None)


def build_full_fleet_clarification(
    *,
    item_count: int,
    default_cap: Optional[int] = None,
    kind: str = "sunucu",
) -> str:
    cap = default_cap if default_cap is not None else get_default_fleet_cap()
    hard = get_hard_max_fleet_cap()
    show = min(int(item_count), int(hard))
    return (
        f"### Tam {kind} listesi / filo taraması — onay gerekli\n\n"
        f"Bu istek **tüm {kind}** / filo kapsamı gibi görünüyor "
        f"(aday ≈ **{item_count}**; varsayılan üst sınır **{cap}**).\n\n"
        f"Onaylarsanız **yalnızca bu soru** için tavan **{show}** olur; "
        "cevap bittikten sonra sonraki sorular yine varsayılan limite döner.\n\n"
        "**Uyarı:** Geniş tarama **uzun sürebilir**, zaman aşımına uğrayabilir "
        "veya kısmen tamamlanmayabilir (SSH/WinRM/API yükü).\n\n"
        "- Devam: **evet** / **onaylıyorum** / **devam**\n"
        "- Vazgeç: **hayır** / **iptal**\n"
    )


def count_fleet_candidates(db, *, platform: str) -> int:
    """Platforma göre aday sayısı (AI-ready / VM / OCP)."""
    plat = (platform or "linux").strip().lower()
    try:
        from app.models.server import Server
        from app.services.platform_scope import (
            is_linux_server,
            is_windows_server,
            is_vm,
            vm_filter_condition,
        )

        if plat in ("virt", "hypervisor", "virtualization"):
            return int(db.query(Server).filter(vm_filter_condition()).count())

        if plat == "windows":
            rows = db.query(Server).all()
            wins = [s for s in rows if is_windows_server(s)]
            ai = [s for s in wins if getattr(s, "ai_ready", False)]
            return len(ai) if ai else len(wins)

        if plat == "openshift":
            try:
                from app.models.openshift import OpenShiftCluster
                return max(1, int(db.query(OpenShiftCluster).count()))
            except Exception:
                return 0

        if plat == "unified":
            try:
                return int(db.query(Server).filter(Server.ai_ready == True).count())  # noqa: E712
            except Exception:
                return int(db.query(Server).count())

        # linux / exadata / default — fiziksel/AI-ready Linux
        rows = db.query(Server).all()
        linux = [s for s in rows if is_linux_server(s) and not is_vm(s)]
        ai = [s for s in linux if getattr(s, "ai_ready", False)]
        return len(ai) if ai else len(linux)
    except Exception as e:
        logger.debug("count_fleet_candidates: %s", e)
        return 0


def kind_label(platform: str) -> str:
    p = (platform or "").lower()
    if p in ("virt", "hypervisor", "virtualization"):
        return "VM"
    if p == "windows":
        return "Windows sunucu"
    if p == "openshift":
        return "OpenShift küme/workload"
    if p == "unified":
        return "sunucu / hedef"
    return "sunucu"


def resolve_full_scan_turn(
    db,
    *,
    session_id: Optional[int],
    message: str,
    platform: str,
) -> Dict[str, Any]:
    """Chat girişlerinde ortak karar.

    Returns dict:
      action: "proceed" | "clarify" | "decline" | "confirmed"
      work_message: str  (confirmed ise orijinal soru)
      clarification / decline_text
      full_scan: bool
    """
    plat = (platform or "linux").strip().lower()
    pending = get_full_scan_pending(session_id, platform=plat)
    kind = kind_label(plat)

    if pending and is_confirm_message(message):
        clear_full_scan_pending(session_id, platform=plat)
        return {
            "action": "confirmed",
            "work_message": (pending.get("question") or message).strip(),
            "full_scan": True,
            "item_count": pending.get("item_count"),
        }
    if pending and is_decline_message(message):
        clear_full_scan_pending(session_id, platform=plat)
        return {
            "action": "decline",
            "work_message": message,
            "full_scan": False,
            "decline_text": (
                f"Tamam — tam {kind} / filo taraması iptal edildi. "
                f"Sonraki sorularda varsayılan üst sınır ({get_default_fleet_cap()}) geçerli."
            ),
        }
    if wants_full_fleet(message):
        n = count_fleet_candidates(db, platform=plat)
        cap = get_default_fleet_cap()
        # Virt VM listesi ayrı default kullanabilir
        if plat in ("virt", "hypervisor", "virtualization"):
            try:
                from app.services import runtime_settings as rts
                cap = int(rts.get_int("virt_chat_vm_list_limit"))
            except Exception:
                cap = 50
        if n > cap:
            set_full_scan_pending(
                session_id, question=message, item_count=n, platform=plat, kind=kind,
            )
            return {
                "action": "clarify",
                "work_message": message,
                "full_scan": False,
                "clarification": build_full_fleet_clarification(
                    item_count=n, default_cap=cap, kind=kind,
                ),
                "item_count": n,
            }
    return {"action": "proceed", "work_message": message, "full_scan": False}
