from __future__ import annotations

import ipaddress
import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh
from app.utils.ipv4 import validate_gateway_ipv4, validate_host_ipv4

ACTION_TITLES = {"add": "VLAN arayüzü ekle"}

# UI subnet listesi ile uyumlu
ALLOWED_PREFIXES = set(range(8, 31))


def list_pools() -> list[dict[str, Any]]:
    """Eski API uyumu — havuz yok; VLAN ID kullanıcıdan alınır."""
    return []


def job_summary(action: str, payload: dict[str, Any]) -> str:
    parent = payload.get("parent")
    vlan_id = payload.get("vlan_id")
    return f"{ACTION_TITLES.get(action, action)}: {parent}.{vlan_id}"


def _mgmt_iface(session: Session, server: TargetServer) -> str:
    r = run_ssh(
        session,
        server,
        "ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"dev\"){print $(i+1); exit}}'",
        timeout=15,
    )
    return (r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else ""


def list_interfaces(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    """Add VLAN parent seçimi — yönetim + docker/ilo vb. hariç."""
    from app.modules import network as network_mod

    rows = network_mod.list_usable_interfaces(session, server)
    # VLAN UI: usable list (mgmt already hidden)
    return [
        {"name": r["name"], "is_mgmt": r.get("is_mgmt", False), "hidden": r.get("hidden", False)}
        for r in rows
    ]


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    parent = (payload.get("parent") or "").strip()
    try:
        vlan_id = int(payload.get("vlan_id") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("VLAN ID sayı olmalı") from exc
    ip = (payload.get("ip") or payload.get("address") or "").strip()
    gateway = (payload.get("gateway") or "").strip()
    # prefix: from subnet field or parse legacy ip_cidr
    prefix_raw = payload.get("subnet") if payload.get("subnet") is not None else payload.get("prefix")
    if prefix_raw is None and payload.get("ip_cidr"):
        try:
            legacy = ipaddress.ip_interface(str(payload["ip_cidr"]).strip())
            ip = str(legacy.ip)
            prefix_raw = legacy.network.prefixlen
        except ValueError as exc:
            raise ValueError("IP/CIDR geçersiz") from exc
    try:
        prefix = int(prefix_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Subnet (prefix) seçin") from exc

    if not parent or not re.match(r"^[a-zA-Z0-9_-]+$", parent):
        raise ValueError("Geçerli Interface seçin")
    if "." in parent:
        raise ValueError("Interface bir VLAN arayüzü olamaz")
    if vlan_id < 1 or vlan_id > 4094:
        raise ValueError("VLAN ID 1–4094 arasında olmalı")
    if prefix not in ALLOWED_PREFIXES:
        raise ValueError("Subnet /8–/30 aralığında olmalı")
    if not ip:
        raise ValueError("IP zorunlu")
    if not gateway:
        raise ValueError("Gateway zorunlu")
    try:
        ip = validate_host_ipv4(ip)
    except ValueError as exc:
        raise ValueError(f"IP: {exc}") from exc
    try:
        gateway = validate_gateway_ipv4(gateway)
    except ValueError as exc:
        raise ValueError(f"Gateway: {exc}") from exc
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError("IP geçersiz") from exc
    if addr.version != 4:
        raise ValueError("Yalnızca IPv4 desteklenir")
    try:
        iface = ipaddress.ip_interface(f"{ip}/{prefix}")
    except ValueError as exc:
        raise ValueError("IP/Subnet geçersiz") from exc
    try:
        gw = ipaddress.ip_address(gateway)
    except ValueError as exc:
        raise ValueError("Gateway geçersiz") from exc
    if gw.version != 4:
        raise ValueError("Gateway IPv4 olmalı")
    if gw not in iface.network:
        raise ValueError(f"Gateway, {iface.network} ağı içinde olmalı")
    if gw == iface.ip:
        raise ValueError("Gateway, IP ile aynı olamaz")

    conn_name = f"{parent}.{vlan_id}"
    return {
        "parent": parent,
        "vlan_id": vlan_id,
        "ip": str(addr),
        "subnet": prefix,
        "ip_cidr": str(iface.with_prefixlen),
        "gateway": str(gw),
        "conn_name": conn_name,
        "ifname": conn_name,
    }


def _nmcli_add_cmd(data: dict[str, Any]) -> str:
    """Tek satırda VLAN + IPv4 ayarları."""
    return (
        f"nmcli con add type vlan con-name {data['conn_name']} ifname {data['ifname']} "
        f"dev {data['parent']} id {data['vlan_id']} "
        f"ipv4.addresses {data['ip_cidr']} ipv4.gateway {data['gateway']} "
        f"ipv4.method manual ipv6.method disabled ipv4.never-default yes"
    )


def _nmcli_bounce_cmd(data: dict[str, Any]) -> str:
    name = data["conn_name"]
    return f"nmcli con down {name}; nmcli con up {name}"


def _check_vlan_conflicts(session: Session, server: TargetServer, data: dict[str, Any]) -> None:
    """Önizleme/apply öncesi: VLAN adı (ifname/con-name) ve IP çakışması."""
    ifname = data["ifname"]
    target_ip = data["ip"]

    link = run_ssh(
        session,
        server,
        f"ip -br link show {shlex.quote(ifname)} 2>/dev/null | head -n1",
        timeout=10,
    )
    if (link.stdout or "").strip():
        raise ValueError(f"VLAN arayüzü zaten mevcut: {ifname}")

    nmcli = run_ssh(
        session,
        server,
        f"nmcli -t -f NAME con show 2>/dev/null | grep -Fx {shlex.quote(ifname)}",
        timeout=10,
    )
    if (nmcli.stdout or "").strip():
        raise ValueError(f"nmcli connection zaten mevcut: {ifname}")

    ip_q = shlex.quote(target_ip)
    ip_check = run_ssh(
        session,
        server,
        f"ip -o -4 addr show 2>/dev/null | awk -v ip={ip_q} "
        "'{{split($4,a,\"/\"); if(a[1]==ip){{print $2; exit}}}}'",
        timeout=15,
    )
    owner = (ip_check.stdout or "").strip().split("@")[0]
    if owner:
        raise ValueError(f"IP {target_ip} zaten kullanımda ({owner})")


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    for server in servers:
        try:
            if action != "add":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            data = _validate_payload(payload)
            ifaces = list_interfaces(session, server)
            parent_row = next((i for i in ifaces if i["name"] == data["parent"]), None)
            if parent_row is None:
                raise ValueError(f"Interface bulunamadı: {data['parent']}")
            if parent_row.get("is_mgmt"):
                raise ValueError("Yönetim arayüzüne VLAN eklenemez")
            _check_vlan_conflicts(session, server, data)
            cmds = [
                _nmcli_add_cmd(data),
                "sleep 3.5",
                _nmcli_bounce_cmd(data),
                "ip addr / SSH sağlık kontrolü",
            ]
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=(
                        f"{server.hostname}: {data['ifname']} "
                        f"({data['ip_cidr']}, gw {data['gateway']}) eklenecek — yönetim ağına dokunulmayacak"
                    ),
                    planned_commands=cmds,
                    before_state=data,
                    risk_notes="Yanlış gateway SSH kopmasına yol açabilir; yönetim arayüzü korunur.",
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: {msg}",
                    error=msg,
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
    d = plan.before_state
    try:
        _check_vlan_conflicts(session, server, d)
    except ValueError as exc:
        return False, d, "", str(exc)
    conn = d["conn_name"]
    parent = d["parent"]
    vlan_id = int(d["vlan_id"])
    ip_cidr = d["ip_cidr"]
    gateway = d["gateway"]
    script = f"""
set -e
CONN={shlex.quote(conn)}
PARENT={shlex.quote(parent)}
VID={vlan_id}
IFACE="$CONN"
nmcli con add type vlan con-name "$CONN" ifname "$IFACE" dev "$PARENT" id "$VID" \\
  ipv4.addresses {shlex.quote(ip_cidr)} ipv4.gateway {shlex.quote(gateway)} \\
  ipv4.method manual ipv6.method disabled ipv4.never-default yes
sleep 3.5
nmcli con down "$CONN"
nmcli con up "$CONN"
ip -br addr show "$IFACE" || true
echo OK
"""
    r = run_ssh(session, server, script, timeout=120)
    health = run_ssh(session, server, "echo alive", timeout=15)
    ok = r.ok and health.ok and "alive" in health.stdout
    after = {
        **d,
        "alive": health.ok,
        "checklist": ["ip addr kontrol et", "Ağ ekibine VLAN bilgisini ilet"],
    }
    if not ok and r.ok:
        run_ssh(
            session,
            server,
            f"nmcli con down {shlex.quote(conn)} 2>/dev/null; nmcli con delete {shlex.quote(conn)} 2>/dev/null; true",
            timeout=30,
        )
        after["rolled_back"] = True
    return ok, after, r.stdout + "\n" + health.stdout, r.stderr
