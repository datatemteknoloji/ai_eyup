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


def _ssh_timeouts() -> tuple:
    try:
        from app.services.runtime_settings import get_float
        return (
            float(get_float("ssh_connect_timeout_sec")),
            float(get_float("ssh_banner_timeout_sec")),
            float(get_float("ssh_auth_timeout_sec")),
        )
    except Exception:
        return DEFAULT_TIMEOUT, BANNER_TIMEOUT, AUTH_TIMEOUT


def connect_ssh(
    client: paramiko.SSHClient,
    *,
    hostname: str,
    username: str,
    port: int = 22,
    password: Optional[str] = None,
    pkey: Optional[paramiko.PKey] = None,
    timeout: Optional[float] = None,
) -> bool:
    """paramiko SSHClient ile bağlan: önce key (varsa), olmazsa şifre.

    Şifreyle bağlanırken ÖNCE keyboard-interactive (PAM / Centrify), olmazsa
    düz password denenir. Her auth denemesi AYRI bir TCP+Transport açar —
    bir metod reddedilince aynı transport üzerinde ikinci deneme Centrify /
    sıkı sshd'de "No existing session" üretir.

    Dönüş: True (bağlandı). Bağlanılamazsa paramiko.AuthenticationException fırlatır.
    """
    connect_t, banner_t, auth_t = _ssh_timeouts()
    if timeout is None:
        timeout = connect_t

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
                banner_timeout=banner_t,
                auth_timeout=auth_t,
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
                banner_timeout=banner_t,
                auth_timeout=auth_t,
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
                    banner_timeout=banner_t,
                    auth_timeout=auth_t,
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
                    banner_timeout=banner_t,
                    auth_timeout=auth_t,
                    allow_agent=False,
                    look_for_keys=False,
                )
                connected = True
            except Exception as conn_err:
                last_err = conn_err

    if not connected:
        if password is None and pkey is None:
            msg = "SSH kimlik bilgisi yok (password/key sağlanmadı)."
        elif last_err is not None and _is_timeout_err(last_err):
            msg = (
                f"SSH zaman aşımı / erişilemiyor ({hostname}:{port}). "
                "Ağ, firewall veya sunucu yanıt vermiyor olabilir."
            )
        elif last_err is not None and _is_banner_err(last_err):
            msg = (
                f"SSH banner okunamadı ({hostname}:{port}). "
                "Yoğun paralel bağlantı veya Centrify/sshd gecikmesi olabilir — tekrar denenebilir."
            )
        else:
            msg = "SSH kimlik doğrulama başarısız (key/password reddedildi)."
        if last_err is not None:
            raise paramiko.AuthenticationException(f"{msg} Son hata: {last_err}") from last_err
        raise paramiko.AuthenticationException(msg)

    return True


def _is_timeout_err(err: BaseException) -> bool:
    s = str(err).lower()
    return "timed out" in s or "timeout" in s or "errno 110" in s


def _is_banner_err(err: BaseException) -> bool:
    s = str(err).lower()
    return "banner" in s or "bad file descriptor" in s or "errno 9" in s


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


def _auth_with_fresh_transport(
    hostname: str,
    port: int,
    timeout: float,
    auth_fn,
    *,
    banner_timeout: float = BANNER_TIMEOUT,
    auth_timeout: float = AUTH_TIMEOUT,
):
    """Yeni TCP+Transport aç, auth_fn çalıştır; başarısızsa transport'u kapat."""
    transport = None
    try:
        transport = _open_transport(
            hostname, port, timeout,
            banner_timeout=banner_timeout,
            auth_timeout=auth_timeout,
        )
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


def _open_transport(
    hostname: str,
    port: int,
    timeout: float,
    *,
    banner_timeout: float = BANNER_TIMEOUT,
    auth_timeout: float = AUTH_TIMEOUT,
) -> paramiko.Transport:
    """TCP + SSH handshake (henüz auth edilmemiş) Transport.

    Host key doğrulaması bilinçli atlanır: çağıranların tamamı AutoAddPolicy
    kullanıyordu.
    """
    sock = socket.create_connection((hostname, port), timeout=timeout)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = banner_timeout
    transport.auth_timeout = auth_timeout
    transport.start_client(timeout=max(timeout, banner_timeout))
    return transport
