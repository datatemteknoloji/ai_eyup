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
from app.core.config import settings, get_active_model, remote_llm_enabled
from app.models.server import Server
from app.models.chat_session import ChatSession, ChatMessage
from app.models.event import SystemEvent
from app.services.platform_scope import is_windows_server
from app.services import llm_gateway

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
    'kaynak', 'tüket', 'tuket', 'tüketim', 'tuketim',
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
                   winrm_server_count: int, selected_server_names: List[str],
                   history_block: str = "") -> str:
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
        "Sen 15+ yillik deneyime sahip kıdemli bir",
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
        "",
        "ONEMLI: Kullaniciya ASLA 'bunu su komutla siz kontrol edebilirsiniz' / 'asagidaki",
        "yontemleri kullanarak bulabilirsiniz' seklinde bir KILAVUZ/MANUEL TALIMAT LISTESI verme.",
        "Sistem WinRM ile komutu ZATEN calistirabiliyor — BAGLAM'da ilgili veri yoksa bu senin",
        "o komutu calistirmadigin anlamina gelir, kullanicinin gitmesi degil. Bu durumda sadece",
        "'Bu bilgi mevcut taramada toplanmadi.' de; kullaniciyi kendi basina komut calistirmaya",
        "yonlendirme.",
    ])

    rules = NL.join([
        "YANIT KURALLARI:",
        "0. ONCEKI KONUSMA bolumu varsa bu bir sohbetin parcasidir — takip sorularini",
        "   ('peki disk?', 'o sunucuda ise nasil?' gibi) ONCEKI KONUSMA'ya bakarak hangi",
        "   sunucu/konudan bahsedildigini cikararak yanitla. Guncel veri icin her zaman",
        "   BAGLAM bolumunu esas al — gecmisteki eski degerleri guncelmis gibi tekrar etme.",
        "1. BAGLAM bolumundeki GERCEK veriyi once kullan — kendi bilginle asla tahmin yapma",
        "1b. ONCEDEN OGRENILMIS BILGILER sadece canli veride o bilgi yoksa kullanilir; kullanirken",
        "    '(onceden ogrenilmis, X once dogrulandi)' diye belirt. Celiski varsa canli veri kazanir.",
        "1c. 'Hangi uygulamalar/veritabanlari calisiyor' gibi sorularda TESPIT EDILEN UYGULAMALAR",
        "    bolumunu kullan (otomatik periyodik tarama) — bos ise 'uygulama taramasi henuz yapilmadi' de.",
        "2. Baglam bos veya yetersizse: 'Bu sunucu icin WinRM verisi alinamadi (baglanamadi veya zaman asimi).' de.",
        "   ASLA 'tekrar deneniyor' veya 'bekleniyor' deme — bu sistem otomatik retry yapmaz.",
        "3. ASLA 'WinRM yapamam', 'dogrudan baglanamam', 'veri tabanindan bakiyorum' yazma.",
        "4. Tablo istenirse Markdown tablo kullan (| kolon | kolon |)",
        "5. Turkce yanitla",
        "5b. YANIT UZUNLUGU — VARSAYILAN KISA: Varsayilan olarak KISA, SADE ve NET cevap ver.",
        "    Basit/dogrudan bir soruya 1-3 cumlelik dogrudan cevap yeterlidir — gereksiz giris",
        "    cumlesi veya istenmeyen ek yorum ekleme. Kullanici acikca 'detayli anlat',",
        "    'derinlemesine incele', 'kok neden analizi yap' gibi DAHA FAZLA DETAY istemedikce",
        "    asagidaki UZMAN YANIT TARZI'ndaki kok-neden/tani/adim/risk sablonunu HER soruya",
        "    zorla uygulama.",
        "6. Veri varsa asla 'bilmiyorum' ya da 'emin degilim' deme — veriyi yorumla",
        "",
        "UZMAN YANIT TARZI (SADECE ariza/performans/guvenlik gibi kok-neden gerektiren",
        "sorularda veya kullanici acikca detay istediginde uygula — basit sorularda ATLA):",
        "7. Boyle bir soruda bir kıdemli admin gibi ele al:",
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
    if history_block:
        prompt_parts.append("ONCEKI KONUSMA (bu oturumdaki son mesajlar, sadece baglam/niyet icin):\n" + history_block)
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
        from app.services.chat_history import title_from_message
        title = title_from_message(message)
        session = ChatSession(title=title, server_ids=request.server_ids or [], category=CATEGORY)
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

    from app.services.chat_history import fetch_recent_history, format_history_block
    history_block = format_history_block(fetch_recent_history(db, session_id, limit=8))

    all_windows_servers = _get_windows_servers(db)
    selected_servers: List[Server] = []
    has_explicit = bool(request.server_ids or request.server_id)
    if request.server_ids:
        selected_servers = [s for s in all_windows_servers if s.id in request.server_ids]
    elif request.server_id:
        selected_servers = [s for s in all_windows_servers if s.id == request.server_id]

    mentioned: List[Server] = []
    if not has_explicit:
        ml_srv = message.lower()
        for s in all_windows_servers:
            if (s.name and s.name.lower() in ml_srv) or (s.ip_address and s.ip_address in message):
                mentioned.append(s)

    from app.services.chat_fleet_policy import (
        apply_live_collect_policy,
        inventory_lines_for_prompt,
    )
    inventory_servers = (
        list(selected_servers) if has_explicit and selected_servers
        else list(all_windows_servers)
    )
    live_targets, fleet_note, _allow_live = apply_live_collect_policy(
        selected_servers if has_explicit else all_windows_servers,
        message=message,
        has_explicit_selection=has_explicit and bool(selected_servers),
        mentioned=mentioned if not has_explicit else None,
    )
    selected_servers = live_targets

    ml = message.lower()
    needs_winrm = any(k in ml for k in _ALL_WINRM_KEYWORDS) and not request.skip_server_context

    db.add(ChatMessage(session_id=session_id, role="user", content=message))
    db.commit()

    winrm_ctx = ""
    if needs_winrm and selected_servers:
        def _collect_winrm_ctx() -> str:
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
                try:
                    from app.services.fact_learning import extract_and_store_facts
                    extract_and_store_facts(db, srv, info, platform="windows")
                except Exception:
                    pass
            return "\n\n".join(ctxs)
        try:
            # WinRM PowerShell çağrıları senkron/bloklayan I/O yapar (birden fazla
            # sunucuda kümülatif saniyeler sürebilir) — event loop'u kilitlememesi
            # için thread pool'da çalıştırılır.
            winrm_ctx = await asyncio.get_event_loop().run_in_executor(None, _collect_winrm_ctx)
        except Exception as e:
            logger.warning(f"WinRM info collect failed: {e}")

    context_parts = []
    if fleet_note:
        context_parts.append(fleet_note)
    if winrm_ctx:
        context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + winrm_ctx.strip())
    elif selected_servers:
        lines = [f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}" for s in selected_servers]
        context_parts.append("VERITABANI BILGILERI:\n" + "\n".join(lines))
    elif inventory_servers and needs_winrm:
        context_parts.append(inventory_lines_for_prompt(inventory_servers))

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
                    "ONCEDEN OGRENILMIS BILGILER (yapisal, gecmis taramalardan — canli veriyle "
                    "celisirse canli veriyi esas al, kullanirken 'onceden ogrenilmis (X once "
                    "dogrulandi)' diye belirt):\n" + "\n\n".join(_facts_blocks)
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
                    "IIS, MSSQL, PostgreSQL vb.; celisirse canli veriyi esas al):\n"
                    + "\n\n".join(_apps_blocks)
                )
        except Exception:
            pass

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
            if rag_ctx.get("metrics"):
                context_parts.append("METRİK AÇIKLAMALARI:\n" + rag_ctx["metrics"].strip())
            if rag_ctx.get("knowledge"):
                context_parts.append(
                    "BİLGİ BANKASI / RAG:\n" + rag_ctx["knowledge"].strip()
                )
        except Exception as rag_err:
            logger.debug(f"RAG context atlanıyor: {rag_err}")

    context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."
    prompt = _build_prompt(
        message=message,
        context_str=context_str,
        winrm_collected=bool(winrm_ctx),
        winrm_server_count=len(selected_servers) if winrm_ctx else 0,
        selected_server_names=[s.name for s in selected_servers],
        history_block=history_block,
    )

    try:
        model = request.model or get_active_model(db)
        async with httpx.AsyncClient(timeout=120.0) as client:
            data = await llm_gateway.generate_async(client, model=model, prompt=prompt)
            if not data.get("error"):
                ai_response = data.get("response", "Yanıt alınamadı")
            else:
                ai_response = f"AI servisi yanıt veremedi: {data.get('error')}"
    except Exception as e:
        logger.error(f"LLM error: {e}")
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
                from app.services.chat_history import title_from_message
                title = title_from_message(message)
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
                from app.services.chat_history import maybe_set_session_title
                if maybe_set_session_title(session, message):
                    db.commit()

            yield _sse({"session_id": session_id, "start": True})

            from app.services.chat_obs import ChatTiming
            _timing = ChatTiming(platform="windows")

            # Tam filo onayı — chitchat'ten ÖNCE (ok/tamam çakışmasın)
            from app.services.chat_full_scan_policy import (
                resolve_full_scan_turn,
                set_request_fleet_cap,
                reset_request_fleet_cap,
                get_hard_max_fleet_cap,
                get_full_scan_pending,
            )
            _fs = resolve_full_scan_turn(
                db, session_id=session_id, message=message, platform="windows",
            )
            if _fs.get("action") == "clarify":
                clarify = _fs.get("clarification") or ""
                yield _sse({"phase": "answering"})
                yield _sse({"needs_confirmation": True, "intent": "full_scan_clarify"})
                for i in range(0, len(clarify), 8):
                    yield _sse({"token": clarify[i:i + 8]})
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
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
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                db.add(ChatMessage(
                    session_id=session_id, role="assistant", content=decline,
                    meta={"intents": ["full_scan_declined"]},
                ))
                db.commit()
                yield _sse({"done": True, "session_id": session_id})
                return

            from app.services.chat_chitchat_policy import canned_chitchat_answer
            _pending_fs = get_full_scan_pending(session_id, platform="windows")
            _cc = None if (_fs.get("full_scan") or _pending_fs) else canned_chitchat_answer(
                message, platform="windows",
            )
            if _cc:
                yield _sse({"phase": "answering"})
                yield _sse({"intent": "chitchat"})
                _timing.note_ttft()
                for i in range(0, len(_cc), 8):
                    yield _sse({"token": _cc[i:i + 8]})
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
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
                    "[WindowsChat] full_scan CONFIRMED session=%s items≈%s",
                    session_id, _fs.get("item_count"),
                )

            from app.services.chat_history import (
                fetch_recent_history, format_history_block, has_prior_messages,
            )
            from app.services.chat_cache_service import get_cached_answer, save_to_cache

            _is_followup = has_prior_messages(db, session_id)
            history_block = format_history_block(fetch_recent_history(db, session_id, limit=8)) if _is_followup else ""

            # ── Sunucu seçimi (Dalga 1 filo politikası) ───────────────────
            all_windows_servers = _get_windows_servers(db)
            selected_servers: List[Server] = []
            has_explicit = bool(request.server_ids or request.server_id)
            if request.server_ids:
                selected_servers = [s for s in all_windows_servers if s.id in request.server_ids]
            elif request.server_id:
                selected_servers = [s for s in all_windows_servers if s.id == request.server_id]

            mentioned: List[Server] = []
            if not has_explicit:
                ml_srv = message.lower()
                for s in all_windows_servers:
                    if (s.name and s.name.lower() in ml_srv) or (s.ip_address and s.ip_address in message):
                        mentioned.append(s)

            from app.services.chat_fleet_policy import (
                apply_live_collect_policy,
                inventory_lines_for_prompt,
            )
            inventory_servers = (
                list(selected_servers) if has_explicit and selected_servers
                else list(all_windows_servers)
            )
            live_targets, fleet_note, _allow_live = apply_live_collect_policy(
                selected_servers if has_explicit else all_windows_servers,
                message=message,
                has_explicit_selection=has_explicit and bool(selected_servers),
                mentioned=mentioned if not has_explicit else None,
            )
            selected_servers = live_targets

            cache_ids = [s.id for s in selected_servers] if has_explicit else []
            cached = None if _is_followup else get_cached_answer(
                db, message, cache_ids, platform="windows",
            )
            _timing.mark("cache")
            if cached:
                db.add(ChatMessage(session_id=session_id, role="user", content=message))
                db.commit()
                answer = cached["answer"]
                yield _sse({"phase": "answering"})
                _timing.note_ttft()
                for i in range(0, len(answer), 8):
                    yield _sse({"token": answer[i:i + 8]})
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

            ml = message.lower()
            needs_winrm = any(k in ml for k in _ALL_WINRM_KEYWORDS) and not request.skip_server_context
            context_timeout = min(60.0, max(25.0, 15.0 + 1.0 * len(selected_servers)))

            server_context = ""
            if selected_servers:
                lines = [
                    f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}"
                    for s in selected_servers
                ]
                server_context = "Seçili sunucular:\n" + "\n".join(lines)
            elif inventory_servers:
                server_context = inventory_lines_for_prompt(inventory_servers)
            if fleet_note:
                server_context = (
                    (server_context + "\n\n" + fleet_note).strip()
                    if server_context
                    else fleet_note
                )

            # ── Dalga 2: collect XOR agentic ──────────────────────────────
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
                and (not request.skip_server_context)
                and _rts.get_bool("windows_chat_agentic_mode")
            )
            _live_path = resolve_live_path(
                message,
                agentic_enabled=_agentic_ok,
                wants_fixed_collect=bool(needs_winrm),
                has_live_targets=bool(selected_servers),
                is_followup=_is_followup,
                has_episode=has_session_episode(session_id=session_id, platform="windows"),
            )
            logger.info(
                "[WindowsChat] live_path reason=%s collect=%s agentic=%s targets=%s",
                _live_path.reason, _live_path.run_fixed_collect, _live_path.run_agentic,
                len(selected_servers),
            )

            async def _collect_winrm():
                if not needs_winrm or not _live_path.run_fixed_collect:
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
                            return build_server_context(srv.name, srv.ip_address or "-", {"error": "WinRM kimlik bilgisi/bağlantı yok"}), None
                        info = collect_server_info(client, groups)
                        return build_server_context(srv.name, srv.ip_address or "-", info), info

                    tasks = [loop.run_in_executor(None, _collect_one, srv) for srv in selected_servers]
                    done, pending = await asyncio.wait(tasks, timeout=context_timeout)
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
                                        extract_and_store_facts(db, selected_servers[i], info, platform="windows")
                                    except Exception:
                                        pass
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
                from app.services.chat_obs import await_live_then_rag
                winrm_task = asyncio.ensure_future(_collect_winrm())
                rag_task = asyncio.ensure_future(_collect_rag())
                live_results, rag_ctx = await await_live_then_rag(
                    [winrm_task],
                    rag_task,
                    live_timeout=context_timeout + 2.0,
                )
                winrm_ctx = live_results[0] if isinstance(live_results[0], str) else ""
                rag_ctx = rag_ctx if isinstance(rag_ctx, dict) else {}
            except Exception:
                winrm_ctx, rag_ctx = "", {}
            _timing.mark("collect_end")

            event_ctx = _windows_event_context(db, selected_servers)

            context_parts = []
            if winrm_ctx:
                context_parts.append("SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + winrm_ctx.strip())
            elif server_context:
                context_parts.append("VERITABANI BILGILERI:\n" + server_context.strip())

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
                            "ONCEDEN OGRENILMIS BILGILER (yapisal, gecmis taramalardan — canli veriyle "
                            "celisirse canli veriyi esas al, kullanirken 'onceden ogrenilmis (X once "
                            "dogrulandi)' diye belirt):\n" + "\n\n".join(_facts_blocks)
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
                            "IIS, MSSQL, PostgreSQL vb.; celisirse canli veriyi esas al):\n"
                            + "\n\n".join(_apps_blocks)
                        )
                except Exception:
                    pass

            if event_ctx:
                context_parts.append(event_ctx)
            if rag_ctx.get("runbook"):
                context_parts.append("RUNBOOK:\n" + rag_ctx["runbook"].strip())
            if rag_ctx.get("incidents"):
                context_parts.append("BENZER OLAYLAR:\n" + rag_ctx["incidents"].strip())
            if rag_ctx.get("metrics"):
                context_parts.append("METRIK ACIKLAMALARI:\n" + rag_ctx["metrics"].strip())
            if rag_ctx.get("knowledge"):
                context_parts.append("BILGI BANKASI / RAG:\n" + rag_ctx["knowledge"].strip())

            context_str = "\n\n".join(context_parts) if context_parts else "Bu sorgu için bağlam verisi toplanmadı."

            try:
                from app.services.assistant_playbooks import append_playbook_to_context
                context_str = append_playbook_to_context(
                    db, context_str, platform="windows", question=message,
                )
            except Exception:
                pass

            try:
                from app.services.episode_memory import append_episode_to_context
                context_str = append_episode_to_context(
                    context_str, session_id=session_id, platform="windows",
                )
            except Exception:
                pass

            # ── Agentic READ_ONLY WinRM (Dalga 2 XOR) ─────────────────────
            if _live_path.run_agentic:
                yield _sse({"phase": "tools"})
                _timing.mark("agentic_start")
                try:
                    from app.services.unified_tool_chat import run_read_only_tool_loop
                    from app.services.agent.tools import domains_for_platform
                    max_tool_steps = _rts.get_int("windows_chat_max_tool_steps")
                    tool_server_summary = "\n".join(
                        f"- {s.name} ({s.ip_address}) OS={s.os_type or s.os_version or 'Windows'} bağlantı=WinRM"
                        for s in selected_servers
                    )
                    loop = asyncio.get_event_loop()
                    gen = run_read_only_tool_loop(
                        db, model, message, context_str, tool_server_summary,
                        max_steps=max_tool_steps,
                        domains=domains_for_platform("windows"),
                        platform="windows",
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
                                logger.warning(f"[WindowsChat] agentic tool loop hatası: {item.get('detail')}")
                            break

                    if tool_context_text:
                        context_str = (
                            context_str
                            + "\n\nARAÇ SONUÇLARI (modelin çağırdığı READ_ONLY WinRM/canlı sorgular):\n"
                            + tool_context_text
                        )
                except Exception as e:
                    logger.warning(f"[WindowsChat] agentic tool loop devre dışı: {e}")
                _timing.mark("agentic_end")

            try:
                from app.services.episode_memory import save_episode, summarize_live_context
                live_bits = []
                if winrm_ctx:
                    live_bits.append(winrm_ctx if isinstance(winrm_ctx, str) else str(winrm_ctx))
                if "ARAÇ SONUÇLARI" in (context_str or ""):
                    live_bits.append(context_str.split("ARAÇ SONUÇLARI", 1)[-1][:2000])
                summary = summarize_live_context("\n".join(live_bits))
                if summary:
                    save_episode(
                        session_id=session_id,
                        platform="windows",
                        summary=summary,
                        server_names=[s.name for s in selected_servers] if selected_servers else None,
                    )
            except Exception:
                pass

            prompt = _build_prompt(
                message=message,
                context_str=context_str,
                winrm_collected=bool(winrm_ctx),
                winrm_server_count=len(selected_servers) if winrm_ctx else 0,
                selected_server_names=[s.name for s in selected_servers],
                history_block=history_block,
            )

            db.add(ChatMessage(session_id=session_id, role="user", content=message))
            db.commit()

            # model/provider yukarıda agentic için belirlendi
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
                        extra_headers={"HTTP-Referer": "https://datatem.ai", "X-Title": "datatem AI"},
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

            if full_response and not _is_followup and not needs_winrm:
                save_to_cache(db, message, full_response, cache_ids, platform="windows")

            _timing.finish(
                cache_hit=False,
                extra={"path": getattr(_live_path, "reason", ""), "targets": len(selected_servers)},
            )
            yield _sse({"done": True, "session_id": session_id})

        except Exception as e:
            logger.error(f"Windows chat stream error: {e}", exc_info=True)
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
