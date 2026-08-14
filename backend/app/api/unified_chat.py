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
_OPENSHIFT_TRIGGER = [
    'openshift', 'ocp', 'kubernetes', 'k8s', 'kube', 'pod', 'pods', 'namespace',
    'crashloop', 'crashloopbackoff', 'imagepull', 'deployment', 'statefulset',
    'route', 'scc', 'operator', 'etcd', 'oc get', 'kubectl', 'kubevirt',
    'proje', 'project', 'clusterversion', 'machineconfig',
]
_GENERAL_TRIGGER = [
    'cpu', 'ram', 'memory', 'bellek', 'disk', 'performans', 'performance', 'kullanım',
    'usage', 'yük', 'load', 'durum', 'status', 'genel', 'özet', 'rapor', 'servis', 'service',
    'kaynak', 'tüket', 'tuket', 'tüketim', 'tuketim',
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
        "- OpenShift/pod/namespace araç sonuçlarını değerlendirirken kıdemli bir OpenShift",
        "  Platform Yöneticisi gibi düşün — Linux systemd ile karıştırma.",
        "- Sanallaştırma/VM/hypervisor envanteri sorulduğunda kıdemli bir Sanallaştırma",
        "  Yöneticisi gibi düşün: cluster/HA/DRS, datastore/storage kapasite planlama, VM",
        "  migration/snapshot stratejisi, kaynak overcommit riskleri.",
        "Platformlar arası bir soruda (ör. 'tüm sunucular') her platformun kendi uzmanlık",
        "perspektifinden bulgularını üret, SONRA bunları tek bir mimar özetinde birleştir.",
        "Aynı yanıtta Linux SSH çıktısını OpenShift pod listesi gibi sunma.",
        "",
        "SISTEM YETENEKLERI:",
        "- Linux AI Ready sunuculara SSH ile bağlanıp gerçek komut/metrik toplayabiliyorsun",
        "- Windows AI Ready sunuculara WinRM/PowerShell ile bağlanıp gerçek veri toplayabiliyorsun",
        "- Sanallaştırma (hypervisor/VM) envanterini veritabanından özetleyebiliyorsun",
        "- OpenShift Virtualization (KubeVirt) VM'leri OpenShift modülünde canlı listelenir",
        "- Geçmiş konuşma, runbook ve incident kayıtları kullanılabiliyor",
        "",
        "SANALLASTIRMA KAPSAMI (KRİTİK — karıştırma):",
        "- OpenShift Virtualization (OV / KubeVirt) BİR SANALLAŞTIRMA ORTAMIDIR.",
        "- 'Kaç sanallaştırma ortamı / hangi hypervisor'lar var?' sorusunda YALNIZCA",
        "  hypervisors tablosundaki VMware kaydına bakıp 'OV yok / sayılmaz' DEME.",
        "- OpenShift sayfasındaki Virtual Machines (KubeVirt) listesi varsa OV ortamı",
        "  MEVCUTTUR; bunu sanallaştırma kapsamına dahil et. Hypervisor satırı yoksa",
        "  'ayrı openshift_virt hypervisor kaydı yok; OV OpenShift kümesi üzerinden",
        "  yönetiliyor' diye ayır — 'sanallaştırma sayılmaz' deme.",
        "- VMware/vCenter = hypervisor envanteri; OV = OpenShift/KubeVirt yüzeyi;",
        "  ikisi de sanallaştırmadır, farklı entegrasyon yollarıdır.",
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
        "1d. GENEL bir teknik/kavramsal soruysa (BU ORTAMDAKİ belirli bir sunucu/VM/metriğe "
        "    bağlı olmayan, ör. 'RAID5 nedir', 'TCP handshake nasıl işler', 'X ne işe yarar') "
        "    kendi mühendislik bilgini SERBESTÇE kullan — BAĞLAM'da bu konuda veri olmaması "
        "    sorun değildir, 'bu bilgi mevcut değil' DEME.",
        "2. Platformlar arası soruda (ör. 'tüm sunucular') Linux ve Windows verilerini AYRI",
        "   bölümler halinde, yukarıdaki ROL DEĞİŞİMİ kuralına göre değerlendirip TEK bir",
        "   yanıt/tablo içinde birleştir",
        "3. Tablo istenirse Markdown tablo kullan, mümkünse 'Platform' kolonu ekle (Linux/Windows)",
        "4. Türkçe yanıtla — net ve açıklayıcı yaz",
        "5. Veri eksikse (ve soru BU ORTAMA özgüyse) hangi platform/sunucu için eksik olduğunu",
        "   açıkça belirt",
        "6. YANIT UZUNLUĞU — VARSAYILAN KISA: Varsayılan olarak KISA, SADE ve NET cevap ver.",
        "   Basit/doğrudan bir soruya ('kaç VM var?', 'hangi sürüm?', 'CPU kullanımı ne kadar?'",
        "   gibi) 1-3 cümlelik doğrudan cevap ya da küçük bir tablo yeterlidir — gereksiz giriş",
        "   cümlesi, arka plan bilgisi veya istenmeyen ek yorum ekleme. SADECE kullanıcı açıkça",
        "   'detaylı anlat', 'derinlemesine incele', 'kök neden analizi yap', 'tüm detaylarıyla",
        "   açıkla' derse ya da soru gerçekten arıza/performans/güvenlik gibi kök-neden",
        "   gerektiren bir konuysa somut kanıt, olası neden ve risk uyarısı ekleyerek genişlet.",
        "   HER cevaba aynı sabit şablonu (kök neden → tanı komutu → numaralı adım → risk)",
        "   zorla uygulama.",
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

            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.commit()

            from app.services.chat_obs import ChatTiming
            _timing = ChatTiming(platform="unified")

            # Tam filo onayı — chitchat'ten ÖNCE (ok/tamam çakışmasın)
            from app.services.chat_full_scan_policy import (
                resolve_full_scan_turn,
                set_request_fleet_cap,
                reset_request_fleet_cap,
                get_hard_max_fleet_cap,
                get_full_scan_pending,
            )
            _fs = resolve_full_scan_turn(
                db, session_id=session_id, message=message, platform="unified",
            )
            if _fs.get("action") == "clarify":
                clarify = _fs.get("clarification") or ""
                yield _sse({"phase": "answering"})
                yield _sse({"needs_confirmation": True, "intent": "full_scan_clarify"})
                for i in range(0, len(clarify), 8):
                    yield _sse({"token": clarify[i:i + 8]})
                db.add(ChatMessage(
                    session_id=session_id, role="assistant", content=clarify,
                    meta={"intents": ["full_scan_clarify"]},
                ))
                db.commit()
                yield _sse({"done": True, "session_id": session_id, "needs_confirmation": True})
                return
            if _fs.get("action") == "decline":
                decline = _fs.get("decline_text") or "İptal edildi."
                yield _sse({"phase": "answering"})
                for i in range(0, len(decline), 8):
                    yield _sse({"token": decline[i:i + 8]})
                db.add(ChatMessage(
                    session_id=session_id, role="assistant", content=decline,
                    meta={"intents": ["full_scan_declined"]},
                ))
                db.commit()
                yield _sse({"done": True, "session_id": session_id})
                return

            from app.services.chat_chitchat_policy import canned_chitchat_answer
            _pending_fs = get_full_scan_pending(session_id, platform="unified")
            _cc = None if (_fs.get("full_scan") or _pending_fs) else canned_chitchat_answer(
                message, platform="unified",
            )
            if _cc:
                yield _sse({"phase": "answering"})
                yield _sse({"intent": "chitchat"})
                _timing.note_ttft()
                for i in range(0, len(_cc), 8):
                    yield _sse({"token": _cc[i:i + 8]})
                db.add(ChatMessage(
                    session_id=session_id, role="assistant", content=_cc,
                    meta={"intents": ["chitchat"]},
                ))
                db.commit()
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
                    "[UnifiedChat] full_scan CONFIRMED session=%s items≈%s",
                    session_id, _fs.get("item_count"),
                )

            # Konusma gecmisi — bu takip sorusu mu (session'da onceki mesaj var mi)?
            from app.services.chat_history import fetch_recent_history, format_history_block, has_prior_messages
            _is_followup = has_prior_messages(db, session_id)
            history_block = format_history_block(fetch_recent_history(db, session_id, limit=8)) if _is_followup else ""

            # Takip sorularinda cache'e bakilmiyor — bkz. chat.py'deki ayni mantik.
            cache_key_ids: List[int] = []
            cached = None if _is_followup else get_cached_answer(
                db, message, cache_key_ids, platform="unified",
            )
            _timing.mark("cache")
            if cached:
                answer = cached["answer"]
                yield _sse({"phase": "answering"})
                _timing.note_ttft()
                for i in range(0, len(answer), 8):
                    yield _sse({"token": answer[i:i+8]})
                db.add(ChatMessage(session_id=session_id, role="assistant", content=answer))
                s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s:
                    s.updated_at = datetime.now(timezone.utc)
                db.commit()
                _timing.finish(cache_hit=True, extra={"from_cache": True})
                yield _sse({"done": True, "session_id": session_id, "from_cache": True})
                return

            yield _sse({"phase": "collecting"})
            _timing.mark("collect_start")

            skip_ctx = bool(request.skip_server_context)

            # ── Dalga 2: tek structured intent router ─────────────────────
            from app.services.unified_intent_router import route_unified
            from app.services.chat_path_policy import has_session_episode
            from app.services.chat_planning_intent import (
                build_planning_clarification,
                set_planning_clarification_pending,
                has_planning_clarification_pending,
                clear_planning_clarification_pending,
                resolve_planning_scope,
                should_reopen_planning_agentic,
                message_has_vcenter_intent,
            )
            _clarify_pending = has_planning_clarification_pending(session_id, platform="unified")
            _has_episode = has_session_episode(session_id=session_id, platform="unified")
            _route = route_unified(
                message,
                is_followup=_is_followup,
                has_episode=_has_episode,
                clarification_pending=_clarify_pending,
                skip_ctx=skip_ctx,
            )
            logger.info(
                "[UnifiedChat] route mode=%s reason=%s domains=%s complexity=%s",
                _route.mode, _route.reason, sorted(_route.domains), _route.complexity,
            )

            wants_openshift = _route.wants_openshift
            linux_specific = _route.linux_specific
            windows_specific = _route.windows_specific
            wants_linux = _route.wants_linux
            wants_windows = _route.wants_windows

            # Planlama: belirsiz kapsam → seçenek sor (tool/collect yok)
            if _route.mode == "planning_clarify":
                clarify = build_planning_clarification()
                answer_text = clarify["text"]
                yield _sse({"phase": "answering"})
                yield _sse({
                    "type": "clarify",
                    "options": clarify["options"],
                })
                _timing.note_ttft()
                for i in range(0, len(answer_text), 8):
                    yield _sse({"token": answer_text[i:i + 8]})
                db.add(ChatMessage(session_id=session_id, role="assistant", content=answer_text))
                s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s:
                    s.updated_at = datetime.now(timezone.utc)
                db.commit()
                set_planning_clarification_pending(session_id, platform="unified")
                _timing.finish(
                    cache_hit=False,
                    extra={
                        "path": "planning_clarify",
                        "route": _route.mode,
                        "route_reason": _route.reason,
                        "L": 0,
                        "W": 0,
                    },
                )
                yield _sse({"done": True, "session_id": session_id})
                return

            from app.services.linux_chat_intent import (
                is_fleet_inventory_query,
                is_inventory_status_query,
                format_fleet_inventory_answer,
            )
            if is_inventory_status_query(message) or is_fleet_inventory_query(message):
                from app.services.infra_summary import build_infra_overview_text
                ml = (message or "").lower()
                linux_only = any(k in ml for k in ("linux", "rhel", "centos", "ubuntu", "debian"))
                win_only = any(k in ml for k in ("windows", "winrm"))
                if is_inventory_status_query(message):
                    plat = None
                    if linux_only and not win_only:
                        plat = "linux"
                    elif win_only and not linux_only:
                        plat = "windows"
                    answer_text = build_infra_overview_text(db, platform=plat)
                else:
                    if win_only and not linux_only:
                        servers = _windows_ai_ready_servers(db)
                        title = "Windows sunucu envanteri (kayıtlı)"
                    else:
                        servers = _linux_ai_ready_servers(db)
                        title = "Linux sunucu envanteri (kayıtlı)"
                    answer_text = format_fleet_inventory_answer(servers, title=title)
                logger.info(
                    "[UnifiedChat] inventory fast-path summary=%s linux_only=%s win_only=%s",
                    is_inventory_status_query(message), linux_only, win_only,
                )
                yield _sse({"phase": "answering"})
                _timing.note_ttft()
                for i in range(0, len(answer_text or ""), 8):
                    yield _sse({"token": answer_text[i:i + 8]})
                db.add(ChatMessage(session_id=session_id, role="assistant", content=answer_text or ""))
                s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if s:
                    s.updated_at = datetime.now(timezone.utc)
                db.commit()
                _timing.finish(cache_hit=False, extra={"path": "inventory"})
                yield _sse({"done": True, "session_id": session_id})
                return

            # Kullanıcı 1/2/3 veya kapsam seçtiyse pending temizle
            if resolve_planning_scope(message):
                clear_planning_clarification_pending(session_id, platform="unified")

            linux_servers = _linux_ai_ready_servers(db)
            windows_servers = _windows_ai_ready_servers(db)

            # Mesajda açıkça belirtilen sunucu varsa sadece onu hedefle (daha hızlı ve odaklı).
            # chat.py'deki _servers_mentioned_in_message'ı kullanıyoruz: sadece `name` +
            # `ip_address` substring eşleşmesi (eski kod) `hostname`'i hiç kontrol etmiyordu ve
            # kelime sınırı olmadan substring eşleştiği için hem yanlış eşleşme hem de
            # (hostname farklıysa) HİÇ eşleşmeme riski vardı — bu durumda linux_targets sessizce
            # TÜM filoya düşüp (bkz. aşağıdaki `or`) geniş filolarda zaman aşımına yol açıyordu.
            from app.api.chat import _servers_mentioned_in_message
            from app.services.chat_fleet_policy import (
                apply_live_collect_policy,
                inventory_lines_for_prompt,
            )
            mentioned = _servers_mentioned_in_message(db, message)
            linux_mentioned = [s for s in mentioned if not is_windows_server(s)]
            windows_mentioned = [s for s in mentioned if is_windows_server(s)]

            # Unified'da UI sunucu seçimi yok — yalnızca mention veya filo/karşılaştır kelimesi
            # canlı collect açar; aksi halde DB envanter + yönlendirme (Dalga 1 TTFT).
            linux_targets, linux_fleet_note, _lx_live = apply_live_collect_policy(
                linux_servers,
                message=message,
                has_explicit_selection=False,
                mentioned=linux_mentioned,
            )
            windows_targets, windows_fleet_note, _win_live = apply_live_collect_policy(
                windows_servers,
                message=message,
                has_explicit_selection=False,
                mentioned=windows_mentioned,
            )
            fleet_notes = [n for n in (linux_fleet_note, windows_fleet_note) if n]
            # Aynı UNSELECTED_LIVE_HINT iki kez eklenmesin
            if len(fleet_notes) == 2 and fleet_notes[0] == fleet_notes[1]:
                fleet_notes = [fleet_notes[0]]

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

            # Dalga 3: knowledge/simple → fast; live/planning → strong (UI seçimi strong'da korunur)
            _requested_model = request.model or get_active_model(db)
            _tier = (
                "fast"
                if (_route.mode == "knowledge" or _route.complexity == "simple")
                else "strong"
            )
            model, _model_tier = llm_gateway.resolve_model_for_tier(_tier, _requested_model)
            provider = _detect_provider(model)
            logger.info(
                "[UnifiedChat] model=%s tier=%s requested=%s",
                model, _model_tier, _requested_model,
            )

            inventory_context = ""
            if not linux_targets and not windows_targets and (wants_linux or wants_windows):
                parts = []
                if wants_linux and linux_servers:
                    parts.append(inventory_lines_for_prompt(linux_servers))
                if wants_windows and windows_servers:
                    parts.append(inventory_lines_for_prompt(windows_servers))
                inventory_context = "\n\n".join(parts)

            # ── Collect XOR agentic (path policy) ─────────────────────────
            from app.services import runtime_settings
            from app.services.chat_path_policy import resolve_live_path, has_session_episode
            _uses_external_api = (
                (provider == "groq" and bool(settings.GROQ_API_KEY)) or
                (provider == "openai" and bool(settings.OPENAI_API_KEY)) or
                (provider == "openrouter" and bool(settings.OPENROUTER_API_KEY))
            )
            _agentic_ok = (
                (not _uses_external_api)
                and (not skip_ctx)
                and runtime_settings.get_bool("unified_chat_agentic_mode")
                and _route.need_live
            )
            _wants_fixed = bool(
                (wants_linux and linux_targets) or (wants_windows and windows_targets)
            )
            _has_targets = bool(linux_targets or windows_targets)
            _clarify_pending = has_planning_clarification_pending(session_id, platform="unified")
            _live_path = resolve_live_path(
                message,
                agentic_enabled=_agentic_ok,
                wants_fixed_collect=_wants_fixed,
                has_live_targets=_has_targets,
                is_followup=_is_followup,
                has_episode=has_session_episode(session_id=session_id, platform="unified"),
                allow_agentic_without_collect=(
                    _route.mode == "planning_agentic"
                    or should_reopen_planning_agentic(
                        message,
                        wants_openshift=wants_openshift,
                        has_episode=has_session_episode(session_id=session_id, platform="unified"),
                        clarification_pending=_clarify_pending,
                        is_followup=_is_followup,
                    )
                    or bool(wants_openshift)
                    or message_has_vcenter_intent(message)
                ),
            )
            # Router knowledge → path ile hizala
            if _route.mode == "knowledge" and _live_path.reason != "knowledge_only":
                from app.services.chat_path_policy import LivePathDecision
                _live_path = LivePathDecision(
                    run_fixed_collect=False,
                    run_agentic=False,
                    is_deep=False,
                    reason="knowledge_only",
                )
            logger.info(
                "[UnifiedChat] live_path reason=%s collect=%s agentic=%s L=%s W=%s route=%s",
                _live_path.reason, _live_path.run_fixed_collect, _live_path.run_agentic,
                len(linux_targets), len(windows_targets), _route.mode,
            )

            async def _collect_linux():
                if not (wants_linux and linux_targets and _live_path.run_fixed_collect):
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
                if not (wants_windows and windows_targets and _live_path.run_fixed_collect):
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
                if request.use_rag is False or not _route.need_rag:
                    return {}
                try:
                    from app.services.rag_service import get_rag_context_for_message
                    return await get_rag_context_for_message(message)
                except Exception:
                    return {}

            # Dalga 3: canlı collect bitince ilerle; RAG best-effort
            from app.services.chat_obs import await_live_then_rag
            linux_task = _asyncio.ensure_future(_collect_linux())
            windows_task = _asyncio.ensure_future(_collect_windows())
            rag_task = _asyncio.ensure_future(_collect_rag())
            live_results, rag_ctx = await await_live_then_rag(
                [linux_task, windows_task],
                rag_task,
                live_timeout=context_timeout + 3.0,
            )
            linux_ctx = live_results[0] if isinstance(live_results[0], str) else ""
            windows_ctx = live_results[1] if isinstance(live_results[1], str) else ""
            rag_ctx = rag_ctx if isinstance(rag_ctx, dict) else {}
            _timing.mark("collect_end")

            context_parts = [_infra_overview(db)]
            for _fn in fleet_notes:
                context_parts.append(_fn)
            if inventory_context and not linux_ctx and not windows_ctx:
                context_parts.append(inventory_context)
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
            if rag_ctx.get("metrics"):
                context_parts.append("METRIK ACIKLAMALARI:\n" + rag_ctx["metrics"].strip())
            if rag_ctx.get("knowledge"):
                context_parts.append("BILGI BANKASI / RAG:\n" + rag_ctx["knowledge"].strip())
            context_str = "\n\n".join(context_parts)

            try:
                from app.services.assistant_playbooks import append_playbook_to_context
                context_str = append_playbook_to_context(
                    db, context_str, platform="unified", question=message,
                )
            except Exception:
                pass

            try:
                from app.services.episode_memory import append_episode_to_context
                context_str = append_episode_to_context(
                    context_str, session_id=session_id, platform="unified",
                )
            except Exception:
                pass

            coll_lines = []
            if linux_ctx:
                coll_lines.append(f"LINUX: {len(linux_targets)} sunucudan canlı veri toplandı.")
            elif wants_linux and linux_targets:
                coll_lines.append("LINUX: Bu sorgu için canlı veri toplanamadı (zaman aşımı/bağlantı).")
            elif wants_linux and not linux_targets:
                coll_lines.append(
                    "LINUX: Canlı SSH yok (hedef seçilmedi / filo kelimesi yok). "
                    "DB envanter kullanıldı; sunucu adı veya 'filo/karşılaştır' deyin."
                )
            if windows_ctx:
                coll_lines.append(f"WINDOWS: {len(windows_targets)} sunucudan canlı veri toplandı.")
            elif wants_windows and windows_targets:
                coll_lines.append("WINDOWS: Bu sorgu için canlı veri toplanamadı (zaman aşımı/bağlantı).")
            elif wants_windows and not windows_targets:
                coll_lines.append(
                    "WINDOWS: Canlı WinRM yok (hedef seçilmedi / filo kelimesi yok). "
                    "DB envanter kullanıldı; sunucu adı veya 'filo/karşılaştır' deyin."
                )
            collection_summary = "\n".join(coll_lines)

            # ── Agentic READ_ONLY tool-calling (Dalga 2 XOR) ──────────────
            # Yalnızca yerel Ollama / uzak OpenAI-uyumlu gateway (llm_gateway) yolunda
            # çalışır — groq/openai/openrouter doğrudan entegrasyonları bu döngüyü
            # desteklemez. Collect ile birlikte yalnızca derin yol / force_both.
            if _live_path.run_agentic:
                yield _sse({"phase": "tools"})
                _timing.mark("agentic_start")
                try:
                    from app.services.unified_tool_chat import run_read_only_tool_loop
                    from app.services.agent.tools import domains_for_platform
                    from app.services.chat_planning_intent import (
                        planning_agentic_limits,
                        planning_tool_domains,
                        message_has_vcenter_intent,
                        is_depth_followup,
                        resolve_planning_scope,
                        PLANNING_CLARIFY_OPTIONS,
                    )
                    max_tool_steps = runtime_settings.get_int("unified_chat_max_tool_steps")
                    _depth = is_depth_followup(message)
                    _planning, _plan_steps, _stop_after = planning_agentic_limits(
                        message, depth=_depth,
                    )
                    if _planning:
                        max_tool_steps = _plan_steps
                    # Kısa "1"/"2"/"3" seçimini araç döngüsü için zenginleştir
                    agentic_user_message = message
                    _scope = resolve_planning_scope(message)
                    if _scope and len((message or "").strip()) <= 24:
                        for _opt in PLANNING_CLARIFY_OPTIONS:
                            if _opt["id"] == _scope:
                                agentic_user_message = _opt["prompt"]
                                break
                    tool_server_lines = []
                    for _s in linux_targets:
                        tool_server_lines.append(f"- {_s.name} ({_s.ip_address}) OS={_s.os_type or _s.os_version or 'Linux'} bağlantı=SSH")
                    for _s in windows_targets:
                        tool_server_lines.append(f"- {_s.name} ({_s.ip_address}) OS={_s.os_type or 'Windows'} bağlantı=WinRM")
                    try:
                        from app.models.openshift import OpenShiftCluster
                        for _c in db.query(OpenShiftCluster).all():
                            tool_server_lines.append(f"- OpenShift cluster: {_c.name}")
                    except Exception:
                        pass
                    # Migrasyon/planlama: vCenter/hypervisor envanterini tool özetine ekle
                    if _planning or message_has_vcenter_intent(message) or wants_openshift:
                        try:
                            from app.models.hypervisor import Hypervisor
                            for _h in db.query(Hypervisor).limit(40).all():
                                hname = getattr(_h, "name", None) or "?"
                                htype = getattr(_h, "type", None) or getattr(_h, "hypervisor_type", None) or "hv"
                                tool_server_lines.append(f"- Hypervisor: {hname} ({htype})")
                        except Exception:
                            pass
                    tool_server_summary = "\n".join(tool_server_lines)
                    # Domain: planlama/vCenter+OCP → vcenter+openshift+infra (Linux SSH kapalı)
                    # Domain: router kararı öncelikli
                    tool_domains = _route.domains if _route.domains else None
                    if not tool_domains:
                        tool_domains = planning_tool_domains(
                            message,
                            wants_openshift=wants_openshift,
                            linux_specific=linux_specific,
                            windows_specific=windows_specific,
                        )
                    if tool_domains is None:
                        if wants_openshift and not linux_specific and not windows_specific:
                            tool_domains = domains_for_platform("openshift")
                        elif (wants_linux or wants_windows) and not wants_openshift:
                            dom = set()
                            if wants_linux:
                                dom |= {"linux", "infra"}
                            if wants_windows:
                                dom |= {"windows", "infra"}
                            tool_domains = frozenset(dom) if dom else None

                    logger.info(
                        "[UnifiedChat] agentic planning=%s steps=%s stop_after=%s domains=%s",
                        _planning, max_tool_steps, _stop_after if _planning else None,
                        sorted(tool_domains) if tool_domains else "all",
                    )

                    loop = _asyncio.get_event_loop()
                    gen = run_read_only_tool_loop(
                        db, model, agentic_user_message, context_str, tool_server_summary,
                        max_steps=max_tool_steps,
                        domains=tool_domains,
                        platform="unified",
                        stop_after_tools=_stop_after if _planning else None,
                        planning_mode=_planning,
                        planning_depth=_depth,
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
                                logger.warning(f"[UnifiedChat] agentic tool loop hatası: {item.get('detail')}")
                            break

                    if tool_context_text:
                        context_str = context_str + "\n\nARAÇ SONUÇLARI (bu turda modelin kendi kararıyla çalıştırdığı ek SSH/canlı sorgular):\n" + tool_context_text
                except Exception as e:
                    logger.warning(f"[UnifiedChat] agentic tool loop devre dışı bırakıldı: {e}")
                _timing.mark("agentic_end")

            try:
                from app.services.episode_memory import save_episode, summarize_live_context
                live_bits = []
                if linux_ctx:
                    live_bits.append(linux_ctx if isinstance(linux_ctx, str) else str(linux_ctx))
                if windows_ctx:
                    live_bits.append(windows_ctx if isinstance(windows_ctx, str) else str(windows_ctx))
                if "ARAÇ SONUÇLARI" in (context_str or ""):
                    live_bits.append(context_str.split("ARAÇ SONUÇLARI", 1)[-1][:2000])
                summary = summarize_live_context("\n".join(live_bits))
                if summary:
                    names = [s.name for s in (linux_targets or [])] + [s.name for s in (windows_targets or [])]
                    save_episode(
                        session_id=session_id,
                        platform="unified",
                        summary=summary,
                        server_names=names or None,
                    )
            except Exception:
                pass

            prompt = _build_prompt(message, context_str, collection_summary, history_block)

            yield _sse({"phase": "answering"})
            full_response = ""
            _ttft_sent = False

            async with httpx.AsyncClient(timeout=180.0) as client:
                if provider == "groq" and settings.GROQ_API_KEY:
                    async for token in _stream_external_openai(client, settings.GROQ_API_URL, settings.GROQ_API_KEY, model, prompt):
                        full_response += token
                        if not _ttft_sent and token:
                            _timing.note_ttft()
                            _ttft_sent = True
                        yield _sse({"token": token})
                elif provider == "openai" and settings.OPENAI_API_KEY:
                    async for token in _stream_external_openai(client, settings.OPENAI_API_URL, settings.OPENAI_API_KEY, model, prompt):
                        full_response += token
                        if not _ttft_sent and token:
                            _timing.note_ttft()
                            _ttft_sent = True
                        yield _sse({"token": token})
                elif provider == "openrouter" and settings.OPENROUTER_API_KEY:
                    async for token in _stream_external_openai(
                        client, settings.OPENROUTER_API_URL, settings.OPENROUTER_API_KEY, model, prompt,
                        extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"}
                    ):
                        full_response += token
                        if not _ttft_sent and token:
                            _timing.note_ttft()
                            _ttft_sent = True
                        yield _sse({"token": token})
                else:
                    async for chunk in llm_gateway.stream_generate(client, model=model, prompt=prompt):
                        if chunk.get("error"):
                            yield _sse({"error": chunk["error"]})
                            return
                        token = chunk.get("response", "")
                        if token:
                            full_response += token
                            if not _ttft_sent:
                                _timing.note_ttft()
                                _ttft_sent = True
                            yield _sse({"token": token})
                        if chunk.get("done"):
                            break

            db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response or "(yanıt alınamadı)"))
            s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if s:
                s.updated_at = datetime.now(timezone.utc)
            db.commit()

            if full_response and not linux_ctx and not windows_ctx and not _is_followup:
                save_to_cache(db, message, full_response, cache_key_ids, platform="unified")

            _timing.finish(
                cache_hit=False,
                extra={
                    "path": getattr(_live_path, "reason", ""),
                    "route": getattr(_route, "mode", ""),
                    "route_reason": getattr(_route, "reason", ""),
                    "model_tier": locals().get("_model_tier", ""),
                    "L": len(linux_targets),
                    "W": len(windows_targets),
                },
            )
            yield _sse({"done": True, "session_id": session_id})

        except Exception as e:
            logger.error(f"Unified chat stream error: {e}", exc_info=True)
            yield _sse({"error": str(e)})
        finally:
            try:
                _tok = locals().get("_fleet_scan_token")
                if _tok is not None:
                    from app.services.chat_full_scan_policy import reset_request_fleet_cap
                    reset_request_fleet_cap(_tok)
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
