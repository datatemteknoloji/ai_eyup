"""Faz 3b — Redfish (iLO / iDRAC) log okuyucu. YALNIZ GET (Basic auth; oturum/POST/DELETE YOK).

Yollar `/redfish/v1` kökünden BAĞLANTI İZLENEREK bulunur (üretici yolu sabitlenmez; iDRAC `Managers/.../LogServices/Sel|Lclog`,
iLO `Systems/1/LogServices/IML`, `Managers/1/LogServices/IEL` vb. aynı şemayla bulunur — sahada doğrulanmadı, bkz.
docs/plans/hw-api-sources.md). İzlenebilecek yol şekilleri `endpoints.REDFISH_GET` ile sınırlıdır; `/Actions` her durumda yasak.

Kimlik koruması: servis kökü kimlik gerektirmez; ilk KİMLİKLİ istek (`Managers` koleksiyonu) 401/403 dönerse HEMEN `AuthHalt`
(yeniden deneme YOK). Ağ/zaman aşımı yeniden denenmez (BMC yavaş; sonraki turda).
"""
from __future__ import annotations

import base64
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

from app.services.hw import host_log_rules as R
from app.services.hw import host_logs as HL
from app.services.hw.http import HwApiError, HwHttp

logger = logging.getLogger(__name__)

PRODUCT = "redfish"
SOURCE = "bmc_redfish"
MAX_ENTRIES_PER_SERVICE = 200        # tek log servisinden en fazla bu kadar kayıt işlenir
MAX_PAGES = 6                        # sayfalama üst sınırı
MAX_DETAIL_GETS = 50                 # Members yalnız bağlantı ise tek tek okunacak en fazla kayıt
MAX_REQUESTS = 80                    # uç nokta başına toplam istek bütçesi
TIMEOUT = (5, 25)                    # (bağlantı, okuma) sn
HW_SERVICES = {"sel", "iml"}         # tam donanım log servisleri (tüm kayıtlar); diğerleri yalnız donanım kalıbı/Warning+

_SEV = {"ok": R.SEV_INFO, "informational": R.SEV_INFO, "info": R.SEV_INFO, "warning": R.SEV_WARNING,
        "critical": R.SEV_CRITICAL}


class AuthHalt(Exception):
    """Kimlik reddedildi (401/403) → denemeleri durdur."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


class Unreachable(Exception):
    """Ağ / TLS / zaman aşımı / 5xx — sonraki turda tekrar."""


class Unsupported(Exception):
    """Redfish servis kökü yok / log servisi bulunamadı."""


class RfResult(NamedTuple):
    items: List[HL.Item]
    services: List[str]
    entries_seen: int
    bmc: Dict[str, Optional[str]]      # {"vendor": ..., "model": ..., "redfish": ...}


def _basic(user: str, pw: str) -> Dict[str, str]:
    tok = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {tok}", "Accept": "application/json", "OData-Version": "4.0"}


def _split(link: str) -> Tuple[str, Optional[Dict[str, str]]]:
    path, _, q = (link or "").partition("?")
    params = None
    if q:
        params = {}
        for kv in q.split("&"):
            k, _, v = kv.partition("=")
            if k:
                params[k] = v
    return path, params


def _oid(d: Any) -> Optional[str]:
    return d.get("@odata.id") if isinstance(d, dict) and isinstance(d.get("@odata.id"), str) else None


def _members(doc: Any) -> List[Any]:
    return list(doc.get("Members") or []) if isinstance(doc, dict) else []


def parse_created(v: Any) -> Optional[datetime]:
    """RFC3339 (`2026-10-27T10:11:12+03:00`, `...Z`, ofsetsiz → UTC). Geçersiz → None."""
    if not isinstance(v, str) or not v.strip():
        return None
    raw = v.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    raw = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", raw)     # kesirli saniye 7+ hane vb.
        if not m:
            return None
        dt = datetime.fromisoformat(m.group(1))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def entry_to_item(e: Dict[str, Any], *, full_service: bool, cutoff: datetime) -> Optional[HL.Item]:
    """Tek LogEntry → Item. Önem Redfish `Severity`'den (otoriter); kategori sınıflandırıcıdan. Saklama penceresinden eski
    atlanır; tam servis (SEL/IML) dışında yalnız donanım kalıbı eşleşen veya Warning/Critical kayıtlar alınır."""
    msg = str(e.get("Message") or e.get("Name") or e.get("EntryCode") or "").strip()
    if not msg:
        return None
    ts = parse_created(e.get("Created") or e.get("EventTimestamp"))
    if ts is not None and ts < cutoff:
        return None
    rf = _SEV.get(str(e.get("Severity") or "").lower())
    c = R.classify_sel(msg) if full_service else R.classify_text(msg)
    if c is None:
        if rf not in (R.SEV_WARNING, R.SEV_CRITICAL):
            return None
        cat, sev = "platform", rf
    else:
        cat, sev = c.category, (rf or c.severity)
    return HL.Item(ts, sev, cat, msg)


class RedfishClient:
    """Tek BMC için ince, SALT-OKUNUR istemci. `session` testlerde sahte `requests.Session` yerine geçer."""

    def __init__(self, host: str, username: str, password: str, *, verify: Any = False, session=None, port: int = 443):
        h = (host or "").strip()
        base = h if "://" in h else f"https://{h}"
        if port and port != 443 and ":" not in base.split("://", 1)[1]:
            base = f"{base}:{int(port)}"
        self.http = HwHttp(base, PRODUCT, verify=verify, timeout=TIMEOUT, session=session)
        self._h = _basic(username, password)
        self.budget = MAX_REQUESTS

    def get(self, link: str, *, auth: bool = True) -> Any:
        """`auth=False`: Authorization BAŞLIĞI GÖNDERİLMEZ (servis kökü herkese açıktır; yanlış kimlik bilgisi kökte bile
        reddedilebileceğinden ilk KİMLİKLİ istek bilinçli olarak `Managers`'tır)."""
        if self.budget <= 0:
            raise Unreachable("istek bütçesi doldu")
        self.budget -= 1
        path, params = _split(link)
        headers = self._h if auth else {k: v for k, v in self._h.items() if k != "Authorization"}
        try:
            return self.http.get(path, params=params, headers=headers, retry=False)
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):
                raise AuthHalt(e.kind, e.message) from e
            if e.kind in ("network", "tls", "server"):
                raise Unreachable(e.message) from e
            if e.kind == "readonly":
                raise
            raise Unsupported(e.message) from e      # 404 / parse / diğer client hataları

    def close(self) -> None:
        self.http.close()

    # ── Bağlantı testi (düşük yük: kök + Managers) ──────────────────────────────────────────────────────────────
    def test(self) -> Dict[str, Any]:
        root = self.get("/redfish/v1/", auth=False)
        if not isinstance(root, dict) or not (root.get("RedfishVersion") or root.get("@odata.id")):
            raise Unsupported("Redfish servis kökü bulunamadı")
        mgr = _oid(root.get("Managers")) or "/redfish/v1/Managers"
        self.get(mgr)                                  # İLK kimlikli istek: 401/403 burada AuthHalt
        return {"redfish": root.get("RedfishVersion"), "vendor": root.get("Vendor")}

    # ── Log keşfi + okuma ───────────────────────────────────────────────────────────────────────────────────────
    def _log_services(self, root: Dict[str, Any]) -> List[Tuple[str, str]]:
        """[(servis_adı, servis_yolu)] — Systems ve Managers altındaki tüm LogServices."""
        found: List[Tuple[str, str]] = []
        for key, default in (("Managers", "/redfish/v1/Managers"), ("Systems", "/redfish/v1/Systems")):
            coll = self.get(_oid(root.get(key)) or default)
            for m in _members(coll):
                mp = _oid(m)
                if not mp:
                    continue
                doc = self.get(mp)
                ls = _oid(doc.get("LogServices")) if isinstance(doc, dict) else None
                if not ls:
                    continue
                for svc in _members(self.get(ls)):
                    sp = _oid(svc)
                    if sp:
                        found.append((sp.rstrip("/").rsplit("/", 1)[-1], sp))
        return found

    def _entries(self, svc_path: str) -> Tuple[List[Dict[str, Any]], int]:
        """(kayıtlar, toplam). En fazla MAX_ENTRIES_PER_SERVICE / MAX_PAGES; büyük günlüklerde `$skip` ile SON kayıtlara atlanır
        (best-effort; desteklenmezse ilk sayfalarla yetinilir)."""
        doc = self.get(svc_path.rstrip("/") + "/Entries")
        total = int(doc.get("Members@odata.count") or len(_members(doc))) if isinstance(doc, dict) else 0
        out: List[Dict[str, Any]] = []
        nxt = doc.get("Members@odata.nextLink") if isinstance(doc, dict) else None
        if total > MAX_ENTRIES_PER_SERVICE and isinstance(nxt, str) and "$skip" in nxt:
            try:
                tail = self.get(svc_path.rstrip("/") + f"/Entries?$skip={total - MAX_ENTRIES_PER_SERVICE}")
                doc, nxt = tail, tail.get("Members@odata.nextLink") if isinstance(tail, dict) else None
            except (Unsupported, Unreachable):
                pass
        pages = 0
        detail_left = MAX_DETAIL_GETS
        while True:
            for m in _members(doc):
                if len(out) >= MAX_ENTRIES_PER_SERVICE:
                    break
                if isinstance(m, dict) and (m.get("Message") or m.get("Created") or m.get("Name")):
                    out.append(m)
                elif _oid(m) and detail_left > 0:         # yalnız bağlantı: tek tek oku (üst sınırlı)
                    detail_left -= 1
                    d = self.get(_oid(m))
                    if isinstance(d, dict):
                        out.append(d)
            pages += 1
            if len(out) >= MAX_ENTRIES_PER_SERVICE or pages >= MAX_PAGES or not isinstance(nxt, str) or not nxt:
                break
            doc = self.get(nxt)
            nxt = doc.get("Members@odata.nextLink") if isinstance(doc, dict) else None
        return out, total

    def collect(self, now: Optional[datetime] = None) -> RfResult:
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=HL.RETENTION_DAYS)
        root = self.get("/redfish/v1/", auth=False)
        if not isinstance(root, dict) or not (root.get("RedfishVersion") or root.get("@odata.id")):
            raise Unsupported("Redfish servis kökü bulunamadı")
        services = self._log_services(root)              # ilk kimlikli istek burada: 401/403 → AuthHalt
        if not services:
            raise Unsupported("Log servisi bulunamadı")
        items: List[HL.Item] = []
        names: List[str] = []
        seen = 0
        for name, path in services:
            try:
                entries, _total = self._entries(path)
            except Unsupported:
                continue                                   # bir servis okunamıyorsa diğerleri sürer
            names.append(name)
            seen += len(entries)
            full = name.lower() in HW_SERVICES
            for e in entries:
                it = entry_to_item(e, full_service=full, cutoff=cutoff)
                if it is not None:
                    items.append(it)
        return RfResult(items, names, seen, {"vendor": root.get("Vendor"), "model": None,
                                             "redfish": root.get("RedfishVersion")})
