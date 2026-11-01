"""Faz 3b — BMC (iLO/iDRAC) Redfish log toplama orkestrasyonu.

Bayrak `hw_bmc_logs_enabled` (varsayılan KAPALI): kapalıyken BMC'ye HİÇ bağlanılmaz. Kimlik: `bmc_creds.resolve` (zincirleme YOK).
Aynı profili kullanan uç noktalar gruplanır: her grupta İLK uç nokta tek başına denenir (kanarya); kimlik reddedilirse gruptaki
kalan uç noktalara bu turda DENENMEZ. Reddedilen uç nokta `auth_halted` olur ve yalnız başarılı «Bağlantıyı test et» ile sürer.
Kalan uç noktalar düşük eşzamanlılıkla (MAX_WORKERS) okunur; DB yazımı ana iş parçacığındadır.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.hw import HwBmcEndpoint, HwBmcProfile, HwServer
from app.services.hw import bmc_creds as BC
from app.services.hw import bmc_endpoints as EP
from app.services.hw import host_logs as HL
from app.services.hw import redfish as RF

logger = logging.getLogger(__name__)

MAX_WORKERS = 3
MAX_RUN_SEC = 1200          # tur başına süre bütçesi (aşılırsa kalanlar sonraki tura)

ClientFactory = Callable[[str, str, str, bool], Any]


def enabled() -> bool:
    try:
        from app.services.runtime_settings import get_bool
        return bool(get_bool("hw_bmc_logs_enabled"))
    except Exception:  # noqa: BLE001
        return False


def _default_factory(ip: str, user: str, pw: str, verify: bool):
    return RF.RedfishClient(ip, user, pw, verify=verify)


def _fetch(factory: ClientFactory, ip: str, user: str, pw: str, verify: bool, now: datetime):
    """Ağ işi (iş parçacığında; DB'ye dokunmaz). → ("ok", RfResult) | ("auth", msg) | ("unreachable", msg) | ("unsupported", msg)"""
    client = None
    try:
        client = factory(ip, user, pw, verify)
        return "ok", client.collect(now)
    except RF.AuthHalt as e:
        return "auth", e.message
    except RF.Unreachable as e:
        return "unreachable", str(e)[:200]
    except RF.Unsupported as e:
        return "unsupported", str(e)[:200]
    except Exception as e:  # noqa: BLE001
        logger.debug("bmc fetch: %s", type(e).__name__)
        return "unreachable", type(e).__name__
    finally:
        try:
            if client is not None and hasattr(client, "close"):
                client.close()
        except Exception:  # noqa: BLE001
            pass


def _apply(db: Session, ep: HwBmcEndpoint, kind: str, payload: Any, now: datetime, out: Dict[str, Any]) -> None:
    ep.last_run_at = now
    if kind == "ok":
        res: RF.RfResult = payload
        tk, tid = EP.log_target(db, ep)
        n = HL.ingest_lines(db, tk, tid, RF.SOURCE, res.items, now)
        ep.status, ep.last_error, ep.last_ok_at = "ok", None, now
        v = (res.bmc.get("vendor") or "").lower()
        if not ep.vendor and v:
            ep.vendor = "dell" if "dell" in v else "hpe" if ("hp" in v or "hewlett" in v) else "other"
        out["entries"] += n
        out["ok"] += 1
    elif kind == "auth":
        ep.status, ep.auth_halted, ep.last_error = "auth_failed", True, str(payload)[:500]
        out["auth_failed"] += 1
    elif kind == "unsupported":
        ep.status, ep.last_error = "unsupported", str(payload)[:500]
        out["unsupported"] += 1
    else:
        ep.status, ep.last_error = "unreachable", str(payload)[:500]
        out["unreachable"] += 1


def collect_bmc(db: Session, now: datetime, *, client_factory: Optional[ClientFactory] = None,
                max_run_sec: int = MAX_RUN_SEC) -> Dict[str, Any]:
    """Bayrak AÇIKKEN çağrılır (testler `client_factory` verir)."""
    factory = client_factory or _default_factory
    out: Dict[str, Any] = {"endpoints": 0, "ok": 0, "auth_failed": 0, "unreachable": 0, "unsupported": 0,
                           "no_ip": 0, "no_cred": 0, "skipped_group": 0, "halted": 0, "entries": 0, "timeout": False}
    EP.sync_endpoints(db)
    db.commit()
    profiles: List[HwBmcProfile] = db.query(HwBmcProfile).all()
    hw_by_id = {h.id: h for h in db.query(HwServer).all()}
    eps = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.enabled == True).order_by(HwBmcEndpoint.id).all()  # noqa: E712

    groups: Dict[int, List[Tuple[HwBmcEndpoint, str, str, bool]]] = {}
    for ep in eps:
        out["endpoints"] += 1
        if ep.auth_halted:
            out["halted"] += 1
            continue
        if not (ep.bmc_ip or "").strip():
            ep.status = "no_ip"
            out["no_ip"] += 1
            continue
        hs = hw_by_id.get(ep.target_id) if ep.target_kind == "hw" else None
        res = BC.resolve(ep, vendor=(ep.vendor or (hs.vendor if hs else None)),
                         instance_id=(hs.instance_id if hs else None), profiles=profiles)
        if res.profile is None:
            ep.status = "no_cred"
            out["no_cred"] += 1
            continue
        user, pw = BC.load(res.profile)
        if not user:
            ep.status = "no_cred"
            out["no_cred"] += 1
            continue
        groups.setdefault(res.profile.id, []).append((ep, user, pw, bool(res.profile.verify_tls)))
    db.commit()

    t0 = time.monotonic()

    def over() -> bool:
        return (time.monotonic() - t0) > max_run_sec

    for pid, members in groups.items():
        if over():
            out["timeout"] = True
            break
        ep0, u0, p0, v0 = members[0]
        kind, payload = _fetch(factory, ep0.bmc_ip.strip(), u0, p0, v0, now)
        try:
            _apply(db, ep0, kind, payload, now, out)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("bmc_logs: kanarya yazılamadı")
        if kind == "auth":
            out["skipped_group"] += len(members) - 1        # kalanlara BU TURDA denenmez (hesap kilitlenmesin)
            continue
        rest = members[1:]
        if not rest:
            continue
        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="hw-bmc") as pool:
            futs = {}
            for m in rest:
                if over():
                    out["timeout"] = True
                    break
                futs[pool.submit(_fetch, factory, m[0].bmc_ip.strip(), m[1], m[2], m[3], now)] = m[0]
            for f in as_completed(futs):
                ep = futs[f]
                k, pl = f.result()
                try:
                    _apply(db, ep, k, pl, now, out)
                    db.commit()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    logger.exception("bmc_logs: yazılamadı")
    return out


# ── Tek uç nokta «Bağlantıyı test et» (API) ──────────────────────────────────────────────────────────────────────
def test_endpoint(db: Session, ep: HwBmcEndpoint, *, client_factory: Optional[ClientFactory] = None) -> Dict[str, Any]:
    """TEK deneme (kök + Managers). Başarılıysa `auth_halted` kalkar. Kimlik yok/IP yok → ağa çıkmadan açıklama döner."""
    profiles = db.query(HwBmcProfile).all()
    hs = db.query(HwServer).filter(HwServer.id == ep.target_id).first() if ep.target_kind == "hw" else None
    if not (ep.bmc_ip or "").strip():
        return {"ok": False, "status": "no_ip", "message": "BMC IP tanımlı değil."}
    res = BC.resolve(ep, vendor=(ep.vendor or (hs.vendor if hs else None)),
                     instance_id=(hs.instance_id if hs else None), profiles=profiles)
    if res.profile is None:
        return {"ok": False, "status": "no_cred", "message": "Bu uç nokta için kimlik profili tanımlı değil."}
    user, pw = BC.load(res.profile)
    factory = client_factory or _default_factory
    client = None
    now = datetime.now(timezone.utc)
    try:
        client = factory(ep.bmc_ip.strip(), user, pw, bool(res.profile.verify_tls))
        info = client.test()
        ep.status, ep.auth_halted, ep.last_error, ep.last_run_at = "ok", False, None, now
        db.commit()
        return {"ok": True, "status": "ok", "level": res.level, "redfish": (info or {}).get("redfish")}
    except RF.AuthHalt as e:
        ep.status, ep.auth_halted, ep.last_error, ep.last_run_at = "auth_failed", True, e.message[:500], now
        db.commit()
        return {"ok": False, "status": "auth_failed", "message": e.message, "level": res.level}
    except RF.Unsupported as e:
        ep.status, ep.last_error, ep.last_run_at = "unsupported", str(e)[:500], now
        db.commit()
        return {"ok": False, "status": "unsupported", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        msg = str(e) or type(e).__name__
        ep.status, ep.last_error, ep.last_run_at = "unreachable", msg[:500], now
        db.commit()
        return {"ok": False, "status": "unreachable", "message": msg}
    finally:
        try:
            if client is not None and hasattr(client, "close"):
                client.close()
        except Exception:  # noqa: BLE001
            pass
