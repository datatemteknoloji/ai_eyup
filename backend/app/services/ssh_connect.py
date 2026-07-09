"""
Ortak SSH bağlantı yardımcı fonksiyonu.

Codebase'deki tüm SSH bağlantı noktaları (ssh_manager, server_connector, terminal,
level1, package_service, system_update_service, rhsm_sync_service) aynı deseni
kullanıyordu: önce private key, olmazsa şifre ile paramiko.SSHClient.connect().
Bu modül o deseni TEK yerden sağlar, böylece PAM tabanlı sıkılaştırılmış (hardened)
sshd sunucularına uyum (keyboard-interactive fallback) her çağıran için otomatik
uygulanır ve gelecekte tekrar dağılıp unutulmaz.
"""
import logging
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

    Bazı sıkılaştırılmış (PAM tabanlı) sshd yapılandırmaları "password" SSH auth
    metodunu formalite olarak kabul edip PAM seviyesinde reddeder, ama AYNI şifreyi
    "keyboard-interactive" (PAM conversation) üzerinden kabul eder — OpenSSH istemcisi
    bu ikisini kullanıcıya aynı "şifre sor" davranışıyla gösterdiği için fark edilmez,
    ama paramiko'nun connect(password=...) çağrısı keyboard-interactive'i otomatik
    denemez (sadece sunucu "password" metodunu HİÇ desteklemediğinde otomatik düşer).
    Bu fonksiyon, düz şifre denemesi AuthenticationException ile başarısız olursa aynı
    şifreyle otomatik olarak keyboard-interactive'e düşer.

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
        try:
            client.connect(
                hostname=hostname, port=port, username=username, password=password,
                timeout=timeout, allow_agent=False, look_for_keys=False,
            )
            connected = True
        except paramiko.AuthenticationException:
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                logger.warning(f"'password' auth reddedildi, keyboard-interactive deneniyor: {hostname}")
                transport.auth_interactive(
                    username,
                    lambda title, instructions, prompt_list: [password] * len(prompt_list),
                )
                connected = True
            else:
                raise

    if not connected:
        raise paramiko.AuthenticationException(
            "Hem key hem de password ile bağlantı başarısız (veya hiçbiri sağlanmadı)."
        )

    return True
