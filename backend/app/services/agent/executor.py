"""
Agent Executor — tool'ların gerçek yan etkilerini (SSH komutları) güvenli çalıştırır.

Güvenlik sınırları:
  - Her komut policy.classify_command'dan geçer; DENIED ise asla çalışmaz.
  - cmd_timeout zorunlu (varsayılan 30sn, mutating için daha uzun).
  - Çıktı boyutu MAX_OUTPUT_CHARS ile sınırlanır (LLM'e dönmeden önce).
  - sudo yalnızca açıkça allow_sudo=True verilen (onaylı mutating) çağrılarda.
  - Tüm çalıştırmalar activity_logger ile denetim kaydına yazılır.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.ssh_manager import SSHManager
from app.services.agent.policy import classify_command, RiskLevel

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 12000


def get_default_credential(db: Session) -> Optional[GlobalCredential]:
    return (
        db.query(GlobalCredential)
        .filter(GlobalCredential.is_default == True)  # noqa: E712
        .first()
    )


def _truncate(text: str) -> str:
    if text and len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + f"\n... [çıktı {len(text)} karaktere kadar kesildi]"
    return text or ""


def run_ssh_command(
    db: Session,
    server: Server,
    command: str,
    *,
    allow_sudo: bool = False,
    timeout: int = 30,
    session_id: Optional[int] = None,
) -> Dict:
    """
    Tek bir sunucuda komut çalıştırır. policy engine'den geçmeyen komut çalışmaz.

    Returns: {ok, stdout, stderr, command, server, error}
    """
    risk = classify_command(command)
    if risk == RiskLevel.DENIED:
        logger.warning(f"[AgentExecutor] DENIED komut ({server.name}): {command[:120]}")
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name,
            "error": "Komut güvenlik politikası tarafından reddedildi (yıkıcı/yasaklı).",
        }

    use_sudo = allow_sudo and command.strip().startswith("sudo ")
    exec_cmd = command.strip()
    if use_sudo:
        # SSHManager sudo'yu kendi sarmalıyor; baştaki 'sudo ' kısmını ayıkla
        exec_cmd = exec_cmd[len("sudo "):].strip()

    cred = get_default_credential(db)
    if not cred:
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name,
            "error": "Varsayılan SSH kimlik bilgisi bulunamadı.",
        }

    ssh = SSHManager(
        host=server.ip_address,
        username=cred.username,
        password=cred.password,
        private_key=cred.private_key,
        port=cred.port or 22,
        sudo_password=cred.sudo_password,
    )

    if not ssh.connect():
        logger.warning(f"[AgentExecutor] SSH bağlanamadı: {server.name}")
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name,
            "error": "SSH bağlantısı kurulamadı.",
        }

    try:
        success, stdout, stderr = ssh.execute_command(
            exec_cmd, use_sudo=use_sudo, cmd_timeout=timeout
        )
        result = {
            "ok": bool(success),
            "stdout": _truncate(stdout),
            "stderr": _truncate(stderr),
            "command": command,
            "server": server.name,
            "error": "" if success else (stderr.strip()[:500] if stderr else "Komut başarısız"),
        }
        logger.info(
            f"[AgentExecutor] {server.name} risk={risk.value} sudo={use_sudo} "
            f"ok={success} cmd={command[:80]}"
        )
        return result
    except Exception as e:
        logger.error(f"[AgentExecutor] Komut hatası ({server.name}): {e}")
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name, "error": str(e),
        }
    finally:
        ssh.close()
