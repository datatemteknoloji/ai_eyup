"""HPE OneView (appliance) ve OneView Global Dashboard (OVGD) adaptörü — SALT-OKUNUR.

Mod `ovgd`: tek uç (OVGD, `X-Api-Version: 2`); appliance'lar `GET /rest/appliances` ile keşfedilir ve sunucu/alarm
verisi OVGD'nin birleşik uçlarından okunur (ayrıca appliance'a bağlanılmaz → tek hesap, tek oturum).
Mod `oneview`: bir veya birkaç appliance (paylaşılan hesap); her biri için `/rest/version` → sürüm tespiti.

Kimlik koruması: oturum açma TEK deneme; ilk 401/403'te `AuthHalt` fırlar → kalan appliance'lara DENENMEZ.
Alan adları/tipleri: OVGD swagger'ından (Doğrulanmış) ve OneView API dokümanı dizininden (yalnız adlar); tip/birim
farkı olan alanlar `docs/plans/hw-api-sources.md` içinde “Doğrulanmadı”.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.services.hw import auth_guard
from app.services.hw.constants import (
    CAP_HPE, CAP_HW, HEALTH_CRITICAL, HEALTH_OK, HEALTH_UNKNOWN, HEALTH_WARNING, KIND_HPE, MODE_ONEVIEW, MODE_OVGD,
    SEV_CRITICAL, SEV_INFO, SEV_UNKNOWN, SEV_WARNING, SUPPORT_COMPATIBLE, SUPPORT_LABEL_TR, SUPPORT_UNSUPPORTED,
    SUPPORT_VERIFIED,
)
from app.services.hw.creds import base_url, load_credentials, load_meta
from app.services.hw.http import HwApiError, HwHttp
from app.services.hw.identity import normalize_serial, normalize_uuid
from app.services.hw.snapshot import (
    ALL_PARTS, AlertRec, EnclosureRec, HwSnapshot, ManagerRec, PART_ALERTS, PART_INVENTORY, PART_WARRANTY, ServerRec,
)
from app.services.integrations.types import ConnTestResult, ProviderHealth

logger = logging.getLogger(__name__)

PAGE = 200                 # OneView start/count
OVGD_PAGE = 500            # OVGD swagger: count=-1 → en çok 500
MAX_PAGES = 200
OVGD_API_VERSION = 2       # swagger: X-Api-Version min=max=2
KNOWN_API = {3800: "6.60", 7600: "10.00", 9000: "11.x"}

_HEALTH = {"ok": HEALTH_OK, "warning": HEALTH_WARNING, "critical": HEALTH_CRITICAL}
_SEV = {"critical": SEV_CRITICAL, "warning": SEV_WARNING, "ok": SEV_INFO}


def _health(v: Any) -> str:
    return _HEALTH.get(str(v or "").strip().lower(), HEALTH_UNKNOWN)


def _tail(uri: Optional[str]) -> Optional[str]:
    if not uri or not isinstance(uri, str):
        return None
    return uri.rstrip("/").rsplit("/", 1)[-1] or None


def make_ref(manager_key: str, uri_path: Optional[str]) -> str:
    """Sunucu ve alarmın AYNI formülle hesapladığı kimlik: `<yönetim noktası>|<kaynak yolu>`."""
    return f"{manager_key}|{uri_path or ''}"


def support_for_api(api: Optional[int]) -> str:
    """OneView REST API sürümüne göre. 7600 (10.00) ve 9000 (11.x): Doğrulanmış; 3800 (6.60): Uyumlu; <3800: Desteklenmeyen."""
    if api is None:
        return SUPPORT_COMPATIBLE
    if api in (7600, 9000):
        return SUPPORT_VERIFIED
    if api < 3800:
        return SUPPORT_UNSUPPORTED
    return SUPPORT_COMPATIBLE


def support_for_version(version: Optional[str]) -> str:
    """OneView ürün sürümü dizesinden ('10.00.00-0507518', '6.60.04-0476963')."""
    m = re.match(r"^(\d+)\.(\d+)", (version or "").strip())
    if not m:
        return SUPPORT_COMPATIBLE
    mm = (int(m.group(1)), int(m.group(2)))
    if mm in ((10, 0), (11, 20), (11, 40)):
        return SUPPORT_VERIFIED
    if mm < (6, 60):
        return SUPPORT_UNSUPPORTED
    return SUPPORT_COMPATIBLE


def _bmc_ip(d: Dict[str, Any]) -> Optional[str]:
    ip = d.get("mpIpAddress")
    if isinstance(ip, str) and ip:
        return ip
    info = d.get("mpHostInfo") or {}
    for a in (info.get("mpIpAddresses") or []):
        if isinstance(a, dict) and a.get("address") and str(a.get("type")) != "LinkLocal" and ":" not in str(a["address"]):
            return str(a["address"])
    return (info.get("mpHostName") or None) if isinstance(info, dict) else None


def norm_server(d: Dict[str, Any], manager_key: str, *, web_url: Optional[str] = None,
                is_ovgd: bool = False) -> Optional[ServerRec]:
    """server-hardware kaydı → ServerRec. OVGD'de kaynak yolu `originalUri` (appliance'taki uri)."""
    uri = (d.get("originalUri") if is_ovgd else None) or d.get("uri")
    if not uri and not d.get("uuid"):
        return None
    loc = d.get("locationUri") or ""
    in_encl = "/rest/enclosures/" in loc
    ff_raw = d.get("formFactor")
    if in_encl:
        ff = "blade"
    elif "rack" in str(ff_raw or "").lower():
        ff = "rack"
    else:
        ff = "unknown"
    mem = d.get("memoryMb")
    return ServerRec(
        provider_ref=make_ref(manager_key, uri), vendor="hpe", name=str(d.get("name") or ""),
        manager_key=manager_key, os_hostname=(d.get("serverName") or None), model=(d.get("model") or None),
        serial=normalize_serial(d.get("serialNumber")), uuid=normalize_uuid(d.get("uuid")),
        virtual_serial=normalize_serial(d.get("virtualSerialNumber")),
        virtual_uuid=normalize_uuid(d.get("virtualUuid")), bmc_ip=_bmc_ip(d), bmc_type=(d.get("mpModel") or None),
        bmc_version=(d.get("mpFirmwareVersion") or None), bios_version=(d.get("romVersion") or None),
        form_factor=ff, enclosure_ref=(_tail(loc) if in_encl else None),
        bay=(str(d["position"]) if d.get("position") is not None else None),
        health=_health(d.get("status")), raw_status=(d.get("status") or None),
        power_state=({"on": "on", "off": "off"}.get(str(d.get("powerState") or "").lower(), "unknown")
                     if d.get("powerState") is not None else None),
        connected=None, cpu_count=(d.get("processorCount") if isinstance(d.get("processorCount"), int) else None),
        memory_gb=(round(mem / 1024.0, 1) if isinstance(mem, (int, float)) else None), web_url=web_url,
        extra={"form_factor_raw": ff_raw, "state": d.get("state"), "profile_uri": d.get("serverProfileUri"),
               "appliance": d.get("applianceName"), "appliance_location": d.get("applianceLocation")},
    )


def norm_enclosure(d: Dict[str, Any], manager_key: str, *, is_ovgd: bool = False) -> Optional[EnclosureRec]:
    uri = (d.get("originalUri") if is_ovgd else None) or d.get("uri")
    if not uri:
        return None
    return EnclosureRec(provider_ref=make_ref(manager_key, uri), name=str(d.get("name") or ""), manager_key=manager_key,
                        model=(d.get("enclosureModel") or d.get("enclosureType") or None),
                        serial=normalize_serial(d.get("serialNumber")), health=_health(d.get("status")),
                        bay_count=(d.get("deviceBayCount") if isinstance(d.get("deviceBayCount"), int) else None))


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def norm_alert(a: Dict[str, Any], manager_key: str, *, is_ovgd: bool = False) -> Optional[AlertRec]:
    sev = _SEV.get(str(a.get("severity") or "").lower(), SEV_UNKNOWN)
    uri = a.get("uri")
    if not uri:
        return None
    assoc = a.get("associatedResource") or {}
    res_uri = (a.get("associatedResourceOriginalUri") if is_ovgd else None) or (assoc.get("resourceUri") if isinstance(assoc, dict) else None) or a.get("resourceUri")
    server_ref = make_ref(manager_key, res_uri) if isinstance(res_uri, str) and "/rest/server-hardware/" in res_uri else None
    state = "active" if str(a.get("alertState") or "").lower() == "active" else "cleared"
    return AlertRec(
        provider_ref=make_ref(manager_key, uri), severity=sev, message=str(a.get("description") or "").strip(),
        category=(a.get("healthCategory") or a.get("physicalResourceType") or None), server_ref=server_ref,
        entity_name=(a.get("associatedResourceName") or (assoc.get("resourceName") if isinstance(assoc, dict) else None) or None),
        manager_key=manager_key, state=state, occurred_at=_parse_iso(a.get("created")),
        cleared_at=_parse_iso(a.get("clearedTime")), type_id=(a.get("alertTypeID") or None),
    )


class HpeClient:
    """OneView appliance (product=oneview) veya OVGD (product=ovgd) için ince istemci."""

    def __init__(self, http: HwHttp, product: str, username: str, password: str, *, domain: str = "Local",
                 throttle: float = 0.0):
        self.http, self.product = http, product
        self.username, self.password, self.domain = username, password, domain
        self.throttle = throttle
        self.token: Optional[str] = None
        self.api: Optional[int] = None

    def _h(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api is not None:
            h["X-API-Version"] = str(self.api)
        if self.token:
            h["Auth"] = self.token
        return h

    def version(self) -> Dict[str, Any]:
        v = self.http.get("/rest/version", headers={"Accept": "application/json"})
        return v if isinstance(v, dict) else {}

    def login(self, api: int) -> None:
        self.api = api
        body = {"userName": self.username, "password": self.password, "authLoginDomain": self.domain}
        try:
            r = self.http.login(body, headers={"Content-Type": "application/json", "Accept": "application/json",
                                               "X-API-Version": str(api)})
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):
                raise auth_guard.AuthHalt(e.kind, e.message, f"{self.product} oturum açma") from e
            raise
        try:
            j = r.json() or {}
        except ValueError:
            j = {}
        # OneView: sessionID; OVGD: token (swagger)
        self.token = j.get("sessionID") or j.get("token")
        if not self.token:
            raise HwApiError("parse", "Oturum açıldı ama oturum anahtarı dönmedi.")

    def logout(self) -> None:
        if self.token:
            self.http.logout(headers=self._h())
        self.token = None

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            return self.http.get(path, params=params, headers=self._h())
        except HwApiError as e:
            if e.kind in ("auth", "forbidden"):
                raise auth_guard.AuthHalt(e.kind, e.message, path) from e
            raise

    def members(self, path: str, *, params: Optional[Dict[str, Any]] = None, page: int = PAGE,
                max_pages: int = MAX_PAGES) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        start = 0
        for _ in range(max_pages):
            p = dict(params or {})
            p["start"], p["count"] = start, page
            payload = self.get(path, p)
            mem = (payload.get("members") if isinstance(payload, dict) else None) or []
            out.extend(m for m in mem if isinstance(m, dict))
            total = payload.get("total") if isinstance(payload, dict) else None
            if len(mem) < page or (isinstance(total, int) and len(out) >= total) or not payload.get("nextPageUri"):
                break
            start += len(mem)
            if self.throttle:
                time.sleep(self.throttle)
        return out


def appliance_hosts(row, meta: Dict[str, Any]) -> List[str]:
    hosts = [row.endpoint] + [h for h in (meta.get("appliances") or []) if isinstance(h, str)]
    seen, out = set(), []
    for h in hosts:
        b = base_url(h, None)
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


class HpeProvider:
    kind = KIND_HPE

    def __init__(self, row, *, http_factory=None):
        self.row = row
        self.meta = load_meta(row)
        self.mode = self.meta.get("mode") or MODE_OVGD
        self._http_factory = http_factory

    # ── protokol ─────────────────────────────────────────────────────────────────────────────────────────────────
    def capabilities(self) -> Set[str]:
        return {CAP_HW, CAP_HPE}

    def health(self) -> ProviderHealth:
        from app.services.hw.sync import provider_stale, data_age_sec
        return ProviderHealth(ok=(self.row.last_status == "ok"), stale=provider_stale(self.row),
                              data_age_sec=data_age_sec(self.row), message=self.row.last_error or "")

    def _verify(self, base: str):
        ca = ((self.meta.get("ca_bundles") or {}).get(base) or self.meta.get("ca_bundle_path") or "").strip()
        return ca if (ca and self.row.verify_ssl) else bool(self.row.verify_ssl)

    def _client(self, base: str, product: str) -> HpeClient:
        user, pw = load_credentials(self.row)
        http = (self._http_factory(base, product) if self._http_factory
                else HwHttp(base, product, verify=self._verify(base)))
        return HpeClient(http, product, user, pw, domain=str(self.meta.get("login_domain") or "Local"),
                         throttle=float(self.meta.get("throttle_sec") or 0.0))

    # ── test ─────────────────────────────────────────────────────────────────────────────────────────────────────
    def test_connection(self) -> ConnTestResult:
        hosts = appliance_hosts(self.row, self.meta)
        if not hosts:
            return ConnTestResult(False, message="Sunucu adresi zorunlu")
        results: List[Dict[str, Any]] = []
        ok_all = True
        api_label = None
        for base in hosts:
            res = self._test_one(base)
            results.append(res)
            if res.get("auth_halt"):
                # ilk kimlik hatasında kalan appliance'lara DENEME YOK (paylaşılan hesap kilitlenmesin)
                for rest in hosts[len(results):]:
                    results.append({"host": rest, "ok": False, "skipped": True,
                                    "message": "Kimlik hatası nedeniyle denenmedi."})
                return ConnTestResult(False, message=res["message"],
                                      details={"auth_halt": True, "kind": res.get("kind"), "appliances": results})
            ok_all = ok_all and bool(res.get("ok"))
            api_label = api_label or res.get("api_version")
        n_ok = sum(1 for r in results if r.get("ok"))
        msg = (f"Bağlandı — {n_ok}/{len(results)} uç" if len(results) > 1 else
               (results[0].get("message") or ("Bağlandı" if ok_all else "Bağlanılamadı")))
        return ConnTestResult(n_ok > 0 and ok_all, api_version=api_label, message=msg,
                              details={"appliances": results})

    def _test_one(self, base: str) -> Dict[str, Any]:
        product = "ovgd" if self.mode == MODE_OVGD else "oneview"
        c = self._client(base, product)
        out: Dict[str, Any] = {"host": base, "ok": False}
        try:
            v = c.version()
            cur, mn = v.get("currentVersion"), v.get("minimumVersion")
            api = OVGD_API_VERSION if product == "ovgd" else (int(cur) if cur else None)
            if product == "oneview":
                lvl = support_for_api(api)
                out.update(api_version=str(cur), support_level=lvl)
                if lvl == SUPPORT_UNSUPPORTED:
                    out["message"] = f"OneView API {cur} desteklenmiyor (en az 3800 / OneView 6.60)."
                    return out
            elif cur is not None and mn is not None and int(mn) > OVGD_API_VERSION:
                out["message"] = f"OVGD en az API {mn} istiyor; bu entegrasyon API v2 ile çalışır."
                return out
            else:
                out.update(api_version=str(cur), support_level=SUPPORT_COMPATIBLE)
            c.login(int(api or OVGD_API_VERSION))
            out["ok"] = True
            out["message"] = f"Bağlandı — API {cur} ({SUPPORT_LABEL_TR.get(out.get('support_level'), '')})"
            return out
        except auth_guard.AuthHalt as h:
            out.update(auth_halt=True, kind=h.kind, message=h.message)
            return out
        except HwApiError as e:
            out.update(kind=e.kind, message=e.message)
            return out
        finally:
            c.logout()
            c.http.close()

    # ── toplama ──────────────────────────────────────────────────────────────────────────────────────────────────
    def collect(self, parts: Iterable[str], *, since_alert: Optional[datetime] = None) -> HwSnapshot:
        parts = set(parts) & set(ALL_PARTS)
        snap = HwSnapshot()
        if PART_WARRANTY in parts:
            snap.not_measurable.append("Garanti: HPE OneView/OVGD API'sinde garanti uç noktası yok (not_measurable)")
        if self.mode == MODE_OVGD:
            self._collect_ovgd(parts, snap)
        else:
            self._collect_appliances(parts, snap)
        snap.not_measurable.append("Güvenlik durumu (securityStatus): hiçbir OneView API sürümünde yok")
        return snap

    def _collect_ovgd(self, parts: Set[str], snap: HwSnapshot) -> None:
        bases = appliance_hosts(self.row, self.meta)[:1]
        if not bases:
            raise HwApiError("client", "OVGD adresi zorunlu")
        base = bases[0]
        c = self._client(base, "ovgd")
        try:
            v = c.version()
            if v.get("minimumVersion") is not None and int(v["minimumVersion"]) > OVGD_API_VERSION:
                raise HwApiError("unsupported", f"OVGD en az API {v['minimumVersion']} istiyor.")
            c.login(OVGD_API_VERSION)
            snap.warnings.append("OVGD API v2 sözleşmesi (swagger) ile okunuyor; OVGD 3.00 için gerçek yanıt fixture'ı ile doğrulanmadı.")
            appliances = c.members("/rest/appliances", page=OVGD_PAGE)
            for a in appliances:
                key = a.get("id") or _tail(a.get("uri")) or str(a.get("applianceName"))
                ver = a.get("version")
                m = ManagerRec(key=str(key), kind="oneview", name=str(a.get("applianceName") or a.get("name") or key),
                               address=(a.get("applianceLocation") or a.get("hostname")), version=ver,
                               api_version=(str(a["currentApiVersion"]) if a.get("currentApiVersion") is not None else None),
                               support_level=support_for_version(ver), status="ok")
                if str(a.get("state") or "").lower() not in ("online", ""):
                    m.status, m.error = "error", f"Appliance durumu: {a.get('state')}"
                if m.support_level == SUPPORT_UNSUPPORTED:
                    m.status, m.error = "unsupported", f"OneView {ver} desteklenmiyor"
                snap.managers.append(m)
            snap.managers.append(ManagerRec(key="ovgd", kind="ovgd", name=self.row.label or "OVGD", address=base,
                                            version=None, api_version=str(v.get("currentVersion")),
                                            support_level=SUPPORT_COMPATIBLE, status="ok"))
            by_key = {m.key: m for m in snap.managers}
            if PART_INVENTORY in parts:
                snap.parts.add(PART_INVENTORY)
                for d in c.members("/rest/server-hardware", page=OVGD_PAGE):
                    akey = _tail(d.get("appluri")) or "ovgd"
                    s = norm_server(d, akey, web_url=base, is_ovgd=True)
                    if s:
                        snap.servers.append(s)
                for e in c.members("/rest/enclosures", page=OVGD_PAGE):
                    akey = _tail(e.get("appluri")) or "ovgd"
                    en = norm_enclosure(e, akey, is_ovgd=True)
                    if en:
                        snap.enclosures.append(en)
                names = {(en.manager_key, _tail(en.provider_ref.split("|", 1)[1])): en.name for en in snap.enclosures}
                for s in snap.servers:
                    if s.enclosure_ref:
                        s.enclosure_name = names.get((s.manager_key, s.enclosure_ref))
                counts: Dict[str, int] = {}
                for s in snap.servers:
                    counts[s.manager_key or ""] = counts.get(s.manager_key or "", 0) + 1
                for k, m in by_key.items():
                    m.server_count = counts.get(k, 0)
                    if m.status == "ok":
                        snap.complete_managers.add(k)
            if PART_ALERTS in parts:
                snap.parts.add(PART_ALERTS)
                for a in c.members("/rest/resource-alerts", params={"query": "alertState EQ 'Active'"},
                                   page=OVGD_PAGE, max_pages=10):
                    ar = norm_alert(a, _tail(a.get("appluri")) or "ovgd", is_ovgd=True)
                    if ar and ar.severity in (SEV_CRITICAL, SEV_WARNING):
                        snap.alerts.append(ar)
        finally:
            c.logout()
            c.http.close()

    def _collect_appliances(self, parts: Set[str], snap: HwSnapshot) -> None:
        hosts = appliance_hosts(self.row, self.meta)
        if not hosts:
            raise HwApiError("client", "Appliance adresi zorunlu")
        for base in hosts:
            key = re.sub(r"^https?://", "", base).lower()
            m = ManagerRec(key=key, kind="oneview", name=key, address=base)
            snap.managers.append(m)
            c = self._client(base, "oneview")
            try:
                v = c.version()
                cur = v.get("currentVersion")
                m.api_version = str(cur) if cur is not None else None
                m.support_level = support_for_api(int(cur) if cur else None)
                if m.support_level == SUPPORT_UNSUPPORTED:
                    m.status, m.error = "unsupported", f"OneView API {cur} desteklenmiyor"
                    continue
                if m.support_level != SUPPORT_VERIFIED:
                    snap.warnings.append(f"{key}: API {cur} “Doğrulanmış” sürüm değil; en iyi çaba ile okunuyor.")
                c.login(int(cur))                  # AuthHalt tüm döngüyü keser
                if PART_INVENTORY in parts:
                    encl = {}
                    for e in c.members("/rest/enclosures"):
                        en = norm_enclosure(e, key)
                        if en:
                            snap.enclosures.append(en)
                            encl[_tail(e.get("uri"))] = en.name
                    n = 0
                    for d in c.members("/rest/server-hardware"):
                        s = norm_server(d, key, web_url=base)
                        if s:
                            s.enclosure_name = encl.get(s.enclosure_ref) if s.enclosure_ref else None
                            snap.servers.append(s)
                            n += 1
                    snap.parts.add(PART_INVENTORY)
                    snap.complete_managers.add(key)
                    m.server_count = n
                if PART_ALERTS in parts:
                    try:
                        rows = c.members("/rest/alerts", params={"filter": "alertState='Active'"}, max_pages=10)
                    except HwApiError as e:
                        if e.kind != "client":
                            raise
                        rows = c.members("/rest/alerts", max_pages=5)   # filtre sözdizimi reddedildi → sınırlı, filtresiz
                        snap.warnings.append(f"{key}: alarm filtresi reddedildi; son kayıtlar filtresiz okundu.")
                    snap.parts.add(PART_ALERTS)
                    for a in rows:
                        ar = norm_alert(a, key)
                        if ar and ar.state == "active" and ar.severity in (SEV_CRITICAL, SEV_WARNING):
                            snap.alerts.append(ar)
                m.status = "ok"
            except HwApiError as e:
                m.status, m.error = "error", e.message          # ağ/TLS/5xx: bu appliance atlanır, diğerleri sürer
                snap.warnings.append(f"{key}: {e.message}")
            finally:
                c.logout()
                c.http.close()
