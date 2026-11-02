"""Faz 3a — host kaynaklı donanım logları → `hw_log_entries` (iLO/iDRAC'e BAĞLANMADAN).

Kaynaklar (hepsi mevcut erişim; yeni port/firewall/hesap YOK):
* ESXi: vCenter `FetchSystemEventLog` (IPMI SEL) + `BrowseDiagnosticLog` (vmkernel/vmkwarning) → donanım kalıplarına süzülür.
* Linux/Windows fiziksel sunucu: mevcut log toplayıcıların `SystemEvent` kayıtları donanım kalıplarına göre ayrıştırılır
  (yeni SSH/WinRM komutu YOK).

Kurallar: salt-okunur; `hw_host_logs_enabled` KAPALIyken hiçbir şey çalışmaz; vCenter oturumu hypervisor başına 1 kez
açılır (başarısızsa yeniden denenmez); tekilleştirme `(target_kind, target_id, source, event_key)`; saklama 30 gün;
mesajlar kaydedilmeden önce maskelenir (IPv4/UUID/MAC/WWN).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.hw import HwLogEntry
from app.services.hw import host_log_rules as R

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
MAX_NEW_KEYS_PER_TARGET = 200           # bir hedefte tek turda en fazla bu kadar yeni farklı kayıt (en ağır önce)
MAX_MSG_LEN = 1000
PROJECTION_WINDOW_H = 48
PROJECTION_MAX_ROWS = 4000
KERNEL_LINES, WARNING_LINES = 2000, 1000


class Item(NamedTuple):
    ts: Optional[datetime]
    severity: str
    category: str
    message: str
    count: int = 1                     # projeksiyonda SystemEvent.occurrence_count
    first_ts: Optional[datetime] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def enabled() -> bool:
    try:
        from app.services.runtime_settings import get_bool
        return bool(get_bool("hw_host_logs_enabled"))
    except Exception:  # noqa: BLE001
        return False


# ── Yazma: tekilleştirme ────────────────────────────────────────────────────────────────────────────────────────
def _group(source: str, items: Iterable[Item]) -> Dict[str, Dict[str, Any]]:
    g: Dict[str, Dict[str, Any]] = {}
    for it in items:
        key = R.event_key(source, it.message)
        e = g.get(key)
        if e is None:
            e = g[key] = {"sev": it.severity, "cat": it.category, "msg": it.message, "ts": [], "latest": None,
                          "abs_count": 0, "first_ts": None}
        e["sev"] = R.worse(e["sev"], it.severity)
        if it.ts is not None:
            t = _aware(it.ts)
            e["ts"].append(t)
            if e["latest"] is None or t >= e["latest"]:      # örnek metin = en yeni satır
                e["latest"], e["msg"] = t, it.message
        e["abs_count"] += max(1, int(it.count or 1))
        if it.first_ts is not None:
            ft = _aware(it.first_ts)
            e["first_ts"] = ft if e["first_ts"] is None else min(e["first_ts"], ft)
    return g


def ingest_lines(db: Session, kind: str, tid: int, source: str, items: List[Item], now: Optional[datetime] = None) -> int:
    """Artımlı: yalnız satırın zamanı `last_seen_at`'tan YENİ olanlar `occurrences`'a eklenir (aynı satırlar iki turda
    ikilenmez). Zaman damgası olmayan satır yalnız yeni kayıtta sayılır. Döner: eklenen/güncellenen kayıt sayısı."""
    return _upsert(db, kind, tid, source, items, now or _now(), absolute=False)


def ingest_counted(db: Session, kind: str, tid: int, source: str, items: List[Item], now: Optional[datetime] = None) -> int:
    """Mutlak: her turda kaynağın toplam sayacı yazılır (SystemEvent.occurrence_count) → idempotent."""
    return _upsert(db, kind, tid, source, items, now or _now(), absolute=True)


def _upsert(db: Session, kind: str, tid: int, source: str, items: List[Item], now: datetime, *, absolute: bool) -> int:
    if not items:
        return 0
    groups = _group(source, items)
    have = {r.event_key: r for r in db.query(HwLogEntry).filter(
        HwLogEntry.target_kind == kind, HwLogEntry.target_id == tid, HwLogEntry.source == source,
        HwLogEntry.event_key.in_(list(groups.keys()))).all()}
    touched = 0
    new_keys = [k for k in groups if k not in have]
    if len(new_keys) > MAX_NEW_KEYS_PER_TARGET:
        new_keys.sort(key=lambda k: -R._RANK.get(groups[k]["sev"], 0))
        drop = set(new_keys[MAX_NEW_KEYS_PER_TARGET:])
    else:
        drop = set()
    for key, g in groups.items():
        if key in drop:
            continue
        ts_max = max(g["ts"]) if g["ts"] else None
        ts_min = min(g["ts"]) if g["ts"] else None
        row = have.get(key)
        msg = R.mask_text(g["msg"], MAX_MSG_LEN)
        if row is None:
            n = g["abs_count"]
            row = HwLogEntry(
                target_kind=kind, target_id=tid, source=source, event_key=key, category=g["cat"], severity=g["sev"],
                message=msg, occurrences=max(1, n), occurred_at=ts_max or now,
                first_seen_at=g["first_ts"] or ts_min or now, last_seen_at=ts_max or now)
            db.add(row)
            touched += 1
            continue
        if absolute:
            row.occurrences = max(1, g["abs_count"])
            if ts_max is not None and (row.last_seen_at is None or ts_max >= _aware(row.last_seen_at)):
                row.last_seen_at = ts_max
                row.occurred_at = ts_max
                row.message = msg
            if g["first_ts"] is not None and (row.first_seen_at is None or g["first_ts"] < _aware(row.first_seen_at)):
                row.first_seen_at = g["first_ts"]
            touched += 1
        else:
            seen = _aware(row.last_seen_at)
            new_n = sum(1 for t in g["ts"] if seen is None or t > seen)
            if new_n:
                row.occurrences = int(row.occurrences or 1) + new_n
                row.last_seen_at = ts_max
                row.occurred_at = ts_max
                row.message = msg
                row.severity = g["sev"]
                touched += 1
    db.flush()
    return touched


def purge(db: Session, now: Optional[datetime] = None) -> int:
    cutoff = (now or _now()) - timedelta(days=RETENTION_DAYS)
    n = db.query(HwLogEntry).filter(HwLogEntry.last_seen_at.isnot(None), HwLogEntry.last_seen_at < cutoff) \
        .delete(synchronize_session=False)
    db.flush()
    return n


# ── ESXi (vCenter) ──────────────────────────────────────────────────────────────────────────────────────────────
def items_from_sel(sel: List[Dict[str, Any]]) -> List[Item]:
    """SEL kalıcı bir geçmiş tutar (sahada 2011'e kadar kayıt var). Saklama penceresinden eski kayıtlar atlanır;
    aksi halde her tur `purge` siler, sonraki tur yeniden yazar (gürültü) ve eski bir olay güncel görünür."""
    out: List[Item] = []
    cutoff = _now() - timedelta(days=RETENTION_DAYS)
    for r in sel or []:
        msg = (r.get("message") or "").strip()
        if not msg:
            continue
        ts = R.parse_ts(r.get("when"))
        if ts is not None and _aware(ts) < cutoff:
            continue
        c = R.classify_sel(msg)
        out.append(Item(ts, c.severity, c.category, msg))
    return out


def items_from_log_lines(lines: List[str]) -> List[Item]:
    out: List[Item] = []
    for ln in lines or []:
        c = R.classify_text(ln)
        if c is None:
            continue
        out.append(Item(R.parse_ts(ln), c.severity, c.category, ln.strip()))
    return out


def ingest_host_payload(db: Session, inv_id: int, payload: Dict[str, Any], now: datetime) -> Dict[str, int]:
    """Tek ESXi host için `get_host_hw_logs` çıktısı → tablo. Döner: {sel, vmkernel}."""
    counts = {"sel": 0, "vmkernel": 0}
    counts["sel"] = ingest_lines(db, "esxi", inv_id, "esxi_sel", items_from_sel(payload.get("sel") or []), now)
    items: List[Item] = []
    for key in ("vmkernel", "vmkwarning"):
        items += items_from_log_lines((payload.get("logs") or {}).get(key) or [])
    counts["vmkernel"] = ingest_lines(db, "esxi", inv_id, "esxi_vmkernel", items, now)
    return counts


def collect_esxi(db: Session, now: datetime, *, client_factory=None) -> Dict[str, Any]:
    """Her VMware hypervisor için tek oturum; host başına hata diğerlerini durdurmaz."""
    from app.models.hypervisor import Hypervisor, HypervisorType
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.services.hypervisor_credentials import hv_password

    out: Dict[str, Any] = {"hypervisors": 0, "hosts": 0, "entries": 0, "errors": [], "login_failed": []}
    hvs = [h for h in db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE).all()
           if not (getattr(h, "meta_data", None) or {}).get("fake_seed")]
    for hv in hvs:
        host = (hv.ip_address or hv.hostname or "").strip()
        user = (hv.username or "").strip()
        if not host or not user:
            out["errors"].append(f"{hv.name}: IP/kullanıcı bilgisi eksik")
            continue
        out["hypervisors"] += 1
        try:
            if client_factory is not None:
                client = client_factory(hv)
            else:
                from app.services.vmware.vcenter_client import VCenterClient
                client = VCenterClient(host=host, username=user, password=hv_password(hv),
                                       port=hv.port or 443, verify_ssl=False)
            res = client.get_host_hw_logs(kernel_lines=KERNEL_LINES, warning_lines=WARNING_LINES)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{hv.name}: {type(exc).__name__}")
            logger.warning("hw_host_logs: %s okunamadı: %s", hv.name, type(exc).__name__)
            continue
        if res.get("login_failed"):
            out["login_failed"].append(hv.name)          # yeniden DENENMEZ; sonraki tur zamanlayıcıda
            continue
        inv = {r.host_ref: r.id for r in db.query(HypervisorHostInventory)
               .filter(HypervisorHostInventory.hypervisor_id == hv.id).all()}
        for ref, payload in (res.get("hosts") or {}).items():
            inv_id = inv.get(ref)
            if inv_id is None:
                continue
            out["hosts"] += 1
            try:
                c = ingest_host_payload(db, inv_id, payload, now)
                out["entries"] += c["sel"] + c["vmkernel"]
                for e in payload.get("errors") or []:
                    out["errors"].append(f"{hv.name}/{payload.get('host_name')}: {e}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                out["errors"].append(f"{hv.name}/{payload.get('host_name')}: {type(exc).__name__}")
                logger.exception("hw_host_logs: host yazılamadı")
        db.commit()
    return out


# ── Linux / Windows (mevcut SystemEvent kayıtlarından) ───────────────────────────────────────────────────────────
_SRC_LINUX, _SRC_WIN = "linux_journal", "windows_event"


def project_system_events(db: Session, now: datetime, *, window_h: int = PROJECTION_WINDOW_H) -> Dict[str, int]:
    """Mevcut log toplayıcıların `SystemEvent` kayıtlarını donanım kalıplarına göre `hw_log_entries`'e yansıtır.
    Yeni SSH/WinRM çağrısı YOK; fiziksel olmayan (server_type=VIRTUAL) sunucular atlanır."""
    from app.models.event import SystemEvent
    from app.models.server import Server

    rx = "|".join(re.escape(t) for t in R.prefilter_tokens())
    since = now - timedelta(hours=window_h)
    rows = (db.query(SystemEvent, Server)
            .join(Server, Server.id == SystemEvent.server_id)
            .filter(SystemEvent.event_type == "log_entry",
                    SystemEvent.source.in_(("log_collector", "windows_collector")),
                    SystemEvent.last_seen >= since,
                    func.upper(func.coalesce(Server.server_type, "")) != "VIRTUAL",
                    or_(SystemEvent.description.op("~*")(rx), SystemEvent.title.op("~*")(rx)))
            .order_by(SystemEvent.last_seen.desc()).limit(PROJECTION_MAX_ROWS).all())
    by_target: Dict[tuple, List[Item]] = defaultdict(list)
    for ev, srv in rows:
        raw = ev.raw_data or {}
        msg = (ev.description or ev.title or "").strip()
        if ev.source == "windows_collector":
            eid = raw.get("windows_event_id")
            try:
                eid = int(eid) if eid is not None else None
            except (TypeError, ValueError):
                eid = None
            c = R.classify_windows(str(raw.get("category") or ""), eid, msg,
                                   "critical" if ev.severity in ("critical", "emergency") else None)
            src = _SRC_WIN
        else:
            c = R.classify_text(msg)
            src = _SRC_LINUX
        if c is None:
            continue
        last = _aware(ev.last_seen) or now
        by_target[(srv.id, src)].append(
            Item(last, c.severity, c.category, msg, count=int(ev.occurrence_count or 1), first_ts=_aware(ev.created_at)))
    n = 0
    for (sid, src), items in by_target.items():
        n += ingest_counted(db, "server", sid, src, items, now)
    return {"scanned": len(rows), "targets": len(by_target), "entries": n}


# ── Son toplama zamanı (kartta «son toplama 14:52» için; kayıt yokken de bilinebilsin) ─────────────────────────────
LAST_RUN_KEY = "ainew:hw_host_logs:last_run"


def mark_run(now: datetime, result: Dict[str, Any]) -> None:
    """Toplama turunun zamanını + hata sayısını Redis'e yazar (worker ve API süreçleri paylaşır). Fail-open."""
    try:
        import json
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is None:
            return
        esxi = result.get("esxi") or {}
        errs = len(esxi.get("errors") or []) + len(esxi.get("login_failed") or []) + (1 if esxi.get("error") else 0)
        ipmi = result.get("ipmi") or {}
        errs += len(ipmi.get("errors") or []) + (1 if ipmi.get("error") else 0)
        bmc = result.get("bmc") or {}
        errs += int(bmc.get("auth_failed") or 0) + int(bmc.get("unreachable") or 0) + (1 if bmc.get("error") else 0)
        r.set(LAST_RUN_KEY, json.dumps({"at": now.isoformat(), "errors": errs}), ex=RETENTION_DAYS * 86400)
    except Exception:  # noqa: BLE001
        logger.debug("hw_host_logs: son çalışma zamanı yazılamadı", exc_info=True)


def last_run() -> Optional[Dict[str, Any]]:
    """{at: ISO, errors: int} veya None (hiç çalışmadı / Redis yok)."""
    try:
        import json
        from app.core.redis_client import get_redis
        r = get_redis()
        raw = r.get(LAST_RUN_KEY) if r is not None else None
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


# ── Orkestrasyon ────────────────────────────────────────────────────────────────────────────────────────────────
def any_enabled() -> bool:
    """Üç bayraktan biri açık mı? (arka plan görevi ve zamanlayıcı kapısı)"""
    from app.services.hw import bmc_logs, ipmi_inband
    return enabled() or ipmi_inband.enabled() or bmc_logs.enabled()


def logs_available(db: Optional[Session] = None) -> bool:
    """Portalsız «Donanım Logları» modu kapısı: log bayraklarından biri açık VEYA `hw_log_entries`'te kayıt var.

    Salt-okunur; hiçbir toplama başlatmaz. Hata (DB/tablo yok) → False (yükseltme/ilk boot'ta 500 üretmez).
    """
    try:
        if any_enabled():
            return True
    except Exception:  # noqa: BLE001
        pass
    own = None
    try:
        if db is None:
            from app.core.database import SessionLocal
            own = db = SessionLocal()
        return db.query(HwLogEntry.id).limit(1).first() is not None
    except Exception:  # noqa: BLE001
        return False
    finally:
        if own is not None:
            own.close()


def run_host_log_sync(db: Session, *, force: bool = False, client_factory=None, ipmi_runner=None,
                      bmc_factory=None) -> Dict[str, Any]:
    """Zamanlayıcı girişi. Bayrakların HEPSİ kapalıyken hiçbir şey yapmaz (vCenter/SSH/BMC'ye ek çağrı yok).

    * `hw_host_logs_enabled`  → ESXi (vCenter) + Linux/Windows yansıtması (Faz 3a)
    * `hw_ipmi_inband_enabled` → Linux fiziksel SSH `ipmitool sel` (Faz 3b/B)
    * `hw_bmc_logs_enabled`    → iLO/iDRAC Redfish (Faz 3b/D)
    """
    from app.services.hw import bmc_logs, ipmi_inband
    run_3a = force or enabled()
    run_ipmi = ipmi_inband.enabled()
    run_bmc = bmc_logs.enabled()
    if not force and not (run_3a or run_ipmi or run_bmc):
        return {"skipped": "disabled"}
    now = _now()
    out: Dict[str, Any] = {"ok": True}
    if run_3a:
        try:
            out["esxi"] = collect_esxi(db, now, client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("hw_host_logs: ESXi toplama hata")
            out["esxi"] = {"error": type(exc).__name__}
        try:
            out["projection"] = project_system_events(db, now)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("hw_host_logs: yansıtma hata")
            out["projection"] = {"error": type(exc).__name__}
    if run_ipmi:
        try:
            out["ipmi"] = ipmi_inband.collect_inband(db, now, runner=ipmi_runner)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("hw_host_logs: ipmitool toplama hata")
            out["ipmi"] = {"error": type(exc).__name__}
    if run_bmc:
        try:
            out["bmc"] = bmc_logs.collect_bmc(db, now, client_factory=bmc_factory)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("hw_host_logs: BMC toplama hata")
            out["bmc"] = {"error": type(exc).__name__}
    try:
        out["purged"] = purge(db, now)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("hw_host_logs: temizlik hata")
    if client_factory is None and ipmi_runner is None and bmc_factory is None:   # testler gerçek Redis anahtarını ezmesin
        mark_run(now, out)
    return out
