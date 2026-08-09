from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules import pkg_common
from app.modules.base import HostPlan
from app.services import package_repo_store as store
from app.services.bootstrap import get_smtp_host, get_smtp_test_mail
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"configure": "Mail (sendmail) yapılandır"}

_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")


def job_summary(action: str, payload: dict[str, Any]) -> str:
    host = (payload.get("smtp_host") or "").strip()
    return f"{ACTION_TITLES.get(action, action)}: DS {host}" if host else ACTION_TITLES.get(action, action)


def _validate_smtp_host(host: str) -> str:
    h = (host or "").strip()
    if not h:
        raise ValueError("SMTP host tanımlı değil — Ayarlar → Mail / SMTP")
    if not _HOST_RE.match(h) or ".." in h:
        raise ValueError(f"Geçersiz SMTP host: {h}")
    return h


def _ds_edit_script(smtp_host: str) -> str:
    """Replace first smart-host DS line: DS<host> or 'DS host' → user format 'DS host'."""
    import base64

    py = f"""
from pathlib import Path
conf = Path("/etc/mail/sendmail.cf")
host = {smtp_host!r}
new_line = "DS" + host
text = conf.read_text(errors="replace")
lines = text.splitlines(keepends=True)
out = []
replaced = False
for line in lines:
    raw = line.rstrip("\\r\\n")
    if (raw == "DS" or raw.startswith("DS")) and not replaced:
        nl = "\\n" if line.endswith("\\n") else ""
        out.append(new_line + nl)
        replaced = True
        continue
    out.append(line)
if not replaced:
    if out and not str(out[-1]).endswith("\\n"):
        out[-1] = str(out[-1]) + "\\n"
    out.append(new_line + "\\n")
conf.write_text("".join(out))
print("DS_UPDATED", host)
"""
    b64 = base64.b64encode(py.encode()).decode("ascii")
    return f"""
set -e
CONF=/etc/mail/sendmail.cf
[ -f "$CONF" ]
cp -a "$CONF" "$CONF.bak.$(date +%s)"
echo {shlex.quote(b64)} | base64 -d | python3
grep -n '^DS' "$CONF" | head -n 5
echo DS_OK
"""


def _smtp_port_check_script(smtp_host: str) -> str:
    h = shlex.quote(smtp_host)
    return f"""
set +e
HOST={h}
timeout 8 bash -c "exec 3<>/dev/tcp/$HOST/25" 2>/dev/null
RC=$?
if [ "$RC" -eq 0 ]; then
  echo SMTP_PORT_OK
else
  if command -v nc >/dev/null 2>&1; then
    timeout 8 nc -z -w 5 "$HOST" 25 >/dev/null 2>&1 && echo SMTP_PORT_OK || echo SMTP_PORT_FAIL
  elif command -v telnet >/dev/null 2>&1; then
    printf '\\x1d\\n' | timeout 8 telnet "$HOST" 25 2>&1 | grep -Eiq 'Connected|Escape|220' && echo SMTP_PORT_OK || echo SMTP_PORT_FAIL
  else
    echo SMTP_PORT_FAIL
  fi
fi
"""


def _sendmail_test_script(to_addr: str) -> str:
    to = shlex.quote(to_addr)
    return f"""
set +e
TO={to}
printf '%s\\n' 'Subject: this is the subject' '' 'This is a test mail' | sendmail -v -- "$TO"
RC=$?
if [ "$RC" -eq 0 ]; then
  echo SENDMAIL_TEST_OK
else
  echo SENDMAIL_TEST_FAIL exit=$RC
fi
exit 0
"""


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    try:
        if action != "configure":
            raise ValueError(f"Bilinmeyen aksiyon: {action}")
        smtp_host = _validate_smtp_host(get_smtp_host(session) or str(payload.get("smtp_host") or ""))
        test_mail = get_smtp_test_mail(session) or str(payload.get("smtp_test_mail") or "").strip()

        for server in servers:
            osinfo = store.read_target_os(session, server)
            os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
            creds = None
            if os_id and major:
                creds = store.get_subscription_creds_optional(session, os_id, major)

            cmds: list[str] = [
                "dnf remove -y 'postfix*' || true",
            ]
            if creds:
                cmds.append("# subscription wipe + register (install sonrası wipe YOK)")
            else:
                cmds.append("# subscription atlandı (key yok — mevcut kayıt ile dnf)")
            cmds.extend(
                [
                    "dnf install -y sendmail sendmail-cf",
                    "chmod 773 /var/spool/clientmqueue",
                    f"# /etc/mail/sendmail.cf → DS {smtp_host}",
                    "systemctl enable sendmail",
                    "systemctl start sendmail",
                    "systemctl status sendmail --no-pager -l | head -n 20",
                ]
            )
            if smtp_host:
                cmds.append(f"# opsiyonel: SMTP 25 erişim → {smtp_host}")
            if test_mail:
                cmds.append(f"# opsiyonel: test mail → {test_mail}")

            risk = (
                "Talep eden ekibin ÇM üzerinden Relay için Uygulama Üzerinden Mail Gönderim "
                "talebini oluşturması gerekmektedir."
            )
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: sendmail + DS {smtp_host}",
                    planned_commands=cmds,
                    before_state={
                        "smtp_host": smtp_host,
                        "smtp_test_mail": test_mail,
                        "use_subscription": bool(creds),
                        "os_id": os_id,
                        "version_major": major,
                    },
                    risk_notes=risk,
                )
            )
    except Exception as exc:  # noqa: BLE001
        for server in servers:
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: önizleme hatası",
                    error=str(exc),
                )
            )
    return plans


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    _ = (action, payload, job_id)
    if not plan.ok:
        return False, plan.before_state, "", plan.error

    smtp_host = _validate_smtp_host(
        str(plan.before_state.get("smtp_host") or get_smtp_host(session) or "")
    )
    test_mail = str(plan.before_state.get("smtp_test_mail") or get_smtp_test_mail(session) or "").strip()

    osinfo = store.read_target_os(session, server)
    os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
    creds = store.get_subscription_creds_optional(session, os_id, major) if os_id and major else None
    redacts: list[str] = []
    if creds:
        redacts.append(creds[1])

    cmds: list[str] = [
        "set +e\ndnf remove -y 'postfix*' 2>/dev/null || true\necho POSTFIX_REMOVE_DONE\n",
    ]
    if creds:
        cmds.append(pkg_common.subscription_wipe_script())
        cmds.append(pkg_common.subscription_register_script(creds[0], creds[1]))
    cmds.append("set -e\ndnf install -y sendmail sendmail-cf\necho DNF_INSTALL_OK\n")
    cmds.append(
        "set -e\n"
        "mkdir -p /var/spool/clientmqueue\n"
        "chmod 773 /var/spool/clientmqueue\n"
        "echo CHMOD_OK\n"
    )
    cmds.append(_ds_edit_script(smtp_host))
    cmds.append(
        "set -e\n"
        "systemctl enable sendmail\n"
        "systemctl start sendmail\n"
        "systemctl is-active sendmail\n"
        "systemctl status sendmail --no-pager -l | head -n 25\n"
        "echo SENDMAIL_SERVICE_OK\n"
    )

    ok, logs, err = pkg_common.run_steps(session, server, cmds, redact_substrings=redacts, timeout=900)
    if not ok:
        return False, {**plan.before_state, "phase": "configure"}, logs, err

    after: dict[str, Any] = {
        **plan.before_state,
        "smtp_host": smtp_host,
        "configured": True,
        "checklist": [
            "ÇM Relay talebinin açıldığını doğrula",
            "SMTP 25 ve test mail sonuçlarını kontrol et",
        ],
    }

    port_ok: bool | None = None
    if smtp_host:
        pr = run_ssh(session, server, _smtp_port_check_script(smtp_host), timeout=30)
        port_log = (pr.stdout or "") + (("\n" + pr.stderr) if pr.stderr else "")
        logs = logs + "\n--- optional: smtp port 25 ---\n" + port_log
        port_ok = "SMTP_PORT_OK" in port_log
        after["smtp_port_ok"] = port_ok
        after["smtp_port_detail"] = (
            f"SMTP {smtp_host}:25 erişim başarılı" if port_ok else f"SMTP {smtp_host}:25 erişim başarısız (opsiyonel)"
        )

    mail_ok: bool | None = None
    if test_mail:
        mr = run_ssh(session, server, _sendmail_test_script(test_mail), timeout=60)
        mail_log = (mr.stdout or "") + (("\n" + mr.stderr) if mr.stderr else "")
        logs = logs + "\n--- optional: sendmail test ---\n" + mail_log
        mail_ok = "SENDMAIL_TEST_OK" in mail_log
        after["smtp_test_mail"] = test_mail
        after["sendmail_test_ok"] = mail_ok
        after["sendmail_test_detail"] = (
            "Test maili başarıyla iletildi" if mail_ok else "Test mail gönderimi başarısız (opsiyonel)"
        )
    else:
        after["sendmail_test_ok"] = None
        after["sendmail_test_detail"] = "Test mail adresi tanımlı değil — atlandı"

    notes: list[str] = []
    if port_ok is not None:
        notes.append(str(after.get("smtp_port_detail") or ""))
    if after.get("sendmail_test_detail"):
        notes.append(str(after["sendmail_test_detail"]))
    after["optional_notes"] = [n for n in notes if n]

    return True, after, logs, ""
