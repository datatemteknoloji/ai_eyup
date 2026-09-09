"""
VCenterClient.get_all_vm_perf_io / get_vm_perf_io — "veri yok" ile "ölçüldü ve
sıfırdı" ayrımı.

Regresyon: sayaç ID'si bulunduğu (`found`de var) ama QueryPerf o VM için hiç
örnek döndürmediğinde (`sums` boş) kod `0.0` yazıyordu. Bu, "disk latency her
VM'de 0ms" gibi yanıltıcı bir veri kümesi üretiyordu — host tarafında AYNI
sınıf hata zaten `_reduce_instances`'ta "veri yoksa None döner" ilkesiyle
düzeltilmişti (bkz. o fonksiyonun docstring'i), VM tarafında bu iki fonksiyon
gözden kaçmıştı.
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


# counterId 10 = read IOPS (bir örnek: 0 → GERÇEKTEN ölçülmüş sıfır IOPS,
# 0.0 dönmeli). counterId 11 = write IOPS (örnek yok → None dönmeli).
# counterId 12 = disk latency (örnek yok → None dönmeli, 0.0 DEĞİL).
_QUERYPERF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
<soapenv:Body>
<QueryPerfResponse xmlns="urn:vim25">
<returnval>
<entity type="VirtualMachine">vm-101</entity>
<value><id><counterId>10</counterId><instance>scsi0:0</instance></id><value>0</value></value>
</returnval>
</QueryPerfResponse>
</soapenv:Body>
</soapenv:Envelope>"""


def test_get_all_vm_perf_io_returns_none_when_counter_has_no_samples(monkeypatch):
    client = _client()
    fake_session = MagicMock()
    fake_session.post.return_value = _fake_soap_response(_QUERYPERF_XML)
    monkeypatch.setattr(client, "_soap_login", lambda: fake_session)
    monkeypatch.setattr(
        client, "_perf_manager_and_counters",
        lambda soap_session, soap_url: (
            "perfMgr-1",
            {"read": 10, "write": 11, "disk_latency": 12},
        ),
    )

    result = client.get_all_vm_perf_io(["vm-101"])

    row = result["vm-101"]
    # Gerçekten örneklenmiş sıfır IOPS → 0.0 (veri VAR, değer sıfır)
    assert row["disk_read_iops"] == 0.0
    # Hiç örnek gelmeyen sayaçlar → None (veri YOK, "ölçülmedi" ile "sıfır
    # ölçüldü" birbirine karışmamalı)
    assert row["disk_write_iops"] is None
    assert row["disk_latency_ms"] is None


def test_get_vm_perf_io_single_vm_same_none_semantics(monkeypatch):
    client = _client()
    fake_session = MagicMock()
    fake_session.post.return_value = _fake_soap_response(_QUERYPERF_XML)
    monkeypatch.setattr(client, "_soap_login", lambda: fake_session)
    monkeypatch.setattr(
        client, "_perf_manager_and_counters",
        lambda soap_session, soap_url: (
            "perfMgr-1",
            {"read": 10, "write": 11, "disk_latency": 12},
        ),
    )

    result = client.get_vm_perf_io("vm-101")

    assert result["disk_read_iops"] == 0.0
    assert result["disk_write_iops"] is None
    assert result["disk_latency_ms"] is None
