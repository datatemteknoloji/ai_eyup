from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"set": "Path sahibi/izin ayarla"}

MODE_TEMPLATES = {
    "750": {"label": "Sahip rwx, grup rx (750)", "mode": "750"},
    "740": {"label": "Sahip rwx, grup r (740)", "mode": "740"},
    "700": {"label": "Sadece sahip (700)", "mode": "700"},
    "640": {"label": "Sahip rw, grup r (640)", "mode": "640"},
    "600": {"label": "Sadece sahip dosya (600)", "mode": "600"},
}

CRITICAL_EXACT = frozenset(
    {
        "/",
        "/etc",
        "/boot",
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/root",
        "/dev",
        "/proc",
        "/sys",
        "/run",
        "/var/run",
    }
)
CRITICAL_PREFIXES = (
    "/etc/",
    "/boot/",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/lib/",
    "/lib64/",
    "/root/",
    "/dev/",
    "/proc/",
    "/sys/",
    "/run/",
)

PATH_RE = re.compile(r"^/[A-Za-z0-9._+/-]+$")


def list_whitelist() -> list[dict[str, Any]]:
    """Deprecated: free-text path; kept for API compatibility."""
    return []


def list_mode_templates() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in MODE_TEMPLATES.items()]


def job_summary(action: str, payload: dict[str, Any]) -> str:
    return f"{ACTION_TITLES.get(action, action)}: {payload.get('path')}"


def _normalize_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        raise ValueError("Path zorunlu")
    if ".." in path.split("/"):
        raise ValueError("Path içinde '..' olamaz")
    if "\x00" in path or any(c.isspace() for c in path):
        raise ValueError("Path geçersiz karakter içeriyor")
    if not path.startswith("/"):
        raise ValueError("Path mutlak olmalı ( / ile başlamalı )")
    # collapse duplicate slashes except leading
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1:
        path = path.rstrip("/")
    if not PATH_RE.match(path):
        raise ValueError("Path yalnızca güvenli karakterler içermeli")
    return path


def _is_critical(path: str) -> bool:
    if path in CRITICAL_EXACT:
        return True
    return any(path.startswith(p) for p in CRITICAL_PREFIXES)


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "set":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            path = _normalize_path(payload.get("path") or "")
            owner = (payload.get("owner") or "").strip()
            group = (payload.get("group") or "").strip()
            mode = (payload.get("mode") or "").strip()
            recursive = bool(payload.get("recursive", False))
            if _is_critical(path):
                raise ValueError("Kritik sistem path'ine izin verilmez")
            if not owner or not group or not mode:
                raise ValueError("owner, group, mode zorunlu")
            if mode not in MODE_TEMPLATES and not (len(mode) in {3, 4} and mode.isdigit()):
                raise ValueError("Geçersiz izin şablonu")
            mode_val = MODE_TEMPLATES.get(mode, {}).get("mode", mode)
            chk = run_ssh(
                session,
                server,
                f"test -e {shlex.quote(path)} && getent passwd {shlex.quote(owner)} >/dev/null "
                f"&& getent group {shlex.quote(group)} >/dev/null "
                f"&& stat -c '%U:%G %a' {shlex.quote(path)}",
                timeout=20,
            )
            if not chk.ok:
                raise ValueError(
                    f"Path sunucuda yok veya user/group bulunamadı: {chk.stderr or chk.stdout or path}"
                )
            before_stat = chk.stdout.strip()
            chown = f"chown {'-R ' if recursive else ''}{shlex.quote(owner)}:{shlex.quote(group)} {shlex.quote(path)}"
            chmod = f"chmod {'-R ' if recursive else ''}{shlex.quote(mode_val)} {shlex.quote(path)}"
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: {path} → {owner}:{group} {mode_val}"
                    + (" (recursive)" if recursive else ""),
                    planned_commands=[chown, chmod, f"stat -c '%U:%G %a' {shlex.quote(path)}"],
                    before_state={
                        "path": path,
                        "stat": before_stat,
                        "owner": owner,
                        "group": group,
                        "mode": mode_val,
                        "recursive": recursive,
                    },
                    risk_notes="Recursive açıksa alt ağaç da değişir." if recursive else "Yalnız seçilen path.",
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


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    _ = (job_id, action, payload)
    if not plan.ok:
        return False, plan.before_state, "", plan.error
    out, err = [], []
    for cmd in plan.planned_commands:
        r = run_ssh(session, server, cmd, timeout=60)
        out.append(r.stdout)
        err.append(r.stderr)
        if not r.ok and not cmd.startswith("stat "):
            return False, plan.before_state, "\n".join(out), "\n".join(err)
    after = {**plan.before_state, "stat_after": (out[-1] if out else "").strip()}
    return True, after, "\n".join(out), "\n".join(err)
