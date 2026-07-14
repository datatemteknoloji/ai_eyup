"""
Windows Remote Management (WinRM) client.
Uses pywinrm to execute PowerShell/CMD on Windows servers over HTTP(S).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WinRMClient:
    """WinRM client for Windows server management via PowerShell."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 5985,
        use_https: bool = False,
        verify_ssl: bool = False,
        timeout: int = 30,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.use_https = use_https
        self.verify_ssl = verify_ssl
        self.timeout = timeout

    def _get_session(self):
        import winrm  # lazy import — not all environments have pywinrm
        scheme = "https" if self.use_https else "http"
        return winrm.Session(
            f"{scheme}://{self.host}:{self.port}/wsman",
            auth=(self.username, self.password),
            transport="ntlm",
            server_cert_validation="ignore" if not self.verify_ssl else "validate",
            operation_timeout_sec=self.timeout,
            read_timeout_sec=self.timeout + 10,
        )

    def run_ps(self, script: str) -> Dict[str, Any]:
        """Execute a PowerShell script and return output."""
        try:
            session = self._get_session()
            result = session.run_ps(script)
            return {
                "success": result.status_code == 0,
                "stdout": result.std_out.decode("utf-8", errors="replace"),
                "stderr": result.std_err.decode("utf-8", errors="replace"),
                "exit_code": result.status_code,
            }
        except Exception as exc:
            logger.error("WinRM PS error on %s: %s", self.host, exc)
            return {"success": False, "stdout": "", "stderr": str(exc), "exit_code": -1}

    def run_cmd(self, command: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a CMD command."""
        try:
            session = self._get_session()
            result = session.run_cmd(command, args or [])
            return {
                "success": result.status_code == 0,
                "stdout": result.std_out.decode("utf-8", errors="replace"),
                "stderr": result.std_err.decode("utf-8", errors="replace"),
                "exit_code": result.status_code,
            }
        except Exception as exc:
            return {"success": False, "stdout": "", "stderr": str(exc), "exit_code": -1}

    def test_connection(self) -> Dict[str, Any]:
        """Test WinRM connectivity — returns {connected, message, latency_ms}."""
        import time
        t0 = time.time()
        result = self.run_ps("Write-Output 'winrm_ok'")
        latency = int((time.time() - t0) * 1000)
        if result["success"] and "winrm_ok" in result["stdout"]:
            return {"connected": True, "message": "WinRM bağlantısı başarılı", "latency_ms": latency}
        return {
            "connected": False,
            "message": result["stderr"] or "Bağlantı başarısız",
            "latency_ms": latency,
        }

    @classmethod
    def from_server(cls, server) -> Optional["WinRMClient"]:
        """Build a WinRMClient from a Server ORM object."""
        from app.core.encryption import decrypt_secret
        cfg = server.connection_config or {}
        username = cfg.get("username") or cfg.get("winrm_username")
        raw_password = cfg.get("password") or cfg.get("winrm_password")
        password = decrypt_secret(raw_password) if raw_password else None
        if not username or not password:
            return None

        # Require winrm=True flag and a proper WinRM port (≥5985) to distinguish
        # from SSH-only servers that also have username/password in connection_config.
        winrm_port = cfg.get("winrm_port")
        is_winrm = bool(cfg.get("winrm")) and winrm_port and int(winrm_port) >= 5985
        if not is_winrm:
            return None

        host = (server.ip_address or "").strip() or (server.hostname or "").strip()
        if not host:
            return None

        try:
            from app.services.runtime_settings import get_int
            default_to = get_int("winrm_timeout_sec")
        except Exception:
            default_to = 30
        return cls(
            host=host,
            username=username,
            password=password,
            port=int(winrm_port),
            use_https=bool(cfg.get("winrm_https")),
            timeout=cfg.get("timeout") or default_to,
        )
