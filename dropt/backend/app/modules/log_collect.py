from __future__ import annotations

import shlex
from typing import Any

import paramiko
from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.artifacts import job_artifact_dir
from app.services.privilege import elevate_command
from app.services.target_ssh import connect_user, run_ssh
from app.services.ssh_probe import load_portal_private_key

ACTION_TITLES = {
    "package": "Log paketi hazırla",
}

# Whitelist templates — free path entry is not allowed
TEMPLATES: dict[str, dict[str, Any]] = {
    "system": {
        "label": "Sistem (journal + messages/secure)",
        "paths": ["/var/log/messages", "/var/log/secure", "/var/log/syslog", "/var/log/auth.log"],
        "include_journal": True,
    },
    "journal": {
        "label": "Yalnızca journalctl",
        "paths": [],
        "include_journal": True,
    },
    "messages": {
        "label": "messages / syslog",
        "paths": ["/var/log/messages", "/var/log/syslog"],
        "include_journal": False,
    },
}

DEFAULT_MAX_MB = 100
ALLOWED_HOURS = {1, 6, 24}


def list_templates() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": val["label"], "paths": val["paths"], "include_journal": val["include_journal"]}
        for key, val in TEMPLATES.items()
    ]


def job_summary(action: str, payload: dict[str, Any]) -> str:
    title = ACTION_TITLES.get(action, action)
    hours = payload.get("hours", 1)
    template = payload.get("template", "system")
    return f"{title}: son {hours} saat · şablon={template}"


def _connect_user(session: Session, server: TargetServer) -> tuple[str, str | None]:
    return connect_user(session, server)


def _ssh_client(session: Session, server: TargetServer, timeout: float = 30.0) -> paramiko.SSHClient:
    username, password = _connect_user(session, server)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict[str, Any] = {
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
    return client


def _normalize_payload(payload: dict[str, Any]) -> tuple[int, str, int, dict[str, Any]]:
    hours = int(payload.get("hours") or 1)
    if hours not in ALLOWED_HOURS:
        raise ValueError("Süre 1, 6 veya 24 saat olmalı")
    template_id = str(payload.get("template") or "system")
    if template_id not in TEMPLATES:
        raise ValueError("Geçersiz log şablonu")
    max_mb = int(payload.get("max_mb") or DEFAULT_MAX_MB)
    if max_mb < 1 or max_mb > 200:
        raise ValueError("Maksimum paket boyutu 1–200 MB olmalı")
    return hours, template_id, max_mb, TEMPLATES[template_id]


def build_plans(
    session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]
) -> list[HostPlan]:
    if action != "package":
        return [
            HostPlan(
                server_id=s.id,  # type: ignore[arg-type]
                hostname=s.hostname,
                ip=s.ip,
                ok=False,
                summary_tr=f"Bilinmeyen aksiyon: {action}",
                error="Bilinmeyen aksiyon",
            )
            for s in servers
        ]

    try:
        hours, template_id, max_mb, tmpl = _normalize_payload(payload)
    except ValueError as exc:
        return [
            HostPlan(
                server_id=s.id,  # type: ignore[arg-type]
                hostname=s.hostname,
                ip=s.ip,
                ok=False,
                summary_tr=str(exc),
                error=str(exc),
            )
            for s in servers
        ]

    plans: list[HostPlan] = []
    for server in servers:
        try:
            probe = run_ssh(session, server, "echo ok && df -Pm /tmp | tail -1", timeout=15)
            if not probe.ok:
                plans.append(
                    HostPlan(
                        server_id=server.id,  # type: ignore[arg-type]
                        hostname=server.hostname,
                        ip=server.ip,
                        ok=False,
                        summary_tr=f"{server.hostname}: erişilemedi",
                        error=probe.stderr.strip() or f"exit {probe.exit_code}",
                    )
                )
                continue

            sources = []
            if tmpl["include_journal"]:
                sources.append(f"journalctl (son {hours} saat)")
            for p in tmpl["paths"]:
                sources.append(p)

            cmds = [
                f"# şablon={template_id} max={max_mb}MB",
                f"journalctl --since '{hours} hour ago'  # include={tmpl['include_journal']}",
                *[f"include if exists: {p}" for p in tmpl["paths"]],
                "tar czf /tmp/dropt-logs-….tgz …",
            ]
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=(
                        f"{server.hostname}: son {hours} saat · {tmpl['label']} · "
                        f"limit {max_mb} MB (aşılırsa kesilir)"
                    ),
                    planned_commands=cmds,
                    before_state={"sources": sources, "template": template_id, "hours": hours, "max_mb": max_mb},
                    risk_notes="Salt okuma; yazma yok. Paket içeriği DB’ye yazılmaz.",
                )
            )
        except Exception as exc:  # noqa: BLE001
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


def _remote_collect_script(hours: int, paths: list[str], include_journal: bool, max_mb: int) -> str:
    path_list = " ".join(shlex.quote(p) for p in paths)
    journal_flag = "1" if include_journal else "0"
    # Produce ARCHIVE path on stdout last line: ARCHIVE=/tmp/...
    return f"""
set -e
WORKDIR=$(mktemp -d /tmp/dropt-logs.XXXXXX)
ARCHIVE=/tmp/dropt-logs-$(date +%s).tgz
MAX_BYTES=$(( {max_mb} * 1024 * 1024 ))
INCLUDE_JOURNAL={journal_flag}
HOURS={hours}

if [ "$INCLUDE_JOURNAL" = "1" ]; then
  journalctl --since "${{HOURS}} hour ago" --no-pager > "$WORKDIR/journalctl.txt" 2>"$WORKDIR/journalctl.err" || true
fi

for P in {path_list}; do
  if [ -f "$P" ]; then
    BN=$(basename "$P")
    # copy last ~max_mb of file if huge
    SIZE=$(stat -c%s "$P" 2>/dev/null || stat -f%z "$P" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt "$MAX_BYTES" ]; then
      tail -c "$MAX_BYTES" "$P" > "$WORKDIR/$BN" || true
    else
      cp -a "$P" "$WORKDIR/$BN" || true
    fi
  fi
done

# rough size check of workdir
DIR_BYTES=$(du -sb "$WORKDIR" 2>/dev/null | awk '{{print $1}}' || echo 0)
if [ "$DIR_BYTES" -gt "$MAX_BYTES" ]; then
  # shrink journal first
  if [ -f "$WORKDIR/journalctl.txt" ]; then
    tail -c $(( MAX_BYTES / 2 )) "$WORKDIR/journalctl.txt" > "$WORKDIR/journalctl.txt.trim" || true
    mv "$WORKDIR/journalctl.txt.trim" "$WORKDIR/journalctl.txt"
  fi
fi

tar czf "$ARCHIVE" -C "$WORKDIR" .
rm -rf "$WORKDIR"
SIZE=$(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE")
echo "ARCHIVE=$ARCHIVE"
echo "SIZE=$SIZE"
"""


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int,
) -> tuple[bool, dict[str, Any], str, str]:
    if action != "package" or not plan.ok:
        return False, plan.before_state, "", plan.error or "Plan uygulanamaz"

    hours, template_id, max_mb, tmpl = _normalize_payload(payload)
    script = _remote_collect_script(hours, list(tmpl["paths"]), bool(tmpl["include_journal"]), max_mb)
    remote = elevate_command(session, script)

    client = None
    try:
        client = _ssh_client(session, server, timeout=60)
        _stdin, stdout, stderr = client.exec_command(remote, timeout=180)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if exit_code != 0:
            return False, plan.before_state, out, err or f"exit {exit_code}"

        remote_path = ""
        size = 0
        for line in out.splitlines():
            if line.startswith("ARCHIVE="):
                remote_path = line.split("=", 1)[1].strip()
            if line.startswith("SIZE="):
                try:
                    size = int(line.split("=", 1)[1].strip())
                except ValueError:
                    size = 0
        if not remote_path:
            return False, plan.before_state, out, "Arşiv yolu alınamadı"

        local_dir = job_artifact_dir(job_id)
        filename = f"{server.hostname.replace('/', '_')}-{server.id}.tgz"
        local_path = local_dir / filename

        sftp = client.open_sftp()
        try:
            sftp.get(remote_path, str(local_path))
            # cleanup remote
            client.exec_command(f"rm -f {shlex.quote(remote_path)}", timeout=30)
        finally:
            sftp.close()

        actual_size = local_path.stat().st_size if local_path.exists() else size
        after = {
            **plan.before_state,
            "template": template_id,
            "hours": hours,
            "max_mb": max_mb,
            "artifact_filename": filename,
            "artifact_path": str(local_path),
            "artifact_size_bytes": actual_size,
            "downloadable": True,
        }
        summary_out = f"Paket hazır: {filename} ({actual_size} bayt)"
        return True, after, summary_out + "\n" + out, err
    except Exception as exc:  # noqa: BLE001
        return False, plan.before_state, "", str(exc)
    finally:
        if client is not None:
            client.close()
