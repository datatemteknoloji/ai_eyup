"""
Ortak SSH bağlantı yardımcı fonksiyonu.

Codebase'deki tüm SSH bağlantı noktaları (ssh_manager, server_connector, terminal,
level1, package_service, system_update_service, rhsm_sync_service) aynı deseni
kullanıyordu: önce private key, olmazsa şifre ile paramiko.SSHClient.connect().
Bu modül o deseni TEK yerden sağlar, böylece PAM tabanlı sıkılaştırılmış (hardened)
sshd sunucularına uyum (keyboard-interactive önceliği) her çağıran için otomatik
uygulanır ve gelecekte tekrar dağılıp unutulmaz.
"""
import logging
import socket
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


def connect_ssh(
    client: paramiko.SSHClient,
    *,
    hostname: str,
    username: str,
    port: int = 22,
    password: Optional[str] = None,
    pkey: Optional[paramiko.PKey] = None,
    timeout: float = 10,
) -> bool:
    """paramiko SSHClient ile bağlan: önce key (varsa), olmazsa şifre.

    Şifreyle bağlanırken ÖNCE "keyboard-interactive" (PAM conversation) denenir,
    o başarısız olursa düz "password" SSH auth metoduna düşülür. Sıra bilerek bu
    şekilde: çoğu PAM tabanlı sıkılaştırılmış (hardened) sshd yapılandırması
    "password" metodunu formalite olarak kabul edip PAM seviyesinde reddeder, ama
    AYNI şifreyi "keyboard-interactive" üzerinden kabul eder — OpenSSH istemcisinin
    "şifre sor" prompt'u da zaten fiilen bu yöntemi kullanır, kullanıcı farkı
    görmez. "password" metodunu formalite olarak kabul edip reddeden bir sunucuda,
    paramiko'nun connect(password=...) çağrısı bunu otomatik olarak
    keyboard-interactive'e düşürmez (sadece sunucu "password" metodunu HİÇ
    desteklemediğinde otomatik düşer) — bu yüzden keyboard-interactive'i EN BAŞTA
    deneyip normal/eski sunucular için password'e düşmek, tersinden daha güvenilir.

    Dönüş: True (bağlandı). Bağlanılamazsa paramiko.AuthenticationException fırlatır.
    """
    connected = False

    if pkey is not None:
        try:
            client.connect(
                hostname=hostname, port=port, username=username, pkey=pkey,
                timeout=timeout, allow_agent=False, look_for_keys=False,
            )
            connected = True
        except Exception as key_err:
            logger.warning(f"Key auth failed for {hostname}, trying password... ({key_err})")

    if not connected and password:
        transport = _open_transport(hostname, port, timeout)
        try:
            try:
                transport.auth_interactive(
                    username,
                    lambda title, instructions, prompt_list: [password] * len(prompt_list),
                )
                connected = True
            except paramiko.SSHException as ki_err:
                logger.warning(
                    f"keyboard-interactive başarısız, 'password' metoduna düşülüyor: {hostname} ({ki_err})"
                )
                transport.auth_password(username, password)
                connected = True
        except Exception:
            transport.close()
            raise
        if connected:
            # exec_command/vb. çağrılarının çalışması için transport'u client'a bağla —
            # client.connect() kullanmadığımız için normalde bunu SSHClient kendisi yapardı.
            client._transport = transport

    if not connected:
        raise paramiko.AuthenticationException(
            "Hem key hem de password ile bağlantı başarısız (veya hiçbiri sağlanmadı)."
        )

    return True


def _open_transport(hostname: str, port: int, timeout: float) -> paramiko.Transport:
    """TCP + SSH handshake'i tamamlanmış (henüz auth edilmemiş) bir Transport açar.

    Host key doğrulaması burada bilerek atlanır: çağıranların tamamı zaten
    AutoAddPolicy kullanıyordu (ilk görüşte güven, known_hosts'a hiç yazılmıyor),
    bu da fiilen doğrulama yapmadığından davranış değişmiyor.
    """
    sock = socket.create_connection((hostname, port), timeout=timeout)
    transport = paramiko.Transport(sock)
    transport.start_client(timeout=timeout)
    return transport
