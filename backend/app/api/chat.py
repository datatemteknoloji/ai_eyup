"""
Chat API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import logging
import httpx

from app.core.database import get_db
from app.core.config import settings
from app.models.server import Server

logger = logging.getLogger(__name__)

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    server_ids: Optional[List[int]] = None
    server_id: Optional[int] = None

class ChatResponse(BaseModel):
    response: str
    commands: Optional[List[dict]] = None
    suggestions: Optional[List[str]] = None

@router.post("/", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat mesajı gönder ve AI yanıtı al"""
    try:
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Seçili sunucuları bul
        selected_servers = []
        if request.server_ids and len(request.server_ids) > 0:
            selected_servers = db.query(Server).filter(
                Server.id.in_(request.server_ids),
                Server.ai_ready == True
            ).all()
        elif request.server_id:
            server = db.query(Server).filter(
                Server.id == request.server_id,
                Server.ai_ready == True
            ).first()
            if server:
                selected_servers = [server]
        
        # AI Ready sunucu listesi
        ai_ready_servers = db.query(Server).filter(Server.ai_ready == True).all()
        
        # Sunucu bilgilerini context olarak hazırla
        server_context = ""
        if selected_servers:
            server_context = "Seçili sunucular:\n"
            for s in selected_servers:
                server_context += f"- {s.name} ({s.ip_address}): {s.status}, CPU: {s.cpu_cores}, RAM: {s.memory_gb}GB\n"
        elif ai_ready_servers:
            server_context = f"Toplam {len(ai_ready_servers)} AI Ready sunucu mevcut.\n"
        
        # Ollama'ya istek gönder
        try:
            ollama_url = settings.OLLAMA_URL
            model = settings.OLLAMA_DEFAULT_MODEL
            
            prompt = f"""Sen bir sunucu yönetim asistanısın. Türkçe yanıt ver.

{server_context}

Kullanıcı sorusu: {message}

Lütfen net, kısa ve yardımcı bir yanıt ver. Gerekirse komut önerileri de sun."""

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    ai_response = data.get("response", "Yanıt alınamadı")
                    
                    return ChatResponse(
                        response=ai_response,
                        commands=None,
                        suggestions=None
                    )
                else:
                    logger.error(f"Ollama error: {response.status_code} - {response.text}")
                    return ChatResponse(
                        response=f"AI servisi yanıt veremedi (HTTP {response.status_code}). Ollama servisinin çalıştığından emin olun.",
                        commands=None,
                        suggestions=None
                    )
        except httpx.TimeoutException:
            logger.error("Ollama timeout")
            return ChatResponse(
                response="AI servisi zaman aşımına uğradı. Lütfen tekrar deneyin.",
                commands=None,
                suggestions=None
            )
        except httpx.ConnectError:
            logger.error("Ollama connection error")
            return ChatResponse(
                response="AI servisine bağlanılamadı. Ollama servisinin çalıştığından emin olun.",
                commands=None,
                suggestions=None
            )
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return ChatResponse(
                response=f"AI servisi hatası: {str(e)}",
                commands=None,
                suggestions=None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
