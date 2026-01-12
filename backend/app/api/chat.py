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

# In-memory session storage (geçici - production'da database kullanılmalı)
chat_sessions = {}
chat_messages = {}
next_session_id = 1

class ChatRequest(BaseModel):
    message: str
    server_ids: Optional[List[int]] = None
    server_id: Optional[int] = None
    session_id: Optional[int] = None

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

@router.get("/sessions")
async def list_chat_sessions():
    """Tüm chat session'larını listele"""
    global chat_sessions
    sessions = []
    for session_id, session in chat_sessions.items():
        message_count = len(chat_messages.get(session_id, []))
        sessions.append({
            "id": session_id,
            "title": session.get("title", f"Chat {session_id}"),
            "server_ids": session.get("server_ids", []),
            "created_at": session.get("created_at", ""),
            "updated_at": session.get("updated_at"),
            "message_count": message_count
        })
    # En son güncellenenler önce
    sessions.sort(key=lambda x: x.get("updated_at") or x.get("created_at", ""), reverse=True)
    return sessions

@router.post("/sessions")
async def create_chat_session(server_ids: Optional[List[int]] = None):
    """Yeni chat session oluştur"""
    global chat_sessions, next_session_id
    session_id = next_session_id
    next_session_id += 1
    
    from datetime import datetime
    chat_sessions[session_id] = {
        "title": f"Yeni Chat {session_id}",
        "server_ids": server_ids or [],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    chat_messages[session_id] = []
    
    return {
        "id": session_id,
        "title": chat_sessions[session_id]["title"],
        "server_ids": chat_sessions[session_id]["server_ids"],
        "created_at": chat_sessions[session_id]["created_at"],
        "updated_at": chat_sessions[session_id]["updated_at"],
        "message_count": 0
    }

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int):
    """Session mesajlarını getir"""
    if session_id not in chat_messages:
        raise HTTPException(status_code=404, detail="Session not found")
    
    messages = chat_messages[session_id]
    return [{
        "id": msg.get("id", i),
        "session_id": session_id,
        "role": msg.get("role"),
        "content": msg.get("content"),
        "created_at": msg.get("created_at", "")
    } for i, msg in enumerate(messages)]

@router.put("/sessions/{session_id}")
async def update_session_title(session_id: int, title: str):
    """Session başlığını güncelle"""
    if session_id not in chat_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    from datetime import datetime
    chat_sessions[session_id]["title"] = title
    chat_sessions[session_id]["updated_at"] = datetime.now().isoformat()
    
    return {"success": True}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int):
    """Session'ı sil"""
    if session_id not in chat_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    del chat_sessions[session_id]
    if session_id in chat_messages:
        del chat_messages[session_id]
    
    return {"success": True}

@router.post("/", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat mesajı gönder ve AI yanıtı al"""
    global chat_sessions, chat_messages, next_session_id
    
    try:
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")
        
        # Session ID yoksa yeni session oluştur
        session_id = request.session_id
        if not session_id:
            session_id = next_session_id
            next_session_id += 1
            from datetime import datetime
            # İlk mesajdan başlık oluştur
            title = message[:50] + ("..." if len(message) > 50 else "")
            chat_sessions[session_id] = {
                "title": title,
                "server_ids": request.server_ids or [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            chat_messages[session_id] = []
        elif session_id not in chat_sessions:
            raise HTTPException(status_code=404, detail="Session not found")
        
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
        
        # Prometheus'tan performans metriklerini çek (eğer performans sorusu ise)
        performance_context = ""
        if any(keyword in message.lower() for keyword in ['performans', 'performance', 'cpu', 'memory', 'disk', 'kullanım', 'metrik', 'metric', '15 dakika', 'son']):
            try:
                prometheus_url = settings.PROMETHEUS_URL
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    # CPU metrikleri - son değerler
                    try:
                        # CPU kullanımı: 100 - idle (instance bazında)
                        cpu_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[15m])) * 100)'
                        cpu_response = await client.get(
                            f"{prometheus_url}/api/v1/query",
                            params={"query": cpu_query}
                        )
                        if cpu_response.status_code == 200:
                            cpu_data = cpu_response.json()
                            if cpu_data.get("status") == "success" and cpu_data.get("data", {}).get("result"):
                                results = cpu_data["data"]["result"]
                                if results:
                                    cpu_values = [float(r["value"][1]) for r in results]
                                    avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
                                    performance_context += f"\n📊 Son 15 dakikalık ortalama CPU kullanımı: {avg_cpu:.2f}%\n"
                                    # Sunucu bazında detay
                                    for r in results[:5]:  # İlk 5 sunucu
                                        instance = r.get("metric", {}).get("instance", "unknown")
                                        server_name = r.get("metric", {}).get("server_name", instance)
                                        cpu_val = float(r["value"][1])
                                        performance_context += f"  - {server_name} ({instance}): {cpu_val:.2f}%\n"
                    except Exception as e:
                        logger.warning(f"CPU metrik çekme hatası: {e}")
                    
                    # Memory metrikleri
                    try:
                        memory_query = '(1 - (avg(node_memory_MemAvailable_bytes) / avg(node_memory_MemTotal_bytes))) * 100'
                        memory_response = await client.get(
                            f"{prometheus_url}/api/v1/query",
                            params={"query": memory_query}
                        )
                        if memory_response.status_code == 200:
                            memory_data = memory_response.json()
                            if memory_data.get("status") == "success" and memory_data.get("data", {}).get("result"):
                                results = memory_data["data"]["result"]
                                if results:
                                    memory_values = [float(r["value"][1]) for r in results]
                                    avg_memory = sum(memory_values) / len(memory_values) if memory_values else 0
                                    performance_context += f"\n💾 Son 15 dakikalık ortalama Memory kullanımı: {avg_memory:.2f}%\n"
                    except Exception as e:
                        logger.warning(f"Memory metrik çekme hatası: {e}")
                    
                    # Disk metrikleri
                    try:
                        disk_query = '(1 - (avg(node_filesystem_avail_bytes{mountpoint="/"}) / avg(node_filesystem_size_bytes{mountpoint="/"}))) * 100'
                        disk_response = await client.get(
                            f"{prometheus_url}/api/v1/query",
                            params={"query": disk_query}
                        )
                        if disk_response.status_code == 200:
                            disk_data = disk_response.json()
                            if disk_data.get("status") == "success" and disk_data.get("data", {}).get("result"):
                                results = disk_data["data"]["result"]
                                if results:
                                    disk_values = [float(r["value"][1]) for r in results]
                                    avg_disk = sum(disk_values) / len(disk_values) if disk_values else 0
                                    performance_context += f"\n💿 Son 15 dakikalık ortalama Disk kullanımı: {avg_disk:.2f}%\n"
                    except Exception as e:
                        logger.warning(f"Disk metrik çekme hatası: {e}")
                
                if not performance_context:
                    performance_context = "\n⚠️ Prometheus'tan metrik çekilemedi. Node Exporter'ların kurulu ve çalışır durumda olduğundan emin olun.\n"
            except Exception as e:
                logger.warning(f"Prometheus metrik çekme hatası: {e}")
                performance_context = "\n⚠️ Prometheus metrikleri şu anda kullanılamıyor.\n"
        
        # User mesajını kaydet
        from datetime import datetime
        user_msg = {
            "id": len(chat_messages[session_id]),
            "role": "user",
            "content": message,
            "created_at": datetime.now().isoformat()
        }
        chat_messages[session_id].append(user_msg)
        
        # Ollama'ya istek gönder
        try:
            ollama_url = settings.OLLAMA_URL
            model = settings.OLLAMA_DEFAULT_MODEL
            
            prompt = f"""Sen bir sunucu yönetim asistanısın. Türkçe yanıt ver.

{server_context}
{performance_context}

Kullanıcı sorusu: {message}

Lütfen net, kısa ve yardımcı bir yanıt ver. Performans soruları için yukarıdaki metrikleri kullan. Gerekirse komut önerileri de sun."""

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
                    
                    # AI yanıtını kaydet
                    assistant_msg = {
                        "id": len(chat_messages[session_id]),
                        "role": "assistant",
                        "content": ai_response,
                        "created_at": datetime.now().isoformat()
                    }
                    chat_messages[session_id].append(assistant_msg)
                    
                    # Session'ı güncelle
                    chat_sessions[session_id]["updated_at"] = datetime.now().isoformat()
                    
                    return ChatResponse(
                        response=ai_response,
                        commands=None,
                        suggestions=None,
                        session_id=session_id
                    )
                else:
                    logger.error(f"Ollama error: {response.status_code} - {response.text}")
                    error_response = f"AI servisi yanıt veremedi (HTTP {response.status_code}). Ollama servisinin çalıştığından emin olun."
                    
                    # Hata mesajını kaydet
                    error_msg = {
                        "id": len(chat_messages[session_id]),
                        "role": "assistant",
                        "content": error_response,
                        "created_at": datetime.now().isoformat()
                    }
                    chat_messages[session_id].append(error_msg)
                    
                    return ChatResponse(
                        response=error_response,
                        commands=None,
                        suggestions=None,
                        session_id=session_id
                    )
        except httpx.TimeoutException:
            logger.error("Ollama timeout")
            error_response = "AI servisi zaman aşımına uğradı. Lütfen tekrar deneyin."
            error_msg = {
                "id": len(chat_messages[session_id]),
                "role": "assistant",
                "content": error_response,
                "created_at": datetime.now().isoformat()
            }
            chat_messages[session_id].append(error_msg)
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id
            )
        except httpx.ConnectError:
            logger.error("Ollama connection error")
            error_response = "AI servisine bağlanılamadı. Ollama servisinin çalıştığından emin olun."
            error_msg = {
                "id": len(chat_messages[session_id]),
                "role": "assistant",
                "content": error_response,
                "created_at": datetime.now().isoformat()
            }
            chat_messages[session_id].append(error_msg)
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id
            )
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            error_response = f"AI servisi hatası: {str(e)}"
            error_msg = {
                "id": len(chat_messages[session_id]),
                "role": "assistant",
                "content": error_response,
                "created_at": datetime.now().isoformat()
            }
            chat_messages[session_id].append(error_msg)
            return ChatResponse(
                response=error_response,
                commands=None,
                suggestions=None,
                session_id=session_id
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
