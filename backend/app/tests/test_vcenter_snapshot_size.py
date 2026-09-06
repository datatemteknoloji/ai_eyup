"""
VCenterClient snapshot tree parsing + per-snapshot boyut hesabı testleri.

Regresyon: `_list_snapshots_soap` yalnızca `rootSnapshotList` tag'ini kabul
ediyordu — ağaçtaki `childSnapshotList` (alt/torun) snapshot'lar sessizce
kayboluyordu. Gerçek bir vCenter ortamında doğrulanan iki-seviyeli bir
snapshot ağacı (root + 1 child) burada mock'lanır.
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


_SNAPSHOT_TREE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/"
 xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:xsd="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<soapenv:Body>
<RetrievePropertiesResponse xmlns="urn:vim25"><returnval><obj type="VirtualMachine">vm-9026</obj>\
<propSet><name>snapshot</name><val xsi:type="VirtualMachineSnapshotInfo">\
<currentSnapshot type="VirtualMachineSnapshot">snapshot-11017</currentSnapshot>\
<rootSnapshotList><snapshot type="VirtualMachineSnapshot">snapshot-11015</snapshot>\
<vm type="VirtualMachine">vm-9026</vm><name>ddwwd</name><description>q</description>\
<createTime>2025-12-15T18:47:39.073973Z</createTime><state>poweredOff</state>\
<quiesced>true</quiesced><childSnapshotList>\
<snapshot type="VirtualMachineSnapshot">snapshot-11017</snapshot>\
<vm type="VirtualMachine">vm-9026</vm><name>dsdddd</name>\
<description>Bulk snapshot from IP input</description>\
<createTime>2025-12-15T18:54:18.992114Z</createTime><state>poweredOff</state>\
<quiesced>true</quiesced></childSnapshotList></rootSnapshotList></val></propSet>\
</returnval></RetrievePropertiesResponse>
</soapenv:Body>
</soapenv:Envelope>"""


def test_list_snapshots_soap_includes_nested_child_snapshot(monkeypatch):
    client = _client()
    fake_session = MagicMock()
    fake_session.post.return_value = _fake_soap_response(_SNAPSHOT_TREE_XML)
    monkeypatch.setattr(client, "_soap_login", lambda: fake_session)

    result = client._list_snapshots_soap("vm-9026")

    ids = {s["id"] for s in result}
    assert ids == {"snapshot-11015", "snapshot-11017"}, (
        "childSnapshotList içindeki snapshot kaybolmamalı (regresyon testi)"
    )
    root = next(s for s in result if s["id"] == "snapshot-11015")
    child = next(s for s in result if s["id"] == "snapshot-11017")
    assert root["name"] == "ddwwd"
    assert child["name"] == "dsdddd"
    assert child["description"] == "Bulk snapshot from IP input"


def test_get_vm_snapshot_sizes_assigns_deltas_in_chain_order(monkeypatch):
    """
    disk.diskFile zinciri = [base, delta1, delta2]; iki snapshot linear sırayla
    (snapshot-11015 sonra snapshot-11017) oluşturulmuş — i. snapshot i. delta'yı
    'yaratmış' sayılmalı (RVTools/PowerCLI ile aynı mantık).
    """
    client = _client()

    layout = {
        "disks": {
            "2000": [
                "[datastore2] enes-94-clone/enes-94-clone_2.vmdk",
                "[datastore2] enes-94-clone/enes-94-clone_2-000001.vmdk",
                "[datastore2] enes-94-clone/enes-94-clone_2-000002.vmdk",
            ]
        },
        "snapshots": {
            "snapshot-11015": ["[datastore2] enes-94-clone/enes-94-clone_2.vmdk"],
            "snapshot-11017": [
                "[datastore2] enes-94-clone/enes-94-clone_2.vmdk",
                "[datastore2] enes-94-clone/enes-94-clone_2-000001.vmdk",
            ],
        },
    }
    monkeypatch.setattr(client, "_get_vm_layout_soap", lambda vm_id: layout)
    monkeypatch.setattr(client, "_soap_login", lambda: MagicMock())
    monkeypatch.setattr(
        client, "_list_snapshots_soap",
        lambda vm_id: [
            {"id": "snapshot-11015", "create_time": "2025-12-15T18:47:39Z"},
            {"id": "snapshot-11017", "create_time": "2025-12-15T18:54:18Z"},
        ],
    )
    monkeypatch.setattr(
        client, "_get_datastore_browser_map",
        lambda soap_session, soap_url: {"datastore2": "datastoreBrowser-12"},
    )

    def _fake_search(soap_session, soap_url, browser_ref, ds_name, folder, filenames):
        # Gerçek datastore: descriptor ~1KB + delta extent = asıl boyut
        sizes = {
            "enes-94-clone_2-000001.vmdk": 900,
            "enes-94-clone_2-000001-delta.vmdk": 1_000_000,
            "enes-94-clone_2-000002.vmdk": 950,
            "enes-94-clone_2-000002-delta.vmdk": 2_000_000,
        }
        return {f: sizes[f] for f in filenames if f in sizes}

    monkeypatch.setattr(client, "_search_datastore_file_sizes", _fake_search)

    sizes = client.get_vm_snapshot_sizes("vm-9026")

    assert sizes["snapshot-11015"]["size_bytes"] == 900 + 1_000_000
    assert sizes["snapshot-11017"]["size_bytes"] == 950 + 2_000_000
    assert sizes["snapshot-11015"]["exact"] is True
    assert sizes["snapshot-11017"]["exact"] is True


def test_vmdk_size_candidates_include_extents():
    c = VCenterClient._vmdk_size_candidates
    assert c("disk-000001.vmdk") == [
        "disk-000001.vmdk",
        "disk-000001-delta.vmdk",
        "disk-000001-sesparse.vmdk",
        "disk-000001-flat.vmdk",
    ]
    assert c("disk-000001-delta.vmdk") == ["disk-000001-delta.vmdk"]


def test_get_vm_snapshot_sizes_skips_irregular_chain(monkeypatch):
    """Silinmiş/dallanmış bir snapshot yüzünden zincir uzunluğu snapshot sayısıyla
    eşleşmiyorsa YANLIŞ boyut üretmek yerine sessizce atlanmalı."""
    client = _client()
    layout = {
        "disks": {"2000": ["[ds] a/a.vmdk", "[ds] a/a-000001.vmdk"]},
        "snapshots": {
            "snap-1": ["[ds] a/a.vmdk"],
            "snap-2": ["[ds] a/a.vmdk"],  # iki snapshot ama zincirde yalnız 1 delta -> düzensiz
        },
    }
    monkeypatch.setattr(client, "_get_vm_layout_soap", lambda vm_id: layout)
    monkeypatch.setattr(client, "_soap_login", lambda: MagicMock())

    sizes = client.get_vm_snapshot_sizes("vm-x")
    assert sizes == {}
