"""
VCenterClient.get_all_vm_live_stats — VMware Tools ÇALIŞMA durumu toplama.

Regresyon: `get_vm_full_details()` VM'in Tools çalışma durumunu
`guest/identity` REST cevabından (`guest.get("tools_status")`) okumaya
çalışıyordu ama o endpoint (`/vcenter/vm/{vm}/guest/identity`) bu alanı HİÇ
döndürmez — `Server.vm_tools_status` DB'de her zaman NULL kalıyordu (20
soruluk denetimde "VMware Tools çalışmayan VM'leri bul" sorusu bu yüzden
cevapsız kalıyordu). Gerçek kaynak SOAP `guest.toolsRunningStatus` — bu artık
`get_all_vm_live_stats()` ile toplanıp `metric_sync.py` tarafından
`Server.vm_tools_status`'a yazılıyor.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.services.vmware.vcenter_client import VCenterClient


def _client() -> VCenterClient:
    return VCenterClient(host="vc.example.local", username="u", password="p", port=443)


def _fake_soap_response(text: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


_LIVE_STATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
<soapenv:Body>
<RetrievePropertiesResponse xmlns="urn:vim25">
<returnval>
<obj type="VirtualMachine">vm-101</obj>
<propSet><name>name</name><val>web01</val></propSet>
<propSet><name>runtime.powerState</name><val>poweredOn</val></propSet>
<propSet><name>guest.toolsVersionStatus2</name><val>guestToolsNeedUpgrade</val></propSet>
<propSet><name>guest.toolsRunningStatus</name><val>guestToolsNotRunning</val></propSet>
</returnval>
</RetrievePropertiesResponse>
</soapenv:Body>
</soapenv:Envelope>"""


def test_get_all_vm_live_stats_parses_tools_running_and_version_status(monkeypatch):
    client = _client()
    fake_session = MagicMock()
    fake_session.post.return_value = _fake_soap_response(_LIVE_STATS_XML)
    monkeypatch.setattr(client, "_soap_login", lambda: fake_session)
    monkeypatch.setattr(client, "_get_root_folder", lambda soap_session, soap_url: "group-d1")

    results = client.get_all_vm_live_stats()

    assert len(results) == 1
    vm = results[0]
    assert vm["name"] == "web01"
    assert vm["tools_version_status"] == "guestToolsNeedUpgrade"
    assert vm["tools_running_status"] == "guestToolsNotRunning"
