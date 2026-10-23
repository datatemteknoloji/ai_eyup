"""Donanım testleri için sahte HTTP oturumu (ağa ÇIKMAZ) + doküman örneklerinden türetilmiş fixture'lar."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.services.hw.http import HwHttp


class FakeResp:
    def __init__(self, status: int = 200, body: Any = None, headers: Optional[Dict[str, str]] = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def close(self):
        pass


Router = Callable[[str, str, Dict[str, Any], Any, Dict[str, str]], Tuple[int, Any, Dict[str, str]]]


class FakeSession:
    """`router(method, path, params, json_body, headers) -> (status, body, headers)`."""

    def __init__(self, router: Router):
        self.router = router
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []

    def request(self, method, url, params=None, json=None, headers=None, verify=None, timeout=None,
                allow_redirects=None):
        path = urlparse(url).path
        self.calls.append((method, path, dict(params or {})))
        status, body, hdrs = self.router(method, path, dict(params or {}), json, dict(headers or {}))
        return FakeResp(status, body, hdrs)

    def close(self):
        pass

    def count(self, method: Optional[str] = None, path_prefix: str = "") -> int:
        return sum(1 for m, p, _ in self.calls if (method is None or m == method) and p.startswith(path_prefix))


def http_for(router: Router, base: str, product: str) -> Tuple[HwHttp, FakeSession]:
    sess = FakeSession(router)
    return HwHttp(base, product, session=sess, sleep=lambda *_: None), sess


# ── Dell OME fixture'ları (alanlar docs/plans/hw-api-sources.md ile aynı) ─────────────────────────────────────────
OME_SERVER = {
    "Id": 10073, "DeviceName": "esx-blade-01.kfs.local", "Model": "PowerEdge M640", "Type": 1000,
    "Identifier": "ABC1234", "DeviceServiceTag": "abc1234", "Status": 1000, "PowerState": 17, "ConnectionState": True,
    "ManagedState": 3000, "IpAddress": "10.1.1.5", "ChassisName": "MX7000-A", "SlotName": "Sled-3",
    "DeviceManagement": [{"NetworkAddress": "10.20.30.41",
                          "ManagementProfile": [{"AgentName": "iDRAC", "Version": "4.40.00.00"}]}],
}
OME_RACK = {
    "Id": 10074, "DeviceName": "lin-db-02", "Model": "PowerEdge R740", "Type": 1000, "Identifier": "XYZ9876",
    "DeviceServiceTag": "XYZ9876", "Status": 4000, "PowerState": 17, "ConnectionState": True,
    "DeviceManagement": [{"NetworkAddress": "10.20.30.42",
                          "ManagementProfile": [{"AgentName": "iDRAC", "Version": "5.10.50.00"}]}],
}
OME_CHASSIS = {"Id": 10100, "DeviceName": "MX7000-A", "Model": "PowerEdge MX7000", "Type": 2000,
               "DeviceServiceTag": "CHS0001", "Status": 1000}
OME_ALERT = {"Id": 5001, "SeverityType": 16, "AlertDeviceId": 10074, "CategoryName": "Storage",
             "TimeStamp": "2026-10-23 10:00:00.000", "Message": "Drive 3 failed", "AlertMessageId": "PDR1016"}
OME_ALERT_INFO = {"Id": 5002, "SeverityType": 2, "AlertDeviceId": 10074, "CategoryName": "Audit",
                  "TimeStamp": "2026-10-23 10:01:00.000", "Message": "User login"}
OME_WARRANTY = {"Id": 1, "DeviceId": 10074, "DeviceIdentifier": "XYZ9876", "ServiceLevelDescription": "ProSupport",
                "ServiceProvider": "Dell", "StartDate": "2021-01-01 00:00:00.000", "EndDate": "2026-01-01 00:00:00.000"}


def ome_router(*, login_status: int = 201, version: str = "4.7.0", devices=None, alerts=None, warranties=None,
               mid_status: Optional[int] = None) -> Router:
    devices = devices if devices is not None else [OME_SERVER, OME_RACK, OME_CHASSIS]
    alerts = alerts if alerts is not None else [OME_ALERT, OME_ALERT_INFO]
    warranties = warranties if warranties is not None else [OME_WARRANTY]

    def router(method, path, params, body, headers):
        if method == "POST" and path == "/api/SessionService/Sessions":
            if login_status != 201:
                return login_status, {"error": "bad"}, {}
            return 201, {"Id": "guid-1"}, {"X-Auth-Token": "tok"}
        if method == "DELETE" and path.startswith("/api/SessionService/Sessions("):
            return 204, None, {}
        if mid_status and method == "GET" and path != "/api/ApplicationService/Info":
            return mid_status, {}, {}
        if path == "/api/ApplicationService/Info":
            return 200, {"Name": "OpenManage Enterprise", "Version": version}, {}
        if path == "/api/GroupService/Groups":
            return 200, {"value": [{"Id": 500, "Name": "Custom"}, {"Id": 1, "Name": "All Devices"}]}, {}
        if path.endswith("/AllLeafDeviceSummaries"):
            return 200, {"value": devices, "@odata.count": len(devices)}, {}
        if path == "/api/AlertService/Alerts":
            return 200, {"value": alerts, "@odata.count": len(alerts)}, {}
        if path == "/api/WarrantyService/Warranties":
            return 200, {"value": warranties, "@odata.count": len(warranties)}, {}
        return 404, {}, {}

    return router


# ── HPE OneView fixture'ları ────────────────────────────────────────────────────────────────────────────────────
OV_ENCL = {"uri": "/rest/enclosures/09SGH1", "name": "Encl-1", "model": "Synergy 12000 Frame", "serialNumber": "09SGH1",
           "status": "OK", "deviceBayCount": 12}
OV_BLADE = {"uri": "/rest/server-hardware/37333036", "name": "Encl-1, bay 3", "serverName": "esx-hpe-03",
            "model": "Synergy 480 Gen10", "serialNumber": "mxq1234abc", "uuid": "37333036-3831-4D32-3234-303930344D31",
            "formFactor": "HalfHeight", "locationUri": "/rest/enclosures/09SGH1", "position": 3, "powerState": "On",
            "status": "OK", "romVersion": "I42 v2.40", "mpModel": "iLO5", "mpFirmwareVersion": "2.72",
            "mpHostInfo": {"mpHostName": "ilo-03", "mpIpAddresses": [{"address": "10.9.9.3", "type": "Static"}]},
            "processorCount": 2, "memoryMb": 262144}
OV_RACK = {"uri": "/rest/server-hardware/99999", "name": "rack-7", "serverName": "lin-hpe-07", "model": "ProLiant DL380 Gen10",
           "serialNumber": "CZ12345678", "uuid": "11111111-2222-3333-4444-555555555555", "formFactor": "RackServer",
           "locationUri": None, "powerState": "On", "status": "Critical", "mpModel": "iLO5",
           "mpHostInfo": {"mpIpAddresses": [{"address": "10.9.9.7", "type": "Static"}]}}
OV_ALERT = {"uri": "/rest/alerts/77", "severity": "Critical", "alertState": "Active", "description": "Fan failed",
            "alertTypeID": "hpOneView.fanFailed", "physicalResourceType": "server-hardware",
            "associatedResource": {"resourceUri": "/rest/server-hardware/99999", "resourceName": "rack-7"}, "created": "2026-10-23T09:00:00.000Z"}


def oneview_router(*, login_status: int = 200, api: int = 9000, calls_log: Optional[list] = None) -> Router:
    def router(method, path, params, body, headers):
        if calls_log is not None:
            calls_log.append((method, path))
        if path == "/rest/version":
            return 200, {"minimumVersion": 120, "currentVersion": api}, {}
        if method == "POST" and path == "/rest/login-sessions":
            if login_status != 200:
                return login_status, {"errorCode": "AUTHN_AUTH_FAIL"}, {}
            return 200, {"sessionID": "sess-1"}, {}
        if method == "DELETE" and path == "/rest/login-sessions":
            return 204, None, {}
        if path == "/rest/enclosures":
            return 200, {"members": [OV_ENCL], "total": 1}, {}
        if path == "/rest/server-hardware":
            return 200, {"members": [OV_BLADE, OV_RACK], "total": 2}, {}
        if path == "/rest/alerts":
            return 200, {"members": [OV_ALERT], "total": 1}, {}
        return 404, {}, {}

    return router


def make_row(db, *, kind: str = "dell_ome", endpoint: str = "ome.example", username: str = "viewer",
             password: str = "pw", meta: Optional[Dict[str, Any]] = None, enabled: bool = True, label: str = "_t_hw"):
    from app.core.encryption import encrypt_secret
    from app.models.integration_instance import IntegrationInstance
    row = IntegrationInstance(category="hardware", kind=kind, label=label, endpoint=endpoint, enabled=enabled,
                              verify_ssl=False, last_status="never", sync_interval_sec=900,
                              credential_ref=encrypt_secret(json.dumps({"username": username, "password": password})),
                              meta_json=json.dumps(meta or {}))
    db.add(row)
    db.commit()
    return row
