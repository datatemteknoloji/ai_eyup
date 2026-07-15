"""
NLQ pipeline orchestrator + audit.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.linux_inventory import NlqQueryAudit
from app.models.user import User
from app.services.audit import record_audit
from app.services.nlq.executor import execute_query
from app.services.nlq.formatter import format_answer
from app.services.nlq.live_checker import live_check_servers
from app.services.nlq.parser import detect_live_check_phrase, parse_question
from app.services.nlq.validator import QueryValidationError, validate_query

logger = logging.getLogger(__name__)


def _user_allowed_tiers(user: Optional[User]) -> Optional[List[str]]:
    if user is None:
        return None
    if (user.role or "") == "admin":
        return None
    tiers = getattr(user, "allowed_tiers", None)
    if tiers is None:
        return None
    if isinstance(tiers, list):
        return [str(t) for t in tiers]
    return None


def run_nlq(
    db: Session,
    question: str,
    *,
    user: Optional[User] = None,
    live_check: Optional[bool] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    force_live = live_check
    if force_live is None and detect_live_check_phrase(question):
        force_live = True

    raw = parse_question(question, model=model)
    try:
        validated = validate_query(
            raw,
            allowed_tiers=_user_allowed_tiers(user),
            force_live_check=force_live if force_live is not None else None,
        )
    except QueryValidationError as e:
        dur = int((time.time() - t0) * 1000)
        _audit(db, user, question, raw, None, None, 0, dur, bool(force_live), "invalid_query", e.message)
        return e.as_dict()

    if validated.get("intent") == "unsupported":
        dur = int((time.time() - t0) * 1000)
        _audit(db, user, question, validated, None, None, 0, dur, bool(force_live), "unsupported", validated.get("reason"))
        return {
            "status": "unsupported",
            "question": question,
            "reason": validated.get("reason"),
            "missing_fields": validated.get("missing_fields") or [],
        }

    exec_result = execute_query(db, validated)
    live_diff = None
    if validated.get("live_check"):
        live_diff = live_check_servers(db, exec_result.get("results") or [])

    answer_md = format_answer(question, validated, exec_result, live_diff=live_diff)
    dur = int((time.time() - t0) * 1000)
    _audit(
        db, user, question, validated,
        exec_result.get("sql_template"),
        {"filter_count": len(validated.get("filters") or [])},
        exec_result["summary"]["total_found"],
        dur,
        bool(validated.get("live_check")),
        "success",
        None,
    )
    record_audit(
        db,
        category="nlq",
        action="nlq.query",
        status="success",
        actor=user,
        summary=(question or "")[:200],
        detail={"result_count": exec_result["summary"]["total_found"], "ms": dur},
    )

    return {
        "status": "success",
        "question": question,
        "interpreted_query": {
            "filters": validated.get("filters"),
            "sort": validated.get("sort"),
            "limit": validated.get("limit"),
            "live_check": validated.get("live_check"),
            "requested_columns": validated.get("requested_columns"),
        },
        "summary": exec_result["summary"],
        "results": exec_result["results"],
        "live_diff": live_diff,
        "answer_markdown": answer_md,
        "execution_duration_ms": dur,
    }


def _audit(
    db: Session,
    user: Optional[User],
    question: str,
    query_json: Any,
    sql_template: Optional[str],
    params: Optional[dict],
    result_count: int,
    duration_ms: int,
    live_check: bool,
    status: str,
    error: Optional[str],
) -> None:
    try:
        db.add(NlqQueryAudit(
            user_id=user.id if user else None,
            username=user.username if user else None,
            original_question=(question or "")[:4000],
            generated_query_json=query_json if isinstance(query_json, dict) else {"raw": str(query_json)},
            executed_sql_template=sql_template,
            query_parameters=params,
            result_count=result_count,
            execution_duration_ms=duration_ms,
            live_check_requested=live_check,
            status=status,
            error_message=(error or None),
        ))
        db.commit()
    except Exception as e:
        logger.warning("nlq audit write failed: %s", e)
        db.rollback()
