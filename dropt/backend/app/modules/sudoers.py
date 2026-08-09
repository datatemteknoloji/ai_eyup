from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session, col, func, select

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"grant": "Sudo yetkisi ver"}

TEMPLATES: dict[str, dict[str, Any]] = {
    "systemctl_status": {
        "label": "systemctl status/is-active (salt okuma)",
        "commands": ["/usr/bin/systemctl status *", "/usr/bin/systemctl is-active *"],
    },
    "service_restart": {
        "label": "Belirli servis restart (systemctl)",
        "commands": ["/usr/bin/systemctl restart *", "/usr/bin/systemctl status *"],
    },
    "disk_tools": {
        "label": "Disk araçları (lsblk/df)",
        "commands": ["/usr/bin/lsblk", "/usr/bin/df"],
    },
}

# Kabuk metachar / ALL — sudoers komut alanında riskli
_FORBIDDEN_CMD = re.compile(r"[;&|`$<>()]|\bALL\b", re.IGNORECASE)
# User specification satırı (basitleştirilmiş RHEL sudoers biçimi)
_USER_SPEC_RE = re.compile(
    r"^(?P<who>%?\S+)\s+(?P<hosts>\S+)\s*=\s*"
    r"(?:\((?P<runas>[^)]*)\))?\s*"
    r"(?P<tags>(?:NOEXEC|EXEC|SETENV|NOSETENV|PASSWD|NOPASSWD|LOG_INPUT|NOLOG_INPUT|"
    r"LOG_OUTPUT|NOLOG_OUTPUT)\s*:\s*)*"
    r"(?P<cmds>.+)$"
)
_BUILTINS = {"root", "%wheel", "%sudo", "admin", "%admin"}


def list_templates() -> list[dict[str, Any]]:
    return [{"id": k, "label": v["label"], "commands": v["commands"]} for k, v in TEMPLATES.items()]


def job_summary(action: str, payload: dict[str, Any]) -> str:
    return f"{ACTION_TITLES.get(action, action)}: {payload.get('target_name')}"


def _normalize_who(name: str, target_type: str) -> tuple[str, str]:
    """(display_name_without_%, target_type) — @ prefix temizlenir; % → group."""
    raw = (name or "").strip()
    if raw.startswith("@"):
        raw = raw[1:].strip()
    if raw.startswith("%"):
        return raw[1:].strip(), "group"
    return raw, (target_type or "user").strip().lower() or "user"


def _resolve_commands(payload: dict[str, Any]) -> list[str]:
    template_id = (payload.get("template") or "").strip()
    raw = payload.get("commands") or []
    cmds = [str(c).strip() for c in raw if str(c).strip()]
    if template_id and not cmds:
        if template_id not in TEMPLATES:
            raise ValueError("Geçersiz sudo şablonu")
        return list(TEMPLATES[template_id]["commands"])
    if not cmds:
        raise ValueError("En az bir komut (absolut path) gerekli")
    for c in cmds:
        first = c.split()[0] if c else ""
        if not first.startswith("/"):
            raise ValueError(f"Absolut path gerekli: {c}")
        if _FORBIDDEN_CMD.search(c):
            raise ValueError(f"Yasaklı kalıp (ALL / shell metachar): {c}")
    return cmds


def _dump_sudoers_script() -> str:
    return r"""
set +e
for f in /etc/sudoers /etc/sudoers.d/*; do
  [ -f "$f" ] || continue
  [ -r "$f" ] || continue
  printf '###FILE:%s\n' "$f"
  # yorum/boş satır ayıkla; #include satırlarını da at
  sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$f" 2>/dev/null
done
echo SUDOERS_DUMP_END
"""


def _is_builtin_who(who: str) -> bool:
    w = (who or "").strip().lower()
    if w in _BUILTINS:
        return True
    if w.startswith("defaults"):
        return True
    return False


def parse_sudoers_dump(text: str) -> list[dict[str, Any]]:
    """SSH dump çıktısından custom user/group kurallarını çıkar."""
    rules: list[dict[str, Any]] = []
    current_file = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip("\n")
        if line.strip() == "SUDOERS_DUMP_END":
            break
        if line.startswith("###FILE:"):
            current_file = line[len("###FILE:") :].strip()
            continue
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("defaults"):
            continue
        if s.lower().startswith("#include"):
            continue
        m = _USER_SPEC_RE.match(s)
        if not m:
            continue
        who = m.group("who")
        if _is_builtin_who(who):
            continue
        runas = (m.group("runas") or "root").strip() or "root"
        tags = (m.group("tags") or "").strip()
        cmds_raw = (m.group("cmds") or "").strip()
        nopasswd = "NOPASSWD" in tags.upper()
        # virgülle ayrılmış komutlar (basit split; tırnaklı args nadir)
        commands = [c.strip() for c in cmds_raw.split(",") if c.strip()]
        rules.append(
            {
                "who": who,
                "is_group": who.startswith("%"),
                "hosts": m.group("hosts"),
                "runas": runas,
                "nopasswd": nopasswd,
                "commands": commands,
                "raw": s,
                "source_file": current_file,
            }
        )
    return rules


def list_custom_rules(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    r = run_ssh(session, server, _dump_sudoers_script(), timeout=45)
    if not r.ok and not (r.stdout or "").strip():
        raise ValueError((r.stderr or r.stdout or "sudoers okunamadı")[:400])
    return parse_sudoers_dump(r.stdout or "")


def list_rules_for_who(
    session: Session, server: TargetServer, who: str
) -> list[dict[str, Any]]:
    """who = user veya %group veya group adı."""
    name, ttype = _normalize_who(who, "user" if not who.strip().startswith("%") else "group")
    if not name:
        raise ValueError("Kullanıcı/grup zorunlu")
    needle = f"%{name}" if ttype == "group" else name
    needle_l = needle.lower()
    all_rules = list_custom_rules(session, server)
    return [x for x in all_rules if str(x.get("who") or "").lower() == needle_l]


def find_server_by_hostname(session: Session, hostname: str) -> TargetServer | None:
    host = (hostname or "").strip()
    if not host:
        return None
    return session.exec(
        select(TargetServer).where(func.lower(col(TargetServer.hostname)) == host.lower())
    ).first()


def resolve_command_path(
    session: Session,
    server: TargetServer,
    command: str,
    *,
    as_user: str = "",
) -> dict[str, Any]:
    """Kısa komut adını absolut path'e çevir.

    1) as_user verilmişse login shell ile ``command -v`` / ``which``
    2) user yok veya path boşsa root fallback
    """
    cmd = (command or "").strip()
    # sadece binary adı; argümanları ayıkla
    binary = cmd.split()[0] if cmd else ""
    if not binary:
        raise ValueError("Komut adı zorunlu")
    if "/" in binary or re.search(r"[;&|`$<>()]", binary):
        raise ValueError("Sadece kısa komut adı yazın (örn. systemctl), path/metachar yok")
    if not re.match(r"^[A-Za-z0-9_+=.-]+$", binary):
        raise ValueError(f"Geçersiz komut adı: {binary}")

    qbin = shlex.quote(binary)
    which_expr = f"(command -v {qbin} || which {qbin} || type -P {qbin}) 2>/dev/null | head -n1"

    user_name = ""
    user_tried = False
    user_exists = False
    user_path = ""
    note = ""

    raw_who = (as_user or "").strip()
    if raw_who:
        name, ttype = _normalize_who(raw_who, "user")
        # grup için PATH yok — grup üyesinden ziyade formdaki "user" beklenir;
        # yine de % ise skip user try, direkt root
        if ttype == "group":
            note = "grup için login PATH yok; root fallback kullanılacak"
        elif name and name != "root":
            user_name = name
            user_tried = True
            exists = run_ssh(
                session, server, f"getent passwd {shlex.quote(name)} >/dev/null && echo YES", timeout=15
            )
            user_exists = "YES" in (exists.stdout or "")
            if user_exists:
                # login shell PATH
                script = f"su - {shlex.quote(name)} -c {shlex.quote(which_expr)} || true"
                ur = run_ssh(session, server, script, timeout=20)
                lines = [ln.strip() for ln in (ur.stdout or "").splitlines() if ln.strip()]
                user_path = lines[0] if lines else ""
                if user_path.startswith("/") and " " not in user_path:
                    return {
                        "query": binary,
                        "path": user_path,
                        "source": "user",
                        "as_user": name,
                        "user_exists": True,
                        "fallback": False,
                        "note": "",
                    }
                note = f"{name} PATH'inde bulunamadı; root fallback"
            else:
                note = f"kullanıcı yok ({name}); root fallback"

    rr = run_ssh(session, server, f"{which_expr} || true", timeout=15)
    root_path = (rr.stdout or "").strip().splitlines()
    root_path = root_path[0].strip() if root_path else ""
    if root_path.startswith("/") and " " not in root_path:
        return {
            "query": binary,
            "path": root_path,
            "source": "root",
            "as_user": user_name,
            "user_exists": user_exists,
            "user_tried": user_tried,
            "fallback": bool(user_tried or note),
            "note": note or ("root PATH" if not user_tried else note),
        }

    return {
        "query": binary,
        "path": "",
        "source": "",
        "as_user": user_name,
        "user_exists": user_exists,
        "user_tried": user_tried,
        "fallback": False,
        "note": note or "komut bulunamadı (user ve root)",
    }


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "grant":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            name, target_type = _normalize_who(
                str(payload.get("target_name") or ""),
                str(payload.get("target_type") or "user"),
            )
            runas = (payload.get("runas") or "root").strip() or "root"
            if not re.match(r"^[A-Za-z0-9_.@+-]+$", runas):
                raise ValueError(f"Geçersiz runas: {runas}")
            nopasswd = bool(payload.get("nopasswd", False))
            if not name:
                raise ValueError("Hedef kullanıcı/grup zorunlu")
            if not re.match(r"^[A-Za-z0-9_.@+-]+$", name):
                raise ValueError(f"Geçersiz hedef ad: {name}")
            cmds = _resolve_commands(payload)

            if target_type == "group":
                chk = run_ssh(session, server, f"getent group {shlex.quote(name)}", timeout=15)
                exists = bool((chk.stdout or "").strip())
            else:
                chk = run_ssh(session, server, f"getent passwd {shlex.quote(name)}", timeout=15)
                exists = bool((chk.stdout or "").strip())
            if not exists:
                plans.append(
                    HostPlan(
                        server_id=server.id,  # type: ignore[arg-type]
                        hostname=server.hostname,
                        ip=server.ip,
                        ok=False,
                        summary_tr=f"{name} bulunamadı",
                        error="Hedef kullanıcı/grup sunucuda yok",
                    )
                )
                continue

            spec = f"%{name}" if target_type == "group" else name
            tag = "NOPASSWD: " if nopasswd else ""
            cmd_part = ", ".join(cmds)
            line = f"{spec} ALL=({runas}) {tag}{cmd_part}".strip()
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:40]
            fname = f"/etc/sudoers.d/90-dropt-{safe}"
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: {spec} → ({runas}) {len(cmds)} komut → {fname}",
                    planned_commands=[
                        f"# {line}",
                        f"write {fname}",
                        f"visudo -cf {fname}",
                        f"sudo -l -U {name}",
                    ],
                    before_state={
                        "line": line,
                        "file": fname,
                        "target": spec,
                        "runas": runas,
                        "commands": cmds,
                        "nopasswd": nopasswd,
                    },
                    risk_notes="Yalnız /etc/sudoers.d altına dosya yazılır; visudo fail olursa geri alınır.",
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
    line = plan.before_state.get("line", "")
    fname = plan.before_state.get("file", "")
    target = str(plan.before_state.get("target") or "").lstrip("%")
    script = f"""
set -e
TMP=$(mktemp)
printf '%s\\n' {shlex.quote(str(line))} > "$TMP"
visudo -cf "$TMP"
install -m 440 "$TMP" {shlex.quote(str(fname))}
visudo -cf {shlex.quote(str(fname))}
rm -f "$TMP"
echo OK
sudo -n -l -U {shlex.quote(target)} 2>/dev/null | head -n 40 || true
"""
    r = run_ssh(session, server, script, timeout=45)
    after = {**plan.before_state, "written": r.ok}
    return r.ok, after, r.stdout, r.stderr
