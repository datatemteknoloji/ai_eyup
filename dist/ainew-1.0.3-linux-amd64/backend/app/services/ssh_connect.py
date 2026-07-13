"""
Ortak SSH bağlantı yardımcı fonksiyonu.

Codebase'deki tüm SSH bağlantı noktaları (ssh_manager, server_connector, terminal,
level1, package_service, system_update_service, rhsm_sync_service) aynı deseni
kullanır. Centrify / PAM (ChallengeResponseAuthentication) sunucularında
keyboard-interactive önceliklidir; başarısız auth sonrası transport yeniden
kullanılmaz (OpenSSH/Centrify oturumu düşürür → "No existing session").
"""
import logging
import socket
from typing import List, Optional, Sequence, Tuple

import paramiko

logger = logging.getLogger(__name__)

# Centrify + Banner /etc/issue ortamlarında 5s sık sık banner/auth yarışına düşer.
DEFAULT_TIMEOUT = 20.0
BANNER_TIMEOUT = 30.0
AUTH_TIMEOUT = 30.0


def connect_ssh(
    client: paramiko.SSHClient,
    *,
    hostname: str,
    username: str,
    port: int = 22,
    password: Optional[str] = None,
    pkey: Optional[paramiko.PKey] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """paramiko SSHClient ile bağlan: önce key (varsa), olmazsa şifre.

    Şifreyle bağlanırken ÖNCE keyboard-interactive (PAM / Centrify), olmazsa
    düz password denenir. Her auth denemesi AYRI bir TCP+Transport açar —
    bir metod reddedilince aynı transport üzerinde ikinci deneme Centrify /
    sıkı sshd'de "No existing session" üretir.

    Dönüş: True (bağlandı). Bağlanılamazsa paramiko.AuthenticationException fırlatır.
    """
    connected = False
    last_err: Optional[BaseException] = None

    if pkey is not None:
        try:
            client.connect(
                hostname=hostname,
                port=port,
                username=username,
                pkey=pkey,
                timeout=timeout,
                banner_timeout=BANNER_TIMEOUT,
                auth_timeout=AUTH_TIMEOUT,
                allow_agent=False,
                look_for_keys=False,
            )
            connected = True
        except Exception as key_err:
            last_err = key_err
            logger.warning(
                "Key auth failed for %s, trying password... (%s)", hostname, key_err
            )
            try:
                client.close()
            except Exception:
                pass
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if not connected and password:
        # 1) keyboard-interactive (Centrify ChallengeResponse / PAM)
        try:
            transport = _auth_with_fresh_transport(
                hostname,
                port,
                timeout,
                lambda t: _auth_keyboard_interactive(t, username, password),
            )
            client._transport = transport
            connected = True
        except Exception as ki_err:
            last_err = ki_err
            logger.warning(
                "keyboard-interactive başarısız, 'password' metoduna düşülüyor: %s (%s)",
                hostname,
                ki_err,
            )

        # 2) password — her zaman yeni transport (önceki oturum ölü olabilir)
        if not connected:
            try:
                transport = _auth_with_fresh_transport(
                    hostname,
                    port,
                    timeout,
                    lambda t: t.auth_password(username, password),
                )
                client._transport = transport
                connected = True
            except Exception as pw_err:
                last_err = pw_err
                logger.warning("password auth başarısız: %s (%s)", hostname, pw_err)

        # 3) Son çare: SSHClient.connect (paramiko kendi KI fallback'ini dener)
        if not connected:
            try:
                client.connect(
                    hostname=hostname,
                    port=port,
                    username=username,
                    password=password,
                    timeout=timeout,
                    banner_timeout=BANNER_TIMEOUT,
                    auth_timeout=AUTH_TIMEOUT,
                    allow_agent=False,
                    look_for_keys=False,
                )
                connected = True
            except Exception as conn_err:
                last_err = conn_err

    if not connected:
        msg = "Hem key hem de password ile bağlantı başarısız (veya hiçbiri sağlanmadı)."
        if last_err is not None:
            raise paramiko.AuthenticationException(f"{msg} Son hata: {last_err}") from last_err
        raise paramiko.AuthenticationException(msg)

    return True


def _auth_keyboard_interactive(
    transport: paramiko.Transport, username: str, password: str
) -> List[str]:
    """Centrify/PAM: yalnızca gizli (echo=False) prompt'lara şifre yaz."""

    def handler(
        title: str,
        instructions: str,
        prompt_list: Sequence[Tuple[str, bool]],
    ) -> List[str]:
        if title:
            logger.debug("SSH KI title (%s): %s", transport.remote_version, title)
        if instructions:
            logger.debug("SSH KI instructions: %s", instructions[:200])
        answers: List[str] = []
        for prompt, echo in prompt_list:
            pl = (prompt or "").lower()
            if not echo or "password" in pl or "passcode" in pl or "şifre" in pl:
                answers.append(password)
            else:
                # Bilgi / kullanıcı adı benzeri echo'lu prompt — boş bırak
                answers.append("")
        return answers

    return transport.auth_interactive(username, handler)


def _auth_with_fresh_transport(hostname: str, port: int, timeout: float, auth_fn):
    """Yeni TCP+Transport aç, auth_fn çalıştır; başarısızsa transport'u kapat."""
    transport = None
    try:
        transport = _open_transport(hostname, port, timeout)
        auth_fn(transport)
        if not transport.is_authenticated():
            raise paramiko.AuthenticationException("Auth tamamlandı ama oturum authenticated değil")
        return transport
    except Exception:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass
        raise


def _open_transport(hostname: str, port: int, timeout: float) -> paramiko.Transport:
    """TCP + SSH handshake (henüz auth edilmemiş) Transport.

    Host key doğrulaması bilinçli atlanır: çağıranların tamamı AutoAddPolicy
    kullanıyordu.
    """
    sock = socket.create_connection((hostname, port), timeout=timeout)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = BANNER_TIMEOUT
    transport.auth_timeout = AUTH_TIMEOUT
    # Banner /etc/issue + Centrify bazen yavaş; kısa timeout EBADF / banner hatası üretir
    transport.start_client(timeout=max(timeout, BANNER_TIMEOUT))
    return transport
