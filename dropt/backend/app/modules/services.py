from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {
    "start": "Servis başlat",
    "stop": "Servis durdur",
    "restart": "Servis yeniden başlat",
}

UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._@\\-]{0,200}$")

# Custom olsa bile portaldan operasyon yasak
DENYLIST_EXACT = frozenset(
    {
        "sshd",
        "ssh",
        "NetworkManager",
        "network",
        "firewalld",
        "iptables",
        "nftables",
        "dbus",
        "dbus-broker",
        "systemd-journald",
        "systemd-logind",
        "systemd-udevd",
        "systemd-resolved",
        "systemd-timesyncd",
        "systemd-networkd",
        "multipathd",
        "auditd",
        "rsyslog",
        "cron",
        "crond",
        "getty",
        "serial-getty",
        "user@",
        "polkit",
        "tuned",
    }
)

DENYLIST_PREFIXES = (
    "systemd-",
    "dbus-",
    "getty@",
    "serial-getty@",
    "user@",
    "dracut-",
    "initrd-",
)


def job_summary(action: str, payload: dict[str, Any]) -> str:
    unit = (payload.get("unit") or "").strip()
    return f"{ACTION_TITLES.get(action, action)}: {unit}"


def _unit_base(name: str) -> str:
    n = (name or "").strip()
    if n.endswith(".service"):
        n = n[: -len(".service")]
    return n


def _normalize_unit(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        raise ValueError("Servis (unit) zorunlu")
    if "/" in name or ".." in name or any(c.isspace() for c in name) or "\x00" in name:
        raise ValueError("Geçersiz unit adı")
    base = _unit_base(name)
    if not UNIT_RE.match(base):
        raise ValueError("Unit adı yalnızca güvenli karakterler içermeli")
    if _is_denied(base):
        raise ValueError(f"Kritik sistem servisine izin yok: {base}")
    return f"{base}.service"


def _is_denied(base: str) -> bool:
    if base in DENYLIST_EXACT:
        return True
    return any(base.startswith(p) for p in DENYLIST_PREFIXES)


def _unit_status_script(unit: str) -> str:
    u = shlex.quote(unit)
    return (
        f"echo ACTIVE=$(systemctl is-active {u} 2>/dev/null || true)\n"
        f"echo ENABLED=$(systemctl is-enabled {u} 2>/dev/null || true)\n"
        f"echo LOAD=$(systemctl show -p LoadState --value {u} 2>/dev/null || true)\n"
        f"echo FRAG=$(systemctl show -p FragmentPath --value {u} 2>/dev/null || true)\n"
        f"echo DESC=$(systemctl show -p Description --value {u} 2>/dev/null || true)\n"
        f"echo SUB=$(systemctl show -p SubState --value {u} 2>/dev/null || true)\n"
    )


def _parse_status_kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _assert_custom_fragment(frag: str) -> None:
    frag = (frag or "").strip()
    if not frag or frag == "/dev/null":
        raise ValueError("Unit dosyası bulunamadı")
    # Yalnızca /etc/systemd/system altındaki custom unit'ler
    if not (frag.startswith("/etc/systemd/system/") and frag.endswith(".service")):
        raise ValueError(
            f"Yalnızca /etc/systemd/system altındaki custom servislere izin var (frag={frag})"
        )


def list_services(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    """Sunucudaki custom (.service under /etc/systemd/system) unit'leri listele."""
    script = r"""
set +e
echo SERVICES_BEGIN
for f in /etc/systemd/system/*.service; do
  [ -e "$f" ] || continue
  [ -d "$f" ] && continue
  base=$(basename "$f" .service)
  [ -n "$base" ] || continue
  active=$(systemctl is-active "$base.service" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$base.service" 2>/dev/null || true)
  load=$(systemctl show -p LoadState --value "$base.service" 2>/dev/null || true)
  frag=$(systemctl show -p FragmentPath --value "$base.service" 2>/dev/null || true)
  desc=$(systemctl show -p Description --value "$base.service" 2>/dev/null || true)
  sub=$(systemctl show -p SubState --value "$base.service" 2>/dev/null || true)
  # desc içindeki | kırpmamak için son alan
  printf 'UNIT\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$base" "$active" "$enabled" "$load" "$frag" "$sub" "$desc"
done
echo SERVICES_END
"""
    r = run_ssh(session, server, script, timeout=45)
    if not r.ok and not r.stdout:
        raise RuntimeError(r.stderr or "Servis listesi alınamadı")

    rows: list[dict[str, Any]] = []
    in_block = False
    for line in r.stdout.splitlines():
        if line.strip() == "SERVICES_BEGIN":
            in_block = True
            continue
        if line.strip() == "SERVICES_END":
            break
        if not in_block or not line.startswith("UNIT\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        base = parts[1]
        active = parts[2]
        enabled = parts[3]
        load = parts[4]
        frag = parts[5]
        sub = parts[6]
        desc = "\t".join(parts[7:])
        if _is_denied(base):
            continue
        if frag and not frag.startswith("/etc/systemd/system/"):
            continue
        rows.append(
            {
                "unit": f"{base}.service",
                "name": base,
                "active": active or "unknown",
                "sub_state": sub or "",
                "enabled": enabled or "unknown",
                "load_state": load or "",
                "fragment_path": frag or "",
                "description": (desc or "")[:200],
                "operable": load != "not-found" and not _is_denied(base),
            }
        )
    rows.sort(key=lambda x: x["name"].lower())
    return rows


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    if action not in ACTION_TITLES:
        for server in servers:
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: bilinmeyen aksiyon",
                    error=f"Bilinmeyen aksiyon: {action}",
                )
            )
        return plans

    try:
        unit = _normalize_unit(str(payload.get("unit") or ""))
    except ValueError as exc:
        for server in servers:
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: geçersiz unit",
                    error=str(exc),
                )
            )
        return plans

    for server in servers:
        try:
            r = run_ssh(session, server, _unit_status_script(unit), timeout=20)
            st = _parse_status_kv(r.stdout)
            frag = st.get("FRAG", "")
            load = st.get("LOAD", "")
            if load == "not-found":
                raise ValueError(f"Unit bulunamadı: {unit}")
            _assert_custom_fragment(frag)
            active = st.get("ACTIVE", "unknown")
            enabled = st.get("ENABLED", "unknown")
            risk = ""
            if action == "stop" and active == "active":
                risk = "Servis durdurulacak; bağımlı uygulamalar etkilenebilir"
            elif action == "restart" and active == "active":
                risk = "Servis kısa süre kesintiye uğrayacak"

            cmd = f"systemctl {action} -- {shlex.quote(unit)}"
            verify = (
                f"systemctl is-active -- {shlex.quote(unit)}; "
                f"systemctl is-enabled -- {shlex.quote(unit)} || true"
            )
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{ACTION_TITLES[action]}: {unit} (şu an: {active})",
                    planned_commands=[cmd, verify],
                    before_state={
                        "unit": unit,
                        "active": active,
                        "enabled": enabled,
                        "sub_state": st.get("SUB", ""),
                        "fragment_path": frag,
                        "description": st.get("DESC", ""),
                        "action": action,
                    },
                    risk_notes=risk,
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
    _ = job_id
    if action not in ACTION_TITLES or not plan.ok:
        return False, plan.before_state, "", plan.error or "Plan uygulanamaz"

    try:
        unit = _normalize_unit(str(payload.get("unit") or plan.before_state.get("unit") or ""))
    except ValueError as exc:
        return False, plan.before_state, "", str(exc)

    # Yeniden doğrula (apply sırasında state değişmiş olabilir)
    pre = run_ssh(session, server, _unit_status_script(unit), timeout=20)
    st = _parse_status_kv(pre.stdout)
    try:
        if st.get("LOAD") == "not-found":
            raise ValueError(f"Unit bulunamadı: {unit}")
        _assert_custom_fragment(st.get("FRAG", ""))
    except ValueError as exc:
        return False, {**plan.before_state, **st}, pre.stdout, str(exc)

    cmd = f"systemctl {action} -- {shlex.quote(unit)}"
    r = run_ssh(session, server, cmd, timeout=120)
    post = run_ssh(session, server, _unit_status_script(unit), timeout=20)
    after = _parse_status_kv(post.stdout)
    after_state = {
        "unit": unit,
        "action": action,
        "active": after.get("ACTIVE", ""),
        "enabled": after.get("ENABLED", ""),
        "sub_state": after.get("SUB", ""),
        "fragment_path": after.get("FRAG", ""),
        "before_active": plan.before_state.get("active"),
    }

    # Başarı kriteri
    ok = r.ok
    active = after.get("ACTIVE", "")
    if action == "start" and active not in {"active", "activating"}:
        ok = False
    elif action == "stop" and active not in {"inactive", "failed", "deactivating"}:
        # failed is stopped but unhealthy — still "stopped"
        if active == "active":
            ok = False
    elif action == "restart" and active not in {"active", "activating"}:
        ok = False

    stdout = (r.stdout or "") + ("\n" + post.stdout if post.stdout else "")
    stderr = r.stderr or ""
    if not ok and not stderr:
        stderr = f"Beklenen state oluşmadı (active={active})"
    return ok, after_state, stdout, stderr
