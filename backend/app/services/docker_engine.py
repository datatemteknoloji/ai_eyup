"""
Docker Engine API (unix socket) — platform durumu, loglar, exec yardımcıları.

httpx UDS transport; docker CLI gerekmez.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


def docker_sock() -> str:
    return os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


def docker_sock_readable() -> bool:
    sock = docker_sock()
    return os.path.exists(sock) and os.access(sock, os.R_OK)


def docker_sock_writable() -> bool:
    sock = docker_sock()
    return os.path.exists(sock) and os.access(sock, os.R_OK | os.W_OK)


def _client(timeout: float = 60.0) -> httpx.Client:
    sock = docker_sock()
    if not os.path.exists(sock):
        raise RuntimeError(f"Docker soketi yok: {sock}")
    transport = httpx.HTTPTransport(uds=sock)
    return httpx.Client(transport=transport, base_url="http://docker", timeout=timeout)


def api_get(path: str, params: Optional[dict] = None, timeout: float = 30.0) -> Any:
    with _client(timeout=timeout) as client:
        resp = client.get(path, params=params)
        if resp.status_code >= 400:
            raise RuntimeError(f"Docker API {resp.status_code}: {resp.text[:400]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except Exception:
            return resp.text


def api_post(path: str, body: Optional[dict] = None, timeout: float = 120.0, params: Optional[dict] = None) -> Tuple[int, Any]:
    with _client(timeout=timeout) as client:
        resp = client.post(path, json=body, params=params)
        raw = resp.content
        payload: Any
        if not raw:
            payload = None
        else:
            try:
                payload = resp.json()
            except Exception:
                payload = raw.decode("utf-8", errors="replace")
        if resp.status_code >= 400:
            msg = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)[:400]
            raise RuntimeError(f"Docker API {resp.status_code}: {msg}")
        return resp.status_code, payload


def list_containers(all_containers: bool = True) -> List[Dict[str, Any]]:
    data = api_get("/containers/json", params={"all": "true" if all_containers else "false"})
    return data if isinstance(data, list) else []


def inspect_container(container_id: str) -> Dict[str, Any]:
    data = api_get(f"/containers/{container_id}/json", timeout=20.0)
    return data if isinstance(data, dict) else {}


def restart_container(container_id: str, timeout_sec: int = 15) -> None:
    if not docker_sock_writable():
        raise RuntimeError("Docker soketi yazılamıyor — yeniden başlatma için RW mount gerekli")
    api_post(f"/containers/{container_id}/restart", params={"t": str(timeout_sec)}, timeout=timeout_sec + 60)


def container_logs_tail(container_id: str, tail: int = 200, timestamps: bool = True) -> str:
    """Son N satır log (takip yok)."""
    with _client(timeout=60.0) as client:
        resp = client.get(
            f"/containers/{container_id}/logs",
            params={
                "stdout": "true",
                "stderr": "true",
                "tail": str(max(1, min(tail, 5000))),
                "timestamps": "true" if timestamps else "false",
                "follow": "false",
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Log okunamadı: {resp.status_code} {resp.text[:300]}")
        return _demux_or_text(resp.content)


def iter_container_logs(
    container_id: str,
    *,
    tail: int = 200,
    follow: bool = True,
    timestamps: bool = True,
) -> Generator[str, None, None]:
    """Canlı log satırları (follow). Bağlantı kesilince generator biter."""
    params = {
        "stdout": "true",
        "stderr": "true",
        "tail": str(max(1, min(tail, 2000))),
        "timestamps": "true" if timestamps else "false",
        "follow": "true" if follow else "false",
    }
    # follow uzun sürebilir
    timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)
    sock = docker_sock()
    transport = httpx.HTTPTransport(uds=sock)
    with httpx.Client(transport=transport, base_url="http://docker", timeout=timeout) as client:
        with client.stream("GET", f"/containers/{container_id}/logs", params=params) as resp:
            if resp.status_code >= 400:
                body = resp.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Log stream hatası: {resp.status_code} {body[:300]}")
            buf = b""
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                buf += chunk
                # Docker multiplex: 8-byte header + payload; TTY yoksa
                text, buf = _consume_docker_stream(buf)
                if text:
                    for line in text.splitlines(keepends=True):
                        yield line if line.endswith("\n") else line + "\n"


def _demux_or_text(raw: bytes) -> str:
    text, rest = _consume_docker_stream(raw)
    if rest:
        # kalan tek başına payload olabilir
        try:
            text += rest.decode("utf-8", errors="replace")
        except Exception:
            pass
    return text


def _consume_docker_stream(buf: bytes) -> Tuple[str, bytes]:
    """Docker non-TTY multiplex stream → utf-8 text; parse edilemeyen kısım leftover."""
    out: List[str] = []
    i = 0
    n = len(buf)
    # Heuristic: if looks like multiplex (stream type 0-2 in first byte)
    while i + 8 <= n:
        stream_type = buf[i]
        if stream_type not in (0, 1, 2):
            # plain text (TTY / some engines)
            try:
                return buf.decode("utf-8", errors="replace"), b""
            except Exception:
                return "", b""
        size = int.from_bytes(buf[i + 4 : i + 8], "big")
        if i + 8 + size > n:
            break
        payload = buf[i + 8 : i + 8 + size]
        out.append(payload.decode("utf-8", errors="replace"))
        i += 8 + size
    return "".join(out), buf[i:]


def find_container_by_name(name: str, containers: Optional[Iterable[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    name = (name or "").lstrip("/")
    items = list(containers) if containers is not None else list_containers(True)
    for c in items:
        names = [n.lstrip("/") for n in (c.get("Names") or [])]
        if name in names:
            return c
    return None


def exec_in_container(
    container_id: str,
    cmd: List[str],
    *,
    stdin_data: Optional[bytes] = None,
    user: Optional[str] = None,
    workdir: Optional[str] = None,
    timeout: float = 600.0,
) -> Tuple[int, bytes]:
    """
    Container içinde komut çalıştır; stdout+stderr birleşik döner.
    Dönüş: (exit_code, output_bytes)
    """
    if not docker_sock_writable() and stdin_data:
        # exec create/start genelde sock üzerinde yazma ister
        pass
    if not docker_sock_readable():
        raise RuntimeError("Docker soketi okunamıyor")

    body: Dict[str, Any] = {
        "AttachStdout": True,
        "AttachStderr": True,
        "AttachStdin": bool(stdin_data),
        "Tty": False,
        "Cmd": cmd,
    }
    if user:
        body["User"] = user
    if workdir:
        body["WorkingDir"] = workdir

    _, created = api_post(f"/containers/{container_id}/exec", body=body, timeout=30.0)
    if not isinstance(created, dict) or not created.get("Id"):
        raise RuntimeError(f"exec create başarısız: {created}")
    exec_id = created["Id"]

    # Start with hijack stream — httpx stream POST
    sock = docker_sock()
    transport = httpx.HTTPTransport(uds=sock)
    timeout_cfg = httpx.Timeout(connect=10.0, read=timeout, write=timeout, pool=30.0)
    start_body = {"Detach": False, "Tty": False}
    output = bytearray()
    with httpx.Client(transport=transport, base_url="http://docker", timeout=timeout_cfg) as client:
        with client.stream(
            "POST",
            f"/exec/{exec_id}/start",
            json=start_body,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"exec start: {resp.status_code} {resp.read()[:300]!r}")
            # Not sending stdin via hijack with httpx is awkward; for dump we don't need stdin.
            # For restore with large stdin, use put_archive + psql -f instead.
            for chunk in resp.iter_bytes():
                if chunk:
                    output.extend(chunk)

    text_out = _demux_or_text(bytes(output)).encode("utf-8", errors="replace")

    inspect = api_get(f"/exec/{exec_id}/json", timeout=15.0)
    exit_code = 0
    if isinstance(inspect, dict):
        exit_code = int(inspect.get("ExitCode") or 0)
    return exit_code, text_out


def put_archive(container_id: str, dest_path: str, tar_bytes: bytes) -> None:
    """Tar arşivini container'a kopyala (dest_path dizin olmalı)."""
    if not docker_sock_writable():
        raise RuntimeError("Docker soketi yazılamıyor")
    sock = docker_sock()
    transport = httpx.HTTPTransport(uds=sock)
    with httpx.Client(transport=transport, base_url="http://docker", timeout=300.0) as client:
        resp = client.put(
            f"/containers/{container_id}/archive",
            params={"path": dest_path},
            content=tar_bytes,
            headers={"Content-Type": "application/x-tar"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"put_archive: {resp.status_code} {resp.text[:300]}")
