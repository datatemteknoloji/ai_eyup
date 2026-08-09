from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import get_current_user, require_admin
from app.assistant.catalog import get_capability, list_capabilities
from app.assistant import history as ahist
from app.assistant.ollama_client import list_models
from app.assistant.pending import clear_pending
from app.assistant.router import resolve_ollama_base, route_message
from app.core.database import get_session
from app.models.assistant_feedback import AssistantFeedback
from app.models.user import User
from app.services import assistant_settings as aset

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class AssistantChatResponse(BaseModel):
    operation_id: Optional[str] = None
    title_tr: Optional[str] = None
    route: Optional[str] = None
    deep_link: Optional[str] = None
    server_ids: list[int] = []
    server_hostnames: list[str] = []
    reference_server_ids: list[int] = []
    reference_hostnames: list[str] = []
    confidence: float = 0.0
    summary_tr: str = ""
    checklist_tr: list[str] = []
    clarifying_questions: list[str] = []
    out_of_scope_note: Optional[str] = None
    required_inputs: list[str] = []
    analysis_tr: str = ""
    analysis_probed: bool = False
    source: str = "catalog"


class AssistantTestResponse(BaseModel):
    ok: bool
    message: str
    models: list[str] = []


class AssistantFeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    suggested_operation_id: str = Field(default="", max_length=64)
    correct_operation_id: str = Field(min_length=1, max_length=64)


class HistoryItem(BaseModel):
    id: int
    role: str
    content: str
    operation_id: str = ""
    result: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


def _format_assistant_text(result: dict[str, Any]) -> str:
    lines = [str(result.get("summary_tr") or "").strip()]
    title = (result.get("title_tr") or "").strip()
    if title:
        lines.append(f"Önerilen: {title}")
    hosts = result.get("server_hostnames") or []
    if hosts:
        lines.append(f"Hedef: {', '.join(hosts)}")
    refs = result.get("reference_hostnames") or []
    if refs:
        lines.append(f"Referans: {', '.join(refs)}")
    checklist = result.get("checklist_tr") or []
    if checklist:
        lines.append("Kontrol listesi:")
        for i, c in enumerate(checklist, 1):
            lines.append(f"{i}. {c}")
    analysis = (result.get("analysis_tr") or "").strip()
    if analysis:
        lines.append(analysis)
    questions = result.get("clarifying_questions") or []
    if questions:
        lines.append("Netleştirme:")
        for q in questions:
            lines.append(f"• {q}")
    note = result.get("out_of_scope_note")
    if note:
        lines.append(f"Not: {note}")
    return "\n".join(x for x in lines if x)


@router.get("/status")
def assistant_status(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return {
        "enabled": aset.is_assistant_enabled(session),
        "model": aset.get_assistant_model(session),
        "ollama_mode": aset.get_assistant_ollama_mode(session),
        "configured": bool(resolve_ollama_base(session)[0] and aset.get_assistant_model(session)),
    }


@router.get("/capabilities")
def assistant_capabilities(
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not aset.is_assistant_enabled(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asistan devre dışı")
    caps = [
        {
            "id": c.get("id"),
            "title_tr": c.get("title_tr"),
            "route": c.get("route"),
            "summary_tr": c.get("summary_tr"),
        }
        for c in list_capabilities()
    ]
    return {"capabilities": caps}


@router.get("/history")
def assistant_history(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not aset.is_assistant_enabled(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asistan devre dışı")
    uid = int(user.id)  # type: ignore[arg-type]
    rows = ahist.list_history(session, uid)
    items: list[dict[str, Any]] = []
    for r in rows:
        result = None
        if r.role == "assistant" and r.result_json:
            try:
                result = json.loads(r.result_json)
            except json.JSONDecodeError:
                result = None
        items.append(
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "operation_id": r.operation_id or "",
                "result": result,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return {"items": items, "ttl_hours": 24}


@router.delete("/history")
def assistant_history_clear(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not aset.is_assistant_enabled(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asistan devre dışı")
    uid = int(user.id)  # type: ignore[arg-type]
    ahist.clear_history(session, uid)
    clear_pending(uid)
    return {"ok": True}


@router.post("/chat", response_model=AssistantChatResponse)
async def assistant_chat(
    body: AssistantChatRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AssistantChatResponse:
    uid = int(user.id)  # type: ignore[arg-type]
    try:
        result = await route_message(session, body.message, user_id=uid)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    ahist.append_turn(
        session,
        uid,
        user_text=body.message.strip(),
        assistant_text=_format_assistant_text(result),
        result=result,
    )
    return AssistantChatResponse(**result)


@router.post("/feedback")
def assistant_feedback(
    body: AssistantFeedbackRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not aset.is_assistant_enabled(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Asistan devre dışı")
    if not get_capability(body.correct_operation_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Geçersiz operasyon")
    row = AssistantFeedback(
        user_id=int(user.id),  # type: ignore[arg-type]
        message=body.message.strip()[:8000],
        suggested_operation_id=(body.suggested_operation_id or "").strip()[:64],
        correct_operation_id=body.correct_operation_id.strip()[:64],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"ok": True, "id": row.id}


@router.post("/test", response_model=AssistantTestResponse)
async def assistant_test(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> AssistantTestResponse:
    base, api_key = resolve_ollama_base(session)
    if not base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce gateway URL veya doğrudan host/port kaydedin",
        )
    try:
        models = await list_models(base, api_key)
        return AssistantTestResponse(
            ok=True,
            message=f"Bağlantı OK · {len(models)} model",
            models=models,
        )
    except Exception as exc:  # noqa: BLE001
        return AssistantTestResponse(ok=False, message=str(exc), models=[])


@router.get("/models")
async def assistant_models(
    _admin: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    base, api_key = resolve_ollama_base(session)
    if not base:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Önce gateway URL veya doğrudan host/port kaydedin",
        )
    try:
        models = await list_models(base, api_key)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"models": models}
