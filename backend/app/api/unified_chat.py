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
from app.models.hypervisor import Hypervisor
from app.models.chat_session import ChatSession, ChatMessage
from app.models.credential import GlobalCredential
from app.services.platform_scope import is_windows_server, is_vm

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
    all_servers = db.query(Server).all()
    linux_all = [s for s in all_servers if not is_windows_server(s)]
    windows_all = [s for s in all_servers if is_windows_server(s)]
    linux_ai = [s for s in linux_all if s.ai_ready]
    windows_ai = [s for s in windows_all if s.ai_ready]
    vms = [s for s in all_servers if is_vm(s)]
    physical = [s for s in all_servers if not is_vm(s)]
    hypervisors = db.query(Hypervisor).all()

    lines = [
        "GENEL ENVANTER OZETI:",
        f"- Linux/Unix sunucu: {len(linux_all)} adet ({len(linux_ai)} AI Ready)",
        f"- Windows sunucu: {len(windows_all)} adet ({len(windows_ai)} AI Ready)",
        f"- Sanal makine (VM) toplam: {len(vms)} adet, fiziksel host: {len(physical)} adet",
        f"- Hypervisor/entegrasyon: {len(hypervisors)} adet"
        + (f" ({', '.join(sorted(set(h.hypervisor_type.value for h in hypervisors if h.hypervisor_type)))})" if hypervisors else ""),
    ]
    if linux_ai:
        lines.append("\nAI Ready Linux sunucular:")
        for s in linux_ai:
            lines.append(f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Linux'}, Durum={s.status}")
    if windows_ai:
        lines.append("\nAI Ready Windows sunucular:")
        for s in windows_ai:
            lines.append(f"- {s.name} ({s.ip_address}): OS={s.os_version or s.os_type or 'Windows'}, Durum={s.status}")
    if hypervisors:
        lines.append("\nHypervisorlar:")
        for h in hypervisors:
            vm_count = sum(1 for s in vms if s.hypervisor_id == h.id)
            lines.append(f"- {h.name} ({h.type or '-'}): host={h.hostname or '-'}, durum={h.status or '-'}, VM sayisi={vm_count}")
    return "\n".join(lines)


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


def _build_prompt(message: str, context_str: str, collection_summary: str) -> str:
    NL = "\n"
    identity = NL.join([
        "Sen AINE (AI Infrastructure Engine) adında, 15+ yillik deneyime sahip kıdemli bir",
        "Altyapı Mimarisin (Senior Infrastructure Architect) — Linux, Windows ve sanallaştırma",
        "(VMware/oVirt/KVM) altyapılarının TAMAMINDAN sorumlusun. Platformlar arası çapraz",
        "analiz ve karşılaştırma yapabiliyorsun (ör. 'tüm sunucularda en yüksek CPU kullanan 5 sunucu',",
        "'Linux ve Windows arasında güvenlik yaması durumu karşılaştırması', 'genel altyapı sağlık özeti').",
        "",
        "SISTEM YETENEKLERI:",
        "- Linux AI Ready sunuculara SSH ile bağlanıp gerçek komut/metrik toplayabiliyorsun",
        "- Windows AI Ready sunuculara WinRM/PowerShell ile bağlanıp gerçek veri toplayabiliyorsun",
        "- Sanallaştırma (hypervisor/VM) envanterini veritabanından özetleyebiliyorsun",
        "- Geçmiş konuşma, runbook ve incident kayıtları kullanılabiliyor",
        "",
        "ONEMLI: Asla 'SSH/WinRM yapamam' veya 'doğrudan bağlanamam' deme.",
        "Sistem bunu yapabiliyor. Veri gelmemişse toplanmamış demektir, toplanamaz değil.",
    ])

    rules = NL.join([
        "YANIT KURALLARI:",
        "1. BAĞLAM bölümündeki GERÇEK veriyi kullan — kendi bilginle asla tahmin yapma",
        "2. Platformlar arası soruda (ör. 'tüm sunucular') Linux ve Windows verilerini AYRI",
        "   bölümler halinde ama TEK bir yanıt/tablo içinde birleştir",
        "3. Tablo istenirse Markdown tablo kullan, mümkünse 'Platform' kolonu ekle (Linux/Windows)",
        "4. Türkçe yanıtla — net ve açıklayıcı yaz",
        "5. Veri eksikse hangi platform/sunucu için eksik olduğunu açıkça belirt",
        "6. Her soruyu kıdemli bir mimar gibi ele al: kök neden, tanı komutu, çözüm adımları, risk uyarısı",
    ])

    parts = [identity]
    if collection_summary:
        parts.append("TOPLAMA DURUMU:\n" + collection_summary)
    parts.append(rules)
    parts.append("BAGLAM:\n" + context_str)
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
                title = message[:50] + ("..." if len(message) > 50 else "")
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

            yield _sse({"session_id": session_id, "start": True})

            cache_key_ids: List[int] = []
            cached = get_cached_answer(db, message, cache_key_ids)
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
            wants_linux = (any(k in ml for k in _LINUX_TRIGGER) or any(k in ml for k in _GENERAL_TRIGGER)) and not skip_ctx
            wants_windows = (any(k in ml for k in _WINDOWS_TRIGGER) or any(k in ml for k in _GENERAL_TRIGGER)) and not skip_ctx

            linux_servers = _linux_ai_ready_servers(db)
            windows_servers = _windows_ai_ready_servers(db)

            # Mesajda açıkça belirtilen sunucu varsa sadece onu hedefle (daha hızlı ve odaklı)
            msg_lower_srv = ml
            linux_mentioned = [s for s in linux_servers if (s.name and s.name.lower() in msg_lower_srv) or (s.ip_address and s.ip_address in message)]
            windows_mentioned = [s for s in windows_servers if (s.name and s.name.lower() in msg_lower_srv) or (s.ip_address and s.ip_address in message)]
            linux_targets = linux_mentioned or linux_servers
            windows_targets = windows_mentioned or windows_servers

            context_timeout = min(30.0, max(15.0, 10.0 + 1.2 * (len(linux_targets) + len(windows_targets))))
            global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()

            async def _collect_linux():
                if not (wants_linux and linux_targets):
                    return ""
                try:
                    from app.services.linux_info_collector import detect_needed_groups, collect_server_info, build_server_context
                    groups = detect_needed_groups(message)
                    loop = _asyncio.get_event_loop()
                    tasks = [loop.run_in_executor(None, lambda s=srv: collect_server_info(s, groups, global_cred)) for srv in linux_targets]
                    done, pending = await _asyncio.wait(tasks, timeout=context_timeout)
                    for t in pending:
                        t.cancel()
                    ctxs = []
                    for i, t in enumerate(tasks):
                        if t in done:
                            try:
                                ctxs.append(build_server_context(linux_targets[i], t.result()))
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
                            return build_server_context(srv.name, srv.ip_address or "-", {"error": "WinRM kimlik bilgisi/bağlantı yok"})
                        info = collect_server_info(client, groups)
                        return build_server_context(srv.name, srv.ip_address or "-", info)

                    tasks = [loop.run_in_executor(None, _collect_one, srv) for srv in windows_targets]
                    done, pending = await _asyncio.wait(tasks, timeout=context_timeout)
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

            try:
                results = await _asyncio.wait_for(
                    _asyncio.gather(_collect_linux(), _collect_windows(), _collect_rag(), return_exceptions=True),
                    timeout=context_timeout + 3.0,
                )
                linux_ctx = results[0] if isinstance(results[0], str) else ""
                windows_ctx = results[1] if isinstance(results[1], str) else ""
                rag_ctx = results[2] if isinstance(results[2], dict) else {}
            except _asyncio.TimeoutError:
                linux_ctx, windows_ctx, rag_ctx = "", "", {}

            context_parts = [_infra_overview(db)]
            if linux_ctx:
                context_parts.append("LINUX SUNUCULARDAN ALINAN GERCEK VERILER (SSH):\n" + linux_ctx.strip())
            if windows_ctx:
                context_parts.append("WINDOWS SUNUCULARDAN ALINAN GERCEK VERILER (WinRM):\n" + windows_ctx.strip())
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

            prompt = _build_prompt(message, context_str, collection_summary)

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
                            done_flag = chunk.get("done", False)
                            if token:
                                full_response += token
                                yield _sse({"token": token})
                            if done_flag:
                                break

            db.add(ChatMessage(session_id=session_id, role="assistant", content=full_response or "(yanıt alınamadı)"))
            s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if s:
                s.updated_at = datetime.now(timezone.utc)
            db.commit()

            if full_response and not linux_ctx and not windows_ctx:
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
