"""
Linux MCP endpoints used by MCP panel page.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
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
        password=cred.password,
        private_key=cred.private_key,
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
        {"name": t.get("name"), "description": t.get("description") or ""}
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
