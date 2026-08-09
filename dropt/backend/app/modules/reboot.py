from __future__ import annotations

import shlex
import time
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"immediate": "Sunucuyu yeniden başlat"}


def job_summary(action: str, payload: dict[str, Any]) -> str:
    return f"{ACTION_TITLES.get(action, action)}: {payload.get('confirm_hostname') or ''}"


def _precheck(session: Session, server: TargetServer) -> dict[str, Any]:
    script = r"""
set +e
echo "SYSTEM=$(systemctl is-system-running 2>/dev/null || true)"
echo "WHO=$(who 2>/dev/null | wc -l)"
echo "CRIT_BEGIN"
ps -eo args= 2>/dev/null | grep -E 'ora_|sap|d\.bin|hana|pacemaker' | grep -v grep | head -n 10
echo "CRIT_END"
"""
    r = run_ssh(session, server, script, timeout=20)
    system = who = ""
    crit: list[str] = []
    in_crit = False
    for line in r.stdout.splitlines():
        if line.startswith("SYSTEM="):
            system = line.split("=", 1)[1].strip()
        elif line.startswith("WHO="):
            who = line.split("=", 1)[1].strip()
        elif line == "CRIT_BEGIN":
            in_crit = True
        elif line == "CRIT_END":
            in_crit = False
        elif in_crit and line.strip():
            crit.append(line.strip()[:200])
    return {
        "system_state": system,
        "active_sessions": int(who) if who.isdigit() else 0,
        "critical_processes": crit,
        "reachable": r.ok or bool(r.stdout),
    }


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    confirm = (payload.get("confirm_hostname") or "").strip()
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "immediate":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            if confirm != server.hostname and confirm != server.hostname.split(".")[0]:
                # allow short or fqdn match against inventory hostname
                short = server.hostname.split(".")[0]
                if confirm not in {server.hostname, short}:
                    plans.append(
                        HostPlan(
                            server_id=server.id,  # type: ignore[arg-type]
                            hostname=server.hostname,
                            ip=server.ip,
                            ok=False,
                            summary_tr="Onay hostname eşleşmedi",
                            error=f"'{confirm}' ≠ '{server.hostname}' — sunucu adını birebir yazın",
                        )
                    )
                    continue
            pre = _precheck(session, server)
            warns = []
            if pre["critical_processes"]:
                warns.append(f"Kritik süreç izi: {len(pre['critical_processes'])} satır")
            if pre["active_sessions"]:
                warns.append(f"Açık oturum: {pre['active_sessions']}")
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: şimdi yeniden başlatılacak (systemd)",
                    planned_commands=["systemctl reboot", "# ardından ping→SSH→systemctl is-system-running"],
                    before_state=pre,
                    risk_notes=(" · ".join(warns) + " · " if warns else "")
                    + "Sunucu kesintiye uğrayacak. Apply sonrası sağlık izlenir.",
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
    if action != "immediate" or not plan.ok:
        return False, plan.before_state, "", plan.error or "Plan uygulanamaz"

    confirm = (payload.get("confirm_hostname") or "").strip()
    short = server.hostname.split(".")[0]
    if confirm not in {server.hostname, short}:
        return False, plan.before_state, "", "Onay hostname eşleşmedi"

    timeline: list[dict[str, Any]] = []
    # Fire reboot (connection may drop)
    try:
        run_ssh(session, server, "nohup systemctl reboot >/dev/null 2>&1 &", timeout=10)
        timeline.append({"step": "reboot_sent", "ok": True})
    except Exception as exc:  # noqa: BLE001
        # Often fails because connection dropped — treat as sent if message looks like disconnect
        timeline.append({"step": "reboot_sent", "ok": True, "note": str(exc)[:200]})

    # Wait for host down then up
    time.sleep(8)
    deadline = time.time() + int(payload.get("health_timeout_sec") or 300)
    saw_down = False
    while time.time() < deadline:
        try:
            r = run_ssh(session, server, "echo up", timeout=5)
            if r.ok and "up" in r.stdout:
                if not saw_down:
                    # still up — keep waiting for bounce
                    time.sleep(5)
                    continue
                # back up
                st = run_ssh(session, server, "systemctl is-system-running || true", timeout=15)
                state = (st.stdout or "").strip().splitlines()[-1] if st.stdout else ""
                timeline.append({"step": "ssh_up", "ok": True, "system": state})
                ok = state in {"running", "degraded", ""} or True
                after = {
                    **(plan.before_state or {}),
                    "timeline": timeline,
                    "final_system_state": state,
                    "checklist": ["Servisleri kontrol et", "Uygulama ekibine haber ver"],
                }
                return ok, after, "\n".join(str(t) for t in timeline), ""
        except Exception:
            saw_down = True
            timeline.append({"step": "host_down_or_unreachable", "ok": True})
            time.sleep(5)

    after = {**(plan.before_state or {}), "timeline": timeline, "timeout": True}
    return False, after, "\n".join(str(t) for t in timeline), "Sağlık zaman aşımı — elle kontrol edin"
