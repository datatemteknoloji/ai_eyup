from dataclasses import dataclass

import paramiko

from app.services.ssh_probe import load_portal_private_key


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def ssh_exec(
    *,
    host: str,
    port: int,
    username: str,
    command: str,
    timeout: float = 30.0,
    password: str | None = None,
) -> ExecResult:
    """Run a remote command via portal SSH key (preferred) or password fallback."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs: dict = {
            "hostname": host,
            "port": port,
            "username": username,
            "timeout": timeout,
            "allow_agent": False,
            "look_for_keys": False,
            "banner_timeout": timeout,
            "auth_timeout": timeout,
        }
        if password:
            connect_kwargs["password"] = password
        else:
            connect_kwargs["pkey"] = load_portal_private_key()

        client.connect(**connect_kwargs)
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return ExecResult(exit_code=exit_code, stdout=out, stderr=err)
    finally:
        client.close()
