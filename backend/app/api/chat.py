"""
Chat API endpoints - veritabanı tabanlı (kalıcı, tüm worker'larda aynı veri)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, delete
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import logging
import httpx

from app.core.database import get_db
from app.core.config import settings
from app.models.server import Server
from app.models.chat_session import ChatSession, ChatMessage
from app.services.monitoring.prometheus_metrics import PrometheusMetricsService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models")
async def list_available_models():
    """Ollama'da mevcut modelleri listele"""
    try:
        ollama_url = settings.OLLAMA_URL
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append({
                        "name": model.get("name"),
                        "size": model.get("size"),
                        "parameter_size": model.get("details", {}).get("parameter_size"),
                        "family": model.get("details", {}).get("family")
                    })
                return {
                    "success": True,
                    "models": models,
                    "default": settings.OLLAMA_DEFAULT_MODEL
                }
            else:
                return {
                    "success": False,
                    "models": [],
                    "default": settings.OLLAMA_DEFAULT_MODEL,
                    "error": "Ollama'ya bağlanılamadı"
                }
    except Exception as e:
        logger.error(f"Model listesi alınamadı: {e}")
        return {
            "success": False,
            "models": [],
            "default": settings.OLLAMA_DEFAULT_MODEL,
            "error": str(e)
        }


class ChatRequest(BaseModel):
    message: str
    server_ids: Optional[List[int]] = None
    server_id: Optional[int] = None
    session_id: Optional[int] = None
    model: Optional[str] = None  # Ollama model seçimi


class ChatResponse(BaseModel):
    response: str
    commands: Optional[List[dict]] = None
    suggestions: Optional[List[str]] = None
    session_id: Optional[int] = None


class ChatSessionResponse(BaseModel):
    id: int
    title: str
    server_ids: List[int]
    created_at: str
    updated_at: Optional[str] = None
    message_count: int = 0


class ChatMessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


def _session_to_dict(session: ChatSession, message_count: int = 0) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "server_ids": session.server_ids or [],
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "message_count": message_count,
    }


@router.get("/sessions")
async def list_chat_sessions(db: Session = Depends(get_db)):
    """Tüm chat session'larını listele (DB'den)"""
    sessions = db.query(ChatSession).order_by(
        func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc()
    ).all()
    result = []
    for s in sessions:
        count = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
        result.append(_session_to_dict(s, message_count=count))
    return result


@router.post("/sessions")
async def create_chat_session(
    server_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db),
):
    """Yeni chat session oluştur"""
    session = ChatSession(
        title="Yeni Chat",
        server_ids=server_ids or [],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_to_dict(session, message_count=0)


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int, db: Session = Depends(get_db)):
    """Session mesajlarını getir"""
    if db.query(ChatSession).filter(ChatSession.id == session_id).first() is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
        .all()
    )
    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else "",
        }
        for m in messages
    ]


@router.put("/sessions/{session_id}")
async def update_session_title(
    session_id: int,
    title: str,
    db: Session = Depends(get_db),
):
    """Session başlığını güncelle"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.title = title
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, db: Session = Depends(get_db)):
    """Session'ı sil"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    db.delete(session)
    db.commit()
    return {"success": True}


@router.delete("/sessions")
async def delete_all_sessions(db: Session = Depends(get_db)):
    """Tüm chat session'larını sil (kalıcı)"""
    count = db.query(ChatSession).count()
    db.execute(delete(ChatMessage))
    db.execute(delete(ChatSession))
    db.commit()
    return {"success": True, "cleared": count}


@router.post("/", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat mesajı gönder ve AI yanıtı al (SSH komut çalıştırma desteği ile)"""
    try:
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        session_id = request.session_id
        if not session_id:
            # Yeni session oluştur
            title = message[:50] + ("..." if len(message) > 50 else "")
            session = ChatSession(
                title=title,
                server_ids=request.server_ids or [],
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            session_id = session.id
        else:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

        # Seçili sunucuları bul
        selected_servers = []
        if request.server_ids and len(request.server_ids) > 0:
            selected_servers = (
                db.query(Server)
                .filter(
                    Server.id.in_(request.server_ids),
                    Server.ai_ready == True,
                )
                .all()
            )
        elif request.server_id:
            server = (
                db.query(Server)
                .filter(
                    Server.id == request.server_id,
                    Server.ai_ready == True,
                )
                .first()
            )
            if server:
                selected_servers = [server]
        
        # Eğer sunucu seçilmemişse tüm AI Ready sunucuları al
        if not selected_servers:
            selected_servers = db.query(Server).filter(Server.ai_ready == True).all()
        
        ai_ready_servers = db.query(Server).filter(Server.ai_ready == True).all()

        server_context = ""
        if selected_servers:
            server_context = "Seçili sunucular:\n"
            for s in selected_servers:
                server_context += f"- {s.name} ({s.ip_address}): {s.status}, CPU: {s.cpu_cores}, RAM: {s.memory_gb}GB\n"
        elif ai_ready_servers:
            server_context = f"Toplam {len(ai_ready_servers)} AI Ready sunucu mevcut.\n"

        prometheus_context = ""
        # Prometheus context'i sadece metrik/performans soruları için çek
        if any(keyword in message.lower() for keyword in ['metrik', 'cpu', 'ram', 'memory', 'disk', 'performance', 'yük', 'kullanım']):
            try:
                metrics_service = PrometheusMetricsService()
                prometheus_context = await metrics_service.get_metrics_context_for_ai(message)
                if not prometheus_context:
                    available_metrics = await metrics_service.get_node_exporter_metrics()
                    if available_metrics:
                        prometheus_context = f"\n📋 Mevcut Prometheus Metrikleri ({len(available_metrics)} adet):\n"
                        for metric in sorted(available_metrics)[:20]:
                            prometheus_context += f"  - {metric}\n"
                        if len(available_metrics) > 20:
                            prometheus_context += f"  ... ve {len(available_metrics) - 20} metrik daha\n"
            except Exception as e:
                logger.warning(f"Prometheus context oluşturma hatası: {e}")
                prometheus_context = "\n⚠️ Prometheus metrikleri şu anda kullanılamıyor.\n"

        # User mesajını DB'ye kaydet
        user_msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=message,
        )
        db.add(user_msg)
        db.commit()
        
        # SSH komut gerekip gerekmediğini kontrol et
        requires_ssh = any(keyword in message.lower() for keyword in [
            'disk', 'cpu', 'ram', 'memory', 'process', 'service', 'log', 'çalış',
            'kontrol et', 'göster', 'listele', 'ne kadar', 'durumu', 'uptime',
            'top', 'ps', 'df', 'free', 'systemctl', 'journalctl'
        ])
        
        ssh_results = []
        if requires_ssh and selected_servers:
            from app.services.ai_agent import AIAgent
            agent = AIAgent(settings.OLLAMA_URL)
            
            # AI Agent ile sorguyu işle (komut oluştur ve çalıştır)
            agent_result = await agent.process_query(message, selected_servers, db)
            
            if agent_result.get("type") == "command_execution":
                ssh_results = agent_result.get("commands_executed", [])
                # AI'nin özeti varsa direkt kullan
                if agent_result.get("response"):
                    ai_response = agent_result["response"]
                    
                    # Komut sonuçlarını ekle
                    if ssh_results:
                        ai_response += "\n\n**Çalıştırılan Komutlar:**\n"
                        for cmd in ssh_results:
                            ai_response += f"\n**{cmd['server']}:** `{cmd['command']}`\n"
                            if cmd['success']:
                                ai_response += f"```\n{cmd['output'][:300]}\n```\n"
                            else:
                                ai_response += f"❌ {cmd['error']}\n"
                    
                    # AI yanıtını kaydet
                    assistant_msg = ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=ai_response,
                    )
                    db.add(assistant_msg)
                    db.commit()
                    
                    return ChatResponse(
                        response=ai_response,
                        commands=ssh_results if ssh_results else None,
                        session_id=session_id
                    )

        try:
            ollama_url = settings.OLLAMA_URL
            # Kullanıcının seçtiği model veya default model
            model = request.model or settings.OLLAMA_DEFAULT_MODEL
            # Basit ve net prompt oluştur
            context_parts = []
            if server_context:
                context_parts.append(server_context.strip())
            if prometheus_context:
                context_parts.append(prometheus_context.strip())
            
            context_str = "\n\n".join(context_parts) if context_parts else "Henüz sunucu bilgisi yok."
            
            prompt = f"""Sen bir sunucu yönetim asistanı (Server Management Assistant) olarak çalışıyorsun. 
TÜRKÇE yanıt ver. Kısa, net ve doğrudan cevap ver.

SUNUCU BİLGİLERİ:
{context_str}

KULLANICI SORUSU: {message}

CEVAP: """

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    ai_response = data.get("response", "Yanıt alınamadı")

                    assistant_msg = ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=ai_response,
                    )
                    db.add(assistant_msg)
                    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if session:
                        session.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    return ChatResponse(
                        response=ai_response,
                        commands=None,
                        suggestions=None,
                        session_id=session_id,
                    )
                else:
                    logger.error(f"Ollama error: {response.status_code} - {response.text}")
                    error_response = (
                        f"AI servisi yanıt veremedi (HTTP {response.status_code}). "
                        "Ollama servisinin çalıştığından emin olun."
                    )
                    err_msg = ChatMessage(
                        session_id=session_id,
                        role="assistant",
                        content=error_response,
                    )
                    db.add(err_msg)
                    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if session:
                        session.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    return ChatResponse(
                        response=error_response,
                        commands=None,
                        suggestions=None,
                        session_id=session_id,
                    )
        except httpx.TimeoutException:
            logger.error("Ollama timeout")
            error_response = "AI servisi zaman aşımına uğradı. Lütfen tekrar deneyin."
            err_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=error_response,
            )
            db.add(err_msg)
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session:
                session.updated_at = datetime.now(timezone.utc)
            db.commit()
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id,
            )
        except httpx.ConnectError:
            logger.error("Ollama connection error")
            error_response = "AI servisine bağlanılamadı. Ollama servisinin çalıştığından emin olun."
            err_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=error_response,
            )
            db.add(err_msg)
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session:
                session.updated_at = datetime.now(timezone.utc)
            db.commit()
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id,
            )
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            error_response = f"AI servisi hatası: {str(e)}"
            err_msg = ChatMessage(
                session_id=session_id,
                role="assistant",
                content=error_response,
            )
            db.add(err_msg)
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session:
                session.updated_at = datetime.now(timezone.utc)
            db.commit()
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
