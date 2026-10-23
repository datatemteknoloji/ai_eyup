"""Donanım sağlayıcı istemcilerinin ÇAĞIRABİLECEĞİ tüm uçlar (tek kaynak).

`docs/plans/hw-api-sources.md` ile birebir tutarlıdır (test_hw_api_sources.py). İstemci bu listenin dışına
çıkamaz: GET yalnız `GET_PATTERNS`, POST yalnız oturum açma, DELETE yalnız oturum kapatma. `FORBIDDEN` kalıpları
(konsol/SSO/güç/yazma) her durumda reddedilir.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ── Dell OME 4.7.0 ──────────────────────────────────────────────────────────────────────────────────────────────
OME_LOGIN = ("POST", "/api/SessionService/Sessions")
OME_LOGOUT = ("DELETE", re.compile(r"^/api/SessionService/Sessions\('?[0-9A-Za-z-]+'?\)$"))
OME_GET: List[str] = [
    r"^/api/ApplicationService/Info$",
    r"^/api/GroupService/Groups$",
    r"^/api/GroupService/Groups\(\d+\)/AllLeafDeviceSummaries$",
    r"^/api/DeviceService/Devices\(\d+\)/InventoryDetails\('deviceSoftware'\)$",
    r"^/api/DeviceService/Devices\(\d+\)/InventoryDetails\('deviceLocation'\)$",
    r"^/api/AlertService/Alerts$",
    r"^/api/WarrantyService/Warranties$",
]

# ── HPE OneView (appliance) ─────────────────────────────────────────────────────────────────────────────────────
ONEVIEW_LOGIN = ("POST", "/rest/login-sessions")
ONEVIEW_LOGOUT = ("DELETE", "/rest/login-sessions")
ONEVIEW_GET: List[str] = [
    r"^/rest/version$",
    r"^/rest/server-hardware$",
    r"^/rest/enclosures$",
    r"^/rest/alerts$",
]

# ── HPE OVGD (API v2) ───────────────────────────────────────────────────────────────────────────────────────────
OVGD_LOGIN = ("POST", "/rest/login-sessions/")
OVGD_LOGOUT = ("DELETE", "/rest/login-sessions/")
OVGD_GET: List[str] = [
    r"^/rest/version$",
    r"^/rest/appliances$",
    r"^/rest/resource-alerts$",
    r"^/rest/server-hardware$",
    r"^/rest/enclosures$",
]

# Her durumda reddedilen kalıplar (konsol / SSO / güç / sanal medya / oturum anahtarı / yazma)
FORBIDDEN = re.compile(
    r"(VirtualSession|BlinkStatus|/Actions|remoteConsole|javaRemoteConsole|iloSsoUrl|oaSsoUrl|/sso\b|"
    r"mpSessionKey|powerState|refreshState|mpFirmwareVersion|environmentalConfiguration|/discovery)",
    re.I,
)

GET_PATTERNS: Dict[str, List[re.Pattern]] = {
    "ome": [re.compile(p) for p in OME_GET],
    "oneview": [re.compile(p) for p in ONEVIEW_GET],
    "ovgd": [re.compile(p) for p in OVGD_GET],
}
LOGIN: Dict[str, Tuple[str, str]] = {"ome": OME_LOGIN, "oneview": ONEVIEW_LOGIN, "ovgd": OVGD_LOGIN}
LOGOUT: Dict[str, Tuple[str, object]] = {"ome": OME_LOGOUT, "oneview": ONEVIEW_LOGOUT, "ovgd": OVGD_LOGOUT}


def allowed(product: str, method: str, path: str) -> bool:
    """(ürün, yöntem, yol[sorgusuz]) izinli mi?"""
    method = method.upper()
    if FORBIDDEN.search(path):
        return False
    if method == "GET":
        return any(p.match(path) for p in GET_PATTERNS.get(product, []))
    if method == "POST":
        return path.rstrip("/") == LOGIN[product][1].rstrip("/") and method == LOGIN[product][0]
    if method == "DELETE":
        m, pat = LOGOUT[product]
        if m != method:
            return False
        if isinstance(pat, re.Pattern):
            return bool(pat.match(path))
        return path.rstrip("/") == str(pat).rstrip("/")
    return False


def all_documented_paths() -> List[str]:
    """Kaynak kaydı testi için: kodda kullanılan tüm uç yolları (şablon biçiminde)."""
    return sorted(set(OME_GET + ONEVIEW_GET + OVGD_GET))
