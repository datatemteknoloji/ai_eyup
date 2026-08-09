from __future__ import annotations

import re
from typing import Any, Callable

from sqlmodel import Session

from app.models.server import TargetServer

# Ops that never probe targets (SSH) — DB queries handled separately
_NO_PROBE = frozenset({"terminal", "reboot", "log_collect", "mail_config", "path_perms"})

# operation_id → probe kind (SSH/cache)
_PROBE_KIND: dict[str, str] = {
    "filesystem": "filesystem",
    "filesystem_extend": "filesystem",
    "filesystem_create": "filesystem",
    "filesystem_organize": "filesystem",
    "sysctl": "sysctl",
    "limits": "limits",
    "packages": "packages",
    "services": "services",
    "vlan_add": "vlan",
    "network_add": "vlan",
    "network_mgmt": "vlan",
    "network_ip_change": "vlan",
    "asm_add_disk": "asm",
    "hostname": "hostname",
    "sudoers": "sudoers",
    "local_users": "local_users",
    "server_facts": "hostname",  # soft facts via hostname state + optional
}


def _server(session: Session, row: dict[str, Any]) -> TargetServer | None:
    return session.get(TargetServer, int(row["id"]))


def _safe(fn: Callable[[], Any]) -> tuple[Any | None, str | None]:
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)[:200]


def _probe_filesystem(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import filesystem

    inv = filesystem.list_inventory(session, server, refresh=False)
    vgs = []
    for v in (inv.get("volume_groups") or [])[:12]:
        vgs.append(
            {
                "name": v.get("name"),
                "size_gb": v.get("size_gb"),
                "free_gb": v.get("free_gb"),
                "is_root": bool(v.get("is_root")),
            }
        )
    fss = []
    for f in (inv.get("filesystems") or [])[:20]:
        fss.append(
            {
                "mount": f.get("mount") or f.get("mountpoint") or f.get("path"),
                "lv": f.get("lv_name") or f.get("lv"),
                "vg": f.get("vg_name") or f.get("vg"),
                "size_gb": f.get("size_gb") or f.get("size"),
                "fstype": f.get("fstype") or f.get("fs_type"),
                "free_gb": f.get("free_gb") or f.get("avail_gb"),
            }
        )
    free_disks = []
    for d in (inv.get("free_disks") or [])[:10]:
        free_disks.append(
            {
                "name": d.get("name") or d.get("device"),
                "size_gb": d.get("size_gb") or d.get("size"),
                "wwid": (d.get("wwid") or "")[-16:],
            }
        )
    return {
        "root_vg": inv.get("root_vg"),
        "volume_groups": vgs,
        "filesystems": fss,
        "free_disks": free_disks,
        "disk_mode": inv.get("disk_mode"),
        "cached": inv.get("cached"),
    }


def _probe_sysctl(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import sysctl

    data = sysctl.get_current_values(session, server, None, refresh=False)
    vals = data.get("values") or {}
    # Keep a compact subset for chat
    keep = [
        "vm.nr_hugepages",
        "vm.hugetlb_shm_group",
        "kernel.sem",
        "kernel.shmall",
        "kernel.shmmax",
        "kernel.shmmni",
        "fs.file-max",
        "net.core.rmem_max",
        "net.core.wmem_max",
    ]
    slim = {k: vals[k] for k in keep if k in vals}
    if not slim:
        slim = dict(list(vals.items())[:12])
    return {"values": slim, "cached": data.get("cached")}


def _probe_limits(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import limits

    data = limits.get_current_limits(session, server, refresh=False)
    rows = data.get("entries") or data.get("rows") or data.get("limits") or []
    slim = []
    for r in (rows or [])[:30]:
        if isinstance(r, dict):
            slim.append({k: r.get(k) for k in list(r.keys())[:6]})
        else:
            slim.append({"line": str(r)[:120]})
    return {"rows": slim, "cached": data.get("cached")}


def _probe_packages(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import packages
    from app.services import package_repo_store as pkg_store

    osinfo = pkg_store.read_target_os(session, server)
    mounts = packages.list_data_mount_candidates(session, server)[:8]
    return {
        "os": osinfo,
        "data_mounts": [
            {"path": m.get("path") or m.get("mount"), "size": m.get("size") or m.get("size_gb")}
            for m in mounts
            if isinstance(m, dict)
        ],
    }


def _probe_services(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import services

    rows = services.list_services(session, server)[:25]
    return {
        "services": [
            {
                "unit": r.get("unit") or r.get("name"),
                "active": r.get("active"),
                "enabled": r.get("enabled"),
            }
            for r in rows
        ]
    }


def _probe_vlan(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import vlan

    ifaces = vlan.list_interfaces(session, server)[:30]
    return {
        "interfaces": [
            {
                "name": i.get("name") or i.get("device"),
                "ipv4": i.get("ipv4") or i.get("ip"),
                "vlan": i.get("vlan_id") or i.get("vlan"),
            }
            for i in ifaces
            if isinstance(i, dict)
        ]
    }


def _probe_asm(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import asm

    scan = asm.scan_disks(session, server, refresh=False)
    disks = scan.get("disks") or []
    usable = [d for d in disks if d.get("usable")][:15]
    return {
        "disk_count": len(disks),
        "usable_count": len(usable),
        "usable": [
            {
                "name": d.get("name"),
                "size_gb": d.get("size_gb") or d.get("size"),
                "wwid_tail": (d.get("wwid") or "")[-16:],
            }
            for d in usable
        ],
        "cached": scan.get("cached"),
    }


def _probe_hostname(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import hostname as hn

    st = hn.read_hostname_state(session, server)
    return {
        "hostname": st.get("hostname") or st.get("fqdn"),
        "short_name": st.get("short_name"),
        "domain": st.get("domain"),
    }


def _probe_sudoers(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import sudoers

    rules = sudoers.list_custom_rules(session, server)[:20]
    return {"rules": rules}


def _probe_local_users(session: Session, server: TargetServer) -> dict[str, Any]:
    from app.modules import local_user

    users = local_user.list_local_users(session, server)[:30]
    return {
        "users": [
            {"username": u.get("username") or u.get("name"), "uid": u.get("uid")}
            for u in users
            if isinstance(u, dict)
        ]
    }


_PROBERS: dict[str, Callable[[Session, TargetServer], dict[str, Any]]] = {
    "filesystem": _probe_filesystem,
    "sysctl": _probe_sysctl,
    "limits": _probe_limits,
    "packages": _probe_packages,
    "services": _probe_services,
    "vlan": _probe_vlan,
    "asm": _probe_asm,
    "hostname": _probe_hostname,
    "sudoers": _probe_sudoers,
    "local_users": _probe_local_users,
}


def probe_kind_for_op(operation_id: str | None) -> str | None:
    if not operation_id or operation_id in _NO_PROBE:
        return None
    return _PROBE_KIND.get(operation_id)


def run_probe(session: Session, kind: str, row: dict[str, Any]) -> dict[str, Any]:
    server = _server(session, row)
    if server is None:
        return {"ok": False, "error": "Sunucu bulunamadı", "hostname": row.get("hostname")}
    fn = _PROBERS.get(kind)
    if not fn:
        return {"ok": False, "error": f"Probe yok: {kind}", "hostname": server.hostname}
    data, err = _safe(lambda: fn(session, server))
    if err:
        return {"ok": False, "error": err, "hostname": server.hostname}
    return {"ok": True, "hostname": server.hostname, "data": data}


def _requested_size_gb(message: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(g|gb|gi|gib)\b", message or "", flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _fs_mount_key(f: dict[str, Any]) -> str:
    return str(f.get("mount") or f.get("mountpoint") or f.get("path") or "").strip()


def _is_real_fs(f: dict[str, Any]) -> bool:
    mp = _fs_mount_key(f)
    fstype = str(f.get("fstype") or f.get("fs_type") or "").lower()
    if not mp or mp.startswith(("/dev", "/run", "/sys", "/proc")):
        return False
    if fstype in {"tmpfs", "devtmpfs", "cgroup", "cgroup2", "overlay", "squashfs", "rpc_pipefs", "autofs"}:
        return False
    return True


def _fmt_size(val: Any) -> str:
    if val is None or val == "":
        return "?"
    s = str(val).strip()
    if re.search(r"(?i)[kmgt]i?b?$", s):
        return s
    try:
        return f"{float(s):g}G"
    except ValueError:
        return s


def _summarize_filesystem(label: str, payload: dict[str, Any], *, want_gb: float | None) -> list[str]:
    if not payload.get("ok"):
        return [f"{label}: okunamadı — {payload.get('error')}"]
    data = payload.get("data") or {}
    lines = [f"{label} ({payload.get('hostname')}):"]
    vgs = data.get("volume_groups") or []
    if vgs:
        parts = [
            f"{v.get('name')} free={_fmt_size(v.get('free_gb'))}/{_fmt_size(v.get('size_gb'))}"
            for v in vgs[:6]
        ]
        lines.append("  VG: " + "; ".join(parts))
    fss = [f for f in (data.get("filesystems") or []) if _is_real_fs(f)][:12]
    if fss:
        parts = [
            f"{_fs_mount_key(f)} {_fmt_size(f.get('size_gb') or f.get('size'))} "
            f"({f.get('fstype') or f.get('fs_type') or '?'})"
            for f in fss
        ]
        lines.append("  FS: " + "; ".join(parts))
    free_disks = data.get("free_disks") or []
    if free_disks:
        lines.append(f"  Boş disk: {len(free_disks)} adet")
        for d in free_disks[:4]:
            lines.append(f"    · {d.get('name')} {_fmt_size(d.get('size_gb') or d.get('size'))}")
    if want_gb is not None and vgs:
        candidates = [
            v for v in vgs if not v.get("is_root") and float(v.get("free_gb") or 0) >= want_gb
        ]
        if candidates:
            names = ", ".join(str(v.get("name")) for v in candidates[:3])
            lines.append(f"  → {want_gb:g}G için uygun VG: {names}")
        else:
            rootish = [v for v in vgs if float(v.get("free_gb") or 0) >= want_gb]
            if rootish:
                lines.append(
                    f"  → {want_gb:g}G sığan VG var ({rootish[0].get('name')}); root VG ise dikkat."
                )
            elif free_disks:
                lines.append(
                    f"  → VG free yetersiz; {len(free_disks)} boş disk ile yeni VG/LV düşünülebilir."
                )
            else:
                lines.append(f"  → {want_gb:g}G için yeterli VG free / boş disk görünmüyor.")
    return lines


def _summarize_generic(kind: str, label: str, payload: dict[str, Any]) -> list[str]:
    if not payload.get("ok"):
        return [f"{label}: okunamadı — {payload.get('error')}"]
    data = payload.get("data") or {}
    host = payload.get("hostname")
    lines = [f"{label} ({host}):"]
    if kind == "sysctl":
        vals = data.get("values") or {}
        for k, v in list(vals.items())[:10]:
            lines.append(f"  {k} = {v}")
    elif kind == "limits":
        rows = data.get("rows") or []
        lines.append(f"  {len(rows)} satır/özet okundu")
        for r in rows[:6]:
            lines.append(f"  · {r}")
    elif kind == "packages":
        osinfo = data.get("os") or {}
        lines.append(
            f"  OS: {osinfo.get('os_id') or '?'} {osinfo.get('version_major') or ''} "
            f"({osinfo.get('pretty_name') or osinfo.get('pretty') or ''})".strip()
        )
        mounts = data.get("data_mounts") or []
        if mounts:
            lines.append("  Data mount: " + ", ".join(str(m.get("path")) for m in mounts[:5]))
    elif kind == "services":
        svcs = data.get("services") or []
        lines.append(f"  Custom unit: {len(svcs)}")
        for s in svcs[:8]:
            lines.append(f"  · {s.get('unit')} active={s.get('active')} enabled={s.get('enabled')}")
    elif kind == "vlan":
        ifaces = data.get("interfaces") or []
        for i in ifaces[:10]:
            lines.append(f"  · {i.get('name')} ip={i.get('ipv4') or '-'} vlan={i.get('vlan') or '-'}")
    elif kind == "asm":
        lines.append(f"  Disk: {data.get('disk_count')} · usable: {data.get('usable_count')}")
        for d in (data.get("usable") or [])[:6]:
            lines.append(f"  · {d.get('name')} {_fmt_size(d.get('size_gb'))} …{d.get('wwid_tail')}")
    elif kind == "hostname":
        lines.append(
            f"  hostname={data.get('hostname')} short={data.get('short_name')} "
            f"domain={data.get('domain')}"
        )
    elif kind == "sudoers":
        rules = data.get("rules") or []
        lines.append(f"  Custom sudo kuralı: {len(rules)}")
        for r in rules[:6]:
            lines.append(f"  · {r}")
    elif kind == "local_users":
        users = data.get("users") or []
        lines.append("  Users: " + ", ".join(str(u.get("username")) for u in users[:15]))
    else:
        lines.append(f"  {str(data)[:240]}")
    return lines


def _compare_filesystem(target: dict[str, Any], ref: dict[str, Any], want_gb: float | None) -> list[str]:
    lines = ["Karşılaştırma:"]
    if not target.get("ok") or not ref.get("ok"):
        lines.append("  Karşılaştırma için her iki sunucu da okunamadı.")
        return lines
    t = target.get("data") or {}
    r = ref.get("data") or {}
    ref_fs = {
        _fs_mount_key(f): f
        for f in (r.get("filesystems") or [])
        if _is_real_fs(f) and _fs_mount_key(f)
    }
    tgt_fs = {
        _fs_mount_key(f): f
        for f in (t.get("filesystems") or [])
        if _is_real_fs(f) and _fs_mount_key(f)
    }
    for mp, rf in list(ref_fs.items())[:10]:
        tf = tgt_fs.get(mp)
        if tf:
            lines.append(
                f"  {mp}: referans {_fmt_size(rf.get('size_gb'))} / hedef {_fmt_size(tf.get('size_gb'))} "
                f"(vg {rf.get('vg')}→{tf.get('vg')})"
            )
        else:
            lines.append(
                f"  {mp}: referansta var ({_fmt_size(rf.get('size_gb'))}, vg={rf.get('vg')}); "
                f"hedefte yok — yeni FS adayı."
            )
    if want_gb is not None:
        lines.append(
            f"  İstenen boyut ~{want_gb:g}G; FileSystem Management’ta hedef sunucuda "
            f"Preview → Apply ile oluşturun (asistan uygulamaz)."
        )
    if len(lines) == 1:
        lines.append("  Ortak anlamlı mount farkı yok; VG/boş disk özetine bakın.")
    return lines


def _compare_sysctl(target: dict[str, Any], ref: dict[str, Any]) -> list[str]:
    lines = ["Karşılaştırma (sysctl):"]
    if not target.get("ok") or not ref.get("ok"):
        lines.append("  Karşılaştırma için her iki sunucu da okunamadı.")
        return lines
    tv = (target.get("data") or {}).get("values") or {}
    rv = (ref.get("data") or {}).get("values") or {}
    keys = sorted(set(tv) | set(rv))
    diff = 0
    for k in keys:
        a, b = tv.get(k, ""), rv.get(k, "")
        if str(a) != str(b):
            diff += 1
            lines.append(f"  {k}: hedef={a!s} · referans={b!s}")
    if diff == 0:
        lines.append("  Karşılaştırılan anahtarlar aynı görünüyor.")
    else:
        lines.append(
            f"  {diff} fark var; HugePages / sysctl ekranında hedefe referans değerleri "
            f"yapıştırıp Preview → Apply edin."
        )
    return lines


def build_analysis(
    session: Session,
    *,
    operation_id: str | None,
    message: str,
    targets: list[dict[str, Any]],
    references: list[dict[str, Any]],
    user: Any | None = None,
) -> dict[str, Any]:
    """
    Readonly probe / portal DB query + theoretical notes. Never applies changes.
    """
    from app.assistant.queries import is_db_query_op, run_db_query

    empty = {
        "analysis_tr": "",
        "analysis_lines": [],
        "probed": False,
        "probe_kind": None,
    }

    # Portal DB Q&A (inventory, jobs, audit, …) — no SSH
    if is_db_query_op(operation_id):
        q = run_db_query(session, operation_id, message, user=user)
        lines = ["Portal sorgu (readonly, uygulama yok):"] + list(q.get("lines") or [])
        if operation_id == "servers":
            lines.append("Ayrıntı / düzenleme: Sunucular sayfası.")
        elif operation_id == "jobs":
            lines.append("Ayrıntı: İşler sayfası.")
        elif operation_id == "audit":
            lines.append("Ayrıntı: Denetim sayfası.")
        return {
            "analysis_tr": "\n".join(lines),
            "analysis_lines": lines,
            "probed": True,
            "probe_kind": f"db:{operation_id}",
        }

    kind = probe_kind_for_op(operation_id)
    empty["probe_kind"] = kind
    if not kind or not targets:
        return empty

    want_gb = _requested_size_gb(message)
    target_payloads = [run_probe(session, kind, t) for t in targets[:1]]
    ref_payloads = [run_probe(session, kind, r) for r in references[:1]]

    lines: list[str] = ["Readonly analiz (uygulama yok):"]
    if kind == "filesystem":
        for p in target_payloads:
            lines.extend(_summarize_filesystem("Hedef", p, want_gb=want_gb))
        for p in ref_payloads:
            lines.extend(_summarize_filesystem("Referans", p, want_gb=None))
        if target_payloads and ref_payloads:
            lines.extend(_compare_filesystem(target_payloads[0], ref_payloads[0], want_gb))
    elif kind == "sysctl":
        for p in target_payloads:
            lines.extend(_summarize_generic(kind, "Hedef", p))
        for p in ref_payloads:
            lines.extend(_summarize_generic(kind, "Referans", p))
        if target_payloads and ref_payloads:
            lines.extend(_compare_sysctl(target_payloads[0], ref_payloads[0]))
    else:
        for p in target_payloads:
            lines.extend(_summarize_generic(kind, "Hedef", p))
        for p in ref_payloads:
            lines.extend(_summarize_generic(kind, "Referans", p))
        if target_payloads and ref_payloads and target_payloads[0].get("ok") and ref_payloads[0].get("ok"):
            lines.append(
                "Karşılaştırma: referans ile hedefi yan yana inceleyin; "
                "uygulama yalnızca ilgili ops ekranında Preview → Apply ile yapılır."
            )

    lines.append("Sonraki adım: deep link ile ops ekranını açın; asistan sunucuda değişiklik yapmaz.")
    text = "\n".join(lines)
    return {
        "analysis_tr": text,
        "analysis_lines": lines,
        "probed": True,
        "probe_kind": kind,
        "requested_size_gb": want_gb,
    }
