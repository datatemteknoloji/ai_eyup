"""
Host adı çözümleme: önce sistem DNS, sonra mount edilen host /etc/hosts.

Compose extra_hosts yerine dinamik kaynak — host OS /etc/hosts güncellenince
container recreate gerekmez (RO bind mount).
"""
from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

HOST_ETC_HOSTS = Path(os.environ.get("HOST_ETC_HOSTS", "/host-etc-hosts"))


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def lookup_host_etc_hosts(hostname: str, hosts_path: Optional[Path] = None) -> Optional[str]:
    """hostname → IP (ilk eşleşme). Yoksa None."""
    path = hosts_path or HOST_ETC_HOSTS
    if not path.is_file():
        return None
    target = _norm(hostname)
    if not target:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, *names = parts
        if any(_norm(n) == target for n in names):
            return ip
    return None


def resolve_connect_host(hostname: str) -> Tuple[str, str]:
    """
    Bağlantı için host adı çöz.
    Dönüş: (connect_host, note)
    - DNS OK ise orijinal hostname (IP'ye zorlamaz)
    - DNS fail + /etc/hosts eşleşmesi → IP
    - ikisi de fail → orijinal hostname + uyarı
    """
    host = (hostname or "").strip()
    if not host:
        return "", "host boş"
    # Zaten IP ise dokunma
    try:
        socket.inet_pton(socket.AF_INET, host)
        return host, f"IP: {host}"
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host.strip("[]"))
        return host, f"IPv6: {host}"
    except OSError:
        pass

    try:
        socket.getaddrinfo(host, None)
        return host, f"DNS OK: {host}"
    except OSError:
        pass

    mapped = lookup_host_etc_hosts(host)
    if mapped:
        return mapped, f"Host /etc/hosts: {host} → {mapped}"
    return host, f"Uyarı: {host} çözülemedi (DNS + host /etc/hosts)"


def rewrite_url_host(url: str) -> Tuple[str, str, Optional[str]]:
    """
    URL hostname'ini gerekirse IP ile değiştir.
    Dönüş: (new_url, note, original_hostname_or_None)
    original_hostname, Host/SNI için saklanır (IP'ye yazıldıysa).
    """
    raw = (url or "").strip()
    if not raw:
        return "", "URL boş", None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    hostname = parsed.hostname
    if not hostname:
        return raw.rstrip("/"), "hostname yok", None

    connect, note = resolve_connect_host(hostname)
    if connect == hostname:
        return raw.rstrip("/"), note, None

    # netloc: userinfo@host:port
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    port = parsed.port
    if ":" in connect and not connect.startswith("["):
        # IPv6 literal
        host_part = f"[{connect}]"
    else:
        host_part = connect
    netloc = f"{userinfo}{host_part}" + (f":{port}" if port else "")
    new = urlunparse((
        parsed.scheme,
        netloc,
        parsed.path or "",
        parsed.params,
        parsed.query,
        parsed.fragment,
    )).rstrip("/")
    return new, note, hostname
