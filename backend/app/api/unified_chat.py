"""
Unified (Tüm Altyapı) AI Chat API — Linux + Windows + Sanallaştırma'yı tek sohbette birleştirir.

Mimari `chat.py` / `windows_chat.py` ile aynıdır (session/DB, SSE streaming, çoklu LLM
sağlayıcı); tek fark bağlam toplama katmanının hem Linux (SSH) hem Windows (WinRM) hem de
sanallaştırma (DB özet) verilerini aynı anda, paralel olarak toplayıp birleştirmesidir.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, delete
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import asyncio as _asyncio
import json as _json
import logging
import httpx

from app.core.database import get_db
from app.core.config import settings, get_active_model
from app.models.server import Server
from app.models.chat_session import ChatSession, ChatMessage
from app.models.credential import GlobalCredential
from app.services.platform_scope import is_windows_server
from app.services import llm_gateway

logger = logging.getLogger(__name__)

CATEGORY = "unified"
router = APIRouter()


# ── Sağlayıcı tespiti / streaming — chat.py ile aynı mantık ──────────────────
def _detect_provider(model: str) -> str:
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


def _sse(obj: dict) -> str:
    return "data: " + _json.dumps(obj) + "\n\n"


# ── Sunucu envanteri yardımcıları ────────────────────────────────────────────
def _linux_ai_ready_servers(db: Session) -> List[Server]:
    return [s for s in db.query(Server).filter(Server.ai_ready == True).all() if not is_windows_server(s)]


def _windows_ai_ready_servers(db: Session) -> List[Server]:
    return [s for s in db.query(Server).filter(Server.ai_ready == True).all() if is_windows_server(s)]


def _infra_overview(db: Session) -> str:
    """Ucuz DB sorgularıyla tüm platformların özetini çıkar (her sorguda güvenle kullanılabilir)."""
    from app.services.infra_summary import build_infra_overview_text
    return build_infra_overview_text(db)


# ── İstek/yanıt modelleri ─────────────────────────────────────────────────────
class UnifiedChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    model: Optional[str] = None
    use_rag: Optional[bool] = True
    skip_server_context: Optional[bool] = False


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
async def list_sessions(db: Session = Depends(get_db)):
    from app.services.chat_history import repair_session_title_from_first_user_message

    sessions = db.query(ChatSession).filter(
        ChatSession.category == CATEGORY
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
async def create_session(db: Session = Depends(get_db)):
    session = ChatSession(title="Yeni Chat", server_ids=[], category=CATEGORY)
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


# ── Anahtar kelimeler — hangi platform(lar)dan canlı veri toplanacak ─────────
_LINUX_TRIGGER = [
    'linux', 'rhel', 'centos', 'ubuntu', 'debian', 'selinux', 'systemctl', 'journalctl',
    'kernel', 'ssh', 'vmstat', 'iostat', 'firewalld', 'iptables',
]
_WINDOWS_TRIGGER = [
    'windows', 'winrm', 'powershell', 'defender', 'event log', 'olay günlüğü', 'wsus',
    'active directory', 'iis', 'kb', 'domain',
]
_GENERAL_TRIGGER = [
    'cpu', 'ram', 'memory', 'bellek', 'disk', 'performans', 'performance', 'kullanım',
    'usage', 'yük', 'load', 'durum', 'status', 'genel', 'özet', 'rapor', 'servis', 'service',
    'log', 'hata', 'error', 'güncelleme', 'update', 'yama', 'patch', 'güvenlik', 'security',
    'os', 'işletim', 'sürüm', 'version', 'network', 'ağ', 'uptime',
]


def _build_prompt(message: str, context_str: str, collection_summary: str, history_block: str = "") -> str:
    NL = "\n"
    identity = NL.join([
        "Sen 15+ yillik deneyime sahip kıdemli bir",
        "Altyapı Mimarisin (Senior Infrastructure Architect) — Linux, Windows ve sanallaştırma",
        "(VMware/oVirt/KVM/Proxmox/Hyper-V) altyapılarının TAMAMINDAN sorumlusun. Platformlar",
        "arası çapraz analiz ve karşılaştırma yapabiliyorsun (ör. 'tüm sunucularda en yüksek CPU",
        "kullanan 5 sunucu', 'Linux ve Windows arasında güvenlik yaması durumu karşılaştırması',",
        "'genel altyapı sağlık özeti', 'srv1 ile srv2 config ve mimari karşılaştırması').",
        "Kullanıcı iki veya daha fazla sunucu/VM/ESX adı verip 'karşılaştır' derse:",
        "Linux/Windows → OS config; VM → sanal makine; ESX → donanım özellikleri",
        "açısından madde madde karşılaştır; hangisinin",
        "ne için daha uygun olduğunu kısaca öner.",
        "",
        "ROL DEĞİŞİMİ — HER PLATFORMU KENDİ UZMANI GİBİ DÜŞÜN:",
        "Tek bir jenerik bakış açısıyla değil, BAĞLAM'daki veri hangi platforma aitse o platformun",
        "kıdemli yöneticisi gibi düşünüp cevap ver:",
        "- 'LINUX SUNUCULARDAN ALINAN GERCEK VERILER' bölümünü değerlendirirken kıdemli bir Linux",
        "  Sistem Yöneticisi gibi düşün: RHEL/CentOS/Ubuntu/Debian, systemd, SELinux, LVM, kernel",
        "  parametreleri (sysctl), paket yönetimi (dnf/apt), journalctl/log analizi.",
        "- 'WINDOWS SUNUCULARDAN ALINAN GERCEK VERILER' bölümünü değerlendirirken kıdemli bir",
        "  Windows Server Yöneticisi gibi düşün: Active Directory, GPO, PowerShell, WSUS/yama",
        "  yönetimi, Event Viewer/Event Log analizi, IIS, Windows Firewall/Defender.",
        "- Sanallaştırma/VM/hypervisor envanteri sorulduğunda kıdemli bir Sanallaştırma",
        "  Yöneticisi gibi düşün: cluster/HA/DRS, datastore/storage kapasite planlama, VM",
        "  migration/snapshot stratejisi, kaynak overcommit riskleri.",
        "Platformlar arası bir soruda (ör. 'tüm sunucular') her platformun kendi uzmanlık",
        "perspektifinden bulgularını üret, SONRA bunları tek bir mimar özetinde birleştir.",
        "",
        "SISTEM YETENEKLERI:",
        "- Linux AI Ready sunuculara SSH ile bağlanıp gerçek komut/metrik toplayabiliyorsun",
        "- Windows AI Ready sunuculara WinRM/PowerShell ile bağlanıp gerçek veri toplayabiliyorsun",
        "- Sanallaştırma (hypervisor/VM) envanterini veritabanından özetleyebiliyorsun",
        "- Geçmiş konuşma, runbook ve incident kayıtları kullanılabiliyor",
        "",
        "ONEMLI: Asla 'SSH/WinRM yapamam' veya 'doğrudan bağlanamam' deme.",
        "Sistem bunu yapabiliyor. Veri gelmemişse toplanmamış demektir, toplanamaz değil.",
        "",
        "ONEMLI: Kullaniciya ASLA 'bunu su komutla siz kontrol edebilirsiniz' / 'asagidaki",
        "yontemleri kullanarak bulabilirsiniz' seklinde bir KILAVUZ/MANUEL TALIMAT LISTESI verme.",
        "Sistem SSH/WinRM ile komutu ZATEN calistirabiliyor — BAGLAM'da ilgili veri yoksa bu",
        "senin o komutu calistirmadigin anlamina gelir, kullanicinin gitmesi degil. Bu durumda",
        "sadece 'Bu bilgi mevcut taramada toplanmadi.' de; kullaniciyi kendi basina komut",
        "calistirmaya yonlendirme.",
    ])

    rules = NL.join([
        "YANIT KURALLARI:",
        "0. ONCEKI KONUSMA bölümü varsa bu bir sohbetin parçasıdır — takip sorularını",
        "   ('peki cpu?', 'o sunucuda ise nasıl?' gibi) ONCEKI KONUSMA'ya bakarak hangi",
        "   sunucu/platform/konudan bahsedildiğini çıkararak yanıtla. Güncel veri için her",
        "   zaman BAĞLAM bölümünü esas al — geçmişteki eski değerleri güncelmiş gibi tekrar etme.",
        "1. BAĞLAM bölümündeki GERÇEK veriyi kullan — kendi bilginle asla tahmin yapma",
        "1b. ONCEDEN OGRENILMIS BILGILER sadece canli veride o bilgi yoksa kullanilir; kullanirken",
        "    '(onceden ogrenilmis, X once dogrulandi)' diye belirt. Celiski varsa canli veri kazanir.",
        "1c. 'Hangi uygulamalar/veritabanlari calisiyor' gibi sorularda TESPIT EDILEN UYGULAMALAR",
        "    bolumunu kullan (otomatik periyodik tarama) — bos ise 'uygulama taramasi henuz yapilmadi' de.",
        "2. Platformlar arası soruda (ör. 'tüm sunucular') Linux ve Windows verilerini AYRI",
        "   bölümler halinde, yukarıdaki ROL DEĞİŞİMİ kuralına göre değerlendirip TEK bir",
        "   yanıt/tablo içinde birleştir",
        "3. Tablo istenirse Markdown tablo kullan, mümkünse 'Platform' kolonu ekle (Linux/Windows)",
        "4. Türkçe yanıtla — net ve açıklayıcı yaz",
        "5. Veri eksikse hangi platform/sunucu için eksik olduğunu açıkça belirt",
        "6. Her soruyu ilgili platformun kıdemli yöneticisi gibi ele al: kök neden, tanı komutu, "
        "çözüm adımları, risk uyarısı",
    ])

    parts = [identity]
    if collection_summary:
        parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    parts.append(rules)
    parts.append("BAGLAM:\n" + context_str)
    if history_block:
        parts.append("ONCEKI KONUSMA (bu oturumdaki son mesajlar, sadece baglam/niyet icin):\n" + history_block)
    parts.append("KULLANICI SORUSU: " + message)
    parts.append("YANIT (Markdown, Türkçe):")
    return "\n\n".join(parts)


@router.post("/stream")
async def unified_chat_stream(request: UnifiedChatRequest, db: Session = Depends(get_db)):
    """Streaming unified chat: Linux + Windows + Sanallaştırma bağlamını paralel toplar."""
    from app.services.chat_cache_service import get_cached_answer, save_to_cache

    async def event_generator():
        try:
            message = request.message.strip()
            if not message:
                yield _sse({"error": "Mesaj boş"})
                return

            session_id = request.session_id
            if not session_id:
                from app.services.chat_history import title_from_message
                title = title_from_message(message)
                session = ChatSession(title=title, server_ids=[], category=CATEGORY)
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

            # Takip sorularinda cache'e bakilmiyor — bkz. chat.py'deki ayni mantik.
            cache_key_ids: List[int] = []
            cached = None if _is_followup else get_cached_answer(db, message, cache_key_ids)
            if cached:
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                db.commit()
                answer = cached["answer"]
                for i in range(0, len(answer), 8):
                    yield _sse({"token": answer[i:i+8]})
                db.add(ChatMessage(session_id=session_id, role="assistant", content=answer))
                s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s:
                    s.updated_at = datetime.now(timezone.utc)
                db.commit()
                yield _sse({"done": True, "session_id": session_id, "from_cache": True})
                return

            ml = message.lower()
            skip_ctx = bool(request.skip_server_context)
            # chat.py'deki has_recognized_topic() ile aynı mantık — "vm.min_free_kbytes" gibi
            # _LINUX_TRIGGER/_GENERAL_TRIGGER listelerinde olmayan ama spesifik bir sysctl/kernel
            # parametresine işaret eden sorgular da Linux context toplamayı tetiklemeli.
            from app.services.linux_info_collector import has_recognized_topic as _has_topic_u
            wants_linux = (
                any(k in ml for k in _LINUX_TRIGGER) or any(k in ml for k in _GENERAL_TRIGGER) or _has_topic_u(message)
            ) and not skip_ctx
            wants_windows = (any(k in ml for k in _WINDOWS_TRIGGER) or any(k in ml for k in _GENERAL_TRIGGER)) and not skip_ctx

            linux_servers = _linux_ai_ready_servers(db)
            windows_servers = _windows_ai_ready_servers(db)

            # Mesajda açıkça belirtilen sunucu varsa sadece onu hedefle (daha hızlı ve odaklı).
            # chat.py'deki _servers_mentioned_in_message'ı kullanıyoruz: sadece `name` +
            # `ip_address` substring eşleşmesi (eski kod) `hostname`'i hiç kontrol etmiyordu ve
            # kelime sınırı olmadan substring eşleştiği için hem yanlış eşleşme hem de
            # (hostname farklıysa) HİÇ eşleşmeme riski vardı — bu durumda linux_targets sessizce
            # TÜM filoya düşüp (bkz. aşağıdaki `or`) geniş filolarda zaman aşımına yol açıyordu.
            from app.api.chat import _servers_mentioned_in_message
            mentioned_ids = {s.id for s in _servers_mentioned_in_message(db, message)}
            linux_mentioned = [s for s in linux_servers if s.id in mentioned_ids]
            windows_mentioned = [s for s in windows_servers if s.id in mentioned_ids]
            linux_targets = linux_mentioned or linux_servers
            windows_targets = windows_mentioned or windows_servers

            # Alt sınır 15s -> 30s'ye çıkarıldı: "OS config" gibi genel/geniş sorgular
            # detect_needed_groups'tan ~9 grup (services/security/disk/os/cpu/kernel/load/
            # uptime/memory) döner ve bunların HER BİRİ o sunucuya ayrı bir SSH komutu olarak
            # gidiyor — tek bir SSH oturumu üzerinden sıralı çalıştıkları için ölçümlerde tek
            # sunucu için bile 20-27s sürebiliyor (bkz. enes97/minio1 karşılaştırma vakası).
            # Eski 15s tabanı, sadece 1-2 sunuculuk (küçük filo formülü düşük çıkan) ama GENİŞ
            # kapsamlı sorgularda süre dolmadan bitmeyip sessizce zaman aşımına uğruyor ve
            # "veri toplanamadı"ya yol açıyordu. Üst sınır da 45s -> 60s'ye çıkarıldı ki büyük
            # filolarda + geniş sorguda taban değil ölçeklenen kısım devreye girsin.
            context_timeout = min(60.0, max(30.0, 10.0 + 2.0 * (len(linux_targets) + len(windows_targets))))
            # Varsayılan (is_default=True) işaretli bir credential yoksa da (chat.py ile aynı
            # davranış) ilk tanımlı global credential'a düş — sadece tek bir global credential
            # tanımlıyken "varsayılan" olarak işaretlenmemiş olması yaygın bir kurulum hatasıydı
            # ve bu durumda global_cred=None kalıp per-server ayarı olmayan sunucular
            # "SSH credential yok" hatası alıyordu.
            global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
            if not global_cred:
                global_cred = db.query(GlobalCredential).first()

            async def _collect_linux():
                if not (wants_linux and linux_targets):
                    return ""
                try:
                    from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
                    groups = detect_needed_groups(message)
                    loop = _asyncio.get_event_loop()
                    tasks = [loop.run_in_executor(None, lambda s=srv: collect_server_info(s, groups, global_cred, message)) for srv in linux_targets]
                    done, pending = await _asyncio.wait(tasks, timeout=context_timeout)
                    for t in pending:
                        t.cancel()
                    ctxs = []
                    for i, t in enumerate(tasks):
                        if t in done:
                            try:
                                info = t.result()
                                ctxs.append(build_server_context(linux_targets[i], info))
                                try:
                                    from app.services.fact_learning import extract_and_store_facts
                                    extract_and_store_facts(db, linux_targets[i], info, platform="linux")
                                except Exception:
                                    pass
                            except Exception:
                                pass
                    return "\n\n".join(ctxs)
                except Exception as e:
                    logger.debug(f"Unified linux context error: {e}")
                    return ""

            async def _collect_windows():
                if not (wants_windows and windows_targets):
                    return ""
                try:
                    from app.services.windows.windows_info_collector import detect_needed_groups, collect_server_info, build_server_context
                    from app.services.windows_log_collector import _build_client
                    groups = detect_needed_groups(message)
                    loop = _asyncio.get_event_loop()

                    def _collect_one(srv):
                        client = _build_client(srv, db)
                        if not client:
                            return build_server_context(srv.name, srv.ip_address or "-", {"error": "WinRM kimlik bilgisi/bağlantı yok"}), None
                        info = collect_server_info(client, groups)
                        return build_server_context(srv.name, srv.ip_address or "-", info), info

                    tasks = [loop.run_in_executor(None, _collect_one, srv) for srv in windows_targets]
                    done, pending = await _asyncio.wait(tasks, timeout=context_timeout)
                    for t in pending:
                        t.cancel()
                    ctxs = []
                    for i, t in enumerate(tasks):
                        if t in done:
                            try:
                                ctx_str, info = t.result()
                                ctxs.append(ctx_str)
                                if info:
                                    try:
                                        from app.services.fact_learning import extract_and_store_facts
                                        extract_and_store_facts(db, windows_targets[i], info, platform="windows")
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    return "\n\n".join(ctxs)
                except Exception as e:
                    logger.debug(f"Unified windows context error: {e}")
                    return ""

            async def _collect_rag():
                if request.use_rag is False:
                    return {}
                try:
                    from app.services.rag_service import get_rag_context_for_message
                    return await get_rag_context_for_message(message)
                except Exception:
                    return {}

            # NOT: wait_for(gather(...)) kullanmıyoruz çünkü tek bir yavaş görev (ör. büyük
            # Linux filosu) zaman aşımına uğradığında TÜM sonuçları (zaten tamamlanmış
            # Windows/RAG dahil) iptal edip atardı. asyncio.wait ile her görevin sonucu
            # kendi tamamlanma durumuna göre bağımsız olarak korunur.
            linux_task = _asyncio.ensure_future(_collect_linux())
            windows_task = _asyncio.ensure_future(_collect_windows())
            rag_task = _asyncio.ensure_future(_collect_rag())
            done, pending = await _asyncio.wait(
                [linux_task, windows_task, rag_task], timeout=context_timeout + 3.0
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

            linux_ctx = _safe_result(linux_task, "")
            windows_ctx = _safe_result(windows_task, "")
            rag_ctx = _safe_result(rag_task, {})
            linux_ctx = linux_ctx if isinstance(linux_ctx, str) else ""
            windows_ctx = windows_ctx if isinstance(windows_ctx, str) else ""
            rag_ctx = rag_ctx if isinstance(rag_ctx, dict) else {}

            context_parts = [_infra_overview(db)]
            if linux_ctx:
                context_parts.append("LINUX SUNUCULARDAN ALINAN GERCEK VERILER (SSH):\n" + linux_ctx.strip())
            if windows_ctx:
                context_parts.append("WINDOWS SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + windows_ctx.strip())

            _all_targets = list(linux_targets) + list(windows_targets)
            if _all_targets:
                try:
                    from app.services.fact_learning import get_learned_facts_block
                    _facts_blocks = []
                    for _s in _all_targets[:5]:
                        _fb = get_learned_facts_block(db, _s)
                        if _fb:
                            _facts_blocks.append(f"[{_s.name}]\n{_fb}")
                    if _facts_blocks:
                        context_parts.append(
                            "ONCEDEN OGRENILMIS BILGILER (yapisal, gecmis taramalardan — canli "
                            "veriyle celisirse canli veriyi esas al, kullanirken 'onceden ogrenilmis "
                            "(X once dogrulandi)' diye belirt):\n" + "\n\n".join(_facts_blocks)
                        )
                except Exception:
                    pass

                try:
                    from app.services.app_discovery import get_discovered_apps_block
                    _apps_blocks = []
                    for _s in _all_targets[:5]:
                        _ab = get_discovered_apps_block(db, _s)
                        if _ab:
                            _apps_blocks.append(f"[{_s.name}]\n{_ab}")
                    if _apps_blocks:
                        context_parts.append(
                            "TESPIT EDILEN UYGULAMALAR (otomatik tarama ile bulunan calisan servisler — "
                            "Oracle DB, PostgreSQL, Nginx, IIS, MSSQL vb.; celisirse canli veriyi esas al):\n"
                            + "\n\n".join(_apps_blocks)
                        )
                except Exception:
                    pass

            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER OLAYLAR:\n" + rag_ctx["incidents"].strip())
            context_str = "\n\n".join(context_parts)

            coll_lines = []
            if linux_ctx:
                coll_lines.append(f"LINUX: {len(linux_targets)} sunucudan canlı veri toplandı.")
            elif wants_linux and linux_targets:
                coll_lines.append("LINUX: Bu sorgu için canlı veri toplanamadı (zaman aşımı/bağlantı).")
            if windows_ctx:
                coll_lines.append(f"WINDOWS: {len(windows_targets)} sunucudan canlı veri toplandı.")
            elif wants_windows and windows_targets:
                coll_lines.append("WINDOWS: Bu sorgu için canlı veri toplanamadı (zaman aşımı/bağlantı).")
            collection_summary = "\n".join(coll_lines)

            prompt = _build_prompt(message, context_str, collection_summary, history_block)

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
                        extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"}
                    ):
                        full_response += token
                        yield _sse({"token": token})
                else:
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

            db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response or "(yanıt alınamadı)"))
            s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if s:
                s.updated_at = datetime.now(timezone.utc)
            db.commit()

            if full_response and not linux_ctx and not windows_ctx and not _is_followup:
                save_to_cache(db, message, full_response, cache_key_ids)

            yield _sse({"done": True, "session_id": session_id})

        except Exception as e:
            logger.error(f"Unified chat stream error: {e}", exc_info=True)
            yield _sse({"error": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
