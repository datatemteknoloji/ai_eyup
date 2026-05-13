"""
Web SSH Terminal — WebSocket üzerinden tarayıcıdan SSH bağlantısı
"""
import asyncio
import logging
import io
import paramiko
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.server import Server
from app.models.credential import GlobalCredential

logger = logging.getLogger(__name__)
router = APIRouter()

COLS = 220
ROWS = 50


def _get_creds(server: Server, gc: GlobalCredential | None) -> dict:
    cfg = server.connection_config or {}
    return {
        "host":     server.ip_address,
        "port":     int(cfg.get("port") or (gc.port if gc else 22) or 22),
        "username": cfg.get("username") or (gc.username if gc else "root") or "root",
        "password": cfg.get("password") or (gc.password if gc else None),
        "key":      cfg.get("private_key") or (gc.private_key if gc else None),
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

    connected = False
    if pkey:
        try:
            client.connect(creds["host"], port=creds["port"], username=creds["username"],
                           pkey=pkey, timeout=10, allow_agent=False, look_for_keys=False)
            connected = True
        except Exception:
            pass

    if not connected and creds["password"]:
        client.connect(creds["host"], port=creds["port"], username=creds["username"],
                       password=creds["password"], timeout=10, allow_agent=False, look_for_keys=False)
        connected = True

    if not connected:
        raise ConnectionError("SSH kimlik bilgileriyle bağlantı kurulamadı")

    return client


@router.websocket("/ws/{server_id}")
async def ssh_terminal(websocket: WebSocket, server_id: int):
    """
    WebSocket üzerinden SSH terminal.
    İstemciden gelen data → SSH stdin
    SSH stdout/stderr → istemciye gönder
    """
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
