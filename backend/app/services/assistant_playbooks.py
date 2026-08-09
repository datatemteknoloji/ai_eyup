"""Assistant tool playbook — başarılı READ_ONLY tool zincirlerini hatırlar."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.assistant_playbook import AssistantPlaybook

logger = logging.getLogger(__name__)

_PLAYBOOK_TTL_DAYS = 30
_SIM_THRESHOLD = 0.62
# Anlık metrik/log tool'ları playbook'a yazılmaz (yalnızca prosedürel keşif)
_SKIP_TOOLS = frozenset({
    "get_processes",
    "read_service_logs",
    "get_service_logs",
    "get_kernel_errors",
    "get_security_events",
    "win_read_event_logs",
    "list_ocp_events",
    "vcenter_live_alarms",
    "vcenter_live_tasks",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_intent(question: str) -> str:
    t = (question or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[?!.,;:]+", "", t)
    return t[:400]


def _filter_tools(tools: Sequence[str]) -> List[str]:
    out: List[str] = []
    for t in tools:
        name = (t or "").strip()
        if not name or name in _SKIP_TOOLS:
            continue
        if name not in out:
            out.append(name)
    return out[:12]


def record_playbook(
    db: Session,
    *,
    platform: str,
    question: str,
    tools: Sequence[str],
    server_scope: Optional[str] = None,
    outcome_summary: Optional[str] = None,
) -> Optional[int]:
    """Başarılı tool turundan playbook kaydet / benzeri güçlendir."""
    plat = (platform or "linux").strip().lower() or "linux"
    intent = normalize_intent(question)
    tool_list = _filter_tools(tools)
    if not intent or len(intent) < 12 or not tool_list:
        return None
    try:
        rows = (
            db.query(AssistantPlaybook)
            .filter(
                AssistantPlaybook.platform == plat,
                or_(
                    AssistantPlaybook.expires_at.is_(None),
                    AssistantPlaybook.expires_at > _now(),
                ),
            )
            .order_by(AssistantPlaybook.hit_count.desc())
            .limit(40)
            .all()
        )
        best = None
        best_score = 0.0
        for row in rows:
            score = SequenceMatcher(None, intent, row.intent_norm or "").ratio()
            if score > best_score:
                best_score = score
                best = row
        if best and best_score >= 0.90:
            existing = list(best.tools_json or [])
            for t in tool_list:
                if t not in existing:
                    existing.append(t)
            best.tools_json = existing[:12]
            best.hit_count = int(best.hit_count or 0) + 1
            best.expires_at = _now() + timedelta(days=_PLAYBOOK_TTL_DAYS)
            if outcome_summary:
                best.outcome_summary = (outcome_summary or "")[:500]
            if server_scope:
                best.server_scope = server_scope[:80]
            db.commit()
            return best.id

        row = AssistantPlaybook(
            platform=plat,
            intent_norm=intent,
            tools_json=tool_list,
            server_scope=(server_scope or None),
            outcome_summary=(outcome_summary or "")[:500] if outcome_summary else None,
            hit_count=1,
            expires_at=_now() + timedelta(days=_PLAYBOOK_TTL_DAYS),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Playbook kaydedildi platform=%s tools=%s", plat, tool_list)
        return row.id
    except Exception as e:
        logger.debug("Playbook kayıt hatası: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def find_playbook_hints(
    db: Session,
    *,
    platform: str,
    question: str,
    limit: int = 2,
) -> str:
    """Prompt'a eklenecek kısa 'önceki başarılı yaklaşım' bloğu."""
    plat = (platform or "linux").strip().lower() or "linux"
    intent = normalize_intent(question)
    if not intent or len(intent) < 10:
        return ""
    try:
        rows = (
            db.query(AssistantPlaybook)
            .filter(
                AssistantPlaybook.platform == plat,
                or_(
                    AssistantPlaybook.expires_at.is_(None),
                    AssistantPlaybook.expires_at > _now(),
                ),
            )
            .order_by(AssistantPlaybook.hit_count.desc())
            .limit(60)
            .all()
        )
        scored: List[tuple] = []
        for row in rows:
            score = SequenceMatcher(None, intent, row.intent_norm or "").ratio()
            if score >= _SIM_THRESHOLD:
                scored.append((score, row))
        scored.sort(key=lambda x: (-x[0], -(x[1].hit_count or 0)))
        picked = [r for _, r in scored[: max(1, min(limit, 2))]]
        if not picked:
            return ""
        lines = [
            "ÖNCEKİ BAŞARILI YAKLAŞIM (benzer sorularda işe yarayan araç sırası — "
            "değer uydurma, araçları buna göre çağır):"
        ]
        for row in picked:
            tools = row.tools_json or []
            if isinstance(tools, str):
                try:
                    tools = json.loads(tools)
                except Exception:
                    tools = [tools]
            lines.append(f"- araçlar: {', '.join(str(t) for t in tools)}")
            row.hit_count = int(row.hit_count or 0) + 1
        db.commit()
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Playbook lookup hatası: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return ""


def append_playbook_to_context(
    db: Session,
    context_str: str,
    *,
    platform: str,
    question: str,
) -> str:
    hint = find_playbook_hints(db, platform=platform, question=question)
    if not hint:
        return context_str
    base = (context_str or "").rstrip()
    return f"{base}\n\n{hint}" if base else hint


def purge_expired_playbooks(db: Session) -> int:
    try:
        n = (
            db.query(AssistantPlaybook)
            .filter(
                AssistantPlaybook.expires_at.isnot(None),
                AssistantPlaybook.expires_at < _now(),
            )
            .delete(synchronize_session=False)
        )
        if n:
            db.commit()
        return int(n or 0)
    except Exception:
        db.rollback()
        return 0
