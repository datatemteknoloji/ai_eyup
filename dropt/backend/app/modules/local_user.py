from __future__ import annotations

import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.protected_users import is_protected_uid, is_protected_username
from app.services.ssh_exec import ExecResult
from app.services.target_ssh import run_ssh


def _run(
    session: Session,
    server: TargetServer,
    command: str,
    *,
    timeout: float = 30.0,
) -> ExecResult:
    return run_ssh(session, server, command, timeout=timeout)


def parse_passwd_status(line: str) -> dict[str, Any]:
    """Parse `passwd -S user` → status fields."""
    parts = line.strip().split()
    if len(parts) < 2:
        return {"exists": False, "raw": line}
    status_code = parts[1]
    mapping = {
        "P": "active",
        "PS": "active",
        "L": "locked",
        "LK": "locked",
        "NP": "no_password",
    }
    return {
        "exists": True,
        "username": parts[0],
        "status_code": status_code,
        "status": mapping.get(status_code, status_code),
        "raw": line.strip(),
    }


def get_user_state(session: Session, server: TargetServer, username: str) -> dict[str, Any]:
    u = shlex.quote(username)
    ent = _run(session, server, f"getent passwd {u} || true")
    if not ent.stdout.strip():
        return {"exists": False, "username": username}
    # name:passwd:uid:gid:gecos:home:shell
    fields = ent.stdout.strip().split(":")
    uid = int(fields[2]) if len(fields) > 2 and fields[2].isdigit() else None
    gid = int(fields[3]) if len(fields) > 3 and fields[3].isdigit() else None
    home = fields[5] if len(fields) > 5 else ""
    shell = fields[6] if len(fields) > 6 else ""
    groups = _run(session, server, f"id -nG {u} 2>/dev/null || true")
    status = _run(session, server, f"passwd -S {u} 2>/dev/null || true")
    st = parse_passwd_status(status.stdout.splitlines()[0] if status.stdout.strip() else "")
    return {
        "exists": True,
        "username": username,
        "uid": uid,
        "gid": gid,
        "home": home,
        "shell": shell,
        "groups": groups.stdout.strip().split() if groups.stdout.strip() else [],
        "status": st.get("status", "unknown"),
        "status_code": st.get("status_code"),
        "protected": is_protected_username(username) or is_protected_uid(uid),
    }


def list_local_users(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    """List human-ish accounts (UID >= 1000) plus note system count."""
    script = r"""
getent passwd | awk -F: '$3 >= 1000 || $1=="root" {print $1":"$3":"$6":"$7}'
"""
    result = _run(session, server, script.strip(), timeout=20)
    if not result.ok and not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or f"Kullanıcı listesi alınamadı (exit {result.exit_code})")

    users: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 4:
            continue
        name, uid_s, home, shell = parts[0], parts[1], parts[2], parts[3]
        uid = int(uid_s) if uid_s.isdigit() else None
        st = _run(session, server, f"passwd -S {shlex.quote(name)} 2>/dev/null || true")
        parsed = parse_passwd_status(st.stdout.splitlines()[0] if st.stdout.strip() else "")
        grp = _run(session, server, f"id -nG {shlex.quote(name)} 2>/dev/null || true")
        users.append(
            {
                "username": name,
                "uid": uid,
                "home": home,
                "shell": shell,
                "groups": grp.stdout.strip().split() if grp.stdout.strip() else [],
                "status": parsed.get("status", "unknown"),
                "protected": is_protected_username(name) or is_protected_uid(uid),
            }
        )
    users.sort(key=lambda u: (0 if u["username"] == "root" else 1, u["username"]))
    return users


def _validate_username(username: str) -> str:
    name = username.strip()
    if not name or len(name) > 32:
        raise ValueError("Kullanıcı adı geçersiz")
    if not all(c.isalnum() or c in "._-" for c in name):
        raise ValueError("Kullanıcı adı yalnızca harf, rakam, ._- içerebilir")
    if is_protected_username(name):
        raise ValueError(f"'{name}' korunan hesaptır; işlem yapılamaz")
    return name


def plan_create(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    username = _validate_username(payload.get("username", ""))
    groups = [g.strip() for g in (payload.get("groups") or []) if str(g).strip()]
    force_change = bool(payload.get("force_password_change", False))
    before = get_user_state(session, server, username)
    if before.get("exists"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' zaten var",
            before_state=before,
            error="Kullanıcı zaten mevcut",
        )
    cmds = [
        f"useradd -m {shlex.quote(username)}"
        + (f" -G {shlex.quote(','.join(groups))}" if groups else ""),
        f"echo {shlex.quote(username)}:'***' | chpasswd",
    ]
    if force_change:
        cmds.append(f"chage -d 0 {shlex.quote(username)}")
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=f"{server.hostname}: '{username}' oluşturulacak"
        + (f" (gruplar: {', '.join(groups)})" if groups else ""),
        planned_commands=cmds,
        before_state=before,
        risk_notes="Yeni yerel hesap açılacak.",
    )


def plan_lock_unlock(
    session: Session, server: TargetServer, payload: dict[str, Any], *, lock: bool
) -> HostPlan:
    username = _validate_username(payload.get("username", ""))
    before = get_user_state(session, server, username)
    if not before.get("exists"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' bulunamadı",
            before_state=before,
            error="Kullanıcı yok",
        )
    if before.get("protected"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' korunan hesap",
            before_state=before,
            error="Korunan hesap",
        )
    cmd = f"usermod {'-L' if lock else '-U'} {shlex.quote(username)}"
    verb = "kilitlenecek" if lock else "kilidi açılacak"
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=f"{server.hostname}: '{username}' {verb} (şu an: {before.get('status')})",
        planned_commands=[cmd, f"passwd -S {shlex.quote(username)}"],
        before_state=before,
        risk_notes="Hesap giriş yapamayacak." if lock else "Hesap tekrar giriş yapabilecek.",
    )


def plan_delete(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    username = _validate_username(payload.get("username", ""))
    remove_home = bool(payload.get("remove_home", False))
    backup_home = bool(payload.get("backup_home", False))
    before = get_user_state(session, server, username)
    if not before.get("exists"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' bulunamadı",
            before_state=before,
            error="Kullanıcı yok",
        )
    if before.get("protected"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' korunan hesap",
            before_state=before,
            error="Korunan hesap",
        )
    cmds: list[str] = []
    home = before.get("home") or f"/home/{username}"
    if backup_home:
        cmds.append(f"tar czf /var/tmp/{shlex.quote(username)}-home-backup.tgz -C / {shlex.quote(home.lstrip('/'))}")
    if remove_home:
        cmds.append(f"userdel -r {shlex.quote(username)}")
    else:
        cmds.append(f"userdel {shlex.quote(username)}")
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=f"{server.hostname}: '{username}' silinecek"
        + (" (ev dizini dahil)" if remove_home else "")
        + (" + yedek" if backup_home else ""),
        planned_commands=cmds,
        before_state=before,
        risk_notes="Silme geri alınamaz.",
    )


def plan_password_reset(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    username = _validate_username(payload.get("username", ""))
    before = get_user_state(session, server, username)
    if not before.get("exists"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' bulunamadı",
            before_state=before,
            error="Kullanıcı yok",
        )
    if before.get("protected"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' korunan hesap",
            before_state=before,
            error="Korunan hesap",
        )
    force = bool(payload.get("force_password_change", True))
    cmds = [f"echo {shlex.quote(username)}:'***' | chpasswd"]
    if force:
        cmds.append(f"chage -d 0 {shlex.quote(username)}")
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=f"{server.hostname}: '{username}' şifresi sıfırlanacak"
        + (" (ilk girişte değiştir)" if force else ""),
        planned_commands=cmds,
        before_state=before,
        risk_notes="Yeni parola uygulanacak.",
    )


def plan_expire(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    username = _validate_username(payload.get("username", ""))
    before = get_user_state(session, server, username)
    if not before.get("exists"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' bulunamadı",
            before_state=before,
            error="Kullanıcı yok",
        )
    if before.get("protected"):
        return HostPlan(
            server_id=server.id,  # type: ignore[arg-type]
            hostname=server.hostname,
            ip=server.ip,
            ok=False,
            summary_tr=f"{server.hostname}: '{username}' korunan hesap",
            before_state=before,
            error="Korunan hesap",
        )
    # expire_days: 0 = never, or YYYY-MM-DD date string in expire_date
    expire_date = (payload.get("expire_date") or "").strip()
    expire_days = payload.get("expire_days")
    if expire_date:
        cmd = f"chage -E {shlex.quote(expire_date)} {shlex.quote(username)}"
        summary = f"son kullanım {expire_date}"
    elif expire_days is not None:
        days = int(expire_days)
        cmd = f"chage -E {days} {shlex.quote(username)}" if days >= 0 else f"chage -E -1 {shlex.quote(username)}"
        summary = "süre kaldırılacak" if days < 0 else f"{days} gün sonra expire"
    else:
        raise ValueError("expire_date veya expire_days gerekli")
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=f"{server.hostname}: '{username}' {summary}",
        planned_commands=[cmd, f"chage -l {shlex.quote(username)}"],
        before_state=before,
        risk_notes="Hesap süre sınırı güncellenecek.",
    )


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action == "create":
                plans.append(plan_create(session, server, payload))
            elif action == "lock":
                plans.append(plan_lock_unlock(session, server, payload, lock=True))
            elif action == "unlock":
                plans.append(plan_lock_unlock(session, server, payload, lock=False))
            elif action == "delete":
                plans.append(plan_delete(session, server, payload))
            elif action == "bulk_lock":
                plans.append(plan_lock_unlock(session, server, payload, lock=True))
            elif action == "password_reset":
                plans.append(plan_password_reset(session, server, payload))
            elif action == "set_expire":
                plans.append(plan_expire(session, server, payload))
            else:
                plans.append(
                    HostPlan(
                        server_id=server.id,  # type: ignore[arg-type]
                        hostname=server.hostname,
                        ip=server.ip,
                        ok=False,
                        summary_tr=f"Bilinmeyen aksiyon: {action}",
                        error="Bilinmeyen aksiyon",
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


ACTION_TITLES = {
    "create": "Yerel kullanıcı oluştur",
    "lock": "Yerel kullanıcı kilitle",
    "unlock": "Yerel kullanıcı kilit aç",
    "delete": "Yerel kullanıcı sil",
    "bulk_lock": "Toplu kullanıcı kilitle",
    "password_reset": "Şifre sıfırla",
    "set_expire": "Hesap süresini ayarla",
}


def job_summary(action: str, payload: dict[str, Any]) -> str:
    title = ACTION_TITLES.get(action, f"local_user.{action}")
    uname = (payload.get("username") or "").strip()
    return f"{title}: {uname}" if uname else title


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    """Execute planned commands (with real password for create). Returns ok, after, stdout, stderr."""
    _ = job_id
    if not plan.ok:
        return False, plan.before_state, "", plan.error

    username = _validate_username(payload.get("username", ""))
    out_chunks: list[str] = []
    err_chunks: list[str] = []

    if action == "create":
        password = payload.get("password") or ""
        if len(password) < 6:
            return False, plan.before_state, "", "Parola en az 6 karakter olmalı"
        groups = [g.strip() for g in (payload.get("groups") or []) if str(g).strip()]
        cmd = f"useradd -m {shlex.quote(username)}"
        if groups:
            cmd += f" -G {shlex.quote(','.join(groups))}"
        r1 = _run(session, server, cmd)
        out_chunks.append(r1.stdout)
        err_chunks.append(r1.stderr)
        if not r1.ok:
            return False, plan.before_state, "\n".join(out_chunks), "\n".join(err_chunks) or "useradd başarısız"
        # chpasswd via stdin-safe: printf
        pw_cmd = f"printf '%s:%s\\n' {shlex.quote(username)} {shlex.quote(password)} | chpasswd"
        r2 = _run(session, server, pw_cmd)
        out_chunks.append(r2.stdout)
        err_chunks.append(r2.stderr)
        if not r2.ok:
            return False, get_user_state(session, server, username), "\n".join(out_chunks), "\n".join(err_chunks)
        if payload.get("force_password_change"):
            r3 = _run(session, server, f"chage -d 0 {shlex.quote(username)}")
            out_chunks.append(r3.stdout)
            err_chunks.append(r3.stderr)
        after = get_user_state(session, server, username)
        return after.get("exists", False), after, "\n".join(out_chunks), "\n".join(err_chunks)

    if action == "password_reset":
        password = payload.get("password") or ""
        if len(password) < 6:
            return False, plan.before_state, "", "Parola en az 6 karakter olmalı"
        pw_cmd = f"printf '%s:%s\\n' {shlex.quote(username)} {shlex.quote(password)} | chpasswd"
        r1 = _run(session, server, pw_cmd)
        out_chunks.append(r1.stdout)
        err_chunks.append(r1.stderr)
        if not r1.ok:
            return False, plan.before_state, "\n".join(out_chunks), "\n".join(err_chunks)
        if payload.get("force_password_change", True):
            r2 = _run(session, server, f"chage -d 0 {shlex.quote(username)}")
            out_chunks.append(r2.stdout)
            err_chunks.append(r2.stderr)
        after = get_user_state(session, server, username)
        return True, after, "\n".join(out_chunks), "\n".join(err_chunks)

    # Generic: run planned commands except masked ones / verify-only passwd -S last
    for cmd in plan.planned_commands:
        if cmd.startswith("echo ") and "chpasswd" in cmd:
            continue
        r = _run(session, server, cmd)
        out_chunks.append(r.stdout)
        err_chunks.append(r.stderr)
        if not r.ok and not cmd.startswith("passwd -S") and not cmd.startswith("chage -l"):
            after = get_user_state(session, server, username)
            return False, after, "\n".join(out_chunks), "\n".join(err_chunks) or f"Komut başarısız: {cmd}"

    after = get_user_state(session, server, username)
    if action == "delete":
        ok = not after.get("exists")
    elif action in {"lock", "bulk_lock"}:
        ok = after.get("status") == "locked"
    elif action == "unlock":
        ok = after.get("status") in {"active", "no_password", "P", "PS"} or after.get("status_code") in {
            "P",
            "PS",
            "NP",
        }
    elif action == "set_expire":
        ok = True
    else:
        ok = True
    return ok, after, "\n".join(out_chunks), "\n".join(err_chunks)
