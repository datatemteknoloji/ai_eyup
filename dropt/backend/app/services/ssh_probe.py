from dataclasses import dataclass
import os
from pathlib import Path
import socket

import paramiko

KEY_DIR = Path(os.environ.get("PORTAL_SSH_KEY_DIR", "/ssh-keys"))
PRIVATE_KEY_PATH = KEY_DIR / "id_rsa"
PUBLIC_KEY_PATH = KEY_DIR / "id_rsa.pub"


@dataclass
class SshProbeResult:
    ok: bool
    message: str


@dataclass
class BootstrapResult:
    password_ok: bool
    key_installed: bool
    message: str


def probe_tcp(
    *,
    host: str,
    port: int,
    timeout: float = 2.0,
) -> SshProbeResult:
    """Fast reachability check before Paramiko (dead hosts fail in ~2s, not 8–12s)."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return SshProbeResult(ok=True, message="TCP erişilebilir")
    except OSError as exc:
        return SshProbeResult(ok=False, message=f"TCP/{port} erişilemiyor: {exc}")
    except Exception as exc:  # noqa: BLE001
        return SshProbeResult(ok=False, message=f"TCP kontrolü başarısız: {exc}")


def ensure_portal_keypair() -> tuple[Path, Path]:
    """Create portal RSA keypair once under PORTAL_SSH_KEY_DIR."""
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        return PRIVATE_KEY_PATH, PUBLIC_KEY_PATH

    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(PRIVATE_KEY_PATH))
    os.chmod(PRIVATE_KEY_PATH, 0o600)
    pub_line = f"{key.get_name()} {key.get_base64()} portal@dropt\n"
    PUBLIC_KEY_PATH.write_text(pub_line, encoding="utf-8")
    os.chmod(PUBLIC_KEY_PATH, 0o644)
    return PRIVATE_KEY_PATH, PUBLIC_KEY_PATH


def read_portal_public_key() -> str:
    ensure_portal_keypair()
    return PUBLIC_KEY_PATH.read_text(encoding="utf-8").strip()


def load_portal_private_key() -> paramiko.PKey:
    ensure_portal_keypair()
    return paramiko.RSAKey.from_private_key_file(str(PRIVATE_KEY_PATH))


def _connect(
    *,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    pkey: paramiko.PKey | None = None,
    timeout: float = 8.0,
) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        pkey=pkey,
        timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def probe_ssh_password(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: float = 8.0,
) -> SshProbeResult:
    client = None
    try:
        client = _connect(
            host=host, port=port, username=username, password=password, timeout=timeout
        )
        _stdin, stdout, _stderr = client.exec_command("echo ok", timeout=timeout)
        _ = stdout.read()
        return SshProbeResult(ok=True, message="SSH bağlantısı başarılı (şifre)")
    except paramiko.AuthenticationException:
        return SshProbeResult(ok=False, message="Kimlik doğrulama başarısız (kullanıcı/şifre)")
    except paramiko.SSHException as exc:
        return SshProbeResult(ok=False, message=f"SSH hatası: {exc}")
    except OSError as exc:
        return SshProbeResult(ok=False, message=f"Ağ/bağlantı hatası: {exc}")
    except Exception as exc:  # noqa: BLE001
        return SshProbeResult(ok=False, message=f"Bağlantı denemesi başarısız: {exc}")
    finally:
        if client is not None:
            client.close()


def probe_ssh_key(
    *,
    host: str,
    port: int,
    username: str,
    timeout: float = 8.0,
) -> SshProbeResult:
    client = None
    try:
        pkey = load_portal_private_key()
        client = _connect(host=host, port=port, username=username, pkey=pkey, timeout=timeout)
        _stdin, stdout, _stderr = client.exec_command("echo ok", timeout=timeout)
        _ = stdout.read()
        return SshProbeResult(ok=True, message="SSH bağlantısı başarılı (key)")
    except paramiko.AuthenticationException:
        return SshProbeResult(ok=False, message="Key ile kimlik doğrulama başarısız")
    except Exception as exc:  # noqa: BLE001
        return SshProbeResult(ok=False, message=f"Key bağlantı hatası: {exc}")
    finally:
        if client is not None:
            client.close()


def install_portal_pubkey_with_password(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    timeout: float = 12.0,
) -> BootstrapResult:
    """
    1) Login with password
    2) Ensure ~/.ssh/authorized_keys contains portal public key
    3) Verify login with portal private key
    """
    pub = read_portal_public_key()
    # Escape for single-quoted remote shell fragment
    pub_escaped = pub.replace("'", "'\"'\"'")

    remote_script = f"""
set -e
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
PUB='{pub_escaped}'
if ! grep -qxF "$PUB" "$HOME/.ssh/authorized_keys"; then
  printf '%s\\n' "$PUB" >> "$HOME/.ssh/authorized_keys"
fi
"""

    client = None
    try:
        pw_probe = probe_ssh_password(
            host=host, port=port, username=username, password=password, timeout=timeout
        )
        if not pw_probe.ok:
            # Password may be disabled after a prior key enrollment — try key before failing.
            key_only = probe_ssh_key(host=host, port=port, username=username, timeout=timeout)
            if key_only.ok:
                return BootstrapResult(
                    password_ok=False,
                    key_installed=True,
                    message=(
                        f"Şifre auth başarısız ({pw_probe.message}); "
                        "portal key ile giriş OK (yeniden kayıt)"
                    ),
                )
            return BootstrapResult(
                password_ok=False,
                key_installed=False,
                message=f"{pw_probe.message}; key ile de giriş yapılamadı",
            )

        client = _connect(
            host=host, port=port, username=username, password=password, timeout=timeout
        )
        _stdin, stdout, stderr = client.exec_command(remote_script, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if exit_status != 0:
            return BootstrapResult(
                password_ok=True,
                key_installed=False,
                message=f"Şifre OK; pubkey yazılamadı: {err or f'exit {exit_status}'}",
            )
        client.close()
        client = None

        key_probe = probe_ssh_key(host=host, port=port, username=username, timeout=timeout)
        if key_probe.ok:
            return BootstrapResult(
                password_ok=True,
                key_installed=True,
                message="Şifre OK; portal pubkey yazıldı; key ile giriş doğrulandı",
            )
        return BootstrapResult(
            password_ok=True,
            key_installed=False,
            message=f"Şifre OK; pubkey yazıldı ama key ile giriş doğrulanamadı: {key_probe.message}",
        )
    except Exception as exc:  # noqa: BLE001
        return BootstrapResult(
            password_ok=True,
            key_installed=False,
            message=f"Şifre OK; pubkey kurulumu hata: {exc}",
        )
    finally:
        if client is not None:
            client.close()
