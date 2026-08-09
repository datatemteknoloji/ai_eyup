"""SSH ile fiziksel / sanal makine tespiti (systemd-detect-virt + yedekler)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.server import Server

logger = logging.getLogger(__name__)

# Dropt server_facts ile aynı mantık
DETECT_SCRIPT = r"""
set +e
V=$(systemd-detect-virt 2>/dev/null)
if [ -z "$V" ] || [ "$V" = "none" ]; then
  V=$(hostnamectl 2>/dev/null | awk -F: '/Virtualization/ {gsub(/^ +/,"",$2); print $2; exit}')
fi
if [ -z "$V" ] || [ "$V" = "none" ]; then
  if grep -qi hypervisor /proc/cpuinfo 2>/dev/null; then V=vm; else V=physical; fi
fi
echo "VIRT=$V"
echo "CHASSIS=$(hostnamectl 2>/dev/null | awk -F: '/Chassis/ {gsub(/^ +/,"",$2); print $2; exit}')"
if [ -f /etc/os-release ]; then
  . /etc/os-release
  echo "OS_PRETTY=${PRETTY_NAME:-}"
fi
echo "KERNEL=$(uname -r 2>/dev/null)"
echo "CPUS=$(nproc 2>/dev/null || true)"
"""


def classify_virt_label(virt_raw: str) -> tuple[str, str]:
    """
    Returns (server_type, virt_label).
    server_type: PHYSICAL | VIRTUAL
    """
    v = (virt_raw or "").strip().lower()
    if v in {"", "none", "physical"}:
        return "PHYSICAL", v or "physical"
    return "VIRTUAL", v


def parse_detect_stdout(stdout: str) -> dict[str, Any]:
    raw: dict[str, str] = {}
    for line in (stdout or "").splitlines():
        if "=" in line:
            k, val = line.split("=", 1)
            raw[k.strip()] = val.strip()
    virt = raw.get("VIRT") or ""
    server_type, virt_label = classify_virt_label(virt)
    return {
        "ok": bool(raw),
        "server_type": server_type,
        "virtualization": virt_label,
        "chassis": raw.get("CHASSIS") or "",
        "os_pretty": raw.get("OS_PRETTY") or "",
        "kernel": raw.get("KERNEL") or "",
        "cpus": raw.get("CPUS") or "",
    }


def apply_detected_type(
    server: Server,
    *,
    server_type: str,
    virtualization: str = "",
    force: bool = False,
) -> bool:
    """
    hypervisor_id doluysa (VMware sync) ezme — SoT hypervisor.
    Returns True if server_type changed.
    """
    if server.hypervisor_id and not force:
        # Sync VM: tip VIRTUAL kalsın
        if (server.server_type or "").upper() != "VIRTUAL":
            server.server_type = "VIRTUAL"
            return True
        return False
    st = (server_type or "UNKNOWN").upper()
    if st not in ("PHYSICAL", "VIRTUAL", "UNKNOWN"):
        st = "UNKNOWN"
    changed = (server.server_type or "").upper() != st
    server.server_type = st
    # virt etiketini connection_config meta'da tut (opsiyonel)
    try:
        cfg = dict(server.connection_config or {})
        if virtualization:
            cfg["_virtualization"] = virtualization[:64]
        server.connection_config = cfg
    except Exception:
        pass
    return changed


def detect_via_ainew_ssh(db: Session, server: Server) -> Optional[dict[str, Any]]:
    """Ainew connection_config / GlobalCredential ile SSH detect (örn. datatem)."""
    if not server.ip_address:
        return None
    try:
        from app.models.credential import GlobalCredential
        from app.services.ssh_credentials import resolve_ssh_creds
        from app.services.ssh_manager import SSHManager
    except ImportError:
        return None

    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()
    creds = resolve_ssh_creds(server, global_cred=global_cred)
    if not creds.get("username") or not creds.get("host"):
        return None

    ssh = SSHManager(
        host=creds["host"],
        username=creds["username"],
        password=creds.get("password"),
        private_key=creds.get("private_key"),
        port=int(creds.get("port") or 22),
    )
    try:
        if not ssh.connect():
            return None
        ok, stdout, stderr = ssh.execute_command(DETECT_SCRIPT, cmd_timeout=25)
        ssh.close()
        if not (ok or stdout):
            logger.debug("virt detect ssh cmd failed: %s", stderr)
            return None
        out = parse_detect_stdout(stdout)
        out["source"] = "ainew-ssh"
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("virt detect ainew ssh failed for %s: %s", server.id, exc)
        try:
            ssh.close()
        except Exception:
            pass
        return None


def detect_via_dropt_facts(
    *,
    dropt_base: str,
    dropt_token: str,
    dropt_server_id: int,
) -> Optional[dict[str, Any]]:
    """Level 1 otomasyon user (root…) ile Dropt facts — machine_type."""
    import httpx

    try:
        with httpx.Client(timeout=45.0) as client:
            r = client.get(
                f"{dropt_base.rstrip('/')}/api/servers/{dropt_server_id}/facts",
                headers={"Authorization": f"Bearer {dropt_token}"},
            )
        if r.status_code >= 400:
            logger.debug("dropt facts %s: %s", r.status_code, r.text[:200])
            return None
        facts = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("dropt facts failed: %s", exc)
        return None

    if not facts.get("reachable") and not facts.get("ok"):
        return None
    mt = (facts.get("machine_type") or "").strip().lower()
    virt = (facts.get("virtualization") or "").strip().lower()
    if mt == "physical" or virt in {"", "none", "physical"}:
        server_type = "PHYSICAL"
    else:
        server_type = "VIRTUAL"
    return {
        "ok": True,
        "server_type": server_type,
        "virtualization": virt or mt,
        "os_pretty": facts.get("os_pretty") or "",
        "kernel": facts.get("kernel") or "",
        "source": "dropt-facts",
    }


def probe_and_apply(
    db: Session,
    server: Server,
    *,
    dropt_base: str = "",
    dropt_token: str = "",
    dropt_server_id: Optional[int] = None,
    prefer_dropt: bool = True,
) -> dict[str, Any]:
    """
    Önce (Ops) Dropt facts / otomasyon SSH; olmazsa ainew SSH.
    hypervisor_id varsa zorla VIRTUAL bırakır.
    """
    result: dict[str, Any] = {"detected": False, "server_type": server.server_type, "source": None}
    if server.hypervisor_id:
        apply_detected_type(server, server_type="VIRTUAL", virtualization="hypervisor-sync")
        db.commit()
        result.update(detected=True, server_type="VIRTUAL", source="hypervisor_id")
        return result

    detected: Optional[dict[str, Any]] = None
    if prefer_dropt and dropt_base and dropt_token and dropt_server_id:
        detected = detect_via_dropt_facts(
            dropt_base=dropt_base,
            dropt_token=dropt_token,
            dropt_server_id=int(dropt_server_id),
        )
    if not detected:
        detected = detect_via_ainew_ssh(db, server)

    if not detected:
        # Bilinmiyor — PHYSICAL varsayma
        if not server.server_type or (server.server_type or "").upper() in ("", "UNKNOWN"):
            server.server_type = "UNKNOWN"
            db.commit()
        result["server_type"] = server.server_type
        return result

    apply_detected_type(
        server,
        server_type=detected["server_type"],
        virtualization=str(detected.get("virtualization") or ""),
    )
    if detected.get("os_pretty") and not server.os_version:
        server.os_version = str(detected["os_pretty"])[:255]
    if detected.get("kernel") and not server.kernel_version:
        server.kernel_version = str(detected["kernel"])[:100]
        server.os_type = server.os_type or "linux"
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(server, "connection_config")
    db.commit()
    db.refresh(server)
    result.update(
        detected=True,
        server_type=server.server_type,
        source=detected.get("source") or "ainew-ssh",
        virtualization=detected.get("virtualization"),
    )
    return result
