"""
Admin chat niyet yönlendirici — Linux + Virt.

LLM son çare: önce normalize + intent, sonra deterministik / canlı veri.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Intent sabitleri
INTENT_INVENTORY = "inventory"
INTENT_INVENTORY_SUMMARY = "inventory_summary"
INTENT_DIRECT_CMD = "direct_cmd"
INTENT_VIRT_QA = "virt_qa"
INTENT_SSH_TOPIC = "ssh_topic"
INTENT_LLM = "llm"


@dataclass
class RouteResult:
    intent: str
    confidence: float
    normalized_q: str
    hints: Dict[str, Any] = field(default_factory=dict)


def normalize_admin_question(question: str, platform: str = "linux") -> str:
    """Platforma göre typo/TR normalize."""
    q = question or ""
    if platform == "virt":
        try:
            from app.services.hypervisor_intelligence import _normalize_virt_question
            return _normalize_virt_question(q)
        except Exception:
            pass
    try:
        from app.services.linux_chat_intent import _fold
        return _fold(q)
    except Exception:
        return q.lower()


def route_admin_question(question: str, platform: str = "linux") -> RouteResult:
    """Soruyu intent'e yönlendir.

    platform: linux | virt
    """
    raw = question or ""
    platform = (platform or "linux").lower()
    normalized = normalize_admin_question(raw, platform)

    if platform == "virt":
        return _route_virt(raw, normalized)
    return _route_linux(raw, normalized)


def _route_linux(raw: str, normalized: str) -> RouteResult:
    from app.services.linux_chat_intent import (
        extract_direct_commands,
        is_fleet_inventory_query,
        is_inventory_status_query,
    )

    # Özet/sayı soruları önce — çapraz platform sızdıran agentic yoluna düşmesin
    if is_inventory_status_query(raw):
        return RouteResult(
            intent=INTENT_INVENTORY_SUMMARY,
            confidence=0.96,
            normalized_q=normalized,
            hints={"summary": True},
        )

    if is_fleet_inventory_query(raw):
        return RouteResult(
            intent=INTENT_INVENTORY,
            confidence=0.95,
            normalized_q=normalized,
            hints={"fleet": True},
        )

    cmds = extract_direct_commands(raw)
    if cmds:
        return RouteResult(
            intent=INTENT_DIRECT_CMD,
            confidence=0.9,
            normalized_q=normalized,
            hints={"commands": cmds},
        )

    try:
        from app.services.linux_info_collector import has_recognized_topic
        if has_recognized_topic(raw):
            return RouteResult(
                intent=INTENT_SSH_TOPIC,
                confidence=0.75,
                normalized_q=normalized,
                hints={},
            )
    except Exception:
        pass

    return RouteResult(
        intent=INTENT_LLM,
        confidence=0.4,
        normalized_q=normalized,
        hints={},
    )


def _route_virt(raw: str, normalized: str) -> RouteResult:
    """Virt: normalize edilmiş soruda QA_RULES eşleşmesi var mı?"""
    try:
        from app.services.hypervisor_intelligence import QA_RULES
        for pattern, handler in QA_RULES:
            try:
                if re.search(pattern, normalized, re.IGNORECASE):
                    return RouteResult(
                        intent=INTENT_VIRT_QA,
                        confidence=0.95,
                        normalized_q=normalized,
                        hints={
                            "handler": getattr(handler, "__name__", str(handler)),
                            "pattern": pattern[:80],
                        },
                    )
            except re.error:
                continue
    except Exception as e:
        logger.debug("virt route QA_RULES: %s", e)

    return RouteResult(
        intent=INTENT_LLM,
        confidence=0.4,
        normalized_q=normalized,
        hints={},
    )


def resolve_linux_targets(
    db,
    message: str,
    *,
    server_ids: Optional[List[int]] = None,
    server_id: Optional[int] = None,
    session_id: Optional[int] = None,
    allow_full_fleet: bool = False,
    max_fleet: int = 64,
) -> tuple:
    """Sunucu seçimi — tam filo default YOK (allow_full_fleet=False).

    Döner: (servers: list, note: Optional[str])
    note doluysa kullanıcıya 'hangi sunucu?' mesajı gösterilir.
    """
    from app.models.server import Server
    from app.services.platform_scope import is_windows_server

    def _ai_ready():
        return [s for s in db.query(Server).filter(Server.ai_ready == True).all()
                if not is_windows_server(s)]

    all_srv = _ai_ready()
    if server_ids:
        chosen = [s for s in all_srv if s.id in server_ids]
        return chosen, None
    if server_id:
        chosen = [s for s in all_srv if s.id == server_id]
        return chosen, None

    # Mesajda ad/IP
    ml = (message or "").lower()
    mentioned = [
        s for s in all_srv
        if (s.name and s.name.lower() in ml) or (s.ip_address and s.ip_address in (message or ""))
    ]
    if mentioned:
        return mentioned, None

    # Session'daki son seçim (meta) — yoksa sorma
    if session_id:
        try:
            from app.models.chat_session import ChatSession
            sess = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            meta = (sess.meta if sess and hasattr(sess, "meta") else None) or {}
            if isinstance(meta, dict):
                last_ids = meta.get("last_server_ids") or meta.get("server_ids")
                if last_ids:
                    chosen = [s for s in all_srv if s.id in last_ids]
                    if chosen:
                        return chosen[:max_fleet], None
        except Exception:
            pass

    if allow_full_fleet:
        return all_srv[:max_fleet], None

    # Filo envanter (hostname/IP listesi) için full fleet OK — çağıran allow eder
    return [], (
        "Hangi sunucu için bakayım? AI Ready sunucu adı veya IP yazın, "
        "ya da sohbetten sunucu seçin.\n\n"
        + ("Kayıtlı: " + ", ".join(s.name for s in all_srv[:20]) if all_srv else "AI Ready sunucu yok.")
    )
