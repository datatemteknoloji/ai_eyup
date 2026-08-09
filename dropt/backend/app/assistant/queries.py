from __future__ import annotations

import ipaddress
import re
from typing import Any

from sqlmodel import Session, col, func, or_, select

from app.models.job import AuditLog, Job, JobStatus
from app.models.server import ServerStatus, TargetServer
from app.models.user import User, UserRole

_MAX_LIST = 40


def _norm(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("ı", "i").replace("ğ", "g").replace("ü", "u")
    t = t.replace("ş", "s").replace("ö", "o").replace("ç", "c")
    return t


def _ip_key(ip: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in ipaddress.ip_address((ip or "").strip()).packed)
    except ValueError:
        return None


def parse_ipv4_filter(message: str) -> dict[str, Any] | None:
    """
    Examples:
      192.168.1.100 altındaki / IP < 192.168.1.100
      100'ün altındaki IP (varsayılan 192.168.1.x)
      192.168.1.0/24
    """
    text = message or ""
    n = _norm(text)

    m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\s*/\s*(\d{1,2})\b", text)
    if m:
        try:
            net = ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False)
            return {"type": "cidr", "network": str(net)}
        except ValueError:
            pass

    # IP < 192.168.1.100  OR  < 192.168.1.100
    m = re.search(r"(<=|>=|<|>|=)\s*(\d{1,3}(?:\.\d{1,3}){3})\b", text)
    if m:
        sym = m.group(1)
        op = {"<": "lt", ">": "gt", "<=": "le", ">=": "ge", "=": "eq"}[sym]
        return {"type": "cmp", "op": op, "ip": m.group(2)}

    # 192.168.1.100 altındaki / üstündeki
    m = re.search(
        r"(\d{1,3}(?:\.\d{1,3}){3})\s*(?:ip\s*)?(alt[ıi]nda\w*|asag[ıi]\w*|ustunde\w*|üstünde\w*|yukar[ıi]\w*)",
        n,
    )
    if m:
        ip, cue = m.group(1), m.group(2)
        op = "lt" if any(x in cue for x in ("alt", "asag")) else "gt"
        return {"type": "cmp", "op": op, "ip": ip}

    # altındaki 192.168.1.100
    m = re.search(
        r"(alt[ıi]nda\w*|asag[ıi]\w*|ustunde\w*|üstünde\w*|yukar[ıi]\w*|below|under|above)\s*"
        r"(?:olan\s+)?(?:ip\s*)?(\d{1,3}(?:\.\d{1,3}){3})",
        n,
    )
    if m:
        cue, ip = m.group(1), m.group(2)
        op = "lt" if any(x in cue for x in ("alt", "asag", "below", "under")) else "gt"
        return {"type": "cmp", "op": op, "ip": ip}

    # 100 ip'nin altı / 100'ün altındaki ipler  (+ optional 192.168.1.)
    m = re.search(
        r"(?:(\d{1,3}(?:\.\d{1,3}){2})\.)?(\d{1,3})\s+"
        r"(?:ip\S*\s*)?(?:['’]?(?:un|ün|in|nin|nun)\s+)?"
        r"(alt[ıi]|asag[ıi]|below|under)",
        n,
    )
    if m:
        base = m.group(1) or "192.168.1"
        return {"type": "octet_lt", "base": base, "octet": int(m.group(2))}

    m = re.search(
        r"(?:(\d{1,3}(?:\.\d{1,3}){2})\.)?(\d{1,3})\s+"
        r"(?:ip\S*\s*)?(?:['’]?(?:un|ün|in|nin|nun)\s+)?"
        r"(ust|üst|yukar|above|over)",
        n,
    )
    if m:
        base = m.group(1) or "192.168.1"
        return {"type": "octet_gt", "base": base, "octet": int(m.group(2))}

    return None


def _match_ip_filter(ip: str, filt: dict[str, Any]) -> bool:
    key = _ip_key(ip)
    if key is None:
        return False
    ftype = filt.get("type")
    if ftype == "cidr":
        try:
            return ipaddress.ip_address(ip) in ipaddress.ip_network(filt["network"], strict=False)
        except ValueError:
            return False
    if ftype == "cmp":
        ref = _ip_key(str(filt.get("ip") or ""))
        if ref is None:
            return False
        op = filt.get("op")
        if op == "lt":
            return key < ref
        if op == "gt":
            return key > ref
        if op == "le":
            return key <= ref
        if op == "ge":
            return key >= ref
        return key == ref
    if ftype in ("octet_lt", "octet_gt"):
        parts = (ip or "").split(".")
        if len(parts) != 4:
            return False
        base = str(filt.get("base") or "192.168.1").split(".")
        if parts[0:3] != base[0:3]:
            # still allow if user didn't care about subnet — compare last octet only when prefix matches OR message had no base
            if len(base) == 3 and ".".join(parts[0:3]) != ".".join(base):
                return False
        try:
            last = int(parts[3])
        except ValueError:
            return False
        thr = int(filt.get("octet") or 0)
        return last < thr if ftype == "octet_lt" else last > thr
    return False


def parse_server_status(message: str) -> ServerStatus | None:
    n = _norm(message)
    mapping = [
        (ServerStatus.ready, ("ready", "hazir", "hazır", "erişilebilir", "erisilebilir")),
        (ServerStatus.unreachable, ("unreachable", "ulasilamaz", "ulaşılamaz", "erişilemez", "erisilemez")),
        (ServerStatus.unknown, ("unknown", "bilinmeyen")),
    ]
    for st, keys in mapping:
        if any(k in n for k in keys):
            return st
    return None


def parse_job_status(message: str) -> JobStatus | None:
    n = _norm(message)
    for st in JobStatus:
        if st.value in n:
            return st
    if "basarisiz" in n or "failed" in n or "hata" in n:
        return JobStatus.failed
    if "basarili" in n or "success" in n or "tamamland" in n:
        return JobStatus.success
    if "calisiyor" in n or "running" in n:
        return JobStatus.running
    return None


def parse_job_id(message: str) -> int | None:
    m = re.search(r"(?:job|iş|is)\s*[#:]?\s*(\d+)\b", message or "", flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*(?:numarali|nolu|no['’]?lu)\s*(?:job|iş|is)\b", _norm(message))
    if m:
        return int(m.group(1))
    return None


def parse_talep_id(message: str) -> str | None:
    m = re.search(r"(?:talep|ticket|req)[\s#:]*([A-Za-z0-9._/-]+)", message or "", flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _os_label(os_pretty: str) -> str:
    """Normalize os_pretty for grouping (empty → bilinmiyor)."""
    raw = (os_pretty or "").strip()
    if not raw:
        return "(OS bilinmiyor / boş)"
    # Keep pretty name but collapse whitespace
    return re.sub(r"\s+", " ", raw)


def _os_major_label(os_pretty: str) -> str:
    """RHEL/CentOS-style major bucket when possible."""
    from app.services.package_repo_store import parse_os_pretty

    os_id, major = parse_os_pretty(os_pretty or "")
    if os_id and major:
        names = {
            "rhel": "RHEL",
            "centos": "CentOS",
            "rocky": "Rocky",
            "almalinux": "AlmaLinux",
            "ol": "Oracle Linux",
        }
        return f"{names.get(os_id, os_id)} {major}"
    return _os_label(os_pretty)


def _virt_label(s: TargetServer) -> str:
    mt = (s.machine_type or "").strip().lower()
    virt = (s.virtualization or "").strip()
    if mt == "physical":
        return "Fiziksel"
    if mt == "virtual":
        return f"Sanal — {virt}" if virt else "Sanal"
    if virt:
        return f"Sanal — {virt}"
    return "(tip bilinmiyor)"


def _detect_group_by(n: str) -> str | None:
    """Return group dimension: os | os_major | status | key | virt | tag."""
    # Explicit group / çeşit / dağılım
    wants_group = any(
        x in n
        for x in (
            "cesit",
            "çeşit",
            "dagilim",
            "dağılım",
            "grupla",
            "gruplu",
            "ozet",
            "özet",
            "kac cesit",
            "kaç çeşit",
            "hangi os",
            "hangi işletim",
            "hangi isletim",
            "os tipler",
            "os tur",
            "işletim sistemi",
            "isletim sistemi",
        )
    )
    if any(x in n for x in ("os major", "major", "rhel 8", "rhel 9", "el8", "el9")) and any(
        x in n
        for x in (
            "cesit",
            "çeşit",
            "dagilim",
            "dağılım",
            "ozet",
            "özet",
            "grupla",
            "kac cesit",
            "kaç çeşit",
        )
    ):
        return "os_major"
    if wants_group or any(x in n for x in ("kac cesit os", "kaç çeşit os", "os dagilim", "os dağılım")):
        if any(x in n for x in ("status", "durum", "ready", "unreachable")):
            return "status"
        if any(x in n for x in ("ssh key", "anahtar", "key var", "key yok")):
            return "key"
        if any(x in n for x in ("sanal", "fiziksel", "virtual", "vmware", "kvm", "machine")):
            return "virt"
        if "tag" in n or "etiket" in n:
            return "tag"
        if any(x in n for x in ("os", "işletim", "isletim", "rhel", "centos", "rocky", "alma")):
            # major dağılımı yalnızca özet niyetinde
            if "major" in n and any(
                x in n for x in ("cesit", "çeşit", "dagilim", "dağılım", "ozet", "özet", "grupla", "kac", "kaç")
            ):
                return "os_major"
            return "os"
        # default group for "kaç çeşit / özet / dağılım" without dimension → OS
        if any(x in n for x in ("cesit", "çeşit", "dagilim", "dağılım", "ozet", "özet", "grupla")):
            return "os"

    # Soft: "OS özeti", "status özeti"
    if "os" in n and any(x in n for x in ("ozet", "özet", "say", "kac", "kaç", "dagilim", "dağılım")):
        return "os_major" if "major" in n else "os"
    if any(x in n for x in ("status ozet", "durum ozet", "durum dağılım", "status dağılım", "kac ready", "kaç ready")):
        if any(x in n for x in ("dagilim", "dağılım", "ozet", "özet", "cesit", "çeşit", "kac tane", "kaç tane")):
            return "status"
    if any(x in n for x in ("key ozet", "anahtar ozet", "ssh key dağılım", "kacinda key", "kaçında key")):
        return "key"
    if any(x in n for x in ("sanal kac", "kaç sanal", "fiziksel kac", "kaç fiziksel", "virt ozet", "makine tipi")):
        return "virt"
    return None


def _detect_count_only(n: str, group_by: str | None) -> bool:
    if group_by:
        return False
    return any(
        x in n
        for x in (
            "kac sunucu",
            "kaç sunucu",
            "kac tane sunucu",
            "kaç tane sunucu",
            "toplam sunucu",
            "sunucu sayisi",
            "sunucu sayısı",
            "how many server",
            "server count",
        )
    )


def _parse_os_name_filter(message: str) -> str | None:
    """Filter hosts whose os_pretty matches (e.g. rhel 9, rocky)."""
    n = _norm(message)
    # rhel 9 / rhel9 / el9
    m = re.search(r"\b(rhel|centos|rocky|alma|almalinux|oracle|ol)\s*([0-9]{1,2})?\b", n)
    if m and any(x in n for x in ("hangi", "olan", "liste", "goster", "göster", "kac", "kaç", "filtre")):
        name = m.group(1)
        major = m.group(2) or ""
        if name in ("alma", "almalinux"):
            name = "alma"
        if name in ("oracle", "ol"):
            name = "oracle"
        return f"{name}{major}".strip()
    if "rhel" in n and any(x in n for x in ("hangi", "olanlar", "liste")):
        return "rhel"
    return None


def _match_os_filter(os_pretty: str, filt: str) -> bool:
    blob = _norm(os_pretty)
    f = (filt or "").lower()
    if f.startswith("rhel") or f.startswith("red hat"):
        ok = "rhel" in blob or "red hat" in blob or "redhat" in blob
        maj = re.sub(r"^rhel", "", f)
        if maj and ok:
            return bool(re.search(rf"\b{re.escape(maj)}(\.|$|\s)", blob))
        return ok
    if f.startswith("centos"):
        ok = "centos" in blob
        maj = re.sub(r"^centos", "", f)
        return (maj in blob) if maj and ok else ok
    if f.startswith("rocky"):
        return "rocky" in blob and (
            not re.sub(r"^rocky", "", f) or re.sub(r"^rocky", "", f) in blob
        )
    if f.startswith("alma"):
        return "alma" in blob
    if f.startswith("oracle") or f.startswith("ol"):
        return "oracle" in blob or blob.startswith("ol ")
    return f in blob


def _group_lines(title: str, buckets: dict[str, int], total: int) -> list[str]:
    lines = [f"{title}: {len(buckets)} çeşit · {total} sunucu"]
    for label, cnt in sorted(buckets.items(), key=lambda x: (-x[1], x[0].lower())):
        lines.append(f"  · {label} — {cnt}")
    if not buckets:
        lines.append("  (veri yok)")
    return lines


def query_servers(session: Session, message: str) -> dict[str, Any]:
    rows = list(session.exec(select(TargetServer).order_by(col(TargetServer.hostname))).all())
    ip_filt = parse_ipv4_filter(message)
    status = parse_server_status(message)
    n = _norm(message)
    want_no_key = any(x in n for x in ("ssh key yok", "anahtar yok", "key yok", "ssh_key_installed false"))
    want_key = "ssh key var" in n or "anahtar kurulu" in n
    tag = None
    m = re.search(r"(?:tag|etiket)\s*[:=]?\s*([a-z0-9._-]+)", n)
    if m:
        tag = m.group(1)
    os_filt = _parse_os_name_filter(message)
    group_by = _detect_group_by(n)
    count_only = _detect_count_only(n, group_by)

    matched: list[TargetServer] = []
    for s in rows:
        if status is not None and s.status != status:
            continue
        if want_no_key and s.ssh_key_installed:
            continue
        if want_key and not s.ssh_key_installed:
            continue
        if tag and tag not in _norm(s.tags or ""):
            continue
        if ip_filt and not _match_ip_filter(s.ip or "", ip_filt):
            continue
        if os_filt and not _match_os_filter(s.os_pretty or "", os_filt):
            continue
        matched.append(s)

    has_filter = bool(ip_filt or status or want_no_key or want_key or tag or os_filt)
    list_intent = any(
        x in n
        for x in (
            "liste",
            "goster",
            "göster",
            "hangileri",
            "hangi sunucu",
            "kac sunucu",
            "kaç sunucu",
            "envanter",
            "inventory",
            "ip",
            "altinda",
            "altında",
            "asag",
            "filter",
            "filtre",
            "cesit",
            "çeşit",
            "dagilim",
            "dağılım",
            "ozet",
            "özet",
            "grupla",
            "kac tane",
            "kaç tane",
            "os ",
            "işletim",
            "isletim",
        )
    ) or bool(group_by) or count_only or bool(os_filt)

    if not has_filter and not list_intent and not group_by and not count_only:
        return {
            "ok": True,
            "lines": [
                "Portal envanter sorgusu: filtre veya özet belirtmediniz.",
                "Örnek: “kaç çeşit OS var?”, “status dağılımı”, “192.168.1.100 altındaki IP’ler”,",
                "“ready olmayan sunucular”, “RHEL 9 hangileri”, “tag=prod”.",
                f"Toplam kayıt: {len(rows)}",
            ],
            "count": 0,
            "total": len(rows),
        }

    if not has_filter and (list_intent or group_by or count_only):
        matched = list(rows)

    # --- Aggregate / count modes ---
    if group_by == "os":
        buckets: dict[str, int] = {}
        for s in matched:
            label = _os_label(s.os_pretty or "")
            buckets[label] = buckets.get(label, 0) + 1
        lines = _group_lines("OS dağılımı (os_pretty)", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": len(buckets), "total": len(rows), "mode": "group_os"}

    if group_by == "os_major":
        buckets = {}
        for s in matched:
            label = _os_major_label(s.os_pretty or "")
            buckets[label] = buckets.get(label, 0) + 1
        lines = _group_lines("OS major dağılımı", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": len(buckets), "total": len(rows), "mode": "group_os_major"}

    if group_by == "status":
        buckets = {}
        for s in matched:
            st = getattr(s.status, "value", str(s.status))
            buckets[st] = buckets.get(st, 0) + 1
        lines = _group_lines("Durum (status) dağılımı", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": len(buckets), "total": len(rows), "mode": "group_status"}

    if group_by == "key":
        buckets = {"SSH key var": 0, "SSH key yok": 0}
        for s in matched:
            if s.ssh_key_installed:
                buckets["SSH key var"] += 1
            else:
                buckets["SSH key yok"] += 1
        lines = _group_lines("SSH key dağılımı", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": 2, "total": len(rows), "mode": "group_key"}

    if group_by == "virt":
        buckets = {}
        for s in matched:
            label = _virt_label(s)
            buckets[label] = buckets.get(label, 0) + 1
        lines = _group_lines("Makine tipi dağılımı", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": len(buckets), "total": len(rows), "mode": "group_virt"}

    if group_by == "tag":
        buckets = {}
        for s in matched:
            tags = [t.strip() for t in (s.tags or "").split(",") if t.strip()]
            if not tags:
                buckets["(tags boş)"] = buckets.get("(tags boş)", 0) + 1
            else:
                for t in tags:
                    buckets[t] = buckets.get(t, 0) + 1
        lines = _group_lines("Tag dağılımı", buckets, len(matched))
        return {"ok": True, "lines": lines, "count": len(buckets), "total": len(rows), "mode": "group_tag"}

    if count_only:
        lines = [f"Toplam sunucu: {len(matched)} (envanter {len(rows)})"]
        if has_filter:
            lines.append("  (filtre uygulanmış sayı)")
        return {"ok": True, "lines": lines, "count": len(matched), "total": len(rows), "mode": "count"}

    # --- List mode ---
    lines = [f"Envanter sonucu: {len(matched)}/{len(rows)} sunucu"]
    if ip_filt:
        lines.append(f"  Filtre IP: {ip_filt}")
    if status:
        lines.append(f"  Filtre status: {status.value}")
    if tag:
        lines.append(f"  Filtre tag: {tag}")
    if os_filt:
        lines.append(f"  Filtre OS: {os_filt}")
    if want_key:
        lines.append("  Filtre: SSH key var")
    if want_no_key:
        lines.append("  Filtre: SSH key yok")
    for s in matched[:_MAX_LIST]:
        os_bit = (s.os_pretty or "").strip()
        os_short = (os_bit[:40] + "…") if len(os_bit) > 40 else os_bit
        extra = f"  os={os_short}" if os_short else ""
        lines.append(
            f"  · {s.hostname}  {s.ip}  [{getattr(s.status, 'value', s.status)}]  "
            f"key={'yes' if s.ssh_key_installed else 'no'}{extra}"
        )
    if len(matched) > _MAX_LIST:
        lines.append(f"  … +{len(matched) - _MAX_LIST} daha (Sunucular sayfasında devam)")
    if not matched:
        lines.append("  Eşleşen sunucu yok.")
    return {"ok": True, "lines": lines, "count": len(matched), "total": len(rows), "mode": "list"}


def query_jobs(session: Session, message: str) -> dict[str, Any]:
    jid = parse_job_id(message)
    st = parse_job_status(message)
    talep = parse_talep_id(message)
    n = _norm(message)

    if jid is not None:
        job = session.get(Job, jid)
        if job is None:
            return {"ok": True, "lines": [f"Job #{jid} bulunamadı."], "count": 0}
        lines = [
            f"Job #{job.id} · {job.module}/{job.action} · {job.status.value}",
            f"  Talep: {job.talep_id or '-'}",
            f"  Başlık: {job.title or '-'}",
            f"  Özet: {(job.summary_tr or '-')[:200]}",
            f"  Hata: {(job.error_message or '-')[:240]}",
            f"  Kullanıcı: {job.created_by_username}",
            f"  Progress: {job.progress_done}/{job.progress_total}",
        ]
        return {"ok": True, "lines": lines, "count": 1}

    stmt = select(Job).order_by(col(Job.id).desc()).limit(_MAX_LIST)
    if st is not None:
        stmt = select(Job).where(Job.status == st).order_by(col(Job.id).desc()).limit(_MAX_LIST)
    rows = list(session.exec(stmt).all())
    if talep:
        rows = [j for j in rows if talep.lower() in _norm(j.talep_id or "")]
    if "son" in n and st is None and jid is None:
        rows = list(session.exec(select(Job).order_by(col(Job.id).desc()).limit(15)).all())

    lines = [f"İşler: {len(rows)} kayıt (son / filtre)"]
    if st:
        lines[0] = f"İşler [{st.value}]: {len(rows)} kayıt"
    for j in rows[:_MAX_LIST]:
        lines.append(
            f"  · #{j.id} {j.status.value} {j.module}/{j.action} talep={j.talep_id or '-'} "
            f"{(j.title or j.summary_tr or '')[:60]}"
        )
    if not rows:
        lines.append("  Eşleşen iş yok.")
    return {"ok": True, "lines": lines, "count": len(rows)}


def query_audit(session: Session, message: str) -> dict[str, Any]:
    jid = parse_job_id(message)
    talep = parse_talep_id(message)
    n = _norm(message)
    stmt = select(AuditLog).order_by(col(AuditLog.id).desc()).limit(_MAX_LIST)
    rows = list(session.exec(stmt).all())
    if jid is not None:
        rows = [r for r in rows if r.job_id == jid]
    if talep:
        rows = [r for r in rows if talep.lower() in _norm(r.talep_id or "")]
    # username hint
    m = re.search(r"(?:kullanici|user|username)\s*[:=]?\s*([a-z0-9._-]+)", n)
    if m:
        u = m.group(1)
        rows = [r for r in rows if u in _norm(r.username or "")]
    # hostname token
    m = re.search(r"(?:host|hostname|sunucu)\s*[:=]?\s*([a-z0-9._-]+)", n)
    if m:
        h = m.group(1)
        rows = [r for r in rows if h in _norm(r.hostname or "")]

    lines = [f"Denetim: {len(rows)} kayıt"]
    for r in rows[:_MAX_LIST]:
        lines.append(
            f"  · #{r.id} {r.action} [{getattr(r.status, 'value', r.status)}] "
            f"user={r.username or '-'} host={r.hostname or '-'} "
            f"{(r.message or '')[:80]}"
        )
    if not rows:
        lines.append("  Eşleşen audit yok.")
    return {"ok": True, "lines": lines, "count": len(rows)}


def query_portal_users(session: Session, message: str, user: User | None) -> dict[str, Any]:
    if user is None or user.role != UserRole.admin:
        return {
            "ok": False,
            "lines": ["Portal kullanıcı listesi yalnızca Admin için."],
            "count": 0,
        }
    rows = list(session.exec(select(User).order_by(col(User.username))).all())
    n = _norm(message)
    if "admin" in n:
        rows = [u for u in rows if u.role == UserRole.admin]
    if "operator" in n or "operasyon" in n:
        rows = [u for u in rows if u.role == UserRole.operator]
    if "pasif" in n or "inactive" in n:
        rows = [u for u in rows if not u.is_active]
    if "aktif" in n and "pasif" not in n:
        rows = [u for u in rows if u.is_active]
    if " ad" in n or n.startswith("ad ") or "active directory" in n:
        rows = [u for u in rows if (u.auth_source.value if hasattr(u.auth_source, "value") else str(u.auth_source)) == "ad"]

    lines = [f"Portal kullanıcıları: {len(rows)}"]
    for u in rows[:_MAX_LIST]:
        src = u.auth_source.value if hasattr(u.auth_source, "value") else str(u.auth_source)
        role = u.role.value if hasattr(u.role, "value") else str(u.role)
        lines.append(f"  · {u.username}  role={role}  src={src}  active={u.is_active}")
    return {"ok": True, "lines": lines, "count": len(rows)}


def query_package_repos(session: Session, message: str, user: User | None) -> dict[str, Any]:
    if user is None or user.role != UserRole.admin:
        return {
            "ok": False,
            "lines": ["Paket repo özeti yalnızca Admin için."],
            "count": 0,
        }
    from app.services import package_repo_store as pkg_store

    repos = pkg_store.list_local_repos(session)
    n = _norm(message)
    lines = [f"Local paket repo: {len(repos)}"]
    for r in repos[:_MAX_LIST]:
        if n and len(n) > 8:
            blob = _norm(f"{r.keyword} {r.os_id} {r.os_major} {r.label or ''}")
            # if message mentions a keyword-like token, soft filter
            tokens = [t for t in re.split(r"\W+", n) if len(t) > 3]
            if tokens and not any(t in blob for t in tokens if t not in {"paket", "repo", "keyword", "goster", "liste"}):
                # only filter when an obvious package token present
                pkg_tokens = [t for t in tokens if t in blob or t in {"docker", "snowlinux", "oracle"}]
                if pkg_tokens and not any(t in blob for t in pkg_tokens):
                    continue
        lines.append(
            f"  · keyword={r.keyword} os={r.os_id}/{r.os_major} enabled={r.enabled} "
            f"source={getattr(r, 'source_type', '') or 'nfs'}"
        )
    return {"ok": True, "lines": lines, "count": len(repos)}


def query_settings(session: Session, message: str) -> dict[str, Any]:
    from app.services import bootstrap
    from app.services.privilege import get_automation_user_kind

    kind = get_automation_user_kind(session)
    escalate = {"root": "yok", "local": "sudo -n", "ad": "dzdo -n"}.get(kind, kind)
    lines = [
        "Portal ayarları (readonly):",
        f"  App: {bootstrap.get_app_name(session)}",
        f"  SMTP host: {bootstrap.get_smtp_host(session) or '-'}",
        f"  SMTP test mail: {bootstrap.get_smtp_test_mail(session) or '-'}",
        f"  Automation user: {bootstrap.get_automation_username(session)}",
        f"  Automation kind: {kind} (escalate: {escalate})",
    ]
    return {"ok": True, "lines": lines, "count": 1}


def query_ops_catalogs(session: Session, message: str) -> dict[str, Any]:
    """Static portal catalogs (sysctl allowed, sudo templates, etc.)."""
    n = _norm(message)
    lines: list[str] = []
    if any(x in n for x in ("sysctl", "hugepage", "kernel.sem", "izinli parametre")):
        from app.modules import sysctl

        keys = sysctl.list_allowed_params()
        lines = [f"İzinli sysctl parametreleri ({len(keys)}):"]
        for k in keys[:50]:
            lines.append(f"  · {k}")
        return {"ok": True, "lines": lines, "count": len(keys)}
    if "sudo" in n and ("sablon" in n or "şablon" in n or "template" in n):
        from app.modules import sudoers

        tpls = sudoers.list_templates()
        lines = [f"Sudo şablonları ({len(tpls)}):"]
        for t in tpls[:30]:
            lines.append(f"  · {t.get('id') or t.get('name')}: {(t.get('label') or t.get('description') or '')[:80]}")
        return {"ok": True, "lines": lines, "count": len(tpls)}
    if "vlan" in n and ("pool" in n or "havuz" in n):
        from app.modules import vlan

        pools = vlan.list_pools()
        lines = [f"VLAN pool ({len(pools)}):"]
        for p in pools[:30]:
            lines.append(f"  · {p}")
        return {"ok": True, "lines": lines, "count": len(pools)}
    if "limits" in n or "ulimit" in n or "nproc" in n:
        from app.modules import limits

        items = limits.list_allowed_items()
        lines = [f"Limits kalemleri ({len(items)}):"]
        for i in items[:40]:
            lines.append(f"  · {i}")
        return {"ok": True, "lines": lines, "count": len(items)}
    return {
        "ok": True,
        "lines": [
            "Portal katalog sorgusu: sysctl izinli key / sudo şablon / VLAN pool / limits kalemi sorabilirsiniz.",
        ],
        "count": 0,
    }


_DB_OPS = frozenset(
    {
        "servers",
        "jobs",
        "audit",
        "portal_users",
        "package_repos",
        "settings_info",
        "ops_catalog",
    }
)


def is_db_query_op(operation_id: str | None) -> bool:
    return bool(operation_id and operation_id in _DB_OPS)


def run_db_query(
    session: Session,
    operation_id: str | None,
    message: str,
    *,
    user: User | None = None,
) -> dict[str, Any]:
    if not operation_id or operation_id not in _DB_OPS:
        return {"ok": False, "lines": [], "count": 0}
    if operation_id == "servers":
        return query_servers(session, message)
    if operation_id == "jobs":
        return query_jobs(session, message)
    if operation_id == "audit":
        return query_audit(session, message)
    if operation_id == "portal_users":
        return query_portal_users(session, message, user)
    if operation_id == "package_repos":
        return query_package_repos(session, message, user)
    if operation_id == "settings_info":
        return query_settings(session, message)
    if operation_id == "ops_catalog":
        return query_ops_catalogs(session, message)
    return {"ok": False, "lines": [], "count": 0}
