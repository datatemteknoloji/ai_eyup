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
import re
import unicodedata
import httpx

from app.core.database import get_db
from app.core.config import settings, get_active_model, remote_llm_enabled
from app.models.server import Server
from app.models.hypervisor import Hypervisor
from app.models.chat_session import ChatSession, ChatMessage
from app.services.monitoring.prometheus_metrics import PrometheusMetricsService
from app.models.credential import GlobalCredential
from app.services.platform_scope import is_windows_server
from app.services import llm_gateway

logger = logging.getLogger(__name__)


def _linux_ai_ready_servers(db: Session):
    """AI Ready sunucular — Windows sunucular hariç (Linux AI asistanı yalnızca Linux'ta çalışır)."""
    return [s for s in db.query(Server).filter(Server.ai_ready == True).all() if not is_windows_server(s)]

def _detect_provider(model: str) -> str:
    """Model adından sağlayıcıyı tespit et."""
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
    """OpenAI-uyumlu API için streaming generator (Groq, OpenAI, OpenRouter)."""
    import json as _j
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
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
                chunk = _j.loads(data)
                token = chunk["choices"][0]["delta"].get("content", "")
                if token:
                    yield token
            except Exception:
                continue


router = APIRouter()


@router.get("/models")
async def list_available_models(db: Session = Depends(get_db)):
    """Ollama'da (veya uzak gateway aktifse uzak sağlayıcıda) mevcut modelleri listele"""
    if remote_llm_enabled():
        model = llm_gateway.active_model_label()
        return {
            "success": True,
            "models": [{"name": model, "size": None, "parameter_size": None, "family": "remote"}],
            "default": model,
            "remote": True,
        }
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
                    "default": get_active_model(db)
                }
            else:
                return {
                    "success": False,
                    "models": [],
                    "default": get_active_model(db),
                    "error": "Ollama'ya bağlanılamadı"
                }
    except Exception as e:
        logger.error(f"Model listesi alınamadı: {e}")
        return {
            "success": False,
            "models": [],
            "default": get_active_model(db),
            "error": str(e)
        }


class ChatRequest(BaseModel):
    message: str
    server_ids: Optional[List[int]] = None
    server_id: Optional[int] = None
    hypervisor_ids: Optional[List[int]] = None
    hypervisor_id: Optional[int] = None
    session_id: Optional[int] = None
    model: Optional[str] = None  # Ollama model seçimi
    use_rag: Optional[bool] = True  # RAG (runbook, incident, metrik) kullanılsın mı
    skip_server_context: Optional[bool] = False  # SSH/Prometheus context toplama, event analizi için


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


def _normalize_user_message_for_match(message: str) -> str:
    msg = unicodedata.normalize("NFKD", message.lower())
    msg = "".join(c for c in msg if not unicodedata.combining(c))
    tr = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")
    return msg.translate(tr)


def _servers_mentioned_in_message(db: Session, message: str) -> List[Server]:
    """Mesajda geçen name / hostname / ip ile eşleşen Server satırları."""
    msg = _normalize_user_message_for_match(message)
    found: List[Server] = []
    seen: set = set()
    for s in db.query(Server).all():
        for c in ((s.name or "").strip(), (s.hostname or "").strip(), (s.ip_address or "").strip()):
            if len(c) < 3:
                continue
            try:
                if re.search(r"\b" + re.escape(c.lower()) + r"\b", msg):
                    if s.id not in seen:
                        seen.add(s.id)
                        found.append(s)
                    break
            except re.error:
                continue
    return found


@router.get("/sessions")
async def list_chat_sessions(db: Session = Depends(get_db)):
    """Linux AI chat session'larını listele (DB'den)"""
    from app.services.chat_history import repair_session_title_from_first_user_message

    sessions = db.query(ChatSession).filter(
        ChatSession.category == "linux"
    ).order_by(
        func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc()
    ).all()
    result = []
    dirty = False
    for s in sessions:
        before = s.title
        repair_session_title_from_first_user_message(db, s)
        if s.title != before:
            dirty = True
        count = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
        result.append(_session_to_dict(s, message_count=count))
    if dirty:
        db.commit()
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
        category="linux",
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
            "meta": m.meta or None,
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
    """Linux chat session'larını sil (kalıcı)"""
    ids = [s.id for s in db.query(ChatSession.id).filter(ChatSession.category == "linux").all()]
    if ids:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
        db.commit()
    return {"success": True, "cleared": len(ids)}


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
            from app.services.chat_history import title_from_message
            title = title_from_message(message)
            session = ChatSession(
                title=title,
                server_ids=request.server_ids or [],
                category="linux",
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            session_id = session.id
        else:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            from app.services.chat_history import maybe_set_session_title
            if maybe_set_session_title(session, message):
                db.commit()

        # Konusma gecmisi — bu session'da onceki mesaj var mi? (takip sorusu mu?)
        # Su anki mesaj henuz DB'ye kaydedilmeden once cekiliyor, bu yuzden hariç
        # tutma gerekmiyor. Bkz. app/services/chat_history.py docstring'i.
        from app.services.chat_history import fetch_recent_history, format_history_block
        _prior_history = fetch_recent_history(db, session_id, limit=8)
        history_block = format_history_block(_prior_history)

        # Seçili sunucuları bul
        selected_servers = []
        explicit_server_target = bool((request.server_ids and len(request.server_ids) > 0) or request.server_id or (request.hypervisor_ids and len(request.hypervisor_ids) > 0) or request.hypervisor_id)
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

        # Hypervisor hedeflenmişse, o hypervisor(lar)a bağlı AI-ready sunucuları seç
        if not selected_servers and request.hypervisor_ids and len(request.hypervisor_ids) > 0:
            selected_servers = (
                db.query(Server)
                .filter(
                    Server.hypervisor_id.in_(request.hypervisor_ids),
                    Server.ai_ready == True,
                )
                .all()
            )
        elif not selected_servers and request.hypervisor_id:
            selected_servers = (
                db.query(Server)
                .filter(
                    Server.hypervisor_id == request.hypervisor_id,
                    Server.ai_ready == True,
                )
                .all()
            )
        
        # Eğer sunucu seçilmemişse tüm AI Ready sunucuları al (Windows hariç)
        if not selected_servers:
            selected_servers = _linux_ai_ready_servers(db)
        
        ai_ready_servers = _linux_ai_ready_servers(db)

        mentioned = _servers_mentioned_in_message(db, message)
        if mentioned:
            if explicit_server_target:
                selected_servers = list(dict.fromkeys(mentioned + selected_servers))
            else:
                selected_servers = mentioned

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
            'cpu', 'ram', 'memory', 'bellek', 'disk', 'bandwidth',
            'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
            'kullanım', 'usage', 'durum', 'status', 'genel', 'overview', 'özet',
            'trafik', 'traffic', 'throughput',
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
            'netstat', 'ss -', 'ip route', 'ip addr', 'ifconfig', 'arp',
            'route', 'traceroute', 'ping', 'nmap', 'tcpdump', 'dig', 'nslookup',
            'çıktı', 'cikti', 'output', 'komut', 'command', 'göster', 'listele',
            'getir', 'ver', 'çalıştır', 'alırmısın', 'alabilirmisin',
            'lsblk', 'fdisk', 'blkid', 'lspci', 'lshw', 'dmidecode',
            'last', 'lastb', 'who', 'docker ps', 'podman ps', 'kubectl',
            'crontab', 'cat ', 'grep ', 'tail ', 'head ', 'find ',
        ]
        # OS/kernel/sistem bilgisi → Prometheus'ta yok, SSH gerekir
        APP_KEYWORDS = [
            'uygulama', 'uygulamalar', 'application', 'applications',
            'çalışıyor', 'calisiyor', 'hangi program', 'installed software',
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
            'dns', 'nameserver', 'resolv', 'resolve.conf', 'resolv.conf',
            'nslookup', 'dig', 'isim çözümleme', 'name resolution',
            'gateway', 'ağ geçidi', 'default route', 'ip route',
        ]
        DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
        msg_lower_ctx = message.lower()
        needs_prometheus = any(k in msg_lower_ctx for k in PROMETHEUS_KEYWORDS) and not request.skip_server_context
        SERVER_TRIGGER_CTX = PROMETHEUS_KEYWORDS + SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS + APP_KEYWORDS
        # Yukarıdaki elle yazılmış listeler dışında kalan ama linux_info_collector'ın
        # KEYWORD_TO_GROUPS/EXTRA_GROUPS_KEYWORDS'ünde tanımlı bir konu varsa (örn.
        # "vm.swappiness", "sysctl", "dirty_ratio" gibi kernel tuning terimleri) yine
        # SSH context topla — bkz. has_recognized_topic() docstring'i.
        from app.services.linux_info_collector import has_recognized_topic as _has_topic_ctx
        needs_ssh_ctx = (
            any(k in msg_lower_ctx for k in SERVER_TRIGGER_CTX) or _has_topic_ctx(message)
        ) and not request.skip_server_context
        ssh_timeout_ctx = 40.0 if any(k in msg_lower_ctx for k in DEEP_PERF_KEYWORDS) else 20.0

        # Kullanıcı sunucu seçmemişse yalnızca sunucu/altyapı niyeti varsa tüm AI-ready sunucuları ekle.
        if not selected_servers and needs_ssh_ctx:
            selected_servers = _linux_ai_ready_servers(db)

        # Genel sorularda (sunucu niyeti yok + sunucu seçilmedi) otomatik sunucu bağlamı ekleme.
        server_context = ""
        include_server_context = bool(selected_servers) and (needs_ssh_ctx or explicit_server_target)
        if include_server_context:
            server_context = "Secili sunucular (gercek DB verileri):\n"
            for s in selected_servers:
                os_info = s.os_version or s.os_type or "Linux"
                server_context += f"- {s.name} ({s.ip_address}): OS={os_info}, Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB\n"

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
        all_server_contexts: List[str] = []
        try:
            import asyncio
            from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
            if selected_servers and (needs_ssh_ctx or (needs_prometheus and not prometheus_context)):
                global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                if not global_cred:
                    global_cred = db.query(GlobalCredential).first()
                has_any_ssh = global_cred is not None or any(
                    (getattr(s, "connection_config", None) or {}).get("username")
                    for s in selected_servers
                )
                if not has_any_ssh:
                    logger.warning("Chat SSH: Global veya sunucu SSH bilgisi yok")
                else:
                    groups = detect_needed_groups(message)
                    loop = asyncio.get_event_loop()
                    # Paralel SSH: tüm sunucuları aynı anda sorgula, max ssh_timeout_ctx saniye bekle
                    tasks = [
                        loop.run_in_executor(
                            None,
                            lambda s=srv, g=groups, gc=global_cred, m=message: collect_server_info(s, g, gc, m),
                        )
                        for srv in selected_servers
                    ]
                    done, pending = await asyncio.wait(tasks, timeout=float(ssh_timeout_ctx))
                    for t in pending:
                        t.cancel()
                    for i, task in enumerate(tasks):
                        srv = selected_servers[i]
                        if task in done:
                            try:
                                info_result = task.result()
                                all_server_contexts.append(build_server_context(srv, info_result))
                                try:
                                    from app.services.fact_learning import extract_and_store_facts
                                    extract_and_store_facts(db, srv, info_result, platform="linux")
                                except Exception:
                                    pass
                            except Exception as e_srv:
                                logger.warning("SSH failed for %s: %s", srv.name, e_srv)
                                all_server_contexts.append(build_server_context(srv, {"error": str(e_srv)}))
                        else:
                            logger.warning("SSH zaman asimi: %s", srv.name)
                            all_server_contexts.append(
                                build_server_context(srv, {"error": f"SSH zaman asimi ({int(ssh_timeout_ctx)}s)"})
                            )
                    if all_server_contexts:
                        ssh_context = "\n\n".join(all_server_contexts)
        except Exception as e:
            logger.warning(f"SSH info collect failed: {e}")
            ssh_context = ""


        ssh_results = []

        try:
            # Kullanıcının seçtiği model veya default model
            model = request.model or get_active_model(db)
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

            # Onceden ogrenilmis yapisal gercekler (bkz. fact_learning.py) — canli
            # SSH verisi eksik/zaman asimina ugramis alanlar icin dusmeyen bir
            # fallback ve tekrar SSH'a gitmeden hizli cevap saglar.
            if selected_servers:
                try:
                    from app.services.fact_learning import get_learned_facts_block
                    _facts_blocks = []
                    for _s in selected_servers[:5]:
                        _fb = get_learned_facts_block(db, _s)
                        if _fb:
                            _facts_blocks.append(f"[{_s.name}]\n{_fb}")
                    if _facts_blocks:
                        context_parts.append(
                            "ONCEDEN OGRENILMIS BILGILER (yapisal, gecmis SSH taramalarindan — "
                            "canli BAGLAM ile celisirse canli veriyi esas al, kullanirken 'onceden "
                            "ogrenilmis (X once dogrulandi)' diye belirt):\n" + "\n\n".join(_facts_blocks)
                        )
                except Exception:
                    pass

                try:
                    from app.services.app_discovery import get_discovered_apps_block
                    _apps_blocks = []
                    for _s in selected_servers[:5]:
                        _ab = get_discovered_apps_block(db, _s)
                        if _ab:
                            _apps_blocks.append(f"[{_s.name}]\n{_ab}")
                    if _apps_blocks:
                        context_parts.append(
                            "TESPIT EDILEN UYGULAMALAR (otomatik tarama ile bulunan calisan servisler — "
                            "Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.; periyodik tarandigi icin en "
                            "guncel BAGLAM'daki canli veriyle celisirse canli veriyi esas al):\n"
                            + "\n\n".join(_apps_blocks)
                        )
                except Exception:
                    pass

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

            # Hypervisor bağlamı (seçim varsa)
            selected_hypervisors = []
            if request.hypervisor_ids and len(request.hypervisor_ids) > 0:
                selected_hypervisors = db.query(Hypervisor).filter(Hypervisor.id.in_(request.hypervisor_ids)).all()
            elif request.hypervisor_id:
                hv = db.query(Hypervisor).filter(Hypervisor.id == request.hypervisor_id).first()
                if hv:
                    selected_hypervisors = [hv]
            if selected_hypervisors:
                hv_lines = []
                for h in selected_hypervisors:
                    hv_lines.append(f"- {h.name} ({h.hypervisor_type.value if h.hypervisor_type else '-'}): host={h.hostname or '-'}, ip={h.ip_address or '-'}, port={h.port or '-'}")
                context_parts.append("SEÇİLİ HYPERVISORLAR:\n" + "\n".join(hv_lines))

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                ssh_collected=bool(ssh_context),
                ssh_server_count=len(all_server_contexts) if ssh_context else 0,
                prometheus_available=bool(prometheus_context),
                selected_server_names=[s.name for s in selected_servers],
                history_block=history_block,
            )

            async with httpx.AsyncClient(timeout=120.0) as client:
                data = await llm_gateway.generate_async(client, model=model, prompt=prompt)

                if not data.get("error"):
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
                    logger.error(f"LLM error: {data.get('error')}")
                    if remote_llm_enabled():
                        error_response = f"AI servisi yanıt veremedi.\n\n**Hata:** {data.get('error')}"
                    else:
                        error_response = (
                            "AI servisi yanıt veremedi (Ollama hatası).\n\n"
                            "**Kontrol edin:**\n"
                            "• Ollama çalışıyor mu? `curl %s/api/tags`\n"
                            "• Model yüklü mü? `ollama list` ve `ollama run %s`\n"
                            "• Sunucuda bellek yeterli mi?\n\n"
                            "**Hata:** %s"
                        ) % (
                            settings.OLLAMA_URL.rstrip("/"),
                            (request.model or get_active_model(db)).split(":")[0],
                            data.get("error"),
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
    # Güvenlik
    "selinux":       ["SELinux Durumu", "SELinux status", "getenforce", "Enforcing", "Permissive", "Disabled"],
    "sestatus":      ["SELinux Durumu", "SELinux status"],
    "firewall":      ["Firewall", "firewalld", "iptables", "nft"],
    "iptables":      ["Firewall", "iptables"],
    # Kernel/OS
    "uname":         ["Kernel", "kernel_full", "kernel_version", "uname"],
    "kernel":        ["Kernel"],
    "hostname":      ["OS", "hostname", "Hostname", "Static hostname"],
    "os":            ["OS", "PRETTY_NAME", "Oracle", "Red Hat", "Ubuntu", "CentOS"],
    "revision":      ["OS", "PRETTY_NAME", "VERSION"],
    # Performans
    "cpu":           ["CPU", "load average"],
    "disk":          ["Disk", "df -h", "Inode"],
    "memory":        ["Bellek", "Memory", "free -h"],
    "free":          ["Bellek", "RAM", "Mem:", "Swap:"],
    "df":            ["Disk", "Filesystem", "df -h"],
    "uptime":        ["Uptime", "load average", "Son Önyükleme"],
    # Ağ topoloji (SSH'dan gelir)
    "gateway":       ["Varsayılan Ağ Geçidi", "default via", "default", "0.0.0.0", "UG"],
    "default gw":    ["Varsayılan Ağ Geçidi", "default via", "default", "0.0.0.0", "UG"],
    "gw":            ["Varsayılan Ağ Geçidi", "default via", "default", "0.0.0.0", "UG"],
    "default route": ["Varsayılan Ağ Geçidi", "default via", "default"],
    "route":         ["Yönlendirme Tablosu", "Varsayılan Ağ Geçidi", "default via"],
    "resolv":        ["/etc/resolv.conf", "nameserver", "search", "DNS"],
    "resolv.conf":   ["/etc/resolv.conf", "nameserver", "search"],
    "nameserver":    ["/etc/resolv.conf", "nameserver", "DNS"],
    "dns":           ["/etc/resolv.conf", "nameserver", "search", "DNS"],
    "ip addr":       ["Ağ Arayüzleri", "inet "],
    "network":       ["Ağ Arayüzleri", "MAC Adresleri", "Varsayılan Ağ Geçidi", "ifconfig"],
    "mac":           ["MAC Adresleri", "link/ether", "ether "],
    "mac adresi":    ["MAC Adresleri", "link/ether", "ether "],
    "mac address":   ["MAC Adresleri", "link/ether", "ether "],
    "ifconfig":      ["ifconfig", "MAC Adresleri", "Ağ Arayüzleri", "link/ether"],
    "ethernet":      ["MAC Adresleri", "link/ether", "ether "],
    "arp":           ["ARP Tablosu", "MAC Adresleri", "link/ether"],
    "port":          ["Dinlenen Portlar", "Açık Portlar", "LISTEN"],
    # Servis/süreç
    "log":           ["Hata Logları", "Son Hatalar", "Auth Logları"],
    "servis":        ["Çalışan Servisler", "Hatalı Servisler"],
    "service":       ["Çalışan Servisler", "Hatalı Servisler"],
    "docker":        ["Docker (Çalışan)", "Docker (Tümü)", "Docker İstatistikleri"],
    "container":     ["Docker (Çalışan)", "Podman (Çalışan)", "Konteyner Servisleri"],
    "konteyner":     ["Docker (Çalışan)", "Podman (Çalışan)"],
    "ntp":           ["NTP Durumu", "NTP Kaynakları", "Zaman Senkronizasyonu", "Reference ID", "Stratum"],
    "chrony":        ["NTP Durumu", "Reference ID", "Stratum"],
    "sertifika":     ["Sertifika Detayları", "Sertifika Dosyaları", "notAfter", "subject"],
    "ssl":           ["Sertifika Detayları", "OpenSSL Versiyonu"],
    "cron":          ["Kullanıcı Cron", "/etc/crontab", "Systemd Timer"],
    "java":          ["Java", "java_version"],
    "python":        ["Python", "python_version"],
    "donanım":       ["Donanım (Sistem)", "Sunucu Modeli", "PCI Aygıtlar"],
    "hardware":      ["Donanım (Sistem)", "Sunucu Modeli", "PCI Aygıtlar"],
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

    # Gateway/IP gibi tek satır veriler için önceden tablo oluştur
    # Model direkt bunu yanıtında kullanacak, yorumlamayacak
    ml_lower = message.lower()
    is_table_query = any(k in ml_lower for k in ["gateway", "gw", "resolv", "nameserver", "dns server", "ip adresi", "mac adresi"])
    
    if is_table_query:
        # Her sunucu için tek satır değer çıkart ve tablo yap
        table_rows = []
        for ctx in ssh_contexts:
            m = _re.match(r"=== (.+?) \((.+?)\) ===", ctx)
            if not m:
                continue
            srv_name, srv_ip = m.group(1), m.group(2)
            # İlgili satırları topla
            relevant_values = []
            for line in ctx.split("\n"):
                for pat in matched_patterns:
                    if pat.lower() in line.lower():
                        # Gerçek değer satırı: label satırı değil, veri satırı al
                        stripped = line.strip()
                        if stripped and ":" not in stripped[:30] and stripped not in relevant_values:
                            relevant_values.append(stripped)
                        elif stripped.endswith(":") is False and stripped:
                            if stripped not in relevant_values and len(stripped) > 5:
                                relevant_values.append(stripped)
            value = relevant_values[0] if relevant_values else "SSH verisi yok"
            table_rows.append(f"| {srv_name} | {srv_ip} | {value} |")
        
        if table_rows:
            header = "| Sunucu | IP | Değer |\n|--------|-------|-------|"
            table = header + "\n" + "\n".join(table_rows)
            return (
                "SSH GERCEK VERİ TABLOSU (asagidaki degerleri AYNEN kullan, hic degistirme):\n"
                + table + "\n\n"
            )

    return (
        "ODAKLI OZET (SSH'dan gelen GERCEK veriler -- kesinlikle bunlari kullan, tahmin etme):\n"
        + "\n".join(rows)
        + "\n"
        + "UYARI: Yukardaki degerler gercek SSH ciktisidir. Farkli deger uretme, aynen goster.\n"
    )


def _build_prompt(
    message,
    context_str,
    ssh_collected,
    ssh_server_count,
    prometheus_available,
    selected_server_names,
    history_block="",
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
        "Sen 15+ yillik deneyime sahip kıdemli bir Linux Sistem Yoneticisi",
        "ve Sanallaştırma Uzmanisın (Senior Linux SysAdmin & Virtualization Engineer).",
        "Kullanıcı birden fazla sunucu adı verip 'karşılaştır' / 'compare' derse:",
        "Linux/Windows için OS config (sürüm, kernel, güvenlik) ve kaynakları;",
        "VM için sanal makine özelliklerini; ESX için donanım (vendor/model/CPU/RAM/NIC)",
        "farklarını yan yana özetle; hangisinin production'a daha uygun olduğunu kısaca öner.",
        "",
        "UZMANLIK ALANLARIN:",
        "--- Linux Sistem Yonetimi ---",
        "- Red Hat / CentOS / AlmaLinux / Rocky, Debian / Ubuntu, SUSE uzerinde derin bilgi",
        "- systemd, journalctl, cgroups, namespaces, kernel parametreleri (sysctl)",
        "- Performans analizi: top, htop, atop, sar, vmstat, iostat, iotop, perf, strace, lsof",
        "- Ag yonetimi: ss, netstat, tcpdump, iperf3, ip route, firewalld, iptables, nftables",
        "- Depolama: LVM, RAID, ZFS, ext4/xfs tuning, fstab, mount, smartctl, fdisk/parted",
        "- Guvenlik: SELinux, AppArmor, sudo, PAM, auditd, fail2ban, OpenSSH hardening",
        "- Paket yonetimi: rpm/dnf/yum, dpkg/apt, zypper, dependency hell cozme",
        "- Cron, at, systemd timer'lar, log rotation (logrotate), rsyslog/journald",
        "- Kernel tuning: vm.swappiness, net.core, fs.file-max, dirty_ratio gibi parametreler",
        "",
        "--- Sanallaştırma & Konteyner ---",
        "- VMware vSphere / ESXi / vCenter: VM yonetimi, vMotion, DRS, HA, datastore, snapshot",
        "- oVirt / RHEV / KVM: VM olusturma, live migration, storage domain, network profili",
        "- Docker & Docker Compose: image yonetimi, network, volume, log driver, resource limit",
        "- Temel Kubernetes: pod, deployment, service, pv/pvc sorunlari",
        "- QEMU/libvirt: virsh komutlari, xml config, snapshot, clone",
        "",
        "--- Monitoring & Tanı ---",
        "- Prometheus, Node Exporter, Alertmanager, Grafana",
        "- Log analizi: grep/awk/sed ile pattern tespiti, anomali yorumlama",
        "- Darboğaz tespiti: CPU steal, iowait, memory pressure, network saturation",
        "",
        "SISTEM YETENEKLERI:",
        "- Yonetilen sunuculara SSH ile baglanip gercek komutlar calistirabiliyor",
        "  (sestatus, getenforce, df, ps, journalctl, vmstat, iostat, sar, ss, netstat vb.)",
        "- Prometheus/Node Exporter uzerinden CPU, RAM, disk, network metrikleri okunabiliyor",
        "- Gecmis konusma, runbook'lar ve incident kayitlari kullanilabiliyor",
        "",
        "ONEMLI: Asla 'SSH yapamam' veya 'dogrudan baglanamam' deme.",
        "Sistem SSH yapabiliyor. Eger veri gelmemisse toplanmamis demektir, toplanamaz degil.",
        "",
        "ONEMLI: Kullaniciya ASLA 'bunu su komutla siz kontrol edebilirsiniz' / 'asagidaki",
        "yontemleri kullanarak bulabilirsiniz' seklinde bir KILAVUZ/MANUEL TALIMAT LISTESI verme.",
        "Sistem SSH ile komutu ZATEN calistirabiliyor — BAGLAM'da ilgili veri yoksa bu SENIN",
        "o komutu calistirmadigin/calistiramadigin anlamina gelir, kullanicinin gitmesi degil.",
        "Bu durumda sadece 'Bu bilgi mevcut taramada toplanmadi.' de; kullaniciyi kendi",
        "basina komut calistirmaya yonlendirme.",
    ])

    rules = NL.join([
        "YANIT KURALLARI:",
        "0. ONCEKI KONUSMA bolumu varsa, bu bir SOHBETIN PARCASIDIR — takip sorularini",
        "   ('peki cpu?', 'o sunucuda ise nasil?', 'ayni sunucu icin...' gibi) ONCEKI KONUSMA'ya",
        "   bakarak hangi sunucu/konudan bahsedildigini cikararak yanitla. Ancak GUNCEL veri",
        "   icin her zaman asagidaki BAGLAM bolumunu esas al — ONCEKI KONUSMA'daki eski",
        "   degerleri/verileri GUNCEL degermis gibi tekrar etme, sadece baglam/niyet icin kullan.",
        "1. BAGLAM bolumundeki GERCEK veriyi once kullan — kendi bilginle asla tahmin yapma",
        "1b. ONCEDEN OGRENILMIS BILGILER bolumunu SADECE canli SSH verisinde o bilgi YOKSA kullan",
        "    ve kullanirken acikca belirt: '(onceden ogrenilmis, [X] once dogrulandi)'. Canli veri",
        "    varsa ve celisiyorsa HER ZAMAN canli veriyi esas al.",
        "1c. 'Bu sunucuda hangi uygulamalar/veritabanlari/servisler calisiyor' gibi sorularda TESPIT",
        "    EDILEN UYGULAMALAR bolumunu kullan (otomatik periyodik tarama sonucu) — bu bolum bos ise",
        "    'Bu sunucu icin uygulama taramasi henuz yapilmadi veya hicbir bilinen servis bulunamadi.' de.",
        "2. Baglam bos veya yetersizse: 'Bu sunucu icin SSH verisi alinamadi (baglanamadi veya zaman asimi).' de.",
        "   ASLA 'tekrar deneniyor' veya 'bekleniyor' deme — bu sistem otomatik retry yapmaz.",
        "3. ASLA 'SSH yapamam', 'dogrudan baglanamam', 'veri tabanindan bakiyorum' yazma.",
        "   Dogru cumle: '[sunucu_adi] icin SSH baglantisi basarisiz oldu veya veri alinamadi.'",
        "4. Tablo istenirse Markdown tablo kullan (| kolon | kolon |)",
        "5. Turkce yanitla — kisaltmadan, net ve aciklayici yaz",
        "6. Veri varsa asla 'bilmiyorum' ya da 'emin degilim' deme — veriyi yorumla",
        "7. resolv.conf, /etc/ dosya iceriklerini gorudugunde, oldugu gibi goster (trim etme)",
        "",
        "UZMAN YANIT TARZI:",
        "8. Her soruyu bir kıdemli admin gibi ele al:",
        "   - Once olasi KOKEN NEDENLER (root cause) belirt",
        "   - Somut TANI KOMUTU oner (calistirilabilir, parametreli)",
        "   - COZUM ADIMLARI numaralı liste halinde ver",
        "   - Varsa UYARI / RISK bilgisi ekle (ornegin: 'production'da dikkat, once test et')",
        "9. Performans sorularinda degerler anlamsiz kalmayacak sekilde yorum yap:",
        "   - CPU iowait > %20 → disk darbogazı sinyali gibi",
        "   - Load average > CPU cekirdek sayisi → sistem bunalmis gibi",
        "10. Komut onerirken ciktiyi nasil yorumlayacagini da goster",
        "11. Kritik islemler icin (rm, mkfs, reboot, kill) MUTLAKA uyari ver ve once yedek/snapshot al de",
        "12. VMware/oVirt sorularinda vSphere/oVirt terimleri kullan (datastore, portgroup, vNIC vb.)",
    ])

    prompt_parts = [identity]
    if collection_summary:
        prompt_parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    prompt_parts.append(rules)
    prompt_parts.append("BAGLAM:\n" + context_str)
    if history_block:
        prompt_parts.append("ONCEKI KONUSMA (bu oturumdaki son mesajlar, sadece baglam/niyet icin):\n" + history_block)
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
                from app.services.chat_history import title_from_message
                title = title_from_message(message)
                session = ChatSession(title=title, server_ids=request.server_ids or [], category="linux")
                db.add(session)
                db.commit()
                db.refresh(session)
                session_id = session.id
            else:
                session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if not session:
                    yield _sse({"error": "Session bulunamadı"})
                    return
                from app.services.chat_history import maybe_set_session_title
                if maybe_set_session_title(session, message):
                    db.commit()

            yield _sse({"session_id": session_id, "start": True})

            # Konusma gecmisi — bu takip sorusu mu (session'da onceki mesaj var mi)?
            from app.services.chat_history import fetch_recent_history, format_history_block, has_prior_messages
            _is_followup = has_prior_messages(db, session_id)
            history_block = format_history_block(fetch_recent_history(db, session_id, limit=8)) if _is_followup else ""

            # ── 1. Cache kontrolü ─────────────────────────────────────────
            # Takip sorularinda cache'e bakilmiyor: onceki turlere bagimli bir soru
            # ("peki cpu?" gibi), session'i bilmeyen izole bir cache anahtariyla
            # eslesip baglamsiz/eski bir cevap donebilir (bkz. chat_cache_service.py
            # _context_key — session_id icermiyor).
            server_ids = request.server_ids or []
            cached = None if _is_followup else get_cached_answer(db, message, server_ids)
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

            # ── 2a. Direkt komut çalıştırma (AI bypass) ─────────────────
            # Kullanıcı belirli bir Linux komutu istiyorsa → SSH'dan direkt çalıştır
            _LONG_CMDS = ['vmstat', 'iostat', 'sar', 'top -b']

            def _extract_commands_from_msg(msg):
                """Mesajdan Linux komutlarini token bazli cikar."""
                _CMD_SPECS = [
                    ('vmstat', 4), ('iostat', 4), ('sar', 4),
                    ('netstat', 3), ('ss', 3), ('ps', 3),
                    ('df', 2), ('du', 2), ('lsblk', 2), ('lscpu', 1),
                    ('free', 2), ('lsmod', 1), ('uptime', 1),
                    ('top', 3), ('ifconfig', 2), ('arp', 2),
                    ('route', 2), ('ip', 3),
                ]
                tokens = msg.split()
                found = []
                i = 0
                while i < len(tokens):
                    tok = tokens[i].lower().rstrip(".,?!")
                    matched = False
                    for cmd_name, max_args in _CMD_SPECS:
                        if tok == cmd_name:
                            parts = [tokens[i]]
                            j = i + 1
                            count = 0
                            while j < len(tokens) and count < max_args:
                                arg = tokens[j].rstrip(".,?!")
                                if arg.startswith("-") or arg.lstrip("-").isdigit():
                                    parts.append(arg)
                                    count += 1
                                    j += 1
                                else:
                                    break
                            cmd = " ".join(parts)
                            if cmd not in found:
                                found.append(cmd)
                            i = j
                            matched = True
                            break
                    if not matched:
                        i += 1
                return found

            direct_cmds = _extract_commands_from_msg(message)
            logger.info(f"[DIRECT] direct_cmds={direct_cmds!r} server_id={request.server_id!r}")


            if direct_cmds:
                logger.info(f"Direkt komut(lar) algılandı: {direct_cmds!r}")
                # Analiz isteniyor mu?
                _ANALYZE_KEYWORDS = ['analiz', 'analyze', 'yorumla', 'değerlendir', 'incele',
                                     'açıkla', 'neden', 'sorun', 'problem', 'yavaş', 'yüksek',
                                     'kontrol et', 'ne anlama', 'ne göster', 'raporla', 'rapor']
                _needs_analysis = any(k in message.lower() for k in _ANALYZE_KEYWORDS)

                # Sunucuları belirle: önce UI'dan seçilen, sonra mesaj içinden, son çare hepsi
                _all_ai_srv = _linux_ai_ready_servers(db)
                if request.server_ids:
                    _target_servers = [s for s in _all_ai_srv if s.id in request.server_ids]
                elif request.server_id:
                    _target_servers = [s for s in _all_ai_srv if s.id == request.server_id]
                else:
                    ml_dc2 = message.lower()
                    _target_servers = [s for s in _all_ai_srv if (s.name and s.name.lower() in ml_dc2) or (s.ip_address and s.ip_address in message)]
                    if not _target_servers:
                        _target_servers = _all_ai_srv

                from app.services.ssh_manager import SSHManager
                from app.core.encryption import decrypt_secret as _dec_secret
                _cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                if not _cred:
                    _cred = db.query(GlobalCredential).first()

                # Her komut için timeout belirle
                def _get_timeout(cmd):
                    return 120 if any(lc in cmd for lc in _LONG_CMDS) else 30

                async def _run_all_cmds():
                    import asyncio as _a
                    loop = _a.get_event_loop()
                    # Her sunucu için tüm komutları sırayla çalıştır (SSH bağlantısını yeniden kullan)
                    async def _ssh_server(srv):
                        def _do():
                            results = {}
                            try:
                                # Per-server connection_config varsa onu, yoksa global credential'ı
                                # kullan (diğer tüm SSH noktalarıyla aynı öncelik). Şifre/anahtar DB'de
                                # Fernet ile şifreli tutulduğu için decrypt_secret() ile açılmadan
                                # paramiko'ya verilirse auth sessizce başarısız olur.
                                cfg = srv.connection_config or {}
                                username = cfg.get("username") or (_cred.username if _cred else None)
                                raw_pw = cfg.get("password") or (_cred.password if _cred else None)
                                port = cfg.get("port") or (_cred.port if _cred else 22) or 22
                                if not username:
                                    for cmd in direct_cmds:
                                        results[cmd] = (None, "SSH credential yok")
                                    return srv.name, results
                                ssh = SSHManager(host=srv.ip_address, username=username,
                                                 password=_dec_secret(raw_pw) if raw_pw else None, port=port)
                                if not ssh.connect():
                                    for cmd in direct_cmds:
                                        results[cmd] = (None, "SSH bağlantısı kurulamadı")
                                    return srv.name, results
                                for cmd in direct_cmds:
                                    t = _get_timeout(cmd)
                                    ok, out, err = ssh.execute_command(f"timeout {t} {cmd} 2>&1")
                                    if ok and out and out.strip():
                                        results[cmd] = (out.strip(), "")
                                    else:
                                        # Komut bulunamadı mı yoksa gerçek hata mı?
                                        combined = (out or "") + (err or "")
                                        if "not found" in combined.lower() or "command not found" in combined.lower() or (not ok and not out and not err):
                                            results[cmd] = (None, f"Komut yüklü değil: {cmd.split()[0]}")
                                        elif out and out.strip():
                                            results[cmd] = (out.strip(), "")
                                        else:
                                            results[cmd] = (None, err.strip() if err else "Komut çalışmadı")
                                ssh.close()
                            except Exception as ex:
                                for cmd in direct_cmds:
                                    results[cmd] = (None, str(ex))
                            return srv.name, results
                        return await loop.run_in_executor(None, _do)

                    tasks = [_a.ensure_future(_ssh_server(s)) for s in _target_servers]
                    return await _a.gather(*tasks)

                srv_count = len(_target_servers)
                srv_names_str = ", ".join(s.name for s in _target_servers)
                cmds_str = " + ".join(f"`{c}`" for c in direct_cmds)
                yield _sse({"token": f"{cmds_str} komutu {srv_count} sunucuda çalıştırılıyor ({srv_names_str})...\n\n"})
                _all_results = await _run_all_cmds()  # [(srv_name, {cmd: (out, err)}), ...]

                # Ham çıktıyı formatla
                raw_output_lines = [f"## Komut Çıktıları ({', '.join(direct_cmds)})\n"]
                cmd_context_parts = []
                for srv_name, cmd_results in _all_results:
                    raw_output_lines.append(f"### {srv_name}\n")
                    srv_ctx = [f"=== {srv_name} ==="]
                    for cmd, (out, err) in cmd_results.items():
                        if out:
                            raw_output_lines.append(f"**`{cmd}`**\n```\n{out}\n```\n")
                            srv_ctx.append(f"--- {cmd} ---\n{out}")
                        else:
                            raw_output_lines.append(f"**`{cmd}`**: *SSH hatası: {err or 'bilinmiyor'}*\n")
                            srv_ctx.append(f"--- {cmd} ---\nHATA: {err or 'bilinmiyor'}")
                    cmd_context_parts.append("\n".join(srv_ctx))
                raw_output = "\n".join(raw_output_lines)

                if not _needs_analysis:
                    for i in range(0, len(raw_output), 8):
                        yield _sse({"token": raw_output[i:i+8]})
                    full_resp = raw_output
                else:
                    for i in range(0, len(raw_output), 8):
                        yield _sse({"token": raw_output[i:i+8]})
                    yield _sse({"token": "\n---\n## Analiz\n\n"})

                    cmd_context = "\n\n".join(cmd_context_parts)
                    cmds_label = ", ".join(f"`{c}`" for c in direct_cmds)
                    analysis_prompt = (
                        "Sen bir Linux altyapı uzmanısın. Aşağıda sunuculardan alınan "
                        f"{cmds_label} komut çıktıları var.\n\n"
                        "KRİTİK KURAL: Sadece aşağıdaki gerçek verileri kullan. "
                        "'Komut yüklü değil' veya 'SSH hatası' yazan komutlar için HİÇBİR VERİ UYDURMA. "
                        "O komutlar için sadece 'Yüklü değil' veya 'Hata' yaz.\n\n"
                        "KOMUT ÇIKTILARI:\n"
                        + cmd_context
                        + "\n\nKULLANICI İSTEĞİ: " + message
                        + "\n\nLütfen sadece mevcut gerçek verileri analiz et: performans sorunlarını, "
                        "yüksek değerleri, anormallikleri ve önerileri Türkçe olarak açıkla. "
                        "Sunucular arasında karşılaştırma yap. Markdown kullan. "
                        "Gerçek veri olmayan komutlar için tablo uydurma."
                        + "\n\nYANIT (Türkçe, Markdown):"
                    )

                    # LLM streaming (yerel Ollama veya uzak gateway — llm_gateway üzerinden)
                    _model = request.model or get_active_model(db)
                    analysis_text = ""
                    try:
                        async with httpx.AsyncClient(timeout=120) as _hc:
                            async for _d in llm_gateway.stream_generate(
                                _hc, model=_model, prompt=analysis_prompt,
                                options={"temperature": 0.3, "num_predict": 1500},
                            ):
                                tok = _d.get("response", "")
                                if tok:
                                    analysis_text += tok
                                    yield _sse({"token": tok})
                                if _d.get("done"):
                                    break
                    except Exception as ae:
                        err_msg = f"\n*Analiz hatası: {ae}*"
                        analysis_text = err_msg
                        yield _sse({"token": err_msg})
                    full_resp = raw_output + "\n---\n## Analiz\n\n" + analysis_text

                # Oturuma kaydet
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                db.add(ChatMessage(session_id=session_id, role="assistant", content=full_resp))
                s_obj = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s_obj:
                    from datetime import datetime, timezone as _tz
                    s_obj.updated_at = datetime.now(_tz.utc)
                db.commit()
                yield _sse({"done": True, "session_id": session_id})
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
            elif request.hypervisor_ids:
                selected_servers = db.query(Server).filter(
                    Server.hypervisor_id.in_(request.hypervisor_ids), Server.ai_ready == True
                ).all()
            elif request.hypervisor_id:
                selected_servers = db.query(Server).filter(
                    Server.hypervisor_id == request.hypervisor_id, Server.ai_ready == True
                ).all()

            # ── Mesajdan sunucu adı/IP otomatik algılama ─────────────────
            # Kullanıcı "ahmet-test2 sunucusundan..." veya "192.168.1.46'dan..."
            # dediğinde o sunucuyu otomatik seç
            if not selected_servers:
                all_ai_servers = _linux_ai_ready_servers(db)
                msg_lower_srv = message.lower()
                detected_servers = []
                for s in all_ai_servers:
                    name_match = s.name and s.name.lower() in msg_lower_srv
                    ip_match = s.ip_address and s.ip_address in message
                    if name_match or ip_match:
                        detected_servers.append(s)
                if detected_servers:
                    selected_servers = detected_servers
                    logger.info(f"Mesajdan sunucu algılandı: {[s.name for s in detected_servers]}")
                else:
                    selected_servers = all_ai_servers

            server_context = ""
            if selected_servers:
                lines = [
                    f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, "
                    f"Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB"
                    for s in selected_servers
                ]
                server_context = "Seçili sunucular:\n" + "\n".join(lines)

            # ── 2c. Grafik/zaman serisi rapor isteği (node_exporter → TimescaleDB) ──
            # "son 2 saatlik disk ve network utilizasyonu ver" gibi hem bir süre HEM
            # bir metrik türü içeren mesajları LLM'e gitmeden, deterministik olarak
            # metric_data'dan çekip metin özeti + grafik verisi (meta.charts) olarak
            # döndürür. Süre belirtilmezse (örn. "cpu kullanımını göster") normal
            # metin/Prometheus akışına devam eder.
            from app.services.metric_history import detect_chart_request, build_chart_response
            chart_req = detect_chart_request(message)
            if chart_req and selected_servers:
                target_server = selected_servers[0]
                chart_result = build_chart_response(db, target_server, chart_req["hours"], chart_req["groups"])
                if chart_result:
                    db.add(ChatMessage(session_id=session_id, role="user", content=message))
                    db.commit()
                    answer_text = chart_result["summary_text"]
                    if len(selected_servers) > 1:
                        answer_text += f"\n\n_(Not: Birden fazla sunucu seçili, grafik sadece **{target_server.name}** için oluşturuldu.)_"
                    for i in range(0, len(answer_text), 8):
                        yield _sse({"token": answer_text[i:i+8]})
                    db.add(ChatMessage(
                        session_id=session_id, role="assistant", content=answer_text,
                        meta={"charts": chart_result["charts"]},
                    ))
                    s_chart = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if s_chart:
                        from datetime import datetime as _dt, timezone as _tz2
                        s_chart.updated_at = _dt.now(_tz2.utc)
                    db.commit()
                    yield _sse({"done": True, "session_id": session_id})
                    return

            # ── 3. Keyword analizi ────────────────────────────────────────
            PROMETHEUS_KEYWORDS = [
                'cpu', 'ram', 'memory', 'bellek', 'disk', 'bandwidth',
                'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
                'kullanım', 'usage', 'durum', 'status', 'genel', 'overview', 'özet',
                'trafik', 'traffic', 'throughput',
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
                # Ağ komutları
                'netstat', 'ss -', 'ip route', 'ip addr', 'ifconfig', 'arp',
                'route', 'traceroute', 'ping', 'nmap', 'tcpdump', 'dig', 'nslookup',
                # Genel komut isteği
                'çıktı', 'cikti', 'output', 'komut', 'command', 'göster', 'listele',
                'getir', 'ver', 'çalıştır', 'çalıştırır', 'alırmısın', 'alır mısın',
                'alabilirmisin', 'alabilir misin', 'görebilirmiyim', 'göster',
                # Disk/sistem komutları
                'lsblk', 'fdisk', 'blkid', 'mount', 'df', 'du',
                'lspci', 'lshw', 'dmidecode', 'lsusb',
                # Kullanıcı/güvenlik
                'last', 'lastb', 'who', 'w ', 'id ', 'groups',
                # Servis/uygulama
                'docker ps', 'podman ps', 'kubectl',
                'crontab', 'at -l', 'atq',
                'cat ', 'grep ', 'tail ', 'head ', 'less ', 'more ',
                'find ', 'locate ', 'which ', 'whereis ',
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
                'dns', 'nameserver', 'resolv', 'resolve.conf', 'resolv.conf',
                'nslookup', 'dig', 'isim çözümleme', 'name resolution',
                'gateway', 'ağ geçidi', 'default route', 'ip route',
            ]
            DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
            ml = message.lower()
            needs_prometheus = any(k in ml for k in PROMETHEUS_KEYWORDS) and not request.skip_server_context
            # SSH: sunucu/sistem sorusu içeriyorsa her zaman çalıştır (keyword listesine bağlı değil)
            SERVER_TRIGGER = PROMETHEUS_KEYWORDS + SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS
            # Elle yazılmış SERVER_TRIGGER listesi dışında kalan ama linux_info_collector'ın
            # kapsamlı KEYWORD_TO_GROUPS/EXTRA_GROUPS_KEYWORDS'ünde tanımlı bir konu varsa
            # (örn. "vm.swappiness", "sysctl", "dirty_ratio") yine SSH context topla —
            # aksi halde needs_ssh hep False kalır, _collect_ssh() hiç çalışmaz, context boş
            # gider ve LLM context'siz "SSH bağlantısı sağlanamadı" diye cevap verir (SSH
            # aslında hiç denenmemiştir). Bkz. has_recognized_topic() docstring'i.
            from app.services.linux_info_collector import has_recognized_topic as _has_topic
            needs_ssh = (
                any(k in ml for k in SERVER_TRIGGER) or _has_topic(message)
            ) and not request.skip_server_context
            is_deep         = any(k in ml for k in DEEP_PERF_KEYWORDS)
            # Alt sınır 20s -> 30s (unified_chat.py'deki aynı düzeltmeyle uyumlu): "genel mod"a
            # düşen sorgular (STANDARD_GROUPS'un tamamı, ~9 grup/60+ komut) tek sunucuda bile
            # ölçümlerde 20-27s sürebiliyor — eski 20s taban bunu sığdırmadan zaman aşımına
            # uğrayıp "SSH verisi alınamadı" yanıtına yol açıyordu (bkz. "selinux durumu"
            # sorgusunun "durum" kelimesi yüzünden genel moda düşmesi — artık ayrıca
            # linux_info_collector.detect_needed_groups bu durumu da hafifletiyor).
            base_timeout    = 40.0 if is_deep else 30.0
            context_timeout = min(60.0, max(base_timeout, 12.0 + 1.5 * len(selected_servers)))

            # Varsayılan (is_default=True) işaretli bir credential yoksa da ilk tanımlı global
            # credential'a düş (unified_chat.py ile aynı davranış) — tek bir global credential
            # tanımlıyken "varsayılan" işaretlenmemiş olması yaygın bir kurulum hatasıydı.
            global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
            if not global_cred:
                global_cred = db.query(GlobalCredential).first()

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
                        loop.run_in_executor(None, lambda s=srv: collect_server_info(s, groups, global_cred, message))
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
                                try:
                                    from app.services.fact_learning import extract_and_store_facts
                                    extract_and_store_facts(db, selected_servers[i], info, platform="linux")
                                except Exception:
                                    pass
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

            # NOT: wait_for(gather(...)) KULLANMIYORUZ — _collect_ssh() zaten kendi içinde
            # context_timeout ile sınırlı (bkz. yukarıdaki asyncio.wait). Dıştan ayrıca
            # wait_for(..., timeout=context_timeout+2.0) sarmak, sadece _collect_prometheus()
            # veya _collect_rag() biraz uzun sürdüğünde ZATEN TOPLANMIŞ ssh_ctx'i de (gather
            # tek bir birim olduğu için) tamamen atıp "SSH verisi alınamadı"ya yol açıyordu —
            # unified_chat.py'deki aynı düzeltmeyle uyumlu: her kaynağın sonucu kendi tamamlanma
            # durumuna göre bağımsız korunur.
            prom_task = _asyncio.ensure_future(_collect_prometheus())
            ssh_task = _asyncio.ensure_future(_collect_ssh())
            rag_task = _asyncio.ensure_future(_collect_rag())
            done, pending = await _asyncio.wait(
                [prom_task, ssh_task, rag_task], timeout=context_timeout + 2.0
            )
            for t in pending:
                t.cancel()

            def _safe_result(task, default):
                if task in done:
                    try:
                        return task.result()
                    except Exception:
                        return default
                return default

            prom_ctx = _safe_result(prom_task, "")
            ssh_ctx = _safe_result(ssh_task, "")
            rag_ctx = _safe_result(rag_task, {})
            prom_ctx = prom_ctx if isinstance(prom_ctx, str) else ""
            ssh_ctx = ssh_ctx if isinstance(ssh_ctx, str) else ""
            rag_ctx = rag_ctx if isinstance(rag_ctx, dict) else {}

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

            if selected_servers:
                try:
                    from app.services.fact_learning import get_learned_facts_block
                    _facts_blocks = []
                    for _s in selected_servers[:5]:
                        _fb = get_learned_facts_block(db, _s)
                        if _fb:
                            _facts_blocks.append(f"[{_s.name}]\n{_fb}")
                    if _facts_blocks:
                        context_parts.append(
                            "ONCEDEN OGRENILMIS BILGILER (yapisal, gecmis SSH taramalarindan — "
                            "canli BAGLAM ile celisirse canli veriyi esas al, kullanirken 'onceden "
                            "ogrenilmis (X once dogrulandi)' diye belirt):\n" + "\n\n".join(_facts_blocks)
                        )
                except Exception:
                    pass

                try:
                    from app.services.app_discovery import get_discovered_apps_block
                    _apps_blocks = []
                    for _s in selected_servers[:5]:
                        _ab = get_discovered_apps_block(db, _s)
                        if _ab:
                            _apps_blocks.append(f"[{_s.name}]\n{_ab}")
                    if _apps_blocks:
                        context_parts.append(
                            "TESPIT EDILEN UYGULAMALAR (otomatik tarama ile bulunan calisan servisler — "
                            "Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.; periyodik tarandigi icin en "
                            "guncel BAGLAM'daki canli veriyle celisirse canli veriyi esas al):\n"
                            + "\n\n".join(_apps_blocks)
                        )
                except Exception:
                    pass

            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER OLAYLAR:\n" + rag_ctx["incidents"].strip())
            if rag_ctx.get("metrics"):
                context_parts.append("METRIK ACIKLAMALARI:\n" + rag_ctx["metrics"].strip())

            # Hypervisor bağlamı (seçim varsa)
            selected_hypervisors = []
            if request.hypervisor_ids and len(request.hypervisor_ids) > 0:
                selected_hypervisors = db.query(Hypervisor).filter(Hypervisor.id.in_(request.hypervisor_ids)).all()
            elif request.hypervisor_id:
                hv = db.query(Hypervisor).filter(Hypervisor.id == request.hypervisor_id).first()
                if hv:
                    selected_hypervisors = [hv]
            if selected_hypervisors:
                hv_lines = []
                for h in selected_hypervisors:
                    hv_lines.append(f"- {h.name} ({h.hypervisor_type.value if h.hypervisor_type else '-'}): host={h.hostname or '-'}, ip={h.ip_address or '-'}, port={h.port or '-'}")
                context_parts.append("SEÇİLİ HYPERVISORLAR:\n" + "\n".join(hv_lines))

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                ssh_collected=bool(ssh_ctx),
                ssh_server_count=len([s for s in selected_servers]) if ssh_ctx else 0,
                prometheus_available=bool(prom_ctx),
                selected_server_names=[s.name for s in selected_servers],
                history_block=history_block,
            )

            # Kullanıcı mesajını kaydet
            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.commit()

            # ── 6. AI Streaming (Ollama / Groq / OpenAI / Anthropic / OpenRouter) ──────
            model = request.model or get_active_model(db)
            provider = _detect_provider(model)
            full_response = ""

            async with httpx.AsyncClient(timeout=180.0) as client:
                if provider == "groq" and settings.GROQ_API_KEY:
                    async for token in _stream_external_openai(
                        client, settings.GROQ_API_URL, settings.GROQ_API_KEY,
                        model, prompt
                    ):
                        full_response += token
                        yield _sse({"token": token})

                elif provider == "openai" and settings.OPENAI_API_KEY:
                    async for token in _stream_external_openai(
                        client, settings.OPENAI_API_URL, settings.OPENAI_API_KEY,
                        model, prompt
                    ):
                        full_response += token
                        yield _sse({"token": token})

                elif provider == "openrouter" and settings.OPENROUTER_API_KEY:
                    async for token in _stream_external_openai(
                        client, settings.OPENROUTER_API_URL, settings.OPENROUTER_API_KEY,
                        model, prompt,
                        extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"}
                    ):
                        full_response += token
                        yield _sse({"token": token})

                else:
                    # Ollama (varsayılan) veya REMOTE_LLM_ENABLED ise uzak gateway
                    async for chunk in llm_gateway.stream_generate(client, model=model, prompt=prompt):
                        if chunk.get("error"):
                            yield _sse({"error": chunk["error"]})
                            return
                        token = chunk.get("response", "")
                        if token:
                            full_response += token
                            yield _sse({"token": token})
                        if chunk.get("done"):
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

            # SSH verisi içeren yanıtlar canlı veri, takip soruları da bağlama bağımlı —
            # ikisi de cache'e kaydedilmez (aksi halde sonraki izole bir soru bu bağlama
            # bağımlı cevabı yanlışlıkla kullanabilir).
            if full_response and not is_deep and not needs_ssh and not _is_followup:
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
