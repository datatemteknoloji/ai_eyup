"""
Linux MCP endpoints used by MCP panel page.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_active_model, settings
from app.core.database import get_db
from app.core.encryption import decrypt_secret
from app.models.credential import GlobalCredential
from app.models.server import Server
from app.services.mcp_client import (
    BUILTIN_LINUX_TOOLS,
    McpCredential,
    call_linux_mcp_tool,
    list_linux_mcp_tools,
    run_builtin_tool,
)

router = APIRouter()


class ToolCallRequest(BaseModel):
    tool_name: str
    host: str
    arguments: Optional[Dict[str, Any]] = None


class MultiToolRequest(BaseModel):
    tool_name: str
    server_ids: List[int]
    arguments: Optional[Dict[str, Any]] = None


class AnalyzeRequest(BaseModel):
    results: List[Dict[str, Any]]   # [{server_name, tool_name, ok, result}]
    question: Optional[str] = None
    model: Optional[str] = None


def _default_credential(db: Session) -> GlobalCredential:
    cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    if not cred:
        cred = db.query(GlobalCredential).first()
    if not cred:
        raise HTTPException(status_code=400, detail="Default global SSH credential bulunamadi")
    return cred


def _to_mcp_credential(cred: GlobalCredential) -> McpCredential:
    return McpCredential(
        username=cred.username,
        password=decrypt_secret(cred.password) if cred.password else None,
        private_key=decrypt_secret(cred.private_key) if cred.private_key else None,
        port=cred.port or 22,
    )


def _pick_host_for_listing(db: Session) -> str:
    ai_ready = db.query(Server).filter(Server.ai_ready == True).all()
    for server in ai_ready:
        if server.ip_address:
            return server.ip_address
        if server.hostname:
            return server.hostname
    any_server = db.query(Server).first()
    if any_server and (any_server.ip_address or any_server.hostname):
        return any_server.ip_address or any_server.hostname
    return "127.0.0.1"


@router.get("/tools")
async def list_tools(host: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    cred = _default_credential(db)
    selected_host = host or _pick_host_for_listing(db)

    mcp_tools, warning = await list_linux_mcp_tools(selected_host, _to_mcp_credential(cred))
    normalized_mcp = [
        {
            "name": t.get("name"),
            "description": t.get("description") or "",
            "category": "mcp",
            "icon": "🔌",
            "schema": t.get("inputSchema") or t.get("input_schema"),
        }
        for t in mcp_tools
        if t.get("name")
    ]

    all_tools = BUILTIN_LINUX_TOOLS + normalized_mcp
    seen = set()
    unique_tools = []
    for tool in all_tools:
        if tool["name"] in seen:
            continue
        seen.add(tool["name"])
        unique_tools.append(tool)

    return {
        "tools": unique_tools,
        "host_used": selected_host,
        "warning": warning,
    }


@router.post("/run-multi")
async def run_multi(payload: MultiToolRequest, db: Session = Depends(get_db)):
    """Aynı aracı birden fazla sunucuda paralel çalıştırır."""
    servers = db.query(Server).filter(Server.id.in_(payload.server_ids)).all()
    if not servers:
        raise HTTPException(status_code=404, detail="Sunucu bulunamadı")
    cred = _default_credential(db)
    mcp_cred = _to_mcp_credential(cred)
    loop = asyncio.get_event_loop()

    async def _run_one(server: Server):
        host = server.ip_address or server.hostname or ""
        t0 = time.time()
        try:
            if payload.tool_name.startswith("builtin."):
                result = await loop.run_in_executor(
                    None, run_builtin_tool, host, mcp_cred, payload.tool_name
                )
            else:
                result = await call_linux_mcp_tool(
                    host, mcp_cred, payload.tool_name, payload.arguments or {}
                )
            return {
                "server_id": server.id, "server_name": server.name,
                "host": host, "ok": True, "result": result,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        except Exception as exc:
            return {
                "server_id": server.id, "server_name": server.name,
                "host": host, "ok": False, "error": str(exc),
                "elapsed_ms": int((time.time() - t0) * 1000),
            }

    results = await asyncio.gather(*[_run_one(s) for s in servers])
    return {"tool_name": payload.tool_name, "results": list(results)}


@router.post("/analyze")
async def analyze_results(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    """Çalıştırma sonuçlarını AI ile analiz eder — SSE stream döner."""

    def _extract_text(r: Dict[str, Any]) -> str:
        """Sonuçtan insan-okunur metin çıkarır."""
        if not r.get("ok"):
            return f"[HATA] {r.get('error', 'bilinmeyen hata')}"
        res = r.get("result") or {}
        stdout = res.get("stdout") or ""
        if stdout:
            return stdout[:3000]
        # MCP content array
        content = res.get("content") or []
        if isinstance(content, list):
            return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")[:3000]
        return str(res)[:2000]

    ctx_parts = []
    for r in payload.results:
        ctx_parts.append(f"--- {r.get('server_name', '?')} ---\n{_extract_text(r)}")
    context = "\n\n".join(ctx_parts)

    tool_name = (payload.results[0].get("tool_name") or "") if payload.results else ""
    question = payload.question or (
        "Bu sunucuların genel durumunu değerlendir. Dikkat edilmesi gereken "
        "sorunları, kritik değerleri ve önerileri maddeler hâlinde listele."
    )

    prompt = (
        f"Sen bir Linux sistem yönetimi ve AIOps uzmanısın.\n"
        f"Aşağıda {len(payload.results)} sunucudan alınan '{tool_name}' aracı çıktısı bulunuyor.\n\n"
        f"{context}\n\n"
        f"Soru: {question}\n\n"
        "Yanıtını Türkçe yaz. Kritik sorunları ⚠️, normal durumları ✓, "
        "önerileri 💡 işaretiyle belirt. Kısa ve eyleme geçirilebilir ol."
    )

    model = payload.model or get_active_model(db)

    async def _stream():
        import httpx
        import json
        from app.services import llm_gateway
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async for chunk in llm_gateway.stream_generate(client, model=model, prompt=prompt):
                    if chunk.get("error"):
                        yield f"data: {json.dumps({'error': chunk['error']})}\n\n"
                        return
                    yield f"data: {json.dumps(chunk)}\n\n"
                    if chunk.get("done"):
                        return
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})


@router.post("/call-tool")
async def call_tool(payload: ToolCallRequest, db: Session = Depends(get_db)):
    cred = _default_credential(db)
    mcp_cred = _to_mcp_credential(cred)

    try:
        if payload.tool_name.startswith("builtin."):
            result = run_builtin_tool(payload.host, mcp_cred, payload.tool_name)
        else:
            result = await call_linux_mcp_tool(
                payload.host,
                mcp_cred,
                payload.tool_name,
                payload.arguments or {},
            )
        return {
            "ok": True,
            "tool_name": payload.tool_name,
            "host": payload.host,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
