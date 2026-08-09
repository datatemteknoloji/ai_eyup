from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.modules import vlan as vlan_mod
from app.services.target_ssh import run_ssh
from app.utils.ipv4 import validate_gateway_ipv4, validate_host_ipv4

ACTION_TITLES = {
    "add_network": "Add Network",
    "add_vlan": "Add VLAN",
    "change_ip": "IP Değişikliği",
}

BOND_MODES = {
    "1": "active-backup",
    "4": "802.3ad",
    "6": "balance-alb",
}

# Kesinlikle gösterme / işlem yapma
_EXCLUDED_IFACE_RE = re.compile(
    r"^(lo|docker\d*|veth|br-|virbr|cni|flannel|calico|weave|cni0|kube|"
    r"nerdctl|podman|ilo|idrac|usb|tun|tap|awdl|llw|utun|hm\d|"
    r"team\d+|ovs-|geneve|vxlan|wg\d*|tailscale)",
    re.IGNORECASE,
)

ALLOWED_PREFIXES = set(range(8, 31))


def job_summary(action: str, payload: dict[str, Any]) -> str:
    if action == "add_vlan":
        return vlan_mod.job_summary("add", payload)
    if action == "change_ip":
        iface = payload.get("interface") or "?"
        new_ip = payload.get("ip") or "?"
        return f"IP Değişikliği: {iface} → {new_ip}"
    ctype = (payload.get("connection_type") or "ethernet").strip()
    iface = payload.get("interface") or payload.get("bond_name") or "?"
    vlan = payload.get("vlan_id")
    extra = f" vlan={vlan}" if vlan else ""
    return f"Add Network ({ctype}): {iface}{extra}"


_NSLOOKUP_NAME_RE = re.compile(r"(?im)^\s*Name:\s*(\S+)\s*$")
_NSLOOKUP_ADDR_RE = re.compile(r"(?im)^\s*Address:\s*([0-9.]+)(?:#\d+)?\s*$")
_NSLOOKUP_PTR_RE = re.compile(r"(?im)name\s*=\s*([^\s.]+(?:\.[^\s.]+)*)\.?\s*$")
_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def portal_nslookup(query: str) -> dict[str, Any]:
    """
    Dropt (API konteyneri / uygulama sunucusu) üzerinden nslookup.
    Forward: hostname → Address; reverse: IP → name=.
    Kısa ad NXDOMAIN olursa /etc/resolv.conf search domain ile yeniden dener.
    """
    q = (query or "").strip().rstrip(".")
    out: dict[str, Any] = {
        "query": q,
        "ok": False,
        "fqdn": None,
        "ip": None,
        "raw": "",
        "error": None,
    }
    if not q:
        out["error"] = "boş sorgu"
        return out

    candidates = [q]
    if not _IPV4_RE.match(q) and "." not in q:
        try:
            resolv = Path("/etc/resolv.conf").read_text(encoding="utf-8", errors="ignore")
            for line in resolv.splitlines():
                parts = line.split()
                if parts and parts[0].lower() == "search":
                    for dom in parts[1:]:
                        candidates.append(f"{q}.{dom.rstrip('.')}")
                    break
                if parts and parts[0].lower() == "domain" and len(parts) > 1:
                    candidates.append(f"{q}.{parts[1].rstrip('.')}")
        except OSError:
            pass

    last_raw = ""
    last_err = None
    for cand in candidates:
        try:
            proc = subprocess.run(
                ["nslookup", cand],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except FileNotFoundError:
            out["error"] = "nslookup yok (bind-utils/dnsutils)"
            return out
        except Exception as exc:  # noqa: BLE001
            out["error"] = str(exc)[:200]
            return out

        text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        last_raw = text[:2000]
        is_ip = bool(_IPV4_RE.match(cand))

        if "NXDOMAIN" in text or "can't find" in text.lower():
            last_err = "NXDOMAIN"
            continue

        if is_ip:
            m = _NSLOOKUP_PTR_RE.search(text)
            if m:
                out["query"] = cand
                out["fqdn"] = m.group(1).rstrip(".").lower()
                out["ip"] = cand
                out["ok"] = True
                out["raw"] = last_raw
                return out
            last_err = "reverse lookup başarısız"
            continue

        names = _NSLOOKUP_NAME_RE.findall(text)
        addrs = _NSLOOKUP_ADDR_RE.findall(text)
        fqdn = names[-1].rstrip(".").lower() if names else None
        ip = None
        if addrs:
            ip = addrs[-1] if names and len(addrs) >= 1 else addrs[-1]
        if fqdn and ip:
            out["query"] = cand
            out["fqdn"] = fqdn
            out["ip"] = ip
            out["ok"] = True
            out["raw"] = last_raw
            return out
        last_err = "forward lookup parse edilemedi"

    out["raw"] = last_raw
    out["error"] = last_err or "nslookup başarısız"
    return out


def build_dns_ticket_text(*, fqdn: str, old_ip: str, new_ip: str) -> str:
    """DNS Tanımı → Dns Kayıt Değiştirme talep içeriği."""
    f = (fqdn or "").strip().rstrip(".")
    o = (old_ip or "").strip()
    n = (new_ip or "").strip()
    return (
        f'{f} - {o} dns kaydının "{f} - {n}" olarak değiştirilmesini rica ederiz.'
    )


_HPSA_TAIL = (
    "/opt/opsware/agent/pylibs3/cog/bs_software --debug || true; "
    "/opt/opsware/agent/pylibs3/cog/bs_hardware --debug || true"
)


def build_ip_change_success_checklist(
    *,
    fqdn: str,
    old_ip: str,
    new_ip: str,
    is_primary: bool = True,
    lang: str = "tr",
) -> list[str]:
    """IP değişikliği başarı sonrası kontrol listesi (dinamik FQDN / IP; tr|en)."""
    host = (fqdn or "").strip().rstrip(".") or "—"
    old = (old_ip or "").strip() or "—"
    new = (new_ip or "").strip() or "—"
    en = (lang or "tr").lower().startswith("en")
    if en:
        dns_gate = (
            "This step must be applied if the interface being changed has the primary IP "
            "address (the IP that matches the DNS query). If it is a secondary IP address, "
            "this step is not required.\n\n"
        )
        if is_primary:
            item1 = (
                dns_gate
                + "The requester must open a ticket to update DNS records using the format below.\n\n"
                "Request path: DNS Definition / Change DNS Record\n"
                "Sample request:\n"
                f'"{host} {old}" record should be updated so that it becomes "{host} {new}".'
            )
        else:
            item1 = (
                dns_gate
                + "Because this change was made on a secondary IP, a DNS record request is not "
                "required (see the primary IP rule above).\n\n"
                "Request path: DNS Definition / Change DNS Record\n"
                "Sample request (primary IP only):\n"
                f'"{host} {old}" record should be updated so that it becomes "{host} {new}".'
            )
        return [
            item1,
            (
                "Relevant teams must be informed so monitoring definitions can be updated.\n\n"
                "Sample mail:\n"
                "To: Sistem İzleme ve Hizmet Analiz İşletimi, Sistem İşletim ve İzleme, "
                "Altyapı İzleme\n"
                "CC: Unix Linux Sistem Tasarım ve Planlama\n\n"
                f'An IP change was performed on server "{host}" ("{old}"). '
                f'"{host}" ==> "{new}" has been updated.\n'
                "Please update the required monitoring records."
            ),
        ]
    dns_gate = (
        "İşlem yapılan Interface birincil IP adresi ise (dns sorgusu ile eşleşen IP) "
        "bu adımı uygulanmalıdır. Eğer ikincil IP adresi ise bu işlemin yapılması "
        "gerek bulunmamaktadır.\n\n"
    )
    item1 = (
        dns_gate
        + "Talep sahibinin belirtilen formatı kullanarak dns bilgilerinin güncellenmesi "
        "için talep oluşturması gerekmektedir.\n\n"
        "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n"
        "Örnek Talep:\n"
        f'"{host} {old}" kaydının "{host} {new}" olacak şekilde DNS kaydının '
        "güncellenmesini rica ederiz."
    )
    if not is_primary:
        item1 = (
            dns_gate
            + "Bu işlem ikincil IP üzerinde yapıldığı için DNS kayıt talebi gerekmez "
            "(yukarıdaki birincil IP kuralı).\n\n"
            "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n"
            "Örnek Talep (yalnızca birincil IP için):\n"
            f'"{host} {old}" kaydının "{host} {new}" olacak şekilde DNS kaydının '
            "güncellenmesini rica ederiz."
        )
    return [
        item1,
        (
            "İzleme tanımlarının güncellenmesi üzere ilgili ekipler bilgilendirilmelidir.\n\n"
            "Örnek Mail:\n"
            "To: Sistem İzleme ve Hizmet Analiz İşletimi, Sistem İşletim ve İzleme, "
            "Altyapı İzleme\n"
            "CC: Unix Linux Sistem Tasarım ve Planlama\n\n"
            f'"{host}" ("{old}") isimli sunucuda ip değişikliği yapılmıştır. '
            f'"{host}" ==> "{new}" olarak güncellenmiştir.\n'
            "Gerekli izleme kayıtları düzenlemesinin yapılmasını rica ederiz."
        ),
    ]


def _parse_resolv_conf(text: str) -> dict[str, Any]:
    searches: list[str] = []
    nameservers: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts:
            continue
        key = parts[0].lower()
        if key == "search":
            searches.extend(parts[1:])
        elif key == "domain" and len(parts) > 1 and not searches:
            searches.append(parts[1])
        elif key == "nameserver" and len(parts) > 1:
            nameservers.append(parts[1])
    return {"dns": nameservers, "dns_search": searches}


def _split_hostname(fqdn: str, short_hint: str = "", domain_hint: str = "") -> tuple[str, str, str]:
    f = (fqdn or "").strip().rstrip(".").lower()
    short = (short_hint or "").strip().rstrip(".").lower()
    domain = (domain_hint or "").strip().rstrip(".").lower()
    if f and "." in f:
        head, _, rest = f.partition(".")
        short = short or head
        domain = domain or rest
    elif f:
        short = short or f
    if not f and short and domain:
        f = f"{short}.{domain}"
    elif not f:
        f = short
    return short, domain, f


def list_usable_interfaces(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    """
    UP + excluded değil + VLAN değil + yönetim iface gizli.
    Bond slave / ethernet seçimi için.
    """
    mgmt = vlan_mod._mgmt_iface(session, server)
    script = r"""
set +e
ip -br link show 2>/dev/null | while read -r name state rest; do
  [ -z "$name" ] && continue
  name="${name%%@*}"
  echo "$name|$state"
done
"""
    r = run_ssh(session, server, script, timeout=25)
    rows: list[dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        name, state = line.split("|", 1)
        name = name.strip()
        state = state.strip().upper()
        if not name or name == "lo":
            continue
        if "." in name:
            continue
        if _EXCLUDED_IFACE_RE.search(name):
            continue
        if "UP" not in state:
            continue
        is_mgmt = name == mgmt
        rows.append(
            {
                "name": name,
                "state": state,
                "is_mgmt": is_mgmt,
                "hidden": is_mgmt,
                "usable": not is_mgmt,
            }
        )
    return rows


def next_bond_name(session: Session, server: TargetServer) -> str:
    r = run_ssh(
        session,
        server,
        "ip -br link show 2>/dev/null | awk '{print $1}' | sed 's/@.*//'; "
        "nmcli -t -f DEVICE,NAME con show 2>/dev/null",
        timeout=20,
    )
    text = r.stdout or ""
    used: set[int] = set()
    for m in re.finditer(r"\bbond(\d+)\b", text, flags=re.IGNORECASE):
        used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"bond{n}"


def list_ip_change_inventory(session: Session, server: TargetServer) -> dict[str, Any]:
    """
    IP Değişikliği envanteri:
    - docker/ilo/idrac/... hariç, üzerinde IPv4 olan tüm iface (bond + vlan dahil)
    - ana IP: varsayılan route (dev/src) + Dropt nslookup teyidi
    - DNS/dns-search: /etc/resolv.conf (ana IP için formda kullanılır)
    """
    script = r"""
set +e
echo "===HOST==="
echo "SHORT=$(hostname -s 2>/dev/null)"
echo "DOMAIN=$(hostname -d 2>/dev/null)"
echo "FQDN=$(hostname -f 2>/dev/null)"
echo "===DEFAULT==="
ip -4 route get 8.8.8.8 2>/dev/null | head -n1
echo "===ADDR==="
ip -4 -o addr show 2>/dev/null | while read -r num name fam cidr rest; do
  [ -z "$name" ] && continue
  name="${name%%@*}"
  echo "$name|$cidr"
done
echo "===RESOLV==="
cat /etc/resolv.conf 2>/dev/null
echo "===RESOLV_END==="
echo "===NM==="
ip -4 -o addr show 2>/dev/null | awk '{print $2}' | sed 's/@.*//' | sort -u | while read -r dev; do
  [ -z "$dev" ] && continue
  conn=$(nmcli -t -f GENERAL.CONNECTION device show "$dev" 2>/dev/null | head -n1 | cut -d: -f2-)
  [ -z "$conn" ] || [ "$conn" = "--" ] && conn="$dev"
  gw=$(nmcli -g IP4.GATEWAY connection show "$conn" 2>/dev/null | head -n1)
  vlan=$(nmcli -g vlan.id connection show "$conn" 2>/dev/null | head -n1)
  echo "DEV=$dev|CONN=$conn|GW=${gw}|VLAN=${vlan}"
done
echo "===NM_END==="
"""
    r = run_ssh(session, server, script, timeout=45)
    if not (r.stdout or "").strip() and not r.ok:
        raise RuntimeError(r.stderr.strip() or "IP envanteri alınamadı")

    short = domain = fqdn = ""
    default_line = ""
    addr_pairs: list[tuple[str, str]] = []
    resolv_lines: list[str] = []
    nm_by_dev: dict[str, dict[str, str]] = {}
    section = ""
    for line in (r.stdout or "").splitlines():
        if line.startswith("==="):
            if line.startswith("===HOST"):
                section = "host"
            elif line.startswith("===DEFAULT"):
                section = "default"
            elif line.startswith("===ADDR"):
                section = "addr"
            elif line.startswith("===RESOLV_END"):
                section = ""
            elif line.startswith("===RESOLV"):
                section = "resolv"
            elif line.startswith("===NM_END"):
                section = ""
            elif line.startswith("===NM"):
                section = "nm"
            else:
                section = ""
            continue
        if section == "host":
            if line.startswith("SHORT="):
                short = line.split("=", 1)[1].strip()
            elif line.startswith("DOMAIN="):
                domain = line.split("=", 1)[1].strip()
            elif line.startswith("FQDN="):
                fqdn = line.split("=", 1)[1].strip()
        elif section == "default" and line.strip():
            default_line = line.strip()
        elif section == "addr" and "|" in line:
            name, cidr = line.split("|", 1)
            addr_pairs.append((name.strip(), cidr.strip()))
        elif section == "resolv":
            resolv_lines.append(line)
        elif section == "nm" and line.startswith("DEV="):
            parts = dict(p.split("=", 1) for p in line.split("|") if "=" in p)
            dev = parts.get("DEV", "").strip()
            if dev:
                nm_by_dev[dev] = {
                    "conn": parts.get("CONN", "").strip() or dev,
                    "gateway": parts.get("GW", "").strip(),
                    "vlan": parts.get("VLAN", "").strip(),
                }

    # default route dev + src
    default_dev = ""
    default_src = ""
    m_dev = re.search(r"\bdev\s+(\S+)", default_line)
    m_src = re.search(r"\bsrc\s+(\S+)", default_line)
    if m_dev:
        default_dev = m_dev.group(1).split("@")[0]
    if m_src:
        default_src = m_src.group(1)

    portal_ip = (server.ip or "").strip()
    short, domain, fqdn = _split_hostname(fqdn, short, domain)
    # Portal hostname hint
    portal_host = (server.hostname or "").strip().rstrip(".")
    if portal_host and "." in portal_host and not domain:
        _, _, fqdn2 = _split_hostname(portal_host)
        if fqdn2:
            short, domain, fqdn = _split_hostname(fqdn2, short, domain)
    elif portal_host and not short:
        short = portal_host.split(".")[0]

    ns_forward_host = portal_nslookup(short or portal_host)
    ns_forward_fqdn = portal_nslookup(fqdn) if fqdn and fqdn != short else {"ok": False}
    ns_reverse = portal_nslookup(portal_ip) if portal_ip else {"ok": False, "query": portal_ip}

    # Prefer nslookup FQDN when available
    ns_fqdn = None
    ns_ip = None
    for nsr in (ns_forward_fqdn, ns_forward_host, ns_reverse):
        if nsr.get("ok") and nsr.get("fqdn"):
            ns_fqdn = nsr["fqdn"]
            break
    for nsr in (ns_forward_fqdn, ns_forward_host, ns_reverse):
        if nsr.get("ok") and nsr.get("ip"):
            ns_ip = nsr["ip"]
            break
    if ns_fqdn:
        short, domain, fqdn = _split_hostname(ns_fqdn, short, domain)

    resolv = _parse_resolv_conf("\n".join(resolv_lines))

    # Aggregate addrs by device (first IPv4)
    by_dev: dict[str, dict[str, Any]] = {}
    for name, cidr in addr_pairs:
        if not name or name == "lo":
            continue
        if _EXCLUDED_IFACE_RE.search(name):
            continue
        try:
            iface = ipaddress.ip_interface(cidr.split()[0] if " " in cidr else cidr)
        except ValueError:
            continue
        if iface.version != 4:
            continue
        if name in by_dev:
            continue
        nm = nm_by_dev.get(name) or {}
        vlan_id = None
        vlan_raw = (nm.get("vlan") or "").strip()
        if vlan_raw.isdigit():
            vlan_id = int(vlan_raw)
        elif "." in name:
            tail = name.rsplit(".", 1)[-1]
            if tail.isdigit():
                vlan_id = int(tail)
        ip_s = str(iface.ip)
        reasons: list[str] = []
        if default_dev and name == default_dev:
            reasons.append("default_route")
        if default_src and ip_s == default_src:
            reasons.append("default_src")
        if ns_ip and ip_s == ns_ip:
            reasons.append("nslookup_forward")
        if portal_ip and ip_s == portal_ip:
            reasons.append("portal_ip")
            if ns_reverse.get("ok"):
                reasons.append("nslookup_reverse")
        is_primary = bool(reasons) and (
            "default_route" in reasons
            or "default_src" in reasons
            or "nslookup_forward" in reasons
            or ("portal_ip" in reasons and "nslookup_reverse" in reasons)
            or ("portal_ip" in reasons and "default_route" in reasons)
        )
        # Soft primary: default route wins; else nslookup IP match
        if not is_primary:
            is_primary = ("default_route" in reasons) or (
                "nslookup_forward" in reasons
            ) or ("default_src" in reasons)
            if not is_primary and "portal_ip" in reasons and ns_reverse.get("ok"):
                is_primary = True

        by_dev[name] = {
            "name": name,
            "ip": ip_s,
            "subnet": int(iface.network.prefixlen),
            "ip_cidr": str(iface.with_prefixlen),
            "gateway": (nm.get("gateway") or "") if (nm.get("gateway") not in {"", "--"}) else "",
            "vlan_id": vlan_id,
            "conn_name": nm.get("conn") or name,
            "is_primary": is_primary,
            "primary_reasons": reasons,
            "has_vlan": vlan_id is not None,
        }

    interfaces = sorted(by_dev.values(), key=lambda x: (not x["is_primary"], x["name"]))
    # Ensure at most one primary: prefer default_route, then nslookup, then portal
    primaries = [i for i in interfaces if i["is_primary"]]
    if len(primaries) > 1:
        def _rank(row: dict[str, Any]) -> int:
            rs = row.get("primary_reasons") or []
            if "default_route" in rs:
                return 0
            if "default_src" in rs:
                return 1
            if "nslookup_forward" in rs:
                return 2
            if "nslookup_reverse" in rs:
                return 3
            return 9

        winner = sorted(primaries, key=_rank)[0]["name"]
        for row in interfaces:
            row["is_primary"] = row["name"] == winner

    return {
        "server_id": server.id,
        "hostname": server.hostname,
        "portal_ip": portal_ip,
        "short_name": short,
        "domain": domain,
        "fqdn": fqdn,
        "default_route": {
            "raw": default_line,
            "dev": default_dev,
            "src": default_src,
        },
        "nslookup": {
            "forward_short": ns_forward_host,
            "forward_fqdn": ns_forward_fqdn,
            "reverse_portal_ip": ns_reverse,
            "resolved_ip": ns_ip,
            "resolved_fqdn": ns_fqdn or fqdn,
        },
        "dns": resolv["dns"],
        "dns_search": resolv["dns_search"],
        "interfaces": interfaces,
    }


def _parse_dns_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[\s,;]+", raw.strip())
        return [p.strip() for p in parts if p.strip()]
    return [str(x).strip() for x in raw if str(x).strip()]


def _validate_change_ip(session: Session, server: TargetServer, payload: dict[str, Any]) -> dict[str, Any]:
    inv = list_ip_change_inventory(session, server)
    iface_name = (payload.get("interface") or payload.get("ifname") or "").strip()
    if not iface_name:
        raise ValueError("Interface seçin")
    current = next((i for i in inv["interfaces"] if i["name"] == iface_name), None)
    if current is None:
        raise ValueError(f"IP taşıyan uygun interface değil: {iface_name}")

    ipd = _validate_common_ip(payload)
    is_primary = bool(current.get("is_primary"))

    vlan_id = current.get("vlan_id")
    if current.get("has_vlan"):
        raw_vid = payload.get("vlan_id")
        if raw_vid is None or str(raw_vid).strip() == "":
            raise ValueError("VLAN ID zorunlu (mevcut VLAN arayüzü)")
        try:
            vlan_id = int(raw_vid)
        except (TypeError, ValueError) as exc:
            raise ValueError("VLAN ID sayı olmalı") from exc
        if vlan_id < 1 or vlan_id > 4094:
            raise ValueError("VLAN ID 1–4094 arasında olmalı")
    else:
        vlan_id = None

    dns: list[str] = []
    dns_search: list[str] = []
    if is_primary:
        dns = _parse_dns_list(payload.get("dns") if payload.get("dns") is not None else inv.get("dns"))
        dns_search = _parse_dns_list(
            payload.get("dns_search") if payload.get("dns_search") is not None else inv.get("dns_search")
        )
        if not dns:
            raise ValueError("Ana IP arayüzünde en az bir DNS (nameserver) zorunlu")
        if not dns_search:
            raise ValueError("Ana IP arayüzünde dns-search zorunlu")
        for d in dns:
            try:
                ipaddress.ip_address(d)
            except ValueError as exc:
                raise ValueError(f"Geçersiz DNS: {d}") from exc

    old_ip = current["ip"]
    new_ip = ipd["ip"]
    fqdn = inv.get("fqdn") or server.hostname or ""
    ticket = ""
    if old_ip != new_ip and fqdn:
        ticket = build_dns_ticket_text(fqdn=str(fqdn), old_ip=old_ip, new_ip=new_ip)

    parent = None
    if vlan_id is not None and "." in iface_name:
        parent = iface_name.rsplit(".", 1)[0]

    # IP conflict on another iface
    if new_ip != old_ip:
        owner = next((i["name"] for i in inv["interfaces"] if i["ip"] == new_ip and i["name"] != iface_name), None)
        if owner:
            raise ValueError(f"IP {new_ip} zaten {owner} üzerinde")

    return {
        **ipd,
        "interface": iface_name,
        "conn_name": current.get("conn_name") or iface_name,
        "old_ip": old_ip,
        "old_subnet": current.get("subnet"),
        "old_gateway": current.get("gateway") or "",
        "old_vlan_id": current.get("vlan_id"),
        "vlan_id": vlan_id,
        "parent": parent,
        "is_primary": is_primary,
        "dns": dns,
        "dns_search": dns_search,
        "old_dns": list(inv.get("dns") or []),
        "old_dns_search": list(inv.get("dns_search") or []),
        "short_name": inv.get("short_name") or "",
        "domain": inv.get("domain") or "",
        "fqdn": fqdn,
        "nslookup": inv.get("nslookup") or {},
        "dns_ticket_text": ticket,
        "update_portal_ip": is_primary and new_ip != (server.ip or "").strip(),
    }


def _change_ip_commands(data: dict[str, Any]) -> list[str]:
    conn = data["conn_name"]
    iface = data["interface"]
    cmds: list[str] = []
    old_vid = data.get("old_vlan_id")
    new_vid = data.get("vlan_id")
    parent = data.get("parent")
    dns_args = ""
    if data.get("is_primary") and data.get("dns"):
        dns_args = (
            f" ipv4.dns \"{' '.join(data['dns'])}\""
            f" ipv4.dns-search \"{' '.join(data['dns_search'])}\""
        )
    never = "" if data.get("is_primary") else " ipv4.never-default yes"

    if old_vid is not None and new_vid is not None and int(old_vid) != int(new_vid) and parent:
        new_conn = f"{parent}.{int(new_vid)}"
        cmds.append(f"nmcli connection delete {shlex.quote(conn)} 2>/dev/null || true")
        cmds.append(
            "nmcli con add type vlan "
            f"con-name {new_conn} ifname {new_conn} "
            f"dev {parent} id {int(new_vid)} "
            f"ipv4.addresses {data['ip_cidr']} ipv4.gateway {data['gateway']} "
            f"ipv4.method manual ipv6.method disabled{never}{dns_args}"
        )
        cmds.append(f"nmcli connection up {new_conn}")
        cmds.append(_HPSA_TAIL)
        return cmds

    mods = [
        "ipv4.method manual",
        f"ipv4.addresses {data['ip_cidr']}",
        f"ipv4.gateway {data['gateway']}",
        "ipv6.method disabled",
    ]
    if data.get("is_primary"):
        mods.append("ipv4.never-default no")
        if data.get("dns"):
            mods.append(f"ipv4.dns \"{' '.join(data['dns'])}\"")
        if data.get("dns_search"):
            mods.append(f"ipv4.dns-search \"{' '.join(data['dns_search'])}\"")
    else:
        mods.append("ipv4.never-default yes")

    cmds.append(f"nmcli connection modify {shlex.quote(conn)} " + " ".join(mods))
    cmds.append(f"nmcli connection up {shlex.quote(conn)}")
    cmds.append(f"ip -br addr show {shlex.quote(iface)} || true")
    if data.get("is_primary") and data.get("dns"):
        search = " ".join(data["dns_search"])
        ns = " ".join(data["dns"])
        cmds.append(f"# /etc/resolv.conf ← search {search}; nameserver {ns}")
        cmds.append("cat > /etc/resolv.conf <<'EOF'")
        cmds.append(f"search {search}")
        for n in data["dns"]:
            cmds.append(f"nameserver {n}")
        cmds.append("EOF")
    # Aynı SSH oturumunda (bağlantı kopmadan); hata IP job'unu bozmaz
    cmds.append(_HPSA_TAIL)
    return cmds


def _validate_common_ip(payload: dict[str, Any]) -> dict[str, Any]:
    ip = (payload.get("ip") or payload.get("address") or "").strip()
    gateway = (payload.get("gateway") or "").strip()
    prefix_raw = payload.get("subnet") if payload.get("subnet") is not None else payload.get("prefix")
    try:
        prefix = int(prefix_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Subnet (prefix) seçin") from exc
    if prefix not in ALLOWED_PREFIXES:
        raise ValueError("Subnet /8–/30 aralığında olmalı")
    if not ip:
        raise ValueError("IP zorunlu")
    if not gateway:
        raise ValueError("Gateway zorunlu")
    ip = validate_host_ipv4(ip)
    gateway = validate_gateway_ipv4(gateway)
    iface = ipaddress.ip_interface(f"{ip}/{prefix}")
    gw = ipaddress.ip_address(gateway)
    if gw not in iface.network:
        raise ValueError(f"Gateway, {iface.network} ağı içinde olmalı")
    if gw == iface.ip:
        raise ValueError("Gateway, IP ile aynı olamaz")
    return {
        "ip": str(iface.ip),
        "subnet": prefix,
        "ip_cidr": str(iface.with_prefixlen),
        "gateway": str(gw),
    }


def _optional_vlan_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("vlan_id")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        vid = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("VLAN ID sayı olmalı") from exc
    if vid < 1 or vid > 4094:
        raise ValueError("VLAN ID 1–4094 arasında olmalı")
    return vid


def _validate_add_network(session: Session, server: TargetServer, payload: dict[str, Any]) -> dict[str, Any]:
    ctype = (payload.get("connection_type") or "ethernet").strip().lower()
    if ctype not in {"ethernet", "bond"}:
        raise ValueError("Connection type: ethernet veya bond")

    ipd = _validate_common_ip(payload)
    vlan_id = _optional_vlan_id(payload)
    usable = [i for i in list_usable_interfaces(session, server) if i.get("usable")]
    usable_names = {i["name"] for i in usable}

    if ctype == "ethernet":
        iface = (payload.get("interface") or payload.get("parent") or "").strip()
        if not iface or not re.match(r"^[a-zA-Z0-9_-]+$", iface):
            raise ValueError("Interface seçin")
        if iface not in usable_names:
            raise ValueError(f"Kullanılabilir interface değil: {iface}")
        out = {
            **ipd,
            "connection_type": "ethernet",
            "interface": iface,
            "vlan_id": vlan_id,
            "mode": None,
            "slaves": [],
            "bond_name": None,
            "access": vlan_id is None,
        }
        if vlan_id is not None:
            out["conn_name"] = f"{iface}.{vlan_id}"
            out["ifname"] = out["conn_name"]
            out["parent"] = iface
        else:
            out["conn_name"] = iface
            out["ifname"] = iface
        return out

    # bond
    mode = str(payload.get("mode") or "1").strip()
    if mode not in BOND_MODES:
        raise ValueError("Bond mode: 1, 4 veya 6")
    slaves_raw = payload.get("slaves") or payload.get("bond_slaves") or []
    if isinstance(slaves_raw, str):
        slaves = [s.strip() for s in slaves_raw.split(",") if s.strip()]
    else:
        slaves = [str(s).strip() for s in slaves_raw if str(s).strip()]
    if len(slaves) < 1:
        raise ValueError("En az bir bond slave seçin")
    for s in slaves:
        if s not in usable_names:
            raise ValueError(f"Slave kullanılabilir değil: {s}")
    if len(set(slaves)) != len(slaves):
        raise ValueError("Slave listesinde tekrar var")

    bond_name = (payload.get("bond_name") or "").strip() or next_bond_name(session, server)
    if not re.match(r"^bond\d+$", bond_name, flags=re.IGNORECASE):
        raise ValueError("Geçersiz bond adı")

    out = {
        **ipd,
        "connection_type": "bond",
        "interface": bond_name,
        "bond_name": bond_name,
        "mode": mode,
        "mode_label": BOND_MODES[mode],
        "slaves": slaves,
        "vlan_id": vlan_id,
        "access": vlan_id is None,
    }
    if vlan_id is not None:
        out["conn_name"] = f"{bond_name}.{vlan_id}"
        out["ifname"] = out["conn_name"]
        out["parent"] = bond_name
    else:
        out["conn_name"] = bond_name
        out["ifname"] = bond_name
    return out


def _delete_conn_cmds(names: list[str]) -> list[str]:
    cmds = []
    for n in names:
        q = shlex.quote(n)
        cmds.append(f"nmcli connection delete {q} 2>/dev/null || true")
    return cmds


def _planned_commands(data: dict[str, Any]) -> list[str]:
    ctype = data["connection_type"]
    vlan_id = data.get("vlan_id")
    cmds: list[str] = []

    if ctype == "ethernet":
        iface = data["interface"]
        cmds.extend(_delete_conn_cmds([iface]))
        if vlan_id is None:
            cmds.append(
                f"nmcli connection add type ethernet ifname {iface} con-name {iface} "
                f"ipv4.addresses {data['ip_cidr']} ipv4.gateway {data['gateway']} "
                f"ipv4.method manual ipv6.method disabled ipv4.never-default yes"
            )
            cmds.append(f"nmcli connection up {iface}")
        else:
            # Add VLAN path on parent
            cmds.append(vlan_mod._nmcli_add_cmd({**data, "parent": iface}))
            cmds.append("sleep 3.5")
            cmds.append(vlan_mod._nmcli_bounce_cmd(data))
        return cmds

    # bond
    bond = data["bond_name"]
    mode = data["mode"]
    slaves = list(data["slaves"])
    cmds.extend(_delete_conn_cmds(slaves + [bond, data["conn_name"]]))
    if vlan_id is None:
        cmds.append(
            f"nmcli connection add type bond ifname {bond} con-name {bond} mode {mode} "
            f"ip4 {data['ip_cidr']} gw4 {data['gateway']} "
            f"ipv4.method manual ipv6.method disabled ipv4.never-default yes"
        )
        for s in slaves:
            cmds.append(
                f"nmcli connection add type ethernet ifname {s} con-name {s}-slave "
                f"master {bond} slave-type bond"
            )
        cmds.append(f"nmcli connection up {bond}")
    else:
        cmds.append(
            f"nmcli connection add type bond ifname {bond} con-name {bond} mode {mode} "
            f"ipv4.method disabled ipv6.method disabled"
        )
        for s in slaves:
            cmds.append(
                f"nmcli connection add type ethernet ifname {s} con-name {s}-slave "
                f"master {bond} slave-type bond"
            )
        cmds.append(f"nmcli connection up {bond}")
        cmds.append(vlan_mod._nmcli_add_cmd({**data, "parent": bond}))
        cmds.append("sleep 3.5")
        cmds.append(vlan_mod._nmcli_bounce_cmd(data))
    return cmds


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    if action == "add_vlan":
        return vlan_mod.build_plans(session, "add", servers, payload)
    if action == "change_ip":
        plans: list[HostPlan] = []
        for server in servers:
            try:
                data = _validate_change_ip(session, server, payload)
                cmds = _change_ip_commands(data)
                risk = (
                    "Ana IP değişiminde SSH bağlantısı kopabilir. "
                    "Uygulama sonrası DNS Tanımı → Dns Kayıt Değiştirme talebi açılmalıdır."
                    if data.get("is_primary")
                    else "İkincil arayüz IP değişikliği; DNS alanları güncellenmez."
                )
                if data.get("dns_ticket_text"):
                    risk += f" Talep önerisi: {data['dns_ticket_text']}"
                plans.append(
                    HostPlan(
                        server_id=server.id,  # type: ignore[arg-type]
                        hostname=server.hostname,
                        ip=server.ip,
                        ok=True,
                        summary_tr=(
                            f"{server.hostname}: IP Değişikliği {data['interface']} "
                            f"{data['old_ip']} → {data['ip_cidr']}"
                            + (" (ana IP)" if data.get("is_primary") else "")
                        ),
                        planned_commands=cmds,
                        before_state=data,
                        risk_notes=risk,
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
    if action != "add_network":
        raise ValueError(f"Bilinmeyen aksiyon: {action}")

    plans = []
    for server in servers:
        try:
            data = _validate_add_network(session, server, payload)
            if data.get("vlan_id") is not None and data["connection_type"] == "ethernet":
                vlan_mod._check_vlan_conflicts(
                    session,
                    server,
                    {
                        "ifname": data["ifname"],
                        "ip": data["ip"],
                        "conn_name": data["conn_name"],
                    },
                )
            cmds = _planned_commands(data)
            kind = "access" if data.get("access") else "trunk(vlan)"
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=(
                        f"{server.hostname}: Add Network {data['connection_type']} "
                        f"{data['ifname']} {data['ip_cidr']} ({kind})"
                    ),
                    planned_commands=cmds,
                    before_state=data,
                    risk_notes=(
                        "Mevcut connection silinebilir; yanlış gateway SSH kopmasına yol açabilir. "
                        "Yönetim arayüzü listelenmez."
                    ),
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
    if action == "add_vlan":
        return vlan_mod.apply_plan(session, server, "add", payload, plan, job_id=job_id)
    if action == "change_ip":
        return _apply_change_ip(session, server, payload, plan, job_id=job_id)
    _ = (job_id, payload)
    if action != "add_network":
        return False, {}, "", f"Bilinmeyen aksiyon: {action}"
    if not plan.ok:
        return False, plan.before_state, "", plan.error

    d = dict(plan.before_state)
    # Re-validate live
    try:
        d = _validate_add_network(session, server, {**payload, **d})
    except ValueError as exc:
        return False, plan.before_state, "", str(exc)

    parts: list[str] = ["set -e"]
    ctype = d["connection_type"]
    vlan_id = d.get("vlan_id")

    def sh_del(name: str) -> str:
        return f"nmcli connection delete {shlex.quote(name)} 2>/dev/null || true"

    if ctype == "ethernet":
        iface = d["interface"]
        parts.append(sh_del(iface))
        if vlan_id is None:
            parts.append(
                "nmcli connection add type ethernet "
                f"ifname {shlex.quote(iface)} con-name {shlex.quote(iface)} "
                f"ipv4.addresses {shlex.quote(d['ip_cidr'])} "
                f"ipv4.gateway {shlex.quote(d['gateway'])} "
                "ipv4.method manual ipv6.method disabled ipv4.never-default yes"
            )
            parts.append(f"nmcli connection up {shlex.quote(iface)}")
            parts.append(f"ip -br addr show {shlex.quote(iface)} || true")
        else:
            # delegate VLAN create (parent already cleaned of default conn)
            parent = iface
            conn = d["conn_name"]
            parts.append(
                "nmcli con add type vlan "
                f"con-name {shlex.quote(conn)} ifname {shlex.quote(conn)} "
                f"dev {shlex.quote(parent)} id {int(vlan_id)} "
                f"ipv4.addresses {shlex.quote(d['ip_cidr'])} "
                f"ipv4.gateway {shlex.quote(d['gateway'])} "
                "ipv4.method manual ipv6.method disabled ipv4.never-default yes"
            )
            parts.append("sleep 3.5")
            parts.append(f"nmcli con down {shlex.quote(conn)}; nmcli con up {shlex.quote(conn)}")
            parts.append(f"ip -br addr show {shlex.quote(conn)} || true")
    else:
        bond = d["bond_name"]
        mode = d["mode"]
        slaves = list(d["slaves"])
        for s in slaves:
            parts.append(sh_del(s))
            parts.append(sh_del(f"{s}-slave"))
        parts.append(sh_del(bond))
        parts.append(sh_del(d["conn_name"]))
        if vlan_id is None:
            parts.append(
                "nmcli connection add type bond "
                f"ifname {shlex.quote(bond)} con-name {shlex.quote(bond)} mode {shlex.quote(mode)} "
                f"ip4 {shlex.quote(d['ip_cidr'])} gw4 {shlex.quote(d['gateway'])} "
                "ipv4.method manual ipv6.method disabled ipv4.never-default yes"
            )
            for s in slaves:
                parts.append(
                    "nmcli connection add type ethernet "
                    f"ifname {shlex.quote(s)} con-name {shlex.quote(s + '-slave')} "
                    f"master {shlex.quote(bond)} slave-type bond"
                )
            parts.append(f"nmcli connection up {shlex.quote(bond)}")
            parts.append(f"ip -br addr show {shlex.quote(bond)} || true")
        else:
            parts.append(
                "nmcli connection add type bond "
                f"ifname {shlex.quote(bond)} con-name {shlex.quote(bond)} mode {shlex.quote(mode)} "
                "ipv4.method disabled ipv6.method disabled"
            )
            for s in slaves:
                parts.append(
                    "nmcli connection add type ethernet "
                    f"ifname {shlex.quote(s)} con-name {shlex.quote(s + '-slave')} "
                    f"master {shlex.quote(bond)} slave-type bond"
                )
            parts.append(f"nmcli connection up {shlex.quote(bond)}")
            conn = d["conn_name"]
            parts.append(
                "nmcli con add type vlan "
                f"con-name {shlex.quote(conn)} ifname {shlex.quote(conn)} "
                f"dev {shlex.quote(bond)} id {int(vlan_id)} "
                f"ipv4.addresses {shlex.quote(d['ip_cidr'])} "
                f"ipv4.gateway {shlex.quote(d['gateway'])} "
                "ipv4.method manual ipv6.method disabled ipv4.never-default yes"
            )
            parts.append("sleep 3.5")
            parts.append(f"nmcli con down {shlex.quote(conn)}; nmcli con up {shlex.quote(conn)}")
            parts.append(f"ip -br addr show {shlex.quote(conn)} || true")

    parts.append("echo OK")
    script = "\n".join(parts) + "\n"
    r = run_ssh(session, server, script, timeout=180)
    health = run_ssh(session, server, "echo alive", timeout=15)
    ok = r.ok and health.ok and "alive" in health.stdout
    after = {**d, "alive": health.ok, "checklist": ["ip addr / nmcli con show kontrol edin"]}
    if not ok and r.ok:
        # best-effort rollback of created conn
        run_ssh(
            session,
            server,
            f"nmcli con delete {shlex.quote(d['conn_name'])} 2>/dev/null || true; "
            f"nmcli con delete {shlex.quote(d.get('bond_name') or '')} 2>/dev/null || true; true",
            timeout=40,
        )
        after["rolled_back"] = True
    return ok, after, r.stdout + "\n" + health.stdout, r.stderr


def _apply_change_ip(
    session: Session,
    server: TargetServer,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    _ = job_id
    if not plan.ok:
        return False, plan.before_state, "", plan.error
    try:
        d = _validate_change_ip(session, server, {**payload, **dict(plan.before_state)})
    except ValueError as exc:
        return False, plan.before_state, "", str(exc)

    conn = d["conn_name"]
    parts: list[str] = ["set -e"]
    old_vid = d.get("old_vlan_id")
    new_vid = d.get("vlan_id")
    parent = d.get("parent")

    if old_vid is not None and new_vid is not None and int(old_vid) != int(new_vid) and parent:
        new_conn = f"{parent}.{int(new_vid)}"
        parts.append(f"nmcli connection delete {shlex.quote(conn)} 2>/dev/null || true")
        dns_bits = ""
        if d.get("is_primary") and d.get("dns"):
            dns_bits = (
                f" ipv4.dns {shlex.quote(' '.join(d['dns']))}"
                f" ipv4.dns-search {shlex.quote(' '.join(d['dns_search']))}"
            )
        never = "" if d.get("is_primary") else " ipv4.never-default yes"
        parts.append(
            "nmcli con add type vlan "
            f"con-name {shlex.quote(new_conn)} ifname {shlex.quote(new_conn)} "
            f"dev {shlex.quote(parent)} id {int(new_vid)} "
            f"ipv4.addresses {shlex.quote(d['ip_cidr'])} "
            f"ipv4.gateway {shlex.quote(d['gateway'])} "
            f"ipv4.method manual ipv6.method disabled{never}{dns_bits}"
        )
        parts.append(f"nmcli connection up {shlex.quote(new_conn)}")
        d["conn_name"] = new_conn
        d["interface"] = new_conn
    else:
        mod = [
            "nmcli connection modify",
            shlex.quote(conn),
            "ipv4.method manual",
            f"ipv4.addresses {shlex.quote(d['ip_cidr'])}",
            f"ipv4.gateway {shlex.quote(d['gateway'])}",
            "ipv6.method disabled",
        ]
        if d.get("is_primary"):
            mod.append("ipv4.never-default no")
            if d.get("dns"):
                mod.append(f"ipv4.dns {shlex.quote(' '.join(d['dns']))}")
            if d.get("dns_search"):
                mod.append(f"ipv4.dns-search {shlex.quote(' '.join(d['dns_search']))}")
        else:
            mod.append("ipv4.never-default yes")
        parts.append(" ".join(mod))
        parts.append(f"nmcli connection up {shlex.quote(conn)}")
        parts.append(f"ip -br addr show {shlex.quote(d['interface'])} || true")
        if d.get("is_primary") and d.get("dns"):
            search = " ".join(d["dns_search"])
            resolv = f"search {search}\n" + "\n".join(f"nameserver {n}" for n in d["dns"]) + "\n"
            parts.append(f"cat > /etc/resolv.conf <<'DROPT_EOF'\n{resolv}DROPT_EOF")

    # IP up sonrası aynı oturumda HPSA; || true ile set -e etkilemez
    parts.append(_HPSA_TAIL)
    parts.append("echo OK")
    script = "\n".join(parts) + "\n"

    # Primary IP change: run once over current portal SSH; then health via new IP if needed
    r = run_ssh(session, server, script, timeout=180)
    health = run_ssh(session, server, "echo alive", timeout=20)
    if (not health.ok or "alive" not in (health.stdout or "")) and d.get("update_portal_ip"):
        previous_ip = server.ip
        server.ip = d["ip"]
        health2 = run_ssh(session, server, "echo alive", timeout=20)
        if health2.ok and "alive" in (health2.stdout or ""):
            session.add(server)
            session.commit()
            session.refresh(server)
            health = health2
        else:
            server.ip = previous_ip

    ok = r.ok and health.ok and "alive" in (health.stdout or "")
    if ok and d.get("update_portal_ip") and (server.ip or "").strip() != d["ip"]:
        server.ip = d["ip"]
        session.add(server)
        session.commit()
        session.refresh(server)

    fqdn = str(d.get("fqdn") or "").strip()
    after = {
        **d,
        "alive": health.ok,
        "portal_ip": server.ip,
        "dns_ticket_text": d.get("dns_ticket_text") or "",
        "checklist": build_ip_change_success_checklist(
            fqdn=fqdn,
            old_ip=str(d.get("old_ip") or ""),
            new_ip=str(d.get("ip") or ""),
            is_primary=bool(d.get("is_primary")),
            lang="tr",
        ),
        "checklist_en": build_ip_change_success_checklist(
            fqdn=fqdn,
            old_ip=str(d.get("old_ip") or ""),
            new_ip=str(d.get("ip") or ""),
            is_primary=bool(d.get("is_primary")),
            lang="en",
        ),
        "nslookup": d.get("nslookup") or {},
    }
    return ok, after, (r.stdout or "") + "\n" + (health.stdout or ""), r.stderr or ""
