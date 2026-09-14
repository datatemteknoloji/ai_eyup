"""İkinci vCenter: ad çakışması birleşmez."""
from app.services.virt_scope import (
    count_names,
    disambiguate,
    encode_ref,
    owned_by_other_vcenter,
    parse_ref,
)


def test_ref_roundtrip_keeps_vcenters_apart():
    assert encode_ref(3, "datastore1") == "hv:3:datastore1"
    assert parse_ref("hv:3:datastore1") == (3, "datastore1")
    assert parse_ref("plain-host") == (None, "plain-host")
    assert parse_ref("hv:3:datastore1") != parse_ref("hv:9:datastore1")


def test_same_name_two_vcenters_gets_distinct_labels():
    counts = count_names([(1, "esxi01"), (2, "esxi01"), (1, "esxi02")])
    assert counts["esxi01"] == 2
    assert disambiguate("esxi01", 2, counts, {2: "dc-b"}) == "esxi01 (dc-b)"
    assert disambiguate("esxi02", 1, counts, {1: "dc-a"}) == "esxi02"


def test_sync_does_not_claim_other_vcenter_row():
    assert owned_by_other_vcenter(4, 9) is True
    assert owned_by_other_vcenter(9, 9) is False
    assert owned_by_other_vcenter(None, 9) is False
