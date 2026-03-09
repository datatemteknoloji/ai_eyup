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
from app.models.credential import GlobalCredential

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
    use_rag: Optional[bool] = True  # RAG (runbook, incident, metrik) kullanılsın mı


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
            server_context = "Secili sunucular (gercek DB verileri):\n"
            for s in selected_servers:
                os_info = s.os_version or s.os_type or "Linux"
                server_context += f"- {s.name} ({s.ip_address}): OS={os_info}, Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB\n"
        elif ai_ready_servers:
            server_context = f"AI Ready sunucular ({len(ai_ready_servers)} adet):\n"
            for s in ai_ready_servers:
                os_info = s.os_version or s.os_type or "Linux"
                server_context += f"- {s.name} ({s.ip_address}): OS={os_info}, {s.status}\n"

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
        
        # SSH ile gercek veri topla
        ssh_context = ""
        try:
            from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
            import asyncio
            if selected_servers:
                global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                groups = detect_needed_groups(message)
                all_server_contexts = []
                for srv in selected_servers:
                    info = await asyncio.get_event_loop().run_in_executor(
                        None, lambda s=srv: collect_server_info(s, groups, global_cred)
                    )
                    all_server_contexts.append(build_server_context(srv, info))
                if all_server_contexts:
                    ssh_context = "\n\n".join(all_server_contexts)
        except Exception as e:
            logger.warning(f"SSH info collect failed: {e}")
            ssh_context = ""

        ssh_results = []

        try:
            ollama_url = settings.OLLAMA_URL
            # Kullanıcının seçtiği model veya default model
            model = request.model or settings.OLLAMA_DEFAULT_MODEL
            # Basit ve net prompt oluştur
            context_parts = []
            # SSH'tan gelen gercek veri en oncelikli
            if ssh_context:
                context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (SSH):\n" + ssh_context.strip())
            elif server_context:
                context_parts.append("VERITABANI BILGILERI:\n" + server_context.strip())
            if prometheus_context:
                context_parts.append(prometheus_context.strip())

            # RAG: Runbook, geçmiş incident/event ve metrik açıklamaları (use_rag=True ise)
            if request.use_rag is not False:
                try:
                    from app.services.rag_service import get_rag_context_for_message
                    rag_ctx = await get_rag_context_for_message(message)
                    if rag_ctx.get("runbook"):
                        context_parts.append("RUNBOOK / DOKÜMANTASYON (ilgili bölümler):\n" + rag_ctx["runbook"].strip())
                    if rag_ctx.get("incidents"):
                        context_parts.append("BENZER GEÇMİŞ OLAYLAR / INCIDENT'LAR:\n" + rag_ctx["incidents"].strip())
                    if rag_ctx.get("metrics"):
                        context_parts.append("METRİK AÇIKLAMALARI:\n" + rag_ctx["metrics"].strip())
                except Exception as rag_err:
                    logger.debug(f"RAG context atlanıyor: {rag_err}")

            context_str = "\n\n".join(context_parts) if context_parts else "Sunucu bilgisi yok."

            prompt = f"""Sen Linux sistem yonetimi uzmani bir asistansin.
TURKCE yanit ver.

KESIN KURALLAR:
1. Asagidaki GERCEK VERILER, sunuculara SSH ile baglanarak toplanmistir. Bu verileri kullan.
2. RUNBOOK / BENZER OLAY / METRIK aciklamalari verildiyse, soruyla ilgiliyse onlari da kullan.
3. Kendi bilginden tahmin yapma, uydurma. Yalnizca verilen verileri kullan.
4. Eger veri yoksa "Bu bilgi mevcut degil" de.
5. Tablo formatinda istenmisse Markdown tablo olustur (| kolon | kolon |).
6. Rapor istenmisse bolumler halinde duzenli sunum yap.

{context_str}

KULLANICI SORUSU: {message}

YANIT (Markdown formatinda, Turkce):"""

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
                    # Ollama'dan gelen hata metnini oku (model bulunamadı, bellek vb.)
                    ollama_error_detail = ""
                    try:
                        body = response.json()
                        if isinstance(body, dict):
                            ollama_error_detail = body.get("error", "") or body.get("message", "") or ""
                    except Exception:
                        if response.text and len(response.text) < 300:
                            ollama_error_detail = response.text
                    extra = f"**Ollama hatası:** {ollama_error_detail}" if ollama_error_detail else ""
                    error_response = (
                        "AI servisi yanıt veremedi (Ollama HTTP %d).\n\n"
                        "**Kontrol edin:**\n"
                        "• Ollama çalışıyor mu? `curl %s/api/tags`\n"
                        "• Model yüklü mü? `ollama list` ve `ollama run %s`\n"
                        "• Sunucuda bellek yeterli mi?"
                    ) % (
                        response.status_code,
                        settings.OLLAMA_URL.rstrip("/"),
                        (request.model or settings.OLLAMA_DEFAULT_MODEL).split(":")[0],
                    )
                    if extra:
                        error_response += "\n\n" + extra
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
        # 500 döndürmek yerine kullanıcıya anlamlı mesaj ver; session varsa kaydet
        err_msg = (
            "AI servisi yanıt veremedi. Ollama servisinin çalıştığından emin olun. "
            "(Bağlantı, zaman aşımı veya geçici hata olabilir.)"
        )
        # session_id satır 206'da her zaman tanımlanır; NameError oluşamaz.
        # None ise oturum oluşturulmadan hata çıktı demektir — DB kaydı atlanır.
        try:
            if session_id is not None:
                err_assistant = ChatMessage(session_id=session_id, role="assistant", content=err_msg)
                db.add(err_assistant)
                sess = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if sess:
                    sess.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception as db_err:
            logger.warning(f"Could not save error message to session: {db_err}")
        return ChatResponse(
            response=err_msg,
            commands=None,
            suggestions=None,
            session_id=session_id,
        )
