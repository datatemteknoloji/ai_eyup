"""
Chat API endpoints - veritabanı tabanlı (kalıcı, tüm worker'larda aynı veri)
"""
from fastapi import APIRouter, Depends, HTTPException, Body
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
from app.services.response_layers import wrap_layer

logger = logging.getLogger(__name__)


def _linux_ai_ready_servers(db: Session):
    """AI Ready sunucular — Windows sunucular hariç (Linux AI asistanı yalnızca Linux'ta çalışır)."""
    return [s for s in db.query(Server).filter(Server.ai_ready == True).all() if not is_windows_server(s)]


# DİKKAT: kernel_version / os_version / hostname zaten linux_info_collector'ın periyodik
# arka plan taramasıyla Server tablosuna yazılıyor (bkz. auto_onboarding.py, servers.py,
# Server modeli). Bu alanlar SORULDUĞUNDA — ve başka canlı/operasyonel bir konu YOKSA —
# filoya SSH atmaya gerek yok. Kullanıcı bulgusu: "sunucularımızın kernel versiyonları"
# sorusu tüm AI-Ready filoya paralel SSH atıp 20-90s bekletiyordu, oysa cevap veritabanında
# zaten kayıtlıydı. NOT: Bu liste MODÜL SEVİYESİNDE tutulur (chat_message VE chat_stream
# ikisi de kullanır) — daha önce her iki endpoint'te birbirinden bağımsız kopya listeler
# olduğu için düzeltme yalnızca birine uygulanmış, chat_stream (frontend'in gerçekte
# kullandığı endpoint) hâlâ eski/yavaş davranışta kalmıştı.
DB_STATIC_SYSINFO_KEYWORDS = [
    'os', 'işletim', 'operating system', 'kernel', 'çekirdek', 'cekirdek',
    'distro', 'distribution', 'revision', 'revizyon', 'sürüm', 'surum', 'release', 'versiyon',
    'rhel', 'centos', 'ubuntu', 'debian', 'oracle linux', 'oracle',
    'uname', 'kernel versiyonu', 'çekirdek versiyonu',
    'hostname', 'makine adi', 'makine adı',
]
# Kullanıcı açıkça canlı doğrulama isterse (DB'deki son taramadan beri değişmiş olabilir
# diye düşünüyorsa) DB kısayolu atlanır, normal SSH akışı çalışır.
LIVE_VERIFY_KEYWORDS = [
    'canlı', 'canli', 'şimdi doğrula', 'simdi dogrula', 'live check',
    'ssh ile', 'ssh at', 'gerçek zamanlı',
]


def _kw_hit(text: str, keyword: str) -> bool:
    # Kısa/genel kelimeler ('ver', 'os' gibi) naif substring ile "versiyon", "server"
    # içindeki gibi YANLIŞ eşleşme üretir (bkz. "kernel versiyonları" sorusunun 'ver'
    # kelimesine çarpıp db_only_answer'ı iptal ettiği bulgu) — 3 karakter ve altı
    # keyword'ler için kelime sınırı zorunlu tutulur.
    if len(keyword) <= 3:
        return bool(re.search(rf'(?<![a-zçğıöşü0-9]){re.escape(keyword)}(?![a-zçğıöşü0-9])', text))
    return keyword in text


def _kw_any(text: str, keywords) -> bool:
    return any(_kw_hit(text, k) for k in keywords)


def _classify_db_only_sysinfo(msg_lower: str, ssh_only_keywords, ssh_sysinfo_keywords):
    """Mesaj yalnızca DB'de zaten kayıtlı statik alan(lar)ı (kernel/OS sürümü, hostname)
    soruyorsa ve başka canlı/operasyonel bir konu ya da canlı doğrulama isteği yoksa
    True döner — bu durumda SSH'a hiç gidilmeden DB verisiyle cevap üretilir.
    """
    matched_db_static_topic = _kw_any(msg_lower, DB_STATIC_SYSINFO_KEYWORDS)
    wants_live_verify = _kw_any(msg_lower, LIVE_VERIFY_KEYWORDS)
    db_only_answer = matched_db_static_topic and not wants_live_verify and not (
        _kw_any(msg_lower, ssh_only_keywords) or _kw_any(msg_lower, ssh_sysinfo_keywords)
    )
    return db_only_answer, matched_db_static_topic

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
            "reachable": True,
            "models": [{"name": model, "size": None, "parameter_size": None, "family": "remote"}],
            "default": model,
            "remote": True,
            "provider": "remote",
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
                    "reachable": True,
                    "models": models,
                    "default": get_active_model(db),
                    "provider": "ollama",
                }
            else:
                return {
                    "success": False,
                    "reachable": False,
                    "models": [],
                    "default": get_active_model(db),
                    "error": "Ollama'ya bağlanılamadı",
                    "provider": "ollama",
                }
    except Exception as e:
        logger.error(f"Model listesi alınamadı: {e}")
        return {
            "success": False,
            "reachable": False,
            "models": [],
            "default": get_active_model(db),
            "error": str(e),
            "provider": "ollama",
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
    ephemeral: Optional[bool] = False  # Gizli mod: mesajlar DB'ye yazılmaz
    # linux | openshift | exadata — OpenShift sohbeti Linux SSH/tool ile karışmasın
    platform: Optional[str] = "linux"


_CHAT_CATEGORIES = frozenset({"linux", "openshift", "exadata"})


def _normalize_chat_platform(platform: Optional[str]) -> str:
    p = (platform or "linux").strip().lower()
    return p if p in _CHAT_CATEGORIES else "linux"


class SessionCreate(BaseModel):
    server_ids: Optional[List[int]] = None
    category: Optional[str] = "linux"


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
async def list_chat_sessions(category: str = "linux", db: Session = Depends(get_db)):
    """Platform AI chat session'larını listele (DB'den)."""
    from app.services.chat_history import repair_session_title_from_first_user_message

    cat = _normalize_chat_platform(category)
    sessions = db.query(ChatSession).filter(
        ChatSession.category == cat
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
    body: SessionCreate = Body(default_factory=SessionCreate),
    db: Session = Depends(get_db),
):
    """Yeni chat session oluştur"""
    cat = _normalize_chat_platform(body.category)
    session = ChatSession(
        title="Yeni Chat",
        server_ids=body.server_ids or [],
        category=cat,
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
async def delete_all_sessions(category: str = "linux", db: Session = Depends(get_db)):
    """Platform chat session'larını sil (kalıcı)"""
    cat = _normalize_chat_platform(category)
    ids = [s.id for s in db.query(ChatSession.id).filter(ChatSession.category == cat).all()]
    if ids:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
        db.commit()
    return {"success": True, "cleared": len(ids)}


@router.post("/", response_model=ChatResponse)
async def chat_message(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat mesajı gönder ve AI yanıtı al (SSH komut çalıştırma desteği ile)"""
    try:
        raw_message = request.message.strip()
        if not raw_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        from app.services.chat_output_directives import extract_output_directive
        message, output_directive = extract_output_directive(raw_message)

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

        # Seçili sunucular + Dalga 1 filo politikası (stream ile aynı)
        selected_servers = []
        explicit_server_target = bool(
            (request.server_ids and len(request.server_ids) > 0)
            or request.server_id
            or (request.hypervisor_ids and len(request.hypervisor_ids) > 0)
            or request.hypervisor_id
        )
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

        ai_ready_servers = _linux_ai_ready_servers(db)
        mentioned = _servers_mentioned_in_message(db, message)
        from app.services.chat_fleet_policy import (
            apply_live_collect_policy,
            inventory_lines_for_prompt,
        )
        inventory_servers = (
            list(selected_servers) if explicit_server_target and selected_servers
            else list(ai_ready_servers)
        )
        live_targets, _fleet_policy_note, _allow_live = apply_live_collect_policy(
            selected_servers if explicit_server_target else ai_ready_servers,
            message=message,
            has_explicit_selection=explicit_server_target and bool(selected_servers),
            mentioned=mentioned if not explicit_server_target else (
                list(dict.fromkeys(mentioned + selected_servers)) if mentioned else None
            ),
        )
        # Mention + explicit: politika mention'ı yok saydıysa birleştir
        if explicit_server_target and mentioned:
            from app.services.linux_info_collector import cap_servers_for_ssh as _cap_merge
            merged = list(dict.fromkeys(mentioned + list(live_targets or selected_servers)))
            live_targets, _cap_m = _cap_merge(merged, message)
            if _cap_m:
                _fleet_policy_note = ((_fleet_policy_note or "") + "\n" + _cap_m).strip()
        selected_servers = live_targets
        inventory_for_db = inventory_servers

        # Önce Prometheus (Node Exporter metrikleri) — SSH'a gerek kalmadan çoğu metrik buradan gelir
        PROMETHEUS_KEYWORDS = [
            'cpu', 'ram', 'memory', 'bellek', 'disk', 'bandwidth',
            'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
            'kullanım', 'usage', 'kaynak', 'tüket', 'tuket', 'tüketim', 'tuketim',
            'durum', 'status', 'genel', 'overview', 'özet',
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
        # OS/kernel/sistem bilgisi → Prometheus'ta yok
        APP_KEYWORDS = [
            'uygulama', 'uygulamalar', 'application', 'applications',
            'çalışıyor', 'calisiyor', 'hangi program', 'installed software',
        ]
        # DB_STATIC_SYSINFO_KEYWORDS / LIVE_VERIFY_KEYWORDS / _kw_hit / _kw_any modül
        # seviyesinde tanımlı (bkz. dosya başı) — chat_stream ile paylaşılır.
        SSH_SYSINFO_KEYWORDS = [
            'servis', 'service', 'running service', 'failed service',
            'sistem bilgi',
            'selinux', 'sestatus', 'getenforce', 'enforcing', 'permissive',
            'firewall', 'firewalld', 'iptables', 'güvenlik', 'security',
            'açık port', 'open port', 'sudo', 'sudoers',
            'mac', 'mac adresi', 'mac address', 'ifconfig', 'donanim adresi',
            'network', 'ağ arayüz', 'ethernet', 'ip link', 'ip addr', 'arp',
            'dns', 'nameserver', 'resolv', 'resolve.conf', 'resolv.conf',
            'nslookup', 'dig', 'isim çözümleme', 'name resolution',
            'gateway', 'ağ geçidi', 'default route', 'ip route',
            'sysctl', 'swappiness', 'dirty_ratio', 'dmesg', 'coredump', 'oom',
            'multipath', 'lvm', 'vgdisplay', 'pvdisplay', 'smartctl', 'zfs',
            'kök neden', 'kok neden', 'root cause', 'teşhis', 'teshis', 'diagnos',
            'neden yavaş', 'neden dolu', 'neden düştü', 'neden kapalı',
        ]
        DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
        msg_lower_ctx = message.lower()
        needs_prometheus = any(k in msg_lower_ctx for k in PROMETHEUS_KEYWORDS) and not request.skip_server_context
        # Dalga 1: prom ≠ SSH — SSH tetikleyicileri Prometheus listesinden ayrı
        _SSH_TRIGGER_CTX = SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS + APP_KEYWORDS + DEEP_PERF_KEYWORDS
        from app.services.linux_info_collector import has_recognized_topic as _has_topic_ctx

        db_only_answer, matched_db_static_topic = _classify_db_only_sysinfo(
            msg_lower_ctx, SSH_ONLY_KEYWORDS, SSH_SYSINFO_KEYWORDS
        )
        raw_topic_match = any(k in msg_lower_ctx for k in _SSH_TRIGGER_CTX) or _has_topic_ctx(message)
        # Prometheus-only sorular da "sunucu niyeti" sayılır (envanter/DB context için)
        prom_topic = any(k in msg_lower_ctx for k in PROMETHEUS_KEYWORDS)
        needs_ssh_ctx = raw_topic_match and not request.skip_server_context and not db_only_answer
        needs_db_sysinfo_ctx = (
            matched_db_static_topic or raw_topic_match or prom_topic
        ) and not request.skip_server_context
        ssh_timeout_ctx = 40.0 if any(k in msg_lower_ctx for k in DEEP_PERF_KEYWORDS) else 20.0

        # DB-only: canlı hedef yoksa envanterden liste (SSH yok)
        if db_only_answer and not selected_servers and inventory_for_db:
            selected_servers = inventory_for_db[:80]

        # Filo taramasını sınırla (canlı hedefler zaten policy+cap'ten geçti; ekstra cap güvenlik)
        _fleet_note = _fleet_policy_note
        if selected_servers and (needs_ssh_ctx or needs_db_sysinfo_ctx):
            from app.services.linux_info_collector import cap_servers_for_ssh as _cap_ssh
            selected_servers, _cap_note = _cap_ssh(selected_servers, message)
            if _cap_note:
                _fleet_note = ((_fleet_note or "") + "\n" + _cap_note).strip()
            if needs_ssh_ctx:
                n = len(selected_servers)
                ssh_timeout_ctx = min(90.0, max(float(ssh_timeout_ctx), 25.0 + 0.9 * n))

        # Genel sorularda (sunucu niyeti yok + sunucu seçilmedi) otomatik sunucu bağlamı ekleme.
        server_context = ""
        include_server_context = bool(selected_servers) and (
            needs_ssh_ctx or needs_db_sysinfo_ctx or explicit_server_target
        )
        if include_server_context and selected_servers:
            server_context = "Secili sunucular (gercek DB verileri):\n"
            for s in selected_servers:
                os_info = s.os_version or s.os_type or "Linux"
                extra_fields = []
                if s.kernel_version:
                    extra_fields.append(f"Kernel={s.kernel_version}")
                if s.hostname and s.hostname != s.name:
                    extra_fields.append(f"Hostname={s.hostname}")
                extra_str = (", " + ", ".join(extra_fields)) if extra_fields else ""
                server_context += f"- {s.name} ({s.ip_address}): OS={os_info}{extra_str}, Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB\n"
        elif not selected_servers and inventory_for_db and needs_db_sysinfo_ctx:
            server_context = inventory_lines_for_prompt(inventory_for_db)
        # _fleet_note context_parts'a eklenir (aşağıda) — server_context'e çift yazma


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

        # User mesajını DB'ye kaydet (gizli modda atla)
        if not request.ephemeral:
            user_msg = ChatMessage(
                session_id=session_id,
                role="user",
                content=raw_message,
            )
            db.add(user_msg)
            db.commit()
        
        # SSH ile gercek veri topla — sunucu keyword olmayan sohbet mesajlarında atla
        ssh_context = ""
        all_server_contexts: List[str] = []
        try:
            import asyncio
            from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
            # Dalga 1: Prometheus tek başına SSH açmaz
            if selected_servers and needs_ssh_ctx:
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
                                    if not request.ephemeral:
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
            if _fleet_note:
                context_parts.append(_fleet_note)
            if db_only_answer and selected_servers:
                context_parts.append(
                    "NOT: Bu bilgi (kernel/OS sürümü, hostname) periyodik arka plan taramasıyla "
                    "veritabanında zaten kayıtlı olduğu için sunuculara SSH ile bağlanılmadı, "
                    "doğrudan veritabanından okundu (daha hızlı yanıt için). Canlı/anlık "
                    "doğrulama isterseniz sorunuza 'canlı doğrula' ekleyip tekrar sorun."
                )
            # SSH'tan gelen gercek veri en oncelikli
            if ssh_context:
                focused = _extract_focused_summary(message, all_server_contexts)
                if focused:
                    context_parts.append(focused)
                context_parts.append(wrap_layer("ssh", ssh_context))
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
                            "ONCEDEN OGRENILMIS BILGILER (yapisal; SSH tarama veya admin manuel sabitleme — "
                            "canli BAGLAM ile celisirse canli veriyi esas al; MANUEL SABITLEME etiketli "
                            "satirlarda ozellikle dikkatli ol):\n" + "\n\n".join(_facts_blocks)
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

            # RAG: Runbook, incident/event, metrik + Bilgi Bankası (use_rag=True ise)
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
                    if rag_ctx.get("knowledge"):
                        context_parts.append(
                            "BİLGİ BANKASI / RAG (soruya ilgili öğrenilmiş sunucu bilgileri):\n"
                            + rag_ctx["knowledge"].strip()
                        )
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
                output_directive=output_directive,
            )

            async with httpx.AsyncClient(timeout=120.0) as client:
                data = await llm_gateway.generate_async(client, model=model, prompt=prompt)

                if not data.get("error"):
                    from app.services.answer_sanitize import sanitize_llm_answer
                    ai_response = sanitize_llm_answer(data.get("response", "Yanıt alınamadı") or "")

                    if not request.ephemeral:
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
                    if not request.ephemeral:
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
            if not request.ephemeral:
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
            if not request.ephemeral:
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
            if not request.ephemeral:
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
            if session_id is not None and not request.ephemeral:
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
    "kernel":        ["Kernel", "dmesg", "Kernel Log"],
    "dmesg":         ["dmesg Hatalar", "dmesg (son satırlar)", "dmesg (son)", "dmesg (sorun", "Kernel Logları", "Journal"],
    "analiz":        ["Journal", "dmesg", "Auth/secure", "Failed units", "sysctl conf", "sshd_config", "/etc/fstab"],
    "teşhis":        ["Journal", "dmesg", "Failed units", "Audit", "sysctl", "Firewall"],
    "teshis":        ["Journal", "dmesg", "Failed units", "Audit", "sysctl", "Firewall"],
    "config":        ["sysctl conf", "sshd_config", "/etc/fstab", "limits.conf", "DNS/nsswitch", "Firewall"],
    "yapılandırma":  ["sysctl conf", "sshd_config", "/etc/fstab", "SELinux config", "Ağ bağlantı"],
    "oom":           ["dmesg", "OOM", "out of memory", "oom-kill"],
    "oops":          ["dmesg", "oops", "panic", "segfault"],
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
    platform="linux",
    output_directive=None,
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

    if platform == "openshift":
        identity = NL.join([
            "Sen 15+ yillik deneyime sahip kıdemli bir OpenShift / Kubernetes Platform Yoneticisisin.",
            "Bu sohbet YALNIZCA OpenShift Container Platform kapsamındadır.",
            "",
            "UZMANLIK: pod, Deployment, StatefulSet, namespace/proje, Route, SCC, node, operator,",
            "CrashLoopBackOff, ImagePullBackOff, OOMKilled, PVC, etcd, clusterversion.",
            "",
            "KARISTIRMA: Linux sunucu SSH/systemd (systemctl, journalctl, SELinux) cevabi URETME.",
            "O konular icin kullaniciyi Linux AIOps sohbetine yonlendir.",
            "BAĞLAM ve ARAÇ SONUÇLARI OpenShift canlı verisidir — uydurma.",
            "",
            "ONEMLI: Asla 'cluster'a baglanamam' deme. Sistem OpenShift API ile sorgu yapabiliyor.",
        ])
    elif platform == "exadata":
        identity = NL.join([
            "Sen kıdemli bir Exadata / Oracle altyapı uzmanısın.",
            "Bu sohbet Exadata compute/cell'e bağlı Linux sunucular üzerindendir.",
            "Bağlamda Exadata kaydı yoksa uydurma; envanter eksikliğini açıkça söyle.",
            "Genel Linux SSH araçlarıyla node sağlığını inceleyebilirsin; cell/ILOM özel API yoksa belirt.",
        ])
    else:
        identity = NL.join([
        "Sen 15+ yillik deneyime sahip kıdemli bir Linux Sistem Yoneticisi",
        "ve Sanallaştırma Uzmanisın (Senior Linux SysAdmin & Virtualization Engineer).",
        "Kullanıcı birden fazla sunucu adı verip 'karşılaştır' / 'compare' derse:",
        "Linux/Windows için OS config (sürüm, kernel, güvenlik) ve kaynakları;",
        "VM için sanal makine özelliklerini; ESX için donanım (vendor/model/CPU/RAM/NIC)",
        "farklarını yan yana özetle; hangisinin production'a daha uygun olduğunu kısaca öner.",
        "",
        "PLATFORM SINIRI: Bu sohbet Linux sunucu (SSH/systemd) odaklıdır.",
        "OpenShift pod/namespace/cluster durumunu Linux SSH verisiyle karistirma;",
        "pod/CrashLoop sorulari icin OpenShift AIOps sohbetini oner.",
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
        "ADMIN TEŞHİS: 'analiz/dmesg/log/config/kök neden/sorun' sorularında BAGLAM'da",
        "journal, dmesg, auth/secure, failed units, fstab, sysctl, sshd_config, SELinux,",
        "firewall, DNS, cron, tuned vb. admin checklist alanları gelir — bunları kullanarak",
        "kıdemli bir sysadmin gibi yorumla. Eksik alan varsa uydurma.",
        "",
        "ONEMLI: Asla 'SSH yapamam' veya 'dogrudan baglanamam' deme.",
        "Sistem SSH yapabiliyor. Eger veri gelmemisse toplanmamis demektir, toplanamaz degil.",
        "",
        "ONEMLI: BAGLAM'da 'dmesg Hatalar: (err/crit ... yok)' veya benzeri '(... yok)' ibaresi",
        "varsa bu TOPLANMADI demek DEGILDIR — komut calisti ve ilgili satir bulunamadi.",
        "Bunu 'kritik dmesg satiri yok / temiz' diye ozetle; 'dmesg toplanmadi' deme.",
        "Gercekten SSH zaman asimi veya 'Hata:' satiri varsa ancak o zaman toplanamadigini soyle.",
        "",
        "ONEMLI: ASLA 'bilinmiyor' / 'bilmiyorum' kelimesini yazma. Veri BAGLAM'da varsa",
        "somut degeri yaz (ornegin hostname=minio2, SELinux=disabled, firewalld=inactive,",
        "steal=0.0). Veri yoksa: 'Bu bilgi mevcut taramada toplanmadi.' de — baska bir sey degil.",
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
        "5. Turkce yanitla",
        "5b. YANIT UZUNLUGU — VARSAYILAN KISA: Varsayilan olarak KISA, SADE ve NET cevap ver.",
        "    Basit/dogrudan bir soruya ('CPU kac cekirdek?', 'disk doluluk yuzdesi ne?', 'hangi",
        "    surum kurulu?' gibi) 1-3 cumlelik dogrudan cevap yeterlidir — gereksiz giris",
        "    cumlesi, arka plan bilgisi veya istenmeyen ek yorum ekleme. Kullanici acikca",
        "    'detayli anlat', 'derinlemesine incele', 'kok neden analizi yap', 'tum",
        "    detaylariyla acikla' gibi DAHA FAZLA DETAY istemedikce asagidaki UZMAN YANIT",
        "    TARZI'ndaki kok-neden/tani/adim/risk sablonunu HER soruya zorla uygulama.",
        "6. Veri varsa asla 'bilmiyorum' ya da 'emin degilim' deme — veriyi yorumla",
        "7. resolv.conf, /etc/ dosya iceriklerini gorudugunde, oldugu gibi goster (trim etme)",
        "",
        "UZMAN YANIT TARZI (SADECE arıza/performans/güvenlik gibi kök-neden gerektiren",
        "sorularda veya kullanici acikca detay istediginde uygula — basit sorularda ATLA):",
        "8. Boyle bir soruda bir kıdemli admin gibi ele al:",
        "   - Once olasi KOKEN NEDENLER (root cause) belirt",
        "   - BAGLAM'da komut ciktisi varsa yorumla; yoksa 'Bu bilgi mevcut taramada toplanmadi' de",
        "   - COZUM ADIMLARI numaralı liste halinde ver (yapilabilir, sirali)",
        "   - Varsa UYARI / RISK bilgisi ekle (ornegin: 'production'da dikkat, once test et')",
        "9. Teknik derinlikte cevap ver: kernel/sysctl, storage, network, security, container",
        "   konularinda somut parametre/esik/komut adi kullan — genel sohbet etme.",
        "10. Performans sorularinda degerleri yorumla:",
        "   - CPU iowait > %20 → disk darbogazı sinyali",
        "   - Load average > CPU cekirdek sayisi → sistem bunalmis",
        "11. Birden fazla sunucu varsa karsilastirma tablosu kur; anomaliyi isaretle.",
        "12. Kullaniciya 'kendiniz su komutu calistirin' deme; sistem SSH yapar.",
        "    Eksik veri varsa kisa soyle: hangi grup toplanamadi (or. journal, sysctl).",
        "13. Kritik islemler icin (rm, mkfs, reboot, kill) MUTLAKA uyari ver ve once yedek/snapshot al de",
        "14. VMware/oVirt sorularinda vSphere/oVirt terimleri kullan (datastore, portgroup, vNIC vb.)",
    ])

    prompt_parts = [identity]
    if collection_summary:
        prompt_parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    prompt_parts.append(rules)
    prompt_parts.append("BAGLAM:\n" + context_str)
    if history_block:
        prompt_parts.append("ONCEKI KONUSMA (bu oturumdaki son mesajlar, sadece baglam/niyet icin):\n" + history_block)
    prompt_parts.append("KULLANICI SORUSU: " + message)
    from app.services.chat_output_directives import directive_system_addendum
    _dir_add = directive_system_addendum(output_directive)
    if _dir_add:
        prompt_parts.append(_dir_add.strip())
        prompt_parts.append("YANIT:")
    else:
        prompt_parts.append("YANIT (Markdown, Turkce):")

    return "\n\n".join(prompt_parts)


# ── Streaming chat endpoint ──────────────────────────────────────────────────
from fastapi.responses import StreamingResponse
import json as _json
import asyncio as _asyncio


def _sse(obj: dict) -> str:
    return "data: " + _json.dumps(obj) + "\n\n"


def _persist_chat_pair(
    db: Session,
    session_id: int,
    *,
    ephemeral: bool,
    user: Optional[str] = None,
    assistant: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """Gizli (ephemeral) modda ChatMessage yazma; aksi halde user/assistant kaydet."""
    if ephemeral:
        return
    if user is not None:
        db.add(ChatMessage(session_id=session_id, role="user", content=user))
    if assistant is not None:
        kwargs = {"session_id": session_id, "role": "assistant", "content": assistant}
        if meta is not None:
            kwargs["meta"] = meta
        db.add(ChatMessage(**kwargs))
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if s:
        from datetime import datetime, timezone
        s.updated_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/stream")
async def chat_stream(request: "ChatRequest", db: Session = Depends(get_db)):
    """Streaming chat: cache → paralel context → Ollama SSE"""
    payload = request.model_dump()

    async def pipeline(payload: dict, db: Session):
        from app.services.chat_cache_service import get_cached_answer, save_to_cache
        request = ChatRequest(**payload)

        async def event_generator():
            try:
                raw_message = request.message.strip()
                if not raw_message:
                    yield _sse({"error": "Mesaj boş"})
                    return

                from app.services.chat_output_directives import (
                    OutputDirective as _OD,
                    extract_output_directive,
                )
                message, output_directive = extract_output_directive(raw_message)
                _has_directive = output_directive != _OD.NONE

                ephemeral = bool(request.ephemeral)
                chat_platform = _normalize_chat_platform(request.platform)

                # ── Session ──────────────────────────────────────────────────
                session_id = request.session_id
                if not session_id:
                    from app.services.chat_history import title_from_message
                    title = "[Gizli]" if ephemeral else title_from_message(message)
                    session = ChatSession(
                        title=title,
                        server_ids=request.server_ids or [],
                        category=chat_platform,
                    )
                    db.add(session)
                    db.commit()
                    db.refresh(session)
                    session_id = session.id
                else:
                    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                    if not session:
                        yield _sse({"error": "Session bulunamadı"})
                        return
                    if not ephemeral:
                        from app.services.chat_history import maybe_set_session_title
                        if maybe_set_session_title(session, message):
                            db.commit()

                yield _sse({"session_id": session_id, "start": True})

                # Kullanıcı mesajını stream başında kaydet (sayfa değişse bile history'de kalsın)
                if not ephemeral:
                    db.add(ChatMessage(session_id=session_id, role="user", content=raw_message))
                    db.commit()

                from app.services.chat_obs import ChatTiming
                _timing = ChatTiming(platform=chat_platform)

                # ── Tam filo onayı (pending) — chitchat'ten ÖNCE (ok/tamam çakışmasın) ──
                from app.services.chat_full_scan_policy import (
                    resolve_full_scan_turn,
                    set_request_fleet_cap,
                    reset_request_fleet_cap,
                    get_hard_max_fleet_cap,
                    get_default_fleet_cap,
                    get_full_scan_pending,
                )
                _fs = resolve_full_scan_turn(
                    db, session_id=session_id, message=message, platform=chat_platform,
                )
                if _fs.get("action") == "clarify":
                    clarify = _fs.get("clarification") or ""
                    yield _sse({"phase": "answering"})
                    yield _sse({"needs_confirmation": True, "intent": "full_scan_clarify"})
                    for i in range(0, len(clarify), 8):
                        yield _sse({"token": clarify[i:i + 8]})
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=clarify,
                        meta={"intents": ["full_scan_clarify"]},
                    )
                    yield _sse({"done": True, "session_id": session_id, "needs_confirmation": True})
                    return
                if _fs.get("action") == "decline":
                    decline = _fs.get("decline_text") or "İptal edildi."
                    yield _sse({"phase": "answering"})
                    for i in range(0, len(decline), 8):
                        yield _sse({"token": decline[i:i + 8]})
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=decline,
                        meta={"intents": ["full_scan_declined"]},
                    )
                    yield _sse({"done": True, "session_id": session_id})
                    return

                # ── Selamlaşma / sohbet: anında (pending onay yoksa) ──
                from app.services.chat_chitchat_policy import canned_chitchat_answer
                _pending_fs = get_full_scan_pending(session_id, platform=chat_platform)
                _cc = None if (_fs.get("full_scan") or _pending_fs) else canned_chitchat_answer(
                    message, platform=chat_platform,
                )
                if _cc:
                    yield _sse({"phase": "answering"})
                    yield _sse({"intent": "chitchat"})
                    _timing.note_ttft()
                    for i in range(0, len(_cc), 8):
                        yield _sse({"token": _cc[i:i + 8]})
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=_cc,
                        meta={"intents": ["chitchat"]},
                    )
                    _timing.finish(cache_hit=False, extra={"path": "chitchat"})
                    yield _sse({"done": True, "session_id": session_id})
                    return

                message = _fs.get("work_message") or message
                _fleet_scan_token = None
                if _fs.get("full_scan"):
                    _fleet_scan_token = set_request_fleet_cap(
                        get_hard_max_fleet_cap(), full_scan=True,
                    )
                    logger.info(
                        "[ChatStream] full_scan CONFIRMED platform=%s session=%s items≈%s hard=%s",
                        chat_platform, session_id, _fs.get("item_count"), get_hard_max_fleet_cap(),
                    )

                # Konusma gecmisi — bu takip sorusu mu (session'da onceki mesaj var mi)?
                from app.services.chat_history import fetch_recent_history, format_history_block, has_prior_messages
                _is_followup = (not ephemeral) and has_prior_messages(db, session_id)
                history_block = format_history_block(fetch_recent_history(db, session_id, limit=8)) if _is_followup else ""

                # ── 1. Cache kontrolü ─────────────────────────────────────────
                # Takip sorularinda cache'e bakilmiyor: onceki turlere bagimli bir soru
                # ("peki cpu?" gibi), session'i bilmeyen izole bir cache anahtariyla
                # eslesip baglamsiz/eski bir cevap donebilir (bkz. chat_cache_service.py
                # _context_key — session_id icermiyor).
                # Gizli modda cache okuma/yazma yok (prompt sızıntısı önlemi).
                server_ids = request.server_ids or []
                cached = None if (_is_followup or ephemeral or _has_directive) else get_cached_answer(
                    db, message, server_ids, platform=chat_platform,
                )
                _timing.mark("cache")
                if cached:
                    answer = cached["answer"]
                    yield _sse({"phase": "answering"})
                    _timing.note_ttft()
                    for i in range(0, len(answer), 8):
                        yield _sse({"token": answer[i:i+8]})
                    _persist_chat_pair(db, session_id, ephemeral=ephemeral, user=None, assistant=answer)
                    _timing.finish(cache_hit=True, extra={"from_cache": True})
                    yield _sse({"done": True, "session_id": session_id, "from_cache": True})
                    return

                yield _sse({"phase": "collecting"})
                _timing.mark("collect_start")
                # ── 2a/2b. Niyet yönlendirici (inventory / direct_cmd) ───────
                from app.services.admin_intent_router import (
                    route_admin_question,
                    resolve_linux_targets,
                    INTENT_INVENTORY,
                    INTENT_INVENTORY_SUMMARY,
                    INTENT_DIRECT_CMD,
                )
                from app.services.linux_chat_intent import (
                    format_fleet_inventory_answer,
                    load_identity_overlays,
                    collect_live_identity,
                )
                _route = route_admin_question(message, platform="linux")
                logger.info(
                    "[ROUTE] intent=%s conf=%.2f hints=%s",
                    _route.intent, _route.confidence, list((_route.hints or {}).keys()),
                )

                # Platform-scoped DB özeti (SSH/agent yok) — Linux sohbetinde Windows/OCP sızmaz
                if _route.intent == INTENT_INVENTORY_SUMMARY:
                    from app.services.infra_summary import build_infra_overview_text
                    inv_answer = build_infra_overview_text(db, platform=chat_platform)
                    for i in range(0, len(inv_answer), 8):
                        yield _sse({"token": inv_answer[i:i + 8]})
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=inv_answer,
                    )
                    if not ephemeral and not _has_directive:
                        save_to_cache(
                            db, message, inv_answer, server_ids, platform=chat_platform,
                        )
                    yield _sse({"done": True, "session_id": session_id})
                    return

                if chat_platform != "openshift" and _route.intent == INTENT_INVENTORY:
                    _inv_servers, _inv_note = resolve_linux_targets(
                        db, message,
                        server_ids=request.server_ids,
                        server_id=request.server_id,
                        session_id=session_id,
                        allow_full_fleet=True,  # hostname/IP listesi filoyu tarayabilir
                    )
                    if not _inv_servers and _inv_note:
                        for i in range(0, len(_inv_note), 8):
                            yield _sse({"token": _inv_note[i:i + 8]})
                        _persist_chat_pair(
                            db, session_id, ephemeral=ephemeral, user=None, assistant=_inv_note,
                        )
                        yield _sse({"done": True, "session_id": session_id})
                        return

                    yield _sse({"token": f"Hostname/IP için {len(_inv_servers)} sunucuda canlı kimlik taranıyor...\n\n"})

                    _overlays = load_identity_overlays(db, [s.id for s in _inv_servers])
                    for _sid, _slot in _overlays.items():
                        _slot.setdefault("source", "learned")

                    _cred_inv = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                    if not _cred_inv:
                        _cred_inv = db.query(GlobalCredential).first()
                    _live_ok = _live_fail = 0
                    if _inv_servers and _cred_inv:
                        import asyncio as _aio_inv
                        _loop_inv = _aio_inv.get_event_loop()
                        _live_map, _live_ok, _live_fail = await _loop_inv.run_in_executor(
                            None,
                            lambda: collect_live_identity(
                                _inv_servers, _cred_inv, db=db, ephemeral=ephemeral,
                            ),
                        )
                        for _sid, _slot in _live_map.items():
                            _overlays[_sid] = {**_overlays.get(_sid, {}), **_slot, "source": "ssh"}

                    inv_answer = format_fleet_inventory_answer(
                        _inv_servers, overlays=_overlays, live_ok=_live_ok, live_fail=_live_fail,
                    )
                    for i in range(0, len(inv_answer), 8):
                        yield _sse({"token": inv_answer[i:i + 8]})
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=inv_answer,
                    )
                    yield _sse({"done": True, "session_id": session_id})
                    return

                # ── 2b. Direkt komut çalıştırma (AI bypass) ─────────────────
                _LONG_CMDS = ['vmstat', 'iostat', 'sar', 'top -b']

                direct_cmds = list((_route.hints or {}).get("commands") or [])
                if _route.intent != INTENT_DIRECT_CMD:
                    direct_cmds = []
                logger.info(f"[DIRECT] direct_cmds={direct_cmds!r} server_id={request.server_id!r}")


                if direct_cmds:
                    logger.info(f"Direkt komut(lar) algılandı: {direct_cmds!r}")
                    _ANALYZE_KEYWORDS = ['analiz', 'analyze', 'yorumla', 'değerlendir', 'incele',
                                         'açıkla', 'neden', 'sorun', 'problem', 'yavaş', 'yüksek',
                                         'kontrol et', 'ne anlama', 'ne göster', 'raporla', 'rapor']
                    _needs_analysis = any(k in message.lower() for k in _ANALYZE_KEYWORDS)

                    # Tam filo default YOK — seçim / mesaj / session; yoksa sor
                    _target_servers, _tgt_note = resolve_linux_targets(
                        db, message,
                        server_ids=request.server_ids,
                        server_id=request.server_id,
                        session_id=session_id,
                        allow_full_fleet=False,
                    )
                    if not _target_servers:
                        _ask = _tgt_note or "Hangi sunucuda komutu çalıştırayım?"
                        for i in range(0, len(_ask), 8):
                            yield _sse({"token": _ask[i:i + 8]})
                        _persist_chat_pair(
                            db, session_id, ephemeral=ephemeral, user=None, assistant=_ask,
                        )
                        yield _sse({"done": True, "session_id": session_id})
                        return

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
                                raw_output_lines.append(f"**`{cmd}`**: *SSH hatası: {err or 'detay dönmedi'}*\n")
                                srv_ctx.append(f"--- {cmd} ---\nHATA: {err or 'detay dönmedi'}")
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
                    _persist_chat_pair(
                        db, session_id, ephemeral=ephemeral, user=None, assistant=full_resp,
                    )
                    yield _sse({"done": True, "session_id": session_id})
                    return

                # ── 2. Seçili sunucular + Dalga 1 filo politikası ─────────────
                selected_servers = []
                has_explicit_selection = bool(
                    (request.server_ids and len(request.server_ids) > 0)
                    or request.server_id
                    or (request.hypervisor_ids and len(request.hypervisor_ids) > 0)
                    or request.hypervisor_id
                )
                fleet_policy_note = None
                inventory_servers = []
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

                if chat_platform == "openshift":
                    selected_servers = []
                    inventory_servers = []
                else:
                    from app.services.chat_fleet_policy import (
                        apply_live_collect_policy,
                        inventory_lines_for_prompt,
                    )
                    all_ai_servers = _linux_ai_ready_servers(db)
                    mentioned = []
                    if not has_explicit_selection:
                        msg_lower_srv = message.lower()
                        for s in all_ai_servers:
                            if (s.name and s.name.lower() in msg_lower_srv) or (
                                s.ip_address and s.ip_address in message
                            ):
                                mentioned.append(s)
                        if mentioned:
                            logger.info(f"Mesajdan sunucu algılandı: {[s.name for s in mentioned]}")
                    inventory_servers = (
                        list(selected_servers) if has_explicit_selection and selected_servers
                        else list(all_ai_servers)
                    )
                    live_targets, fleet_policy_note, _allow_live = apply_live_collect_policy(
                        selected_servers if has_explicit_selection else all_ai_servers,
                        message=message,
                        has_explicit_selection=has_explicit_selection and bool(selected_servers),
                        mentioned=mentioned if not has_explicit_selection else None,
                    )
                    selected_servers = live_targets

                server_context = ""
                if chat_platform == "openshift":
                    try:
                        from app.models.openshift import OpenShiftCluster
                        clusters = db.query(OpenShiftCluster).all()
                        if clusters:
                            server_context = "OPENSHIFT CLUSTERLAR:\n" + "\n".join(
                                f"- {c.name}" for c in clusters
                            )
                    except Exception:
                        server_context = ""
                else:
                    if selected_servers:
                        def _srv_line(s):
                            extra = []
                            if s.kernel_version:
                                extra.append(f"Kernel={s.kernel_version}")
                            if s.hostname and s.hostname != s.name:
                                extra.append(f"Hostname={s.hostname}")
                            extra_str = (", " + ", ".join(extra)) if extra else ""
                            return (
                                f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}{extra_str}, "
                                f"Durum={s.status}, CPU={s.cpu_cores} core, RAM={s.memory_gb}GB"
                            )
                        server_context = "Canlı hedefler:\n" + "\n".join(
                            _srv_line(s) for s in selected_servers
                        )
                    elif inventory_servers:
                        server_context = inventory_lines_for_prompt(inventory_servers)
                    # fleet_policy_note context_parts'a (_fleet_note_stream) eklenir — burada değil


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
                        answer_text = chart_result["summary_text"]
                        if len(selected_servers) > 1:
                            answer_text += f"\n\n_(Not: Birden fazla sunucu seçili, grafik sadece **{target_server.name}** için oluşturuldu.)_"
                        for i in range(0, len(answer_text), 8):
                            yield _sse({"token": answer_text[i:i+8]})
                        _persist_chat_pair(
                            db, session_id, ephemeral=ephemeral,
                            user=None, assistant=answer_text,
                            meta={"charts": chart_result["charts"]},
                        )
                        yield _sse({"done": True, "session_id": session_id})
                        return

                # ── 3. Keyword analizi ────────────────────────────────────────
                PROMETHEUS_KEYWORDS = [
                    'cpu', 'ram', 'memory', 'bellek', 'disk', 'bandwidth',
                    'yük', 'load', 'performans', 'performance', 'metrik', 'metric',
                    'kullanım', 'usage', 'kaynak', 'tüket', 'tuket', 'tüketim', 'tuketim',
                    'durum', 'status', 'genel', 'overview', 'özet',
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
                # NOT: 'os'/'kernel'/'versiyon'/'hostname' vb. burada YOK — modül seviyesindeki
                # DB_STATIC_SYSINFO_KEYWORDS'te (bkz. dosya başı, chat_message ile paylaşılır).
                # Bu alanlar zaten Server tablosunda kayıtlı, SSH gerektirmez (bkz. db_only_answer).
                SSH_SYSINFO_KEYWORDS = [
                    'servis', 'service', 'running service', 'failed service',
                    'sistem bilgi',
                    'selinux', 'sestatus', 'getenforce', 'enforcing', 'permissive',
                    'firewall', 'firewalld', 'iptables', 'güvenlik', 'security',
                    'açık port', 'open port', 'sudo', 'sudoers',
                    'mac', 'mac adresi', 'mac address', 'ifconfig', 'donanim adresi',
                    'network', 'ağ arayüz', 'ethernet', 'ip link', 'ip addr', 'arp',
                    'dns', 'nameserver', 'resolv', 'resolve.conf', 'resolv.conf',
                    'nslookup', 'dig', 'isim çözümleme', 'name resolution',
                    'gateway', 'ağ geçidi', 'default route', 'ip route',
                    'sysctl', 'swappiness', 'dmesg', 'coredump', 'oom', 'oops',
                ]
                DEEP_PERF_KEYWORDS = ['vmstat', 'iostat', '1 dakika', '1 dak', 'derin analiz', 'benchmark', '1 saniyelik', '10 defa', 'saniye aralık', 'örnekle']
                ml = message.lower()
                needs_prometheus = any(k in ml for k in PROMETHEUS_KEYWORDS) and not request.skip_server_context
                # Dalga 1: Prometheus kelimeleri tek başına SSH açmaz (prom ≠ SSH).
                # SSH: SSH_ONLY / SSH_SYSINFO / derin perf / has_recognized_topic.
                # has_recognized_topic "kernel"/"os" da tanır → db_only_answer needs_ssh'i bastırır.
                from app.services.linux_info_collector import has_recognized_topic as _has_topic
                db_only_answer, matched_db_static_topic = _classify_db_only_sysinfo(
                    ml, SSH_ONLY_KEYWORDS, SSH_SYSINFO_KEYWORDS
                )
                _ssh_trigger = SSH_ONLY_KEYWORDS + SSH_SYSINFO_KEYWORDS + DEEP_PERF_KEYWORDS
                needs_ssh = (
                    any(k in ml for k in _ssh_trigger) or _has_topic(message)
                ) and not request.skip_server_context and not db_only_answer
                # OpenShift sohbeti Linux SSH/Prometheus ile karışmasın
                if chat_platform == "openshift":
                    needs_ssh = False
                    needs_prometheus = False
                    selected_servers = []
                # DB-only cevaplarda envanterden sunucu listesi (SSH yok)
                if db_only_answer and not selected_servers and inventory_servers:
                    selected_servers = inventory_servers[:80]
                is_deep         = any(k in ml for k in DEEP_PERF_KEYWORDS)
                # Filo üst sınırı — 200+ host'u tek turda patlatma (SSH) veya prompt'u
                # şişirme (db_only_answer — tüm filo DB tablosu LLM'e gönderilmesin).
                _fleet_note_stream = fleet_policy_note
                if selected_servers and (needs_ssh or db_only_answer):
                    from app.services.linux_info_collector import cap_servers_for_ssh as _cap_ssh_stream
                    selected_servers, _cap_note = _cap_ssh_stream(selected_servers, message)
                    if _cap_note:
                        _fleet_note_stream = ((_fleet_note_stream or "") + "\n" + _cap_note).strip()
                # Alt sınır 20s -> 30s (unified_chat.py'deki aynı düzeltmeyle uyumlu): "genel mod"a
                # düşen sorgular (STANDARD_GROUPS'un tamamı, ~9 grup/60+ komut) tek sunucuda bile
                # ölçümlerde 20-27s sürebiliyor — eski 20s taban bunu sığdırmadan zaman aşımına
                # uğrayıp "SSH verisi alınamadı" yanıtına yol açıyordu (bkz. "selinux durumu"
                # sorgusunun "durum" kelimesi yüzünden genel moda düşmesi — artık ayrıca
                # linux_info_collector.detect_needed_groups bu durumu da hafifletiyor).
                base_timeout    = 40.0 if is_deep else 30.0
                context_timeout = min(90.0, max(base_timeout, 20.0 + 1.0 * len(selected_servers)))

                # Varsayılan (is_default=True) işaretli bir credential yoksa da ilk tanımlı global
                # credential'a düş (unified_chat.py ile aynı davranış) — tek bir global credential
                # tanımlıyken "varsayılan" işaretlenmemiş olması yaygın bir kurulum hatasıydı.
                global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
                if not global_cred:
                    global_cred = db.query(GlobalCredential).first()

                # ── Dalga 2: collect XOR agentic (model/provider collect'ten önce) ──
                from app.services import runtime_settings as _rts
                from app.services.chat_path_policy import resolve_live_path, has_session_episode
                model = request.model or get_active_model(db)
                provider = _detect_provider(model)
                _uses_external_api = (
                    (provider == "groq" and bool(settings.GROQ_API_KEY)) or
                    (provider == "openai" and bool(settings.OPENAI_API_KEY)) or
                    (provider == "openrouter" and bool(settings.OPENROUTER_API_KEY))
                )
                _agentic_ok = (
                    (not _uses_external_api)
                    and (not ephemeral)
                    and (not request.skip_server_context)
                    and _rts.get_bool("linux_chat_agentic_mode")
                )
                # OpenShift: SSH collect yok ama agentic OCP araçları çalışabilir
                _wants_fixed = bool(needs_ssh) and chat_platform != "openshift"
                _live_path = resolve_live_path(
                    message,
                    agentic_enabled=_agentic_ok,
                    wants_fixed_collect=_wants_fixed,
                    has_live_targets=bool(selected_servers),
                    is_followup=_is_followup,
                    has_episode=has_session_episode(session_id=session_id, platform=chat_platform),
                    # OpenShift: SSH collect'i zaten yok, agentic hep açık. Linux/Exadata:
                    # BELİRLİ bir sunucu seçilmemişse (filo/genel soru — ör. "kritik event
                    # var mı", "kaç sunucu var") sabit SSH collect'i zaten çalışamaz;
                    # bu durumda DB/agentic araçlarına (db_list_critical_events, db_list_vms
                    # vb.) erişim KAPALI kalırsa soru hiçbir araç çağırmadan context'ten
                    # (RAG/cache) uydurma cevaplanıyordu — bkz. gözlemlenen regresyon.
                    allow_agentic_without_collect=(
                        chat_platform == "openshift" or not selected_servers
                    ),
                )
                if _live_path.is_deep:
                    is_deep = True
                logger.info(
                    "[LinuxChat] live_path reason=%s collect=%s agentic=%s targets=%s",
                    _live_path.reason, _live_path.run_fixed_collect, _live_path.run_agentic,
                    len(selected_servers),
                )

                # ── 4. Paralel context toplama ────────────────────────────────
                async def _collect_prometheus():
                    if not needs_prometheus:
                        return ""
                    try:
                        return await PrometheusMetricsService().get_metrics_context_for_ai(message)
                    except Exception:
                        return ""

                async def _collect_ssh():
                    # Dalga 1: Prometheus tek başına SSH açmaz
                    # Dalga 2: agentic-first XOR — sabit collect kapalıysa atla
                    if not needs_ssh or not _live_path.run_fixed_collect:
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
                                        if not ephemeral:
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

                # Dalga 3: canlı collect (prom+ssh) bitince ilerle; RAG best-effort
                from app.services.chat_obs import await_live_then_rag
                prom_task = _asyncio.ensure_future(_collect_prometheus())
                ssh_task = _asyncio.ensure_future(_collect_ssh())
                rag_task = _asyncio.ensure_future(_collect_rag())
                live_results, rag_ctx = await await_live_then_rag(
                    [prom_task, ssh_task],
                    rag_task,
                    live_timeout=context_timeout + 2.0,
                )
                prom_ctx = live_results[0] if isinstance(live_results[0], str) else ""
                ssh_ctx = live_results[1] if isinstance(live_results[1], str) else ""
                rag_ctx = rag_ctx if isinstance(rag_ctx, dict) else {}
                _timing.mark("collect_end")

                # ── 5. Prompt ─────────────────────────────────────────────────
                context_parts = []
                if chat_platform == "openshift":
                    try:
                        from app.services.agent.tools import _openshift_ask_handler
                        import json as _json_ocp
                        ocp_live = _openshift_ask_handler(db, {"question": message}, {})
                        if ocp_live.get("ok"):
                            context_parts.append(
                                "OPENSHIFT CANLI ÖZET (API):\n"
                                + _json_ocp.dumps(
                                    {
                                        k: ocp_live.get(k)
                                        for k in (
                                            "cluster", "version", "node_count", "nodes",
                                            "project_count", "pod_count", "pods_by_status",
                                            "problem_pod_count", "problem_pods_sample",
                                        )
                                        if ocp_live.get(k) is not None
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                )[:12000]
                            )
                        elif ocp_live.get("error"):
                            context_parts.append(
                                f"OPENSHIFT CANLI ÖZET: alınamadı — {ocp_live.get('error')}"
                            )
                    except Exception as _ocp_e:
                        logger.warning(f"[Chat] openshift prefetch: {_ocp_e}")
                elif chat_platform == "exadata" and not selected_servers:
                    context_parts.append(
                        "EXADATA NOTU: Bu ortamda Exadata node'una bağlı sunucu kaydı yok. "
                        "Cevap uydurma; kullanıcıyı Exadata envanter tanımlamaya yönlendir."
                    )
                if _fleet_note_stream:
                    context_parts.append(_fleet_note_stream)
                if db_only_answer and selected_servers:
                    context_parts.append(
                        "NOT: Bu bilgi (kernel/OS sürümü, hostname) periyodik arka plan taramasıyla "
                        "veritabanında zaten kayıtlı olduğu için sunuculara SSH ile bağlanılmadı, "
                        "doğrudan veritabanından okundu (daha hızlı yanıt için). Canlı/anlık "
                        "doğrulama isterseniz sorunuza 'canlı doğrula' ekleyip tekrar sorun."
                    )
                if ssh_ctx:
                    # Per-server contexts for focused summary
                    _ssh_server_ctxs = [c for c in ssh_ctx.split("\n\n") if c.strip()]
                    focused = _extract_focused_summary(message, _ssh_server_ctxs)
                    if focused:
                        context_parts.append(focused)
                    context_parts.append(wrap_layer("ssh", ssh_ctx))
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
                                "ONCEDEN OGRENILMIS BILGILER (yapisal; SSH tarama veya admin manuel sabitleme — "
                                "canli BAGLAM ile celisirse canli veriyi esas al; MANUEL SABITLEME etiketli "
                                "satirlarda ozellikle dikkatli ol):\n" + "\n\n".join(_facts_blocks)
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
                if rag_ctx.get("knowledge"):
                    context_parts.append(
                        "BILGI BANKASI / RAG:\n" + rag_ctx["knowledge"].strip()
                    )

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

                try:
                    from app.services.assistant_playbooks import append_playbook_to_context
                    context_str = append_playbook_to_context(
                        db, context_str, platform=chat_platform, question=message,
                    )
                except Exception:
                    pass

                try:
                    from app.services.episode_memory import append_episode_to_context
                    context_str = append_episode_to_context(
                        context_str, session_id=session_id, platform=chat_platform,
                    )
                except Exception:
                    pass

                # ── 5b. Model/sağlayıcı yukarıda (Dalga 2 path) belirlendi ──
                # Agentic READ_ONLY tool-calling — XOR: collect ile birlikte yalnızca
                # derin yol / force_both. Bkz. chat_path_policy.resolve_live_path.
                if _live_path.run_agentic:
                    yield _sse({"phase": "tools"})
                    _timing.mark("agentic_start")
                    try:
                        from app.services.unified_tool_chat import run_read_only_tool_loop
                        from app.services.agent.tools import domains_for_platform
                        max_tool_steps = _rts.get_int("linux_chat_max_tool_steps")
                        tool_domains = domains_for_platform(chat_platform)
                        if chat_platform == "openshift":
                            from app.models.openshift import OpenShiftCluster
                            clusters = db.query(OpenShiftCluster).all()
                            tool_server_summary = "\n".join(
                                f"- OpenShift cluster: {c.name} api={getattr(c, 'api_url', None) or '-'}"
                                for c in clusters
                            ) or "(Tanımlı OpenShift cluster yok)"
                        else:
                            tool_server_summary = "\n".join(
                                f"- {s.name} ({s.ip_address}) OS={s.os_type or s.os_version or 'Linux'} bağlantı=SSH"
                                for s in selected_servers
                            )

                        loop = _asyncio.get_event_loop()
                        gen = run_read_only_tool_loop(
                            db, model, message, context_str, tool_server_summary,
                            max_steps=max_tool_steps,
                            domains=tool_domains,
                            platform=chat_platform,
                            output_directive=output_directive,
                        )

                        def _next_item(g):
                            try:
                                return next(g)
                            except StopIteration:
                                return None

                        tool_context_text = ""
                        while True:
                            item = await loop.run_in_executor(None, _next_item, gen)
                            if item is None:
                                break
                            itype = item.get("type")
                            if itype == "tool_call":
                                yield _sse({"type": "tool_call", "tool": item.get("tool"), "label": item.get("label")})
                            elif itype == "tool_result":
                                yield _sse({"type": "tool_result", "tool": item.get("tool")})
                            elif itype == "final":
                                tool_context_text = item.get("tool_text") or ""
                                break
                            elif itype in ("skipped", "error"):
                                if itype == "error":
                                    logger.warning(f"[LinuxChat] agentic tool loop hatası: {item.get('detail')}")
                                break

                        if tool_context_text:
                            context_str = context_str + "\n\nARAÇ SONUÇLARI (bu turda modelin kendi kararıyla çalıştırdığı ek SSH/canlı sorgular):\n" + tool_context_text
                    except Exception as e:
                        logger.warning(f"[LinuxChat] agentic tool loop devre dışı bırakıldı: {e}")
                        # XOR agentic-first başarısızsa ve collect atlandıysa: bir kez collect dene
                        if needs_ssh and selected_servers and not _live_path.run_fixed_collect and not ssh_ctx:
                            try:
                                from app.services.linux_info_collector import (
                                    detect_needed_groups, collect_server_info, build_server_context as _bsc_fb,
                                )
                                groups = detect_needed_groups(message)
                                loop_fb = _asyncio.get_event_loop()
                                tasks_fb = [
                                    loop_fb.run_in_executor(
                                        None, lambda s=srv: collect_server_info(s, groups, global_cred, message)
                                    )
                                    for srv in selected_servers
                                ]
                                done_fb, pend_fb = await _asyncio.wait(tasks_fb, timeout=min(45.0, context_timeout))
                                for t in pend_fb:
                                    t.cancel()
                                ctxs_fb = []
                                for i, t in enumerate(tasks_fb):
                                    if t in done_fb:
                                        try:
                                            ctxs_fb.append(_bsc_fb(selected_servers[i], t.result()))
                                        except Exception:
                                            pass
                                if ctxs_fb:
                                    ssh_ctx = "\n\n".join(ctxs_fb)
                                    context_str = (
                                        wrap_layer("ssh_agentic", ssh_ctx)
                                        + ("\n\n" + context_str if context_str else "")
                                    )
                            except Exception as e_fb:
                                logger.debug("agentic fallback collect: %s", e_fb)
                    _timing.mark("agentic_end")

                # Episode: bu turdaki canlı keşfi follow-up için Redis'e yaz
                try:
                    from app.services.episode_memory import save_episode, summarize_live_context
                    live_bits = []
                    if ssh_ctx:
                        live_bits.append(ssh_ctx if isinstance(ssh_ctx, str) else str(ssh_ctx))
                    if "ARAÇ SONUÇLARI" in (context_str or ""):
                        live_bits.append(context_str.split("ARAÇ SONUÇLARI", 1)[-1][:2000])
                    summary = summarize_live_context("\n".join(live_bits))
                    if summary and not ephemeral:
                        save_episode(
                            session_id=session_id,
                            platform=chat_platform,
                            summary=summary,
                            server_names=[s.name for s in selected_servers] if selected_servers else None,
                        )
                except Exception:
                    pass

                try:
                    from app.services.llm_context_budget import apply_context_char_budget
                    context_str = apply_context_char_budget(context_str)
                except Exception:
                    pass

                prompt = _build_prompt(
                    message=message,
                    context_str=context_str,
                    ssh_collected=bool(ssh_ctx),
                    ssh_server_count=len([s for s in selected_servers]) if ssh_ctx else 0,
                    prometheus_available=bool(prom_ctx),
                    selected_server_names=[s.name for s in selected_servers],
                    history_block=history_block,
                    platform=chat_platform,
                    output_directive=output_directive,
                )

                # Kullanıcı mesajı stream başında kaydedildi; burada yalnızca AI yanıtı

                # ── 6. AI Streaming (Ollama / Groq / OpenAI / Anthropic / OpenRouter) ──────
                yield _sse({"phase": "answering"})
                full_response = ""
                _ttft_sent = False

                async with httpx.AsyncClient(timeout=180.0) as client:
                    if provider == "groq" and settings.GROQ_API_KEY:
                        async for token in _stream_external_openai(
                            client, settings.GROQ_API_URL, settings.GROQ_API_KEY,
                            model, prompt
                        ):
                            full_response += token
                            if not _ttft_sent and token:
                                _timing.note_ttft()
                                _ttft_sent = True
                            yield _sse({"token": token})

                    elif provider == "openai" and settings.OPENAI_API_KEY:
                        async for token in _stream_external_openai(
                            client, settings.OPENAI_API_URL, settings.OPENAI_API_KEY,
                            model, prompt
                        ):
                            full_response += token
                            if not _ttft_sent and token:
                                _timing.note_ttft()
                                _ttft_sent = True
                            yield _sse({"token": token})

                    elif provider == "openrouter" and settings.OPENROUTER_API_KEY:
                        async for token in _stream_external_openai(
                            client, settings.OPENROUTER_API_URL, settings.OPENROUTER_API_KEY,
                            model, prompt,
                            extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"}
                        ):
                            full_response += token
                            if not _ttft_sent and token:
                                _timing.note_ttft()
                                _ttft_sent = True
                            yield _sse({"token": token})

                    else:
                        # Ollama (varsayılan) veya REMOTE_LLM_ENABLED ise uzak gateway
                        llm_err = None
                        async for chunk in llm_gateway.stream_generate(client, model=model, prompt=prompt, timeout=180.0):
                            if chunk.get("error"):
                                llm_err = str(chunk["error"])
                                yield _sse({"error": llm_err})
                                break
                            token = chunk.get("response", "")
                            if token:
                                full_response += token
                                if not _ttft_sent:
                                    _timing.note_ttft()
                                    _ttft_sent = True
                                yield _sse({"token": token})
                            if chunk.get("done"):
                                break
                        if llm_err and not full_response:
                            full_response = f"(Hata: {llm_err})"

                # ── 7. Kaydet + Cache ─────────────────────────────────────────
                from app.services.answer_sanitize import sanitize_llm_answer
                full_response = sanitize_llm_answer(full_response or "")
                if not ephemeral:
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
                if (
                    full_response and not is_deep and not needs_ssh and not _is_followup
                    and not ephemeral and not _has_directive
                ):
                    save_to_cache(db, message, full_response, server_ids, platform=chat_platform)

                _timing.finish(
                    cache_hit=False,
                    extra={
                        "path": getattr(_live_path, "reason", ""),
                        "targets": len(selected_servers) if selected_servers else 0,
                    },
                )
                yield _sse({"done": True, "session_id": session_id})

            except Exception as e:
                logger.error(f"Stream error: {e}", exc_info=True)
                yield _sse({"error": str(e)})
                try:
                    _sid = locals().get("session_id")
                    if _sid and not locals().get("ephemeral"):
                        db.rollback()
                        db.add(ChatMessage(session_id=_sid, role="assistant", content=f"(Hata: {e})"))
                        s = db.query(ChatSession).filter(ChatSession.id == _sid).first()
                        if s:
                            from datetime import datetime, timezone
                            s.updated_at = datetime.now(timezone.utc)
                        db.commit()
                        yield _sse({"done": True, "session_id": _sid})
                except Exception:
                    try:
                        db.rollback()
                    except Exception:
                        pass
            finally:
                try:
                    _tok = locals().get("_fleet_scan_token")
                    if _tok is not None:
                        from app.services.chat_full_scan_policy import reset_request_fleet_cap
                        reset_request_fleet_cap(_tok)
                except Exception:
                    pass

        async for chunk in event_generator():
            yield chunk

    plat = _normalize_chat_platform(payload.get("platform"))
    from app.services.chat_orchestrator.http_bridge import attach_and_stream
    return attach_and_stream(
        platform=plat,
        payload=payload,
        message=payload.get("message") or "",
        session_id=payload.get("session_id"),
        pipeline=pipeline,
    )


class ChatFeedbackRequest(BaseModel):
    platform: str = "linux"
    question: str
    answer: Optional[str] = None
    server_ids: Optional[List[int]] = None
    session_id: Optional[int] = None
    message_id: Optional[int] = None
    vote: str  # up | down
    correction_text: Optional[str] = None


@router.post("/feedback")
def chat_feedback(body: ChatFeedbackRequest, db: Session = Depends(get_db)):
    """Asistan cevabına 👍/👎 veya düzeltme — QA cache öğrenmesi."""
    from app.services.chat_cache_service import apply_feedback

    try:
        result = apply_feedback(
            db,
            platform=body.platform,
            question=body.question,
            answer=body.answer,
            server_ids=body.server_ids,
            vote=body.vote,
            correction_text=body.correction_text,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("chat feedback failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
