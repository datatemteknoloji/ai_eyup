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
    sudo_password_override: Optional[str] = None,
    actor_name: Optional[str] = None,
) -> Dict:
    """
    Tek bir sunucuda komut çalıştırır. policy engine'den geçmeyen komut çalışmaz.

    Returns: {ok, stdout, stderr, command, server, error}
    """
    def _audit(status: str, err: str = "") -> None:
        try:
            from app.services.audit import record_audit
            record_audit(db, category="ssh", action="ssh.exec", status=status,
                         actor=actor_name, target_type="server",
                         target_id=getattr(server, "id", None),
                         server_id=getattr(server, "id", None),
                         summary=f"{getattr(server, 'name', '?')}: {command[:140]}",
                         detail={"sudo": allow_sudo, "error": err[:300] if err else None})
        except Exception:
            pass

    risk = classify_command(command)
    if risk == RiskLevel.DENIED:
        logger.warning(f"[AgentExecutor] DENIED komut ({server.name}): {command[:120]}")
        _audit("blocked", "policy denied")
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
        # Transient override (kullanıcının onayda girdiği root şifresi) varsa onu kullan;
        # bu şifre DB'ye yazılmaz, yalnızca bu çağrı için bellekte tutulur.
        sudo_password=sudo_password_override or cred.sudo_password,
    )

    if not ssh.connect():
        logger.warning(f"[AgentExecutor] SSH bağlanamadı: {server.name}")
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name,
            "error": "SSH bağlantısı kurulamadı.",
        }

    def _perm_denied(out: str, err: str) -> bool:
        combined = (out + err).lower()
        return (
            "permission denied" in combined
            or "permision denied" in combined
            # journalctl özel mesajı: "insufficient permissions" / "erişim izni yetersiz"
            or "insufficient permission" in combined
            or "must be superuser" in combined
            or "operation not permitted" in combined
        )

    try:
        success, stdout, stderr = ssh.execute_command(
            exec_cmd, use_sudo=use_sudo, cmd_timeout=timeout
        )

        # ── Permission-denied auto-retry ───────────────────────────────────
        # READ_ONLY araçlar (journalctl, dmesg…) allow_sudo=True ile işaretlenir;
        # sudo prefix olmasa da erişim reddedilirse stored/override şifresiyle retry.
        if (
            not success
            and allow_sudo
            and not use_sudo
            and _perm_denied(stdout, stderr)
        ):
            sudo_pwd = sudo_password_override or (cred.sudo_password if cred else None)

            if sudo_pwd:
                logger.info(f"[AgentExecutor] Permission denied → sudo retry: {server.name} {exec_cmd[:60]}")
                try:
                    success2, stdout2, stderr2 = ssh.execute_command(
                        exec_cmd, use_sudo=True, cmd_timeout=timeout
                    )
                    result = {
                        "ok": bool(success2),
                        "stdout": _truncate(stdout2),
                        "stderr": _truncate(stderr2),
                        "command": command,
                        "server": server.name,
                        "error": "" if success2 else (stderr2.strip()[:500] if stderr2 else "Komut başarısız"),
                        "ran_as_sudo": True,
                    }
                    _audit("success" if success2 else "failure", "" if success2 else (stderr2 or ""))
                    return result
                except Exception as re_exc:
                    logger.warning(f"[AgentExecutor] Sudo retry exception: {re_exc}")
                    # Retry başarısız → orijinal sonucu döndür
            else:
                # Sudo şifresi yok → needs_sudo sinyali gönder
                _audit("failure", "permission denied — needs_sudo")
                return {
                    "ok": False,
                    "stdout": _truncate(stdout),
                    "stderr": _truncate(stderr),
                    "command": command,
                    "server": server.name,
                    "error": "Bu komut root yetkisi gerektiriyor (permission denied).",
                    "needs_sudo": True,
                }

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
        _audit("success" if success else "failure", "" if success else (stderr or ""))
        return result
    except Exception as e:
        logger.error(f"[AgentExecutor] Komut hatası ({server.name}): {e}")
        _audit("failure", str(e))
        return {
            "ok": False, "stdout": "", "stderr": "",
            "command": command, "server": server.name, "error": str(e),
        }
    finally:
        ssh.close()
