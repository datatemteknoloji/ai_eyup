"""Dell OpenManage Enterprise (OME 4.7.0) adaptörü — SALT-OKUNUR.

Her uç `docs/plans/hw-api-sources.md` içinde kayıtlıdır. Performans (OME dokümanı): `Devices` yerine
`GroupService/Groups(id)/AllLeafDeviceSummaries`, `$top` ≤ 3000, döngü/eşzamanlı yağma yok (istekler art arda).
Kimlik doğrulama: oturum açma TEK deneme (yeniden deneme yok); 401/403 → `AuthHalt` (çağıran senkronu durdurur).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.hw import auth_guard
from app.services.hw.constants import (
    CAP_DELL, CAP_HW, HEALTH_CRITICAL, HEALTH_OK, HEALTH_UNKNOWN, HEALTH_WARNING, KIND_DELL, SEV_CRITICAL,
    SEV_INFO, SEV_UNKNOWN, SEV_WARNING, SUPPORT_COMPATIBLE, SUPPORT_UNSUPPORTED, SUPPORT_VERIFIED,
)
from app.services.hw.creds import base_url, load_credentials, load_meta, verify_arg
from app.services.hw.http import HwApiError, HwHttp
from app.services.hw.identity import normalize_serial
from app.services.hw.snapshot import (
    ALL_PARTS, AlertRec, EnclosureRec, FirmwareRec, HwSnapshot, ManagerRec, PART_ALERTS, PART_INVENTORY,
    PART_WARRANTY, ServerRec, WarrantyRec,
)
from app.services.integrations.types import ConnTestResult, ProviderHealth

logger = logging.getLogger(__name__)

PAGE = 500                 # $top (dokümanda maks 3000)
MAX_PAGES = 100
ALERT_MAX_PAGES = 6
ALERT_LOOKBACK_DAYS = 7
THROTTLE_SEC = 0.0         # sayfalar arası bekleme (kart ayarından artırılabilir)
FIRMWARE_MAX_PER_RUN = 200

TYPE_SERVER = 1000         # DeviceService: Server
TYPE_CHASSIS = 2000        # DeviceService: Chassis

_HEALTH = {1000: HEALTH_OK, 3000: HEALTH_WARNING, 4000: HEALTH_CRITICAL, 2000: HEALTH_UNKNOWN, 5000: HEALTH_UNKNOWN}
_POWER = {17: "on", 18: "off", 1: "unknown"}
_ALERT_SEV = {16: SEV_CRITICAL, 8: SEV_WARNING, 2: SEV_INFO, 4: SEV_INFO, 1: SEV_UNKNOWN}


def _items(payload: Any) -> List[Dict[str, Any]]:
    """OData `value` listesi; dokümandaki iç içe `value` örneklerini de düzleştirir."""
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("value")
        if raw is None:
            return [payload] if payload else []
    else:
        return []
    out: List[Dict[str, Any]] = []
    for it in raw or []:
        if isinstance(it, dict) and isinstance(it.get("value"), list) and "Id" not in it:
            out.extend(x for x in it["value"] if isinstance(x, dict))
        elif isinstance(it, dict):
            out.append(it)
    return out


def parse_ts(v: Any) -> Optional[datetime]:
    """OME zaman damgası ('2020-09-04 02:00:37.782' / ISO). Saat dilimi dokümanda yok → UTC varsayılır (Doğrulanmadı)."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip()
    if s.startswith("0001-01-01"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def support_for(version: Optional[str]) -> str:
    """OME sürümüne göre destek seviyesi. 4.7.x Doğrulanmış; <3 Desteklenmeyen; diğer Uyumlu."""
    if not version:
        return SUPPORT_COMPATIBLE
    m = re.match(r"^(\d+)\.(\d+)", version.strip())
    if not m:
        return SUPPORT_COMPATIBLE
    major, minor = int(m.group(1)), int(m.group(2))
    if (major, minor) == (4, 7):
        return SUPPORT_VERIFIED
    if major < 3:
        return SUPPORT_UNSUPPORTED
    return SUPPORT_COMPATIBLE


# ── normalizasyon (saf fonksiyonlar; contract testleri bunları doküman örnekleriyle sınar) ──────────────────────
def norm_device(d: Dict[str, Any], *, web_url: Optional[str] = None) -> Optional[ServerRec]:
    """AllLeafDeviceSummaries (DeviceMinModel) → ServerRec (yalnız Type=1000 Server)."""
    if d.get("Type") != TYPE_SERVER:
        return None
    mgmt = d.get("DeviceManagement") or []
    first = mgmt[0] if mgmt and isinstance(mgmt[0], dict) else {}
    prof_l = first.get("ManagementProfile") or []
    prof = prof_l[0] if prof_l and isinstance(prof_l[0], dict) else {}
    model = d.get("Model")
    if isinstance(model, str) and model.strip().lower() in ("", "unknown"):
        model = None
    chassis = d.get("ChassisName") or None
    status = d.get("Status")
    power = d.get("PowerState")
    serial = normalize_serial(d.get("DeviceServiceTag") or d.get("Identifier"))
    return ServerRec(
        provider_ref=str(d.get("Id")), vendor="dell", name=str(d.get("DeviceName") or ""),
        os_hostname=str(d.get("DeviceName") or "") or None, model=model, serial=serial,
        bmc_ip=(first.get("NetworkAddress") or d.get("IpAddress") or None),
        bmc_type=(prof.get("AgentName") or None), bmc_version=(prof.get("Version") or None),
        form_factor=("blade" if chassis else "standalone"),
        enclosure_name=chassis, bay=(d.get("SlotName") or None),
        health=_HEALTH.get(status, HEALTH_UNKNOWN), raw_status=(str(status) if status is not None else None),
        power_state=_POWER.get(power, "unknown") if power is not None else None,
        connected=(bool(d["ConnectionState"]) if d.get("ConnectionState") is not None else None),
        web_url=web_url,
        extra={"managed_state": d.get("ManagedState"), "device_type": d.get("Type")},
    )


def norm_chassis(d: Dict[str, Any]) -> Optional[EnclosureRec]:
    if d.get("Type") != TYPE_CHASSIS:
        return None
    status = d.get("Status")
    return EnclosureRec(provider_ref=str(d.get("Id")), name=str(d.get("DeviceName") or ""),
                        model=(None if str(d.get("Model") or "").lower() in ("", "unknown") else d.get("Model")),
                        serial=normalize_serial(d.get("DeviceServiceTag") or d.get("Identifier")),
                        health=_HEALTH.get(status, HEALTH_UNKNOWN))


def norm_alert(a: Dict[str, Any]) -> Optional[AlertRec]:
    sev = _ALERT_SEV.get(a.get("SeverityType"), SEV_UNKNOWN)
    if a.get("Id") is None:
        return None
    dev = a.get("AlertDeviceId")
    return AlertRec(
        provider_ref=str(a["Id"]), severity=sev, message=str(a.get("Message") or a.get("EemiMessage") or "").strip(),
        category=(a.get("CategoryName") or None), server_ref=(str(dev) if dev not in (None, "") else None),
        entity_name=(a.get("AlertEntityName") or a.get("AlertDeviceName") or None),
        occurred_at=parse_ts(a.get("TimeStamp")), type_id=(a.get("AlertMessageId") or None),
        state="event",     # OME alarmları olay kaydıdır (aktif/temizlendi durumu dokümanda yok)
    )


def norm_warranty(w: Dict[str, Any]) -> Optional[WarrantyRec]:
    if w.get("Id") is None:
        return None
    dev = w.get("DeviceId")
    return WarrantyRec(
        provider_ref=str(w["Id"]), server_ref=(str(dev) if dev not in (None, "", 0) else None),
        serial=normalize_serial(w.get("DeviceIdentifier")),
        service_level=(w.get("ServiceLevelDescription") or None), provider_name=(w.get("ServiceProvider") or None),
        start_date=parse_ts(w.get("StartDate")), end_date=parse_ts(w.get("EndDate")),
    )


class OmeClient:
    product = "ome"

    def __init__(self, http: HwHttp, username: str, password: str, *, throttle: float = THROTTLE_SEC):
        self.http = http
        self.username = username
        self.password = password
        self.throttle = throttle
        self.token: Optional[str] = None
        self.session_path: Optional[str] = None

    def _h(self) -> Dict[str, str]:
        return {"X-Auth-Token": self.token or ""}

    def login(self) -> None:
        """Tek deneme. 401/403 → AuthHalt."""
        try:
            r = self.http.login({"UserName": self.username, "Password": self.password,
                                 "SessionType": "API"},
                                headers={"Content-Type": "application/json", "Accept": "application/json"})
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):
                raise auth_guard.AuthHalt(e.kind, e.message, "OME oturum açma") from e
            raise
        tok = r.headers.get("X-Auth-Token")
        if not tok:
            raise HwApiError("parse", "Oturum açıldı ama X-Auth-Token başlığı dönmedi.")
        self.token = tok
        sid = None
        try:
            sid = (r.json() or {}).get("Id")
        except Exception:  # noqa: BLE001
            sid = None
        if not sid:
            loc = r.headers.get("Location") or ""
            m = re.search(r"\('?([0-9A-Za-z-]+)'?\)", loc)
            sid = m.group(1) if m else None
        if sid:
            self.session_path = f"/api/SessionService/Sessions('{sid}')"

    def logout(self) -> None:
        if self.token and self.session_path:
            self.http.logout(self.session_path, headers=self._h())
        self.token = None

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            return self.http.get(path, params=params, headers=self._h())
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):
                # oturum ortasında 401/403: yeniden giriş DENEMEZ — durdur
                raise auth_guard.AuthHalt(e.kind, e.message, path) from e
            raise

    def _paged(self, path: str, *, params: Optional[Dict[str, Any]] = None, max_pages: int = MAX_PAGES,
               stop=None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        skip = 0
        for _ in range(max_pages):
            p = dict(params or {})
            p["$top"], p["$skip"] = PAGE, skip
            payload = self._get(path, p)
            page = _items(payload)
            out.extend(page)
            total = payload.get("@odata.count") if isinstance(payload, dict) else None
            if stop is not None and stop(page):
                break
            if len(page) < PAGE or (isinstance(total, int) and len(out) >= total):
                break
            skip += PAGE
            if self.throttle:
                time.sleep(self.throttle)
        return out

    # ── okumalar ─────────────────────────────────────────────────────────────────────────────────────────────────
    def app_version(self) -> Optional[str]:
        items = _items(self._get("/api/ApplicationService/Info"))
        return str(items[0].get("Version")) if items and items[0].get("Version") else None

    def all_devices_group_id(self) -> int:
        groups = _items(self._get("/api/GroupService/Groups", {"$top": 1000}))
        for g in groups:
            if g.get("Name") == "All Devices" and g.get("Id") is not None:
                return int(g["Id"])
        raise HwApiError("parse", "“All Devices” grubu bulunamadı (GroupService/Groups).")

    def devices(self, gid: int) -> List[Dict[str, Any]]:
        return self._paged(f"/api/GroupService/Groups({gid})/AllLeafDeviceSummaries")

    def alerts(self, since: Optional[datetime]) -> List[Dict[str, Any]]:
        """En yeniden eskiye; `since`'ten (veya son N günden) eski kayda gelince durur."""
        floor = since or (datetime.now(timezone.utc) - timedelta(days=ALERT_LOOKBACK_DAYS))

        def _old(page: List[Dict[str, Any]]) -> bool:
            ts = [parse_ts(a.get("TimeStamp")) for a in page]
            ts = [t for t in ts if t]
            return bool(ts) and min(ts) < floor

        rows = self._paged("/api/AlertService/Alerts", params={"$orderby": "TimeStamp desc"},
                           max_pages=ALERT_MAX_PAGES, stop=_old)
        return [a for a in rows if (parse_ts(a.get("TimeStamp")) or floor) >= floor]

    def warranties(self) -> List[Dict[str, Any]]:
        return self._paged("/api/WarrantyService/Warranties")

    def device_software(self, device_id: str) -> List[Dict[str, Any]]:
        p = self._get(f"/api/DeviceService/Devices({int(device_id)})/InventoryDetails('deviceSoftware')")
        info = (_items(p) or [{}])[0].get("InventoryInfo") or []
        return [i for i in info if isinstance(i, dict)]


class DellOmeProvider:
    kind = KIND_DELL

    def __init__(self, row, *, http: Optional[HwHttp] = None):
        self.row = row
        self.meta = load_meta(row)
        self.base = base_url(row.endpoint, self.meta.get("port"))
        self._http = http

    # ── protokol ─────────────────────────────────────────────────────────────────────────────────────────────────
    def capabilities(self) -> Set[str]:
        return {CAP_HW, CAP_DELL}

    def health(self) -> ProviderHealth:
        from app.services.hw.sync import provider_stale, data_age_sec
        return ProviderHealth(ok=(self.row.last_status == "ok"), stale=provider_stale(self.row),
                              data_age_sec=data_age_sec(self.row), message=self.row.last_error or "")

    def _client(self) -> OmeClient:
        user, pw = load_credentials(self.row)
        http = self._http or HwHttp(self.base, "ome", verify=verify_arg(self.row, self.meta))
        return OmeClient(http, user, pw, throttle=float(self.meta.get("throttle_sec") or THROTTLE_SEC))

    def test_connection(self) -> ConnTestResult:
        """Bir oturum açar, sürümü okur, kapatır. Kimlik reddi → ok=False + `details.auth_halt` (yeniden denenmez)."""
        if not self.base:
            return ConnTestResult(False, message="Sunucu adresi zorunlu")
        c = self._client()
        try:
            c.login()
            ver = c.app_version()
            level = support_for(ver)
            msg = f"Bağlandı — OME {ver or 'sürüm okunamadı'} ({_level_tr(level)})"
            if level == SUPPORT_UNSUPPORTED:
                return ConnTestResult(False, api_version=ver, message=f"OME {ver} desteklenmiyor (en az 3.x gerekir).",
                                      details={"support_level": level})
            return ConnTestResult(True, api_version=ver, message=msg, details={"support_level": level})
        except auth_guard.AuthHalt as h:
            return ConnTestResult(False, message=h.message, details={"auth_halt": True, "kind": h.kind})
        except HwApiError as e:
            return ConnTestResult(False, message=e.message, details={"kind": e.kind})
        finally:
            c.logout()
            c.http.close()

    # ── toplama ──────────────────────────────────────────────────────────────────────────────────────────────────
    def collect(self, parts: Iterable[str], *, since_alert: Optional[datetime] = None) -> HwSnapshot:
        parts = set(parts) & set(ALL_PARTS)
        snap = HwSnapshot()
        c = self._client()
        mgr = ManagerRec(key="ome", kind="ome", name=self.row.label or "OME", address=self.base)
        try:
            c.login()                         # AuthHalt dışarı çıkar (senkron durur)
            try:
                mgr.version = c.app_version()
            except HwApiError as e:
                if e.kind in ("network", "tls", "server"):
                    raise
                snap.not_measurable.append(f"OME sürümü: okunamadı ({e.message})")
            mgr.support_level = support_for(mgr.version)
            if mgr.support_level == SUPPORT_UNSUPPORTED:
                mgr.status, mgr.error = "unsupported", f"OME {mgr.version} desteklenmiyor"
                snap.managers.append(mgr)
                snap.warnings.append(mgr.error)
                return snap
            if mgr.support_level != SUPPORT_VERIFIED:
                snap.warnings.append(f"OME {mgr.version or '?'} “Doğrulanmış” sürüm (4.7.x) değil; en iyi çaba ile okunuyor.")
            device_by_ref: Dict[str, ServerRec] = {}
            if PART_INVENTORY in parts:       # cihaz listesi yalnız envanter turunda okunur (alarm turunda DEĞİL)
                gid = c.all_devices_group_id()
                raw = c.devices(gid)
                for d in raw:
                    s = norm_device(d, web_url=self.base)
                    if s:
                        s.manager_key = "ome"
                        device_by_ref[s.provider_ref] = s
                        continue
                    e = norm_chassis(d)
                    if e:
                        e.manager_key = "ome"
                        snap.enclosures.append(e)
                snap.parts.add(PART_INVENTORY)
                snap.servers = list(device_by_ref.values())
                snap.complete_managers.add("ome")
                mgr.server_count = len(snap.servers)
                if self.meta.get("fetch_firmware"):
                    self._firmware(c, snap)
            if PART_ALERTS in parts:
                snap.parts.add(PART_ALERTS)
                for a in c.alerts(since_alert):
                    ar = norm_alert(a)
                    if ar and ar.severity in (SEV_CRITICAL, SEV_WARNING):
                        ar.manager_key = "ome"
                        snap.alerts.append(ar)
            if PART_WARRANTY in parts:
                snap.parts.add(PART_WARRANTY)
                for w in c.warranties():
                    wr = norm_warranty(w)
                    if wr:
                        snap.warranties.append(wr)
                if not snap.warranties:
                    snap.not_measurable.append("Garanti: OME garanti kaydı dönmedi (OME internetsiz olabilir)")
            snap.not_measurable.append("Form faktör: OME yalnız şasi/slot bilgisi verir (blade/bağımsız ayrımı)")
            mgr.status = "ok"
            snap.managers.append(mgr)
            return snap
        finally:
            c.logout()
            c.http.close()

    def _firmware(self, c: OmeClient, snap: HwSnapshot) -> None:
        """Cihaz başına `deviceSoftware` envanteri. Tur başına en fazla `firmware_max_per_run` cihaz; sıra SABİT (cihaz Id) ve
        başlangıç `meta.firmware_cursors["ome"]` (önceki turun bıraktığı yer) → sınırdan fazla sunucuda bile art arda turlarda HEPSİ okunur.
        Dell `bios_version` buradan türetilir (`SoftwareType=BIOS`, `Status=Installed`)."""
        servers = sorted(snap.servers, key=lambda x: (0, int(x.provider_ref), "") if str(x.provider_ref).isdigit()
                         else (1, 0, str(x.provider_ref)))
        total = len(servers)
        try:
            cap = max(1, int(self.meta.get("firmware_max_per_run") or FIRMWARE_MAX_PER_RUN))
        except (TypeError, ValueError):
            cap = FIRMWARE_MAX_PER_RUN
        try:
            start = int((self.meta.get("firmware_cursors") or {}).get("ome") or 0)
        except (TypeError, ValueError):
            start = 0
        start = start % total if total else 0
        n = 0
        for k in range(min(cap, total)):
            s = servers[(start + k) % total]
            try:
                items = c.device_software(s.provider_ref)
            except HwApiError as e:
                if e.kind in ("network", "server"):
                    snap.warnings.append("Firmware okuması ağ/sunucu hatası nedeniyle kesildi; kalan cihazlar sonraki turda.")
                    break
                items = []              # cihaz bazlı hata (ör. 404): bu cihazı atla, imleç ilerler
            for it in items:
                cid = it.get("ComponentId")
                snap.firmware.append(FirmwareRec(server_ref=s.provider_ref,
                                                 name=str(it.get("DeviceDescription") or ""),
                                                 component_type=it.get("SoftwareType"),
                                                 version=it.get("Version"),
                                                 status=it.get("Status"),
                                                 component_id=(str(cid) if cid is not None else None)))
                if (it.get("SoftwareType") == "BIOS" and it.get("Status") == "Installed" and it.get("Version")
                        and not s.bios_version):
                    s.bios_version = str(it["Version"])
            n += 1
            if c.throttle:
                time.sleep(c.throttle)
        snap.firmware_cursors["ome"] = (start + n) % total if total else 0
        snap.firmware_progress["ome"] = {"read": n, "total": total}


def _level_tr(level: str) -> str:
    from app.services.hw.constants import SUPPORT_LABEL_TR
    return SUPPORT_LABEL_TR.get(level, level)
