"""
Windows AI Chat API endpoints — WinRM canlı veri + SystemEvent (Event Log) geçmişi + RAG.
Linux `chat.py` ile aynı mimari (session/DB, streaming, çoklu LLM sağlayıcı),
veri toplama katmanı SSH yerine WinRM/PowerShell kullanır.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, delete
from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone, timedelta
import asyncio
import json as _json
import logging
import httpx

from app.core.database import get_db
from app.core.config import settings, get_active_model
from app.models.server import Server
from app.models.chat_session import ChatSession, ChatMessage
from app.models.event import SystemEvent
from app.services.platform_scope import is_windows_server

logger = logging.getLogger(__name__)

CATEGORY = "windows"

router = APIRouter()


def _detect_provider(model: str) -> str:
    """Model adından sağlayıcıyı tespit et (chat.py ile aynı mantık)."""
    m = (model or "").lower()
    if m.startswith("groq:") or any(x in m for x in ["llama3-70b", "llama3-8b", "mixtral-8x7b", "gemma2-9b", "llama-3.1-70b", "llama-3.3-70b"]):
        return "groq"
    if m.startswith("gpt-") or m.startswith("openai/") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("claude") or m.startswith("anthropic/"):
        return "anthropic"
    if "/" in m and not m.startswith("http"):
        return "openrouter"
    return "ollama"


async def _stream_external_openai(client, url: str, api_key: str, model: str, prompt: str, extra_headers: dict = None):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        "model": model.replace("groq:", "").replace("openai/", ""),
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": 2048,
    }
    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            yield f"[API Hatası {resp.status_code}: {body.decode()[:200]}]"
            return
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = _json.loads(data)
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    yield token
            except Exception:
                continue


def _get_windows_servers(db: Session, ai_ready_only: bool = True) -> List[Server]:
    q = db.query(Server)
    if ai_ready_only:
        q = q.filter(Server.ai_ready == True)
    return [s for s in q.all() if is_windows_server(s)]


def _build_windows_client(server: Server, db: Session):
    """windows_log_collector'daki kimlik/istemci çözümleme mantığını yeniden kullanır."""
    from app.services.windows_log_collector import _build_client
    return _build_client(server, db)


def _windows_event_context(db: Session, selected_servers: List[Server], hours: int = 24) -> str:
    """Periyodik toplayıcının (windows_log_collector) DB'ye yazdığı Event Log kayıtlarından özet."""
    if not selected_servers:
        return ""
    ids = [s.id for s in selected_servers]
    since = datetime.utcnow() - timedelta(hours=hours)
    events = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.server_id.in_(ids),
            SystemEvent.created_at >= since,
            SystemEvent.severity.in_(["critical", "warning"]),
            # Sadece OS (WinRM/Event Log) kaynaklı kayıtlar — bir Windows VM'e
            # ait vCenter/sanallaştırma olayı buraya sızmasın.
            SystemEvent.source.notin_([
                "vcenter_event", "vcenter_alarm", "vcenter_task",
                "virt_collector", "virt_resource",
            ]),
        )
        .order_by(SystemEvent.created_at.desc())
        .limit(40)
        .all()
    )
    if not events:
        return ""
    name_map = {s.id: s.name for s in selected_servers}
    lines = [f"SON {hours} SAATTEKI WINDOWS EVENT LOG KAYITLARI (veritabanindan, periyodik toplanmis):"]
    for e in events:
        lines.append(f"- [{(e.severity or '').upper()}] {name_map.get(e.server_id, '?')}: {e.title}")
    return "\n".join(lines)


class ChatRequest(BaseModel):
    message: str
    server_ids: Optional[List[int]] = None
    server_id: Optional[int] = None
    session_id: Optional[int] = None
    model: Optional[str] = None
    use_rag: Optional[bool] = True
    skip_server_context: Optional[bool] = False


class ChatResponse(BaseModel):
    response: str
    session_id: Optional[int] = None


def _session_to_dict(session: ChatSession, message_count: int = 0) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "server_ids": session.server_ids or [],
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "message_count": message_count,
    }


@router.get("/models")
async def list_available_models(db: Session = Depends(get_db)):
    try:
        ollama_url = settings.OLLAMA_URL
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [
                    {
                        "name": m.get("name"),
                        "size": m.get("size"),
                        "parameter_size": m.get("details", {}).get("parameter_size"),
                        "family": m.get("details", {}).get("family"),
                    }
                    for m in data.get("models", [])
                ]
                return {"success": True, "models": models, "default": get_active_model(db)}
            return {"success": False, "models": [], "default": get_active_model(db), "error": "Ollama'ya bağlanılamadı"}
    except Exception as e:
        logger.error(f"Model listesi alınamadı: {e}")
        return {"success": False, "models": [], "default": get_active_model(db), "error": str(e)}


@router.get("/sessions")
async def list_chat_sessions(db: Session = Depends(get_db)):
    """Windows AI chat session'larını listele (DB'den)"""
    sessions = db.query(ChatSession).filter(
        ChatSession.category == CATEGORY
    ).order_by(
        func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc()
    ).all()
    result = []
    for s in sessions:
        count = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
        result.append(_session_to_dict(s, message_count=count))
    return result


@router.post("/sessions")
async def create_chat_session(server_ids: Optional[List[int]] = None, db: Session = Depends(get_db)):
    session = ChatSession(title="Yeni Chat", server_ids=server_ids or [], category=CATEGORY)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_to_dict(session, message_count=0)


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int, db: Session = Depends(get_db)):
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
async def update_session_title(session_id: int, title: str, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.title = title
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, db: Session = Depends(get_db)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    db.delete(session)
    db.commit()
    return {"success": True}


@router.delete("/sessions")
async def delete_all_sessions(db: Session = Depends(get_db)):
    ids = [s.id for s in db.query(ChatSession.id).filter(ChatSession.category == CATEGORY).all()]
    if ids:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
        db.commit()
    return {"success": True, "cleared": len(ids)}


# ── Anahtar kelime tespiti (WinRM veri toplamayı ne zaman tetikleyelim) ─────
_ALL_WINRM_KEYWORDS = [
    'cpu', 'ram', 'memory', 'bellek', 'performans', 'performance', 'kullanım', 'usage',
    'yük', 'load', 'durum', 'status', 'genel', 'özet',
    'disk', 'depolama', 'storage', 'sürücü', 'drive', 'alan', 'space', 'c:', 'd:',
    'servis', 'service', 'hizmet', 'durdu', 'stopped', 'başla', 'start', 'restart',
    'log', 'event log', 'olay günlüğü', 'günlük', 'hata', 'error', 'warning', 'uyarı',
    'kritik', 'critical', 'exception',
    'update', 'güncelleme', 'yama', 'patch', 'kb',
    'network', 'ağ', 'ip adres', 'ethernet', 'adaptör',
    'os', 'işletim sistemi', 'windows sürüm', 'version', 'versiyon', 'build',
    'domain', 'hostname', 'donanım', 'hardware', 'cpu model', 'işlemci',
]


def _build_prompt(message: str, context_str: str, winrm_collected: bool,
                   winrm_server_count: int, selected_server_names: List[str]) -> str:
    NL = "\n"
    coll = []
    if winrm_collected and winrm_server_count > 0:
        names = ", ".join(selected_server_names[:5])
        if len(selected_server_names) > 5:
            names += " ve {} sunucu daha".format(len(selected_server_names) - 5)
        coll.append(f"WINRM DURUMU: {winrm_server_count} sunucudan gercek veri toplandi ({names}).")
    elif selected_server_names:
        names = ", ".join(selected_server_names[:5])
        coll.append(
            f"WINRM DURUMU: Bu sorgu icin WinRM verisi toplanmadi (sunucular: {names})."
            " Kullaniciya soruyu daha spesifik girmesini onerebilirsin."
        )
    collection_summary = NL.join(coll)

    identity = NL.join([
        "Sen AINE (AI Infrastructure Engine) adinda, 15+ yillik deneyime sahip kıdemli bir",
        "Windows Server Sistem Yoneticisisin (Senior Windows Systems Administrator).",
        "",
        "UZMANLIK ALANLARIN:",
        "- Windows Server 2012/2016/2019/2022, Active Directory, DNS, DHCP, Group Policy",
        "- PowerShell scripting, WMI/CIM sorgulari, Event Viewer analizi",
        "- IIS, .NET uygulamalari, MSSQL temel yonetim",
        "- Windows Update yonetimi (WSUS), yama/patch stratejileri",
        "- Servis yonetimi (services.msc), Task Scheduler, Performance Monitor",
        "- Disk yonetimi (Disk Management, Storage Spaces), NTFS izinleri",
        "- Ag: ipconfig, netstat, Windows Firewall, NIC teaming",
        "- Guvenlik: Windows Defender, BitLocker, yerel/domain hesap politikalari",
        "",
        "SISTEM YETENEKLERI:",
        "- Yonetilen Windows sunuculara WinRM/PowerShell ile baglanip gercek veri toplayabiliyor",
        "  (Get-CimInstance, Get-Service, Get-WinEvent, Get-PSDrive, Windows Update COM API vb.)",
        "- Gecmiste toplanmis Event Log kayitlari (System/Application) veritabaninda saklaniyor",
        "- Gecmis konusma, runbook'lar ve incident kayitlari kullanilabiliyor",
        "",
        "ONEMLI: Asla 'WinRM yapamam' veya 'dogrudan baglanamam' deme.",
        "Sistem WinRM yapabiliyor. Eger veri gelmemisse toplanmamis demektir, toplanamaz degil.",
    ])

    rules = NL.join([
        "YANIT KURALLARI:",
        "1. BAGLAM bolumundeki GERCEK veriyi once kullan — kendi bilginle asla tahmin yapma",
        "2. Baglam bos veya yetersizse: 'Bu sunucu icin WinRM verisi alinamadi (baglanamadi veya zaman asimi).' de.",
        "   ASLA 'tekrar deneniyor' veya 'bekleniyor' deme — bu sistem otomatik retry yapmaz.",
        "3. ASLA 'WinRM yapamam', 'dogrudan baglanamam', 'veri tabanindan bakiyorum' yazma.",
        "4. Tablo istenirse Markdown tablo kullan (| kolon | kolon |)",
        "5. Turkce yanitla — kisaltmadan, net ve aciklayici yaz",
        "6. Veri varsa asla 'bilmiyorum' ya da 'emin degilim' deme — veriyi yorumla",
        "",
        "UZMAN YANIT TARZI:",
        "7. Her soruyu bir kıdemli admin gibi ele al:",
        "   - Once olasi KOKEN NEDENLER (root cause) belirt",
        "   - Somut TANI KOMUTU oner (calistirilabilir PowerShell)",
        "   - COZUM ADIMLARI numarali liste halinde ver",
        "   - Varsa UYARI / RISK bilgisi ekle",
        "8. Kritik islemler icin (Restart-Service, Remove-Item, Restart-Computer) MUTLAKA uyari ver",
        "   ve once yedek/onay al de.",
    ])

    prompt_parts = [identity]
    if collection_summary:
        prompt_parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    prompt_parts.append(rules)
    prompt_parts.append("BAGLAM:\n" + context_str)
    prompt_parts.append("KULLANICI SORUSU: " + message)
    prompt_parts.append("YANIT (Markdown, Turkce):")
    return "\n\n".join(prompt_parts)


def _sse(obj: dict) -> str:
    return "data: " + _json.dumps(obj) + "\n\n"


@router.post("/", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Non-streaming Windows chat (API parite; frontend varsayılan olarak /stream kullanır)."""
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session_id = request.session_id
    if not session_id:
        title = message[:50] + ("..." if len(message) > 50 else "")
        session = ChatSession(title=title, server_ids=request.server_ids or [], category=CATEGORY)
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id
    else:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    all_windows_servers = _get_windows_servers(db)
    selected_servers: List[Server] = []
    if request.server_ids:
        selected_servers = [s for s in all_windows_servers if s.id in request.server_ids]
    elif request.server_id:
        selected_servers = [s for s in all_windows_servers if s.id == request.server_id]
    if not selected_servers:
        selected_servers = all_windows_servers

    ml = message.lower()
    needs_winrm = any(k in ml for k in _ALL_WINRM_KEYWORDS) and not request.skip_server_context

    db.add(ChatMessage(session_id=session_id, role="user", content=message))
    db.commit()

    winrm_ctx = ""
    if needs_winrm and selected_servers:
        try:
            from app.services.windows.windows_info_collector import detect_needed_groups, collect_server_info, build_server_context
            groups = detect_needed_groups(message)
            ctxs = []
            for srv in selected_servers:
                client = _build_windows_client(srv, db)
                if not client:
                    ctxs.append(build_server_context(srv.name, srv.ip_address or "-", {"error": "WinRM kimlik bilgisi/bağlantı yok"}))
                    continue
                info = collect_server_info(client, groups)
                ctxs.append(build_server_context(srv.name, srv.ip_address or "-", info))
            winrm_ctx = "\n\n".join(ctxs)
        except Exception as e:
            logger.warning(f"WinRM info collect failed: {e}")

    context_parts = []
    if winrm_ctx:
        context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + winrm_ctx.strip())
    elif selected_servers:
        lines = [f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}" for s in selected_servers]
        context_parts.append("VERITABANI BILGILERI:\n" + "\n".join(lines))

    event_ctx = _windows_event_context(db, selected_servers)
    if event_ctx:
        context_parts.append(event_ctx)

    if request.use_rag is not False:
        try:
            from app.services.rag_service import get_rag_context_for_message
            rag_ctx = await get_rag_context_for_message(message)
            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK / DOKÜMANTASYON:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER GEÇMİŞ OLAYLAR / INCIDENT'LAR:\n" + rag_ctx["incidents"].strip())
        except Exception as rag_err:
            logger.debug(f"RAG context atlanıyor: {rag_err}")

    context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."
    prompt = _build_prompt(
        message=message,
        context_str=context_str,
        winrm_collected=bool(winrm_ctx),
        winrm_server_count=len(selected_servers) if winrm_ctx else 0,
        selected_server_names=[s.name for s in selected_servers],
    )

    try:
        ollama_url = settings.OLLAMA_URL
        model = request.model or get_active_model(db)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{ollama_url}/api/generate", json={"model": model, "prompt": prompt, "stream": False})
            if response.status_code == 200:
                ai_response = response.json().get("response", "Yanıt alınamadı")
            else:
                ai_response = f"AI servisi yanıt veremedi (Ollama HTTP {response.status_code})."
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        ai_response = f"AI servisi hatası: {str(e)}"

    db.add(ChatMessage(session_id=session_id, role="assistant", content=ai_response))
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        session.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ChatResponse(response=ai_response, session_id=session_id)


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """Streaming Windows chat: paralel WinRM + Event Log DB + RAG bağlamı → LLM SSE."""

    async def event_generator():
        try:
            message = request.message.strip()
            if not message:
                yield _sse({"error": "Mesaj boş"})
                return

            session_id = request.session_id
            if not session_id:
                title = message[:50] + ("..." if len(message) > 50 else "")
                session = ChatSession(title=title, server_ids=request.server_ids or [], category=CATEGORY)
                db.add(session)
                db.commit()
                db.refresh(session)
                session_id = session.id
            else:
                session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if not session:
                    yield _sse({"error": "Session bulunamadı"})
                    return

            yield _sse({"session_id": session_id, "start": True})

            # ── Sunucu seçimi (yalnızca Windows sunucular) ──────────────────
            all_windows_servers = _get_windows_servers(db)
            selected_servers: List[Server] = []
            if request.server_ids:
                selected_servers = [s for s in all_windows_servers if s.id in request.server_ids]
            elif request.server_id:
                selected_servers = [s for s in all_windows_servers if s.id == request.server_id]

            if not selected_servers:
                ml_srv = message.lower()
                detected = [
                    s for s in all_windows_servers
                    if (s.name and s.name.lower() in ml_srv) or (s.ip_address and s.ip_address in message)
                ]
                selected_servers = detected if detected else all_windows_servers

            ml = message.lower()
            needs_winrm = any(k in ml for k in _ALL_WINRM_KEYWORDS) and not request.skip_server_context
            context_timeout = 25.0

            server_context = ""
            if selected_servers:
                lines = [
                    f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}"
                    for s in selected_servers
                ]
                server_context = "Seçili sunucular:\n" + "\n".join(lines)

            async def _collect_winrm():
                if not needs_winrm:
                    return ""
                try:
                    from app.services.windows.windows_info_collector import (
                        detect_needed_groups, collect_server_info, build_server_context,
                    )
                    groups = detect_needed_groups(message)
                    loop = asyncio.get_event_loop()

                    def _collect_one(srv):
                        client = _build_windows_client(srv, db)
                        if not client:
                            return build_server_context(srv.name, srv.ip_address or "-", {"error": "WinRM kimlik bilgisi/bağlantı yok"})
                        info = collect_server_info(client, groups)
                        return build_server_context(srv.name, srv.ip_address or "-", info)

                    tasks = [loop.run_in_executor(None, _collect_one, srv) for srv in selected_servers]
                    done, pending = await asyncio.wait(tasks, timeout=context_timeout)
                    for t in pending:
                        t.cancel()
                    ctxs = []
                    for t in tasks:
                        if t in done:
                            try:
                                ctxs.append(t.result())
                            except Exception:
                                pass
                    return "\n\n".join(ctxs)
                except Exception as e:
                    logger.debug(f"WinRM context error: {e}")
                    return ""

            async def _collect_rag():
                if request.use_rag is False:
                    return {}
                try:
                    from app.services.rag_service import get_rag_context_for_message
                    return await get_rag_context_for_message(message)
                except Exception:
                    return {}

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(_collect_winrm(), _collect_rag(), return_exceptions=True),
                    timeout=context_timeout + 2.0,
                )
                winrm_ctx = results[0] if isinstance(results[0], str) else ""
                rag_ctx = results[1] if isinstance(results[1], dict) else {}
            except asyncio.TimeoutError:
                winrm_ctx, rag_ctx = "", {}

            event_ctx = _windows_event_context(db, selected_servers)

            context_parts = []
            if winrm_ctx:
                context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + winrm_ctx.strip())
            elif server_context:
                context_parts.append("VERITABANI BILGILERI:\n" + server_context.strip())
            if event_ctx:
                context_parts.append(event_ctx)
            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER OLAYLAR:\n" + rag_ctx["incidents"].strip())

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                winrm_collected=bool(winrm_ctx),
                winrm_server_count=len(selected_servers) if winrm_ctx else 0,
                selected_server_names=[s.name for s in selected_servers],
            )

            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.commit()

            model = request.model or get_active_model(db)
            provider = _detect_provider(model)
            full_response = ""

            async with httpx.AsyncClient(timeout=180.0) as client:
                if provider == "groq" and settings.GROQ_API_KEY:
                    async for token in _stream_external_openai(client, settings.GROQ_API_URL, settings.GROQ_API_KEY, model, prompt):
                        full_response += token
                        yield _sse({"token": token})
                elif provider == "openai" and settings.OPENAI_API_KEY:
                    async for token in _stream_external_openai(client, settings.OPENAI_API_URL, settings.OPENAI_API_KEY, model, prompt):
                        full_response += token
                        yield _sse({"token": token})
                elif provider == "openrouter" and settings.OPENROUTER_API_KEY:
                    async for token in _stream_external_openai(
                        client, settings.OPENROUTER_API_URL, settings.OPENROUTER_API_KEY, model, prompt,
                        extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"},
                    ):
                        full_response += token
                        yield _sse({"token": token})
                else:
                    async with client.stream(
                        "POST", f"{settings.OLLAMA_URL}/api/generate",
                        json={"model": model, "prompt": prompt, "stream": True},
                    ) as resp:
                        if resp.status_code != 200:
                            yield _sse({"error": f"Ollama HTTP {resp.status_code}"})
                            return
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                chunk = _json.loads(line)
                            except Exception:
                                continue
                            token = chunk.get("response", "")
                            if token:
                                full_response += token
                                yield _sse({"token": token})
                            if chunk.get("done"):
                                break

            db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response or "(yanıt alınamadı)"))
            s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if s:
                s.updated_at = datetime.now(timezone.utc)
            db.commit()

            yield _sse({"done": True, "session_id": session_id})

        except Exception as e:
            logger.error(f"Windows chat stream error: {e}", exc_info=True)
            yield _sse({"error": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
