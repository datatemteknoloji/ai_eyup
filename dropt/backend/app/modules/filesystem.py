from __future__ import annotations

import json
import re
import shlex
from typing import Any

from sqlmodel import Session

from app.core.config import get_settings
from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.machine_type import asm_disk_mode, effective_machine_type
from app.services.target_ssh import run_ssh

ACTION_TITLES = {
    "extend": "Disk alanını büyüt",
    "create": "Yeni disk alanı oluştur",
    "organize": "Disk organize et",
}

MOUNT_BLACKLIST = frozenset({"/", "/boot", "/boot/efi", "/efi", "/sys", "/proc", "/dev", "/root"})
# root VG üzerinde extend'e izinli mount'lar (create/organize root VG'yi yine kilitler)
ROOT_VG_EXTEND_ALLOWLIST = frozenset({"/home", "/var", "/tmp", "/var/tmp"})
MAX_ADD_GB = 500
MAX_CREATE_GB = 2000
MIN_SIZE_GB = 0.1  # 0.1 GiB ≈ 102 MiB (örn. 0.5 → 512 MiB)
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
MOUNT_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
# Partition hizası (~1MiB) + LVM pe_start/metadata + 1×PE (4MiB) payı — yüzde değil sabit
DISK_USABLE_RESERVE_BYTES = 16 * 1024 * 1024
MIN_VG_FREE_BYTES = 4 * 1024 * 1024  # ~1 PE
GIB = 1024**3
MIB = 1024**2
# %100 organize: sabitler kaynak LV’nin tamamını yemeyecek kadar yer bırakmalı
_ORG_REMAIN_EPS_GB = 0.05

_INVENTORY_TTL_SEC = 60 * 60 * 12


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _inventory_cache_key(server_id: int) -> str:
    return f"filesystem:inventory:{server_id}"


def get_cached_inventory(server_id: int) -> dict[str, Any] | None:
    try:
        raw = _redis().get(_inventory_cache_key(server_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def set_cached_inventory(server_id: int, payload: dict[str, Any]) -> None:
    try:
        # cached flag istemciye yazılmaz / saklanmaz
        body = {k: v for k, v in payload.items() if k != "cached"}
        _redis().setex(_inventory_cache_key(server_id), _INVENTORY_TTL_SEC, json.dumps(body))
    except Exception:
        pass


def invalidate_cached_inventory(server_id: int) -> None:
    try:
        _redis().delete(_inventory_cache_key(server_id))
    except Exception:
        pass


def job_summary(action: str, payload: dict[str, Any]) -> str:
    if action == "organize":
        slices = payload.get("slices") or []
        return f"{ACTION_TITLES.get(action, action)}: {payload.get('mount')} → {len(slices)} FS"
    if _payload_use_all_free(payload):
        return f"{ACTION_TITLES.get(action, action)}: {payload.get('mount')} 100%FREE"
    if action == "create":
        return f"{ACTION_TITLES.get(action, action)}: {payload.get('mount')} {payload.get('size_gb')}GB"
    return f"{ACTION_TITLES.get(action, action)}: {payload.get('mount')} +{payload.get('add_gb')}GB"


def _vg_lv_from_mapper_basename(name: str) -> tuple[str, str] | None:
    """
    LVM device-mapper adı: datavg-data1lv → (datavg, data1lv)
    Tire içeren isimler `--` ile kaçar: my--vg-my--lv → (my-vg, my-lv)
    """
    name = (name or "").strip()
    if not name or name.startswith("mpath") or re.match(r"^dm-\d+$", name):
        return None
    vg_chars: list[str] = []
    i = 0
    while i < len(name):
        if name[i] == "-":
            if i + 1 < len(name) and name[i + 1] == "-":
                vg_chars.append("-")
                i += 2
                continue
            vg = "".join(vg_chars)
            lv = name[i + 1 :].replace("--", "-")
            if vg and lv:
                return vg, lv
            return None
        vg_chars.append(name[i])
        i += 1
    return None


def detect_root_vg(session: Session, server: TargetServer) -> str:
    """`/` mount'unun LV'sinin VG adı (örn. rootvg)."""
    script = r"""
set +e
SRC=$(findmnt -no SOURCE / 2>/dev/null | head -1)
REAL=$(readlink -f "$SRC" 2>/dev/null || echo "$SRC")
echo "SRC=$SRC"
echo "REAL=$REAL"
lvs --noheadings -o lv_path,vg_name,lv_name 2>/dev/null | while read -r path vg lv; do
  path=$(echo "$path" | xargs); vg=$(echo "$vg" | xargs); lv=$(echo "$lv" | xargs)
  [ -z "$path" ] && continue
  pr=$(readlink -f "$path" 2>/dev/null || echo "$path")
  echo "LV|$path|$vg|$lv|$pr"
done
"""
    r = run_ssh(session, server, script, timeout=25)
    src = real = ""
    lvs_rows: list[tuple[str, str, str, str]] = []
    for line in r.stdout.splitlines():
        if line.startswith("SRC="):
            src = line.split("=", 1)[1].strip()
        elif line.startswith("REAL="):
            real = line.split("=", 1)[1].strip()
        elif line.startswith("LV|"):
            p = line.split("|")
            if len(p) >= 5:
                lvs_rows.append((p[1].strip(), p[2].strip(), p[3].strip(), p[4].strip()))
    for path, vg, _lv, pr in lvs_rows:
        if real and pr == real:
            return vg
        if src and (path == src or pr == src):
            return vg
    parsed = _vg_lv_from_mapper_basename(src.rsplit("/", 1)[-1] if src else "")
    if parsed:
        return parsed[0]
    return ""


def _enrich_filesystems(
    session: Session, server: TargetServer, rows: list[dict[str, Any]], root_vg: str
) -> list[dict[str, Any]]:
    """Her FS satırına vg_name / lv_name / on_root_vg ekle; root VG üzerinde extend kapat."""
    r = run_ssh(
        session,
        server,
        r"""
set +e
# LV|path|vg|lv|real
lvs --noheadings -o lv_path,vg_name,lv_name 2>/dev/null | while read -r path vg lv; do
  path=$(echo "$path" | xargs); vg=$(echo "$vg" | xargs); lv=$(echo "$lv" | xargs)
  [ -z "$path" ] && continue
  real=$(readlink -f "$path" 2>/dev/null || echo "$path")
  echo "LV|$path|$vg|$lv|$real"
done
echo ---
# SRC|src|real  (df cihazları)
df -PT 2>/dev/null | awk 'NR>1 {print $1}' | while read -r src; do
  [ -n "$src" ] || continue
  real=$(readlink -f "$src" 2>/dev/null || echo "$src")
  echo "SRC|$src|$real"
done
""",
        timeout=40,
    )
    # key → (vg, lv)
    by_path: dict[str, tuple[str, str]] = {}
    by_real: dict[str, tuple[str, str]] = {}
    for line in r.stdout.splitlines():
        if line.strip() == "---" or not line.startswith("LV|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        path, vg, lv, real = parts[1].strip(), parts[2].strip(), parts[3].strip(), parts[4].strip()
        if not vg:
            continue
        pair = (vg, lv)
        by_path[path] = pair
        by_path[f"/dev/{vg}/{lv}"] = pair
        # mapper escaped form
        esc_vg = vg.replace("-", "--")
        esc_lv = lv.replace("-", "--")
        by_path[f"/dev/mapper/{esc_vg}-{esc_lv}"] = pair
        if real:
            by_real[real] = pair

    def resolve(src: str) -> tuple[str, str]:
        if not src:
            return "", ""
        if src in by_path:
            return by_path[src]
        # /dev/VG/LV
        m = re.match(r"^/dev/([^/]+)/([^/]+)$", src)
        if m and not m.group(1).startswith("mapper"):
            return m.group(1), m.group(2)
        # mapper basename (dm-N olmadan önce src üzerinden)
        base = src.rsplit("/", 1)[-1]
        parsed = _vg_lv_from_mapper_basename(base)
        if parsed:
            return parsed
        # real path → /dev/dm-N eşlemesi
        # SRC satırlarından real bul
        return "", ""

    # src → real map
    src_real: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if not line.startswith("SRC|"):
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            src_real[parts[1].strip()] = parts[2].strip()

    out: list[dict[str, Any]] = []
    for row in rows:
        src = row.get("source") or ""
        vg, lv = ("", "")
        if src.startswith("/dev/"):
            vg, lv = resolve(src)
            if not vg:
                real = src_real.get(src) or ""
                if real and real in by_real:
                    vg, lv = by_real[real]
            if not vg:
                # son çare: mapper adını src'den parse et
                parsed = _vg_lv_from_mapper_basename(src.rsplit("/", 1)[-1])
                if parsed:
                    vg, lv = parsed
        on_root = bool(root_vg and vg and vg == root_vg)
        blacklisted = bool(row.get("blacklisted"))
        mount = str(row.get("mount") or "")
        base_ok = (
            (not blacklisted)
            and src.startswith("/dev/")
            and row.get("fstype") in {"xfs", "ext4", "ext3"}
            and bool(vg)
        )
        if on_root:
            extendable = base_ok and mount in ROOT_VG_EXTEND_ALLOWLIST
        else:
            extendable = base_ok
        out.append(
            {
                **row,
                "vg_name": vg,
                "lv_name": lv,
                "on_root_vg": on_root,
                "extendable": extendable,
            }
        )
    return out


def _is_overlay_fs(src: str, fstype: str, mount: str) -> bool:
    """df çıktısında overlay / overlayfs (docker rootfs vb.) — listelenmez."""
    blob = f"{src} {fstype} {mount}".lower()
    return "overlay" in blob


def list_filesystems(
    session: Session,
    server: TargetServer,
    *,
    root_vg: str | None = None,
) -> list[dict[str, Any]]:
    # -h: Size/Used/Avail insan okunur; -P: tek satır; -T: tip
    script = r"""
df -hPT 2>/dev/null | awk 'NR>1 {print $1"|"$2"|"$3"|"$4"|"$5"|"$6"|"$7}'
"""
    r = run_ssh(session, server, script, timeout=20)
    rows: list[dict[str, Any]] = []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 7:
            continue
        src, fstype, size, used, avail, pct, mount = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
            parts[4],
            parts[5],
            parts[6],
        )
        if _is_overlay_fs(src, fstype, mount):
            continue
        blacklisted = mount in MOUNT_BLACKLIST
        rows.append(
            {
                "source": src,
                "fstype": fstype,
                "size": size,
                "used": used,
                "avail": avail,
                "use_pct": pct,
                "mount": mount,
                "blacklisted": blacklisted,
                "extendable": (not blacklisted) and src.startswith("/dev/") and fstype in {"xfs", "ext4", "ext3"},
            }
        )
    if root_vg is None:
        root_vg = detect_root_vg(session, server)
    return _enrich_filesystems(session, server, rows, root_vg)


def list_volume_groups(
    session: Session,
    server: TargetServer,
    *,
    root_vg: str | None = None,
) -> list[dict[str, Any]]:
    r = run_ssh(
        session,
        server,
        "vgs --noheadings -o vg_name,vg_size,vg_free --units g --nosuffix 2>/dev/null "
        "| awk '{print $1\"|\"$2\"|\"$3}'",
        timeout=20,
    )
    if root_vg is None:
        root_vg = detect_root_vg(session, server)
    rows: list[dict[str, Any]] = []
    for line in r.stdout.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        try:
            name = parts[0]
            is_root = bool(root_vg and name == root_vg)
            rows.append(
                {
                    "name": name,
                    "size_gb": float(parts[1]),
                    "free_gb": float(parts[2]),
                    "is_root_vg": is_root,
                    "selectable": not is_root,
                }
            )
        except ValueError:
            continue
    return rows


def list_inventory(
    session: Session,
    server: TargetServer,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """FileSystem Management tek ekran verisi (Redis cache)."""
    from app.modules import asm

    sid = int(server.id)  # type: ignore[arg-type]
    if not refresh:
        cached = get_cached_inventory(sid)
        if cached is not None:
            return {**cached, "cached": True}

    # Tek root VG tespiti — vgs/fs paylaşır
    root_vg = detect_root_vg(session, server)
    vgs = list_volume_groups(session, server, root_vg=root_vg)
    fss = list_filesystems(session, server, root_vg=root_vg)
    vg_free = {str(v["name"]): float(v.get("free_gb") or 0) for v in vgs}
    vg_size = {str(v["name"]): float(v.get("size_gb") or 0) for v in vgs}
    for f in fss:
        vn = str(f.get("vg_name") or "")
        if vn:
            f["vg_free_gb"] = vg_free.get(vn)
            f["vg_size_gb"] = vg_size.get(vn)
    mode = asm_disk_mode(server)
    # Yenile / cold load: VMware vb. yeni disk için SCSI rescan + ASM disk cache atla
    if refresh:
        asm.invalidate_cached_scan(sid)
    scan = asm.scan_disks(session, server, refresh=refresh)
    free_disks = [d for d in (scan.get("disks") or []) if d.get("usable")]
    payload = {
        "root_vg": root_vg,
        "volume_groups": vgs,
        "filesystems": fss,
        "free_disks": free_disks,
        "disk_mode": mode,
        "machine_type": effective_machine_type(server),
        "cached_disks": bool(scan.get("cached")),
    }
    set_cached_inventory(sid, payload)
    return {**payload, "cached": False}


def refresh_inventory_cache_once(session: Session, server: TargetServer) -> None:
    """Başarılı FS apply sonrası inventory + partitionsuz disk cache 1 kez taze tara."""
    try:
        from app.modules import asm

        sid = int(server.id)  # type: ignore[arg-type]
        invalidate_cached_inventory(sid)
        asm.invalidate_cached_scan(sid)
        list_inventory(session, server, refresh=True)
    except Exception:
        pass


TWO_TB = 2 * 1024**4


def _part_path_for_device(device: str) -> str:
    """ /dev/sdc → /dev/sdc1 ; /dev/mapper/mpatha → /dev/mapper/mpatha1|p1 """
    from app.modules.asm import partition_path, sd_partition_path

    dev = (device or "").rstrip("/")
    if dev.startswith("/dev/mapper/"):
        return partition_path(dev.rsplit("/", 1)[-1])
    return sd_partition_path(dev)


def _payload_use_all_free(payload: dict[str, Any]) -> bool:
    v = payload.get("use_all_free")
    return v is True or v in (1, "1", "true", "True", "yes", "on")


def _disk_usable_bytes(size_bytes: int) -> int:
    return max(0, int(size_bytes or 0) - DISK_USABLE_RESERVE_BYTES)


def _disk_usable_gb(size_bytes: int) -> float:
    """Usable GiB (ondalıklı) — rezerv düşülmüş. Sub-GB disklerde 0’a floor etme."""
    return round(_disk_usable_bytes(size_bytes) / float(GIB), 3)


def _disk_gb_floor(size_bytes: int) -> int:
    """Geriye uyum: usable GiB floor."""
    return max(0, _disk_usable_bytes(size_bytes) // GIB)


def _estimated_free_bytes(vg_free_gb: float, disks: list[dict[str, Any]]) -> int:
    vg_b = int(float(vg_free_gb) * GIB)
    disk_b = sum(_disk_usable_bytes(int(d.get("size_bytes") or 0)) for d in disks)
    return max(0, vg_b + disk_b)


def _parse_size_gb(raw: Any, *, field: str = "boyut") -> float:
    """GB (ondalıklı). 0.5 → 0.5 GiB ≈ 512 MiB. Nokta veya virgül."""
    if raw is None or raw == "":
        raise ValueError(f"{field} zorunlu")
    if isinstance(raw, bool):
        raise ValueError(f"{field} geçersiz")
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).strip().replace(",", ".")
        if not s:
            raise ValueError(f"{field} zorunlu")
        try:
            val = float(s)
        except ValueError as exc:
            raise ValueError(f"{field} sayı olmalı (örn. 0.5 veya 10)") from exc
    if val != val or val <= 0:  # NaN
        raise ValueError(f"{field} pozitif olmalı")
    return val


def _size_gb_to_mb(size_gb: float) -> int:
    """GiB → MiB (lvcreate -L …M). En az 1 MiB."""
    mb = int(round(float(size_gb) * 1024))
    return max(1, mb)


def _assert_size_gb(size_gb: float, *, max_gb: float, field: str = "Boyut") -> None:
    if size_gb < MIN_SIZE_GB or size_gb > max_gb:
        raise ValueError(f"{field} {MIN_SIZE_GB}–{max_gb} GB olmalı (örn. 0.5 = 512MiB)")


def _lvextend_size_cmd(*, lv_path: str, vg_name: str, add_gb: float, use_all_free: bool) -> str:
    if use_all_free:
        return f"lvextend -l +100%FREE {shlex.quote(lv_path)}"
    need_m = _size_gb_to_mb(add_gb)
    # İstek tam yetmezse (partition/PV overhead) gerçek VFree'ye clamp
    return (
        "set -e\n"
        f"VG={shlex.quote(vg_name)}\n"
        f"LV={shlex.quote(lv_path)}\n"
        f"NEED_M={need_m}\n"
        'FREE_M=$(vgs --noheadings --nosuffix --units m -o vg_free "$VG" | tr -d \' \' | cut -d. -f1)\n'
        'FREE_M=${FREE_M:-0}\n'
        'if [ "$FREE_M" -lt 1 ]; then echo "VG_FREE_EMPTY" >&2; exit 1; fi\n'
        'if [ "$FREE_M" -lt "$NEED_M" ]; then\n'
        '  echo "CLAMP: requested ${NEED_M}M, using ${FREE_M}M (partition/PV overhead)"\n'
        '  lvextend -L +${FREE_M}M "$LV"\n'
        "else\n"
        f'  lvextend -L +{need_m}M "$LV"\n'
        "fi\n"
    )


def _lvcreate_size_cmd(*, vg_name: str, lv_name: str, size_gb: float, use_all_free: bool) -> str:
    if use_all_free:
        return f"lvcreate -y -l 100%FREE -n {shlex.quote(lv_name)} {shlex.quote(vg_name)}"
    need_m = _size_gb_to_mb(size_gb)
    return (
        "set -e\n"
        f"VG={shlex.quote(vg_name)}\n"
        f"LV={shlex.quote(lv_name)}\n"
        f"NEED_M={need_m}\n"
        'FREE_M=$(vgs --noheadings --nosuffix --units m -o vg_free "$VG" | tr -d \' \' | cut -d. -f1)\n'
        'FREE_M=${FREE_M:-0}\n'
        'if [ "$FREE_M" -lt 1 ]; then echo "VG_FREE_EMPTY" >&2; exit 1; fi\n'
        'if [ "$FREE_M" -lt "$NEED_M" ]; then\n'
        '  echo "CLAMP: requested ${NEED_M}M, using ${FREE_M}M (partition/PV overhead)"\n'
        '  lvcreate -y -L ${FREE_M}M -n "$LV" "$VG"\n'
        "else\n"
        f'  lvcreate -y -L {need_m}M -n "$LV" "$VG"\n'
        "fi\n"
    )


def _collect_add_disks(session: Session, server: TargetServer, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Payload add_disks → hâlâ usable olan free disk kayıtları."""
    from app.modules import asm

    raw = payload.get("add_disks") or []
    if not isinstance(raw, list) or not raw:
        return []
    scan = asm.scan_disks(session, server, refresh=False)
    usable = [d for d in (scan.get("disks") or []) if d.get("usable")]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        device = str(item.get("device") or "").strip()
        wwid = str(item.get("wwid") or "").strip()
        alias = str(item.get("alias") or "").strip()
        match = None
        for d in usable:
            if wwid and d.get("wwid") == wwid:
                match = d
                break
            if device and d.get("device") == device:
                match = d
                break
            if alias and d.get("alias") == alias:
                match = d
                break
        if match is None:
            raise ValueError(f"Seçilen disk uygun değil veya kullanımda: {alias or device or wwid}")
        key = str(match.get("wwid") or match.get("device") or match.get("alias"))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "alias": match.get("alias") or alias,
                "wwid": match.get("wwid") or wwid,
                "device": match.get("device") or device,
                "size": match.get("size") or "",
                "size_bytes": int(match.get("size_bytes") or 0),
            }
        )
    return out


def _vg_extend_prep_cmds(vg_name: str, disks: list[dict[str, Any]]) -> list[str]:
    """Partition (fdisk/parted) + pvcreate + vgextend — tek script; fdisk exit !=0 tolere."""
    cmds: list[str] = []
    part_paths: list[str] = []
    for d in disks:
        device = str(d["device"])
        size_b = int(d.get("size_bytes") or 0)
        part = _part_path_for_device(device)
        part_paths.append(part)
        if size_b >= TWO_TB:
            cmds.append(f"# partition parted gpt {device} → {part}")
            part_body = (
                f"parted -s {shlex.quote(device)} mklabel gpt || true\n"
                f"parted -s {shlex.quote(device)} mkpart primary 0% 100% || true\n"
                f"partprobe {shlex.quote(device)} 2>/dev/null || true\n"
            )
        else:
            cmds.append(f"# partition fdisk {device} → {part}")
            # fdisk ioctl uyarısında exit!=0 verebilir; partition oluştuysa devam
            part_body = (
                f"printf 'n\\np\\n1\\n\\n\\nw\\n' | fdisk {shlex.quote(device)} || true\n"
                f"partprobe {shlex.quote(device)} 2>/dev/null || true\n"
            )
        script = (
            "set +e\n"
            + part_body
            + "sleep 1\n"
            + f"for i in $(seq 1 30); do [ -b {shlex.quote(part)} ] && break; sleep 1; done\n"
            + f"if [ ! -b {shlex.quote(part)} ]; then "
            + f"echo PART_MISSING:{shlex.quote(part)} >&2; exit 1; fi\n"
            # Önceki yarıda kalmış denemede PV zaten varsa geç
            + f"if pvs {shlex.quote(part)} >/dev/null 2>&1; then echo PV_EXISTS; "
            + f"else pvcreate -y {shlex.quote(part)} || "
            + f"{{ echo PVCREATE_FAIL:{shlex.quote(part)} >&2; exit 1; }}; fi\n"
            + "echo PART_PV_OK\n"
        )
        cmds.append(script)
    if part_paths:
        joined = " ".join(shlex.quote(p) for p in part_paths)
        cmds.append(
            "set +e\n"
            f"vgextend {shlex.quote(vg_name)} {joined}\n"
            "ec=$?\n"
            'if [ $ec -ne 0 ]; then echo "VGEXTEND_FAIL" >&2; exit $ec; fi\n'
            "echo VGEXTEND_OK\n"
        )
    return cmds


def _ensure_capacity(
    *,
    vg_free_gb: float,
    need_gb: float,
    add_disks: list[dict[str, Any]],
    use_all_free: bool = False,
) -> float:
    """VG free + disk usable (16MiB rezerv). Dönüş: disk usable GB (özet)."""
    disk_gb = sum(_disk_usable_gb(int(d.get("size_bytes") or 0)) for d in add_disks)
    est = _estimated_free_bytes(vg_free_gb, add_disks)
    if use_all_free:
        if est < MIN_VG_FREE_BYTES:
            raise ValueError(
                "100%FREE için VG’de kullanılabilir boş alan yok. "
                "Partitionsuz disk seçin (usable = ham − 16MiB rezerv) veya alan ekleyin."
            )
        return disk_gb
    need_b = int(round(float(need_gb) * GIB))
    if est < need_b:
        if not add_disks:
            raise ValueError(
                f"VG boş alan yetersiz ({vg_free_gb:.1f} GB < {need_gb:g} GB). "
                "Partitionsuz disk seçin veya sanallaştırma ekibinden disk isteyin."
            )
        raise ValueError(
            f"Seçilen diskler + VG boş alan yetersiz "
            f"(~{est / GIB:.2f} GB usable < {need_gb:g} GB; disklerde 16MiB LVM/partition rezervi düşülür)"
        )
    return disk_gb


def _assert_vg_operable(session: Session, server: TargetServer, vg_name: str) -> None:
    vg_name = (vg_name or "").strip()
    if not vg_name:
        raise ValueError("VG adı zorunlu")
    root_vg = detect_root_vg(session, server)
    if root_vg and vg_name == root_vg:
        raise ValueError(f"root LV içeren VG üzerinde işlem yapılamaz: {vg_name}")
    vgs = list_volume_groups(session, server)
    vg = next((v for v in vgs if v["name"] == vg_name), None)
    if vg is None:
        raise ValueError(f"VG bulunamadı: {vg_name}")
    if not vg.get("selectable", True):
        raise ValueError(f"Bu VG kilitli: {vg_name}")


def _lv_info(session: Session, server: TargetServer, source: str) -> dict[str, Any]:
    """df source (/dev/mapper/VG-LV veya /dev/dm-N) → lv_path / vg / lv."""
    script = f"""
set +e
SRC={shlex.quote(source)}
REAL=$(readlink -f "$SRC" 2>/dev/null || echo "$SRC")
echo "SRC=$SRC"
echo "REAL=$REAL"
lvs --noheadings -o lv_path,vg_name,lv_name 2>/dev/null | while read -r path vg lv; do
  path=$(echo "$path" | xargs); vg=$(echo "$vg" | xargs); lv=$(echo "$lv" | xargs)
  [ -z "$path" ] && continue
  pr=$(readlink -f "$path" 2>/dev/null || echo "$path")
  echo "LV|$path|$vg|$lv|$pr"
done
vgs --noheadings -o vg_name,vg_free --units g --nosuffix 2>/dev/null | awk '{{print "VG|"$1"|"$2}}'
"""
    r = run_ssh(session, server, script, timeout=25)
    src = source
    real = source
    lvs_rows: list[tuple[str, str, str, str]] = []
    vg_free: dict[str, float] = {}
    for line in r.stdout.splitlines():
        if line.startswith("SRC="):
            src = line.split("=", 1)[1].strip() or src
        elif line.startswith("REAL="):
            real = line.split("=", 1)[1].strip() or real
        elif line.startswith("LV|"):
            p = line.split("|")
            if len(p) >= 5:
                lvs_rows.append((p[1].strip(), p[2].strip(), p[3].strip(), p[4].strip()))
        elif line.startswith("VG|"):
            p = line.split("|")
            if len(p) >= 3:
                try:
                    vg_free[p[1].strip()] = float(p[2].strip())
                except ValueError:
                    pass

    lv_path = vg = lv = ""

    # 1) dm real path eşlemesi
    for path, vg_name, lv_name, pr in lvs_rows:
        if real and pr == real:
            lv_path, vg, lv = path, vg_name, lv_name
            break
        if path == src or path == real or path == source:
            lv_path, vg, lv = path, vg_name, lv_name
            break

    # 2) /dev/mapper/VG-LV veya basename parse
    if not lv_path:
        for candidate in (src, source, real):
            base = candidate.rsplit("/", 1)[-1] if candidate else ""
            parsed = _vg_lv_from_mapper_basename(base)
            if not parsed:
                m = re.match(r"^/dev/([^/]+)/([^/]+)$", candidate or "")
                if m and m.group(1) != "mapper":
                    parsed = (m.group(1), m.group(2))
            if not parsed:
                continue
            p_vg, p_lv = parsed
            for path, vg_name, lv_name, _pr in lvs_rows:
                if vg_name == p_vg and lv_name == p_lv:
                    lv_path, vg, lv = path, vg_name, lv_name
                    break
            if lv_path:
                break
            # lvs satırı yoksa bile yol tahmin et
            vg, lv = p_vg, p_lv
            lv_path = f"/dev/{vg}/{lv}"

    return {
        "real": real,
        "lv_path": lv_path,
        "vg": vg,
        "lv": lv,
        "vg_free_gb": vg_free.get(vg, 0.0) if vg else 0.0,
    }


def _lv_size_gb(session: Session, server: TargetServer, vg: str, lv: str) -> float:
    r = run_ssh(
        session,
        server,
        f"lvs --noheadings -o lv_size --units g --nosuffix "
        f"{shlex.quote(vg)}/{shlex.quote(lv)} 2>/dev/null | awk '{{print $1}}'",
        timeout=15,
    )
    try:
        return float((r.stdout or "").strip().split()[0])
    except (ValueError, IndexError):
        return 0.0


def _lv_name_from_mount(mount: str, *, used: set[str] | None = None) -> str:
    """/test3 → test3lv; /data/app → data_applv (her zaman 'lv' soneki)."""
    parts = [p for p in (mount or "").strip("/").split("/") if p]
    stem = "_".join(parts) if parts else "data"
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem)
    if not stem or not stem[0].isalpha():
        stem = f"x{stem}" if stem else "data"
    # 'lv' için yer bırak (max 32)
    stem = stem[:30].rstrip("_") or "data"

    def with_lv(s: str, n: int = 0) -> str:
        if n <= 1:
            raw = f"{s}lv"
        else:
            suffix = f"_{n}lv"
            raw = f"{s[: 32 - len(suffix)]}{suffix}"
        return raw[:32]

    used = used if used is not None else set()
    n = 1
    name = with_lv(stem, n)
    while not NAME_RE.match(name) or name in used:
        n += 1
        name = with_lv(stem, n)
        if n > 99:
            raise ValueError(f"LV adı üretilemedi: {mount}")
    used.add(name)
    return name


def _assert_fs_empty_and_idle(session: Session, server: TargetServer, mount: str) -> None:
    """Organize için: mount boş (lost+found hariç) ve process bağlı olmamalı."""
    m = shlex.quote(mount)
    script = f"""
set +e
M={m}
if ! mountpoint -q "$M" 2>/dev/null; then
  echo NOT_MOUNTED
  exit 0
fi
# açık process?
if command -v fuser >/dev/null 2>&1; then
  PIDS=$(fuser -m "$M" 2>/dev/null | tr -s ' ' '\\n' | grep -E '^[0-9]+$' | head -n 5)
  if [ -n "$PIDS" ]; then
    echo "BUSY:$PIDS"
  fi
fi
# lost+found dışı içerik?
EXTRA=$(find "$M" -mindepth 1 ! -name lost+found -print -quit 2>/dev/null)
if [ -n "$EXTRA" ]; then
  echo "NONEMPTY:$EXTRA"
fi
# df used (1K blocks) — metadata toleransı 256
USED=$(df -P "$M" 2>/dev/null | awk 'NR==2 {{print $3}}')
echo "USED_KB:${{USED:-0}}"
echo CHECK_DONE
"""
    r = run_ssh(session, server, script, timeout=30)
    out = r.stdout or ""
    if "NOT_MOUNTED" in out:
        raise ValueError(f"Mount bağlı değil: {mount}")
    if "BUSY:" in out:
        raise ValueError(f"FS kullanımda (açık process): {mount} — organize edilemez")
    if "NONEMPTY:" in out:
        raise ValueError(f"FS boş değil (veri var): {mount} — organize edilemez")
    used_kb = 0
    for line in out.splitlines():
        if line.startswith("USED_KB:"):
            try:
                used_kb = int(line.split(":", 1)[1].strip() or "0")
            except ValueError:
                used_kb = 0
    # ~256MB üstü kullanım şüpheli (boş FS metadata genelde çok küçük)
    if used_kb > 256 * 1024:
        raise ValueError(
            f"FS kullanımda görünüyor (used≈{used_kb // 1024}MB): {mount} — organize edilemez"
        )


def _owner_ok(owner: str) -> bool:
    if not owner:
        return True
    return bool(
        re.match(
            r"^[A-Za-z_][A-Za-z0-9_-]{0,31}(:[A-Za-z_][A-Za-z0-9_-]{0,31})?$",
            owner,
        )
    )


def _build_organize(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    """Mevcut boş FS'i yık → aynı VG içinde N yeni FS; kalan VG free."""
    source_mount = (payload.get("mount") or "").strip()
    raw_slices = payload.get("slices") or []
    if not source_mount or source_mount in MOUNT_BLACKLIST:
        raise ValueError("Kaynak mount kara listede veya boş")
    if not isinstance(raw_slices, list) or len(raw_slices) < 1:
        raise ValueError("En az bir yeni FS satırı (slice) gerekli")
    if len(raw_slices) > 32:
        raise ValueError("En fazla 32 FS satırı")

    fss = list_filesystems(session, server)
    row = next((x for x in fss if x["mount"] == source_mount), None)
    if row is None:
        raise ValueError("Kaynak mount bulunamadı")
    if row.get("on_root_vg"):
        raise ValueError("root VG üzerindeki dosya sistemi organize edilemez")
    if not row.get("extendable"):
        raise ValueError("Bu FS organize edilemez (LVM + xfs/ext, blacklist/overlay hariç)")

    info = _lv_info(session, server, row["source"])
    if not info.get("lv_path") or not info.get("vg") or not info.get("lv"):
        raise ValueError("LVM volume bulunamadı — yalnızca LV desteklenir")
    vg_name = str(info["vg"])
    old_lv = str(info["lv"])
    old_path = str(info["lv_path"])
    _assert_vg_operable(session, server, vg_name)
    _assert_fs_empty_and_idle(session, server, source_mount)

    budget_gb = _lv_size_gb(session, server, vg_name, old_lv)
    if budget_gb < 1:
        raise ValueError("Kaynak LV boyutu okunamadı veya <1GB")

    used_names: set[str] = set()
    slices: list[dict[str, Any]] = []
    mounts_seen: set[str] = set()
    use_all_count = 0

    # 1. pass: doğrula + sabit boyutlar; %100 satırı sonra bütçeden kalan alır
    pending: list[dict[str, Any]] = []
    fixed_total = 0
    for i, s in enumerate(raw_slices):
        if not isinstance(s, dict):
            raise ValueError(f"Slice {i + 1} geçersiz")
        mnt = str(s.get("mount") or "").strip()
        fstype = str(s.get("fstype") or "xfs").strip().lower()
        owner = str(s.get("owner") or "").strip()
        use_all = bool(s.get("use_all_free"))
        if not MOUNT_RE.match(mnt) or ".." in mnt or mnt in MOUNT_BLACKLIST:
            raise ValueError(f"Slice {i + 1}: mount geçersiz veya kara listede ({mnt})")
        if mnt in mounts_seen:
            raise ValueError(f"Tekrarlayan mount: {mnt}")
        mounts_seen.add(mnt)
        if fstype not in {"xfs", "ext4"}:
            raise ValueError(f"Slice {i + 1}: fstype xfs veya ext4 olmalı")
        if use_all:
            use_all_count += 1
            if use_all_count > 1:
                raise ValueError("Yalnızca bir satırda “%100’ü kullan” seçilebilir")
            size_gb = 0.0  # apply’da 100%FREE; önizlemede kalan tahmini
        else:
            size_gb = _parse_size_gb(s.get("size_gb"), field=f"Slice {i + 1} boyut")
            _assert_size_gb(size_gb, max_gb=MAX_CREATE_GB, field=f"Slice {i + 1} boyut")
        if not _owner_ok(owner):
            raise ValueError(f"Slice {i + 1}: owner geçersiz")
        lv_name = _lv_name_from_mount(mnt, used=used_names)
        # kaynak LV dışında aynı isim VG'de varsa çakışma
        if lv_name != old_lv:
            exists = run_ssh(
                session,
                server,
                f"lvs {shlex.quote(vg_name)}/{shlex.quote(lv_name)} >/dev/null 2>&1 && echo LVEXISTS || true",
                timeout=10,
            )
            if "LVEXISTS" in (exists.stdout or ""):
                raise ValueError(f"LV zaten var: {vg_name}/{lv_name} (mount={mnt})")
        # hedef mount kaynak değilse ve zaten dolu/mounted ise (başka FS) engelle
        if mnt != source_mount:
            chk = run_ssh(
                session,
                server,
                f"if mountpoint -q {shlex.quote(mnt)} 2>/dev/null; then echo MOUNTED; "
                f"elif [ -d {shlex.quote(mnt)} ] && [ -n \"$(ls -A {shlex.quote(mnt)} 2>/dev/null)\" ]; then echo NONEMPTY; "
                f"else echo OK; fi",
                timeout=15,
            )
            if "MOUNTED" in (chk.stdout or ""):
                raise ValueError(f"Hedef mount zaten bağlı: {mnt}")
            if "NONEMPTY" in (chk.stdout or ""):
                raise ValueError(f"Hedef mount dizini boş değil: {mnt}")
        if not use_all:
            fixed_total += size_gb
        pending.append(
            {
                "mount": mnt,
                "size_gb": size_gb,
                "use_all_free": use_all,
                "fstype": fstype,
                "owner": owner,
                "lv_name": lv_name,
                "device": f"/dev/{vg_name}/{lv_name}",
            }
        )

    if fixed_total > budget_gb + 1e-6:
        raise ValueError(
            f"Sabit toplam {fixed_total:g}GB > kaynak LV ≈{budget_gb:.2f}GB — "
            "boyutları küçültün (kalan VG'de bırakılır)"
        )
    remain_est = max(0.0, budget_gb - float(fixed_total))
    for sl in pending:
        if sl["use_all_free"]:
            # int(budget) kırpması yok: sabitler kaynak LV’yi bitirmesin yeter
            if remain_est < _ORG_REMAIN_EPS_GB:
                raise ValueError(
                    f"%100 satırı için kalan bütçe yok "
                    f"(sabit {fixed_total:g}GB, kaynak ≈{budget_gb:.2f}GB, kalan ≈{remain_est:.2f}GB)"
                )
            if remain_est > MAX_CREATE_GB:
                raise ValueError(f"%100 satırı boyutu {MAX_CREATE_GB} GB sınırını aşıyor")
            # Önizleme tahmini; gerçek boyut lvcreate -l 100%FREE ile VG kalan extent
            sl["size_gb"] = round(remain_est, 3)
        slices.append(
            {
                "mount": sl["mount"],
                "size_gb": float(sl["size_gb"]),
                "fstype": sl["fstype"],
                "owner": sl["owner"],
                "lv_name": sl["lv_name"],
                "device": sl["device"],
                "use_all_free": bool(sl["use_all_free"]),
            }
        )

    # %100 satırı bütçenin kalanını alır → toplam ≈ budget (VG’de ekstra bırakılmaz)
    total_gb = float(fixed_total) + (remain_est if use_all_count else 0.0)
    if use_all_count == 0:
        total_gb = sum(float(sl["size_gb"]) for sl in slices)
        if total_gb > budget_gb + 1e-6:
            raise ValueError(
                f"Toplam {total_gb:g}GB > kaynak LV ≈{budget_gb:.2f}GB — "
                "boyutları küçültün (kalan VG'de bırakılır)"
            )
    remain_gb = max(0.0, budget_gb - float(total_gb))

    # --- tear-down (non-interactive) ---
    cmds: list[str] = [
        f"# organize: {source_mount} ({vg_name}/{old_lv} ≈{budget_gb:.1f}G) → {len(slices)} FS, kalan ~{remain_gb:.1f}G VG",
        f"umount {shlex.quote(source_mount)}",
        (
            "TS=$(date +%s)\n"
            "cp -a /etc/fstab /etc/fstab.bak.dropt.$TS\n"
            f"awk -v m={shlex.quote(source_mount)} "
            "'BEGIN{FS=OFS=\" \"} /^[[:space:]]*#/ || NF<2 {print; next} "
            "{mp=$2; if (mp!=m) print}' /etc/fstab > /etc/fstab.dropt.new\n"
            "mv -f /etc/fstab.dropt.new /etc/fstab\n"
        ),
        f"lvremove -y {shlex.quote(old_path)}",
    ]

    # --- rebuild: sabit boyutlar önce, %100FREE en sonda (extent yutmasın) ---
    slices_ordered = [s for s in slices if not s.get("use_all_free")] + [
        s for s in slices if s.get("use_all_free")
    ]
    for sl in slices_ordered:
        dev = sl["device"]
        mnt = sl["mount"]
        fstype = sl["fstype"]
        mkfs = (
            f"mkfs.xfs -f {shlex.quote(dev)}"
            if fstype == "xfs"
            else f"mkfs.ext4 -F {shlex.quote(dev)}"
        )
        fstab = f"{dev} {mnt} {fstype} defaults 0 0"
        cmds.append(
            _lvcreate_size_cmd(
                vg_name=vg_name,
                lv_name=sl["lv_name"],
                size_gb=float(sl["size_gb"] or 0),
                use_all_free=bool(sl.get("use_all_free")),
            )
        )
        cmds.extend(
            [
                mkfs,
                f"mkdir -p {shlex.quote(mnt)}",
                f"grep -qF {shlex.quote(dev)} /etc/fstab || echo {shlex.quote(fstab)} >> /etc/fstab",
                f"mount {shlex.quote(mnt)}",
            ]
        )
        if sl["owner"]:
            cmds.append(f"chown {shlex.quote(sl['owner'])} {shlex.quote(mnt)}")
        cmds.append(f"df -h {shlex.quote(mnt)}")

    summary = (
        f"{server.hostname}: organize {source_mount} → {len(slices)} FS "
        f"(bütçe ≈{budget_gb:.1f}G, kalan VG ~{remain_gb:.1f}G · {vg_name})"
    )
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=summary,
        planned_commands=cmds,
        before_state={
            "action": "organize",
            "mount": source_mount,
            "vg_name": vg_name,
            "old_lv": old_lv,
            "old_path": old_path,
            "budget_gb": budget_gb,
            "remain_gb": remain_gb,
            "slices": slices,
            "fs": row,
            "lvm": info,
        },
        risk_notes=(
            "YIKICI: kaynak FS umount + fstab satırı silinir + lvremove -y. "
            "Yalnızca boş ve idle FS'lerde çalışır."
        ),
    )


def _build_extend(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    mount = (payload.get("mount") or "").strip()
    use_all_free = _payload_use_all_free(payload)
    add_gb = 0.0
    if not mount or mount in MOUNT_BLACKLIST:
        raise ValueError("Mount kara listede veya boş")
    if not use_all_free:
        add_gb = _parse_size_gb(payload.get("add_gb"), field="Büyüme")
        _assert_size_gb(add_gb, max_gb=MAX_ADD_GB, field="Büyüme")
    fss = list_filesystems(session, server)
    row = next((x for x in fss if x["mount"] == mount), None)
    if row is None:
        raise ValueError("Mount bulunamadı")
    if not row.get("extendable"):
        if row.get("on_root_vg"):
            allow = ", ".join(sorted(ROOT_VG_EXTEND_ALLOWLIST))
            raise ValueError(
                f"root VG üzerinde yalnızca şu mount'lar büyütülebilir: {allow}"
            )
        raise ValueError("Bu dosya sistemi sihirbazla büyütülemez (LVM/xfs/ext gerekli)")
    info = _lv_info(session, server, row["source"])
    if not info.get("lv_path"):
        raise ValueError("LVM volume bulunamadı — yalnızca LV desteklenir")
    vg_name = str(info["vg"])
    # root VG allowlist extend: operable kilidini atla; diğer VG'lerde kilit devam
    if row.get("on_root_vg"):
        if mount not in ROOT_VG_EXTEND_ALLOWLIST:
            raise ValueError("root VG mount allowlist dışı")
        vgs = list_volume_groups(session, server)
        if not any(v["name"] == vg_name for v in vgs):
            raise ValueError(f"VG bulunamadı: {vg_name}")
    else:
        _assert_vg_operable(session, server, vg_name)
    add_disks = _collect_add_disks(session, server, payload)
    disk_gb = _ensure_capacity(
        vg_free_gb=float(info["vg_free_gb"]),
        need_gb=add_gb or 1,
        add_disks=add_disks,
        use_all_free=use_all_free,
    )
    grow = "xfs_growfs" if row["fstype"] == "xfs" else "resize2fs"
    cmds: list[str] = []
    if add_disks:
        cmds.extend(_vg_extend_prep_cmds(vg_name, add_disks))
    cmds.extend(
        [
            _lvextend_size_cmd(
                lv_path=str(info["lv_path"]),
                vg_name=vg_name,
                add_gb=add_gb,
                use_all_free=use_all_free,
            ),
            f"{grow} {mount}" if row["fstype"] == "xfs" else f"{grow} {info['lv_path']}",
            f"df -h {mount}",
        ]
    )
    size_lbl = "100%FREE" if use_all_free else f"+{add_gb:g}GB"
    summary = f"{server.hostname}: {mount} {size_lbl} (VG {vg_name} boş {info['vg_free_gb']:.1f}GB"
    if add_disks:
        summary += f" + disk usable ~{disk_gb}GB / {len(add_disks)} pv"
    summary += ")"
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=summary,
        planned_commands=cmds,
        before_state={
            "action": "extend",
            "fs": row,
            "lvm": info,
            "add_gb": add_gb,
            "use_all_free": use_all_free,
            "mount": mount,
            "add_disks": add_disks,
            "disk_gb": disk_gb,
        },
        risk_notes="",
    )


def _build_create(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    vg_name = (payload.get("vg_name") or "").strip()
    lv_name = (payload.get("lv_name") or "").strip()
    mount = (payload.get("mount") or "").strip()
    use_all_free = _payload_use_all_free(payload)
    size_gb = 0.0
    fstype = (payload.get("fstype") or "xfs").strip().lower()
    owner = (payload.get("owner") or "").strip()
    if fstype not in {"xfs", "ext4"}:
        raise ValueError("fstype xfs veya ext4 olmalı")
    if not NAME_RE.match(vg_name):
        raise ValueError("VG adı geçersiz")
    if not NAME_RE.match(lv_name):
        raise ValueError("LV adı geçersiz")
    if not MOUNT_RE.match(mount) or ".." in mount.split("/") or mount in MOUNT_BLACKLIST:
        raise ValueError("Mount geçersiz veya kara listede")
    if not use_all_free:
        size_gb = _parse_size_gb(payload.get("size_gb"), field="Boyut")
        _assert_size_gb(size_gb, max_gb=MAX_CREATE_GB, field="Boyut")
    if owner and not re.match(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}(:[A-Za-z_][A-Za-z0-9_-]{0,31})?$", owner):
        raise ValueError("Owner geçersiz (user veya user:group)")

    _assert_vg_operable(session, server, vg_name)
    vgs = list_volume_groups(session, server)
    vg = next((v for v in vgs if v["name"] == vg_name), None)
    if vg is None:
        raise ValueError(f"VG bulunamadı: {vg_name}")
    add_disks = _collect_add_disks(session, server, payload)
    disk_gb = _ensure_capacity(
        vg_free_gb=float(vg["free_gb"]),
        need_gb=size_gb or 1,
        add_disks=add_disks,
        use_all_free=use_all_free,
    )

    chk = run_ssh(
        session,
        server,
        f"if mountpoint -q {shlex.quote(mount)} 2>/dev/null; then echo MOUNTED; "
        f"elif [ -e {shlex.quote(mount)} ] && [ ! -d {shlex.quote(mount)} ]; then echo NOTDIR; "
        f"elif [ -d {shlex.quote(mount)} ] && [ -n \"$(ls -A {shlex.quote(mount)} 2>/dev/null)\" ]; then echo NONEMPTY; "
        f"else echo OK; fi; "
        f"lvs {shlex.quote(vg_name)}/{shlex.quote(lv_name)} >/dev/null 2>&1 && echo LVEXISTS || true",
        timeout=20,
    )
    out = chk.stdout
    if "MOUNTED" in out:
        raise ValueError("Mount noktası zaten bağlı")
    if "NOTDIR" in out:
        raise ValueError("Mount yolu dizin değil")
    if "NONEMPTY" in out:
        raise ValueError("Mount dizini boş değil")
    if "LVEXISTS" in out:
        raise ValueError("LV zaten var")

    dev = f"/dev/{vg_name}/{lv_name}"
    mkfs = f"mkfs.xfs -f {shlex.quote(dev)}" if fstype == "xfs" else f"mkfs.ext4 -F {shlex.quote(dev)}"
    fstab = f"{dev} {mount} {fstype} defaults 0 0"
    cmds: list[str] = []
    if add_disks:
        cmds.extend(_vg_extend_prep_cmds(vg_name, add_disks))
    cmds.extend(
        [
            _lvcreate_size_cmd(
                vg_name=vg_name,
                lv_name=lv_name,
                size_gb=size_gb,
                use_all_free=use_all_free,
            ),
            mkfs,
            f"mkdir -p {shlex.quote(mount)}",
            f"cp -a /etc/fstab /etc/fstab.bak.dropt.$(date +%s)",
            f"grep -qF {shlex.quote(dev)} /etc/fstab || echo {shlex.quote(fstab)} >> /etc/fstab",
            f"mount {shlex.quote(mount)}",
        ]
    )
    if owner:
        cmds.append(f"chown {shlex.quote(owner)} {shlex.quote(mount)}")
    cmds.append(f"df -h {shlex.quote(mount)}")
    size_lbl = "100%FREE" if use_all_free else f"{size_gb:g}GB"
    summary = (
        f"{server.hostname}: {mount} oluşturulacak "
        f"({size_lbl} {fstype} · {vg_name}/{lv_name}"
    )
    if add_disks:
        summary += f" · +usable ~{disk_gb}GB / {len(add_disks)} pv"
    summary += ")"
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=summary,
        planned_commands=cmds,
        before_state={
            "action": "create",
            "vg_name": vg_name,
            "lv_name": lv_name,
            "mount": mount,
            "size_gb": size_gb,
            "use_all_free": use_all_free,
            "fstype": fstype,
            "owner": owner,
            "device": dev,
            "vg_free_gb": vg["free_gb"],
            "add_disks": add_disks,
            "disk_gb": disk_gb,
        },
        risk_notes="",
    )


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    if len(servers) > 1:
        for server in servers:
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: FileSystem Management tek sunucuda çalışır",
                    error="Aynı anda yalnızca 1 sunucu seçilebilir",
                )
            )
        return plans

    for server in servers:
        try:
            if action == "extend":
                plans.append(_build_extend(session, server, payload))
            elif action == "create":
                plans.append(_build_create(session, server, payload))
            elif action == "organize":
                plans.append(_build_organize(session, server, payload))
            else:
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
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
    _ = (action, payload)
    if not plan.ok:
        return False, plan.before_state, "", plan.error
    sid = int(server.id)  # type: ignore[arg-type]
    out: list[str] = []
    err: list[str] = []
    runnable = [
        str(c)
        for c in plan.planned_commands
        if str(c).strip() and not str(c).strip().startswith("#")
    ]
    total = max(1, len(runnable))
    step = 0

    def _progress(done: int, label: str) -> None:
        if not job_id:
            return
        from app.services.job_events import publish_job_progress

        publish_job_progress(
            int(job_id),
            done=done,
            total=total,
            label=label,
            hostname=server.hostname,
            session=session,
        )

    if job_id:
        _progress(0, "başlıyor")

    for cmd in plan.planned_commands:
        raw = str(cmd)
        if not raw.strip() or raw.strip().startswith("#"):
            out.append(raw.strip())
            continue
        step += 1
        # Konsolda hangi adımın çalıştığı görünsün
        preview = raw.strip().splitlines()[0][:160]
        out.append(f"\n--- step {step}/{total}: {preview} ---")
        _progress(step - 1, f"çalışıyor: {preview}")
        r = run_ssh(session, server, raw, timeout=180)
        if r.stdout:
            out.append(r.stdout.rstrip())
            if job_id:
                from app.services.job_events import publish_job_event

                publish_job_event(
                    int(job_id),
                    {
                        "type": "stdout",
                        "hostname": server.hostname,
                        "text": (r.stdout or "")[:4000],
                    },
                )
        if r.stderr:
            out.append((r.stderr or "").rstrip())
            err.append(r.stderr)
            if job_id:
                from app.services.job_events import publish_job_event

                publish_job_event(
                    int(job_id),
                    {
                        "type": "stderr",
                        "hostname": server.hostname,
                        "text": (r.stderr or "")[:2000],
                    },
                )
        if not r.ok and not raw.lstrip().startswith("df "):
            fail_msg = (
                f"[FAILED] step {step}/{total} exit={r.exit_code}: {preview}\n"
                f"{(r.stderr or r.stdout or '').strip() or '(stderr/stdout boş)'}"
            )
            out.append(fail_msg)
            err.append(fail_msg)
            _progress(step, f"hata: {preview}")
            invalidate_cached_inventory(sid)
            try:
                from app.modules import asm

                asm.invalidate_cached_scan(sid)
            except Exception:
                pass
            return False, plan.before_state, "\n".join(out), "\n".join(err)
        _progress(step, f"bitti: {preview}")
    mount = plan.before_state.get("mount", "")
    action_name = str(plan.before_state.get("action") or "")
    if action_name == "organize":
        slices = plan.before_state.get("slices") or []
        dfs: list[str] = []
        for sl in slices:
            m = (sl or {}).get("mount") if isinstance(sl, dict) else ""
            if m:
                dfr = run_ssh(session, server, f"df -PT {shlex.quote(str(m))} | tail -1", timeout=15)
                dfs.append(f"{m}: {(dfr.stdout or '').strip()}")
        after = {
            **plan.before_state,
            "df_after": "\n".join(dfs),
            "checklist": [
                "Yeni mount'ları df ile doğrula",
                "VG free (kalan) kontrol et",
                "fstab backup .bak.dropt.*",
            ],
        }
    else:
        df = run_ssh(session, server, f"df -h {shlex.quote(str(mount))} | tail -1", timeout=15)
        after = {
            **plan.before_state,
            "df_after": df.stdout.strip(),
            "checklist": (
                ["Mount ve df doğrula", "Uygulama ekibine yeni alanı bildir"]
                if action_name == "create"
                else ["df ile büyümeyi doğrula"]
            ),
        }
    refresh_inventory_cache_once(session, server)
    if job_id:
        _progress(total, "tamam")
    return True, after, "\n".join(out), "\n".join(err)
