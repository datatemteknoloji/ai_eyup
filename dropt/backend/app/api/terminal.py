"""Browser web terminal — Paramiko interactive shell over WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import paramiko
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.core.database import engine
from app.core.security import TokenError, safe_decode_token
from app.models.job import AuditStatus
from app.models.server import TargetServer
from app.models.user import User, UserRole
from app.services.audit import write_audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/terminal", tags=["terminal"])

IDLE_SEC = 900


def _user_from_token(session: Session, token: str) -> User | None:
    try:
        payload = safe_decode_token(token)
    except TokenError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws/{server_id}")
async def terminal_ws(websocket: WebSocket, server_id: int) -> None:
    await websocket.accept()
    token = websocket.query_params.get("token") or ""
    os_user = (websocket.query_params.get("username") or "").strip()
    os_pass = websocket.query_params.get("password") or ""
    cols = int(websocket.query_params.get("cols") or 120)
    rows = int(websocket.query_params.get("rows") or 32)

    client: paramiko.SSHClient | None = None
    chan: paramiko.Channel | None = None

    with Session(engine) as session:
        user = _user_from_token(session, token)
        if user is None:
            await websocket.send_text("\r\n[portal] Oturum geçersiz\r\n")
            await websocket.close(code=4401)
            return
        server = session.get(TargetServer, server_id)
        if server is None:
            await websocket.send_text("\r\n[portal] Sunucu bulunamadı\r\n")
            await websocket.close(code=4404)
            return

        if user.role == UserRole.admin and not os_user:
            os_user = "root"
        if not os_user or not os_pass:
            await websocket.send_text("\r\n[portal] OS kullanıcı adı ve şifre gerekli\r\n")
            await websocket.close(code=4400)
            return

        write_audit(
            session,
            action="terminal.open",
            status=AuditStatus.info,
            message=f"Terminal açıldı ({os_user}@{server.hostname})",
            user_id=user.id,
            username=user.username,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            target_server_id=server.id,
            hostname=server.hostname,
            ip=server.ip,
            after_state={"os_username": os_user},
        )
        host = server.ip
        port = server.port
        hostname = server.hostname
        portal_user = user.username
        portal_role = user.role.value if hasattr(user.role, "value") else str(user.role)
        portal_uid = user.id

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        await asyncio.to_thread(
            client.connect,
            hostname=host,
            port=port,
            username=os_user,
            password=os_pass,
            timeout=20,
            allow_agent=False,
            look_for_keys=False,
            banner_timeout=20,
            auth_timeout=20,
        )
        chan = client.invoke_shell(term="xterm-256color", width=cols, height=rows)
        chan.settimeout(0.0)
        await websocket.send_text(
            f"\r\n[portal] Bağlandı: {os_user}@{hostname} — kalıcı işler için sihirbaz kullanın.\r\n"
        )
    except Exception as exc:  # noqa: BLE001
        await websocket.send_text(f"\r\n[portal] Bağlantı hatası: {exc}\r\n")
        await websocket.close(code=4502)
        with Session(engine) as session:
            write_audit(
                session,
                action="terminal.open.failed",
                status=AuditStatus.failed,
                message=str(exc)[:500],
                user_id=portal_uid,
                username=portal_user,
                role=portal_role,
                target_server_id=server_id,
                hostname=hostname,
                ip=host,
            )
        return

    async def pump_ssh() -> None:
        assert chan is not None
        while True:
            await asyncio.sleep(0.02)
            if chan.closed:
                break
            try:
                if chan.recv_ready():
                    data = chan.recv(8192)
                    if not data:
                        break
                    await websocket.send_bytes(data)
                if chan.recv_stderr_ready():
                    err = chan.recv_stderr(4096)
                    if err:
                        await websocket.send_bytes(err)
            except Exception:
                break

    ssh_task = asyncio.create_task(pump_ssh())
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=IDLE_SEC)
            except asyncio.TimeoutError:
                await websocket.send_text("\r\n[portal] Boşta kalma zaman aşımı\r\n")
                break
            if msg["type"] == "websocket.disconnect":
                break
            if msg["type"] != "websocket.receive":
                continue
            if "bytes" in msg and msg["bytes"] is not None:
                if chan and not chan.closed:
                    chan.send(msg["bytes"])
            elif "text" in msg and msg["text"] is not None:
                text = msg["text"]
                if text.startswith("{") and "resize" in text:
                    try:
                        obj: dict[str, Any] = json.loads(text)
                        if obj.get("type") == "resize" and chan:
                            chan.resize_pty(width=int(obj.get("cols") or 120), height=int(obj.get("rows") or 32))
                    except Exception:
                        pass
                elif chan and not chan.closed:
                    chan.send(text.encode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    finally:
        ssh_task.cancel()
        try:
            await ssh_task
        except Exception:
            pass
        if chan is not None:
            try:
                chan.close()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        # wipe password reference
        os_pass = ""
        with Session(engine) as session:
            write_audit(
                session,
                action="terminal.close",
                status=AuditStatus.info,
                message=f"Terminal kapandı ({os_user}@{hostname})",
                user_id=portal_uid,
                username=portal_user,
                role=portal_role,
                target_server_id=server_id,
                hostname=hostname,
                ip=host,
                after_state={"os_username": os_user},
            )
