"""Shared SSH helpers for target-host modules."""

from __future__ import annotations

from sqlmodel import Session

from app.models.server import Credential, TargetServer
from app.services.bootstrap import get_automation_username
from app.services.credential_manager import CredentialManager
from app.services.privilege import elevate_command
from app.services.ssh_exec import ExecResult, ssh_exec


def connect_user(session: Session, server: TargetServer) -> tuple[str, str | None]:
    username = get_automation_username(session)
    password: str | None = None
    if server.credentials_id:
        cred = session.get(Credential, server.credentials_id)
        if cred:
            username = cred.ssh_username or username
            if cred.encrypted_ssh_password and not server.ssh_key_installed:
                password = CredentialManager().decrypt(cred.encrypted_ssh_password)
    return username, password


def run_ssh(
    session: Session,
    server: TargetServer,
    command: str,
    *,
    timeout: float = 45.0,
    elevate: bool = True,
) -> ExecResult:
    username, password = connect_user(session, server)
    remote = elevate_command(session, command) if elevate else command
    return ssh_exec(
        host=server.ip,
        port=server.port,
        username=username,
        command=remote,
        timeout=timeout,
        password=password if not server.ssh_key_installed else None,
    )


def upload_files(
    session: Session,
    server: TargetServer,
    local_files: list[str],
    remote_dir: str,
    *,
    timeout: float = 120.0,
) -> list[str]:
    """SFTP ile dosyaları remote_dir altına yükler; remote path listesi döner.

    Escalate gerektiğinde önce /tmp'ye yazar, sonra elevated mv ile hedefe taşır.
    """
    import shlex
    import uuid
    from pathlib import Path

    import paramiko

    from app.services.privilege import get_automation_user_kind
    from app.services.ssh_probe import load_portal_private_key

    if not local_files:
        raise ValueError("Yüklenecek dosya yok")
    remote_dir = (remote_dir or "").rstrip("/")
    if not remote_dir.startswith("/") or ".." in remote_dir:
        raise ValueError("Geçersiz remote dizin")

    username, password = connect_user(session, server)
    kind = get_automation_user_kind(session)
    needs_stage = kind != "root"

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {
        "hostname": server.ip,
        "port": server.port,
        "username": username,
        "timeout": timeout,
        "allow_agent": False,
        "look_for_keys": False,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
    }
    if password and not server.ssh_key_installed:
        kwargs["password"] = password
    else:
        kwargs["pkey"] = load_portal_private_key()
    client.connect(**kwargs)
    uploaded: list[str] = []
    try:
        staging = f"/tmp/dropt-upload-{uuid.uuid4().hex}" if needs_stage else remote_dir
        mkdir_cmd = elevate_command(session, f"mkdir -p {shlex.quote(remote_dir)}")
        if needs_stage:
            mkdir_cmd = f"mkdir -p {shlex.quote(staging)} && {mkdir_cmd}"
        _stdin, stdout, _stderr = client.exec_command(mkdir_cmd, timeout=30)
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(f"Remote mkdir başarısız: {remote_dir}")
        sftp = client.open_sftp()
        try:
            for lp in local_files:
                name = Path(lp).name
                if needs_stage:
                    staged = f"{staging}/{name}"
                    final = f"{remote_dir}/{name}"
                    sftp.put(lp, staged)
                    mv = elevate_command(
                        session,
                        f"mv -f {shlex.quote(staged)} {shlex.quote(final)}",
                    )
                    _i, so, se = client.exec_command(mv, timeout=60)
                    if so.channel.recv_exit_status() != 0:
                        err = se.read().decode("utf-8", errors="replace")
                        raise RuntimeError(f"Remote mv başarısız: {final} ({err[:200]})")
                    uploaded.append(final)
                else:
                    remote = f"{remote_dir}/{name}"
                    sftp.put(lp, remote)
                    uploaded.append(remote)
        finally:
            sftp.close()
            if needs_stage:
                client.exec_command(f"rm -rf {shlex.quote(staging)}", timeout=15)
    finally:
        client.close()
    return uploaded
