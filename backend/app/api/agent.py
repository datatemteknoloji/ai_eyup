"""
Agentic AI API — tool-calling + insan onayı (human-in-the-loop).

Endpoint'ler:
  POST /agent/chat                       → agent döngüsünü başlat
  GET  /agent/actions/pending            → bekleyen onaylar
  GET  /agent/actions                    → son aksiyonlar (audit)
  POST /agent/actions/{id}/approve       → onayla ve devam et
  POST /agent/actions/{id}/reject        → reddet ve devam et
"""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.agent_action import AgentAction
from app.models.user import User
from app.services.agent.orchestrator import (
    start_agent, continue_after_decision, continue_after_answer,
)

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    server_ids: Optional[List[int]] = None
    model: Optional[str] = None


class AnswerRequest(BaseModel):
    answer: Any = None


class ApproveRequest(BaseModel):
    # Kullanıcının onay anında girdiği geçici root/sudo şifresi (yetki yükseltme).
    # Kayıtlı sudo şifresi yoksa istenir; DB'ye yazılmaz, yalnızca o çalıştırma için kullanılır.
    sudo_password: Optional[str] = None


def _action_to_dict(a: AgentAction) -> dict:
    return {
        "id": a.id,
        "session_id": a.session_id,
        "server_id": a.server_id,
        "tool_name": a.tool_name,
        "arguments": a.arguments or {},
        "risk_level": a.risk_level,
        "status": a.status,
        "preview": a.preview,
        "requires_root": bool(getattr(a, "requires_root", False)),
        "result": a.result or {},
        "model": a.model,
        "decided_by": a.decided_by,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "executed_at": a.executed_at.isoformat() if a.executed_at else None,
    }


@router.post("/chat")
def agent_chat(req: AgentChatRequest, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    # NOT: kasıtlı olarak senkron `def` — start_agent() zinciri (LLM tool-calling
    # turları + SSH komut çalıştırma) tamamen bloklayan/senkron I/O yapar. FastAPI
    # senkron endpoint'leri otomatik thread pool'da çalıştırır; `async def` olsaydı
    # bu çağrı doğrudan event loop'u dakikalarca (MAX_STEPS turu) kilitlerdi.
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    result = start_agent(
        db, message,
        session_id=req.session_id,
        server_ids=req.server_ids,
        model=req.model,
        actor=user,
    )
    return result


@router.get("/actions/pending")
async def pending_actions(session_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(AgentAction).filter(AgentAction.status == "pending")
    if session_id:
        q = q.filter(AgentAction.session_id == session_id)
    actions = q.order_by(AgentAction.created_at.desc()).all()
    return {"actions": [_action_to_dict(a) for a in actions], "total": len(actions)}


@router.get("/actions")
async def list_actions(limit: int = 50, db: Session = Depends(get_db)):
    actions = (
        db.query(AgentAction)
        .order_by(AgentAction.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return {"actions": [_action_to_dict(a) for a in actions]}


@router.post("/actions/{action_id}/approve")
def approve_action(action_id: int, req: ApproveRequest = ApproveRequest(),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    # NOT: senkron `def` — bkz. agent_chat üstündeki not (continue_after_decision
    # de aynı bloklayan LLM/SSH zincirini tetikler).
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Aksiyon bulunamadı")
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"Aksiyon zaten '{action.status}'")
    # Yetki yükseltme gerekiyorsa root şifresi zorunlu.
    if getattr(action, "requires_root", False) and not (req.sudo_password or "").strip():
        raise HTTPException(status_code=400,
                            detail="Bu işlem için root/sudo şifresi gerekli.")
    return continue_after_decision(
        db, action, approved=True,
        decided_by=user.username,
        sudo_password=(req.sudo_password or None),
    )


@router.post("/actions/{action_id}/reject")
def reject_action(action_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Aksiyon bulunamadı")
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"Aksiyon zaten '{action.status}'")
    return continue_after_decision(db, action, approved=False, decided_by=user.username)


@router.post("/actions/{action_id}/answer")
def answer_action(action_id: int, req: AnswerRequest, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    action = db.query(AgentAction).filter(AgentAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Aksiyon bulunamadı")
    if action.status != "awaiting_input":
        raise HTTPException(status_code=409, detail=f"Aksiyon zaten '{action.status}'")
    if req.answer in (None, "", []):
        raise HTTPException(status_code=400, detail="Yanıt boş olamaz")
    return continue_after_answer(db, action, req.answer, decided_by=user.username)
