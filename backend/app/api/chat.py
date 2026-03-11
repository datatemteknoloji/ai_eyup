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

        # Önce Prometheus (Node Exporter metrikleri) — SSH'a gerek kalmadan çoğu metrik buradan gelir
        PROMETHEUS_KEYWORDS = [
            'cpu', 'ram', 'memory', 'bellek', 'disk', 'network', 'ağ', 'bandwidth',
            'uptime', 'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
            'kullanım', 'usage', 'durum', 'status', 'genel', 'overview', 'özet',
            'sunucu', 'server', 'makine', 'machine', 'trafik', 'traffic',
        ]
        SSH_ONLY_KEYWORDS = [
            'log', 'journal', 'hata mesaj', 'error log', 'syslog',
            'proses', 'process', 'ps aux', 'çalışan', 'running process',
            'config', 'yapılandırma', 'konfigür', '/etc/', '/var/',
            'komut çalıştır', 'run command', 'execute',
            'servis restart', 'service restart', 'systemctl',
            'installed', 'kurulu', 'paket', 'package', 'version',
            'vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz',
            'io performans', 'disk performans', 'benchmark',
        ]
        # OS/kernel/sistem bilgisi → Prometheus'ta yok, SSH gerekir
        SSH_SYSINFO_KEYWORDS = [
            'os', 'işletim', 'operating system', 'kernel', 'distro', 'distribution',
            'revision', 'revizyon', 'sürüm', 'release', 'versiyon',
            'rhel', 'centos', 'ubuntu', 'debian', 'oracle linux', 'oracle',
            'servis', 'service', 'running service', 'failed service',
            'hostname', 'makine adi', 'sistem bilgi',
            'selinux', 'sestatus', 'getenforce', 'enforcing', 'permissive',
            'firewall', 'firewalld', 'iptables', 'güvenlik', 'security',
            'açık port', 'open port', 'sudo', 'sudoers',
            'uname', 'kernel versiyonu', 'çekirdek versiyonu',
        'mac', 'mac adresi', 'mac address', 'ifconfig', 'donanim adresi',
        'network', 'ağ arayüz', 'ethernet', 'ip link', 'ip addr', 'arp',
        ]
        DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
        msg_lower_ctx = message.lower()
        needs_prometheus = any(k in msg_lower_ctx for k in PROMETHEUS_KEYWORDS)
        SERVER_TRIGGER_CTX = PROMETHEUS_KEYWORDS + SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS
        needs_ssh_ctx = any(k in msg_lower_ctx for k in SERVER_TRIGGER_CTX)
        ssh_timeout_ctx = 75.0 if any(k in msg_lower_ctx for k in DEEP_PERF_KEYWORDS) else 12.0

        prometheus_context = ""
        if needs_prometheus:
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
                logger.warning(f"Prometheus context hatası: {e}")

        # User mesajını DB'ye kaydet
        user_msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=message,
        )
        db.add(user_msg)
        db.commit()
        
        # SSH ile gercek veri topla — sunucu keyword olmayan sohbet mesajlarında atla
        ssh_context = ""
        try:
            from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
            import asyncio
            if selected_servers and (needs_ssh_ctx or (needs_prometheus and not prometheus_context)):
                global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                groups = detect_needed_groups(message)
                loop = asyncio.get_event_loop()
                # Tüm sunuculara paralel bağlan
                tasks = [
                    loop.run_in_executor(None, lambda s=srv: collect_server_info(s, groups, global_cred))
                    for srv in selected_servers
                ]
                done, pending = await asyncio.wait(tasks, timeout=ssh_timeout_ctx)
                for t in pending:
                    t.cancel()
                    logger.warning(f"SSH paralel timeout ({ssh_timeout_ctx}s): bir sunucu yanıt vermedi")
                all_server_contexts = []
                for i, t in enumerate(tasks):
                    if t in done:
                        try:
                            info = t.result()
                            all_server_contexts.append(build_server_context(selected_servers[i], info))
                        except Exception as e_srv:
                            logger.debug(f"SSH failed for {selected_servers[i].name}: {e_srv}")
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
                focused = _extract_focused_summary(message, all_server_contexts)
                if focused:
                    context_parts.append(focused)
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

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                ssh_collected=bool(ssh_context),
                ssh_server_count=len(all_server_contexts) if ssh_context else 0,
                prometheus_available=bool(prometheus_context),
                selected_server_names=[s.name for s in selected_servers],
            )

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





import re as _re

# Keyword → bağlamdan hangi satırları öne çıkar
_FOCUS_PATTERNS = {
    "selinux":    ["SELinux Durumu", "SELinux status", "getenforce", "Enforcing", "Permissive", "Disabled", "disabled"],
    "sestatus":   ["SELinux Durumu", "SELinux status"],
    "firewall":   ["Firewall Durumu", "firewalld", "iptables", "inactive", "active"],
    "iptables":   ["Firewall Durumu", "iptables"],
    "uname":     ["Kernel", "kernel_full", "kernel_version", "uname"],
    "hostname":  ["OS", "hostname", "Hostname", "Static hostname"],
    "free":      ["Bellek", "RAM", "Mem:", "Swap:", "free -"],
    "free -m":   ["Bellek", "RAM", "Mem:", "Swap:"],
    "df":        ["Disk", "Filesystem", "df -h"],
    "df -h":     ["Disk", "Filesystem"],
    "uptime":    ["Uptime", "load average"],
    "kernel":     ["Kernel"],
    "os":         ["OS", "PRETTY_NAME", "Oracle", "Red Hat", "Ubuntu", "CentOS"],
    "revision":   ["OS", "PRETTY_NAME", "VERSION"],
    "cpu":        ["CPU", "load average"],
    "disk":       ["Disk", "df -h"],
    "memory":     ["Bellek", "Memory", "free -h"],
    "port":       ["Açık Portlar", "LISTEN"],
    "log":        ["Hata Loglari"],
    "servis":     ["Calisan Servisler", "Hatali Servisler"],
    "mac":        ["MAC Adresleri", "link/ether", "ether ", "MAC"],
    "mac adresi": ["MAC Adresleri", "link/ether", "ether "],
    "mac address":["MAC Adresleri", "link/ether", "ether "],
    "ifconfig":   ["ifconfig", "MAC Adresleri", "Ag Arayuzleri", "link/ether", "ether "],
    "network":    ["Ag Arayuzleri", "MAC Adresleri", "ifconfig", "link/ether"],
    "ethernet":   ["MAC Adresleri", "link/ether", "ether "],
    "arp":        ["MAC Adresleri", "link/ether"],
}


def _extract_focused_summary(message: str, ssh_contexts: list) -> str:
    """
    Soru ile ilgili alanları tüm sunucu bağlamlarından çıkarıp
    başa yerleştir. Model önce bunu görür.
    Eşleşen pattern yoksa her sunucunun ilk birkaç satırını özetle.
    """
    ml = message.lower()
    matched_patterns = []
    for kw, patterns in _FOCUS_PATTERNS.items():
        if kw in ml:
            matched_patterns.extend(patterns)
    # Eşleşme yoksa temel bilgileri her zaman öne çıkar
    if not matched_patterns:
        matched_patterns = ["Kernel", "OS", "CPU", "Bellek", "Disk", "Uptime", "uname",
                            "hostname", "Mem:", "SELinux"]

    rows = []
    for ctx in ssh_contexts:
        # Sunucu adını bul
        m = _re.match(r"=== (.+?) \((.+?)\) ===", ctx)
        if not m:
            continue
        srv_name = m.group(1)
        srv_ip   = m.group(2)
        # İlgili satırları topla
        relevant = []
        for line in ctx.split("\n"):
            for pat in matched_patterns:
                if pat.lower() in line.lower():
                    cleaned = line.strip()
                    if cleaned and cleaned not in relevant:
                        relevant.append(cleaned)
        if relevant:
            rows.append("**{}** ({}):\n  {}".format(srv_name, srv_ip, "\n  ".join(relevant)))

    if not rows:
        return ""

    return (
        "ODAKLI OZET (soruyla ilgili veriler -- BUNLARI KULLAN):\n"
        + "\n".join(rows)
        + "\n"
    )


def _build_prompt(
    message,
    context_str,
    ssh_collected,
    ssh_server_count,
    prometheus_available,
    selected_server_names,
):
    NL = "\n"
    parts = []

    # Toplama durumu ozeti
    coll = []
    if ssh_collected and ssh_server_count > 0:
        names = ", ".join(selected_server_names[:5])
        if len(selected_server_names) > 5:
            names += " ve {} sunucu daha".format(len(selected_server_names) - 5)
        coll.append("SSH DURUMU: {} sunucudan gercek veri toplandı ({}).".format(ssh_server_count, names))
    elif selected_server_names:
        names = ", ".join(selected_server_names[:5])
        coll.append(
            "SSH DURUMU: Bu sorgu icin SSH verisi toplanmadi (sunucular: {})."
            " Kullaniciya soruyu daha spesifik girmesini onerebilirsin.".format(names)
        )
    if prometheus_available:
        coll.append("PROMETHEUS: Node Exporter metrikleri mevcut.")
    collection_summary = NL.join(coll)

    identity = NL.join([
        "Sen bir Linux altyapi yonetim asistanisin. Adin AINE (AI Infrastructure Engine).",
        "",
        "YETENEKLERIN:",
        "- Bu sistem yonetilen sunuculara SSH ile baglanip gercek komutlar calistirabiliyor",
        "  (sestatus, getenforce, df, ps, journalctl, vmstat, iostat vb.)",
        "- Prometheus/Node Exporter uzerinden CPU, RAM, disk, network metrikleri okunabiliyor",
        "- Gecmis konusma verileri ve runbook'lar kullanilabiliyor",
        "",
        "ONEMLI: Asla 'SSH yapamam' veya 'dogrudan baglanamam' deme.",
        "Sistem SSH yapabiliyor. Eger veri gelmemisse toplanmamis demektir, toplanamaz degil.",
    ])

    rules = NL.join([
        "KURALLAR:",
        "1. BAGLAM bolumundeki gercek veriyi once kullan, kendi bilginle tahmin yapma",
        "2. Baglam bos veya yetersizse: asagidaki formati kullan:",
        "   '> Bu bilgi icin sunuculardan veri toplanmadi.'",
        "   '> Simdi tekrar deneniyor... veya sunucu adini belirterek tekrar sor.'",
        "3. ASLA 'SSH yapamam', 'dogrudan baglanamam', 'veri tabanindan bakiyorum' yazma",
        "   Dogru cumle: 'Bu sorgu icin SSH verisi toplanmamis, asagidaki gibi sor:'",
        "4. Tablo istenirse Markdown tablo kullan (| kolon | kolon |)",
        "5. Turkce yanitla — kisaltmadan, net ve acimlayici yaz",
        "6. Veri varsa asla 'bilmiyorum' ya da 'emin degilim' deme, veriyi yorumla",
    ])

    prompt_parts = [identity]
    if collection_summary:
        prompt_parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    prompt_parts.append(rules)
    prompt_parts.append("BAGLAM:\n" + context_str)
    prompt_parts.append("KULLANICI SORUSU: " + message)
    prompt_parts.append("YANIT (Markdown, Turkce):")

    return "\n\n".join(prompt_parts)


# ── Streaming chat endpoint ──────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import json as _json
import asyncio as _asyncio


def _sse(obj: dict) -> str:
    return "data: " + _json.dumps(obj) + "\n\n"


@router.post("/stream")
async def chat_stream(request: "ChatRequest", db: Session = Depends(get_db)):
    """Streaming chat: cache → paralel context → Ollama SSE"""
    from app.services.chat_cache_service import get_cached_answer, save_to_cache

    async def event_generator():
        try:
            message = request.message.strip()
            if not message:
                yield _sse({"error": "Mesaj boş"})
                return

            # ── Session ──────────────────────────────────────────────────
            session_id = request.session_id
            if not session_id:
                title = message[:50] + ("..." if len(message) > 50 else "")
                session = ChatSession(title=title, server_ids=request.server_ids or [])
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

            # ── 1. Cache kontrolü ─────────────────────────────────────────
            server_ids = request.server_ids or []
            cached = get_cached_answer(db, message, server_ids)
            if cached:
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                db.commit()
                answer = cached["answer"]
                for i in range(0, len(answer), 8):
                    yield _sse({"token": answer[i:i+8]})
                db.add(ChatMessage(session_id=session_id, role="assistant", content=answer))
                s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s:
                    from datetime import datetime, timezone
                    s.updated_at = datetime.now(timezone.utc)
                db.commit()
                yield _sse({"done": True, "session_id": session_id, "from_cache": True})
                return

            # ── 2. Seçili sunucular ───────────────────────────────────────
            selected_servers = []
            if request.server_ids:
                selected_servers = db.query(Server).filter(
                    Server.id.in_(request.server_ids), Server.ai_ready == True
                ).all()
            elif request.server_id:
                srv = db.query(Server).filter(
                    Server.id == request.server_id, Server.ai_ready == True
                ).first()
                if srv:
                    selected_servers = [srv]
            if not selected_servers:
                selected_servers = db.query(Server).filter(Server.ai_ready == True).all()

            server_context = ""
            if selected_servers:
                lines = [
                    f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, "
                    f"Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB"
                    for s in selected_servers
                ]
                server_context = "Seçili sunucular:\n" + "\n".join(lines)

            # ── 3. Keyword analizi ────────────────────────────────────────
            PROMETHEUS_KEYWORDS = [
                'cpu', 'ram', 'memory', 'bellek', 'disk', 'network', 'ağ', 'bandwidth',
                'uptime', 'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
                'kullanım', 'usage', 'durum', 'status', 'genel', 'overview', 'özet',
                'sunucu', 'server', 'makine', 'machine', 'trafik', 'traffic',
            ]
            SSH_ONLY_KEYWORDS = [
                'log', 'journal', 'hata mesaj', 'error log', 'syslog',
                'proses', 'process', 'ps aux', 'çalışan', 'running process',
                'config', 'yapılandırma', 'konfigür', '/etc/', '/var/',
                'komut çalıştır', 'run command', 'execute',
                'servis restart', 'service restart', 'systemctl',
                'installed', 'kurulu', 'paket', 'package', 'version',
                'vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz',
                'io performans', 'disk performans', 'benchmark',
            ]
            SSH_SYSINFO_KEYWORDS = [
                'os', 'işletim', 'operating system', 'kernel', 'distro', 'distribution',
                'revision', 'revizyon', 'sürüm', 'release', 'versiyon',
                'rhel', 'centos', 'ubuntu', 'debian', 'oracle linux', 'oracle',
                'servis', 'service', 'running service', 'failed service',
                'hostname', 'makine adi', 'sistem bilgi',
                'selinux', 'sestatus', 'getenforce', 'enforcing', 'permissive',
                'firewall', 'firewalld', 'iptables', 'güvenlik', 'security',
                'açık port', 'open port', 'sudo', 'sudoers',
                'uname', 'kernel versiyonu', 'çekirdek versiyonu',
            'mac', 'mac adresi', 'mac address', 'ifconfig', 'donanim adresi',
            'network', 'ağ arayüz', 'ethernet', 'ip link', 'ip addr', 'arp',
            ]
            DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
            ml = message.lower()
            needs_prometheus = any(k in ml for k in PROMETHEUS_KEYWORDS)
            # SSH: sunucu/sistem sorusu içeriyorsa her zaman çalıştır (keyword listesine bağlı değil)
            SERVER_TRIGGER = PROMETHEUS_KEYWORDS + SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS
            needs_ssh = any(k in ml for k in SERVER_TRIGGER)
            is_deep         = any(k in ml for k in DEEP_PERF_KEYWORDS)
            context_timeout = 75.0 if is_deep else 12.0

            global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()

            # ── 4. Paralel context toplama ────────────────────────────────
            async def _collect_prometheus():
                if not needs_prometheus:
                    return ""
                try:
                    return await PrometheusMetricsService().get_metrics_context_for_ai(message)
                except Exception:
                    return ""

            async def _collect_ssh():
                if not (needs_ssh or needs_prometheus):
                    return ""
                try:
                    from app.services.linux_info_collector import (
                        detect_needed_groups, collect_server_info, build_server_context as _bsc,
                    )
                    groups = detect_needed_groups(message)
                    loop = _asyncio.get_event_loop()
                    tasks = [
                        loop.run_in_executor(None, lambda s=srv: collect_server_info(s, groups, global_cred))
                        for srv in selected_servers
                    ]
                    done, pending = await _asyncio.wait(tasks, timeout=context_timeout)
                    for t in pending:
                        t.cancel()
                    ctxs = []
                    for i, t in enumerate(tasks):
                        if t in done:
                            try:
                                info = t.result()
                                ctxs.append(_bsc(selected_servers[i], info))
                            except Exception:
                                pass
                    return "\n\n".join(ctxs)
                except Exception as e:
                    logger.debug(f"SSH context error: {e}")
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
                results = await _asyncio.wait_for(
                    _asyncio.gather(
                        _collect_prometheus(), _collect_ssh(), _collect_rag(),
                        return_exceptions=True,
                    ),
                    timeout=context_timeout + 2.0,
                )
                prom_ctx = results[0] if isinstance(results[0], str) else ""
                ssh_ctx  = results[1] if isinstance(results[1], str) else ""
                rag_ctx  = results[2] if isinstance(results[2], dict) else {}
            except _asyncio.TimeoutError:
                prom_ctx, ssh_ctx, rag_ctx = "", "", {}

            # ── 5. Prompt ─────────────────────────────────────────────────
            context_parts = []
            if ssh_ctx:
                # Per-server contexts for focused summary
                _ssh_server_ctxs = [c for c in ssh_ctx.split("\n\n") if c.strip()]
                focused = _extract_focused_summary(message, _ssh_server_ctxs)
                if focused:
                    context_parts.append(focused)
                context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (SSH):\n" + ssh_ctx.strip())
            elif server_context:
                context_parts.append("VERITABANI BILGILERI:\n" + server_context.strip())
            if prom_ctx:
                context_parts.append(prom_ctx.strip())
            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER OLAYLAR:\n" + rag_ctx["incidents"].strip())
            if rag_ctx.get("metrics"):
                context_parts.append("METRIK ACIKLAMALARI:\n" + rag_ctx["metrics"].strip())

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                ssh_collected=bool(ssh_ctx),
                ssh_server_count=len([s for s in selected_servers]) if ssh_ctx else 0,
                prometheus_available=bool(prom_ctx),
                selected_server_names=[s.name for s in selected_servers],
            )

            # Kullanıcı mesajını kaydet
            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.commit()

            # ── 6. Ollama streaming ───────────────────────────────────────
            model = request.model or settings.OLLAMA_DEFAULT_MODEL
            full_response = ""

            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{settings.OLLAMA_URL}/api/generate",
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
                        done_flag = chunk.get("done", False)
                        if token:
                            full_response += token
                            yield _sse({"token": token})
                        if done_flag:
                            break

            # ── 7. Kaydet + Cache ─────────────────────────────────────────
            db.add(ChatMessage(
                session_id=session_id, role="assistant",
                content=full_response or "(yanıt alınamadı)",
            ))
            s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if s:
                from datetime import datetime, timezone
                s.updated_at = datetime.now(timezone.utc)
            db.commit()

            # SSH verisi içeren yanıtlar canlı veri — cache'e kaydetme
            if full_response and not is_deep and not needs_ssh:
                save_to_cache(db, message, full_response, server_ids)

            yield _sse({"done": True, "session_id": session_id})

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield _sse({"error": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
