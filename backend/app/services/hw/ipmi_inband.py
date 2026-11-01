"""Faz 3b — Linux FİZİKSEL sunucuda in-band `ipmitool` (SSH üzerinden; BMC hesabı / BMC ağına 443 erişimi GEREKMEZ).

Salt-okunur ve izin listeli: yalnız `ipmitool mc info`, `sel time get`, `sel elist`, `lan print <1-8>`.
`sel clear/delete`, `power`, `mc reset`, `raw`, `user`, `set`, kurulum/modprobe YOK (test kilitler). Root değilse `sudo -n`
(parola sorulmaz); yetki/ipmitool/cihaz yoksa host durumu (`no_sudo|no_ipmitool|no_device`) yazılır, hata sayılmaz.

Bayrak: `hw_ipmi_inband_enabled` (varsayılan KAPALI). SEL → `hw_log_entries` (kaynak `ipmi_sel`, hedef `server`).
BMC IP keşfi: `lan print` kanal 1–8 → `hw_bmc_endpoints` (`ip_source=discovered`; `manual`/`portal` ezilmez).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.hw import host_log_rules as R
from app.services.hw import host_logs as HL

logger = logging.getLogger(__name__)

SOURCE = "ipmi_sel"
SEL_TAIL = 500                       # SEL'den en fazla bu kadar son kayıt
UNRELIABLE_CLOCK_MAX = 20            # BMC saati güvenilmezse en fazla bu kadar son kayıt (eski olay «yeni» görünmesin)
MAX_WORKERS = 4                      # düşük eşzamanlılık (BMC yerel arayüzü yavaş)
CMD_TIMEOUT_SEC = 90

# İzin listesi: (alt komut, argüman) — test bunu script'e karşı doğrular.
ALLOWED = {("mc", "info"), ("sel", "elist"), ("sel", "time"), ("lan", "print")}
FORBIDDEN_WORDS = ("clear", "delete", "power", "reset", "raw", "user", "chassis", "sol", "fru", "set ", "modprobe",
                   "apt", "yum", "dnf", "install", "reboot")

# bash betiği: tek SSH oturumu, bölüm işaretleri. `want_lan` False ise lan print çalıştırılmaz.
_HEAD = (
    'S=""; [ "$(id -u)" = "0" ] || S="sudo -n"\n'
    'if ! command -v ipmitool >/dev/null 2>&1; then echo "##STATE=no_ipmitool"; exit 0; fi\n'
    'echo "##HOSTUTC=$(date -u +%s)"\n'
    'echo "##MC"; $S ipmitool mc info 2>&1 | head -40\n'
    'echo "##SELTIME"; $S ipmitool sel time get 2>&1 | head -3\n'
    f'echo "##SEL"; $S ipmitool sel elist 2>&1 | tail -n {SEL_TAIL}\n'
)
_LAN = (
    'for c in 1 2 3 4 5 6 7 8; do o=$($S ipmitool lan print $c 2>&1 | head -40); echo "##LAN $c"; echo "$o"; '
    'echo "$o" | grep -Eq "^IP Address[[:space:]]*:[[:space:]]*[1-9]" && break; done\n'
)
_TAIL = 'echo "##END"\n'


def build_script(want_lan: bool) -> str:
    return _HEAD + (_LAN if want_lan else "") + _TAIL


# ── Ayrıştırıcılar (SAF) ─────────────────────────────────────────────────────────────────────────────────────────
def split_sections(out: str) -> Dict[str, str]:
    """`##NAME` işaretli bölümler → {NAME: metin}. `##LAN n` → `LAN:n`. `##STATE=x` / `##HOSTUTC=n` → anahtar=değer."""
    secs: Dict[str, str] = {}
    cur: Optional[str] = None
    buf: List[str] = []

    def flush():
        if cur is not None:
            secs[cur] = "\n".join(buf).strip("\n")

    for line in (out or "").splitlines():
        if line.startswith("##"):
            flush()
            buf = []
            tag = line[2:].strip()
            if "=" in tag:
                k, v = tag.split("=", 1)
                secs[k] = v.strip()
                cur = None
            elif tag.startswith("LAN "):
                cur = "LAN:" + tag.split(None, 1)[1]
            else:
                cur = tag
        else:
            buf.append(line)
    flush()
    return secs


class SelRec(NamedTuple):
    rec_id: str
    when: Optional[datetime]          # BMC yerel (naif) saati; Pre-Init/zamansız → None
    sensor: str
    event: str
    direction: str                    # Asserted | Deasserted | ""


_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def parse_sel_elist(text: str) -> List[SelRec]:
    """`ipmitool sel elist` satırı: `ID | MM/DD/YYYY | HH:MM:SS | Sensor | Olay | [Asserted]`. Pre-Init (BMC saati kurulmadan
    önceki) kayıtlar ATLANIR."""
    out: List[SelRec] = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5 or not parts[0].replace(" ", "").isalnum():
            continue
        rid, d, t = parts[0], parts[1], parts[2]
        if not (_DATE.match(d) and _TIME.match(t)):
            continue                                    # Pre-Init / bozuk satır
        try:
            when = datetime.strptime(f"{d} {t}", "%m/%d/%Y %H:%M:%S")
        except ValueError:
            continue
        direction = parts[5] if len(parts) > 5 and parts[5] in ("Asserted", "Deasserted") else ""
        out.append(SelRec(rid, when, parts[3], parts[4], direction))
    return out


def parse_bmc_time(text: str) -> Optional[datetime]:
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})", text or "")
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None


def clock_offset(bmc_now: Optional[datetime], host_utc: Optional[datetime]) -> Optional[timedelta]:
    """BMC saatinin UTC'ye göre sapması. |fark| ≤ 15 dk → 0 (UTC). 30 dk katı sapma (≤14 sa, ±8 dk içinde) → saat dilimi.
    Aksi (saat yanlış / bilinmiyor) → None (güvenilmez)."""
    if bmc_now is None or host_utc is None:
        return None
    skew = bmc_now - host_utc.replace(tzinfo=None)
    if abs(skew) <= timedelta(minutes=15):
        return timedelta(0)
    step = timedelta(minutes=30)
    k = round(skew / step)
    near = k * step
    if abs(near) <= timedelta(hours=14) and abs(skew - near) <= timedelta(minutes=8):
        return near
    return None


def sel_message(r: SelRec) -> str:
    base = f"{r.sensor}: {r.event}".strip()
    return f"{base} ({r.direction})" if r.direction else base


def items_from_sel_text(text: str, bmc_now: Optional[datetime], host_utc: Optional[datetime],
                        now: Optional[datetime] = None) -> Tuple[List[HL.Item], bool]:
    """(öğeler, saat_güvenilir). Deasserted kayıt = durum düzeldi → önem `info`. Saklama penceresinden eski kayıtlar atlanır."""
    recs = parse_sel_elist(text)
    off = clock_offset(bmc_now, host_utc)
    reliable = off is not None
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=HL.RETENTION_DAYS)
    if not reliable:
        recs = recs[-UNRELIABLE_CLOCK_MAX:]
    items: List[HL.Item] = []
    for r in recs:
        msg = sel_message(r)
        if not msg or r.sensor == "" or r.event == "":
            continue
        ts: Optional[datetime] = None
        if reliable and r.when is not None:
            ts = (r.when - off).replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        c = R.classify_sel(msg)
        sev = R.SEV_INFO if r.direction == "Deasserted" else c.severity
        items.append(HL.Item(ts, sev, c.category, msg))
    return items, reliable


class McInfo(NamedTuple):
    vendor: Optional[str]            # dell | hpe | other | None
    manufacturer: Optional[str]


def parse_mc_info(text: str) -> McInfo:
    m = re.search(r"Manufacturer Name\s*:\s*(.+)", text or "")
    name = m.group(1).strip() if m else None
    if not name:
        return McInfo(None, None)
    low = name.lower()
    if "dell" in low:
        return McInfo("dell", name)
    if "hewlett" in low or re.search(r"\bhp\b|\bhpe\b", low):
        return McInfo("hpe", name)
    return McInfo("other", name)


_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def parse_lan(text: str) -> Optional[Dict[str, str]]:
    """Geçerli IP varsa {ip, source}; 0.0.0.0 / 255.* / çoklu yayın → None."""
    ip = src = None
    for line in (text or "").splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "IP Address":
            ip = v
        elif k == "IP Address Source":
            src = v
    if not ip:
        return None
    m = _IPV4.match(ip)
    if not m:
        return None
    o = [int(x) for x in m.groups()]
    if any(x > 255 for x in o) or o[0] in (0, 127, 255) or o[0] >= 224:
        return None
    return {"ip": ip, "source": src or ""}


def discover_ip(secs: Dict[str, str]) -> Optional[Dict[str, str]]:
    for ch in range(1, 9):
        v = parse_lan(secs.get(f"LAN:{ch}", ""))
        if v:
            return v
    return None


def device_state(secs: Dict[str, str]) -> str:
    """ok | no_ipmitool | no_device | no_sudo | error"""
    if secs.get("STATE") == "no_ipmitool":
        return "no_ipmitool"
    blob = "\n".join(secs.get(k, "") for k in ("MC", "SELTIME", "SEL")).lower()
    if ("password is required" in blob or "a terminal is required" in blob or "sudo:" in blob
            or "not in the sudoers" in blob):
        return "no_sudo"
    if "could not open device" in blob or "no such file or directory" in blob:
        return "no_device"
    if "insufficient privileges" in blob:
        return "no_sudo"
    if not secs.get("MC") and not secs.get("SEL") and "HOSTUTC" not in secs:
        return "error"
    return "ok"


# ── SSH çalıştırıcı + toplama ────────────────────────────────────────────────────────────────────────────────────
Runner = Callable[[Dict[str, Any], str], Tuple[bool, str]]


def ssh_runner(creds: Dict[str, Any], script: str) -> Tuple[bool, str]:
    """(bağlandı, stdout). Parola sorulmaz (`sudo -n`); betik bash'e stdin yerine `bash -c` ile verilir."""
    from app.services.ssh_manager import SSHManager
    ssh = SSHManager(host=creds["host"], username=creds["username"], password=creds.get("password"),
                     private_key=creds.get("private_key"), port=creds.get("port") or 22,
                     sudo_password=creds.get("sudo_password"))
    try:
        if not ssh.connect(retries=1):
            return False, ""
        import shlex
        _ok, out, _err = ssh.execute_command("bash -c " + shlex.quote(script), cmd_timeout=CMD_TIMEOUT_SEC)
        return True, out or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("ipmi_inband: %s", type(exc).__name__)
        return False, ""
    finally:
        try:
            ssh.close()
        except Exception:  # noqa: BLE001
            pass


def enabled() -> bool:
    try:
        from app.services.runtime_settings import get_bool
        return bool(get_bool("hw_ipmi_inband_enabled"))
    except Exception:  # noqa: BLE001
        return False


def _candidates(db: Session):
    from app.models.server import Server
    from app.services.platform_scope import is_windows_server
    out = []
    for s in db.query(Server).filter(Server.ai_ready == True).all():  # noqa: E712
        if (s.server_type or "").upper() != "PHYSICAL" or is_windows_server(s) or not s.ip_address:
            continue
        out.append(s)
    return out


def collect_inband(db: Session, now: datetime, *, runner: Optional[Runner] = None) -> Dict[str, Any]:
    """Bayrak AÇIKKEN çağrılır. Host başına hata diğerlerini durdurmaz; sonuç sayaçlarda."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.models.credential import GlobalCredential
    from app.models.hw import HwBmcEndpoint
    from app.services.hw import bmc_endpoints as EP
    from app.services.ssh_credentials import resolve_ssh_creds

    out: Dict[str, Any] = {"hosts": 0, "ok": 0, "skipped_state": {}, "entries": 0, "ips": 0, "clock_suspect": [], "errors": []}
    run = runner or ssh_runner
    servers = _candidates(db)
    if not servers:
        return out
    gcred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
    if gcred is None:
        gcred = db.query(GlobalCredential).first()
    creds_by_id: Dict[int, Dict[str, Any]] = {}
    want_lan: Dict[int, bool] = {}
    eps = {(e.target_kind, e.target_id): e for e in db.query(HwBmcEndpoint).filter(HwBmcEndpoint.target_kind == "server").all()}
    for s in servers:
        c = resolve_ssh_creds(s, global_cred=gcred)
        if not c.get("username") or not c.get("host") or not c.get("has_secret"):
            continue
        creds_by_id[s.id] = c
        ep = eps.get(("server", s.id))
        want_lan[s.id] = ep is None or not ep.bmc_ip or ep.ip_source == "discovered"
    results: Dict[int, Tuple[bool, str]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="hw-ipmi") as pool:
        futs = {pool.submit(run, creds_by_id[sid], build_script(want_lan[sid])): sid for sid in creds_by_id}
        for f in as_completed(futs):
            sid = futs[f]
            try:
                results[sid] = f.result()
            except Exception as exc:  # noqa: BLE001
                results[sid] = (False, "")
                out["errors"].append(f"{sid}: {type(exc).__name__}")
    by_id = {s.id: s for s in servers}
    for sid, (connected, text) in results.items():
        srv = by_id[sid]
        out["hosts"] += 1
        ep = EP.ensure_endpoint(db, "server", sid)
        ep.ipmi_run_at = now
        if not connected:
            ep.ipmi_status = "error"
            out["errors"].append(f"{srv.name}: SSH")
            continue
        secs = split_sections(text)
        st = device_state(secs)
        ep.ipmi_status = st
        if st != "ok":
            out["skipped_state"][st] = out["skipped_state"].get(st, 0) + 1
            continue
        try:
            host_utc = None
            if secs.get("HOSTUTC", "").isdigit():
                host_utc = datetime.fromtimestamp(int(secs["HOSTUTC"]), tz=timezone.utc)
            items, reliable = items_from_sel_text(secs.get("SEL", ""), parse_bmc_time(secs.get("SELTIME", "")), host_utc, now)
            if not reliable and items:
                out["clock_suspect"].append(srv.name)
            out["entries"] += HL.ingest_lines(db, "server", sid, SOURCE, items, now)
            mc = parse_mc_info(secs.get("MC", ""))
            if mc.vendor and not ep.vendor:
                ep.vendor = mc.vendor
            if want_lan.get(sid):
                d = discover_ip(secs)
                if d and (not ep.bmc_ip or ep.ip_source in (None, "", "discovered")):
                    if ep.bmc_ip != d["ip"]:
                        out["ips"] += 1
                    ep.bmc_ip, ep.ip_source = d["ip"], "discovered"
            out["ok"] += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            out["errors"].append(f"{srv.name}: {type(exc).__name__}")
            logger.exception("ipmi_inband: yazılamadı")
    db.commit()
    return out
