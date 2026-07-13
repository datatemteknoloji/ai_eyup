"""
Web SSH Terminal — WebSocket üzerinden tarayıcıdan SSH bağlantısı
"""
import asyncio
import logging
import io
import paramiko
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.core.database import ThreadSessionLocal as SessionLocal
from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.ssh_connect import connect_ssh
from app.services.ssh_credentials import resolve_ssh_creds

logger = logging.getLogger(__name__)
router = APIRouter()

COLS = 220
ROWS = 50


def _get_creds(server: Server, gc: GlobalCredential | None) -> dict:
    """SSH butonu — toplu tarama ile aynı credential çözümleyici."""
    c = resolve_ssh_creds(server, global_cred=gc)
    return {
        "host": c["host"],
        "port": c["port"],
        "username": c["username"],
        "password": c["password"],
        "key": c["private_key"],
    }


def _make_ssh(creds: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if creds["key"]:
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(creds["key"]))
                break
            except Exception:
                pass

    connected = connect_ssh(
        client,
        hostname=creds["host"], username=creds["username"], port=creds["port"],
        password=creds["password"], pkey=pkey, timeout=10,
    )

    if not connected:
        raise ConnectionError("SSH kimlik bilgileriyle bağlantı kurulamadı")

    return client


@router.websocket("/ws/{server_id}")
async def ssh_terminal(websocket: WebSocket, server_id: int, token: str = ""):
    """
    WebSocket üzerinden SSH terminal.
    İstemciden gelen data → SSH stdin
    SSH stdout/stderr → istemciye gönder
    Token query param: ?token=<jwt>
    """
    # JWT doğrulama — WebSocket query param olarak alınır
    from app.core.security import decode_access_token
    from app.models.user import User

    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.accept()
        await websocket.send_text("\r\n\033[31mYetkilendirme hatası: geçerli bir token gerekli.\033[0m\r\n")
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        uid = payload.get("uid")
        user = db.query(User).filter(User.id == uid, User.is_active == True).first() if uid else None
        if not user:
            await websocket.accept()
            await websocket.send_text("\r\n\033[31mYetkilendirme hatası: kullanıcı bulunamadı.\033[0m\r\n")
            await websocket.close(code=4401)
            return
    finally:
        db.close()

    await websocket.accept()
    db = SessionLocal()
    ssh_client = None
    channel = None

    try:
        server = db.query(Server).filter_by(id=server_id).first()
        if not server or not server.ip_address:
            await websocket.send_text("\r\n\033[31mSunucu bulunamadı veya IP adresi yok.\033[0m\r\n")
            await websocket.close()
            return

        gc = db.query(GlobalCredential).filter_by(is_default=True).first() \
             or db.query(GlobalCredential).first()

        creds = _get_creds(server, gc)

        await websocket.send_text(
            f"\r\n\033[36mBağlanılıyor: {creds['username']}@{creds['host']}:{creds['port']}\033[0m\r\n"
        )

        # SSH bağlan
        try:
            ssh_client = _make_ssh(creds)
        except Exception as e:
            await websocket.send_text(f"\r\n\033[31mBağlantı hatası: {e}\033[0m\r\n")
            await websocket.close()
            return

        # PTY kanal aç
        channel = ssh_client.invoke_shell(
            term="xterm-256color", width=COLS, height=ROWS
        )
        channel.setblocking(False)

        await websocket.send_text(
            f"\r\n\033[32mBağlandı: {server.name} ({creds['host']})\033[0m\r\n"
        )

        loop = asyncio.get_event_loop()

        async def ssh_to_ws():
            """SSH → WebSocket"""
            while True:
                await asyncio.sleep(0.01)
                try:
                    data = await loop.run_in_executor(None, _read_channel, channel)
                    if data is None:
                        break
                    if data:
                        await websocket.send_bytes(data)
                except Exception:
                    break

        def _read_channel(ch) -> bytes | None:
            try:
                if ch.closed or ch.exit_status_ready():
                    return None
                if ch.recv_ready():
                    return ch.recv(4096)
                if ch.recv_stderr_ready():
                    return ch.recv_stderr(4096)
                return b""
            except Exception:
                return None

        # SSH→WS task başlat
        ssh_task = asyncio.create_task(ssh_to_ws())

        # WS → SSH (ana döngü)
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(websocket.receive(), timeout=0.05)
                except asyncio.TimeoutError:
                    # Channel kapandı mı kontrol et
                    if channel.exit_status_ready() or channel.closed:
                        break
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "websocket.disconnect":
                    break
                elif msg_type == "websocket.receive":
                    data = msg.get("bytes") or (msg.get("text") or "").encode()
                    if data:
                        # Resize mesajı: \x01{cols},{rows}
                        if data[:1] == b"\x01":
                            try:
                                dims = data[1:].decode().split(",")
                                cols, rows = int(dims[0]), int(dims[1])
                                channel.resize_pty(width=cols, height=rows)
                            except Exception:
                                pass
                        else:
                            channel.sendall(data)
        finally:
            ssh_task.cancel()
            try:
                await ssh_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"SSH terminal hata ({server_id}): {e}")
        try:
            await websocket.send_text(f"\r\n\033[31mHata: {e}\033[0m\r\n")
        except Exception:
            pass
    finally:
        if channel:
            try:
                channel.close()
            except Exception:
                pass
        if ssh_client:
            try:
                ssh_client.close()
            except Exception:
                pass
        db.close()
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info(f"SSH terminal kapandı: server_id={server_id}")
