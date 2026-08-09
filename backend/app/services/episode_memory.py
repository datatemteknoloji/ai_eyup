"""Oturum episode belleği — Redis, kısa TTL; learned_facts'e yazılmaz."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TTL_SEC = 45 * 60  # 45 dk
_MAX_SUMMARY = 3500


def _key(session_id: int, platform: str) -> str:
    plat = (platform or "linux").strip().lower() or "linux"
    return f"ainew:episode:{plat}:{int(session_id)}"


def save_episode(
    *,
    session_id: Optional[int],
    platform: str,
    summary: str,
    server_names: Optional[List[str]] = None,
    tools: Optional[List[str]] = None,
) -> bool:
    """Canlı keşif özetini oturuma yaz (follow-up için)."""
    if not session_id:
        return False
    text = (summary or "").strip()
    if len(text) < 40:
        return False
    text = text[:_MAX_SUMMARY]
    payload: Dict[str, Any] = {
        "summary": text,
        "servers": (server_names or [])[:20],
        "tools": (tools or [])[:12],
    }
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if not r:
            return False
        r.setex(_key(session_id, platform), _TTL_SEC, json.dumps(payload, ensure_ascii=False))
        return True
    except Exception as e:
        logger.debug("Episode save atlandı: %s", e)
        return False


def get_episode_block(*, session_id: Optional[int], platform: str) -> str:
    """Prompt'a eklenecek kısa OTURUM EPISODE bloğu."""
    if not session_id:
        return ""
    try:
        from app.core.redis_client import get_redis

        r = get_redis()
        if not r:
            return ""
        raw = r.get(_key(session_id, platform))
        if not raw:
            return ""
        data = json.loads(raw)
        summary = (data.get("summary") or "").strip()
        if not summary:
            return ""
        lines = [
            "OTURUM EPISODE (bu sohbette az önce toplanmış canlı keşif — learned_facts değil, kısa ömürlü):",
            summary[:_MAX_SUMMARY],
        ]
        servers = data.get("servers") or []
        if servers:
            lines.append("Sunucular: " + ", ".join(str(s) for s in servers[:12]))
        tools = data.get("tools") or []
        if tools:
            lines.append("Araçlar: " + ", ".join(str(t) for t in tools[:10]))
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Episode read atlandı: %s", e)
        return ""


def append_episode_to_context(
    context_str: str,
    *,
    session_id: Optional[int],
    platform: str,
) -> str:
    block = get_episode_block(session_id=session_id, platform=platform)
    if not block:
        return context_str
    base = (context_str or "").rstrip()
    return f"{base}\n\n{block}" if base else block


def summarize_live_context(context_str: str, *, max_chars: int = 2800) -> str:
    """SSH/tool bağlamından episode için kısaltılmış özet."""
    text = (context_str or "").strip()
    if not text:
        return ""
    # Çok uzun satırları kısalt
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if len(line) > 240:
            line = line[:237] + "..."
        lines.append(line)
        if sum(len(x) + 1 for x in lines) >= max_chars:
            break
    return "\n".join(lines)[:max_chars]
