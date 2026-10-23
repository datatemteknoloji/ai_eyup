"""Donanım sağlayıcıları — GERÇEK HTTP taşıması (127.0.0.1 döngü adresi; dış ağa ÇIKMAZ).

`test_hw_framework.py` sahte oturum kullanır; burada `requests` + soket katmanı da çalışır: sayfalama
(OME `$top/$skip`, OneView/OVGD `start/count`), 401'de tek istek + hesap kilidi koruması, zaman aşımı (sınırlı yeniden
deneme, kilitlemez), oturum aç/kapat ve salt-okunur allowlist (sunucuya yalnız izinli yöntem/yol gelir).
İzole geçici DB kullanır.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import pytest

from app.models.hw import HwServer
from app.services.hw import auth_guard, endpoints as ep, sync
from app.services.hw.constants import KIND_HPE
from app.services.hw.dell_ome import DellOmeProvider
from app.services.hw.http import HwHttp
from app.services.hw.oneview import HpeProvider
from app.tests import hw_fakes as F

Handler = Callable[[str, str, Dict[str, str], Any], Tuple[int, Any, Dict[str, str]]]


class LoopbackServer:
    """Gerçek TCP sunucusu; `handler(method, path, params, body) -> (status, body, headers)`. Tüm istekleri kaydeder."""

    def __init__(self, handler: Handler):
        self.log: List[Tuple[str, str, Dict[str, str]]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # sessiz
                pass

            def _do(self):
                u = urlparse(self.path)
                params = {k: v[0] for k, v in parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                outer.log.append((self.command, u.path, params))
                status, payload, hdrs = handler(self.command, u.path, params, body)
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if data:
                    self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _do

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._t.start()

    def count(self, method: str | None = None, prefix: str = "") -> int:
        return sum(1 for m, p, _ in self.log if (method is None or m == method) and p.startswith(prefix))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def servers():
    made: List[LoopbackServer] = []

    def make(handler: Handler) -> LoopbackServer:
        s = LoopbackServer(handler)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


@pytest.fixture()
def db(isolated_db):
    return isolated_db


def _page(items: List[Any], params: Dict[str, str], top: str, skip: str) -> List[Any]:
    t, s = int(params.get(top, len(items))), int(params.get(skip, 0))
    return items[s:s + t]


# ── Dell OME ────────────────────────────────────────────────────────────────────────────────────────────────────

def _ome_handler(n_devices: int, *, login_status: int = 201, slow_path: str = "", slow_sec: float = 0.0) -> Handler:
    devices = [{"Id": 20000 + i, "DeviceName": f"ome-srv-{i:04d}", "Model": "PowerEdge R650", "Type": 1000,
                "Identifier": f"SN{i:06d}", "DeviceServiceTag": f"SN{i:06d}", "Status": 1000 if i % 7 else 4000,
                "PowerState": 17, "ConnectionState": True,
                "DeviceManagement": [{"NetworkAddress": f"10.30.{i // 250}.{i % 250 + 1}",
                                      "ManagementProfile": [{"AgentName": "iDRAC", "Version": "6.10.30.00"}]}]}
               for i in range(n_devices)]

    def h(method, path, params, body):
        if method == "POST" and path == "/api/SessionService/Sessions":
            if login_status != 201:
                return login_status, {"error": {"code": "bad"}}, {}
            return 201, {"Id": "guid-lb"}, {"X-Auth-Token": "tok-lb"}
        if method == "DELETE" and path.startswith("/api/SessionService/Sessions("):
            return 204, None, {}
        if slow_path and path == slow_path:
            time.sleep(slow_sec)
        if path == "/api/ApplicationService/Info":
            return 200, {"Name": "OpenManage Enterprise", "Version": "4.7.0"}, {}
        if path == "/api/GroupService/Groups":
            return 200, {"value": [{"Id": 1, "Name": "All Devices"}]}, {}
        if path.endswith("/AllLeafDeviceSummaries"):
            return 200, {"value": _page(devices, params, "$top", "$skip"), "@odata.count": len(devices)}, {}
        if path == "/api/AlertService/Alerts":
            return 200, {"value": [], "@odata.count": 0}, {}
        if path == "/api/WarrantyService/Warranties":
            return 200, {"value": [], "@odata.count": 0}, {}
        return 404, {}, {}

    return h


def _ome_provider(row, srv: LoopbackServer, **kw) -> DellOmeProvider:
    http = HwHttp(srv.base, "ome", sleep=lambda *_: None, timeout=kw.pop("timeout", (2, 5)))
    return DellOmeProvider(row, http=http)


def test_ome_pagination_over_real_http_and_persist(db):
    srv = LoopbackServer(_ome_handler(1200))
    try:
        row = F.make_row(db, endpoint="127.0.0.1")
        res = sync.sync_instance(db, row, force=True, provider=_ome_provider(row, srv))
        assert res["ok"] is True, res
        assert srv.count("GET", "/api/GroupService/Groups(1)/AllLeafDeviceSummaries") == 3     # PAGE=500 → 500+500+200
        assert srv.count("POST") == 1 and srv.count("DELETE") == 1                              # tek oturum aç/kapat
        assert db.query(HwServer).filter(HwServer.instance_id == row.id).count() == 1200
        # sunucuya yalnız izinli (yöntem, yol) geldi
        for m, p, _ in srv.log:
            assert ep.allowed("ome", m, p) or (m == "DELETE" and ep.OME_LOGOUT[1].match(p)), (m, p)
    finally:
        srv.close()


def test_ome_bad_password_one_request_then_silence_over_real_http(db):
    srv = LoopbackServer(_ome_handler(10, login_status=401))
    try:
        row = F.make_row(db, endpoint="127.0.0.1", password="wrong")
        res = sync.sync_instance(db, row, force=True, provider=_ome_provider(row, srv))
        assert res["ok"] is False and res.get("auth_halted") is True
        assert len(srv.log) == 1 and srv.count("POST") == 1                                     # sunucu YALNIZ 1 istek gördü
        db.refresh(row)
        assert auth_guard.is_halted(row) and row.last_status == "auth_failed"
        for force in (False, True):                                                              # sonraki turlar hiç istek yapmaz
            r2 = sync.sync_instance(db, row, force=force, provider=_ome_provider(row, srv))
            assert r2.get("skipped") == "auth_halted"
        assert len(srv.log) == 1
    finally:
        srv.close()


def test_ome_timeout_bounded_retries_and_does_not_halt(db):
    srv = LoopbackServer(_ome_handler(10, slow_path="/api/GroupService/Groups", slow_sec=1.5))
    try:
        row = F.make_row(db, endpoint="127.0.0.1")
        t0 = time.time()
        res = sync.sync_instance(db, row, force=True, provider=_ome_provider(row, srv, timeout=(1, 0.3)))
        assert res["ok"] is False and not res.get("auth_halted")
        # Groups: ilk deneme + RETRY_MAX(2) yeniden deneme = 3 (üstel bekleme testte uykusuz); sonsuz döngü yok
        assert srv.count("GET", "/api/GroupService/Groups") == 3
        assert srv.count("POST") == 1                                                            # her tur tek oturum açma
        assert time.time() - t0 < 20
        db.refresh(row)
        assert not auth_guard.is_halted(row)                                                     # ağ hatası hesabı KİLİTLEMEZ
    finally:
        srv.close()


# ── HPE OneView (appliance) ve OVGD ─────────────────────────────────────────────────────────────────────────────

def _blade(i: int, prefix: str = "ov") -> Dict[str, Any]:
    return {"uri": f"/rest/server-hardware/{prefix}{i:05d}", "name": f"{prefix}-blade-{i:04d}", "serverName": f"{prefix}-host-{i}",
            "model": "ProLiant DL360 Gen10", "serialNumber": f"CZ{prefix}{i:06d}", "uuid": f"{i:08x}-0000-4000-8000-{i:012x}",
            "formFactor": "RackServer", "locationUri": None, "powerState": "On", "status": "OK" if i % 5 else "Critical",
            "mpModel": "iLO5", "mpHostInfo": {"mpIpAddresses": [{"address": f"10.50.{i // 250}.{i % 250 + 1}", "type": "Static"}]}}


def _members(items: List[Any], params: Dict[str, str]) -> Dict[str, Any]:
    start, count = int(params.get("start", 0)), int(params.get("count", len(items)))
    mem = items[start:start + count]
    out: Dict[str, Any] = {"members": mem, "total": len(items), "start": start, "count": len(mem)}
    if start + count < len(items):
        out["nextPageUri"] = f"/rest/x?start={start + count}&count={count}"
    return out


def _ov_handler(n: int, *, login_status: int = 200, prefix: str = "ov") -> Handler:
    blades = [_blade(i, prefix) for i in range(n)]

    def h(method, path, params, body):
        p = path.rstrip("/")
        if p == "/rest/version":
            return 200, {"minimumVersion": 120, "currentVersion": 9000}, {}
        if method == "POST" and p == "/rest/login-sessions":
            if login_status != 200:
                return login_status, {"errorCode": "AUTHN_AUTH_FAIL"}, {}
            return 200, {"sessionID": "sess-lb"}, {}
        if method == "DELETE" and p == "/rest/login-sessions":
            return 204, None, {}
        if p == "/rest/enclosures":
            return 200, {"members": [], "total": 0}, {}
        if p == "/rest/server-hardware":
            return 200, _members(blades, params), {}
        if p == "/rest/alerts":
            return 200, {"members": [], "total": 0}, {}
        return 404, {}, {}

    return h


def test_oneview_pagination_over_real_http(db):
    srv = LoopbackServer(_ov_handler(450))
    try:
        row = F.make_row(db, kind=KIND_HPE, endpoint="ov-lb.example", meta={"mode": "oneview"})

        def factory(base, product):
            return HwHttp(srv.base, product, sleep=lambda *_: None, timeout=(2, 5))

        res = sync.sync_instance(db, row, force=True, provider=HpeProvider(row, http_factory=factory))
        assert res["ok"] is True, res
        assert srv.count("GET", "/rest/server-hardware") == 3                                    # PAGE=200 → 200+200+50
        assert srv.count("POST") == 1 and srv.count("DELETE") == 1
        assert db.query(HwServer).filter(HwServer.instance_id == row.id).count() == 450
        for m, p, _ in srv.log:
            assert ep.allowed("oneview", m, p) or m == "DELETE", (m, p)
    finally:
        srv.close()


def test_oneview_shared_account_24_appliances_real_http_stops_at_first_401(db):
    srvs = [LoopbackServer(_ov_handler(5, login_status=401, prefix=f"a{i}")) for i in range(3)]
    try:
        hosts = [f"ov{i:02d}.example" for i in range(24)]
        row = F.make_row(db, kind=KIND_HPE, endpoint=hosts[0], meta={"mode": "oneview", "appliances": hosts[1:]},
                         password="wrong")
        by_host = {f"https://{h}": srvs[i % 3] for i, h in enumerate(hosts)}

        def factory(base, product):
            srv = by_host.get(base) or srvs[0]
            return HwHttp(srv.base, product, sleep=lambda *_: None, timeout=(2, 5))

        res = sync.sync_instance(db, row, force=True, provider=HpeProvider(row, http_factory=factory))
        assert res.get("auth_halted") is True
        assert sum(s.count("POST") for s in srvs) == 1                                           # 24 appliance'ın YALNIZ ilki denendi
        db.refresh(row)
        assert auth_guard.is_halted(row)
    finally:
        for s in srvs:
            s.close()


def test_ovgd_pagination_and_single_session_over_real_http(db):
    servers_n = 700
    blades = [{**_blade(i, "gd"), "originalUri": f"/rest/server-hardware/gd{i:05d}", "appluri": f"/rest/appliances/app{i % 24:02d}"}
              for i in range(servers_n)]
    appliances = [{"id": f"app{i:02d}", "uri": f"/rest/appliances/app{i:02d}", "applianceName": f"ov{i:02d}", "state": "Online",
                   "version": "8.60.00-0481310", "currentApiVersion": 4200, "applianceLocation": f"ov{i:02d}.example"}
                  for i in range(24)]

    def h(method, path, params, body):
        p = path.rstrip("/")
        if p == "/rest/version":
            return 200, {"minimumVersion": 2, "currentVersion": 2}, {}
        if method == "POST" and p == "/rest/login-sessions":
            return 200, {"token": "tok-gd"}, {}
        if method == "DELETE" and p == "/rest/login-sessions":
            return 204, None, {}
        if p == "/rest/appliances":
            return 200, _members(appliances, params), {}
        if p == "/rest/server-hardware":
            return 200, _members(blades, params), {}
        if p in ("/rest/enclosures", "/rest/resource-alerts"):
            return 200, {"members": [], "total": 0}, {}
        return 404, {}, {}

    srv = LoopbackServer(h)
    try:
        row = F.make_row(db, kind=KIND_HPE, endpoint="ovgd.example", meta={"mode": "ovgd"})

        def factory(base, product):
            return HwHttp(srv.base, product, sleep=lambda *_: None, timeout=(2, 5))

        res = sync.sync_instance(db, row, force=True, provider=HpeProvider(row, http_factory=factory))
        assert res["ok"] is True, res
        assert srv.count("POST") == 1 and srv.count("DELETE") == 1                               # 24 appliance → TEK OVGD oturumu
        assert srv.count("GET", "/rest/server-hardware") == 2                                    # OVGD_PAGE=500 → 500+200
        assert db.query(HwServer).filter(HwServer.instance_id == row.id).count() == servers_n
        for m, p, _ in srv.log:
            assert ep.allowed("ovgd", m, p) or m == "DELETE", (m, p)
    finally:
        srv.close()
