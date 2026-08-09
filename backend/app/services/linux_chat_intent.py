"""
Linux chat niyet yardımcıları.

1) Direkt komut çıkarımı — NL içindeki 'ip bilgisi' gibi ifadeleri komut sanma.
2) Filo envanter soruları — hostname/IP: learned facts + canlı SSH + DB.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_IP_OBJECTS = {
    "a", "addr", "address", "link", "l", "route", "r",
    "neigh", "n", "rule", "maddr", "monitor", "netns",
    "ntable", "tunnel", "tuntap", "xfrm", "mroute", "mrule",
    "token", "tcpmetrics", "vrf", "sr", "maddress", "help",
}

_CMD_SPECS = [
    ("vmstat", 4), ("iostat", 4), ("sar", 4),
    ("netstat", 3), ("ss", 3), ("ps", 3),
    ("df", 2), ("du", 2), ("lsblk", 2), ("lscpu", 1),
    ("free", 2), ("lsmod", 1), ("uptime", 1),
    ("top", 3), ("ifconfig", 2), ("arp", 2),
    ("route", 2), ("ip", 4),
]

# NL içinde geçen ama argsız komut sanılmaması gerekenler (free space, top 20, …)
_BARE_CMD_GUARD = {"free", "df", "ss", "top", "ps", "route", "du", "uptime"}


_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
})


def _fold(s: str) -> str:
    s = (s or "").translate(_TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def extract_direct_commands(msg: str) -> List[str]:
    """Mesajdan çalıştırılacak Linux komutlarını çıkar.

    Çıplak `ip` / 'ip bilgisini' ASLA komut değildir — sadece ip addr, ip -br a vb.
    """
    tokens = (msg or "").split()
    found: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].lower().rstrip(".,?!")
        matched = False
        for cmd_name, max_args in _CMD_SPECS:
            if tok != cmd_name:
                continue
            parts = [tokens[i]]
            j = i + 1
            if cmd_name == "ip":
                if j >= len(tokens):
                    i += 1
                    matched = True
                    break
                nxt = tokens[j].rstrip(".,?!")
                nxt_l = nxt.lower()
                if not (nxt.startswith("-") or nxt_l in _IP_OBJECTS):
                    i += 1
                    matched = True
                    break
            count = 0
            while j < len(tokens) and count < max_args:
                arg = tokens[j].rstrip(".,?!")
                arg_l = arg.lower()
                if arg.startswith("-") or arg.lstrip("-").isdigit():
                    parts.append(arg)
                    count += 1
                    j += 1
                elif cmd_name == "ip" and (
                    arg_l in _IP_OBJECTS
                    or (count > 0 and arg_l in {
                        "show", "list", "add", "del", "delete",
                        "get", "set", "flush", "help",
                    })
                ):
                    parts.append(arg)
                    count += 1
                    j += 1
                else:
                    break
            if cmd_name == "ip" and len(parts) < 2:
                i = max(j, i + 1)
                matched = True
                break
            # free/df/top/… argsız NL false-positive
            if cmd_name in _BARE_CMD_GUARD and len(parts) == 1:
                fold_msg = _fold(msg)
                toks = [t.lower().rstrip(".,?!:") for t in (msg or "").split() if t.strip()]
                # "Admin: uptime" / "Lütfen uptime göster" → kısa komut niyeti
                skip_pfx = {"admin", "acil", "lutfen", "lütfen", "bilgi", "tekrar"}
                content = [t for t in toks if t not in skip_pfx and not t.startswith("tekrar")]
                short_cmd = (
                    bool(content)
                    and content[0] == cmd_name
                    and len(content) <= 4
                )
                cmd_intent = bool(re.search(
                    rf"(calistir|komut|run|execute|{re.escape(cmd_name)}\s+-)",
                    fold_msg,
                ))
                if not (short_cmd or cmd_intent):
                    i = max(j, i + 1)
                    matched = True
                    break
            cmd = " ".join(parts)
            if cmd not in found:
                found.append(cmd)
            i = j
            matched = True
            break
        if not matched:
            i += 1
    return found


# Pattern'ler _fold() sonrası ASCII-ish metinde çalışır (ı→i, ş→s, …)
_INVENTORY_STATUS_PATTERNS = [
    r"envanter\s*(durum|ozet|ozeti|sayi|kac|ne\s*kadar)",
    r"(kac|ne\s*kadar)\s+(sunucu|linux|host|makine)",
    r"sunucu\s*(sayisi|durumu|ozeti)",
    r"(filo|altyapi)\s*(ozet|durum|sayi)",
    r"ai\s*ready\s*(kac|sayi|durum)",
    r"inventory\s*(status|summary|count|overview)",
    r"how\s+many\s+servers",
]

_INVENTORY_PATTERNS = [
    r"hostname.{0,40}ip",
    r"ip.{0,40}hostname",
    r"hostname.{0,20}(ve|ile|&|/|,).{0,20}ip",
    r"makine\s*adi.{0,40}ip",
    r"ip\s*(adres|bilgi)",
    r"sunucu(lar(in|imizin)?)?\s*(listesi|envanter)",
    r"(hangi|tum|butun)\s+sunucu",
    r"sunucu(lar)?\s*(adi|isim|hostname|ip)",
    r"(fqdn|host\s*adi).{0,30}ip",
    r"ai\s*ready\s*sunucu",
    r"envanter\s*(ver|goster|listele)",
    r"(listele|goster|ver)\s*.{0,20}sunucu",
    r"isim.{0,20}(ve|ile|&|/|,).{0,20}ip",
    r"adlarini.{0,40}ip",
    r"\badi\b.{0,20}(ve|ile).{0,20}ip",
    r"kayitli.{0,40}sunucu",
    r"hangi.{0,30}sunucu.{0,30}(var|kayit)",
    r"linux\s+host",
    r"server\s+inventory",
    r"list\s+servers",
    r"inventory.{0,30}ip",
]


def is_inventory_status_query(msg: str) -> bool:
    """Sayı/özet envanter sorusu (hostname listesi değil) — platform-scoped DB özeti."""
    m = _fold(msg)
    if not m.strip():
        return False
    if extract_direct_commands(msg):
        return False
    for pat in _INVENTORY_STATUS_PATTERNS:
        if re.search(pat, m):
            return True
    return False


def is_fleet_inventory_query(msg: str) -> bool:
    """Hostname/IP veya sunucu listesi isteyen filo/envanter sorusu mu?"""
    m = _fold(msg)
    if not m.strip():
        return False
    cmds = extract_direct_commands(msg)
    if cmds:
        return False
    for pat in _INVENTORY_PATTERNS:
        if re.search(pat, m):
            return True
    if re.search(r"sunucu", m) and re.search(r"(bilgi|liste|neler|hangileri|kayit|kayıt)", m):
        if re.search(r"(hostname|fqdn|ip|adres|isim|\bad)", m):
            return True
    if re.search(r"sunucu", m) and re.search(r"\bip\b", m):
        if re.search(r"(hostname|fqdn|isim|\bad|adlar|makine)", m):
            return True
    return False


def parse_primary_ips(ip_brief: str) -> str:
    """ip -br addr / ip -o -4 çıktısından UP arayüz IPv4 listesi."""
    if not ip_brief:
        return ""
    ips: List[str] = []
    for line in ip_brief.splitlines():
        line = line.strip()
        if not line or line.startswith("lo"):
            continue
        # ip -br: eth0 UP 192.168.1.1/24 ...
        for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", line):
            ip = m.group(1)
            if ip.startswith("127."):
                continue
            if ip not in ips:
                ips.append(ip)
    return ", ".join(ips[:4])


def load_identity_overlays(db, server_ids: Sequence[int]) -> Dict[int, Dict[str, str]]:
    """LearnedFact'ten hostname_short / hostname_fqdn / ip_brief haritası."""
    out: Dict[int, Dict[str, str]] = {}
    if not server_ids:
        return out
    try:
        from app.models.learned_fact import LearnedFact
        rows = (
            db.query(LearnedFact)
            .filter(
                LearnedFact.server_id.in_(list(server_ids)),
                LearnedFact.key.in_(["hostname_short", "hostname_fqdn", "ip_brief", "network_interfaces"]),
            )
            .all()
        )
        for r in rows:
            slot = out.setdefault(r.server_id, {})
            if r.key == "hostname_fqdn" and r.value:
                slot["hostname_fqdn"] = r.value.strip().splitlines()[0][:120]
            elif r.key == "hostname_short" and r.value:
                slot["hostname_short"] = r.value.strip().splitlines()[0][:120]
            elif r.key == "ip_brief" and r.value:
                slot["live_ips"] = parse_primary_ips(r.value)
            elif r.key == "network_interfaces" and r.value and "live_ips" not in slot:
                slot["live_ips"] = parse_primary_ips(r.value)
    except Exception as e:
        logger.debug("load_identity_overlays: %s", e)
    return out


def format_fleet_inventory_answer(
    servers: Sequence[Any],
    title: Optional[str] = None,
    overlays: Optional[Dict[int, Dict[str, str]]] = None,
    live_ok: int = 0,
    live_fail: int = 0,
) -> str:
    """Hostname/IP tablosu — öncelik: canlı SSH > learned fact > DB."""
    overlays = overlays or {}
    rows: List[Tuple[str, str, str, str, str, str]] = []
    for s in servers:
        sid = getattr(s, "id", None)
        ov = overlays.get(sid, {}) if sid is not None else {}
        name = getattr(s, "name", None) or "-"
        host = (
            ov.get("hostname_fqdn")
            or ov.get("hostname_short")
            or getattr(s, "hostname", None)
            or getattr(s, "vm_guest_hostname", None)
            or name
            or "-"
        )
        ip = ov.get("live_ips") or getattr(s, "ip_address", None) or "-"
        os_info = getattr(s, "os_version", None) or getattr(s, "os_type", None) or "Linux"
        status = getattr(s, "status", None) or "-"
        src = ov.get("source") or ("learned" if (ov.get("hostname_short") or ov.get("hostname_fqdn")) else "db")
        rows.append((name, host, ip, os_info, str(status), src))

    hdr = title or "Linux sunucu envanteri (hostname / IP)"
    if not rows:
        return (
            f"## {hdr}\n\n"
            "AI Ready Linux sunucu kaydı bulunamadı. "
            "Sunucular → AI Ready işaretli Linux host ekleyin.\n"
        )

    lines = [
        f"## {hdr}",
        "",
        f"**{len(rows)}** sunucu:",
        "",
        "| Sunucu | Hostname (canlı/öğrenilmiş) | IP | OS | Durum | Kaynak |",
        "|---|---|---|---|---|---|",
    ]
    for name, host, ip, os_info, status, src in rows:
        lines.append(f"| {name} | {host} | {ip} | {os_info} | {status} | {src} |")
    lines.append("")
    note_parts = []
    if live_ok:
        note_parts.append(f"canlı SSH: {live_ok} host")
    if live_fail:
        note_parts.append(f"SSH başarısız: {live_fail}")
    note_parts.append("öğrenilmiş fact + DB yedek")
    lines.append("_Kaynak önceliği: canlı SSH → Bilgi Bankası (learned) → kayıtlı envanter. (" + "; ".join(note_parts) + ")_")
    return "\n".join(lines)


def collect_live_identity(
    servers: Sequence[Any],
    global_cred,
    db=None,
    ephemeral: bool = False,
) -> Tuple[Dict[int, Dict[str, str]], int, int]:
    """Filo için hafif SSH identity collect + fact öğrenme.

    Döner: (overlays, ok_count, fail_count)
    """
    from app.services.linux_info_collector import collect_server_info, cap_servers_for_ssh

    capped, _note = cap_servers_for_ssh(list(servers), "hostname ip identity")
    overlays: Dict[int, Dict[str, str]] = {}
    ok = fail = 0
    for s in capped:
        try:
            info = collect_server_info(s, ["identity"], global_cred, "hostname ip")
            if info.get("error"):
                fail += 1
                continue
            slot: Dict[str, str] = {"source": "ssh"}
            if info.get("hostname_fqdn"):
                slot["hostname_fqdn"] = str(info["hostname_fqdn"]).strip().splitlines()[0][:120]
            if info.get("hostname_short"):
                slot["hostname_short"] = str(info["hostname_short"]).strip().splitlines()[0][:120]
            if info.get("ip_brief"):
                slot["live_ips"] = parse_primary_ips(info["ip_brief"]) or slot.get("live_ips", "")
                # management IP yoksa DB ip kalsın; live_ips ek bilgi
            overlays[s.id] = slot
            ok += 1
            # DB hostname alanını canlı ile hizala (kalıcı öğrenme)
            live_hn = slot.get("hostname_short") or slot.get("hostname_fqdn")
            if live_hn and getattr(s, "hostname", None) != live_hn:
                try:
                    s.hostname = live_hn
                except Exception:
                    pass
            if db is not None and not ephemeral:
                try:
                    from app.services.fact_learning import extract_and_store_facts
                    extract_and_store_facts(db, s, info, platform="linux")
                except Exception as e:
                    logger.debug("identity fact store: %s", e)
        except Exception as e:
            logger.debug("identity collect %s: %s", getattr(s, "name", "?"), e)
            fail += 1
    if db is not None and ok and not ephemeral:
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    return overlays, ok, fail
