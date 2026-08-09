from __future__ import annotations

import json
import re
import shlex
from typing import Any

from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.models.job import Job, JobRun, JobRunStatus
from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.machine_type import asm_disk_mode, effective_machine_type
from app.services.target_ssh import run_ssh

ACTION_TITLES = {"add_disk": "ASM disk ekle"}

# ASM label: ASM_<PREFIX>_<NNN> ≤ 25 → prefix en fazla 17 (3 haneli indeks)
ALIAS_PREFIX_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,16}$")
ASM_NAME_MAX_LEN = 25
TWO_TB = 2 * 1024**4  # 2 TiB — fdisk vs parted eşiği

_SCAN_TTL_SEC = 60 * 60 * 12


def job_summary(action: str, payload: dict[str, Any]) -> str:
    disks = payload.get("disks") or []
    prefix = payload.get("alias_prefix") or payload.get("alias") or ""
    return f"{ACTION_TITLES.get(action, action)}: {prefix} ×{len(disks) or 1}"


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _cache_key(server_id: int, mode: str) -> str:
    return f"asm:scan:v2:{mode}:{server_id}"


def get_cached_scan(server_id: int, mode: str) -> dict[str, Any] | None:
    try:
        raw = _redis().get(_cache_key(server_id, mode))
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, list):
            return {"disks": data, "groups": [], "recent": []}
        if isinstance(data, dict) and isinstance(data.get("disks"), list):
            groups = data.get("groups") if isinstance(data.get("groups"), list) else []
            return {
                "disks": data["disks"],
                "groups": groups,
                "recent": data.get("recent") if isinstance(data.get("recent"), list) else [],
            }
        return None
    except Exception:
        return None


def set_cached_scan(
    server_id: int,
    mode: str,
    disks: list[dict[str, Any]],
    recent: list[dict[str, Any]] | None = None,
    groups: list[dict[str, Any]] | None = None,
) -> None:
    try:
        payload = {
            "disks": disks,
            "groups": groups or [],
            "recent": recent or [],
        }
        _redis().setex(_cache_key(server_id, mode), _SCAN_TTL_SEC, json.dumps(payload))
    except Exception:
        pass


def invalidate_cached_scan(server_id: int, mode: str | None = None) -> None:
    try:
        r = _redis()
        if mode:
            r.delete(_cache_key(server_id, mode))
        else:
            r.delete(_cache_key(server_id, "multipath"))
            r.delete(_cache_key(server_id, "sd"))
    except Exception:
        pass


def refresh_scan_cache_once(session: Session, server: TargetServer) -> None:
    """Apply sonrası eski disklerin listede kalmaması için cache 1 kez taze tara."""
    try:
        sid = int(server.id)  # type: ignore[arg-type]
        invalidate_cached_scan(sid)
        scan_disks(session, server, refresh=False)
    except Exception:
        pass


_LIST_SCRIPT = r"""
set +e
python3 - <<'PY'
import json, os, re, subprocess

def run(cmd):
    try:
        # RHEL8 python3=3.6: text= yok → universal_newlines (3.6+ / 3.7+ text alias)
        return subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""

lv_names=set()
for line in run(["lvs","--noheadings","-o","lv_dm_path,lv_name"]).splitlines():
    for p in line.split():
        p=p.strip().lstrip("/dev/mapper/")
        if p: lv_names.add(p)
for line in run(["lvs","--noheadings","-o","vg_name,lv_name"]).splitlines():
    parts=line.split()
    if len(parts)>=2:
        vg,lv=parts[0],parts[1]
        lv_names.add(f"{vg}-{lv}")
        lv_names.add(f"{vg.replace('-','--')}-{lv.replace('-','--')}")

# LVM PV set (parent + partition: /dev/mapper/test01, test01p1, …)
pvs=set()
for line in run(["pvs","--noheadings","-o","pv_name"]).splitlines():
    p=line.strip()
    if not p:
        continue
    pvs.add(p)
    pvs.add(p.split("/")[-1])

# /dev/mapper adları — partition child tespiti (test01p1, test011, mpatha1)
try:
    mapper_names=set(os.listdir("/dev/mapper"))
except Exception:
    mapper_names=set()

def has_mapper_partition(parent: str) -> bool:
    for n in mapper_names:
        if n == parent:
            continue
        if re.match(r"^" + re.escape(parent) + r"p?\d+$", n):
            return True
    return False

def pv_uses_disk(name: str) -> bool:
    # Parent veya onun partition i PV ise True
    if name in pvs or f"/dev/mapper/{name}" in pvs or f"/dev/{name}" in pvs:
        return True
    for p in pvs:
        base=p.split("/")[-1]
        if re.match(r"^" + re.escape(name) + r"p?\d+$", base):
            return True
    return False

# lsblk: part child / fstype / mount
raw=run(["lsblk","-J","-b","-o","NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,PKNAME"])
try:
    tree=json.loads(raw or "{}")
except Exception:
    tree={"blockdevices":[]}

def walk(nodes, acc):
    for n in nodes or []:
        name=(n.get("name") or "").strip()
        if name:
            acc[name]=n
        walk(n.get("children") or [], acc)

by_name={}
walk(tree.get("blockdevices") or [], by_name)

def has_part_children(node):
    for c in node.get("children") or []:
        if (c.get("type") or "")=="part":
            return True
        if has_part_children(c):
            return True
    return False

def disk_in_use(name: str) -> bool:
    if has_mapper_partition(name):
        return True
    if pv_uses_disk(name):
        return True
    node=by_name.get(name)
    if node:
        if has_part_children(node):
            return True
        if node.get("fstype") or node.get("mountpoint"):
            return True
    # holders: dm/LVM bağlıysa sysfs
    for base in (f"/sys/block/{name}/holders", f"/sys/devices/virtual/block/{name}/holders"):
        try:
            if os.path.isdir(base) and os.listdir(base):
                return True
        except Exception:
            pass
    return False

asm=set()
for line in run(["oracleasm","listdisks"]).splitlines():
    x=line.strip()
    if x: asm.add(x)

out=[]
mp=run(["multipath","-ll"])
cur=None
for line in mp.splitlines():
    m=re.match(r"^(\S+)\s+\(([^)]+)\)", line)
    if m:
        cur={"name":m.group(1),"wwid":m.group(2),"size":"","size_bytes":0}
        out.append(cur)
        continue
    if cur and "size=" in line:
        sm=re.search(r"size=(\S+)", line)
        if sm:
            cur["size"]=sm.group(1)
            s=sm.group(1).upper().replace(",","")
            mm=re.match(r"([0-9.]+)([KMGTP])", s)
            if mm:
                n=float(mm.group(1)); u=mm.group(2)
                mul={"K":1024,"M":1024**2,"G":1024**3,"T":1024**4,"P":1024**5}[u]
                cur["size_bytes"]=int(n*mul)

final=[]
for d in out:
    name=d.get("name") or ""
    wwid=d.get("wwid") or ""
    if not wwid:
        continue
    if name in lv_names:
        continue
    # Partition satırları (mpatha1 / aliasp1) — parent zaten kontrol edilir
    if re.search(r"(mpath[a-z]+)\d+$", name, re.I):
        continue
    if re.search(r"p\d+$", name):
        continue
    if name.lower() in {"root","swap","home","var","usr"}:
        continue
    # Partition / PV / FS / mount / holders → free listesine girme
    if disk_in_use(name):
        continue
    usable = name not in asm and not any(name.upper()==a or a in name.upper() for a in asm)
    final.append({
        "alias": name,
        "wwid": wwid,
        "size": d.get("size") or "",
        "size_bytes": d.get("size_bytes") or 0,
        "usable": bool(usable),
        "device": f"/dev/mapper/{name}",
        "is_lv": False,
    })
print(json.dumps(final))
PY
"""

# Sanal: partitionsuz / kullanılmayan sd|vd|xvd diskler
_LIST_SCRIPT_SD = r"""
set +e
python3 - <<'PY'
import json, re, subprocess

def run(cmd):
    try:
        # RHEL8 python3=3.6: text= yok → universal_newlines (3.6+ / 3.7+ text alias)
        return subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""

# LVM PV set
pvs=set()
for line in run(["pvs","--noheadings","-o","pv_name"]).splitlines():
    p=line.strip()
    if p:
        pvs.add(p)
        pvs.add(p.split("/")[-1])

# multipath path üyeleri (sd*) — çift liste olmasın
mp_paths=set()
for line in run(["multipath","-ll"]).splitlines():
    for m in re.finditer(r"\b((?:sd|vd|xvd)[a-z]+)\b", line):
        mp_paths.add(m.group(1))

asm=set()
for line in run(["oracleasm","listdisks"]).splitlines():
    x=line.strip()
    if x: asm.add(x.upper())

# lsblk tree
raw=run(["lsblk","-J","-b","-o","NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT"])
try:
    tree=json.loads(raw or "{}")
except Exception:
    tree={"blockdevices":[]}

def has_part_children(node):
    for c in node.get("children") or []:
        if (c.get("type") or "")=="part":
            return True
        if has_part_children(c):
            return True
    return False

final=[]
for d in tree.get("blockdevices") or []:
    name=(d.get("name") or "").strip()
    typ=(d.get("type") or "").strip()
    if typ!="disk":
        continue
    if not re.match(r"^(sd|vd|xvd)[a-z]+$", name):
        continue
    if name in mp_paths:
        continue
    if has_part_children(d):
        continue
    if d.get("fstype") or d.get("mountpoint"):
        continue
    dev=f"/dev/{name}"
    if dev in pvs or name in pvs:
        continue
    # boyut
    try:
        size_b=int(d.get("size") or 0)
    except Exception:
        size_b=0
    size=""
    if size_b>=1024**4:
        size=f"{size_b/1024**4:.1f}T"
    elif size_b>=1024**3:
        size=f"{size_b/1024**3:.1f}G"
    elif size_b>=1024**2:
        size=f"{size_b/1024**2:.0f}M"
    else:
        size=str(size_b)
    # serial (opsiyonel kimlik)
    serial=(run(["lsblk","-ndo","SERIAL",dev]) or "").strip()
    wwid=f"SERIAL:{serial}" if serial else f"DEV:{name}"
    usable=True
    # oracleasm isim çakışması kaba kontrol
    if any(name.upper() in a or a.endswith(name.upper()) for a in asm):
        usable=False
    final.append({
        "alias": name,
        "wwid": wwid,
        "size": size,
        "size_bytes": size_b,
        "usable": usable,
        "device": dev,
        "is_lv": False,
        "mode": "sd",
    })
print(json.dumps(final))
PY
"""

_LISTDISKS_MARK = "__LISTDISKS__"


def normalize_asm_group_label(name: str) -> str | None:
    """
    oracleasm listdisks adını uniq grup etiketine indirger.

    Örnekler:
      data1 / ASM_DATA_001 / ASM_DATA_WWID2 → DATA
      ASM_REDO_01 / ASMARCH01 → REDO / ARCH
      ASM_DATA_01A / ASM_REDO_01B → DATA_A / REDO_B
      ASM_DATA_01A_A1B2C3D4 → DATA_A  (WWID son haneler atılır)
      ASMNEWDATA01 → NEWDATA
      ASM_FG2_DATA01 / ASM_MSR1_REDO02 → FG2_DATA / MSR1_REDO
      ASM_HUAW_CONF01 / ASM_HIT_REDO01 → HUAW_CONF / HIT_REDO
    """
    s = (name or "").strip().upper()
    if not s:
        return None
    # mapper/path kırıntısı gelirse basename
    if "/" in s:
        s = s.rsplit("/", 1)[-1]

    if s.startswith("ASM_"):
        s = s[4:]
    elif s.startswith("ASM") and len(s) > 3 and s[3].isalpha():
        s = s[3:]

    s = s.strip("_")
    if not s:
        return None

    # Literal WWID kuyruğu: _WWID, _WWID2
    s = re.sub(r"_WWID\d*$", "", s, flags=re.IGNORECASE).strip("_")
    # Hex WWID kuyruğu (genelde son 8+): _A1B2C3D4
    while True:
        m = re.match(r"^(.+)_([0-9A-F]{6,16})$", s)
        if not m:
            break
        s = m.group(1).strip("_")
    if not s:
        return None

    # BODY + sıra + kutu harfi → BODY_BOX  (DATA_01A, DATA01A, FG2_DATA_01A)
    m = re.match(r"^(.+)_(\d{1,4})([A-Z])$", s)
    if not m:
        m = re.match(r"^(.+?)(\d{1,4})([A-Z])$", s)
    if m:
        body = m.group(1).strip("_")
        box = m.group(3)
        # BODY sonunda tek harf kutusu zaten varsa (DATA_A) dokunma — bu dal sıra ister
        if body:
            return f"{body}_{box}"
        return box

    # BODY + sıra → BODY  (FG2_DATA01, MSR1_REDO02, NEWDATA01, DATA_001, data1)
    m = re.match(r"^(.+?)_?(\d+)$", s)
    if m:
        body = m.group(1).strip("_")
        return body or None

    # Zaten temiz: DATA, DATA_A, MSR1_REDO, HUAW_CONF
    return s or None


def group_asm_disk_names(names: list[str]) -> list[dict[str, Any]]:
    """listdisks satırlarından uniq grup listesi (label, count, samples)."""
    buckets: dict[str, dict[str, Any]] = {}
    for raw in names:
        label = normalize_asm_group_label(raw)
        if not label:
            continue
        # Alias öneki alanı ile uyum (max 17)
        if len(label) > 17:
            label = label[:17]
        if not ALIAS_PREFIX_RE.match(label):
            continue
        bucket = buckets.get(label)
        if bucket is None:
            bucket = {"label": label, "count": 0, "samples": []}
            buckets[label] = bucket
        bucket["count"] += 1
        samples: list[str] = bucket["samples"]
        if len(samples) < 3 and raw.strip() and raw.strip() not in samples:
            samples.append(raw.strip())
    return sorted(buckets.values(), key=lambda x: x["label"])


def merge_asm_groups(group_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Cluster: node gruplarını label bazında birleştir (count max — aynı disk iki node)."""
    buckets: dict[str, dict[str, Any]] = {}
    for groups in group_lists:
        for g in groups or []:
            label = str(g.get("label") or "").strip().upper()
            if not label:
                continue
            count = int(g.get("count") or 0)
            samples = [str(x) for x in (g.get("samples") or []) if x][:3]
            cur = buckets.get(label)
            if cur is None:
                buckets[label] = {"label": label, "count": count, "samples": samples}
            else:
                # Aynı ASM diskleri cluster'da her iki node'da görünür → max al
                cur["count"] = max(int(cur["count"]), count)
                for s in samples:
                    if len(cur["samples"]) >= 3:
                        break
                    if s not in cur["samples"]:
                        cur["samples"].append(s)
    return sorted(buckets.values(), key=lambda x: x["label"])


def _parse_listdisks_stdout(stdout: str) -> list[str]:
    lines = (stdout or "").splitlines()
    names: list[str] = []
    after = False
    for line in lines:
        if line.strip() == _LISTDISKS_MARK:
            after = True
            continue
        if not after:
            continue
        name = line.strip()
        if name and not name.startswith("[") and not name.startswith("{"):
            names.append(name)
    # Mark yoksa (eski çıktı) — boş bırak; gruplar için ayrıca SSH yapılabilir
    return names


def scan_disks(
    session: Session,
    server: TargetServer,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    physical/override → multipath -ll
    virtual → partitionsuz /dev/sd|vd|xvd
    groups: oracleasm listdisks → uniq ASM label grupları
    """
    sid = int(server.id)  # type: ignore[arg-type]
    mode = asm_disk_mode(server)
    mtype = effective_machine_type(server)

    if not refresh:
        cached = get_cached_scan(sid, mode)
        if cached is not None:
            return {
                "disks": cached["disks"],
                "groups": cached.get("groups") or [],
                "recent": [],
                "cached": True,
                "server_id": sid,
                "disk_mode": mode,
                "machine_type": mtype,
            }

    list_script = _LIST_SCRIPT if mode == "multipath" else _LIST_SCRIPT_SD
    listdisks_tail = f"\necho {_LISTDISKS_MARK}\noracleasm listdisks 2>/dev/null || true\n"
    if refresh:
        script = (
            "set +e\n"
            'for host in /sys/class/scsi_host/host*; do echo "- - -" > "$host/scan" 2>/dev/null; done\n'
            "sleep 1\n"
            + list_script
            + listdisks_tail
        )
    else:
        script = "set +e\n" + list_script + listdisks_tail

    r = run_ssh(session, server, script, timeout=120 if refresh else 60)
    disks: list[dict[str, Any]] = []
    try:
        for line in reversed((r.stdout or "").splitlines()):
            line = line.strip()
            if not line or line == _LISTDISKS_MARK:
                continue
            if line.startswith("RECENT_JSON:"):
                continue
            if line.startswith("[") or line.startswith("{"):
                data = json.loads(line)
                if isinstance(data, list):
                    disks = data
                    for d in disks:
                        d.setdefault("mode", mode)
                break
    except json.JSONDecodeError:
        disks = []
    groups = group_asm_disk_names(_parse_listdisks_stdout(r.stdout or ""))
    set_cached_scan(sid, mode, disks, recent=[], groups=groups)
    return {
        "disks": disks,
        "groups": groups,
        "recent": [],
        "cached": False,
        "server_id": sid,
        "disk_mode": mode,
        "machine_type": mtype,
    }


def _normalize_disks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    disks = payload.get("disks")
    if isinstance(disks, list) and disks:
        out = []
        for d in disks:
            wwid = str(d.get("wwid") or "").strip()
            if not wwid:
                raise ValueError("Her disk için WWID zorunlu")
            out.append(
                {
                    "wwid": wwid,
                    "size_bytes": int(d.get("size_bytes") or 0),
                    "size": str(d.get("size") or ""),
                    "source_alias": str(d.get("alias") or d.get("source_alias") or ""),
                    "device": str(d.get("device") or ""),
                }
            )
        return out
    wwid = (payload.get("wwid") or "").strip()
    if not wwid:
        raise ValueError("En az bir disk seçin")
    return [
        {
            "wwid": wwid,
            "size_bytes": int(payload.get("size_bytes") or 0),
            "size": "",
            "source_alias": str(payload.get("alias") or ""),
            "device": str(payload.get("device") or ""),
        }
    ]


def _validate_common(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    alias_prefix = (payload.get("alias_prefix") or payload.get("alias") or "").strip()
    if not ALIAS_PREFIX_RE.match(alias_prefix):
        raise ValueError(
            "Alias öneki geçersiz (örn. DATA; harf ile başlar, en fazla 17 karakter; "
            f"ASM_{{öneki}}_001 ≤ {ASM_NAME_MAX_LEN} karakter)"
        )
    return alias_prefix, _normalize_disks(payload)


def format_seq_index(index: int) -> str:
    """001, 002, …; 1000+ için doğal genişlik."""
    if index < 1:
        raise ValueError("ASM sıra indeksi 1'den küçük olamaz")
    if index < 1000:
        return f"{index:03d}"
    return str(index)


def sequential_aliases(prefix: str, index: int) -> tuple[str, str]:
    """(multipath_alias, asm_name) → DATA_004, ASM_DATA_004."""
    seq = format_seq_index(index)
    mp_alias = f"{prefix}_{seq}"
    asm_name = f"ASM_{prefix}_{seq}".upper()
    if len(asm_name) > ASM_NAME_MAX_LEN:
        raise ValueError(
            f"ASM adı {ASM_NAME_MAX_LEN} karakter sınırını aşıyor ({len(asm_name)}): {asm_name}. "
            "Daha kısa alias öneki kullanın."
        )
    return mp_alias, asm_name


def _seq_index_patterns(prefix: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    p = re.escape(prefix)
    asm_re = re.compile(rf"^ASM_{p}_(\d+)$", re.IGNORECASE)
    # /dev/mapper/DATA_001 veya DATA_001p1
    mp_re = re.compile(rf"^{p}_(\d+)(?:p\d+)?$", re.IGNORECASE)
    return asm_re, mp_re


def max_seq_index_from_lines(lines: list[str], prefix: str) -> int:
    """Mevcut isimlerden max indeks (gap'ler atlanır: 001+003 → 3)."""
    asm_re, mp_re = _seq_index_patterns(prefix)
    max_idx = 0
    for line in lines:
        s = (line or "").strip()
        if not s or s == "__MAPPER__":
            continue
        m = asm_re.match(s) or mp_re.match(s)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx


def _ssh_seq_inventory(session: Session, server: TargetServer) -> list[str]:
    script = (
        "set +e\n"
        "oracleasm listdisks 2>/dev/null\n"
        "echo __MAPPER__\n"
        "ls -1 /dev/mapper 2>/dev/null\n"
    )
    r = run_ssh(session, server, script, timeout=45)
    return (r.stdout or "").splitlines()


def max_seq_index_for_servers(
    session: Session,
    servers: list[TargetServer],
    prefix: str,
) -> int:
    """Tüm hedef sunuculardaki ASM_/mapper adlarından global max indeks."""
    if not servers:
        return 0
    if not ALIAS_PREFIX_RE.match(prefix):
        raise ValueError("Alias öneki geçersiz (örn. DATA)")
    max_idx = 0
    errors: list[str] = []
    for server in servers:
        try:
            lines = _ssh_seq_inventory(session, server)
            max_idx = max(max_idx, max_seq_index_from_lines(lines, prefix))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{server.hostname}: {exc}")
    if errors and max_idx == 0 and len(errors) == len(servers):
        raise ValueError("ASM sıra numarası alınamadı: " + "; ".join(errors))
    return max_idx


def partition_suffix(mapper_alias: str) -> str:
    """Son karakter harf → 1; rakam → p1."""
    if not mapper_alias:
        raise ValueError("Boş mapper alias")
    last = mapper_alias[-1]
    if last.isalpha():
        return "1"
    if last.isdigit():
        return "p1"
    return "1"


def partition_path(mapper_alias: str) -> str:
    return f"/dev/mapper/{mapper_alias}{partition_suffix(mapper_alias)}"


def sd_partition_path(device: str) -> str:
    """ /dev/sdc → /dev/sdc1 ; /dev/nvme0n1 → /dev/nvme0n1p1 """
    base = device.rstrip("/")
    name = base.split("/")[-1]
    return f"{base}{partition_suffix(name)}"


def is_rhel9(server: TargetServer) -> bool:
    """RHEL 9.x (9.4/9.5/…); release alt sürümü önemsiz — major 9 yeterli."""
    text = (server.os_pretty or "").strip().lower()
    if not text:
        return False
    if re.search(r"\bel9\b", text):
        return True
    if "red hat" in text or "rhel" in text or "enterprise linux" in text:
        # "red hat enterprise linux 9.7" / "rhel 9" / "9 (plow)"
        if re.search(r"\b9(?:\.\d+)?\b", text):
            return True
    return bool(re.search(r"\brhel\s*9(?:\.\d+)?\b", text))


def asm_verify_path(asm_name: str, server: TargetServer) -> str:
    """RHEL 9 → by-label; diğerleri → oracleasm/disks."""
    name = (asm_name or "").strip()
    if is_rhel9(server):
        return f"/dev/disk/by-label/{name}"
    return f"/dev/oracleasm/disks/{name}"


def _sd_disk_name(d: dict[str, Any]) -> str:
    alias = str(d.get("source_alias") or d.get("alias") or "").strip()
    if alias and re.match(r"^(sd|vd|xvd)[a-z]+$", alias):
        return alias
    wwid = str(d.get("wwid") or "")
    if wwid.startswith("DEV:"):
        return wwid[4:]
    device = str(d.get("device") or "")
    if device.startswith("/dev/"):
        return device.split("/")[-1]
    raise ValueError(f"Sanal disk adı çözülemedi: {d}")


def _build_disk_specs(
    alias_prefix: str,
    disks: list[dict[str, Any]],
    mode: str,
    *,
    start_index: int,
) -> list[dict[str, Any]]:
    specs = []
    for i, d in enumerate(disks):
        size_b = int(d.get("size_bytes") or 0)
        mp_alias, asm_name = sequential_aliases(alias_prefix, start_index + i)
        if mode == "multipath":
            specs.append(
                {
                    **d,
                    "disk_mode": mode,
                    "seq_index": start_index + i,
                    "multipath_alias": mp_alias,
                    "base_device": f"/dev/mapper/{mp_alias}",
                    "asm_name": asm_name,
                    "partition_path": partition_path(mp_alias),
                    "partition_tool": "parted" if size_b >= TWO_TB else "fdisk",
                }
            )
        else:
            name = _sd_disk_name(d)
            base = str(d.get("device") or f"/dev/{name}")
            specs.append(
                {
                    **d,
                    "disk_mode": mode,
                    "seq_index": start_index + i,
                    "source_alias": name,
                    "multipath_alias": mp_alias,
                    "base_device": base,
                    "asm_name": asm_name,
                    "partition_path": sd_partition_path(base),
                    "partition_tool": "parted" if size_b >= TWO_TB else "fdisk",
                }
            )
    return specs


def _wwids_from_scan(session: Session, server: TargetServer, *, refresh: bool) -> set[str]:
    """Yalnızca ASM için 'boş' görünen diskler (UI listesi). Cluster varlık kontrolünde kullanma."""
    result = scan_disks(session, server, refresh=refresh)
    out: set[str] = set()
    for d in result.get("disks") or []:
        wwid = str(d.get("wwid") or "").strip()
        if wwid:
            out.add(wwid)
    return out


# multipath -ll tüm WWID'ler (partition/ASM sonrası da görünür) — RHEL8 py3.6 uyumlu
_MPATH_PRESENT_WWIDS_SCRIPT = r"""
set +e
python3 - <<'PY'
import re, subprocess
try:
    mp = subprocess.check_output(
        ["multipath", "-ll"], universal_newlines=True, stderr=subprocess.DEVNULL
    )
except Exception:
    mp = ""
for line in mp.splitlines():
    m = re.match(r"^(\S+)\s+\(([^)]+)\)", line)
    if m:
        print(m.group(2).strip())
PY
"""

# sanal: tüm sd|vd|xvd kimlikleri (in-use filtresi yok)
_SD_PRESENT_WWIDS_SCRIPT = r"""
set +e
python3 - <<'PY'
import json, re, subprocess

def run(cmd):
    try:
        return subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""

raw = run(["lsblk", "-J", "-b", "-o", "NAME,TYPE,SERIAL"])
try:
    tree = json.loads(raw or "{}")
except Exception:
    tree = {"blockdevices": []}
for d in tree.get("blockdevices") or []:
    name = (d.get("name") or "").strip()
    typ = (d.get("type") or "").strip()
    if typ != "disk":
        continue
    if not re.match(r"^(sd|vd|xvd)[a-z]+$", name):
        continue
    serial = (d.get("serial") or "").strip()
    if serial:
        print("SERIAL:%s" % serial)
    print("DEV:%s" % name)
PY
"""


def _wwids_present_on_server(session: Session, server: TargetServer) -> set[str]:
    """
    Diskin node'da görünür olup olmadığı (free/ASM fark etmez).
    Primary createdisk sonrası free-list boşalsa bile multipath WWID burada kalır.
    """
    mode = asm_disk_mode(server)
    script = _MPATH_PRESENT_WWIDS_SCRIPT if mode == "multipath" else _SD_PRESENT_WWIDS_SCRIPT
    r = run_ssh(session, server, script, timeout=60)
    return {ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()}


def _validate_cluster_disks(
    session: Session,
    servers: list[TargetServer],
    disks: list[dict[str, Any]],
    *,
    refresh: bool = True,
) -> None:
    """Her WWID tüm cluster node'larında multipath/lsblk'te görünmeli (in-use olsa da)."""
    _ = refresh  # varlık kontrolü her zaman canlı; free-cache kullanılmaz
    if len(servers) <= 1:
        return
    if len(servers) > 2:
        raise ValueError("ASM cluster en fazla 2 sunucu destekler")
    wwid_sets: dict[int, set[str]] = {}
    for server in servers:
        wwid_sets[int(server.id)] = _wwids_present_on_server(session, server)  # type: ignore[arg-type]
    for d in disks:
        wwid = str(d.get("wwid") or "").strip()
        if not wwid:
            continue
        missing = [s.hostname for s in servers if wwid not in wwid_sets.get(int(s.id), set())]  # type: ignore[arg-type]
        if missing:
            raise ValueError(
                f"WWID '{wwid}' şu sunucularda bulunamadı: {', '.join(missing)}. İşlem iptal edildi."
            )


def _load_job_servers(session: Session, job_id: int) -> list[TargetServer]:
    job = session.get(Job, job_id)
    if not job or not job.server_ids:
        return []
    ids = [int(i) for i in job.server_ids]
    rows = session.exec(select(TargetServer).where(col(TargetServer.id).in_(ids))).all()
    by_id = {int(s.id): s for s in rows}  # type: ignore[arg-type]
    return [by_id[i] for i in ids if i in by_id]


def _ordered_servers(servers: list[TargetServer], payload: dict[str, Any]) -> list[tuple[TargetServer, str]]:
    if len(servers) == 1:
        return [(servers[0], "single")]
    primary_id = int(payload.get("primary_server_id") or 0)
    by_id = {s.id: s for s in servers}
    if primary_id not in by_id:
        primary_id = servers[0].id  # type: ignore[assignment]
    primary = by_id[primary_id]
    peers = [s for s in servers if s.id != primary_id]
    return [(primary, "primary"), *[(p, "peer") for p in peers]]


def _preview_multipath_block(wwid: str, alias: str) -> str:
    return f'multipath {{\n\twwid {wwid}\n\talias {alias}\n}}'


def build_plans(session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]) -> list[HostPlan]:
    plans: list[HostPlan] = []
    try:
        if action != "add_disk":
            raise ValueError(f"Bilinmeyen aksiyon: {action}")
        alias_prefix, disks = _validate_common(payload)
        if len(servers) > 2:
            raise ValueError("ASM cluster en fazla 2 sunucu destekler")
        if len(servers) > 1:
            _validate_cluster_disks(session, servers, disks, refresh=True)
        modes = {asm_disk_mode(s) for s in servers}
        if len(modes) > 1:
            raise ValueError(
                "Cluster'da karışık fiziksel (multipath) / sanal (/dev/sd) ASM modu desteklenmiyor"
            )
        mode = modes.pop() if modes else "multipath"
        ordered = _ordered_servers(servers, payload)
        primary_id = ordered[0][0].id
        cluster = len(ordered) > 1
        used_max = max_seq_index_for_servers(session, servers, alias_prefix)
        start_index = used_max + 1
        disk_specs = _build_disk_specs(alias_prefix, disks, mode, start_index=start_index)

        for server, role in ordered:
            host_mode = asm_disk_mode(server)
            if host_mode == "multipath":
                if role in {"single", "primary"}:
                    cmds: list[str] = [
                        "# /etc/multipath.conf → multipaths { … } içine:",
                    ]
                    for spec in disk_specs:
                        cmds.append(_preview_multipath_block(spec["wwid"], spec["multipath_alias"]))
                    cmds.append("service multipathd reload")
                    for spec in disk_specs:
                        cmds.append(
                            f"# partition ({spec['partition_tool']}) → {spec['partition_path']}"
                        )
                        cmds.append(
                            f"oracleasm createdisk {spec['asm_name']} {spec['partition_path']}"
                        )
                    for spec in disk_specs:
                        cmds.append(f"ls -lL {asm_verify_path(spec['asm_name'], server)}")
                    summary = (
                        f"{server.hostname}: {len(disk_specs)} ASM disk [multipath] "
                        f"(ASM_{alias_prefix.upper()}_{format_seq_index(start_index)}"
                        + (
                            f"…{format_seq_index(start_index + len(disk_specs) - 1)}"
                            if len(disk_specs) > 1
                            else ""
                        )
                        + ")"
                        + (" [ana sunucu]" if role == "primary" else "")
                    )
                else:
                    cmds = [
                        "# peer: aynı multipath blokları → multipaths { }",
                        "service multipathd reload",
                        "oracleasm scandisks",
                        "# createdisk / partition YOK",
                    ]
                    summary = f"{server.hostname}: cluster üyesi — multipath + reload + scandisks"
            else:
                if role in {"single", "primary"}:
                    cmds = ["# sanal: multipath yok"]
                    for spec in disk_specs:
                        cmds.append(
                            f"# partition ({spec['partition_tool']}) {spec['base_device']} → {spec['partition_path']}"
                        )
                        cmds.append(
                            f"oracleasm createdisk {spec['asm_name']} {spec['partition_path']}"
                        )
                    for spec in disk_specs:
                        cmds.append(f"ls -lL {asm_verify_path(spec['asm_name'], server)}")
                    summary = (
                        f"{server.hostname}: {len(disk_specs)} ASM disk [/dev/sd*] "
                        f"(ASM_{alias_prefix.upper()}_{format_seq_index(start_index)}"
                        + (
                            f"…{format_seq_index(start_index + len(disk_specs) - 1)}"
                            if len(disk_specs) > 1
                            else ""
                        )
                        + ")"
                        + (" [ana sunucu]" if role == "primary" else "")
                    )
                else:
                    cmds = [
                        "# peer sanal: multipath yok",
                        "oracleasm scandisks",
                        "# createdisk / partition YOK",
                    ]
                    summary = f"{server.hostname}: cluster üyesi — yalnızca scandisks"
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=summary,
                    planned_commands=cmds,
                    before_state={
                        "role": role,
                        "cluster": cluster,
                        "primary_server_id": primary_id,
                        "alias_prefix": alias_prefix,
                        "seq_start": start_index,
                        "disks": disk_specs,
                        "disk_mode": host_mode,
                        "machine_type": effective_machine_type(server),
                    },
                    risk_notes="",
                )
            )
    except Exception as exc:  # noqa: BLE001
        for server in servers:
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


def _append_multipath_blocks(
    session: Session,
    server: TargetServer,
    disks: list[dict[str, Any]],
) -> Any:
    """Insert multipath { } blocks inside multipaths { } (create section if missing)."""
    import base64

    payload = json.dumps(
        [{"wwid": d["wwid"], "alias": d["multipath_alias"]} for d in disks],
        ensure_ascii=True,
    )
    b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    # Avoid f-string brace hell: only interpolate b64 via format
    script = """
set -e
CONF=/etc/multipath.conf
mkdir -p /etc
touch "$CONF"
cp -a "$CONF" "$CONF.bak.$(date +%s)" 2>/dev/null || true
echo __B64__ | base64 -d > /tmp/dropt-mp-disks.json
python3 <<'PY'
import json, pathlib, re
conf_path = pathlib.Path("/etc/multipath.conf")
text = conf_path.read_text() if conf_path.exists() else ""
disks = json.loads(pathlib.Path("/tmp/dropt-mp-disks.json").read_text())

to_add = []
for d in disks:
    wwid, alias = d["wwid"], d["alias"]
    if wwid in text:
        print("SKIP", wwid)
        continue
    to_add.append(
        "\\tmultipath {\\n\\t\\twwid " + wwid + "\\n\\t\\talias " + alias + "\\n\\t}\\n"
    )
if not to_add:
    print("NOTHING_NEW")
else:
    chunk = "".join(to_add)
    m = re.search(r"multipaths\\s*\\{", text)
    if m:
        idx = m.end()
        # multipaths { sonrası mevcut \\n'i koru; chunk zaten }\\n ile biter —
        # text[idx:] başındaki ekstra \\n'leri yut ki bloklar arasında boş satır olmasın
        rest = text[idx:]
        rest_stripped = rest.lstrip("\\n")
        # { ile ilk multipath arasında tek satır sonu kalsın
        text = text[:idx] + "\\n" + chunk + rest_stripped
    else:
        if text and not text.endswith("\\n"):
            text += "\\n"
        text += "\\nmultipaths {\\n" + chunk + "}\\n"
    conf_path.write_text(text)
    print("UPDATED", len(to_add))
PY
service multipathd reload
sleep 2
echo MPATH_OK
""".replace("__B64__", shlex.quote(b64))
    return run_ssh(session, server, script, timeout=90)


def _create_partition(
    session: Session,
    server: TargetServer,
    device: str,
    size_bytes: int,
    *,
    partition_path: str = "",
) -> Any:
    """device: /dev/mapper/ALIAS veya /dev/sdc.

    Multipath'te fdisk yazdıktan sonra kernel re-read ioctl sık fail eder (Invalid argument);
    partition genelde diskte vardır. Bu yüzden fdisk/parted exit koduna körü körüne
    güvenilmez: node yenileme + beklenen partition path kontrolü yapılır.
    """
    dev = device
    part = (partition_path or "").strip()
    part_q = shlex.quote(part) if part else "''"
    # Ortak: cihaz bekle + partition zaten varsa çık + kernel/mpath yenile + PART bekle
    refresh_and_wait = f"""
# Kernel / multipath partition görünürlüğünü yenile
partprobe "$DEV" 2>/dev/null || true
if command -v kpartx >/dev/null 2>&1; then
  kpartx -a -s "$DEV" 2>/dev/null || kpartx -u -s "$DEV" 2>/dev/null || true
fi
if echo "$DEV" | grep -q '^/dev/mapper/'; then
  MAP=$(basename "$DEV")
  multipathd resize map "$MAP" 2>/dev/null || true
  multipath -r 2>/dev/null || true
fi
udevadm settle 2>/dev/null || true
sleep 2
# Beklenen partition node
PART={part_q}
if [ -n "$PART" ] && [ "$PART" != "''" ]; then
  for i in $(seq 1 45); do
    if [ -b "$PART" ]; then
      echo PART_OK
      exit 0
    fi
    # Yeniden dene: multipath bazen gecikmeli üretir
    if [ $((i % 5)) -eq 0 ]; then
      partprobe "$DEV" 2>/dev/null || true
      command -v kpartx >/dev/null 2>&1 && kpartx -u -s "$DEV" 2>/dev/null || true
      if echo "$DEV" | grep -q '^/dev/mapper/'; then
        multipathd resize map "$(basename "$DEV")" 2>/dev/null || true
      fi
      udevadm settle 2>/dev/null || true
    fi
    sleep 1
  done
  echo "PART_NODE_MISSING expected=$PART"
  ls -la "$DEV"* 2>/dev/null || true
  lsblk "$DEV" 2>/dev/null || true
  exit 1
fi
# Path verilmediyse: lsblk'te part çocuğu yeterli
if lsblk -n -o TYPE "$DEV" 2>/dev/null | grep -q part; then
  echo PART_OK
  exit 0
fi
echo PART_VERIFY_FAILED
lsblk "$DEV" 2>/dev/null || true
exit 1
"""

    if size_bytes >= TWO_TB:
        script = f"""
set -e
DEV={shlex.quote(dev)}
for i in $(seq 1 30); do [ -b "$DEV" ] && break; sleep 1; done
[ -b "$DEV" ]
PART={part_q}
if [ -n "$PART" ] && [ "$PART" != "''" ] && [ -b "$PART" ]; then
  echo PART_EXISTS
  exit 0
fi
if lsblk -n -o TYPE "$DEV" 2>/dev/null | grep -q part; then
  echo PART_EXISTS
  exit 0
fi
set +e
parted -s "$DEV" mklabel gpt
parted -s "$DEV" mkpart primary 0% 100%
set -e
{refresh_and_wait}
"""
    else:
        script = f"""
set -e
DEV={shlex.quote(dev)}
for i in $(seq 1 30); do [ -b "$DEV" ] && break; sleep 1; done
[ -b "$DEV" ]
PART={part_q}
if [ -n "$PART" ] && [ "$PART" != "''" ] && [ -b "$PART" ]; then
  echo PART_EXISTS
  exit 0
fi
if lsblk -n -o TYPE "$DEV" 2>/dev/null | grep -q part; then
  echo PART_EXISTS
  exit 0
fi
# fdisk multipath'te re-read ioctl yüzünden non-zero dönebilir; tablo yine yazılmış olabilir
set +e
printf 'n\\np\\n1\\n\\n\\nw\\n' | fdisk "$DEV"
FDISK_RC=$?
set -e
echo "FDISK_RC=$FDISK_RC"
{refresh_and_wait}
"""
    return run_ssh(session, server, script, timeout=180)


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

    role = plan.before_state.get("role") or "single"
    disks: list[dict[str, Any]] = list(plan.before_state.get("disks") or [])
    primary_id = int(plan.before_state.get("primary_server_id") or 0)
    mode = plan.before_state.get("disk_mode") or asm_disk_mode(server)
    cluster = bool(plan.before_state.get("cluster"))

    # Peer: önce primary success; cluster WWID varlık kontrolü primary bitince de geçerli
    # (multipath -ll — free-list değil)
    if role == "peer" and job_id and primary_id:
        primary_run = session.exec(
            select(JobRun).where(JobRun.job_id == job_id, JobRun.target_server_id == primary_id)
        ).first()
        if primary_run is None or primary_run.status != JobRunStatus.success:
            return (
                False,
                {**plan.before_state, "skipped": True},
                "",
                "Ana sunucu başarısız veya tamamlanmadı — peer atlandı",
            )

    if cluster and job_id:
        try:
            job_servers = _load_job_servers(session, job_id)
            if len(job_servers) > 1:
                _validate_cluster_disks(session, job_servers, disks, refresh=True)
        except ValueError as exc:
            return False, plan.before_state, "", str(exc)

    logs: list[str] = []

    if mode == "multipath":
        mp = _append_multipath_blocks(session, server, disks)
        logs.append(mp.stdout)
        if not mp.ok and "MPATH_OK" not in mp.stdout:
            refresh_scan_cache_once(session, server)
            return False, plan.before_state, "\n".join(logs), mp.stderr or "multipath başarısız"

    if role in {"single", "primary"}:
        created: list[str] = []
        verify_out: list[str] = []
        for spec in disks:
            base = spec.get("base_device") or f"/dev/mapper/{spec['multipath_alias']}"
            part_path = spec["partition_path"]
            part = _create_partition(
                session,
                server,
                base,
                int(spec.get("size_bytes") or 0),
                partition_path=str(part_path or ""),
            )
            logs.append(part.stdout)
            if not part.ok and "PART_OK" not in part.stdout and "PART_EXISTS" not in part.stdout:
                refresh_scan_cache_once(session, server)
                return False, plan.before_state, "\n".join(logs), part.stderr or f"partition başarısız: {base}"

            asm_name = spec["asm_name"]
            create = run_ssh(
                session,
                server,
                f"set -e; "
                f"for i in $(seq 1 30); do [ -b {shlex.quote(part_path)} ] && break; sleep 1; done; "
                f"[ -b {shlex.quote(part_path)} ]; "
                f"oracleasm createdisk {shlex.quote(asm_name)} {shlex.quote(part_path)}",
                timeout=120,
            )
            logs.append(create.stdout)
            if not create.ok:
                refresh_scan_cache_once(session, server)
                return False, plan.before_state, "\n".join(logs), create.stderr or f"createdisk başarısız: {asm_name}"
            created.append(asm_name)

        for i, spec in enumerate(disks):
            asm_name = spec["asm_name"]
            path = asm_verify_path(asm_name, server)
            verify = run_ssh(
                session,
                server,
                f"ls -lL {shlex.quote(path)} 2>&1 || true",
                timeout=30,
            )
            out = (verify.stdout or verify.stderr or "").strip()
            if out:
                logs.append(out)
            verify_out.append(out)
            if i < len(disks) - 1:
                run_ssh(session, server, "sleep 0.3", timeout=5)

        after = {
            **plan.before_state,
            "created": created,
            "verify": verify_out,
            "checklist": ["ASM path çıktılarını kontrol et", "DBA ekibine ilet"],
        }
        refresh_scan_cache_once(session, server)
        return True, after, "\n".join(logs), ""

    # peer
    if mode == "multipath":
        # multipath already written + reload above
        pass
    scan = run_ssh(
        session,
        server,
        "set -e; oracleasm scandisks; echo SCAN_OK",
        timeout=60,
    )
    logs.append(scan.stdout)
    ok = scan.ok or "SCAN_OK" in scan.stdout
    after = {
        **plan.before_state,
        "scanned": ok,
        "checklist": ["Peer'de disk görünürlüğünü doğrula"],
    }
    refresh_scan_cache_once(session, server)
    return ok, after, "\n".join(logs), scan.stderr
